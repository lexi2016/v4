"""Authoritative 2026 NYSE core-session calendar used by the existing US lane.

This module is intentionally small and read-only.  It does not fetch data and
it does not schedule work.  It supplies one missing contract: whether a dated
US equity session is open and its official regular-session close time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

CALENDAR_PATH = Path(__file__).with_name("us_equity_calendar_2026.json")
NY = ZoneInfo("America/New_York")
HK = ZoneInfo("Asia/Hong_Kong")
SUPPORTED_YEAR = 2026
MAX_LOOKBACK_DAYS = 31


@dataclass(frozen=True)
class UsEquitySession:
    session_date: str
    state: str
    close_at: datetime | None
    source_url: str


def _load() -> dict:
    payload = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "v4.us_equity_calendar.v1" or payload.get("year") != 2026:
        raise ValueError("US_EQUITY_CALENDAR_IDENTITY_INVALID")
    if payload.get("timezone") != "America/New_York":
        raise ValueError("US_EQUITY_CALENDAR_TIMEZONE_INVALID")
    return payload


def _token(value: str | date) -> str:
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("US_EQUITY_SESSION_DATE_INVALID")
    parsed = datetime.strptime(value, "%Y%m%d").date()
    return parsed.strftime("%Y%m%d")


def session(value: str | date) -> UsEquitySession:
    payload = _load()
    token = _token(value)
    day = datetime.strptime(token, "%Y%m%d").date()
    source_url = str(payload["official_source"]["url"])
    if day.year != SUPPORTED_YEAR:
        raise ValueError("US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE")
    if day.weekday() >= 5:
        return UsEquitySession(token, "CLOSED_WEEKEND", None, source_url)
    if token in set(payload["holidays"]):
        return UsEquitySession(token, "CLOSED_HOLIDAY", None, source_url)
    hhmm = str(payload["early_close"] if token in set(payload["early_closes"]) else payload["regular_close"])
    close = datetime.combine(day, time(int(hhmm[:2]), int(hhmm[2:])), NY)
    state = "OPEN_EARLY_CLOSE" if token in set(payload["early_closes"]) else "OPEN_FULL_DAY"
    return UsEquitySession(token, state, close, source_url)


def latest_completed_session(cutoff: datetime, *, max_lookback_days: int = 10) -> UsEquitySession:
    """Resolve the latest official US core session completed before an HK cutoff.

    ``cutoff`` must be timezone aware.  DST is handled by ``ZoneInfo``.  The
    function never guesses through an unbounded history window.
    """
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("US_EQUITY_CUTOFF_TIMEZONE_REQUIRED")
    if type(max_lookback_days) is not int or not 0 <= max_lookback_days <= MAX_LOOKBACK_DAYS:
        raise ValueError("US_EQUITY_LOOKBACK_RANGE_INVALID")
    observed_ny = cutoff.astimezone(NY)
    cursor = observed_ny.date()
    for _ in range(max_lookback_days + 1):
        if cursor.year != SUPPORTED_YEAR:
            raise ValueError("US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE")
        candidate = session(cursor)
        if candidate.close_at is not None and candidate.close_at <= observed_ny:
            return candidate
        cursor -= timedelta(days=1)
    raise ValueError("US_EQUITY_COMPLETED_SESSION_NOT_FOUND")


__all__ = ["CALENDAR_PATH", "HK", "NY", "UsEquitySession", "latest_completed_session", "session"]
