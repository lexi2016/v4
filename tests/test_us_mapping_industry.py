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
    assert selection['listing_mode']=='INDUSTRY_MATCH'
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
        assert data['listing_mode']=='INDUSTRY_MATCH' and data['pagination']['total']==2
        assert {s['symbol'] for s in data['stocks']}=={'HK.00001','HK.00002'}
        assert all(s['strict_state']=='REJECT' for s in data['stocks'])
        assert data['counts']['industry_match_count']==2
        assert all(m['industry'] and m['source_refs'] and m['warnings']
            for s in data['stocks'] for m in s['industry_matches'])
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
    assert data['stocks'][0]['strict_state']=='PENDING'
    assert data['stocks'][0]['industry_matches'][0]['return_pct'] is None
    assert data['counts']['industry_match_count']==1


def test_previous_selection_shape_roundtrips_without_adding_industry_fields(tmp_path):
    from v4.manager_workbench.contracts import PlanSnapshot
    c,b=fixture_batch(tmp_path);result=run_us_mapping(c,b)
    for k in ['listing_mode','listing_policy_version','listing_policy_sha256']:
        result['selection'].pop(k)
    result['selection']['counts'].pop('industry_match_count')
    for candidate in result['selection']['candidates']:
        candidate.pop('industry_matches')
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
    assert selection['listing_mode']=='INDUSTRY_MATCH'
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
        response=client.get(route,params=dict(view='compact',offset=offset,limit=200))
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
