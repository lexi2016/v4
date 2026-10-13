"""Exact reviewed US classification delta and manager asset closure; never apply by default."""
from pathlib import Path
import argparse,copy,hashlib,json,plistlib,re,shutil,sys,stat
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
import ops.api_release_integration as generic
from ops.api_release_integration import (_base_binding,_diff_proof,DELTA_SCHEMA_VERSION,build_integrated_app,
 inventory_tree,inventory_digest,shared_api_release_lock,verify_api_release_candidate)
from operate_v7_cutover import validate,API,SCHED
from prepare_v7_operator import FORMAL,CANONICAL
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
SOURCE_RECEIPT=HERE/'us29-closure-implementation-r1.json'
SOURCE_RECEIPT_SHA='b4d3f3b5663d535d07839669a01578fd03778690725b768da83bf9e88c12b075'
BASE_RECEIPT_SHA='52912e3cf866cec47cabb1221c71f1131ac518f08572d6d7c57ce34b87ee62bf'
SOURCES={'v4/manager_workbench/inputs/source_bindings.py','v4/manager_workbench/inputs/native.py','v4/manager_workbench/engines/us_mapping.py','apps/web/src/manager-workbench/display.ts',
 'v4/manager_workbench/research_data/us_mapping_relation_evidence_20261013_v3.json','v4/manager_workbench/research_data/us_mapping_relation_evidence_review_20261013_v3.json'}
API_COMPAT_ROOT=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-pool-labels-20261014-r1/app')
API_COMPAT_PLIST_SHA='216d2083f7eab672664f4e8c2adfee4b852980c707f36384dbae7380cf488756'
API_COMPAT_MANIFEST_SHA='10caba13acb78d8d0f3be119ed477812fca41d2ad55fe2c5bc87f25d66dc424f'
API_COMPAT_ACTUAL_DIGEST='dc98f11aec8e258fc37909607347c936f0b02bb237baa9ea8bd89565801cb0cd'
ORIGINAL_IDENTITY=generic._release_identity
INHERITED_DATA={
 'v4/manager_research/us_mapping_relation_evidence_20261011.json':'69e09810a8c5fcaa52cf1b16d339756b67a6ea6c8eb7837c440bea86fdaebfb0',
 'v4/manager_research/us_mapping_relation_evidence_review_20261011.json':'5e24b82049ca848f7536b084166537415722375414cfc762da8b179919947350',
 'v4/manager_research/us_mapping_reviewed_20260930.json':'e6108eca9f30a44a96674941ffc7b44557d44a4f3cbe17983d96d1de23ca956a',
 'v4/manager_research/us_mapping_relation_registry.json':'ffd6ff853eb69a8329c18cf5ac77745ac08f14905279036e494c34eb0b55b3fe'}

def inherited_data(api_root,scheduler_root):
 pending={}
 for rel,expected in INHERITED_DATA.items():
  raw=(CANONICAL/rel).read_bytes()
  if sha(raw)!=expected or sha((api_root/rel).read_bytes())!=expected:
   raise ValueError('INHERITED_DATA_SHA_DRIFT:'+rel)
  target=scheduler_root/rel
  if target.exists():
   if sha(target.read_bytes())!=expected:raise ValueError('INHERITED_SCHEDULER_DATA_DRIFT:'+rel)
  else:pending[rel]=raw
 return pending

def exact_api_identity(**args):
 root=Path(args['app_root'])
 if root!=API_COMPAT_ROOT:return ORIGINAL_IDENTITY(**args)
 path=Path(args['manifest_path']);raw=path.read_bytes()
 if (sha(API.read_bytes())!=API_COMPAT_PLIST_SHA or sha(raw)!=API_COMPAT_MANIFEST_SHA
     or args['manifest_sha256']!=API_COMPAT_MANIFEST_SHA or path!=root.parent/'release-manifest.json'
     or Path(args['release_root'])!=root.parent or args['release_id']!=root.parent.name):
  raise ValueError('EXACT_API_COMPATIBILITY_IDENTITY_DRIFT')
 manifest=json.loads(raw);candidate=manifest['candidate'];inv=manifest['application_inventory'];actual,excluded=generic._inventory_tree_with_generated_cache(root)
 if (manifest.get('schema_version')!='v4.release_candidate.v1' or candidate.get('app_root')!=str(root)
     or candidate.get('release_id')!=root.parent.name or inv['entries']!=actual
     or inventory_digest(actual)!=API_COMPAT_ACTUAL_DIGEST or inv['entry_count']!=len(actual)
     or args.get('application_inventory_sha256',API_COMPAT_ACTUAL_DIGEST)!=API_COMPAT_ACTUAL_DIGEST):
  raise ValueError('EXACT_API_COMPATIBILITY_INVENTORY_DRIFT')
 role,contract=generic._module_manifest_identity(root,candidate)
 return dict(release_root=str(root.parent),app_root=str(root),release_id=root.parent.name,release_manifest_path=str(path),
  release_manifest_sha256=sha(raw),application_inventory_sha256=inventory_digest(actual),application_inventory_entry_count=len(actual),
  generated_bytecode_cache_exclusions=excluded,generated_bytecode_cache_exclusion_sha256=inventory_digest(excluded),
  module_role=role,module_contract_sha256=contract,manifest=manifest,inventory=actual,
  fixed_declared_aggregate=inv['aggregate_sha256'],exact_api_aggregate_compat=True)

