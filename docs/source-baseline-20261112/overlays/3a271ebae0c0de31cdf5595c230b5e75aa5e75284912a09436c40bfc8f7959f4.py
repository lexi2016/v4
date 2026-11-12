from __future__ import annotations
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
import domains.task_status as module
from contracts.close_timeline import CLOSE_TIMELINE
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.execution_ledger import ExecutionLedger

DATE='20261026'
SLOT='2030'
CATALOG=load_workload_catalog()
WORKLOAD=next(w for w in CATALOG.workloads if w.workload_id=='fupan_video_check')
NODE=next(n for n in CLOSE_TIMELINE if n['workload_id']==WORKLOAD.workload_id)
NOW=datetime(2026,10,26,20,30,10,tzinfo=ZoneInfo('Asia/Shanghai'))
FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)

def write_observation(ledger,status='QUEUED_BEHIND',filename='f'*32,**extra):
    # Same shape and existing write_receipt path used by C2's wrapper.
    payload=dict(FLAGS,schema_version='v4.scheduler_observation.v1',business_date=DATE,slot=SLOT,status=status,lane='DEFAULT',planned_at='2026-10-26T20:30:00+08:00',queued_at='2026-10-26T20:30:00+08:00',observed_at='2026-10-26T20:30:00+08:00',cutoff_at='2026-10-26T23:59:59.999999+08:00')
    payload.update(extra)
    relative=f'scheduler_observations/live/{DATE}/{SLOT}/{filename}.observation.json'
    ledger.write_receipt(relative,payload)
    return ledger.root/relative

def read(ledger,now=NOW):
    return module._load_scheduler_slot_observations(ledger,CATALOG,DATE,now)

def claims(ledger,pid=12345):
    common=dict(run_id='dispatch-run',pid=pid,created_at='2026-10-26T20:30:00.001+08:00',scheduled_date=DATE,business_date=DATE,target_date=DATE,slot=SLOT,mode='LIVE')
    for relative,value in [
        (f'claims/live/{DATE}/{SLOT}/dispatch.claim.json',dict(common,schema_version='v3_5.dispatch_claim.v1')),
        (f'workloads/live/{DATE}/{SLOT}/{WORKLOAD.workload_id}.workload-claim.json',dict(common,schema_version='v3_5.workload_claim.v1',workload_id=WORKLOAD.workload_id)),
    ]:
        path=ledger.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

def project(ledger,observations,row=None,receipts=(),now=NOW):
    row=row or dict(task_state='CANNOT_CONFIRM',status='CANNOT_CONFIRM',last_run=None)
    return module._apply_scheduler_slot_observation(row,WORKLOAD,observations,ledger,DATE,receipts,now,timeline=True)

def test_queued_behind_reaches_real_logical_and_closing_rows_without_run_or_ready(tmp_path):
    ledger=ExecutionLedger(tmp_path)
    before=module.build_task_status(CATALOG,ledger,DATE,now=NOW,data_root=tmp_path/'data')
    path=write_observation(ledger,blocking_slot='1710',blocking_pid=9123)
    before_sha=hashlib.sha256(path.read_bytes()).hexdigest()
    result=module.build_task_status(CATALOG,ledger,DATE,now=NOW,data_root=tmp_path/'data')
    logical=next(r for r in result['groups']['logical'] if r['workload_id']==WORKLOAD.workload_id)
    node=next(r for r in result['timeline_nodes'] if r['node_id']==NODE['node_id'])
    assert logical['status']=='QUEUED_BEHIND'
    assert node['task_state']=='QUEUED' and node['run_id'] is None
    assert node['scheduler_execution']['owner_id']==WORKLOAD.owner_id
    assert node['scheduler_execution']['blocking_slot']=='1710'
    assert node['scheduler_execution']['business_ready'] is False
    assert result['timeline_nodes'][:8]==before['timeline_nodes'][:8]
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before_sha

