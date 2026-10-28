"""Daily 15:55 PyTDX recapture binding after the existing Stage owner succeeds."""

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling import manager_close_executor as manager_close
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry, WorkloadExecutionError


HK = ZoneInfo("Asia/Hong_Kong")
TRADE_DATE = "20260928"
STATE_FLAGS = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _request(slot: str, mode: DispatchMode = DispatchMode.LIVE) -> DispatchRequest:
    return DispatchRequest(
        scheduled_date=TRADE_DATE,
        business_date=TRADE_DATE,
        target_date=TRADE_DATE,
        slot=slot,
        mode=mode,
    )


def _env(monkeypatch, tmp_path):
    app = APP_ROOT.resolve()
    state = tmp_path / "manager-state"
    universe = tmp_path / "v3_shared_data"
    store = universe / ".runtime/data"
    provider = app / "upstreams/v3_shared_data"
    for path in (state, store, provider):
        path.mkdir(parents=True, exist_ok=True)
    materializer = app / "ops/materialize_manager_close_discovery.py"
    monkeypatch.setenv("V4_MANAGER_CLOSE_CAPTURE_MODE", "PYTDX_LATE_OBSERVATION")
    monkeypatch.setenv("V4_MANAGER_MATERIALIZER_APP_ROOT", str(app))
    monkeypatch.setenv("V4_MANAGER_MATERIALIZER_SHA256", hashlib.sha256(materializer.read_bytes()).hexdigest())
    monkeypatch.setenv("V4_MANAGER_RESEARCH_STATE_ROOT", str(state))
    monkeypatch.setenv("V35_HK_0_2_REAL_PYTHON", sys.executable)
    monkeypatch.setenv("V35_SHARED_PACKAGE_ROOT", str(provider))
    return app, state, universe, store, provider, materializer


def _published_child_result(app: Path, state: Path, materializer: Path) -> dict:
    base = state / "workbench_research" / TRADE_DATE
    (base / "inputs").mkdir(parents=True, exist_ok=True)
    snapshot_ref = f"workbench_research/{TRADE_DATE}/inputs/close_recapture_pytdx.json"
    candidate_ref = f"workbench_research/{TRADE_DATE}/close_recapture.candidates.json"
    artifact_ref = f"workbench_research/{TRADE_DATE}/close_recapture.json"
    receipt_ref = f"workbench_research/{TRADE_DATE}/close_recapture.receipt.json"
    snapshot = {
        "schema_version": "v4.manager_close_recapture_pytdx_snapshot.v1",
        "source_trade_date": TRADE_DATE,
        "stage_id": "STAGE_1545_1555",
        "source_rows": [{"code": "HK.00001", "update_time": "2026-09-28 15:46:00"}],
        **STATE_FLAGS,
    }
    candidate = {
        "schema_version": "v4.manager_close_recapture_candidate_overlay.v1",
        "source_trade_date": TRADE_DATE,
        "target_trade_date": "20260929",
        "rows": [{"symbol": "HK.00001", "observed_at": "2026-09-28T15:46:00+08:00"}],
        **STATE_FLAGS,
    }
    snapshot_raw = json.dumps(snapshot, sort_keys=True).encode()
    candidate_raw = json.dumps(candidate, sort_keys=True).encode()
    (state / snapshot_ref).write_bytes(snapshot_raw)
    (state / candidate_ref).write_bytes(candidate_raw)
    snapshot_sha = hashlib.sha256(snapshot_raw).hexdigest()
    candidate_sha = hashlib.sha256(candidate_raw).hexdigest()
    payload = {
        "schema_version": "v4.manager_close_recapture.v1",
        "status": "READY",
        "source_trade_date": TRADE_DATE,
        "target_trade_date": "20260929",
        "plan_trade_date": "20260929",
        "market": "HK_CONNECT",
        "capture_mode": "LATE_OBSERVATION",
        "observation_type": "PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION",
        "pool": {"trade_date": TRADE_DATE, "run_id": "pool-run"},
        "source": {"provider": "pytdx_exhq", "source_id": "pytdx"},
        "bar_window": {"stage_id": "STAGE_1545_1555"},
        "request": {"started_at": "2026-09-29T00:01:00+08:00",
                    "captured_at": "2026-09-29T00:01:01+08:00",
                    "available_at": "2026-09-29T00:01:02+08:00"},
        "snapshot": {"artifact_ref": snapshot_ref, "sha256": snapshot_sha, "row_count": 1},
        "candidate_overlay": {"artifact_ref": candidate_ref, "sha256": candidate_sha, "count": 1},
        **STATE_FLAGS,
    }
    artifact_raw = json.dumps(payload, sort_keys=True).encode()
    (state / artifact_ref).write_bytes(artifact_raw)
    artifact_sha = hashlib.sha256(artifact_raw).hexdigest()
    receipt = {
        "schema_version": "v4.manager_close_recapture_receipt.v1",
        "status": "READY",
        "source_trade_date": TRADE_DATE,
        "target_trade_date": "20260929",
        "artifact_ref": artifact_ref,
        "artifact_sha256": artifact_sha,
        "snapshot_ref": snapshot_ref,
        "snapshot_sha256": snapshot_sha,
        "candidate_overlay_ref": candidate_ref,
        "candidate_overlay_sha256": candidate_sha,
        **STATE_FLAGS,
    }
    receipt_raw = json.dumps(receipt, sort_keys=True).encode()
    (state / receipt_ref).write_bytes(receipt_raw)
    return {
        "schema_version": "v4.manager_close_recapture_result.v1",
        "status": "MATERIALIZED",
        "source_trade_date": TRADE_DATE,
        "plan_trade_date": "20260929",
        "capture_mode": "LATE_OBSERVATION",
        "module_origin": str(materializer.resolve()),
        "module_sha256": hashlib.sha256(materializer.read_bytes()).hexdigest(),
        "state_root": str(state.resolve()),
        "artifact_ref": artifact_ref,
        "artifact_sha256": artifact_sha,
        "receipt_ref": receipt_ref,
        "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
        "snapshot_ref": snapshot_ref,
        "snapshot_sha256": snapshot_sha,
        "candidate_overlay_ref": candidate_ref,
        "candidate_overlay_sha256": candidate_sha,
        "candidate_count": 1,
        **STATE_FLAGS,
    }


