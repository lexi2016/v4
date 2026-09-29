from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from contracts.us_equity_calendar import latest_completed_session, session
from ops.us_market_digest import (
    build_us_market_phase_payload,
    us_capture_window,
    us_market_day_certification,
)


def test_official_holiday_and_early_close_are_explicit():
    holiday = session("20260907")
    assert holiday.state == "CLOSED_HOLIDAY"
    assert holiday.close_at is None
    early = session("20261127")
    assert early.state == "OPEN_EARLY_CLOSE"
    assert early.close_at.hour == 13
    assert early.close_at.tzinfo == ZoneInfo("America/New_York")


def test_producer_calendar_certification_reports_normal_holiday_and_half_day():
    regular = us_market_day_certification("20260924")
    assert regular["status"] == "VERIFIED"
    assert regular["reason"] == "OPEN_FULL_DAY"
    assert regular["close_at"].startswith("2026-09-24T16:00:00-04:00")

    holiday = us_market_day_certification("20260907")
    assert holiday["status"] == "CLOSED"
    assert holiday["reason"] == "CLOSED_HOLIDAY"

    early_close = us_market_day_certification("20261127")
    assert early_close["status"] == "VERIFIED"
    assert early_close["reason"] == "OPEN_EARLY_CLOSE"
    assert early_close["close_at"].startswith("2026-11-27T13:00:00-05:00")


def test_producer_only_downgrades_unverified_live_calendar_dates():
    def build(session_date, captured_at):
        return build_us_market_phase_payload(
            session_date,
            capture_phase="PRE_OPEN",
            fetched_at=captured_at,
            fetch_rss=lambda *_args: b"<rss><channel></channel></rss>",
        )

    regular = build("20260924", "2026-09-24T13:00:30Z")
    assert regular["status"] == "READY_EMPTY"
    assert "OPEN_FULL_DAY" not in regular["cannot_confirm"]

    early_close = build("20261127", "2026-11-27T14:00:30Z")
    assert early_close["status"] == "READY_EMPTY"
    assert "OPEN_EARLY_CLOSE" not in early_close["cannot_confirm"]

    holiday = build("20260907", "2026-09-07T13:00:30Z")
    assert holiday["status"] == "CANNOT_CONFIRM"
    assert "CLOSED_HOLIDAY" in holiday["cannot_confirm"]

    uncovered = build("20270104", "2027-01-04T14:00:30Z")
    assert uncovered["status"] == "CANNOT_CONFIRM"
    assert "US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE" in uncovered["cannot_confirm"]


def test_capture_slot_width_and_ny_offsets_remain_explicit_across_dst_and_half_day():
    cases = (
        ("20260115", "PRE_OPEN", -5),
        ("20260924", "PRE_OPEN", -4),
        ("20261127", "POST_CLOSE", -5),
    )
    for session_date, phase, offset_hours in cases:
        start, end = us_capture_window(session_date, phase)
        assert (end - start).total_seconds() == 5 * 60
        assert start.utcoffset().total_seconds() == offset_hours * 60 * 60


def test_manager_cutoff_resolves_previous_completed_us_session_with_dst():
    cutoff = datetime.fromisoformat("2026-09-24T09:27:35.408396+08:00")
    resolved = latest_completed_session(cutoff)
    assert resolved.session_date == "20260923"
    assert resolved.close_at.isoformat().startswith("2026-09-23T16:00:00-04:00")


def test_weekend_observation_rolls_to_friday_without_guessing_a_weekday():
    observed = datetime(2026, 9, 27, 12, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    assert latest_completed_session(observed).session_date == "20260925"


@pytest.mark.parametrize("session_date", ["20251231", "20270104"])
def test_session_refuses_years_outside_the_calendar_contract(session_date):
    with pytest.raises(ValueError, match="US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE"):
        session(session_date)
    result = us_market_day_certification(session_date)
    assert result == {
        "status": "CANNOT_CONFIRM",
        "reason": "US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE",
    }


@pytest.mark.parametrize("cutoff", [
    datetime(2026, 1, 1, 9, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    datetime(2027, 1, 4, 9, tzinfo=ZoneInfo("Asia/Hong_Kong")),
])
def test_previous_completed_search_fails_closed_on_cross_year_or_uncovered_input(cutoff):
    with pytest.raises(ValueError, match="US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE"):
        latest_completed_session(cutoff)


@pytest.mark.parametrize("lookback", [-1, 32, 10**9, True])
def test_previous_completed_search_rejects_invalid_or_unbounded_lookback(lookback):
    cutoff = datetime(2026, 9, 27, 12, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    with pytest.raises(ValueError, match="US_EQUITY_LOOKBACK_RANGE_INVALID"):
        latest_completed_session(cutoff, max_lookback_days=lookback)
