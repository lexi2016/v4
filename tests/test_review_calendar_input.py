"""Strict input validation against the supplied frozen A-share calendar only."""
import pytest
from shared_data.market_calendar import evaluate_a_share_trade_date

@pytest.mark.parametrize("value", [20260904, None, True, "202611", "202691", "２０２６０９０４", "20260230"])
def test_calendar_rejects_noncanonical_date(value):
    result=evaluate_a_share_trade_date(value)
    assert result["eligible"] is False
    assert result["status"] == "CALENDAR_DATE_INVALID"

@pytest.mark.parametrize("value, expected", [("20260904", "TRADING_DAY_READY"),
        ("20260906","SKIPPED_NON_TRADING_DAY_WEEKEND"),
        ("20261001","SKIPPED_NON_TRADING_DAY_HOLIDAY"),
        ("20270906","CALENDAR_OUT_OF_RANGE")])
def test_frozen_calendar_valid_dates_unchanged(value, expected):
    assert evaluate_a_share_trade_date(value)["status"] == expected
