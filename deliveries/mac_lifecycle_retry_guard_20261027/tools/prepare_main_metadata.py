"""Prepare immutable Main metadata only; application bytes stay identical."""
from pathlib import Path
import copy
import hashlib
import json
import plistlib
import shutil

B=Path(__file__).resolve().parent
BASE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/runtime-graph-repair-20261026-main-r2')
TARGET=BASE.parent/'mac-lifecycle-main-binding-20261027-r1'
COMPONENT=BASE.parent/'mac-lifecycle-retry-component-20261027-r1'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def ref(path):return dict(path=str(path),sha256=sha(path))
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')


def main():
    source=json.loads((B/'control/COMPONENT_PACKAGE.json').read_text());physical=Path(source['final_package']['root'])
    # A fresh outer component manifest binds every staged file and the new
    # fixed entry. It does not rewrite the old a_daily outer manifest.
    component_files={p.relative_to(physical.parent).as_posix():sha(p) for p in physical.rglob('*') if p.is_file()}
    outer=physical.parent/'release-manifest.json'
    save(outer,dict(schema='lifecycle_a_sync_component_release.v1',release_id=COMPONENT.name,
        files=component_files,clean_binding=str(COMPONENT/'a_sync/app/ops/a_share_daily_sync.py'),
        original_a_sync_root='/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/schedule-remediation-a-daily-20261026-r1/a_sync',
        component_manifest_sha256=sha(physical/'component/component-manifest.json'),
        RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False))
    candidate=B/'main_package'/TARGET.name;candidate.mkdir(parents=True,exist_ok=False)
    old_raw=(BASE/'release-manifest.json').read_bytes();old_sha=hashlib.sha256(old_raw).hexdigest();old=json.loads(old_raw)
    assert old_sha=='2ed2da9abc77280da40f0f6f2cf9f0401759d517b7272b30c6ea3f5053cef031'
    shutil.copytree(BASE/'app',candidate/'app',symlinks=True)
    files={p.relative_to(BASE).as_posix():sha(p) for p in (BASE/'app').rglob('*') if p.is_file()}
    copied={p.relative_to(candidate).as_posix():sha(p) for p in (candidate/'app').rglob('*') if p.is_file()}
    assert files==copied
    # Existing inventory includes source bookkeeping; require exact declared
    # files and retain all originals without silently dropping extras.
    assert all(files.get(k)==v for k,v in old['files'].items() if k.startswith('app/'))
    updated=copy.deepcopy(old)
    previous={k:copy.deepcopy(old[k]) for k in ('release_id','app_root','clean_binding','external_a_clean_binding_files','external_a_clean_component_sources','source_a_manifest','source_a_release')}
    updated.update(release_id=TARGET.name,app_root=str(TARGET/'app'),candidate_app_root=str(candidate/'app'),
        future_installed_root=str(TARGET),prepared_root=str(candidate),clean_binding=str(COMPONENT/'a_sync/app/ops/a_share_daily_sync.py'),
        external_a_clean_binding_files={str(COMPONENT/rel):digest for rel,digest in component_files.items()},
        external_a_clean_component_sources={str(COMPONENT/'a_sync/component'/p['path']):p['sha256'] for p in json.loads((physical/'component/component-manifest.json').read_text())['files']},
        lifecycle_parent_release_manifest=ref(BASE/'release-manifest.json'),lifecycle_parent_binding_provenance=previous,
        lifecycle_component_release=dict(path=str(COMPONENT/'release-manifest.json'),sha256=sha(outer)),
        lifecycle_scope='MAIN_METADATA_BINDING_ONLY; APPLICATION_BYTES_UNCHANGED; NO_LANE_LOGIC_CHANGE',
        status='PREPARED_NOT_ACTIVE',activation_performed=False)
    save(candidate/'release-manifest.json',updated)
    assert sha(BASE/'release-manifest.json')==old_sha
    plist=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist');before=plist.read_bytes();j=plistlib.loads(before);after=copy.deepcopy(j)
    manifest_sha=sha(candidate/'release-manifest.json')
    replacements={'V35_APP_ROOT':str(TARGET/'app'),'V35_RELEASE_ID':TARGET.name,
        'V35_RELEASE_MANIFEST_PATH':str(TARGET/'release-manifest.json'),'V35_RELEASE_MANIFEST_SHA256':manifest_sha,
        'V35_RESEARCH_PANEL_A_SYNC_SCRIPT':updated['clean_binding']}
    def replace(key,value):
        if key in replacements:return replacements[key]
        if key=='PYTHONPATH':return ':'.join(str(TARGET/'app')+p[len(str(BASE/'app')):] if p==str(BASE/'app') or p.startswith(str(BASE/'app')+'/') else p for p in value.split(':'))
        return value
    for key,value in j.get('EnvironmentVariables',{}).items():after['EnvironmentVariables'][key]=replace(key,value)
    for i,arg in enumerate(j['ProgramArguments']):
        if '=' in arg:key,value=arg.split('=',1);after['ProgramArguments'][i]=key+'='+replace(key,value)
    assert j['WorkingDirectory']==str(BASE/'app');after['WorkingDirectory']=str(TARGET/'app')
    allowed=set(replacements)|{'PYTHONPATH'}
    for key,value in j.get('EnvironmentVariables',{}).items():
        if key not in allowed:assert after['EnvironmentVariables'][key]==value
    for old_arg,new_arg in zip(j['ProgramArguments'],after['ProgramArguments']):
        if old_arg.split('=',1)[0] not in allowed:assert old_arg==new_arg
    for key in j:
        if key not in {'WorkingDirectory','ProgramArguments','EnvironmentVariables'}:assert after[key]==j[key]
    (B/'control/main-scheduler.before.plist').write_bytes(before);(B/'control/main-scheduler.candidate.plist').write_bytes(plistlib.dumps(after,sort_keys=False))
    save(B/'control/MAIN_METADATA_PACKAGE.json',dict(package_root=str(candidate),target_root=str(TARGET),manifest=ref(candidate/'release-manifest.json'),
        old_manifest=ref(BASE/'release-manifest.json'),old_plist=ref(plist),candidate_plist=ref(B/'control/main-scheduler.candidate.plist'),
        main_application_file_count=len(files),application_files_all_exact=copied==files,component_manifest=ref(outer),
        new_component_target=str(COMPONENT),healthy_lane_bytes_and_env_preserved=True,scheduler_reload_executed=False,
        runtime_activation='REQUIRES_ROOT_DECISION_AND_SHARED_SCHEDULER_RELOAD_AUTHORIZATION'))
    print(json.dumps(dict(status='MAIN_METADATA_ONLY_CANDIDATE',application_files=len(files),manifest_sha256=manifest_sha)))


if __name__=='__main__':main()
