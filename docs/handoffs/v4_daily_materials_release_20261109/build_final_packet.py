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
 rid='v4-daily-materials-20261109-r2-'+role;root=P/rid;root.mkdir(exist_ok=True);app=root/'app'
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
merged=Path(sys.argv[1]);delta=json.loads(merged.read_text());entries=delta['entries'];assert {item['scope'] for item in entries}<={'api','main','research_panel'}
main=load_service('com.lexi.v4.scheduler.plist');stage=load_service('com.lexi.stage-center.scheduler.plist');api=load_service('com.lexi.v4.api.plist')
# Seal Main before Stage. Its old storage_phase2 policy/pins are historical
# provenance, never a forward pointer to this not-yet-created policy.
copy_app(main,'main');mainchanges=apply_entries(main,entries);seal(main,mainchanges)
assert main['m']['storage_phase2']==json.loads(main['mp'].read_text())['storage_phase2']
copy_app(stage,'stage');reader=stage['app']/'infrastructure/manager_input_attestation.py';before=(stage['old']/'infrastructure/manager_input_attestation.py').read_text();after=patch_stage_owner_reader(before);assert reader.read_text() in (before,after);reader.write_text(after)
(P/'stage-reader-r2.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='active/infrastructure/manager_input_attestation.py',tofile='r2/infrastructure/manager_input_attestation.py')))
cfg=stage['app']/'stage_center_tick_config.json';c=json.loads((stage['old']/'stage_center_tick_config.json').read_text());historical=c['research_historical_owner_bindings'];historical.append(deepcopy(c['research_owner_binding']));historical.append(dict(app_root=str(main['old']),release_id=main['e']['V4_RELEASE_ID'],manifest_sha256=main['old_manifest_sha256'],manifest_path=str(main['oldm'])));assert len(historical)==5
c['research_owner_binding']=dict(app_root=str(main['app']),release_id=main['rid'],manifest_sha256=main['msha'],manifest_path=str(main['mp']));save(cfg,c);seal(stage,{'infrastructure/manager_input_attestation.py','stage_center_tick_config.json'});stagep,stagepath=draft(stage,'STAGE_FINAL.plist')
copy_app(api,'api');apichanges=apply_entries(api,entries)
for relative,patch in [('infrastructure/scheduling/dispatcher.py',patch_dispatcher),('apps/api/v4_api/runtime_graph_router.py',patch_frontend_identity)]:
 t=api['app']/relative;b=(api['old']/relative).read_text();a=patch(b);assert t.read_text() in (b,a);t.write_text(a);apichanges.add(relative)
seal(api,apichanges)
oldpanel=Path(api['e']['V4_RESEARCH_PANEL_ROOT']);oldasset=Path(api['e']['V4_RESEARCH_PANEL_ASSET_MANIFEST']);panel=P/'research-panel-r2';assets=json.loads(oldasset.read_text());assert all(sha(oldpanel/x['path'])==x['sha256'] for x in assets['files'])
if not panel.exists():shutil.copytree(oldpanel,panel,symlinks=True)
staticdelta=set()
for item in entries:
 if item['scope']!='research_panel':continue
 relative=str(Path(item['target']).relative_to(oldpanel)) if Path(item['target']).is_absolute() else item['target'];assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
 overlay(panel/relative,Path(item['source']),item['before_sha256'],item['after_sha256']);staticdelta.add(relative)
newassets=deepcopy(assets);listed={x['path'] for x in assets['files']}
for x in newassets['files']:
 actual=sha(panel/x['path']);assert actual==x['sha256'] or x['path'] in staticdelta;x['sha256']=actual
for relative in sorted(staticdelta-listed):newassets['files'].append({'path':relative,'sha256':sha(panel/relative)})
asset=P/'research-panel-assets-r2.json';save(asset,newassets);apip,apipath=draft(api,'API_FINAL.plist');apip['EnvironmentVariables'].update(V4_RESEARCH_PANEL_ROOT=str(panel),V4_RESEARCH_PANEL_ASSET_MANIFEST=str(asset));apipath.write_bytes(plistlib.dumps(apip,sort_keys=True));apidesc=descriptor(api,apipath);stagedesc=descriptor(stage,stagepath)
policy=json.loads(Path(main['e']['V4_RESEARCH_RETENTION_POLICY']).read_text());pins=json.loads(Path(policy['managed_pin_inventory']['path']).read_text())
for ref in pins['source_bindings']:
 if ref['path']==str(api['live']):ref['sha256']=sha(apipath)
 elif ref['path']==str(stage['live']):ref['sha256']=sha(stagepath)
 elif ref['path']==str(oldasset):ref.update(path=str(asset),sha256=sha(asset))
 else:
  mapped=False
  for s in [main,api]:
   if ref['path'].startswith(str(s['old'])+'/'):
    ref['path']=str(s['app'])+ref['path'][len(str(s['old'])):];ref['sha256']=sha(Path(ref['path']));mapped=True;break
  if not mapped:assert sha(Path(ref['path']))==ref['sha256'],'UNRELATED_SOURCE_DRIFT:'+ref['path']
pins['expected_main_app_root']=str(main['app']);pinpath=P/'research_storage_pins_r2.json';save(pinpath,pins);policy['managed_pin_inventory']={'path':str(pinpath),'sha256':sha(pinpath)};policypath=P/'research_storage_policy_r2.json';save(policypath,policy)
mainp,mainpath=draft(main,'MAIN_FINAL.plist');mainp['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(policypath),V4_RESEARCH_RETENTION_POLICY_SHA256=sha(policypath));mainpath.write_bytes(plistlib.dumps(mainp,sort_keys=True));maindesc=descriptor(main,mainpath)
packet=dict(schema='v4.daily_materials_dependency_packet.v1',status='PREPARED_NOT_ACTIVATED',services=dict(api=apidesc,main=maindesc,stage=stagedesc),pins=dict(path=str(pinpath),sha256=sha(pinpath)),policy=dict(path=str(policypath),sha256=sha(policypath)),scheduler_lane_lock_root=str(H/'Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners'),company_score_delta=dict(path=str(merged),sha256=sha(merged)),static=dict(root=str(panel),manifest=str(asset),manifest_sha256=sha(asset),delta_paths=sorted(staticdelta)),main_manifest_policy='PRESERVED_HISTORICAL_PROVENANCE_RUNTIME_AUTHORITY_IS_FINAL_MAIN_PLIST_ENV',main_delta_scope='EXISTING_SCORE_ACTION_POSTPROCESS_ONLY_NUMERIC_FORMULA_AND_CANDIDATE_RULES_UNCHANGED',RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,natural_execution_verified=False)
packet['tool_source_files']=[dict(path=str(p),sha256=sha(p)) for p in [Path(__file__),W/'ops/prepare_daily_materials_release.py',W/'ops/activate_daily_materials_release.py']];save(P/'PACKET_FINAL.json',packet);result=validate_dependency_packet(packet);save(P/'DEPENDENCY_FINAL_CHECK.json',result);print(json.dumps(result))
