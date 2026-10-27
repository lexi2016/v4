"""This case only: build local immutable candidates after an explicit handoff.

Never acquires live locks or invokes launchctl. No old baseline is inferred.
The executing controller must revalidate every bound identity under original locks.
"""
from __future__ import annotations
import argparse, copy, hashlib, importlib.util, json, os, plistlib, re, shutil, stat, sys
from contextlib import contextmanager
from pathlib import Path

CASE=Path('/Users/lexi/Desktop/学习/agents调试/V4_BUSINESS_GAPS_20261027')
OUTPUT_ROOT=CASE/'controller/publication_control_r1'
LABELS={'main':'com.lexi.v35.scheduler','api':'com.lexi.v35.api-only','collector':'com.lexi.v35.runtime-graph','stage':'com.lexi.stage-center.scheduler','a_precapture':'com.lexi.stage-center.a-opening-precapture'}
SCOPE='V4_BUSINESS_GAPS_PUBLICATION_R1'
EXPECTED_US_LEDGER_ROOT='/Users/lexi/Library/Application Support/com.lexi.v4.local/state/dispatcher'
SAFETY=dict(RESEARCH_ONLY=True,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):
    with Path(path).open() as stream:value=json.load(stream)
    if not isinstance(value,dict):raise ValueError('JSON_OBJECT_REQUIRED:'+str(path))
    return value

def pin(path,digest):
    path=Path(path)
    if path.is_symlink() or path.resolve()!=path or sha(path)!=digest:raise ValueError('PIN_DRIFT:'+str(path))

def dump(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,sort_keys=True);stream.flush();os.fsync(stream.fileno())

def module(name,path):
    parent=str(Path(path).parent)
    if parent not in sys.path:sys.path.insert(0,parent)
    spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj;spec.loader.exec_module(obj);return obj


def environment(plist):
    result={}
    for arg in plist.get('ProgramArguments',[]):
        if isinstance(arg,str) and re.match(r'^[A-Za-z_][A-Za-z_0-9]*=',arg):
            key,value=arg.split('=',1)
            if key in result and result[key]!=value:raise ValueError('DUPLICATE_ENV:'+key)
            result[key]=value
    for key,value in plist.get('EnvironmentVariables',{}).items():
        if key in result and result[key]!=str(value):raise ValueError('ENV_FORMS_DISAGREE:'+key)
        result[key]=str(value)
    return result


def assert_safety(plist):
    values=environment(plist)
    for flag in ('PRODUCTION_ALLOWED','BUY_GATE_UPDATED','ORDERS_SENT'):
        present=[values[key] for key in (flag,flag.lower()) if key in values]
        if not present or any(value.strip().lower() not in {'false','0','no','off'} for value in present):raise ValueError('UNSAFE_OR_MISSING_SERVICE_FLAG:'+flag)


def env_both(plist,updates):
    result=copy.deepcopy(plist);args=result['ProgramArguments']
    if args[0]=='/usr/bin/env':
        args=[arg for arg in args if not (isinstance(arg,str) and arg.partition('=')[0] in updates)]
        index=next((i for i in range(1,len(args)) if not re.match(r'^[A-Za-z_][A-Za-z_0-9]*=',args[i])),len(args))
        args[index:index]=[key+'='+value for key,value in sorted(updates.items())]
        result['ProgramArguments']=args
    result.setdefault('EnvironmentVariables',{}).update(updates)
    environment(result)
    return result


def require_main_launcher(plist,app_root):
    expected=str(Path(app_root)/'ops/launch_v35_macos_scheduler.sh')
    launchers=[arg for arg in plist['ProgramArguments'] if isinstance(arg,str) and '=' not in arg and arg.endswith('/ops/launch_v35_macos_scheduler.sh')]
    if launchers!=[expected]:raise ValueError('MAIN_PROGRAMARGUMENTS_LAUNCHER_MISMATCH')
    return expected


