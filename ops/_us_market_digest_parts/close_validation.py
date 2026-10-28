"""Validate regular-session quote observations without requiring identical seconds."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime

from contracts.us_equity_calendar import NY, session


def validate_close_observations(snapshot: Mapping) -> str | None:
    """Field 30 is an update time; each quote must have reached the session close.

    Tencent's field 3 is the regular quote and field 4 the previous close.
    Observation seconds may differ across symbols. Dates, close cutoff, source
    response identity and complete coverage remain independent requirements.
    """
    try:
        token = str(snapshot.get("capture_session_date") or snapshot.get("source_date") or "")
        official = session(token)
        captured = datetime.fromisoformat(str(snapshot["captured_at"]).replace("Z", "+00:00"))
        if captured.tzinfo is None or official.close_at is None:
            return "QUOTE_REGULAR_CLOSE_UNCONFIRMED"
        quotes = snapshot.get("quotes") or []
        if not quotes:
            return "QUOTE_REGULAR_CLOSE_UNCONFIRMED"
        for quote in quotes:
            if quote.get("session_date") != token:
                return "QUOTE_SESSION_DATE_MISMATCH_CAPTURE"
            observed = datetime.strptime(token + " " + str(quote.get("session_time") or ""), "%Y%m%d %H:%M:%S").replace(tzinfo=NY)
            if not official.close_at <= observed <= captured:
                return "QUOTE_OUTSIDE_COMPLETED_REGULAR_SESSION"
    except (ValueError, TypeError, KeyError):
        return "QUOTE_REGULAR_CLOSE_UNCONFIRMED"
    return None


def normalize_close_snapshot(snapshot: Mapping) -> dict:
    """Correct only the false mixed-second failure, retaining prices and lineage."""
    result = deepcopy(dict(snapshot))
    if result.get("capture_phase") != "POST_CLOSE":
        return result
    error = validate_close_observations(result)
    if error:
        result["status"] = "CANNOT_CONFIRM"
        result["cannot_confirm"] = sorted(set(result.get("cannot_confirm") or []) | {error})
        return result
    if result.get("provider_session_dates") != [result.get("capture_session_date")]:
        return result
    for row in result.get("rows") or []:
        row["cannot_confirm"] = [r for r in row.get("cannot_confirm") or [] if r != "QUOTE_SESSION_TIME_MIXED"]
        if (row.get("requested_symbol_count") == row.get("available_symbol_count")
                and not row.get("missing_symbols") and not row["cannot_confirm"]
                and row.get("quote_session_dates") == result["provider_session_dates"]
                and row.get("quote_session_times")):
            row["status"] = "READY"
    result["cannot_confirm"] = [r for r in result.get("cannot_confirm") or [] if r != "QUOTE_SESSION_TIME_MIXED"]
    rows = result.get("rows") or []
    if (len(rows) == 24 and all(r.get("status") == "READY" for r in rows)
            and result.get("requested_symbol_count") == result.get("available_symbol_count")
            and set(result["cannot_confirm"]).issubset({"MARKET_SNAPSHOT_INCOMPLETE"})):
        result["status"] = "READY"
        result["cannot_confirm"] = []
    return result
