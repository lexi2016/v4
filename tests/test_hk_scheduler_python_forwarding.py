from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_scheduled_slot_accepts_and_forwards_hk_0_2_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixed HK 0.2 interpreter must survive the slot boundary into the registry."""
    from ops import run_scheduled_slot as scheduled_slot

    captured: dict[str, object] = {}

    class FakeRegistry:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(scheduled_slot, "FixedExecutorRegistry", FakeRegistry)
    monkeypatch.setattr(
        scheduled_slot,
        "dispatch_due",
        lambda *args, **kwargs: type(
            "Receipt",
            (),
            {
                "status": "SUCCEEDED",
                "run_id": "run-1",
                "receipt_path": None,
                "selected_workload_ids": (),
                "started_workload_ids": (),
                "failure_class": None,
                "retry_after": None,
                "release_id": None,
                "app_root": "",
                "release_manifest_path": "",
                "release_manifest_sha256": "",
                "upstream_fingerprint": None,
                "attempt": 1,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        )(),
    )

    hk_python = tmp_path / "v3.5-hk02" / "bin" / "python"
    result = scheduled_slot.run_scheduled_slot(
        data_root=tmp_path / "data",
        slot="1730",
        business_date="20260821",
        scheduled_date="20260821",
        target_date="20260824",
        ledger_root=tmp_path / "ledger",
        shared_data_root=tmp_path / "shared",
        hk_universe_root=tmp_path / "universe",
        shared_package_root=tmp_path / "package",
        preselection_input_root=tmp_path / "preselection",
        stage_selection_root=tmp_path / "selection",
        hk_0_2_python_executable=hk_python,
    )

    assert result["status"] == "SUCCEEDED"
    assert captured["hk_0_2_python_executable"] == hk_python


def test_scheduler_cli_forwards_hk_0_2_python_to_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The minute scheduler must expose the runtime as an explicit CLI boundary."""
    from ops import run_v35_macos_scheduler as scheduler

    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260821", "1730"))
    monkeypatch.setattr(
        scheduler,
        "run_scheduled_slot",
        lambda **kwargs: {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "hk_0_2_python_executable": str(kwargs["hk_0_2_python_executable"]),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )

    hk_python = tmp_path / "v3.5-hk02" / "bin" / "python"
    assert scheduler.main(
        [
            "--data-root", str(tmp_path / "data"),
            "--ledger-root", str(tmp_path / "ledger"),
            "--stage-selection-root", str(tmp_path / "selection"),
            "--slot", "1730",
            "--date", "20260821",
            "--hk-0-2-python", str(hk_python),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["hk_0_2_python_executable"] == str(hk_python)


def test_scheduler_launcher_has_fail_closed_hk_runtime_wiring() -> None:
    launcher = Path(__file__).parents[1] / "ops" / "launch_v35_macos_scheduler.sh"
    source = launcher.read_text(encoding="utf-8")

    assert "v3.5-hk02/bin/python" in source
    assert "V35_HK_0_2_PYTHON" in source
    assert "--hk-0-2-python" in source


def test_scheduler_launcher_keeps_global_scheduler_alive_when_hk_runtime_is_missing(
    tmp_path: Path,
) -> None:
    """HK runtime absence is a lane-local degradation, not a scheduler outage."""
    runtime_root = tmp_path / "runtime"
    fake_python = runtime_root / "venvs" / "v3.5-mac" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    (runtime_root / "venvs" / "v3.5-mac" / "lib" / "python3.14" / "site-packages").mkdir(parents=True)
    log_path = tmp_path / "scheduler-argv.log"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$V35_TEST_LOG\"\nexit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "V35_RUNTIME_ROOT": str(runtime_root),
            "V35_DATA_ROOT": str(tmp_path / "data"),
            "V35_DISPATCH_LEDGER_ROOT": str(tmp_path / "ledger"),
            "V35_STAGE_CENTER_SELECTION_ROOT": str(tmp_path / "selection"),
            "V35_PRESELECTION_INPUT_ROOT": str(tmp_path / "preselection"),
            "V35_TEST_LOG": str(log_path),
        }
    )
    launcher = Path(__file__).parents[1] / "ops" / "launch_v35_macos_scheduler.sh"
    completed = subprocess.run(
        ["bash", str(launcher)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    argv = log_path.read_text(encoding="utf-8").splitlines()
    assert "-m" in argv
    assert "ops.run_v35_macos_scheduler" in argv
    assert "--hk-0-2-python" in argv
    hk_arg = argv[argv.index("--hk-0-2-python") + 1]
    assert hk_arg.endswith("venvs/v3.5-hk02/bin/python.invalid")


def test_scheduler_launcher_fails_closed_when_main_site_packages_are_missing(
    tmp_path: Path,
) -> None:
    """The scheduler launcher rejects a runtime without its required package directory."""
    runtime_root = tmp_path / "runtime"
    fake_python = runtime_root / "venvs" / "v3.5-mac" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env.pop("V35_HK_0_2_PYTHON", None)
    env.update(
        {
            "V35_RUNTIME_ROOT": str(runtime_root),
            "V35_DATA_ROOT": str(tmp_path / "data"),
            "V35_DISPATCH_LEDGER_ROOT": str(tmp_path / "ledger"),
            "V35_STAGE_CENTER_SELECTION_ROOT": str(tmp_path / "selection"),
            "V35_PRESELECTION_INPUT_ROOT": str(tmp_path / "preselection"),
        }
    )
    launcher = Path(__file__).parents[1] / "ops" / "launch_v35_macos_scheduler.sh"
    completed = subprocess.run(
        ["bash", str(launcher)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "V3.5 scheduler Python site-packages is missing" in completed.stderr


def test_scheduler_launcher_forwards_valid_hk_runtime_path(
    tmp_path: Path,
) -> None:
    """A valid release-local HK runtime reaches the main scheduler unchanged."""
    runtime_root = tmp_path / "runtime"
    mac_python = runtime_root / "venvs" / "v3.5-mac" / "bin" / "python"
    hk_python = runtime_root / "venvs" / "v3.5-hk02" / "bin" / "python"
    mac_python.parent.mkdir(parents=True)
    hk_python.parent.mkdir(parents=True)
    (runtime_root / "venvs" / "v3.5-mac" / "lib" / "python3.14" / "site-packages").mkdir(parents=True)
    log_path = tmp_path / "scheduler-argv.log"
    mac_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$V35_TEST_LOG\"\nexit 0\n",
        encoding="utf-8",
    )
    hk_python.write_text(
        "#!/bin/sh\nif [ \"$1\" = \"-c\" ]; then printf '3.13.12\\n'; fi\nexit 0\n",
        encoding="utf-8",
    )
    mac_python.chmod(0o755)
    hk_python.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "V35_RUNTIME_ROOT": str(runtime_root),
            "V35_DATA_ROOT": str(tmp_path / "data"),
            "V35_DISPATCH_LEDGER_ROOT": str(tmp_path / "ledger"),
            "V35_STAGE_CENTER_SELECTION_ROOT": str(tmp_path / "selection"),
            "V35_PRESELECTION_INPUT_ROOT": str(tmp_path / "preselection"),
            "V35_TEST_LOG": str(log_path),
        }
    )
    launcher = Path(__file__).parents[1] / "ops" / "launch_v35_macos_scheduler.sh"
    completed = subprocess.run(
        ["bash", str(launcher)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    argv = log_path.read_text(encoding="utf-8").splitlines()
    hk_arg = argv[argv.index("--hk-0-2-python") + 1]
    assert hk_arg == str(hk_python)


def test_registry_rejects_explicit_python_314_as_hk_lane_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A direct 3.14 override must not execute either HK 0.2 producer."""
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.scheduling import executor_registry as registry_module
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry

    version = subprocess.run(
        [sys.executable, "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if version == "3.13.12":
        pytest.skip("the test requires the direct Python 3.14 scheduler runtime")

    package_root = tmp_path / "shared-package"
    scripts_root = package_root / "scripts"
    scripts_root.mkdir(parents=True)
    for entry in (
        "capture_public_fupan.py",
        "materialize_v192_selector.py",
        "update_hk_0_2_panel.py",
        "materialize_hk_0_2.py",
    ):
        (scripts_root / entry).write_text("# fixture entry\n", encoding="utf-8")
    selector = tmp_path / "selector.parquet"
    selector.write_bytes(b"fixture")
    monkeypatch.setattr(registry_module, "resolve_selector_panel", lambda *_args: selector)
    calls: list[str] = []

    def fake_runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(str(command[2]))
        return subprocess.CompletedProcess(command, 0, "", "")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared-data",
        hk_universe_root=tmp_path / "hk-universe",
        shared_package_root=package_root,
        selector_data_root=tmp_path / "selector-data",
        preselection_input_root=tmp_path / "preselection-input",
        repo_root=Path(__file__).parents[1],
        runner=fake_runner,
        hk_0_2_python_executable=Path(sys.executable),
    )
    request = DispatchRequest(
        scheduled_date="20260821",
        business_date="20260821",
        target_date="20260824",
        slot="1730",
        mode=DispatchMode.LIVE,
    )

    result = registry._preselection_pools(request)

    assert result["status"] == "SUCCEEDED"
    assert result["hk_lane_status"] == "CANNOT_CONFIRM"
    assert any("Python" in str(item.get("stderr")) for item in result["hk_lane_degradations"])
    assert "scripts.update_hk_0_2_panel" not in calls
    assert "scripts.materialize_hk_0_2" not in calls


def test_registry_rejects_default_scheduler_python_314_too(tmp_path: Path) -> None:
    """Omitting the override must not silently select the scheduler interpreter."""
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry

    version = subprocess.run(
        [sys.executable, "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if version == "3.13.12":
        pytest.skip("the test requires the direct Python 3.14 scheduler runtime")

    registry = FixedExecutorRegistry(data_root=tmp_path / "data", repo_root=tmp_path)
    error = registry._hk_0_2_runtime_error()

    assert error is not None
    assert "requires Python 3.13.12" in error


def test_registry_accepts_formal_hk02_python_31312(tmp_path: Path) -> None:
    """The release-local HK 0.2 interpreter remains an allowed runtime."""
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry

    hk_python = Path(
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/current/"
        "runtime/venvs/v3.5-hk02/bin/python"
    )
    if not hk_python.is_file():
        pytest.skip("formal HK 0.2 runtime is not available in this checkout")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path,
        hk_0_2_python_executable=hk_python,
    )

    assert registry._hk_0_2_runtime_error() is None