def rewrite_owner(plist,old_app,new_app,manifest_sha,*,main=False):
    if main:require_main_launcher(plist,old_app)
    old_release=str(Path(old_app).parent);new_release=str(Path(new_app).parent)
    def replace(value):
        if isinstance(value,str):return value.replace(old_release,new_release)
        if isinstance(value,list):return [replace(item) for item in value]
        if isinstance(value,dict):return {key:replace(item) for key,item in value.items()}
        return value
    result=replace(copy.deepcopy(plist));result['WorkingDirectory']=str(new_app)
    values=environment(result)
    updates={'V35_APP_ROOT':str(new_app),'V35_RELEASE_ID':Path(new_app).parent.name,
             'V35_RELEASE_MANIFEST_PATH':str(Path(new_app).parent/'release-manifest.json'),'V35_RELEASE_MANIFEST_SHA256':manifest_sha}
    if 'PYTHONPATH' in values:updates['PYTHONPATH']=values['PYTHONPATH']
    result=env_both(result,updates)
    if main:require_main_launcher(result,new_app)
    return result


def handoff_ready(path,expected_sha):
    pin(path,expected_sha);value=load(path)
    if (value.get('schema_version')!='v4.business_gaps.publication_handoff.v1'
        or value.get('status')!='HANDED_OFF' or value.get('guards_released') is not True
        or value.get('owner_active') is not False or value.get('receiver_scope')!=SCOPE):
        raise RuntimeError('PENDING_EXPLICIT_LATEST_OWNER_HANDOFF')
    statement=value['owner_statement']
    if statement.get('scope')!='V4_BUSINESS_GAPS_20261027':raise ValueError('OWNER_STATEMENT_SCOPE')
    pin(statement['path'],statement['sha256'])
    return value


def validate_handoff_descriptors(value):
    """Read metadata only; never open or acquire an original lock in prepare."""
    for key in ('owner','lane_A_LONG','lane_DEFAULT','pdf_ingestion','collector'):
        row=value['locks'][key];path=Path(row['path']);info=path.lstat()
        if not path.is_absolute() or path.resolve()!=path or not stat.S_ISREG(info.st_mode):raise ValueError('ORIGINAL_LOCK_DESCRIPTOR:'+key)
        if (info.st_dev,info.st_ino)!=(row['device'],row['inode']):raise ValueError('ORIGINAL_LOCK_DESCRIPTOR_DRIFT:'+key)
    owner=value['locks']['owner'];pin(owner['marker'],owner['marker_sha256']);marker=load(owner['marker'])
    if marker.get('active') is not False or marker.get('phase')!='DONE':raise RuntimeError('PENDING_ORIGINAL_OWNER_ACTIVE')
    params=value['main_guard_parameters']
    if params.get('service')!='gui/501/com.lexi.v35.scheduler' or params.get('guard_program')!='/bin/sleep' or not 604800<=params.get('guard_seconds',0)<691200:raise ValueError('ORIGINAL_MAIN_READBACK_SCOPE')
    if params.get('domain')!='gui/501':raise ValueError('ORIGINAL_MAIN_READBACK_DOMAIN')
    for key in ('ledger_root','log_path','expected_python','expected_python_resolved','expected_python_binary_sha256'):
        if not isinstance(params.get(key),str) or not params[key]:raise ValueError('ORIGINAL_MAIN_READBACK_DESCRIPTOR:'+key)


@contextmanager
def api_identity_scope(helper,base,contract):
    """Current API is standard; keep the original strict identity verifier."""
    pin(contract['path'],contract['sha256'])
    if Path(helper.MODULE_CONTRACT_PATH)!=Path(contract['path']):raise ValueError('API_MODULE_CONTRACT_PATH')
    pin(base['manifest'],base['manifest_sha256'])
    if load(base['manifest']).get('schema_version')!='v4.release_candidate.v1':raise ValueError('STANDARD_CURRENT_API_REQUIRED')
    yield


def protected_windows(catalog):
    if not isinstance(catalog.get('workloads'),list):raise ValueError('SCHEDULE_CATALOG_SHAPE_UNKNOWN')
    slots=set()
    for workload in catalog.get('workloads',[]):
        slots.update(slot for slot in workload.get('slots',[]) if isinstance(slot,str) and re.fullmatch(r'\d{4}',slot))
    windows=[[slot,slot] for slot in sorted(slots)]
    for mandatory in [['1300','1300'],['1314','1316']]:
        if mandatory not in windows:windows.append(mandatory)
    return sorted(windows)


