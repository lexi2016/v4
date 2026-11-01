#!/usr/bin/env python3
"""Read-only final candidate/source/data/role preservation audit."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import plistlib

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate',type=Path,required=True)
parser.add_argument('--replay',type=Path,required=True)
args=parser.parse_args()
source=Path(__file__).resolve().parents[3];sys.path.insert(0,str(source))
from ops import prepare_f10_stage_binding as prepare
from ops.activate_stage_four_repairs import verify_release
receipt=json.loads((args.candidate/'candidate_receipt.json').read_bytes())
tools=prepare.inventory_tools(prepare.ROLE_PINS['api'][1])
results={}
for role,values in prepare.ROLE_PINS.items():
    assert prepare.loaded_role(*values)==receipt['actual_role_baselines'][role]
    prepare.verified_baseline(values[1],values[2],tools)
for role,row in receipt['roles'].items():
    app=Path(row['app_root']); results[role]=verify_release(app.parent,row['manifest_sha256'],tools)
    manifest=json.loads((app.parent/'release-manifest.json').read_bytes())
    delta=manifest['f10_stage_binding_repair']['delta']
    assert [r['path'] for r in delta]==row['delta']
    if role=='stage':assert (app/prepare.ATTESTATION).read_bytes()==(source/prepare.ATTESTATION).read_bytes()
    else:
        assert {r['path'] for r in delta}=={prepare.MANUAL_REL,*[v['path'] for v in row['generated_cache_omissions']]}
    for entry in tools.inventory_tree(app):
        assert '__pycache__' not in Path(entry['path']).parts and not entry['path'].endswith(('.pyc','.pyo'))
external=receipt['protected_external'];env=receipt['preserved_panel_environment']
for key,ref in external.items():
    if key!='panel_inventory':assert prepare.sha(Path(ref['path']).read_bytes())==ref['sha256']
panel=Path(env['V4_RESEARCH_PANEL_ROOT']);entries=tools.inventory_tree(panel)
assert {'entry_count':len(entries),'aggregate_sha256':tools.inventory_digest(entries)}==external['panel_inventory']
assets=json.loads(Path(env['V4_RESEARCH_PANEL_ASSET_MANIFEST']).read_bytes())['files']
for item in assets:
    prepare.no_alias(panel/item['path']);assert prepare.sha((panel/item['path']).read_bytes())==item['sha256']
for role,proposal in receipt['release_proposal'].items():
    original_raw=Path(proposal['copied_preimage']).read_bytes();proposed_raw=Path(proposal['proposed_plist']).read_bytes()
    assert prepare.sha(original_raw)==proposal['original_sha256'] and prepare.sha(proposed_raw)==proposal['proposed_sha256']
    original=plistlib.loads(original_raw);proposed=plistlib.loads(proposed_raw)
    assert proposed['EnvironmentVariables']==receipt['proposed_environment'][role]
    assert proposed['WorkingDirectory']==receipt['roles'][role]['app_root']
    assert proposed.get('StartCalendarInterval')==original.get('StartCalendarInterval')
    if role=='stage':
        old=receipt['actual_role_baselines'][role]['environment']['V4_APP_ROOT'];new=receipt['roles'][role]['app_root']
        assert proposed['ProgramArguments']==[s.replace(old,new) for s in original['ProgramArguments']]
        assert proposed['EnvironmentVariables']['PYTHONPATH']==original['EnvironmentVariables']['PYTHONPATH'].replace(old,new)
    else:assert proposed['ProgramArguments']==original['ProgramArguments']
plan=json.loads((args.candidate/'two-role-release-plan.json').read_bytes())
assert plan['forward_order']==['stage','api'] and plan['rollback_order']==['api','stage']
assert plan['activation_executed'] is False and plan['existing_fixed_workflow']['direct_original_command_usable'] is False
for item in plan['protected_labels']:assert prepare.sha(Path(item['plist_path']).read_bytes())==item['plist_sha256']
source_reads={};ledger_reads={}
replay=json.loads(args.replay.read_bytes())
stage=Path(receipt['roles']['stage']['app_root']);config=json.loads((stage/'stage_center_tick_config.json').read_bytes())
for sample in replay['samples']:
    assert sample['status']=='PASS_READ_ONLY_HISTORICAL_REPLAY'
    for name,digest in sample['reads'].items():
        assert prepare.sha(Path(name).read_bytes())==digest;source_reads[name]=digest
    witness=sample['completion_witness'];path=Path(config['research_scheduler_ledger_root'])/witness['receipt_ref']
    assert prepare.sha(path.read_bytes())==witness['receipt_sha256'];ledger_reads[str(path)]=witness['receipt_sha256']
manual=receipt['manual_source'];assert prepare.sha(Path(manual['path']).read_bytes())==manual['sha256']
print(json.dumps({'status':'PASS_READ_ONLY_PROTECTION_AUDIT','roles':results,
    'loaded_baselines_and_plists_unchanged':True,'web_panel_and_other_app_bytes_unchanged':True,
    'external_panel_file_count':len(entries),'manifest_listed_assets_sha_verified':len(assets),
    'protected_source_data_files':len(source_reads),'protected_original_dispatch_receipts':len(ledger_reads),
    'generated_cache_omissions':receipt['roles']['api']['generated_cache_omissions'],
    'candidate_bytecode_cache_count':0,'review_only_release_proposals_verified':True,'protected_label_count':len(plan['protected_labels']),'data_written':False,'services_activated':False},ensure_ascii=False,indent=2))
