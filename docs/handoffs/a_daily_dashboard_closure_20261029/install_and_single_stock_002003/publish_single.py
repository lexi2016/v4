"""One registered002003 result into the complete owner product; never compute."""
from pathlib import Path
import argparse,copy,fcntl,hashlib,importlib.util,json,sys
HERE=Path(__file__).resolve().parent
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/install_and_single_stock_002003')
ROOT=B.parent.parent/'today_full_r1/daily_products/a_share';API=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-dashboard-c6-20261030-r2-api/app')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):return {'path':str(Path(p).resolve()),'sha256':sha(p)}
def owner():
 p=HERE/'composed_source/ops/research_panel_daily_product.py';spec=importlib.util.spec_from_file_location('single_merge_original_owner',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def load(m,r):return json.loads(m.checked(r).read_text())
def prepare():
 m=owner();binding=load(m,ref(B/'CANARY_BINDING.json'));result=load(m,ref(B/'single_run/RESULT.json'))
 if (result['status']!='COMPLETED_WAIT_REAL_LINEAGE_ACCEPTANCE' or result['binding']!=ref(B/'CANARY_BINDING.json') or result['symbol']!='002003.SZ' or not result['coverage']['known_full_history'] or result['coverage']['missing']):raise ValueError('SINGLE_COMPLETION_BINDING_INVALID')
 for r in binding['pointers']+[binding['source_config']]+binding['code']:m.checked(r)
 index_path=ROOT/'index.json';event_path=ROOT/'events/latest.json';index=json.loads(index_path.read_text());event=json.loads(event_path.read_text());old_manifest=index['dates']['20261029']
 if old_manifest!=binding['prior_manifest']:raise ValueError('SINGLE_MERGE_NUMERIC_SOURCE_CHANGED')
 mf=load(m,old_manifest);product=load(m,mf['artifact']);oldrow=load(m,product['row_refs']['002003.SZ']);newrow=load(m,result['row'])
 if (product['processed_count']!=5808 or product['unique_count']!=247 or mf['artifact']!=binding['prior_product'] or product['row_refs']['002003.SZ']!=binding['prior_row'] or {k:v for k,v in oldrow.items() if k not in {'statistics','historical_coverage'}}!={k:v for k,v in newrow.items() if k not in {'statistics','historical_coverage'}}):raise ValueError('SINGLE_MERGE_POOL_OR_NONSTATISTICAL_ROW_CHANGE')
 if newrow['historical_coverage']!=result['coverage']:raise ValueError('SINGLE_MERGE_COVERAGE_RESULT_CONFLICT')
 sys.path[:0]=[str(API/'upstreams'),str(API)]
 from infrastructure.research_lane_source import ResearchLaneSource
 ResearchLaneSource._a_daily_checkpoint_binding(None,newrow,product,'002003.SZ','20261029')
 cache=load(m,result['history_cache']);m.checked(binding['prior_history_cache'])
 if cache['coverage']!=result['coverage'] or cache['source_identity']!=binding['source_identity'] or cache['rules_signature']!=m.digest(load(m,binding['source_config'])):raise ValueError('SINGLE_MERGE_HISTORY_IDENTITY_INVALID')
 # Immutable new row/version. Original full pool and all other row refs survive.
 runkey=m.digest({'prior_manifest':old_manifest,'binding':result['binding'],'row':result['row']})
 rowref=m.save(ROOT/'checkpoints/20261029'/runkey/'002003.SZ.json',newrow,immutable=True)
 newproduct=copy.deepcopy(product);newproduct['row_refs']['002003.SZ']=rowref
 version=ROOT/'versions/20261029'/product['source_generation']/m.digest(newproduct);artifact=m.save(version/'product.json',newproduct,immutable=True)
 newmf={**mf,'artifact':artifact};manifest=m.save(version/'manifest.json',newmf,immutable=True)
 charts={'status':'MECHANICAL_247_DELIVERY_PASS','numeric_manifest':manifest,'manifest':binding['chart_manifest'],'receipt':binding['chart_completion'],'chart_origin_manifest':old_manifest,'history_updated_symbols':['002003.SZ']}
 for r in [charts['manifest'],charts['receipt'],binding['existing_chart']['projection'],binding['existing_chart']['html']]:m.checked(r)
 png=binding['existing_chart']['PNG'];m.checked({'path':png['path'],'sha256':png['sha256']})
 index['dates']['20261029']=manifest;index.setdefault('original_charts',{})['20261029']=charts
 if index.get('latest')==old_manifest:index['latest']=manifest
 event.update(manifest=manifest,artifact=artifact,original_charts=charts,event_id=m.digest({'numeric_manifest':manifest,'original_charts':charts}))
 staged_index=m.save(B/'single_publish/index.json',index);staged_event=m.save(B/'single_publish/latest.json',event)
 plan={'status':'PREPARED_SINGLE_STATS_ONLY_WAIT_ROOT_REAL_ACCEPTANCE','result':ref(B/'single_run/RESULT.json'),'binding':result['binding'],'numeric_manifest':manifest,'previous_manifest':old_manifest,'index':{'target':str(index_path),'before':ref(index_path),'candidate':staged_index},'event':{'target':str(event_path),'before':ref(event_path),'candidate':staged_event},'history':{'target':binding['prior_history_cache']['path'],'before':binding['prior_history_cache'],'candidate':result['history_cache']},'immutable_row':rowref,'immutable_artifact':artifact,'unchanged_other_rows':5807,'unchanged_candidates':247,'row_changed_fields':['statistics','historical_coverage'],'existing_chart_projection':binding['existing_chart']['projection'],'existing_png_sha256':png['sha256'],'new_chart_calculations':0,'global_history_status':product['history_status'],**m.FLAGS}
 m.save(B/'SINGLE_PUBLISH_PLAN.json',plan);print(json.dumps({'status':plan['status'],'plan':ref(B/'SINGLE_PUBLISH_PLAN.json'),'manifest':manifest}))
def apply(review_path):
 m=owner();path=B/'SINGLE_PUBLISH_PLAN.json';plan=load(m,ref(path));review=json.loads(review_path.read_text())
 if (review.get('status')!='REVIEWED_PASS_ONE_REAL_HISTORY' or review.get('result_sha256')!=plan['result']['sha256'] or review.get('single_publish_plan_sha256')!=sha(path)):raise ValueError('ROOT_REAL_SINGLE_ACCEPTANCE_BINDING_REQUIRED')
 lock=open(B/'single-publish.lock','a+b');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 binding=load(m,plan['binding'])
 for r in binding['pointers']+[binding['source_config']]+binding['code']+[plan['result'],plan['immutable_row'],plan['immutable_artifact'],plan['numeric_manifest']]:m.checked(r)
 for key in ['history','index','event']:
  step=plan[key];m.checked(step['before']);m.checked(step['candidate'])
 # Cache persists first, then full-pool index and its original completion event.
 after={key:m.save(plan[key]['target'],load(m,plan[key]['candidate'])) for key in ['history','index','event']}
 m.save(B/'SINGLE_PUBLISH_RECEIPT.json',{'status':'PUBLISHED_002003_STATS_ONLY_IN_COMPLETE_PRODUCT','plan':ref(path),'review':ref(review_path),'after':after,'numeric_manifest':plan['numeric_manifest'],'unchanged_other_rows':5807,'unchanged_candidates':247,'new_chart_calculations':0,**m.FLAGS});print(json.dumps({'status':'PUBLISHED_002003_STATS_ONLY_IN_COMPLETE_PRODUCT','after':after}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--apply-reviewed',type=Path);a=p.parse_args()
 if a.prepare:prepare()
 elif a.apply_reviewed:apply(a.apply_reviewed)
 else:p.error('--prepare or --apply-reviewed required')
