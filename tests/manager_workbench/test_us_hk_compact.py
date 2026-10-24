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
    from v4.manager_workbench.api import _index
    store=NS(get_plan=lambda *a,**k:snapshot,list_plans=lambda *a,**k:[snapshot],
        list_plan_metadata=lambda *a,**k:([_index(snapshot)],[]))
    service=NS(store=store,config=NS(shared_root=None))
    app=FastAPI();app.include_router(create_router(service));return TestClient(app)


def metadata_store(tmp_path):
    from v4.manager_workbench.store import WorkbenchStore
    store=WorkbenchStore(tmp_path)
    def add(run_id, *, phase='RETROSPECTIVE', **patch):
        folder=store.root/'catalog'/'20261022'/phase;folder.mkdir(parents=True,exist_ok=True)
        snapshot=store.root/'snapshots'/(run_id+'.json');snapshot.parent.mkdir(exist_ok=True)
        snapshot.write_bytes(b'contents must not be opened for a version menu')
        value=dict(run_id=run_id,product_sha256='b'*64,input_sha256='a'*64,generated_at='2026-10-24T10:00:00+00:00')
        value.update(patch);(folder/(run_id+'.json')).write_text(json.dumps(value))
        return folder/(run_id+'.json')
    return store,add


def test_version_metadata_reads_only_small_catalog_and_isolates_bad_entries(tmp_path,monkeypatch):
    store,add=metadata_store(tmp_path);add('valid');add('bad_sha',product_sha256='not-a-sha');add('missing')
    (store.root/'snapshots'/'missing.json').unlink()
    bad=add('bad_json');bad.write_text('{')
    wrong=add('wrong_key');value=json.loads(wrong.read_text());value['run_id']='other';wrong.write_text(json.dumps(value))
    add('linked');(store.root/'snapshots'/'linked.json').unlink();(store.root/'snapshots'/'linked.json').symlink_to(store.root/'snapshots'/'valid.json')
    reads=[];original=store._read
    def read(path,**kwargs):
        reads.append((str(path.relative_to(store.root)),kwargs.get('max_bytes')))
        assert path.parent.name!='snapshots'
        return original(path,**kwargs)
    monkeypatch.setattr(store,'_read',read)
    metadata,gaps=store.list_plan_metadata('20261022')
    assert [row['run_id'] for row in metadata]==['valid']
    assert metadata[0]['content_verification']=='CATALOG_METADATA_ONLY' and 'state' not in metadata[0]
    assert len(gaps)==5 and all(g['code']=='VERSION_METADATA_UNAVAILABLE' for g in gaps)
    assert all(limit==16*1024 for _,limit in reads)


def test_compact_route_uses_metadata_not_full_version_hydration(tmp_path,monkeypatch):
    import v4.manager_workbench.api as api_module
    store,add=metadata_store(tmp_path);add('selected');add('other')
    lane=NS(lane=NS(value='US_MAPPING'),selection=None,gaps=[])
    snapshot=NS(run_id='selected',context=NS(target_date='20261022',phase=NS(value='RETROSPECTIVE')),
        generated_at='2026-10-24T10:00:00+00:00',product_sha256='b'*64,input_sha256='a'*64,gaps=[],lanes=[lane])
    monkeypatch.setattr(store,'get_plan',lambda *a,**k:snapshot)
    monkeypatch.setattr(store,'list_plans',lambda *a,**k:(_ for _ in ()).throw(AssertionError('FULL_VERSION_READ_FORBIDDEN')))
    monkeypatch.setattr(api_module,'saved_names',lambda *a:{})
    monkeypatch.setattr(api_module,'selection_view',lambda *a,**k:dict(lane_state='PARTIAL',stocks=[],counts={},pagination=dict(total=0,offset=0,limit=1)))
    app=FastAPI();app.include_router(create_router(NS(store=store,config=NS(shared_root=None))))
    client=TestClient(app)
    for view in ['compact','diagnostics']:
        response=client.get('/api/v4/manager-workbench/days/20261022/recommendations/US_MAPPING',params=dict(run_id='selected',view=view,limit=1))
        assert response.status_code==200
        versions=response.json()['data']['versions']
        assert {v['run_id'] for v in versions}=={'selected','other'}
        assert next(v for v in versions if v['run_id']=='selected')['state']=='READY'
        assert next(v for v in versions if v['run_id']=='other')['content_verification']=='CATALOG_METADATA_ONLY'


def test_metadata_menu_does_not_bypass_selected_snapshot_validation(tmp_path):
    import pytest
    store,add=metadata_store(tmp_path);add('selected')
    metadata,_=store.list_plan_metadata('20261022');assert metadata[0]['run_id']=='selected'
    with pytest.raises(ValueError):store.get_plan('20261022',run_id='selected')


def test_compact_200_rows_under_one_mib_with_full_counts_and_no_raw_factor_groups(tmp_path):
    codes=tuple(f'HK.{i:05d}' for i in range(1,201));c,b=fixture_batch(tmp_path,codes=codes)
    # The new default requires actual industry evidence, independent of the
    # fixture's named technology-customer strict transmission evidence.
    for code in codes:
        relation_id='PEER-'+code
        b['records'].append(dict(record_role='CATALOG_OBSERVATION',source_status='CATALOG_OBSERVATION',
            us_symbol='NVDA',owner='catalog',source_sha256='a'*64,available_at=c['cutoff'],source_session='20261022',
            relations=[dict(target_symbol=code,catalog_relation_id=relation_id,relation_type='CATALOG_OBSERVATION_ONLY',
                catalog_relation=dict(relation_id=relation_id,hk_code=code[3:],
                    source_record=dict(关系编号=relation_id,code=code[3:],asset_code='NVDA',type='BUSINESS_PEER',
                        segment='semiconductors',研究行业='semiconductors',fact='Saved catalog industry peer'),
                    recovery_v2r1=dict(closure_status='CLOSED_RESEARCH_SCOPE',current_applicability_state='DATED_SCOPE_ONLY')))]))
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
    assert old['counts']['pending']==compact['counts']['pending']==1
    assert old['stocks']==[]  # company cooperation alone does not prove same industry
    assert old['listing_mode']=='INDUSTRY_MATCH' and old['counts']['industry_match_count']==0


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
    factor=next(row['us_factor_summary'] for row in projected.rows if 'us_factor_summary' in row)
    assert default['counts']==compact['counts'] and default['listing_mode']=='INDUSTRY_MATCH'
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
