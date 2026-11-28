"""Bind five existing P4 rows to A-fixed D-inclusive chart windows."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from research.act070a.case_contract import case_digest, decimal_number, iso_day, require, row_id

WINDOWS = (5, 10, 20)
CHART_SESSIONS = 35
SIDES = ("UP", "DOWN", "FLAT")
P4_FIELDS = (
    "registered_segment", "chronological_candle_volume", "up_candle_volume",
    "down_candle_volume", "flat_candle_volume",
)
BINDING = "A_FIXED_D_INCLUSIVE_EVIDENCE_WINDOWS"


def chart_bars(case: dict) -> list[dict]:
    """Return ordered A-signed bars after checking their exact D boundary."""
    bars = [row for row in case["rows"] if row["kind"] == "CHART_BAR"]
    ids = [row["row_id"] for row in bars]
    require(len(bars) == len(set(ids)) == CHART_SESSIONS and ids == case["chart"]["row_ids"],
            "INVALID_CHART_MAPPING", case["case_id"])
    dates = [iso_day(row["fields"]["date"]) for row in bars]
    require(dates == sorted(set(dates)) and dates[-1] == iso_day(case["d"]),
            "INVALID_D_PREFIX", case["case_id"])
    indices = [row["source"]["stock_session_index"] for row in bars]
    require(all(type(index) is int and index >= 0 for index in indices)
            and indices == list(range(indices[0], indices[0] + CHART_SESSIONS)),
            "INVALID_CHART_MAPPING", "nonconsecutive actual stock sessions")
    for row in bars:
        day = row["fields"]["date"]
        require(row["status"] == "OBSERVED_D_ONLY"
                and row["occurred_date"] == row["first_knowable_date"] == day,
                "INVALID_CHART_MAPPING", row["row_id"])
    return bars


def _scalar(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def ratio(numerator: Decimal | None, denominator: Decimal | None) -> dict:
    result = _scalar(numerator / denominator) if numerator is not None and denominator else None
    return {"value": result, "status": "OBSERVED_D_ONLY" if result is not None else "UNCOMPUTABLE"}


def _summarize(values: list[Decimal]) -> tuple[dict, Decimal | None, Decimal | None]:
    total = sum(values, Decimal(0)) if values else None
    mean = total / len(values) if values else None
    return {"count": len(values), "sum": _scalar(total), "mean": _scalar(mean)}, total, mean


def _candle(row: dict) -> tuple[dict, Decimal]:
    fields = row["fields"]
    close, opening, volume = (decimal_number(str(fields[key])) for key in ("close", "open", "volume"))
    require(volume >= 0, "INVALID_CHART_MAPPING", row["row_id"])
    side = "UP" if close > opening else "DOWN" if close < opening else "FLAT"
    return {"row_id": row["row_id"], "date": fields["date"], "volume": fields["volume"], "side": side}, volume


def _evidence_windows(case: dict) -> tuple[dict, dict, dict]:
    observed = [_candle(row) for row in chart_bars(case)[-max(WINDOWS):]]
    bounds, chronology, summaries = {}, {}, {side: {} for side in SIDES}
    trailing_five = [volume for _, volume in observed[-5:]]
    vr5 = ratio(trailing_five[-1], sum(trailing_five, Decimal(0)) / 5)
    for size in WINDOWS:
        key = str(size)
        window = observed[-size:]
        first, end = window[0][0], window[-1][0]
        bounds[key] = {"start_row_id": first["row_id"], "start_date": first["date"],
                       "end_row_id": end["row_id"], "end_date": end["date"], "session_count": size}
        totals, means = {}, {}
        for side in SIDES:
            values = [volume for item, volume in window if item["side"] == side]
            summaries[side][key], totals[side], means[side] = _summarize(values)
            if side == "DOWN" and totals[side] == 0:
                summaries[side][key]["mean"] = means[side] = None
        chronology[key] = {
            "bars": [item for item, _ in window],
            "up_to_down_sum_ratio": ratio(totals["UP"], totals["DOWN"]),
            "up_to_down_mean_ratio": ratio(means["UP"], means["DOWN"]),
        }
    return (
        {"binding": BINDING, "structural_event_binding": "UNBOUND", "windows": bounds},
        {"windows": chronology, "vr5": vr5},
        summaries,
    )


def bind_p4(case: dict) -> dict:
    """Copy one frozen case and change only five P4 rows and its input digest."""
    require(case.get("input_sha256") == case_digest(case), "INPUT_HASH_MISMATCH", case["case_id"])
    binding, chronological, by_side = _evidence_windows(case)
    values = [binding, chronological, *({"windows": by_side[side]} for side in SIDES)]
    expected = {
        row_id(case["case_id"], "PRIM", "P4", str(ordinal)): (field, value)
        for ordinal, (field, value) in enumerate(zip(P4_FIELDS, values, strict=True), start=24)
    }
    patched = deepcopy(case)
    seen = set()
    for row in patched["rows"]:
        item_id = row["row_id"]
        if row.get("primitive_id") != "P4" and item_id not in expected:
            continue
        require(item_id in expected and item_id not in seen, "INVALID_P4_ROSTER", item_id)
        field, value = expected[item_id]
        require(row.get("kind") == "PRIMITIVE" and row.get("primitive_id") == "P4"
                and row.get("status") == "MISSING_SOURCE" and row.get("gap_reason") == "SEGMENT_DEFINITION_SOURCE_UNBOUND"
                and row.get("fields") == {field: "UNKNOWN"}
                and row["occurred_date"] == row["first_knowable_date"] == case["d"],
                "UNEXPECTED_P4_BASE", item_id)
        row.update({"status": "OBSERVED_D_ONLY", "fields": {field: value}, "gap_reason": "",
                    "source": {"id": "act077a_fixed_d_only_p4", "locator": "A-chart-whitelist:5/10/20:D-inclusive"}})
        seen.add(item_id)
    require(seen == expected.keys(), "INVALID_P4_ROSTER", "five frozen P4 identities required")
    patched["input_sha256"] = case_digest(patched)
    return patched
