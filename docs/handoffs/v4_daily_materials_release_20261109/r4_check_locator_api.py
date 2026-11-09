from pathlib import Path
import json,sys,os,plistlib,subprocess
P=Path(__file__).parent;packet=json.loads((P/'PACKET.json').read_text());api=packet['services']['api'];p=plistlib.loads(Path(api['draft_plist']).read_bytes());env=dict(os.environ,**p['EnvironmentVariables']);env['PYTHONPATH']=api['app_root']+':'+env.get('PYTHONPATH','')
code='''from pathlib import Path
import os,json,hashlib
from fastapi.testclient import TestClient
from apps.api.v4_api.app import create_app
app=create_app(data_root=Path(os.environ['V4_DATA_ROOT']),shared_data_root=Path(os.environ['V4_SHARED_DATA_ROOT']),stage_center_selection_root=Path(os.environ['V4_STAGE_CENTER_SELECTION_ROOT']))
client=TestClient(app)
results=[]
paths=['/api/v1/runs/date-list','/api/v4/runtime-graph/frontend-build','/research-panel/workbench-host/kb-single-stock.mjs']
for path in paths:
 r=client.get(path);assert r.status_code==200,(path,r.status_code,r.text[:500]);raw=r.content
 item=dict(path=path,http_status=r.status_code,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
 if 'application/json' in r.headers.get('content-type',''):
  d=r.json();assert isinstance(d,dict),(path,type(d));item.update(status=d.get('status'),material_lifecycle=d.get('material_lifecycle'),missing_reason=d.get('missing_reason'),source_date=d.get('source_date'))
  if path.endswith('date-list'):
   assert d['dates'] and d['default_date'] in d['dates'];assert d['runtime_identity']['status']=='MANIFEST_EXECUTION_FILES_VERIFIED';item.update(default_date=d['default_date'],runtime_identity=d['runtime_identity'],dates_count=len(d['dates']))
  if path.endswith('frontend-build'):assert d['status']=='VERIFIED';item['identity']=d
 results.append(item)
print(json.dumps(dict(status='PASS_CANDIDATE_ASGI_GET_ONLY_EXISTING_PUBLISHED_DATA',no_listening_socket=True,new_371_material_publication='NOT_RUN',samples=results),ensure_ascii=False,indent=2))
'''
r=subprocess.run([sys.executable,'-B','-c',code],env=env,cwd=api['app_root'],capture_output=True,text=True,timeout=60)
tag='API_CANDIDATE_THIRD_COMPANY_R4' if os.environ.get('V4_CANDIDATE_EXTRA_ONLY') else 'API_CANDIDATE_CHECK_R4'
(P/(tag+'.stderr')).write_text(r.stderr);(P/(tag+'.json')).write_text(r.stdout);print(r.stdout);print(r.stderr);assert r.returncode==0
