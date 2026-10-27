"""R4 compact budget: exact deployed dependency namespace, no listener/actions."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

W=Path(__file__).parents[1]
API=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/business-gaps-20261027-r1-api/app')
CASE=Path('/Users/lexi/Desktop/学习/agents调试/V4_BUSINESS_GAPS_20261027')
sys.path.insert(0,str(API))
import domains.runtime_graph_evidence
spec=importlib.util.spec_from_file_location('domains.runtime_graph_evidence',W/'domains/runtime_graph_evidence.py')
owner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=owner;spec.loader.exec_module(owner)


def fake_reader(monkeypatch):
    catalog=SimpleNamespace(workloads=[SimpleNamespace(workload_id='x',enabled=False)])
    monkeypatch.setattr(owner,'ExecutionLedger',lambda *a:SimpleNamespace(list_receipts=lambda *a,**k:[],verify_receipt_chain=lambda *a,**k:(True,'')))
    monkeypatch.setattr(owner,'build_task_status',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('full TaskStatus called')))
    reader=owner.CurrentEvidenceReader(dict(ledger_root='/unused',task_evidence_root='/unused',stage_selection_root='/unused',
        graph_root='/unused',opening_root='/unused',stage_receipt_root='/unused',daily_receipt_root='/unused',main={}))
    reader._catalog=lambda:catalog
    reader.descriptors=lambda:[dict(node_id='x',kind='MAIN',owner='fixture',executor_status='REGISTERED')]
    reader._runtime_binding=lambda:{'current_runtime_verified':False}
    return reader


def test_noncompact_full_contract_keeps_original_taskstatus_branch(monkeypatch):
    reader=fake_reader(monkeypatch)
    with pytest.raises(RuntimeError,match='full TaskStatus called'):
        reader.collect('20261027')


def test_compact_reuses_original_rows_and_keeps_current_slot_observation(monkeypatch):
    import domains.task_status as tasks
    reader=fake_reader(monkeypatch)
    monkeypatch.setattr(tasks,'_logical_row',lambda w,*a:dict(workload_id=w.workload_id,status='FAILED',result_code='last_completed_failure'))
    monkeypatch.setattr(tasks,'_load_scheduler_slot_observations',lambda *a:'same-original-observations')
    def apply(row,workload,observations,*a,**k):
        assert observations=='same-original-observations'
        return {**row,'scheduler_state':'RUNNING_VERIFIED_OBSERVATION','last_completed_status':'FAILED'}
    monkeypatch.setattr(tasks,'_apply_scheduler_slot_observation',apply)
    result=reader.collect('20261027',compact=True)
    node=result['nodes'][0]
    assert node['execution_phase']=='RUNNING_VERIFIED_OBSERVATION'
    assert node['task_status']['last_completed_status']=='FAILED'


def test_complete_actual_dependency_namespace_cold_http_handler_budget(tmp_path):
    # Fresh process: only five explicitly overlaid owner modules may come from
    # the worktree. All task/ledger/Stage dependencies come from actual R3.
    script=r'''
from pathlib import Path
import sys,os,importlib,importlib.util,json,time,hashlib
api=Path(sys.argv[1]);w=Path(sys.argv[2]);case=Path(sys.argv[3]);scratch=Path(sys.argv[4]);sys.path.insert(0,str(api))
os.environ['V4_RUNTIME_GRAPH_CONFIG']='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/business-gaps-20261027-r1-collector/runtime-graph-config.json'
os.environ['V35_RUNTIME_GRAPH_DATA_ROOT']='/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data'
os.environ['V4_MANAGER_SECURITY_MASTER_ROOT']='/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data'
overlays=[('infrastructure.runtime_graph.current','infrastructure/runtime_graph/current.py'),('stage_center.consumer','stage_center/consumer.py'),('domains._preselection_parts.source_validation','domains/_preselection_parts/source_validation.py'),('domains.runtime_graph_evidence','domains/runtime_graph_evidence.py'),('apps.api.v35_api.app','apps/api/v35_api/app.py')]
for name,rel in overlays:
 importlib.import_module(name.rpartition('.')[0]);spec=importlib.util.spec_from_file_location(name,w/rel);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
import domains.task_status as tasks
assert Path(tasks.__file__)==api/'domains/task_status.py'
assert hashlib.sha256(Path(tasks.__file__).read_bytes()).hexdigest()=='24d52d7258bb4421810c6116dc54366df9f1363f3fa62850f1a828bd67011ae6'
from apps.api.v35_api.app import create_app
from fastapi.testclient import TestClient
shared=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data')
app=create_app(data_root=scratch,stage_center_selection_root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection'),preselection_source_root=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data'),morning_news_data_root=shared)
client=TestClient(app);start=time.perf_counter();response=client.get('/api/v3/runtime-graph/authorities?date=20261027&projection=compact');elapsed=time.perf_counter()-start
assert response.status_code==200,response.text[:1000]
body=response.json();assert len(body['nodes'])==46
assert elapsed<3,(elapsed,len(response.content));assert len(response.content)<4*1024*1024
checks=[]
for sid,code,name in [('STAGE_0930_0935','300860','锋尚文化'),('STAGE_0940_0945','300473','德尔股份'),('STAGE_1445_1500','600865','百大集团')]:
 r=client.get('/api/v3/workbench/stage',params=dict(date='20261027',stage=sid,limit=10));assert r.status_code==200,r.text[:1000]
 actual=r.json();old=json.loads((case/'controller/actual_ui'/f'{sid}_ACTUAL.json').read_text())
 row=next(x for x in actual['markets']['A']['rows'] if code in x['code']);original=next(x for x in old['markets']['A']['rows'] if code in x['code'])
 assert row['name']==row['stock_name']==row['display_name']==name
 assert {k:v for k,v in row.items() if k not in {'name','stock_name','display_name','display_identity'}}=={k:v for k,v in original.items() if k not in {'name','stock_name','display_name','display_identity'}},{k:(original.get(k),row.get(k)) for k in set(original)|set(row) if original.get(k)!=row.get(k) and k not in {'name','stock_name','display_name','display_identity'}}
 checks.append(dict(stage=sid,code=code,name=name,non_display_fields_unchanged=True))
start=time.perf_counter();auction=client.get('/api/v3/workbench/stage?date=20261027&stage=STAGE_0925&limit=10');auction_elapsed=time.perf_counter()-start
assert auction.status_code==200,auction.text[:1000]
a=auction.json();assert a['markets']['A']['source_rows']==0 and a['markets']['A']['requested_rows']==482
assert a['markets']['A']['source_status']=='CANNOT_CONFIRM' and a['selection_markets']['A_SHARE']['requested_rows'] is None
assert a['execution_evidence']['natural_verified'] is False and a['execution_evidence']['execution_verified'] is False
assert auction_elapsed<3,auction_elapsed
result=dict(status='PASS_LOCAL_COLD_HTTP_HANDLER_NOT_DEPLOYED_ACCEPTANCE',graph_http_status=response.status_code,graph_seconds=elapsed,graph_bytes=len(response.content),nodes=len(body['nodes']),auction_seconds=auction_elapsed,auction_request_rows=482,auction_accepted_source_rows=0,checks=checks,task_status_path=tasks.__file__,task_status_sha256=hashlib.sha256(Path(tasks.__file__).read_bytes()).hexdigest(),source_modules={name:dict(path=sys.modules[name].__file__,sha256=hashlib.sha256(Path(sys.modules[name].__file__).read_bytes()).hexdigest()) for name,rel in overlays},service_actions=0,provider_requests=0)
(case/'R4_COLD_HANDLER_AND_STAGE_READBACK_CORRECTED_ROOTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
'''
    result=subprocess.run([sys.executable,'-B','-c',script,str(API),str(W),str(CASE),str(tmp_path/'data')],
        cwd=API,text=True,capture_output=True,timeout=60)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
