from __future__ import annotations

import importlib.util
from pathlib import Path

from contracts.trading_calendar import TradingDayState
from ops import run_hkconnect_0915_0920_capture as capture


def _existing_fixture_helpers():
    helper_path = Path(__file__).with_name("test_hkconnect_0915_0920_capture.py")
    spec = importlib.util.spec_from_file_location("existing_hkconnect_capture_test_helpers", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("existing capture fixture helpers unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hk_open_connect_closed_day_enters_existing_capture_fixture(tmp_path, monkeypatch):
    helpers = _existing_fixture_helpers()
    trade_date = "20260925"
    monkeypatch.setattr(helpers, "TRADE_DATE", trade_date)
    monkeypatch.setattr(helpers, "SIGNAL_DATE", "20260924")

    gate = capture._calendar_gate(trade_date)
    assert gate["status"] == "ELIGIBLE"
    assert gate["calendar"]["hk_securities"] == TradingDayState.FULL_TRADING_DAY.value
    assert gate["calendar"]["hk_connect"] == TradingDayState.NON_TRADING_DAY.value

    data_root, shared_root, package_root, shared, consumer, _calls, _sha = helpers._shared_fixture(tmp_path)
    invoked = []
    original_capture = shared.run_capture

    def fixture_capture(root, date, futu_python, **kwargs):
        invoked.append(date)
        return original_capture(root, date, futu_python, **kwargs)

    result = helpers.materialize_hkconnect_0915_0920(
        data_root,
        shared_root,
        package_root,
        trade_date,
        Path(__file__),
        shared_module=shared,
        consumer_module=consumer,
        capture_runner=fixture_capture,
    )
    assert result["status"] == "MATERIALIZED_FROM_SHARED_HK_0920"
    assert invoked == [trade_date]
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_hk_securities_holiday_skips_existing_capture_owner():
    result = capture._calendar_gate("20260217")
    assert result["status"] == "SKIPPED_NON_TRADING_DAY"
