from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading

from ops import run_v35_macos_scheduler_daemon as daemon


class FinishedChild:
    pid = 842_401

    def __init__(self) -> None:
        self.returncode = 0

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class HangingChild:
    pid = 842_402

    def __init__(self) -> None:
        self.killed = False

    def poll(self):
        return -15 if self.killed else None

    def wait(self, timeout=None):
        if self.killed:
            return -15
        raise subprocess.TimeoutExpired("pdf-queue-child", timeout)


def test_pdf_queue_hook_waits_for_scheduler_cycle_then_runs_one_bounded_child(tmp_path):
    app = tmp_path / "app"
    (app / "ops").mkdir(parents=True)
    (app / "ops/run_zsxq_hourly_delta.py").write_text("# isolated fixture\n", encoding="utf-8")
    data_root = tmp_path / "data"
    data_root.mkdir()
    cycle_active = threading.Event()
    cycle_active.set()
    spawned = threading.Event()
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write(
            json.dumps(
                {
                    "schema_version": "v4.zsxq_pdf_queue_tick.v1",
                    "status": "NO_RETRYABLE_TASKS",
                    "processed_document_count": 0,
                    "pending_task_count": 0,
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
            ).encode("utf-8")
        )
        kwargs["stdout"].flush()
        spawned.set()
        return FinishedChild()

    hook = daemon.PdfQueueDrainHook(
        app_root=app,
        data_root=data_root,
        python_path=Path(sys.executable),
        cycle_active=cycle_active,
        popen_factory=popen,
        poll_seconds=0.01,
        wall_seconds=1,
        idle_seconds=60,
    )
    hook.thread.start()
    try:
        assert not spawned.wait(0.05)
        cycle_active.clear()
        assert spawned.wait(1)
        command = calls[0][0]
        assert "--pdf-queue-tick" in command
        assert "--pdf-time-budget-seconds" in command
        assert command[command.index("--pdf-time-budget-seconds") + 1] == str(daemon.PDF_QUEUE_TICK_SECONDS)
        assert calls[0][1]["start_new_session"] is True
    finally:
        hook.stop()
    assert not hook.thread.is_alive()


def test_pdf_queue_hook_reaps_its_child_on_daemon_shutdown(tmp_path, monkeypatch):
    app = tmp_path / "app"
    data_root = tmp_path / "data"
    app.mkdir()
    data_root.mkdir()
    child = HangingChild()
    started = threading.Event()
    signal_calls = []

    def popen(_command, **_kwargs):
        started.set()
        return child

    def killpg(pid, signum):
        signal_calls.append((pid, signum))
        child.killed = True

    monkeypatch.setattr(daemon.os, "killpg", killpg)
    hook = daemon.PdfQueueDrainHook(
        app_root=app,
        data_root=data_root,
        python_path=Path(sys.executable),
        popen_factory=popen,
        poll_seconds=0.01,
        wall_seconds=10,
    )
    hook.thread.start()
    assert started.wait(1)
    hook.stop(join_seconds=1)
    assert child.killed is True
    assert signal_calls
    assert not hook.thread.is_alive()


def test_pdf_queue_hook_requires_explicit_existing_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("V35_DATA_ROOT", raising=False)
    assert daemon.PdfQueueDrainHook.from_environment(start=False) is None

    data_root = tmp_path / "data"
    data_root.mkdir()
    app_root = tmp_path / "app"
    (app_root / "ops").mkdir(parents=True)
    (app_root / "ops/run_zsxq_hourly_delta.py").write_text("# isolated fixture\n", encoding="utf-8")
    monkeypatch.setenv("V35_DATA_ROOT", str(data_root))
    monkeypatch.setenv("V35_APP_ROOT", str(app_root))
    hook = daemon.PdfQueueDrainHook.from_environment(start=False)
    assert hook is not None
    assert hook.data_root == data_root
    assert hook.app_root == app_root


def test_pdf_queue_hook_passes_only_explicit_local_root_to_existing_tick(tmp_path, monkeypatch):
    app = tmp_path / "app"
    (app / "ops").mkdir(parents=True)
    (app / "ops/run_zsxq_hourly_delta.py").write_text("# isolated fixture\n", encoding="utf-8")
    data_root = tmp_path / "data"
    local_root = tmp_path / "local"
    announcement_queue = tmp_path / "announcement_flash" / "queue"
    data_root.mkdir()
    local_root.mkdir()
    announcement_queue.mkdir(parents=True)
    monkeypatch.setenv("V35_DATA_ROOT", str(data_root))
    monkeypatch.setenv("V35_APP_ROOT", str(app))
    monkeypatch.setenv("V35_ZSXQ_PDF_LOCAL_ROOT", str(local_root))
    monkeypatch.setenv("V35_ZSXQ_PDF_ANNOUNCEMENT_QUEUE_ROOT", str(announcement_queue))
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write(b'{"status":"NO_RETRYABLE_TASKS"}')
        kwargs["stdout"].flush()
        return FinishedChild()

    hook = daemon.PdfQueueDrainHook.from_environment(start=False, popen_factory=popen)
    assert hook is not None
    hook._run_child()
    command = calls[0][0]
    assert "--pdf-queue-tick" in command
    assert command[command.index("--pdf-local-root") + 1] == str(local_root)
    assert command[command.index("--pdf-classification-queue-root") + 1] == str(announcement_queue)


def test_pdf_queue_hook_does_not_add_local_root_when_unconfigured(tmp_path, monkeypatch):
    app = tmp_path / "app"
    (app / "ops").mkdir(parents=True)
    (app / "ops/run_zsxq_hourly_delta.py").write_text("# isolated fixture\n", encoding="utf-8")
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("V35_DATA_ROOT", str(data_root))
    monkeypatch.setenv("V35_APP_ROOT", str(app))
    monkeypatch.delenv("V35_ZSXQ_PDF_LOCAL_ROOT", raising=False)
    monkeypatch.delenv("V35_ZSXQ_PDF_ANNOUNCEMENT_QUEUE_ROOT", raising=False)
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write(b'{"status":"NO_RETRYABLE_TASKS"}')
        kwargs["stdout"].flush()
        return FinishedChild()

    hook = daemon.PdfQueueDrainHook.from_environment(start=False, popen_factory=popen)
    assert hook is not None
    hook._run_child()
    assert "--pdf-local-root" not in calls[0][0]


def _analysis_hook_fixture(tmp_path, monkeypatch, *, progressing=True, analysis=True):
    from infrastructure import pdf_research_execution as execution
    app = tmp_path / 'app';app.mkdir()
    data = tmp_path / 'data';data.mkdir()
    progress = tmp_path / 'progress.json'
    task = {'run_id': 'frozen-run', 'reference': {'path': str(tmp_path / 'manifest.json'), 'sha256': 'a' * 64}, 'progress_path': str(progress)}
    monkeypatch.setattr(execution, 'next_analysis_task', lambda _root: task if analysis else None)
    current = [0.0]
    monkeypatch.setattr(daemon.time, 'monotonic', lambda: current[0])
    captured, stopped = [], []
    class Child:
        pid = 1234567
        calls = 0
        def poll(self):
            self.calls += 1
            current[0] += 30
            progress.write_text(json.dumps({'sequence': self.calls, 'kind': 'model_stream' if progressing else 'heartbeat', 'characters': 1}))
            return 0 if self.calls == 8 else None
        def wait(self, timeout=None): return 0
    child = Child()
    def popen(command, **kwargs):
        captured.append(command)
        kwargs['stdout'].write(b'{"status":"GENERATED_PENDING_REVIEW","task_type":"ANALYSIS","model_posts":1}')
        kwargs['stdout'].flush()
        return child
    hook = daemon.PdfQueueDrainHook(app_root=app, data_root=data, python_path=Path(sys.executable),
        popen_factory=popen, wall_seconds=150, poll_seconds=.01)
    monkeypatch.setattr(hook, '_finish_child', lambda _child, reason: stopped.append((child.pid, reason)))
    return hook, captured, stopped, current


def test_analysis_supervisor_keeps_owned_child_healthy_beyond_total_150_seconds(tmp_path, monkeypatch):
    hook, commands, stopped, current = _analysis_hook_fixture(tmp_path, monkeypatch)
    result = hook._run_child()
    assert result['status'] == 'GENERATED_PENDING_REVIEW'
    assert current[0] == 240 and stopped == []
    assert '--pdf-queue-tick' in commands[0]
    assert commands[0][commands[0].index('--pdf-task-type') + 1] == 'analysis'
    assert '--pdf-analysis-run-manifest' in commands[0]


def test_analysis_supervisor_ignores_heartbeat_and_signals_only_owned_child(tmp_path, monkeypatch):
    hook, commands, stopped, current = _analysis_hook_fixture(tmp_path, monkeypatch, progressing=False)
    assert hook._run_child()['status'] == 'PDF_ANALYSIS_NO_PROGRESS_TIMEOUT'
    assert stopped == [(1234567, 'NO_PROGRESS_TIMEOUT')]
    assert current[0] >= 150


def test_original_ocr_total_budget_is_unchanged(tmp_path, monkeypatch):
    hook, commands, stopped, current = _analysis_hook_fixture(tmp_path, monkeypatch, analysis=False)
    assert hook._run_child()['status'] == 'PDF_QUEUE_CHILD_TIMEOUT'
    assert '--pdf-task-type' not in commands[0]
    assert stopped == [(1234567, 'TIMEOUT')]
