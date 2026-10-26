"""Exact fresh-owner composition; no active-schema relaxation or live actions."""
from pathlib import Path
import copy, hashlib, importlib.util, json, os, plistlib, shutil, subprocess, sys
B=Path(__file__).resolve().parent
W=Path('/Users/lexi/.codex/worktrees/mac-lifecycle-retry-guard-20261027/v4_app')
BASE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/runtime-graph-repair-20261026-api-r2')
P=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
TARGET=BASE.parent/'mac-lifecycle-notes-21-api-20261027-r2'
OUT=B/'api_package'/TARGET.name
MSHA='c4f1c68c8f0b2dcf9ed98949146ced5b3aafaa67beadbb3c0b1e847e4e811a59'
PSHA='ec095bb5615452c116e79d78f35a0c75e34cf4b67788d8a1dfe32b509354e550'
DELTA=['apps/api/v35_api/a_share_lifecycle_notes.json','apps/api/v35_api/a_share_panel_history.py']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):
    with Path(p).open('x') as f:json.dump(x,f,sort_keys=True,ensure_ascii=False,indent=2);f.write('\n')
def inventory(root):
    result={}
    for p in sorted(root.rglob('*')):
        assert not p.is_symlink(),'SYMLINK_REFUSED'
        if p.is_file():
            rel=p.relative_to(root).as_posix();assert '__pycache__' not in p.parts and not rel.endswith('.pyc')
            result[rel]={'sha256':sha(p),'bytes':p.stat().st_size}
    return result
assert sha(BASE/'release-manifest.json')==MSHA and sha(P)==PSHA
base=json.loads((BASE/'release-manifest.json').read_text())
assert base['schema_version']=='v4.runtime_graph_repair_release.v1' and base['app_root']==str(BASE/'app') and base['release_id']==BASE.name
before=inventory(BASE/'app');declared={r['path']:{'sha256':r['sha256'],'bytes':r['bytes']} for r in base['app_files']}
assert len(declared)==len(base['app_files'])==1319 and declared==before and base['symlinks']==[]
assert len(base['source_changes'])==6
OUT.mkdir(parents=True,exist_ok=False);shutil.copytree(BASE/'app',OUT/'app')
for rel in DELTA:shutil.copyfile(W/rel,OUT/'app'/rel)
after=inventory(OUT/'app');expected=copy.deepcopy(before)
for rel in DELTA:expected[rel]={'sha256':sha(W/rel),'bytes':(W/rel).stat().st_size}
assert after==expected and inventory(BASE/'app')==before
assert sum(before[k]==after[k] for k in before)==1317
assert all(after[r['path']]['sha256']==r['after_sha256'] for r in base['source_changes'])
sys.path.insert(0,str(W));from ops import build_release_candidate as builder
entries=builder.inventory_tree(OUT/'app')
manifest={'schema_version':builder.SCHEMA_VERSION,'candidate':{'root':str(OUT),'app_root':str(OUT/'app'),'release_id':TARGET.name,'module_role':'gateway'},
'application_inventory':{'entry_count':len(entries),'entries':entries,'aggregate_sha256':builder.inventory_digest(entries)},
'app_files':[{'path':k,**v} for k,v in after.items()],'symlinks':[],
'lifecycle_source_custody':{'baseline_release':str(BASE),'manifest_sha256':MSHA,'plist_sha256':PSHA,'delta_paths':DELTA,'preserved_count':1317,'graph_six_preserved':base['source_changes']},
'research_only':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
save(OUT/'release-manifest.json',manifest)
env=dict(os.environ,V35_APP_ROOT=str(OUT/'app'),V35_RELEASE_ID=TARGET.name,V35_RELEASE_MANIFEST_PATH=str(OUT/'release-manifest.json'),V35_RELEASE_MANIFEST_SHA256=sha(OUT/'release-manifest.json'))
code="import sys,json;sys.path.insert(0,sys.argv[1]);from infrastructure.scheduling.dispatcher import validate_release_identity;print(json.dumps(validate_release_identity(),sort_keys=True))"
r=subprocess.run([sys.executable,'-B','-c',code,str(OUT/'app')],cwd=OUT/'app',env=env,capture_output=True,text=True)
save(B/'control/ORIGINAL_DISPATCHER_FRESH_R2.json',{'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr});assert r.returncode==0
projected=copy.deepcopy(manifest);projected['candidate'].update(root=str(TARGET),app_root=str(TARGET/'app'))
project=B/'control/release-manifest.fresh-r2.materialized.json';save(project,projected)
raw=P.read_bytes();old=plistlib.loads(raw);new=copy.deepcopy(old)
updates={'V35_APP_ROOT':str(TARGET/'app'),'V35_RELEASE_ID':TARGET.name,'V35_RELEASE_MANIFEST_PATH':str(TARGET/'release-manifest.json'),'V35_RELEASE_MANIFEST_SHA256':sha(project)}
def value(k,v):
    if k in updates:return updates[k]
    if k=='PYTHONPATH':return ':'.join(str(TARGET/'app')+p[len(str(BASE/'app')):] if p==str(BASE/'app') or p.startswith(str(BASE/'app')+'/') else p for p in v.split(':'))
    return v
for k,v in old.get('EnvironmentVariables',{}).items():new['EnvironmentVariables'][k]=value(k,v)
for i,arg in enumerate(old['ProgramArguments']):
    if '=' in arg:k,v=arg.split('=',1);new['ProgramArguments'][i]=k+'='+value(k,v)
assert old['WorkingDirectory']==str(BASE/'app');new['WorkingDirectory']=str(TARGET/'app')
allowed=set(updates)|{'PYTHONPATH'}
assert all(new[k]==v for k,v in old.items() if k not in {'EnvironmentVariables','ProgramArguments','WorkingDirectory'})
assert all(new['EnvironmentVariables'][k]==v for k,v in old.get('EnvironmentVariables',{}).items() if k not in allowed)
assert all(a==b for a,b in zip(old['ProgramArguments'],new['ProgramArguments']) if a.split('=',1)[0] not in allowed)
(B/'control/api-only.fresh-r2.before.plist').write_bytes(raw)
newraw=plistlib.dumps(new,sort_keys=False);(B/'control/api-only.fresh-r2.candidate.plist').write_bytes(newraw)
assert sha(P)==PSHA and sha(BASE/'release-manifest.json')==MSHA
save(B/'control/API_FRESH_R2_PACKAGE.json',{'status':'FRESH_EXACT_TWO_FILE_CANDIDATE_DISPATCHER_PASS_INSTALL_INTERFACE_GAP','package_root':str(OUT),'target_root':str(TARGET),
'candidate_manifest_sha256':sha(OUT/'release-manifest.json'),'materialized_manifest':str(project),'materialized_manifest_sha256':sha(project),'base_manifest_sha256':MSHA,'base_plist_sha256':PSHA,
'candidate_plist_sha256':hashlib.sha256(newraw).hexdigest(),'files':1319,'non_delta_preserved':1317,'graph_six_preserved':True,'dispatcher_exit_code':0,
'interface_gap':'Original api_release_integration rejects active v4.runtime_graph_repair_release.v1; no schema bypass or forged api_integration receipt added. Root must coordinate existing owner/control before installing.',
'api_source_sha256':sha(OUT/'app'/DELTA[1]),'asset_sha256':sha(OUT/'app'/DELTA[0]),'service_actions':0})
print(json.dumps({'status':'FRESH_R2_CANDIDATE_READY','files':1319,'preserved':1317,'dispatcher':r.returncode,'materialized_manifest_sha256':sha(project)}))
