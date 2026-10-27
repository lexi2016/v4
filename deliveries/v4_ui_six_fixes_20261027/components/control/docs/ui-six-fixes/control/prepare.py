"""This case only: build local immutable candidates after an explicit handoff.

Never acquires live locks or invokes launchctl. No old baseline is inferred.
The executing controller must revalidate every bound identity under original locks.
"""
from __future__ import annotations
import argparse, copy, hashlib, importlib.util, json, os, plistlib, re, shutil, stat, sys
from pathlib import Path

CASE=Path('/Users/lexi/Desktop/学习/agents调试/V4_UI_SIX_FIXES_20261027')
OUTPUT_ROOT=CASE/'controller/publication_control_r2'
LABELS={'main':'com.lexi.v35.scheduler','api':'com.lexi.v35.api-only','collector':'com.lexi.v35.runtime-graph'}
SCOPE='V4_UI_PDF_PUBLICATION_CONTROL_R2'
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
    if (value.get('schema_version')!='v4.ui_pdf_publication_handoff.v1'
        or value.get('status')!='HANDED_OFF' or value.get('guards_released') is not True
        or value.get('owner_active') is not False or value.get('receiver_scope')!=SCOPE):
        raise RuntimeError('PENDING_EXPLICIT_LATEST_OWNER_HANDOFF')
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


def verify_business_review(handoff):
    receipt=load(handoff['business_review']['path']).get('review_receipt')
    if not isinstance(receipt,dict) or receipt.get('verdict')!='REVIEWED/PASS':raise ValueError('BUSINESS_PASS_REQUIRED')
    for field,key in (('combined_source_freeze_sha256','source_freeze'),('api_overlay_sha256','api_overlay'),('pdf_main_overlay_sha256','main_overlay')):
        if receipt.get(field)!=handoff[key]['sha256']:raise ValueError('BUSINESS_REVIEW_BINDING_MISMATCH:'+field)


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