def apply_overlay(helper,base_app,candidate_app,rows):
    """Exact known deltas only; all Root 21/76 and other non-delta bytes survive."""
    entries=[]
    for row in sorted(rows,key=lambda row:row['path']):
        relative=helper._normalise_relative(row['path'])
        source=Path(row['source_path']);pin(source,row['after_sha256'])
        before=helper._safe_child(base_app,relative,allow_missing=True)
        raw=before.read_bytes() if before.exists() else None
        digest=hashlib.sha256(raw).hexdigest() if raw is not None else None
        if digest!=row['before_sha256']:raise ValueError('OVERLAP_REQUIRES_BOUNDED_ADJUDICATION:'+relative)
        proof,hunks=helper._diff_proof(raw,source.read_bytes()) if raw is not None else (None,None)
        entries.append({'path':relative,'before_sha256':digest,'after_sha256':sha(source),'unified_diff_sha256':proof,'unified_diff_hunk_count':hunks})
    shutil.copytree(base_app,candidate_app,symlinks=True)
    if helper.inventory_tree(base_app)!=helper.inventory_tree(candidate_app):raise ValueError('BASE_COPY_DRIFT')
    for entry in entries:
        with helper._candidate_parent_writable(candidate_app,entry['path']) as target:
            if target.exists():target.chmod(target.stat().st_mode|0o200)
            shutil.copy2(next(row['source_path'] for row in rows if row['path']==entry['path']),target)
    records,preserved=helper._verify_delta_files(base_app=base_app,candidate_app=candidate_app,entries=entries)
    return entries,{'non_delta_count':len(preserved),'non_delta_sha256':helper.inventory_digest(preserved),'records':records}


def manifest(helper,app,target,base_manifest,*,component=None,new_paths=()):
    legacy=base_manifest.get('files')
    if 'files' in base_manifest:
        if component!='main' or not isinstance(legacy,dict):raise ValueError('AUXILIARY_MANIFEST_INDEX_REQUIRES_ADJUDICATION')
        for path,digest in legacy.items():
            if (not isinstance(path,str) or not path.startswith('app/') or helper._normalise_relative(path[4:])!=path[4:]
                or not isinstance(digest,str) or re.fullmatch(r'[0-9a-f]{64}',digest) is None):raise ValueError('UNKNOWN_MAIN_LEGACY_INDEX')
        if legacy!={'app/'+row['path']:row['sha256'] for row in base_manifest['app_files']}:raise ValueError('MAIN_LEGACY_INDEX_DISAGREES_WITH_APP_FILES')
    result=copy.deepcopy(base_manifest);items=helper.inventory_tree(app)
    result['app_files']=[{'path':r['path'],'bytes':r['size'],'sha256':r['sha256']} for r in items if r['kind']=='file']
    if legacy is not None:
        projected={'app/'+row['path']:row['sha256'] for row in result['app_files']}
        added=set(projected)-set(legacy)
        if set(legacy)-set(projected) or not added.issubset({'app/'+path for path in new_paths}):raise ValueError('MAIN_LEGACY_INDEX_UNAUTHORIZED_KEY_SET_DRIFT')
        result['files']={path:projected[path] for path in legacy}
        result['files'].update({path:projected[path] for path in sorted(added)})
    result['symlinks']=[{'path':r['path'],'target':r['target']} for r in items if r['kind']=='symlink']
    result['application_inventory']={'entry_count':len(items),'entries':items,'aggregate_sha256':helper.inventory_digest(items)}
    if component=='api' and base_manifest.get('schema_version')=='v4.runtime_graph_repair_release.v1':
        result['schema_version']='v4.release_candidate.v1'
        result['candidate']={'root':str(target),'app_root':str(target/'app'),'release_id':target.name,'module_role':'gateway'}
    result.update(app_root=str(target/'app'),release_id=target.name,**SAFETY)
    if 'candidate' in result:result['candidate'].update(root=str(target),app_root=str(target/'app'),release_id=target.name)
    return result


def validate_stage_plist(before,after,old_app,new_app,key):
    for field in ('StartCalendarInterval','RunAtLoad','KeepAlive','WatchPaths','QueueDirectories','ThrottleInterval','ProcessType'):
        if before.get(field)!=after.get(field):raise ValueError('STAGE_SCHEDULE_OR_LIFECYCLE_DRIFT:'+field)
    for value,app in ((before,Path(old_app)),(after,Path(new_app))):
        args=value['ProgramArguments']
        expected=[str(app/'ops/run_stage_center_nodes.py'),'--config',str(app/'stage_center_tick_config.json')]
        if key=='a_precapture':expected+=['--node','PRECAPTURE_A_0925']
        if len(args)!=len(expected)+2 or args[1]!='-B' or args[2:]!=expected:raise ValueError('STAGE_ACTUAL_LAUNCHER_MISMATCH:'+key)


