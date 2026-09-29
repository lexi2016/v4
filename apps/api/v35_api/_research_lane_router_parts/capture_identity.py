"""apps.api.v35_api.research_lane_router: capture_identity (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __capture_identity_failure_body(_v4_scope, /, *, payload, snapshot, reason, research_date, store):
    """Keep a failed identity typed while retaining exact artifact lineage."""

    result = _v4_global(_v4_scope, '_global_industry_missing')(research_date=research_date, reason=reason)
    result["artifact_trade_date"] = _v4_global(_v4_scope, 'str')(payload.get("trade_date") or research_date)
    session_date = _v4_global(_v4_scope, 'str')(snapshot.get("capture_session_date") or "")
    result["source_date"] = session_date
    result["us_session_date"] = session_date
    result["capture_session_date"] = session_date
    result["capture_phase"] = _v4_global(_v4_scope, 'str')(snapshot.get("capture_phase") or "POST_CLOSE")
    result["artifact"] = _v4_global(_v4_scope, '_global_industry_lineage')(store, research_date, payload)
    return result


def __bound_capture_for_snapshot_body(_v4_scope, /, *, payload, snapshot, research_date):
    """Bind one snapshot to one explicit payload capture identity.

    The store already validates the individual artifact.  This consumer-level
    check additionally prevents a valid snapshot from being paired with an
    unrelated, stale, or ambiguous capture when target and US session dates
    differ.
    """

    session_date = _v4_global(_v4_scope, 'str')(snapshot.get("capture_session_date") or "")
    provider_dates = snapshot.get("provider_session_dates")
    if not _v4_global(_v4_scope, 'isinstance')(provider_dates, _v4_global(_v4_scope, 'list')):
        return None, "MARKET_SNAPSHOT_PROVIDER_SESSION_DATES_UNBOUND"
    normalized_provider_dates = [_v4_global(_v4_scope, 'str')(value) for value in provider_dates]
    if (
        _v4_global(_v4_scope, 'len')(normalized_provider_dates) != 1
        or normalized_provider_dates[0] != session_date
    ):
        return None, "MARKET_SNAPSHOT_PROVIDER_SESSION_DATE_UNIQUE_REQUIRED"

    captures = payload.get("us_session_captures")
    if not _v4_global(_v4_scope, 'isinstance')(captures, _v4_global(_v4_scope, 'list')):
        return None, "MARKET_SNAPSHOT_CAPTURE_IDENTITY_UNBOUND"
    snapshot_late = _v4_global(_v4_scope, '_is_late_capture_identity')(snapshot)
    snapshot_phase = _v4_global(_v4_scope, 'str')(snapshot.get("capture_phase") or "")
    matches: list[dict[str, Any]] = []
    for value in captures:
        if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
            continue
        capture = _v4_global(_v4_scope, 'dict')(value)
        if (
            capture.get("us_session_date") != session_date
            or capture.get("capture_phase") != snapshot_phase
            or capture.get("original_time_capture") is not True
            or capture.get("capture_origin") != "ORIGINAL_TIME_CAPTURE"
            or _v4_global(_v4_scope, '_is_late_capture_identity')(capture) != snapshot_late
            or (
                snapshot_late and capture.get("late") is not True
            )
            or (
                not snapshot_late and capture.get("late", False) is not False
            )
        ):
            continue
        if _v4_global(_v4_scope, 'any')(
            field in snapshot
            and snapshot.get(field) is not None
            and capture.get(field) != snapshot.get(field)
            for field in _v4_global(_v4_scope, '_CAPTURE_IDENTITY_FIELDS')
        ):
            continue
        receipt = snapshot.get("provider_receipt")
        if _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'Mapping')) and _v4_global(_v4_scope, 'any')(
            field in receipt
            and receipt.get(field) is not None
            and capture.get(field) != receipt.get(field)
            for field in _v4_global(_v4_scope, '_CAPTURE_IDENTITY_FIELDS')
        ):
            continue
        matches.append(capture)

    if _v4_global(_v4_scope, 'len')(matches) != 1:
        return None, "MARKET_SNAPSHOT_CAPTURE_IDENTITY_AMBIGUOUS_OR_UNBOUND"
    capture = matches[0]
    for field in _v4_global(_v4_scope, '_CAPTURE_IDENTITY_FIELDS'):
        if (
            field in payload
            and payload.get(field) is not None
            and payload.get(field) != capture.get(field)
        ):
            return None, "MARKET_SNAPSHOT_PAYLOAD_CAPTURE_IDENTITY_MISMATCH"

    if snapshot_phase != "POST_CLOSE":
        return None, "MARKET_SNAPSHOT_NOT_POST_CLOSE"
    if snapshot_late:
        if (
            capture.get("capture_mode") != _v4_global(_v4_scope, 'LATE_CAPTURE_MODE')
            or capture.get("reason") != _v4_global(_v4_scope, 'LATE_CAPTURE_REASON')
            or capture.get("capture_reason") not in (None, _v4_global(_v4_scope, 'LATE_CAPTURE_REASON'))
        ):
            return None, "MARKET_SNAPSHOT_LATE_CAPTURE_IDENTITY_INVALID"
        if session_date != research_date:
            # A late cross-date projection is accepted only for the directly
            # preceding calendar date.  Without a bound US holiday calendar,
            # any other date remains CANNOT_CONFIRM rather than being treated
            # as a valid old-session fallback.
            try:
                expected_previous = (
                    _v4_global(_v4_scope, 'datetime').strptime(research_date, "%Y%m%d") - _v4_global(_v4_scope, 'timedelta')(days=1)
                ).strftime("%Y%m%d")
            except _v4_global(_v4_scope, 'ValueError'):
                return None, "MARKET_SNAPSHOT_TARGET_DATE_INVALID"
            if session_date != expected_previous:
                return None, "MARKET_SNAPSHOT_CAPTURE_DATE_NOT_BOUND_TO_TARGET"
    elif session_date != research_date:
        return None, "MARKET_SNAPSHOT_CROSS_DATE_REQUIRES_LATE_CAPTURE"
    return capture, None
