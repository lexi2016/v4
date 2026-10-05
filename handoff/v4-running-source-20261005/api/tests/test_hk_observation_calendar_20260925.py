from __future__ import annotations

import sys
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from contracts.trading_calendar import (
    TradingDayState as ContractTradingDayState,
    load_market_calendar,
    resolve_market_states as resolve_contract_market_states,
)
from domains.preselection import date_catalog
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import PreselectionPoolStore
from ops.run_stage_center_nodes import _calendar_gate as nodes_calendar_gate
from ops.run_stage_center_tick import _calendar_gate as tick_calendar_gate
from stage_center.calendar import TradingDayState, resolve_market_states
from stage_center.hk_stage8.precapture import prepare_due_snapshot
from stage_center.runner import (
    RunnerError,
    _build_hk_stage_binding,
    _stage_markets_for_date,
)
from stage_center.scheduler import evaluate_due


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _hk_d1_pool(trade_date: str, signal_date: str) -> dict[str, object]:
    flags = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "target_date": trade_date,
        "signal_date": signal_date,
        "pool_id": "hkconnect_d1_top100",
        "display_name": "synthetic verified HK D-1",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": "synthetic/verified-pool.json",
        "source_sha256": hashlib.sha256(f"pool:{trade_date}".encode()).hexdigest(),
        "stage_selection_eligible": True,
        "rows": [
            {
                "symbol": f"HK.{rank:05d}",
                "code": f"HK.{rank:05d}",
                "market": "HK",
                "pool_id": "hkconnect_d1_top100",
                "signal_date": signal_date,
                "trade_date": trade_date,
                "target_date": trade_date,
                "selected_strategy": "prob_active",
                "prob_active": 0.5,
                **flags,
            }
            for rank in range(1, 101)
        ],
        "cannot_confirm": [],
        **flags,
    }


def test_hk_securities_open_date_is_separate_from_southbound_connect() -> None:
    states = resolve_market_states("20260925")

    assert states["a_share"] is TradingDayState.NON_TRADING_DAY
    assert states["hk_securities"] is TradingDayState.FULL_TRADING_DAY
    assert states["hk_connect"] is TradingDayState.NON_TRADING_DAY


def test_stage_due_and_node_calendar_gate_continue_hk_observation_on_connect_closed_date() -> None:
    decision = evaluate_due(
        "STAGE_0925",
        "20260925",
        datetime(2026, 9, 25, 9, 25, 5, tzinfo=SHANGHAI),
    )
    node_gate = nodes_calendar_gate("20260925", markets=("A_SHARE", "HK_CONNECT"))

    assert decision.status == "DUE"
    assert decision.calendar["hk_connect"] == TradingDayState.NON_TRADING_DAY.value
    assert node_gate["status"] == "ELIGIBLE"
    assert node_gate["calendar"]["hk_connect"] == TradingDayState.NON_TRADING_DAY.value
    assert _stage_markets_for_date("STAGE_0925", "20260925") == ("HK_CONNECT",)
    assert _stage_markets_for_date("STAGE_0925", "20260701") == ("A_SHARE",)
    assert _stage_markets_for_date("STAGE_0925", "20261001") == ()


def test_tick_gate_observes_hk_securities_but_still_skips_hk_market_holiday() -> None:
    observation = tick_calendar_gate("20260925")
    holiday = tick_calendar_gate("20261001")

    assert observation["status"] == "ELIGIBLE"
    assert observation["calendar"]["hk_connect"] == ContractTradingDayState.NON_TRADING_DAY.value
    assert holiday["status"] == "NON_TRADING_DAY"


