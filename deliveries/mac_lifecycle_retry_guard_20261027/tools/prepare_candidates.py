"""Bounded lifecycle component assembly and original API integration builder."""
import ast
import copy
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

B=Path(__file__).resolve().parent
W=Path('/Users/lexi/.codex/worktrees/mac-lifecycle-retry-guard-20261027/v4_app')
OLD=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/schedule-remediation-a-daily-20261026-r1/a_sync')
API=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/futu76-mac-price-signal-api-20261027-r2')
FINAL=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/mac-lifecycle-retry-component-20261027-r1/a_sync')
sys.path.insert(0,str(W))
from ops import api_release_integration as integration
from ops import build_release_candidate as original_builder
integration.MODULE_CONTRACT_PATH=B/'control/api_module_contracts.json'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def ref(path):return dict(path=str(path),sha256=sha(path))
def save(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')


def shim_values(original,values,env):
    tree=ast.parse(original);out=original
    for node in tree.body:
        if not isinstance(node,ast.Assign) or len(node.targets)!=1:continue
        target=node.targets[0];replacement=None
        if isinstance(target,ast.Name) and target.id in values:replacement=target.id+' = '+values[target.id]
        if (isinstance(target,ast.Subscript) and isinstance(target.value,ast.Attribute)
                and isinstance(target.value.value,ast.Name) and target.value.value.id=='os'
                and target.value.attr=='environ' and isinstance(target.slice,ast.Constant) and target.slice.value in env):
            key=target.slice.value;replacement='os.environ['+json.dumps(key)+'] = '+json.dumps(env[key])
        if replacement is not None:
            old=ast.get_source_segment(original,node);assert out.count(old)==1;out=out.replace(old,replacement,1)
    return out


def component(physical,declared,pins,source_ref):
    physical.mkdir(parents=True,exist_ok=False)
    for p in pins:
        dst=physical/'component'/p['path'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(W/p['path'],dst)
    for rel in ['seed-evidence-descriptor.json','preimage/a_share_daily_sync.py']:
        dst=physical/'component'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(OLD/'component'/rel,dst)
    manifest=json.loads((OLD/'component/component-manifest.json').read_text())
    manifest.update(component_id='mac-lifecycle-retry-component-20261027-r1',files=pins,file_count=len(pins),
        source_manifest_path=source_ref['path'],source_manifest_sha256=source_ref['sha256'],source_manifest_entry_count=len(pins),
        external_approved_descriptor=ref(physical/'component/seed-evidence-descriptor.json'))
    # Keep this provenance locator truthful for each immutable variant.
    manifest['external_approved_descriptor']['path']=str(declared/'component/seed-evidence-descriptor.json')
    save(physical/'component/component-manifest.json',manifest)
    original=(OLD/'app/ops/a_share_daily_sync.py').read_text()
    values={'_COMPONENT_ROOT':'Path('+json.dumps(str(declared/'component'))+')',
        '_FIXED_ENTRY':'Path('+json.dumps(str(declared/'app/ops/a_share_daily_sync.py'))+')',
        '_COMPONENT_MANIFEST_SHA':json.dumps(sha(physical/'component/component-manifest.json')),
        '_SOURCE_MANIFEST_SHA':json.dumps(source_ref['sha256']), '_PINS':json.dumps(pins,ensure_ascii=False)}
    env={'V35_A_SYNC_SEED_ADJUSTMENT_INPUTS':str(declared/'component/seed-evidence-descriptor.json'),
         'V35_A_SYNC_SEED_ADJUSTMENT_INPUTS_SHA256':sha(physical/'component/seed-evidence-descriptor.json')}
    rendered=shim_values(original,values,env)
    # Compare original loader semantics with only declared constants neutralized.
    neutral={k:'None' for k in values};neutral_env={k:'neutral' for k in env}
    assert ast.dump(ast.parse(shim_values(original,neutral,neutral_env)))==ast.dump(ast.parse(shim_values(rendered,neutral,neutral_env)))
    entry=physical/'app/ops/a_share_daily_sync.py';entry.parent.mkdir(parents=True);entry.write_text(rendered)
    overlay=json.loads((OLD/'component/overlay-manifest.json').read_text())
    overlay.update(component_root=str(declared/'component'),component_manifest_path=str(declared/'component/component-manifest.json'),
        component_manifest_sha256=sha(physical/'component/component-manifest.json'),source_manifest_path=source_ref['path'],
        source_manifest_sha256=source_ref['sha256'],fixed_entry_path=str(declared/'app/ops/a_share_daily_sync.py'),
        preimage_path=str(declared/'component/preimage/a_share_daily_sync.py'),installed_shim_sha256=sha(entry),
        status='CANDIDATE_NOT_INSTALLED')
    save(physical/'component/overlay-manifest.json',overlay)
    return dict(root=str(physical),declared_root=str(declared),entry=ref(entry),manifest=ref(physical/'component/component-manifest.json'),
        source=source_ref,ops_file_count=len(pins),loader_logic_unchanged=True,descriptor_unchanged=sha(physical/'component/seed-evidence-descriptor.json')==sha(OLD/'component/seed-evidence-descriptor.json'))


def main():
    pins=[]
    for p in sorted([*(W/'ops/_a_share_daily_sync_parts').glob('*.py'),W/'ops/a_share_daily_sync.py',W/'ops/a_share_lifecycle_notes.json']):
        pins.append(dict(path=p.relative_to(W).as_posix(),bytes=p.stat().st_size,sha256=sha(p)))
    assert len(pins)==15
    save(B/'SOURCE_COMPONENT_MANIFEST.json',dict(schema='lifecycle_retry_exact_component.v1',baseline_manifest=ref(OLD/'component/component-manifest.json'),
        files=pins,source_fact_rows='Prior19 plus accepted two broker facts; no data/PIT certification',
        changed_paths=['ops/a_share_daily_sync.py','ops/_a_share_daily_sync_parts/sync_workflow.py','ops/a_share_lifecycle_notes.json']))
    source=ref(B/'SOURCE_COMPONENT_MANIFEST.json')
    local=B/'component_validation/a_sync';a=component(local,local,pins,source)
    final=B/'component_package/mac-lifecycle-retry-component-20261027-r1/a_sync';z=component(final,FINAL,pins,source)
    save(B/'control/COMPONENT_PACKAGE.json',dict(local_validation=a,final_package=z,root_target=str(FINAL),
        scheduler_environment_delta={'V35_RESEARCH_PANEL_A_SYNC_SCRIPT':str(FINAL/'app/ops/a_share_daily_sync.py')},
        no_runtime_writes=True,install_requires='Root materializes absent new root; exact one-env scheduler binding CAS; running scheduler environment requires Root decision before reload'))
    # Produce the one-env candidate without writing/restarting the scheduler.
    sp=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist');before=sp.read_bytes();j=plistlib.loads(before);k=copy.deepcopy(j)
    old_entry=str(OLD/'app/ops/a_share_daily_sync.py');new_entry=str(FINAL/'app/ops/a_share_daily_sync.py');changes=0
    for key,value in j.get('EnvironmentVariables',{}).items():
        if key=='V35_RESEARCH_PANEL_A_SYNC_SCRIPT':assert value==old_entry;k['EnvironmentVariables'][key]=new_entry;changes+=1
    for i,value in enumerate(j.get('ProgramArguments',[])):
        if value.startswith('V35_RESEARCH_PANEL_A_SYNC_SCRIPT='):
            assert value=='V35_RESEARCH_PANEL_A_SYNC_SCRIPT='+old_entry;k['ProgramArguments'][i]='V35_RESEARCH_PANEL_A_SYNC_SCRIPT='+new_entry;changes+=1
    assert changes==1
    # Reverse exactly that scalar and demand equality for all other fields.
    reversed_payload=copy.deepcopy(k)
    if 'V35_RESEARCH_PANEL_A_SYNC_SCRIPT' in reversed_payload.get('EnvironmentVariables',{}):reversed_payload['EnvironmentVariables']['V35_RESEARCH_PANEL_A_SYNC_SCRIPT']=old_entry
    reversed_payload['ProgramArguments']=[x.replace(new_entry,old_entry) if x=='V35_RESEARCH_PANEL_A_SYNC_SCRIPT='+new_entry else x for x in reversed_payload['ProgramArguments']]
    assert reversed_payload==j
    (B/'control/scheduler.before.plist').write_bytes(before);(B/'control/scheduler.candidate.plist').write_bytes(plistlib.dumps(k,sort_keys=False))
    # Existing active-base exact-delta API builder; inventory comes from the
    # original build_release_candidate helper, with mandatory entry_count.
    ap=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist');active=integration.read_active_release(ap)
    assert active['release_manifest_sha256']=='680d9516725cd625a9c80a96c8a5536e4ccc3fe45f54720a8fbe9c5e02db6a34'
    entries=[]
    for rel in sorted(['apps/api/v35_api/a_share_lifecycle_notes.json','apps/api/v35_api/a_share_panel_history.py']):
        old=(API/'app'/rel).read_bytes();new=(W/rel).read_bytes();proof,hunks=integration._diff_proof(old,new)
        entries.append(dict(path=rel,before_sha256=hashlib.sha256(old).hexdigest(),after_sha256=hashlib.sha256(new).hexdigest(),unified_diff_sha256=proof,unified_diff_hunk_count=hunks))
    delta=dict(schema_version=integration.DELTA_SCHEMA_VERSION,base=integration._base_binding(active),entries=entries)
    save(B/'control/API_DELTA.json',delta)
    package=B/'api_package/mac-lifecycle-notes-21-api-20261027-r1';package.mkdir(parents=True,exist_ok=False)
    result=integration.build_integrated_app(active_api_plist_path=ap,source_root=W,candidate_root=package,delta_receipt_path=B/'control/API_DELTA.json')
    inventory=original_builder.inventory_tree(package/'app')
    manifest=dict(schema_version=original_builder.SCHEMA_VERSION,candidate=dict(root=str(package),app_root=str(package/'app'),release_id=package.name,module_role='gateway'),
        application_inventory=dict(entry_count=len(inventory),entries=inventory,aggregate_sha256=original_builder.inventory_digest(inventory)),api_integration=result,
        research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    save(package/'release-manifest.json',manifest)
    check=integration.verify_api_release_candidate(candidate_root=package,active_api_plist_path=ap,expected_manifest_sha256=sha(package/'release-manifest.json'))
    code="import sys,json;sys.path.insert(0,sys.argv[1]);from infrastructure.scheduling.dispatcher import validate_release_identity;print(json.dumps(validate_release_identity(),sort_keys=True))"
    env=dict(os.environ,V35_APP_ROOT=str(package/'app'),V35_RELEASE_ID=package.name,V35_RELEASE_MANIFEST_PATH=str(package/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=sha(package/'release-manifest.json'))
    validation=subprocess.run([sys.executable,'-B','-c',code,str(package/'app')],cwd=package/'app',env=env,text=True,capture_output=True)
    save(B/'control/ORIGINAL_DISPATCHER.json',dict(exit_code=validation.returncode,stdout=validation.stdout,stderr=validation.stderr))
    assert validation.returncode==0
    save(B/'control/API_PACKAGE.json',dict(package_root=str(package),manifest=ref(package/'release-manifest.json'),verification=check,
        dispatcher_pass=True,entry_count=len(inventory),api_source=ref(package/'app/apps/api/v35_api/a_share_panel_history.py'),
        active_preimage=ref(API/'release-manifest.json'),active_plist=ref(ap),no_service_actions=True))
    print(json.dumps(dict(status='CANDIDATES_PREPARED',component_ops=15,api_entry_count=len(inventory),api_non_delta_preserved=check['non_delta_entry_count'])))


if __name__=='__main__':main()
