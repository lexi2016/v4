from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.v35_api.preselection_router import create_preselection_router
from apps.api.v35_api.runtime_router import create_runtime_router
from contracts.close_timeline import CLOSE_TIMELINE
from domains.task_status import _closing_task_projection, _timeline_receipt
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.execution_ledger import ExecutionLedger

DATE='20261026'
ITEM=next(x for x in CLOSE_TIMELINE if x['node_id']=='FUPAN_VIDEO_CHECK')
FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)
WORKLOAD=next(row for row in load_workload_catalog().workloads if row.workload_id==ITEM['workload_id'])

def test_explicit_date_does_not_discover_history_but_validates_date():
    class Reader:
        def read(self,date,limit,*,offset): return {'trade_date':date,'limit':limit,'offset':offset}
    calls=[]
    def catalog():
        calls.append('catalog');return {'default_date':DATE,'system_date':DATE}
    def validate(date):
        if date != DATE: raise ValueError('invalid date')
        return date
    app=FastAPI();router=create_preselection_router(Reader(),get_catalog=catalog,validate_date=validate);app.include_router(router)
    client=TestClient(app)
    assert client.get(f'/api/v3/preselection-pools?date={DATE}&limit=20&page=2').json()['offset']==20
    assert calls==[]
    assert client.get('/api/v3/preselection-pools').json()['selected_date']==DATE
    assert calls==['catalog']
    with pytest.raises(ValueError,match='invalid date'):client.get('/api/v3/preselection-pools?date=invalid')

def dispatch(status='SUCCEEDED', business=None):
    return dict(FLAGS,business_date=DATE,scheduled_date=DATE,target_date=DATE,mode='LIVE',run_id='dispatch-1',status=status,
        selected_workload_ids=[ITEM['workload_id']],workload_results=[dict(workload_id=ITEM['workload_id'],status=status,stdout=json.dumps(business) if business else '')])

def projection(receipt,execution=None,**kw):
    return _closing_task_projection(ITEM,receipt,execution,business_date=DATE,receipt_path=None,chain_verified=kw.get('verified',True),not_due=kw.get('not_due',False),workload=kw.get('workload',WORKLOAD))

def test_dispatch_success_never_becomes_business_ready():
    receipt=dispatch()
    assert projection(receipt,receipt)['task_state']=='CANNOT_CONFIRM'
    assert projection(receipt,receipt)['run_id']=='dispatch-1'

def test_legacy_failed_receipt_remains_visible_without_invented_run():
    receipt=dict(FLAGS,node_id=ITEM['node_id'],date=DATE,status='FAIL')
    result=projection(receipt)
    assert result['task_state']=='FAILED'
    assert result['run_id'] is None
    assert result['binding_status']=='CANNOT_CONFIRM'

@pytest.mark.parametrize('status,state',[('QUEUED_BEHIND','QUEUED'),('RUNNING','RUNNING'),('WAITING_SOURCE_UPDATE','WAITING_DEPENDENCY'),('PARTIAL_WITH_ROWS','PARTIAL')])
def test_business_receipt_states_are_distinct(status,state):
    receipt=dict(FLAGS,node_id=ITEM['node_id'],date=DATE,status=status,run_id='business-1')
    assert projection(receipt)['task_state']==state

def test_ready_requires_exact_business_receipt_and_dispatch_binding():
    business=dict(FLAGS,node_id=ITEM['node_id'],date=DATE,status='READY',run_id='business-1',source_sha256='a'*64)
    assert projection(business,dispatch(business=business))['task_state']=='READY'
    assert projection(business,dispatch())['task_state']=='CANNOT_CONFIRM'
    assert projection(business,dispatch(business=business),verified=False)['task_state']=='CANNOT_CONFIRM'
    assert projection({**business,'date':'20261025'},dispatch(business=business))['task_state']=='CANNOT_CONFIRM'
    assert projection({**business,'owner_id':'wrong'},dispatch(business=business))['task_state']=='CANNOT_CONFIRM'
    wrong_target={**business,'target_date':'20261025'}
    assert projection(wrong_target,dispatch(business=wrong_target))['task_state']=='CANNOT_CONFIRM'

def test_no_receipt_only_planned_before_slot():
    assert projection(None,not_due=True)['task_state']=='PLANNED'
    assert projection(None)['task_state']=='CANNOT_CONFIRM'

