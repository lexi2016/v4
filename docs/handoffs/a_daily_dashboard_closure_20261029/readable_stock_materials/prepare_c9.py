"""C9 only: material whitelist and completed event shards; exact inactive API."""
from pathlib import Path
import copy,csv,difflib,hashlib,json,plistlib,re,shutil,subprocess,sys,tempfile
HERE=Path(__file__).resolve().parent;TASK=HERE.parents[3];BASE='c918a17f1cfb74a4e01f19dc8f156f18217884ee'
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/readable_stock_materials');B.mkdir(exist_ok=True)
DAILY=B.parent.parent/'today_full_r1/daily_products/a_share'
sys.path.insert(0,str(TASK));from ops import research_panel_daily_product as owner
from ops.api_release_integration import inventory_tree,inventory_digest
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();ref=lambda p:dict(path=str(Path(p).resolve()),sha256=sha(p))
def load(r):return json.loads(owner.checked(r).read_text())
def save(p,v):return owner.save(p,v)
def merge(name,current):
 base=subprocess.run(['git','show',BASE+':'+name],cwd=TASK,check=True,capture_output=True).stdout;after=(TASK/name).read_bytes()
 if name=='research-panel/numeric283-panel.js':
  # C9 replaces the entire statistics presentation; C7's two old wording
  # amendments are deliberately superseded, all other installed code survives.
  start=b'  function statisticsPresentation(';end=b'  function validateDatedChart('
  a=current.index(start);b=current.index(end,a);x=base.index(start);y=base.index(end,x);current=current[:a]+base[x:y]+current[b:]
 with tempfile.TemporaryDirectory(prefix='c9-merge-') as td:
  files=[Path(td)/s for s in ['current','base','after']]
  for p,raw in zip(files,[current,base,after]):p.write_bytes(raw)
  result=subprocess.run(['git','merge-file','-p',*map(str,files)],capture_output=True)
  if result.returncode:raise ValueError('C9_CONCURRENT_SOURCE_CONFLICT:'+name)
  return result.stdout
def candidate():
 label='com.lexi.v4.api';live=Path('/Users/lexi/Library/LaunchAgents')/(label+'.plist');before=B/(label+'.before.plist');before.write_bytes(live.read_bytes());pl=plistlib.loads(before.read_bytes());old=Path(pl['EnvironmentVariables']['V4_APP_ROOT']).parent;new=old.parent/'a-daily-chart-first-20261030-r1-api'
 if new.exists():raise FileExistsError('preserve existing candidate:'+str(new))
 new.mkdir();base=inventory_tree(old/'app');shutil.copytree(old/'app',new/'app',symlinks=True);shutil.copytree(old/'research-panel',new/'research-panel',symlinks=True)
 paths=['infrastructure/research_lane_source.py','apps/api/v4_api/research_router.py','research-panel/daily.html','research-panel/numeric283-panel.js','research-panel/related-reports.js'];changed={};diff=[]
 for name in paths:
  target=new/name if name.startswith('research-panel/') else new/'app'/name;pre=target.read_bytes();post=merge(name,pre);target.chmod(target.stat().st_mode|0o200);target.write_bytes(post);changed[name]=dict(before_sha256=hashlib.sha256(pre).hexdigest(),after=ref(target));diff.extend(difflib.unified_diff(pre.decode().splitlines(True),post.decode().splitlines(True),fromfile='a/'+name,tofile='b/'+name))
 entries=inventory_tree(new/'app');bm={r['path']:r for r in base};am={r['path']:r for r in entries};assert {p for p in bm.keys()|am.keys() if bm.get(p)!=am.get(p)}==set(paths[:2])
 assets=json.loads((old/'research-panel-assets.json').read_text())
 for row in assets['files']:row['sha256']=sha(new/'research-panel'/row['path'])
 assetref=save(new/'research-panel-assets.json',assets);m=json.loads((old/'release-manifest.json').read_text());m.update(release_id=new.name,app_root=str(new/'app'),source_root=str(TASK),parent_release_root=str(old),activation_status='INACTIVE_C9_PENDING_REVIEW');m['candidate'].update(root=str(new),app_root=str(new/'app'),release_id=new.name);m['application_inventory']=dict(entries=entries,entry_count=len(entries),aggregate_sha256=inventory_digest(entries));m['app_files']=[dict(path=r['path'],kind='file',sha256=r['sha256'],size=r['size']) for r in entries if r['kind']=='file'];m['research_panel'].update(root=str(new/'research-panel'),asset_manifest=assetref['path'],asset_manifest_sha256=assetref['sha256']);mf=save(new/'release-manifest.json',m)
 def rewrite(v):
  if isinstance(v,str):return v.replace(str(old),str(new))
  if isinstance(v,list):return [rewrite(x) for x in v]
  if isinstance(v,dict):return {k:rewrite(x) for k,x in v.items()}
  return v
 pl=rewrite(pl);pl['EnvironmentVariables'].update(V4_RELEASE_ID=new.name,V4_RELEASE_MANIFEST_SHA256=mf['sha256']);target=B/(label+'.candidate.plist');target.write_bytes(plistlib.dumps(pl,sort_keys=True));(HERE/'EXACT_INSTALLED_DELTA.diff').write_text(''.join(diff));return dict(api=dict(release=str(new),parent=str(old),manifest=mf,plist_before=ref(before),plist_candidate=ref(target),changed=changed,other_app_and_static_bytes_preserved=True),Main='UNCHANGED_NO_RESTART')
