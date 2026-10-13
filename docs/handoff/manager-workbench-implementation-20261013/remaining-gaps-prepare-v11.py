"""Exact Stage-base three-source + reviewed Futu94 delta. Preparation only by default."""
from pathlib import Path
import argparse,copy,hashlib,json,plistlib,shutil,sys,stat
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
import importlib.util
spec=importlib.util.spec_from_file_location('accepted_calendar_v11',HERE/'recover_cached_full_date.py');runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime);runtime.install_runtime()
import ops.api_release_integration as generic
from ops.api_release_integration import (_base_binding,_diff_proof,DELTA_SCHEMA_VERSION,build_integrated_app,
 inventory_tree,inventory_digest,shared_api_release_lock,verify_api_release_candidate)
from operate_v7_cutover import validate,API,SCHED
from prepare_v7_operator import FORMAL,CANONICAL
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
BUSINESS={'v4/manager_workbench/inputs/native.py','v4/manager_workbench/inputs/source_bindings.py','v4/manager_workbench/engines/us_mapping.py'}
STAGE_API_ROOT=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-stage-evidence-20261013-api/app')
STAGE_MANIFEST_SHA='758efa07955f2c061478c1b4d63fcb0db0972db86fc865996295b557061deb1e'
STAGE_PLIST_SHA='b3669aa2c154f908698280c687c11066640f92a30de4fff7e987aebb3ef00639'
FUTU_PRODUCT=HERE/'remaining-gaps-futu-batch-r1/binding-product-38b4b023d165c6bfcb39f75d.json'
FUTU_PRODUCT_SHA='a7521f1d5b7f1efc3a8b954910aa3b91e64e785482f6c26c3efe5fce1972dcae'
FUTU_REVIEW=Path('/private/tmp/mwb-futu94-data-independent-uJT4HB/receipt.json')
FUTU_REVIEW_SHA='e07d09b6c1b0f1964f374794351da18f53a8a66c40d2932916926b4f4c8e507d'
SOURCE_RECEIPT=HERE/'remaining-gaps-us-implementation-r1.json'
SOURCE_RECEIPT_SHA='d2aa3a31116c37e29514130eb138c4ef5719fd4982515d8a7dfdf43e03f16454'
BASE_RECEIPT_SHA='730e988b3995c264288636d0bd7adef75819688212153d91776b20dd387e6149'
US_REVIEW_SHA='4781d3ee67bb947409130d207db09cb29e9714e6e90fd8d0bb6d9a2ba809ea26'
ORIGINAL_IDENTITY=generic._release_identity

def declared_cache_proof(root,manifest):
 """Only the fixed manifest's regular generated cache records may differ."""
 entries=manifest['application_inventory']['entries'];actual=inventory_tree(root)
 by={e['path']:e for e in actual};declared={e['path']:e for e in entries}
 if len(declared)!=len(entries) or inventory_digest(entries)!=manifest['application_inventory']['aggregate_sha256']:
  raise ValueError('STAGE_DECLARED_INVENTORY_DIGEST_INVALID')
 excluded=[]
 for rel in sorted(set(by)|set(declared)):
  if by.get(rel)==declared.get(rel):continue
  old=declared.get(rel)
  if rel in by or not old or not generic._is_generated_cpython_314_cache_file(root,rel):raise ValueError('STAGE_NON_CACHE_SOURCE_DRIFT:'+rel)
  if generic._entry_for_path(root,rel)!=old:raise ValueError('STAGE_DECLARED_CACHE_BYTES_DRIFT:'+rel)
  excluded.append(old)
 if not excluded:raise ValueError('STAGE_EXACT_CACHE_COMPAT_NOT_NEEDED')
 return actual,excluded

