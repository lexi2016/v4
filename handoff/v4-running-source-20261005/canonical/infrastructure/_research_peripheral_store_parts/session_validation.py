"""infrastructure.research_peripheral_store: session_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_us_session_captures_body(_v4_scope, /, value):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral us_session_captures")
    captures: list[dict[str, Any]] = []
    seen_ids: set[str] = _v4_global(_v4_scope, 'set')()
    required = {
        "us_session_date",
        "capture_phase",
        "session_timezone",
        "capture_window_start",
        "capture_window_end",
        "capture_id",
        "run_id",
        "captured_at",
        "capture_origin",
        "original_time_capture",
    }
    for value_row in value:
        if not _v4_global(_v4_scope, 'isinstance')(value_row, _v4_global(_v4_scope, 'Mapping')) or not required.issubset(value_row):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral capture fields")
        row = _v4_global(_v4_scope, 'dict')(value_row)
        us_session_date = row.get("us_session_date")
        try:
            _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(us_session_date))
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral us_session_date") from error
        if row.get("capture_phase") not in _v4_global(_v4_scope, '_CAPTURE_PHASES'):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral capture_phase")
        if row.get("session_timezone") != "America/New_York":
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral session_timezone must be America/New_York")
        _v4_global(_v4_scope, '_aware_timestamp')(row.get("capture_window_start"), "capture_window_start")
        _v4_global(_v4_scope, '_aware_timestamp')(row.get("capture_window_end"), "capture_window_end")
        captured_at = _v4_global(_v4_scope, '_parse_aware_timestamp')(row.get("captured_at"), "captured_at")
        start = _v4_global(_v4_scope, 'datetime').fromisoformat(_v4_global(_v4_scope, 'str')(row["capture_window_start"]).replace("Z", "+00:00"))
        end = _v4_global(_v4_scope, 'datetime').fromisoformat(_v4_global(_v4_scope, 'str')(row["capture_window_end"]).replace("Z", "+00:00"))
        if end <= start:
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral capture window must be increasing")
        session_day = _v4_global(_v4_scope, 'datetime').strptime(_v4_global(_v4_scope, 'str')(us_session_date), "%Y%m%d").date()
        phase = row["capture_phase"]
        if phase == "PRE_OPEN":
            expected_start = _v4_global(_v4_scope, 'datetime').combine(session_day, _v4_global(_v4_scope, 'time')(9, 0), tzinfo=_v4_global(_v4_scope, '_US_SESSION_TZ'))
            expected_end = _v4_global(_v4_scope, 'datetime').combine(session_day, _v4_global(_v4_scope, 'time')(9, 5), tzinfo=_v4_global(_v4_scope, '_US_SESSION_TZ'))
        elif phase == "POST_CLOSE":
            expected_start = _v4_global(_v4_scope, 'datetime').combine(session_day, _v4_global(_v4_scope, 'time')(16, 15), tzinfo=_v4_global(_v4_scope, '_US_SESSION_TZ'))
            expected_end = _v4_global(_v4_scope, 'datetime').combine(session_day, _v4_global(_v4_scope, 'time')(16, 20), tzinfo=_v4_global(_v4_scope, '_US_SESSION_TZ'))
        else:
            expected_start = _v4_global(_v4_scope, 'datetime').combine(session_day, _v4_global(_v4_scope, 'time').min, tzinfo=_v4_global(_v4_scope, '_US_SESSION_TZ'))
            expected_end = _v4_global(_v4_scope, 'datetime').combine(session_day + _v4_global(_v4_scope, 'timedelta')(days=1), _v4_global(_v4_scope, 'time').min, tzinfo=_v4_global(_v4_scope, '_US_SESSION_TZ'))
        if start.astimezone(_v4_global(_v4_scope, '_US_SESSION_TZ')) != expected_start or end.astimezone(_v4_global(_v4_scope, '_US_SESSION_TZ')) != expected_end:
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral capture window timezone or phase mismatch")
        late = row.get("late", False)
        if _v4_global(_v4_scope, 'type')(late) is not _v4_global(_v4_scope, 'bool'):
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral late must be boolean")
        capture_origin = row.get("capture_origin")
        manual_late = capture_origin == "MANUAL_RECOVERY"
        if not late and row.get("capture_mode") == _v4_global(_v4_scope, '_LATE_CAPTURE_MODE'):
            raise _v4_global(_v4_scope, 'ValueError')("late capture mode requires late identity")
        if phase in {"PRE_OPEN", "POST_CLOSE"}:
            local_capture = captured_at.astimezone(_v4_global(_v4_scope, '_US_SESSION_TZ'))
            if late:
                if phase != "POST_CLOSE":
                    raise _v4_global(_v4_scope, 'ValueError')("late capture must be POST_CLOSE")
                if row.get("capture_mode") != _v4_global(_v4_scope, '_LATE_CAPTURE_MODE'):
                    raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral late capture_mode")
                expected_late_reason = (
                    _v4_global(_v4_scope, '_MANUAL_LATE_CAPTURE_REASON')
                    if manual_late
                    else _v4_global(_v4_scope, '_LATE_CAPTURE_REASON')
                )
                if row.get("reason") != expected_late_reason:
                    raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral late capture reason")
                if row.get("capture_reason") not in (None, expected_late_reason):
                    raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral late capture_reason")
                for field in (
                    "natural_capture_window_start",
                    "natural_capture_window_end",
                    "allowed_recovery_window_start",
                    "allowed_recovery_window_end",
                ):
                    _v4_global(_v4_scope, '_aware_timestamp')(row.get(field), field)
                natural_start = _v4_global(_v4_scope, '_parse_aware_timestamp')(
                    row["natural_capture_window_start"],
                    "natural_capture_window_start",
                )
                natural_end = _v4_global(_v4_scope, '_parse_aware_timestamp')(
                    row["natural_capture_window_end"],
                    "natural_capture_window_end",
                )
                allowed_start = _v4_global(_v4_scope, '_parse_aware_timestamp')(
                    row["allowed_recovery_window_start"],
                    "allowed_recovery_window_start",
                )
                allowed_end = _v4_global(_v4_scope, '_parse_aware_timestamp')(
                    row["allowed_recovery_window_end"],
                    "allowed_recovery_window_end",
                )
                if natural_start != expected_start or natural_end != expected_end:
                    raise _v4_global(_v4_scope, 'ValueError')("late capture natural window mismatch")
                expected_recovery_end = expected_start + _v4_global(_v4_scope, '_LATE_RECOVERY_MAX_AGE')
                if (
                    allowed_start != expected_start
                    or allowed_end != expected_recovery_end
                    or allowed_end <= allowed_start
                ):
                    raise _v4_global(_v4_scope, 'ValueError')("late capture recovery window mismatch")
                if not (
                    allowed_start <= local_capture < allowed_end
                    and local_capture.utcoffset() == expected_start.utcoffset()
                ):
                    raise _v4_global(_v4_scope, 'ValueError')("research peripheral late captured_at outside recovery window")
                if manual_late:
                    from contracts.us_equity_calendar import latest_completed_session

                    try:
                        latest_session = latest_completed_session(captured_at)
                    except ValueError as error:
                        raise _v4_global(_v4_scope, 'ValueError')("manual recovery session resolution failed") from error
                    if latest_session.session_date != us_session_date:
                        raise _v4_global(_v4_scope, 'ValueError')("manual recovery is not the latest completed US session")
            elif not (
                expected_start <= local_capture < expected_end
                and local_capture.utcoffset() == expected_start.utcoffset()
            ):
                raise _v4_global(_v4_scope, 'ValueError')("research peripheral captured_at outside capture window")
        capture_id = row.get("capture_id")
        run_id = row.get("run_id")
        if not _v4_global(_v4_scope, 'isinstance')(capture_id, _v4_global(_v4_scope, 'str')) or not capture_id.strip():
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral capture_id is missing")
        if capture_id in seen_ids:
            raise _v4_global(_v4_scope, 'ValueError')("duplicate research peripheral capture_id")
        seen_ids.add(capture_id)
        if not _v4_global(_v4_scope, 'isinstance')(run_id, _v4_global(_v4_scope, 'str')) or not run_id.strip():
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral run_id is missing")
        if capture_origin not in _v4_global(_v4_scope, '_CAPTURE_ORIGINS'):
            raise _v4_global(_v4_scope, 'ValueError')("invalid research peripheral capture_origin")
        if _v4_global(_v4_scope, 'type')(row.get("original_time_capture")) is not _v4_global(_v4_scope, 'bool'):
            raise _v4_global(_v4_scope, 'ValueError')("research peripheral original_time_capture must be boolean")
        if row.get("capture_phase") == "HISTORICAL_BACKFILL":
            if capture_origin != "HISTORICAL_BACKFILL" or row.get("original_time_capture") is not False:
                raise _v4_global(_v4_scope, 'ValueError')("historical backfill capture identity is unsafe")
        elif manual_late:
            if not late or row.get("original_time_capture") is not False:
                raise _v4_global(_v4_scope, 'ValueError')("manual recovery capture identity is unsafe")
        elif capture_origin != "ORIGINAL_TIME_CAPTURE" or row.get("original_time_capture") is not True:
            raise _v4_global(_v4_scope, 'ValueError')("live capture identity is unsafe")
        captures.append(row)
    return captures
