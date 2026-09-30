"""Read-only replay of the original 4076 -> 811b research projection.

Run from outside active source with the existing Stage interpreter. This
imports only the research consumer; no Stage runner, provider or collector.
No originals, authorization, receipts or source modules are written.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import importlib
import json
from pathlib import Path
import sys

SOURCE = "4076de79920c43cfa57336c23262a491cd77730f29b4e1a530bc5ed9836ef571"
ARCHIVE = "811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0"
AFTER = "e3dce4261dfe27c9d058b062991715f4894a3b309233f028ca62089559017095"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    app, root = args.app_root.resolve(), args.data_root.resolve()
    if not app.is_dir() or not root.is_dir():
        parser.error("existing isolated app-root and original data-root are required")
    source_rel = f"research/hourly/source/{SOURCE}.json"
    archive_rel = "research/hourly/live/20260930/1400.json"
    receipt_rel = "receipts/research/hourly/live/20260930/1400.json"
    paths = [source_rel, archive_rel, receipt_rel, "manifest.json"]
    observed: dict[str, str] = {}
    def file_sha(relative: str) -> str:
        current = root
        for component in Path(relative).parts:
            current /= component
            if current.is_symlink():
                raise ValueError("original read target contains a symlink")
        return hashlib.sha256(current.read_bytes()).hexdigest()
    report = {"schema": "pr16.a1445.readonly_replay.v1", "stage_executed": False,
        "provider_executed": False, "collector_executed": False, "write_performed": False,
        "real_time_success": False, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False}
    code = 2
    try:
        observed = {p: file_sha(p) for p in paths}
        if observed[source_rel] != SOURCE or observed[archive_rel] != ARCHIVE:
            raise ValueError("original source/archive bytes do not match the frozen witness")
        sys.path.insert(0, str(app))
        rc = importlib.import_module("stage_center.research_context")
        module = Path(rc.__file__).resolve()
        if module != app / "stage_center/research_context.py":
            raise ValueError("research_context imported from a different application")
        if hashlib.sha256(module.read_bytes()).hexdigest() != AFTER:
            raise ValueError("research_context is not the reviewed after image")
        cutoff = datetime.fromisoformat("2026-09-30T15:00:00+08:00")
        slot, payload, binding = rc._verified_hourly_slot(root, trade_date="20260930", cutoff=cutoff)
        if (slot != "1400" or binding["source_input_sha256"] != SOURCE
                or rc._payload_base_sha(payload) != ARCHIVE
                or binding["actual_source_generated_at"] != "2026-09-30T14:12:03+08:00"):
            raise ValueError("original verified slot/archive/source/time binding changed")
        rows, evidence = rc._bound_source_rows(root, payload=payload, paths=binding,
            trade_date="20260930", slot="1400", cutoff=cutoff)
        if rows is None:
            raise ValueError("original source witness missing")
        report.update(status="PASS_READONLY_FULL_PROJECTION", source_sha256=SOURCE,
            archive_base_sha256=ARCHIVE, consumer_sha256=AFTER, slot=slot,
            source_generated_at=binding["actual_source_generated_at"],
            pit_rejected_slots=binding["pit_rejected_slots"], source_evidence=list(evidence),
            articles=payload["article_count"], stock_pool=payload["stock_pool_count"])
        code = 0
    except (OSError, ValueError, TypeError, KeyError, ImportError) as error:
        report.update(status="CANNOT_CONFIRM", error=f"{type(error).__name__}:{error}")
    finally:
        unchanged = bool(observed) and all(file_sha(p) == value for p, value in observed.items())
        report["original_files_unchanged"] = unchanged
        report["original_file_sha256"] = observed
        if not unchanged:
            report["status"] = "CANNOT_CONFIRM"
            code = 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
