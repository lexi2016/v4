"""Prepare the single-stock feedback isolated exact-delta package; no activation.

Run with --prepare once, then --check immediately before any separate owner
cutover. This program never edits a plist, service, shared file, or pointer.
"""
from pathlib import Path
from urllib.request import build_opener,ProxyHandler
import argparse,hashlib,json,plistlib,re,shutil,subprocess
from ops import research_panel_qfq as q
R=Path('/Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/kb_panel_upgrade_20261101/junda_feedback_20261101_r1');W=Path(q.__file__).resolve().parents[1]
KEYS=['V4_APP_ROOT','V4_RELEASE_ID','V4_RELEASE_MANIFEST_PATH','V4_RELEASE_MANIFEST_SHA256','V4_RESEARCH_PANEL_ROOT','V4_RESEARCH_PANEL_ASSET_MANIFEST','V4_WORKBENCH_HOST_BINDING','V4_WORKBENCH_HOST_BINDING_SHA256']
EXPECTED={'V4_APP_ROOT':'/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/date-history-fix-20261101-r1/app','V4_RESEARCH_PANEL_ROOT':'/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/junda-single-20261101-310e64e55bd17d85/research-panel'}
FILES={'api:infrastructure/research_workbench_host.py':'3b0a9574beef4ca94e697ec9ce7181e7d016456784a4224bdae4145b81e14af9',
'site:workbench.html':'ea485c47a5197e616858a054e00071fcf93dfe702b7df148c885ae0aac46dcd3',
'site:workbench-host/bootstrap.mjs':'42a829275b8bb8b7d5e819f14153bf78798396be28c47feb72721cd5e0f0343d',
'site:workbench-host/kb-single-stock.mjs':'39329558fb8ebba69c2f0c3687dcb38f76893e387944553743e30331e785aa95',
'site:workbench-host/dot/shell/workbench.local.mjs':'eee0fe8c2d7a8f47e3298fb3e69d35ddc4952dfcf9402cdd127ec56259a5e0a6',
'site:workbench-host/kb-chart-overlay.mjs':None,'site:workbench-host/kb-signal-view.mjs':None}

