"""Actual closure-r1 registry route for the bounded manager PyTDX lane."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling import executor_registry as registry_module
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.executor_registry import (
    FixedExecutorRegistry,
    WorkloadExecutionError,
)


APP_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = APP_ROOT / "contracts/runtime_workloads.json"
DATE = "20260929"
MODE = "PYTDX_LATE_OBSERVATION"
PYTDX_PYTHON = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/runtime/venvs/v4-hk02/bin/python"
)
CHILD_APP_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/20260929-manager-pytdx-close-r1/app"
)
CHILD_SHA256 = "84b584713fdb1513379dd2513735d5f3a2e23cdfff9f07756526f7592de339e1"
PROVIDER_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data"
)


def _request(slot: str) -> DispatchRequest:
    return DispatchRequest(DATE, DATE, DATE, slot, DispatchMode.LIVE)


def _workload(name: str):
    catalog = load_workload_catalog(CATALOG_PATH)
    return next(item for item in catalog.workloads if item.workload_id == name)


def _materialized_child(app: Path, state: Path, source_date: str) -> dict:
    target_date = "20260930"
    lane = state / "workbench_research" / source_date
    lane.mkdir(parents=True)
    artifact_ref = f"workbench_research/{source_date}/close_recapture.json"
    receipt_ref = f"workbench_research/{source_date}/close_recapture.receipt.json"
    snapshot_ref = f"workbench_research/{source_date}/close_recapture.snapshot.json"
    candidate_ref = f"workbench_research/{source_date}/close_recapture.candidates.json"
    flags = {
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }

    def write(ref: str, payload: dict) -> tuple[bytes, str]:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        (state / ref).write_bytes(raw)
        return raw, hashlib.sha256(raw).hexdigest()

    snapshot, snapshot_sha = write(snapshot_ref, {
        "schema_version": "v4.manager_close_recapture_pytdx_snapshot.v1",
        "source_trade_date": source_date,
        "stage_id": "STAGE_1545_1555",
    })
    candidate, candidate_sha = write(candidate_ref, {
        "schema_version": "v4.manager_close_recapture_candidate_overlay.v1",
        "source_trade_date": source_date,
        "target_trade_date": target_date,
        "rows": [{"symbol": "HK.00001", "candidate_status": "OBSERVATION_ONLY"}],
    })
    del snapshot, candidate
    artifact_payload = {
        "schema_version": "v4.manager_close_recapture.v1",
        "source_trade_date": source_date,
        "plan_trade_date": target_date,
        "capture_mode": "LATE_OBSERVATION",
        "observation_type": "PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION",
        "pool": {"trade_date": source_date},
        "source": {"provider": "pytdx_exhq", "source_id": "pytdx"},
        "bar_window": {"stage_id": "STAGE_1545_1555"},
        "snapshot": {"artifact_ref": snapshot_ref, "sha256": snapshot_sha},
        "candidate_overlay": {
            "artifact_ref": candidate_ref,
            "sha256": candidate_sha,
            "count": 1,
        },
        **flags,
    }
    artifact_raw, artifact_sha = write(artifact_ref, artifact_payload)
    receipt_payload = {
        "schema_version": "v4.manager_close_recapture_receipt.v1",
        "source_trade_date": source_date,
        "target_trade_date": target_date,
        "artifact_ref": artifact_ref,
        "artifact_sha256": artifact_sha,
        "snapshot_ref": snapshot_ref,
        "snapshot_sha256": snapshot_sha,
        "candidate_overlay_ref": candidate_ref,
        "candidate_overlay_sha256": candidate_sha,
        **flags,
    }
    receipt_raw, receipt_sha = write(receipt_ref, receipt_payload)
    del artifact_raw, receipt_raw
    module_path = app / "ops/materialize_manager_close_discovery.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("# simulated child source identity\n", encoding="utf-8")
    module_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    return {
        "schema_version": "v4.manager_close_recapture_result.v1",
        "status": "MATERIALIZED",
        "source_trade_date": source_date,
        "plan_trade_date": target_date,
        "module_origin": str(module_path),
        "module_sha256": module_sha,
        "state_root": str(state.resolve()),
        "capture_mode": "LATE_OBSERVATION",
        "artifact_ref": artifact_ref,
        "receipt_ref": receipt_ref,
        "artifact_sha256": artifact_sha,
        "receipt_sha256": receipt_sha,
        "snapshot_ref": snapshot_ref,
        "snapshot_sha256": snapshot_sha,
        "candidate_overlay_ref": candidate_ref,
        "candidate_overlay_sha256": candidate_sha,
        "candidate_count": 1,
        **flags,
    }


def _registry(tmp_path: Path, monkeypatch, runner):
    universe = tmp_path / "universe"
    shared_store = universe / ".runtime/data"
    data = tmp_path / "data"
    state = tmp_path / "manager-state"
    child = tmp_path / "child-app"
    provider = tmp_path / "provider"
    for path in (universe, shared_store, data, state, child, provider):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("V4_MANAGER_CLOSE_CAPTURE_MODE", MODE)
    monkeypatch.setenv("V4_MANAGER_MATERIALIZER_APP_ROOT", str(child))
    monkeypatch.setenv("V4_MANAGER_MATERIALIZER_SHA256", "0" * 64)
    monkeypatch.setenv("V4_MANAGER_RESEARCH_STATE_ROOT", str(state))
    monkeypatch.setenv("V4_HK_0_2_REAL_PYTHON", str(PYTDX_PYTHON))
    monkeypatch.setenv("V4_SHARED_PACKAGE_ROOT", str(provider))
    return FixedExecutorRegistry(
        data_root=data,
        shared_data_root=shared_store,
        hk_universe_root=universe,
        shared_package_root=provider,
        shared_futu_python_executable=sys.executable,
        repo_root=APP_ROOT,
        runner=runner,
    ), child, state, universe, provider


@pytest.mark.parametrize(
    "stage_status,recapture_valid,expect_outer_success",
    [
        ("SUCCEEDED", True, True),
        ("FAILED", True, False),
        ("SUCCEEDED", False, False),
        ("FAILED", False, False),
    ],
)
def test_candidate_registry_routes_live_1555_to_same_date_pytdx_recapture(
    tmp_path, monkeypatch, stage_status, recapture_valid, expect_outer_success
):
    calls: list[tuple[list[str], dict]] = []
    materializer = {}
    context: dict[str, Path] = {}

    def runner(command, *, cwd, timeout_seconds, env):
        calls.append((command, {"cwd": cwd, "timeout_seconds": timeout_seconds, "env": env}))
        module = command[2]
        if module == "ops.run_stage_center_milestone":
            return subprocess.CompletedProcess(
                command, 0 if stage_status == "SUCCEEDED" else 1,
                stdout=json.dumps({"status": stage_status, "trade_date": DATE}),
                stderr="" if stage_status == "SUCCEEDED" else "stage preflight failed",
            )
        if module == "ops.materialize_manager_close_discovery":
            app, state = context["child"], context["state"]
            materializer.update(_materialized_child(app, state, DATE))
            if not recapture_valid:
                materializer["status"] = "INVALID_STATUS"
            return subprocess.CompletedProcess(command, 0, json.dumps(materializer), "")
        raise AssertionError(f"unexpected candidate dispatcher child: {module}")

    registry, child, state, universe, _provider = _registry(tmp_path, monkeypatch, runner)
    selection_root = tmp_path / "stage-selection"
    selection_root.mkdir()
    registry.stage_selection_root = selection_root
    context.update(child=child, state=state)
    module_path = child / "ops/materialize_manager_close_discovery.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("# simulated child source identity\n", encoding="utf-8")
    sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    monkeypatch.setenv("V4_MANAGER_MATERIALIZER_SHA256", sha)
    work = _workload("fupan_review_start")
    if expect_outer_success:
        result = registry(work, _request("1555"))
        assert result["manager_close_recapture"]["status"] == "SUCCEEDED"
        assert result["status"] == "SUCCEEDED"
    else:
        with pytest.raises(WorkloadExecutionError) as caught:
            registry(work, _request("1555"))
        result = caught.value.result
        assert result["status"] == "FAILED"
        if recapture_valid:
            assert result["manager_close_recapture"]["status"] == "SUCCEEDED"
        else:
            assert result["manager_close_recapture"]["status"] == "FAILED"
        assert result["stage_readback_status"] == stage_status
    assert result["stage_readback_status"] == stage_status

    assert [command[0][2] for command in calls] == [
        "ops.run_stage_center_milestone",
        "ops.materialize_manager_close_discovery",
    ]
    recapture_command, recapture_call = calls[1]
    assert "--close-recapture" in recapture_command
    assert recapture_command[recapture_command.index("--trade-date") + 1] == DATE
    assert recapture_command[recapture_command.index("--universe-root") + 1] == str(universe)
    assert recapture_command[recapture_command.index("--state-root") + 1] == str(state)
    assert recapture_command[recapture_command.index("--app-root") + 1] == str(child)
    assert recapture_command[recapture_command.index("--pytdx-python") + 1] == str(PYTDX_PYTHON)
    assert recapture_command[recapture_command.index("--provider-root") + 1] == str(_provider)
    assert "--futu-python" not in recapture_command
    assert recapture_call["cwd"] == child
    assert recapture_call["env"]["RESEARCH_ONLY"] == "true"
    assert recapture_call["env"]["PRODUCTION_ALLOWED"] == "false"
    assert recapture_call["env"]["V4_MANAGER_CLOSE_CAPTURE_MODE"] == MODE
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def _hourly_registry(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def runner(command, *, cwd, timeout_seconds, env):
        calls.append(command)
        module = command[2]
        if module == "ops.run_zsxq_hourly_delta":
            body = {"status": "READY"}
        elif module == "ops.materialize_research_peripherals":
            body = {"status": "READY"}
        elif module == "ops.collect_hourly_research_input":
            body = {"status": "READY_WITH_RESEARCH_POOL", "row_count": 1}
        elif module == "ops.run_hourly_research":
            body = {"status": "READY", "row_count": 1}
        else:
            raise AssertionError(f"unexpected 1500/1530 child: {module}")
        return subprocess.CompletedProcess(command, 0, json.dumps(body), "")

    registry, *_ = _registry(tmp_path, monkeypatch, runner)
    monkeypatch.setattr(registry_module, "_audited_peripheral_degradation", lambda *_a, **_k: {})
    return registry, calls


def test_candidate_registry_1500_prepare_is_reuse_only_and_never_futu(tmp_path, monkeypatch):
    registry, calls = _hourly_registry(tmp_path, monkeypatch)
    result_1500 = registry(_workload("hourly_research"), _request("1500"))
    assert result_1500["manager_close_dependency"]["status"] == "SUCCEEDED"
    assert result_1500["manager_close_dependency"]["no_op"] is True
    assert result_1500["manager_close_dependency"]["reason"] == (
        "FUTU_UNIVERSE_PREPARE_SKIPPED_BY_PYTDX_LATE_OBSERVATION_MODE"
    )
    assert not any(command[2] == "ops.materialize_manager_close_discovery" for command in calls)


def test_candidate_registry_1530_capture_is_disabled_without_futu_child(tmp_path, monkeypatch):
    registry, calls = _hourly_registry(tmp_path, monkeypatch)
    result_1530 = registry(_workload("hourly_research"), _request("1530"))
    assert result_1530["status"] == "SUCCEEDED"
    assert result_1530["no_op"] is True
    assert result_1530["reason"] == "1530_CAPTURE_DISABLED_BY_PYTDX_LATE_OBSERVATION_MODE"
    assert calls == []


@pytest.mark.parametrize("stage_status", ["SUCCEEDED", "FAILED"])
def test_candidate_fupan_review_start_1555_invokes_pytdx_independently_of_stage_readback(
    tmp_path, monkeypatch, stage_status
):
    calls: list[tuple[list[str], dict]] = []
    materializer: dict = {}
    context: dict[str, Path] = {}

    def runner(command, *, cwd, timeout_seconds, env):
        calls.append((command, {"cwd": cwd, "timeout_seconds": timeout_seconds, "env": env}))
        module = command[2]
        if module == "ops.run_stage_center_milestone":
            exit_code = 0 if stage_status == "SUCCEEDED" else 1
            body = {"status": stage_status, "date": DATE, "node": "FUPAN_REVIEW_START"}
            return subprocess.CompletedProcess(
                command, exit_code, json.dumps(body),
                "" if exit_code == 0 else "stage readback receipt unavailable",
            )
        if module == "ops.materialize_manager_close_discovery":
            child_result = _materialized_child(context["child"], context["state"], DATE)
            materializer.update(child_result)
            return subprocess.CompletedProcess(command, 0, json.dumps(materializer), "")
        raise AssertionError(f"unexpected fupan-review candidate child: {module}")

    registry, child, state, universe, _provider = _registry(tmp_path, monkeypatch, runner)
    stage_selection_root = tmp_path / "stage-selection"
    stage_selection_root.mkdir()
    registry.stage_selection_root = stage_selection_root
    context.update(child=child, state=state)
    module_path = child / "ops/materialize_manager_close_discovery.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("# simulated child source identity\n", encoding="utf-8")
    monkeypatch.setenv("V4_MANAGER_MATERIALIZER_SHA256", hashlib.sha256(module_path.read_bytes()).hexdigest())

    workload = _workload("fupan_review_start")
    if stage_status == "SUCCEEDED":
        result = registry(workload, _request("1555"))
        assert result["status"] == "SUCCEEDED"
    else:
        with pytest.raises(WorkloadExecutionError) as caught:
            registry(workload, _request("1555"))
        result = caught.value.result
        assert result["status"] == "FAILED"

    assert result["stage_readback_status"] == stage_status
    assert result["manager_close_recapture_status"] == "SUCCEEDED"
    assert result["manager_close_recapture"]["status"] == "SUCCEEDED"
    assert [call[0][2] for call in calls] == [
        "ops.run_stage_center_milestone",
        "ops.materialize_manager_close_discovery",
    ]
    recapture_command, recapture_call = calls[1]
    assert "--close-recapture" in recapture_command
    assert recapture_command[recapture_command.index("--trade-date") + 1] == DATE
    assert recapture_command[recapture_command.index("--universe-root") + 1] == str(universe)
    assert "--futu-python" not in recapture_command
    assert recapture_call["cwd"] == child
    assert recapture_call["env"]["RESEARCH_ONLY"] == "true"
    assert recapture_call["env"]["PRODUCTION_ALLOWED"] == "false"
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False
