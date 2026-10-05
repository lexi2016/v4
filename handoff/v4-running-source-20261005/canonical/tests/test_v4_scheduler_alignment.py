"""Focused checks for the canonical persistent scheduler entry points."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PYTHONPATH = os.pathsep.join(
    [str(ROOT), os.environ.get("PYTHONPATH", "")]
).rstrip(os.pathsep)


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": RUNTIME_PYTHONPATH,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def test_public_scheduler_entries_import_and_help() -> None:
    for module in (
        "ops.macos_research_panel_daily",
        "ops.run_v35_macos_scheduler",
        "ops.run_v35_macos_scheduler_daemon",
    ):
        imported = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=ROOT,
            env=_python_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        assert imported.returncode == 0, imported.stderr

    daemon_help = subprocess.run(
        [sys.executable, "-m", "ops.run_v35_macos_scheduler_daemon", "--help"],
        cwd=ROOT,
        env=_python_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert daemon_help.returncode == 0, daemon_help.stderr
    assert "persistent" in daemon_help.stdout.lower()


def test_persistent_daemon_wraps_one_shot_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    from ops import run_v35_macos_scheduler_daemon as daemon

    monkeypatch.setenv("V35_RELEASE_ID", "alignment-test")
    for name in (
        "PRODUCTION_ALLOWED",
        "BUY_GATE_UPDATED",
        "ORDERS_SENT",
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
    ):
        monkeypatch.setenv(name, "false")
    stop_event = threading.Event()
    calls: list[list[str]] = []

    def fake_scheduler(argv: list[str]) -> int:
        calls.append(list(argv))
        print(
            json.dumps(
                {
                    "status": "NO_DUE_SLOT",
                    "release_id": "alignment-test",
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            )
        )
        stop_event.set()
        return 0

    code = daemon.run_daemon(
        ["--release-id", "alignment-test", "--slot", "0700"],
        scheduler_main=fake_scheduler,
        clock=lambda: datetime(2026, 9, 13, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        stop_event=stop_event,
        install_signals=False,
        poll_interval_seconds=0.01,
        heartbeat_seconds=60.0,
    )

    assert code == 0
    assert calls == [["--release-id", "alignment-test", "--slot", "0700"]]
    output = daemon.last_emitted_output()
    assert '"status": "DAEMON_READY"' in output
    assert '"status": "DAEMON_CYCLE"' in output
    assert '"status": "DAEMON_STOPPED"' in output


def test_launcher_selects_persistent_entry_without_running_workloads(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    python_bin = runtime_root / "venvs" / "v3.5-mac" / "bin" / "python"
    site_packages = runtime_root / "venvs" / "v3.5-mac" / "lib" / "python3.14" / "site-packages"
    python_bin.parent.mkdir(parents=True)
    site_packages.mkdir(parents=True)
    log_path = tmp_path / "python-argv.txt"
    python_bin.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$@\" > \"{log_path}\"\n",
        encoding="utf-8",
    )
    python_bin.chmod(0o755)
    env = _python_env()
    env.update(
        {
            "V35_RUNTIME_ROOT": str(runtime_root),
            "V35_DATA_ROOT": str(tmp_path / "data"),
            "V35_DISPATCH_LEDGER_ROOT": str(tmp_path / "ledger"),
            "V35_STAGE_CENTER_SELECTION_ROOT": str(tmp_path / "selection"),
            "V35_PRESELECTION_INPUT_ROOT": str(tmp_path / "preselection"),
            "V35_HK_0_2_PYTHON": "/bin/false",
            "V35_DAEMON_MODE": "persistent-minute",
            "V35_RELEASE_ID": "alignment-test",
        }
    )
    completed = subprocess.run(
        ["bash", str(ROOT / "ops" / "launch_v35_macos_scheduler.sh")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert log_path.read_text(encoding="utf-8").splitlines()[:3] == [
        "-S",
        "-m",
        "ops.run_v35_macos_scheduler_daemon",
    ]


def test_panel_forwards_explicit_host_and_budget(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import ops.macos_research_panel_daily as panel

    tdx_root = tmp_path / "tdx"
    day_dir = tdx_root / "vipdoc" / "sh" / "lday"
    day_dir.mkdir(parents=True)
    (day_dir / "sh600000.day").write_bytes(b"")
    seen: dict[str, object] = {}

    def fake_sync(*args: object, **kwargs: object) -> dict[str, object]:
        seen["sync_kwargs"] = kwargs
        return {"status": "READY", "formula_tdx_root": str(tmp_path / "formula")}

    def fake_formula(*args: object, **kwargs: object) -> dict[str, object]:
        seen["formula_kwargs"] = kwargs
        return {"status": "READY"}

    def fake_run_lanes(
        *,
        target_date: str,
        receipt_root: Path,
        a_runner: object,
        hk_runner: object,
        lane: str,
    ) -> dict[str, object]:
        del receipt_root, hk_runner, lane
        seen["a_result"] = a_runner(target_date)  # type: ignore[operator]
        return {
            "overall_status": "READY",
            "target_date": target_date,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(panel, "run_windows_a_sync_authority", fake_sync)
    monkeypatch.setattr(panel, "run_windows_a_formula_authority", fake_formula)
    monkeypatch.setattr(panel, "run_scheduled_lanes", fake_run_lanes)
    paths = {
        "--receipt-root": tmp_path / "receipts",
        "--a-tdx-root": tdx_root,
        "--hk-tdx-root": tmp_path / "hk",
        "--a-sync-script": tmp_path / "sync.py",
        "--a-formula-script": tmp_path / "formula.py",
        "--a-seed-panel": tmp_path / "seed.parquet",
        "--a-data-root": tmp_path / "data",
        "--a-selector-pointer": tmp_path / "selector.ptr",
        "--a-backtest-pointer": tmp_path / "backtest.ptr",
        "--a-selector-seed": tmp_path / "selector.parquet",
        "--a-backtest-seed": tmp_path / "backtest.parquet",
        "--a-contract-csv": tmp_path / "contract.csv",
        "--a-canonical-formula": tmp_path / "canonical.py",
        "--a-return-root": tmp_path / "returns",
        "--hk-updater-script": tmp_path / "hk.py",
        "--hk-asset-root": tmp_path / "assets",
    }
    argv = [
        "panel",
        "--date",
        "20260911",
        "--lane",
        "A",
        "--a-minimum-rows",
        "1",
        "--a-host",
        "59.36.5.11",
        "--a-port",
        "7709",
        "--a-sync-run-budget-seconds",
        "321",
    ]
    for option, value in paths.items():
        argv.extend([option, str(value)])
    monkeypatch.setattr(sys, "argv", argv)

    assert panel.main() == 0
    assert seen["sync_kwargs"] == {
        "minimum_target_date_files": 1,
        "authority_args": {
            "run_budget_seconds": 321.0,
            "host": "59.36.5.11:7709",
        },
    }

    monkeypatch.setenv("V35_A_SYNC_HOST", "env-host")
    monkeypatch.setenv("V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS", "456")
    env_argv: list[str] = []
    skip_value = False
    for value in argv:
        if skip_value:
            skip_value = False
            continue
        if value in {"--a-host", "--a-port", "--a-sync-run-budget-seconds"}:
            skip_value = True
            continue
        env_argv.append(value)
    monkeypatch.setattr(sys, "argv", env_argv)
    assert panel.main() == 0
    assert seen["sync_kwargs"] == {
        "minimum_target_date_files": 1,
        "authority_args": {
            "run_budget_seconds": 456.0,
            "host": "env-host",
        },
    }


def test_panel_authority_wrapper_merges_host_and_budget_before_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exercise the real wrapper so an override cannot duplicate ``host``."""

    from types import SimpleNamespace

    import ops.macos_research_panel_daily as panel

    tdx_root = tmp_path / "tdx"
    day_path = tdx_root / "vipdoc" / "sh" / "lday" / "sh600000.day"
    day_path.parent.mkdir(parents=True)
    day_path.write_bytes(
        panel.A_DAY_STRUCT.pack(20260911, 1000, 1010, 990, 1005, 1000.0, 100, 0)
    )
    seen: dict[str, object] = {}

    def fake_run(args: argparse.Namespace) -> dict[str, object]:
        seen["args"] = args
        return {"status": "PASS", "exit_code": 0}

    authority_module = SimpleNamespace(run=fake_run)
    monkeypatch.setattr(panel, "_load_authority_module", lambda *_args: authority_module)

    result = panel.run_windows_a_sync_authority(
        tmp_path / "authority.py",
        tdx_root,
        "20260911",
        tmp_path / "receipts",
        minimum_target_date_files=1,
        authority_args={"host": "59.36.5.11:7709", "run_budget_seconds": 12.5},
    )

    args = seen["args"]
    assert isinstance(args, argparse.Namespace)
    assert args.host == "59.36.5.11:7709"
    assert args.run_budget_seconds == 12.5
    assert result["status"] == "READY"
    assert result["authority_status"] == "PASS"
    assert (tmp_path / "receipts" / "a_sync_authority.json").is_file()


def test_panel_budget_and_port_validation_remain_fail_closed() -> None:
    import ops.macos_research_panel_daily as panel

    with pytest.raises(ValueError, match="positive finite"):
        panel._resolve_a_sync_run_budget(0)
    with pytest.raises(ValueError, match="positive finite"):
        panel._resolve_a_sync_run_budget(float("nan"))
