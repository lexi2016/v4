"""ops.us_market_digest: session_windows (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _us_capture_window_body(_v4_scope, /, us_session_date, capture_phase):
    """Return a local, DST-aware capture window for one US session date."""
    selected = _v4_global(_v4_scope, '_session_date')(us_session_date)
    phase = _v4_global(_v4_scope, '_phase')(capture_phase)
    if phase == _v4_global(_v4_scope, 'HISTORICAL_BACKFILL_PHASE'):
        start = _v4_global(_v4_scope, 'datetime').combine(selected, _v4_global(_v4_scope, 'time').min, tzinfo=_v4_global(_v4_scope, 'US_TZ'))
        end = _v4_global(_v4_scope, 'datetime').combine(selected + _v4_global(_v4_scope, 'timedelta')(days=1), _v4_global(_v4_scope, 'time').min, tzinfo=_v4_global(_v4_scope, 'US_TZ'))
        return start, end
    start_time, end_time = _v4_global(_v4_scope, '_PHASE_TIMES')[phase]
    return (
        _v4_global(_v4_scope, 'datetime').combine(selected, start_time, tzinfo=_v4_global(_v4_scope, 'US_TZ')),
        _v4_global(_v4_scope, 'datetime').combine(selected, end_time, tzinfo=_v4_global(_v4_scope, 'US_TZ')),
    )


def _resolve_capture_for_shanghai_slot_body(_v4_scope, /, business_date, slot):
    """Resolve a fixed Shanghai scheduler slot to an explicit US phase.

    The scheduler keeps one slot for each possible daylight-saving offset.  We
    resolve the instant through ``America/New_York`` instead of hard-coding a
    seasonal month table.  A slot that is not the active five-minute capture
    window fails closed so a second seasonal slot cannot create a duplicate
    capture or be mistaken for a market-day decision.
    """
    selected = _v4_global(_v4_scope, '_session_date')(business_date)
    if not _v4_global(_v4_scope, 'isinstance')(slot, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, 'len')(slot) != 4 or not slot.isdigit():
        raise _v4_global(_v4_scope, 'ValueError')("US_CAPTURE_SLOT_INVALID")
    hour, minute = _v4_global(_v4_scope, 'int')(slot[:2]), _v4_global(_v4_scope, 'int')(slot[2:])
    if hour > 23 or minute > 59:
        raise _v4_global(_v4_scope, 'ValueError')("US_CAPTURE_SLOT_INVALID")
    shanghai_instant = _v4_global(_v4_scope, 'datetime').combine(
        selected,
        _v4_global(_v4_scope, 'time')(hour, minute),
        tzinfo=_v4_global(_v4_scope, 'SHANGHAI_TZ'),
    )
    us_instant = shanghai_instant.astimezone(_v4_global(_v4_scope, 'US_TZ'))
    us_session_date = us_instant.date().strftime("%Y%m%d")
    for phase in _v4_global(_v4_scope, 'US_CAPTURE_PHASES'):
        start, end = _v4_global(_v4_scope, 'us_capture_window')(us_session_date, phase)
        if start <= us_instant < end:
            return {
                "capture_phase": phase,
                "us_session_date": us_session_date,
            }
    raise _v4_global(_v4_scope, 'ValueError')("US_CAPTURE_SLOT_NOT_DUE")


def _us_post_close_recovery_window_body(_v4_scope, /, us_session_date):
    """Return the 24-hour recovery bound for one POST_CLOSE session."""
    natural_start, _ = _v4_global(_v4_scope, 'us_capture_window')(_v4_global(_v4_scope, 'str')(us_session_date), "POST_CLOSE")
    return natural_start, natural_start + _v4_global(_v4_scope, 'LATE_POST_CLOSE_MAX_AGE')


def __validate_late_post_close_window_body(_v4_scope, /, us_session_date, *, now):
    """Validate the current New York instant for a late reuse or capture.

    Reuse is a read-only idempotency operation.  It must be admitted only for
    the requested US session while the bounded recovery window is open, but it
    must not require the caller's old capture timestamp to equal the current
    second.  The stricter timestamp check remains in
    ``_validate_late_post_close_context`` for a new network capture.
    """
    session_date = _v4_global(_v4_scope, '_date')(us_session_date)
    natural_start, recovery_end = _v4_global(_v4_scope, 'us_post_close_recovery_window')(session_date)
    now_local = _v4_global(_v4_scope, '_capture_now')(now)
    from contracts.us_equity_calendar import latest_completed_session

    try:
        latest = latest_completed_session(now_local)
    except ValueError as error:
        raise _v4_global(_v4_scope, 'ValueError')(f"US_LATE_POST_CLOSE_SESSION_RESOLUTION_FAILED:{error}") from error
    if latest.session_date != session_date:
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_NOT_LATEST_COMPLETED_SESSION")
    if now_local < natural_start:
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_NOT_YET_DUE")
    if now_local >= recovery_end:
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_RECOVERY_WINDOW_EXPIRED")
    return now_local, natural_start, recovery_end


def __validate_late_post_close_context_body(_v4_scope, /, us_session_date, *, captured_at, now):
    """Validate and return ``(now_local, capture_local, recovery_end)``.

    ``now`` is an internal clock seam for deterministic tests.  Production
    callers leave it unset, so the check always uses the real New York clock.
    The captured timestamp must be the current capture instant at
    second-resolution; accepting an earlier timestamp would silently turn a
    late replay into a fabricated in-window observation.
    """
    session_date = _v4_global(_v4_scope, '_date')(us_session_date)
    now_local, natural_start, recovery_end = _v4_global(_v4_scope, '_validate_late_post_close_window')(
        session_date,
        now=now,
    )
    capture_timestamp = _v4_global(_v4_scope, '_parse_capture_timestamp')(captured_at)
    capture_local = capture_timestamp.astimezone(_v4_global(_v4_scope, 'US_TZ')).replace(microsecond=0)
    if not (natural_start <= capture_local < recovery_end):
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_CAPTURE_OUTSIDE_RECOVERY_WINDOW")
    if capture_local.utcoffset() != natural_start.utcoffset():
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_CAPTURE_TIMEZONE_MISMATCH")
    if capture_local > now_local:
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_CAPTURE_IN_FUTURE")
    if capture_local != now_local:
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_CAPTURE_TIMESTAMP_NOT_CURRENT")
    return now_local, capture_local, recovery_end
