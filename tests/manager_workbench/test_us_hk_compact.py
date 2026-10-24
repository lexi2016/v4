from copy import deepcopy
from types import SimpleNamespace as NS
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from v4.manager_workbench.api import create_router
from v4.manager_workbench.contracts import PlanSnapshot, LaneResult, seal_snapshot
from v4.manager_workbench.engines.core import merge_decisions
from v4.manager_workbench.engines.us_mapping import run_us_mapping
from v4.manager_workbench.service import count_rows
from test_us_hk_selection_closure import fixture_batch, history, source


def saved_result(context,result):
    stocks=merge_decisions(context,[result])
    return seal_snapshot(dict(context=context,run_id=context['scope_refs']['run_id'],input_sha256='a'*64,
        generated_at=context['cutoff'],available_at=context['cutoff'],lanes=[result],stocks=stocks,
        counts=count_rows([__import__('v4.manager_workbench.contracts',fromlist=['StockDecision']).StockDecision.model_validate(s) for s in stocks]).model_dump(mode='json')))


def client_for(snapshot):
    store=NS(get_plan=lambda *a,**k:snapshot,list_plans=lambda *a,**k:[snapshot])
    service=NS(store=store,config=NS(shared_root=None))
    app=FastAPI();app.include_router(create_router(service));return TestClient(app)


def test_compact_200_rows_under_one_mib_with_full_counts_and_no_raw_factor_groups(tmp_path):
    codes=tuple(f'HK.{i:05d}' for i in range(1,201));c,b=fixture_batch(tmp_path,codes=codes)
    result=run_us_mapping(c,b);result['rows'][0]['us_factor_summary']={'groups':{'raw':'x'*(3*1024*1024)}}
    snapshot=saved_result(c,result);client=client_for(snapshot)
    response=client.get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING',params=dict(run_id=snapshot.run_id,view='compact',limit=200))
    assert response.status_code==200;data=response.json()['data']
    assert len(response.content)<=1024*1024
    assert len(data['stocks'])==200 and data['counts']['candidate_count']==200 and data['counts']['selected']==3
    assert 'us_factor_summary' not in response.text and 'groups' not in response.text and 'hk_history' not in response.text
    assert data['lane_sources']['source_cutoff']==c['cutoff']
    page=client.get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING',params=dict(view='compact',offset=190)).json()['data']
    assert len(page['stocks'])==10 and page['counts']==data['counts'] and page['pagination']['total']==200
    assert data['stocks'][0]['symbol']==result['selection']['candidates'][0]['symbol']


def test_diagnostics_paginate_same_saved_relationships_and_all_gate_causes(tmp_path):
    c,b=fixture_batch(tmp_path);source(b,'AMD')['relations']=deepcopy(source(b)['relations']);history(b)['rows'][0]['readiness']={}
    result=run_us_mapping(c,b);snapshot=saved_result(c,result);client=client_for(snapshot)
    data=client.get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING',params=dict(view='diagnostics',symbol='HK.00001',relationship_limit=1,relationship_offset=1)).json()['data']
    stock=data['stocks'][0]
    assert stock['relationship_pagination']==dict(total=2,offset=1,limit=1)
    assert len(stock['relationships'])==1 and stock['strict']['decision']=='PENDING'
    assert stock['strict']['reasons']==result['selection']['strict_decisions'][0]['reasons']
    assert data['snapshot']['run_id']==snapshot.run_id


def test_new_default_projects_same_canonical_counts_without_path_votes(tmp_path):
    c,b=fixture_batch(tmp_path);history(b)['rows'][0]['readiness']={};snapshot=saved_result(c,run_us_mapping(c,b));client=client_for(snapshot)
    old=client.get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING').json()['data']
    compact=client.get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING?view=compact').json()['data']
    assert old['counts']['selected']==compact['counts']['selected']==0
    assert old['counts']['unassessed']==compact['counts']['pending']==1
    assert old['stocks']==[]  # old positive-only default remains positive-only


