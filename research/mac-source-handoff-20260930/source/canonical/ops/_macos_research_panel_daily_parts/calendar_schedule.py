"""ops.macos_research_panel_daily: calendar_schedule (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __scheduled_day_is_cross_market_trading_day_body(_v4_scope, /, target_date):
    """Return whether an implicit daily run may collect both panel lanes.

    An omitted ``--date`` is the launchd path.  It must be fail-closed when
    launchd coalesces a missed weekday run onto a weekend or an exchange
    holiday; an explicit date remains a deliberate, testable replay request.
    The calendar is loaded from this source tree, never inferred from the
    weekday alone.
    """
    try:
        from contracts.trading_calendar import (
            TradingDayState,
            load_market_calendar,
            resolve_market_states,
        )

        calendar = load_market_calendar(_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, '__file__')).resolve().parents[1] / "contracts" / "market_calendar_2026.json")
        states = resolve_market_states(calendar, _v4_global(_v4_scope, '_date')(target_date))
    except _v4_global(_v4_scope, 'Exception'):
        return False
    return _v4_global(_v4_scope, 'all')(
        states.get(market) in {
            TradingDayState.FULL_TRADING_DAY,
            TradingDayState.HALF_TRADING_DAY_AM,
        }
        for market in ("a_share", "hk_securities")
    )


def __non_trading_day_result_body(_v4_scope, /, target_date, receipt_root, *, lane):
    """Emit explicit no-op receipts for an implicit non-trading-day launch."""
    target_date = _v4_global(_v4_scope, '_date')(target_date)
    requested_lane = _v4_global(_v4_scope, '_normalize_lane')(lane)
    requested = {"A", "HK"} if requested_lane == "ALL" else {requested_lane}
    lanes = {
        lane: _v4_global(_v4_scope, '_receipt')(
            _v4_global(_v4_scope, 'Path')(receipt_root),
            lane,
            target_date,
            {
                "status": "NON_TRADING_DAY",
                "reason_code": "IMPLICIT_DATE_NOT_CROSS_MARKET_TRADING_DAY",
                "coverage_rate": 0.0,
                "row_count": 0,
                "sha256": "",
                "runner_called": False,
            },
        )
        for lane in requested
    }
    lanes.update({name: _v4_global(_v4_scope, '_not_requested_lane')() for name in {"A", "HK"} - requested})
    return {
        "schema_version": "v3.macos.research_panel_daily.v1",
        "target_date": target_date,
        "requested_lane": requested_lane,
        "overall_status": "NON_TRADING_DAY",
        "lanes": lanes,
        "runner_called": False,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }


def _run_scheduled_lanes_body(_v4_scope, /, *, target_date, receipt_root, a_runner, hk_runner, lane):
    """Run launchd's implicit date only on a proven A/H business day.

    Callers that supply ``target_date`` retain the existing explicit replay
    semantics, including the ability to diagnose a holiday snapshot.
    """
    explicit_date = target_date is not None
    resolved = _v4_global(_v4_scope, '_date')(target_date if explicit_date else _v4_global(_v4_scope, '_today_shanghai')())
    if not explicit_date and not _v4_global(_v4_scope, '_scheduled_day_is_cross_market_trading_day')(resolved):
        return _v4_global(_v4_scope, '_non_trading_day_result')(resolved, receipt_root, lane=lane)
    return _v4_global(_v4_scope, 'run_lanes')(
        target_date=resolved,
        receipt_root=receipt_root,
        a_runner=a_runner,
        hk_runner=hk_runner,
        lane=lane,
    )
