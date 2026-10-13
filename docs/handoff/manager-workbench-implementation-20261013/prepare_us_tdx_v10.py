"""Prepare the reviewed panel-first five-source delta on active V8; no activation."""
from pathlib import Path
import argparse,copy,hashlib,json,plistlib,shutil,sys,stat
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
from ops.api_release_integration import (read_active_release,_base_binding,_diff_proof,DELTA_SCHEMA_VERSION,
 build_integrated_app,inventory_tree,inventory_digest,shared_api_release_lock,verify_api_release_candidate)
from operate_v7_cutover import validate,API,SCHED
from prepare_v7_operator import FORMAL,CANONICAL
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
OWNER='upstreams/v3_shared_data/shared_data/hk_daily_supplement.py'
MIRROR='v3_shared_data/shared_data/hk_daily_supplement.py'
BUSINESS={'v4/manager_workbench/inputs/native.py','v4/manager_workbench/inputs/source_bindings.py','v4/manager_workbench/engines/us_mapping.py','v4/manager_workbench/engines/oversold.py',OWNER}

def install_exact_owner_guard():
 import operate_v7_cutover as operator
 original=operator.allowed_source
 operator.allowed_source=lambda rel:rel==OWNER or original(rel)
 return original

def sources(receipt_path,receipt_sha256):
 raw=receipt_path.read_bytes()
 if sha(raw)!=receipt_sha256:raise ValueError('TDXPY_REVIEWED_SOURCE_RECEIPT_DRIFT')
 reviewed=json.loads((HERE/'us-oversold-adapter-futu-r1.json').read_text())
 entries={x['path']:dict(path=x['path'],before_sha256=x['formal_v7_sha256'],after_sha256=x['after_sha256']) for x in reviewed['scope']}
 panel_first=json.loads(raw)
 updates=panel_first.get('files')
 needed=BUSINESS-{'v4/manager_workbench/engines/us_mapping.py'}
 if not isinstance(updates,dict) or not needed.issubset(updates):raise ValueError('PANEL_FIRST_SOURCE_RECEIPT_REQUIRED')
 for rel in needed:
  current=updates[rel]
  if rel==OWNER:
   # This is the exact formal/canonical V8 owner preimage, not the preceding
   # worktree TDX candidate in the panel-priority receipt's before_sha256.
   entries[OWNER]=dict(path=OWNER,before_sha256='5528a6b44bfb5b79265732b85beb1fb89860355b48a852da07264fb34231c79c',after_sha256=current['after_sha256'])
  else:entries[rel]['after_sha256']=current['after_sha256']
 if set(entries)!=BUSINESS:raise ValueError('EXACT_FIVE_SOURCE_SCOPE_REQUIRED')
 for x in entries.values():
  if sha((ROOT/x['path']).read_bytes())!=x['after_sha256']:raise ValueError('REVIEWED_SOURCE_DRIFT:'+x['path'])
 return sorted(entries.values(),key=lambda x:x['path'])