def test_legacy_absent_selection_preserves_hash_default_and_original_path_votes(tmp_path):
    c,b=fixture_batch(tmp_path);result=run_us_mapping(c,b);result.pop('selection')
    result['rows']=[r for r in result['rows'] if r.get('source_diagnostic')]
    snapshot=saved_result(c,result);encoded=snapshot.model_dump(mode='json')
    assert 'selection' not in encoded['lanes'][0]
    assert PlanSnapshot.model_validate(json.loads(json.dumps(encoded))).product_sha256==snapshot.product_sha256
    assert merge_decisions(c,[result])[0]['decision']=='CONDITIONAL_WATCH'
    client=client_for(snapshot);old=client.get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING').json()['data']
    compact=client.get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING?view=compact').json()['data']
    assert compact['legacy'] is True and compact['selection_identity'] is None
    assert old['counts']==compact['counts']
    assert old['stocks'][0]['symbol']==compact['stocks'][0]['symbol']


def test_api_pagination_constraints_and_diagnostics_symbol_validation(tmp_path):
    c,b=fixture_batch(tmp_path);client=client_for(saved_result(c,run_us_mapping(c,b)))
    for params in [dict(view='compact',limit=201),dict(view='compact',offset=-1),dict(view='diagnostics',relationship_limit=201),dict(view='diagnostics',symbol='US.NVDA'),dict(view='raw')]:
        assert client.get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING',params=params).status_code==422


def test_real_legacy_compact_preserves_five_benefits_and_addressable_detail():
    from pathlib import Path
    import hashlib
    path=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/snapshots/173530a9ac4b4105b41094337907b801.json')
    raw=path.read_bytes();snapshot=PlanSnapshot.model_validate_json(raw);client=client_for(snapshot)
    response=client.get('/api/v4/manager-workbench/days/20261022/recommendations/US_MAPPING',params=dict(run_id=snapshot.run_id,view='compact',limit=200))
    assert response.status_code==200 and len(response.content)<=1024*1024
    data=response.json()['data'];summary=data['us_mapping_summary']['factor_summary']['single_day_mapping']
    assert data['legacy'] is True and data['selection_identity'] is None
    assert summary['counts']['BENEFIT']==5
    assert {r['symbol'] for r in summary['rows'] if r['decision']=='BENEFIT'}=={'HK.00992','HK.01211','HK.01810','HK.02015','HK.09868'}
    stock=summary['rows'][0]
    detail=client.get('/api/v4/manager-workbench/stocks/'+stock['symbol'],params=dict(date='20261022',run_id=snapshot.run_id,lane=stock['recommendation_lane'],row_id=stock['row_id']))
    assert detail.status_code==200
    assert detail.json()['data']['plan_run_id']==snapshot.run_id
    assert detail.json()['data']['stock']['symbol']==stock['symbol']
    assert path.read_bytes()==raw


@__import__('pytest').mark.parametrize('fault',['missing','duplicate'])
def test_repair_r1_source_coverage_gap_keeps_rejected_zero_incomplete_in_api(tmp_path,fault):
    c,b=fixture_batch(tmp_path,returns='0.5')
    if fault=='missing':b['records']=[r for r in b['records'] if r['us_symbol']!='WDC']
    else:b['records'].append(deepcopy(source(b,'AMD')))
    result=run_us_mapping(c,b);gate=next(g for g in result['selection']['strict_decisions'][0]['gates'] if g['gate']=='source_contract')
    assert gate['state']=='PENDING' and 'US_SOURCE_33_COVERAGE_INCOMPLETE' in gate['reasons']
    data=client_for(saved_result(c,result)).get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING?view=compact').json()['data']
    assert data['counts']['selected']==0 and data['counts']['rejected']==1
    assert data['evaluation_complete'] is False and 'US_SOURCE_33_COVERAGE_INCOMPLETE' in data['selection_gaps']
    from v4.manager_workbench.service import project_preopen_lane
    projected=project_preopen_lane(LaneResult.model_validate(result),cutoff='2026-10-23T07:00:00+08:00')
    assert projected.selection.evaluation_complete is False
    assert 'US_SOURCE_33_COVERAGE_INCOMPLETE' in projected.selection.gaps


