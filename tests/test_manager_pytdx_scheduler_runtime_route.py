"""The enabled 15:55 catalog workload independently runs the existing PyTDX owner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.executor_registry import (
    FixedExecutorRegistry,
    WorkloadExecutionError,
)


APP_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = APP_ROOT / "contracts/runtime_workloads.json"
DATE = "20260929"
CAPTURE_MODE = "PYTDX_LATE_OBSERVATION"
SAFETY_FLAGS = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _request() -> DispatchRequest:
    return DispatchRequest(DATE, DATE, DATE, "1555", DispatchMode.LIVE)


def _workload():
    catalog = load_workload_catalog(CATALOG_PATH)
    return next(item for item in catalog.workloads if item.workload_id == "fupan_review_start")


def _materialized_child(app: Path, state: Path) -> dict:
    target_date = "20260930"
    snapshot_ref = f"workbench_research/{DATE}/inputs/close_recapture_pytdx.json"
    candidate_ref = f"workbench_research/{DATE}/close_recapture.candidates.json"
    artifact_ref = f"workbench_research/{DATE}/close_recapture.json"
    receipt_ref = f"workbench_research/{DATE}/close_recapture.receipt.json"

    def write(ref: str, payload: dict) -> str:
        path = state / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    snapshot_sha = write(snapshot_ref, {
        "schema_version": "v4.manager_close_recapture_pytdx_snapshot.v1",
        "source_trade_date": DATE,
        "stage_id": "STAGE_1545_1555",
    })
    candidate_sha = write(candidate_ref, {
        "schema_version": "v4.manager_close_recapture_candidate_overlay.v1",
        "source_trade_date": DATE,
        "target_trade_date": target_date,
        "rows": [{"symbol": "HK.00001", "candidate_status": "OBSERVATION_ONLY"}],
    })
    artifact_sha = write(artifact_ref, {
        "schema_version": "v4.manager_close_recapture.v1",
        "source_trade_date": DATE,
        "plan_trade_date": target_date,
        "capture_mode": "LATE_OBSERVATION",
        "observation_type": "PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION",
        "pool": {"trade_date": DATE},
        "source": {"provider": "pytdx_exhq", "source_id": "pytdx"},
        "bar_window": {"stage_id": "STAGE_1545_1555"},
        "snapshot": {"artifact_ref": snapshot_ref, "sha256": snapshot_sha},
        "candidate_overlay": {
            "artifact_ref": candidate_ref,
            "sha256": candidate_sha,
            "count": 1,
        },
        **SAFETY_FLAGS,
    })
    receipt_sha = write(receipt_ref, {
        "schema_version": "v4.manager_close_recapture_receipt.v1",
        "source_trade_date": DATE,
        "target_trade_date": target_date,
        "artifact_ref": artifact_ref,
        "artifact_sha256": artifact_sha,
        "snapshot_ref": snapshot_ref,
        "snapshot_sha256": snapshot_sha,
        "candidate_overlay_ref": candidate_ref,
        "candidate_overlay_sha256": candidate_sha,
        **SAFETY_FLAGS,
    })
    module_path = app / "ops/materialize_manager_close_discovery.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("# controlled child identity for route regression\n", encoding="utf-8")
    return {
        "schema_version": "v4.manager_close_recapture_result.v1",
        "status": "MATERIALIZED",
        "source_trade_date": DATE,
        "plan_trade_date": target_date,
        "module_origin": str(module_path),
        "module_sha256": hashlib.sha256(module_path.read_bytes()).hexdigest(),
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
        **SAFETY_FLAGS,
    }


@pytest.mark.parametrize(
    "stage_status,recapture_valid,expect_outer_success",
    [
        ("SUCCEEDED", True, True),
        ("FAILED", True, False),
        ("SUCCEEDED", False, False),
        ("FAILED", False, False),
    ],
)
def test_catalog_fupan_review_start_1555_runs_independent_pytdx_recapture(
    tmp_path, monkeypatch, stage_status, recapture_valid, expect_outer_success
):
    calls = []
    paths = {
        "data": tmp_path / "data",
        "state": tmp_path / "manager-state",
        "universe": tmp_path / "universe",
        "provider": tmp_path / "provider",
        "app": tmp_path / "materializer-app",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    shared_store = paths["universe"] / ".runtime/data"
    shared_store.mkdir(parents=True)
    pytdx_python = tmp_path / "configured-pytdx-python"
    pytdx_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pytdx_python.chmod(0o755)
    module_path = paths["app"] / "ops/materialize_manager_close_discovery.py"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text("# controlled child identity for route regression\n", encoding="utf-8")

    monkeypatch.setenv("V4_MANAGER_CLOSE_CAPTURE_MODE", CAPTURE_MODE)
    monkeypatch.setenv("V4_MANAGER_MATERIALIZER_APP_ROOT", str(paths["app"]))
    monkeypatch.setenv(
        "V4_MANAGER_MATERIALIZER_SHA256",
        hashlib.sha256(module_path.read_bytes()).hexdigest(),
    )
    monkeypatch.setenv("V4_MANAGER_RESEARCH_STATE_ROOT", str(paths["state"]))
    monkeypatch.setenv("V35_HK_0_2_REAL_PYTHON", str(pytdx_python))
    monkeypatch.setenv("V35_SHARED_PACKAGE_ROOT", str(paths["provider"]))

    def runner(command, *, cwd, timeout_seconds, env):
        module = command[2]
        calls.append((command, cwd, timeout_seconds, env))
        if module == "ops.run_stage_center_milestone":
            succeeded = stage_status == "SUCCEEDED"
            return subprocess.CompletedProcess(
                command,
                0 if succeeded else 1,
                json.dumps({"status": stage_status, "date": DATE, "node": "FUPAN_REVIEW_START"}),
                "" if succeeded else "stage readback failed",
            )
        if module == "ops.materialize_manager_close_discovery":
            payload = _materialized_child(paths["app"], paths["state"])
            if not recapture_valid:
                payload["status"] = "INVALID_STATUS"
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        raise AssertionError(f"unexpected scheduler child: {module}")

    registry = FixedExecutorRegistry(
        data_root=paths["data"],
        shared_data_root=shared_store,
        hk_universe_root=paths["universe"],
        shared_package_root=paths["provider"],
        timeout_seconds=600,
        repo_root=APP_ROOT,
        runner=runner,
    )
    selection_root = tmp_path / "stage-selection"
    selection_root.mkdir()
    registry.stage_selection_root = selection_root
    workload = _workload()
    assert workload.enabled is True
    assert "1555" in workload.slots

    if expect_outer_success:
        result = registry(workload, _request())
        assert result["status"] == "SUCCEEDED"
    else:
        with pytest.raises(WorkloadExecutionError) as caught:
            registry(workload, _request())
        result = caught.value.result
        assert result["status"] == "FAILED"

    expected_recapture_status = "SUCCEEDED" if recapture_valid else "FAILED"
    assert result["stage_readback_status"] == stage_status
    assert result["manager_close_recapture_status"] == expected_recapture_status
    assert result["manager_close_recapture"]["status"] == expected_recapture_status
    assert [call[0][2] for call in calls] == [
        "ops.run_stage_center_milestone",
        "ops.materialize_manager_close_discovery",
    ]

    stage_call, recapture_call = calls
    assert stage_call[0][stage_call[0].index("--stage-id") + 1] == "STAGE_1545_1555"
    command, cwd, _timeout, child_env = recapture_call
    assert "--close-recapture" in command
    assert command[command.index("--trade-date") + 1] == DATE
    assert command[command.index("--state-root") + 1] == str(paths["state"])
    assert command[command.index("--universe-root") + 1] == str(paths["universe"])
    assert command[command.index("--app-root") + 1] == str(paths["app"])
    assert command[command.index("--pytdx-python") + 1] == str(pytdx_python)
    assert command[command.index("--provider-root") + 1] == str(paths["provider"])
    assert "--futu-python" not in command
    assert cwd == paths["app"]
    assert child_env["V4_MANAGER_CLOSE_CAPTURE_MODE"] == CAPTURE_MODE
    assert child_env["RESEARCH_ONLY"] == "true"
    assert child_env["PRODUCTION_ALLOWED"] == "false"
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False
