"""Offline frozen US_MAPPING replay; raw derivatives stay in caller's local-only directory.

Does not submit a job, collect, load HK history, or write runtime state.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--bind-master", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    code_root = args.code_root.resolve()
    if args.output.resolve().is_relative_to(code_root):
        raise ValueError("RAW_REPLAY_OUTPUT_MUST_STAY_LOCAL_ONLY_OUTSIDE_SOURCE_ROOT")
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(code_root), str(code_root / "upstreams")]
    def no_network(*_, **__):
        raise AssertionError("OFFLINE_REPLAY_NETWORK_FORBIDDEN")
    socket.create_connection = no_network
    socket.socket = no_network
    from v4.manager_workbench.contracts import Coverage, Lane, RunContext
    from v4.manager_workbench.engines.us_mapping import run_us_mapping
    from v4.manager_workbench.inputs.validation import batch as seal_batch

    original = json.loads(args.input.read_bytes())
    original_snapshot = json.loads(args.snapshot.read_bytes())
    data = deepcopy(original)
    source_batch = next(b for b in data["batches"] if b["lane"] == "US_MAPPING")
    context = RunContext.model_validate(data["context"])
    assert context.target_date == "20261020"
    assert context.source_sessions == {"us": "20261019", "hk_price": "20261016"}
    master_enrichment = None
    original_pin = deepcopy(context.scope_refs["owner_bindings"]["us_mapping"])
    if args.bind_master:
        from v4.manager_workbench.config import load_config
        from v4.manager_workbench.inputs.native import NativeAdapters
        if not args.config:
            raise ValueError("CONFIG_REQUIRED_FOR_EXISTING_MASTER_BINDING")
        adapter = NativeAdapters(load_config(args.config))
        identity, refs = adapter._security_master_identity(context)
        assert identity["status"] == "READY", identity
        assert identity["source_date"] == "20261016"
        assert context.scope_refs["owner_bindings"]["us_mapping"] == original_pin
        assert set(context.scope_refs["owner_bindings"]) == set(original["context"]["scope_refs"]["owner_bindings"]) | {"security_master"}
        ids = [ref.evidence_id for ref in refs]
        payload = next(record["us_factor_payload"] for record in source_batch["records"]
                       if isinstance(record.get("us_factor_payload"), dict))
        payload["hk_industry_classification"]["hk_industry_identity"] = identity
        for holder in (payload, payload["hk_industry_classification"]):
            holder["evidence_ids"] = list(dict.fromkeys(holder.get("evidence_ids", []) + ids))
        source_batch["evidence_refs"].extend(ref.model_dump(mode="json") for ref in refs)
        for record in source_batch["records"]:
            record["evidence_ids"] = list(dict.fromkeys(record.get("evidence_ids", []) + ids))
        master_enrichment = dict(identity=identity, pin=context.scope_refs["owner_bindings"]["security_master"],
            note="Existing exact HK20261016 owner added; input identity intentionally changes. No other source pin refreshed.")
        source_batch = seal_batch(context, Lane.US_MAPPING, source_batch["records"], source_batch["evidence_refs"],
            source_batch["scope_description"], Coverage.model_validate(source_batch["coverage"]),
            source_batch["gaps"], source_batch["universe_ref"]).model_dump(mode="json")
    else:
        assert source_batch["context"] == context.model_dump(mode="json")
    result = run_us_mapping(context.model_dump(mode="json"), source_batch)
    daily = next(r["us_factor_summary"]["single_day_mapping"] for r in result["rows"] if "us_factor_summary" in r)
    codes = [r["symbol"] for r in daily["rows"]]
    catalog = daily["catalog_relation_dispositions"]
    assert len(codes) == len(set(codes)) == 698
    assert len(catalog) == len({r["catalog_relation_id"] for r in catalog}) == 1003
    for decision in ("BENEFIT", "RISK", "CONFLICT", "OBSERVATION", "UNMAPPED", "UNASSESSED"):
        assert daily["counts"][decision] == sum(r["decision"] == decision for r in daily["rows"])
    assert daily["strict_v1_status"] == "PAUSED_NOT_EXECUTED"
    assert daily["deferred_gates"] == ["HK_MA20", "HK_RETURN5", "HK_TURNOVER20", "TOP10", "THEME3"]
    assert daily["RESEARCH_ONLY"] and not any(daily[k] for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert all(not r["active_transmission"] and r["signed_hk_return_pct"] is None for r in catalog)
    assert not any(r["catalog_disposition"].startswith("ADOPTED_") for r in catalog)
    assert daily["formal_target_eligibility"] == "CANNOT_CONFIRM"
    source_paths = [p for r in daily["rows"] for p in r["mapping_paths"]]
    factor = next(r["us_factor_summary"] for r in result["rows"] if "us_factor_summary" in r)
    raw_out = args.output / "lane.local-only.json"
    raw_out.write_bytes(canonical(result))
    (args.output / "input.local-only.json").write_bytes(canonical(dict(context=context.model_dump(mode="json"), batch=source_batch)))
    summary = dict(mode="candidate_existing_master" if args.bind_master else "frozen_input",
        code_root=str(code_root), python=sys.executable, python_version=sys.version.split()[0],
        anchor_run_id=original_snapshot["run_id"], original_snapshot_sha256=sha(args.snapshot),
        frozen_input_file_sha256=sha(args.input), frozen_input_snapshot_sha256=original_snapshot["changes"]["input_snapshot_sha256"],
        original_batch_sha256=original["batches"][0]["input_sha256"], replay_batch_sha256=source_batch["input_sha256"],
        source_pin_sha256=hashlib.sha256(canonical(original_pin)).hexdigest(),
        quote_sha256=original_pin["quote_sha256"], quote_receipt_sha256=original_pin["owner_receipt_sha256"],
        quote_manifest_sha256=original_pin["owner_manifest_sha256"],
        relation_registry_sha256=original_pin["relation_sha256"],
        full_overlay_summary=original_pin["full_overlay_summary"],
        target_date=daily["target_date"], source_session=daily["source_session"], price_session=daily["price_session"],
        counts=daily["counts"], reasons=dict(Counter(r["reason"] for r in daily["rows"])),
        mapping_grade_counts=dict(Counter(str(r["mapping_grade"]) for r in daily["rows"])),
        path_count=len(source_paths), synthetic_catalog_legacy_path_count=sum(p.get("relation_type")=="CATALOG_OBSERVATION_ONLY" for p in source_paths),
        catalog_relation_count=len(catalog), catalog_dispositions=daily["catalog_consumption"]["disposition_counts"],
        catalog_candidate_qualifications=dict(Counter(r["qualification"] for r in daily["catalog_candidates"])),
        identity_gap_count=factor["industry_summary"]["identity_gap_count"],
        identity_resolved_count=factor["industry_summary"]["identity_resolved_count"],
        strict_v1_status=daily["strict_v1_status"], formal_target_eligibility=daily["formal_target_eligibility"],
        master_enrichment=master_enrichment, raw_output_sha256=sha(raw_out),
        source_files={str(p.relative_to(code_root)):sha(p) for p in [
            code_root/"v4/manager_workbench/engines/us_mapping.py",
            code_root/"v4/manager_workbench/engines/strict_us_selection.py",
            code_root/"v4/manager_workbench/inputs/native.py"]},
        selected_symbols={name:[r["symbol"] for r in daily["rows"] if r["decision"]==name] for name in ["BENEFIT", "RISK", "CONFLICT"]})
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2)+"\n")
    print(json.dumps({k:summary[k] for k in ["mode","counts","identity_gap_count","identity_resolved_count","synthetic_catalog_legacy_path_count","catalog_relation_count","replay_batch_sha256"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
