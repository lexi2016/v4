from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.executor_registry import (
    FixedExecutorRegistry,
    WorkloadExecutionError,
)
from ops import run_scheduled_slot as scheduled_slot
from ops import run_v4_macos_scheduler as scheduler


REPO = Path(__file__).resolve().parents[1]


def _request(slot: str) -> DispatchRequest:
    return DispatchRequest(
        scheduled_date="20260909",
        business_date="20260909",
        target_date="20260909",
        slot=slot,
        mode=DispatchMode.LIVE,
    )


def _workload(workload_id: str):
    return next(
        item for item in load_workload_catalog().workloads if item.workload_id == workload_id
    )


def test_registry_applies_a_override_only_and_preserves_timeout_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[float] = []

    def fake_panel(self, request: DispatchRequest, *, lane: str) -> dict[str, object]:
        del request
        return self._run("ops.macos_research_panel_daily", ["--lane", lane])

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, env
        calls.append(timeout_seconds)
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "READY"}), "")

    monkeypatch.setattr(FixedExecutorRegistry, "_research_panel_daily", fake_panel)
    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=REPO,
        runner=runner,
        timeout_seconds=600,
        a_daily_timeout_seconds=3600,
    )

    a_result = registry(_workload("research_panel_daily_a"), _request("1700"))
    hk_result = registry(_workload("research_panel_daily_hk"), _request("1720"))
    generic_result = registry._run("ops.generic_workload", [])

    assert a_result["status"] == "SUCCEEDED"
    assert hk_result["status"] == "SUCCEEDED"
    assert generic_result["status"] == "SUCCEEDED"
    assert calls == [3600.0, 600, 600]
    assert registry._active_workload_id is None

    timeout_calls: list[float] = []

    def timeout_runner(command, *, cwd, timeout_seconds, env):
        del cwd, env
        timeout_calls.append(timeout_seconds)
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    timeout_registry = FixedExecutorRegistry(
        data_root=tmp_path / "timeout-data",
        repo_root=REPO,
        runner=timeout_runner,
        timeout_seconds=600,
        a_daily_timeout_seconds=3600,
    )
    monkeypatch.setattr(FixedExecutorRegistry, "_research_panel_daily", fake_panel)
    with pytest.raises(WorkloadExecutionError) as caught:
        timeout_registry(_workload("research_panel_daily_a"), _request("1700"))

    assert timeout_calls == [3600.0]
    assert caught.value.result["status"] == "TIMEOUT"
    assert caught.value.result["exit_code"] == 124
    assert caught.value.result["exception_type"] == "TimeoutExpired"


@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf, -math.inf, True, "invalid"])
def test_registry_rejects_invalid_explicit_a_timeout(tmp_path: Path, value: object) -> None:
    with pytest.raises(ValueError, match="A_DAILY_TIMEOUT_SECONDS_INVALID"):
        FixedExecutorRegistry(
            data_root=tmp_path / "data",
            repo_root=REPO,
            a_daily_timeout_seconds=value,  # type: ignore[arg-type]
        )


