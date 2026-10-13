"""Read an immutable real canary through the active-base candidate. No model."""
import json
import subprocess
import sys
from pathlib import Path
HANDOFF=Path(__file__).resolve().parent
REPO=HANDOFF.parents[2]
CANDIDATE=HANDOFF/'deployment-deltas/isolated-api-candidate-v6/app'
original=json.loads((HANDOFF/'real-single-article-owner-identity-v3-canary-receipt.json').read_text())
script='''import json,sys
from pathlib import Path
from fastapi.testclient import TestClient
from apps.api.v35_api.app import create_app
from v4.manager_workbench.config import WorkbenchConfig
p=json.loads(sys.stdin.read());state=Path(p['state_directory'])/'derived'
cfg=WorkbenchConfig(state_root=state,manager_root=state.parent/'unread-manager',shared_root=state.parent/'unread-shared',stage_root=state.parent/'unread-stage')
app=create_app(data_root=state.parent/'api-auxiliary',manager_workbench_config=cfg)
with TestClient(app) as c:
 r=c.get('/api/v4/manager-workbench/days/20261012',params={'phase':'RETROSPECTIVE','run_id':p['run_id']});d=r.json()['data']
 assert r.status_code==200 and d['snapshot']['product_sha256']==p['product_sha256']
 assert len(d['stocks'])==1 and d['stocks'][0]['decision']=='UNASSESSED'
 proof=dict(http_status=r.status_code,run_id=p['run_id'],product_sha256=d['snapshot']['product_sha256'],counts=d['counts'],stocks=len(d['stocks']),immutable_saved_product_matches=True,model_calls=0,manager_page_status=c.get('/manager-selection/').status_code,empty_date_status=c.get('/api/v4/manager-workbench/days/20261014').status_code)
 print(json.dumps(proof))
'''
r=subprocess.run([sys.executable,'-c',script],cwd=CANDIDATE,input=json.dumps(original),text=True,capture_output=True)
(HANDOFF/'integration-real-v6-saved-readback.log').write_text(r.stdout+r.stderr)
if r.returncode:print(r.stderr);raise SystemExit(r.returncode)
proof=json.loads(r.stdout);proof.update(candidate_app=str(CANDIDATE),state_directory=original['state_directory'],environment='RETROSPECTIVE saved real single article, read only through TestClient; no model or port')
(HANDOFF/'integration-real-v6-saved-readback-receipt.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof))
