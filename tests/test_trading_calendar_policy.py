from __future__ import annotations

import hashlib
import json

import pytest

from contracts.trading_calendar import (
    CALENDAR_PATH,
    CalendarYearMissing,
    MarketCalendarRange,
    MarketScope,
    RunPolicy,
    SessionRequirement,
    TradingDayState,
    load_market_calendar,
    load_market_calendar_range,
    next_session,
    previous_session,
    resolve_market_state,
    resolve_market_states,
)
from domains.runtime_policy import evaluate_run_policy
from infrastructure.research_workbench_host import ResearchWorkbenchHost


def _synthetic_2027_calendar_reference(tmp_path):
    """Write a complete, explicitly synthetic calendar for boundary tests."""
    source_markets = ("a_share", "hk_securities", "hk_connect_southbound")

    def market(label, derives_from=(), holidays=()):
        return {
            "label": label,
            "derives_from": list(derives_from),
            "full_day_sessions": [
                {"start": "0900", "end": "1200"},
                {"start": "1300", "end": "1600"},
            ],
            "half_day_sessions": [{"start": "0900", "end": "1100"}],
            "full_day_close": "1600",
            "half_day_close": "1100",
            "half_days": [],
            "holiday_periods": list(holidays),
        }

    payload = {
        "schema_version": "v3_5.market_calendar_2027.v1",
        "year": 2027,
        "timezone": "Asia/Shanghai",
        "official_sources": [
            {
                "market": market_key,
                "name": "Synthetic test fixture",
                "url": f"https://example.invalid/synthetic-calendar/2027/{market_key}",
            }
            for market_key in source_markets
        ],
        "markets": {
            "a_share": market(
                "Synthetic A-share",
                holidays=[
                    {"name": "fixture closure", "start": "20270101", "end": "20270104"}
                ],
            ),
            "hk_securities": market(
                "Synthetic HK securities",
                holidays=[
                    {"name": "fixture closure", "start": "20270101", "end": "20270101"}
                ],
            ),
            "hk_connect_southbound": market(
                "Synthetic HK Connect Southbound",
                derives_from=("a_share", "hk_securities"),
                holidays=[
                    {
                        "name": "fixture-only southbound closure",
                        "start": "20270105",
                        "end": "20270105",
                    }
                ],
            ),
        },
    }
    path = tmp_path / "synthetic_market_calendar_2027.json"
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path.resolve(strict=True)), "sha256": hashlib.sha256(raw).hexdigest()}


def _legacy_calendar_reference():
    path = CALENDAR_PATH.resolve(strict=True)
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


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


def test_2026_mid_autumn_dates_keep_hk_securities_and_connect_calendars_distinct() -> None:
    calendar = load_market_calendar()

    sep_25 = resolve_market_states(calendar, "20260925")
    assert sep_25["a_share"] == TradingDayState.NON_TRADING_DAY
    assert sep_25["hk_securities"] == TradingDayState.FULL_TRADING_DAY
    assert sep_25["hk_connect"] == TradingDayState.NON_TRADING_DAY

    sep_28 = resolve_market_states(calendar, "20260928")
    assert sep_28 == {
        "a_share": TradingDayState.FULL_TRADING_DAY,
        "hk_securities": TradingDayState.FULL_TRADING_DAY,
        "hk_connect": TradingDayState.FULL_TRADING_DAY,
    }


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


def test_legacy_2026_calendar_and_session_calls_match_sha_bound_range() -> None:
    calendar = load_market_calendar()
    calendar_range = load_market_calendar_range({}, legacy_reference=_legacy_calendar_reference())

    assert isinstance(calendar_range, MarketCalendarRange)
    assert calendar_range.years == (2026,)
    assert calendar_range.sha256_by_year[2026] == _legacy_calendar_reference()["sha256"]
    for market in ("a_share", "hk_securities", "hk_connect"):
        assert resolve_market_states(calendar_range, "20260925")[market] == resolve_market_states(
            calendar, "20260925"
        )[market]
        assert previous_session(calendar_range, "20260928", market=market) == previous_session(
            calendar, "20260928", market=market
        )
        assert next_session(calendar_range, "20260924", market=market) == next_session(
            calendar, "20260924", market=market
        )


def test_sha_bound_calendar_range_crosses_years_without_merging_markets(tmp_path) -> None:
    future_ref = _synthetic_2027_calendar_reference(tmp_path)
    calendar_range = load_market_calendar_range(
        {2027: future_ref},
        legacy_reference=_legacy_calendar_reference(),
    )

    assert calendar_range.years == (2026, 2027)
    assert resolve_market_states(calendar_range, "20270104") == {
        "a_share": TradingDayState.NON_TRADING_DAY,
        "hk_securities": TradingDayState.FULL_TRADING_DAY,
        "hk_connect": TradingDayState.NON_TRADING_DAY,
    }
    assert resolve_market_states(calendar_range, "20270105") == {
        "a_share": TradingDayState.FULL_TRADING_DAY,
        "hk_securities": TradingDayState.FULL_TRADING_DAY,
        "hk_connect": TradingDayState.NON_TRADING_DAY,
    }
    assert next_session(calendar_range, "20261231", market="a_share") == "20270105"
    assert next_session(calendar_range, "20261231", market="hk_securities") == "20270104"
    assert next_session(calendar_range, "20261231", market="hk_connect") == "20270106"
    assert previous_session(calendar_range, "20270105", market="a_share") == "20261231"
    assert previous_session(calendar_range, "20270104", market="hk_securities") == "20261231"
    assert previous_session(calendar_range, "20270106", market="hk_connect") == "20261231"


def test_missing_year_fails_closed_with_market_and_candidate_date() -> None:
    calendar_range = load_market_calendar_range({}, legacy_reference=_legacy_calendar_reference())

    with pytest.raises(
        CalendarYearMissing,
        match=r"year=2027 market=a_share trade_date=20270101",
    ):
        next_session(calendar_range, "20261231", market="a_share")
    with pytest.raises(
        CalendarYearMissing,
        match=r"year=2027 market=hk_securities trade_date=20270104",
    ):
        resolve_market_state(calendar_range, "20270104", market="hk_securities")


def test_calendar_range_rejects_sha_duplicate_and_year_conflicts(tmp_path) -> None:
    future_ref = _synthetic_2027_calendar_reference(tmp_path)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_market_calendar_range({2027: {**future_ref, "sha256": "0" * 64}})
    with pytest.raises(ValueError, match="duplicate market calendar year: year=2026"):
        load_market_calendar_range(
            {2026: _legacy_calendar_reference()},
            legacy_reference=_legacy_calendar_reference(),
        )
    with pytest.raises(ValueError, match=r"reference year conflict: key=2026 actual=2027"):
        load_market_calendar_range({2026: future_ref})


def test_workbench_observation_date_uses_year_range_and_legacy_ref(tmp_path) -> None:
    future_ref = _synthetic_2027_calendar_reference(tmp_path)
    host = ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    host.binding = {
        "calendar": _legacy_calendar_reference(),
        "calendar_by_year": {"2027": future_ref},
        "observation_dates": {},
    }

    assert host._observation_date("2026-12-31") == "2027-01-05"


def test_workbench_legacy_calendar_does_not_guess_missing_next_year() -> None:
    host = ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    host.binding = {"calendar": _legacy_calendar_reference(), "observation_dates": {}}

    with pytest.raises(
        ValueError,
        match=r"WORKBENCH_CALENDAR_YEAR_UNBOUND:year=2027:market=a_share:date=20270101",
    ):
        host._observation_date("2026-12-31")