def prepare_config(raw,pin_path,pin_sha256,cutoff):
 pin_bytes=pin_path.read_bytes()
 if sha(pin_bytes)!=pin_sha256:raise ValueError('TDXPY_PANEL_GAP_PIN_DRIFT')
 pin=json.loads(pin_bytes)
 import importlib.util
 spec=importlib.util.spec_from_file_location('v10_accepted_calendar',HERE/'recover_cached_full_date.py');runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime);runtime.install_runtime()
 from upstreams.v3_shared_data.shared_data.hk_daily_supplement import read_tdxpy_window_supplement,read_tdxpy_panel_identity,_read_master_identity
 old=json.loads(raw);new=copy.deepcopy(old);root=Path(old['shared_root'])
 panel=read_tdxpy_panel_identity(root,pin,'20261012');master,codes=_read_master_identity(root,'20261012')
 manifest,records=read_tdxpy_window_supplement(pin,target_date='20261012',cutoff=cutoff,expected_panel_sha=panel['panel_sha256'],
    expected_master_sha=master['artifact_sha256'],expected_codes=codes,expected_panel_manifest_sha=panel['panel_manifest_sha256'],expected_master_manifest_sha=master['manifest_sha256'])
 gaps=manifest.get('gap_codes')
 if (manifest.get('capture_scope')!='PANEL_GAPS' or manifest.get('master_code_count')!=692 or len(codes)!=692
     or not isinstance(gaps,list) or not gaps or gaps!=sorted(set(gaps)) or not set(gaps).issubset(codes)
     or manifest.get('code_count')!=len(gaps) or [r.get('code') for r in records]!=gaps
     or manifest.get('panel_valid_count')!=692-len(gaps) or manifest.get('projection_price_date')!='20261012'
     or not isinstance(manifest.get('panel_gap_plan_sha256'),str) or len(manifest['panel_gap_plan_sha256'])!=64):
  raise ValueError('EXACT_PANEL_GAPS_WITH_FULL692_MOTHER_REQUIRED')
 futu=json.loads((HERE/'.tmp/us-oversold-futu-prepared-r1/receipt.json').read_text())['single_response']
 for key,sha_key in [('raw_relative','raw_sha256'),('receipt_relative','receipt_sha256')]:
  if sha((Path(futu['source_local_path'])/futu[key]).read_bytes())!=futu[sha_key]:raise ValueError('PROVEN_FUTU_SOURCE_DRIFT')
 hk=new.setdefault('source_bindings',{}).setdefault('hk_panel',{}).setdefault('20261012',{})
 hk['futu_history']=[futu];hk['tdxpy_history']=pin
 if new.get('scheduled_lanes')!=['US_MAPPING','OVERSOLD'] or new.get('capture_enabled') or new.get('capture_lease_token'):raise ValueError('EXACT_PAUSED_CAPTURE_DISABLED_CONFIG_REQUIRED')
 from v4.manager_workbench.config import WorkbenchConfig
 WorkbenchConfig.model_validate(new)
 if new['state_root']!=old['state_root']:raise ValueError('FORMAL_STATE_ROOT_CHANGED')
 allowed=copy.deepcopy(old);slot=allowed.setdefault('source_bindings',{}).setdefault('hk_panel',{}).setdefault('20261012',{})
 slot['futu_history']=[futu];slot['tdxpy_history']=pin
 if new!=allowed:raise ValueError('CONFIG_NON_BINDING_CHANGE')
 return new,manifest