def prepare(output,*,handoff_path,handoff_sha):
    h=handoff_ready(handoff_path,handoff_sha)  # before any candidate/lock/service work
    validate_handoff_descriptors(h)
    if h.get('us_ledger_root')!=EXPECTED_US_LEDGER_ROOT:raise ValueError('INDEPENDENT_US_LEDGER_BINDING_MISMATCH')
    output=Path(output).absolute()
    if output.resolve()!=output or not output.is_relative_to(OUTPUT_ROOT):raise ValueError('OUTPUT_OUTSIDE_CASE')
    for name in ('integration','rewrite','operator','main_guard'):
        pin(h['helpers'][name]['path'],h['helpers'][name]['sha256'])
    helper=module('publication_original_integration',h['helpers']['integration']['path'])
    rewrite=module('publication_original_rewrite',h['helpers']['rewrite']['path'])
    operator=module('publication_original_operator',h['helpers']['operator']['path'])
    contract=h['api_module_contract'];pin(contract['path'],contract['sha256']);helper.MODULE_CONTRACT_PATH=Path(contract['path'])
    values={};base={}
    for key,label in LABELS.items():
        row=h['components'][key];expected=Path.home()/'Library/LaunchAgents'/(label+'.plist')
        if row['plist']!=str(expected):raise ValueError('FIXED_PLIST_SCOPE')
        pin(row['plist'],row['plist_sha256']);pin(row['manifest'],row['manifest_sha256'])
        values[key]=plistlib.loads(Path(row['plist']).read_bytes());assert_safety(values[key])
        if values[key]['Label']!=label or values[key]['WorkingDirectory']!=row['app_root']:raise ValueError('PLIST_ROOT_OR_LABEL_DRIFT')
        if environment(values[key]).get('V35_APP_ROOT',row['app_root'])!=row['app_root']:raise ValueError('APP_ROOT_ENV_DRIFT')
        if helper.inventory_digest(helper.inventory_tree(Path(row['app_root'])))!=row['application_inventory_sha256']:raise ValueError('HANDOFF_APPLICATION_INVENTORY_DRIFT:'+key)
        base[key]=copy.deepcopy(row)
    require_main_launcher(values['main'],base['main']['app_root'])
    with api_identity_scope(helper,base['api'],contract):current=helper.read_active_release(Path(base['api']['plist']))
    if current['app_root']!=base['api']['app_root'] or current['release_manifest_sha256']!=base['api']['manifest_sha256']:raise ValueError('FRESH_API_BASE_MISMATCH')
    for key in LABELS:
        operator.verify_release({'components':{key:{'release_root':str(Path(base[key]['app_root']).parent),'sha256':base[key]['manifest_sha256']}}},key)
    pin(h['source_freeze']['path'],h['source_freeze']['sha256'])
    freeze=load(h['source_freeze']['path'])
    if freeze.get('scope')!=SCOPE:raise ValueError('FROZEN_SOURCE_SCOPE')
    overlays={key:[] for key in ('main','api','collector','stage')}
    for row in freeze['overlay_entries']:
        if row['component'] not in overlays:raise ValueError('UNKNOWN_OVERLAY_COMPONENT')
        pin(row['source_path'],row['after_sha256']);overlays[row['component']].append(row)
    if any(not rows for rows in overlays.values()):raise ValueError('MISSING_COMPONENT_OVERLAY')
    native=h['native_reader_roots'];pin(native['path'],native['sha256']);native=load(native['path'])
    for row in native['sources']:pin(row['path'],row['sha256'])
    if set(native['native_reader_roots'])!={'manager_main_state_root','manager_api_state_root','pdf_data_root','us_ledger_root','stage_candidate_root','stage_a_opening_root'}:raise ValueError('NATIVE_READER_EXACT_ROOT_SET')
    if native['native_reader_roots']['us_ledger_root']!=h['us_ledger_root']:raise ValueError('NATIVE_US_LEDGER_ROOT_DRIFT')
    output.mkdir(mode=0o700)
    target_root=Path(base['api']['app_root']).parents[1]
    targets={key:target_root/('business-gaps-20261027-r1-'+key) for key in LABELS}
    targets['a_precapture']=targets['stage']
    if any(root.exists() for root in targets.values()):raise ValueError('TARGET_ALREADY_EXISTS')
    components={};proofs={}
    for key in ('main','api','collector','stage'):
        candidate=output/key;candidate.mkdir();old_app=Path(base[key]['app_root'])
        if key in overlays:
            entries,proof=apply_overlay(helper,old_app,candidate/'app',overlays[key]);proofs[key]=proof
        else:
            shutil.copytree(old_app,candidate/'app',symlinks=True);entries=[]
            if helper.inventory_tree(old_app)!=helper.inventory_tree(candidate/'app'):raise ValueError('GRAPH_COPY_DRIFT')
        m=manifest(helper,candidate/'app',targets[key],load(base[key]['manifest']),component=key,new_paths=[row['path'] for row in overlays[key] if row['before_sha256'] is None])
        if key=='api':
            m['external_module_contract']=copy.deepcopy(contract)
            m['source_manifest_identity']={'path':base[key]['manifest'],'sha256':base[key]['manifest_sha256'],'schema_version':load(base[key]['manifest'])['schema_version'],
                                           'plist_sha256':base[key]['plist_sha256'],'application_inventory_sha256':base[key]['application_inventory_sha256']}
            receipt={'schema_version':helper.DELTA_SCHEMA_VERSION,'base':helper._base_binding(current),'entries':entries}
            dump(candidate/helper.DELTA_RECEIPT_NAME,receipt)
            # Use the original integrated-builder verifier's exact contract.
            records=proofs['api']['records'];m['api_integration']={'schema_version':helper.SCHEMA_VERSION,'base':receipt['base'],
                'target_role':'gateway','base_role':'gateway','bootstrap_transition':False,
                'delta_receipt_file':helper.DELTA_RECEIPT_NAME,'delta_receipt_sha256':sha(candidate/helper.DELTA_RECEIPT_NAME),
                'delta_entries':records,'non_delta_active_release_bytes_preserved':True,
                'non_delta_entry_count':proofs['api']['non_delta_count'],'non_delta_inventory_sha256':proofs['api']['non_delta_sha256']}
        dump(candidate/'release-manifest.json',m)
        components[key]={'candidate_app':str(candidate/'app'),'path':str(candidate/'release-manifest.json'),'release_root':str(targets[key]),'sha256':sha(candidate/'release-manifest.json'),
                         'application_inventory_sha256':m['application_inventory']['aggregate_sha256']}
    components['a_precapture']=copy.deepcopy(components['stage'])
    if base['stage']['app_root']!=base['a_precapture']['app_root'] or base['stage']['manifest_sha256']!=base['a_precapture']['manifest_sha256']:raise ValueError('STAGE_SHARED_ROOT_DIVERGED')
    old_config=Path(h['graph_config']['path']);pin(old_config,h['graph_config']['sha256']);config=load(old_config)
    if config['main']['app_root']!=base['main']['app_root']:raise ValueError('GRAPH_MAIN_BASE_BINDING_MISMATCH')
    for key in ('main','api','stage'):
        old=base[key]['app_root'];new=str(targets[key]/'app')
        if key=='main':config['main']['app_root']=new
        for row in config['entry_sources'].values():
            if row['module_file'].startswith(old+'/'):
                rel=row['module_file'][len(old)+1:];row.update(module_file=new+'/'+rel,module_sha256=sha(output/key/'app'/rel))
    config['native_reader_roots']=native['native_reader_roots']
    config_path=output/'runtime-graph-config.json';dump(config_path,config);config_target=targets['collector']/'runtime-graph-config.json'
    proposed={}
    for key in ('main','collector','stage','a_precapture'):
        proposed[key]=rewrite_owner(values[key],base[key]['app_root'],targets[key]/'app',components[key]['sha256'],main=key=='main')
    args=proposed['collector']['ProgramArguments'];args[args.index('--config')+1]=str(config_target)
    proposed['api']=rewrite.rewrite_api_only_plist(values['api'],candidate_app_root=targets['api']/'app',release_id=targets['api'].name,
        manifest_path=targets['api']/'release-manifest.json',manifest_sha256=components['api']['sha256'])
    proposed['api']=env_both(proposed['api'],{'V4_RUNTIME_GRAPH_CONFIG':str(config_target),'V4_TASK_STATUS_US_LEDGER_ROOT':h['us_ledger_root']})
    if proposed['api']['ProgramArguments'][0]!='/usr/bin/env':raise ValueError('API_ENV_WRAPPER_REQUIRED')
    for key in ('stage','a_precapture'):validate_stage_plist(values[key],proposed[key],base[key]['app_root'],targets[key]/'app',key)
    operations=[]
    for key in LABELS:
        assert_safety(proposed[key])
        path=output/(LABELS[key]+'.plist');raw=plistlib.dumps(proposed[key],fmt=plistlib.FMT_XML,sort_keys=True)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        operations.append({'component':key,'label':LABELS[key],'plist':base[key]['plist'],'before_sha256':base[key]['plist_sha256'],
            'after_sha256':sha(path),'template_path':str(path),'template_sha256':sha(path),'replace_prefix':'__NONE__','new_prefix':'__NONE__','env_set':{},'set':{},'remove':[]})
    prior={'components':{key:{'candidate_app':row['app_root'],'path':row['manifest'],'release_root':str(Path(row['app_root']).parent),'sha256':row['manifest_sha256'],
                             'application_inventory_sha256':row['application_inventory_sha256']} for key,row in base.items()},
        'operations':[{**row,'after_sha256':row['before_sha256']} for row in operations],'config_path':str(old_config),'config_target':str(old_config),'config_sha256':h['graph_config']['sha256']}
    dump(output/'PRIOR_PLAN.json',prior)
    catalog=h['schedule_catalog'];pin(catalog['path'],catalog['sha256'])
    p={'scope':SCOPE,'handoff':{'path':str(handoff_path),'sha256':handoff_sha},'components':components,'operations':operations,
       'base':base,'config_path':str(config_path),'config_target':str(config_target),'config_sha256':sha(config_path),
       'prior_plan':str(output/'PRIOR_PLAN.json'),'prior_plan_sha256':sha(output/'PRIOR_PLAN.json'),'helpers':h['helpers'],
       'api_module_contract':contract,'locks':h['locks'],'main_guard_parameters':h['main_guard_parameters'],
       'api_baseline':helper._base_binding(current),
       'workbench_root':h['workbench_root'],'us_ledger_root':h['us_ledger_root'],'protected_windows':protected_windows(load(catalog['path'])),
       'minimum_margin_seconds':300,'read_only_services':h['read_only_services'],'proofs':proofs,'frozen_inputs':{key:h[key] for key in ('source_freeze','native_reader_roots')},
       'stage_config_relative':'stage_center_tick_config.json',
       'prepare_path':str(Path(__file__).absolute()),'prepare_sha256':sha(__file__),**SAFETY}
    # Fresh read CAS after copying: a changed handoff/base produces no runnable plan.
    for row in base.values():
        pin(row['plist'],row['plist_sha256']);pin(row['manifest'],row['manifest_sha256'])
        if helper.inventory_digest(helper.inventory_tree(Path(row['app_root'])))!=row['application_inventory_sha256']:raise ValueError('BASE_CHANGED_DURING_PREPARE')
    for key in ('stage','a_precapture'):
        for slot in values[key].get('StartCalendarInterval',[]):
            clock=f"{slot['Hour']:02d}{slot['Minute']:02d}"
            if [clock,clock] not in p['protected_windows']:p['protected_windows'].append([clock,clock])
    if len(h['read_only_services'])!=1 or h['read_only_services'][0]['label']!='com.lexi.stage-center.hk-deadline':raise ValueError('EXACT_UNCHANGED_DEADLINE_SCOPE')
    for row in h['read_only_services']:
        if row['plist']!=str(Path.home()/'Library/LaunchAgents'/(row['label']+'.plist')):raise ValueError('READ_ONLY_PLIST_SCOPE')
        pin(row['plist'],row['plist_sha256']);pin(row['expected_launcher'],row['launcher_sha256'])
        value=plistlib.loads(Path(row['plist']).read_bytes())
        if row['expected_launcher'] not in value['ProgramArguments'] or '--deadline-only' not in value['ProgramArguments']:raise ValueError('UNCHANGED_DEADLINE_LAUNCHER_SCOPE')
    dump(output/'PLAN.json',p);return p


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--handoff',type=Path,required=True);ap.add_argument('--handoff-sha',required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();prepare(args.output,handoff_path=args.handoff,handoff_sha=args.handoff_sha)
