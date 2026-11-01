#!/usr/bin/env python3
"""Build sealed Stage/API/A-pre-capture candidates from exact bytes; never activate."""
from __future__ import annotations
import argparse, ast, copy, difflib, hashlib, importlib.util, json, os, shutil, subprocess, sys
from pathlib import Path

BASE_COMMIT = '684afcc20be355513b52484430533fe8f2d95e53'
LOCAL = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
STAGE = LOCAL/'releases/a-stage-owner-compatibility-20261030-r2-stage/app'
API = LOCAL/'candidates/date-history-fix-20261101-r1/app'
MAIN = LOCAL/'releases/workbench-daily-chain-20261031-r6-main/app'
PRECAPTURE = LOCAL/'releases/a-snapshot-recovery-20261029-r1-stage/app'
MANUAL_CONFIG = LOCAL/'releases/v4-retirement-20261028-api/config/api-v4_manual_collection_stage_config.json'
MANUAL_CONFIG_PIN = 'c6c3a1144d69b23714bdd432e1f228cc56c9f9e4a80fffec8df28f5c5ebb87ee'
MANUAL_CONFIG_RELATIVE = 'config/api-v4_manual_collection_stage_config.json'
PINS = {'stage':'9ef8f0bdebca08a7ac5cc04f42ef4a323d186d2d894ee29a8062908802361d35',
        'api':'2bcd7c67bc27f515824eb1a861d534f1937e863e44505d8244a54780b694e247',
        'main':'f32d922fafcbf8c1e6f9958d5802eef80e58195502f16410a6d11f744e98ac74',
        'a_precapture':'8b9e9c22f4641c395e853dcfd2b0c7054f9fdcd416d9ed0bc86412da617a5694'}
SHARED = ('stage_center/candidate_input.py', 'contracts/a_share_code.py',
          'contracts/a_share_entity_filter.py')
STAGE_PATHS = (*SHARED, 'stage_center/hk_stage8/rtdata.py', 'stage_center/market_retry.py',
               'stage_center/snapshot_recovery.py','stage_center/collector_capture.py',
               'ops/stage_data_recovery.py')
SOP_PATHS = ('infrastructure/operations_sop_reader.py','docs/SOP.md',
    'docs/operations/STAGE_SELECTION_SOP.md','docs/operations/records/2026-10-28_29-stage-selection-repair.md')

def sha(raw): return hashlib.sha256(raw).hexdigest()
def dump(path, payload): path.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def once(text, before, after):
    if text.count(before)!=1: raise ValueError('OVERLAY_ANCHOR_MISMATCH:'+before[:90])
    return text.replace(before,after,1)
def exact_overlay(before, after, inherited):
    old,new=before.decode().splitlines(True),after.decode().splitlines(True)
    result=inherited.decode()
    for group in difflib.SequenceMatcher(None,old,new,autojunk=False).get_grouped_opcodes(3):
        a=''.join(old[group[0][1]:group[-1][2]]);b=''.join(new[group[0][3]:group[-1][4]])
        result=once(result,a,b)
    return result.encode()
