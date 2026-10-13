"""Actual R10 factory + real HTTP with synthetic 251-row native inputs only."""
from pathlib import Path
import json
import subprocess
import importlib.util
import sys
REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
HANDOFF=Path(__file__).resolve().parent
CANDIDATE=HANDOFF/'deployment-deltas/isolated-api-candidate-v6/app'
import tempfile
root=Path(tempfile.mkdtemp(prefix='active-api-http-',dir=REPO/'tests/manager_workbench/runtime/.tmp'))
script='''import json,sys,time
from pathlib import Path
from fastapi.testclient import TestClient
from apps.api.v35_api.app import create_app
import importlib.util
args=json.loads(sys.stdin.read());fixture_path=Path(args['fixture_path']);root=Path(args['state_directory'])
spec=importlib.util.spec_from_file_location('actual_native_fixture',fixture_path)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
config=mod.fixture(root,count=251);cfg=config.model_dump(mode='json')
(root/'config.json').write_text(config.model_dump_json(indent=2))
app=create_app(data_root=root/'data',manager_workbench_config=cfg)
with TestClient(app) as client:
 before=client.get('/api/v4/manager-workbench/days/20261013')
 submitted=client.post('/api/v4/manager-workbench/runs',json={'target_date':'20261013','phase':'MANUAL','lanes':['OVERSOLD']})
 job_id=submitted.json()['data']['job_id']
 for i in range(100):
  job=client.get('/api/v4/manager-workbench/runs/'+job_id).json()['data']
  if job['state'] not in ('RUNNING','QUEUED'):break
  time.sleep(.01)
 full=client.get('/api/v4/manager-workbench/days/20261013',params={'run_id':job['run_id'],'offset':200,'limit':51})
 data=full.json()['data'];html=client.get('/manager-selection/')
 proof={'initial_status':before.status_code,'post_status':submitted.status_code,'job_state':job['state'],
 'read_status':full.status_code,'counts':data['counts'],'last_page_rows':len(data['stocks']),
 'run_id':job['run_id'],'product_sha256':data['snapshot']['product_sha256'],'schema':full.json()['schema_version'],
 'manager_page_status':html.status_code,'compiled_page_has_vue_bundle':'.js' in html.text and '/src/manager-selection/main.ts' not in html.text,
 'old_modules_loaded':[k for k in sys.modules if k.startswith('v4.manager_research') or k in {'apps.api.v35_api.manager_research_router','apps.api.v35_api.manager_workbench_router'}],
 'old_owner_excluded':app.state.manager_workbench_old_owner_excluded}
 print(json.dumps(proof))
 assert proof['job_state']=='SUCCEEDED' and proof['counts']['selected']==251 and proof['last_page_rows']==51 and proof['old_modules_loaded']==[]
 assert proof['manager_page_status']==200 and proof['compiled_page_has_vue_bundle']
''' 
result=subprocess.run([sys.executable,'-c',script],input=json.dumps({'fixture_path':str(REPO/'tests/manager_workbench/runtime/test_native_pipeline.py'),'state_directory':str(root)}),cwd=CANDIDATE,text=True,capture_output=True)
(HANDOFF/'integration-active-api-v6-http.log').write_text(result.stdout+result.stderr)
if result.returncode:print(result.stdout,result.stderr[-2000:]);raise SystemExit(result.returncode)
proof=json.loads(result.stdout);proof.update(state_directory=str(root),candidate_app=str(CANDIDATE),config_path=str(root/'config.json'),
    environment='actual R10 active-base factory/closure; synthetic inputs; TestClient only; no port or service started')
(HANDOFF/'integration-active-api-v6-http-receipt.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
