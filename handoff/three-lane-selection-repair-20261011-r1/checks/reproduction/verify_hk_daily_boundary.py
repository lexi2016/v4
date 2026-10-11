"""Independent projection probes using the existing synthetic reader fixture.

No SelectionStore/producer is created here, and no source hashes purport to be
live market artifacts. The candidate and its tests are read, never modified.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / "candidate"), str(ROOT / "candidate/tests"),
                str(ROOT / "support_source"), str(ROOT / "support_source/upstreams")]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sources() -> list[dict]:
    names = ["v4/manager_research/workspace_daily_channels.py", "v4/manager_research/workspace.py",
             "v4/manager_research/connect_selection.py", "stage_center/consumer.py",
             "tests/test_manager_three_lane_channels_r1.py"]
    return [{"path": str(ROOT / "candidate" / name),
             "sha256": sha256((ROOT / "candidate" / name).read_bytes())} for name in names]


def market(value):
    return value["stage_selection"]["selection_markets"]["HK_CONNECT"]


def execution(value):
    return value["stage_selection"]["execution_evidence"]


def zero(value):
    market(value).update(status="READY_EMPTY", selection_status="READY_EMPTY", rows=[], selected_rows=0)
    execution(value)["markets"]["HK_CONNECT"]["selected_rows"] = 0


def main() -> dict:
    before_sources = sources()
    from test_manager_three_lane_channels_r1 import hk_workspace, channel
    cases = []

    def probe(name, mutate, status, count, symbols=None, expected_gap=None, orders=None):
        value = hk_workspace()
        mutate(value)
        before = deepcopy(value)
        result = channel(value, "HK_CONNECT")
        actual_symbols = [row["symbol"] for row in result["rows"]]
        actual_orders = [row.get("order") for row in result["rows"]]
        passed = (result["status"] == status and result["candidate_count"] == count and value == before
                  and result["natural_run_verified"] is False
                  and result["formal_selection_input"] is False
                  and all(row["formal_eligible"] is False and row["action_level"] == "NO_BUY" for row in result["rows"])
                  and (symbols is None or actual_symbols == symbols)
                  and (orders is None or actual_orders == orders)
                  and (expected_gap is None or expected_gap in result["gaps"]))
        cases.append({"probe": name, "status": "PASS" if passed else "FAIL",
                      "expected": {"channel_status": status, "candidate_count": count, "symbols": symbols,
                                   "orders": orders, "required_gap": expected_gap},
                      "actual": {"channel_status": result["status"], "candidate_count": result["candidate_count"],
                                 "pending_count": result["pending_count"], "symbols": actual_symbols,
                                 "rank": [row.get("rank") for row in result["rows"]], "orders": actual_orders,
                                 "gaps": result["gaps"], "natural_run_verified": result["natural_run_verified"],
                                 "source_selection": result.get("source_selection"),
                                 "source_refs": [row.get("source_refs") for row in result["rows"]]},
                      "input_unchanged": value == before})

    untouched = lambda value: None
    rejected = {"status": "CANNOT_CONFIRM", "count": None, "symbols": []}
    probe("preserves_original_source_order_rank_and_trio_without_plan_run", untouched, "READY", 2,
          ["HK.00002", "HK.00001"], orders=[1, 2])
    probe("different_code_and_symbol_cannot_bypass_target_membership",
          lambda value: market(value)["rows"][0].update(code="HK.00888", symbol="HK.00002"), **rejected)
    probe("same_symbol_alias_is_consistent",
          lambda value: market(value)["rows"][0].update(symbol="HK.00002"), "READY", 2,
          ["HK.00002", "HK.00001"], orders=[1, 2])
    probe("duplicate_rank_rejected", lambda value: market(value)["rows"][1].update(rank=2), **rejected)
    probe("bool_order_rejected", lambda value: market(value)["rows"][0].update(order=True), **rejected)
    probe("nonsequential_original_projection_order_rejected",
          lambda value: market(value)["rows"][0].update(order=7), **rejected)
    for field, wrong in (("production_allowed", True), ("buy_gate_updated", True), ("orders_sent", True), ("RESEARCH_ONLY", False)):
        probe("declared_row_safety_conflict_" + field,
              lambda value, field=field, wrong=wrong: market(value)["rows"][0].update({field: wrong}), **rejected)
    for field, wrong in (("source_mode", "HK_CONNECT_D1_PRESELECT_REFERENCE"),
                         ("second_filter_status", "WAITING_0920_SECOND_FILTER"),
                         ("lane_evidence", ["D1_PRESELECT_REFERENCE"]),
                         ("candidate_lanes", ["D1_PRESELECT_REFERENCE"])):
        probe("original_row_recovery_marker_" + field,
              lambda value, field=field, wrong=wrong: market(value)["rows"][0].update({field: wrong}), **rejected)
    for field, wrong in (("mode", "BACKFILL"), ("recovery_mode", "HISTORICAL_BACKFILL"),
                         ("backfill_run_id", "backfill-synthetic-test"), ("temporal_cutoff_safe", False)):
        probe("execution_recovery_marker_" + field,
              lambda value, field=field, wrong=wrong: execution(value).update({field: wrong}), **rejected)
    probe("missing_stage_never_uses_focus", lambda value: value.pop("stage_selection"), **rejected)
    probe("missing_execution_preserves_research_rows_as_partial",
          lambda value: value["stage_selection"].pop("execution_evidence"), "PARTIAL", 2,
          ["HK.00002", "HK.00001"], "HK_STAGE_EXECUTION_SELECTION_BINDING_UNVERIFIED", orders=[1, 2])
    probe("complete_verified_zero_is_zero", zero, "READY_EMPTY", 0, [])
    def unbound_zero(value):
        zero(value)
        value["stage_selection"].pop("execution_evidence")
    probe("zero_without_execution_binding_stays_unknown", unbound_zero, "PARTIAL", None, [])
    def incomplete_zero(value):
        zero(value)
        market(value)["source_rows"] = 99
    probe("zero_without_100_complete_original_inputs_stays_unknown", incomplete_zero, "PARTIAL", None, [])
    def absent_inputs(value):
        zero(value)
        market(value).update(requested_rows=0, source_rows=0)
    probe("no_original_inputs_cannot_be_ready_empty", absent_inputs, **rejected)
    probe("empty_status_with_nonempty_rows_rejected",
          lambda value: market(value).update(status="READY_EMPTY", selection_status="READY_EMPTY"), **rejected)
    probe("selected_count_above_original_input_count_rejected",
          lambda value: market(value).update(source_rows=1), **rejected)
    probe("before_native_094005_cutoff_rejected",
          lambda value: value["plan_context"].update(research_cutoff="2026-10-09T09:40:04+08:00"), **rejected)
    probe("native_094005_cutoff_accepted",
          lambda value: value["plan_context"].update(research_cutoff="2026-10-09T09:40:05+08:00"), "READY", 2,
          ["HK.00002", "HK.00001"], orders=[1, 2])
    probe("d1_hash_conflict_rejected",
          lambda value: market(value)["source_evidence"].append("hk_d1_binding_sha256=" + "9" * 64), **rejected)
    def reject_one(value):
        market(value)["rows"][0]["code"] = "HK.00888"
    probe("target_membership_rejection_preserves_later_original_order", reject_one, "PARTIAL", 1,
          ["HK.00001"], "NOT_IN_TARGET_HK_CONNECT_UNIVERSE", orders=[2])

    after_sources = sources()
    assert before_sources == after_sources, "Candidate changed concurrently; rerun for one stable source snapshot"
    return {"schema_version": "independent.hk_daily_projection_boundary_review.v1",
            "scope": "Existing synthetic verified-reader fixture only; Linux Python projection checks; no store/producer/API/Mac execution",
            "python_version": sys.version, "live_or_mac_verified": False, "natural_run_verified": False,
            "source_snapshot_unchanged_during_run": True, "sources": before_sources,
            "passed": sum(case["status"] == "PASS" for case in cases),
            "failed": sum(case["status"] == "FAIL" for case in cases), "cases": cases}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    result = main()
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if options.output:
        options.output.write_text(rendered, encoding="utf-8")
        print(json.dumps({"output": str(options.output.resolve()), "sha256": sha256(rendered.encode()),
                          "passed": result["passed"], "failed": result["failed"]}, ensure_ascii=False))
    else:
        print(rendered, end="")
    raise SystemExit(bool(result["failed"]))
