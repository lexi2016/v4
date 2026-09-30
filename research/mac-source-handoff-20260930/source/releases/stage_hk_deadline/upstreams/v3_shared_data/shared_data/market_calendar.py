"""Frozen 2026 A-share trading-day guard for scheduled shared acquisition."""
from __future__ import annotations

from datetime import datetime


CALENDAR_SCHEMA = "v3_shared_data.a_share_market_calendar.2026.v1"
ORACLE_SCHEMA = "v3.market_calendar.2026.v1"
ORACLE_SOURCE_SHA256 = "66ff439b8363b7e36077bb86bf052710afbb6c47276b68f77fe259cb1d24a1b6"

_CLOSED_PERIODS = (
    ("20260101", "20260104"),
    ("20260215", "20260223"),
    ("20260404", "20260406"),
    ("20260501", "20260505"),
    ("20260619", "20260621"),
    ("20260925", "20260927"),
    ("20261001", "20261007"),
)


def evaluate_a_share_trade_date(date8: str) -> dict[str, object]:
    try:
        if not isinstance(date8, str) or len(date8) != 8 or not date8.isascii() or not date8.isdigit():
            raise ValueError("date must be exact ASCII YYYYMMDD")
        day = datetime.strptime(date8, "%Y%m%d").date()
    except ValueError:
        return {
            "eligible": False,
            "status": "CALENDAR_DATE_INVALID",
            "date": str(date8),
            "schema_version": CALENDAR_SCHEMA,
        }
    if day.year != 2026:
        return {
            "eligible": False,
            "status": "CALENDAR_OUT_OF_RANGE",
            "date": str(date8),
            "schema_version": CALENDAR_SCHEMA,
        }
    if day.weekday() >= 5:
        status = "SKIPPED_NON_TRADING_DAY_WEEKEND"
        eligible = False
    elif any(start <= date8 <= end for start, end in _CLOSED_PERIODS):
        status = "SKIPPED_NON_TRADING_DAY_HOLIDAY"
        eligible = False
    else:
        status = "TRADING_DAY_READY"
        eligible = True
    return {
        "eligible": eligible,
        "status": status,
        "date": date8,
        "schema_version": CALENDAR_SCHEMA,
        "oracle_schema": ORACLE_SCHEMA,
        "oracle_source_sha256": ORACLE_SOURCE_SHA256,
    }


__all__ = ["CALENDAR_SCHEMA", "evaluate_a_share_trade_date"]
