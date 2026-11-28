"""Project the L1 diagnostic sidecar from a frozen V4 D-only indicator row."""

from __future__ import annotations

from decimal import Decimal
from math import isclose, isfinite

from research.act070a.case_contract import OHLCV_FIELDS, case_digest, decimal_number, require
from research.act077a.p4 import chart_bars, ratio


def _number(value) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if isfinite(number) else None


def l1_observations(case: dict, indicator_row) -> dict:
    """Return one observation. The caller supplies the last row of its locked prefix."""
    require(case.get("input_sha256") == case_digest(case), "INPUT_HASH_MISMATCH", case["case_id"])
    bars = chart_bars(case)
    last = bars[-1]["fields"]
    require(str(indicator_row["date"]) == case["d"] and all(
        decimal_number(str(indicator_row[field])) == decimal_number(str(last[field])) for field in OHLCV_FIELDS
    ), "L1_D_SOURCE_IDENTITY_MISMATCH", case["case_id"])
    volumes = [decimal_number(str(row["fields"]["volume"])) for row in bars]
    require(all(volume >= 0 for volume in volumes), "INVALID_CHART_MAPPING", case["case_id"])
    vr5_reference = ratio(volumes[-1], sum(volumes[-5:], Decimal(0)) / 5)["value"]
    vr5 = _number(indicator_row["vol_ratio_5"])
    require((vr5 is None and vr5_reference is None)
            or (vr5 is not None and vr5_reference is not None and isclose(vr5, vr5_reference, rel_tol=1e-12)),
            "L1_D_SOURCE_IDENTITY_MISMATCH", "frozen vr5 disagrees with chart tail")
    w, y = _number(indicator_row["W"]), _number(indicator_row["Y"])
    return {
        "case_id": case["case_id"], "d": case["d"], "layer": "L1", "status": "OBSERVE_ANOMALY",
        "observations": {
            "vr5": vr5, "peak35_ratio": ratio(volumes[-1], max(volumes))["value"],
            "upper_wick_pct": _number(indicator_row["upper_wick_pct"]),
            "W": w, "Y": y, "W_ge_Y": w >= y if w is not None and y is not None else None,
            "low60_gain_pct": _number(indicator_row["low60_gain_pct"]),
        },
    }
