"""This installation: exact active Main plus reviewed C4/C5/C6 and explicit output root."""
from pathlib import Path
import ast, hashlib, json, plistlib, shutil, subprocess, sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/install_and_single_stock_002003')
OLD=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-sop-closure-20261029-r1-main');NEW=OLD.parent/'a-daily-dashboard-c6-20261030-r1-main'
PRODUCT=B.parent.parent/'today_full_r1';C5=HERE.parent/'a_daily_1540_source';C6=HERE.parent/'history_prefix_reuse_source'
sys.path.insert(0,str(ROOT));from ops.api_release_integration import inventory_tree,inventory_digest
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n');return {'path':str(p),'sha256':sha(p)}
def gitbytes(name):return subprocess.run(['git','show','e6df789828ef064a9114e27962f99d2575711e7f:'+name],cwd=ROOT,check=True,capture_output=True).stdout
def rewrite(v):
 if isinstance(v,str):return v.replace(str(OLD),str(NEW))
 if isinstance(v,list):return [rewrite(x) for x in v]
 if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
 return v
def put(name,raw):
 p=NEW/'app'/name;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():p.chmod(p.stat().st_mode|0o200)
 p.write_bytes(raw)
if NEW.exists():raise FileExistsError('preserve existing inactive Main')
v=json.loads((C5/'OVERLAY_INVENTORY.json').read_text());base=inventory_tree(OLD/'app');NEW.mkdir();shutil.copytree(OLD/'app',NEW/'app',symlinks=True)
assert inventory_tree(NEW/'app')==base
for name,item in v['files'].items():
 if name=='ops/research_panel_daily_product.py':put(name,gitbytes(name))
 elif name!='ops/macos_research_panel_daily_gate.py':assert sha(NEW/'app'/name)==item['before_sha256'],name
gate=NEW/'app/ops/macos_research_panel_daily_gate.py';assert sha(gate)==v['gate_dependency']['release_before_sha256'];gate.chmod(gate.stat().st_mode|0o200)
for patch in [C5/'dependencies/gate_materialize_daily_product.patch',C5/'CANDIDATE_OVERLAY.patch']:
 # Only files in the frozen overlay become writable; no unrelated dirty sources are copied.
 for name in v['files']:
  p=NEW/'app'/name
  if p.exists():p.chmod(p.stat().st_mode|0o200)
 subprocess.run(['git','apply','--check',str(patch)],cwd=NEW/'app',check=True,capture_output=True);subprocess.run(['git','apply',str(patch)],cwd=NEW/'app',check=True,capture_output=True)
for name,item in v['files'].items():assert sha(NEW/'app'/name)==item['after_sha256'],name
subprocess.run(['git','apply',str(C6/'C6_OVERLAY.patch')],cwd=NEW/'app',check=True,capture_output=True)
assert sha(NEW/'app/ops/research_panel_daily_product.py')==json.loads((C6/'OVERLAY_INVENTORY.json').read_text())['C6_producer_sha256']
extra=['ops/render_original_formula_projection.py','domains/research_daily_product.py','domains/research_daily_statistics.py','docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json']
for name in extra:put(name,gitbytes(name))
# Parent output root contract shared by the two existing owner entry points.
root_expr="Path(os.environ['V4_A_SHARE_DAILY_PRODUCT_ROOT'])/'daily_products/a_share' if os.environ.get('V4_A_SHARE_DAILY_PRODUCT_ROOT') else None"
for name,old,new in [
 ('ops/macos_research_panel_daily_gate.py','formula_result=formula)','formula_result=formula, output_root='+root_expr+')'),
 ('infrastructure/scheduling/executor_registry.py','target=int(request.business_date), cache_only=True)','target=int(request.business_date), cache_only=True, output_root='+root_expr+')')]:
 p=NEW/'app'/name;text=p.read_text();assert text.count(old)==1,name;text=text.replace(old,new,1);p.write_text(text)
entries=inventory_tree(NEW/'app');before={r['path']:r for r in base};after={r['path']:r for r in entries};delta=[p for p in sorted(set(before)|set(after)) if before.get(p)!=after.get(p)];assert set(delta)==set(v['files'])|set(extra),delta
for name in delta:
 if name.endswith('.py'):ast.parse((NEW/'app'/name).read_text(),filename=name)
manifest=json.loads((OLD/'release-manifest.json').read_text());manifest.update(release_id=NEW.name,app_root=str(NEW/'app'),source_root=str(ROOT),parent_release_root=str(OLD),activation_status='INACTIVE_PENDING_COMPOSED_REVIEW');manifest['candidate'].update(root=str(NEW),app_root=str(NEW/'app'),release_id=NEW.name);manifest['application_inventory']={'entries':entries,'entry_count':len(entries),'aggregate_sha256':inventory_digest(entries)};manifest['app_files']=[{'path':r['path'],'kind':'file','sha256':r['sha256'],'size':r['size']} for r in entries if r['kind']=='file'];save(NEW/'release-manifest.json',manifest)
pl=rewrite(plistlib.loads((B/'com.lexi.v4.scheduler.before.plist').read_bytes()));env=pl['EnvironmentVariables'];env.update(V4_RELEASE_ID=NEW.name,V4_APP_ROOT=str(NEW/'app'),V4_RELEASE_MANIFEST_PATH=str(NEW/'release-manifest.json'),V4_RELEASE_MANIFEST_SHA256=sha(NEW/'release-manifest.json'),V4_A_SHARE_DAILY_PRODUCT_ROOT=str(PRODUCT),V4_RESEARCH_DAILY_PRODUCT_CONFIG=str(ROOT/'docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json'));template=B/'com.lexi.v4.scheduler.candidate.plist';template.write_bytes(plistlib.dumps(pl,sort_keys=True))
receipt={'status':'MAIN_INACTIVE_EXACT_C4_C5_C6_PREPARED','manifest':{'path':str(NEW/'release-manifest.json'),'sha256':sha(NEW/'release-manifest.json')},'delta':{p:{'before':before.get(p),'after':after.get(p)} for p in delta},'plist_candidate':{'path':str(template),'sha256':sha(template)},'apply_order':['active Main exact inventory','C4 original producer','C4 accepted8line gatehook','C5 accepted10path overlay','C6 accepted2function overlay','C4 renderer/rule/statistics/config','explicit output_root at original gate and cached leaf'],'root_binding':{'daily_parent':str(PRODUCT),'raw_history_root':env['V4_RESEARCH_PANEL_A_DATA_ROOT'],'source_config':env['V4_RESEARCH_DAILY_PRODUCT_CONFIG']},'targeted':'all accepted overlay before/after SHA verified;14path allowlist;Python AST parse all changed py','runtime_installed':False,'natural1540':'NOT_RUN','RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False};save(B/'MAIN_CANDIDATE_RECEIPT.json',receipt);print(json.dumps({'status':receipt['status'],'manifest':receipt['manifest'],'delta_count':len(delta)}))
