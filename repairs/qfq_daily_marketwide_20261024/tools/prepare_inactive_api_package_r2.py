"""One inactive actual-R6 clone using the original explicit-delta package builder."""
from pathlib import Path
import hashlib, importlib.util, json, os, plistlib, shutil, sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value):
 p=Path(p)
 with p.open('x') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def ref(p):return dict(path=str(Path(p).resolve()),sha256=sha(p))
def all_environment(payload):
 values=dict(payload.get('EnvironmentVariables',{}))
 for argument in payload['ProgramArguments']:
  if '=' in argument:
   key,value=argument.split('=',1);values[key]=value
 return values
def main():
 cfg_path=HERE/'PREPARATION_EXECUTION_CONFIG_R2.json';cfg=json.loads(cfg_path.read_text())
 for r in cfg['frozen_refs']:assert sha(r['path'])==r['sha256'],r['path']
 starts=[]
 for line in Path(cfg['registry_path']).open():
  e=json.loads(line)
  if e.get('execution_id')==cfg['execution_id'] and e.get('event_type')=='RUN_STARTED':starts.append(e)
 assert len(starts)==1
 matching=[]
 for line in Path(cfg['registry_path']).open():
  event=json.loads(line)
  if (event.get('execution_id')==cfg['execution_id'] and 'CHECKPOINT' in event.get('event_type','')
      and event.get('code_sha256')==sha(__file__) and event.get('input_sha256')==cfg['input_sha256']):matching.append(event)
 assert len(matching)==1
 artifact_paths=matching[0]['artifact_path'];artifact_hashes=matching[0]['artifact_sha256']
 assert artifact_paths[0]==str(cfg_path) and artifact_hashes[0]==sha(cfg_path)
 assert sha(cfg['live_api_plist']['path'])==cfg['live_api_plist']['sha256']
 proposal=json.loads(Path(cfg['proposal']['path']).read_text());base=Path(proposal['base_release']);target=Path(proposal['proposed_new_inactive_release'])
 assert not target.exists() and not target.is_symlink(),'EXISTING_TARGET_STOP'
 module_path=base/'app/ops/api_release_integration.py'
 spec=importlib.util.spec_from_file_location('existing_api_release_integration',module_path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 # Existing canonical role policy is an explicit read-only dependency, absent
 # from legacy R6; preserve legacy parent identity and original checks.
 m.MODULE_CONTRACT_PATH=Path(cfg['existing_gateway_role_contract']['path'])
 assert sha(m.MODULE_CONTRACT_PATH)==cfg['existing_gateway_role_contract']['sha256']
 active=m.read_active_release(Path(cfg['live_api_plist']['path']))
 assert active['release_manifest_sha256']==proposal['base_manifest']['sha256']
 assert active['release_root']==str(base)
 source=HERE/'exact_overlay_source';source.mkdir()
 records=[]
 items=[(v['relative_path'],v['artifact']) for v in proposal['overlay_files']]
 dist=Path(cfg['frozen_dist_root'])
 items += [('apps/web/dist/'+str(Path(v['path']).relative_to(dist)),v) for v in proposal['static_bundle']]
 for relative,r in items:
  assert sha(r['path'])==r['sha256']
  dest=source/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(r['path'],dest)
  before=base/'app'/relative;before_sha=sha(before) if before.is_file() else None
  if before_sha==r['sha256']:continue
  diff,hunks=m._diff_proof(before.read_bytes(),dest.read_bytes()) if before_sha else (None,None)
  records.append(dict(path=relative,before_sha256=before_sha,after_sha256=r['sha256'],unified_diff_sha256=diff,unified_diff_hunk_count=hunks))
 receipt=HERE/'EXPLICIT_DELTA_RECEIPT_R1.json'
 save(receipt,dict(schema_version=m.DELTA_SCHEMA_VERSION,base=m._base_binding(active),entries=sorted(records,key=lambda r:r['path'])))
 target.mkdir()
 integration=m.build_integrated_app(active_api_plist_path=Path(cfg['live_api_plist']['path']),source_root=source,candidate_root=target,delta_receipt_path=receipt,explicit_untracked_paths=[r['path'] for r in records if r['before_sha256'] is None])
 inventory=m.inventory_tree(target/'app');parent=json.loads((base/'release-manifest.json').read_text())
 candidate=dict(parent['candidate'],root=str(target),app_root=str(target/'app'),release_id=target.name)
 manifest=dict(schema_version='v4.release_candidate.v1',activation_status='PREPARED_NOT_ACTIVATED',candidate=candidate,application_inventory=dict(entries=inventory,entry_count=len(inventory),aggregate_sha256=m.inventory_digest(inventory)),api_integration=integration,parent_manifest=ref(base/'release-manifest.json'),task_overlay=dict(proposal=cfg['proposal'],source_review=cfg['source_review'],source_paths=[v['relative_path'] for v in proposal['overlay_files']],frozen_static_artifacts=proposal['static_bundle'],old_unreferenced_static_assets='PRESERVED_BYTE_IDENTICAL; original explicit-delta verifier forbids unrelated removals'))
 save(target/'release-manifest.json',manifest)
 verified=m.verify_api_release_candidate(candidate_root=target,active_api_plist_path=Path(cfg['live_api_plist']['path']),expected_manifest_sha256=sha(target/'release-manifest.json'),active_pointer='base')
 old=plistlib.loads(Path(cfg['live_api_plist']['path']).read_bytes());new=json.loads(json.dumps(old))
 changes={'V35_APP_ROOT':str(target/'app'),'V35_RELEASE_ID':target.name,'V35_RELEASE_MANIFEST_PATH':str(target/'release-manifest.json'),'V35_RELEASE_MANIFEST_SHA256':sha(target/'release-manifest.json'),'V4_A_SHARE_HISTORY_DATA_ROOT':proposal['new_history_env']['value']}
 args=new['ProgramArguments'];seen=set()
 for i,v in enumerate(args):
  if '=' not in v:continue
  key,value=v.split('=',1)
  if key in changes:args[i]=key+'='+changes[key];seen.add(key)
  elif key=='PYTHONPATH':args[i]=key+'='+value.replace(str(base/'app'),str(target/'app'));seen.add(key)
 assert set(changes)-{'V4_A_SHARE_HISTORY_DATA_ROOT'}<=seen
 assert 'V4_A_SHARE_HISTORY_DATA_ROOT' not in seen
 index=next(i for i in range(1,len(args)) if '=' not in args[i]);args.insert(index,'V4_A_SHARE_HISTORY_DATA_ROOT='+changes['V4_A_SHARE_HISTORY_DATA_ROOT'])
 for key,value in list(new.get('EnvironmentVariables',{}).items()):
  if key in changes:new['EnvironmentVariables'][key]=changes[key]
  elif key=='PYTHONPATH':new['EnvironmentVariables'][key]=value.replace(str(base/'app'),str(target/'app'))
 new['WorkingDirectory']=str(target/'app')
 plist=HERE/'api-candidate.plist'
 with plist.open('xb') as f:f.write(plistlib.dumps(new,sort_keys=False));f.flush();os.fsync(f.fileno())
 assert all_environment(new)['V35_SHARED_DATA_ROOT']==proposal['preserve_global_shared_root']
 assert sha(cfg['live_api_plist']['path'])==cfg['live_api_plist']['sha256'],'LIVE_PLIST_DRIFT'
 result=dict(status='PREPARED_NOT_ACTIVATED',execution_id=cfg['execution_id'],original_builder_source=ref(module_path),parent=integration['base'],candidate_manifest=ref(target/'release-manifest.json'),candidate_plist=ref(plist),delta_receipt=ref(receipt),original_candidate_verification=verified,source_review=cfg['source_review'],source_overlay_count=6,proposed_static_count=len(proposal['static_bundle']),application_inventory_count=len(inventory),non_delta_preserved=integration['non_delta_active_release_bytes_preserved'],live_plist_unchanged=True,live_api_service_mutated=False,scheduler_CURRENT_modified=False,history_only_root=changes['V4_A_SHARE_HISTORY_DATA_ROOT'],global_shared_root=all_environment(new)['V35_SHARED_DATA_ROOT'],live_API_UI_verified=False,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
 save(HERE/'PREPARATION_ACTUAL_RESULT_R1.json',result)
 print(json.dumps({k:v for k,v in result.items() if k not in {'parent','original_candidate_verification'}},ensure_ascii=False))
if __name__=='__main__':main()
