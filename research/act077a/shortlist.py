"""Mechanical ACT-077A proxies over a frozen V4 same-D record."""

from __future__ import annotations

from research.act070a.case_contract import iso_day, require
from research.act071a.case_contract import STOCK_PATTERN

PASS = "PASS_CANDIDATE_PROXY"
WATCH = "WATCH_PROXY"
VETO = "VETO_PROXY"
PROXIES = {PASS, WATCH, VETO}
HIGH_TIERS = {"POSITION_HIGH_WARNING", "POSITION_EXTREME_WARNING"}
NO_PROXY = "NO_ELIGIBLE_PROXY"


def pre_screen(stock_code: str, d: str, same_d: dict | None) -> dict:
    """Record one candidate eligibility result. The caller controls exposure and windows."""
    require(STOCK_PATTERN.fullmatch(stock_code), "INVALID_A_SHARE_CODE", stock_code)
    iso_day(d)
    report = {
        "stock_code": stock_code, "d": d, "proxy": WATCH, "native_position_tier": None,
        "native_new_entry_status": None, "native_global_l2_gate": None, "native_scoped_risk_signals": [],
        "upper_layer_stress_candidate": False, "proxy_basis": "NO_SAME_D_V4_FORMULA",
    }
    if same_d is None:
        return report
    require(same_d.get("ts_code") == stock_code and same_d.get("date") == d
            and same_d.get("engine_version") == "V4.0" and same_d.get("action_id") == "ACT-065A",
            "V4_SAME_D_IDENTITY_MISMATCH", stock_code)
    if same_d["formula_hit_count"] == 0:
        return report
    require(same_d["formula_hit_count"] > 0, "V4_SAME_D_IDENTITY_MISMATCH", "formula hit count")
    tier, gate, entry = (same_d[key] for key in ("position_tier", "global_l2_gate", "new_entry_status"))
    require(gate in {"PASS", "WATCH_CAP", "REJECT"} and entry in {"QUALIFIED", "WATCH", "UNKNOWN", "REJECTED"},
            "UNRECOGNIZED_V4_GATE_STATUS", str((gate, entry)))
    risks = [field for field in ("wick_supply_warning", "b1_extreme_combo_veto") if same_d[field] is True]
    if gate == "REJECT":
        proxy, basis = VETO, "V4_GLOBAL_L2_REJECT"
    elif entry == "REJECTED" and risks:
        proxy, basis = VETO, "V4_REJECTED_WITH_SAME_D_SCOPED_RISK"
    elif entry == "QUALIFIED" and gate == "PASS":
        proxy, basis = PASS, "V4_QUALIFIED_AND_GLOBAL_PASS"
    elif entry in {"WATCH", "UNKNOWN"}:
        proxy, basis = WATCH, "V4_WATCH_OR_UNKNOWN"
    else:
        proxy, basis = NO_PROXY, "V4_STATUS_OUTSIDE_FROZEN_PROXY_RULES"
    report.update({
        "proxy": proxy, "native_position_tier": tier, "native_new_entry_status": entry,
        "native_global_l2_gate": gate, "native_scoped_risk_signals": risks, "proxy_basis": basis,
        # The frozen engine has no typed upper-attack-anchor break event.
        # Only its explicit same-D upper tier plus wick-supply flag is used.
        "upper_layer_stress_candidate": tier in HIGH_TIERS and "wick_supply_warning" in risks,
    })
    return report


def choose_slot(candidates, *, required_proxy: str, used_stocks, upper_stress: bool = False) -> dict | None:
    """Select the first eligible candidate in A's already frozen mechanical order."""
    require(required_proxy in PROXIES, "INVALID_SHORTLIST_SLOT", required_proxy)
    banned = set(used_stocks)
    return next((row for row in candidates if row["stock_code"] not in banned and row["proxy"] == required_proxy
                 and (not upper_stress or row["upper_layer_stress_candidate"] is True)), None)
