"""Original trusted reader; optional candidate manifest overlay is test-only."""
from pathlib import Path
from datetime import datetime
import argparse,hashlib,json,os,sys
HERE=Path(__file__).resolve().parent
P=json.loads((HERE/'PLAN.json').read_bytes());APP=Path(P['app_root']);sys.path.insert(0,str(APP))
from infrastructure import manager_input_attestation as A
from infrastructure.owned_io import SafeRoot

def probe(overlay=None):
    manifest=Path(overlay) if overlay else APP.parent/'release-manifest.json'
    raw=manifest.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    for k,v in {'V4_APP_ROOT':str(APP),'V4_RELEASE_ID':P['release_id'],'V4_RELEASE_MANIFEST_PATH':str(APP.parent/'release-manifest.json'),'V4_RELEASE_MANIFEST_SHA256':digest,'STAGE_CENTER_CONFIG':str(APP/'stage_center_tick_config.json')}.items():os.environ[k]=v
    original=SafeRoot.read_bytes
    if overlay:
        def reader(self,relative,*args,**kwargs):
            if self.root==APP.parent and relative=='release-manifest.json':return raw
            return original(self,relative,*args,**kwargs)
        SafeRoot.read_bytes=reader
    try:
        cfg=json.loads((APP/'stage_center_tick_config.json').read_bytes());data=Path(cfg['v4_research_data_root'])
        owner,ledger,_=A.trusted_research_owner(APP,data)
        results={}
        for slot,when in [('1300','13:15:00'),('1400','14:45:00'),('0900','09:35:00')]:
            try:
                record,_=A.read_stage_hourly_attestation(stage_app=APP,data_root=data,date='20261029',slot=slot,mode='LIVE',as_of=datetime.fromisoformat('2026-10-29T'+when+'+08:00'))
                results[slot]={'status':'VERIFIED','completion_witness':record['completion_witness']}
            except Exception as error:results[slot]={'status':'REJECTED','error':type(error).__name__+':'+str(error)}
        assert results['1300']['status']==results['1400']['status']=='VERIFIED',results
        assert results['0900']['status']=='REJECTED',results
        return {'status':'PASS','mode':'CANDIDATE_MANIFEST_OVERLAY_NOT_DEPLOYED' if overlay else 'ACTUAL_INSTALLED_READER','manifest_sha256':digest,'trusted_owner':str(owner),'ledger':str(ledger),'results':results,'shared_writes':0}
    finally:SafeRoot.read_bytes=original

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--candidate-overlay',type=Path);a=parser.parse_args();print(json.dumps(probe(a.candidate_overlay),ensure_ascii=False))
