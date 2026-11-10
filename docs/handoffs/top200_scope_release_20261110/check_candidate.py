"""Read-only packaging integration check; no sockets, service or producer actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


p = argparse.ArgumentParser()
p.add_argument('--packet', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
packet = json.loads(a.packet.read_text())
api = packet['services']['api']
env = plistlib.loads(Path(api['draft_plist']).read_bytes())['EnvironmentVariables']
root = Path(env['V4_A_SHARE_DAILY_PRODUCT_ROOT'])
if (root / 'daily_products/a_share/index.json').is_file():
    root = root / 'daily_products/a_share'
stage = Path(env['V4_OPENING_SELECTION_ROOT'])
protected = [root / 'index.json', stage / 'selection_latest.json']
protected += sorted((stage.parent / 'receipts/20261109').glob('*/receipt.json'))
before = {str(path): sha(path) for path in protected}


def child(role, code):
    service = packet['services'][role]
    child_env = dict(os.environ)
    child_env.update(plistlib.loads(Path(service['draft_plist']).read_bytes())['EnvironmentVariables'])
    child_env.update(PYTHONPATH=service['app_root'], PYTHONDONTWRITEBYTECODE='1',
                     TOP200_PACKET=str(a.packet))
    result = subprocess.run([sys.executable, '-B', '-c', code], cwd=service['app_root'],
                            env=child_env, text=True, capture_output=True)
    if result.returncode:
        a.out.with_suffix('.failure.json').write_text(json.dumps(dict(role=role,
            returncode=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2))
        raise RuntimeError(role + ': ' + result.stderr)
    return json.loads(result.stdout)


policy = child('main', '''
import json,os
from pathlib import Path
from ops.research_storage_governance import configured_policy
from ops.research_storage_retention import _checked_file
p=json.loads(Path(os.environ['TOP200_PACKET']).read_text())
policy=configured_policy()
pins=json.loads(Path(policy['managed_pin_inventory']['path']).read_text())
sub={s['live_plist']:s['draft_plist'] for s in p['services'].values()}
for ref in pins['source_bindings']:
    _checked_file(Path(sub.get(ref['path'],ref['path'])),ref['sha256'])
print(json.dumps(dict(status='PASS_ACTUAL_MAIN_POLICY_AUTHORITY_AND_CHECKED_FILE',
  source_bindings=len(pins['source_bindings']),expected_main_app_root=pins['expected_main_app_root'],
  draft_api_plist_substitution=True,auto_gc_enabled=policy['auto_gc_enabled'],dry_run=policy['dry_run'])))
''')
api_result = child('api', '''
import hashlib,json,os
from pathlib import Path
from fastapi.testclient import TestClient
from apps.api.v4_api.app import create_app
client=TestClient(create_app(data_root=Path(os.environ['V4_DATA_ROOT']),
 shared_data_root=Path(os.environ['V4_SHARED_DATA_ROOT']),
 ledger_root=Path(os.environ['V4_DISPATCH_LEDGER_ROOT']) if os.environ.get('V4_DISPATCH_LEDGER_ROOT') else None,
 stage_center_selection_root=Path(os.environ['V4_STAGE_CENTER_SELECTION_ROOT'])))
paths=['/api/v1/runs/date-list','/api/v4/runtime-graph/frontend-build',
 '/api/v4/research/a-share/top200-hit?date=20261109','/']
responses={path:client.get(path) for path in paths}
assert all(r.status_code==200 for r in responses.values()),[(p,r.status_code,r.text[:300])for p,r in responses.items()]
dates=responses[paths[0]].json();front=responses[paths[1]].json()
assert dates['runtime_identity']['release_id']==os.environ['V4_RELEASE_ID']
assert dates['runtime_identity']['status']=='MANIFEST_EXECUTION_FILES_VERIFIED'
assert front['status']=='VERIFIED' and front['api_manifest_sha256']==os.environ['V4_RELEASE_MANIFEST_SHA256']
row=next(r for r in responses[paths[2]].json()['dates'] if r['date']=='20261109')
assert (row['a_pool']['selected_count'],row['a_pool']['hit_count'])==(487,36)
assert (row['seven_stage']['selected_count'],row['seven_stage']['hit_count'],row['stage_coverage']['available'])==(10,2,1)
assert all(s['execution_status']=='EXECUTION_FAILED' and s['hit_count'] is None
 for k,s in row['seven_stage']['stages'].items() if k!='STAGE_0925')
index=responses['/'].content
app=Path(os.environ['V4_APP_ROOT'])
assert index==(app/'apps/web/dist/index.html').read_bytes()
assert b'main-DCRf2b-t.js' in index and b'main-n9OD1tAD.css' in index
for asset in ['main-DCRf2b-t.js','main-n9OD1tAD.css']:
 r=client.get('/assets/'+asset);assert r.status_code==200
 assert r.content==(app/'apps/web/dist/assets'/asset).read_bytes()
print(json.dumps(dict(status='PASS_CANDIDATE_ASGI_READ_ONLY',http_status={p:r.status_code for p,r in responses.items()},
 release_id=os.environ['V4_RELEASE_ID'],manifest_sha256=os.environ['V4_RELEASE_MANIFEST_SHA256'],
 dated_pool=dict(selected=487,hits=36),stage=dict(selected=10,hits=2,available=1),
 native_frontend_exact_bytes=True,frontend_build_status=front['status'])))
''')
after = {str(path): sha(path) for path in protected}
assert before == after, 'BUSINESS_SOURCE_CHANGED_DURING_READ_ONLY_CHECK'
result = dict(status='PASS_READ_ONLY_CANDIDATE_INTEGRATION', packet_sha256=sha(a.packet),
              policy=policy, api=api_result, preserved_source_hashes=before,
              service_operations=False, producer_replay=False, business_data_written=False,
              actual_deployment='NOT_RUN', actual_UI='NOT_RUN', natural_run='NOT_RUN')
a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False))
