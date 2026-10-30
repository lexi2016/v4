"""This repair only: exact installed parents, display names and HTML-only copies."""
from pathlib import Path
import copy,difflib,hashlib,importlib.util,json,os,plistlib,re,shutil,subprocess,sys,tempfile
HERE=Path(__file__).resolve().parent;TASK=HERE.parents[3]
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/display_name_chart_interaction_fix');DAILY=B.parent.parent/'today_full_r1/daily_products/a_share';B.mkdir(exist_ok=True)
sys.path.insert(0,str(TASK));from ops.api_release_integration import inventory_tree,inventory_digest
from ops import render_original_formula_projection as renderer
from ops import research_panel_daily_product as owner
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
ref=lambda p:{'path':str(Path(p).resolve()),'sha256':sha(p)}
def save(p,v):return owner.save(p,v)
def load(r):return json.loads(owner.checked(r).read_text())
def merge(name,current):
 base=subprocess.run(['git','show','HEAD:'+name],cwd=TASK,check=True,capture_output=True).stdout;after=(TASK/name).read_bytes()
 if name=='infrastructure/research_lane_source.py':
  old=b'        product = self.read_a_daily_product(date)\n';new=b'        product = self.read_a_daily_product(date, include_display_names=False)\n';assert current.count(old)==base.count(old)==1;current=current.replace(old,new,1);base=base.replace(old,new,1)
 with tempfile.TemporaryDirectory(prefix='c8-source-merge-') as td:
  paths=[Path(td)/s for s in ['current','base','after']]
  for p,raw in zip(paths,[current,base,after]):p.write_bytes(raw)
  result=subprocess.run(['git','merge-file','-p',*map(str,paths)],capture_output=True)
  if result.returncode:raise ValueError('C8_CONCURRENT_SOURCE_CONFLICT:'+name)
  return result.stdout

receipts=load(ref(B/'CANDIDATES.json')) if '--data-only' in sys.argv else {};patches=[]
for role,label,paths in ([] if '--data-only' in sys.argv else [
 ('api','com.lexi.v4.api',['infrastructure/research_lane_source.py','research-panel/numeric283-panel.js','research-panel/related-reports.js']),
 ('main','com.lexi.v4.scheduler',['ops/research_panel_daily_product.py','ops/render_original_formula_projection.py'])]):
 before=Path('/Users/lexi/Library/LaunchAgents')/(label+'.plist');bp=B/(label+'.before.plist');bp.write_bytes(before.read_bytes());pl=plistlib.loads(bp.read_bytes());old=Path(pl['EnvironmentVariables']['V4_APP_ROOT']).parent;new=old.parent/('a-daily-name-zoom-20261030-r1-'+role)
 if new.exists():raise FileExistsError('preserve existing candidate:'+str(new))
 new.mkdir();baseline=inventory_tree(old/'app');shutil.copytree(old/'app',new/'app',symlinks=True)
 if role=='api':shutil.copytree(old/'research-panel',new/'research-panel',symlinks=True)
 changed={}
 for name in paths:
  target=new/name if name.startswith('research-panel/') else new/'app'/name;pre=target.read_bytes();post=merge(name,pre);target.chmod(target.stat().st_mode|0o200);target.write_bytes(post);changed[name]={'before_sha256':hashlib.sha256(pre).hexdigest(),'after':ref(target)};patches.extend(difflib.unified_diff(pre.decode().splitlines(True),post.decode().splitlines(True),fromfile=role+'/a/'+name,tofile=role+'/b/'+name))
 entries=inventory_tree(new/'app');bm={r['path']:r for r in baseline};am={r['path']:r for r in entries};actual={p for p in bm.keys()|am.keys() if bm.get(p)!=am.get(p)};assert actual=={p for p in paths if not p.startswith('research-panel/')}
 manifest=json.loads((old/'release-manifest.json').read_text());manifest.update(release_id=new.name,app_root=str(new/'app'),parent_release_root=str(old),source_root=str(TASK),activation_status='INACTIVE_C8_PENDING_REVIEW');manifest['candidate'].update(root=str(new),app_root=str(new/'app'),release_id=new.name);manifest['application_inventory']={'entries':entries,'entry_count':len(entries),'aggregate_sha256':inventory_digest(entries)};manifest['app_files']=[dict(path=r['path'],kind='file',sha256=r['sha256'],size=r['size']) for r in entries if r['kind']=='file']
 if role=='api':
  assets=json.loads((old/'research-panel-assets.json').read_text())
  for row in assets['files']:row['sha256']=sha(new/'research-panel'/row['path'])
  assetref=save(new/'research-panel-assets.json',assets);manifest['research_panel'].update(root=str(new/'research-panel'),asset_manifest=assetref['path'],asset_manifest_sha256=assetref['sha256'])
 mfref=save(new/'release-manifest.json',manifest)
 def rewrite(v):
  if isinstance(v,str):return v.replace(str(old),str(new))
  if isinstance(v,list):return [rewrite(x) for x in v]
  if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
  return v
 pl=rewrite(pl);pl['EnvironmentVariables']['V4_RELEASE_ID']=new.name;pl['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256']=mfref['sha256'];candidate=B/(label+'.candidate.plist');candidate.write_bytes(plistlib.dumps(pl,sort_keys=True))
 receipts[role]={'manifest':mfref,'release':str(new),'parent':str(old),'plist_before':ref(bp),'plist_candidate':ref(candidate),'changed':changed,'all_other_app_bytes_preserved':True}