def test_1555_success_runs_only_existing_pytdx_recapture_and_reads_store_back(tmp_path, monkeypatch):
    app, state, universe, store, provider, materializer = _env(monkeypatch, tmp_path)
    result_payload = _published_child_result(app, state, materializer)
    calls = []

    def runner(command, *, cwd=None, timeout_seconds=0, env=None):
        module = command[2]
        arguments = command[3:]
        calls.append((module, arguments, cwd, timeout_seconds, dict(env or {})))
        if module == "ops.materialize_stage_workbench":
            return SimpleNamespace(returncode=0, stdout='{"status":"READY"}', stderr="")
        assert module == "ops.materialize_manager_close_discovery"
        return SimpleNamespace(returncode=0, stdout=json.dumps(result_payload), stderr="")

    manager = FixedExecutorRegistry(
        data_root=tmp_path / "v35-data",
        shared_data_root=store,
        hk_universe_root=universe,
        shared_package_root=provider,
        timeout_seconds=600,
        repo_root=APP_ROOT,
        runner=runner,
    )
    out = manager._stage_workbench(_request("1555"))

    assert [call[0] for call in calls] == [
        "ops.materialize_stage_workbench",
        "ops.materialize_manager_close_discovery",
    ]
    stage_call, capture_call = calls
    assert "--stage" in stage_call[1] and stage_call[1][stage_call[1].index("--stage") + 1] == "STAGE_1545_1555"
    args = capture_call[1]
    assert "--close-recapture" in args
    assert args[args.index("--trade-date") + 1] == TRADE_DATE
    assert args[args.index("--universe-root") + 1] == str(universe.resolve())
    assert args[args.index("--state-root") + 1] == str(state.resolve())
    assert args[args.index("--pytdx-python") + 1] == sys.executable
    assert args[args.index("--provider-root") + 1] == str(provider.resolve())
    assert not any("futu" in arg.lower() for arg in args)
    assert capture_call[2] == app
    assert capture_call[3] == 420
    assert capture_call[4]["PRODUCTION_ALLOWED"] == "false"
    assert capture_call[4]["BUY_GATE_UPDATED"] == "false"
    assert capture_call[4]["ORDERS_SENT"] == "false"
    assert out["status"] == "SUCCEEDED"
    assert out["manager_close_recapture"]["status"] == "SUCCEEDED"
    assert out["manager_close_recapture"]["materializer"]["source_trade_date"] == TRADE_DATE
    assert out["modules"][-1] == "ops.materialize_manager_close_discovery"


def test_1555_pytdx_recapture_runs_after_stage_failure_without_upgrading_stage(tmp_path, monkeypatch):
    app, state, universe, store, provider, materializer = _env(monkeypatch, tmp_path)
    result_payload = _published_child_result(app, state, materializer)
    calls = []

    def runner(command, *, cwd=None, timeout_seconds=0, env=None):
        module = command[2]
        calls.append(module)
        if module == "ops.materialize_stage_workbench":
            return SimpleNamespace(returncode=1, stdout="", stderr="stage failed")
        return SimpleNamespace(returncode=0, stdout=json.dumps(result_payload), stderr="")

    manager = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=store,
        hk_universe_root=universe,
        shared_package_root=provider,
        timeout_seconds=600,
        repo_root=APP_ROOT,
        runner=runner,
    )
    out = manager._stage_workbench(_request("1555"))
    assert out["status"] == "FAILED"
    assert out["manager_close_recapture"]["status"] == "SUCCEEDED"
    assert out["manager_close_recapture"]["stage_workbench_status"] == "FAILED"
    assert calls == [
        "ops.materialize_stage_workbench",
        "ops.materialize_manager_close_discovery",
    ]


def test_pytdx_mode_never_dispatches_old_1530_futu_capture(monkeypatch):
    monkeypatch.setenv("V4_MANAGER_CLOSE_CAPTURE_MODE", "PYTDX_LATE_OBSERVATION")
    calls = []
    manager = SimpleNamespace(_run=lambda *args, **kwargs: calls.append((args, kwargs)))
    out = manager_close._manager_close_1530(manager, _request("1530"))
    assert out["status"] == "NOT_APPLICABLE"
    assert out["no_op"] is True
    assert out["reason"] == "1530_CAPTURE_DISABLED_BY_PYTDX_LATE_OBSERVATION_MODE"
    assert calls == []


def test_pytdx_mode_skips_1500_futu_universe_prepare(monkeypatch):
    monkeypatch.setenv("V4_MANAGER_CLOSE_CAPTURE_MODE", "PYTDX_LATE_OBSERVATION")
    calls = []
    manager = SimpleNamespace(_run=lambda *args, **kwargs: calls.append((args, kwargs)))
    out = manager_close._manager_close_1530(manager, _request("1500"), prepare_only=True)
    assert out["status"] == "NOT_APPLICABLE"
    assert out["reason"] == "FUTU_UNIVERSE_PREPARE_SKIPPED_BY_PYTDX_LATE_OBSERVATION_MODE"
    assert out["snapshot_requested"] is False
    assert out["candidate_publication_requested"] is False
    assert calls == []
