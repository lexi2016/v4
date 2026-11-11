"""Bounded offline source/identity/witness checks; never activate or materialize."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import plistlib
import subprocess
import sys

W = Path('/Users/lexi/.codex/worktrees/stage-witness-owner-20261112/v4_app')
sys.path.insert(0, str(W))
from ops.api_release_integration import inventory_tree, inventory_digest


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p): return json.loads(Path(p).read_bytes())
def require(value, error):
    if not value: raise RuntimeError(error)

def check(root):
    root = Path(root); receipt = load(root / 'PREPARE_RECEIPT.json')
    stage = receipt['stage']; main = receipt['main']
    for role in (stage, main):
        require(sha(role['live_plist']) == role['before_plist']['sha256'], 'LIVE_OWNER_CHANGED_REGENERATE_CANDIDATE')
        require(sha(role['proposed_plist']['path']) == role['proposed_plist']['sha256'], 'PROPOSED_PLIST_DRIFT')
    app = Path(stage['app_root']); manifest = load(stage['manifest']['path'])
    require(sha(stage['manifest']['path']) == stage['manifest']['sha256'], 'STAGE_SEAL_DRIFT')
    inv = inventory_tree(app)
    require(inv == manifest['application_inventory']['entries'] and inventory_digest(inv) == manifest['application_inventory']['aggregate_sha256'], 'INVENTORY_DRIFT')
    old_config = load(Path(stage['before_app_root']) / 'stage_center_tick_config.json')
    require(stage['helper_before']['sha256'] == stage['helper_after']['sha256'] == '63408260062e5f32430a00990ef716d81b103b3090cf93374b4cc6112fdf5b17', 'UNCHANGED_DEPLOYED_CAP16_HELPER_REQUIRED')
    require(len(old_config['research_historical_owner_bindings']) == 9, 'EXPECTED_NINE_PRIOR_HISTORY')
    before_stage_plist = plistlib.loads(Path(stage['before_plist']['path']).read_bytes())
    before_stage_manifest = load(before_stage_plist['EnvironmentVariables']['V4_RELEASE_MANIFEST_PATH'])
    require(before_stage_plist['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256'] == '5ffcf399b35ee9e9f5c919ee0c8b39fb1f758f85f17cd3319a85b6e904e2ce5b', 'EXPECTED_DEPLOYED_R2_STAGE')
    actual_changed = [a['path'] for a,b in zip(inv,before_stage_manifest['application_inventory']['entries']) if a != b]
    require(len(inv) == len(before_stage_manifest['application_inventory']['entries']) and actual_changed == ['stage_center_tick_config.json'], 'ONLY_CONFIG_INVENTORY_DIFF_ALLOWED')
    require(stage['inventory_changed'] == actual_changed, 'SOURCE_DIFF_RECEIPT_MISMATCH')
    config = load(stage['config']['path'])
    require(len(config['research_historical_owner_bindings']) == 10, 'EXPECTED_TEN_PRESERVED_HISTORY')
    changed_config = sorted(k for k in set(config) | set(old_config) if config.get(k) != old_config.get(k))
    require(changed_config == ['release_id', 'research_historical_owner_bindings', 'research_owner_binding'], 'CONFIG_SCOPE_DIFF')
    require(config['research_historical_owner_bindings'][:-1] == old_config['research_historical_owner_bindings']
            and config['research_historical_owner_bindings'][-1] == old_config['research_owner_binding']
            and config['research_transition_owner_binding'] == old_config['research_transition_owner_binding'], 'HISTORICAL_OR_TRANSITION_CHANGED')
    old_main = plistlib.loads(Path(main['before_plist']['path']).read_bytes())
    proposed_main = plistlib.loads(Path(main['proposed_plist']['path']).read_bytes())
    restored_main = copy.deepcopy(proposed_main)
    for key in ('V4_RESEARCH_RETENTION_POLICY', 'V4_RESEARCH_RETENTION_POLICY_SHA256'):
        restored_main['EnvironmentVariables'][key] = old_main['EnvironmentVariables'][key]
    require(restored_main == old_main, 'MAIN_IDENTITY_OR_UNRELATED_PLIST_CHANGED')
    before_policy, policy = load(main['before_policy']['path']), load(main['proposed_policy']['path'])
    restored_policy = copy.deepcopy(policy)
    restored_policy['managed_pin_inventory'] = before_policy['managed_pin_inventory']
    restored_policy['single_generation_lifecycle']['reader_inventory'] = before_policy['single_generation_lifecycle']['reader_inventory']
    require(restored_policy == before_policy, 'POLICY_OUTSIDE_CONTROL_REFS_CHANGED')
    old_pins, pins = load(main['before_pins']['path']), load(main['proposed_pins']['path'])
    restored_pins = copy.deepcopy(pins)
    for diff in receipt['exact_stage_pin_diffs']:
        require(restored_pins['source_bindings'][diff['index']] == diff['proposed'], 'PIN_DIFF_RECEIPT_MISMATCH')
        restored_pins['source_bindings'][diff['index']] = diff['before']
    require(restored_pins == old_pins and len(receipt['exact_stage_pin_diffs']) == 4, 'UNRELATED_PINS_OR_SCOPES_CHANGED')
    old_att, att = load(main['before_reader_attestation']['path']), load(main['proposed_reader_attestation']['path'])
    restored_att = copy.deepcopy(att); consumer_diff = receipt['reader_stage_consumer_diff']
    selected = [i for i, row in enumerate(restored_att['consumers']) if row['label'] == 'com.lexi.stage-center.scheduler']
    require(len(selected) == 1 and restored_att['consumers'][selected[0]] == consumer_diff['proposed'], 'STAGE_ATTESTATION_DIFF_DRIFT')
    restored_att['consumers'][selected[0]] = consumer_diff['before']
    require(restored_att == old_att, 'OTHER_READER_ATTESTATION_CHANGED')
    stage_plist = plistlib.loads(Path(stage['proposed_plist']['path']).read_bytes())
    env = {**os.environ, **stage_plist['EnvironmentVariables']}
    source = '''from pathlib import Path
import os,json,datetime
from zoneinfo import ZoneInfo
from infrastructure.manager_input_attestation import trusted_research_owner,read_stage_hourly_attestation
app=Path(os.environ['V4_APP_ROOT']);config=json.loads((app/'stage_center_tick_config.json').read_bytes());root=Path(config['v4_research_data_root'])
owner,ledger,evidence=trusted_research_owner(app,root)
rows=[]
for day,slot in [('20261110','0900'),('20261111','0900'),('20261106','0900'),('20261112','0900')]:
 cutoff=datetime.datetime.strptime(day+'0945','%Y%m%d%H%M').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
 try:
  publication,evidence=read_stage_hourly_attestation(stage_app=app,data_root=root,date=day,slot=slot,mode='LIVE',as_of=cutoff)
  rows.append(dict(date=day,status='WITNESS_PASS',owner_evidence=[x for x in evidence if 'owner' in x],completion_witness=publication['completion_witness']))
 except Exception as error:rows.append(dict(date=day,status='CANNOT_CONFIRM',type=type(error).__name__,error=str(error)))
try:
 read_stage_hourly_attestation(stage_app=app,data_root=root,date='20261111',slot='0900',mode='LIVE',as_of=datetime.datetime(2026,11,11,8,0,tzinfo=ZoneInfo('Asia/Shanghai')))
 raise RuntimeError('EARLY_CUTOFF_WAS_NOT_REJECTED')
except Exception as error:
 early=dict(type=type(error).__name__,error=str(error))
 assert 'AFTER_AS_OF' in str(error),early
print(json.dumps(dict(identity='ORIGINAL_TRUSTED_OWNER_PASS',actual_main=str(owner),samples=rows,early_cutoff=early),ensure_ascii=False))
'''
    proc = subprocess.run([sys.executable, '-B', '-c', source], cwd=app, env=env, capture_output=True, text=True, timeout=45)
    require(proc.returncode == 0, 'ORIGINAL_STAGE_HELPER_FAILED:' + proc.stderr)
    witness = json.loads(proc.stdout)
    require(witness['actual_main'] == main['app_root'], 'TRUSTED_MAIN_NOT_EXACT_ACTUAL_BINDING')
    expected = {'20261110': 'v4-v192-assets-20261109-r1-main', '20261111': 'v4-daily-storage-recovery-20261110-r1-main', '20261106': 'v4-daily-before1700-20261105-r1-main'}
    for sample in witness['samples']:
        if sample['date'] in expected:
            require(sample['status'] == 'WITNESS_PASS' and sample['completion_witness']['release_id'] == expected[sample['date']], 'ORIGINAL_DATED_WITNESS_REGRESSION')
        else:
            if sample['status'] == 'WITNESS_PASS':
                accepted_releases = {row['release_id'] for row in [config['research_owner_binding'], *config['research_historical_owner_bindings']]}
                require(sample['completion_witness']['release_id'] in accepted_releases, 'ACTUAL_D12_OWNER_NOT_BOUND')
            else:
                require(sample['status'] == 'CANNOT_CONFIRM' and sample['type'] in {'FileNotFoundError','PublicationError'}, 'REAL_D12_EVIDENCE_UNRESOLVED')
    env = {**os.environ, **proposed_main['EnvironmentVariables']}
    payload = dict(pins=pins, proposed_stage_plist=stage['proposed_plist']['path'], stage_live_plist=stage['live_plist'])
    source = '''from pathlib import Path
import json,sys
from ops.research_storage_governance import configured_policy
from ops.research_storage_retention import _checked_file
policy=configured_policy();payload=json.loads(sys.stdin.read());rows=[]
for r in payload['pins']['source_bindings']:
 actual=payload['proposed_stage_plist'] if r['path']==payload['stage_live_plist'] else r['path']
 proof=_checked_file(Path(actual),r['sha256']);rows.append(dict(authoritative_path=r['path'],validation_payload=actual,sha256=proof['sha256']))
print(json.dumps(dict(status='ORIGINAL_MAIN_CONFIGURED_POLICY_PASS',planned_pin_payloads=rows,future_live_stage_pin='NOT_INSTALLED_NOT_CLAIMED_LIVE_PASS')))
'''
    proc = subprocess.run([sys.executable, '-B', '-c', source], cwd=main['app_root'], env=env,
        input=json.dumps(payload), capture_output=True, text=True, timeout=45)
    require(proc.returncode == 0, 'ORIGINAL_MAIN_CONTROL_CONFIG_FAILED:' + proc.stderr)
    main_control = json.loads(proc.stdout)
    for role in (stage, main):
        require(sha(role['live_plist']) == role['before_plist']['sha256'], 'LIVE_OWNER_CHANGED_DURING_VALIDATION')
    result = dict(status='OFFLINE_SOURCE_IDENTITY_AND_WITNESS_PASS_NOT_ACTIVATED', stage_inventory_entries=len(inv),
        source_diff=stage['inventory_changed'], semantic_config_diff=changed_config,
        main_business_identity_unchanged=True, main_control=main_control, actual_witness=witness,
        no_live_actions=True, old_transition_and_all_prior_history_preserved=True,
        activation_precondition=receipt['activation_precondition'])
    out = root / 'VALIDATION.json'; out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--candidate-root', type=Path, required=True)
    args = parser.parse_args(); result = check(args.candidate_root)
    print(json.dumps(dict(status=result['status'], entries=result['stage_inventory_entries'], witness=result['actual_witness']), ensure_ascii=False))
