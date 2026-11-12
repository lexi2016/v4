"""SIMULATED child/ledger fixtures; real split owner and subprocess contract."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from contracts.runtime_tasks import DispatchMode,DispatchRequest
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry,WorkloadExecutionError
from infrastructure.scheduling.catalog import load_workload_catalog

ROOT=Path(__file__).resolve().parents[1]
DATE='20260918'

def request(slot='1530',date=DATE):
    return DispatchRequest(scheduled_date=date,business_date=date,target_date=date,slot=slot,mode=DispatchMode.LIVE)

def setup(tmp_path,monkeypatch,change=None):
    app=tmp_path/'SIMULATED_V4_APP';state=tmp_path/'V4_MANAGER_STATE';data=tmp_path/'EXISTING_V4_DATA';universe=tmp_path/'EXISTING_V4_UNIVERSE'
    for path in ['ops/materialize_manager_close_discovery.py','apps/api/v4_api/app.py','apps/api/v4_api/manager_workbench_router.py','v4/manager_research/__init__.py']:
        p=app/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# SIMULATED source identity fixture\n')
    monkeypatch.setenv('V4_MANAGER_MATERIALIZER_APP_ROOT',str(app))
    monkeypatch.setenv('V4_MANAGER_RESEARCH_STATE_ROOT',str(state))
    out=state/f'workbench_research/{DATE}/1530.json';out.parent.mkdir(parents=True)
    raw=(ROOT/'tests/fixtures/manager_r2_SIMULATED.json').read_bytes();out.write_bytes(raw);artifact=json.loads(raw)
    result={'schema_version':'v4.manager_close_materialization_result.v1','status':'MATERIALIZED','trade_date':DATE,'slot':'1530','module_origin':str(app/'ops/materialize_manager_close_discovery.py'),'module_sha256':hashlib.sha256((app/'ops/materialize_manager_close_discovery.py').read_bytes()).hexdigest(),
            'state_root':str(state),'artifact_ref':f'workbench_research/{DATE}/1530.json','artifact_sha256':hashlib.sha256(raw).hexdigest(),'artifact_status':artifact['status'],'run_id':artifact['run_id'],'candidate_count':1,'observation_count':1,'qualified_count':0,'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    if change: result.update(change)
    calls=[]
    def runner(command,**kwargs):
        calls.append((command,kwargs));return subprocess.CompletedProcess(command,0,json.dumps(result),"")
    registry=FixedExecutorRegistry(data_root=data,hk_universe_root=universe,repo_root=ROOT,runner=runner,shared_futu_python_executable=sys.executable)
    return registry,calls,result,app,state,data,universe


def test_only_1530_invokes_single_v4_materializer_with_explicit_roots(tmp_path,monkeypatch):
    registry,calls,_,app,state,data,universe=setup(tmp_path,monkeypatch)
    result=registry._hourly_research(request())
    assert result['status']=='SUCCEEDED'
    assert len(calls)==1
    command,kwargs=calls[0]
    assert command[2]=='ops.materialize_manager_close_discovery'
    for key,value in {'--state-root':state,'--app-root':app,'--data-root':data,'--universe-root':universe,'--news-owner-root':ROOT}.items():
        assert command[command.index(key)+1]==str(value)
    assert kwargs['cwd']==app
    assert kwargs['env']['PYTHONPATH'].split(os.pathsep)[0]==str(app)
    assert not any('collect_hourly_research_input' in x for x in command)


@pytest.mark.parametrize('change',[
    {'production_allowed':True},{'orders_sent':'false'},{'trade_date':'20260917'},
    {'state_root':'/tmp/SIMULATED_WRONG_ROOT'},{'status':'READY'},
    {'artifact_sha256':'0'*64},{'module_origin':'/tmp/not-the-app.py'},
    {'candidate_count':999},{'artifact_status':'BOGUS'},{'qualified_count':1},
])
def test_bad_child_contract_is_a_visible_failure(tmp_path,monkeypatch,change):
    registry,*_=setup(tmp_path,monkeypatch,change)
    with pytest.raises(WorkloadExecutionError) as caught:registry._hourly_research(request())
    assert caught.value.result['status']=='FAILED'
    assert caught.value.result['failure_class']=='UPSTREAM_NOT_READY'


def test_missing_explicit_root_does_not_fall_back(tmp_path,monkeypatch):
    registry,calls,*_=setup(tmp_path,monkeypatch)
    monkeypatch.delenv('V4_MANAGER_RESEARCH_STATE_ROOT')
    with pytest.raises(WorkloadExecutionError):registry._hourly_research(request())
    assert calls==[]


def test_1530_registered_in_existing_hourly_workload_only():
    catalog=load_workload_catalog(ROOT/'contracts/runtime_workloads.json')
    hourly=next(w for w in catalog.workloads if w.workload_id=='hourly_research')
    assert '1530' in hourly.slots
    assert hourly.owner_id=='v35_dispatcher.hourly_research'

@pytest.mark.parametrize('case',['start_error','bad_json','nonzero','missing_predicates','numeric_flag','duplicate_id','missing_value'])
def test_child_failure_or_malformed_artifact_is_never_success(tmp_path,monkeypatch,case):
    registry,calls,result,app,state,*_=setup(tmp_path,monkeypatch)
    path=state/result['artifact_ref']
    payload=json.loads(path.read_text())
    if case=='missing_predicates':payload['candidates'][0]['predicates']=[]
    if case=='numeric_flag':payload['RESEARCH_ONLY']=1
    if case=='duplicate_id':payload['candidates'].append(dict(payload['candidates'][0],symbol='HK.00002'));result.update(candidate_count=2,observation_count=2)
    if case=='missing_value':payload['candidates'][0]['turnover_amount'].pop('value')
    raw=json.dumps(payload).encode();path.write_bytes(raw);result['artifact_sha256']=hashlib.sha256(raw).hexdigest()
    def runner(command,**kwargs):
        if case=='start_error':raise OSError('SIMULATED cannot start child')
        return subprocess.CompletedProcess(command,2 if case=='nonzero' else 0,'garbled' if case=='bad_json' else json.dumps(result),'')
    registry.runner=runner
    # Registry stores injected command runner under this real field.
    if hasattr(registry,'_runner'):registry._runner=runner
    with pytest.raises(WorkloadExecutionError):registry._hourly_research(request())
    status=json.loads((state/f'workbench_research/{DATE}/1530.status.json').read_text())
    assert status['status']=='FAILED' and status['candidates']==[]

def test_verified_child_input_missing_remains_input_missing_on_workbench(tmp_path,monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from infrastructure.manager_close_attempt import write_attempt
    registry,_,result,_,state,*_=setup(tmp_path,monkeypatch)
    (state/result['artifact_ref']).unlink()
    result.update(status='INPUT_MISSING',reason='EXACT_1530_SNAPSHOT_WINDOW_MISSED')
    write_attempt(state,DATE,'INPUT_MISSING',result['reason'],datetime.now(ZoneInfo('Asia/Hong_Kong')))
    def run(command,**kwargs):return subprocess.CompletedProcess(command,2,json.dumps(result),'')
    registry.runner=run
    if hasattr(registry,'_runner'):registry._runner=run
    with pytest.raises(WorkloadExecutionError):registry._hourly_research(request())
    assert json.loads((state/f'workbench_research/{DATE}/1530.status.json').read_text())['status']=='INPUT_MISSING'
