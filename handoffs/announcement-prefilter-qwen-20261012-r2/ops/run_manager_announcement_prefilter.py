#!/usr/bin/env python3
"""Issue #38: post-capture triage in the original daily-announcement evidence run.

Invoke after existing run_manager_daily_announcement.py capture (never before).
This writes an auditable triage receipt only; owner import stays behind the
original reviewed semantic + independent reviewer gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ops.announcement_prefilter_qwen import (LocalModelIdentity, LoopbackChat,
    TriageEngine, attest_local_model, _sha)


def read_exact(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("PREFILTER_SOURCE_FILE_MISSING_OR_SYMLINK")
    raw=path.read_bytes()
    if len(raw)>80_000_000:
        raise ValueError("PREFILTER_SOURCE_TOO_LARGE")
    value=json.loads(raw)
    if not isinstance(value,dict):
        raise ValueError("PREFILTER_SOURCE_JSON_OBJECT_REQUIRED")
    return value,_sha(raw)


def run_from_evidence(*, evidence_root: Path, cache_root: Path, output: Path,
                      model_pid: int | None = None, model_dir: str | None = None,
                      model_name: str = "", revision: str = "",
                      endpoint: str = "http://127.0.0.1:8199/v1/chat/completions",
                      alias: str = "") -> dict[str, Any]:
    """Read only the original capture+body outputs; cannot invent a catalog."""
    evidence = evidence_root.expanduser().absolute()
    if any(p.is_symlink() for p in (evidence,*evidence.parents)) or not evidence.is_dir():
        raise ValueError("PREFILTER_EVIDENCE_ROOT_UNTRUSTED")
    receipt,_=read_exact(evidence/"capture_receipt.json")
    catalog,catalog_raw_sha=read_exact(evidence/"catalog_read.json")
    corpus,body_raw_sha=read_exact(evidence/"body_corpus.json")
    if (receipt.get("schema_version")!="v4.manager_research.announcement_daily_capture.v1"
            or receipt.get("catalog_read_file_sha256")!=catalog_raw_sha
            or receipt.get("body_corpus_file_sha256")!=body_raw_sha
            or receipt.get("target_trade_date")!=catalog.get("target_trade_date")
            or receipt.get("publication_date")!=catalog.get("publication_date")
            or receipt.get("catalog_run_id")!=catalog.get("catalog",{}).get("run_id")
            or receipt.get("catalog_product_sha256")!=catalog.get("catalog",{}).get("sha256")
            or receipt.get("semantic_status")!="NOT_REVIEWED"):
        raise ValueError("PREFILTER_CAPTURE_RECEIPT_SOURCE_OR_DATE_MISMATCH")
    if not all(receipt.get(k) is v for k,v in {
            "RESEARCH_ONLY":True,"production_allowed":False,
            "buy_gate_updated":False,"orders_sent":False}.items()):
        raise ValueError("PREFILTER_CAPTURE_SAFETY_FLAGS_INVALID")
    run_id = receipt.get("evidence_run_id")
    if not isinstance(run_id,str) or len(run_id)!=32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("PREFILTER_EVIDENCE_RUN_ID_INVALID")
    if model_pid is not None and model_dir is not None:
        try:
            identity=attest_local_model(pid=model_pid,model_dir=model_dir,name=model_name,
                revision=revision,endpoint=endpoint,alias=alias)
        except (ValueError,OSError,TimeoutError,subprocess.CalledProcessError):
            identity=LocalModelIdentity(model_name,revision,"",endpoint,"CANNOT_CONFIRM","",alias)
    else:
        identity=LocalModelIdentity(model_name,revision,"",endpoint,"CANNOT_CONFIRM","",alias)
    result=TriageEngine(cache_root,identity,LoopbackChat()).run(catalog,corpus)
    result.update(evidence_run_id=run_id, catalog_read_file_sha256=catalog_raw_sha,
                  body_corpus_file_sha256=body_raw_sha,
                  capture_receipt_file_sha256=_sha((evidence/"capture_receipt.json").read_bytes()))
    # Result's SHA must cover its final linked identity as well.
    result.pop("sha256",None)
    from ops.announcement_prefilter_qwen import _seal
    result=_seal(result)
    out=output.expanduser().absolute()
    if out.is_symlink() or any(p.is_symlink() for p in out.parents):
        raise ValueError("PREFILTER_OUTPUT_SYMLINK_FORBIDDEN")
    out.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
    with out.open("xb") as stream:
        stream.write(raw)
    return result


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root",type=Path,required=True)
    parser.add_argument("--cache-root",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--model-pid",type=int)
    parser.add_argument("--model-dir")
    parser.add_argument("--model-name",default="")
    parser.add_argument("--model-revision",default="")
    parser.add_argument("--model-endpoint",default="http://127.0.0.1:8199/v1/chat/completions")
    parser.add_argument("--model-alias",default="")
    args=parser.parse_args(argv)
    try:
        result=run_from_evidence(evidence_root=args.evidence_root,cache_root=args.cache_root,
            output=args.out,model_pid=args.model_pid,model_dir=args.model_dir,
            model_name=args.model_name,revision=args.model_revision,
            endpoint=args.model_endpoint,alias=args.model_alias)
        print(json.dumps({k:result[k] for k in ("status","target_trade_date","publication_date",
              "input_article_rows","output_article_rows","new_model_calls","new_model_tokens",
              "unassessed_rows","owner_import_status","natural_scheduler_status")},ensure_ascii=False))
        return 0 if result["unassessed_rows"]==0 else 3
    except (ValueError,OSError,TypeError,KeyError,json.JSONDecodeError) as exc:
        print(json.dumps({"status":"FAILED","error":str(exc)[:200],
            "RESEARCH_ONLY":True,"production_allowed":False,"buy_gate_updated":False,
            "orders_sent":False},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