def exact_stage_identity(**args):
 try:return ORIGINAL_IDENTITY(**args)
 except ValueError as error:
  if str(error)!='API_RELEASE_ACTIVE_APPLICATION_INVENTORY_DRIFT':raise
 root=Path(args['app_root']);mp=Path(args['manifest_path'])
 if (root!=STAGE_API_ROOT or Path(args['release_root'])!=root.parent or mp!=root.parent/'release-manifest.json'
     or args['release_id']!='hk-stage-evidence-20261013-api' or args['manifest_sha256']!=STAGE_MANIFEST_SHA
     or sha(mp.read_bytes())!=STAGE_MANIFEST_SHA or sha(API.read_bytes())!=STAGE_PLIST_SHA):
  raise ValueError('EXACT_STAGE_COMPAT_IDENTITY_REQUIRED')
 manifest=json.loads(mp.read_bytes());candidate=manifest['candidate'];inv=manifest['application_inventory']
 if (manifest['schema_version']!='v4.release_candidate.v1' or candidate['release_id']!=args['release_id']
     or candidate['app_root']!=str(root) or args.get('application_inventory_sha256',inv['aggregate_sha256'])!=inv['aggregate_sha256']):raise ValueError('STAGE_MANIFEST_IDENTITY_DRIFT')
 actual,excluded=declared_cache_proof(root,manifest)
 role,contract=generic._module_manifest_identity(root,candidate)
 if role!='gateway':raise ValueError('STAGE_MODULE_ROLE_DRIFT')
 return dict(release_root=str(root.parent),app_root=str(root),release_id=args['release_id'],release_manifest_path=str(mp),
  release_manifest_sha256=STAGE_MANIFEST_SHA,application_inventory_sha256=inv['aggregate_sha256'],application_inventory_entry_count=len(inv['entries']),
  generated_bytecode_cache_exclusions=excluded,generated_bytecode_cache_exclusion_sha256=inventory_digest(excluded),
  module_role=role,module_contract_sha256=contract,manifest=manifest,inventory=actual,exact_stage_cache_compat=True)

def install_stage_compat():generic._release_identity=exact_stage_identity

def sources():
 raw=SOURCE_RECEIPT.read_bytes()
 if sha(raw)!=SOURCE_RECEIPT_SHA:raise ValueError('US_REVIEWED_SOURCE_RECEIPT_DRIFT')
 entries=[dict(path=x['path'],before_sha256=x['before_sha256'],after_sha256=x['after_sha256']) for x in json.loads(raw)['scope'] if x['path'] in BUSINESS]
 if {x['path'] for x in entries}!=BUSINESS:raise ValueError('EXACT_THREE_SOURCE_SCOPE_REQUIRED')
 for x in entries:
  if sha((ROOT/x['path']).read_bytes())!=x['after_sha256']:raise ValueError('REVIEWED_SOURCE_DRIFT:'+x['path'])
 return sorted(entries,key=lambda x:x['path'])

def prepare_config(raw,product_path,product_sha,cutoff):
 from datetime import datetime
 from v4.manager_workbench.config import WorkbenchConfig
 from v4.manager_workbench.contracts import RunContext
 from v4.manager_workbench.inputs.native import NativeAdapters
 old=json.loads(raw);new=copy.deepcopy(old)
 if old.get('scheduled_lanes')!=['US_MAPPING','OVERSOLD'] or old.get('capture_enabled') or old.get('capture_lease_token'):raise ValueError('PAUSED_CAPTURE_DISABLED_CONFIG_REQUIRED')
 if sha(product_path.read_bytes())!=product_sha:raise ValueError('FUTU94_PRODUCT_DRIFT')
 product=json.loads(product_path.read_bytes());bindings=product['bindings'];codes=[b['symbol'] for b in bindings]
 results=product.get('results',[])
 if (product.get('planned_count')!=94 or product.get('mother_scope_count')!=692 or len(results)!=94
     or any(r.get('status')!='READY' for r in results) or {r.get('code') for r in results}!=set(codes)
     or product.get('unprocessed_codes')!=[] or len(codes)!=94 or len(set(codes))!=94 or 'HK.00001' in codes):raise ValueError('EXACT_REVIEWED_FUTU94_REQUIRED')
 if datetime.fromisoformat(product['completed_at'])>datetime.fromisoformat(cutoff):raise ValueError('FUTU94_PRODUCT_AFTER_CUTOFF')
 slot=new['source_bindings']['hk_panel']['20261012'];previous=slot.get('futu_history',[])
 if len(previous)!=1 or previous[0]['symbol']!='HK.00001' or slot.get('tdxpy_history',{}).get('ready_count')!=568:raise ValueError('EXACT_EXISTING_00001_TDX568_REQUIRED')
 adapter=NativeAdapters(WorkbenchConfig.model_validate(old));context=RunContext(target_date='20261013',phase='RETROSPECTIVE',trigger='MANUAL',cutoff=cutoff,source_sessions={'hk_price':'20261012'},rules_version=old['rules_version'])
 for binding in [*previous,*bindings]:adapter._futu_history(context,binding,'20261012')
 slot['futu_history']=[*previous,*bindings]
 WorkbenchConfig.model_validate(new)
 allowed=copy.deepcopy(old);allowed['source_bindings']['hk_panel']['20261012']['futu_history']=[*previous,*bindings]
 if new!=allowed or new['state_root']!=old['state_root']:raise ValueError('CONFIG_NON_FUTU_BINDING_CHANGE')
 return new,dict(product_ref=str(product_path),product_sha256=product_sha,ready_count=94,unassessed_count=30,mother_scope_count=692,expected_assessed_count=662,cutoff=cutoff,preserved_00001=True,preserved_tdx568=True)

