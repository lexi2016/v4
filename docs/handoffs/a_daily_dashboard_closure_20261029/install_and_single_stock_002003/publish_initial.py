"""CAS bind already accepted247 artifacts; no numerical or chart computation."""
from pathlib import Path
import argparse,hashlib,importlib.util,json
HERE=Path(__file__).resolve().parent
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/install_and_single_stock_002003')
ROOT=B.parent.parent/'today_full_r1/daily_products/a_share'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def ref(p):return {'path':str(Path(p).resolve()),'sha256':sha(p)}
def owner():
 p=HERE/'composed_source/ops/research_panel_daily_product.py';spec=importlib.util.spec_from_file_location('single_publish_owner_save',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def prepare():
 m=owner();index_path=ROOT/'index.json';event_path=ROOT/'events/latest.json';index=json.loads(index_path.read_text());event=json.loads(event_path.read_text());manifest=index['dates']['20261029'];numeric=json.loads(m.checked(manifest).read_text());product=json.loads(m.checked(numeric['artifact']).read_text())
 charts=B.parent/'original_formula_charts_247';descriptor={'status':'MECHANICAL_247_DELIVERY_PASS','numeric_manifest':manifest,'manifest':ref(charts/'MANIFEST.json'),'receipt':ref(charts/'COMPLETION_RECEIPT_247.json')}
 chart_receipt=json.loads(m.checked(descriptor['receipt']).read_text());assert chart_receipt['source_binding']['manifest']==manifest and chart_receipt['source_binding']['product']==numeric['artifact'];assert product['unique_count']==247 and product['processed_count']==5808
 index.setdefault('original_charts',{})['20261029']=descriptor;event['original_charts']=descriptor;event['event_id']=m.digest({'numeric_manifest':manifest,'original_charts':descriptor})
 index_candidate=m.save(B/'initial_data/index.json',index);event_candidate=m.save(B/'initial_data/latest.json',event)
 plan={'status':'PREPARED_METADATA_ONLY_WAIT_COMPOSED_REVIEW','numeric_manifest':manifest,'unchanged_numeric_artifact':numeric['artifact'],'index':{'target':str(index_path),'before':ref(index_path),'candidate':index_candidate},'event':{'target':str(event_path),'before':ref(event_path),'candidate':event_candidate},'rows':247,'processed_count':5808,'existing_chart_descriptor':descriptor,'source_save':ref(HERE/'composed_source/ops/research_panel_daily_product.py'),'no_compute_or_render':True,**m.FLAGS};m.save(B/'INITIAL_DATA_PLAN.json',plan);print(json.dumps({'status':plan['status'],'plan':ref(B/'INITIAL_DATA_PLAN.json')}))

def apply(review_path):
 m=owner();plan_path=B/'INITIAL_DATA_PLAN.json';plan=json.loads(plan_path.read_text());review=json.loads(Path(review_path).read_text())
 if review.get('status')!='REVIEWED_PASS_COMPOSED_BINDING' or review.get('initial_data_plan_sha256')!=sha(plan_path):raise ValueError('COMPOSED_REVIEW_BINDING_REQUIRED')
 for key in ['index','event']:
  step=plan[key];m.checked(step['candidate'])
  if sha(step['target'])!=step['before']['sha256']:raise ValueError('INITIAL_DATA_CAS_DRIFT:'+key)
 # Publish original index then original completion; immutable numeric/chart refs remain unchanged.
 after={}
 for key in ['index','event']:
  step=plan[key];after[key]=m.save(step['target'],json.loads(Path(step['candidate']['path']).read_text()))
 m.save(B/'INITIAL_DATA_PUBLISH_RECEIPT.json',{'status':'PUBLISHED_EXISTING247_METADATA_ONLY','plan':ref(plan_path),'review':ref(review_path),'after':after,'numeric_artifact_unchanged':plan['unchanged_numeric_artifact'],'no_compute_or_render':True,**m.FLAGS})
 print(json.dumps({'status':'PUBLISHED_EXISTING247_METADATA_ONLY','after':after}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--apply-reviewed',type=Path);a=p.parse_args()
 if a.prepare:prepare()
 elif a.apply_reviewed:apply(a.apply_reviewed)
 else:p.error('--prepare or --apply-reviewed required')