def manifest(helper,app,target,base_manifest):
    if 'files' in base_manifest:raise ValueError('AUXILIARY_MANIFEST_INDEX_REQUIRES_ADJUDICATION')
    result=copy.deepcopy(base_manifest);items=helper.inventory_tree(app)
    result['app_files']=[{'path':r['path'],'bytes':r['size'],'sha256':r['sha256']} for r in items if r['kind']=='file']
    result['symlinks']=[{'path':r['path'],'target':r['target']} for r in items if r['kind']=='symlink']
    result['application_inventory']={'entries':items,'aggregate_sha256':helper.inventory_digest(items)}
    result.update(app_root=str(target/'app'),release_id=target.name,**SAFETY)
    if 'candidate' in result:result['candidate'].update(root=str(target),app_root=str(target/'app'),release_id=target.name)
    return result


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
    current=helper.read_active_release(Path(base['api']['plist']))
    if current['app_root']!=base['api']['app_root'] or current['release_manifest_sha256']!=base['api']['manifest_sha256']:raise ValueError('FRESH_API_BASE_MISMATCH')
    for key in LABELS:
        operator.verify_release({'components':{key:{'release_root':str(Path(base[key]['app_root']).parent),'sha256':base[key]['manifest_sha256']}}},key)
    for key in ('api_overlay','main_overlay','source_freeze','business_review'):
        pin(h[key]['path'],h[key]['sha256'])
    verify_business_review(h)
    overlays={'api':load(h['api_overlay']['path'])['entries'],'main':load(h['main_overlay']['path'])['entries']}
    if len(overlays['main'])!=2 or len(overlays['api'])!=14:raise ValueError('FROZEN_OVERLAY_COUNTS')
    api_business=[row for row in overlays['api'] if row.get('kind')=='business_source']
    if len(api_business)!=12 or len([row for row in overlays['api'] if row.get('kind')=='built_frontend'])!=2:raise ValueError('FROZEN_API_SOURCE_STATIC_SPLIT')
    freeze=load(h['source_freeze']['path'])
    if (freeze.get('api_overlay_sha256')!=h['api_overlay']['sha256'] or freeze.get('pdf_main_overlay_sha256')!=h['main_overlay']['sha256']):raise ValueError('OVERLAY_NOT_BOUND_TO_BUSINESS_FREEZE')
    expected={row['path']:row['after_sha256'] for row in freeze['business_files']}
    actual={row['path']:row['after_sha256'] for row in api_business+overlays['main']}
    if expected!=actual or len(expected)!=14:raise ValueError('BUSINESS_FROZEN_BYTE_SET_MISMATCH')
    output.mkdir(mode=0o700)
    target_root=Path(base['api']['app_root']).parents[1]
    targets={key:target_root/('ui-pdf-publication-20261027-r2-'+key) for key in LABELS}
    if any(root.exists() for root in targets.values()):raise ValueError('TARGET_ALREADY_EXISTS')
    components={};proofs={}
    for key in ('main','api','collector'):
        candidate=output/key;candidate.mkdir();old_app=Path(base[key]['app_root'])
        if key in overlays:
            entries,proof=apply_overlay(helper,old_app,candidate/'app',overlays[key]);proofs[key]=proof
        else:
            shutil.copytree(old_app,candidate/'app',symlinks=True);entries=[]
            if helper.inventory_tree(old_app)!=helper.inventory_tree(candidate/'app'):raise ValueError('GRAPH_COPY_DRIFT')
        m=manifest(helper,candidate/'app',targets[key],load(base[key]['manifest']))
        if key=='api':
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
    old_config=Path(h['graph_config']['path']);pin(old_config,h['graph_config']['sha256']);config=load(old_config)
    if config['main']['app_root']!=base['main']['app_root']:raise ValueError('GRAPH_MAIN_BASE_BINDING_MISMATCH')
    for key in ('main','api'):
        old=base[key]['app_root'];new=str(targets[key]/'app')
        if key=='main':config['main']['app_root']=new
        for row in config['entry_sources'].values():
            if row['module_file'].startswith(old+'/'):
                rel=row['module_file'][len(old)+1:];row.update(module_file=new+'/'+rel,module_sha256=sha(output/key/'app'/rel))
    config_path=output/'runtime-graph-config.json';dump(config_path,config);config_target=targets['collector']/'runtime-graph-config.json'
    proposed={}
    for key in ('main','collector'):
        proposed[key]=rewrite_owner(values[key],base[key]['app_root'],targets[key]/'app',components[key]['sha256'],main=key=='main')
    args=proposed['collector']['ProgramArguments'];args[args.index('--config')+1]=str(config_target)
    proposed['api']=rewrite.rewrite_api_only_plist(values['api'],candidate_app_root=targets['api']/'app',release_id=targets['api'].name,
        manifest_path=targets['api']/'release-manifest.json',manifest_sha256=components['api']['sha256'])
    proposed['api']=env_both(proposed['api'],{'V4_RUNTIME_GRAPH_CONFIG':str(config_target),'V4_TASK_STATUS_US_LEDGER_ROOT':h['us_ledger_root']})
    if proposed['api']['ProgramArguments'][0]!='/usr/bin/env':raise ValueError('API_ENV_WRAPPER_REQUIRED')
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
       'workbench_root':h['workbench_root'],'us_ledger_root':h['us_ledger_root'],'protected_windows':protected_windows(load(catalog['path'])),
       'minimum_margin_seconds':300,'proofs':proofs,'frozen_inputs':{key:h[key] for key in ('api_overlay','main_overlay','source_freeze','business_review')},
       'prepare_path':str(Path(__file__).absolute()),'prepare_sha256':sha(__file__),**SAFETY}
    # Fresh read CAS after copying: a changed handoff/base produces no runnable plan.
    for row in base.values():
        pin(row['plist'],row['plist_sha256']);pin(row['manifest'],row['manifest_sha256'])
        if helper.inventory_digest(helper.inventory_tree(Path(row['app_root'])))!=row['application_inventory_sha256']:raise ValueError('BASE_CHANGED_DURING_PREPARE')
    dump(output/'PLAN.json',p);return p


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--handoff',type=Path,required=True);ap.add_argument('--handoff-sha',required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();prepare(args.output,handoff_path=args.handoff,handoff_sha=args.handoff_sha)