def test_hk_stage8_precapture_runs_when_hk_is_open_even_if_connect_is_closed(tmp_path: Path) -> None:
    class Config:
        injected_test_mode = False
        hk_d1_root = tmp_path / "d1"
        hk_full_universe_root = None
        shared_data_root = tmp_path / "shared"
        python_path = Path(sys.executable)
        raw_root = tmp_path / "raw"

    calls: list[str] = []
    output = prepare_due_snapshot(
        Config(),
        "20260925",
        datetime(2026, 9, 25, 15, 50, tzinfo=SHANGHAI),
        stage_id="STAGE_1545_1555",
        historical_backfill=False,
        universe_loader=lambda: (tmp_path / "source.json", ("HK.00001",), "a" * 64),
        snapshot_preparer=lambda *args, **kwargs: calls.append("snapshot") or {"status": "READY"},
    )

    assert calls == ["snapshot"]
    assert output and output[0]["status"] == "READY"
    assert output[0]["trade_date"] == "20260925"


def test_date_catalog_keeps_hk_open_today_navigable_without_promoting_it_as_a_pool(tmp_path: Path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": "20260924",
            "stage_dates": ["20260924"],
            "future_target_dates": [],
            "materialized_rows": {"20260924": 1},
        }
    )

    catalog = date_catalog(store, current_date="20260925")

    assert catalog["default_date"] == "20260924"
    assert catalog["navigation_date"] == "20260925"
    assert "20260925" in catalog["dates"]
    assert "20260925" in catalog["hk_observation_only_dates"]


def test_official_calendar_contract_does_not_mark_sep28_or_dec28_as_hk_holidays() -> None:
    calendar = load_market_calendar()
    for trade_date in ("20260928", "20261228"):
        states = resolve_contract_market_states(calendar, trade_date)
        assert states["hk_securities"] is ContractTradingDayState.FULL_TRADING_DAY
        assert states["hk_connect"] is ContractTradingDayState.FULL_TRADING_DAY
        stage_states = resolve_market_states(trade_date)
        assert stage_states["hk_securities"] is TradingDayState.FULL_TRADING_DAY
        assert stage_states["hk_connect"] is TradingDayState.FULL_TRADING_DAY


def test_hk_observation_binding_keeps_prior_pool_date_signal_and_sha(tmp_path: Path) -> None:
    root = tmp_path / "hk-source"
    pool_store = PreselectionPoolStore(root)
    pool_store.materialize(_hk_d1_pool("20260924", "20260923"))

    binding = _build_hk_stage_binding(root, "20260925")
    snapshot = pool_store.read_pool_snapshot("20260924", "hkconnect_d1_top100")

    assert binding.trade_date == "20260925"
    assert binding.role == "HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION"
    assert binding.sha256 == snapshot["artifact_raw_sha256"]
    assert "hk_d1_source_trade_date=20260924" in binding.evidence
    assert "hk_d1_source_signal_date=20260923" in binding.evidence
    assert f"hk_d1_source_manifest_sha256={snapshot['manifest_raw_sha256']}" in binding.evidence
    assert f"hk_d1_source_receipt_sha256={snapshot['receipt_raw_sha256']}" in binding.evidence
    assert snapshot["artifact"]["trade_date"] == "20260924"
    assert snapshot["artifact"]["target_date"] == "20260924"
    assert {row["signal_date"] for row in snapshot["artifact"]["rows"]} == {"20260923"}


def test_hk_observation_binding_without_verified_prior_pool_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "empty-hk-source"
    root.mkdir()

    try:
        _build_hk_stage_binding(root, "20260925")
    except RunnerError as error:
        assert "CANNOT_CONFIRM" in str(error)
    else:
        raise AssertionError("missing HK observation pool must fail closed")


def test_invalid_latest_prior_pool_does_not_silently_use_older_pool(tmp_path: Path) -> None:
    root = tmp_path / "invalid-latest-source"
    store = PreselectionPoolStore(root)
    store.materialize(_hk_d1_pool("20260924", "20260922"))
    store.materialize(_hk_d1_pool("20260923", "20260922"))

    try:
        _build_hk_stage_binding(root, "20260925")
    except RunnerError as error:
        assert "signal_date mismatch" in str(error)
    else:
        raise AssertionError("an invalid latest exact-date pool must not fall back silently")
