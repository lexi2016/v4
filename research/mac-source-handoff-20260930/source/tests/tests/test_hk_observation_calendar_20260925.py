from __future__ import annotations

import sys
import fcntl
import hashlib
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

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
from stage_center.calendar import (
    TradingDayState,
    eligible_stage_markets,
    resolve_market_states,
)
from stage_center.hk_stage8.precapture import prepare_due_snapshot
from stage_center.runner import (
    RunnerError,
    RunnerConfig,
    StageCenterRunner,
    _build_hk_stage_binding,
    _stage_markets_for_date,
)
from stage_center.acquisition import SourceResult
from stage_center.scheduler import DueDecision, evaluate_due
from stage_center.raw_store import RawStore, RawStoreError
import stage_center.runner as stage_runner


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


def test_stage_bundle_market_contract_follows_exact_date_calendar() -> None:
    dual_market_stage = ("A_SHARE", "HK_CONNECT")

    assert eligible_stage_markets(dual_market_stage, "20260924") == dual_market_stage
    assert eligible_stage_markets(dual_market_stage, "20260925") == ("HK_CONNECT",)
    assert eligible_stage_markets(dual_market_stage, "20260701") == ("A_SHARE",)
    assert eligible_stage_markets(dual_market_stage, "20261001") == ()
    with pytest.raises(ValueError, match="calendar unknown"):
        eligible_stage_markets(dual_market_stage, "20270104")


def test_raw_bundle_publish_and_readback_require_calendar_exact_market_set(
    tmp_path: Path,
) -> None:
    store = RawStore(tmp_path / "raw")

    hk_0925 = store.publish(
        trade_date="20260925",
        stage_id="STAGE_0930_0935",
        market="HK_CONNECT",
        source_id="fixture-hk-closed-southbound",
        source_status="CANNOT_CONFIRM",
        rows=(),
        requested_rows=0,
    )
    hk_bundle = store.publish_bundle(
        trade_date="20260925",
        stage_id="STAGE_0930_0935",
        status="CANNOT_CONFIRM",
        markets={"HK_CONNECT": hk_0925},
    )
    assert set(hk_bundle["markets"]) == {"HK_CONNECT"}
    assert set(
        store.read_verified_bundle("20260925", "STAGE_0930_0935")["receipt"]["markets"]
    ) == {"HK_CONNECT"}

    a_0924 = store.publish(
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        market="A_SHARE",
        source_id="fixture-a-share",
        source_status="CANNOT_CONFIRM",
        rows=(),
        requested_rows=0,
    )
    hk_0924 = store.publish(
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        market="HK_CONNECT",
        source_id="fixture-hk-connect",
        source_status="CANNOT_CONFIRM",
        rows=(),
        requested_rows=0,
    )
    with pytest.raises(RawStoreError, match="bundle market set mismatch"):
        store.publish_bundle(
            trade_date="20260924",
            stage_id="STAGE_0930_0935",
            status="CANNOT_CONFIRM",
            markets={"HK_CONNECT": hk_0924},
        )
    dual_bundle = store.publish_bundle(
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        status="CANNOT_CONFIRM",
        markets={"A_SHARE": a_0924, "HK_CONNECT": hk_0924},
    )
    assert set(dual_bundle["markets"]) == {"A_SHARE", "HK_CONNECT"}

    for invalid_date in ("20261001", "20270104"):
        with pytest.raises(RawStoreError):
            store.publish_bundle(
                trade_date=invalid_date,
                stage_id="STAGE_0930_0935",
                status="CANNOT_CONFIRM",
                markets={},
            )


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


