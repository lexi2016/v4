"""Root-owned mechanical integration of the frozen Writer runtime overlays."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
import hashlib, json, os, plistlib, re, shutil, stat
from ops import api_release_integration as integ
R = Path.cwd(); H = R/'docs/handoffs/monthly_membership_research_fix_20261018'
B = json.loads((H/'ROOT_BASELINE_R3.json').read_text())
S = {'ALLOWED_PATHS': json.loads((H/'R3_COUNT_SCOPE.json').read_text())['allowed_paths']}
sha = lambda raw: hashlib.sha256(raw).hexdigest()
identity = {'V35_APP_ROOT','V35_RELEASE_ID','V35_RELEASE_MANIFEST_PATH','V35_RELEASE_MANIFEST_SHA256','V4_MANAGER_WORKBENCH_CONFIG_PATH','PYTHONPATH'}

def effective(pl):
    env = dict(pl['EnvironmentVariables'])
    if pl['ProgramArguments'][0] == '/usr/bin/env':
        for token in pl['ProgramArguments'][1:]:
            key, sep, value = token.partition('=')
            if sep and re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', key): env[key] = value
            else: break
    return env

def normal(pl, app):
    p = deepcopy(pl); p['WorkingDirectory'] = '<app>'
    p['EnvironmentVariables'] = {k:'<identity>' if k in identity else v for k,v in p['EnvironmentVariables'].items()}
    args = []
    for token in p['ProgramArguments']:
        key,sep,value = token.partition('=')
        if sep and key in identity: args.append(key+'=<identity>')
        elif token.startswith(str(app)+os.sep): args.append('<app>'+token[len(str(app)):])
        else: args.append(token)
    p['ProgramArguments'] = args
    return p

receipt = H/'WRITER_R3_RECEIPT.json'
assert receipt.is_file(), 'WRITER_RECEIPT_MISSING'
receipt_sha = sha(receipt.read_bytes())
reports = []
for runtime in ('api',):
    b = B['runtimes'][runtime]; live = Path(b['plist']); raw = live.read_bytes()
    assert sha(raw) == b['plist_sha256'], 'LIVE_BASE_CHANGED'
    old = plistlib.loads(raw); baseapp = Path(b['app_root']); manifest_raw = Path(b['manifest']).read_bytes()
    assert sha(manifest_raw) == b['manifest_sha256']
    prior = json.loads(manifest_raw); before_inv = integ.inventory_tree(baseapp)
    assert before_inv == prior['application_inventory']['entries']
    source = H/'local_only/runtime_overlay_r3/app'
    declared = json.loads(receipt.read_text())['runtime_overlay']['files']
    prefix = 'local_only/runtime_overlay_r3/app/'
    paths = sorted({e['path'].removeprefix(prefix) for e in declared} | {e['path'] for e in json.loads((H/'ROOT_WEB_BUILD_R3.json').read_text())['generated_files']})
    assert all(e['path'].startswith(prefix) for e in declared)
    assert paths and all(p in S['ALLOWED_PATHS'] or (runtime == 'api' and p.startswith('apps/web/dist/')) for p in paths)
    entries = []
    for rel in paths:
        before = (baseapp/rel).read_bytes() if (baseapp/rel).is_file() else None; after = (source/rel).read_bytes()
        if before == after: continue
        diff, hunks = integ._diff_proof(before,after) if before is not None else (None,None)
        entries.append(dict(path=rel,before_sha256=sha(before) if before is not None else None,after_sha256=sha(after),unified_diff_sha256=diff,unified_diff_hunk_count=hunks))
    assert entries, 'EMPTY_DELTA'
    paths = [e['path'] for e in entries]
    root = baseapp.parent.parent/('monthly-membership-'+runtime+'-20261018-r3'); root.mkdir(exist_ok=False)
    work = H/'local_only/release_build_r3'; work.mkdir(exist_ok=True)
    delta_path = work/(runtime+'-release-delta.json')
    if runtime == 'api':
        active = integ.read_active_release(live)
        delta = dict(schema_version=integ.DELTA_SCHEMA_VERSION,base=integ._base_binding(active),entries=entries)
        delta_path.write_text(json.dumps(delta,indent=2)+'\n')
        integration = integ.build_integrated_app(active_api_plist_path=live,source_root=source,candidate_root=root,delta_receipt_path=delta_path,explicit_untracked_paths=[e['path'] for e in entries if e['before_sha256'] is None])
        preserved_count = integration['non_delta_entry_count']; preserved_sha = integration['non_delta_inventory_sha256']
    else:
        shutil.copytree(baseapp,root/'app',symlinks=True,copy_function=shutil.copy2)
        assert integ.inventory_tree(root/'app') == before_inv
        for entry in entries:
            dst = root/'app'/entry['path']; mode = stat.S_IMODE(dst.stat().st_mode)
            dst.chmod(mode|stat.S_IWUSR); shutil.copyfile(source/entry['path'],dst); dst.chmod(mode)
        after_map = {e['path']:e for e in integ.inventory_tree(root/'app')}
        untouched = [e for e in before_inv if e['path'] not in paths]
        assert all(after_map[e['path']] == e for e in untouched)
        assert set(after_map) == {e['path'] for e in before_inv}
        preserved_count = len(untouched); preserved_sha = integ.inventory_digest(untouched)
        delta_path.write_text(json.dumps(entries,indent=2)+'\n')
    rows = integ.inventory_tree(root/'app'); new = deepcopy(prior)
    new['candidate'].update(root=str(root),app_root=str(root/'app'),release_id=root.name)
    if 'formal_release_root' in new['candidate']: new['candidate']['formal_release_root']=str(root)
    new.update(candidate_status='READY_FOR_INDEPENDENT_REVIEW',activation_status='NOT_ACTIVATED',deployment_status='CANNOT_CONFIRM',generated_at=datetime.now(timezone.utc).isoformat())
    new['application_inventory'] = dict(entry_count=len(rows),aggregate_sha256=integ.inventory_digest(rows),entries=rows)
    if runtime == 'api': new['api_integration'] = integration
    else: new.update(role='scheduler',base=dict(app_root=str(baseapp),plist_sha256=sha(raw),manifest_sha256=sha(manifest_raw)),delta_entries=entries,non_delta_entry_count=preserved_count,non_delta_inventory_sha256=preserved_sha,source_workspace_full_tree_copied=False)
    new['monthly_membership_research_fix'] = dict(writer_receipt_sha256=receipt_sha,source_policy='MONTHLY_OBSERVED_RESEARCH',formal_target_eligibility='NOT_PROMOTED',historical_pit_verified=False,RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    mr = (json.dumps(new,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode(); (root/'release-manifest.json').write_bytes(mr)
    if runtime == 'api': integ.verify_api_release_candidate(candidate_root=root,active_api_plist_path=live,expected_manifest_sha256=sha(mr),active_pointer='base',role='gateway',base_role='gateway')
    pl = deepcopy(old); env = pl['EnvironmentVariables']; oldenv = effective(old)
    env.update(V35_APP_ROOT=str(root/'app'),V35_RELEASE_ID=root.name,V35_RELEASE_MANIFEST_PATH=str(root/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=sha(mr))
    env['PYTHONPATH'] = os.pathsep.join(str(root/'app')+x[len(str(baseapp)):] if x==str(baseapp) or x.startswith(str(baseapp)+os.sep) else x for x in oldenv['PYTHONPATH'].split(os.pathsep))
    pl['WorkingDirectory'] = str(root/'app'); args=[]
    for token in old['ProgramArguments']:
        key,sep,value = token.partition('=')
        if sep and key in identity: args.append(key+'='+env[key])
        elif token.startswith(str(baseapp)+os.sep): args.append(str(root/'app')+token[len(str(baseapp)):])
        else: args.append(token)
    pl['ProgramArguments'] = args
    assert normal(pl,root/'app') == normal(old,baseapp), 'NON_IDENTITY_PLIST_CHANGE'
    assert all(effective(pl).get(k)==env.get(k) for k in identity), 'INLINE_ENV_IDENTITY_CONFLICT'
    assert effective(pl)['V4_MANAGER_WORKBENCH_CONFIG_PATH'] == b['config']
    cfg=Path(b['config']); cfg_sha=sha(cfg.read_bytes()); pr=plistlib.dumps(pl,sort_keys=True)
    conf=root/'config'; conf.mkdir(); staged=conf/live.name; rollback=conf/('rollback-'+live.name)
    for path,data in ((staged,pr),(rollback,raw)):
        with path.open('xb') as f: f.write(data)
        path.chmod(0o600)
    assert live.read_bytes()==raw
    report=dict(status='INACTIVE_CANDIDATE_PENDING_INDEPENDENT_REVIEW',runtime=runtime,base_release_id=b['release_id'],base_app_root=str(baseapp),base_plist_sha256=sha(raw),base_manifest_sha256=sha(manifest_raw),candidate_root=str(root),candidate_app_root=str(root/'app'),candidate_manifest_sha256=sha(mr),candidate_inventory_sha256=integ.inventory_digest(rows),delta_paths=paths,delta_entries=entries,non_delta_preserved_count=preserved_count,non_delta_inventory_sha256=preserved_sha,staged_plist_path=str(staged),staged_plist_sha256=sha(pr),rollback_plist_path=str(rollback),rollback_plist_sha256=sha(raw),live_plist=str(live),new_config_path=str(cfg),new_config_sha256=cfg_sha,config_changed=False,schedule_preserved=True,effective_identity_checked_keys=sorted(identity),effective_child_identity_matches_declared=True,writer_receipt_sha256=receipt_sha,manager_state_root='/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench',activated=False)
    (H/('ROOT_'+runtime.upper()+'_RELEASE_BUILD_R3.json')).write_text(json.dumps(report,indent=2)+'\n')
    reports.append({k:report[k] for k in ('runtime','candidate_root','candidate_manifest_sha256','delta_paths','non_delta_preserved_count')})
print(json.dumps(reports))
