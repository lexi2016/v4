"""Synthetic ACT-077A build, projection and frozen validator checks."""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from research.act070a.case_contract import Rejected, json_bytes, strict_json
from research.act071a.build_cases import build_case, write_case
from research.act071a.case_contract import B_SCHEMA, KB_RULES, OUTPUT_SCHEMA, RECEIPT_SCHEMA
from research.act077a.build_cases import case_bundle, write_bound_case
from research.act077a.l1 import l1_observations
from research.act077a.route_c_cli import ROUTE, ROUTE_CASES, register_routes
from research.act077a.selftest_p4 import check_rejection, check_uncomputable, check_unchanged, fixture
from research.act077a.shortlist import NO_PROXY, PASS, VETO, WATCH, choose_slot, pre_screen
from research.act077a.verdict import summarize_validator


def write_json(path: Path, data: dict) -> None:
    path.write_bytes(json_bytes(data))


def check_packages(root: Path) -> None:
    register_routes()
    assert all(ROUTE_CASES["BLIND_SHADOW"].fullmatch(f"B{i:02d}") for i in range(1, 17))
    assert not ROUTE_CASES["BLIND_SHADOW"].fullmatch("B17")
    orig, kb_group, blind = (root / name for name in ("original", "bound_k", "blind"))
    for directory in (orig, kb_group, blind):
        directory.mkdir()
    synthetic = fixture()
    day = synthetic["d"]
    immutable = {
        "day_eligibility": "FALSE", "day_eligibility_reason": "B2_D0_NON_BULLISH_NECESSARY_CONDITION",
        "event_chain_state_b2": "UNKNOWN", "formal_b2_event_presence": "ABSENT",
    }
    context = synthetic["rows"][-1]
    context.update({"status": "OBSERVED_D_ONLY", "occurred_date": day, "first_knowable_date": day})
    rows = synthetic["rows"] + [{
        "row_id": "K01_B2_DAY", "kind": "A_DAY_STATUS", "status": "OBSERVED_D_ONLY",
        "occurred_date": day, "first_knowable_date": day, "fields": immutable,
    }]
    schema, kb = B_SCHEMA.read_bytes(), KB_RULES.read_bytes()
    frozen = build_case(case_id="K01", stock_code="600000.SH", day=day, scope=ROUTE, rows=rows,
                        immutable_b2=immutable, source_sha256={"synthetic": "0" * 64}, schema=schema, kb=kb)
    base = write_case(orig, frozen, schema, kb)
    rec = write_bound_case(orig / "K01", kb_group, trusted_case_sha256=base["input_sha256"])
    assert len(rec["p4_updated_row_ids"]) == 5 and rec["base_input_sha256"] == base["input_sha256"]
    assert all((orig / "K01" / name).read_bytes() == (kb_group / "K01" / name).read_bytes()
               for name in ("chart.png", "chart.svg", B_SCHEMA.name, KB_RULES.name))
    assert rec["immutable_b2"] == base["immutable_b2"]
    raw = [{"date": (date(2021, 1, 1) + timedelta(days=i)).isoformat(),
            "open": 10, "high": 12, "low": 9, "close": 11, "volume": i + 1} for i in range(116)]
    blind_d = raw[-1]["date"]
    blind_record = case_bundle(
        "B16", {"code": "000001.SZ", "d": blind_d, "raw_prefix_sha256": "a" * 64},
        raw, {"raw_archive_sha256": "b" * 64, "price_basis": "RAW", "volume_basis": "RAW"}, blind,
    )
    assert blind_record["scope"] == "BLIND_SHADOW" and len(blind_record["p4_updated_row_ids"]) == 5
    actual = strict_json((blind / "B16" / "input.json").read_bytes())
    indicator = {**raw[-1], "vol_ratio_5": 116 / 114, "W": 10.7, "Y": 11.2,
                 "upper_wick_pct": 100 / 3, "low60_gain_pct": 200 / 9}
    observation = l1_observations(actual, indicator)
    assert observation["status"] == "OBSERVE_ANOMALY"
    assert observation["observations"] == {"W": 10.7, "Y": 11.2, "W_ge_Y": False,
                                          "peak35_ratio": 1, "vr5": 116 / 114,
                                          "upper_wick_pct": 100 / 3, "low60_gain_pct": 200 / 9}
    try:
        l1_observations(actual, {**indicator, "volume": 0})
    except Rejected as exc:
        assert exc.code == "L1_D_SOURCE_IDENTITY_MISMATCH"
    else:
        raise AssertionError("mismatched source accepted")
    trusted = root / "A_receipt.json"
    write_json(trusted, {"schema_version": RECEIPT_SCHEMA, "cases": {"K01": rec, "B16": blind_record}})
    for case_id, group, receipt in (("K01", kb_group, rec), ("B16", blind, blind_record)):
        path = root / f"{case_id}.json"
        write_json(path, {"schema_version": OUTPUT_SCHEMA, "case_id": case_id,
                          "input_sha256": receipt["input_sha256"],
                          "claims": [], "abstain_codes": ["INSUFFICIENT_D_ONLY_EVIDENCE"]})
        args = [sys.executable, "-B", "-m", "research.act077a.route_c_cli", "--case-dir", str(group / case_id),
                "--trusted-receipt", str(trusted), "--output", str(path)]
        proc = subprocess.run(args, capture_output=True, check=True)
        assert strict_json(proc.stdout)["immutable_b2"] == receipt["immutable_b2"]