def test_hk_binding_fails_closed_when_secondary_materializer_holds_lease(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary.mkdir()
    PreselectionPoolStore(secondary).materialize(_hk_d1_pool("20260924", "20260923"))

    lock_path = secondary / "preselection_pools" / ".materialize.lock"
    fd = os.open(
        lock_path,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        os.write(
            fd,
            b'{"schema_version":"v3_5_interprocess_lock.v1","pid":2147483647,"token":"RELEASED"}',
        )
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        for observation_date in ("20260924", "20260925"):
            try:
                _build_hk_stage_binding(
                    primary,
                    observation_date,
                    preselection_source_root=secondary,
                )
            except RunnerError as error:
                assert "CANNOT_CONFIRM" in str(error) or "lock" in str(error).lower()
            else:
                raise AssertionError(
                    f"HK binding for {observation_date} must fail closed while its secondary source is write-locked"
                )
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _run_hk_only_runner_fixture(
    *,
    tmp_path: Path,
    monkeypatch,
    stage_id: str,
    builder_markets: tuple[str, ...],
    collector_calls: list[str],
) -> dict[str, object]:
    primary_root = tmp_path / "d1-primary"
    primary_root.mkdir()
    source_root = tmp_path / "verified-secondary-source"
    PreselectionPoolStore(source_root).materialize(
        _hk_d1_pool("20260924", "20260923")
    )
    lock_path = source_root / "preselection_pools" / ".materialize.lock"
    lock_path.write_text(
        '{"schema_version":"v3_5_interprocess_lock.v1","pid":2147483647,"token":"RELEASED"}',
        encoding="utf-8",
    )
    os.chmod(lock_path, 0o600)
    config = RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate-missing",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_d1_root=primary_root,
        preselection_source_root=source_root,
        shared_data_root=tmp_path / "shared",
        python_path=Path(sys.executable),
    )

    import stage_center.live_collectors as live_collectors
    from stage_center.selection import select_hk_four_lane

    def hk_builder(source, plan, raw):
        return select_hk_four_lane(
            source.rows,
            plan.trade_date,
            plan.stage_id,
            raw["artifact_sha256"],
            source_status=source.status,
            requested_rows=source.requested_rows,
            missing_symbols=source.missing_symbols,
            cannot_confirm=source.cannot_confirm,
            source_evidence=source.source_evidence,
        )

    monkeypatch.setattr(
        live_collectors,
        "production_selection_builders",
        lambda _stage_id: {
            market: hk_builder if market == "HK_CONNECT" else (lambda *_args: {})
            for market in builder_markets
        },
    )

    def collector(plan, market: str) -> SourceResult:
        collector_calls.append(market)
        binding = plan.universe_bindings["HK_CONNECT"]
        assert binding.role == "HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION"
        assert binding.trade_date == "20260925"
        return SourceResult(
            market,
            "READY",
            rows=(
                {
                    "batch_index": 0,
                    "code": "HK.00001",
                    "name": "Synthetic HK security",
                    "update_time": "2026-09-25 09:35:05",
                    "last_price": 10.5,
                    "open_price": 10.0,
                    "high_price": 10.7,
                    "low_price": 9.9,
                    "prev_close_price": 10.0,
                    "turnover": 1000000.0,
                    "volume": 100000.0,
                    "bid_price": 10.49,
                    "ask_price": 10.51,
                    "bid_vol": 1000.0,
                    "ask_vol": 900.0,
                    "window_start": "2026-09-25 09:30:00",
                    "window_end": "2026-09-25 09:35:05",
                    "bar_count": 1,
                    "temporal_cutoff_safe": True,
                    "candidate_lanes": ["LIVE_HKCONNECT_GAINER"],
                    "current_change_pct": 5.0,
                },
            ),
            requested_rows=100,
            source_evidence=("fixture=read-only-synthetic-collector",),
        )

    runner = StageCenterRunner(config, collectors={"HK_CONNECT": collector})
    decision = DueDecision(
        stage_id=stage_id,
        trade_date="20260925",
        status="DUE",
        scheduled_at=None,
        idempotency_key=f"synthetic-{stage_id}",
        calendar={
            "a_share": "NON_TRADING_DAY",
            "hk_securities": "FULL_TRADING_DAY",
            "hk_connect": "NON_TRADING_DAY",
        },
    )
    return runner._run_one(decision)


def test_run_one_hk_only_reuses_prior_binding_through_actual_authority_attachment(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    result = _run_hk_only_runner_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        stage_id="STAGE_0930_0935",
        builder_markets=("HK_CONNECT",),
        collector_calls=calls,
    )

    assert _stage_markets_for_date("STAGE_0930_0935", "20260925") == ("HK_CONNECT",)
    assert calls == ["HK_CONNECT"], result
    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["markets"]["HK_CONNECT"]["selected_rows"] == 1
    evidence = result["markets"]["HK_CONNECT"]["source_evidence"]
    assert "hk_d1_source_trade_date=20260924" in evidence
    assert any(item.startswith("hk_d1_source_manifest_sha256=") for item in evidence)
    assert any(item.startswith("hk_d1_source_receipt_sha256=") for item in evidence)


def test_run_one_hk_only_filters_extra_a_builder_but_keeps_required_hk_builder(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    result = _run_hk_only_runner_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        stage_id="STAGE_0930_0935",
        builder_markets=("A_SHARE", "HK_CONNECT"),
        collector_calls=calls,
    )

    assert calls == ["HK_CONNECT"]
    assert result["status"] == "PARTIAL_WITH_ROWS", result
    assert result["markets"]["HK_CONNECT"]["selection_status"] == "PARTIAL_WITH_ROWS"
    assert result["markets"]["HK_CONNECT"]["selected_rows"] == 1
    evidence = result["markets"]["HK_CONNECT"]["source_evidence"]
    assert "hk_d1_source_trade_date=20260924" in evidence
    assert any(item.startswith("hk_d1_source_manifest_sha256=") for item in evidence)
    assert any(item.startswith("hk_d1_source_receipt_sha256=") for item in evidence)
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False
    raw_store = RawStore(tmp_path / "raw")
    bundle = raw_store.read_verified_bundle("20260925", "STAGE_0930_0935")
    assert result["bundle_id"] == bundle["receipt"]["bundle_id"]
    assert set(bundle["receipt"]["markets"]) == {"HK_CONNECT"}
    raw_market = bundle["receipt"]["markets"]["HK_CONNECT"]
    verified_raw = raw_store.verify_run(
        "20260925", "STAGE_0930_0935", "HK_CONNECT", raw_market["run_id"]
    )
    assert verified_raw["row_count"] == 1
    assert "hk_d1_source_trade_date=20260924" in verified_raw["source_evidence"]


def test_run_one_hk_0925_still_fails_closed_without_exact_second_filter(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    result = _run_hk_only_runner_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        stage_id="STAGE_0925",
        builder_markets=("A_SHARE", "HK_CONNECT"),
        collector_calls=calls,
    )

    assert calls == []
    assert "production HK second-filter root is required for STAGE_0925" in str(result)


def test_run_one_hk_only_still_rejects_a_missing_required_hk_builder(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    result = _run_hk_only_runner_fixture(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        stage_id="STAGE_0930_0935",
        builder_markets=("A_SHARE",),
        collector_calls=calls,
    )

    assert calls == []
    assert "selection builders are missing required markets ('HK_CONNECT',)" in str(result)


def test_prior_hk_authority_read_fails_closed_when_secondary_owner_is_write_locked(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "d1-primary"
    primary.mkdir()
    source_root = tmp_path / "verified-secondary-source"
    PreselectionPoolStore(source_root).materialize(
        _hk_d1_pool("20260924", "20260923")
    )
    lock_path = source_root / "preselection_pools" / ".materialize.lock"
    lock_path.write_text(
        '{"schema_version":"v3_5_interprocess_lock.v1","pid":2147483647,"token":"RELEASED"}',
        encoding="utf-8",
    )
    os.chmod(lock_path, 0o600)
    binding = _build_hk_stage_binding(
        primary,
        "20260925",
        preselection_source_root=source_root,
    )
    fd = os.open(lock_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RunnerError, match="source lease/read CANNOT_CONFIRM"):
            stage_runner._attach_hk_authority(
                SourceResult("HK_CONNECT", "READY", rows=()),
                d1_root=primary,
                preselection_source_root=source_root,
                second_root=None,
                trade_date="20260925",
                stage_id="STAGE_0930_0935",
                hk_binding=binding,
            )
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
