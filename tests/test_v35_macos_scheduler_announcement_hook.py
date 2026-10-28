from __future__ import annotations

import hashlib
import builtins
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import signal
import subprocess
import sys
import threading

import pytest

from ops import run_v35_macos_scheduler_daemon as daemon


HK = daemon.SHANGHAI
NOW = datetime(2026, 9, 28, 9, 0, tzinfo=HK)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding_fixture(tmp_path: Path, monkeypatch, *, enabled: bool = True, policy: str = "BALANCED_V1") -> dict:
    app = (tmp_path / "future-api-app").resolve()
    cycle = app / daemon.ANNOUNCEMENT_CYCLE_RELATIVE
    cycle.parent.mkdir(parents=True)
    cycle.write_text("# isolated no-provider test child\n", encoding="utf-8")
    python = Path(sys.executable)
    resolved_python = python.resolve(strict=True)
    config = tmp_path / "binding-config"
    config.mkdir()
    binding_path = (config / "binding.json").resolve()
    receipt_path = (config / "activation.json").resolve()
    receipt_bytes = b'{"offline_fixture":true}\n'
    receipt_path.write_bytes(receipt_bytes)
    cycle_sha = _sha(cycle)
    python_sha = _sha(resolved_python)
    binding = {
        "schema_version": daemon.ANNOUNCEMENT_BINDING_SCHEMA,
        "enabled": enabled,
        "policy_status": "PROPOSAL_ONLY",
        "policy": policy,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "research_only": True,
        "app_root": str(app),
        "manager_state_root": str((tmp_path / "manager-state").resolve()),
        "security_master_root": str((tmp_path / "security-master").resolve()),
        "python": str(python),
        "python_resolved": str(resolved_python),
        "python_sha256": python_sha,
        "files": {daemon.ANNOUNCEMENT_CYCLE_RELATIVE: cycle_sha},
        "priority_codes": [],
        "activation_receipt": (
            {"path": str(receipt_path), "sha256": hashlib.sha256(receipt_bytes).hexdigest()}
            if enabled
            else None
        ),
    }
    binding_path.write_text(json.dumps(binding, sort_keys=True), encoding="utf-8")
    for name, value in (
        (daemon.ANNOUNCEMENT_BINDING_ENV, str(binding_path)),
        (daemon.ANNOUNCEMENT_APP_ENV, str(app)),
        (daemon.ANNOUNCEMENT_PYTHON_ENV, str(python)),
        (daemon.ANNOUNCEMENT_PYTHON_SHA_ENV, python_sha),
        (daemon.ANNOUNCEMENT_CYCLE_SHA_ENV, cycle_sha),
    ):
        monkeypatch.setenv(name, value)
    return {"app": app, "cycle": cycle, "python": python, "binding_path": binding_path, "binding": binding}