def check_shortlist() -> None:
    stock, day = "600000.SH", "2022-03-01"
    native = {"ts_code": stock, "date": day, "engine_version": "V4.0", "action_id": "ACT-065A",
              "formula_hit_count": 1, "position_tier": "POSITION_HIGH_WARNING", "global_l2_gate": "PASS",
              "new_entry_status": "QUALIFIED", "wick_supply_warning": False, "b1_extreme_combo_veto": False}
    got = pre_screen(stock, day, native)
    assert got["proxy"] == PASS
    assert pre_screen(stock, day, None)["proxy"] == WATCH
    assert pre_screen(stock, day, {**native, "new_entry_status": "REJECTED"})["proxy"] == NO_PROXY
    broad = pre_screen(stock, day, {**native, "global_l2_gate": "REJECT"})
    strict = pre_screen(stock, day, {**native, "new_entry_status": "REJECTED", "wick_supply_warning": True})
    assert broad["proxy"] == VETO and strict["proxy"] == VETO
    assert choose_slot([broad, strict], required_proxy=VETO, used_stocks=(), upper_stress=True) == strict
    assert choose_slot([broad, strict], required_proxy=VETO, used_stocks=(stock,), upper_stress=True) is None


def check_verdict() -> None:
    accepted = {"accepted": True, "code": "ACCEPTED_CANDIDATE_ONLY"}
    failed = {"accepted": False, "code": "OUT_OF_D_REFERENCE"}
    scope = "UPPER_ATTACK_ANCHOR_ONLY"
    assert summarize_validator(accepted, veto_scope=scope) == {"technical_status": "PASS", "veto_scope": scope}
    assert summarize_validator(failed, veto_scope=scope) == {
        "technical_status": "FAIL", "technical_fail_code": "OUT_OF_D_REFERENCE", "veto_scope": scope,
    }
    explicit = summarize_validator(accepted, veto_scope=scope, structural_verdict="STRUCT_WATCH_ONLY")
    assert explicit["structural_verdict"] == "STRUCT_WATCH_ONLY"
    try:
        summarize_validator(failed, veto_scope=scope, structural_verdict="STRUCT_PASS_CANDIDATE")
    except Rejected as exc:
        assert exc.code == "STRUCTURAL_VERDICT_REQUIRES_TECHNICAL_PASS"
    else:
        raise AssertionError("technical failure received a structural verdict")


def main():
    check_unchanged()
    check_uncomputable()
    check_rejection()
    check_shortlist()
    check_verdict()
    with TemporaryDirectory(prefix="act077a-synthetic-") as temp:
        check_packages(Path(temp))
    print('{"status":"PASS","synthetic_groups":6,"frozen_cli_roundtrips":2,"market_source_opens":0,"model_calls":0}')


if __name__ == "__main__":
    main()