@pytest.mark.parametrize('mutation',[
    {'business_date':'20261025'}, {'slot':'2040'}, {'lane':'A_LONG'},
    {'planned_at':'2026-10-26T20:31:00+08:00'}, {'observed_at':'2026-10-26T20:30:11+08:00'},
    {'queued_at':'2026-10-26T20:29:00+08:00'}, {'production_allowed':True},
    {'observed_at':'2026-10-26T20:30:00'}, {'schema_version':'wrong'},
])
def test_bad_identity_time_or_safety_never_falls_back_to_good_queue(tmp_path,mutation):
    ledger=ExecutionLedger(tmp_path);write_observation(ledger,filename='0'*32)
    write_observation(ledger,filename='1'*32,**mutation)
    assert project(ledger,read(ledger))['task_state']=='CANNOT_CONFIRM'

def test_hash_mismatch_is_not_hidden_by_an_older_valid_observation(tmp_path):
    ledger=ExecutionLedger(tmp_path);write_observation(ledger,filename='0'*32)
    path=write_observation(ledger,filename='1'*32);value=json.loads(path.read_text());value['status']='RUNNING';path.write_text(json.dumps(value))
    assert read(ledger)[SLOT]['status']=='CANNOT_CONFIRM'

@pytest.mark.parametrize('extra',[{'owner_id':'wrong-owner'},{'workload_id':'other-workload'}])
def test_explicit_catalog_identity_mismatch_is_unknown(tmp_path,extra):
    ledger=ExecutionLedger(tmp_path);write_observation(ledger,**extra)
    assert project(ledger,read(ledger))['task_state']=='CANNOT_CONFIRM'

def test_same_pulse_queue_then_running_ignores_uuid_order_and_binds_original_pid_claim(tmp_path,monkeypatch):
    ledger=ExecutionLedger(tmp_path)
    write_observation(ledger,'RUNNING',filename='0'*32,pid=12345,actual_started_at='2026-10-26T20:30:00+08:00')
    write_observation(ledger,'QUEUED',filename='f'*32)
    claims(ledger);monkeypatch.setattr(module,'_scheduler_pid_alive',lambda pid:pid==12345)
    result=project(ledger,read(ledger))
    assert result['task_state']=='RUNNING' and result['run_id']=='dispatch-run'
    assert result['binding_status']=='EXACT_WORKLOAD_CLAIM_PID'

def test_conflicting_same_rank_running_is_ambiguous(tmp_path):
    ledger=ExecutionLedger(tmp_path)
    for name,pid in [('0'*32,12345),('f'*32,12346)]:
        write_observation(ledger,'RUNNING',filename=name,pid=pid,actual_started_at='2026-10-26T20:30:00+08:00')
    assert 'AMBIGUOUS' in read(ledger)[SLOT]['reason']
    assert project(ledger,read(ledger))['task_state']=='CANNOT_CONFIRM'

@pytest.mark.parametrize('condition',['missing_claim','wrong_pid','dead_pid','finished_run'])
def test_running_without_current_matching_original_claim_is_unknown(tmp_path,monkeypatch,condition):
    ledger=ExecutionLedger(tmp_path)
    write_observation(ledger,'RUNNING',pid=12345,actual_started_at='2026-10-26T20:30:00+08:00')
    if condition!='missing_claim':claims(ledger,12346 if condition=='wrong_pid' else 12345)
    monkeypatch.setattr(module,'_scheduler_pid_alive',lambda _:condition!='dead_pid')
    receipts=({'run_id':'dispatch-run'},) if condition=='finished_run' else ()
    assert project(ledger,read(ledger),receipts=receipts)['task_state']=='CANNOT_CONFIRM'

