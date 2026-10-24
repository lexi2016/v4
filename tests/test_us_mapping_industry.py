"""Current industry listing decision, independent of the retained strict selector."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from test_us_hk_selection_closure import fixture_batch, history
from test_us_hk_compact import saved_result, client_for
from v4.manager_workbench.engines.us_mapping import run_us_mapping


def catalog(batch, code='00001', us='AMD', kind='BUSINESS_PEER', relation_id='IND1', **source_fields):
    source = dict(关系编号=relation_id, code=code, asset_code=us, type=kind,
        segment='Semiconductors', 研究行业='Semiconductor manufacturing', fact='Saved catalog peer business evidence')
    source.update(source_fields)
    relation = dict(relation_id=relation_id, hk_code=code, source_record=source,
        research_use='PENDING_REVIEW', recovery_v2r1=dict(closure_status='CLOSED_RESEARCH_SCOPE',
            current_applicability_state='DATED_SCOPE_ONLY'))
    batch['records'].append(dict(record_role='CATALOG_OBSERVATION', source_status='CATALOG_OBSERVATION',
        us_symbol=us, source_session='20261022', owner='saved_catalog', source_sha256='a'*64,
        available_at='2026-10-22T16:00:00+08:00', relations=[dict(target_symbol='HK.'+code,
            target_name='Industry peer '+code, relation_type='CATALOG_OBSERVATION_ONLY',
            status='CANNOT_CONFIRM', catalog_relation_id=relation_id, catalog_relation=relation)]))


def test_industry_default_keeps_strict_reject_pending_and_zero_return_without_company_proof(tmp_path):
    c,b=fixture_batch(tmp_path,codes=('HK.00001','HK.00002','HK.00003'),returns='0.5')
    history(b)['rows'][0]['readiness']={}
    catalog(b);catalog(b,us='NVDA',relation_id='IND2');catalog(b,code='00002',us='AMD',relation_id='IND3')
    # Arbitrary company cooperation does not prove the target is in the same industry.
    catalog(b,code='00003',kind='SUPPLY_CHAIN',relation_id='SUPPLY')
    result=run_us_mapping(c,b);selection=result['selection']
    assert selection['listing_mode']=='TRIGGERED_FOCUS'
    assert selection['counts']['industry_match_count']==2
    assert selection['counts']['selected']==0 and selection['counts']['rejected']==3
    by_symbol={x['symbol']:x for x in selection['candidates']}
    assert {x['us_symbol'] for x in by_symbol['HK.00001']['industry_matches']}=={'AMD','NVDA'}
    assert by_symbol['HK.00003']['industry_matches']==[]
    snapshot=saved_result(c,result);client=client_for(snapshot)
    route='/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING'
    for suffix in ['', '?view=compact']:
        response=client.get(route+suffix);assert response.status_code==200
        data=response.json()['data']
        assert data['listing_mode']=='TRIGGERED_FOCUS' and data['pagination']['total']==0
        assert data['focus_counts']['selected']==0 and data['stocks']==[]
        assert data['counts']['industry_match_count']==2
        assert all(m['industry'] and m['source_refs'] and m['warnings']
            for s in data['stocks'] for m in s['industry_matches'])
    catalogue=client.get(route+'?projection=catalogue').json()['data']
    assert catalogue['pagination']['total']==2 and {s['symbol'] for s in catalogue['stocks']}=={'HK.00001','HK.00002'}
    assert catalogue['projection']=='catalogue' and '非推荐' in catalogue['projection_label']
    diagnostic=client.get(route+'?view=diagnostics&symbol=HK.00003').json()['data']['stocks'][0]
    assert diagnostic['strict']['decision']=='REJECTED' and diagnostic['candidate']['industry_matches']==[]


def test_industry_identity_missing_industry_and_arbitrary_relationship_do_not_admit(tmp_path):
    c,b=fixture_batch(tmp_path,codes=('HK.00001','HK.00002','HK.00003','HK.00004'))
    catalog(b,code='00001',kind='SAME_ISSUER')
    catalog(b,code='00002',relation_id='BAD_ID',code_mismatch='unused')
    b['records'][-1]['relations'][0]['catalog_relation']['source_record']['code']='99999'
    catalog(b,code='00003',relation_id='NO_INDUSTRY',segment='',研究行业='')
    catalog(b,code='00004',kind='OWNERSHIP',relation_id='OWNER')
    result=run_us_mapping(c,b)
    assert result['selection']['counts']['industry_match_count']==1
    assert [c['symbol'] for c in result['selection']['candidates'] if c['industry_matches']]==['HK.00001']


def test_missing_company_eligibility_and_technical_proofs_are_reference_only(tmp_path):
    c,b=fixture_batch(tmp_path)
    for source in b['records']:
        source['relations']=[]
    history(b)['rows']=[]
    catalog(b)
    result=run_us_mapping(c,b)
    assert result['selection']['counts']['pending']==1
    data=client_for(saved_result(c,result)).get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING').json()['data']
    assert data['stocks']==[] and data['focus_counts']['selected']==0
    catalogue=client_for(saved_result(c,result)).get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING?projection=catalogue').json()['data']
    assert catalogue['stocks'][0]['strict_state']=='PENDING'
    assert catalogue['stocks'][0]['industry_matches'][0]['return_pct'] is None
    assert data['counts']['industry_match_count']==1


def test_previous_selection_shape_roundtrips_without_adding_industry_fields(tmp_path):
    from v4.manager_workbench.contracts import PlanSnapshot
    c,b=fixture_batch(tmp_path);result=run_us_mapping(c,b)
    for k in ['listing_mode','listing_policy_version','listing_policy_sha256']:
        result['selection'].pop(k)
    result['selection']['counts'].pop('industry_match_count')
    result['selection'].pop('focus')
    for candidate in result['selection']['candidates']:
        candidate.pop('industry_matches')
        for path in candidate['paths']:
            path.pop('quote_verified',None);path.pop('quote_available_at',None);path.pop('focus_theme',None)
    saved=saved_result(c,result);original=saved.model_dump(mode='json')
    assert PlanSnapshot.model_validate_json(json.dumps(original)).model_dump(mode='json')==original
    assert 'listing_mode' not in original['lanes'][0]['selection']
    assert 'industry_matches' not in original['lanes'][0]['selection']['candidates'][0]


def test_real_saved_22_input_industry_contract_and_full_bounded_pagination():
    root=Path(__file__).resolve().parents[1]
    meta=json.loads((root/'docs/handoffs/us_hk_selection_closure_20261023/BACKEND_REAL_CANARY.json').read_text())
    path=Path(meta['input_snapshot_path']);raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==meta['input_file_sha256']
    saved=json.loads(raw);batch=next(b for b in saved['batches'] if b['lane']=='US_MAPPING')
    original=deepcopy(batch);result=run_us_mapping(saved['context'],batch)
    selection=result['selection']
    assert selection['listing_mode']=='TRIGGERED_FOCUS'
    assert {k:selection['counts'][k] for k in ['candidate_count','selected','rejected','pending']}==dict(candidate_count=670,selected=0,rejected=397,pending=273)
    matched=[c for c in selection['candidates'] if c['industry_matches']]
    assert len(matched)==selection['counts']['industry_match_count']>200
    assert len({c['symbol'] for c in matched})==len(matched)
    for c in matched:
        assert all(m['industry'] and m['us_symbol'] and m['source_refs'] for m in c['industry_matches'])
    snapshot=saved_result(saved['context'],result);client=client_for(snapshot)
    route='/api/v4/manager-workbench/days/20261022/recommendations/US_MAPPING'
    seen=[];wire_bytes=[]
    for offset in range(0,len(matched),200):
        response=client.get(route,params=dict(view='compact',projection='catalogue',offset=offset,limit=200))
        assert response.status_code==200
        data=response.json()['data'];assert data['pagination']['total']==len(matched)
        assert len(data['stocks'])<=200 and len(response.content)<=1024*1024
        wire_bytes.append(len(response.content))
        seen.extend(s['symbol'] for s in data['stocks'])
    assert seen==[c['symbol'] for c in matched]
    assert batch==original and path.read_bytes()==raw
    from collections import Counter
    print('REAL_22_INDUSTRY_CANARY '+json.dumps(dict(input_sha256=meta['input_file_sha256'],
        counts=selection['counts'],listing_policy_version=selection['listing_policy_version'],
        listing_policy_sha256=selection['listing_policy_sha256'],engine_identity=selection['engine_identity'],
        match_associations=dict(Counter(m['association'] for c in matched for m in c['industry_matches'])),
        individual_stock_count=sum(any(m['role']=='INDIVIDUAL' for m in c['industry_matches']) for c in matched),
        context_only_stock_count=sum(all(m['role']=='SECTOR_CONTEXT' for m in c['industry_matches']) for c in matched),
        unique_stock_count=len(matched),compact_page_wire_bytes=wire_bytes,source_unchanged=True),sort_keys=True))


def focused(result, symbol='HK.00001'):
    focus=result['selection'].get('focus')
    assert focus is not None, 'New runs must persist the triggered focus rather than expose the full catalogue as recommendations'
    return next(d for d in focus['decisions'] if d['symbol']==symbol)


def test_focus_persists_trigger_and_leaves_strict_missing_material_as_reference(tmp_path):
    c,b=fixture_batch(tmp_path,returns='1')
    history(b)['rows'][0]['readiness']={}
    result=run_us_mapping(c,b);focus=focused(result)
    assert focus['decision']=='SELECTED' and focus['eligible'] and focus['primary_us_symbol']=='NVDA'
    assert focus['primary_return_pct']=='1' and focus['hk_mean_turnover20_hkd'] is None
    assert result['selection']['strict_decisions'][0]['decision']=='PENDING'
    assert result['selection']['focus']['counts']['selected']==1


def test_focus_secondary_gain_cannot_replace_fixed_primary(tmp_path):
    from test_us_hk_selection_closure import source
    c,b=fixture_batch(tmp_path,returns='5');amd=source(b,'AMD');amd['relations']=deepcopy(source(b)['relations'])
    amd['quote'].update(last='100.5',change_pct='0.5')
    result=run_us_mapping(c,b);focus=focused(result)
    assert focus['primary_us_symbol']=='AMD' and focus['decision']=='NOT_TRIGGERED'
    assert focus['primary_return_pct']=='0.5'


def test_focus_caps_persist_each_fate_and_stable_order(tmp_path):
    from test_us_hk_selection_closure import source
    codes=tuple(f'HK.{i:05d}' for i in range(1,17));c,b=fixture_batch(tmp_path,codes=codes)
    for i,relation in enumerate(source(b)['relations']):relation['primary_theme']=f'THEME{i//4}'
    result=run_us_mapping(c,b);f=result['selection'].get('focus');assert f is not None
    assert f['counts']['eligible']==16 and f['counts']['selected']==10 and f['counts']['capped']==6
    assert sum(f['counts'][k] for k in ['selected','capped','not_triggered','pending'])==16
    chosen=[d for d in f['decisions'] if d['decision']=='SELECTED']
    from collections import Counter
    assert max(Counter(d['primary_theme'] for d in chosen).values())<=3
    source(b)['relations'].reverse();again=run_us_mapping(c,b)
    assert again['selection']['focus']==f


def test_focus_etf_background_alone_never_triggers(tmp_path):
    from test_us_hk_selection_closure import source
    c,b=fixture_batch(tmp_path,returns='5');source(b,'SOXX')['relations']=deepcopy(source(b)['relations']);source(b)['relations']=[]
    f=focused(run_us_mapping(c,b));assert f['decision']=='NOT_TRIGGERED' and not f['eligible']
    assert 'ETF_ONLY_BACKGROUND' in f['reasons']


def test_focus_quote_identity_session_and_future_fail_closed(tmp_path):
    from test_us_hk_selection_closure import source
    for fault in ['symbol','session','future','nan','infinite','unknown']:
        c,b=fixture_batch(tmp_path);q=source(b)
        if fault=='symbol':q['quote']['symbol']='AMD'
        elif fault=='session':q['quote']['session_date']='20261021'
        elif fault=='future':q['available_at']='2026-10-24T06:00:00+08:00'
        elif fault=='nan':q['quote']['change_pct']='NaN'
        elif fault=='infinite':q['quote']['last']='Infinity'
        else:q['quote']=None
        f=focused(run_us_mapping(c,b));assert f['decision']=='PENDING' and not f['eligible'],fault


def test_focus_return_threshold_exact_and_no_force_fill(tmp_path):
    for value,expected in [('1','SELECTED'),('0.999','NOT_TRIGGERED'),('0','NOT_TRIGGERED'),('-2','NOT_TRIGGERED')]:
        c,b=fixture_batch(tmp_path,returns=value);f=focused(run_us_mapping(c,b))
        assert f['decision']==expected


def peer_quote_scope(batch):
    from v4.manager_workbench.engines.us_mapping_consumption import MANUAL_QUOTE_SCOPE_SHA256,SCHEDULED_QUOTE_OWNER
    from test_us_hk_selection_closure import source
    payload=batch['records'][0]['us_factor_payload']
    payload['manual_quote_scope']=dict(scope_sha256=MANUAL_QUOTE_SCOPE_SHA256,owner=SCHEDULED_QUOTE_OWNER,
        state='READY',us_session_date='20261022',available_at='2026-10-23T05:00:00+08:00',
        payload_sha256='a'*64,receipt_sha256='b'*64,manifest_sha256='c'*64,
        quotes={us:dict(source(batch,us)['quote'],session_time='16:15:00') for us in ['AMD','NVDA']})


def test_focus_valid_peer_not_blocked_by_strict_company_or_price_material(tmp_path):
    c,b=fixture_batch(tmp_path)
    for row in b['records']:row['relations']=[]
    catalog(b);peer_quote_scope(b);history(b)['rows']=[]
    result=run_us_mapping(c,b);f=focused(result)
    assert f['decision']=='SELECTED' and f['primary_us_symbol']=='AMD'
    assert result['selection']['strict_decisions'][0]['decision']=='PENDING'
    client=client_for(saved_result(c,result));route='/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING'
    data=client.get(route).json()['data']
    assert data['projection']=='focus' and data['pagination']['total']==1
    assert data['stocks'][0]['focus_decision']==f and data['stocks'][0]['strict_decision']=='PENDING'
    assert data['stocks'][0]['primary_return_pct']=='1.5'


def test_focus_api_paginates_persisted_selected_and_catalogue_separately(tmp_path):
    codes=tuple(f'HK.{i:05d}' for i in range(1,6));c,b=fixture_batch(tmp_path,codes=codes)
    for i in range(1,6):catalog(b,code=f'{i:05d}',relation_id=f'IND{i}')
    r=run_us_mapping(c,b);s=saved_result(c,r);client=client_for(s);route='/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING'
    focus=r['selection']['focus'];chosen=[d['symbol'] for d in sorted(focus['decisions'],key=lambda d:d['rank']) if d['decision']=='SELECTED']
    page=client.get(route,params=dict(limit=2,offset=1)).json()['data']
    assert page['pagination']['total']==3 and [x['symbol'] for x in page['stocks']]==chosen[1:3]
    catalogue=client.get(route,params=dict(projection='catalogue')).json()['data']
    assert catalogue['pagination']['total']==5 and catalogue['focus_counts']['capped']==2
    last=focus['decisions'][-1]['symbol'];diag=client.get(route,params=dict(view='diagnostics',symbol=last)).json()['data']
    assert diag['stocks'][0]['focus_decision']==focus['decisions'][-1]
    assert client.get(route,params=dict(projection='all')).status_code==422


def test_focus_liquidity_tie_break_requires_proven_units_and_window(tmp_path):
    c,b=fixture_batch(tmp_path,codes=('HK.00001','HK.00002'))
    for bar in history(b)['rows'][1]['bars']:bar['amount']=50_000_000
    r=run_us_mapping(c,b);assert focused(r,'HK.00002')['rank']==1
    history(b)['rows'][1]['readiness']['field_readiness']['amount']='PENDING'
    r=run_us_mapping(c,b)
    assert focused(r,'HK.00001')['rank']==1 and focused(r,'HK.00002')['rank']==2
    assert focused(r,'HK.00002')['hk_mean_turnover20_hkd'] is None
    assert focused(r,'HK.00002')['decision']=='SELECTED'


def test_old_broad_selection_roundtrip_has_no_new_optional_fields(tmp_path):
    from v4.manager_workbench.contracts import PlanSnapshot
    c,b=fixture_batch(tmp_path);r=run_us_mapping(c,b);r['selection'].pop('focus');r['selection']['listing_mode']='INDUSTRY_MATCH'
    for item in r['selection']['candidates']:
        for path in item['paths']:
            path.pop('quote_verified',None);path.pop('quote_available_at',None);path.pop('focus_theme',None)
    snap=saved_result(c,r);body=snap.model_dump(mode='json');again=PlanSnapshot.model_validate_json(json.dumps(body))
    assert again.model_dump(mode='json')==body and again.product_sha256==snap.product_sha256
    data=client_for(again).get('/api/v4/manager-workbench/days/20261023/recommendations/US_MAPPING').json()['data']
    assert data['projection']=='catalogue' and data['focus_counts'] is None and '非推荐' in data['projection_label']


def test_persisted_focus_counts_and_cap_corruption_are_rejected(tmp_path):
    import pytest
    from v4.manager_workbench.contracts import MappingSelectionSummary
    c,b=fixture_batch(tmp_path);selection=run_us_mapping(c,b)['selection'];selection['focus']['counts']['selected']=578
    with pytest.raises(ValueError,match='FOCUS_COUNTS_MISMATCH'):MappingSelectionSummary.model_validate(selection)


def test_focus_uses_saved_primary_catalog_theme_without_changing_strict_theme(tmp_path):
    c,b=fixture_batch(tmp_path)
    for row in b['records']:row['relations']=[]
    catalog(b,us='DHI',研究行业='Homebuilding',segment='Residential construction')
    peer_quote_scope(b)
    scope=b['records'][0]['us_factor_payload']['manual_quote_scope']
    scope['quotes']['DHI']=dict(symbol='DHI',session_date='20261022',last='105',previous_close='100',change_pct='5',session_time='16:15:00')
    r=run_us_mapping(c,b);f=focused(r)
    primary=next(p for p in r['selection']['candidates'][0]['paths'] if p['path_id']==f['primary_path_id'])
    assert f['decision']=='SELECTED' and f['primary_theme']=='Homebuilding'
    assert primary['primary_theme'] is None and primary['focus_theme']=='Homebuilding'
    assert r['selection']['strict_decisions'][0]['primary_theme'] is None
    original_id=f['primary_path_id']
    scope['quotes']['DHI'].update(last='100.5',change_pct='0.5')
    again=focused(run_us_mapping(c,b))
    assert again['primary_path_id']==original_id and again['primary_theme']=='Homebuilding'
    assert again['decision']=='NOT_TRIGGERED'


def test_focus_known_negative_and_invalid_hk_identity_never_select(tmp_path):
    from test_us_hk_selection_closure import source
    c,b=fixture_batch(tmp_path,returns='5')
    source(b)['relations'][0]['direction']='NEGATIVE'
    f=focused(run_us_mapping(c,b))
    assert f['decision']=='NOT_TRIGGERED' and 'PRIMARY_RELATION_EXCLUDED_OR_NEGATIVE' in f['reasons']
    c,b=fixture_batch(tmp_path,returns='5')
    source(b)['relations'][0]['target_symbol']='HK.00000'
    b['records'][0]['us_factor_payload']['strict_selection_payload']['monthly_membership']['codes']=['HK.00000']
    f=focused(run_us_mapping(c,b),'HK.00000')
    assert f['decision']=='PENDING' and f['reasons'][0]=='HK_CODE_IDENTITY_INVALID'