def state():
 pids=subprocess.check_output(['lsof','-nP','-iTCP:8873','-sTCP:LISTEN','-t'],text=True).split()
 if len(pids)!=1:raise RuntimeError('ACTIVE_8873_OWNER_AMBIGUOUS')
 pid=int(pids[0]);raw=subprocess.check_output(['ps','eww','-p',str(pid),'-o','command='],text=True);env={}
 for key in KEYS:
  m=re.search(r'(?:^|\s)'+re.escape(key)+r'=(.*?)(?=\s+[A-Za-z_][A-Za-z_0-9]*=|$)',raw)
  if not m:raise RuntimeError('ACTIVE_ENV_MISSING:'+key)
  env[key]=m.group(1)
 if any(env[k]!=v for k,v in EXPECTED.items()):raise RuntimeError('ACTIVE_ROOT_CHANGED')
 plist=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v4.api.plist');payload=plistlib.loads(plist.read_bytes())
 frozen=json.loads((R/'FROZEN_BASELINE_REBASE_R2.json').read_text())
 if (pid!=frozen['pid'] or q.sha(plist)!=frozen['api_plist']['sha256'] or env['V4_APP_ROOT']!=frozen['app_root']
     or env['V4_RESEARCH_PANEL_ROOT']!=frozen['site_root']
     or env['V4_RELEASE_MANIFEST_PATH']!=frozen['release_manifest']['path']
     or env['V4_RELEASE_MANIFEST_SHA256']!=frozen['release_manifest']['sha256']
     or env['V4_WORKBENCH_HOST_BINDING']!=frozen['binding']['path']
     or env['V4_WORKBENCH_HOST_BINDING_SHA256']!=frozen['binding']['sha256']):raise RuntimeError('FROZEN_BASELINE_CHANGED')
 if any(payload['EnvironmentVariables'].get(key)!=env[key] for key in KEYS):raise RuntimeError('ACTIVE_PLIST_ENV_MISMATCH')
 if q.sha(Path(env['V4_RELEASE_MANIFEST_PATH']))!=env['V4_RELEASE_MANIFEST_SHA256']:raise RuntimeError('ACTIVE_RELEASE_MANIFEST_CHANGED')
 roots={'api':Path(env['V4_APP_ROOT']),'site':Path(env['V4_RESEARCH_PANEL_ROOT'])};current={}
 for name,expected in FILES.items():
  group,relative=name.split(':',1);p=roots[group]/relative;current[name]=q.sha(p) if p.is_file() else None
  if current[name]!=expected:raise RuntimeError('ACTIVE_SOURCE_CHANGED:'+name)
 if current!=frozen['before']:raise RuntimeError('FROZEN_REBASE_DELTA_SOURCE_CHANGED')
 for key in ('V4_RESEARCH_PANEL_ASSET_MANIFEST','V4_WORKBENCH_HOST_BINDING'):
  path=Path(env[key]);env[key+'_SHA_ACTUAL']=q.sha(path)
 if env['V4_WORKBENCH_HOST_BINDING_SHA256']!=env['V4_WORKBENCH_HOST_BINDING_SHA_ACTUAL']:raise RuntimeError('ACTIVE_BINDING_SHA_CONFLICT')
 op=build_opener(ProxyHandler({}))
 with op.open('http://127.0.0.1:8873/api/v4/research/workbench/days/2026-10-30/versions',timeout=5) as response:v=json.load(response)
 with op.open('http://127.0.0.1:8873/api/v4/research/workbench/days/2026-10-30',timeout=5) as response:d=json.load(response)
 if (v['source_date'],v['observation_date'],v['generation'],v['input_sha256'])!=('2026-10-30','2026-11-02','d22220537892215832f0c01faeaadd11e282b4d65debf979152597a00d1829b5','9eef2834994e6156561efc9666182a2528734adb2a086dfd602c7b7c5f4ef774'):raise RuntimeError('ACTIVE_SOURCE_VERSION_CHANGED')
 if d['scope_count']!=172 or any(x['symbol']=='002865.SZ' for x in d['rows']):raise RuntimeError('ACTIVE_POOL_CHANGED')
 if subprocess.check_output(['lsof','-nP','-iTCP:8873','-sTCP:LISTEN','-t'],text=True).strip()!=str(pid):raise RuntimeError('ACTIVE_PID_CHANGED_DURING_READ')
 return {'pid':pid,'plist_sha256':q.sha(plist),'env':env,'files':current,'source_date':v['source_date'],'observation_date':v['observation_date'],'generation':v['generation'],'input_sha256':v['input_sha256'],'numeric_manifest':v['numeric_manifest'],'candidate_pool_count':d['scope_count']}
