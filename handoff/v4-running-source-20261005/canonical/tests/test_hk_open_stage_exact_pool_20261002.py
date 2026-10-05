from __future__ import annotations

import json
from pathlib import Path

import pytest

import stage_center.runner as stage_runner
from infrastructure.preselection_pool_store import PreselectionPoolStore
from stage_center.calendar import TradingDayState


TARGET_DATE = "20261002"
TARGET_SIGNAL_DATE = "20260930"
CROSS_DATE_TARGET = "20261005"
CROSS_DATE_SIGNAL_DATE = "20261002"
FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _states_for_test(trade_date: str) -> dict[str, TradingDayState]:
    if trade_date == TARGET_DATE:
        return {
            "a_share": TradingDayState.NON_TRADING_DAY,
            "hk_securities": TradingDayState.FULL_TRADING_DAY,
            "hk_connect": TradingDayState.NON_TRADING_DAY,
        }
    if trade_date == "20261001":
        return {
            "a_share": TradingDayState.NON_TRADING_DAY,
            "hk_securities": TradingDayState.NON_TRADING_DAY,
            "hk_connect": TradingDayState.NON_TRADING_DAY,
        }
    return {
        "a_share": TradingDayState.FULL_TRADING_DAY,
        "hk_securities": TradingDayState.FULL_TRADING_DAY,
        "hk_connect": TradingDayState.FULL_TRADING_DAY,
    }


def _pool_payload(
    trade_date: str,
    signal_date: str,
    *,
    row_target_date: str | None = None,
) -> dict:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "target_date": trade_date,
        "signal_date": signal_date,
        "pool_id": "hkconnect_d1_top100",
        "display_name": "HK Connect D-1 Top100",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": "read-only-test-fixture",
        "source_sha256": "a" * 64,
        "stage_selection_eligible": True,
        "rows": [
            {
                "market": "HK",
                "pool_id": "hkconnect_d1_top100",
                "pool_rank": rank,
                "signal_date": signal_date,
                "code": f"HK.{rank:05d}",
                "symbol": f"HK.{rank:05d}",
                "target_date": row_target_date or trade_date,
            }
            for rank in range(1, 101)
        ],
        "cannot_confirm": [],
        **FLAGS,
    }


def _split_date_states_for_test(trade_date: str) -> dict[str, TradingDayState]:
    if trade_date in {CROSS_DATE_TARGET, CROSS_DATE_SIGNAL_DATE}:
        return {
            "a_share": TradingDayState.NON_TRADING_DAY,
            "hk_securities": TradingDayState.FULL_TRADING_DAY,
            "hk_connect": TradingDayState.NON_TRADING_DAY,
        }
    if trade_date == TARGET_SIGNAL_DATE:
        return {
            "a_share": TradingDayState.FULL_TRADING_DAY,
            "hk_securities": TradingDayState.FULL_TRADING_DAY,
            "hk_connect": TradingDayState.FULL_TRADING_DAY,
        }
    return {
        "a_share": TradingDayState.NON_TRADING_DAY,
        "hk_securities": TradingDayState.NON_TRADING_DAY,
        "hk_connect": TradingDayState.NON_TRADING_DAY,
    }


def _split_date_pool_payload(trade_date: str, signal_date: str) -> dict:
    source_run_id = f"synthetic-hk-d1-{trade_date}-{signal_date}"
    source_sha256 = "b" * 64
    source_manifest_sha256 = "c" * 64
    source_receipt_sha256 = "d" * 64
    payload = _pool_payload(trade_date, signal_date)
    payload.update(
        {
            "source_run_id": source_run_id,
            "source_sha256": source_sha256,
            "source_manifest_sha256": source_manifest_sha256,
            "source_receipt_sha256": source_receipt_sha256,
            "historical_provenance": {
                "schema_version": "v4.hk_d1_split_date_provenance.v1",
                "price_signal_date": CROSS_DATE_SIGNAL_DATE,
                "eligibility_source_date": TARGET_SIGNAL_DATE,
                "eligibility_source_run_id": "synthetic-hk-connect-eligibility-20260930",
                "eligibility_source_artifact_sha256": "a" * 64,
                "d1_source_run_id": source_run_id,
                "d1_source_artifact_sha256": source_sha256,
                "d1_source_manifest_sha256": source_manifest_sha256,
                "d1_source_receipt_sha256": source_receipt_sha256,
                "eligibility_source_captured_at": "2026-09-30T16:00:00+08:00",
            },
        }
    )
    return payload


