from __future__ import annotations
import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from contracts.runtime_tasks import DispatchRequest,DispatchMode
from infrastructure.scheduling import dispatcher as dispatch
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.catalog import load_workload_catalog
from ops import run_v4_macos_scheduler_due as due
from ops import run_v4_macos_scheduler_daemon as daemon

ROOT=Path(__file__).resolve().parents[1]
TZ=ZoneInfo('Asia/Shanghai')
MOMENT=datetime(2026,10,28,18,30,tzinfo=TZ)


def bind_release(tmp_path,monkeypatch):
    entries=[]
    for relative in dispatch._RUNTIME_IDENTITY_FILES:
        raw=(ROOT/relative).read_bytes();entries.append({'path':relative,'kind':'file','sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)})
    body={'schema_version':'v4.release_candidate.v1','candidate':{'app_root':str(ROOT),'release_id':'source-closure-test'},'application_inventory':{'entries':entries,'entry_count':len(entries),'aggregate_sha256':hashlib.sha256(json.dumps(entries,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()}}
    path=tmp_path/'manifest.json';raw=json.dumps(body).encode();path.write_bytes(raw)
    for k,v in {'V4_APP_ROOT':str(ROOT),'V4_RELEASE_ID':'source-closure-test','V4_RELEASE_MANIFEST_PATH':str(path),'V4_RELEASE_MANIFEST_SHA256':hashlib.sha256(raw).hexdigest()}.items():monkeypatch.setenv(k,v)
    return body


def test_actual_source_exposes_scheduler_interfaces_without_candidate_imports():
    from infrastructure.scheduling.execution_ledger import SchedulerLaneExpired
    from infrastructure.scheduling.dispatcher import refresh_retry_source_identity
    assert issubclass(SchedulerLaneExpired,ValueError)
    assert Path(dispatch.__file__).resolve().is_relative_to(ROOT)
    for name in ['dispatch_claim_blocks_retry','try_acquire_scheduler_lane','validate_scheduler_lane','write_scheduler_observation']:
        assert callable(getattr(ExecutionLedger,name))
    assert refresh_retry_source_identity({'descriptors':[]})['status']=='CANNOT_CONFIRM'


def test_actual_source_existing_live_claim_blocks_new_release(tmp_path):
    ledger=ExecutionLedger(tmp_path.resolve());request=DispatchRequest('20261028','20261028','20261029','1700',DispatchMode.LIVE)
    claim=ledger.try_claim_dispatch(request);before=(ledger.root/claim.relative_path).read_bytes()
    assert due._slot_blocks_retry(ledger.root,'20261028','1700',moment=MOMENT,release_id='renamed-release')
    assert (ledger.root/claim.relative_path).read_bytes()==before


def test_actual_source_lane_pulse_uses_real_ledger_and_original_slot(tmp_path):
    calls=[]
    class Child:
        pid=987654321
        def poll(self):return None
        def wait(self,timeout=None):return 0
    def fake_child(command,**kwargs):calls.append((command,kwargs));return Child()
    lanes=daemon.SlotProcessLanes(['--ledger-root',str(tmp_path.resolve())],release_id='source-closure',popen_factory=fake_child,clock=lambda:MOMENT)
    assert type(lanes.ledger) is ExecutionLedger
    lanes.enqueue('20261028','1720',MOMENT);lanes.pulse(MOMENT)
    assert len(calls)==1 and len(lanes.active)==1
    command,kwargs=calls[0];assert command[command.index('--slot')+1]=='1720' and command[command.index('--date')+1]=='20261028'
    assert kwargs['start_new_session'] and kwargs['pass_fds'] and kwargs['env']['V4_SCHEDULER_RESOLVED_SLOT']=='1720'
    records=[json.loads(p.read_text()) for p in (tmp_path/'scheduler_observations/live/20261028/1720').glob('*.json')]
    assert any(x['status']=='RUNNING' for x in records)
    for job in lanes.active.values():job['stdout'].close();job['stderr'].close()


def test_actual_source_lane_fd_and_cutoff_guard(tmp_path,monkeypatch):
    from infrastructure.scheduling.execution_ledger import SchedulerLaneExpired
    ledger=ExecutionLedger(tmp_path.resolve());fd=ledger.try_acquire_scheduler_lane('A_LONG')
    assert fd is not None
    try:
        for k,v in {'V4_SCHEDULER_LANE_FD':str(fd),'V4_SCHEDULER_LANE_NAME':'A_LONG','V4_SCHEDULER_RESOLVED_DATE':'20261028','V4_SCHEDULER_RESOLVED_SLOT':'1700'}.items():monkeypatch.setenv(k,v)
        ledger.validate_scheduler_lane('20261028','1700',now=MOMENT)
        with pytest.raises(SchedulerLaneExpired):ledger.validate_scheduler_lane('20261028','1700',now=MOMENT+timedelta(days=1))
        monkeypatch.setenv('V4_SCHEDULER_RESOLVED_SLOT','1720')
        with pytest.raises(ValueError,match='IDENTITY_INVALID'):ledger.validate_scheduler_lane('20261028','1700',now=MOMENT)
    finally:os.close(fd)


def test_actual_source_retry_identity_and_unknown_attempt_budget(tmp_path):
    from infrastructure.scheduling.dispatcher import refresh_retry_source_identity
    root=tmp_path.resolve();pointer=root/'current.txt';pointer.write_text('original')
    old=refresh_retry_source_identity({'descriptors':[{'path':str(pointer),'kind':'pointer'}]});assert old['status']=='IDENTIFIED'
    pointer.write_text('changed');assert refresh_retry_source_identity(old)['fingerprint']!=old['fingerprint']
    ledger=ExecutionLedger(root)
    def failed(name,time):ledger.write_receipt('receipts/live/20261028/1720/'+name+'.dispatch-receipt.json',{'status':'FAILED','failure_class':'INPUT_MISSING','finished_at':time,'source_identity':{'status':'CANNOT_CONFIRM','descriptors':[]}})
    failed('first','2026-10-28T09:20:00Z')
    assert not due._slot_blocks_retry(root,'20261028','1720',moment=MOMENT,release_id='new-code')
    failed('second','2026-10-28T09:30:00Z')
    assert due._slot_blocks_retry(root,'20261028','1720',moment=MOMENT,release_id='different-code')


def test_dispatch_keeps_api_identity_gate_before_claim_or_executor(tmp_path,monkeypatch):
    for name in ['V4_APP_ROOT','V4_RELEASE_ID','V4_RELEASE_MANIFEST_PATH','V4_RELEASE_MANIFEST_SHA256']:monkeypatch.delenv(name,raising=False)
    calls=[];ledger=ExecutionLedger(tmp_path.resolve());request=DispatchRequest('20261028','20261028','20261028','1800',DispatchMode.LIVE)
    receipt=dispatch.dispatch_due(request,load_workload_catalog(),lambda *a:calls.append(a),ledger=ledger)
    assert receipt.status=='FAILED' and receipt.failure_class=='RELEASE_IDENTITY'
    assert not calls and not list(tmp_path.rglob('*.claim.json'))


def test_dispatch_rechecks_real_lane_before_executor_and_retains_release_fields(tmp_path,monkeypatch):
    bind_release(tmp_path,monkeypatch);ledger=ExecutionLedger(tmp_path.resolve());fd=ledger.try_acquire_scheduler_lane('DEFAULT');assert fd is not None
    day='20261028'
    for k,v in {'V4_SCHEDULER_LANE_FD':str(fd),'V4_SCHEDULER_LANE_NAME':'DEFAULT','V4_SCHEDULER_RESOLVED_DATE':day,'V4_SCHEDULER_RESOLVED_SLOT':'1800'}.items():monkeypatch.setenv(k,v)
    # Admission clock is explicit and deterministic; kernel-FD validation remains real.
    original_validate=ExecutionLedger.validate_scheduler_lane
    monkeypatch.setattr(ExecutionLedger,'validate_scheduler_lane',lambda self,date,slot:original_validate(self,date,slot,now=datetime.strptime(day+'1800','%Y%m%d%H%M').replace(tzinfo=TZ)))
    original_policy=dispatch.evaluate_run_policy;closed=[]
    def policy(*a,**k):
        result=original_policy(*a,**k)
        if not closed:os.close(fd);closed.append(True)
        return result
    monkeypatch.setattr(dispatch,'evaluate_run_policy',policy)
    catalog=load_workload_catalog();hourly=next(w for w in catalog.workloads if w.workload_id=='hourly_research');catalog=replace(catalog,workloads=(replace(hourly,slots=('1800',)),))
    calls=[];request=DispatchRequest(day,day,day,'1800',DispatchMode.LIVE)
    try:receipt=dispatch.dispatch_due(request,catalog,lambda *a:calls.append(a),ledger=ledger)
    finally:
        if not closed:os.close(fd)
    assert closed and not calls and receipt.status=='FAILED'
    assert receipt.app_root==str(ROOT) and receipt.release_id=='source-closure-test'
    assert receipt.invoked_workload_ids==() and receipt.started_workload_ids==()
    assert 'SCHEDULER_LANE_FD_INVALID' in receipt.workload_results[0]['stderr']
    assert receipt.source_identity['status']=='CANNOT_CONFIRM'