def test_fixed_receipt_wrong_date_is_rejected_and_original_status_retained(tmp_path):
    path=tmp_path/'runtime_graph/evidence/scheduler_status'/DATE/f"{ITEM['node_id']}.json"
    path.parent.mkdir(parents=True);path.write_text(json.dumps(dict(FLAGS,node_id=ITEM['node_id'],date='20261025',status='READY',run_id='old')))
    result=_timeline_receipt(ITEM,catalog=load_workload_catalog(),ledger=ExecutionLedger(tmp_path/'dispatcher'),receipts=(),business_date=DATE,data_root=tmp_path,stage_selection_root=None,now=datetime(2026,10,26,22,tzinfo=ZoneInfo('Asia/Shanghai')))
    assert result['status']=='READY'
    assert result['task_state']=='CANNOT_CONFIRM'
    assert result['business_date']==DATE

def test_runtime_reader_env_is_local_and_explicit_ledger_wins(tmp_path,monkeypatch):
    import apps.api.v35_api.runtime_router as module
    observed=[]
    monkeypatch.setenv('V4_TASK_STATUS_LEDGER_ROOT',str(tmp_path/'main-ledger'))
    monkeypatch.setenv('V4_TASK_STATUS_EVIDENCE_ROOT',str(tmp_path/'main-evidence'))
    def build(catalog,ledger,date,**kw):
        observed.append((ledger.root,kw['data_root']));return {'business_date':date}
    monkeypatch.setattr(module,'build_task_status',build)
    for explicit in [None,tmp_path/'explicit']:
        app=FastAPI();app.include_router(create_runtime_router(tmp_path/'v4-data',ledger_root=explicit))
        assert TestClient(app).get(f'/api/v3/tasks/status?date={DATE}').json()['business_date']==DATE
    assert observed==[(tmp_path/'main-ledger',tmp_path/'main-evidence'),(tmp_path/'explicit',tmp_path/'main-evidence')]


def test_unbound_business_receipt_does_not_borrow_dispatch_run_id():
    receipt=dict(FLAGS,node_id=ITEM['node_id'],date=DATE,status='FAIL',run_id='old-business-run')
    result=projection(receipt,dispatch())
    assert result['task_state']=='FAILED'
    assert result['run_id'] is None
    assert result['business_run_id']=='old-business-run'
    assert projection({**receipt,'status':'READY'},dispatch('FAILED',business={**receipt,'status':'READY'}))['task_state']=='CANNOT_CONFIRM'


def test_status_next_due_uses_existing_hk_securities_policy_without_enum_crash(monkeypatch):
    from dataclasses import replace
    import domains.task_status as module
    from contracts.trading_calendar import RunPolicy, TradingDayState
    workload=load_workload_catalog().workloads[0]
    monkeypatch.setattr(module,'resolve_market_states',lambda *_:dict(a_share=TradingDayState.NON_TRADING_DAY,hk_connect=TradingDayState.NON_TRADING_DAY,hk_securities=TradingDayState.FULL_TRADING_DAY))
    for policy in (RunPolicy.HK_SECURITIES_TRADE_DAY,RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY):
        assert module._schedule_date_is_eligible(replace(workload,run_policy=policy),DATE) is True
    for policy in (RunPolicy.HK_CONNECT_TRADE_DAY,RunPolicy.A_OR_HK_CONNECT_TRADE_DAY):
        assert module._schedule_date_is_eligible(replace(workload,run_policy=policy),DATE) is False


def test_node9_plan_label_and_due_follow_active_1610_workload_without_rewriting_contract(tmp_path):
    catalog=load_workload_catalog()
    workload=next(row for row in catalog.workloads if row.workload_id=='hk_connect_close_review')
    item=next(row for row in CLOSE_TIMELINE if row['node_id']=='hkconnect_model_selection_review')
    assert workload.slots==('1610',)
    assert item['planned_slot']=='1608'
    def read(hour,minute):
        return _timeline_receipt(item,catalog=catalog,ledger=ExecutionLedger(tmp_path/'dispatcher'),receipts=(),business_date=DATE,data_root=tmp_path,stage_selection_root=None,now=datetime(2026,10,26,hour,minute,tzinfo=ZoneInfo('Asia/Shanghai')))
    before=read(16,9)
    assert before['planned_slot']==before['planned_time']=='1610'
    assert before['label'].startswith('16:10 ')
    assert before['contract_planned_slot']=='1608'
    assert before['planned_time_source']=='WORKLOAD_CATALOG'
    assert before['task_state']=='PLANNED'
    assert read(16,10)['task_state']=='CANNOT_CONFIRM'
    assert item['planned_slot']=='1608' and item['label'].startswith('16:08 ')