def sources():
 raw=SOURCE_RECEIPT.read_bytes()
 if sha(raw)!=SOURCE_RECEIPT_SHA:raise ValueError('US_SOURCE_RECEIPT_DRIFT')
 receipt=json.loads(raw);entries=[dict(path=p,before_sha256=receipt['before_sha256'].get(p),after_sha256=receipt['after_sha256'][p]) for p in SOURCES]
 for x in entries:
  if sha((ROOT/x['path']).read_bytes())!=x['after_sha256']:raise ValueError('US_SOURCE_DRIFT:'+x['path'])
 return sorted(entries,key=lambda x:x['path'])

def manager_assets(dist):
 pending=[dist/'manager-selection/index.html'];paths={};seen=set()
 while pending:
  path=pending.pop()
  if path in seen:continue
  if not path.is_relative_to(dist) or path.is_symlink() or not path.is_file():raise ValueError('MANAGER_ASSET_DEPENDENCY_MISSING')
  seen.add(path);paths['apps/web/dist/'+path.relative_to(dist).as_posix()]=path.read_bytes()
  for filename in re.findall(r'[A-Za-z0-9_.-]+\.(?:js|css|woff2?|svg|png)',path.read_text()):
   dependency=dist/'assets'/filename
   if dependency.is_file() and dependency not in seen:pending.append(dependency)
 return paths
def scheduler_inventory(root, plist_raw, manifest_raw, actual, compatibility):
 # Compatibility is bounded to the fixed parallel release and three exact subtrees.
 declared=json.loads(manifest_raw)['application_inventory']['entries']
 if declared==actual:return actual
 prefixes=['upstreams/review_core','upstreams/v3.5','v3_shared_data']
 if (str(root)!=compatibility['root'] or sha(plist_raw)!=compatibility['plist_sha256']
     or sha(manifest_raw)!=compatibility['manifest_sha256'] or compatibility['prefixes']!=prefixes):
  raise ValueError('EXACT_SCHEDULER_COMPATIBILITY_IDENTITY_DRIFT')
 inside=lambda p:any(p==x or p.startswith(x+'/') for x in prefixes)
 if [x for x in declared if not inside(x['path'])]!=[x for x in actual if not inside(x['path'])]:
  raise ValueError('SCHEDULER_NON_COMPATIBLE_SOURCE_DRIFT')
 subtree=[x for x in actual if inside(x['path'])]
 if ([x for x in declared if inside(x['path'])]!=compatibility['declared_entries']
     or subtree!=compatibility['actual_entries']
     or inventory_digest(subtree)!=compatibility['actual_subtree_digest']
     or inventory_digest(actual)!=compatibility['actual_full_inventory_digest']):
  raise ValueError('SCHEDULER_FIXED_DIRECTORY_BYTES_DRIFT')
 return actual

