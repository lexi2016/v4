"""apps.api.v4_api.research_lane_router: market_freshness (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __verifiable_market_snapshot_dates_body(_v4_scope, /, store):
    """List exact external-finance dates with a verifiable close snapshot."""

    eligible: list[str] = []
    for trade_date in store.list_dates("external_finance"):
        projection = _v4_global(_v4_scope, '_project_global_industries')(
            store=store,
            research_date=trade_date,
        )
        if _v4_global(_v4_scope, '_is_verifiable_close_snapshot')(projection):
            eligible.append(trade_date)
    return _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(eligible), reverse=True)


def __futu_board_freshness_error_body(
    _v4_scope, /, projection, *, source_date, captured_at, ny_zone,
):
    """Validate the official Futu rows used by the industry projection.

    The industry API intentionally leaves legacy ETF/basket observations in
    ``proxy_quotes`` and exposes no raw values in ``quotes``.  Freshness must
    therefore bind the official board snapshot and its per-board timestamps;
    proxy quote validation belongs to a different contract.
    """
    from contracts.us_equity_calendar import session as us_equity_session
    from ops._us_market_digest_parts.futu_boards import FUTU_BOARD_MAP

    metadata = projection.get("futu_board_snapshot")
    if not _v4_global(_v4_scope, 'isinstance')(metadata, _v4_global(_v4_scope, 'Mapping')):
        return "FUTU_BOARD_SNAPSHOT_MISSING"
    if any(metadata.get(key) != value for key, value in {
        "schema_version": "v3_5.futu_us_industry_snapshot.v1",
        "status": projection.get("status"),
        "provider": "Futu OpenD",
        "market": "US",
        "timezone": "America/New_York",
        "capture_session_date": source_date,
    }.items()):
        return "FUTU_BOARD_SNAPSHOT_IDENTITY_INVALID"

    digest = metadata.get("source_response_sha256")
    if (
        not _v4_global(_v4_scope, 'isinstance')(digest, _v4_global(_v4_scope, 'str'))
        or _v4_global(_v4_scope, 'len')(digest) != 64
        or _v4_global(_v4_scope, 'any')(character not in "0123456789abcdef" for character in digest)
        or projection.get("source_response_sha256") != digest
    ):
        return "FUTU_BOARD_SNAPSHOT_SOURCE_HASH_INVALID"

    rows = projection.get("rows")
    if (
        not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list'))
        or _v4_global(_v4_scope, 'len')(rows) != _v4_global(_v4_scope, 'len')(FUTU_BOARD_MAP)
        or [row.get("label") for row in rows if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping'))]
        != [mapping["label"] for mapping in FUTU_BOARD_MAP]
    ):
        return "FUTU_BOARD_SNAPSHOT_ROWS_INVALID"

    calendar_session = us_equity_session(source_date)
    if calendar_session.close_at is None:
        return "FUTU_BOARD_SOURCE_SESSION_NOT_OPEN"

    ready_count = 0
    update_times: set[str] = set()
    for row in rows:
        board = row.get("official_board")
        if not _v4_global(_v4_scope, 'isinstance')(board, _v4_global(_v4_scope, 'Mapping')):
            return "FUTU_BOARD_ROW_INVALID"
        row_status = row.get("status")
        if row_status != board.get("status"):
            return "FUTU_BOARD_ROW_STATUS_MISMATCH"
        if row_status != "READY":
            if row.get("change_pct") is not None or board.get("change_pct") is not None:
                return "FUTU_UNCONFIRMED_BOARD_HAS_CHANGE"
            continue

        if (
            board.get("metric_kind") != "OFFICIAL_BOARD"
            or board.get("market") != "US"
            or board.get("timezone") != "America/New_York"
            or board.get("plate_valid") is not True
            or board.get("session_date") != source_date
            or row.get("quote_session_dates") != [source_date]
        ):
            return "FUTU_BOARD_READY_ROW_IDENTITY_INVALID"
        raw_update_time = board.get("update_time")
        if not _v4_global(_v4_scope, 'isinstance')(raw_update_time, _v4_global(_v4_scope, 'str')):
            return "FUTU_BOARD_UPDATE_TIME_MISSING"
        try:
            update_at = _v4_global(_v4_scope, 'datetime').strptime(
                raw_update_time, "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=ny_zone)
        except _v4_global(_v4_scope, 'ValueError'):
            return "FUTU_BOARD_UPDATE_TIME_INVALID"
        if raw_update_time[:10] != source_date[:4] + "-" + source_date[4:6] + "-" + source_date[6:]:
            return "FUTU_BOARD_UPDATE_DATE_MISMATCH"
        if update_at < calendar_session.close_at:
            return "FUTU_BOARD_UPDATE_BEFORE_SESSION_CLOSE"
        if update_at > captured_at:
            return "FUTU_BOARD_UPDATE_AFTER_CAPTURE"
        ready_count += 1
        update_times.add(raw_update_time)

    expected_status = "READY" if ready_count == len(FUTU_BOARD_MAP) else "PARTIAL" if ready_count else "CANNOT_CONFIRM"
    if (
        metadata.get("status") != expected_status
        or projection.get("status") != expected_status
        or type(projection.get("requested_board_count")) is not int
        or projection.get("requested_board_count") != len(FUTU_BOARD_MAP)
        or type(projection.get("available_board_count")) is not int
        or projection.get("available_board_count") != ready_count
        or projection.get("provider_session_dates") != ([source_date] if ready_count else [])
        or projection.get("provider_session_times") != sorted(update_times)
    ):
        return "FUTU_BOARD_SNAPSHOT_COUNT_OR_SESSION_MISMATCH"
    return None


def __futu_native_board_freshness_error_body(
    _v4_scope, /, projection, *, source_date, captured_at, ny_zone,
):
    """Keep native-board freshness bound to its own frozen registry and session."""
    snapshot = projection.get("native_board_snapshot")
    if snapshot is None:
        return None
    if not _v4_global(_v4_scope, 'isinstance')(snapshot, _v4_global(_v4_scope, 'Mapping')):
        return "FUTU_NATIVE_BOARD_SNAPSHOT_INVALID"
    from contracts.futu_us_boards import validate_futu_us_board_snapshot
    try:
        checked = validate_futu_us_board_snapshot(snapshot, expected_session_date=source_date)
    except (TypeError, ValueError):
        return "FUTU_NATIVE_BOARD_SNAPSHOT_INVALID"
    digest = checked.get("source_response_sha256")
    if (
        not _v4_global(_v4_scope, 'isinstance')(digest, _v4_global(_v4_scope, 'str'))
        or _v4_global(_v4_scope, 'len')(digest) != 64
        or _v4_global(_v4_scope, 'any')(character not in "0123456789abcdef" for character in digest)
    ):
        return "FUTU_NATIVE_BOARD_SOURCE_HASH_INVALID"
    from contracts.us_equity_calendar import session as us_equity_session
    calendar_session = us_equity_session(source_date)
    if calendar_session.close_at is None:
        return "FUTU_NATIVE_BOARD_SOURCE_SESSION_NOT_OPEN"
    for row in checked["rows"]:
        if row.get("status") != "READY":
            continue
        raw_update_time = row.get("update_time")
        if not _v4_global(_v4_scope, 'isinstance')(raw_update_time, _v4_global(_v4_scope, 'str')):
            return "FUTU_NATIVE_BOARD_UPDATE_TIME_MISSING"
        try:
            update_at = _v4_global(_v4_scope, 'datetime').strptime(
                raw_update_time, "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=ny_zone)
        except _v4_global(_v4_scope, 'ValueError'):
            return "FUTU_NATIVE_BOARD_UPDATE_TIME_INVALID"
        if raw_update_time[:10].replace("-", "") != source_date:
            return "FUTU_NATIVE_BOARD_UPDATE_DATE_MISMATCH"
        if update_at < calendar_session.close_at:
            return "FUTU_NATIVE_BOARD_UPDATE_BEFORE_SESSION_CLOSE"
        if update_at > captured_at:
            return "FUTU_NATIVE_BOARD_UPDATE_AFTER_CAPTURE"
    return None


def __with_us_market_freshness_body(_v4_scope, /, projection, *, observed):
    """Separate stored quality from read-time freshness using the owned 2026 NYSE calendar.

    This remains read-only and keeps the existing capture-window, provider-date,
    raw-response, receipt and manifest checks.  Calendar certification only
    determines which completed US session may be called current.
    """
    result = _v4_global(_v4_scope, 'dict')(projection)
    diagnostic: dict[str, Any] = {
        "state": "CANNOT_CONFIRM",
        "observed_at": observed.isoformat(),
        "captured_at": projection.get("captured_at") or "",
        "source_date": projection.get("source_date") or "",
        "basis": "BOUND_PROVIDER_SESSION_AND_OFFICIAL_NYSE_2026_CALENDAR",
        "exchange_calendar_status": "CANNOT_CONFIRM",
        "latest_exchange_session_verified": False,
        "new_capture_performed": False,
        "cannot_confirm": [],
    }
    result.update(display_status="CANNOT_CONFIRM", freshness=diagnostic)
    result["native_display_status"] = (
        "CANNOT_CONFIRM" if result.get("native_board_snapshot") is not None else None
    )
    if result.get("native_board_snapshot") is not None:
        result["native_freshness"] = {
            "state": "CANNOT_CONFIRM",
            "cannot_confirm": ["VERIFIABLE_CLOSE_SNAPSHOT_REQUIRED"],
        }
    if not _v4_global(_v4_scope, '_is_verifiable_close_snapshot')(projection):
        diagnostic["cannot_confirm"] = ["VERIFIABLE_CLOSE_SNAPSHOT_REQUIRED"]
        return result

    def timestamp(value: Any) -> datetime:
        if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value:
            raise _v4_global(_v4_scope, 'ValueError')("CAPTURE_TIMESTAMP_MISSING")
        try:
            parsed = _v4_global(_v4_scope, 'datetime').fromisoformat(value.replace("Z", "+00:00"))
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'ValueError')("CAPTURE_TIMESTAMP_INVALID") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise _v4_global(_v4_scope, 'ValueError')("CAPTURE_TIMESTAMP_TIMEZONE_REQUIRED")
        return parsed

    try:
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise _v4_global(_v4_scope, 'ValueError')("OBSERVATION_TIMEZONE_REQUIRED")
        from contracts.us_equity_calendar import latest_completed_session
        ny_zone = _v4_global(_v4_scope, 'ZoneInfo')("America/New_York")
        official_latest = latest_completed_session(observed)
        session = _v4_global(_v4_scope, 'datetime').strptime(_v4_global(_v4_scope, 'str')(projection["source_date"]), "%Y%m%d").date()
        captured = timestamp(projection.get("captured_at"))
        bound = timestamp(projection.get("bound_capture_captured_at"))
        generated = timestamp(projection.get("generated_at"))
        if captured != bound:
            raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_CAPTURE_TIME_BINDING_MISMATCH")
        if captured > observed or generated > observed or generated < captured:
            raise _v4_global(_v4_scope, 'ValueError')("SNAPSHOT_CAPTURE_OR_GENERATION_TIME_INVALID")
        start = _v4_global(_v4_scope, 'datetime').combine(session, _v4_global(_v4_scope, 'time')(16, 15), tzinfo=ny_zone)
        end = _v4_global(_v4_scope, 'datetime').combine(session, _v4_global(_v4_scope, 'time')(16, 20), tzinfo=ny_zone)
        if (timestamp(projection.get("capture_window_start")) != start
                or timestamp(projection.get("capture_window_end")) != end):
            raise _v4_global(_v4_scope, 'ValueError')("CAPTURE_WINDOW_BINDING_MISMATCH")
        if _v4_global(_v4_scope, '_is_late_capture_identity')(projection):
            recovery_end = start + _v4_global(_v4_scope, 'timedelta')(hours=24)
            if (projection.get("late") is not True
                    or projection.get("capture_mode") != _v4_global(_v4_scope, 'LATE_CAPTURE_MODE')
                    or timestamp(projection.get("allowed_recovery_window_start")) != start
                    or timestamp(projection.get("allowed_recovery_window_end")) != recovery_end):
                raise _v4_global(_v4_scope, 'ValueError')("LATE_CAPTURE_WINDOW_BINDING_MISMATCH")
            end = recovery_end
        if not start <= captured < end:
            raise _v4_global(_v4_scope, 'ValueError')("CAPTURE_OUTSIDE_ORIGINAL_BOUND_WINDOW")
        latest_date = _v4_global(_v4_scope, 'datetime').strptime(official_latest.session_date, "%Y%m%d").date()
        diagnostic.update(
            latest_exchange_session=official_latest.session_date,
            latest_scheduled_capture_date=official_latest.session_date,
            expected_session_close_at=(official_latest.close_at.isoformat() if official_latest.close_at else None),
            exchange_calendar_source_url=official_latest.source_url,
            exchange_calendar_status="VERIFIED_NYSE_2026",
            latest_exchange_session_verified=True,
            capture_age_seconds=(observed - captured).total_seconds(),
        )
        if session > latest_date:
            raise _v4_global(_v4_scope, 'ValueError')("SOURCE_AFTER_LATEST_COMPLETED_EXCHANGE_SESSION")
        if session < latest_date:
            diagnostic.update(state="STALE_EXCHANGE_SESSION", cannot_confirm=[
                "SOURCE_OLDER_THAN_LATEST_COMPLETED_EXCHANGE_SESSION"])
            result["display_status"] = "STALE"
            if result.get("native_board_snapshot") is not None:
                result["native_display_status"] = "STALE"
                result["native_freshness"] = {
                    "state": "STALE_EXCHANGE_SESSION",
                    "cannot_confirm": ["SOURCE_OLDER_THAN_LATEST_COMPLETED_EXCHANGE_SESSION"],
                }
        else:
            diagnostic["state"] = "RECENT_BOUND_CAPTURE"
            # Preserve PARTIAL and all provider/session conflicts.  Calendar
            # verification never upgrades data quality by itself.
            result["display_status"] = projection["status"]
            futu_error = __futu_board_freshness_error_body(
                _v4_scope,
                projection,
                source_date=projection.get("source_date"),
                captured_at=captured,
                ny_zone=ny_zone,
            )
            if futu_error:
                result["display_status"] = "CANNOT_CONFIRM"
                diagnostic["state"] = "CANNOT_CONFIRM"
                diagnostic["cannot_confirm"] = [futu_error]
            if result.get("native_board_snapshot") is not None:
                native_error = __futu_native_board_freshness_error_body(
                    _v4_scope,
                    projection,
                    source_date=projection.get("source_date"),
                    captured_at=captured,
                    ny_zone=ny_zone,
                )
                if native_error:
                    result["native_display_status"] = "CANNOT_CONFIRM"
                    result["native_freshness"] = {
                        "state": "CANNOT_CONFIRM",
                        "cannot_confirm": [native_error],
                    }
                else:
                    result["native_display_status"] = result["native_board_snapshot"].get("status")
                    result["native_freshness"] = {
                        "state": "RECENT_BOUND_CAPTURE",
                        "cannot_confirm": [],
                    }

    except (_v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'KeyError')) as error:
        diagnostic["state"] = "CANNOT_CONFIRM"
        diagnostic["cannot_confirm"] = [_v4_global(_v4_scope, 'str')(error)]
        result["display_status"] = "CANNOT_CONFIRM"
        if result.get("native_board_snapshot") is not None:
            result["native_display_status"] = "CANNOT_CONFIRM"
            result["native_freshness"] = {
                "state": "CANNOT_CONFIRM",
                "cannot_confirm": [_v4_global(_v4_scope, 'str')(error)],
            }
    return result
