from pathlib import Path
import json,sys,os,plistlib,subprocess,hashlib
P=Path(__file__).parent;packet=json.loads((P/'PACKET.json').read_text());api=packet['services']['api'];p=plistlib.loads(Path(api['draft_plist']).read_bytes());env=dict(os.environ,**p['EnvironmentVariables']);env['PYTHONPATH']=api['app_root']+':'+env.get('PYTHONPATH','');expected=Path('/Users/lexi/Desktop/学习/agents调试/v4_daily_materials_release_repair_20261109/v192_group/quote_repair/REPRESENTATIVE_QUOTES.json');(P/'EXPECTED_QUOTE_SAMPLES.json').write_bytes(expected.read_bytes());env['V192_EXPECTED_QUOTES']=str(P/'EXPECTED_QUOTE_SAMPLES.json')
code='''from pathlib import Path
import os,json,hashlib,math
from fastapi.testclient import TestClient
from apps.api.v4_api.app import create_app
client=TestClient(create_app(data_root=Path(os.environ['V4_DATA_ROOT']),shared_data_root=Path(os.environ['V4_SHARED_DATA_ROOT']),stage_center_selection_root=Path(os.environ['V4_STAGE_CENTER_SELECTION_ROOT'])))
response=client.get('/api/v4/research/workbench/days/2026-11-09/v192');assert response.status_code==200,response.text[:300];model=response.json();ref=model['source_close_reference'];assert ref['quote_role']=='SOURCE_DATE_CLOSE_REFERENCE' and ref['source_date']=='2026-11-09' and ref['price_basis']=='QFQ_ASOF_20261109' and ref['amount_basis']=='RAW_TURNOVER';assert ref['source_asof'] is None and ref['source_asof_precision']=='DATE_ONLY';quotes=ref['rows']
assert len(quotes)==19 and all(all(isinstance(q[k],(int,float)) and math.isfinite(q[k]) for k in ['price','change_percent_source','amount_source']) for q in quotes.values());representatives={}
for symbol,value in json.loads(Path(os.environ['V192_EXPECTED_QUOTES']).read_text()).items():
 q=quotes[symbol];expected=value['quote'];assert all(math.isclose(q[key],expected[key],rel_tol=1e-12,abs_tol=1e-9) for key in ['price','change_percent_source','amount_source']);representatives[symbol]=q
metadata=[]
for path in ['/api/v1/runs/date-list','/api/v4/runtime-graph/frontend-build']:
 r=client.get(path);assert r.status_code==200;d=r.json()
 if path.endswith('date-list'):assert d['runtime_identity']['status']=='MANIFEST_EXECUTION_FILES_VERIFIED'
 else:assert d['status']=='VERIFIED'
 metadata.append(dict(path=path,http_status=200,sha256=hashlib.sha256(r.content).hexdigest()))
assets=[]
for path in ['/research-panel/workbench-host/dot/shell/workbench.local.mjs','/research-panel/workbench-host/dot/src/workbench-model.mjs']:
 r=client.get(path);assert r.status_code==200 and 'no-store' in r.headers.get('cache-control','');assets.append(dict(path=path,sha256=hashlib.sha256(r.content).hexdigest()))
print(json.dumps(dict(status='PASS_PACKAGED_QUOTE_MAPPING_ASGI_NO_SOCKET',quote_available_count=len(quotes),metadata={k:ref[k] for k in ['quote_role','source_date','price_basis','amount_basis','source_asof','source_asof_precision']},representatives=representatives,homepage_release_identity=metadata,changed_static=assets,prior_membership371_score_rules='REUSED_PRIOR_PASS_NOT_RETESTED',business_data_written=False),ensure_ascii=False,indent=2))
'''
r=subprocess.run([sys.executable,'-B','-c',code],env=env,cwd=api['app_root'],capture_output=True,text=True,timeout=90);(P/'QUOTE_MAPPING.stderr').write_text(r.stderr);(P/'QUOTE_MAPPING.json').write_text(r.stdout);print(r.stdout);print(r.stderr);assert r.returncode==0