def prepare(out):
 if not out.is_relative_to(HERE) or out.exists():raise ValueError('NEW_HANDOFF_OUTPUT_REQUIRED')
 files=sources()
 baseline_path=HERE/"us29-closure-v14-base-r1.json"
 if sha(baseline_path.read_bytes())!=BASE_RECEIPT_SHA:raise ValueError('EXACT_STAGE_BASE_RECEIPT_DRIFT')
 baseline=json.loads(baseline_path.read_bytes())
 target=FORMAL/'config/manager-workbench-v7.json';cfg_raw=target.read_bytes()
 if sha(cfg_raw)!=baseline['formal_config_sha256']:raise ValueError('EXACT_STAGE_CONFIG_PREIMAGE_REQUIRED')
 with shared_api_release_lock(API) as lease:
  active=generic.read_active_release(API);sraw=SCHED.read_bytes();splist=plistlib.loads(sraw);senv=splist['EnvironmentVariables'];sroot=Path(senv['V35_APP_ROOT']);smanifest=Path(senv['V35_RELEASE_MANIFEST_PATH'])
  if sha(smanifest.read_bytes())!=senv['V35_RELEASE_MANIFEST_SHA256']:raise ValueError('SCHEDULER_MANIFEST_DRIFT')
  sinv=inventory_tree(sroot)
  if json.loads(smanifest.read_bytes())['application_inventory']['entries']!=sinv:raise ValueError('STRICT_SCHEDULER_INVENTORY_DRIFT')
  if json.loads(smanifest.read_bytes())['application_inventory']['aggregate_sha256']!=inventory_digest(sinv):raise ValueError('STRICT_SCHEDULER_DIGEST_DRIFT')
  araw=API.read_bytes();base=dict(api=_base_binding(active),api_plist_sha256=sha(araw),scheduler=dict(app_root=str(sroot),plist_sha256=sha(sraw),manifest_path=str(smanifest),manifest_sha256=sha(smanifest.read_bytes()),inventory_sha256=inventory_digest(sinv)))
  if base!=baseline['base']:raise ValueError('EXACT_STAGE_ACTIVE_BASE_DRIFT')
  inherited_payload=inherited_data(Path(active['app_root']),sroot)
  payload={}
  for item in files:
   rel=item['path'];raw=(ROOT/rel).read_bytes()
   if sha(raw)!=item['after_sha256']:raise ValueError('REVIEWED_SOURCE_DRIFT:'+rel)
   for root in (Path(active['app_root']),sroot,CANONICAL):
    if root==sroot and not rel.startswith('v4/manager_workbench/'):continue
    observed=sha((root/rel).read_bytes()) if (root/rel).exists() else None
    expected=item['before_sha256']
    if observed!=expected:raise ValueError('BASE_FILE_DRIFT:'+str(root/rel))
   payload[rel]=raw
  payload.update(manager_assets(HERE/'.tmp/us29-closure-web-build-r1'))
  payload={rel:raw for rel,raw in payload.items() if not (Path(active['app_root'])/rel).exists() or (Path(active['app_root'])/rel).read_bytes()!=raw}
  out.mkdir(parents=True);source=out/'delta-source';source.mkdir();entries=[]
  for rel in sorted(payload):
   p=source/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(payload[rel]);before=(Path(active['app_root'])/rel).read_bytes() if (Path(active['app_root'])/rel).exists() else None;diff,hunks=_diff_proof(before,payload[rel]) if before is not None else (None,None)
   entries.append(dict(path=rel,before_sha256=sha(before) if before is not None else None,after_sha256=sha(payload[rel]),unified_diff_sha256=diff,unified_diff_hunk_count=hunks))
  delta=out/'api-delta.json';dump(delta,dict(schema_version=DELTA_SCHEMA_VERSION,base=_base_binding(active),entries=entries))
  acandidate=out/'manager-workbench-20261013-v14-api';acandidate.mkdir();result=build_integrated_app(active_api_plist_path=API,source_root=source,candidate_root=acandidate,delta_receipt_path=delta,explicit_untracked_paths=[e["path"] for e in entries if e["before_sha256"] is None])
  scandidate=out/'manager-workbench-20261013-v14-scheduler/app';shutil.copytree(sroot,scandidate,symlinks=True)
  spayload={rel:raw for rel,raw in payload.items() if rel.startswith("v4/manager_workbench/")}
  spayload.update(inherited_payload)
  from ops.api_release_integration import _candidate_parent_writable
  for rel,raw in spayload.items():
   with _candidate_parent_writable(scandidate,rel) as p:
    if p.exists():p.chmod(stat.S_IMODE(p.stat().st_mode)|stat.S_IWUSR)
    p.write_bytes(raw)
  after=inventory_tree(scandidate);unchanged={e['path']:e for e in after if e['path'] not in spayload}
  if unchanged!={e['path']:e for e in sinv if e['path'] not in spayload}:raise ValueError('SCHEDULER_NON_DELTA_DRIFT')
  apps={'api':acandidate/'app','scheduler':scandidate};manifest_shas={}
  for role,app in apps.items():
   inv=inventory_tree(app);manifest=dict(schema_version='v4.release_candidate.v1',candidate_status='PREPARED',deployment_status='NOT_DEPLOYED',candidate=dict(root=str(app.parent),app_root=str(app),release_id='manager-workbench-20261013-v14-'+role,module_role='gateway' if role=='api' else 'scheduler',module_contract_sha256=None),application_inventory=dict(entries=inv,aggregate_sha256=inventory_digest(inv),entry_count=len(inv)),verification_gaps=['Formal cutover and natural slot NOT_RUN'])
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
  config=out/'manager-workbench-v14.json';cfg=json.loads(cfg_raw);cfg['relation_evidence_relative']='v4/manager_workbench/research_data/us_mapping_relation_evidence_20261013_v3.json';cfg['relation_review_relative']='v4/manager_workbench/research_data/us_mapping_relation_evidence_review_20261013_v3.json'
  from v4.manager_workbench.config import WorkbenchConfig
  WorkbenchConfig.model_validate(cfg)
  dump(config,cfg);append('config',config,target)
  for item in files:append('canonical',source/item['path'],CANONICAL/item['path'])
  plists=out/'plists';plists.mkdir()
  for role,path,raw in [('api',API,araw),('scheduler',SCHED,sraw)]:
   old=plistlib.loads(raw);new=copy.deepcopy(old);app=apps[role];oldapp=active['app_root'] if role=='api' else str(sroot)
   fields=dict(V35_APP_ROOT=str(app),V35_RELEASE_ID='manager-workbench-20261013-v14-'+role,V35_RELEASE_MANIFEST_PATH=str(app.parent/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=manifest_shas[role],V4_MANAGER_WORKBENCH_CONFIG_PATH=str(target))
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
   original=plists/(role+'-original.plist');staged=plists/(role+'-v14.plist');original.write_bytes(raw);staged.write_bytes(plistlib.dumps(new,sort_keys=False))
   pairs.append(dict(role=role,label=old['Label'],formal_path=str(path),original=str(original),original_sha256=sha(raw),staged=str(staged),staged_sha256=sha(staged.read_bytes())));append('plist',staged,path)
  if target.read_bytes()!=cfg_raw:raise ValueError('FORMAL_CONFIG_PARALLEL_DRIFT')
  if API.read_bytes()!=araw or SCHED.read_bytes()!=sraw or inventory_tree(sroot)!=sinv or generic.read_active_release(API)['application_inventory_sha256']!=active['application_inventory_sha256']:raise ValueError('ACTIVE_PARALLEL_DRIFT')
  plan=dict(status='PREPARED_NOT_EXECUTED',candidate_api=str(apps['api']),candidate_scheduler=str(apps['scheduler']),api_manifest_sha256=manifest_shas['api'],scheduler_manifest_sha256=manifest_shas['scheduler'],plists=pairs,entries=plan_entries,capture_enabled=False,scheduled_lanes=['US_MAPPING','OVERSOLD'],formal_state_changed=False,base=base,display_source_receipt=dict(path=str(SOURCE_RECEIPT),sha256=SOURCE_RECEIPT_SHA))
  validate(plan,'apply');pp=out/'operator-plan.json';dump(pp,plan)
  receipt=dict(status='PREPARED_DRY_RUN_PASS',plan=str(pp),plan_sha256=sha(pp.read_bytes()),candidate_manifests=manifest_shas,delta_files=files,api_non_delta_preserved=True,scheduler_non_delta_preserved=True,formal_writes=0,services_changed=False,api_delta_paths=sorted(payload),scheduler_delta_paths=sorted(spayload),canonical_sync_paths=[x['path'] for x in files],approved_base_receipt=dict(path=str(baseline_path),sha256=BASE_RECEIPT_SHA),frontend_assets=[rel for rel in payload if rel.startswith('apps/web/dist/')],fixed_api_aggregate_compatibility=dict(root=str(API_COMPAT_ROOT),plist_sha256=API_COMPAT_PLIST_SHA,manifest_sha256=API_COMPAT_MANIFEST_SHA,declared_aggregate=active['fixed_declared_aggregate'],actual_aggregate=API_COMPAT_ACTUAL_DIGEST,declared_entries_exactly_equal_actual=True),formal_config_only_us_evidence_bindings_changed=True,rules_version='POSITIVE_OPERATING_RESEARCH_V1_OVERSOLD_PRICE40_V2')
  receipt['inherited_scheduler_data_closure']=[dict(path=rel,source=str(CANONICAL/rel),sha256=sha(raw),purpose='Read-only v3 original evidence/review and reviewed seed provenance; no legacy business import') for rel,raw in sorted(inherited_payload.items())]
  receipt['runtime_relation_root']=cfg['relation_root']
  dump(out/'receipt.json',receipt);print(json.dumps(receipt))
def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
 q=sub.add_parser('prepare');q.add_argument('--output',type=Path,required=True)
 o=sub.add_parser('operate');o.add_argument('--plan',required=True);o.add_argument('--plan-sha256',required=True);o.add_argument('--operation',choices=['apply','rollback'],default='apply');o.add_argument('--execute',action='store_true')
 a=p.parse_args()
 generic._release_identity=exact_api_identity
 if a.mode=='prepare':prepare(a.output.resolve())
 else:
  import operate_scheduled_lanes_v8 as op
  sys.argv=[str(HERE/'operate_scheduled_lanes_v8.py'),'--plan',a.plan,'--plan-sha256',a.plan_sha256,'--mode',a.operation]+(['--execute'] if a.execute else [])
  op.main()
if __name__=='__main__':main()
