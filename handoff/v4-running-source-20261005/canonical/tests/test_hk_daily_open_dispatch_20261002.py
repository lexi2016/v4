from __future__ import annotations

from contracts.trading_calendar import (
    MarketScope,
    RunPolicy,
    SessionRequirement,
    TradingDayState,
    load_market_calendar,
    resolve_market_states,
)
from domains.runtime_policy import evaluate_run_policy
from domains.task_status import _schedule_date_is_eligible
from infrastructure.scheduling.catalog import load_workload_catalog


TARGET_DATE = "20261002"
WORKLOAD_ID = "research_panel_daily_hk"


def test_daily_hk_dispatch_uses_securities_open_after_close_while_connect_is_closed():
    calendar = load_market_calendar()
    states = resolve_market_states(calendar, TARGET_DATE)
    workload = next(
        item
        for item in load_workload_catalog().workloads
        if item.workload_id == WORKLOAD_ID
    )

    assert states["a_share"] is TradingDayState.NON_TRADING_DAY
    assert states["hk_securities"] is TradingDayState.FULL_TRADING_DAY
    assert states["hk_connect"] is TradingDayState.NON_TRADING_DAY
    assert workload.run_policy is RunPolicy.HK_SECURITIES_TRADE_DAY
    assert workload.market_scope is MarketScope.HK_CONNECT
    assert workload.session_requirement is SessionRequirement.POST_CLOSE
    assert workload.slots == ("1720",)
    assert workload.enabled is True
    assert workload.safety.production_allowed is False
    assert workload.safety.buy_gate_updated is False
    assert workload.safety.orders_sent is False

    decision = evaluate_run_policy(
        workload.run_policy,
        TARGET_DATE,
        workload.slots[0],
        market_scope=workload.market_scope,
        session_requirement=workload.session_requirement,
    )

    assert decision.eligible is True
    assert decision.reason == "ELIGIBLE"
    assert decision.eligible_markets == ("hk_securities",)
    assert decision.blocked_markets == ()
    assert decision.market_states == {"hk_securities": "FULL_TRADING_DAY"}
    assert decision.session_status == "POST_CLOSE_ELIGIBLE"
    assert _schedule_date_is_eligible(workload, TARGET_DATE, calendar=calendar) is True

    old_connect_decision = evaluate_run_policy(
        RunPolicy.HK_CONNECT_TRADE_DAY,
        TARGET_DATE,
        workload.slots[0],
        market_scope=MarketScope.HK_CONNECT,
        session_requirement=SessionRequirement.POST_CLOSE,
    )
    assert old_connect_decision.eligible is False
    assert old_connect_decision.blocked_markets == ("hk_connect",)
