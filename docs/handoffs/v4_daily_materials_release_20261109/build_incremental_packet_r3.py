"""Prepare the approved r2 DAG. Never install or start a service."""
from pathlib import Path
from copy import deepcopy
import os,json,plistlib,shutil,sys,difflib,stat
from ops.prepare_daily_materials_release import sha,clone_release,seal_manifest,patch_dispatcher,patch_frontend_identity,patch_stage_owner_reader,validate_dependency_packet
P=Path(__file__).parent;H=Path.home();W=Path('/Users/lexi/.codex/worktrees/v4-release-dependency-20261109')
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
 rid='v4-daily-materials-20261109-r3-'+role;root=P/rid;root.mkdir(exist_ok=True);app=root/'app'
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
  if isinstance(v,str):return v.replace(str(s.get('plist_old_root',s['old'])),str(s['app']))
  if isinstance(v,list):return [rewrite(x) for x in v]
  if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
  return v
 p=rewrite(p);p['WorkingDirectory']=str(s['app']);p['EnvironmentVariables'].update(V4_APP_ROOT=str(s['app']),V4_RELEASE_ID=s['rid'],V4_RELEASE_MANIFEST_PATH=str(s['mp']),V4_RELEASE_MANIFEST_SHA256=s['msha'])
 target=P/name;target.write_bytes(plistlib.dumps(p,sort_keys=True));target.chmod(0o600);return p,target
merged=Path(sys.argv[1]);delta=json.loads(merged.read_text());entries=delta['entries'];previous_path=P/'PACKET_FINAL.json';previous=json.loads(previous_path.read_text())
# Only the independently identified Main qualification cache delta changed.
static_changes=[]
for item in entries:
 if item['scope']=='api':assert sha(Path(previous['services']['api']['app_root'])/item['target'])==item['after_sha256'],'API_DELTA_CHANGED_REQUIRES_NEW_REVIEW'
 if item['scope']=='research_panel':
  oldpanel=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-workbench-source-close-quote-20261105-r1/research-panel');rel=str(Path(item['target']).relative_to(oldpanel)) if Path(item['target']).is_absolute() else item['target']
  if sha(Path(previous['static']['root'])/rel)!=item['after_sha256']:static_changes.append((rel,item))
assert {rel for rel,_ in static_changes}=={'workbench-host/kb-single-stock.mjs'},'ONLY_EVIDENCED_SINGLE_STATIC_DELTA_ALLOWED'
panel=P/'research-panel-r3'
if not panel.exists():shutil.copytree(previous['static']['root'],panel,symlinks=True)
assets=json.loads(Path(previous['static']['manifest']).read_text())
for rel,item in static_changes:
 before=sha(Path(previous['static']['root'])/rel);overlay(panel/rel,Path(item['source']),before,item['after_sha256'])
for entry in assets['files']:
 actual=sha(panel/entry['path']);assert actual==entry['sha256'] or entry['path'] in {rel for rel,_ in static_changes};entry['sha256']=actual
asset=P/'research-panel-assets-r3.json';save(asset,assets)
apip=plistlib.loads(Path(previous['services']['api']['draft_plist']).read_bytes());apip['EnvironmentVariables'].update(V4_RESEARCH_PANEL_ROOT=str(panel),V4_RESEARCH_PANEL_ASSET_MANIFEST=str(asset));apipath=P/'API_FINAL_R3.plist';apipath.write_bytes(plistlib.dumps(apip,sort_keys=True));apipath.chmod(0o600);apidesc=deepcopy(previous['services']['api']);apidesc.update(draft_plist=str(apipath),draft_plist_sha256=sha(apipath))
main=load_service('com.lexi.v4.scheduler.plist');copy_app(main,'main');changes=apply_entries(main,entries);seal(main,changes)
# Reuse the already reviewed Stage reader and all historical binding bytes;
# only its current Main owner tuple changes. Original active backup remains.
stage=load_service('com.lexi.stage-center.scheduler.plist');stage.update(plist_old_root=Path(previous['services']['stage']['old_app_root']),old=Path(previous['services']['stage']['app_root']),oldm=Path(previous['services']['stage']['manifest']),m=json.loads(Path(previous['services']['stage']['manifest']).read_text()));copy_app(stage,'stage')
cfg=stage['app']/'stage_center_tick_config.json';c=json.loads(cfg.read_text());c['research_owner_binding']=dict(app_root=str(main['app']),release_id=main['rid'],manifest_sha256=main['msha'],manifest_path=str(main['mp']));save(cfg,c);seal(stage,{'stage_center_tick_config.json'});stagep,stagepath=draft(stage,'STAGE_FINAL_R3.plist');stagedesc=descriptor(stage,stagepath);stagedesc.update(old_app_root=previous['services']['stage']['old_app_root'],old_manifest_sha256=previous['services']['stage']['old_manifest_sha256'])
policy=json.loads(Path(previous['policy']['path']).read_text());pins=json.loads(Path(policy['managed_pin_inventory']['path']).read_text());oldmain=previous['services']['main']['app_root']
for ref in pins['source_bindings']:
 if ref['path']==stagedesc['live_plist']:ref['sha256']=sha(stagepath)
 elif ref['path']==apidesc['live_plist']:ref['sha256']=sha(apipath)
 elif ref['path']==previous['static']['manifest']:ref.update(path=str(asset),sha256=sha(asset))
 elif ref['path'].startswith(oldmain+'/'):
  ref['path']=str(main['app'])+ref['path'][len(oldmain):];ref['sha256']=sha(Path(ref['path']))
pins['expected_main_app_root']=str(main['app']);pinpath=P/'research_storage_pins_r3.json';save(pinpath,pins);policy['managed_pin_inventory']={'path':str(pinpath),'sha256':sha(pinpath)};policypath=P/'research_storage_policy_r3.json';save(policypath,policy)
mainp,mainpath=draft(main,'MAIN_FINAL_R3.plist');mainp['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(policypath),V4_RESEARCH_RETENTION_POLICY_SHA256=sha(policypath));mainpath.write_bytes(plistlib.dumps(mainp,sort_keys=True));maindesc=descriptor(main,mainpath)
frozen_delta=P/'DELTA_FINAL_R3.json'
if not frozen_delta.exists():frozen_delta.write_bytes(merged.read_bytes())
assert sha(frozen_delta)==sha(merged),'FROZEN_DELTA_ALREADY_DIFFERENT'
packet=deepcopy(previous);packet['services'].update(main=maindesc,stage=stagedesc,api=apidesc);packet['static'].update(root=str(panel),manifest=str(asset),manifest_sha256=sha(asset),incremental_delta_paths=[rel for rel,_ in static_changes]);packet.update(pins=dict(path=str(pinpath),sha256=sha(pinpath)),policy=dict(path=str(policypath),sha256=sha(policypath)),company_score_delta=dict(path=str(frozen_delta),sha256=sha(frozen_delta)),incremental_from=dict(packet=str(previous_path),packet_sha256=sha(previous_path),scope='Main qualification cache plus final single static date-invalidation delta; API app exact byte reuse'))
packet['tool_source_files']=[dict(path=str(p),sha256=sha(p)) for p in [Path(__file__),W/'ops/prepare_daily_materials_release.py',W/'ops/activate_daily_materials_release.py']];save(P/'PACKET_FINAL_R3.json',packet);result=validate_dependency_packet(packet);save(P/'DEPENDENCY_FINAL_R3_CHECK.json',result);print(json.dumps(result))
