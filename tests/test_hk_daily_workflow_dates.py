from __future__ import annotations

from datetime import date, timedelta

from contracts.trading_calendar import (
    TradingDayState,
    load_market_calendar,
    next_session,
    resolve_market_states,
)
from infrastructure.scheduling.catalog import load_workload_catalog
from ops.run_scheduled_slot import compute_dates, next_trade_day


SESSION_STATES = {
    TradingDayState.FULL_TRADING_DAY,
    TradingDayState.HALF_TRADING_DAY_AM,
}


def _calendar_dates(calendar):
    cursor = date(calendar.year, 1, 1)
    final = date(calendar.year, 12, 31)
    while cursor <= final:
        yield cursor.strftime("%Y%m%d")
        cursor += timedelta(days=1)


def _next_policy_divergence(calendar, *, require_hk_only: bool):
    for business_date in _calendar_dates(calendar):
        states = resolve_market_states(calendar, business_date)
        if require_hk_only:
            eligible = (
                states["hk_securities"] in SESSION_STATES
                and states["a_share"] not in SESSION_STATES
                and states["hk_connect"] not in SESSION_STATES
            )
            if not eligible:
                continue
            hk_target = next_session(calendar, business_date, market="hk_securities")
            legacy_target = next_trade_day(business_date, calendar=calendar)
            if hk_target != legacy_target:
                return business_date, hk_target
            continue

        eligible = all(
            states[market] in SESSION_STATES
            for market in ("a_share", "hk_securities", "hk_connect")
        )
        if not eligible:
            continue
        a_target = next_session(calendar, business_date, market="a_share")
        hk_target = next_session(calendar, business_date, market="hk_securities")
        if a_target != hk_target:
            return business_date, a_target
    raise AssertionError("calendar does not contain the required date case")


def test_runtime_catalog_keeps_hk_daily_and_preselection_date_roles() -> None:
    catalog = load_workload_catalog()
    workloads = {item.workload_id: item for item in catalog.workloads}

    hk_daily = workloads["research_panel_daily_hk"]
    assert hk_daily.run_policy.value == "HK_SECURITIES_TRADE_DAY"
    assert hk_daily.slots == ("1720",)
    assert hk_daily.signal_date_role == "BUSINESS_DATE"
    assert hk_daily.target_date_role == "BUSINESS_DATE"

    preselection = workloads["preselection_pools"]
    assert preselection.run_policy.value == "A_OR_HK_SECURITIES_TRADE_DAY"
    assert preselection.slots == ("1730", "1800")
    assert preselection.signal_date_role == "BUSINESS_DATE"
    assert preselection.target_date_role == "TARGET_DATE"
    assert preselection.safety.production_allowed is False
    assert preselection.safety.buy_gate_updated is False
    assert preselection.safety.orders_sent is False


def test_ordinary_hk_days_use_the_a_target_when_the_a_lane_runs() -> None:
    calendar = load_market_calendar()
    first_date, expected_target = _next_policy_divergence(
        calendar, require_hk_only=False
    )
    all_open_dates = [
        business_date
        for business_date in _calendar_dates(calendar)
        if all(
            state in SESSION_STATES
            for state in resolve_market_states(calendar, business_date).values()
        )
    ]
    assert first_date in all_open_dates
    assert len(all_open_dates) >= 2

    for business_date in all_open_dates[:2]:
        expected_a_target = next_session(calendar, business_date, market="a_share")
        result = compute_dates(
            business_date=business_date, slot="1730", calendar=calendar
        )
        assert result == {
            "scheduled_date": business_date,
            "business_date": business_date,
            "target_date": expected_a_target,
        }

    divergence_result = compute_dates(
        business_date=first_date, slot="1730", calendar=calendar
    )
    assert divergence_result["target_date"] == expected_target
    assert divergence_result["target_date"] != next_session(
        calendar, first_date, market="hk_securities"
    )
    assert compute_dates(
        business_date=first_date, slot="1720", calendar=calendar
    )["target_date"] == first_date


def test_hk_only_preselection_day_uses_next_hk_securities_session() -> None:
    calendar = load_market_calendar()
    business_date, expected_target = _next_policy_divergence(
        calendar, require_hk_only=True
    )

    result = compute_dates(
        business_date=business_date, slot="1730", calendar=calendar
    )

    assert result["target_date"] == expected_target
    assert result["target_date"] != next_trade_day(
        business_date, calendar=calendar
    )