def _materialize_pool(root: Path, trade_date: str, signal_date: str, *, row_target_date: str | None = None) -> Path:
    store = PreselectionPoolStore(root)
    store.materialize(
        _pool_payload(trade_date, signal_date, row_target_date=row_target_date)
    )
    return root / "preselection_pools" / trade_date / "hkconnect_d1_top100.json"


def _bind(root: Path, trade_date: str) -> stage_runner.StageUniverseBinding:
    return stage_runner._build_hk_stage_binding(
        root,
        trade_date,
        preselection_source_root=root,
    )


def test_hk_open_connect_closed_binds_exact_20261002_pool_and_signal(monkeypatch, tmp_path):
    monkeypatch.setattr(stage_runner, "resolve_market_states", _states_for_test)
    target_pool = _materialize_pool(tmp_path, TARGET_DATE, TARGET_SIGNAL_DATE)

    binding = _bind(tmp_path, TARGET_DATE)
    snapshot = PreselectionPoolStore(tmp_path).read_pool_snapshot(
        TARGET_DATE, "hkconnect_d1_top100"
    )

    assert binding.status == "READY"
    assert binding.trade_date == TARGET_DATE
    assert binding.role == "HK_CONNECT_D1_TOP100"
    assert len(binding.codes) == 100
    assert len(set(binding.codes)) == 100
    assert binding.sha256 == snapshot["artifact_raw_sha256"]
    assert f"hk_d1_json={target_pool}" in binding.evidence
    assert f"hk_d1_sha256={snapshot['artifact_raw_sha256']}" in binding.evidence
    assert {row["signal_date"] for row in snapshot["artifact"]["rows"]} == {
        TARGET_SIGNAL_DATE
    }


def test_hk_open_connect_closed_does_not_fall_back_to_older_target_pool(monkeypatch, tmp_path):
    from stage_center.runner import RunnerError

    monkeypatch.setattr(stage_runner, "resolve_market_states", _states_for_test)
    _materialize_pool(tmp_path, "20260930", "20260929")

    with pytest.raises(RunnerError):
        _bind(tmp_path, TARGET_DATE)


def test_hk_open_exact_pool_rejects_wrong_row_target_date(monkeypatch, tmp_path):
    from stage_center.runner import RunnerError

    monkeypatch.setattr(stage_runner, "resolve_market_states", _states_for_test)
    _materialize_pool(
        tmp_path,
        TARGET_DATE,
        TARGET_SIGNAL_DATE,
        row_target_date="20260930",
    )

    with pytest.raises(RunnerError, match="row target_date mismatch"):
        _bind(tmp_path, TARGET_DATE)


def test_hk_open_exact_pool_rejects_artifact_sha_mismatch(monkeypatch, tmp_path):
    from stage_center.runner import RunnerError

    monkeypatch.setattr(stage_runner, "resolve_market_states", _states_for_test)
    artifact = _materialize_pool(tmp_path, TARGET_DATE, TARGET_SIGNAL_DATE)
    artifact.write_bytes(artifact.read_bytes() + b" ")

    with pytest.raises(RunnerError):
        _bind(tmp_path, TARGET_DATE)


def test_normal_hk_connect_day_keeps_exact_d1_binding(monkeypatch, tmp_path):
    monkeypatch.setattr(stage_runner, "resolve_market_states", _states_for_test)
    _materialize_pool(tmp_path, "20260930", "20260929")

    binding = _bind(tmp_path, "20260930")

    assert binding.status == "READY"
    assert binding.trade_date == "20260930"
    assert binding.role == "HK_CONNECT_D1_TOP100"
    assert len(binding.codes) == len(set(binding.codes)) == 100


