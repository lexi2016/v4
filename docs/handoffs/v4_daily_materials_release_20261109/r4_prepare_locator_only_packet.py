"""Prepare the approved r2 DAG. Never install or start a service."""
from pathlib import Path
from copy import deepcopy
import os,json,plistlib,shutil,sys,difflib,stat
from ops.prepare_daily_materials_release import sha,clone_release,seal_manifest,patch_dispatcher,patch_frontend_identity,patch_stage_owner_reader,validate_dependency_packet
E=Path('/Users/lexi/Desktop/学习/agents调试/v4_daily_materials_release_repair_20261109/release');P=Path.home()/'Library/Application Support/com.lexi.v4.local/candidates/v4-daily-materials-20261109-r4';P.mkdir(exist_ok=False);H=Path.home();W=Path('/Users/lexi/.codex/worktrees/v4-release-dependency-20261109')
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def load_service(filename):
 live=H/'Library/LaunchAgents'/filename;p=plistlib.loads(live.read_bytes());e=p['EnvironmentVariables'];mp=Path(e['V4_RELEASE_MANIFEST_PATH']);m=json.loads(mp.read_text());assert sha(mp)==e['V4_RELEASE_MANIFEST_SHA256'];return dict(live=live,p=p,e=e,old=Path(e['V4_APP_ROOT']),oldm=mp,m=m,old_manifest_sha256=e['V4_RELEASE_MANIFEST_SHA256'])
def overlay(path,source,before,after):
 assert path.is_relative_to(P) and path!=P,'DELTA_OUTSIDE_PRIVATE_PACKET'
 assert not path.is_symlink() and all(not parent.is_symlink() for parent in path.parents),'DELTA_SYMLINK'
 assert sha(source)==after,'DELTA_SOURCE:'+str(source)
 if path.exists():
  if sha(path)==after:return
  assert before is not None and sha(path)==before,'DELTA_PREIMAGE:'+str(path)
  mode=stat.S_IMODE(path.stat().st_mode)
 else:
  assert before is None,'DELTA_MISSING:'+str(path);mode=stat.S_IMODE(source.stat().st_mode)
 parents=[]
 try:
  for parent in path.parents:
   if parent==P:break
   if parent.exists() and not parent.stat().st_mode & stat.S_IWUSR:
    original=stat.S_IMODE(parent.stat().st_mode);parent.chmod(original|stat.S_IWUSR);parents.append((parent,original))
  path.parent.mkdir(parents=True,exist_ok=True)
  if path.exists():path.chmod(mode|0o200)
  path.write_bytes(source.read_bytes());path.chmod(mode)
 finally:
  if path.exists():path.chmod(mode)
  for parent,original in reversed(parents):parent.chmod(original)

def copy_app(s,role):
 rid='v4-daily-materials-20261109-r4-'+role;root=P/rid;root.mkdir(exist_ok=True);app=root/'app'
 if not app.exists():clone_release(s['old'],app,s['m'])
 s.update(role=role,rid=rid,root=root,app=app)
def apply_entries(s,entries):
 changes=set()
 for item in entries:
  if item.get('scope')!=s['role']:continue
  relative=item['target'];assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
  overlay(s['app']/relative,Path(item['source']),item['before_sha256'],item['after_sha256']);changes.add(relative)
 return changes
def seal(s,changes):
 m=seal_manifest(s['m'],app=s['app'],release_id=s['rid'],role=s['role'],delta_paths=changes,base_manifest=s['oldm']);mp=s['root']/'release-manifest.json';save(mp,m);s.update(mp=mp,msha=sha(mp))
def descriptor(s,draft):
 return dict(kind=s['role'],label=s['p']['Label'],live_plist=str(s['live']),before_sha256=sha(s['live']),draft_plist=str(draft),draft_plist_sha256=sha(draft),old_app_root=str(s['old']),old_manifest_sha256=s['old_manifest_sha256'],app_root=str(s['app']),manifest=str(s['mp']),manifest_sha256=s['msha'],release_id=s['rid'])
def draft(s,name):
 p=deepcopy(s['p'])
 def rewrite(v):
  if isinstance(v,str):return v.replace(str(s['old']),str(s['app']))
  if isinstance(v,list):return [rewrite(x) for x in v]
  if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
  return v
 p=rewrite(p);p['WorkingDirectory']=str(s['app']);p['EnvironmentVariables'].update(V4_APP_ROOT=str(s['app']),V4_RELEASE_ID=s['rid'],V4_RELEASE_MANIFEST_PATH=str(s['mp']),V4_RELEASE_MANIFEST_SHA256=s['msha'])
 target=P/name;target.write_bytes(plistlib.dumps(p,sort_keys=True));target.chmod(0o600);return p,target
previous_path=E/'PACKET_FINAL_R3.json';previous=json.loads(previous_path.read_text());previous_receipt=E/'R3_ROLLBACK_READBACK.json';assert previous_receipt.is_file(),'ROOT_ROLLBACK_READBACK_REQUIRED'
services={}
for role,base in previous['services'].items():
 live=Path(base['live_plist']);actual=plistlib.loads(live.read_bytes());env=actual['EnvironmentVariables'];assert sha(live)==base['before_sha256'],'RESTORED_TUPLE_REQUIRED:'+role
 assert env['V4_APP_ROOT']==base['old_app_root'] and env['V4_RELEASE_MANIFEST_SHA256']==base['old_manifest_sha256'],'RESTORED_RUNTIME_PIN_REQUIRED:'+role
 oldm=Path(base['manifest']);assert sha(oldm)==base['manifest_sha256'];m=json.loads(oldm.read_text())
 s=dict(live=live,p=plistlib.loads(Path(base['draft_plist']).read_bytes()),e=env,old=Path(base['app_root']),oldm=oldm,m=m,old_manifest_sha256=base['old_manifest_sha256'],rollback_app=base['old_app_root'])
 copy_app(s,role);services[role]=s
