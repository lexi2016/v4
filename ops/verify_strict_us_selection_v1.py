#!/usr/bin/env python3
"""Read-only canary for the frozen US 20261016 -> HK 20261020 mapping view."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v4.manager_workbench.config import load_config
from v4.manager_workbench.contracts import RunContext
from v4.manager_workbench.engines.common import US_FACTOR_RULES_VERSION
from v4.manager_workbench.engines.us_mapping import run_us_mapping
from v4.manager_workbench.inputs.native import NativeAdapters


def _sha(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _factor_summary(lane_result):
    return next((row.get("us_factor_summary") for row in lane_result.get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("us_factor_summary"), dict)), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path,
        help="Existing local Workbench config; read only")
    parser.add_argument("--cutoff", required=True,
        help="Explicit timezone-aware cutoff ISO timestamp")
    parser.add_argument("--target-date", default="20261020")
    parser.add_argument("--us-session", default="20261016")
    parser.add_argument("--hk-price-session", default="20261016")
    args = parser.parse_args()

    config = load_config(args.config)
    if config.rules_version != US_FACTOR_RULES_VERSION:
        raise SystemExit("CANNOT_CONFIRM: configured rules_version is not the existing US_FACTOR rules version")
    context = RunContext(target_date=args.target_date, phase="MANUAL", trigger="MANUAL",
        cutoff=args.cutoff, rules_version=config.rules_version,
        source_sessions={"us": args.us_session, "hk_price": args.hk_price_session})
    adapters = NativeAdapters(config)
    context = adapters.prepare_context(context)
    input_batch = adapters.us_mapping(context)
    input_value = input_batch.model_dump(mode="json")
    lane_result = run_us_mapping(context.model_dump(mode="json"), input_value)
    factor_summary = _factor_summary(lane_result)
    single_day = factor_summary.get("single_day_mapping") if isinstance(factor_summary, dict) else None
    single_day = single_day if isinstance(single_day, dict) else {}
    mapping_payload = next((row.get("us_factor_payload", {}).get("single_day_mapping_payload")
        for row in input_value.get("records", []) if isinstance(row, dict)
        and isinstance(row.get("us_factor_payload"), dict)), {})
    mapping_payload = mapping_payload if isinstance(mapping_payload, dict) else {}
    membership = mapping_payload.get("monthly_membership")
    output = {
        "schema": "us_hk_single_day_mapping_v1_readonly_canary.v1",
        "mode": "MANUAL_LATE_READ_ONLY",
        "target_date": args.target_date,
        "us_source_session": args.us_session,
        "hk_price_session": args.hk_price_session,
        "cutoff": args.cutoff,
        "input_batch_sha256": input_value.get("input_sha256"),
        "single_day_input_sha256": _sha(mapping_payload),
        "single_day_result_sha256": _sha(single_day) if single_day else None,
        "mapping_policy_version": single_day.get("mapping_policy_version"),
        "mapping_policy_sha256": single_day.get("mapping_policy_sha256"),
        "state": single_day.get("state", "CANNOT_CONFIRM"),
        "monthly_observed_scope_count": single_day.get("monthly_observed_scope_count"),
        "monthly_source_date": single_day.get("monthly_source_date") or
            (membership.get("source_date") if isinstance(membership, dict) else None),
        "monthly_source_sha256": single_day.get("monthly_source_sha256") or
            (membership.get("artifact_sha256") if isinstance(membership, dict) else None),
        "monthly_codes_sha256": single_day.get("monthly_codes_sha256") or
            (membership.get("codes_sha256") if isinstance(membership, dict) else None),
        "counts": single_day.get("counts", {}),
        "benefit_rows": single_day.get("benefit_rows", []),
        "risk_rows": single_day.get("risk_rows", []),
        "conflict_rows": single_day.get("conflict_rows", []),
        "observation_rows": single_day.get("observation_rows", []),
        "unmapped_rows": single_day.get("unmapped_rows", []),
        "unassessed_rows": single_day.get("unassessed_rows", []),
        "rows": single_day.get("rows", []),
        "outside_pool_observations": single_day.get("outside_pool_observations", []),
        "industry_source_status": single_day.get("industry_source_status"),
        "industry_source_date": single_day.get("industry_source_date"),
        "industry_source_sha256": single_day.get("industry_source_sha256"),
        "gaps": single_day.get("gaps", ["SINGLE_DAY_SUMMARY_UNAVAILABLE"]),
        "strict_v1_status": "PAUSED_NOT_EXECUTED",
        "deferred_gates": ["HK_MA20", "HK_RETURN5", "HK_TURNOVER20", "TOP10", "THEME3"],
        "formal_target_eligibility": single_day.get("formal_target_eligibility", "CANNOT_CONFIRM"),
        "historical_pit_verified": False,
        "research_effectiveness": "UNVERIFIED",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return 0 if single_day.get("state") in ("READY", "PARTIAL", "CANNOT_CONFIRM") else 1


if __name__ == "__main__":
    raise SystemExit(main())
