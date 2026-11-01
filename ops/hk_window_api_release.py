"""Prepare a reviewed HK reader delta as an API-only copy-on-write candidate.

Uses the existing single-stock API owner for the shared lock, inventory proof,
smoke, CAS switch and rollback.  Preparation and check never change the live
plist or panel pointers.  Activation remains a separate controller action.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
LOCAL = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
BASE = LOCAL / 'candidates/edan-single-20261102-b843699e8d3371ea'
TARGET = LOCAL / 'candidates/hk-window-api-20261102-7d8343f06ff9f8d6'
PLIST = Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist')
EVIDENCE = Path('/Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/kb_panel_upgrade_20261101/batch_20_market_review_20261102_r1/hk_window_repair_20261102_r1')
STAGE = EVIDENCE / 'api_cow_20261102_r1/HK_STAGED_DELTA.json'
REVIEW = EVIDENCE / 'HK_INDEPENDENT_REVIEW_R2.json'
REVIEW_SHA = '8d03d4362edec4e2de5ddb4547b0e026ad8874533d640574d82cc38efce8f13d'
EDAN_STAGE = Path('/Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/kb_panel_upgrade_20261101/libang_300206_20261102_r1/activation_stage_b843699e8d3371ea_r4/STAGED_DELTA.json')
EDAN_STAGE_SHA = '172764b3b4507fc4509134a9bf5548dd0e1b4d7cfd8616d0b0162f662334c0d9'
OWNER = Path('/Users/lexi/Desktop/学习/v4_app/.task_worktrees/edan-single-research-20261102/ops/junda_single_release.py')
OWNER_SHA = '03467259d897fe4968e1b167df6a806106f899993ddde91ef0d1d59dabc499d8'
BASE_MANIFEST_SHA = 'f10179c1b8028d088ae8e00e9de60d068550e9441a41febaa76569a5c2c2fcb1'
PLIST_SHA = '09baad3ed6870940d2747fb639a6b42df73895fcc41a3db5258b36c217ca5cd2'
BASE_APP_INVENTORY_SHA = '9cf110888d75497134643d9560ac530879e6d1bf70baa4e62fdf2a332b9a261a'
BASE_SITE_INVENTORY_SHA = 'f68fb99e3c8aeafb99422e9d381fe21283cb44cdc675eafd3fda7db8c1d43206'
ASSET_SHA = '61d25c7abf56076f5c5bc2095399185cc35361cc5fd987d6bb192397827b5d25'
BINDING_SHA = '5b0c8a84bfb2ef7efe3ba5b7f0ff286c925a933c768b9d565992ac5e41edb557'
RESOLVER = 'upstreams/v3_shared_data/shared_data/hk_history_resolution.py'
RESOLVER_SHA = 'c2b7035a74ca7ce5cb0c527393b70d87c91e348f1fb726ac4242ae7aeed6a58c'
REVIEWED_COMMIT = '7d8343f06ff9f8d6cad796d261b6cd98f0f25937'
PANEL_PYTHON = '/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python'
SOURCE_GENERATION = 'd22220537892215832f0c01faeaadd11e282b4d65debf979152597a00d1829b5'
CHANGES = {
 'domains/manager_close_rebound.py': ('b0bd01c6007ec27a865818c692bfd004f4fa96de8157f8bc493faa3f8695d4ea','a5ed16dd473b6b785399303e147b9677073195efd20aa6cfe76dded3464988c7'),
 'tests/test_hk_window_source_admission.py': (None,'86c9e3663f59d9e1cb7d1c4a91c5fce14aa2e3af9f309f4b578985fcfce758e8'),
 'upstreams/v3_shared_data/shared_data/hk_panel_audit.py': ('30314a806a665d71261521b27cf5ba7aa7a9e4c7247aa7eab9a7348127f134e2','b1038ca2848fd306b2046431f836f8b223af9f73084c10b6e1c0847e1c13ac09'),
 'v4/manager_research/workspace_plan.py': ('222f94d065debf46c5281ad36b7a5a30035ed04d3cd63b7a2ee0b399252d1cc2','1528a0abc0c69f41e589b5ee0c7205c60deaec8536119fda515171846f0e07d1'),
 'v4/manager_workbench/inputs/native.py': ('4bf9df959c4ac30fae7b3ab115a282c737694f032e410bf3350112196007c469','b53973ea088b8a9af71a0653802ea0bb4049f59149e42f0151364d29dd2bba30'),
}
F10_RECEIPT_SHA = 'ee5798e100adc661148c924f345d906166b4123802f9ce12836efa1e3dbaaf39'
F10_STOCK_SHA = {'002865.SZ':'73bf15ad08641205941017ced833849b93f842ab65aa93eb2d22377a15969bb4',
                 '301048.SZ':'817fd3fb1266cb45224bfbaf785d668c466754583aa802c78b0a770165fece36',
                 '300206.SZ':'dd187d4bba2747c3a452692d772a8b9c8c6da37e8671a03d0d8be416c6e14089'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked(path, expected):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != expected:
        raise ValueError('PIN_CHANGED:' + str(path))
    return path


def reference(path, digest):
    checked(path, digest)
    return {'path': str(path), 'sha256': digest}


def load_owner():
    checked(OWNER, OWNER_SHA)
    spec = importlib.util.spec_from_file_location('hk_frozen_single_api_owner', OWNER)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    owner.BASE, owner.TARGET = BASE, TARGET
    owner.PLIST_SHA, owner.BASE_MANIFEST_SHA, owner.BASE_PID = PLIST_SHA, BASE_MANIFEST_SHA, 49683
    owner.STAGE, owner.STAGE_SHA = STAGE, None
    owner.RECEIPT = TARGET / 'preparation.json'
    owner.ACTIVE_RECEIPT = TARGET / 'activation.json'
    owner.STAGED_PLIST = TARGET / 'hk-staged-api.plist'
    owner.BACKUP = TARGET / 'hk-before-api.plist'
    owner.ATTEMPT = TARGET / 'activation-attempt.json'
    return owner


def changes():
    return [{'kind':'api','path':p,'before_sha256':before,
             'after':{'path':str(REPO / p),'sha256':after}}
            for p,(before,after) in sorted(CHANGES.items())]


def verify_sources():
    checked(REVIEW, REVIEW_SHA)
    checked(EDAN_STAGE, EDAN_STAGE_SHA)
    for path, (before, after) in CHANGES.items():
        checked(REPO / path, after)
        raw = subprocess.check_output(['/usr/bin/git','show',REVIEWED_COMMIT + ':' + path], cwd=REPO, timeout=10)
        if sha(raw) != after:
            raise ValueError('REVIEWED_COMMIT_BYTES_CHANGED:' + path)
        base = BASE / 'app' / path
        if before is None:
            if base.exists() or base.is_symlink():
                raise ValueError('BASE_ADDITION_ALREADY_EXISTS:' + path)
        else:
            checked(base, before)
    checked(BASE / 'app' / RESOLVER, RESOLVER_SHA)


def verify_base(owner, *, plist=True):
    checked(BASE / 'release-manifest.json', BASE_MANIFEST_SHA)
    if plist:
        checked(PLIST, PLIST_SHA)
    checked(BASE / 'research-panel-assets.json', ASSET_SHA)
    checked(BASE / 'config/workbench-binding.json', BINDING_SHA)
    verify_sources()
    for path,digest in owner.POINTERS.items():
        checked(path,digest)
    tools = owner.official_tools()
    manifest = json.loads((BASE / 'release-manifest.json').read_text())
    app = tools.inventory_tree(BASE / 'app')
    rec = manifest['application_inventory']
    if (rec['entries'] != app or manifest['app_files'] != app or rec['entry_count'] != len(app)
        or rec['aggregate_sha256'] != tools.inventory_digest(app)
        or tools.inventory_digest(app) != BASE_APP_INVENTORY_SHA):
        raise ValueError('BASE_APP_INVENTORY_CHANGED')
    site = tools.inventory_tree(BASE / 'research-panel')
    if tools.inventory_digest(site) != BASE_SITE_INVENTORY_SHA:
        raise ValueError('BASE_SITE_INVENTORY_CHANGED')
    if manifest['candidate'] != {'root':str(BASE),'app_root':str(BASE/'app'),'release_id':BASE.name,'module_role':'api'}:
        raise ValueError('BASE_MANIFEST_IDENTITY_CHANGED')
    return tools, manifest, app, site


def f10(owner, port):
    found = {}
    for symbol, stock_sha in F10_STOCK_SHA.items():
        route = '/api/v4/research/workbench/days/2026-10-30/f10/' + symbol + '?revision=' + SOURCE_GENERATION
        raw = owner.fetch(port,route)
        item = json.loads(raw)
        if (item.get('status') != 'OBSERVED' or item.get('receipt',{}).get('sha256') != F10_RECEIPT_SHA
            or item.get('stock_ref',{}).get('sha256') != stock_sha):
            raise ValueError('F10_IDENTITY_CHANGED:' + symbol)
        found[symbol] = {'response_sha256':sha(raw),'receipt_sha256':F10_RECEIPT_SHA,'stock_sha256':stock_sha}
    return found


def install_http(owner, expected=None):
    original = owner.verify_http
    def verify(port, *, release_id, manifest_sha, single):
        result = original(port, release_id=release_id, manifest_sha=manifest_sha, single=True)
        result['canonical_f10'] = f10(owner,port)
        if expected is not None and result != expected:
            raise ValueError('LIVE_CONTENT_CHANGED_FROM_FROZEN_BASELINE')
        return result
    owner.verify_http = verify


def freeze(owner):
    if os.path.realpath(sys.executable) != os.path.realpath(PANEL_PYTHON):
        raise ValueError('PANEL_PYTHON_REQUIRED')
    with owner.release_lock():
        tools,_,app,site = verify_base(owner)
        process = owner.live_process()
        if process['pid'] != 49683:
            raise ValueError('BASE_PID_CHANGED')
        owner.assert_live_root(process['pid'],str(BASE/'app'))
        env = plistlib.loads(checked(PLIST,PLIST_SHA).read_bytes())['EnvironmentVariables']
        if (env.get('V4_APP_ROOT') != str(BASE/'app') or env.get('V4_RELEASE_ID') != BASE.name
            or env.get('V4_RELEASE_MANIFEST_PATH') != str(BASE/'release-manifest.json')
            or env.get('V4_RELEASE_MANIFEST_SHA256') != BASE_MANIFEST_SHA
            or env.get('V4_RESEARCH_PANEL_ROOT') != str(BASE/'research-panel')
            or env.get('V4_RESEARCH_PANEL_ASSET_MANIFEST') != str(BASE/'research-panel-assets.json')
            or env.get('V4_WORKBENCH_HOST_BINDING') != str(BASE/'config/workbench-binding.json')
            or env.get('V4_WORKBENCH_HOST_BINDING_SHA256') != BINDING_SHA):
            raise ValueError('BASE_PLIST_IDENTITY_CHANGED')
        owner.STAGE,owner.STAGE_SHA=EDAN_STAGE,EDAN_STAGE_SHA
        install_http(owner)
        baseline = owner.verify_http(8873,release_id=BASE.name,manifest_sha=BASE_MANIFEST_SHA,single=True)
        if owner.live_process()!=process:
            raise ValueError('BASE_PROCESS_CHANGED_DURING_FREEZE')
        stage={'schema':'v4.hk_window_api.stage.v1','status':'FROZEN_FOR_PREPARATION',
          'source_commit':REVIEWED_COMMIT,'review':reference(REVIEW,REVIEW_SHA),
          'operator_sha256':sha(Path(__file__).read_bytes()),'owner':reference(OWNER,OWNER_SHA),
          'base':{'root':str(BASE),'process':process,'plist_sha256':PLIST_SHA,'manifest_sha256':BASE_MANIFEST_SHA,
                  'app_inventory_sha256':tools.inventory_digest(app),'site_inventory_sha256':tools.inventory_digest(site)},
          'target':str(TARGET),'changes':changes(),'old_stage':reference(EDAN_STAGE,EDAN_STAGE_SHA),
          'stocks':json.loads(EDAN_STAGE.read_text())['stocks'],
          'new_binding':reference(BASE/'config/workbench-binding.json',BINDING_SHA),
          'asset_manifest':reference(BASE/'research-panel-assets.json',ASSET_SHA),
          'resolver_sha256':RESOLVER_SHA,'base_live':baseline,
          'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
        owner.json_write(STAGE,stage)
        print(json.dumps({'stage':str(STAGE),'sha256':sha(STAGE.read_bytes()),'base_live':baseline},ensure_ascii=False))


def load_stage(stage_sha):
    stage=json.loads(checked(STAGE,stage_sha).read_text())
    if (stage.get('schema')!='v4.hk_window_api.stage.v1' or stage.get('target')!=str(TARGET)
        or stage.get('source_commit')!=REVIEWED_COMMIT or stage.get('operator_sha256')!=sha(Path(__file__).read_bytes())
        or stage.get('changes')!=changes() or stage.get('review')!=reference(REVIEW,REVIEW_SHA)
        or stage.get('owner')!=reference(OWNER,OWNER_SHA) or stage.get('old_stage')!=reference(EDAN_STAGE,EDAN_STAGE_SHA)
        or stage.get('stocks')!=json.loads(EDAN_STAGE.read_text())['stocks']
        or stage.get('new_binding')!=reference(BASE/'config/workbench-binding.json',BINDING_SHA)
        or stage.get('asset_manifest')!=reference(BASE/'research-panel-assets.json',ASSET_SHA)
        or stage.get('resolver_sha256')!=RESOLVER_SHA
        or stage.get('base',{}).get('root')!=str(BASE) or stage['base'].get('plist_sha256')!=PLIST_SHA
        or stage['base'].get('manifest_sha256')!=BASE_MANIFEST_SHA
        or stage['base'].get('app_inventory_sha256')!=BASE_APP_INVENTORY_SHA
        or stage['base'].get('site_inventory_sha256')!=BASE_SITE_INVENTORY_SHA
        or stage['base'].get('process',{}).get('pid')!=49683
        or stage.get('RESEARCH_ONLY') is not True or any(stage.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))):
        raise ValueError('STAGE_IDENTITY_CHANGED')
    verify_sources()
    return stage


def candidate_manifest(base, inventory, proof, delta_sha, stage_sha, tools):
    result=copy.deepcopy(base)
    result.update(release_id=TARGET.name,app_root=str(TARGET/'app'),
                  candidate={'root':str(TARGET),'app_root':str(TARGET/'app'),'release_id':TARGET.name,'module_role':'api'},
                  activation_status='NOT_ACTIVATED',deployment_status='CANNOT_CONFIRM')
    result['application_inventory']={'entries':inventory,'entry_count':len(inventory),'aggregate_sha256':tools.inventory_digest(inventory)}
    result['app_files']=inventory
    result['research_panel'].update(root=str(TARGET/'research-panel'),asset_manifest=str(TARGET/'research-panel-assets.json'))
    result['hk_window_integration']={'schema':'v4.hk_window_api.integration.v1','base_manifest_sha256':BASE_MANIFEST_SHA,
       'stage_sha256':stage_sha,'review_sha256':REVIEW_SHA,'reviewed_commit':REVIEWED_COMMIT,
       'operator_sha256':sha(Path(__file__).read_bytes()),'owner_sha256':OWNER_SHA,'delta_sha256':delta_sha,
       'resolver_sha256':RESOLVER_SHA,'proof':proof,'base_site_inventory_sha256':BASE_SITE_INVENTORY_SHA}
    return result


def verify_candidate(owner,stage,receipt,stage_sha,*,require_base_plist):
    tools,base,_,site = verify_base(owner,plist=require_base_plist)
    delta=json.loads(checked(TARGET/'reviewed-delta.json',receipt['delta_sha256']).read_text())
    expected=owner.delta_records(stage,{'api':BASE/'app','site':BASE/'research-panel'},tools)
    if delta!=expected:
        raise ValueError('DELTA_CHANGED')
    proof={}
    for kind,source,dest in [('api',BASE/'app',TARGET/'app'),('site',BASE/'research-panel',TARGET/'research-panel')]:
        records,preserved=tools._verify_delta_files(base_app=source,candidate_app=dest,entries=delta[kind])
        proof[kind]={'records':records,'non_delta_count':len(preserved),'non_delta_sha256':tools.inventory_digest(preserved)}
    if proof!=receipt['proof']:
        raise ValueError('NON_DELTA_PROOF_CHANGED')
    if tools.inventory_tree(BASE/'config') != tools.inventory_tree(TARGET/'config'):
        raise ValueError('CONFIG_COPY_CHANGED')
    checked(TARGET/'research-panel-assets.json',ASSET_SHA)
    checked(TARGET/'app'/RESOLVER,RESOLVER_SHA)
    manifest=json.loads(checked(TARGET/'release-manifest.json',receipt['manifest_sha256']).read_text())
    inventory=tools.inventory_tree(TARGET/'app')
    if manifest != candidate_manifest(base,inventory,proof,receipt['delta_sha256'],stage_sha,tools):
        raise ValueError('CANDIDATE_MANIFEST_CHANGED')
    checked(owner.BACKUP,PLIST_SHA)
    checked(owner.STAGED_PLIST,receipt['candidate_plist_sha256'])
    owner.validate_payload_delta(plistlib.loads(owner.BACKUP.read_bytes()),
        plistlib.loads(owner.STAGED_PLIST.read_bytes()),receipt['manifest_sha256'],stage)
    if receipt['operator_sha256']!=sha(Path(__file__).read_bytes()) or receipt['stage_sha256']!=stage_sha:
        raise ValueError('PREPARATION_IDENTITY_CHANGED')


def prepare(owner,stage_sha):
    if os.path.realpath(sys.executable)!=os.path.realpath(PANEL_PYTHON):
        raise ValueError('PANEL_PYTHON_REQUIRED')
    with owner.release_lock():
        stage=load_stage(stage_sha)
        tools,base,app,site=verify_base(owner)
        process=owner.live_process()
        if process!=stage['base']['process']:
            raise ValueError('BASE_PROCESS_CAS_CHANGED')
        owner.assert_live_root(process['pid'],str(BASE/'app'))
        live=owner.verify_http(8873,release_id=BASE.name,manifest_sha=BASE_MANIFEST_SHA,single=True)
        if live!=stage['base_live']:
            raise ValueError('BASE_LIVE_CONTENT_CHANGED')
        required=sum(int(x.get('size',0)) for x in app+site)
        if shutil.disk_usage(TARGET.parent).free < required*2+1024**3:
            raise ValueError('INSUFFICIENT_CANDIDATE_SPACE')
        TARGET.mkdir()
        for name in ('app','research-panel','config'):
            owner.clone_tree(BASE/name,TARGET/name)
        shutil.copyfile(BASE/'research-panel-assets.json',TARGET/'research-panel-assets.json')
        if tools.inventory_tree(TARGET/'app')!=app or tools.inventory_tree(TARGET/'research-panel')!=site:
            raise ValueError('COW_COPY_DRIFT')
        roots={'api':BASE/'app','site':BASE/'research-panel'}
        delta=owner.delta_records(stage,roots,tools)
        for item in stage['changes']:
            target=tools._safe_child(TARGET/'app',item['path'],allow_missing=True)
            owner.replace_candidate_file(target,checked(item['after']['path'],item['after']['sha256']).read_bytes())
        owner.json_write(TARGET/'reviewed-delta.json',delta)
        proof={}
        for kind,src,dest in [('api',BASE/'app',TARGET/'app'),('site',BASE/'research-panel',TARGET/'research-panel')]:
            records,preserved=tools._verify_delta_files(base_app=src,candidate_app=dest,entries=delta[kind])
            proof[kind]={'records':records,'non_delta_count':len(preserved),'non_delta_sha256':tools.inventory_digest(preserved)}
        delta_sha=sha((TARGET/'reviewed-delta.json').read_bytes())
        manifest=candidate_manifest(base,tools.inventory_tree(TARGET/'app'),proof,delta_sha,stage_sha,tools)
        owner.json_write(TARGET/'release-manifest.json',manifest)
        manifest_sha=sha((TARGET/'release-manifest.json').read_bytes())
        raw=checked(PLIST,PLIST_SHA).read_bytes()
        payload=owner.staged_payload(raw,manifest_sha,stage)
        owner.BACKUP.write_bytes(raw)
        owner.STAGED_PLIST.write_bytes(plistlib.dumps(payload))
        receipt={'schema':'v4.hk_window_api.preparation.v1','status':'PREPARED_NOT_ACTIVATED',
            'operator_sha256':sha(Path(__file__).read_bytes()),'owner_sha256':OWNER_SHA,'stage_sha256':stage_sha,
            'base_plist_sha256':PLIST_SHA,'base_process':process,'base_manifest_sha256':BASE_MANIFEST_SHA,
            'base_site_inventory_sha256':BASE_SITE_INVENTORY_SHA,'candidate_plist_sha256':sha(owner.STAGED_PLIST.read_bytes()),
            'manifest_sha256':manifest_sha,'delta_sha256':delta_sha,'proof':proof,'base_live':live}
        verify_candidate(owner,stage,receipt,stage_sha,require_base_plist=True)
        receipt['smoke']=owner.isolated_smoke(payload,manifest_sha)
        for key,value in live.items():
            if receipt['smoke'].get(key)!=value:
                raise ValueError('LIVE_AND_ISOLATED_SMOKE_DIFFER:' + key)
        if owner.live_process()!=process:
            raise ValueError('BASE_PROCESS_CHANGED_DURING_PREPARATION')
        owner.assert_live_root(process['pid'],str(BASE/'app'))
        load_stage(stage_sha)
        verify_candidate(owner,stage,receipt,stage_sha,require_base_plist=True)
        owner.json_write(owner.RECEIPT,receipt)
        print(json.dumps({'status':receipt['status'],'receipt':str(owner.RECEIPT),
                          'receipt_sha256':sha(owner.RECEIPT.read_bytes()),'smoke':receipt['smoke']},ensure_ascii=False))


def bind_owner(owner,stage_sha):
    owner.STAGE,owner.STAGE_SHA=STAGE,stage_sha
    stage=load_stage(stage_sha)
    install_http(owner,stage['base_live'])
    owner.load_stage=lambda: (load_stage(stage_sha),None,None)
    owner.verify_candidate=lambda receipt,stage,require_base_plist: verify_candidate(
        owner,stage,receipt,stage_sha,require_base_plist=require_base_plist)


def check(owner,stage_sha,receipt_sha):
    with owner.release_lock():
        stage=load_stage(stage_sha)
        receipt=json.loads(checked(owner.RECEIPT,receipt_sha).read_text())
        if receipt.get('status')!='PREPARED_NOT_ACTIVATED' or receipt.get('smoke',{}).get('status')!='PASS':
            raise ValueError('PREPARATION_NOT_VERIFIED')
        verify_candidate(owner,stage,receipt,stage_sha,require_base_plist=True)
        if owner.live_process()!=receipt['base_process']:
            raise ValueError('BASE_PROCESS_CAS_CHANGED')
        owner.assert_live_root(receipt['base_process']['pid'],str(BASE/'app'))
        live=owner.verify_http(8873,release_id=BASE.name,manifest_sha=BASE_MANIFEST_SHA,single=True)
        if live!=receipt['base_live']:
            raise ValueError('BASE_LIVE_CONTENT_CHANGED')
        if owner.live_process()!=receipt['base_process']:
            raise ValueError('BASE_PROCESS_CAS_CHANGED')
        print(json.dumps({'status':'PREPARED_PREFLIGHT_PASS','receipt':str(owner.RECEIPT),'manifest_sha256':receipt['manifest_sha256']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('freeze','prepare','check','activate','rollback','recover'))
    parser.add_argument('--stage-sha256')
    parser.add_argument('--receipt-sha256')
    parser.add_argument('--activation-sha256')
    parser.add_argument('--attempt-sha256')
    args=parser.parse_args()
    for key in (['stage_sha256'] if args.action!='freeze' else [])+(['receipt_sha256'] if args.action in ('check','activate','rollback','recover') else [])+(['activation_sha256'] if args.action=='rollback' else [])+(['attempt_sha256'] if args.action=='recover' else []):
        if not re.fullmatch('[0-9a-f]{64}',getattr(args,key) or ''):
            parser.error('--'+key.replace('_','-')+' required as SHA256')
    owner=load_owner()
    if args.action=='freeze':
        freeze(owner)
    else:
        bind_owner(owner,args.stage_sha256)
        if args.action=='prepare':
            prepare(owner,args.stage_sha256)
        elif args.action=='check':
            check(owner,args.stage_sha256,args.receipt_sha256)
        elif args.action=='recover':
            owner.recover_interrupted(receipt_sha=args.receipt_sha256,attempt_sha=args.attempt_sha256)
        else:
            owner.switch(receipt_sha=args.receipt_sha256,rollback=args.action=='rollback',activation_sha=args.activation_sha256)
