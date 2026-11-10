"""Prepare the exact API/static V192 delta; never activate or migrate pins.

Reuse the installed V4 release helpers under an explicit, recorded tools root.
The one managed API plist pin migrates through a new immutable pins/policy
pair. Main changes only its two policy environment references; Stage stays fixed.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import hashlib
import fcntl
import os
import importlib
import json
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile

API_PATHS={'infrastructure/research_workbench_v192.py','infrastructure/research_workbench_host.py'}
STATIC_PATHS={'workbench-host/dot/src/workbench-model.mjs','workbench-host/dot/shell/workbench.local.mjs'}
REWRITES={'V4_APP_ROOT','V4_RELEASE_ID','V4_RELEASE_MANIFEST_PATH','V4_RELEASE_MANIFEST_SHA256',
          'V4_RESEARCH_PANEL_ROOT','V4_RESEARCH_PANEL_ASSET_MANIFEST'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def record(path):return dict(path=str(path),sha256=sha(path))
def save(path,value):
    with Path(path).open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n')


@contextmanager
def release_tools(root):
    """Use only the named existing helper tree, restoring import state after."""
    saved={k:v for k,v in sys.modules.items() if k=='ops' or k.startswith('ops.')}
    search=list(sys.path)
    try:
        for key in saved:sys.modules.pop(key)
        sys.path.insert(0,str(root))
        helpers=importlib.import_module('ops.prepare_daily_materials_release')
        group=importlib.import_module('ops.prepare_v192_group_release')
        if Path(helpers.__file__).resolve()!=root/'ops/prepare_daily_materials_release.py':
            raise ValueError('EXACT_RELEASE_TOOLS_REQUIRED')
        yield helpers,group
    finally:
        for key in list(sys.modules):
            if key=='ops' or key.startswith('ops.'):sys.modules.pop(key)
        sys.modules.update(saved);sys.path[:]=search


@contextmanager
def service_tools(root):
    with release_tools(root):
        yield (importlib.import_module('ops.activate_daily_materials_release'),
               importlib.import_module('ops.prepare_top200_scope_release'))


def api_lock(path):
    from infrastructure.interprocess_lock import owned_interprocess_lock
    return owned_interprocess_lock(Path(path).with_name('.com.lexi.v4.api.release.lock'),timeout_seconds=2,
        timeout_message='API_RELEASE_SHARED_LOCK_BUSY')


def prepare(*,delta_path,output,baseline_path,tools_root):
    baseline=json.loads(baseline_path.read_text());delta=json.loads(delta_path.read_text())
    entries=delta['entries']
    if (len(entries)!=len(API_PATHS)+len(STATIC_PATHS)
            or {(r['scope'],r['target']) for r in entries}!=({('api',p) for p in API_PATHS}|{('research_panel',p) for p in STATIC_PATHS})
            or delta.get('deletions') or delta.get('api_environment')):
        raise ValueError('EXACT_V192_API_STATIC_DELTA_REQUIRED')
    approved=Path.home()/'Library/Application Support/com.lexi.v4.local/candidates'
    if (not output.is_absolute() or output.parent!=approved or output.resolve()!=output or output.exists()):
        raise ValueError('NEW_LIBRARY_CANDIDATE_REQUIRED')
    protected=[];payloads={}
    for role,service in baseline['services'].items():
        path=Path(service['path'])
        if path.is_symlink() or sha(path)!=service['sha256']:raise ValueError('LIVE_PLIST_DRIFT:'+role)
        payload=plistlib.loads(path.read_bytes());env=payload['EnvironmentVariables']
        if (sha(Path(service['manifest']))!=service['manifest_sha']
                or env['V4_APP_ROOT']!=service['app_root'] or env['V4_RELEASE_ID']!=service['release']
                or env['V4_RELEASE_MANIFEST_PATH']!=service['manifest']
                or env['V4_RELEASE_MANIFEST_SHA256']!=service['manifest_sha']):
            raise ValueError('BASE_RELEASE_IDENTITY_DRIFT:'+role)
        payloads[role]=payload;protected.extend([record(path),record(service['manifest'])])
    api=baseline['services']['api'];payload=payloads['api'];env=payload['EnvironmentVariables']
    if payload['Label']!='com.lexi.v4.api':raise ValueError('API_ONLY_LABEL_REQUIRED')
    old_app=Path(api['app_root']);old_manifest=Path(api['manifest'])
    manifest=json.loads(old_manifest.read_text())
    old_static=Path(env['V4_RESEARCH_PANEL_ROOT']);old_assets=Path(env['V4_RESEARCH_PANEL_ASSET_MANIFEST'])
    assets=json.loads(old_assets.read_text())
    if any(sha(old_static/r['path'])!=r['sha256'] for r in assets['files']):raise ValueError('STATIC_BASELINE_DRIFT')
    protected.append(record(old_assets))
    main_env=payloads['main']['EnvironmentVariables']
    policy_path=Path(main_env['V4_RESEARCH_RETENTION_POLICY'])
    if sha(policy_path)!=main_env['V4_RESEARCH_RETENTION_POLICY_SHA256']:raise ValueError('RETENTION_POLICY_DRIFT')
    policy=json.loads(policy_path.read_text());pin_ref=policy['managed_pin_inventory'];pins_path=Path(pin_ref['path'])
    if sha(pins_path)!=pin_ref['sha256']:raise ValueError('MANAGED_PINS_DRIFT')
    pins=json.loads(pins_path.read_text());protected.extend([record(policy_path),record(pins_path)])
    matching=[r for r in pins['source_bindings'] if r['path']==api['path']]
    if len(matching)!=1 or matching[0]['sha256']!=api['sha256']:
        raise ValueError('EXACT_ONE_API_PLIST_PIN_REQUIRED')
    if any(r['path']==baseline['services']['main']['path'] for r in pins['source_bindings']):
        raise ValueError('MAIN_REVERSE_PIN_CYCLE')
    for ref in pins['source_bindings']:
        if sha(ref['path'])!=ref['sha256']:raise ValueError('UNRELATED_MANAGED_PIN_DRIFT:'+ref['path'])
    output.mkdir();rid=output.name+'-api';app=output/rid/'app';app.parent.mkdir()
    with release_tools(tools_root) as (helpers,group):
        helpers.clone_release(old_app,app,manifest)
        for entry in entries:
            if entry['scope']=='api':group.overlay(app,entry)
        final=helpers.seal_manifest(manifest,app=app,release_id=rid,role='api',delta_paths=API_PATHS,base_manifest=old_manifest)
        final['v192_partial_group_repair']=dict(source_root=delta['source_root'],baseline_commit=delta['baseline_commit'],
            delta=record(delta_path),source_state='UNCOMMITTED_REVIEW_CANDIDATE',**dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False))
        final['activation_status']='REVIEW_CANDIDATE_NOT_ACTIVATED';final['deployment_status']='NOT_ACTIVATED'
        manifest_path=app.parent/'release-manifest.json';save(manifest_path,final)
        static=output/'research-panel';shutil.copytree(old_static,static,symlinks=True)
        for entry in entries:
            if entry['scope']=='research_panel':group.overlay(static,entry)
    # Inventory is source-only: include declared assets exactly, never runtime caches.
    listed={r['path'] for r in assets['files']}
    if not STATIC_PATHS<=listed:raise ValueError('STATIC_DELTA_NOT_ALREADY_DECLARED')
    for row in assets['files']:
        actual=sha(static/row['path'])
        if actual!=row['sha256'] and row['path'] not in STATIC_PATHS:raise ValueError('UNLISTED_STATIC_DELTA')
        row['sha256']=actual
    asset_path=output/'research-panel-assets.json';save(asset_path,assets)
    staged=deepcopy(payload);staged['WorkingDirectory']=str(app)
    staged['EnvironmentVariables'].update(V4_APP_ROOT=str(app),V4_RELEASE_ID=rid,
        V4_RELEASE_MANIFEST_PATH=str(manifest_path),V4_RELEASE_MANIFEST_SHA256=sha(manifest_path),
        V4_RESEARCH_PANEL_ROOT=str(static),V4_RESEARCH_PANEL_ASSET_MANIFEST=str(asset_path))
    if {k:v for k,v in staged['EnvironmentVariables'].items() if k not in REWRITES}!={k:v for k,v in env.items() if k not in REWRITES}:
        raise ValueError('UNRELATED_API_ENVIRONMENT_CHANGED')
    draft=output/'API_CANDIDATE.plist';draft.write_bytes(plistlib.dumps(staged,sort_keys=True));draft.chmod(0o600)
    backup=output/'API_BEFORE.plist';backup.write_bytes(Path(api['path']).read_bytes());backup.chmod(0o600)
    new_pins=deepcopy(pins)
    next(r for r in new_pins['source_bindings'] if r['path']==api['path'])['sha256']=sha(draft)
    new_pins_path=output/'research_storage_pins.json';save(new_pins_path,new_pins)
    new_policy=deepcopy(policy);new_policy['managed_pin_inventory']=record(new_pins_path)
    new_policy_path=output/'research_storage_policy.json';save(new_policy_path,new_policy)
    main_payload=deepcopy(payloads['main'])
    main_payload['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(new_policy_path),
        V4_RESEARCH_RETENTION_POLICY_SHA256=sha(new_policy_path))
    with service_tools(tools_root) as (_,guard):
        guard.assert_main_policy_only(payloads['main'],main_payload)
    main_draft=output/'MAIN_POLICY_CANDIDATE.plist'
    main_draft.write_bytes(plistlib.dumps(main_payload,sort_keys=True));main_draft.chmod(0o600)
    main_backup=output/'MAIN_BEFORE.plist'
    main_backup.write_bytes(Path(baseline['services']['main']['path']).read_bytes());main_backup.chmod(0o600)
    frozen=output/'FROZEN_DELTA.json';frozen.write_bytes(delta_path.read_bytes())
    for ref in protected:
        if sha(ref['path'])!=ref['sha256']:raise ValueError('PREPARE_SOURCE_CHANGED:'+ref['path'])
    toolfiles=[tools_root/'ops'/name for name in ('prepare_daily_materials_release.py','prepare_v192_group_release.py','api_release_integration.py','prepare_top200_scope_release.py','activate_daily_materials_release.py')]
    packet=dict(schema='v4.v192_partial_release.v1',status='PREPARED_NOT_ACTIVATED',root=str(output),
        tools_root=str(tools_root),
        api=dict(label=payload['Label'],old_app_root=str(old_app),old_manifest_sha256=api['manifest_sha'],
            manifest_sha256=sha(manifest_path),live_plist=api['path'],before_sha256=api['sha256'],draft_plist=str(draft),draft_plist_sha256=sha(draft),
            rollback_backup=record(backup),app_root=str(app),manifest=record(manifest_path),assets=record(asset_path)),
        protected_references=protected,delta=record(frozen),tool_source_files=[record(p) for p in toolfiles]+[record(Path(__file__).resolve())],
        main=dict(label=payloads['main']['Label'],old_app_root=baseline['services']['main']['app_root'],
            old_manifest_sha256=baseline['services']['main']['manifest_sha'],manifest_sha256=baseline['services']['main']['manifest_sha'],
            live_plist=baseline['services']['main']['path'],before_sha256=baseline['services']['main']['sha256'],
            draft_plist=str(main_draft),draft_plist_sha256=sha(main_draft),rollback_backup=record(main_backup),
            app_root=baseline['services']['main']['app_root'],release_id=baseline['services']['main']['release'],
            manifest=dict(path=baseline['services']['main']['manifest'],sha256=baseline['services']['main']['manifest_sha'])),
        policy=record(new_policy_path),pins=record(new_pins_path),old_policy=record(policy_path),old_pins=record(pins_path),
        activation_status='AWAITING_INDEPENDENT_REVIEW',control_roles=['api','main'],
        scheduler_lane_lock_root=str(Path.home()/'Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners'),
        future_protocol='Independent packet-bound review; shared API lock + DEFAULT/A_LONG lane locks; healthy Main work must finish; require_idle_main and loaded_environment_check; exact protected-reference CAS; API/Main bootout then wait_drained; replace_cas; Main bootstrap with policy-only refs, API bootstrap; read back identities; restore both exact backups on failure. No Stage service control, producer replay or runtime hot edits.',
        main_app_and_stage_unchanged=True,managed_pin_changes=1,main_policy_environment_changes=2,launchctl_called=False,
        RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    validate(packet)
    verify_contents(packet)
    save(output/'PREPARED_PACKET.json',packet)
    return packet


def validate(packet,*,installed=False,restored=False):
    """CAS readback, including the one migrated pin via draft substitution."""
    if installed and restored:raise ValueError('AMBIGUOUS_POINTER_MODE')
    roles={key:packet[key] for key in ('api','main')}
    expected_live={r['live_plist']:r['draft_plist_sha256'] if installed else r['before_sha256'] for r in roles.values()}
    for ref in packet['tool_source_files']+[packet['delta'],packet['policy'],packet['pins'],packet['old_policy'],packet['old_pins']]:
        if sha(ref['path'])!=ref['sha256']:raise ValueError('PACKET_REFERENCE_DRIFT:'+ref['path'])
    for ref in packet['protected_references']:
        if sha(ref['path'])!=expected_live.get(ref['path'],ref['sha256']):raise ValueError('PROTECTED_REFERENCE_DRIFT:'+ref['path'])
    for role,service in roles.items():
        if sha(service['live_plist'])!=expected_live[service['live_plist']]:raise ValueError('LIVE_PLIST_CAS_DRIFT:'+role)
        for ref in (dict(path=service['draft_plist'],sha256=service['draft_plist_sha256']),service['rollback_backup'],service['manifest']):
            if sha(ref['path'])!=ref['sha256']:raise ValueError('SERVICE_CANDIDATE_DRIFT:'+role)
    old_pins=json.loads(Path(packet['old_pins']['path']).read_text());new_pins=json.loads(Path(packet['pins']['path']).read_text())
    expected=deepcopy(old_pins)
    next(r for r in expected['source_bindings'] if r['path']==roles['api']['live_plist'])['sha256']=roles['api']['draft_plist_sha256']
    if new_pins!=expected:raise ValueError('EXACT_ONE_PIN_CHANGE_REQUIRED')
    for ref in new_pins['source_bindings']:
        target=roles['api']['draft_plist'] if not installed and ref['path']==roles['api']['live_plist'] else ref['path']
        if sha(target)!=ref['sha256']:raise ValueError('MANAGED_SOURCE_PIN_DRIFT:'+ref['path'])
    before=json.loads(Path(packet['old_policy']['path']).read_text());after=json.loads(Path(packet['policy']['path']).read_text())
    expected=deepcopy(before);expected['managed_pin_inventory']=packet['pins']
    if after!=expected:raise ValueError('POLICY_DELTA_OUTSIDE_PIN_REFERENCE')
    original=plistlib.loads(Path(roles['main']['rollback_backup']['path']).read_bytes())
    draft=plistlib.loads(Path(roles['main']['draft_plist']).read_bytes())
    expected=deepcopy(original);expected['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=packet['policy']['path'],V4_RESEARCH_RETENTION_POLICY_SHA256=packet['policy']['sha256'])
    if draft!=expected:raise ValueError('MAIN_DELTA_OUTSIDE_TWO_POLICY_REFERENCES')
    return dict(status='PASS_API_STATIC_ONE_PIN_AND_MAIN_TWO_POLICY_REFERENCES',mode='INSTALLED' if installed else 'RESTORED' if restored else 'PREPARED')


def verify_contents(packet):
    manifest=json.loads(Path(packet['api']['manifest']['path']).read_text())
    expected=manifest['application_inventory']
    with release_tools(Path(packet['tools_root'])) as (helpers,_):
        if helpers.frozen_inventory(Path(packet['api']['app_root']),expected['entries'])!=expected['entries']:
            raise ValueError('CANDIDATE_APP_INVENTORY_DRIFT')
    assets=json.loads(Path(packet['api']['assets']['path']).read_text())
    static=Path(packet['root'])/'research-panel'
    if any(sha(static/r['path'])!=r['sha256'] for r in assets['files']):raise ValueError('CANDIDATE_STATIC_DRIFT')
    if sha(packet['api']['assets']['path'])!=packet['api']['assets']['sha256']:raise ValueError('CANDIDATE_ASSET_MANIFEST_DRIFT')


def cutover(packet_path,review_path,*,rollback=False):
    """Controller-only transaction using existing idle/drain/CAS/restore guards."""
    packet=json.loads(packet_path.read_text());review=json.loads(review_path.read_text())
    if review.get('verdict') not in {'PASS','REVIEWED/PASS'} or review.get('packet_sha256')!=sha(packet_path):
        raise ValueError('INDEPENDENT_REVIEW_PACKET_BINDING_REQUIRED')
    validate(packet,installed=rollback);verify_contents(packet)
    services={r:packet[r] for r in ('api','main')}
    backup=packet_path.parent/'cutover-backup';backup.mkdir(exist_ok=True)
    state=dict(status='PRECHECK',rollback_requested=rollback,control_roles=['api','main'],
        stopped=[],changed=[],stage_service_operation=False,business_jobs_replayed=False)
    recovery_services=services;recovery_backup=backup
    state['recovery_target']='PRE_ROLLBACK_INSTALLED_TUPLE' if rollback else 'PRE_ACTIVATION_BASELINE_TUPLE'
    with service_tools(Path(packet['tools_root'])) as (svc,guard),ExitStack() as held:
        held.enter_context(api_lock(services['api']['live_plist']))
        for name in ('DEFAULT.lock','A_LONG.lock'):
            stream=held.enter_context((Path(packet['scheduler_lane_lock_root'])/name).open('a+'))
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            svc.require_idle_main(services['main'])
            for role,service in services.items():
                guard.loaded_environment_check(service)
                if rollback:
                    svc.require_previous_backups(services,backup)
                else:
                    live=Path(service['live_plist']);target=backup/(role+'.plist')
                    if target.exists() and target.read_bytes()!=live.read_bytes():raise ValueError('BACKUP_DRIFT:'+role)
                    target.write_bytes(live.read_bytes());target.chmod(0o600)
            validate(packet,installed=rollback)
            if rollback:
                # Explicit rollback targets the immutable activation backup.
                # Failure recovery targets the installed tuple at operation
                # entry instead, so never reuse or overwrite those originals.
                recovery_backup=Path(tempfile.mkdtemp(prefix='rollback-recovery-',dir=packet_path.parent))
                recovery_services={}
                for role,service in services.items():
                    live=Path(service['live_plist']);target=recovery_backup/(role+'.plist')
                    with target.open('xb') as stream:stream.write(live.read_bytes())
                    target.chmod(0o600)
                    if sha(target)!=service['draft_plist_sha256']:raise ValueError('PRE_ROLLBACK_SNAPSHOT_DRIFT:'+role)
                    recovery_services[role]=dict(service,
                        before_sha256=service['draft_plist_sha256'],draft_plist_sha256=service['before_sha256'],
                        old_app_root=service['app_root'],old_manifest_sha256=service['manifest_sha256'])
                save(recovery_backup/'RECOVERY_TARGET.json',dict(target=state['recovery_target'],
                    packet=record(packet_path),plists={role:record(recovery_backup/(role+'.plist')) for role in services}))
                state['recovery_snapshot']=str(recovery_backup)
                validate(packet,installed=True)
            # Lane locks exclude new Main work; never stop healthy children.
            svc.require_idle_main(services['main'])
            for role in ('main','api'):
                service=services[role];guard.loaded_environment_check(service)
                current,pid=svc.loaded(service['label'])
                expected_root=service['app_root'] if rollback else service['old_app_root']
                expected_sha=service['manifest_sha256'] if rollback else service['old_manifest_sha256']
                if current.returncode!=0 or not pid or expected_root not in current.stdout or expected_sha not in current.stdout:
                    raise ValueError('LOADED_SERVICE_IDENTITY_DRIFT:'+role)
                tracked=svc.descendants(pid)
                svc.run(['launchctl','bootout',f'gui/{os.getuid()}/{service["label"]}']).check_returncode()
                state['stopped'].append(role)
                svc.wait_drained(service['label'],tracked,api=role=='api')
            for role in ('api','main'):
                service=services[role]
                source=backup/(role+'.plist') if rollback else Path(service['draft_plist'])
                expected=service['draft_plist_sha256'] if rollback else service['before_sha256']
                svc.replace_cas(Path(service['live_plist']),source,expected);state['changed'].append(role)
            validate(packet,installed=not rollback,restored=rollback)
            for role in ('api','main'):
                service=services[role]
                svc.run(['launchctl','bootstrap',f'gui/{os.getuid()}',service['live_plist']]).check_returncode()
                wanted=dict(service,app_root=service['old_app_root'],manifest_sha256=service['old_manifest_sha256']) if rollback else service
                svc.wait_running(wanted);guard.loaded_environment_check(service)
            state['homepage_gets']=svc.wait_homepage()
            validate(packet,installed=not rollback,restored=rollback)
            state['status']='RESTORED_EXACT_PREVIOUS_API_MAIN_POLICY' if rollback else 'ACTIVATED_API_MAIN_POLICY_NATURAL_PENDING'
        except BaseException as error:
            state.update(status='FAILED',error=type(error).__name__+':'+str(error))
            if state['stopped']:
                try:
                    state['recovery']=svc.restore_services(recovery_services,recovery_backup,state['stopped'])
                    validate(packet,installed=rollback,restored=not rollback)
                    for role in state['stopped']:guard.loaded_environment_check(services[role])
                except BaseException as recovery:
                    state['recovery']=dict(status='CANNOT_CONFIRM_REQUIRES_CONTROLLER',error=str(recovery))
            raise
        finally:
            receipt=packet_path.parent/('ROLLBACK_RECEIPT.json' if rollback else 'ACTIVATION_RECEIPT.json')
            receipt.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['prepare','validate','activate','rollback'])
    for name in ('delta','output','baseline','tools-root','packet','review'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--installed',action='store_true')
    args=parser.parse_args()
    if args.operation=='prepare':
        result=prepare(delta_path=args.delta,output=args.output,baseline_path=args.baseline,tools_root=args.tools_root)
        result={k:result[k] for k in ('status','activation_status','root')}
    elif args.operation=='validate':
        packet=json.loads(args.packet.read_text());result=validate(packet,installed=args.installed);verify_contents(packet)
    else:result=cutover(args.packet,args.review,rollback=args.operation=='rollback')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
