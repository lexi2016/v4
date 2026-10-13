"""Local-only actual saved canary HTTP fixture. Never synchronize its output."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[6]
HANDOFF=ROOT/'docs/handoff/manager-workbench-implementation-20261013'
proof=json.loads((HANDOFF/'real-single-article-canary-receipt.json').read_text())
candidate=HANDOFF/'deployment-deltas/isolated-api-candidate-v5/app'
script='''import sys,json
from pathlib import Path
from fastapi.testclient import TestClient
from apps.api.v35_api.app import create_app
from v4.manager_workbench.config import WorkbenchConfig
p=json.loads(sys.stdin.read());root=Path(p['state_directory'])
cfg=WorkbenchConfig(state_root=root/'derived',manager_root=root/'unread-manager',shared_root=root/'unread-shared',stage_root=root/'unread-stage')
app=create_app(data_root=root/'api-auxiliary',manager_workbench_config=cfg)
with TestClient(app) as c:
 params=dict(phase='RETROSPECTIVE',run_id=p['run_id'])
 day=c.get('/api/v4/manager-workbench/days/20261012',params=params);detail=c.get('/api/v4/manager-workbench/stocks/HK.06655',params={**params,'date':'20261012'})
 assert day.status_code==detail.status_code==200
 assert day.json()['data']['snapshot']['product_sha256']==p['product_sha256']
 print(json.dumps(dict(day=day.json(),detail=detail.json()),ensure_ascii=False))
'''
r=subprocess.run([sys.executable,'-c',script],cwd=candidate,input=json.dumps(proof),capture_output=True,text=True)
if r.returncode:raise RuntimeError(r.stderr[-2000:])
output=Path(__file__).with_name('real-announcement-http.local.json');output.write_text(r.stdout)
print(json.dumps(dict(fixture=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),http_source='actual R10 candidate TestClient + immutable real r2 snapshot',model_calls=0,excluded_from_sync=True)))
