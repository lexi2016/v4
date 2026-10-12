#!/usr/bin/env python3
"""Isolated failure-path check for the one-shot HK recovery preparation."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

EVIDENCE_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_HK_CUTOFF_RECOVERY_20261012/evidence")
PREPARATION_SCRIPT = EVIDENCE_ROOT / "prepare_hk_cached_recovery.py"
OUTPUT_ROOT = EVIDENCE_ROOT / "isolated_hk_recovery_failure_budget_20261012"


def load_preparation_module():
    spec = importlib.util.spec_from_file_location("prepare_hk_cached_recovery", PREPARATION_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the bounded recovery preparation script")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if OUTPUT_ROOT.exists():
        raise FileExistsError(f"failure-budget evidence root already exists: {OUTPUT_ROOT}")
    module = load_preparation_module()
    app_root = module.APP_ROOT
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from stage_center.acquisition import SourceResult

    original_receipt = json.loads(module.LIVE_RECEIPT.read_text(encoding="utf-8"))
    calls: list[str] = []
    observed_reservations: list[dict[str, object]] = []
    isolated_receipt = OUTPUT_ROOT / "stage_state/receipts" / module.TRADE_DATE / module.STAGE_ID / "receipt.json"

    def injected_failure(plan, market):
        calls.append(market)
        reservation = json.loads(isolated_receipt.read_text(encoding="utf-8"))
        observed_reservations.append({
            "node_attempt_count": reservation.get("node_attempt_count"),
            "execution_markets": reservation.get("execution_markets"),
            "execution_pending": reservation.get("execution_pending"),
            "retry_exhausted": reservation.get("retry_exhausted"),
            "a_share_lane_preserved": reservation.get("markets", {}).get("A_SHARE")
            == original_receipt.get("markets", {}).get("A_SHARE"),
        })
        if market != module.MARKET or plan.trade_date != module.TRADE_DATE or plan.stage_id != module.STAGE_ID:
            raise AssertionError("injected collector escaped the pinned HK stage")
        return SourceResult(
            source_id="pytdx_exhq",
            status="CANNOT_CONFIRM",
            rows=(),
            cannot_confirm=("INJECTED_ISOLATED_FAILURE",),
            error="INJECTED_ISOLATED_FAILURE",
            requested_rows=100,
            source_evidence=("failure_budget_test=true",),
        )

    report = module.execute_scoped_once(
        output_root=OUTPUT_ROOT,
        mode="DRY_RUN",
        collector_override=injected_failure,
    )
    final_receipt = json.loads(isolated_receipt.read_text(encoding="utf-8"))
    if calls != [module.MARKET]:
        raise AssertionError(f"expected one HK collector call, got {calls!r}")
    if len(observed_reservations) != 1:
        raise AssertionError("attempt-3 reservation was not observed exactly once")
    reservation = observed_reservations[0]
    if (
        reservation.get("node_attempt_count") != 3
        or reservation.get("execution_markets") != [module.MARKET]
        or reservation.get("execution_pending") is not True
        or reservation.get("retry_exhausted") is not True
        or reservation.get("a_share_lane_preserved") is not True
    ):
        raise AssertionError(f"attempt-3 reservation was not closed before collection: {reservation!r}")
    if (
        final_receipt.get("node_attempt_count") != 3
        or final_receipt.get("node_outcome") != "TRANSIENT"
        or final_receipt.get("retry_exhausted") is not True
        or final_receipt.get("execution_pending") is not False
    ):
        raise AssertionError("failed attempt 3 did not finish with the original retry budget exhausted")
    if final_receipt.get("markets", {}).get("A_SHARE") != original_receipt.get("markets", {}).get("A_SHARE"):
        raise AssertionError("failure path changed the preserved A-share receipt lane")
    preserved = (
        OUTPUT_ROOT / "stage_state/receipts" / module.TRADE_DATE / module.STAGE_ID
        / "attempt_evidence" / f"preserved-{module.EXPECTED_RECEIPT_SHA256}" / "PRIOR_RECEIPT.json"
    )
    if not preserved.is_file() or preserved.read_bytes() != module.LIVE_RECEIPT.read_bytes():
        raise AssertionError("exact attempt-2 receipt bytes were not archived")

    fourth_root = OUTPUT_ROOT.with_name(OUTPUT_ROOT.name + "_fourth_rejected")
    try:
        module.execute_scoped_once(
            output_root=fourth_root,
            mode="DRY_RUN",
            receipt_path=isolated_receipt,
            collector_override=injected_failure,
        )
    except ValueError as error:
        fourth_rejection = str(error)
        if "receipt SHA" not in fourth_rejection:
            raise AssertionError(f"fourth-attempt refusal used an unexpected guard: {error}") from error
    else:
        raise AssertionError("a fourth attempt was not rejected")
    if fourth_root.exists() or calls != [module.MARKET]:
        raise AssertionError("fourth-attempt rejection created output or invoked the collector")
    if module.sha_file(module.LIVE_RECEIPT) != module.EXPECTED_RECEIPT_SHA256:
        raise AssertionError("failure-budget isolation modified the live receipt")

    result = {
        "schema_version": "hk.recovery_failure_budget_test.v1",
        "result": "PASS",
        "failure_collector_calls": calls,
        "reservation_observed_before_collector": reservation,
        "final_attempt_count": final_receipt.get("node_attempt_count"),
        "final_node_outcome": final_receipt.get("node_outcome"),
        "retry_exhausted": final_receipt.get("retry_exhausted"),
        "fourth_attempt_rejected": True,
        "fourth_attempt_rejection": fourth_rejection,
        "fourth_attempt_output_root_created": fourth_root.exists(),
        "prior_receipt_archived_sha256": module.sha_file(preserved),
        "live_receipt_sha256_unchanged": module.sha_file(module.LIVE_RECEIPT),
        "provider_calls": 0,
        "safety": {"research_only": True, **module.SAFETY_FALSE},
        "isolated_recovery_report_sha256": report.get("report_sha256"),
    }
    report_path = OUTPUT_ROOT / "FAILURE_BUDGET_TEST.json"
    module.write_json(report_path, result)
    print(json.dumps({**result, "report_path": str(report_path)}, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
