from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import plistlib
import shutil
from types import SimpleNamespace
import pytest
from ops import prepare_v192_partial_release as release


def fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    approved=tmp_path/'Library/Application Support/com.lexi.v4.local/candidates';approved.mkdir(parents=True)
    root=tmp_path/'old';root.mkdir();services={};protected=tmp_path/'protected';protected.write_text('same')
    static=root/'research-panel';static.mkdir()
    files=[]
    for relative in release.STATIC_PATHS:
        path=static/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('before')
        files.append(release.record(path)|{'path':relative})
    assets=root/'assets.json';assets.write_text(json.dumps(dict(schema_version='research_panel.assets.v1',source_only=True,files=files)))
    pins=root/'pins.json';policy=root/'policy.json'
    for role,label in [('api','com.lexi.v4.api'),('main','com.lexi.v4.scheduler'),('stage','com.lexi.stage-center.scheduler')]:
        app=root/role/'app';app.mkdir(parents=True)
        for relative in release.API_PATHS:
            path=app/relative;path.parent.mkdir(exist_ok=True);path.write_text('before')
        manifest=app.parent/'release-manifest.json';manifest.write_text('{}')
        env=dict(V4_APP_ROOT=str(app),V4_RELEASE_ID=role,V4_RELEASE_MANIFEST_PATH=str(manifest),V4_RELEASE_MANIFEST_SHA256=release.sha(manifest),
            V4_RESEARCH_PANEL_ROOT=str(static),V4_RESEARCH_PANEL_ASSET_MANIFEST=str(assets),KEEP_SOURCE='exact-source-lineage')
        plist=root/(role+'.plist');payload=dict(Label=label,WorkingDirectory=str(app),EnvironmentVariables=env,ProgramArguments=['/python','-m','api'])
        plist.write_bytes(plistlib.dumps(payload))
        services[role]=dict(path=str(plist),sha256=release.sha(plist),app_root=str(app),release=role,manifest=str(manifest),manifest_sha=release.sha(manifest))
    pins.write_text(json.dumps(dict(source_bindings=[release.record(services['api']['path']),release.record(protected)])))
    policy.write_text(json.dumps(dict(managed_pin_inventory=release.record(pins))))
    main=Path(services['main']['path']);payload=plistlib.loads(main.read_bytes());payload['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(policy),V4_RESEARCH_RETENTION_POLICY_SHA256=release.sha(policy));main.write_bytes(plistlib.dumps(payload));services['main']['sha256']=release.sha(main)
    baseline=tmp_path/'baseline.json';baseline.write_text(json.dumps(dict(services=services)))
    entries=[]
    for scope,paths in [('api',release.API_PATHS),('research_panel',release.STATIC_PATHS)]:
        for relative in paths:
            source=tmp_path/'source'/scope/relative;source.parent.mkdir(parents=True,exist_ok=True);source.write_text('after')
            before=(Path(services['api']['app_root']) if scope=='api' else static)/relative
            entries.append(dict(scope=scope,target=relative,source=str(source),before_sha256=release.sha(before),after_sha256=release.sha(source)))
    delta=tmp_path/'delta.json';delta.write_text(json.dumps(dict(entries=entries,source_root='/source',baseline_commit='baseline')))
    # Existing helper behavior is outside this wrapper's unit scope; the actual
    # pinned helpers are exercised when preparing the real inactive packet.
    def overlay(root,item):
        target=root/item['target']
        if release.sha(target)!=item['before_sha256'] or release.sha(item['source'])!=item['after_sha256']:raise ValueError('DELTA_DRIFT')
        target.write_bytes(Path(item['source']).read_bytes())
    @contextmanager
    def tools(root):
        yield SimpleNamespace(clone_release=lambda app,target,manifest:shutil.copytree(app,target),seal_manifest=lambda manifest,**kw:dict(app_root=str(kw['app']),release_id=kw['release_id'])),SimpleNamespace(overlay=overlay)
    monkeypatch.setattr(release,'release_tools',tools)
    @contextmanager
    def servicetools(root):yield None,SimpleNamespace(assert_main_policy_only=lambda *a:None)
    monkeypatch.setattr(release,'service_tools',servicetools)
    monkeypatch.setattr(release,'verify_contents',lambda p:None)
    toolsroot=tmp_path/'tools'
    for name in ('prepare_daily_materials_release.py','prepare_v192_group_release.py','api_release_integration.py','prepare_top200_scope_release.py','activate_daily_materials_release.py'):
        path=toolsroot/'ops'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('# existing helper')
    return dict(delta_path=delta,output=approved/'candidate',baseline_path=baseline,tools_root=toolsroot),services,pins,policy


def test_prepare_exact_api_assets_migrates_one_pin_and_main_two_refs(tmp_path,monkeypatch):
    args,services,pins,policy=fixture(tmp_path,monkeypatch)
    before={p:p.read_bytes() for p in [pins,policy,*[Path(s['path']) for s in services.values()]]}
    result=release.prepare(**args)
    assert result['status']=='PREPARED_NOT_ACTIVATED' and result['activation_status']=='AWAITING_INDEPENDENT_REVIEW'
    assert result['launchctl_called'] is False and result['main_app_and_stage_unchanged']
    assert result['managed_pin_changes']==1 and result['main_policy_environment_changes']==2
    assert release.validate(result)['status'].startswith('PASS')
    assert all(p.read_bytes()==raw for p,raw in before.items())
    api=result['api'];draft=plistlib.loads(Path(api['draft_plist']).read_bytes());old=plistlib.loads(Path(services['api']['path']).read_bytes())
    assert draft['ProgramArguments']==old['ProgramArguments']
    assert draft['EnvironmentVariables']['KEEP_SOURCE']=='exact-source-lineage'
    assert Path(api['rollback_backup']['path']).read_bytes()==before[Path(services['api']['path'])]
    assert all((Path(api['app_root'])/p).read_text()=='after' for p in release.API_PATHS)
    with pytest.raises(ValueError,match='NEW_LIBRARY_CANDIDATE'):release.prepare(**args)


@pytest.mark.parametrize('change',['scope','live','source','pins'])
def test_prepare_refuses_unapproved_scope_or_changed_binding(tmp_path,monkeypatch,change):
    args,services,pins,policy=fixture(tmp_path,monkeypatch)
    if change in {'scope','source'}:
        data=json.loads(args['delta_path'].read_text())
        if change=='scope':data['entries'][0]['scope']='main'
        else:Path(data['entries'][0]['source']).write_text('drift')
        args['delta_path'].write_text(json.dumps(data))
    elif change=='live':Path(services['api']['path']).write_text('drift')
    else:pins.write_text('{}')
    with pytest.raises(ValueError):release.prepare(**args)
    assert release.sha(services['api']['path'])==services['api']['sha256'] or change=='live'


@pytest.mark.parametrize('failure',[None,'main_busy','main_cas'])
def test_api_main_policy_transaction_reuses_guards_and_restores_both(tmp_path,monkeypatch,failure):
    args,services,pins,policy=fixture(tmp_path,monkeypatch)
    packet=release.prepare(**args);packet_path=args['output']/'PREPARED_PACKET.json'
    review=tmp_path/'review.json';review.write_text(json.dumps(dict(verdict='PASS',packet_sha256=release.sha(packet_path))))
    lanes=Path(packet['scheduler_lane_lock_root']);lanes.mkdir(parents=True)
    events=[];running={r:True for r in ('api','main')}
    roles={packet[r]['label']:r for r in ('api','main')}
    def loaded(label):
        role=roles[label];payload=plistlib.loads(Path(packet[role]['live_plist']).read_bytes());env=payload['EnvironmentVariables']
        return SimpleNamespace(returncode=0 if running[role] else 1,stdout='state = running '+env['V4_APP_ROOT']+' '+env['V4_RELEASE_MANIFEST_SHA256']),100 if running[role] else None
    def run(command):
        if command[1]=='bootout':
            role=roles[command[-1].split('/')[-1]];running[role]=False
        else:
            role=next(r for r in ('api','main') if packet[r]['live_plist']==command[-1]);running[role]=True
        events.append((command[1],role))
        return SimpleNamespace(check_returncode=lambda:None)
    def replace(target,source,before):
        events.append(('cas',target.name))
        assert release.sha(target)==before
        if failure=='main_cas' and str(target)==packet['main']['live_plist'] and Path(source).name=='MAIN_POLICY_CANDIDATE.plist':raise RuntimeError('injected_main_cas_failure')
        target.write_bytes(Path(source).read_bytes())
    def restore(controlled,backup,stopped):
        events.append(('restore',tuple(stopped)))
        for role in stopped:
            assert release.sha(controlled[role]['live_plist']) in {controlled[role]['before_sha256'],controlled[role]['draft_plist_sha256']}
            Path(controlled[role]['live_plist']).write_bytes((backup/(role+'.plist')).read_bytes());running[role]=True
        return {'status':'RESTORED_EXACT_PREVIOUS_TUPLE'}
    def idle(service):
        events.append(('idle','main'))
        if failure=='main_busy':raise RuntimeError('MAIN_NOT_IDLE_OR_ACTIVE_CHILDREN_NO_CUTOVER')
    svc=SimpleNamespace(require_idle_main=idle,loaded=loaded,descendants=lambda pid:[pid],run=run,
        wait_drained=lambda label,pids,**kw:events.append(('drained',roles[label])),replace_cas=replace,
        wait_running=lambda service:events.append(('running',service['label'])),wait_homepage=lambda:[],
        restore_services=restore,require_previous_backups=lambda *a:None)
    guard=SimpleNamespace(loaded_environment_check=lambda s:events.append(('loaded',s['label'])))
    @contextmanager
    def service_tools(root):yield svc,guard
    monkeypatch.setattr(release,'service_tools',service_tools)
    @contextmanager
    def lock(path):events.append(('api-lock',path));yield
    monkeypatch.setattr(release,'api_lock',lock)
    before={r:Path(packet[r]['live_plist']).read_bytes() for r in ('api','main')}
    stage_before=Path(services['stage']['path']).read_bytes()
    if failure:
        with pytest.raises(RuntimeError):release.cutover(packet_path,review)
        assert all(Path(packet[r]['live_plist']).read_bytes()==before[r] for r in before)
        if failure=='main_busy':assert not any(e[0]=='bootout' for e in events)
        else:assert ('restore',('main','api')) in events
    else:
        assert release.cutover(packet_path,review)['status']=='ACTIVATED_API_MAIN_POLICY_NATURAL_PENDING'
        assert release.validate(packet,installed=True)['mode']=='INSTALLED'
        assert release.cutover(packet_path,review,rollback=True)['status']=='RESTORED_EXACT_PREVIOUS_API_MAIN_POLICY'
        assert all(Path(packet[r]['live_plist']).read_bytes()==before[r] for r in before)
        first_cas=next(i for i,e in enumerate(events) if e[0]=='cas')
        assert {e[1] for e in events[:first_cas] if e[0]=='drained'}=={'api','main'}
    assert Path(services['stage']['path']).read_bytes()==stage_before
    assert not any('stage' in str(e) for e in events)


def test_cutover_rejects_unbound_review_before_service_control(tmp_path,monkeypatch):
    args,*_=fixture(tmp_path,monkeypatch);release.prepare(**args)
    review=tmp_path/'review.json';review.write_text(json.dumps(dict(verdict='PASS',packet_sha256='wrong')))
    with pytest.raises(ValueError,match='INDEPENDENT_REVIEW_PACKET_BINDING_REQUIRED'):
        release.cutover(args['output']/'PREPARED_PACKET.json',review)


@pytest.mark.parametrize('failure',['api_bootout','main_cas','main_cas_after_write','api_bootstrap','main_bootstrap'])
def test_explicit_rollback_failure_recovers_exact_installed_tuple(tmp_path,monkeypatch,failure):
    """Exercise the real existing restore/CAS guards against temporary plists."""
    import importlib.util
    tool=Path('/Users/lexi/.codex/worktrees/a925-main-consumer-release-20261110/ops/activate_daily_materials_release.py')
    spec=importlib.util.spec_from_file_location('v192_test_existing_service_guards',tool)
    svc=importlib.util.module_from_spec(spec);spec.loader.exec_module(svc)
    args,_,pins,policy=fixture(tmp_path,monkeypatch)
    packet=release.prepare(**args);packet_path=args['output']/'PREPARED_PACKET.json'
    review=tmp_path/'review.json';review.write_text(json.dumps(dict(verdict='PASS',packet_sha256=release.sha(packet_path))))
    Path(packet['scheduler_lane_lock_root']).mkdir(parents=True)
    roles={packet[r]['label']:r for r in ('api','main')};running={r:True for r in roles.values()}
    loaded_env={r:plistlib.loads(Path(packet[r]['live_plist']).read_bytes())['EnvironmentVariables'] for r in roles.values()}
    armed=False;failed=False;events=[];recovery_targets=[]
    def loaded(label):
        role=roles[label];env=loaded_env[role]
        return SimpleNamespace(returncode=0 if running[role] else 1,stdout='state = running '+env['V4_APP_ROOT']+' '+env['V4_RELEASE_MANIFEST_SHA256']),100 if running[role] else None
    def run(command):
        nonlocal failed
        role=roles[command[-1].split('/')[-1]] if command[1]=='bootout' else next(r for r in roles.values() if packet[r]['live_plist']==command[-1])
        events.append((command[1],role))
        if armed and not failed and failure==role+'_'+command[1]:
            failed=True;raise RuntimeError('injected_'+failure)
        running[role]=command[1]=='bootstrap'
        if running[role]:loaded_env[role]=plistlib.loads(Path(packet[role]['live_plist']).read_bytes())['EnvironmentVariables']
        return SimpleNamespace(check_returncode=lambda:None)
    original_cas=svc.replace_cas
    def replace(target,source,before):
        nonlocal failed
        is_main=str(target)==packet['main']['live_plist']
        if armed and not failed and is_main and failure=='main_cas':
            failed=True;raise RuntimeError('injected_main_cas')
        original_cas(target,source,before)
        if armed and not failed and is_main and failure=='main_cas_after_write':
            failed=True;raise RuntimeError('injected_main_cas_after_write')
    original_restore=svc.restore_services
    def restore(controlled,backup,stopped):
        recovery_targets.append({r:dict(sha=controlled[r]['before_sha256'],root=controlled[r]['old_app_root'],manifest=controlled[r]['old_manifest_sha256']) for r in stopped})
        return original_restore(controlled,backup,stopped)
    def wait_running(service):
        current,pid=loaded(service['label'])
        assert pid and service['app_root'] in current.stdout and service['manifest_sha256'] in current.stdout
    def drained(label,pids,**kw):assert not running[roles[label]]
    def environment(service):
        role=roles[service['label']]
        assert running[role]
        assert loaded_env[role]==plistlib.loads(Path(service['live_plist']).read_bytes())['EnvironmentVariables']
    monkeypatch.setattr(svc,'loaded',loaded);monkeypatch.setattr(svc,'descendants',lambda pid:[pid] if pid else [])
    monkeypatch.setattr(svc,'run',run);monkeypatch.setattr(svc,'wait_drained',drained);monkeypatch.setattr(svc,'wait_running',wait_running)
    monkeypatch.setattr(svc,'wait_homepage',lambda:[]);monkeypatch.setattr(svc,'replace_cas',replace);monkeypatch.setattr(svc,'restore_services',restore)
    @contextmanager
    def tools(root):yield svc,SimpleNamespace(loaded_environment_check=environment)
    monkeypatch.setattr(release,'service_tools',tools)
    @contextmanager
    def lock(path):yield
    monkeypatch.setattr(release,'api_lock',lock)
    assert release.cutover(packet_path,review)['status']=='ACTIVATED_API_MAIN_POLICY_NATURAL_PENDING'
    installed={r:Path(packet[r]['live_plist']).read_bytes() for r in roles.values()}
    original_backups={r:(args['output']/'cutover-backup'/(r+'.plist')).read_bytes() for r in roles.values()}
    armed=True
    with pytest.raises(RuntimeError,match='injected_'):release.cutover(packet_path,review,rollback=True)
    assert failed
    assert all(running.values()),dict(failure=failure,running=running,events=events)
    assert all(Path(packet[r]['live_plist']).read_bytes()==installed[r] for r in roles.values())
    assert release.validate(packet,installed=True)['mode']=='INSTALLED'
    assert recovery_targets
    assert all(value['sha']==packet[role]['draft_plist_sha256'] and value['root']==packet[role]['app_root'] and value['manifest']==packet[role]['manifest_sha256'] for target in recovery_targets for role,value in target.items())
    assert all((args['output']/'cutover-backup'/(r+'.plist')).read_bytes()==original_backups[r] for r in roles.values())
    recovery_receipt=json.loads((args['output']/'ROLLBACK_RECEIPT.json').read_text())
    assert recovery_receipt['recovery']['status']=='RESTORED_EXACT_PREVIOUS_TUPLE'
    assert recovery_receipt['recovery_target']=='PRE_ROLLBACK_INSTALLED_TUPLE'
    snapshot=Path(recovery_receipt['recovery_snapshot'])
    snapshot_identity=json.loads((snapshot/'RECOVERY_TARGET.json').read_text())
    assert snapshot_identity['target']=='PRE_ROLLBACK_INSTALLED_TUPLE'
    assert all((snapshot/(r+'.plist')).read_bytes()==installed[r] and snapshot_identity['plists'][r]['sha256']==packet[r]['draft_plist_sha256'] for r in roles.values())
    proof=dict(failure=failure,recovery_target=recovery_receipt['recovery_target'],
        running_after_failure=dict(running),installed_tuple_sha={r:packet[r]['draft_plist_sha256'] for r in roles.values()},
        restored_tuple_sha={r:release.sha(packet[r]['live_plist']) for r in roles.values()},
        original_activation_backup_sha={r:release.sha(args['output']/'cutover-backup'/(r+'.plist')) for r in roles.values()},
        recovery_snapshot=snapshot_identity,real_existing_restore_guard=str(tool),
        exact_installed_tuple_restored=True,original_activation_backups_preserved=True)
    # The original activation backups still target the baseline on a later retry.
    assert release.cutover(packet_path,review,rollback=True)['status']=='RESTORED_EXACT_PREVIOUS_API_MAIN_POLICY'
    assert all(Path(packet[r]['live_plist']).read_bytes()==original_backups[r] for r in roles.values())
    proof['retry_rollback_status']='RESTORED_EXACT_PREVIOUS_API_MAIN_POLICY'
    (tmp_path/'ROLLBACK_FAILURE_PROOF.json').write_text(json.dumps(proof,indent=2)+'\n')
