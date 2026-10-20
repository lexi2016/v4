"""Offline cancellation acceptance: real durable queue, no inference or collection."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure.owned_io import SafeRoot
from v4.manager_workbench.announcement_update import AnnouncementUpdate
from v4.manager_workbench.api import create_router
from v4.manager_workbench.contracts import HK, JobRecord, JobState, Phase, RunContext
from v4.manager_workbench.jobs import JobCoordinator, StepFailure
from v4.manager_workbench.store import WorkbenchStore
from test_manager_announcement_flash_runner import _bridge_module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('Offline cancellation test attempted network')
    monkeypatch.setattr(socket.socket, 'connect', denied)


def _queue_fixture(tmp_path, monkeypatch):
    bridge = _bridge_module()
    spec = importlib.util.spec_from_file_location('user_stop_real_announcement_queue', bridge.PIPELINE_ROOT/'announcement_queue.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(__import__('sys').modules, spec.name, module)
    spec.loader.exec_module(module)
    queue = module.SerialAnnouncementQueue(tmp_path/'queue', bridge.QUEUE_ID, 'stop-test-model', max_attempts=1)
    def payload(name, size):
        body = name*size
        return {'date':'2026-10-20', 'market':'HK', 'article_id':name, 'source_sha256':'1'*64,
            'body_sha256':bridge.sha(body.encode()), 'prompt_sha256':'2'*64, 'model_id':'stop-test-model',
            'configuration_sha256':'3'*64, 'rules':'stop-fixture', 'role':'announcement_reader',
            'stage':'stop-fixture', 'article_body':body}
    old = queue.enqueue(payload('OLD', 1))['idempotency_key']
    queue.run_next(lambda _job:'{}', lambda _job, parsed:parsed, idempotency_keys={old})
    a = queue.enqueue(payload('A', 10))['idempotency_key']
    b = queue.enqueue(payload('B', 20))['idempotency_key']
    return bridge, module, queue, old, a, b


@pytest.mark.parametrize('request_point', ['before_dispatch', 'in_flight', 'after_commit'])
def test_user_stop_preserves_success_and_pending_and_finishes_inflight(tmp_path, monkeypatch, request_point):
    bridge, module, queue, old, a, b = _queue_fixture(tmp_path, monkeypatch)
    original = deepcopy(queue._load_state()['jobs'][old])
    old_files = {p:p.read_bytes() for p in (tmp_path/'queue'/'jobs'/old).iterdir()}
    io = SafeRoot(tmp_path/'state')
    stop = bridge._UserStop(io, 'a'*32, [])
    calls = []
    def request():
        bridge._write_json(io, stop.ref, {'schema':'v4.manager_workbench.announcement_flash_stop.v1',
            'job_id':'a'*32, 'reason':'USER_REQUEST', 'requested_at':'2026-10-20T14:00:00+08:00'})
    if request_point == 'before_dispatch':
        request()
    def execute(job):
        calls.append(job.idempotency_key)
        assert queue._load_state()['jobs'][a]['status'] == 'RUNNING'
        if request_point == 'in_flight':
            request()
        return '{"saved":"successful in-flight result"}'
    def report(_count):
        assert queue._load_state()['jobs'][a]['status'] == 'SUCCEEDED'
        if request_point == 'after_commit':
            request()
    dispatched = []
    completed, receipt = bridge._dispatch_pending_queue_keys(queue, execute, lambda _job, value:value,
        {old,a,b}, completed=0, max_model_calls=None, dispatched_keys=dispatched,
        on_result=report, stop_requested=stop)
    jobs = queue._load_state()['jobs']
    expected = [] if request_point == 'before_dispatch' else [a]
    assert calls == dispatched == expected
    assert completed == len(expected) and receipt == bridge._user_stop_receipt()
    assert jobs[a]['status'] == ('PENDING' if not expected else 'SUCCEEDED')
    assert jobs[b]['status'] == 'PENDING' and jobs[b]['attempt_count'] == 0
    assert jobs[old] == original and all(p.read_bytes()==raw for p,raw in old_files.items())
    assert not any(job['status']=='RUNNING' for job in jobs.values())
    if expected:
        assert (tmp_path/'queue'/jobs[a]['validated_path']).read_bytes()


def test_normal_system_failure_wins_over_simultaneous_user_stop(tmp_path, monkeypatch):
    bridge, module, queue, old, a, b = _queue_fixture(tmp_path, monkeypatch)
    requested = []
    def fail(_job):
        requested.append(True)
        raise module.ExecutorFailure('TransportError', code='TransportError', raw_response=b'{}')
    completed, receipt = bridge._dispatch_pending_queue_keys(queue, fail, lambda _job, parsed:parsed,
        {a,b}, completed=0, max_model_calls=None, dispatched_keys=[], on_result=lambda _n:None,
        stop_requested=lambda:bool(requested))
    assert completed == 1 and receipt['failure_code'] == 'TransportError'
    assert queue._load_state()['jobs'][a]['status'] == 'FAILED'
    assert queue._load_state()['jobs'][b]['status'] == 'PENDING'


def _parent(tmp_path):
    store = WorkbenchStore(tmp_path/'parent')
    jobs = JobCoordinator(store, workers=1)
    service = SimpleNamespace(store=store, jobs=jobs, config=SimpleNamespace())
    update = AnnouncementUpdate(service, clock=lambda:datetime(2026,10,20,14,0,tzinfo=HK))
    context = RunContext(target_date='20261020', phase=Phase.MANUAL, cutoff='2026-10-20T14:00:00+08:00',
        trigger='MANUAL', rules_version='V4_ANNOUNCEMENT_FLASH_INCREMENTAL_V1', scope_refs={'capture_operation':'ANNOUNCEMENT_FLASH_INCREMENTAL'})
    job = JobRecord(job_id='a'*32, run_id='a'*32, context=context, state=JobState.RUNNING,
        step='FLASH_SELECTION', completed_count=7, total_count=12)
    store.save_job(job)
    return update, service, job


def test_stop_request_api_is_idempotent_and_does_not_pretend_inflight_is_terminal(tmp_path):
    update, service, job = _parent(tmp_path)
    app=FastAPI();app.include_router(create_router(service))
    try:
        with TestClient(app) as client:
            response = client.post(f'/api/v4/manager-workbench/announcement-flash/{job.job_id}/stop')
            assert response.status_code == 202
            assert response.json()['state'] == 'STOP_REQUESTED'
            before = service.store.io.read_bytes(update._job_ref(job.job_id,'stop-request.json'))
            again = client.post(f'/api/v4/manager-workbench/announcement-flash/{job.job_id}/stop')
            assert again.json() == response.json()
            assert service.store.io.read_bytes(update._job_ref(job.job_id,'stop-request.json')) == before
            assert service.jobs.get(job.job_id).state == JobState.RUNNING
    finally:
        service.jobs.stop()


def _save(update, job, basename, value):
    from v4.manager_workbench.announcement_update import _canonical
    update.service.store.io.write_bytes(update._job_ref(job.job_id,basename), _canonical(value)+b'\n')


def test_parent_queued_stop_never_starts_capture_or_model_and_keeps_counts(tmp_path):
    update, service, job = _parent(tmp_path)
    try:
        _save(update, job, 'progress.json', {'completed':8,'total':13,'queue_counts':{'SUCCEEDED':8,'PENDING':5}})
        update.stop(job.job_id)
        # No config/capture bindings exist: taking _work's normal path would fail.
        service.jobs._execute(job, update._work, service.jobs._scope(job.context))
        saved = service.jobs.get(job.job_id)
        assert saved.state == JobState.USER_STOPPED and saved.completed_count == 8 and saved.total_count == 13
        assert saved.finished_at and saved.retryable is False
        progress = update._read_job_artifact(job.job_id,'progress.json')
        assert progress['step'] == 'USER_STOPPED' and progress['queue_counts']['SUCCEEDED'] == 8
    finally:
        service.jobs.stop()


@pytest.mark.parametrize('runner_state', ['USER_STOPPED', 'SUCCEEDED'])
def test_parent_reads_child_terminal_and_counts_even_when_last_poll_missed(tmp_path, runner_state):
    update, service, job = _parent(tmp_path)
    try:
        result = {'schema':'v4.manager_workbench.announcement_flash_result.v1','job_id':job.job_id,
            'target_trade_date':'20261020','state':runner_state,
            'counts':{'queue':{'succeeded':9,'failed':1,'pending':3},'new_candidate_stocks':2},
            'stocks':[{'symbol':'HK.01234','source_sha256':'1'*64}],
            'system_stop':None if runner_state=='SUCCEEDED' else {'failure_code':'USER_STOPPED'}}
        _save(update, job, 'result.json', result)
        _save(update, job, 'progress.json', {'step':runner_state if runner_state=='USER_STOPPED' else 'DONE',
            'completed':9,'total':13})
        original = service.store.io.read_bytes(update._job_ref(job.job_id,'result.json'))
        # A concurrent stop after durable success must not rewrite that success.
        assert update.stop(job.job_id) == {'job_id':job.job_id,'state':runner_state,'stop_requested':False}
        service.jobs._execute(job, lambda j:update._consume_runner_exit(j,0), service.jobs._scope(job.context))
        saved = service.jobs.get(job.job_id)
        assert saved.state == JobState(runner_state) and saved.completed_count == 9 and saved.total_count == 13
        assert saved.finished_at and saved.failure_code is None
        assert service.store.io.read_bytes(update._job_ref(job.job_id,'result.json')) == original
        index = service.store.cursor('announcement_flash_result_index')
        assert index['items'][0]['job_id'] == job.job_id
    finally:
        service.jobs.stop()


def test_parent_nonzero_exit_remains_failed_despite_stop_request_and_keeps_last_counts(tmp_path):
    update, service, job = _parent(tmp_path)
    try:
        update.stop(job.job_id)
        _save(update, job, 'progress.json', {'step':'FAILED','failure_code':'REAL_TRANSPORT_FAILURE',
            'completed':9,'total':13})
        service.jobs._execute(job, lambda j:update._consume_runner_exit(j,1), service.jobs._scope(job.context))
        saved = service.jobs.get(job.job_id)
        assert saved.state == JobState.FAILED and saved.failure_code == 'REAL_TRANSPORT_FAILURE'
        assert saved.completed_count == 9 and saved.total_count == 13
    finally:
        service.jobs.stop()


def test_sigterm_is_cooperative_and_persists_user_request_without_killing_attempt(tmp_path):
    bridge = _bridge_module()
    previous = signal.getsignal(signal.SIGTERM)
    io = SafeRoot(tmp_path/'signal')
    with bridge._cooperative_stop_signals() as signalled:
        stop = bridge._UserStop(io, 'a'*32, signalled)
        assert stop() is False
        os.kill(os.getpid(), signal.SIGTERM)
        assert signalled == [signal.SIGTERM]
        assert stop() is True
        raw = io.read_bytes(stop.ref)
        os.kill(os.getpid(), signal.SIGTERM)
        assert stop() is True and io.read_bytes(stop.ref) == raw
    assert signal.getsignal(signal.SIGTERM) == previous


def test_main_stop_before_run_preserves_progress_and_never_calls_model(tmp_path, monkeypatch):
    bridge = _bridge_module()
    state = tmp_path/'main';io=SafeRoot(state);job_id='a'*32
    base=f'announcement_flash/jobs/{job_id}'
    bridge._write_json(io,base+'/input.json',{'schema':'v4.manager_workbench.announcement_flash_input.v1',
        'job_id':job_id,'target_date':'20261020'})
    bridge._write_json(io,base+'/progress.json',{'step':'FLASH_SELECTION','completed':7,'total':12})
    stop=bridge._UserStop(io,job_id,[signal.SIGTERM]);assert stop()
    monkeypatch.setattr(bridge,'_run',lambda *_a,**_kw:pytest.fail('stopped batch dispatched model planning'))
    assert bridge.main(['--state-root',str(state),'--capture-root',str(tmp_path/'capture'),'--job-id',job_id]) == 0
    progress=json.loads(io.read_bytes(base+'/progress.json'))
    assert progress['step']=='USER_STOPPED' and progress['completed']==7 and progress['total']==12


def test_run_closes_user_stop_before_any_transport_and_keeps_frozen_history(tmp_path, monkeypatch):
    from test_manager_announcement_flash_runner import _transport_canary_runtime_fixture
    bridge, source_input, material, plan, queue, state_root, capture_root, keys, originals = _transport_canary_runtime_fixture(tmp_path, monkeypatch)
    child_id='b'*32
    child={**source_input,'job_id':child_id,
        'resume_root':{'source_job_id':source_input['job_id'],'source_input_sha256':plan['source_input_sha256']},
        'resume_source':{**plan,'schema':'v4.manager_workbench.announcement_flash_resume.v1',
            'transport_recovery':plan,'resume_action':'CANARY','canary_passed':False}}
    # A queued request reaches _run's real dispatch boundary. The fixture's
    # transport is forbidden and every original successful/failed/pending item stays intact.
    def forbidden(*_args,**_kwargs):
        pytest.fail('user-stopped _run constructed model transport')
    import sys
    monkeypatch.setattr(sys.modules['automatic_canary_server'],'GatedStreamingTransport',forbidden)
    result=bridge._run(child,state_root=state_root,capture_root=capture_root,job_id=child_id,
        progress=lambda _value:None,shared_root=tmp_path/'shared',resume_frozen_batch=True,
        resume_action='CANARY',max_model_calls=1,resume_source_job_id=source_input['job_id'],
        resume_source_input_sha256=plan['source_input_sha256'],stop_requested=lambda:True)
    assert result['state']=='USER_STOPPED' and result['system_stop']==bridge._user_stop_receipt()
    assert result['resume']['model_calls']==0 and queue.dispatched==[]
    assert all(queue.jobs[key]==value for key,value in originals.items())
    assert not any(job['status']=='RUNNING' for job in queue.jobs.values())