def prepare(out,*,cutoff,review_receipt,review_receipt_sha256):
 if not out.is_relative_to(HERE) or out.exists():raise ValueError('NEW_HANDOFF_OUTPUT_REQUIRED')
 files=sources()
 baseline_path=HERE/"remaining-gaps-v11-active-base-r1.json"
 if sha(baseline_path.read_bytes())!=BASE_RECEIPT_SHA:raise ValueError('EXACT_STAGE_BASE_RECEIPT_DRIFT')
 baseline=json.loads(baseline_path.read_bytes())
 review_bytes=review_receipt.read_bytes()
 if review_receipt_sha256!=US_REVIEW_SHA or sha(review_bytes)!=US_REVIEW_SHA:raise ValueError('INDEPENDENT_REVIEW_RECEIPT_DRIFT')
 review=json.loads(review_bytes)
 if review.get('status')!='PASS' or review.get('implementation_receipt_sha256')!=SOURCE_RECEIPT_SHA:raise ValueError('US_INDEPENDENT_PASS_REQUIRED')
 target=FORMAL/'config/manager-workbench-v7.json';cfg_raw=target.read_bytes()
 if sha(cfg_raw)!=baseline['formal_config_sha256']:raise ValueError('EXACT_STAGE_CONFIG_PREIMAGE_REQUIRED')
 newcfg,binding_summary=prepare_config(cfg_raw,FUTU_PRODUCT,FUTU_PRODUCT_SHA,cutoff)
 if sha(FUTU_REVIEW.read_bytes())!=FUTU_REVIEW_SHA:raise ValueError("FUTU94_REVIEW_RECEIPT_DRIFT")
 install_stage_compat()
 with shared_api_release_lock(API) as lease:
  active=generic.read_active_release(API);sraw=SCHED.read_bytes();splist=plistlib.loads(sraw);senv=splist['EnvironmentVariables'];sroot=Path(senv['V35_APP_ROOT']);smanifest=Path(senv['V35_RELEASE_MANIFEST_PATH'])
  if sha(smanifest.read_bytes())!=senv['V35_RELEASE_MANIFEST_SHA256']:raise ValueError('SCHEDULER_MANIFEST_DRIFT')
  sinv=inventory_tree(sroot)
  if sinv!=json.loads(smanifest.read_text())['application_inventory']['entries']:raise ValueError('SCHEDULER_INVENTORY_DRIFT')
  araw=API.read_bytes();base=dict(api=_base_binding(active),api_plist_sha256=sha(araw),scheduler=dict(app_root=str(sroot),plist_sha256=sha(sraw),manifest_path=str(smanifest),manifest_sha256=sha(smanifest.read_bytes()),inventory_sha256=inventory_digest(sinv)))
  if base!=baseline['base']:raise ValueError('EXACT_STAGE_ACTIVE_BASE_DRIFT')
  payload={}
  for item in files:
   rel=item['path'];raw=(ROOT/rel).read_bytes()
   if sha(raw)!=item['after_sha256']:raise ValueError('REVIEWED_SOURCE_DRIFT:'+rel)
   for root in (Path(active['app_root']),sroot,CANONICAL):
    observed=sha((root/rel).read_bytes()) if (root/rel).exists() else None
    expected=item['before_sha256']
    if observed!=expected:raise ValueError('BASE_FILE_DRIFT:'+str(root/rel))
   payload[rel]=raw
  out.mkdir(parents=True);source=out/'delta-source';source.mkdir();entries=[]
  for rel in sorted(payload):
   p=source/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(payload[rel]);before=(Path(active['app_root'])/rel).read_bytes();diff,hunks=_diff_proof(before,payload[rel])
   entries.append(dict(path=rel,before_sha256=sha(before),after_sha256=sha(payload[rel]),unified_diff_sha256=diff,unified_diff_hunk_count=hunks))
  delta=out/'api-delta.json';dump(delta,dict(schema_version=DELTA_SCHEMA_VERSION,base=_base_binding(active),entries=entries))
  acandidate=out/'manager-workbench-20261013-v11-api';acandidate.mkdir();result=build_integrated_app(active_api_plist_path=API,source_root=source,candidate_root=acandidate,delta_receipt_path=delta,explicit_untracked_paths=[])
  scandidate=out/'manager-workbench-20261013-v11-scheduler/app';shutil.copytree(sroot,scandidate,symlinks=True)
  spayload=payload
  from ops.api_release_integration import _candidate_parent_writable
  for rel,raw in spayload.items():
   with _candidate_parent_writable(scandidate,rel) as p:
    if p.exists():p.chmod(stat.S_IMODE(p.stat().st_mode)|stat.S_IWUSR)
    p.write_bytes(raw)
  after=inventory_tree(scandidate);unchanged={e['path']:e for e in after if e['path'] not in spayload}
  if unchanged!={e['path']:e for e in sinv if e['path'] not in spayload}:raise ValueError('SCHEDULER_NON_DELTA_DRIFT')
  apps={'api':acandidate/'app','scheduler':scandidate};manifest_shas={}
  for role,app in apps.items():
   inv=inventory_tree(app);manifest=dict(schema_version='v4.release_candidate.v1',candidate_status='PREPARED',deployment_status='NOT_DEPLOYED',candidate=dict(root=str(app.parent),app_root=str(app),release_id='manager-workbench-20261013-v11-'+role,module_role='gateway' if role=='api' else 'scheduler',module_contract_sha256=None),application_inventory=dict(entries=inv,aggregate_sha256=inventory_digest(inv),entry_count=len(inv)),verification_gaps=['Formal cutover and natural slot NOT_RUN'])
   manifest['api_integration' if role=='api' else 'scheduler_integration']=result if role=='api' else dict(base=base['scheduler'],delta_entries=[dict(path=rel,before_sha256=sha((sroot/rel).read_bytes()) if (sroot/rel).exists() else None,after_sha256=sha(raw)) for rel,raw in sorted(spayload.items())])
   mp=app.parent/'release-manifest.json';dump(mp,manifest);manifest_shas[role]=sha(mp.read_bytes())
  for excluded in active.get('generated_bytecode_cache_exclusions',[]):
   p=acandidate/'app'/excluded['path']
   if sha(p.read_bytes())!=excluded['sha256']:raise ValueError('STAGE_CACHE_COPY_DRIFT')
  verify_api_release_candidate(candidate_root=acandidate,active_api_plist_path=API,expected_manifest_sha256=manifest_shas['api'],lock_lease=lease,require_shared_lock=lease is not None)
  plan_entries=[];pairs=[]
  def append(kind,src,dst):
   before=dst.read_bytes() if dst.exists() else None;backup=out/'before'/str(len(plan_entries)) if before is not None else None
   if backup:backup.parent.mkdir(exist_ok=True);backup.write_bytes(before)
   plan_entries.append(dict(kind=kind,source=str(src),target=str(dst),before_sha256=sha(before) if before is not None else None,after_sha256=sha(src.read_bytes()),backup=str(backup) if backup else None))
  config=out/'manager-workbench-v11.json';dump(config,newcfg);append('config',config,target)
  for item in files:append('canonical',source/item['path'],CANONICAL/item['path'])
  plists=out/'plists';plists.mkdir()
  for role,path,raw in [('api',API,araw),('scheduler',SCHED,sraw)]:
   old=plistlib.loads(raw);new=copy.deepcopy(old);app=apps[role];oldapp=active['app_root'] if role=='api' else str(sroot)
   fields=dict(V35_APP_ROOT=str(app),V35_RELEASE_ID='manager-workbench-20261013-v11-'+role,V35_RELEASE_MANIFEST_PATH=str(app.parent/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=manifest_shas[role],V4_MANAGER_WORKBENCH_CONFIG_PATH=str(target))
   env=new.setdefault('EnvironmentVariables',{});assign=set();args=new['ProgramArguments']
   for i,arg in enumerate(args):
    if '=' in arg and not arg.startswith('--'):
     key,text=arg.split('=',1);assign.add(key)
     if key in fields:args[i]=key+'='+fields[key]
     elif key=='PYTHONPATH':args[i]=key+'='+text.replace(oldapp,str(app))
    elif role=='scheduler' and arg==oldapp+'/ops/launch_v35_macos_scheduler.sh':args[i]=str(app/'ops/launch_v35_macos_scheduler.sh')
   for key,text in fields.items():
    if key not in assign or key in env:env[key]=text
   if 'PYTHONPATH' in env:env['PYTHONPATH']=env['PYTHONPATH'].replace(oldapp,str(app))
   if new.get('WorkingDirectory')==oldapp:new['WorkingDirectory']=str(app)
   original=plists/(role+'-original.plist');staged=plists/(role+'-v11.plist');original.write_bytes(raw);staged.write_bytes(plistlib.dumps(new,sort_keys=False))
   pairs.append(dict(role=role,label=old['Label'],formal_path=str(path),original=str(original),original_sha256=sha(raw),staged=str(staged),staged_sha256=sha(staged.read_bytes())));append('plist',staged,path)
  if target.read_bytes()!=cfg_raw:raise ValueError('FORMAL_CONFIG_PARALLEL_DRIFT')
  if API.read_bytes()!=araw or SCHED.read_bytes()!=sraw or inventory_tree(sroot)!=sinv or generic.read_active_release(API)['application_inventory_sha256']!=active['application_inventory_sha256']:raise ValueError('ACTIVE_PARALLEL_DRIFT')
  plan=dict(status='PREPARED_NOT_EXECUTED',candidate_api=str(apps['api']),candidate_scheduler=str(apps['scheduler']),api_manifest_sha256=manifest_shas['api'],scheduler_manifest_sha256=manifest_shas['scheduler'],plists=pairs,entries=plan_entries,capture_enabled=False,scheduled_lanes=['US_MAPPING','OVERSOLD'],formal_state_changed=False,base=base,futu_summary=binding_summary,review_receipt=dict(path=str(review_receipt),sha256=review_receipt_sha256))
  validate(plan,'apply');pp=out/'operator-plan.json';dump(pp,plan)
  receipt=dict(status='PREPARED_DRY_RUN_PASS',plan=str(pp),plan_sha256=sha(pp.read_bytes()),candidate_manifests=manifest_shas,delta_files=files,api_non_delta_preserved=True,scheduler_non_delta_preserved=True,formal_writes=0,services_changed=False,api_delta_paths=sorted(payload),scheduler_delta_paths=sorted(spayload),canonical_sync_paths=[x['path'] for x in files],futu_summary=binding_summary,futu_independent_receipt=dict(path=str(FUTU_REVIEW),sha256=FUTU_REVIEW_SHA),approved_base_receipt=dict(path=str(baseline_path),sha256=BASE_RECEIPT_SHA),stage_cache_compat_exclusions=active.get('generated_bytecode_cache_exclusions',[]))
  dump(out/'receipt.json',receipt);print(json.dumps(receipt))
def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
 q=sub.add_parser('prepare');q.add_argument('--output',type=Path,required=True);q.add_argument('--cutoff',required=True);q.add_argument('--review-receipt',type=Path,required=True);q.add_argument('--review-receipt-sha256',required=True)
 o=sub.add_parser('operate');o.add_argument('--plan',required=True);o.add_argument('--plan-sha256',required=True);o.add_argument('--operation',choices=['apply','rollback'],default='apply');o.add_argument('--execute',action='store_true')
 a=p.parse_args()
 install_stage_compat()
 if a.mode=='prepare':prepare(a.output.resolve(),cutoff=a.cutoff,review_receipt=a.review_receipt,review_receipt_sha256=a.review_receipt_sha256)
 else:
  import operate_scheduled_lanes_v8 as op
  sys.argv=[str(HERE/'operate_scheduled_lanes_v8.py'),'--plan',a.plan,'--plan-sha256',a.plan_sha256,'--mode',a.operation]+(['--execute'] if a.execute else [])
  op.main()
if __name__=='__main__':main()
