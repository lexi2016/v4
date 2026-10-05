"""ops.us_market_digest: capture_metadata (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __parse_capture_timestamp_body(_v4_scope, /, value):
    if value is None:
        raise _v4_global(_v4_scope, 'ValueError')("US_CAPTURE_TIMESTAMP_REQUIRED")
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'datetime')):
        parsed = value
    elif _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')):
        try:
            parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(value.replace("Z", "+00:00"))
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'ValueError')("US_CAPTURE_TIMESTAMP_INVALID") from error
    else:
        raise _v4_global(_v4_scope, 'ValueError')("US_CAPTURE_TIMESTAMP_INVALID")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _v4_global(_v4_scope, 'ValueError')("US_CAPTURE_TIMESTAMP_INVALID")
    return parsed


def _build_capture_metadata_body(_v4_scope, /, us_session_date, capture_phase, *, captured_at, capture_id, run_id, capture_origin, original_time_capture, allow_late_post_close, now):
    """Build the explicit identity carried by every US capture."""
    normalized_date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(us_session_date))
    normalized_phase = _v4_global(_v4_scope, '_phase')(capture_phase)
    start, end = _v4_global(_v4_scope, 'us_capture_window')(normalized_date, normalized_phase)
    if _v4_global(_v4_scope, 'type')(allow_late_post_close) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("allow_late_post_close must be boolean")
    if allow_late_post_close and normalized_phase != "POST_CLOSE":
        raise _v4_global(_v4_scope, 'ValueError')("US_LATE_POST_CLOSE_ONLY")
    if original_time_capture is not None and _v4_global(_v4_scope, 'type')(original_time_capture) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("original_time_capture must be boolean")
    is_original = (
        normalized_phase in _v4_global(_v4_scope, 'US_CAPTURE_PHASES')
        if original_time_capture is None
        else _v4_global(_v4_scope, 'bool')(original_time_capture)
    )
    origin = capture_origin or (
        _v4_global(_v4_scope, 'ORIGINAL_TIME_CAPTURE') if is_original else _v4_global(_v4_scope, 'HISTORICAL_BACKFILL')
    )
    if origin not in {_v4_global(_v4_scope, 'ORIGINAL_TIME_CAPTURE'), _v4_global(_v4_scope, 'HISTORICAL_BACKFILL'), _v4_global(_v4_scope, 'MANUAL_RECOVERY'), _v4_global(_v4_scope, 'MIXED_CAPTURE')}:
        raise _v4_global(_v4_scope, 'ValueError')("unsupported capture_origin")
    if normalized_phase == _v4_global(_v4_scope, 'HISTORICAL_BACKFILL_PHASE') and (
        origin != _v4_global(_v4_scope, 'HISTORICAL_BACKFILL') or is_original
    ):
        raise _v4_global(_v4_scope, 'ValueError')("historical backfill must be explicitly non-original-time")
    if normalized_phase in _v4_global(_v4_scope, 'US_CAPTURE_PHASES'):
        manual_late = (
            allow_late_post_close
            and origin == _v4_global(_v4_scope, 'MANUAL_RECOVERY')
            and not is_original
        )
        if not manual_late and (
            origin != _v4_global(_v4_scope, 'ORIGINAL_TIME_CAPTURE') or not is_original
        ):
            raise _v4_global(_v4_scope, 'ValueError')("live capture must be explicitly original-time")
    captured_timestamp = _v4_global(_v4_scope, '_parse_capture_timestamp')(captured_at)
    if normalized_phase in _v4_global(_v4_scope, 'US_CAPTURE_PHASES'):
        local_capture = captured_timestamp.astimezone(_v4_global(_v4_scope, 'US_TZ'))
        if allow_late_post_close:
            _v4_global(_v4_scope, '_validate_late_post_close_context')(
                normalized_date,
                captured_at=captured_timestamp,
                now=now,
            )
        elif not (start <= local_capture < end) or local_capture.utcoffset() != start.utcoffset():
            raise _v4_global(_v4_scope, 'ValueError')("US_CAPTURE_OUTSIDE_WINDOW")
    captured_iso = _v4_global(_v4_scope, 'isoformat_utc')(captured_timestamp)
    default_capture_id = (
        _v4_global(_v4_scope, '_late_post_close_capture_id')(normalized_date, captured_timestamp)
        if allow_late_post_close
        else _v4_global(_v4_scope, '_deterministic_capture_id')(normalized_date, normalized_phase)
    )
    normalized_capture_id = _v4_global(_v4_scope, 'str')(capture_id or "").strip() or default_capture_id
    normalized_run_id = _v4_global(_v4_scope, 'str')(run_id or "").strip() or f"us-rss:{normalized_date}:{normalized_phase}:{normalized_capture_id}"
    metadata = {
        "us_session_date": normalized_date,
        "capture_phase": normalized_phase,
        "session_timezone": _v4_global(_v4_scope, 'US_SESSION_TIMEZONE'),
        "capture_window_start": start.isoformat(),
        "capture_window_end": end.isoformat(),
        "capture_id": normalized_capture_id,
        "run_id": normalized_run_id,
        "captured_at": captured_iso,
        "capture_origin": origin,
        "original_time_capture": is_original,
    }
    if allow_late_post_close:
        recovery_start, recovery_end = _v4_global(_v4_scope, 'us_post_close_recovery_window')(normalized_date)
        late_reason = (
            _v4_global(_v4_scope, 'MANUAL_LATE_POST_CLOSE_CAPTURE_REASON')
            if origin == _v4_global(_v4_scope, 'MANUAL_RECOVERY')
            else _v4_global(_v4_scope, 'LATE_POST_CLOSE_CAPTURE_REASON')
        )
        metadata.update(
            {
                "capture_mode": _v4_global(_v4_scope, 'LATE_POST_CLOSE_CAPTURE_MODE'),
                "reason": late_reason,
                "capture_reason": late_reason,
                "late": True,
                "natural_capture_window_start": start.isoformat(),
                "natural_capture_window_end": end.isoformat(),
                "allowed_recovery_window_start": recovery_start.isoformat(),
                "allowed_recovery_window_end": recovery_end.isoformat(),
            }
        )
    return metadata