def test_slot_and_scheduler_forward_optional_a_timeout_without_changing_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[dict[str, object]] = []

    class FakeRegistry:
        def __init__(self, **kwargs: object) -> None:
            captured.append(kwargs)

    receipt = SimpleNamespace(
        status="SUCCEEDED",
        run_id="run-1",
        receipt_path=None,
        selected_workload_ids=(),
        started_workload_ids=(),
        failure_class=None,
        retry_after=None,
        release_id=None,
        upstream_fingerprint=None,
        attempt=1,
        production_allowed=False,
        buy_gate_updated=False,
        orders_sent=False,
    )
    monkeypatch.setattr(scheduled_slot, "FixedExecutorRegistry", FakeRegistry)
    monkeypatch.setattr(scheduled_slot, "dispatch_due", lambda *args, **kwargs: receipt)

    scheduled_slot.run_scheduled_slot(
        data_root=tmp_path / "data",
        slot="1700",
        business_date="20260909",
        scheduled_date="20260909",
        target_date="20260909",
        ledger_root=tmp_path / "ledger",
        a_daily_timeout_seconds=3600,
        dry_run=True,
    )
    scheduled_slot.run_scheduled_slot(
        data_root=tmp_path / "data-omitted",
        slot="1720",
        business_date="20260909",
        scheduled_date="20260909",
        target_date="20260909",
        ledger_root=tmp_path / "ledger-omitted",
        dry_run=True,
    )

    assert captured[0]["timeout_seconds"] == 600.0
    assert captured[0]["a_daily_timeout_seconds"] == 3600
    assert captured[1]["timeout_seconds"] == 600.0
    assert captured[1]["a_daily_timeout_seconds"] is None

    captured.clear()
    assert scheduled_slot.main(
        [
            "--data-root", str(tmp_path / "slot-cli-data"),
            "--ledger-root", str(tmp_path / "slot-cli-ledger"),
            "--slot", "1700",
            "--date", "20260909",
            "--a-daily-timeout-seconds", "3600",
            "--dry-run",
        ]
    ) == 0
    assert captured[0]["timeout_seconds"] == 600.0
    assert captured[0]["a_daily_timeout_seconds"] == 3600.0

    scheduler_capture: dict[str, object] = {}
    monkeypatch.setattr(scheduler, "apply_research_proxy_environment", lambda: {})
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260909", "1700"))

    def fake_slot(**kwargs: object) -> dict[str, object]:
        scheduler_capture.update(kwargs)
        return {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(scheduler, "run_scheduled_slot", fake_slot)
    assert scheduler.main(
        [
            "--data-root", str(tmp_path / "scheduler-data"),
            "--ledger-root", str(tmp_path / "scheduler-ledger"),
            "--slot", "1700",
            "--date", "20260909",
            "--a-daily-timeout-seconds", "3600",
        ]
    ) == 0
    assert scheduler_capture["timeout_seconds"] == 600.0
    assert scheduler_capture["a_daily_timeout_seconds"] == 3600.0

    scheduler_capture.clear()
    assert scheduler.main(
        [
            "--data-root", str(tmp_path / "scheduler-data-omitted"),
            "--ledger-root", str(tmp_path / "scheduler-ledger-omitted"),
            "--slot", "1720",
            "--date", "20260909",
        ]
    ) == 0
    assert scheduler_capture["timeout_seconds"] == 600.0
    assert scheduler_capture["a_daily_timeout_seconds"] is None


def test_launcher_emits_bounded_a_timeout_argv_without_waiting(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    mac_python = runtime_root / "venvs" / "v3.5-mac" / "bin" / "python"
    mac_python.parent.mkdir(parents=True)
    (runtime_root / "venvs" / "v3.5-mac" / "lib" / "python3.14" / "site-packages").mkdir(
        parents=True
    )
    log_path = tmp_path / "scheduler-argv.log"
    mac_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$V4_TEST_LOG\"\nexit 0\n",
        encoding="utf-8",
    )
    mac_python.chmod(0o755)
    hk_tdx_root = tmp_path / "research-panel-hk-tdx"
    hk_tdx_root.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "V4_RUNTIME_ROOT": str(runtime_root),
            "V4_DATA_ROOT": str(tmp_path / "data"),
            "V4_DISPATCH_LEDGER_ROOT": str(tmp_path / "ledger"),
            "V4_STAGE_CENTER_SELECTION_ROOT": str(tmp_path / "selection"),
            "V4_PRESELECTION_INPUT_ROOT": str(tmp_path / "preselection"),
            "V4_RESEARCH_PANEL_HK_TDX_ROOT": str(hk_tdx_root),
            "V4_TEST_LOG": str(log_path),
        }
    )
    env.pop("V4_DAEMON_MODE", None)

    launcher = REPO / "ops" / "launch_v4_macos_scheduler.sh"
    completed = subprocess.run(
        ["bash", str(launcher)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    argv = log_path.read_text(encoding="utf-8").splitlines()
    assert argv[argv.index("--a-daily-timeout-seconds") + 1] == "3600"
    assert "--timeout-seconds" not in argv
    assert "ops.run_v4_macos_scheduler" in argv
