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


def test_hk_close_review_uses_securities_calendar_and_keeps_post_close_gate():
    calendar = load_market_calendar()
    states = resolve_market_states(calendar, TARGET_DATE)
    workloads = {
        item.workload_id: item for item in load_workload_catalog().workloads
    }
    workload = workloads["hk_connect_close_review"]

    assert states["a_share"] is TradingDayState.NON_TRADING_DAY
    assert states["hk_securities"] is TradingDayState.FULL_TRADING_DAY
    assert states["hk_connect"] is TradingDayState.NON_TRADING_DAY
    assert workload.run_policy is RunPolicy.HK_SECURITIES_TRADE_DAY
    assert workload.market_scope is MarketScope.HK_CONNECT
    assert workload.session_requirement is SessionRequirement.POST_CLOSE
    assert workload.slots == ("1610",)
    assert workload.safety.production_allowed is False
    assert workload.safety.buy_gate_updated is False
    assert workload.safety.orders_sent is False

    before_hkse_close = evaluate_run_policy(
        workload.run_policy,
        TARGET_DATE,
        "1608",
        market_scope=workload.market_scope,
        session_requirement=workload.session_requirement,
    )
    assert before_hkse_close.eligible is False
    assert before_hkse_close.reason == "REQUIRED_SESSION_CLOSED"
    assert before_hkse_close.market_states == {"hk_securities": "FULL_TRADING_DAY"}

    at_hkse_close = evaluate_run_policy(
        workload.run_policy,
        TARGET_DATE,
        "1610",
        market_scope=workload.market_scope,
        session_requirement=workload.session_requirement,
    )
    assert at_hkse_close.eligible is True
    assert at_hkse_close.reason == "ELIGIBLE"
    assert at_hkse_close.eligible_markets == ("hk_securities",)
    assert at_hkse_close.session_status == "POST_CLOSE_ELIGIBLE"

    hk_holiday = evaluate_run_policy(
        workload.run_policy,
        "20261001",
        "1610",
        market_scope=workload.market_scope,
        session_requirement=workload.session_requirement,
    )
    assert hk_holiday.eligible is False
    assert hk_holiday.reason == "NON_TRADING_DAY"
    assert hk_holiday.market_states == {"hk_securities": "NON_TRADING_DAY"}

    unknown = evaluate_run_policy(
        workload.run_policy,
        "20270102",
        "1610",
        market_scope=workload.market_scope,
        session_requirement=workload.session_requirement,
    )
    assert unknown.eligible is False
    assert unknown.reason == "UNKNOWN"
    assert unknown.market_states == {"hk_securities": "UNKNOWN"}

    fupan_review = workloads["fupan_review_start"]
    assert fupan_review.run_policy is RunPolicy.HK_CONNECT_TRADE_DAY
    assert fupan_review.safety.production_allowed is False
    assert fupan_review.safety.buy_gate_updated is False
    assert fupan_review.safety.orders_sent is False
    connect_decision = evaluate_run_policy(
        fupan_review.run_policy,
        TARGET_DATE,
        fupan_review.slots[0],
        market_scope=fupan_review.market_scope,
        session_requirement=fupan_review.session_requirement,
    )
    assert connect_decision.eligible is False
    assert connect_decision.market_states == {"hk_connect": "NON_TRADING_DAY"}
