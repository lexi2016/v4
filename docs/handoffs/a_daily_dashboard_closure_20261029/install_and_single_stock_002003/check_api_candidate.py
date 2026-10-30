"""Candidate imports, read-only existing247 GETs and synthetic origin boundaries."""
from pathlib import Path
import copy,hashlib,importlib.abc,importlib.util,json,sys,tempfile
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
B=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/install_and_single_stock_002003');API=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-daily-dashboard-c6-20261030-r2-api/app');DATA=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据');PRODUCT=B.parent.parent/'today_full_r1';ARTIFACT=B.parent.parent
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
    spec=ModuleSpec(fullname,loader=None,is_package=True);spec.submodule_search_locations=[str(base/relative)];return spec
sys.meta_path.insert(0,CandidateOnly());sys.path[:0]=[str(API/'upstreams'),str(API),str(ROOT/'tests')]
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.v4_api.research_router import create_research_router
from apps.api.v4_api.research_lane_router import create_research_lane_router
from infrastructure.research_lane_source import ResearchLaneSource
from apps.api.v4_api import app as candidate_app
from test_original_formula_chart_binding import fixture
ref=lambda p:{'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
result={'status':'RUNNING','app_imported':True,'old247_readonly':{},'synthetic_origin':{},'no_service_or_real_evaluation':True}
with tempfile.TemporaryDirectory(prefix='v4-api-compose-check-') as td:
 temp=Path(td);charts=B.parent/'original_formula_charts_247';binding={'artifact_root':str(ARTIFACT),'manifest':ref(charts/'MANIFEST.json'),'receipt':ref(charts/'COMPLETION_RECEIPT_247.json')}
 app=FastAPI();app.include_router(create_research_router(temp/'consumer',shared_data_root=DATA,a_share_daily_root=PRODUCT,original_chart_artifact_root=ARTIFACT,original_chart_binding=binding));app.include_router(create_research_lane_router(Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data'),a_share_daily_root=PRODUCT))
 client=TestClient(app);data=client.get('/api/v4/research/a-share/daily-product').json();assert data['unique_count']==247 and data['processed_count']==5808
 detail=client.get('/api/v4/research/a-share/daily-product',params={'date':'20261029','symbol':'002003.SZ'}).json();assert detail['status']=='READY'
 chart=client.get('/api/v4/research/a-share/original-chart',params={'date':'20261029','symbol':'002003.SZ'}).json();assert chart['status']=='READY',chart
 for kind,asset in chart['assets'].items():
  response=client.get(asset['url']);assert response.status_code==200 and hashlib.sha256(response.content).hexdigest()==asset['sha256']
 result['old247_readonly']={'rows':247,'processed':5808,'symbol_detail':'READY','existing002003_chart':'READY','three_asset_sha':'PASS','root_separate_from_raw_history':True}
 # Original C3 fixture, now a distinct same-source statistical-row version.
 create,oldbinding,manifest,receipt,projection,paths,rebind=fixture(temp/'origin')
 source_root=(temp/'origin/source').resolve();source=ResearchLaneSource(temp,a_share_daily_root=source_root,original_chart_artifact_root=Path(oldbinding['artifact_root']))
 index_path=source_root/'daily_products/a_share/index.json';index=json.loads(index_path.read_text());origin_manifest=index['dates']['20261029'];old_m=json.loads(Path(origin_manifest['path']).read_text());product=json.loads(Path(old_m['artifact']['path']).read_text());newrow=json.loads(Path(product['row_refs']['600025.SH']['path']).read_text());newrow['statistics']['groups'][0]['eligible_event_count']=2;rp=source_root/'daily_products/a_share/history-new-row.json';rp.write_text(json.dumps(newrow));product['row_refs']['600025.SH']=ref(rp)
 pp=source_root/'daily_products/a_share/history-new-product.json';pp.write_text(json.dumps(product));newm={**old_m,'artifact':ref(pp)};mp=source_root/'daily_products/a_share/history-new-manifest.json';mp.write_text(json.dumps(newm));index['dates']['20261029']=ref(mp);index['original_charts']={'20261029':{'numeric_manifest':ref(mp),'manifest':oldbinding['manifest'],'receipt':oldbinding['receipt'],'chart_origin_manifest':origin_manifest,'history_updated_symbols':['600025.SH']}};index_path.write_text(json.dumps(index))
 answer=source.read_original_chart('20261029','600025.SH');assert answer['status']=='READY' and answer['product_manifest']==ref(mp) and answer['chart_numeric_origin_manifest']==origin_manifest;assert answer['assets']['html']['sha256']==oldbinding.get('unused',manifest['samples']['600025.SH']['html']['sha256'])
 bad=copy.deepcopy(newrow);bad['symbol']='000001.SZ';rp.write_text(json.dumps(bad));product['row_refs']['600025.SH']=ref(rp);pp.write_text(json.dumps(product));newm['artifact']=ref(pp);mp.write_text(json.dumps(newm));index['dates']['20261029']=ref(mp);index['original_charts']['20261029']['numeric_manifest']=ref(mp);index_path.write_text(json.dumps(index))
 try:source.read_original_chart('20261029','600025.SH');raise AssertionError('foreign changed row accepted')
 except ValueError:pass
 result['synthetic_origin']={'same_source_stats_only_old_projection_sha_reuse':'PASS','current_numeric_manifest_in_answer':'PASS','changed_row_symbol_rejected':'PASS'}
result['status']='PASS_API_COMPOSED_IMPORT_READONLY_AND_SYNTHETIC';(B/'API_HEALTH_RECEIPT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