def prepare(out,*,pin_path,pin_sha256,cutoff,source_receipt,source_receipt_sha256,review_receipt,review_receipt_sha256):
 if not out.is_relative_to(HERE) or out.exists():raise ValueError('NEW_HANDOFF_OUTPUT_REQUIRED')
 files=sources(source_receipt,source_receipt_sha256)
 review_bytes=review_receipt.read_bytes()
 if sha(review_bytes)!=review_receipt_sha256:raise ValueError('INDEPENDENT_REVIEW_RECEIPT_DRIFT')
 target=FORMAL/'config/manager-workbench-v7.json';cfg_raw=target.read_bytes()
 if sha(cfg_raw)!='0a76879d1f658d326c54af5289f09ee2a42e51e0f9976da29df6a208d49ecd20':raise ValueError('EXACT_V8_CONFIG_PREIMAGE_REQUIRED')
 newcfg,tdx_manifest=prepare_config(cfg_raw,pin_path,pin_sha256,cutoff)
 install_exact_owner_guard()
 with shared_api_release_lock(API) as lease:
  active=read_active_release(API);sraw=SCHED.read_bytes();splist=plistlib.loads(sraw);senv=splist['EnvironmentVariables'];sroot=Path(senv['V35_APP_ROOT']);smanifest=Path(senv['V35_RELEASE_MANIFEST_PATH'])
  if sha(smanifest.read_bytes())!=senv['V35_RELEASE_MANIFEST_SHA256']:raise ValueError('SCHEDULER_MANIFEST_DRIFT')
  sinv=inventory_tree(sroot)
  if sinv!=json.loads(smanifest.read_text())['application_inventory']['entries']:raise ValueError('SCHEDULER_INVENTORY_DRIFT')
  araw=API.read_bytes();base=dict(api=_base_binding(active),api_plist_sha256=sha(araw),scheduler=dict(app_root=str(sroot),plist_sha256=sha(sraw),manifest_path=str(smanifest),manifest_sha256=sha(smanifest.read_bytes()),inventory_sha256=inventory_digest(sinv)))
  frozen_base=json.loads((HERE/'us-futu-v9-prepared-r1.json').read_bytes())['base']
  if base!=frozen_base:raise ValueError('EXACT_ACTIVE_V8_BASE_DRIFT')
  payload={}
  for item in files:
   rel=item['path'];raw=(ROOT/rel).read_bytes()
   if sha(raw)!=item['after_sha256']:raise ValueError('REVIEWED_SOURCE_DRIFT:'+rel)
   for root in (Path(active['app_root']),sroot,CANONICAL):
    observed=sha((root/rel).read_bytes()) if (root/rel).exists() else None
    expected=None if rel==OWNER and root==sroot else item['before_sha256']
    if observed!=expected:raise ValueError('BASE_FILE_DRIFT:'+str(root/rel))
   payload[rel]=raw
  if sha((Path(active['app_root'])/MIRROR).read_bytes())!=next(x['before_sha256'] for x in files if x['path']==OWNER):raise ValueError('OWNER_DEPLOYMENT_MIRROR_DRIFT')
  payload[MIRROR]=payload[OWNER]
  out.mkdir(parents=True);source=out/'delta-source';source.mkdir();entries=[]
  for rel in sorted(payload):
   p=source/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(payload[rel]);before=(Path(active['app_root'])/rel).read_bytes();diff,hunks=_diff_proof(before,payload[rel])
   entries.append(dict(path=rel,before_sha256=sha(before),after_sha256=sha(payload[rel]),unified_diff_sha256=diff,unified_diff_hunk_count=hunks))
  delta=out/'api-delta.json';dump(delta,dict(schema_version=DELTA_SCHEMA_VERSION,base=_base_binding(active),entries=entries))
  acandidate=out/'manager-workbench-20261013-v10-api';acandidate.mkdir();result=build_integrated_app(active_api_plist_path=API,source_root=source,candidate_root=acandidate,delta_receipt_path=delta,explicit_untracked_paths=[])
  scandidate=out/'manager-workbench-20261013-v10-scheduler/app';shutil.copytree(sroot,scandidate,symlinks=True)
  spayload={rel:raw for rel,raw in payload.items() if rel!=MIRROR}
  from ops.api_release_integration import _candidate_parent_writable
  for rel,raw in spayload.items():
   with _candidate_parent_writable(scandidate,rel) as p:
    if p.exists():p.chmod(stat.S_IMODE(p.stat().st_mode)|stat.S_IWUSR)
    p.write_bytes(raw)
  after=inventory_tree(scandidate);unchanged={e['path']:e for e in after if e['path'] not in spayload}
  if unchanged!={e['path']:e for e in sinv if e['path'] not in spayload}:raise ValueError('SCHEDULER_NON_DELTA_DRIFT')
  apps={'api':acandidate/'app','scheduler':scandidate};manifest_shas={}
  for role,app in apps.items():
   inv=inventory_tree(app);manifest=dict(schema_version='v4.release_candidate.v1',candidate_status='PREPARED',deployment_status='NOT_DEPLOYED',candidate=dict(root=str(app.parent),app_root=str(app),release_id='manager-workbench-20261013-v10-'+role,module_role='gateway' if role=='api' else 'scheduler',module_contract_sha256=None),application_inventory=dict(entries=inv,aggregate_sha256=inventory_digest(inv),entry_count=len(inv)),verification_gaps=['Formal cutover and natural slot NOT_RUN'])
   manifest['api_integration' if role=='api' else 'scheduler_integration']=result if role=='api' else dict(base=base['scheduler'],delta_entries=[dict(path=rel,before_sha256=sha((sroot/rel).read_bytes()) if (sroot/rel).exists() else None,after_sha256=sha(raw)) for rel,raw in sorted(spayload.items())])
   mp=app.parent/'release-manifest.json';dump(mp,manifest);manifest_shas[role]=sha(mp.read_bytes())
  verify_api_release_candidate(candidate_root=acandidate,active_api_plist_path=API,expected_manifest_sha256=manifest_shas['api'],lock_lease=lease,require_shared_lock=lease is not None)
  plan_entries=[];pairs=[]
  def append(kind,src,dst):
   before=dst.read_bytes() if dst.exists() else None;backup=out/'before'/str(len(plan_entries)) if before is not None else None
   if backup:backup.parent.mkdir(exist_ok=True);backup.write_bytes(before)
   plan_entries.append(dict(kind=kind,source=str(src),target=str(dst),before_sha256=sha(before) if before is not None else None,after_sha256=sha(src.read_bytes()),backup=str(backup) if backup else None))
  config=out/'manager-workbench-v10.json';dump(config,newcfg);append('config',config,target)
  for item in files:append('canonical',source/item['path'],CANONICAL/item['path'])
  plists=out/'plists';plists.mkdir()
  for role,path,raw in [('api',API,araw),('scheduler',SCHED,sraw)]:
   old=plistlib.loads(raw);new=copy.deepcopy(old);app=apps[role];oldapp=active['app_root'] if role=='api' else str(sroot)
   fields=dict(V35_APP_ROOT=str(app),V35_RELEASE_ID='manager-workbench-20261013-v10-'+role,V35_RELEASE_MANIFEST_PATH=str(app.parent/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=manifest_shas[role],V4_MANAGER_WORKBENCH_CONFIG_PATH=str(target))
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
   original=plists/(role+'-original.plist');staged=plists/(role+'-v10.plist');original.write_bytes(raw);staged.write_bytes(plistlib.dumps(new,sort_keys=False))
   pairs.append(dict(role=role,label=old['Label'],formal_path=str(path),original=str(original),original_sha256=sha(raw),staged=str(staged),staged_sha256=sha(staged.read_bytes())));append('plist',staged,path)
  if target.read_bytes()!=cfg_raw:raise ValueError('FORMAL_CONFIG_PARALLEL_DRIFT')
  if API.read_bytes()!=araw or SCHED.read_bytes()!=sraw or inventory_tree(sroot)!=sinv or read_active_release(API)['application_inventory_sha256']!=active['application_inventory_sha256']:raise ValueError('ACTIVE_PARALLEL_DRIFT')
  plan=dict(status='PREPARED_NOT_EXECUTED',candidate_api=str(apps['api']),candidate_scheduler=str(apps['scheduler']),api_manifest_sha256=manifest_shas['api'],scheduler_manifest_sha256=manifest_shas['scheduler'],plists=pairs,entries=plan_entries,capture_enabled=False,scheduled_lanes=['US_MAPPING','OVERSOLD'],formal_state_changed=False,base=base,tdx_panel_gap_pin_sha256=pin_sha256,tdx_panel_gap_manifest=tdx_manifest,review_receipt=dict(path=str(review_receipt),sha256=review_receipt_sha256))
  validate(plan,'apply');pp=out/'operator-plan.json';dump(pp,plan)
  receipt=dict(status='PREPARED_DRY_RUN_PASS',plan=str(pp),plan_sha256=sha(pp.read_bytes()),candidate_manifests=manifest_shas,delta_files=files,api_non_delta_preserved=True,scheduler_non_delta_preserved=True,formal_writes=0,services_changed=False,api_delta_paths=sorted(payload),scheduler_delta_paths=sorted(spayload),canonical_sync_paths=[x['path'] for x in files],tdx_pin_sha256=pin_sha256)
  dump(out/'receipt.json',receipt);print(json.dumps(receipt))
def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='mode',required=True)
 q=sub.add_parser('prepare');q.add_argument('--output',type=Path,required=True);q.add_argument('--tdx-pin',type=Path,required=True);q.add_argument('--tdx-pin-sha256',required=True);q.add_argument('--cutoff',required=True)
 q.add_argument('--source-receipt',type=Path,default=HERE/'panel-priority-implementation-r1.json');q.add_argument('--source-receipt-sha256',required=True)
 q.add_argument('--review-receipt',type=Path,required=True);q.add_argument('--review-receipt-sha256',required=True)
 o=sub.add_parser('operate');o.add_argument('--plan',required=True);o.add_argument('--plan-sha256',required=True);o.add_argument('--operation',choices=['apply','rollback'],default='apply');o.add_argument('--execute',action='store_true')
 a=p.parse_args()
 if a.mode=='prepare':prepare(a.output.resolve(),pin_path=a.tdx_pin.resolve(),pin_sha256=a.tdx_pin_sha256,cutoff=a.cutoff,source_receipt=a.source_receipt,source_receipt_sha256=a.source_receipt_sha256,review_receipt=a.review_receipt,review_receipt_sha256=a.review_receipt_sha256)
 else:
  install_exact_owner_guard()
  import operate_scheduled_lanes_v8 as op
  sys.argv=[str(HERE/'operate_scheduled_lanes_v8.py'),'--plan',a.plan,'--plan-sha256',a.plan_sha256,'--mode',a.operation]+(['--execute'] if a.execute else [])
  op.main()
if __name__=='__main__':main()
