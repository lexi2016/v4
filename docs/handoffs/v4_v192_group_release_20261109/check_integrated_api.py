from pathlib import Path
import json,sys,os,plistlib,subprocess
P=Path(__file__).parent;packet=json.loads((P/'PACKET.json').read_text());api=packet['services']['api'];p=plistlib.loads(Path(api['draft_plist']).read_bytes());env=dict(os.environ,**p['EnvironmentVariables']);env['PYTHONPATH']=api['app_root']+':'+env.get('PYTHONPATH','')
code='''from pathlib import Path
import os,json,hashlib
from fastapi.testclient import TestClient
from apps.api.v4_api.app import create_app
client=TestClient(create_app(data_root=Path(os.environ['V4_DATA_ROOT']),shared_data_root=Path(os.environ['V4_SHARED_DATA_ROOT']),stage_center_selection_root=Path(os.environ['V4_STAGE_CENTER_SELECTION_ROOT'])))
samples=[]
for path in ['/api/v1/runs/date-list','/api/v4/runtime-graph/frontend-build','/api/v4/research/workbench/days/2026-11-09/v192','/api/v4/research/workbench/days/2026-11-09','/research-panel/workbench-host/bootstrap.mjs','/research-panel/workbench-host/dot/shell/workbench.local.mjs','/research-panel/workbench-host/dot/src/workbench-model.mjs']:
 response=client.get(path);assert response.status_code==200,(path,response.status_code,response.text[:500]);item=dict(path=path,http_status=200,bytes=len(response.content),sha256=hashlib.sha256(response.content).hexdigest())
 if 'application/json' in response.headers.get('content-type',''):
  value=response.json();item['status']=value.get('status')
  if path.endswith('date-list'):
   assert value['dates'] and value['default_date'] in value['dates'];assert value['runtime_identity']['status']=='MANIFEST_EXECUTION_FILES_VERIFIED';item.update(default_date=value['default_date'],runtime_identity=value['runtime_identity'])
  elif path.endswith('frontend-build'):assert value['status']=='VERIFIED';item['identity']=value
  elif path.endswith('/v192'):
   assert value['status']=='READY' and value['count']==19;assert value['source_artifact_sha256']=='6d2ce1d7b36b97b024cc2b39fadbb6443f10e5b471a8a0d65dffc4030216edd1';assert value['selector_sha256']=='2b2411fd6c0a4506fca1703277ec9723a5cdba22b1e2abdfa5559b4700c09699';item.update(count=value['count'],source_artifact_sha256=value['source_artifact_sha256'],selector_sha256=value['selector_sha256'],reader_source=value['reader_source'])
  else:
   assert len(value['rows'])==371 and sum(row['group_states']['original']=='TRUE' for row in value['rows'])==31;item.update(four_group_count=len(value['rows']),original_count=31)
 else:assert 'no-store' in response.headers.get('cache-control','')
 samples.append(item)
print(json.dumps(dict(status='PASS_PACKAGED_ASGI_NO_SOCKET',samples=samples,new_data_or_scores_computed=False,original371_recomputed=False),ensure_ascii=False,indent=2))
'''
r=subprocess.run([sys.executable,'-B','-c',code],env=env,cwd=api['app_root'],capture_output=True,text=True,timeout=90);(P/'INTEGRATED_API.stderr').write_text(r.stderr);(P/'INTEGRATED_API.json').write_text(r.stdout);print(r.stdout);print(r.stderr);assert r.returncode==0
