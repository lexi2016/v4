from datetime import datetime, timedelta
from pathlib import Path
import json
import subprocess
import sys
import threading
import types
import importlib

import pytest
from ops import run_v35_macos_scheduler_daemon as daemon
from v4.manager_workbench import supervisor

NOW = datetime(2026, 10, 26, 17, 0, 12, 250000, tzinfo=daemon.SHANGHAI)

class Event:
    def __init__(self, clock, limit=1):
        self.clock, self.limit, self.waits, self.done = clock, limit, [], False
    def is_set(self): return self.done
    def set(self): self.done = True
    def wait(self, seconds):
        self.waits.append(seconds)
        self.clock[0] += timedelta(seconds=seconds)
        self.done = len(self.waits) >= self.limit
        return self.done


def manager():
    clock = [NOW]
    hook = supervisor.WorkbenchHook.__new__(supervisor.WorkbenchHook)
    hook.clock, hook.cancel, hook.poll_seconds = lambda: clock[0], Event(clock), None
    hook.last_minute = hook.last_result = None
    hook._config_path = hook._config_sha = None
    hook.service = object()
    hook.binding = {'calendar': object(), 'stage_feed': object()}
    return hook, clock


def test_manager_aligns_after_work_and_cancel(monkeypatch):
    hook, clock = manager()
    calls = []
    def tick(*args, **kwargs):
        calls.append(kwargs['at'])
        clock[0] += timedelta(seconds=5)
        return {'state': 'WAITING'}
    monkeypatch.setattr(supervisor, 'tick', tick)
    hook._run()
    assert len(calls) == 1
    assert hook.cancel.waits == [42.75]


def test_manager_minute_idempotency_and_config_revocation(tmp_path, monkeypatch):
    hook, clock = manager()
    calls = []
    monkeypatch.setattr(supervisor, 'tick', lambda *a, **kw: calls.append(kw['at']))
    hook.once(); hook.once()
    assert len(calls) == 1
    hook._config_path = tmp_path/'binding.json'
    hook._config_path.write_bytes(b'original')
    hook._config_sha = supervisor.raw_sha(b'original')
    hook._config_path.write_bytes(b'revoked')
    with pytest.raises(ValueError, match='WORKBENCH_BINDING_REVOKED'): hook.once()
    assert len(calls) == 1


def pdf(tmp_path, **kwargs):
    return daemon.PdfQueueDrainHook(app_root=tmp_path, data_root=tmp_path,
        python_path=Path(sys.executable), clock=lambda: NOW, **kwargs)


def index(tmp_path, artifact=None):
    path=tmp_path/'external_sources/zsxq_hourly/zsxq_pdf_ingestion_index.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'schema_version':'v4.zsxq_pdf_ingestion_index.v1',
        'sources':{}, 'documents':{} if artifact is None else {'doc':{'engine_runs':{'engine':artifact}}}, 'ocr_cache':{}}))
    return path


def test_pdf_empty_cheap_probe_and_300_second_fallback(tmp_path):
    index(tmp_path)
    elapsed=[0.]
    hook=pdf(tmp_path, monotonic=lambda: elapsed[0])
    hook.last_child_finished=0.
    assert hook._queue_probe()['status']=='NO_RETRYABLE_TASKS'
    for second in (0,60,120,180,240):
        elapsed[0]=second
        assert hook._child_due()==(False,60.)
    elapsed[0]=300
    assert hook._child_due()==(True,0.)


def test_pdf_new_pending_index_eligible_immediately(tmp_path):
    hook=pdf(tmp_path, monotonic=lambda:10.)
    hook.last_child_finished=0.
    index(tmp_path, {'status':'PENDING'})
    assert hook._child_due()==(True,0.)


def test_pdf_retry_wakes_at_existing_due_time(tmp_path):
    index(tmp_path, {'status':'PARTIAL','last_error_code':'NETWORK','updated_at':(NOW-timedelta(seconds=270)).isoformat()})
    hook=pdf(tmp_path, monotonic=lambda:10.)
    hook.last_child_finished=0.
    assert hook._child_due()==(False,30.)
    hook.clock=lambda:NOW+timedelta(seconds=30)
    assert hook._child_due()==(True,0.)


def test_pdf_completed_and_unknown_index_wait_for_fallback(tmp_path):
    path=index(tmp_path, {'status':'READY'})
    hook=pdf(tmp_path, monotonic=lambda:10.)
    hook.last_child_finished=0.
    assert hook._child_due()==(False,60.)
    path.write_text('{broken')
    assert hook._queue_probe()['status']=='CANNOT_CONFIRM'
    assert hook._child_due()==(False,60.)


def test_pdf_busy_cycle_gate_never_spawns(tmp_path):
    hook=pdf(tmp_path)
    hook.cycle_active.set()
    hook.cancel=Event([NOW])
    hook._run_child=lambda:pytest.fail('producer while cycle active')
    hook._run()
    assert hook.cancel.waits==[hook.poll_seconds]


def test_pdf_monitor_error_does_not_release_alive_owner(tmp_path):
    class Child:
        returncode=None
        def __init__(self):self.n=0
        def poll(self):
            self.n+=1
            if self.n==1:raise OSError('monitor transient')
            self.returncode=0
            return 0
        def wait(self, timeout):return 0
    child=Child()
    count=[]
    def spawn(command, **kwargs):
        count.append(command)
        kwargs['stdout'].write(b'{"status":"NO_RETRYABLE_TASKS"}\n')
        return child
    hook=pdf(tmp_path,popen_factory=spawn)
    hook.cancel=Event([NOW],limit=5)
    assert hook._run_child()['status']=='NO_RETRYABLE_TASKS'
    assert child.n==2 and len(count)==1 and hook.child is None
    assert '--pdf-time-budget-seconds' in count[0] and '90' in count[0]
    assert hook.wall_seconds==150


def test_pdf_unreaped_owner_never_starts_second_child(tmp_path):
    class Child:
        returncode=0
        def poll(self): return 0
        def wait(self, timeout):raise subprocess.TimeoutExpired('fixture',timeout)
    child=Child()
    count=[]
    hook=pdf(tmp_path,popen_factory=lambda *a,**kw:count.append(1) or child)
    assert hook._run_child()['status']=='PDF_QUEUE_CHILD_REAP_UNCONFIRMED'
    assert hook.child is child
    assert hook._run_child()['status']=='PDF_QUEUE_CHILD_REAP_UNCONFIRMED'
    assert len(count)==1


def test_pdf_log_failure_does_not_repeat_successful_work(tmp_path, monkeypatch):
    hook=pdf(tmp_path)
    hook.cancel=Event([NOW])
    called=[]
    hook._child_due=lambda:(True,0.)
    hook._run_child=lambda:called.append(1) or {'status':'NO_RETRYABLE_TASKS'}
    monkeypatch.setattr(daemon,'_emit_pdf_queue',lambda *a:(_ for _ in ()).throw(OSError('log full')))
    hook._run()
    assert called==[1]