main=services['main'];seal(main,set())
stage=services['stage'];cfg=stage['app']/'stage_center_tick_config.json';c=json.loads(cfg.read_text());c['research_owner_binding']=dict(app_root=str(main['app']),release_id=main['rid'],manifest_sha256=main['msha'],manifest_path=str(main['mp']));save(cfg,c);seal(stage,{'stage_center_tick_config.json'})
api=services['api'];seal(api,set())
# All business/static bytes are unchanged. Only Stage's current owner locator
# is different inside apps; original historical owners remain Library roots.
panel=P/'research-panel';shutil.copytree(previous['static']['root'],panel,symlinks=True);asset=P/'research-panel-assets.json';asset.write_bytes(Path(previous['static']['manifest']).read_bytes());assert sha(asset)==previous['static']['manifest_sha256']
for item in json.loads(asset.read_text())['files']:assert sha(panel/item['path'])==item['sha256']
apip,apipath=draft(api,'API_CANDIDATE.plist');apip['EnvironmentVariables'].update(V4_RESEARCH_PANEL_ROOT=str(panel),V4_RESEARCH_PANEL_ASSET_MANIFEST=str(asset));apipath.write_bytes(plistlib.dumps(apip,sort_keys=True));apidesc=descriptor(api,apipath);apidesc['old_app_root']=api['rollback_app']
stagep,stagepath=draft(stage,'STAGE_CANDIDATE.plist');stagedesc=descriptor(stage,stagepath);stagedesc['old_app_root']=stage['rollback_app']
policy=json.loads(Path(previous['policy']['path']).read_text());pins=json.loads(Path(previous['pins']['path']).read_text());oldmain=previous['services']['main']['app_root'];oldapi=previous['services']['api']['app_root']
for ref in pins['source_bindings']:
 if ref['path']==apidesc['live_plist']:ref['sha256']=sha(apipath)
 elif ref['path']==stagedesc['live_plist']:ref['sha256']=sha(stagepath)
 elif ref['path']==previous['static']['manifest']:ref.update(path=str(asset),sha256=sha(asset))
 else:
  for role,old in [('main',oldmain),('api',oldapi)]:
   if ref['path'].startswith(old+'/'):
    ref['path']=str(services[role]['app'])+ref['path'][len(old):];ref['sha256']=sha(Path(ref['path']));break
pins['expected_main_app_root']=str(main['app']);pinpath=P/'research_storage_pins.json';save(pinpath,pins);policy['managed_pin_inventory']={'path':str(pinpath),'sha256':sha(pinpath)};policypath=P/'research_storage_policy.json';save(policypath,policy)
mainp,mainpath=draft(main,'MAIN_CANDIDATE.plist');mainp['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(policypath),V4_RESEARCH_RETENTION_POLICY_SHA256=sha(policypath));mainpath.write_bytes(plistlib.dumps(mainp,sort_keys=True));maindesc=descriptor(main,mainpath);maindesc['old_app_root']=main['rollback_app']
frozen_delta=P/'DELTA_FINAL.json';frozen_delta.write_bytes(Path(previous['company_score_delta']['path']).read_bytes());assert sha(frozen_delta)==previous['company_score_delta']['sha256']
packet=deepcopy(previous);packet.update(services=dict(api=apidesc,main=maindesc,stage=stagedesc),runtime_candidate_root=str(P),runtime_location_contract='APP_STATIC_POLICY_PINS_AND_LAUNCHER_LIBRARY_ROOT_ONLY',static=dict(previous['static'],root=str(panel),manifest=str(asset)),pins=dict(path=str(pinpath),sha256=sha(pinpath)),policy=dict(path=str(policypath),sha256=sha(policypath)),company_score_delta=dict(path=str(frozen_delta),sha256=sha(frozen_delta)),incremental_from=dict(packet=str(previous_path),packet_sha256=sha(previous_path),scope='Observed Desktop launchd TCC failure; locator-only Library migration; business/static bytes unchanged'),restored_tuple_readback=dict(path=str(previous_receipt),sha256=sha(previous_receipt)))
# Freeze a copy of this preparation script in the safe packet root as evidence.
local_script=P/'prepare_locator_only_packet.py';local_script.write_bytes(Path(__file__).read_bytes());packet['tool_source_files']=[dict(path=str(p),sha256=sha(p)) for p in [local_script,W/'ops/prepare_daily_materials_release.py',W/'ops/activate_daily_materials_release.py']];save(P/'PACKET.json',packet);result=validate_dependency_packet(packet);save(P/'DEPENDENCY_CHECK.json',result);save(E/'R4_LOCATION.json',dict(root=str(P),packet=str(P/'PACKET.json'),packet_sha256=sha(P/'PACKET.json')));print(json.dumps(dict(root=str(P),packet_sha256=sha(P/'PACKET.json'),dependency=result)))