def test_hk_open_after_connect_closure_accepts_exact_security_signal_with_provenance(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(stage_runner, "resolve_market_states", _split_date_states_for_test)
    PreselectionPoolStore(tmp_path).materialize(
        _split_date_pool_payload(CROSS_DATE_TARGET, CROSS_DATE_SIGNAL_DATE)
    )

    binding = _bind(tmp_path, CROSS_DATE_TARGET)
    snapshot = PreselectionPoolStore(tmp_path).read_pool_snapshot(
        CROSS_DATE_TARGET, "hkconnect_d1_top100"
    )

    assert binding.status == "READY"
    assert binding.trade_date == CROSS_DATE_TARGET
    assert len(binding.codes) == len(set(binding.codes)) == 100
    assert binding.sha256 == snapshot["artifact_raw_sha256"]
    assert {row["signal_date"] for row in snapshot["artifact"]["rows"]} == {
        CROSS_DATE_SIGNAL_DATE
    }


def test_hk_open_after_connect_closure_rejects_connect_only_signal(monkeypatch, tmp_path):
    from stage_center.runner import RunnerError

    monkeypatch.setattr(stage_runner, "resolve_market_states", _split_date_states_for_test)
    PreselectionPoolStore(tmp_path).materialize(
        _split_date_pool_payload(CROSS_DATE_TARGET, TARGET_SIGNAL_DATE)
    )

    with pytest.raises(RunnerError, match="envelope signal_date mismatch"):
        _bind(tmp_path, CROSS_DATE_TARGET)


def test_hk_open_after_connect_closure_requires_split_date_provenance(monkeypatch, tmp_path):
    from stage_center.runner import RunnerError

    monkeypatch.setattr(stage_runner, "resolve_market_states", _split_date_states_for_test)
    payload = _split_date_pool_payload(CROSS_DATE_TARGET, CROSS_DATE_SIGNAL_DATE)
    payload.pop("historical_provenance")
    PreselectionPoolStore(tmp_path).materialize(payload)

    with pytest.raises(RunnerError, match="split-date eligibility provenance missing"):
        _bind(tmp_path, CROSS_DATE_TARGET)


def test_hk_open_after_connect_closure_rejects_split_date_provenance_identity_mismatch(
    monkeypatch, tmp_path
):
    from stage_center.runner import RunnerError

    monkeypatch.setattr(stage_runner, "resolve_market_states", _split_date_states_for_test)
    payload = _split_date_pool_payload(CROSS_DATE_TARGET, CROSS_DATE_SIGNAL_DATE)
    payload["historical_provenance"]["d1_source_artifact_sha256"] = "e" * 64
    PreselectionPoolStore(tmp_path).materialize(payload)

    with pytest.raises(RunnerError, match="split-date provenance identity mismatch"):
        _bind(tmp_path, CROSS_DATE_TARGET)


def test_node_report_compaction_accepts_calendar_gate_market_list(capsys):
    from ops import run_stage_center_nodes as nodes

    message = "calendar gate retained as a list"
    payload = {
        "status": "NODES_COMPLETE",
        "trade_date": TARGET_DATE,
        "nodes": [
            {
                "stage_id": "PRECAPTURE_1550",
                "status": "SKIPPED_NON_TRADING_DAY",
                "error": message,
                "markets": ["HK_CONNECT"],
            }
        ],
        "padding": {f"diagnostic_{index:04d}": index for index in range(700)},
        **FLAGS,
    }

    nodes._print_json(payload)
    printed = json.loads(capsys.readouterr().out)

    assert printed["output_truncated"] is True
    assert printed["nodes"][0]["markets"]["HK_CONNECT"] == {
        "status": "SKIPPED_NON_TRADING_DAY",
        "first_error": message,
    }
    assert all(printed[flag] is False for flag in FLAGS)