def refresh_candidate():
 c=json.loads((B/'CANDIDATES.json').read_text());r=c['api'];new=Path(r['release']);old=Path(r['parent']);diff=[]
 for name in list(r['changed']):
  parent=old/name if name.startswith('research-panel/') else old/'app'/name
  target=new/name if name.startswith('research-panel/') else new/'app'/name
  pre=parent.read_bytes();post=merge(name,pre);target.chmod(target.stat().st_mode|0o200);target.write_bytes(post);r['changed'][name]=dict(before_sha256=hashlib.sha256(pre).hexdigest(),after=ref(target));diff.extend(difflib.unified_diff(pre.decode().splitlines(True),post.decode().splitlines(True),fromfile='a/'+name,tofile='b/'+name))
 assets=json.loads((new/'research-panel-assets.json').read_text());rows={x['path']:x for x in assets['files']}
 for path in sorted((TASK/'research-panel/code-map').glob('*')):
  if (path.suffix not in {'.json','.html'} and path.name!='ARCHIFY_LICENSE.txt') or path.name.startswith('.'):continue
  target=new/'research-panel/code-map'/path.name;target.parent.mkdir(exist_ok=True);target.write_bytes(path.read_bytes());name='code-map/'+path.name;rows[name]=dict(path=name,sha256=sha(target))
 for row in rows.values():row['sha256']=sha(new/'research-panel'/row['path'])
 assets['files']=sorted(rows.values(),key=lambda r:r['path']);assetref=save(new/'research-panel-assets.json',assets)
 m=json.loads((new/'release-manifest.json').read_text());entries=inventory_tree(new/'app');m['application_inventory']=dict(entries=entries,entry_count=len(entries),aggregate_sha256=inventory_digest(entries));m['app_files']=[dict(path=r['path'],kind='file',sha256=r['sha256'],size=r['size']) for r in entries if r['kind']=='file'];m['research_panel'].update(asset_manifest=assetref['path'],asset_manifest_sha256=assetref['sha256']);r['manifest']=save(new/'release-manifest.json',m)
 pl=plistlib.loads(Path(r['plist_candidate']['path']).read_bytes());pl['EnvironmentVariables']['V4_RELEASE_MANIFEST_SHA256']=r['manifest']['sha256'];Path(r['plist_candidate']['path']).write_bytes(plistlib.dumps(pl,sort_keys=True));r['plist_candidate']=ref(r['plist_candidate']['path']);save(B/'CANDIDATES.json',c);(HERE/'EXACT_INSTALLED_DELTA.diff').write_text(''.join(diff));print(json.dumps(dict(status='C9_REFRESHED_INACTIVE',api_manifest=r['manifest'],Main='UNCHANGED')))
