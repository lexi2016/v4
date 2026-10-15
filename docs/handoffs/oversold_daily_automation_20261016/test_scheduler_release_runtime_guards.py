from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("scheduler_release_cutover", HERE / "scheduler_release_cutover.py")
assert SPEC and SPEC.loader
cutover = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cutover
SPEC.loader.exec_module(cutover)


def _fixture_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, dict[str, object]]:
    app_root = tmp_path / "oversold-daily-auto-test" / "app"
    runtime_root = tmp_path / "runtime with spaces"
    app_root.mkdir(parents=True)
    manifest_path = app_root.parent / "release-manifest.json"
    manifest_path.write_bytes(b"test release manifest")
    selector_plist = tmp_path / "com.lexi.v35.scheduler.plist"
    monkeypatch.setattr(cutover, "PLIST", selector_plist)
    environment = {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": app_root.parent.name,
        "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "V35_RUNTIME_ROOT": str(runtime_root),
        "PYTHONPATH": os.pathsep.join((str(app_root / "upstreams"), str(app_root))),
        "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(cutover.ACTIVE_CONFIG),
    }
    payload = {
        "ProgramArguments": ["/bin/bash", str(app_root / "ops/launch_v35_macos_scheduler.sh")],
        "WorkingDirectory": str(app_root),
        "EnvironmentVariables": environment,
    }
    selector_plist.write_bytes(plistlib.dumps(payload))
    job_snapshot: dict[str, object] = {
        "returncode": 0,
        "plist_path": str(selector_plist),
        "program": "/bin/bash",
        "working_directory": str(app_root),
        "state": "running",
        "pid": 321,
    }
    return app_root, runtime_root, job_snapshot


def test_process_identity_matches_launchd_cwd_selectors_and_python_module(tmp_path, monkeypatch):
    app_root, runtime_root, job = _fixture_job(tmp_path, monkeypatch)
    command = (f"{runtime_root}/venvs/v3.5-mac/bin/python -S -m "
               "ops.run_v35_macos_scheduler_daemon --data-root /tmp/state")
    monkeypatch.setattr(cutover, "_pid_snapshot", lambda pid: {"exists": True, "pid": pid, "command": command})
    monkeypatch.setattr(cutover, "_process_cwd", lambda _pid: app_root.resolve())

    evidence = cutover._process_identity_for_root(321, app_root, selector_plist=cutover.PLIST,
                                                   job_snapshot=job)

    assert evidence["launchd_label_pid_match"] is True
    assert evidence["launchd_plist_path_match"] is True
    assert evidence["process_cwd"] == str(app_root.resolve())
    assert evidence["app_root_selector_match"] is True
    assert evidence["manager_config_selector_match"] is True
    assert evidence["interpreter_command_match"] is True
    assert evidence["daemon_module_match"] is True
    assert "PYTHONPATH" not in evidence


def test_process_identity_rejects_launchd_label_bound_to_another_pid(tmp_path, monkeypatch):
    app_root, runtime_root, job = _fixture_job(tmp_path, monkeypatch)
    command = f"{runtime_root}/venvs/v3.5-mac/bin/python -S -m ops.run_v35_macos_scheduler_daemon"
    job["pid"] = 654
    monkeypatch.setattr(cutover, "_pid_snapshot", lambda pid: {"exists": True, "pid": pid, "command": command})
    monkeypatch.setattr(cutover, "_process_cwd", lambda _pid: app_root.resolve())

    with pytest.raises(cutover.CutoverError, match="LAUNCHD_LABEL_PID_MISMATCH"):
        cutover._process_identity_for_root(321, app_root, selector_plist=cutover.PLIST,
                                           job_snapshot=job)


