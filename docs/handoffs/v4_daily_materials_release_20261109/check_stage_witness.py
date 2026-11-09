from pathlib import Path
import os,json,plistlib,sys,subprocess
P=Path(__file__).parent
pkg=json.loads((P/'STAGE_PACKAGE.json').read_text());p=plistlib.loads(Path(pkg['draft_plist']).read_bytes());env=dict(os.environ,**p['EnvironmentVariables']);env['PYTHONPATH']=pkg['app_root']+':'+env.get('PYTHONPATH','');env['PYTHONDONTWRITEBYTECODE']='1'
code='''import json,os
from datetime import datetime
from pathlib import Path
from infrastructure.manager_input_attestation import read_stage_hourly_attestation
c=json.loads((Path(os.environ['V4_APP_ROOT'])/'stage_center_tick_config.json').read_text())
results=[]
for date,slot,asof in [('20261109','0900','2026-11-09T09:35:00+08:00'),('20261107','0900','2026-11-07T09:35:00+08:00'),('20261106','0900','2026-11-06T09:35:00+08:00')]:
 try:
  r,e=read_stage_hourly_attestation(stage_app=Path(os.environ['V4_APP_ROOT']),data_root=Path(c['v4_research_data_root']),date=date,slot=slot,mode='LIVE',as_of=datetime.fromisoformat(asof))
  results.append(dict(date=date,slot=slot,status='PASS',completion_witness=r['completion_witness'],evidence=e))
 except Exception as ex:results.append(dict(date=date,slot=slot,status='FAIL',error=type(ex).__name__+':'+str(ex)))
print(json.dumps(results,ensure_ascii=False,indent=2))
'''
r=subprocess.run([sys.executable,'-B','-c',code],cwd=pkg['app_root'],env=env,capture_output=True,text=True,timeout=30)
(P/'STAGE_WITNESS.stderr').write_text(r.stderr);(P/'STAGE_WITNESS.json').write_text(r.stdout);print(r.stdout);print(r.stderr);assert r.returncode==0
assert all(x['status']=='PASS' for x in json.loads(r.stdout))
