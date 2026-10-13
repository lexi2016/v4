"""Manager-only V7 on freshly verified active API and scheduler; no publication."""
from pathlib import Path
import difflib,hashlib,json,plistlib,shutil,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3];sys.path.insert(0,str(ROOT))
from ops.api_release_integration import (read_active_release,build_integrated_app,_base_binding,_diff_proof,
    DELTA_SCHEMA_VERSION,inventory_tree,inventory_digest,shared_api_release_lock)
from prepare_manager_deltas import api_patch,scheduler_patch
sha=lambda raw:hashlib.sha256(raw).hexdigest()
API=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
SCHEDULER=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist')


def build():
    with shared_api_release_lock(API):
        active=read_active_release(API)
        sd=plistlib.loads(SCHEDULER.read_bytes());env=sd['EnvironmentVariables'];sroot=Path(env['V35_APP_ROOT'])
        manifest=Path(env['V35_RELEASE_MANIFEST_PATH'])
        if sha(manifest.read_bytes())!=env['V35_RELEASE_MANIFEST_SHA256']:raise ValueError('SCHEDULER_MANIFEST_DRIFT')
        sinventory=inventory_tree(sroot)
        base=dict(api=_base_binding(active),api_plist_sha256=sha(API.read_bytes()),scheduler=dict(app_root=str(sroot),
            plist_sha256=sha(SCHEDULER.read_bytes()),manifest_path=str(manifest),manifest_sha256=sha(manifest.read_bytes()),inventory=sinventory))
        paths={}
        for path in (ROOT/'v4/manager_workbench').rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and (path.suffix=='.py' or '_vendor' in path.parts):
                paths[path.relative_to(ROOT).as_posix()]=path.read_bytes()
        for rel in ['contracts/us_equity_calendar.py','contracts/us_equity_calendar_2026.json','apps/web/src/manager-selection/main.ts','apps/web/manager-selection/index.html']:
            paths[rel]=(ROOT/rel).read_bytes()
        for p in (ROOT/'apps/web/src/manager-workbench').rglob('*'):
            if p.is_file() and '__tests__' not in p.parts and p.suffix in {'.ts','.vue','.css'}:paths[p.relative_to(ROOT).as_posix()]=p.read_bytes()
        # Frozen frontend dependency closure, verified individually against V6 delta.
        old=json.loads((HERE/'api-integration-delta-v6-receipt.json').read_text())
        assets=[]
        for entry in old['entries']:
            rel=entry['path']
            if rel.startswith('apps/web/dist/'):
                raw=(HERE/'isolated-api-candidate-v6/app'/rel).read_bytes()
                if sha(raw)!=entry['after_sha256']:raise ValueError('FROZEN_FRONTEND_ASSET_DRIFT')
                paths[rel]=raw;assets.append(dict(path=rel,sha256=sha(raw)))
        rel='apps/api/v35_api/app.py';paths[rel]=api_patch((Path(active['app_root'])/rel).read_text()).encode()
        source=HERE/'api-delta-source-v7-final';source.mkdir(exist_ok=False);entries=[]
        for rel,raw in sorted(paths.items()):
            p=source/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            original=Path(active['app_root'])/rel;before=original.read_bytes() if original.exists() else None
            if before==raw:continue
            diff,hunks=_diff_proof(before,raw) if before is not None else (None,None)
            entries.append(dict(path=rel,before_sha256=sha(before) if before is not None else None,after_sha256=sha(raw),unified_diff_sha256=diff,unified_diff_hunk_count=hunks))
        delta=HERE/'api-integration-delta-v7-receipt.json';delta.write_text(json.dumps(dict(schema_version=DELTA_SCHEMA_VERSION,base=_base_binding(active),entries=entries),indent=2)+'\n')
        candidate=HERE/'isolated-api-candidate-v7-final';candidate.mkdir(exist_ok=False)
        result=build_integrated_app(active_api_plist_path=API,source_root=source,candidate_root=candidate,delta_receipt_path=delta,
            explicit_untracked_paths=[e['path'] for e in entries if e['before_sha256'] is None])
        # Scheduler uses its actual R8 base, never the canonical whole file.
        scandidate=HERE/'isolated-scheduler-candidate-v7-final/app';shutil.copytree(sroot,scandidate,symlinks=True)
        scheduler_paths={r:v for r,v in paths.items() if r.startswith('v4/manager_workbench/') or r.startswith('contracts/us_equity_calendar')}
        srel='ops/run_v35_macos_scheduler_daemon.py';scheduler_paths[srel]=scheduler_patch((sroot/srel).read_text()).encode()
        sentries=[]
        for rel,raw in sorted(scheduler_paths.items()):
            oldpath=sroot/rel;before=oldpath.read_bytes() if oldpath.exists() else None
            if before==raw:continue
            target=scandidate/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
            sentries.append(dict(path=rel,before_sha256=sha(before) if before is not None else None,after_sha256=sha(raw)))
        changed={e['path'] for e in sentries};after={e['path']:e for e in inventory_tree(scandidate)}
        if any(after.get(e['path'])!=e for e in sinventory if e['path'] not in changed):raise ValueError('SCHEDULER_NON_MANAGER_DRIFT')
        if inventory_tree(sroot)!=sinventory or sha(SCHEDULER.read_bytes())!=base['scheduler']['plist_sha256']:raise ValueError('SCHEDULER_ACTIVE_DRIFT_DURING_BUILD')
        if read_active_release(API)['application_inventory_sha256']!=active['application_inventory_sha256']:raise ValueError('API_ACTIVE_DRIFT_DURING_BUILD')
        # Canonical synchronization is a separate, exact-path delta; prepare only.
        canonical=Path('/Users/lexi/Desktop/学习/v4_app');sync=[]
        for rel in ['apps/api/v35_api/app.py','ops/run_v35_macos_scheduler_daemon.py']:
            original=(canonical/rel).read_bytes();patch=api_patch if rel.endswith('app.py') else scheduler_patch
            raw=patch(original.decode()).encode();p=HERE/'canonical-candidate-v7'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            sync.append(dict(path=rel,before_sha256=sha(original),after_sha256=sha(raw)))
        for rel,raw in paths.items():
            if rel=='apps/api/v35_api/app.py' or rel.startswith('apps/web/dist/'):continue
            original=canonical/rel;sync.append(dict(path=rel,before_sha256=sha(original.read_bytes()) if original.exists() else None,after_sha256=sha(raw),source=str(source/rel)))
        receipt=dict(status='PREPARED_NOT_DEPLOYED',base=base,api_build=result,api_delta_entries=entries,
            scheduler_delta_entries=sentries,scheduler_non_delta_preserved=len(sinventory)-sum(e['path'] in {x['path'] for x in sinventory} for e in sentries),
            candidate_api=str(candidate/'app'),candidate_scheduler=str(scandidate),frontend_assets_reused=assets,canonical_sync=sync,
            formal_state_changed=False,services_started=False,network_calls=0,model_calls=0)
        for role,app,identity in [('api',candidate/'app',result),('scheduler',scandidate,{'base':base['scheduler'],'delta_entries':sentries})]:
            release=app.parent;items=inventory_tree(app)
            value=dict(schema_version='v4.release_candidate.v1',candidate_status='PREPARED',deployment_status='NOT_DEPLOYED',
                candidate=dict(root=str(release),app_root=str(app),release_id='manager-workbench-20261013-v7-'+role,module_role='gateway' if role=='api' else 'scheduler',module_contract_sha256=None),
                application_inventory=dict(entries=items,aggregate_sha256=inventory_digest(items),entry_count=len(items)),
                verification_gaps=['Real chain/API/UI and formal cutover not run by Writer'])
            value['api_integration' if role=='api' else 'scheduler_integration']=identity
            (release/'release-manifest.json').write_text(json.dumps(value,indent=2)+'\n')
        receipt['api_manifest_sha256']=sha((candidate/'release-manifest.json').read_bytes())
        receipt['scheduler_manifest_sha256']=sha((scandidate.parent/'release-manifest.json').read_bytes())
        (HERE/'isolated-candidate-build-v7-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        print(json.dumps(dict(candidate_api=receipt['candidate_api'],candidate_scheduler=receipt['candidate_scheduler'],api_deltas=len(entries),scheduler_deltas=len(sentries),assets_reused=len(assets))))

if __name__=='__main__':build()
