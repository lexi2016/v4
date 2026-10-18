#!/usr/bin/env python3
"""Read-only offline Issue 45 overlay-consumer verification.

All source and owner roots are supplied by CLI flags or environment variables.
The script makes no network calls, writes no owner/runtime files, and emits only
counts, dates, and hashes. It deliberately omits Connect membership so this
canary verifies catalog conservation without claiming quote assessment.
"""
from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path
import sys


def _path_argument(parser: argparse.ArgumentParser, flag: str, env_key: str, help_text: str):
    parser.add_argument(
        flag,
        dest=flag[2:].replace("-", "_"),
        default=os.environ.get(env_key),
        help=f"{help_text} (or set {env_key})",
    )


def _resolved_path(value: str | None, label: str, *, is_file: bool = False) -> Path:
    if not value:
        raise SystemExit(f"missing required --{label.replace('_', '-')} or its environment variable")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise SystemExit(f"{label} must be an absolute path")
    path = path.resolve()
    if not (path.is_file() if is_file else path.is_dir()):
        raise SystemExit(f"{label} does not exist: {path}")
    return path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    _path_argument(parser, "--source-root", "ISSUE45_SOURCE_ROOT", "checkout containing candidate source")
    _path_argument(parser, "--config-path", "ISSUE45_CONFIG_PATH", "read-only manager-workbench JSON config")
    _path_argument(parser, "--us-owner-root", "ISSUE45_US_OWNER_ROOT", "read-only US quote owner root")
    _path_argument(parser, "--relation-owner-root", "ISSUE45_RELATION_OWNER_ROOT", "read-only relation evidence root")
    _path_argument(parser, "--overlay-source-root", "ISSUE45_OVERLAY_SOURCE_ROOT", "root containing the full overlay owner files")
    parser.add_argument("--target-date", default="20261020")
    parser.add_argument("--us-session", default="20261016")
    parser.add_argument("--cutoff", default="2026-10-18T00:00:00+08:00")
    parser.add_argument(
        "--relation-evidence-relative",
        default="v4/manager_workbench/research_data/us_mapping_relation_evidence_20261013_v3.json",
    )
    parser.add_argument(
        "--relation-review-relative",
        default="v4/manager_workbench/research_data/us_mapping_relation_evidence_review_20261013_v3.json",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    source_root = _resolved_path(args.source_root, "source_root")
    config_path = _resolved_path(args.config_path, "config_path", is_file=True)
    us_owner_root = _resolved_path(args.us_owner_root, "us_owner_root")
    relation_owner_root = _resolved_path(args.relation_owner_root, "relation_owner_root")
    overlay_source_root = _resolved_path(args.overlay_source_root, "overlay_source_root")
    module_relative = Path("v4/manager_workbench/inputs/source_bindings.py")
    if not (source_root / module_relative).is_file():
        raise SystemExit(f"source_root is missing {module_relative}")
    if not (overlay_source_root / module_relative).is_file():
        raise SystemExit(f"overlay_source_root is missing {module_relative}")

    # Prevent Python imports from creating bytecode files under the source tree.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source_root))

    from v4.manager_workbench.config import load_config
    from v4.manager_workbench.contracts import Phase, RunContext
    from v4.manager_workbench.engines.common import RULE
    from v4.manager_workbench.engines.us_mapping import run_us_mapping
    from v4.manager_workbench.inputs import source_bindings
    from v4.manager_workbench.inputs.native import NativeAdapters

    loaded_config = load_config(config_path)
    config = loaded_config.model_copy(
        update={
            "dynamic_source_bindings": False,
            "capture_root": None,
            "source_bindings": {},
            "us_root": us_owner_root,
            "relation_root": relation_owner_root,
            "relation_evidence_relative": args.relation_evidence_relative,
            "relation_review_relative": args.relation_review_relative,
        }
    )
    context = RunContext(
        target_date=args.target_date,
        phase=Phase.NEXT_DAY,
        trigger="SCHEDULED",
        cutoff=args.cutoff,
        source_sessions={"us": args.us_session},
        rules_version=RULE,
        scope_refs={},
    )

    # _full_mapping_overlay resolves the owner directory relative to this
    # module's __file__. Keep candidate imports while overriding only that
    # in-memory read-root calculation to the explicitly supplied owner root.
    original_module_path = source_bindings.__file__
    try:
        source_bindings.__file__ = str(overlay_source_root / module_relative)
        pin = source_bindings.us_mapping(config, context)
    finally:
        source_bindings.__file__ = original_module_path

    summary = pin["full_overlay_summary"]
    assert (summary["state"], summary["stock_count"], summary["relation_count"]) == (
        "READY",
        667,
        1003,
    ), summary
    source = {row["relation_id"]: row for row in pin["full_overlay_projection"]}
    assert len(source) == 1003

    adapters = NativeAdapters(config)
    adapters.membership = lambda *_: (set(), None, [])
    prepared = adapters.prepare_context(
        context.model_copy(update={"scope_refs": {"owner_bindings": {"us_mapping": pin}}})
    )
    batch = adapters.us_mapping(prepared)
    output = run_us_mapping(
        prepared.model_dump(mode="python"), batch.model_dump(mode="python")
    )
    rows = [row for row in output["rows"] if row.get("catalog_relation_id") is not None]
    assert len(rows) == 1003
    relation_ids = [row["catalog_relation_id"] for row in rows]
    assert len(set(relation_ids)) == 1003 and set(relation_ids) == set(source)
    assert Counter(row["catalog_recovery_status"] for row in rows) == {
        "CLOSED_RESEARCH_SCOPE": 757,
        "OPEN": 221,
        "CLOSED_EXCLUDED_SCOPE": 25,
    }
    assert Counter(row["catalog_research_use"] for row in rows) == {
        "PENDING_REVIEW": 985,
        "BACKGROUND_HISTORICAL": 10,
        "EXCLUDED_CURRENT": 5,
        "CONDITIONAL_OBSERVATION": 3,
    }
    for row in rows:
        original = source[row["catalog_relation_id"]]
        relation = row["catalog_relation"]
        assert relation == original
        assert row["catalog_research_use"] == original["research_use"]
        assert row["catalog_recovery_status"] == original["recovery_v2r1"]["closure_status"]
        field_sha = relation["recovery_v2r1"]["field_sha256"]
        assert len(field_sha) == 7 and all(len(value) == 64 for value in field_sha.values())
        assert relation["recovery_v2r1"]["use_scope"] == original["recovery_v2r1"]["use_scope"]
        assert row["decision"] == "UNASSESSED"
    assert batch.coverage.scope_count == batch.coverage.observed_count == 33
    assert output["coverage"]["scope_count"] == output["coverage"]["observed_count"] == 33
    assert "OBSERVED_COUNT_MISMATCH" not in output["gaps"]
    assert "US_MAPPING_OVERLAY_CONSUMER_COUNT_MISMATCH" not in output["gaps"]

    print(
        {
            "state": "PASS",
            "target_date": context.target_date,
            "us_session": context.source_sessions["us"],
            "loaded_config_path": str(config_path),
            "loaded_relation_root_before_override": str(loaded_config.relation_root),
            "offline_relation_root": str(relation_owner_root),
            "quote_owner": {
                "payload_relative": pin["quote_relative"],
                "payload_sha256": pin["quote_sha256"],
                "receipt_relative": pin["owner_receipt_relative"],
                "receipt_sha256": pin["owner_receipt_sha256"],
                "manifest_sha256": pin["owner_manifest_sha256"],
            },
            "overlay": {
                "stock_count": summary["stock_count"],
                "relation_count": summary["relation_count"],
                "relation_bearing_stock_count": len({row["symbol"] for row in rows}),
                "owner_files": [
                    {"relative": item["relative"], "sha256": item["sha256"]}
                    for item in summary["checked_files"]
                ],
                "closure_counts": dict(
                    Counter(row["catalog_recovery_status"] for row in rows)
                ),
                "research_use_counts": dict(
                    Counter(row["catalog_research_use"] for row in rows)
                ),
                "decisions": dict(Counter(row["decision"] for row in rows)),
            },
            "coverage": {
                "fixed_33_scope": batch.coverage.scope_count,
                "fixed_33_observed": batch.coverage.observed_count,
                "fixed_33_assessed": output["coverage"]["assessed_count"],
                "fixed_33_unassessed": output["coverage"]["unassessed_count"],
            },
            "gaps": output["gaps"],
            "writes": "NONE",
            "network": "NONE",
        }
    )


if __name__ == "__main__":
    main()
