"""V3-equivalent Futu K_1M minute window aggregation (deterministic port).

Direct clean port of the current V3 pure function
``run_opening_scheduler.aggregate_futu_minute_window_rows``, parameterized by
stage_id instead of the V3 StageSpec object. Pure: no network, no subprocess,
no filesystem access. Unknown stage ids fail closed with ValueError.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .contracts import STAGE_WINDOWS


def safe_float(value: Any) -> float | None:
    if value in ("", None, "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def aggregate_futu_minute_window_rows(
    trade_date: str,
    stage_id: str,
    raw_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate raw Futu K_1M rows into V3 normalized minute rows.

    The window is ``window_start + 1 minute <= time_key < window_end`` where
    window_start/window_end come from STAGE_WINDOWS (window_end includes the
    +5 seconds for the first three stages). Opening 09:30 bars, wrong dates,
    bars at/after window_end and structurally malformed rows are excluded.
    Aggregate open first, close last, high max, low min, turnover/volume sum,
    previous close from the first dated row of the day, window_start/window_end
    from the included rows, temporal_cutoff_safe True, empty bid/ask quote
    fields exactly as V3.
    """
    window = STAGE_WINDOWS.get(stage_id)
    if window is None:
        raise ValueError(f"unknown stage {stage_id!r}")
    window_start_str, window_end_str, _cutoff_at = window

    trade_day = datetime.strptime(trade_date, "%Y%m%d")
    window_start = datetime.combine(
        trade_day.date(),
        datetime.strptime(window_start_str, "%H:%M:%S").time(),
    ) + timedelta(minutes=1)
    window_end = datetime.combine(
        trade_day.date(),
        datetime.strptime(window_end_str, "%H:%M:%S").time(),
    )

    grouped: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or "").strip().upper()
        try:
            bar_time = datetime.strptime(str(raw.get("time_key") or ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if not code or bar_time.date() != trade_day.date():
            continue
        grouped.setdefault(code, []).append((bar_time, raw))

    aggregated: list[dict[str, Any]] = []
    for batch_index, (code, dated_rows) in enumerate(sorted(grouped.items()), start=1):
        dated_rows.sort(key=lambda item: item[0])
        window_rows = [
            (bar_time, raw)
            for bar_time, raw in dated_rows
            if window_start <= bar_time < window_end
        ]
        if not window_rows:
            continue
        first_time, first = window_rows[0]
        last_time, last = window_rows[-1]
        high_values = [safe_float(raw.get("high")) for _, raw in window_rows]
        low_values = [safe_float(raw.get("low")) for _, raw in window_rows]
        volume = sum(safe_float(raw.get("volume")) or 0.0 for _, raw in window_rows)
        turnover = sum(safe_float(raw.get("turnover")) or 0.0 for _, raw in window_rows)
        day_previous_close = safe_float(dated_rows[0][1].get("last_close"))
        aggregated.append(
            {
                "batch_index": batch_index,
                "code": code,
                "name": str(last.get("name") or first.get("name") or ""),
                "update_time": last_time.strftime("%Y-%m-%d %H:%M:%S"),
                "last_price": safe_float(last.get("close")),
                "open_price": safe_float(first.get("open")),
                "high_price": max((value for value in high_values if value is not None), default=None),
                "low_price": min((value for value in low_values if value is not None), default=None),
                "prev_close_price": day_previous_close,
                "turnover": turnover,
                "volume": volume,
                "bid_price": "",
                "ask_price": "",
                "bid_vol": "",
                "ask_vol": "",
                "window_start": first_time.strftime("%Y-%m-%d %H:%M:%S"),
                "window_end": last_time.strftime("%Y-%m-%d %H:%M:%S"),
                "bar_count": len(window_rows),
                "temporal_cutoff_safe": True,
            }
        )
    return aggregated
