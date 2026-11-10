"""Read-only three-consumer Main compatibility/owner closure check."""
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


parser = argparse.ArgumentParser()
parser.add_argument('--packet', type=Path, required=True)
parser.add_argument('--envelope', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
packet = json.loads(args.packet.read_text())
config = json.loads(Path(packet['stage_config_before']['path']).read_text())
selection = Path(config['selection_root'])
protected = [selection / 'selection_latest.json', args.envelope]
protected += [Path(config['raw_root']) / name for name in ('latest.json', 'bundle_latest.json')]
for date in ('20261109', '20261110'):
    protected += sorted((Path(config['receipt_root']) / date).glob('*/receipt.json'))
api_env = packet['services']['api']['baseline_payload']['EnvironmentVariables']
product = Path(api_env['V4_A_SHARE_DAILY_PRODUCT_ROOT'])
if (product / 'daily_products/a_share/index.json').is_file():
    product = product / 'daily_products/a_share'
protected += [product / 'index.json']
protected = [p for p in protected if p.is_file()]
before = {str(p): sha(p) for p in protected}
temporary_store = Path(packet['root']) / 'checks' / 'isolated-selection'
if temporary_store.exists():
    raise ValueError('FRESH_ISOLATED_STORE_REQUIRED')


def child(role, code):
    service = packet['services'][role]
    env = dict(os.environ)
    env.update(plistlib.loads(Path(service['draft_plist']).read_bytes())['EnvironmentVariables'])
    env.update(PYTHONPATH=service['app_root'], PYTHONDONTWRITEBYTECODE='1',
        A925_PACKET=str(args.packet), A925_ENVELOPE=str(args.envelope), A925_STORE=str(temporary_store))
    result = subprocess.run([sys.executable, '-B', '-c', code], cwd=service['app_root'],
                            env=env, capture_output=True, text=True)
    if result.returncode:
        args.out.with_suffix('.failure.json').write_text(json.dumps(dict(role=role,
            returncode=result.returncode, stdout=result.stdout, stderr=result.stderr), indent=2))
        raise RuntimeError(role + ': ' + result.stderr)
    return json.loads(result.stdout)


policy = child('main', '''
import json,os
from pathlib import Path
from ops.research_storage_governance import configured_policy
from ops.research_storage_retention import _checked_file
p=json.loads(Path(os.environ['A925_PACKET']).read_text());policy=configured_policy()
pins=json.loads(Path(policy['managed_pin_inventory']['path']).read_text())
sub={s['live_plist']:s['draft_plist']for s in p['services'].values()}
for ref in pins['source_bindings']:_checked_file(Path(sub.get(ref['path'],ref['path'])),ref['sha256'])
print(json.dumps(dict(status='PASS_ACTUAL_MAIN_POLICY_AND_24_SOURCE_BINDINGS',
 count=len(pins['source_bindings']),draft_plist_substitution=True,
 expected_main_app_root=pins['expected_main_app_root'],auto_gc_enabled=policy['auto_gc_enabled'],dry_run=policy['dry_run'])))
''')

stage = child('stage', '''
import json,os,sys
from pathlib import Path
from datetime import datetime
from copy import deepcopy
from stage_center.selection import SelectionStore
from ops import run_stage_center_nodes as nodes
p=json.loads(Path(os.environ['A925_PACKET']).read_text());s=p['services']['stage']
before=json.loads(Path(p['stage_config_before']['path']).read_text())
after=json.loads((Path(s['app_root'])/'stage_center_tick_config.json').read_text())
envelope=json.loads(Path(os.environ['A925_ENVELOPE']).read_text())
store=SelectionStore(Path(os.environ['A925_STORE']))
store.publish(envelope,market='A_SHARE')
new=store.read_verified(envelope['trade_date'],envelope['stage_id'],'A_SHARE')
old=SelectionStore(Path(after['selection_root'])).read_verified('20261110','STAGE_0925','A_SHARE')
assert new['algorithm_sha256']=='15fd78695c5c0b345dcbf6b32f884320b1fb51b3f9b40876bfe83fe9655fa896'
assert new['rows']==envelope['rows'] and old['algorithm_sha256']!=new['algorithm_sha256']
assert any(r.get('field_readiness') for r in new['rows'])
from infrastructure.manager_input_attestation import read_stage_hourly_attestation
now=datetime.now(nodes.SHANGHAI);date=now.strftime('%Y%m%d')
publication,owner_evidence=read_stage_hourly_attestation(stage_app=Path(s['app_root']),
 data_root=Path(after['v4_research_data_root']),date='20261110',slot='0900',mode='LIVE',as_of=now)
old_main_id=p['services']['main']['baseline_payload']['EnvironmentVariables']['V4_RELEASE_ID']
assert 'v4_research_historical_owner_release_id='+old_main_id in owner_evidence
hourly=dict(status='PASS_OLD_MAIN_CURRENT_DAY_HISTORICAL_PROVENANCE_READ_ONLY',date='20261110',slot='0900',
 selected_historical_release_id=old_main_id,new_main_natural_execution_claim=False,
 completion_witness_present=bool(publication.get('completion_witness')),owner_evidence=list(owner_evidence))
assert hourly['completion_witness_present']
old_due=[n.node_id for n in nodes._node_candidates(date,now,explicit_node=None,config=before)]
new_due=[n.node_id for n in nodes._node_candidates(date,now,explicit_node=None,config=after)]
assert old_due==new_due
settled=[]
for item in nodes.NODES:
 if not item.is_prep:
  receipt=nodes._read_receipt(after,date,item.stage_id or '')
  if nodes._stage_settled(receipt):settled.append(item.node_id)
assert not set(settled)&set(new_due)
print(json.dumps(dict(status='PASS_ACTUAL_STAGE_ISOLATED_ROUNDTRIP_OLD_AND_NEW_ALGORITHMS',
 interpreter=sys.executable,new_algorithm=new['algorithm_sha256'],old_algorithm=old['algorithm_sha256'],
 new_rows=len(new['rows']),old_rows=len(old['rows']),isolated_store=os.environ['A925_STORE'],
 due_identity_only=dict(evaluated_at=now.isoformat(),date=date,before=old_due,after=new_due,
 settled_stages_not_rearmed=settled),hourly_owner_readback=hourly,jobs_executed=False,provider_queries=False)))
''')

main_consumer = child('main', """
import json,os,sys
from pathlib import Path
from stage_center.selection import SelectionStore
from stage_center.consumer import StageSelectionConsumer
from ops.run_v4_macos_scheduler import consume_shared_stage_selection
store=Path(os.environ['A925_STORE'])
new=SelectionStore(store).read_verified('20261109','STAGE_0925','A_SHARE')
old=SelectionStore(Path(os.environ['V4_STAGE_CENTER_SELECTION_ROOT'])).read_verified('20261110','STAGE_0925','A_SHARE')
assert new['algorithm_sha256']=='15fd78695c5c0b345dcbf6b32f884320b1fb51b3f9b40876bfe83fe9655fa896'
assert old['algorithm_sha256']!=new['algorithm_sha256']
projected=StageSelectionConsumer(store).get('20261109','STAGE_0925',markets=('A_SHARE',))
market=projected['markets']['A_SHARE']
assert len(market['rows'])==10 and market['algorithm_sha256']==new['algorithm_sha256']
listener=consume_shared_stage_selection(business_date='20261109',slot='0925',selection_root=store)
assert listener['status']=='CONSUME_ONLY' and listener['write_performed'] is False
assert listener['producer_called'] is False and listener['direct_acquisition_called'] is False
assert len(listener['selection_markets']['A_SHARE']['rows'])==10
print(json.dumps(dict(status='PASS_ACTUAL_MAIN_NEW_AND_OLD_READERS_AND_ORIGINAL_LISTENER_CONSUMER',
 interpreter=sys.executable,new_algorithm=new['algorithm_sha256'],old_algorithm=old['algorithm_sha256'],
 new_rows=len(new['rows']),old_rows=len(old['rows']),consumer_rows=len(market['rows']),
 original_listener_status=listener['status'],original_listener_rows=len(listener['selection_markets']['A_SHARE']['rows']),
 scheduler_executed=False,producer_called=False,live_store_written=False)))
""")

api = child('api', '''
import json,os,sys,hashlib
from pathlib import Path
from fastapi.testclient import TestClient
from stage_center.selection import SelectionStore
from apps.api.v4_api.app import create_app
p=json.loads(Path(os.environ['A925_PACKET']).read_text())
new=SelectionStore(Path(os.environ['A925_STORE'])).read_verified('20261109','STAGE_0925','A_SHARE')
old=SelectionStore(Path(os.environ['V4_STAGE_CENTER_SELECTION_ROOT'])).read_verified('20261110','STAGE_0925','A_SHARE')
assert new['algorithm_sha256']=='15fd78695c5c0b345dcbf6b32f884320b1fb51b3f9b40876bfe83fe9655fa896'
assert old['algorithm_sha256']!=new['algorithm_sha256']
assert any(r.get('field_readiness') for r in new['rows'])
client=TestClient(create_app(data_root=Path(os.environ['V4_DATA_ROOT']),
 shared_data_root=Path(os.environ['V4_SHARED_DATA_ROOT']),
 ledger_root=Path(os.environ['V4_DISPATCH_LEDGER_ROOT'])if os.environ.get('V4_DISPATCH_LEDGER_ROOT')else None,
 stage_center_selection_root=Path(os.environ['V4_STAGE_CENTER_SELECTION_ROOT'])))
dates=client.get('/api/v1/runs/date-list');front=client.get('/api/v4/runtime-graph/frontend-build')
assert dates.status_code==front.status_code==200
identity=dates.json()['runtime_identity'];frontend=front.json()
assert identity['status']=='MANIFEST_EXECUTION_FILES_VERIFIED' and identity['release_id']==os.environ['V4_RELEASE_ID']
assert frontend['status']=='VERIFIED' and frontend['api_manifest_sha256']==os.environ['V4_RELEASE_MANIFEST_SHA256']
index=Path(os.environ['V4_APP_ROOT'])/'apps/web/dist/index.html'
old_index=Path(p['services']['api']['old_app_root'])/'apps/web/dist/index.html'
assert index.read_bytes()==old_index.read_bytes()
assert b'main-DCRf2b-t.js' in index.read_bytes()
print(json.dumps(dict(status='PASS_ACTUAL_API_NEW_OLD_STORE_CONSUMPTION_AND_HOMEPAGE',
 interpreter=sys.executable,new_algorithm=new['algorithm_sha256'],old_algorithm=old['algorithm_sha256'],
 new_rows=len(new['rows']),old_rows=len(old['rows']),release_id=os.environ['V4_RELEASE_ID'],
 manifest_sha256=os.environ['V4_RELEASE_MANIFEST_SHA256'],frontend_status=frontend['status'],
 top200_native_index_preserved=True,native_index_sha256=hashlib.sha256(index.read_bytes()).hexdigest(),
 date_list_http=dates.status_code,frontend_build_http=front.status_code)))
''')
after = {str(p): sha(p) for p in protected}
assert before == after, 'LIVE_SOURCE_CHANGED_DURING_CHECK'
result = dict(status='PASS_THREE_CONSUMERS_AND_HISTORICAL_MAIN_OWNER_CLOSURE',
    packet_sha256=sha(args.packet), interpreter=sys.executable, policy=policy, stage=stage, main_consumer=main_consumer, api=api,
    preserved_source_hashes=before, service_operations=False, provider_queries=False,
    existing_envelope_serialized_only=True, live_data_written=False,
    deployment='NOT_RUN', actual_UI='NOT_RUN', natural_run='NOT_RUN')
args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False))
