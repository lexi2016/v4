"""Root runs after immutable staging, before activation. No overlay/producer/writes."""
from pathlib import Path
from datetime import datetime
import argparse,hashlib,json,os,re,subprocess,sys
HERE=Path(__file__).resolve().parent
P=json.loads((HERE/'PLAN.json').read_bytes());stage=next(r for r in P['releases'] if r['role']=='stage');APP=Path(stage['app_root'])
def probe():
 manifest=APP.parent/'release-manifest.json';raw=manifest.read_bytes()
 assert hashlib.sha256(raw).hexdigest()==stage['manifest_sha256']
 for role in ('stage','precapture'):
  op=next(r for r in P['operations'] if r['role']==role)
  text=subprocess.run(['/bin/launchctl','print','gui/501/'+op['label']],capture_output=True,text=True,timeout=4)
  if text.returncode!=0 or op['old_app_root'] not in text.stdout or str(APP) in text.stdout:raise ValueError('NOT_ACTIVATED_PRECONDITION')
 for k,v in {'V4_APP_ROOT':str(APP),'V4_RELEASE_ID':stage['release_id'],'V4_RELEASE_MANIFEST_PATH':str(manifest),'V4_RELEASE_MANIFEST_SHA256':stage['manifest_sha256'],'STAGE_CENTER_CONFIG':str(APP/'stage_center_tick_config.json'),'PYTHONDONTWRITEBYTECODE':'1'}.items():os.environ[k]=v
 sys.path.insert(0,str(APP));from infrastructure import manager_input_attestation as A
 cfg=json.loads((APP/'stage_center_tick_config.json').read_bytes());data=Path(cfg['v4_research_data_root']);owner,ledger,_=A.trusted_research_owner(APP,data);results={}
 for slot,when in [('1300','13:15:00'),('1400','14:45:00'),('0900','09:35:00')]:
  try:
   record,_=A.read_stage_hourly_attestation(stage_app=APP,data_root=data,date='20261029',slot=slot,mode='LIVE',as_of=datetime.fromisoformat('2026-10-29T'+when+'+08:00'));results[slot]={'status':'VERIFIED','completion_witness':record['completion_witness']}
  except Exception as error:results[slot]={'status':'REJECTED','error':type(error).__name__+':'+str(error)}
 assert results['1300']['status']==results['1400']['status']=='VERIFIED',results
 assert results['0900']['status']=='REJECTED',results
 return {'status':'PASS','mode':'IMMUTABLE_INSTALLED_CANDIDATE_NOT_ACTIVATED','manifest_sha256':stage['manifest_sha256'],'trusted_owner':str(owner),'ledger':str(ledger),'results':results,'writes':0,'service_actions':0}
if __name__=='__main__':print(json.dumps(probe(),ensure_ascii=False))