def test_root_scan_finds_module_process_by_cwd_when_argv_has_no_app_root(tmp_path, monkeypatch):
    app_root, runtime_root, _job = _fixture_job(tmp_path, monkeypatch)
    command = f"{runtime_root}/venvs/v3.5-mac/bin/python -S -m ops.run_v35_macos_scheduler_daemon"

    def fake_run(arguments, **_kwargs):
        assert arguments[:3] == ["/bin/ps", "-ww", "-axo"]
        return type("Result", (), {"returncode": 0, "stdout": f" 321 {command}\n"})()

    monkeypatch.setattr(cutover.subprocess, "run", fake_run)
    monkeypatch.setattr(cutover, "_process_cwd", lambda _pid: app_root.resolve())

    found = cutover._scheduler_processes_for_root(app_root, cutover.PLIST)

    assert found == [{"pid": 321, "root_match": True, "process_cwd_match": True,
                      "daemon_module_match": True, "configured_interpreter_match": True}]


def test_root_scan_blocks_same_root_daemon_using_an_unexpected_interpreter(tmp_path, monkeypatch):
    app_root, _runtime_root, _job = _fixture_job(tmp_path, monkeypatch)

    def fake_run(arguments, **_kwargs):
        assert arguments[:3] == ["/bin/ps", "-ww", "-axo"]
        return type("Result", (), {"returncode": 0,
                                    "stdout": " 654 /usr/bin/python3 -S -m ops.run_v35_macos_scheduler_daemon\n"})()

    monkeypatch.setattr(cutover.subprocess, "run", fake_run)
    monkeypatch.setattr(cutover, "_process_cwd", lambda _pid: app_root.resolve())

    found = cutover._scheduler_processes_for_root(app_root, cutover.PLIST)

    assert found == [{"pid": 654, "root_match": True, "process_cwd_match": True,
                      "daemon_module_match": True, "configured_interpreter_match": False}]


def test_process_identity_rejects_wrong_cwd_even_with_matching_pid_and_command(tmp_path, monkeypatch):
    app_root, runtime_root, job = _fixture_job(tmp_path, monkeypatch)
    command = f"{runtime_root}/venvs/v3.5-mac/bin/python -S -m ops.run_v35_macos_scheduler_daemon"
    monkeypatch.setattr(cutover, "_pid_snapshot", lambda pid: {"exists": True, "pid": pid, "command": command})
    monkeypatch.setattr(cutover, "_process_cwd", lambda _pid: (tmp_path / "other-app").resolve())

    with pytest.raises(cutover.CutoverError, match="SCHEDULER_PROCESS_CWD_MISMATCH"):
        cutover._process_identity_for_root(321, app_root, selector_plist=cutover.PLIST,
                                           job_snapshot=job)


def test_detach_wait_does_not_treat_live_pid_as_gone_when_label_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(cutover, "_launchctl_snapshot", lambda: {"returncode": 113, "state": None, "pid": None})
    monkeypatch.setattr(cutover, "_pid_snapshot", lambda pid: {"exists": True, "pid": pid})
    monkeypatch.setattr(cutover.time, "sleep", lambda _seconds: None)

    with pytest.raises(cutover.CutoverError, match="SERVICE_DETACH_NOT_CONFIRMED"):
        cutover._wait_detached(321, tmp_path / "app", timeout_seconds=0.01)


def test_recovery_cli_plan_flag_matches_default_and_never_runs_formal_recovery():
    script = HERE / "recover_oversold_20261016.py"
    outputs = []
    for args in ([], ["--plan"]):
        result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        outputs.append(payload)
        assert payload["status"] == "RECOVERY_PLAN_ONLY"
        assert payload["network_or_formal_run"] is False
        assert payload["source_day"] == "20261015"
        assert payload["target_date"] == "20261016"
    assert outputs[0] == outputs[1]

    conflicting_modes = subprocess.run([sys.executable, str(script), "--plan", "--run"],
                                       capture_output=True, text=True)
    assert conflicting_modes.returncode == 2
    assert "not allowed with argument" in conflicting_modes.stderr
