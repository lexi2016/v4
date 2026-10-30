"""Read staged index/event through candidate reader; never alter current pointers."""
from pathlib import Path
import hashlib,importlib.abc,importlib.util,json,sys,tempfile
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/install_and_single_stock_002003');API=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-dashboard-c6-20261030-r2-api/app');PRODUCT=B.parent.parent/'today_full_r1';ARTIFACT=B.parent.parent
class CandidateOnly(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] not in {'apps','domains','infrastructure','contracts','ops','stage_center','shared_data','upstreams'}:return None
  relative=Path(*fullname.split('.'))
  for base in [API,API/'upstreams']:
   p=base/relative.with_suffix('.py');init=base/relative/'__init__.py'
   if p.is_file():return importlib.util.spec_from_file_location(fullname,p)
   if init.is_file():return importlib.util.spec_from_file_location(fullname,init,submodule_search_locations=[str(init.parent)])
   if (base/relative).is_dir():
    from importlib.machinery import ModuleSpec
    s=ModuleSpec(fullname,loader=None,is_package=True);s.submodule_search_locations=[str(base/relative)];return s
sys.meta_path.insert(0,CandidateOnly());sys.path[:0]=[str(API/'upstreams'),str(API)]
from infrastructure.research_lane_source import ResearchLaneSource
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
plan=json.loads((B/'SINGLE_PUBLISH_PLAN.json').read_text());original=Path.read_text
staged={Path(step['target']):Path(step['candidate']['path']).read_text() for key,step in plan.items() if key in {'index','event'}}
def read(path,*args,**kwargs):return staged[path] if path in staged else original(path,*args,**kwargs)
with tempfile.TemporaryDirectory(prefix='v4-single-staged-reader-') as tmp:
 reader=ResearchLaneSource(Path(tmp),a_share_daily_root=PRODUCT,original_chart_artifact_root=ARTIFACT)
 with patch.object(Path,'read_text',read):
  product=reader.read_a_daily_product('20261029');detail=reader.read_a_daily_product('20261029','002003.SZ');event=reader.read_a_daily_latest_event();chart=reader.read_original_chart('20261029','002003.SZ')
  assert product['unique_count']==247 and product['processed_count']==5808
  assert detail['status']=='READY' and detail['row']['historical_coverage']['known_full_history'] and detail['row']['historical_coverage']['evaluated_count']==5266
  assert event['manifest']==plan['numeric_manifest']==chart['product_manifest'] and chart['status']=='READY'
  assert chart['chart_numeric_origin_manifest']==plan['previous_manifest']
  assert chart['assets']['png']['sha256']==plan['existing_png_sha256']
  for key in ['html','png','projection']:
   asset=reader.read_original_chart('20261029','002003.SZ',asset=key,asset_sha256=chart['assets'][key]['sha256'])
   assert hashlib.sha256(asset['_asset_bytes']).hexdigest()==chart['assets'][key]['sha256']
receipt={'status':'PASS_STAGED_SINGLE_OWNER_PRODUCT_READ','plan_sha256':sha(B/'SINGLE_PUBLISH_PLAN.json'),'coverage':5266,'candidates':247,'processed_count':5808,'detail':'READY','chart':'READY','same_existing_3asset_sha':'PASS','event_current_manifest':'PASS','old_numeric_origin_strictly_bound':True,'actual_current_index_written':False,'financial_recalculation':False,'prior_real_lineage_review_required_for_publication':True}
(B/'SINGLE_STAGED_READ_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