def test_r3_business_receipt_conflicting_target_date_never_ready_even_if_stdout_matches():
    business=dict(FLAGS,node_id=ITEM['node_id'],date=DATE,target_date='20261025',status='READY',run_id='business-1')
    assert projection(business,dispatch(business=business))['task_state']=='CANNOT_CONFIRM'

@pytest.mark.parametrize('batch_status,workload_status,expected',[
    ('FAILED','SUCCEEDED','CANNOT_CONFIRM'),
    ('SUCCEEDED','FAILED','FAILED'),
])
def test_r3_aggregate_state_uses_unique_workload_result(batch_status,workload_status,expected):
    receipt=dispatch(batch_status)
    receipt['workload_results'][0]['status']=workload_status
    assert projection(receipt,receipt)['task_state']==expected

def test_r3_failed_aggregate_with_ambiguous_workload_does_not_invent_failure():
    receipt=dispatch('FAILED')
    receipt['workload_results'].append(dict(receipt['workload_results'][0]))
    assert projection(receipt,receipt)['task_state']=='CANNOT_CONFIRM'


@pytest.mark.parametrize('role,receipt_target', [('BUSINESS_DATE',DATE),('TARGET_DATE','20261027')])
def test_r3_legal_date_roles_allow_next_session_request_without_relaxing_node_target(role,receipt_target):
    from dataclasses import replace
    from contracts.trading_calendar import load_market_calendar,next_session
    following=next_session(load_market_calendar(),DATE,market='a_share')
    assert following=='20261027'
    business=dict(FLAGS,node_id=ITEM['node_id'],date=DATE,target_date=receipt_target,status='READY',run_id='business-1')
    execution={**dispatch(business=business),'target_date':following}
    result=projection(business,execution,workload=replace(WORKLOAD,target_date_role=role))
    assert result['task_state']=='READY'
    assert result['binding_status']=='BUSINESS_RECEIPT_BOUND_TO_DISPATCH_RUN'

def test_r3_unknown_or_conflicting_role_is_cannot_confirm():
    from dataclasses import replace
    business=dict(FLAGS,node_id=ITEM['node_id'],date=DATE,target_date=DATE,status='READY',run_id='business-1')
    assert projection(business,dispatch(business=business),workload=replace(WORKLOAD,target_date_role='UNKNOWN'))['task_state']=='CANNOT_CONFIRM'
    assert projection(business,dispatch(business=business),workload=None)['task_state']=='CANNOT_CONFIRM'
    following={**dispatch(business=business),'target_date':'20261027'}
    assert projection(business,following,workload=replace(WORKLOAD,target_date_role='TARGET_DATE'))['task_state']=='CANNOT_CONFIRM'
    conflicting={**dispatch(business=business),'resolved_dates':{ITEM['workload_id']:{'scheduled_date':DATE,'signal_date':DATE,'target_date':'20261025'}}}
    assert projection(business,conflicting)['task_state']=='CANNOT_CONFIRM'

def test_r3_next_session_role_requires_explicit_business_target():
    from dataclasses import replace
    business=dict(FLAGS,node_id=ITEM['node_id'],date=DATE,status='READY',run_id='business-1')
    execution={**dispatch(business=business),'target_date':'20261027'}
    assert projection(business,execution,workload=replace(WORKLOAD,target_date_role='TARGET_DATE'))['task_state']=='CANNOT_CONFIRM'

def test_r3_1500_unrelated_hourly_failure_does_not_fail_successful_close_materials(tmp_path):
    catalog=load_workload_catalog()
    item=next(row for row in CLOSE_TIMELINE if row['node_id']=='FUPAN_CLOSE_MATERIALS')
    execution=dict(FLAGS,business_date=DATE,scheduled_date=DATE,target_date=DATE,mode='LIVE',slot='1500',run_id='mixed-batch',status='FAILED',finished_at='2026-10-26T07:00:10Z',selected_workload_ids=['hourly_research','fupan_close_materials'],workload_results=[{'workload_id':'hourly_research','status':'FAILED'},{'workload_id':'fupan_close_materials','status':'SUCCEEDED'}])
    row=_timeline_receipt(item,catalog=catalog,ledger=ExecutionLedger(tmp_path/'dispatcher'),receipts=(execution,),business_date=DATE,data_root=tmp_path,stage_selection_root=None,now=datetime(2026,10,26,22,tzinfo=ZoneInfo('Asia/Shanghai')),chain_verified=True)
    assert row['status']=='FAILED'  # Original aggregate evidence is retained.
    assert row['task_state']=='CANNOT_CONFIRM'  # No independent business result.