def test_expired_visible_but_verified_ready_and_later_terminal_receipt_take_precedence(tmp_path):
    ledger=ExecutionLedger(tmp_path)
    write_observation(ledger,'EXPIRED',observed_at='2026-10-27T00:00:00+08:00',reason='QUEUED_PAST_ORIGINAL_CUTOFF')
    now=datetime(2026,10,27,0,2,tzinfo=ZoneInfo('Asia/Shanghai'));observations=read(ledger,now)
    assert project(ledger,observations,now=now)['task_state']=='FAILED'
    ready=dict(task_state='READY',status='SUCCESS',last_run='2026-10-26T20:31:00+08:00',run_id='business-dispatch')
    assert project(ledger,observations,row=ready,now=now)['task_state']=='READY'
    later=dict(task_state='FAILED',status='FAIL',last_run='2026-10-27T00:01:00+08:00',run_id='later-failure')
    assert project(ledger,observations,row=later,now=now)['run_id']=='later-failure'

def test_process_finished_even_ready_result_cannot_create_business_ready(tmp_path):
    ledger=ExecutionLedger(tmp_path)
    write_observation(ledger,'FINISHED',pid=12345,actual_started_at='2026-10-26T20:30:00+08:00',return_code=0,result_status='READY')
    assert project(ledger,read(ledger))['task_state']=='CANNOT_CONFIRM'

def test_reader_budget_and_symlink_fail_closed_and_legacy_namespace_is_optional(tmp_path,monkeypatch):
    ledger=ExecutionLedger(tmp_path/'ledger')
    assert read(ledger)=={}
    write_observation(ledger,filename='0'*32);write_observation(ledger,filename='1'*32)
    monkeypatch.setattr(module,'_SCHEDULER_OBSERVATION_MAX_FILES',1)
    assert read(ledger)[SLOT]['reason']=='OBSERVATION_FILE_BUDGET_EXCEEDED'
    monkeypatch.setattr(module,'_SCHEDULER_OBSERVATION_MAX_FILES',512)
    path=ledger.root/f'scheduler_observations/live/{DATE}/{SLOT}'/('2'*32+'.observation.json')
    path.symlink_to(tmp_path/'outside')
    assert read(ledger)[SLOT]['status']=='CANNOT_CONFIRM'


def test_process_only_finished_cannot_erase_existing_blocked_business_result(tmp_path):
    ledger=ExecutionLedger(tmp_path)
    write_observation(ledger,'FINISHED',pid=12345,actual_started_at='2026-10-26T20:30:00+08:00',observed_at='2026-10-26T20:30:05+08:00',return_code=0,result_status='SUCCEEDED')
    blocked=dict(task_state='WAITING_DEPENDENCY',status='BLOCKED',last_run='2026-10-26T20:30:01+08:00',reason='SELECTOR_POINTER_METADATA_MISSING')
    result=project(ledger,read(ledger),row=blocked)
    assert result['task_state']=='WAITING_DEPENDENCY'
    assert result['reason']=='SELECTOR_POINTER_METADATA_MISSING'
    assert result['scheduler_execution']['task_state']=='CANNOT_CONFIRM'


def test_slot_observation_cannot_assign_workload_excluded_by_existing_dispatch_cadence(tmp_path,monkeypatch):
    import infrastructure.scheduling.dispatcher as dispatcher
    ledger=ExecutionLedger(tmp_path);write_observation(ledger)
    monkeypatch.setattr(dispatcher,'_cadence_eligible',lambda workload,request:False)
    result=project(ledger,read(ledger))
    assert result['task_state']=='CANNOT_CONFIRM'
    assert 'scheduler_execution' not in result


def test_old_queue_observation_past_cutoff_is_unknown_without_invented_expiry(tmp_path):
    ledger=ExecutionLedger(tmp_path);write_observation(ledger,blocking_slot=None,blocking_pid=None,reason='PERSISTED_LANE_OWNER_ACTIVE')
    later=datetime(2026,10,27,0,0,1,tzinfo=ZoneInfo('Asia/Shanghai'))
    result=project(ledger,read(ledger,later),now=later)
    assert result['task_state']=='CANNOT_CONFIRM'
    assert result['binding_status']=='STALE_QUEUE_OBSERVATION_PAST_CUTOFF'
    assert result['scheduler_execution']['status']=='QUEUED_BEHIND'