def prepare():
 current=state();candidate=json.loads(CAND.read_text());assert candidate['candidate_generation']==GEN
 for name,sha in candidate['candidate_identity']['source_sha256'].items():
  if q.sha(W/name)!=sha:raise RuntimeError('CANDIDATE_SOURCE_DRIFT:'+name)
 if current['numeric_manifest']!=candidate['numeric_manifest']:raise RuntimeError('ACTIVE_MANIFEST_CHANGED')
 STAGE.mkdir(exist_ok=True);env=current['env'];old_binding=Path(env['V4_WORKBENCH_HOST_BINDING']);old_assets=Path(env['V4_RESEARCH_PANEL_ASSET_MANIFEST']);binding=json.loads(old_binding.read_text());assets=json.loads(old_assets.read_text());binding['single_stock_research']={'path':candidate['binding']['path'],'sha256':candidate['binding']['sha256']};entries={v['path']:v for v in assets['files']}
 for name in ('workbench.html','workbench-host/bootstrap.mjs','workbench-host/kb-single-stock.mjs','workbench-host/dot/shell/workbench.local.mjs','workbench-host/kb-chart-overlay.mjs','workbench-host/kb-signal-view.mjs'):
  path=W/'research-panel'/name
  if name in entries:entries[name]['sha256']=q.sha(path)
  else:assets['files'].append({'path':name,'sha256':q.sha(path)})
 def write_immutable(path,data):
  path.parent.mkdir(parents=True,exist_ok=True)
  if path.exists() and path.read_bytes()!=data:raise RuntimeError('STAGE_EXISTING_CONFLICT:'+str(path))
  if not path.exists():path.write_bytes(data)
  return {'path':str(path),'sha256':q.sha(path),'bytes':len(data)}
 new_binding=write_immutable(STAGE/'new_workbench_binding.json',(json.dumps(binding,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode());new_assets=write_immutable(STAGE/'new_static_assets.json',(json.dumps(assets,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode());changes=[]
 for name,before in FILES.items():
  group,rel=name.split(':',1);candidate_path=(W/rel) if group=='api' else (W/'research-panel'/rel); old_root=Path(env['V4_APP_ROOT'] if group=='api' else env['V4_RESEARCH_PANEL_ROOT']);old_path=old_root/rel
  new=write_immutable(STAGE/'after'/group/rel,candidate_path.read_bytes());old=write_immutable(STAGE/'before'/group/rel,old_path.read_bytes()) if before else None
  changes.append({'kind':group,'path':rel,'before_sha256':before,'after':new,'rollback':old})
 for name,path in [('active_workbench_binding',old_binding),('active_static_manifest',old_assets)]:write_immutable(STAGE/'before'/name,path.read_bytes())
 baseline_ref=write_immutable(BASE,(json.dumps(current,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode());plan={'schema':'junda_workbench_activation_stage.v1','status':'PREPARED_NOT_ACTIVATED','candidate_generation':GEN,'baseline':baseline_ref,'changes':changes,'new_binding':new_binding,'new_asset_manifest':new_assets,'old_binding':{'path':str(old_binding),'sha256':q.sha(old_binding)},'old_asset_manifest':{'path':str(old_assets),'sha256':q.sha(old_assets)},'precondition':'same pid and exact active source/binding/manifest/172 rows; STOP on drift','cutover':'existing API owner only, from actual loaded API app and static bytes, apply the seven reviewed files as deltas; bind new immutable configs under guarded CAS','rollback':'if new candidate remains active, restore captured original API/static files and original config references through same owner; do not write global panel pointers','global_panel_pointers_write':False,'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False};ref=write_immutable(STAGE/'STAGED_DELTA.json',(json.dumps(plan,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode());print('PREPARED',json.dumps(ref,ensure_ascii=False))
def check():
 before=json.loads(BASE.read_text());now=state()
 if now!=before:raise RuntimeError('CAS_ACTIVE_BASELINE_CHANGED')
 plan=json.loads((STAGE/'STAGED_DELTA.json').read_text())
 for item in plan['changes']:
  for ref in (item['after'],item['rollback']):
   if ref:q._source(ref,owner='staged delta')
 for key in ('new_binding','new_asset_manifest'):q._source(plan[key],owner='staged config')
 print('CAS_PASS',json.dumps({'pid':now['pid'],'candidate_generation':GEN,'stage':str(STAGE)},ensure_ascii=False))
p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--check',action='store_true');p.add_argument('--candidate',type=Path,required=True);p.add_argument('--candidate-sha256',required=True);a=p.parse_args();assert a.prepare != a.check
CAND=a.candidate.resolve();assert CAND.parent==R and q.sha(CAND)==a.candidate_sha256
GEN=json.loads(CAND.read_text())['candidate_generation'];assert re.fullmatch(r'[0-9a-f]{64}',GEN)
assert CAND.name==f'JUNDA_FEEDBACK_CANDIDATE_{GEN[:16]}.json'
STAGE=R/f'activation_stage_{GEN[:16]}';BASE=STAGE/'ACTIVATION_BASELINE.json'
if a.prepare:prepare()
else:check()