if patches:(HERE/'EXACT_INSTALLED_DELTA.diff').write_text(''.join(patches))
save(B/'CANDIDATES.json',receipts)
index_path=DAILY/'index.json';event_path=DAILY/'events/latest.json';index=json.loads(index_path.read_text());event=json.loads(event_path.read_text());mf=index['dates']['20261029'];numeric=load(mf);product=load(numeric['artifact']);bound=load(ref(B.parent/'install_and_single_stock_002003/CANARY_BINDING.json'));selector=bound['selector'];stat=Path(selector['path']).stat();assert all(getattr(stat,k)==v for k,v in selector['stat'].items());assert selector['sha256']==product['source_identity']['selector_artifact_sha256'];symbols=[r['symbol'] for r in product['rows']]
previous_names=[p for p in (DAILY/'display_names/20261029').glob('*/names.json') if json.loads(p.read_text()).get('numeric_manifest')==mf]
if '--data-only' in sys.argv and len(previous_names)==1:
 names_ref=ref(previous_names[0]);names=load(names_ref);items=names['items']
else:
 import pyarrow.parquet as pq
 frame=pq.read_table(selector['path'],columns=['ts_code','trade_date','name'],filters=[('ts_code','in',symbols),('trade_date','<=','20261029')]).to_pandas();frame=frame[frame.name.map(lambda v:isinstance(v,str) and bool(v.strip()))].sort_values(['ts_code','trade_date'],kind='stable');latest=frame.groupby('ts_code',sort=False).tail(1)
 items={r.ts_code:dict(symbol=r.ts_code,name=r.name.strip(),source_date=str(r.trade_date)) for r in latest.itertuples()};assert items['002003.SZ']['name']=='伟星股份'
 names=dict(schema_version='v4.a_share.daily_display_names.v1',numeric_manifest=mf,data_date='20261029',source_generation=product['source_generation'],input_sha256=product['source_identity']['input_sha256'],selector={k:v for k,v in selector.items() if k!='stat'},items=items,**owner.FLAGS);names_ref=owner.save(DAILY/'display_names/20261029'/owner.digest(names)/'names.json',names,immutable=True)
descriptor=copy.deepcopy(index['original_charts']['20261029']);chart_manifest=load(descriptor['manifest']);receipt=load(descriptor['receipt']);output=B/'interactive_html';output.mkdir(exist_ok=True);payload_checks=[]
for symbol,item in chart_manifest['samples'].items():
 original=owner.checked(item['html']).read_text();adapted=renderer.interactive_chart_html(original)
 assert re.search(r"<script>(.*?)window.fetch=",original,re.S).group(1)==re.search(r"<script>(.*?)window.fetch=",adapted,re.S).group(1)
 p=output/(symbol+'.html');p.write_text(adapted);newref=ref(p);item['html']=newref
 record=next(row for row in receipt['records'] if row['symbol']==symbol);record['html']=newref
 payload_checks.append(symbol)
assert len(payload_checks)==247
chart_manifest['html_interaction_source']=ref(TASK/'ops/render_original_formula_projection.py');receipt['html_interaction_source']=chart_manifest['html_interaction_source'];descriptor['manifest']=save(B/'HTML_MANIFEST.json',chart_manifest);descriptor['receipt']=save(B/'HTML_COMPLETION.json',receipt)
index.setdefault('display_names',{})['20261029']=names_ref;index['original_charts']['20261029']=descriptor;event.update(display_names=names_ref,original_charts=descriptor,event_id=owner.digest(dict(numeric_manifest=mf,display_names=names_ref,original_charts=descriptor)))
plan={'status':'C8_PREPARED_NOT_PUBLISHED','index':{'target':str(index_path),'before':ref(index_path),'candidate':save(B/'staged_index.json',index)},'event':{'target':str(event_path),'before':ref(event_path),'candidate':save(B/'staged_event.json',event)},'numeric_manifest_unchanged':mf,'numeric_artifact_unchanged':numeric['artifact'],'name_binding':names_ref,'names_count':len(items),'002003':items['002003.SZ'],'HTML_only_count':len(payload_checks),'payload_247_byte_identical':True,'all_PNG_projection_refs_unchanged':True,'candidate_receipt':ref(B/'CANDIDATES.json'),**owner.FLAGS};save(B/'PUBLICATION_PLAN.json',plan);print(json.dumps({'status':plan['status'],'candidates':{k:v['manifest'] for k,v in receipts.items()},'names':len(items),'html':len(payload_checks),'sample':plan['002003'],'plan':ref(B/'PUBLICATION_PLAN.json')},ensure_ascii=False),flush=True)
