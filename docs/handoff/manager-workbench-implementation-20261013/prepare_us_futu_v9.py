"""Prepare only the independently reviewed US/Futu four-source delta on active V8. Never activates."""
from pathlib import Path
import argparse,copy,hashlib,json,plistlib,shutil,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE))
from ops.api_release_integration import (read_active_release,_base_binding,_diff_proof,DELTA_SCHEMA_VERSION,
 build_integrated_app,inventory_tree,inventory_digest,shared_api_release_lock,verify_api_release_candidate)
from operate_v7_cutover import validate,API,SCHED
from prepare_v7_operator import FORMAL,CANONICAL
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def prepare(out):
 if not out.is_relative_to(HERE) or out.exists():raise ValueError('NEW_HANDOFF_OUTPUT_REQUIRED')
 reviewed=json.loads((HERE/'us-oversold-adapter-futu-r1.json').read_text());files=[dict(path=x['path'],before_sha256=x['formal_v7_sha256'],after_sha256=x['after_sha256']) for x in sorted(reviewed['scope'],key=lambda item:item['path'])]
 if {x['path'] for x in files}!={'v4/manager_workbench/inputs/native.py','v4/manager_workbench/inputs/source_bindings.py','v4/manager_workbench/engines/us_mapping.py','v4/manager_workbench/engines/oversold.py'}:raise ValueError('EXACT_FOUR_FILE_SCOPE_REQUIRED')
 target=FORMAL/'config/manager-workbench-v7.json';cfg_raw=target.read_bytes()
 if sha(cfg_raw)!='0a76879d1f658d326c54af5289f09ee2a42e51e0f9976da29df6a208d49ecd20':raise ValueError('EXACT_V8_CONFIG_PREIMAGE_REQUIRED')
 oldcfg=json.loads(cfg_raw);newcfg=copy.deepcopy(oldcfg)
 futu=json.loads((HERE/'.tmp/us-oversold-futu-prepared-r1/receipt.json').read_text())['single_response']
 for key,sha_key in [('raw_relative','raw_sha256'),('receipt_relative','receipt_sha256')]:
  if sha((Path(futu['source_local_path'])/futu[key]).read_bytes())!=futu[sha_key]:raise ValueError('PROVEN_FUTU_SOURCE_DRIFT')
 newcfg.setdefault('source_bindings',{}).setdefault('hk_panel',{}).setdefault('20261012',{})['futu_history']=[futu]
 if newcfg.get('scheduled_lanes')!=['US_MAPPING','OVERSOLD'] or newcfg.get('capture_enabled') or newcfg.get('capture_lease_token'):raise ValueError('EXACT_PAUSED_CAPTURE_DISABLED_CONFIG_REQUIRED')
 with shared_api_release_lock(API) as lease:
  active=read_active_release(API);sraw=SCHED.read_bytes();splist=plistlib.loads(sraw);senv=splist['EnvironmentVariables'];sroot=Path(senv['V35_APP_ROOT']);smanifest=Path(senv['V35_RELEASE_MANIFEST_PATH'])
  if sha(smanifest.read_bytes())!=senv['V35_RELEASE_MANIFEST_SHA256']:raise ValueError('SCHEDULER_MANIFEST_DRIFT')
  sinv=inventory_tree(sroot)
  if sinv!=json.loads(smanifest.read_text())['application_inventory']['entries']:raise ValueError('SCHEDULER_INVENTORY_DRIFT')
  araw=API.read_bytes();base=dict(api=_base_binding(active),api_plist_sha256=sha(araw),scheduler=dict(app_root=str(sroot),plist_sha256=sha(sraw),manifest_path=str(smanifest),manifest_sha256=sha(smanifest.read_bytes()),inventory_sha256=inventory_digest(sinv)))
  payload={}
  for item in files:
   rel=item['path'];raw=(ROOT/rel).read_bytes()
   if sha(raw)!=item['after_sha256']:raise ValueError('REVIEWED_SOURCE_DRIFT:'+rel)
   for root in (Path(active['app_root']),sroot,CANONICAL):
    if sha((root/rel).read_bytes())!=item['before_sha256']:raise ValueError('BASE_FILE_DRIFT:'+str(root/rel))
   payload[rel]=raw
  out.mkdir(parents=True);source=out/'delta-source';source.mkdir();entries=[]
  for item in files:
   rel=item['path'];p=source/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(payload[rel]);before=(Path(active['app_root'])/rel).read_bytes();diff,hunks=_diff_proof(before,payload[rel])
   entries.append(dict(path=rel,before_sha256=item['before_sha256'],after_sha256=item['after_sha256'],unified_diff_sha256=diff,unified_diff_hunk_count=hunks))
  delta=out/'api-delta.json';dump(delta,dict(schema_version=DELTA_SCHEMA_VERSION,base=_base_binding(active),entries=entries))
  acandidate=out/'manager-workbench-20261013-v9-api';acandidate.mkdir();result=build_integrated_app(active_api_plist_path=API,source_root=source,candidate_root=acandidate,delta_receipt_path=delta,explicit_untracked_paths=[])
  scandidate=out/'manager-workbench-20261013-v9-scheduler/app';shutil.copytree(sroot,scandidate,symlinks=True)
  for rel,raw in payload.items():(scandidate/rel).write_bytes(raw)
  after=inventory_tree(scandidate);unchanged={e['path']:e for e in after if e['path'] not in payload}
  if unchanged!={e['path']:e for e in sinv if e['path'] not in payload}:raise ValueError('SCHEDULER_NON_DELTA_DRIFT')
  apps={'api':acandidate/'app','scheduler':scandidate};manifest_shas={}
  for role,app in apps.items():
   inv=inventory_tree(app);manifest=dict(schema_version='v4.release_candidate.v1',candidate_status='PREPARED',deployment_status='NOT_DEPLOYED',candidate=dict(root=str(app.parent),app_root=str(app),release_id='manager-workbench-20261013-v9-'+role,module_role='gateway' if role=='api' else 'scheduler',module_contract_sha256=None),application_inventory=dict(entries=inv,aggregate_sha256=inventory_digest(inv),entry_count=len(inv)),verification_gaps=['Formal cutover and natural slot NOT_RUN'])
   manifest['api_integration' if role=='api' else 'scheduler_integration']=result if role=='api' else dict(base=base['scheduler'],delta_entries=entries)
   mp=app.parent/'release-manifest.json';dump(mp,manifest);manifest_shas[role]=sha(mp.read_bytes())
  verify_api_release_candidate(candidate_root=acandidate,active_api_plist_path=API,expected_manifest_sha256=manifest_shas['api'],lock_lease=lease,require_shared_lock=lease is not None)
  plan_entries=[];pairs=[]
  def append(kind,src,dst):
   before=dst.read_bytes() if dst.exists() else None;backup=out/'before'/str(len(plan_entries)) if before is not None else None
   if backup:backup.parent.mkdir(exist_ok=True);backup.write_bytes(before)
   plan_entries.append(dict(kind=kind,source=str(src),target=str(dst),before_sha256=sha(before) if before is not None else None,after_sha256=sha(src.read_bytes()),backup=str(backup) if backup else None))
  config=out/'manager-workbench-v9.json';dump(config,newcfg);append('config',config,target)
  for rel in payload:append('canonical',source/rel,CANONICAL/rel)
  plists=out/'plists';plists.mkdir()
  for role,path,raw in [('api',API,araw),('scheduler',SCHED,sraw)]:
   old=plistlib.loads(raw);new=copy.deepcopy(old);app=apps[role];oldapp=active['app_root'] if role=='api' else str(sroot)
   fields=dict(V35_APP_ROOT=str(app),V35_RELEASE_ID='manager-workbench-20261013-v9-'+role,V35_RELEASE_MANIFEST_PATH=str(app.parent/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=manifest_shas[role],V4_MANAGER_WORKBENCH_CONFIG_PATH=str(target))
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
   original=plists/(role+'-original.plist');staged=plists/(role+'-v8.plist');original.write_bytes(raw);staged.write_bytes(plistlib.dumps(new,sort_keys=False))
   pairs.append(dict(role=role,label=old['Label'],formal_path=str(path),original=str(original),original_sha256=sha(raw),staged=str(staged),staged_sha256=sha(staged.read_bytes())));append('plist',staged,path)
  if target.read_bytes()!=cfg_raw:raise ValueError('FORMAL_CONFIG_PARALLEL_DRIFT')
  if API.read_bytes()!=araw or SCHED.read_bytes()!=sraw or inventory_tree(sroot)!=sinv or read_active_release(API)['application_inventory_sha256']!=active['application_inventory_sha256']:raise ValueError('ACTIVE_PARALLEL_DRIFT')
  plan=dict(status='PREPARED_NOT_EXECUTED',candidate_api=str(apps['api']),candidate_scheduler=str(apps['scheduler']),api_manifest_sha256=manifest_shas['api'],scheduler_manifest_sha256=manifest_shas['scheduler'],plists=pairs,entries=plan_entries,capture_enabled=False,scheduled_lanes=['US_MAPPING','OVERSOLD'],formal_state_changed=False,base=base,run_id='27a27743e22d414c92b7e8ddcff07260',product_sha256='d44fe52d5a657c4949272f0db0cb4cd5ddc497f4fb7150e17be88e86db04cd60')
  validate(plan,'apply');pp=out/'operator-plan.json';dump(pp,plan)
  receipt=dict(status='PREPARED_DRY_RUN_PASS',plan=str(pp),plan_sha256=sha(pp.read_bytes()),candidate_manifests=manifest_shas,delta_files=files,api_non_delta_preserved=True,scheduler_non_delta_preserved=True,formal_writes=0,services_changed=False)
  dump(out/'receipt.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args();prepare(Path(a.output).resolve())
