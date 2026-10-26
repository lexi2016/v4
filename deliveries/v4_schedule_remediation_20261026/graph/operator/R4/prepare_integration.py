"""R4 metadata only: API r2 from shared clone; retain exact R3 one-shot stage."""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import plistlib
import shutil
import difflib

CASE=Path(__file__).resolve().parent
FROZEN=CASE/'R3_FROZEN'
spec=importlib.util.spec_from_file_location('r3_inventory_only',FROZEN/'prepare_integration.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
inventory=module.inventory


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ui-receipt',type=Path,required=True)
    args=parser.parse_args()
    if not args.ui_receipt.is_file():raise ValueError('UI_HANDOFF_REQUIRED_BEFORE_FINAL_METADATA')
    scope=json.loads((CASE/'SCOPE.json').read_text());root=Path(scope['shared_clone'])
    active_base=Path(scope['api_r2_release_root']).with_name('schedule-remediation-20261026-api-r1')/'app'
    before_files={row['path']:row for row in inventory(active_base)}
    candidate_files=inventory(root);after_files={row['path']:row for row in candidate_files}
    changed=[name for name in sorted(set(before_files)|set(after_files)) if before_files.get(name)!=after_files.get(name)]
    if any(name not in {'apps/api/v35_api/runtime_graph_router.py','domains/task_status.py'} and not name.startswith('tests/') for name in changed):
        raise ValueError('R4_UNEXPECTED_COMPOSITION_DIFF')
    # This also proves that both external lifecycle notes and all UI assets
    # remain byte-identical to the current immutable API r1 baseline.
    output=CASE/'integration'
    if output.exists():raise ValueError('R4_METADATA_ALREADY_EXISTS_NO_OVERWRITE')
    output.mkdir();(output/'baseline').mkdir();(output/'proposed').mkdir()
    plan=json.loads((FROZEN/'integration/BINDING_PLAN.json').read_text())
    api_release=next(r for r in plan['releases'] if r['component']=='api')
    api_op=next(r for r in plan['operations'] if r['role']=='api')
    current_plist=Path(api_op['target']);current_raw=current_plist.read_bytes()
    if sha(current_raw)!=scope['api_plist_before_sha256']:raise ValueError('API_R1_BASELINE_PLIST_DRIFT')
    current=plistlib.loads(current_raw)
    old_app=Path(next(value.split('=',1)[1] for value in current['ProgramArguments'] if value.startswith('V35_APP_ROOT=')))
    if old_app.parent.name!='schedule-remediation-20261026-api-r1':raise ValueError('API_R1_BASELINE_ROOT_DRIFT')
    target=Path(scope['api_r2_release_root'])
    manifest=json.loads((old_app.parent/'release-manifest.json').read_text())
    manifest.update(release_id=target.name,baseline_app=str(old_app),baseline_release_manifest=str(old_app.parent/'release-manifest.json'),
                    baseline_release_manifest_sha256=sha((old_app.parent/'release-manifest.json').read_bytes()),
                    candidate_app_root=str(root),app_files=candidate_files,source_change_scope=changed,r4_changed_paths=changed,
                    r4_identity_manifest_sha256=sha((CASE/'IDENTITY_ONLY_MANIFEST.json').read_bytes()),
                    r4_ui_handoff_path=str(args.ui_receipt),r4_ui_handoff_sha256=sha(args.ui_receipt.read_bytes()))
    manifest_raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();manifest_path=output/'api-release-manifest.json';manifest_path.write_bytes(manifest_raw)
    api_release.update(source_app=str(root),baseline_app=str(old_app),destination=str(target),manifest=str(manifest_path),manifest_sha256=sha(manifest_raw),
                       baseline_manifest=str(old_app.parent/'release-manifest.json'),baseline_manifest_sha256=sha((old_app.parent/'release-manifest.json').read_bytes()))
    proposed=copy.deepcopy(current);old_release=str(old_app.parent);new_release=str(target)
    proposed['ProgramArguments']=[value.replace(old_release,new_release) for value in proposed['ProgramArguments']]
    proposed['WorkingDirectory']=str(target/'app')
    env=proposed.setdefault('EnvironmentVariables',{})
    for key,value in list(env.items()):
        if isinstance(value,str):env[key]=value.replace(old_release,new_release)
    env.update(V35_RELEASE_ID=target.name,V35_RELEASE_MANIFEST_SHA256=sha(manifest_raw))
    for index,value in enumerate(proposed['ProgramArguments']):
        if value.startswith('V35_RELEASE_ID='):proposed['ProgramArguments'][index]='V35_RELEASE_ID='+target.name
        elif value.startswith('V35_RELEASE_MANIFEST_SHA256='):proposed['ProgramArguments'][index]='V35_RELEASE_MANIFEST_SHA256='+sha(manifest_raw)
    proposal_raw=plistlib.dumps(proposed,sort_keys=False)
    for op in plan['operations']:
        before=output/'baseline'/Path(op['target']).name;after=output/'proposed'/Path(op['target']).name
        if op['role']=='api':before.write_bytes(current_raw);after.write_bytes(proposal_raw);op.update(expected_sha256=sha(current_raw),proposed_sha256=sha(proposal_raw))
        else:shutil.copy2(op['baseline'],before);shutil.copy2(op['proposed'],after)
        op.update(baseline=str(before),proposed=str(after))
    for release in plan['releases']:
        if release['component']=='api':continue
        copied=output/(release['component']+'-release-manifest.json');shutil.copy2(release['manifest'],copied);release['manifest']=str(copied)
        # Keep destination, bytes and SHA exactly matching already-staged R3.
    plan['prepared_only']=True;plan['r4_ui_handoff_sha256']=sha(args.ui_receipt.read_bytes())
    (output/'BINDING_PLAN.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    original=json.loads((FROZEN/'SOURCE_DIFF_MANIFEST.json').read_text())
    identity=json.loads((CASE/'IDENTITY_ONLY_MANIFEST.json').read_text())
    for row in original['changed_files']:
        if row['component']=='api' and row['relative_path']=='apps/api/v35_api/runtime_graph_router.py':
            row.update(candidate=identity['candidate'],after_sha256=identity['after_sha256'])
    support=['prepare_integration.py','integrate_batch1.py','activate_one_shots.py','api_activation_gate.py','activate_graph_only.py',
             'activate_daily_deadline.py','test_identity_priority.py','test_non_graph_operator.py','test_stage_reuse.py','baseline_runtime_graph_router.py','IDENTITY_ONLY_MANIFEST.json','SCOPE.json']
    original['support_files']=[{'path':str(CASE/name),'sha256':sha((CASE/name).read_bytes())} for name in support]
    original['r4_increment']='Only API identity module ordering; UI separately bound by handoff and complete app inventory'
    original['r3_business_files_other_than_router_unchanged']=True
    (CASE/'BATCH1_SCOPE.json').write_bytes((CASE/'SCOPE.json').read_bytes())
    original['scope_sha256']=sha((CASE/'BATCH1_SCOPE.json').read_bytes())
    patch=[]
    for row in original['changed_files']:
        before=Path(row['baseline']);after=Path(row['candidate'])
        patch.extend(difflib.unified_diff(before.read_text().splitlines(True),after.read_text().splitlines(True),fromfile=str(before),tofile=str(after)))
    (CASE/'SOURCE_DIFF.patch').write_text(''.join(patch));original['diff_sha256']=sha((CASE/'SOURCE_DIFF.patch').read_bytes())
    (CASE/'SOURCE_DIFF_MANIFEST.json').write_text(json.dumps(original,ensure_ascii=False,indent=2)+'\n')
    receipt={'scope_sha256':sha((CASE/'BATCH1_SCOPE.json').read_bytes()),'source_diff_manifest_sha256':sha((CASE/'SOURCE_DIFF_MANIFEST.json').read_bytes()),
             'binding_plan_sha256':sha((output/'BINDING_PLAN.json').read_bytes()),'api_manifest_sha256':sha(manifest_raw),
             'api_proposal_sha256':sha(proposal_raw),'api_release_root':str(target),'ui_handoff_sha256':sha(args.ui_receipt.read_bytes()),'active_writes':0}
    (CASE/'FINAL_SEAL.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
