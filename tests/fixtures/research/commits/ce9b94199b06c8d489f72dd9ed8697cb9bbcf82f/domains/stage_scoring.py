"""Pure V3.5 stage scoring extracted from the frozen V3 behavior contract."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping


def _number(value: Any) -> float | None:
    try:
        if value in ("", None, "N/A"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pct(new_value: float | None, old_value: float | None) -> float | None:
    if new_value is None or old_value in (None, 0):
        return None
    return (new_value / old_value - 1.0) * 100.0


def _first_number(value: Any) -> float | None:
    if isinstance(value, list) and value:
        return _number(value[0])
    return _number(value)


def _value(row: Mapping[str, Any], primary: str, legacy: str) -> float | None:
    value = _number(row.get(primary))
    return value if value is not None else _number(row.get(legacy))


def _close_position(last_price: float | None, high_price: float | None, low_price: float | None) -> float:
    if last_price is None or high_price is None or low_price is None or high_price <= low_price:
        return 0.5
    return _bounded((last_price - low_price) / (high_price - low_price), 0.0, 1.0)


def _bid_pressure(bid_vol1: float | None, ask_vol1: float | None) -> float:
    if bid_vol1 is None or ask_vol1 is None or bid_vol1 + ask_vol1 <= 0:
        return 0.0
    return _bounded((bid_vol1 / (bid_vol1 + ask_vol1) - 0.5) * 12.0, -6.0, 6.0)


def score_a_stage(row: Mapping[str, Any], stage_id: str) -> float:
    """Reproduce the frozen V3 A-share stage score without runtime dependencies."""
    open_price = _value(row, "open_price", "qmt_open")
    last_price = _value(row, "last_price", "qmt_last")
    previous_close = _value(row, "prev_close_price", "qmt_prev_close")
    high_price = _value(row, "high_price", "qmt_high")
    low_price = _value(row, "low_price", "qmt_low")
    if open_price is None:
        open_price = last_price
    if high_price is None:
        high_price = last_price
    if low_price is None:
        low_price = last_price
    turnover = _value(row, "turnover", "qmt_amount") or 0.0
    bid_vol1 = _value(row, "bid_vol1", "qmt_bid_vol1")
    ask_vol1 = _value(row, "ask_vol1", "qmt_ask_vol1")
    if bid_vol1 is None:
        bid_vol1 = _first_number(row.get("bidVol"))
    if ask_vol1 is None:
        ask_vol1 = _first_number(row.get("askVol"))
    pool_score = _value(row, "pool_score", "stage1_formal_score") or 0.0
    gap_change = _pct(open_price, previous_close) or 0.0
    window_change = _pct(last_price, open_price) or 0.0
    amount_bonus = min(turnover / 100_000_000.0, 6.0) * 2.5
    pool_ratio = _bounded(pool_score / 125.0, 0.0, 1.0)
    pressure = _bid_pressure(bid_vol1, ask_vol1)
    if stage_id == "STAGE_0925":
        return round(
            50.0
            + _bounded(gap_change, -10.0, 10.0) * 10.0
            + amount_bonus
            + pressure
            + pool_ratio * 3.0,
            6,
        )
    return round(
        50.0
        + window_change * 9.0
        + _close_position(last_price, high_price, low_price) * 25.0
        + amount_bonus
        + pressure
        + pool_ratio * 8.0,
        6,
    )


def score_hk_stage(row: Mapping[str, Any]) -> float:
    """Reproduce the frozen V3 HK Connect stage score."""
    score = 35.0
    pct_change = _number(row.get("pct_chg"))
    window_change = _number(row.get("stage_window_change_pct"))
    turnover_yi = _number(row.get("turnover_hkd_yi"))
    cap_yi = _number(row.get("circular_market_cap_hkd_yi"))
    close_position = _number(row.get("stage_close_position"))
    sources = str(row.get("source_universe") or "")
    if pct_change is not None:
        if pct_change >= 15:
            score += 24
        elif pct_change >= 10:
            score += 20
        elif pct_change >= 5:
            score += 14
        elif pct_change > 0:
            score += 6
        else:
            score -= 15
    if window_change is not None:
        if window_change >= 3:
            score += 14
        elif window_change >= 1:
            score += 9
        elif window_change < -2:
            score -= 10
    if turnover_yi is not None:
        if turnover_yi >= 1:
            score += 10
        elif turnover_yi >= 0.2:
            score += 6
        elif turnover_yi >= 0.05:
            score += 3
    if cap_yi is not None and cap_yi <= 100:
        score += 12
    if close_position is not None:
        score += close_position * 8
    if "OLD_DEMON_MEMORY" in sources:
        score += 4
    if "NEW_HKCONNECT_BATCH" in sources:
        score += 3
    if "LOW_FLOAT_FILTER" in sources:
        score += 5
    return round(_bounded(score, 0.0, 100.0), 3)


def _safe_row(source: Mapping[str, Any]) -> dict[str, Any]:
    row = deepcopy(dict(source))
    row.update(
        {
            "recommendation_status": "WATCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )
    return row


def rank_a_stage_rows(
    source_rows: Iterable[Mapping[str, Any]],
    stage_id: str,
    *,
    limit: int = 120,
) -> list[dict[str, Any]]:
    rows = []
    for source in source_rows:
        row = _safe_row(source)
        row["stage_id"] = stage_id
        row["stage_score"] = score_a_stage(row, stage_id)
        rows.append(row)
    rows.sort(
        key=lambda row: (
            -(_number(row.get("stage_score")) or -999999.0),
            -(
                (_value(row, "open_price", "qmt_open") or 0.0)
                / (_value(row, "prev_close_price", "qmt_prev_close") or 1.0)
                if stage_id == "STAGE_0925"
                else (_value(row, "turnover", "qmt_amount") or 0.0)
            ),
            int(_number(row.get("pool_rank") or row.get("stage1_formal_rank")) or 999999),
            str(row.get("symbol") or row.get("stock_code") or ""),
        )
    )
    return _rank(rows[:limit])


def rank_hk_stage_rows(
    source_rows: Iterable[Mapping[str, Any]],
    *,
    limit: int = 120,
) -> list[dict[str, Any]]:
    rows = []
    for source in source_rows:
        row = _safe_row(source)
        row["stage_rtdata_score"] = score_hk_stage(row)
        rows.append(row)
    rows.sort(
        key=lambda row: (
            -(_number(row.get("stage_rtdata_score")) or 0.0),
            -(_number(row.get("pct_chg")) or -999.0),
            -(_number(row.get("turnover_hkd") or row.get("turnover")) or 0.0),
            str(row.get("symbol") or row.get("code") or ""),
        )
    )
    return _rank(rows[:limit])


def _rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, row in enumerate(rows, start=1):
        row["stage_rank"] = str(index)
        row["decision_level"] = "WATCH_TOP" if index <= 10 else "OBSERVE_ONLY"
    return rows