def _plan_only_binding_fixture(tmp_path: Path, monkeypatch, *, same_root: bool = False) -> dict:
    tmp_path.mkdir(parents=True,exist_ok=True)
    fixture=_binding_fixture(tmp_path,monkeypatch,enabled=True)
    binding=fixture['binding'];binding.pop('activation_receipt',None)
    canary_path=(tmp_path/'plan-canary.json').resolve()
    owner_app=fixture['app'] if same_root else (tmp_path/'historical-owner-api-app').resolve()
    owner_app.mkdir(exist_ok=True)
    canary={"schema_version":"manager_daily_chain.plan_refresh_owner_evidence.v2",
        "status":"PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING","app_root":str(fixture['app']),
        "candidate_binding_app_root":str(fixture['app']),"owner_execution_app_root":str(owner_app),
        "execution_mode":"HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK","hook_executed":False,
        "manager_state_root":binding['manager_state_root'],"plan_material_refresh_only":True,
        "announcement_collection_enabled":False,"announcement_network_requests":0,
        "research_only":True,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
    canary_raw=json.dumps(canary,sort_keys=True).encode();canary_path.write_bytes(canary_raw)
    canary_sha=hashlib.sha256(canary_raw).hexdigest()
    binding.update(plan_material_refresh_only=True,announcement_collection_enabled=False,
        plan_material_refresh={'enabled':True,'start_local':'16:00','end_local':'23:00',
            'max_attempts_per_target_date':3,'retry_backoff_seconds':600,'status':'PROPOSAL_ONLY'},
        plan_activation_receipt={'path':str(canary_path),'sha256':canary_sha})
    fixture['binding_path'].write_text(json.dumps(binding,sort_keys=True),encoding='utf-8')
    monkeypatch.setenv(daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV,canary_sha)
    fixture['canary_path']=canary_path
    return fixture


class FinishedChild:
    pid = 842_301

    def __init__(self) -> None:
        self.returncode = 0
        self.wait_calls = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.wait_calls += 1
        return self.returncode


class HangingChild:
    pid = 842_302

    def __init__(self) -> None:
        self.killed = False
        self.wait_calls = 0

    def poll(self):
        return -9 if self.killed else None

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.killed:
            return -9
        raise subprocess.TimeoutExpired("announcement-child", timeout)


def test_missing_binding_is_inert_and_scheduler_runs_once(monkeypatch):
    for name in (
        daemon.ANNOUNCEMENT_BINDING_ENV,
        daemon.ANNOUNCEMENT_APP_ENV,
        daemon.ANNOUNCEMENT_PYTHON_ENV,
        daemon.ANNOUNCEMENT_PYTHON_SHA_ENV,
        daemon.ANNOUNCEMENT_CYCLE_SHA_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    popen_calls = []
    assert daemon.AnnouncementCycleHook.from_environment(popen_factory=lambda *a, **k: popen_calls.append((a, k))) is None
    assert not popen_calls
    original_import = builtins.__import__

    def no_worker_import(name, *args, **kwargs):
        if name.startswith("v4.") or name == "infrastructure.scheduling.manager_announcement_supervisor":
            raise AssertionError("default-disabled daemon imported a V4 worker module")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_worker_import)

    stop = threading.Event()
    calls = []

    def scheduler_main(argv):
        calls.append(argv)
        print(json.dumps({"status": "OK", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}))
        stop.set()
        return 0

    assert daemon.run_daemon(
        ["--release-id", "offline-test"],
        scheduler_main=scheduler_main,
        clock=lambda: NOW,
        stop_event=stop,
        install_signals=False,
        poll_interval_seconds=0.01,
    ) == 0
    assert len(calls) == 1
    assert not popen_calls


def test_bad_binding_isolated_from_original_scheduler(tmp_path, monkeypatch):
    _binding_fixture(tmp_path, monkeypatch, enabled=True)
    monkeypatch.setenv(daemon.ANNOUNCEMENT_CYCLE_SHA_ENV, "f" * 64)
    stop = threading.Event()
    calls = []

    def scheduler_main(argv):
        calls.append(argv)
        print(json.dumps({"status": "OK", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}))
        stop.set()
        return 0

    assert daemon.run_daemon(
        ["--release-id", "offline-test"],
        scheduler_main=scheduler_main,
        clock=lambda: NOW,
        stop_event=stop,
        install_signals=False,
        poll_interval_seconds=0.01,
    ) == 0
    assert len(calls) == 1
    assert '"status": "ANNOUNCEMENT_HOOK_DISABLED"' in daemon.last_emitted_output()


def test_plan_only_binding_uses_distinct_canary_and_never_accepts_announcement_activation(tmp_path,monkeypatch):
    fixture=_plan_only_binding_fixture(tmp_path,monkeypatch)
    identity=daemon._load_announcement_binding(dict(os.environ))
    assert identity['plan_material_refresh_only'] is True
    monkeypatch.setenv(daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV,'f'*64)
    with pytest.raises(daemon.DaemonConfigurationError,match='plan canary SHA'):
        daemon._load_announcement_binding(dict(os.environ))

    fixture=_plan_only_binding_fixture(tmp_path/'forged',monkeypatch)
    canary=json.loads(fixture['canary_path'].read_text())
    assert canary['app_root']==str(fixture['app'])
    assert canary['owner_execution_app_root']!=canary['app_root']
    assert canary['hook_executed'] is False
    canary['announcement_network_requests']=1
    raw=json.dumps(canary,sort_keys=True).encode();fixture['canary_path'].write_bytes(raw)
    sha=hashlib.sha256(raw).hexdigest()
    fixture['binding']['plan_activation_receipt']['sha256']=sha
    fixture['binding_path'].write_text(json.dumps(fixture['binding'],sort_keys=True),encoding='utf-8')
    monkeypatch.setenv(daemon.ANNOUNCEMENT_PLAN_CANARY_SHA_ENV,sha)
    with pytest.raises(daemon.DaemonConfigurationError,match='plan canary contract'):
        daemon._load_announcement_binding(dict(os.environ))


def test_plan_only_binding_accepts_fresh_owner_canary_from_same_api_root(tmp_path,monkeypatch):
    fixture=_plan_only_binding_fixture(tmp_path,monkeypatch,same_root=True)
    identity=daemon._load_announcement_binding(dict(os.environ))
    canary=json.loads(fixture['canary_path'].read_text())
    assert identity['plan_material_refresh_only'] is True
    assert canary['owner_execution_app_root']==canary['candidate_binding_app_root']==str(fixture['app'])
    assert canary['hook_executed'] is False
    assert fixture['binding'].get('activation_receipt') is None


@pytest.mark.parametrize("bad_pin", ["app", "python", "python_sha", "cycle_sha", "safety"])
def test_disabled_binding_and_bad_pins_never_start_child(tmp_path, monkeypatch, bad_pin):
    fixture = _binding_fixture(tmp_path / "disabled", monkeypatch, enabled=False)
    calls = []
    assert daemon.AnnouncementCycleHook.from_environment(
        popen_factory=lambda *args, **kwargs: calls.append((args, kwargs))
    ) is None
    assert not calls
    assert fixture["binding_path"].is_file()

    fixture = _binding_fixture(tmp_path / "bad-pin", monkeypatch, enabled=True)
    if bad_pin == "app":
        monkeypatch.setenv(daemon.ANNOUNCEMENT_APP_ENV, str((tmp_path / "wrong-app").resolve()))
    elif bad_pin == "python":
        monkeypatch.setenv(daemon.ANNOUNCEMENT_PYTHON_ENV, str(Path(sys.executable).resolve().parent / "different-python"))
    elif bad_pin == "python_sha":
        monkeypatch.setenv(daemon.ANNOUNCEMENT_PYTHON_SHA_ENV, "a" * 64)
    elif bad_pin == "cycle_sha":
        monkeypatch.setenv(daemon.ANNOUNCEMENT_CYCLE_SHA_ENV, "a" * 64)
    else:
        binding = json.loads(fixture["binding_path"].read_text(encoding="utf-8"))
        binding["orders_sent"] = True
        fixture["binding_path"].write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(daemon.DaemonConfigurationError):
        daemon.AnnouncementCycleHook.from_environment(
            popen_factory=lambda *args, **kwargs: calls.append((args, kwargs)), start=False
        )
    assert not calls


def test_enabled_child_uses_explicit_app_and_sanitized_isolated_command(tmp_path, monkeypatch):
    fixture = _binding_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("PYTHONPATH", "/untrusted/v35/modules")
    monkeypatch.setenv("PYTHONHOME", "/untrusted/python-home")
    monkeypatch.setenv("V35_ROOT", "/untrusted/v35/root")
    monkeypatch.setenv("V35_RELEASE_ID", "untrusted-v35-release")
    monkeypatch.setenv("PRODUCTION_ALLOWED", "true")
    calls = []
    spawned = threading.Event()
    child = FinishedChild()

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        spawned.set()
        return child

    hook = daemon.AnnouncementCycleHook.from_environment(
        clock=lambda: NOW, popen_factory=popen, poll_seconds=0.01
    )
    assert hook is not None
    assert spawned.wait(1)
    hook.stop()
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [
        str(fixture["python"]),
        "-I",
        "-B",
        str(fixture["cycle"]),
        "--binding",
        str(fixture["binding_path"]),
    ]
    assert kwargs["cwd"] == str(fixture["app"])
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is None and kwargs["stderr"] is None
    assert kwargs["start_new_session"] is True and kwargs["close_fds"] is True
    child_env = kwargs["env"]
    assert child_env["PRODUCTION_ALLOWED"] == "false"
    assert child_env["BUY_GATE_UPDATED"] == "false"
    assert child_env["ORDERS_SENT"] == "false"
    assert child_env["PYTHONNOUSERSITE"] == "1"
    assert not {"PYTHONPATH", "PYTHONHOME", "V35_ROOT", "V35_RELEASE_ID"} & child_env.keys()
    assert set(child_env) <= {
        "LANG", "LC_ALL", "TZ", "TMPDIR", "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT", "PYTHONNOUSERSITE"
    }
    assert child.wait_calls >= 1


def test_child_runs_while_original_scheduler_call_is_blocked(tmp_path, monkeypatch):
    _binding_fixture(tmp_path, monkeypatch)
    spawned = threading.Event()
    scheduler_started = threading.Event()
    release_scheduler = threading.Event()
    stop = threading.Event()
    child = FinishedChild()
    calls = []
    result = []

    def popen(command, **kwargs):
        calls.append(command)
        spawned.set()
        return child

    def scheduler_main(argv):
        scheduler_started.set()
        assert release_scheduler.wait(1)
        print(json.dumps({"status": "OK", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}))
        stop.set()
        return 0

    def run():
        result.append(
            daemon.run_daemon(
                ["--release-id", "offline-test"],
                scheduler_main=scheduler_main,
                clock=lambda: NOW,
                stop_event=stop,
                install_signals=False,
                poll_interval_seconds=0.01,
            )
        )

    hook_factory = daemon.AnnouncementCycleHook.from_environment

    def configured_hook(**kwargs):
        return hook_factory(**{**kwargs, "popen_factory": popen})

    monkeypatch.setattr(daemon.AnnouncementCycleHook, "from_environment", staticmethod(configured_hook))
    runner = threading.Thread(target=run, daemon=True)
    runner.start()
    assert scheduler_started.wait(1)
    assert spawned.wait(1)
    assert runner.is_alive()
    release_scheduler.set()
    runner.join(timeout=2)
    assert not runner.is_alive()
    assert result == [0]
    assert len(calls) == 1
    assert '"result_status": "OK"' in daemon.last_emitted_output()


def test_fixed_minute_dedup_and_low_load_two_minute_bucket(tmp_path, monkeypatch):
    _binding_fixture(tmp_path, monkeypatch)
    spawned = threading.Event()
    checked_again = threading.Event()
    calls = []
    clock_count = 0

    def clock():
        nonlocal clock_count
        clock_count += 1
        if clock_count >= 4:
            checked_again.set()
        return NOW

    def popen(command, **kwargs):
        calls.append(command)
        spawned.set()
        return FinishedChild()

    hook = daemon.AnnouncementCycleHook.from_environment(
        clock=clock, popen_factory=popen, poll_seconds=0.005
    )
    assert hook is not None and spawned.wait(1)
    assert checked_again.wait(1)
    hook.stop()
    assert len(calls) == 1

    minute = NOW.replace(second=0, microsecond=0)
    pair = (minute, minute + timedelta(minutes=1))
    assert sum(daemon._announcement_due(value, "LOW_LOAD_V1") for value in pair) == 1
    assert all(daemon._announcement_due(value, "BALANCED_V1") for value in pair)
    assert not daemon._announcement_due(NOW.replace(hour=6), "BALANCED_V1")
    assert not daemon._announcement_due(NOW.replace(hour=15, minute=25), "BALANCED_V1")


def test_busy_child_consumes_later_minute_without_overlap(tmp_path, monkeypatch):
    fixture = _binding_fixture(tmp_path, monkeypatch)
    current = {"moment": NOW}
    observed_busy_minute = threading.Event()
    released = threading.Event()
    child_exited = threading.Event()
    calls = []

    def clock():
        if current["moment"].minute == NOW.minute + 1:
            observed_busy_minute.set()
        return current["moment"]

    class BusyChild:
        pid = 842_303
        polls = 0

        def poll(self):
            self.polls += 1
            if self.polls == 2:
                current["moment"] = NOW + timedelta(minutes=1)
            if released.is_set():
                child_exited.set()
                return 0
            return None

        def wait(self, timeout=None):
            return 0 if released.is_set() else None

    def popen(command, **kwargs):
        calls.append(command)
        return BusyChild()

    hook = daemon.AnnouncementCycleHook.from_environment(clock=clock, popen_factory=popen, poll_seconds=0.005)
    assert hook is not None
    assert observed_busy_minute.wait(1)
    released.set()
    assert child_exited.wait(1)
    hook.stop()
    assert len(calls) == 1
    assert hook.last_minute == daemon._minute_key(NOW + timedelta(minutes=1))


@pytest.mark.parametrize("stop_child", [False, True], ids=["timeout", "cancel"])
def test_timeout_and_cancel_signal_only_owned_process_group(tmp_path, monkeypatch, stop_child):
    _binding_fixture(tmp_path, monkeypatch)
    spawned = threading.Event()
    killed = threading.Event()
    calls = []
    child = HangingChild()

    def popen(command, **kwargs):
        spawned.set()
        return child

    def killpg(pid, signum):
        calls.append((pid, signum))
        if signum == signal.SIGKILL:
            child.killed = True
            killed.set()

    monkeypatch.setattr(daemon.os, "killpg", killpg)
    hook = daemon.AnnouncementCycleHook.from_environment(
        clock=lambda: NOW,
        popen_factory=popen,
        poll_seconds=0.003,
        wall_seconds=0.03,
        kill_grace_seconds=0.005,
    )
    assert hook is not None and spawned.wait(1)
    if stop_child:
        hook.stop()
    else:
        assert killed.wait(1)
        hook.stop()
    assert calls == [(child.pid, signal.SIGTERM), (child.pid, signal.SIGKILL)]
    assert child.killed and child.wait_calls >= 2


def test_binding_change_revokes_child_without_touching_other_processes(tmp_path, monkeypatch):
    fixture = _binding_fixture(tmp_path, monkeypatch)
    child = HangingChild()
    spawned = threading.Event()
    term_sent = threading.Event()
    calls = []

    def popen(command, **kwargs):
        spawned.set()
        return child

    def killpg(pid, signum):
        calls.append((pid, signum))
        if signum == signal.SIGTERM:
            term_sent.set()
        if signum == signal.SIGKILL:
            child.killed = True

    monkeypatch.setattr(daemon.os, "killpg", killpg)
    hook = daemon.AnnouncementCycleHook.from_environment(
        clock=lambda: NOW, popen_factory=popen, poll_seconds=0.003, kill_grace_seconds=0.005
    )
    assert hook is not None and spawned.wait(1)
    binding = fixture["binding_path"].read_text(encoding="utf-8")
    fixture["binding_path"].write_text(binding + "\n", encoding="utf-8")
    assert term_sent.wait(1)
    hook.stop()
    assert calls[0] == (child.pid, signal.SIGTERM)
    assert all(pid == child.pid for pid, _ in calls)
