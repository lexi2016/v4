"""Inactive API/Main-plist/storage dependency preparation; no live writes."""
from pathlib import Path
import os,json,plistlib,shutil,copy,difflib,sys
from ops.prepare_daily_materials_release import sha,clone_release,seal_manifest,patch_dispatcher,patch_frontend_identity,validate_dependency_packet
P=Path(__file__).parent;H=Path.home()
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def overlay(path,source,before,after):
 if sha(path)==after:return
 assert sha(path)==before, 'DELTA_PREIMAGE:'+str(path)
 assert sha(source)==after,'DELTA_SOURCE:'+str(source)
 mode=path.stat().st_mode & 0o777
 try:
  path.chmod(mode|0o200);path.write_bytes(source.read_bytes())
 finally:path.chmod(mode)
company=json.loads(Path(sys.argv[1]).read_text());entries=company['entries']
live=H/'Library/LaunchAgents/com.lexi.v4.api.plist';p=plistlib.loads(live.read_bytes());e=p['EnvironmentVariables'];old=Path(e['V4_APP_ROOT']);oldm=Path(e['V4_RELEASE_MANIFEST_PATH']);m=json.loads(oldm.read_text())
rid='v4-daily-materials-20261109-r1-api';root=P/rid;root.mkdir(exist_ok=True);app=root/'app'
if not app.exists():clone_release(old,app,m)
deltas=set()
for relative,patch in [('infrastructure/scheduling/dispatcher.py',patch_dispatcher),('apps/api/v4_api/runtime_graph_router.py',patch_frontend_identity)]:
 t=app/relative;b=(old/relative).read_text();a=patch(b)
 assert t.read_text() in (b,a),'PATCH_PREIMAGE:'+relative
 t.write_text(a);deltas.add(relative)
 (P/(Path(relative).stem+'.diff')).write_text(''.join(difflib.unified_diff(b.splitlines(True),a.splitlines(True),fromfile='active/'+relative,tofile='candidate/'+relative)))
for item in entries:
 if item.get('scope')=='research_panel':continue
 relative=item['target'];assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
 overlay(app/relative,Path(item['source']),item['before_sha256'],item['after_sha256']);deltas.add(relative)
m=seal_manifest(m,app=app,release_id=rid,role='api',delta_paths=deltas,base_manifest=oldm);mp=root/'release-manifest.json';save(mp,m)
oldpanel=Path(e['V4_RESEARCH_PANEL_ROOT']);oldasset=Path(e['V4_RESEARCH_PANEL_ASSET_MANIFEST']);panel=P/'research-panel';assets=json.loads(oldasset.read_text())
# One copy, full original asset identity check, no chart generation.
assert all(sha(oldpanel/x['path'])==x['sha256'] for x in assets['files'])
if not panel.exists():shutil.copytree(oldpanel,panel,symlinks=True)
static_delta=set()
for item in entries:
 if item.get('scope')!='research_panel':continue
 relative=str(Path(item['target']).relative_to(oldpanel)) if Path(item['target']).is_absolute() else item['target']
 assert '..' not in Path(relative).parts and not Path(relative).is_absolute()
 overlay(panel/relative,Path(item['source']),item['before_sha256'],item['after_sha256']);static_delta.add(relative)
newassets=copy.deepcopy(assets)
for x in newassets['files']:
 actual=sha(panel/x['path']);assert actual==x['sha256'] or x['path'] in static_delta
 x['sha256']=actual
