from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from infrastructure.preselection_pool_store import PreselectionPoolStore
from stage_center.acquisition import SourceResult
from stage_center.raw_store import RawStore, RawStoreError
from stage_center.runner import RunnerConfig, StageCenterRunner
from stage_center.scheduler import DueDecision
from stage_center.selection import SelectionStore, select_hk_four_lane
from test_hk_observation_calendar_20260925 import _hk_d1_pool


def _test_roots(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    source_root = tmp_path / "verified-source"
    if "preselection_source_root" in RunnerConfig.__dataclass_fields__:
        d1_root = tmp_path / "primary-empty"
        d1_root.mkdir()
        source_config = {"preselection_source_root": source_root}
    else:
        d1_root = source_root
        source_config = {}
    PreselectionPoolStore(source_root).materialize(
        _hk_d1_pool("20260924", "20260923")
    )
    if d1_root != source_root:
        lock_path = source_root / "preselection_pools" / ".materialize.lock"
        lock_path.write_text(
            '{"schema_version":"v3_5_interprocess_lock.v1","pid":2147483647,"token":"RELEASED"}',
            encoding="utf-8",
        )
        os.chmod(lock_path, 0o600)
    return d1_root, source_root, source_config


def _replace_source_pool(source_root: Path) -> None:
    date_root = source_root / "preselection_pools" / "20260924"
    shutil.rmtree(date_root)
    payload = _hk_d1_pool("20260924", "20260923")
    payload["rows"][0]["name"] = "changed after binding"
    PreselectionPoolStore(source_root).materialize(payload)


def _run_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stage_id: str,
    mutate_after_binding: bool = False,
) -> tuple[dict[str, object], list[str], Path]:
    d1_root, source_root, source_config = _test_roots(tmp_path)
    config = RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate-missing",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_d1_root=d1_root,
        shared_data_root=tmp_path / "shared",
        python_path=Path(sys.executable),
        **source_config,
    )
    calls: list[str] = []

    def collector(plan, market: str) -> SourceResult:
        calls.append(market)
        binding = plan.universe_bindings["HK_CONNECT"]
        assert binding.trade_date == "20260925"
        assert binding.role == "HK_CONNECT_D1_TOP100_PRIOR_VERIFIED_OBSERVATION"
        assert "hk_d1_source_trade_date=20260924" in binding.evidence
        assert any(item.startswith("hk_d1_source_manifest_sha256=") for item in binding.evidence)
        assert any(item.startswith("hk_d1_source_receipt_sha256=") for item in binding.evidence)
        if mutate_after_binding:
            _replace_source_pool(source_root)
        return SourceResult(
            market,
            "READY",
            rows=(
                {
                    "batch_index": 0,
                    "code": "HK.00001",
                    "name": "HK.00001",
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

    import stage_center.live_collectors as live_collectors

    monkeypatch.setattr(
        live_collectors,
        "production_selection_builders",
        lambda _stage_id: {
            "A_SHARE": lambda *_args: {},
            "HK_CONNECT": hk_builder,
        },
    )
    runner = StageCenterRunner(config, collectors={"HK_CONNECT": collector})
    result = runner._run_one(
        DueDecision(
            stage_id=stage_id,
            trade_date="20260925",
            status="DUE",
            scheduled_at=None,
            idempotency_key=f"r4-{stage_id}",
            calendar={
                "a_share": "NON_TRADING_DAY",
                "hk_securities": "FULL_TRADING_DAY",
                "hk_connect": "NON_TRADING_DAY",
            },
        )
    )
    return result, calls, source_root


def test_non_injected_run_one_consumes_bound_prior_payload_and_reads_back_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, calls, _source_root = _run_one(
        tmp_path, monkeypatch, stage_id="STAGE_0930_0935"
    )

    assert calls == ["HK_CONNECT"]
    assert result["status"] == "PARTIAL_WITH_ROWS", result
    assert result["markets"]["HK_CONNECT"]["selected_rows"] == 1
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False

    raw_store = RawStore(tmp_path / "raw")
    bundle = raw_store.read_verified_bundle("20260925", "STAGE_0930_0935")
    assert set(bundle["receipt"]["markets"]) == {"HK_CONNECT"}
    raw = bundle["receipt"]["markets"]["HK_CONNECT"]
    verified_raw = raw_store.verify_run(
        "20260925", "STAGE_0930_0935", "HK_CONNECT", raw["run_id"]
    )
    assert verified_raw["row_count"] == 1
    assert "hk_d1_source_trade_date=20260924" in verified_raw["source_evidence"]

    selection = SelectionStore(tmp_path / "selection").read_verified(
        "20260925", "STAGE_0930_0935", "HK_CONNECT"
    )
    assert selection["selection_status"] == "PARTIAL_WITH_ROWS"
    assert len(selection["rows"]) == 1
    assert "hk_d1_source_trade_date=20260924" in selection["source_evidence"]
    assert any(
        item.startswith("hk_d1_source_manifest_sha256=")
        for item in selection["source_evidence"]
    )
    assert any(
        item.startswith("hk_d1_source_receipt_sha256=")
        for item in selection["source_evidence"]
    )


def test_non_injected_run_one_rejects_source_trio_change_after_initial_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, calls, _source_root = _run_one(
        tmp_path,
        monkeypatch,
        stage_id="STAGE_0930_0935",
        mutate_after_binding=True,
    )

    assert calls == ["HK_CONNECT"]
    assert result["status"] != "READY"
    assert result["markets"]["HK_CONNECT"].get("selected_rows", 0) == 0, result
    assert "source identity changed" in str(result), result
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_non_injected_run_one_keeps_exact_0925_second_filter_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, calls, _source_root = _run_one(
        tmp_path, monkeypatch, stage_id="STAGE_0925"
    )

    assert calls == []
    assert result["status"] != "READY"
    assert "second-filter root is required" in str(result)


def test_raw_bundle_publish_and_verify_use_date_derived_market_set(tmp_path: Path) -> None:
    store = RawStore(tmp_path / "raw")

    hk = store.publish(
        trade_date="20260925",
        stage_id="STAGE_0930_0935",
        market="HK_CONNECT",
        source_id="fixture-hk",
        source_status="CANNOT_CONFIRM",
        rows=(),
        requested_rows=0,
    )
    bundle = store.publish_bundle(
        trade_date="20260925",
        stage_id="STAGE_0930_0935",
        status="CANNOT_CONFIRM",
        markets={"HK_CONNECT": hk},
    )
    assert set(bundle["markets"]) == {"HK_CONNECT"}
    assert set(
        store.read_verified_bundle("20260925", "STAGE_0930_0935")["receipt"]["markets"]
    ) == {"HK_CONNECT"}

    a = store.publish(
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        market="A_SHARE",
        source_id="fixture-a",
        source_status="CANNOT_CONFIRM",
        rows=(),
        requested_rows=0,
    )
    hk_dual = store.publish(
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        market="HK_CONNECT",
        source_id="fixture-hk-dual",
        source_status="CANNOT_CONFIRM",
        rows=(),
        requested_rows=0,
    )
    with pytest.raises(RawStoreError, match="bundle market set mismatch"):
        store.publish_bundle(
            trade_date="20260924",
            stage_id="STAGE_0930_0935",
            status="CANNOT_CONFIRM",
            markets={"HK_CONNECT": hk_dual},
        )
    full = store.publish_bundle(
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        status="CANNOT_CONFIRM",
        markets={"A_SHARE": a, "HK_CONNECT": hk_dual},
    )
    assert set(full["markets"]) == {"A_SHARE", "HK_CONNECT"}

    with pytest.raises(RawStoreError):
        store.publish_bundle(
            trade_date="20261001",
            stage_id="STAGE_0930_0935",
            status="CANNOT_CONFIRM",
            markets={},
        )
    with pytest.raises(RawStoreError):
        store.publish_bundle(
            trade_date="20270104",
            stage_id="STAGE_0930_0935",
            status="CANNOT_CONFIRM",
            markets={},
        )
