from __future__ import annotations

import pytest

from contracts.trading_calendar import (
    MarketScope,
    RunPolicy,
    SessionRequirement,
    TradingDayState,
    load_market_calendar,
)
from domains.runtime_policy import evaluate_run_policy


def test_market_calendar_contract_is_strict_and_provenanced() -> None:
    calendar = load_market_calendar()

    assert calendar.schema_version == "v3_5.market_calendar_2026.v1"
    assert calendar.year == 2026
    assert calendar.timezone == "Asia/Shanghai"
    assert set(calendar.markets) == {
        "a_share",
        "hk_securities",
        "hk_connect_southbound",
    }
    assert {source.market for source in calendar.official_sources} == {
        "a_share",
        "hk_securities",
        "hk_connect_southbound",
    }


def test_research_is_ineligible_on_weekend() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20260725",
        "1200",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )

    assert decision.eligible is False
    assert decision.reason == "NON_TRADING_DAY"
    assert decision.eligible_markets == ()
    assert decision.blocked_markets == ("a_share", "hk_connect")
    assert decision.market_states == {
        "a_share": TradingDayState.NON_TRADING_DAY.value,
        "hk_connect": TradingDayState.NON_TRADING_DAY.value,
    }


def test_research_is_eligible_on_frozen_full_trading_day() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20260730",
        "1200",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )

    assert decision.eligible is True
    assert decision.calendar_status == "TRADING_DAY"
    assert decision.eligible_markets == ("a_share", "hk_connect")
    assert decision.blocked_markets == ()


def test_asymmetric_hk_holiday_keeps_only_a_share_eligible() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20260701",
        "1000",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.SESSION_OPEN,
    )

    assert decision.eligible is True
    assert decision.calendar_status == "PARTIAL_MARKET"
    assert decision.eligible_markets == ("a_share",)
    assert decision.blocked_markets == ("hk_connect",)
    assert decision.market_states["a_share"] == TradingDayState.FULL_TRADING_DAY.value
    assert decision.market_states["hk_connect"] == TradingDayState.NON_TRADING_DAY.value


def test_half_day_afternoon_does_not_blanket_disable_other_market() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20261224",
        "1400",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.SESSION_OPEN,
    )

    assert decision.eligible is True
    assert decision.session_status == "PARTIAL_MARKET_ELIGIBLE"
    assert decision.eligible_markets == ("a_share",)
    assert decision.blocked_markets == ("hk_connect",)
    assert decision.market_states["hk_connect"] == TradingDayState.HALF_TRADING_DAY_AM.value


def test_post_close_uses_each_markets_actual_close() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20261224",
        "1400",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.POST_CLOSE,
    )

    assert decision.eligible is True
    assert decision.eligible_markets == ("hk_connect",)
    assert decision.blocked_markets == ("a_share",)
    assert decision.session_status == "PARTIAL_MARKET_ELIGIBLE"


def test_half_day_morning_keeps_both_markets_session_eligible() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20261224",
        "0930",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.SESSION_OPEN,
    )

    assert decision.eligible is True
    assert decision.eligible_markets == ("a_share", "hk_connect")
    assert decision.blocked_markets == ()


def test_exchange_holiday_is_not_inferred_from_weekday() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20260217",
        "1000",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )

    assert decision.eligible is False
    assert decision.reason == "NON_TRADING_DAY"


def test_unknown_date_fails_closed() -> None:
    decision = evaluate_run_policy(
        RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
        "20270104",
        "1000",
        market_scope=MarketScope.CROSS_MARKET,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )

    assert decision.eligible is False
    assert decision.calendar_status == "UNKNOWN"
    assert decision.session_status == "UNKNOWN"
    assert decision.blocked_markets == ("a_share", "hk_connect")


def test_invalid_slot_is_rejected() -> None:
    with pytest.raises(ValueError, match="slot"):
        evaluate_run_policy(
            RunPolicy.A_SHARE_TRADE_DAY,
            "20260730",
            "25:00",
            market_scope=MarketScope.A_SHARE,
            session_requirement=SessionRequirement.SESSION_OPEN,
        )
