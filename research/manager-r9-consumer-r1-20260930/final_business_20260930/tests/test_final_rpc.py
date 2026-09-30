"""New RPC path; upstream fixture only, original stores/plan/router/RPC execute."""
from copy import deepcopy
from datetime import datetime,timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_b1_history import wired,capture,snapshot
from test_b2_cycle import cycle
from v4.manager_research import plan_owner_dispatch as rpc,workspace as ws
from v4.manager_research.workspace_projection import FLAGS
from v4.manager_research.workspace_read_control import ReadCoordinator
from apps.api.v35_api.manager_research_router import create_manager_research_router
from ops import run_manager_announcement_cycle as worker

@pytest.fixture
def rpc_cycle(cycle,monkeypatch,tmp_path):
    c=cycle
    c.svc._existing_research_source=object();c.svc._workspace_us_market_reader=object()
    c.svc._workspace_security_master_root=tmp_path
    c.svc._workspace_reads=ReadCoordinator()
    c.value.update(plan_material_refresh_only=False,morning_plan={'enabled':False},plan_material_refresh={'enabled':False})
    path=tmp_path/'binding.json';path.write_text(json.dumps(c.value));c.binding=path
    monkeypatch.setenv('V4_MANAGER_PLAN_OWNER_BINDING_PATH',str(path))
    monkeypatch.setattr(rpc,'clock_now',lambda:c.clock[0])
    from infrastructure.scheduling import manager_announcement_supervisor as sup
    # Binding file and SHA checks remain real. This fixture substitutes only
    # installed machine inventory validation, not RPC/plan/Store code.
    monkeypatch.setattr(sup,'validate_binding',lambda value,**kw:value)
    app=FastAPI();app.include_router(create_manager_research_router(c.svc))
    client=TestClient(app);c.client=client;c.rpc_calls=[]
    class Connection:
        def __init__(self,host,port,timeout):
            assert (host,port,timeout)==('127.0.0.1',8873,35.0)
        def request(self,method,path,body,headers):
            c.rpc_calls.append((method,path));self.response=client.request(method,path,content=body,headers=headers)
        def getresponse(self):
            response=self.response
            class Response:
                status=response.status_code
                def getheader(self,key,default=''):return response.headers.get(key,default)
                def read(self,n):return response.content[:n]
            return Response()
        def close(self):pass
    monkeypatch.setattr(rpc.http.client,'HTTPConnection',Connection)
    return c

def run(c,capsys):
    with c.monkeypatch.context() as m:
        m.setattr(worker,'sys',SimpleNamespace(version_info=(3,14,0)))
        rc=worker.main(['--binding',str(c.binding)])
    lines=capsys.readouterr().out.strip().splitlines()
    return rc,json.loads(lines[-1])

def request(c):
    return c.client.post('/api/v4/manager/research/workspace/scheduled-cycle',params={
        'date':'20260930','binding_sha256':sha256(c.binding.read_bytes()).hexdigest()})

def test_new_registered_rpc_path_calls_original_plan_owner(rpc_cycle):
    c=rpc_cycle;r=request(c)
    assert r.status_code==200,r.text
    assert r.json()['owner']==rpc.OWNER
    assert ws._read_plan(c.svc.store,'20260930') is not None


def test_worker_same_tick_collects_then_rpc_saves_new_body(rpc_cycle,capsys):
    c=rpc_cycle;rc,res=run(c,capsys)
    assert c.state['events']==['collect','plan']
    saved=ws._read_plan(c.svc.store,'20260930')
    assert {s['symbol'] for s in saved['workspace']['stocks']}=={'HK.00001'}
    assert saved['execution_kind']=='SCHEDULED_PREOPEN'
    assert len(c.rpc_calls)==1 and rc==0
    assert all(saved[k] is v for k,v in FLAGS.items())


def test_new_rpc_two_batches_and_retry_original_transaction(rpc_cycle,capsys):
    c=rpc_cycle;run(c,capsys);first=ws._read_plan(c.svc.store,'20260930')
    assert first and first['workspace']['stocks']
    c.state['issuer']='HK.00002';c.clock[0]+=timedelta(seconds=5)
    run(c,capsys);second=ws._read_plan(c.svc.store,'20260930')
    assert {s['symbol'] for s in second['workspace']['stocks']}=={'HK.00001','HK.00002'}
    assert second['run_id']!=first['run_id']
    c.state['collect']=False;c.clock[0]+=timedelta(seconds=5)
    before=snapshot(c.svc.store.root);run(c,capsys)
    assert snapshot(c.svc.store.root)==before
    assert ws._read_plan(c.svc.store,'20260930')['run_id']==second['run_id']


def test_crossing_cutoff_after_collection_no_plan_write(rpc_cycle,capsys):
    c=rpc_cycle;c.clock[0]=datetime.fromisoformat('2026-09-30T09:29:50+08:00');c.state['delay']=15
    _,res=run(c,capsys)
    assert c.state['events']==['collect']
    assert res['plan_refresh']['outcome']=='EXPIRED_NO_BACKFILL'
    assert ws._read_plan(c.svc.store,'20260930') is None
    assert not (c.svc.store.root/'workspace_plan_runs/20260930').exists()


