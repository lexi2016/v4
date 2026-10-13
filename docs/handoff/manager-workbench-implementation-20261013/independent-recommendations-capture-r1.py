"""Read-only saved-run HTTP fixtures. Local raw responses must never be uploaded."""
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib,json,sys
H=Path(__file__).resolve().parent;W=H.parents[2];sys.path.insert(0,str(W));sys.dont_write_bytecode=True
from fastapi import FastAPI
from fastapi.testclient import TestClient
from v4.manager_workbench.api import create_router,PREFIX
from v4.manager_workbench.contracts import PlanSnapshot
FORMAL=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
sha=lambda raw:hashlib.sha256(raw).hexdigest()
config=json.loads((FORMAL/'config/manager-workbench-v7.json').read_bytes())
proof={}
def client(run):
 path=FORMAL/'state/manager_workbench/manager_workbench/snapshots'/f'{run}.json';raw=path.read_bytes();snap=PlanSnapshot.model_validate(json.loads(raw))
 proof[run]=dict(path=str(path),raw_sha256=sha(raw),product_sha256=snap.product_sha256)
 service=NS(config=NS(shared_root=Path(config['shared_root']) if config.get('shared_root') else None),store=NS(get_plan=lambda *a,**k:snap,list_plans=lambda *a:[snap]))
 app=FastAPI();app.include_router(create_router(service));return TestClient(app),snap
run='528ef6fd4f0b49e7a3ec2b6719fc9afe';c,snap=client(run)
def get(c,run,lane,**kw):
 response=c.get(PREFIX+'/days/20261013/recommendations/'+lane,params=dict(run_id=run,**kw));assert response.status_code==200;return response.json()
us=get(c,run,'US_MAPPING');over=get(c,run,'OVERSOLD');negative=get(c,run,'OVERSOLD',decision='NOT_SELECTED',q='HK.09988')
def detail(c,run,lane,row):
 response=c.get(PREFIX+'/stocks/'+row['symbol'],params=dict(date='20261013',run_id=run,lane=lane,row_id=row['row_id']));assert response.status_code==200;return response.json()
responses=dict(us=us,oversold=over,oversold_alibaba_not_selected=negative,us_detail=detail(c,run,'US_MAPPING',us['data']['stocks'][0]),oversold_detail=detail(c,run,'OVERSOLD',negative['data']['stocks'][0]))
old='84eafbbb71ba4767a591d1a4286fe061';c,snap=client(old);old_over=get(c,old,'OVERSOLD',q='HK.09927')
old_display=dict(us=get(c,old,'US_MAPPING'),oversold=old_over,detail=detail(c,old,'OVERSOLD',old_over['data']['stocks'][0]))
for p in proof.values():assert sha(Path(p['path']).read_bytes())==p['raw_sha256']
out=W/'apps/web/src/manager-workbench/__tests__/fixtures/independent-recommendations-http.local.json'
out.write_text(json.dumps(dict(responses=responses,old_display=old_display,saved_snapshots=proof),ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(fixture=str(out),sha256=sha(out.read_bytes()),saved_snapshots=proof,formal_writes=0,models=0,network=0)))