asset=P/'research-panel-assets.json';save(asset,newassets)
# Explicit environment changes only; keep the original PYTHONPATH auxiliary owners.
p['WorkingDirectory']=str(app);e.update(V4_APP_ROOT=str(app),V4_RELEASE_ID=rid,V4_RELEASE_MANIFEST_PATH=str(mp),V4_RELEASE_MANIFEST_SHA256=sha(mp),V4_RESEARCH_PANEL_ROOT=str(panel),V4_RESEARCH_PANEL_ASSET_MANIFEST=str(asset))
draft=P/'API_CANDIDATE.plist';draft.write_bytes(plistlib.dumps(p,sort_keys=True));draft.chmod(0o600)
api=dict(kind='api',label=p['Label'],live_plist=str(live),before_sha256=sha(live),draft_plist=str(draft),draft_plist_sha256=sha(draft),old_app_root=str(old),old_manifest_sha256=json.loads(oldm.read_text()) and plistlib.loads(live.read_bytes())['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256'],app_root=str(app),manifest=str(mp),manifest_sha256=sha(mp),release_id=rid)
stage=json.loads((P/'STAGE_PACKAGE.json').read_text());sp=plistlib.loads(Path(stage['live_plist']).read_bytes());stage.update(label=sp['Label'],old_manifest_sha256=sp['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256'])
mainlive=H/'Library/LaunchAgents/com.lexi.v4.scheduler.plist';mainp=plistlib.loads(mainlive.read_bytes());me=mainp['EnvironmentVariables'];oldpolicy=Path(me['V4_RESEARCH_RETENTION_POLICY']);policy=json.loads(oldpolicy.read_text());oldpins=Path(policy['managed_pin_inventory']['path']);pins=json.loads(oldpins.read_text());newpins=P/'research_storage_pins.json'
for ref in pins['source_bindings']:
 if ref['path']==str(live):ref['sha256']=sha(draft)
 elif ref['path']==stage['live_plist']:ref['sha256']=stage['draft_plist_sha256']
 elif ref['path']==str(oldasset):ref.update(path=str(asset),sha256=sha(asset))
 elif ref['path'].startswith(str(old)+'/'):
  ref['path']=str(app)+ref['path'][len(str(old)):];ref['sha256']=sha(Path(ref['path']))
 else:assert sha(Path(ref['path']))==ref['sha256'],'UNRELATED_SOURCE_DRIFT:'+ref['path']
save(newpins,pins);policy['managed_pin_inventory']={'path':str(newpins),'sha256':sha(newpins)};newpolicy=P/'research_storage_policy.json';save(newpolicy,policy)
me.update(V4_RESEARCH_RETENTION_POLICY=str(newpolicy),V4_RESEARCH_RETENTION_POLICY_SHA256=sha(newpolicy));maindraft=P/'MAIN_CANDIDATE.plist';maindraft.write_bytes(plistlib.dumps(mainp,sort_keys=True));maindraft.chmod(0o600)
main=dict(kind='main',label=mainp['Label'],live_plist=str(mainlive),before_sha256=sha(mainlive),draft_plist=str(maindraft),draft_plist_sha256=sha(maindraft),old_app_root=me['V4_APP_ROOT'],old_manifest_sha256=me['V4_RELEASE_MANIFEST_SHA256'],app_root=me['V4_APP_ROOT'],manifest=me['V4_RELEASE_MANIFEST_PATH'],manifest_sha256=me['V4_RELEASE_MANIFEST_SHA256'],release_id=me['V4_RELEASE_ID'])
packet=dict(schema='v4.daily_materials_dependency_packet.v1',status='PREPARED_NOT_ACTIVATED',services=dict(api=api,main=main,stage=stage),pins={'path':str(newpins),'sha256':sha(newpins)},policy={'path':str(newpolicy),'sha256':sha(newpolicy)},scheduler_lane_lock_root=str(H/'Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners'),company_delta={'path':str(Path(sys.argv[1])),'sha256':sha(Path(sys.argv[1]))},static=dict(root=str(panel),manifest=str(asset),manifest_sha256=sha(asset),delta_paths=sorted(static_delta)),RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,natural_execution_verified=False)
packet['tool_source_files']=[{'path':str(p),'sha256':sha(p)} for p in [Path(__file__),P/'check_packet.py',Path('/Users/lexi/.codex/worktrees/v4-release-dependency-20261109/ops/prepare_daily_materials_release.py'),Path('/Users/lexi/.codex/worktrees/v4-release-dependency-20261109/ops/activate_daily_materials_release.py')]]
save(P/'PACKET.json',packet);result=validate_dependency_packet(packet);save(P/'DEPENDENCY_CHECK.json',result);print(json.dumps(result))