def inventory_tools():
    spec=importlib.util.spec_from_file_location('stage_repair_inventory',API/'ops/api_release_integration.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
def no_alias(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise ValueError('ABSOLUTE_EXACT_PATH_REQUIRED')
    for node in (path,*path.parents):
        if node.is_symlink():raise ValueError('SYMLINK_PATH_FORBIDDEN:'+str(node))
def write(app,relative,raw):
    target=app/relative;no_alias(target);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(raw)
    if relative.endswith('.py'):ast.parse(raw)
def binding(app):
    raw=(app.parent/'release-manifest.json').read_bytes()
    return {'app_root':str(app),'release_id':app.parent.name,'manifest_sha256':sha(raw)}

def native_capture_overlay(raw):
    text=raw.decode()
    text=once(text,'    provider = provider or NativeAOpeningSnapshotProvider(now=now)\n','')
    text=once(text,'        "invoked_at": wall.isoformat(), "authorizes_selection": False, **flags}\n',
        '        "requested_codes": list(candidate.codes), "source": "NATIVE_A_OPENING_SNAPSHOT",\n'
        '        "invoked_at": wall.isoformat(), "authorizes_selection": False, **flags}\n')
    text=once(text,'        provider.prepare()  # Context only; no quote request before the boundary.\n',
        '        provider = provider or NativeAOpeningSnapshotProvider(now=now)\n'
        '        provider.prepare()  # Context only; no quote request before the boundary.\n')
    text=once(text,'                provider.close()\n','                if provider is not None: provider.close()\n')
    anchor='                payload = self.primary.snapshot(batch, trade_date=trade_date, stage_id=stage_id, cutoff_at=cutoff.isoformat())\n'
    if text.count(anchor)!=2:raise ValueError('NATIVE_PRIMARY_RESPONSE_ANCHOR_MISMATCH')
    text=text.replace(anchor,anchor+'                batches.append(payload)  # Preserve response before identity/row checks.\n')
    anchor='                payload = {**payload, "source_method": "get_market_snapshot"}\n                batches.append(payload)\n'
    if text.count(anchor)!=2:raise ValueError('NATIVE_PRIMARY_BATCH_ANCHOR_MISMATCH')
    text=text.replace(anchor,'                payload = {**payload, "source_method": "get_market_snapshot"}\n')
    return text.encode()

def prepare(output, source, *, prepared_runtime=False):
    no_alias(output);no_alias(source)
    if output.parent not in {Path('/private/tmp'),LOCAL/'candidates'} or output.exists():raise ValueError('NEW_ISOLATED_CANDIDATE_ROOT_REQUIRED')
    tools=inventory_tools();baselines={}
    no_alias(MANUAL_CONFIG)
    manual_raw=MANUAL_CONFIG.read_bytes()
    if sha(manual_raw)!=MANUAL_CONFIG_PIN:raise ValueError('MANUAL_CONFIG_SOURCE_CAS_CHANGED')
    for role,app in [('stage',STAGE),('api',API),('main',MAIN),('a_precapture',PRECAPTURE)]:
        no_alias(app)
        raw=(app.parent/'release-manifest.json').read_bytes()
        if sha(raw)!=PINS[role]:raise ValueError('BASE_MANIFEST_CAS_CHANGED:'+role)
        seal=json.loads(raw);actual=tools.inventory_tree(app)
        if seal['application_inventory']!={'entries':actual,'entry_count':len(actual),'aggregate_sha256':tools.inventory_digest(actual)}:
            raise ValueError('BASE_INVENTORY_DRIFT:'+role)
        baselines[role]=(seal,actual)
    output.mkdir();results={}
    for role,base in [('stage',STAGE),('api',API),('a_precapture',PRECAPTURE)]:
        root=output/(output.name+'-'+role);app=root/'app'
        shutil.copytree(base,app,symlinks=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo'))
        paths=STAGE_PATHS if role=='stage' else (*SHARED,*SOP_PATHS) if role=='api' else SHARED
        for relative in paths:write(app,relative,(source/relative).read_bytes())
        allowed=set(paths)
        if role in {'stage','a_precapture'}:
            relative='infrastructure/stage_quote_provider.py'
            write(app,relative,native_capture_overlay((base/relative).read_bytes()));allowed.add(relative)
        if role=='stage':
            relative='ops/run_stage_center_nodes.py'
            original=subprocess.check_output(['git','show',BASE_COMMIT+':'+relative],cwd=source)
            write(app,relative,exact_overlay(original,(source/relative).read_bytes(),(base/relative).read_bytes()))
            allowed.add(relative)
            relative='ops/_run_stage_center_nodes_parts/stage_dispatch.py'
            text=(base/relative).read_text()
            anchor='    attempt_count = _v4_global(_v4_scope, \'_node_attempt_count\')(receipt)\n'
            extra=('    from stage_center.market_retry import dispatch_partial_market_retry\n'
                   '    market_retry = dispatch_partial_market_retry(_v4_scope, config, trade_date, stage_id, evaluated_at,\n'
                   '        mode=mode, runner=runner, receipt=receipt)\n'
                   '    if market_retry is not None:\n        return market_retry\n')
            write(app,relative,once(text,anchor,extra+anchor).encode());allowed.add(relative)
            relative='stage_center/_runner_parts/slot_execution.py'
            text=(base/relative).read_text()
            text=once(text,'                        result = collectors[market](plan, market)\n',
                '                        from stage_center.collector_capture import retained_collector_call\n'
                '                        result = retained_collector_call(collectors[market], plan, market, self.config.raw_root)\n')
            write(app,relative,text.encode());allowed.add(relative)
            relative='stage_center/_live_collectors_parts/shared_module_loading.py'
            text=(base/relative).read_text()
            text=once(text,'        return process_runner(command, **kwargs)\n',
                '        from stage_center.collector_capture import retained_process_call\n'
                '        return retained_process_call(process_runner, command, **kwargs)\n')
            write(app,relative,text.encode());allowed.add(relative)
            relative='stage_center_tick_config.json';cfg=json.loads((base/relative).read_bytes())
            cfg['release_id']=root.name
            retired=cfg['research_historical_owner_bindings'][0]
            prior=cfg['research_owner_binding'];cfg['research_owner_binding']=binding(MAIN)
            cfg['research_historical_owner_bindings']=[prior,cfg['research_historical_owner_bindings'][1]]
            # Empty isolated write roots; authoritative inputs stay read-only.
            if not prepared_runtime:
                for key in ('raw_root','selection_root','receipt_root','a_auction_root','hk_auction_root','hk_stage_replay_root'):
                    path=output/'isolated-state'/key;path.mkdir(parents=True,exist_ok=True);cfg[key]=str(path)
            write(app,relative,(json.dumps(cfg,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode());allowed.add(relative)
        if role=='api':
            stage_app=Path(results['stage']['app_root'])
            stage_cfg=json.loads((stage_app/'stage_center_tick_config.json').read_bytes())
            manual_cfg=json.loads(manual_raw)
            # Keep the existing manual service's exact allowlisted shape and
            # data roots. Only executable owner and its accepted shared source
            # move to the new Stage tuple; no new manual collection behavior.
            manual_cfg.update(stage_owner_root=str(stage_app),
                stage_owner_python=stage_cfg['python_path'],shared_data_root=stage_cfg['shared_data_root'])
            manual_bytes=(json.dumps(manual_cfg,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
            write(app,MANUAL_CONFIG_RELATIVE,manual_bytes);allowed.add(MANUAL_CONFIG_RELATIVE)
        original=baselines[role][1];actual=tools.inventory_tree(app)
        before={r['path']:r for r in original};after={r['path']:r for r in actual}
        delta=[p for p in sorted(set(before)|set(after)) if before.get(p)!=after.get(p)]
        if set(delta)-allowed:raise ValueError('NON_ALLOWLIST_DELTA:'+repr(set(delta)-allowed))
        manifest=copy.deepcopy(baselines[role][0]);manifest.update(app_root=str(app),release_id=root.name,
            RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,
            activation_status='PREPARED_NOT_ACTIVATED',deployment_status='NOT_DEPLOYED')
        if 'candidate' in manifest:manifest['candidate'].update(root=str(root),app_root=str(app),release_id=root.name)
        manifest['application_inventory']={'entries':actual,'entry_count':len(actual),'aggregate_sha256':tools.inventory_digest(actual)}
        if 'app_files' in manifest:manifest['app_files']=actual
        manifest['repair_provenance']={'source_baseline':BASE_COMMIT,'source_root':str(source),
            'base_app':str(base),'base_manifest_sha256':PINS[role],
            'delta':[{'path':p,'before':before.get(p),'after':after.get(p)} for p in delta],
            'retired_historical_binding_read_only_record':retired if role=='stage' else None,
            'manual_config_source':{'path':str(MANUAL_CONFIG),'sha256':MANUAL_CONFIG_PIN} if role=='api' else None,
            'configuration_mode':'PREPARED_RUNTIME_NOT_EXECUTED' if prepared_runtime else 'ISOLATED_TEST_ONLY'}
        dump(root/'release-manifest.json',manifest)
        results[role]={'app_root':str(app),'release_id':root.name,'manifest_sha256':sha((root/'release-manifest.json').read_bytes()),
                       'inventory_sha256':tools.inventory_digest(actual),'delta':delta,
                       'source_role':{'stage':'STAGE_PRIMARY_SCHEDULER','api':'API_SOP_AND_EXECUTION_READER',
                                      'a_precapture':'A_OPENING_PRECAPTURE'}[role]}
    dump(output/'candidates.json',results)
    api_app=Path(results['api']['app_root']);stage_app=Path(results['stage']['app_root'])
    dump(output/'activation-environment.json',{
        'status':'PREPARED_NOT_APPLIED','runtime_state_roots_changed':False,
        'api_environment':{'V4_APP_ROOT':str(api_app),'V4_RELEASE_ID':results['api']['release_id'],
            'V4_RELEASE_MANIFEST_PATH':str(api_app.parent/'release-manifest.json'),
            'V4_RELEASE_MANIFEST_SHA256':results['api']['manifest_sha256'],
            'V4_MANUAL_COLLECTION_STAGE_CONFIG':str(api_app/MANUAL_CONFIG_RELATIVE)},
        'manual_config_sha256':sha((api_app/MANUAL_CONFIG_RELATIVE).read_bytes()),
        'stage_owner_identity':results['stage'],
        'stage_authority_config_sha256':sha((stage_app/'stage_center_tick_config.json').read_bytes()),
        'manual_HK_child_manifest_environment':
            'Existing fixed HK-only owner program does not consume inherited API manifest variables; '
            'V4_APP_ROOT/release_id/PYTHONPATH are rebound by unchanged manual_collection.py',
    })
    return results
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--prepared-runtime',action='store_true',help='Preserve approved runtime data roots; do not run any scheduler')
    a=p.parse_args()
    print(json.dumps(prepare(a.output,a.source_root,prepared_runtime=a.prepared_runtime),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
