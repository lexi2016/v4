from pathlib import Path
import os,json,plistlib,subprocess,sys
P=Path(__file__).parent;packet=json.loads((P/'PACKET.json').read_text());main=packet['services']['main'];mp=plistlib.loads(Path(main['draft_plist']).read_bytes());env=dict(os.environ,**mp['EnvironmentVariables']);runtime=Path(env['V4_RUNTIME_ROOT']);env['PYTHONPATH']=main['app_root']+':'+str(runtime/'venvs/v4-mac/lib/python3.14/site-packages')+':'+env.get('PYTHONPATH','');python=runtime/'venvs/v4-mac/bin/python'
r=subprocess.run([str(python),'-B','-S','-m','ops.complete_workbench_v192_assets','--help'],cwd=main['app_root'],env=env,capture_output=True,text=True,timeout=30);(P/'MAIN_COMPLETION_IMPORT.stderr').write_text(r.stderr);assert r.returncode==0,r.stderr;(P/'MAIN_COMPLETION_IMPORT.json').write_text(json.dumps(dict(status='PASS_REAL_MAIN_PROFILE_IMPORT_AND_CLI_ONLY',python=str(python),producer_executed=False),indent=2)+'\n')
api=packet['services']['api'];ap=plistlib.loads(Path(api['draft_plist']).read_bytes());env=dict(os.environ,**ap['EnvironmentVariables']);env['PYTHONPATH']=api['app_root']+':'+env.get('PYTHONPATH','')
code='''from pathlib import Path
import os,json,hashlib
from fastapi.testclient import TestClient
from apps.api.v4_api.app import create_app
root=Path(os.environ['V4_A_SHARE_DAILY_PRODUCT_ROOT'])/'daily_products/a_share';index=root/'index.json';before=hashlib.sha256(index.read_bytes()).hexdigest()
client=TestClient(create_app(data_root=Path(os.environ['V4_DATA_ROOT']),shared_data_root=Path(os.environ['V4_SHARED_DATA_ROOT']),stage_center_selection_root=Path(os.environ['V4_STAGE_CENTER_SELECTION_ROOT'])))
samples=[]
for path in ['/api/v1/runs/date-list','/api/v4/runtime-graph/frontend-build','/research-panel/workbench-host/bootstrap.mjs','/research-panel/workbench-host/stock/stock-bridge.mjs','/research-panel/workbench-host/dot/shell/workbench.local.mjs']:
 r=client.get(path);assert r.status_code==200,(path,r.status_code,r.text[:200]);item=dict(path=path,http_status=200,sha256=hashlib.sha256(r.content).hexdigest())
 if path.endswith('date-list'):assert r.json()['runtime_identity']['status']=='MANIFEST_EXECUTION_FILES_VERIFIED'
 elif path.endswith('frontend-build'):assert r.json()['status']=='VERIFIED'
 else:assert 'no-store' in r.headers.get('cache-control','')
 samples.append(item)
base='/api/v4/research/workbench/days/2026-11-09';group=client.get(base+'/v192');assert group.status_code==200;value=group.json()
url=base+'/v192-assets/603286.SH?revision='+value['generation']+'&model_sha256='+value['source_artifact_sha256'];response=client.get(url)
assert response.status_code in [404,409],(response.status_code,response.text[:300])
assert hashlib.sha256(index.read_bytes()).hexdigest()==before
print(json.dumps(dict(status='PASS_PACKAGED_READ_CHAIN_ONLY_PENDING_PUBLISH',homepage_and_static=samples,canary_unpublished_http_status=response.status_code,canary_unpublished_response=response.json(),canonical_index_sha256_unchanged=before,canary_materialized_api='NOT_PUBLISHED_NOT_CLAIMED',GET_materialization=False),ensure_ascii=False,indent=2))
'''
r=subprocess.run([sys.executable,'-B','-c',code],cwd=api['app_root'],env=env,capture_output=True,text=True,timeout=90);(P/'PACKAGED_API.stderr').write_text(r.stderr);(P/'PACKAGED_API.json').write_text(r.stdout);print(r.stdout);print(r.stderr);assert r.returncode==0
