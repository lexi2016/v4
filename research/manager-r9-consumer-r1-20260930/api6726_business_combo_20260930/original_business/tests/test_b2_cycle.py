"""Actual cycle main, plan autorun, transaction and disk plan; synthetic leaf inputs.

The collection callback invokes the original mirror owner directly in a test.
This does NOT establish that a field release routes scheduled calls to mirrors.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from test_b1_history import wired, capture, snapshot
from domains import manager_research_evidence as authority
from v4.manager_research import workspace as ws, workspace_discovery as discovery, us_market_bridge
from v4.manager_research.workspace_projection import FLAGS
from ops import run_manager_announcement_cycle as worker


@pytest.fixture
def cycle(wired,monkeypatch,tmp_path):
    svc,p,clock=wired
    clock[0]=datetime.fromisoformat('2026-09-30T09:29:20+08:00')
    svc._catalyst_data_root=tmp_path/'empty';svc._workspace_ledger_root=None
    svc._close_observation_reader=None;svc.observation_reader=None
    svc.get_catalyst_observations=lambda day:dict(status='READY_EMPTY',target_trade_date=day,cards=[],**FLAGS)
    monkeypatch.setattr(ws,'_materials',lambda *a:dict(materials=[],coverage={},input_bindings=[],gaps=[]))
    monkeypatch.setattr(ws,'_discovery',lambda *a:dict(cards=[],gaps=[],status='READY_EMPTY',coverage={}))
    names={'HK.'+f'{i:05d}':{'name':'样本'+f'{i:05d}'} for i in range(1,7)}
    def leaf_discovery(materials,context,*a,**kw):
        rejected=[]
        cards=discovery.project_material_discovery(materials,names,dict(status='OWNER_VERIFIED',
            source_date=context['market_session'],artifact_sha256='a'*64),context,rejection_audit=rejected)
        return dict(cards=cards,gaps=[],status='READY',coverage={},rejected_relations=rejected)
    monkeypatch.setattr(ws,'read_material_discovery',leaf_discovery)
    monkeypatch.setattr(ws,'read_plan_quotes',lambda *a,**kw:dict(quotes={},verified=False,gaps=[]))
    monkeypatch.setattr(ws,'read_rebound_screen',lambda *a:dict(status='READY',strict=[],near=[],cards=[],gaps=[],coverage={}))
    monkeypatch.setattr(ws,'_previous_observation',lambda *a:(None,None))
    monkeypatch.setattr(ws,'_stage_attempt',lambda *a:(None,['STAGE_TARGET_EXECUTION_RECEIPT_NOT_FOUND']))
    monkeypatch.setattr(us_market_bridge,'project_us_market',lambda *a:dict(status='NOT_RUN',mapping_eligible=False,
        raw_industry_up=[],raw_individual_up=[],gaps=[],**FLAGS))
    monkeypatch.setattr(ws,'_now',lambda:clock[0].isoformat())
    root=tmp_path/'test-authority';root.mkdir();monkeypatch.setenv('V4_MANAGER_UNIVERSE_ROOT',str(root))
    monkeypatch.setattr(authority,'read_universe_evidence',lambda *a,**k:SimpleNamespace(codes=tuple(names),source=dict(
        source_date='20260930',market='HK_CONNECT',role='HK_CONNECT_FULL_MARKET_AUTHORITY',sha256='f'*64,
        observed_at='2026-09-30T07:30:00+08:00',available_at='2026-09-30T07:30:01+08:00')))
    state=dict(issuer='HK.00001',delay=0,fail=False,collect=True,events=[],calls=0)
    def collect(day,**kw):
        state['events'].append('collect');state['calls']+=1
        clock[0]+=timedelta(seconds=state['delay'])
        if state['fail']:raise ValueError('SYNTHETIC_COLLECTION_FAILED')
        if state['collect']:capture(wired,state['issuer'])
        return dict(status='PARTIAL',attempt={'run_id':'a'*32})
    def refresh(day,**kw):
        state['events'].append('plan')
        return ws.refresh_workspace_plan(svc,day,**kw)
    svc.refresh_announcements=collect;svc.refresh_workspace_plan=refresh;svc.close=lambda:None
    value=dict(enabled=True,policy='BALANCED_V1',manager_state_root=str(svc.store.root),security_master_root=str(tmp_path),
        priority_codes=[],files={},python_sha256='a'*64,announcement_collection_enabled=True,
        preopen_plan=dict(enabled=True,lead_seconds=180,status='PROPOSAL_ONLY'))
    from infrastructure.scheduling import manager_announcement_supervisor as supervisor
    monkeypatch.setattr(supervisor,'load_binding',lambda *a:value)
    import v4.manager_research.hkex_provider as hp, v4.manager_research.service as service
    monkeypatch.setattr(hp,'HkexOfficialProvider',lambda **kw:p)
    monkeypatch.setattr(service,'ManagerResearchJobService',lambda *a,**kw:svc)
    import resource
    monkeypatch.setattr(resource,'setrlimit',lambda *a:None)
    monkeypatch.setattr(worker.os,'nice',lambda *a:0)
    monkeypatch.setattr(worker.signal,'signal',lambda *a:None)
    monkeypatch.setattr(worker.signal,'setitimer',lambda *a:None)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return clock[0].astimezone(tz) if tz else clock[0]
    monkeypatch.setattr(worker,'datetime',Clock)
    monkeypatch.setattr(worker,'APP_ROOT',Path.cwd())
    return SimpleNamespace(svc=svc,clock=clock,state=state,value=value,monkeypatch=monkeypatch,p=p,wired=wired)


def run(cycle,capsys):
    # Runtime version check belongs to the main process; tests do not alter it
    # in delivered code. Resource/signal boundaries are test-only no-ops.
    with cycle.monkeypatch.context() as m:
        m.setattr(worker.sys,'version_info',(3,14,0))
        code=worker.main(['--binding','/synthetic/not-read.json'])
    lines=capsys.readouterr().out.strip().splitlines()
    return code,json.loads(lines[-1])


def test_last_preopen_tick_consumes_new_body_in_original_saved_plan(cycle,capsys):
    code,result=run(cycle,capsys)
    assert cycle.state['events']==['collect','plan']
    product=ws._read_plan(cycle.svc.store,'20260930')
    assert product['execution_kind']=='SCHEDULED_PREOPEN'
    assert len(product['workspace']['announcement_review']['eastmoney_hk_documents'])==1
    assert {x['symbol'] for x in product['workspace']['stocks']}=={'HK.00001'}
    assert all(product[k] is v for k,v in FLAGS.items())
    assert product['workspace']['summary']['formal_recommendation_count']==0
    assert result['preopen_plan']['status']=='MATERIALIZED' and code==0


def test_after_collection_clock_is_used_and_crossing_open_never_backfills(cycle,capsys):
    cycle.clock[0]=datetime.fromisoformat('2026-09-30T09:29:50+08:00');cycle.state['delay']=15
    _,result=run(cycle,capsys)
    assert result['preopen_plan']['status']=='EXPIRED_NO_BACKFILL'
    assert ws._read_plan(cycle.svc.store,'20260930') is None
    assert cycle.state['events']==['collect']


def test_second_tick_new_input_updates_once_same_input_keeps_run(cycle,capsys):
    run(cycle,capsys);first=ws._read_plan(cycle.svc.store,'20260930')
    cycle.clock[0]+=timedelta(seconds=10);cycle.state['issuer']='HK.00002'
    run(cycle,capsys);second=ws._read_plan(cycle.svc.store,'20260930')
    assert first['run_id']!=second['run_id']
    assert {x['symbol'] for x in second['workspace']['stocks']}=={'HK.00001','HK.00002'}
    before=snapshot(cycle.svc.store.root);cycle.state['collect']=False
    cycle.clock[0]+=timedelta(seconds=10);_,result=run(cycle,capsys)
    assert result['preopen_plan']['status']=='ALREADY_MATERIALIZED'
    assert ws._read_plan(cycle.svc.store,'20260930')['run_id']==second['run_id']
    assert snapshot(cycle.svc.store.root)==before


def test_collection_failure_still_allows_in_window_plan_from_committed_inputs(cycle,capsys):
    capture(cycle.wired,'HK.00001');cycle.state['fail']=True
    code,result=run(cycle,capsys)
    assert result['status']=='FAILED' and code==2
    assert result['preopen_plan']['status']=='MATERIALIZED'
    assert ws._read_plan(cycle.svc.store,'20260930') is not None


@pytest.mark.parametrize('clock,expected',[('09:26:59','NOT_DUE'),('09:30:00','EXPIRED_NO_BACKFILL'),('18:00:00','EXPIRED_NO_BACKFILL')])
def test_preopen_window_not_expanded(cycle,capsys,clock,expected):
    cycle.clock[0]=datetime.fromisoformat('2026-09-30T'+clock+'+08:00')
    cycle.state['collect']=False
    _,result=run(cycle,capsys)
    assert result['preopen_plan']['status']==expected
    assert ws._read_plan(cycle.svc.store,'20260930') is None


def test_disabled_collection_does_not_fetch_and_plan_still_uses_original_owner(cycle,capsys):
    cycle.value['announcement_collection_enabled']=False
    _,result=run(cycle,capsys)
    assert cycle.state['calls']==0 and len(cycle.p.calls)==0
    assert result['preopen_plan']['status']=='MATERIALIZED'
