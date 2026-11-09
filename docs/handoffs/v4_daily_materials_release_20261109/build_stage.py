from pathlib import Path
import os,json,plistlib,hashlib,stat,copy,difflib
from ops.prepare_daily_materials_release import sha,clone_release,seal_manifest,patch_stage_owner_reader
P=Path(__file__).parent
H=Path.home(); live=H/'Library/LaunchAgents/com.lexi.stage-center.scheduler.plist'
p=plistlib.loads(live.read_bytes());e=p['EnvironmentVariables'];old=Path(e['V4_APP_ROOT']);oldm=Path(e['V4_RELEASE_MANIFEST_PATH']);m=json.loads(oldm.read_text())
rid='v4-daily-materials-20261109-r1-stage';root=P/rid;root.mkdir();app=root/'app'
clone_release(old,app,m)
reader=app/'infrastructure/manager_input_attestation.py';before=reader.read_text();after=patch_stage_owner_reader(before);reader.write_text(after)
(P/'stage-reader.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='active/infrastructure/manager_input_attestation.py',tofile='candidate/infrastructure/manager_input_attestation.py')))
cfg=app/'stage_center_tick_config.json';c=json.loads(cfg.read_text());oldowner=copy.deepcopy(c['research_owner_binding']);c['research_historical_owner_bindings'].append(oldowner)
mainplist=H/'Library/LaunchAgents/com.lexi.v4.scheduler.plist';me=plistlib.loads(mainplist.read_bytes())['EnvironmentVariables'];c['research_owner_binding']={'app_root':me['V4_APP_ROOT'],'release_id':me['V4_RELEASE_ID'],'manifest_sha256':me['V4_RELEASE_MANIFEST_SHA256'],'manifest_path':me['V4_RELEASE_MANIFEST_PATH']}
cfg.write_text(json.dumps(c,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
m=seal_manifest(m,app=app,release_id=rid,role='stage',delta_paths={'infrastructure/manager_input_attestation.py','stage_center_tick_config.json'},base_manifest=oldm);mp=root/'release-manifest.json';mp.write_text(json.dumps(m,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
# Replace only self-owned root occurrences; all unrelated fields retained.
def replace(v):
 if isinstance(v,str):return v.replace(str(old),str(app))
 if isinstance(v,list):return [replace(x) for x in v]
 if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
 return v
p=replace(p);p['EnvironmentVariables'].update(V4_APP_ROOT=str(app),V4_RELEASE_ID=rid,V4_RELEASE_MANIFEST_PATH=str(mp),V4_RELEASE_MANIFEST_SHA256=sha(mp))
draft=P/'STAGE_CANDIDATE.plist';draft.write_bytes(plistlib.dumps(p,sort_keys=True));draft.chmod(0o600)
result=dict(kind='stage',live_plist=str(live),before_sha256=sha(live),draft_plist=str(draft),draft_plist_sha256=sha(draft),old_app_root=str(old),app_root=str(app),manifest=str(mp),manifest_sha256=sha(mp),release_id=rid,main_owner=c['research_owner_binding'],historical=c['research_historical_owner_bindings'],transition=c['research_transition_owner_binding'])
(P/'STAGE_PACKAGE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['app_root','manifest_sha256','draft_plist_sha256']}))
