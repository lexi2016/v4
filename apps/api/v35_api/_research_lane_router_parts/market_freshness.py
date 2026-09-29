"""apps.api.v35_api.research_lane_router: market_freshness (review candidate, not deployment)."""
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
            recovery_end = _v4_global(_v4_scope, 'datetime').combine(session, _v4_global(_v4_scope, 'time')(20), tzinfo=ny_zone)
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
        else:
            diagnostic["state"] = "RECENT_BOUND_CAPTURE"
            # Preserve PARTIAL and all provider/session conflicts.  Calendar
            # verification never upgrades data quality by itself.
            result["display_status"] = projection["status"]
            if _v4_global(_v4_scope, 'len')(projection.get("provider_session_times") or []) != 1:
                result["display_status"] = "PARTIAL"
                diagnostic["cannot_confirm"] = ["QUOTE_SESSION_TIME_MIXED_OR_MISSING"]
    except (_v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'KeyError')) as error:
        diagnostic["state"] = "CANNOT_CONFIRM"
        diagnostic["cannot_confirm"] = [_v4_global(_v4_scope, 'str')(error)]
        result["display_status"] = "CANNOT_CONFIRM"
    return result