def test_repair_r1_preopen_omitted_compact_and_embedded_strict_use_same_judgment(tmp_path):
    from v4.manager_workbench.service import project_preopen_lane
    c,b=fixture_batch(tmp_path);original=LaneResult.model_validate(run_us_mapping(c,b));before=original.model_dump(mode='json')
    projected=project_preopen_lane(original,cutoff='2026-10-23T04:00:00+08:00');c['phase']='PREOPEN';c['cutoff']='2026-10-23T04:00:00+08:00'
    saved=saved_result(c,projected.model_dump(mode='json'));client=client_for(saved);route='/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING'
    default=client.get(route).json()['data'];compact=client.get(route+'?view=compact').json()['data']
    factor=default['us_mapping_summary']['factor_summary']
    assert compact['counts']['selected']==factor['strict_selection']['counts']['selected']==factor['single_day_mapping']['selected_count']==0
    assert compact['counts']['pending']==factor['strict_selection']['counts']['pending']==1
    assert factor['single_day_mapping']['rows'][0]['strict_decision']=='PENDING'
    assert factor['single_day_mapping']['strict_selection']==factor['strict_selection']
    assert original.model_dump(mode='json')==before and original.selection.counts['selected']==1


@__import__('pytest').mark.parametrize('returns',['0.5','1.5'])
@__import__('pytest').mark.parametrize('matched',[False,True])
def test_repair_r2_overlay_consumption_completeness_in_actual_compact_and_preopen(tmp_path,returns,matched):
    from v4.manager_workbench.service import project_preopen_lane
    c,b=fixture_batch(tmp_path,returns=returns)
    c['scope_refs']['US_MAPPING']['full_overlay_summary']=dict(state='READY',stock_count=1,relation_count=1)
    if matched:
        # A consumed, explicitly excluded catalog path remains diagnostic and
        # cannot veto the valid neighboring direct company's strict decision.
        catalog=dict(relation_id='R2',hk_code='00001',research_use='EXCLUDED_CURRENT',
            source_record={'关系编号':'R2','code':'00001','type':'INDUSTRY_PROXY','asset_code':'SOXX','fact':'Excluded dated context'},
            recovery_v2r1=dict(closure_status='CLOSED_RESEARCH_SCOPE',current_applicability_state='EXCLUDED_CURRENT'))
        relation=dict(target_symbol='HK.00001',relation_type='CATALOG_OBSERVATION_ONLY',status='CANNOT_CONFIRM',catalog_relation_id='R2',catalog_relation=catalog)
        b['records'].append(dict(record_role='CATALOG_OBSERVATION',source_status='CATALOG_OBSERVATION',us_symbol='SOXX',relations=[relation]))
    result=run_us_mapping(c,b);selection=result['selection'];gate=next(g for g in selection['strict_decisions'][0]['gates'] if g['gate']=='source_contract')
    gap='US_MAPPING_OVERLAY_CONSUMER_COUNT_MISMATCH'
    assert gate['state']==('PASS' if matched else 'PENDING')
    assert (gap in gate['reasons']) is (not matched)
    lane=LaneResult.model_validate(result);before=lane.model_dump(mode='json')
    projected=project_preopen_lane(lane,cutoff='2026-10-23T07:00:00+08:00')
    for value in [result,projected.model_dump(mode='json')]:
        data=client_for(saved_result(c,value)).get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING?view=compact').json()['data']
        assert data['evaluation_complete'] is matched
        assert (gap in data['selection_gaps']) is (not matched)
        assert data['counts']['candidate_count']==1
        assert data['counts']['selected']==int(matched and returns=='1.5')
        assert data['counts']['rejected']==int(returns=='0.5')
        assert data['counts']['pending']==int(not matched and returns=='1.5')
    assert lane.model_dump(mode='json')==before
    if matched:assert len(selection['candidates'][0]['paths'])==2