def test_callback_rechecks_clock_after_coordinator_entry(rpc_cycle,monkeypatch):
    c=rpc_cycle;before=snapshot(c.svc.store.root)
    original=c.svc._workspace_reads.run
    def delayed(key,fn,**kw):
        c.clock[0]=datetime.fromisoformat('2026-09-30T09:30:01+08:00')
        return original(key,fn,**kw)
    monkeypatch.setattr(c.svc._workspace_reads,'run',delayed)
    r=request(c)
    assert r.status_code==200,r.text
    assert r.json()['outcome']=='EXPIRED_NO_BACKFILL'
    assert snapshot(c.svc.store.root)==before


def test_failed_collection_keeps_old_committed_inputs_and_reports_failure(rpc_cycle,capsys):
    c=rpc_cycle;capture(c.wired,'HK.00001');c.state['fail']=True
    rc,res=run(c,capsys)
    assert rc==2 and res['status']=='FAILED'
    saved=ws._read_plan(c.svc.store,'20260930')
    assert {s['symbol'] for s in saved['workspace']['stocks']}=={'HK.00001'}


def test_disabled_collection_uses_rpc_without_fetching(rpc_cycle,capsys):
    c=rpc_cycle;c.value['announcement_collection_enabled']=False
    rc,res=run(c,capsys)
    assert rc==0 and c.state['calls']==0 and not c.p.calls
    assert ws._read_plan(c.svc.store,'20260930') is not None


@pytest.mark.parametrize('case',['wrong_sha','body','origin','unbound_readers'])
def test_rpc_rejections_do_not_write(rpc_cycle,case):
    c=rpc_cycle;params={'date':'20260930','binding_sha256':sha256(c.binding.read_bytes()).hexdigest()}
    kwargs={}
    if case=='wrong_sha':params['binding_sha256']='0'*64
    if case=='body':kwargs['json']={'symbols':['HK.99999']}
    if case=='origin':kwargs['headers']={'origin':'https://not-local.invalid'}
    if case=='unbound_readers':c.svc._existing_research_source=None
    before=snapshot(c.svc.store.root)
    r=c.client.post('/api/v4/manager/research/workspace/scheduled-cycle',params=params,**kwargs)
    assert r.status_code in {403,409,422},r.text
    assert snapshot(c.svc.store.root)==before


def test_post_cutoff_rpc_is_expired_not_new_plan(rpc_cycle):
    c=rpc_cycle;c.clock[0]=datetime.fromisoformat('2026-09-30T09:30:00+08:00')
    before=snapshot(c.svc.store.root);r=request(c)
    assert r.status_code==200,r.text
    assert r.json()['outcome']=='EXPIRED_NO_BACKFILL'
    assert snapshot(c.svc.store.root)==before


def test_manual_original_announcement_route_refreshes_bound_plan_after_commit(rpc_cycle):
    c=rpc_cycle
    r=c.client.post('/api/v4/manager/research/announcements/refresh',params={'date':'20260930','source_scope':'EASTMONEY_HK'})
    assert r.status_code==200,r.text
    assert c.state['events']==['collect','plan']
    saved=ws._read_plan(c.svc.store,'20260930')
    assert {s['symbol'] for s in saved['workspace']['stocks']}=={'HK.00001'}
    assert r.json()['plan_refresh']['owner']==rpc.OWNER


def test_manual_announcement_without_binding_does_not_enable_plan(rpc_cycle,monkeypatch):
    c=rpc_cycle;monkeypatch.delenv('V4_MANAGER_PLAN_OWNER_BINDING_PATH')
    r=c.client.post('/api/v4/manager/research/announcements/refresh',params={'date':'20260930','source_scope':'EASTMONEY_HK'})
    assert r.status_code==200,r.text
    assert r.json()['plan_refresh']['status']=='NOT_BOUND'
    assert ws._read_plan(c.svc.store,'20260930') is None


def test_rpc_completion_deadline_preserves_real_saved_plan(rpc_cycle,capsys,monkeypatch):
    c=rpc_cycle;run(c,capsys)
    old=ws._read_plan(c.svc.store,'20260930')
    plans_before=snapshot(c.svc.store.root/'workspace_plans')
    original=ws.get_workspace
    def slow_projection(*args,**kwargs):
        value=original(*args,**kwargs)
        c.clock[0]=datetime.fromisoformat('2026-09-30T09:30:01+08:00')
        return value
    monkeypatch.setattr(ws,'get_workspace',slow_projection)
    c.state['issuer']='HK.00002';c.clock[0]=datetime.fromisoformat('2026-09-30T09:29:55+08:00')
    rc,result=run(c,capsys)
    assert rc==2 and result['plan_refresh']['status']=='FAILED'
    assert snapshot(c.svc.store.root/'workspace_plans')==plans_before
    assert ws._read_plan(c.svc.store,'20260930')==old
    attempt=c.svc.store._read(c.svc.store.root/'workspace_plan_runs/20260930/latest.json')
    assert attempt['state']=='FAILED'