def data():
 ip=DAILY/'index.json';ep=DAILY/'events/latest.json';index=json.loads(ip.read_text());event=json.loads(ep.read_text());mf=index['dates']['20261029'];numeric=load(mf);product=load(numeric['artifact']);symbols={r['symbol'] for r in product['rows']};cards_path=B.parent/'preopen_working/observation_cards.json';csv_path=B.parent/'chat_return_0200/report_index.csv';cards=load(ref(cards_path));source_refs=dict(observation_cards=ref(cards_path),report_catalog=ref(csv_path));bycode={r['symbol']:r for r in cards['cards']};assert symbols==set(bycode) and len(symbols)==247
 catalog={s:[] for s in symbols}
 for row in csv.DictReader(csv_path.open(encoding='utf-8-sig')):
  if row.get('symbol') in symbols and row.get('covered_symbol',row['symbol'])==row['symbol']:catalog[row['symbol']].append(row)
 items={}
 for symbol in sorted(symbols):
  r=bycode[symbol]
  if r['source_generation']!=product['source_generation'] or r['source_input_sha256']!=product['source_identity']['input_sha256'] or r['signal_data_date']!=product['data_date']:raise ValueError('RECEIVED_MATERIAL_IDENTITY_CONFLICT:'+symbol)
  fields={k:r.get(k) for k in ['reference_name','business_reported','industry_reported','shareholders_reported','financials_reported','fundamental_state']};provenance=r.get('provenance_details_received') or {};fields['provenance_details']={k:provenance.get(k) for k in ['financial_periods','shareholder_count_history','controller','top10_concentration','top10_tradable_concentration','detail_object_reference','maximum_claim','projection_limit']};stored=r.get('report_binding_candidate');fields['stored_report']={k:stored[k] for k in ['document','source_detail_receipt','integrity_status','relation_class','semantic_status'] if k in stored} if isinstance(stored,dict) else None
  shard=dict(schema_version='v4.a_share.company_materials.v1',symbol=symbol,data_date=product['data_date'],source_generation=product['source_generation'],input_sha256=product['source_identity']['input_sha256'],numeric_manifest=mf,source_refs=source_refs,report_catalog=catalog[symbol],**fields,**owner.FLAGS)
  items[symbol]=owner.save(DAILY/'company_materials/20261029'/owner.digest(shard)/(symbol+'.json'),shard,immutable=True)
 manifest=dict(schema_version='v4.a_share.company_materials_index.v1',data_date=product['data_date'],numeric_manifest=mf,source_generation=product['source_generation'],input_sha256=product['source_identity']['input_sha256'],source_refs=source_refs,items=items,**owner.FLAGS);material_ref=owner.save(DAILY/'company_materials/20261029'/owner.digest(manifest)/'index.json',manifest,immutable=True)
 completed=load(ref(B/'STRATA_RESULT.json'))
 if completed['status']!='COMPLETED_DESCRIPTIVE_SINGLE_STOCK_PARITY_PASS':raise ValueError('REGISTERED_SINGLE_STRATA_REQUIRED')
 cases=load(completed['shard']);case_ref=owner.save(DAILY/'event_cases/20261029'/owner.digest(cases)/'002003.SZ.json',cases,immutable=True);case_index=dict(schema_version='v4.a_share.event_cases_index.v1',data_date=product['data_date'],numeric_manifest=mf,source_generation=product['source_generation'],input_sha256=product['source_identity']['input_sha256'],items={'002003.SZ':case_ref},**owner.FLAGS);events_ref=owner.save(DAILY/'event_cases/20261029'/owner.digest(case_index)/'index.json',case_index,immutable=True)
 index.setdefault('company_materials',{})['20261029']=material_ref;index.setdefault('event_cases',{})['20261029']=events_ref;event.update(company_materials=material_ref,event_cases=events_ref,event_id=owner.digest(dict(numeric_manifest=mf,company_materials=material_ref,event_cases=events_ref,original_charts=event['original_charts'],display_names=event.get('display_names'))))
 plan=dict(owner_publisher=dict(path=str(Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-name-zoom-20261030-r1-main/app/ops/research_panel_daily_product.py')),sha256='a281777b2b5120980151220d832d360498c8c53fcdd43d464bc7a52eae765abe',source_role='C8_MAIN_ORIGINAL_OWNER_EXISTING_NO_SECOND_PRODUCER'),status='C9_PREPARED_NOT_PUBLISHED',index=dict(target=str(ip),before=ref(ip),candidate=save(B/'staged_index.json',index)),event=dict(target=str(ep),before=ref(ep),candidate=save(B/'staged_event.json',event)),numeric_manifest_unchanged=mf,numeric_artifact_unchanged=numeric['artifact'],company_materials=material_ref,event_cases=events_ref,material_shards=247,real_history_symbol_only='002003.SZ',no_same_event_or_price_projection_from_chat=True,source_refs=source_refs,**owner.FLAGS);save(B/'PUBLICATION_PLAN.json',plan);print(json.dumps(dict(status=plan['status'],plan=ref(B/'PUBLICATION_PLAN.json'),material_shards=247,company_materials=material_ref,event_cases=events_ref),ensure_ascii=False))
if __name__=='__main__':
 if '--refresh-candidate' in sys.argv:refresh_candidate();raise SystemExit(0)
 if '--data-only' not in sys.argv:print(json.dumps(dict(candidate=save(B/'CANDIDATES.json',candidate())),ensure_ascii=False),flush=True)
 if '--candidate-only' not in sys.argv:data()
