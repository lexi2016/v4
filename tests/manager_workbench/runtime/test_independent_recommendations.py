"""Read only the saved production snapshot: all counts and decisions remain original."""
import hashlib,json,copy
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from v4.manager_workbench.api import create_router
from v4.manager_workbench.contracts import PlanSnapshot
from v4.manager_workbench.display_read import lane_projection
OLD=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/snapshots/528ef6fd4f0b49e7a3ec2b6719fc9afe.json')

@pytest.fixture
def saved():
 if not OLD.exists():pytest.skip('Actual saved run is local-only; raw data is not uploaded')
 raw=OLD.read_bytes();snap=PlanSnapshot.model_validate(json.loads(raw));before=hashlib.sha256(raw).hexdigest()
 store=NS(get_plan=lambda *a,**k:snap,list_plans=lambda *a:[snap]);svc=NS(store=store,config=NS(shared_root=None));app=FastAPI();app.include_router(create_router(svc))
 yield snap,TestClient(app)
 assert hashlib.sha256(OLD.read_bytes()).hexdigest()==before


def get(client,lane,**params):
 return client.get('/api/v4/manager-workbench/days/20261013/recommendations/'+lane,params={'run_id':'528ef6fd4f0b49e7a3ec2b6719fc9afe',**params})


def test_two_real_independent_lists_and_full_server_counts(saved):
 snap,c=saved;us=get(c,'US_MAPPING').json()['data'];over=get(c,'OVERSOLD',limit=200).json()['data']
 assert (us['counts']['selected'],us['counts']['watch'])==(0,1)
 assert (over['counts']['selected'],over['counts']['watch'])==(20,277)
 assert us['pagination']['total']==1 and len(us['stocks'])==1
 assert us['stocks'][0]['symbol']=='HK.09988' and us['stocks'][0]['us_symbol']=='EQIX'
 assert us['stocks'][0]['decision']=='CONDITIONAL_WATCH' and set(us['stocks'][0]['lane_decisions'])=={'US_MAPPING'}
 assert us['recommendation_projection']['row_count']==37 and us['recommendation_projection']['hk_relation_row_count']==14 and us['recommendation_projection']['distinct_hk_count']==10
 assert us['us_mapping_summary']['source_symbol_count']==33
 assert over['pagination']['total']==297 and len(over['stocks'])==200
 rest=get(c,'OVERSOLD',limit=200,offset=200).json()['data'];assert len(rest['stocks'])==97 and rest['counts']==over['counts']
 assert len({r['row_id'] for r in over['stocks']+rest['stocks']})==297
 assert all(r['decision'] in ('SELECTED','CONDITIONAL_WATCH') for r in over['stocks']+rest['stocks'])
 assert us['recommendation_counts']['OVERSOLD']==over['counts']


def test_lane_filter_never_uses_aggregate_decision_and_detail_has_exact_saved_row(saved):
 snap,c=saved;us=get(c,'US_MAPPING').json()['data']['stocks'][0]
 over=get(c,'OVERSOLD',decision='NOT_SELECTED',q='HK.09988').json()['data']['stocks'][0]
 assert over['decision']=='NOT_SELECTED' and over['metrics']['price_pass'] is False and over['metrics']['volume_pass'] is False
 for lane,row in [('US_MAPPING',us),('OVERSOLD',over)]:
  data=c.get('/api/v4/manager-workbench/stocks/HK.09988',params=dict(date='20261013',run_id=snap.run_id,lane=lane,row_id=row['row_id'])).json()['data']
  assert data['stock']['decision']==row['decision'] and data['recommendation_lane']==lane
  assert [l['lane'] for l in data['lane_details']]==[lane] and len(data['lane_details'][0]['rows'])==1
  original=next(l for l in snap.lanes if l.lane.value==lane).rows[int(row['row_id'].split(':')[1])]
  assert data['lane_details'][0]['rows'][0]['reason']==original['reason']
 bad=c.get('/api/v4/manager-workbench/stocks/HK.09988',params=dict(date='20261013',run_id=snap.run_id,lane='OVERSOLD',row_id=us['row_id']));assert bad.status_code==422
 assert c.get('/api/v4/manager-workbench/stocks/HK.09988',params=dict(date='20261013',run_id=snap.run_id)).json()['data']['stock']['decision']=='CONDITIONAL_WATCH'


def test_unknown_sources_remain_gap_records_not_recommended_stocks(saved):
 snap,c=saved;data=get(c,'US_MAPPING',decision='UNASSESSED').json()['data']
 assert data['counts']['unassessed']==24 and len(data['stocks'])==1 and data['stocks'][0]['symbol']=='HK.06823'
 assert data['recommendation_projection']['source_only_row_count']==23
 assert sum(1 for g in data['us_mapping_summary']['groups'] for r in g['rows'] if not r.get('symbol'))==23
 assert get(c,'ANNOUNCEMENT').status_code==422 and get(c,'OVERSOLD',limit=201).status_code==422


def test_portable_projection_does_not_mutate_or_merge_same_stock_between_lanes():
 rows=[dict(symbol='HK.09988',name='Alibaba',decision='CONDITIONAL_WATCH',reason='US_REVIEWED_RELATION_CONDITIONAL_ONLY',us_symbol='EQIX'),dict(symbol=None,us_symbol='MU',decision='UNASSESSED')]
 other=[dict(symbol='HK.09988',name='Alibaba',decision='NOT_SELECTED',metrics={'price_pass':False})]
 before=copy.deepcopy((rows,other));coverage=NS(model_dump=lambda **k:{'scope_count':33})
 lanes=[NS(lane=NS(value=name),rows=r,state=NS(value='PARTIAL'),coverage=coverage) for name,r in [('US_MAPPING',rows),('OVERSOLD',other)]]
 snap=NS(lanes=lanes,stocks=[]);us=lane_projection(snap,'US_MAPPING',{});over=lane_projection(snap,'OVERSOLD',{},'NOT_SELECTED')
 assert us['stocks'][0]['decision']=='CONDITIONAL_WATCH' and over['stocks'][0]['decision']=='NOT_SELECTED'
 assert (rows,other)==before
