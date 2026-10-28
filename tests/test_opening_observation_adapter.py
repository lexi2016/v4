"""Synthetic fixtures only; no real market data or network access."""
from datetime import datetime
from pathlib import Path
import hashlib
import json

import pytest


def service(tmp_path, **kwargs):
    from apps.api.v35_api.opening_observation_service import OpeningObservationService
    return OpeningObservationService(raw_root=tmp_path / 'raw', selection_root=tmp_path / 'selection',
        now=lambda: datetime.fromisoformat('2026-10-28T10:00:00+08:00'), **kwargs)


def publish(tmp_path, *, evidence=(), requested=3, missing=('SZ.000003',), extra_rows=()):
    from stage_center.raw_store import RAW_FIELDS, RawStore
    row = {key: None for key in RAW_FIELDS}
    row.update(batch_index=0, code='SZ.000001', name='SYNTHETIC TEST',
        update_time='2026-10-28 09:25:00', last_price=10.2, open_price=10,
        high_price=10.2, low_price=10, prev_close_price=10, turnover=0, volume=0,
        window_start='2026-10-28 09:25:00',window_end='2026-10-28 09:25:00',bar_count=1,
        temporal_cutoff_safe=True)
    other = dict(row, code='SH.600000', last_price=8)
    result = RawStore(tmp_path / 'raw').publish(trade_date='20261028', stage_id='STAGE_0925',
        market='A_SHARE', source_id='SYNTHETIC_FIXTURE', source_status='READY',
        rows=[row, other, *[dict(row,**extra) for extra in extra_rows]], requested_rows=requested, missing_symbols=missing, source_evidence=evidence)
    return result


def fingerprint(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.rglob('*') if p.is_file()}


def rehash(root, *, selection=False, mutate_manifest=None, mutate_csv=None):
    """Correctly rehash a deliberately inconsistent synthetic trio and pointer."""
    from stage_center.raw_store import canonical_sha
    latest_path=root/('selection_latest.json' if selection else 'latest.json')
    latest=json.loads(latest_path.read_text());entry=next(iter(latest['entries'].values()))
    artifact=root/entry['artifact_relative'];run=artifact.parent
    manifest=json.loads((run/'manifest.json').read_text());receipt=json.loads((run/'receipt.json').read_text())
    if mutate_csv:
        artifact.write_bytes(mutate_csv(artifact.read_bytes()))
        manifest['artifact_sha256']=receipt['artifact_sha256']=hashlib.sha256(artifact.read_bytes()).hexdigest()
    if mutate_manifest:
        mutate_manifest(manifest,receipt)
    receipt['manifest_sha256']=canonical_sha(manifest)
    (run/'manifest.json').write_text(json.dumps(manifest));(run/'receipt.json').write_text(json.dumps(receipt))
    entry['manifest_sha256']=canonical_sha(manifest);entry['receipt_sha256']=canonical_sha(receipt)
    entry['artifact_sha256']=manifest['artifact_sha256']
    latest_path.write_text(json.dumps(latest))


def publish_selection(tmp_path,raw_sha,canonical_a=False):
    from stage_center.selection import SelectionStore, select_a_0925_auction
    rows=[{'code':(f'A.{i:06d}' if canonical_a else f'{i:06d}.SZ'),'update_time':'2026-10-28 09:25:00',
        'last_price':10.2,'prev_close_price':10,'amount':10000} for i in range(2,15)]
    envelope=select_a_0925_auction(rows,'20261028',raw_sha,requested_rows=20)
    return SelectionStore(tmp_path/'selection').publish(envelope,market='A_SHARE')


def test_empty_store_returns_honest_stages_without_creating_directories(tmp_path):
    result = service(tmp_path).get(date='2026-10-28', symbol='301655.SZ')
    assert result['status'] == 'UNAVAILABLE'
    assert len(result['stages']) == 3
    assert all(x['rows'] == [] and x['availability'] == 'MISSING' for x in result['stages'])
    assert result['candidate_context']['source_date'] is None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('symbol', ['000001', '公司', 'A.000001', '000001.HK', '../000001.SZ'])
def test_rejects_incomplete_ambiguous_or_wrong_market_identity(tmp_path, symbol):
    with pytest.raises(ValueError):
        service(tmp_path).get(date='2026-10-28', symbol=symbol)


@pytest.mark.parametrize('date,source', [('2026-02-30',None), ('../20261028',None), ('2026-10-28','2026-10-28'), ('2026-10-28','2026-10-29')])
def test_rejects_bad_dates_and_source_not_before_target(tmp_path,date,source):
    with pytest.raises(ValueError):
        service(tmp_path).get(date=date, symbol='000001.SZ', candidate_source_date=source)


def test_reads_real_verified_raw_preserves_zero_and_complete_provenance(tmp_path):
    publish(tmp_path)
    before = fingerprint(tmp_path)
    result = service(tmp_path).get(date='20261028', symbol='SZ.000001', candidate_source_date='20261027')
    assert result['trade_date'] == '2026-10-28' and result['symbol'] == '000001.SZ'
    assert result['candidate_context'] == {'source_date':'2026-10-27','authority':'CLIENT_CONTEXT_ONLY','stage_input_identity_verified':False}
    stage = result['stages'][0]
    assert stage['availability'] == 'AVAILABLE'
    assert len(stage['rows']) == 1
    assert stage['metrics']['volume'] == 0 and stage['metrics']['turnover'] == 0
    assert stage['metrics']['change_pct'] == pytest.approx(2)
    assert stage['raw']['requested_rows'] == 3 and stage['raw']['row_count'] == 2
    assert stage['raw']['missing_symbols'] == ['SZ.000003']
    assert stage['raw']['coverage_scope'] == 'VERIFIED_RAW_INPUT_ONLY'
    assert stage['raw']['manifest_sha256'] and stage['raw']['manifest_file_sha256']
    assert stage['raw']['captured_at'] is None
    assert stage['temporal_state'] == 'UNKNOWN' and stage['observation_mode'] == 'UNCONFIRMED'
    assert stage['metrics']['historical_volume_ratio'] is None
    assert fingerprint(tmp_path) == before


def test_absent_security_is_not_screened_out_or_zero(tmp_path):
    publish(tmp_path)
    stage = service(tmp_path).get(date='20261028',symbol='000002.SZ')['stages'][0]
    assert stage['rows'] == [] and stage['metrics']['price'] is None
    assert 'SYMBOL_NOT_COVERED_BY_RAW' in stage['missing_reasons']
    assert stage['selection'] is None


def test_other_date_never_reuses_latest_and_hk_never_merges_a(tmp_path):
    publish(tmp_path)
    assert service(tmp_path).get(date='20261027',symbol='000001.SZ')['stages'][0]['rows'] == []
    assert service(tmp_path).get(date='20261028',symbol='00001.HK')['stages'][0]['rows'] == []


def test_artifact_tampering_fails_closed(tmp_path):
    publish(tmp_path)
    artifact = next((tmp_path/'raw').rglob('artifact.csv'))
    artifact.write_bytes(artifact.read_bytes().replace(b'10.2',b'99.9'))
    stage = service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['availability'] == 'FAILED' and stage['rows'] == []
    assert 'RAW_VERIFICATION_FAILED' in stage['missing_reasons']


def test_source_backfill_marker_is_not_realtime(tmp_path):
    publish(tmp_path, evidence=('due_status=HISTORICAL_BACKFILL','collected_at=2026-10-28T09:26:00+08:00'))
    stage = service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['temporal_state'] == 'LATE'
    assert stage['observation_mode'] == 'RETROSPECTIVE'
    assert stage['source_status'] in ('READY','PARTIAL_WITH_ROWS')


def test_malicious_latest_path_never_reads_external_file(tmp_path):
    publish(tmp_path)
    latest = tmp_path/'raw'/'latest.json'
    data=json.loads(latest.read_text())
    next(iter(data['entries'].values()))['run_id']='../../outside'
    latest.write_text(json.dumps(data))
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['availability']=='FAILED' and stage['rows']==[]


def test_router_rejects_invalid_queries_and_disables_cache(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.v35_api.opening_observation_router import create_opening_observation_router
    app=FastAPI();app.include_router(create_opening_observation_router(service(tmp_path)))
    with TestClient(app) as client:
        assert client.get('/api/v3/research/opening-observation',params={'date':'20261028','symbol':'000001'}).status_code==422
        r=client.get('/api/v3/research/opening-observation',params={'date':'20261028','symbol':'000001.SZ'})
        assert r.status_code==200 and r.headers['cache-control']=='no-store'
        assert r.json()['write_performed'] is False


def test_future_phase_is_not_read_even_when_fixture_exists(tmp_path):
    publish(tmp_path)
    from apps.api.v35_api.opening_observation_service import OpeningObservationService
    s=OpeningObservationService(raw_root=tmp_path/'raw',selection_root=tmp_path/'selection',
        now=lambda:datetime.fromisoformat('2026-10-28T09:24:00+08:00'))
    result=s.get(date='20261028',symbol='000001.SZ')
    assert all(x['availability']=='NOT_DUE' and x['raw'] is None and x['rows']==[] for x in result['stages'])
    assert result['RESEARCH_ONLY'] is True


def test_latest_quote_is_chosen_by_time_not_csv_order_and_all_rows_retained(tmp_path):
    publish(tmp_path,extra_rows=[{'update_time':'2026-10-28 09:24:00','window_start':'2026-10-28 09:24:00',
        'window_end':'2026-10-28 09:24:00','last_price':9}])
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert len(stage['rows'])==2
    assert stage['metrics']['price']==10.2
    assert stage['metrics']['quote_time']=='2026-10-28 09:25:00'


def test_rehashed_csv_date_attack_is_rejected_beyond_native_verifier(tmp_path):
    from stage_center.raw_store import RawStore
    publish(tmp_path)
    rehash(tmp_path/'raw',mutate_csv=lambda b:b.replace(b'20261028,09:25',b'20261027,09:25'))
    # Native verification strips trade_date from CSV. Adapter adds this identity gate.
    assert RawStore(tmp_path/'raw').verify_latest('20261028','STAGE_0925','A_SHARE')
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['availability']=='FAILED' and stage['rows']==[]


def test_missing_native_counts_are_null_not_inferred_complete(tmp_path):
    publish(tmp_path)
    def remove_counts(m,r):
        for key in ('requested_rows','source_rows','coverage_ratio'):
            m.pop(key);r.pop(key)
    rehash(tmp_path/'raw',mutate_manifest=remove_counts)
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['raw']['requested_rows'] is None and stage['raw']['coverage_ratio'] is None
    assert 'REQUESTED_ROWS_NOT_PROVIDED' in stage['raw']['coverage_missing_reasons']


def test_raw_covered_security_absent_from_top10_is_not_rejected(tmp_path):
    raw=publish(tmp_path)
    publish_selection(tmp_path,raw['artifact_sha256'])
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['metrics']['price']==10.2
    assert stage['selection']['selected_symbol_present'] is False
    assert stage['selection']['raw_binding_matches'] is True
    assert stage['selection']['coverage_scope']=='STAGE_RECOMMENDATIONS_TOP10_ONLY'
    assert len(stage['selection']['envelope']['rows'])==10
    assert stage['selection']['envelope']['requested_rows']==20
    assert stage['raw']['requested_rows']==3


@pytest.mark.parametrize('key,value',[('trade_date','20261027'),('stage_id','STAGE_0930_0935'),('market','HK_CONNECT')])
def test_rehashed_selection_envelope_identity_drift_is_rejected(tmp_path,key,value):
    from stage_center.selection import SelectionStore
    raw=publish(tmp_path);publish_selection(tmp_path,raw['artifact_sha256'])
    rehash(tmp_path/'selection',selection=True,
        mutate_manifest=lambda m,r:m['selection_envelope'].update({key:value}))
    assert SelectionStore(tmp_path/'selection').read_verified('20261028','STAGE_0925','A_SHARE')
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['selection'] is None and 'SELECTION_VERIFICATION_FAILED' in stage['missing_reasons']
    assert stage['metrics']['price']==10.2


def test_selection_raw_binding_difference_remains_visible(tmp_path):
    publish(tmp_path);publish_selection(tmp_path,'f'*64)
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['selection']['raw_binding_matches'] is False
    assert stage['selection']['missing_reasons']==['SELECTION_RAW_BINDING_MISMATCH']


def test_missing_price_stays_null_with_a_reason(tmp_path):
    publish(tmp_path,extra_rows=[{'last_price':None,'update_time':'2026-10-28 09:25:01',
        'window_end':'2026-10-28 09:25:01'}])
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['metrics']['price'] is None and stage['metrics']['change_pct'] is None
    assert stage['rows'][-1]['missing_fields']['last_price']=='NOT_PROVIDED'


@pytest.mark.parametrize('name',['latest.json','selection_latest.json'])
def test_malformed_pointer_arrays_return_explicit_failed_states(tmp_path,name):
    root=tmp_path/('raw' if name=='latest.json' else 'selection');root.mkdir()
    (root/name).write_text('[]')
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert ('RAW_VERIFICATION_FAILED' if name=='latest.json' else 'SELECTION_VERIFICATION_FAILED') in stage['missing_reasons']


def test_capture_preceding_quote_cannot_prove_realtime_availability(tmp_path):
    publish(tmp_path,evidence=('collected_at=2026-10-27T09:25:00+08:00',))
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['temporal_state']=='UNKNOWN'
    assert stage['observation_mode']=='UNCONFIRMED'


def test_valid_explicit_capture_time_retains_realtime_observation(tmp_path):
    publish(tmp_path,evidence=('collected_at=2026-10-28T09:25:01+08:00',))
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['temporal_state']=='TIMELY' and stage['observation_mode']=='REALTIME_OBSERVATION'
    assert stage['raw']['manifest']['temporal_cutoff_safe'] is True
    assert stage['raw']['receipt']['temporal_cutoff_safe'] is True


@pytest.mark.parametrize('proof,reason',[
    (False,'RECEIPT_TEMPORAL_PROOF_FALSE'),
    ('missing','RECEIPT_TEMPORAL_PROOF_MISSING'),
    ('true','RECEIPT_TEMPORAL_PROOF_INVALID'),
])
def test_native_rehashed_receipt_proof_cannot_be_ignored_for_realtime(tmp_path,proof,reason):
    from stage_center.raw_store import RawStore
    publish(tmp_path,evidence=('collected_at=2026-10-28T09:25:01+08:00',))
    def change_receipt(m,r):
        if proof=='missing':
            r.pop('temporal_cutoff_safe')
        else:
            r['temporal_cutoff_safe']=proof
    rehash(tmp_path/'raw',mutate_manifest=change_receipt)
    # This deliberately passes the native verifier: the adapter must assess both proofs.
    assert RawStore(tmp_path/'raw').verify_latest('20261028','STAGE_0925','A_SHARE')
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['temporal_state']=='UNSAFE'
    assert stage['observation_mode']=='RETROSPECTIVE'
    assert reason in stage['missing_reasons']
    assert stage['raw']['manifest']['temporal_cutoff_safe'] is True
    if proof=='missing':
        assert 'temporal_cutoff_safe' not in stage['raw']['receipt']
    else:
        assert stage['raw']['receipt']['temporal_cutoff_safe']==proof
    if proof is False:
        assert 'TEMPORAL_PROOF_CONFLICT' in stage['missing_reasons']


def test_temporal_false_without_native_afterfact_contract_stays_failed(tmp_path):
    publish(tmp_path)
    rehash(tmp_path/'raw',mutate_csv=lambda b:b.replace(b'True',b'False'))
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['availability']=='FAILED' and stage['rows']==[]


def test_selection_envelope_cannot_raise_safety_flags(tmp_path):
    raw=publish(tmp_path);publish_selection(tmp_path,raw['artifact_sha256'])
    rehash(tmp_path/'selection',selection=True,
        mutate_manifest=lambda m,r:m['selection_envelope'].update(production_allowed=True))
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['selection'] is None and 'SELECTION_VERIFICATION_FAILED' in stage['missing_reasons']


def test_canonical_a_source_identity_is_explicitly_unresolved_and_keeps_metadata(tmp_path):
    raw=publish(tmp_path,extra_rows=[{'code':'A.000009'},{'code':'A.000010'}])
    publish_selection(tmp_path,raw['artifact_sha256'],canonical_a=True)
    stage=service(tmp_path).get(date='20261028',symbol='000009.SZ')['stages'][0]
    assert stage['raw']['unresolved_source_symbols']==['A.000009','A.000010']
    assert 'AMBIGUOUS_A_SOURCE_IDENTITY' in stage['raw']['identity_missing_reasons']
    assert stage['raw']['row_count']==4 and stage['rows']==[]
    assert 'COVERAGE_CANNOT_CONFIRM_IDENTITY_UNRESOLVED' in stage['missing_reasons']
    assert 'SYMBOL_NOT_COVERED_BY_RAW' not in stage['missing_reasons']
    assert stage['selection']['selected_symbol_present'] is None
    assert len(stage['selection']['envelope']['rows'])==10
    assert 'FULL_SECURITY_IDENTITY_UNAVAILABLE' in stage['selection']['missing_reasons']
    # Qualified matching rows remain useful even with unresolved coexisting A.* rows.
    covered=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert covered['metrics']['price']==10.2


@pytest.mark.parametrize('evidence',[
    ('available_at=2026-10-28T09:30:00+08:00','available_at=2026-10-28T09:25:01+08:00'),
    ('captured_at=2026-10-28T09:25:01+08:00','collected_at=2026-10-28T09:30:00+08:00'),
])
def test_every_timestamp_declaration_is_retained_and_late_cannot_be_overwritten(tmp_path,evidence):
    publish(tmp_path,evidence=evidence)
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['temporal_state']=='LATE' and stage['observation_mode']=='RETROSPECTIVE'
    assert len(stage['raw']['timestamp_evidence'])==4  # native manifest and receipt retain declarations
    assert stage['raw']['timestamp_missing_reasons']


def test_naive_or_invalid_timestamp_cannot_be_silently_replaced_by_timely_one(tmp_path):
    publish(tmp_path,evidence=('captured_at=bad','collected_at=2026-10-28T09:25:01+08:00','available_at=2026-10-28 09:25:01'))
    stage=service(tmp_path).get(date='20261028',symbol='000001.SZ')['stages'][0]
    assert stage['temporal_state']=='UNKNOWN' and stage['observation_mode']=='UNCONFIRMED'
    assert len(stage['raw']['timestamp_evidence'])==6


def test_hk_auction_uses_native_market_cutoff_not_scheduler_cutoff(tmp_path):
    from stage_center.raw_store import RAW_FIELDS,RawStore
    from apps.api.v35_api.opening_observation_service import OpeningObservationService
    row={key:None for key in RAW_FIELDS}
    row.update(batch_index=0,code='HK.00001',update_time='2026-10-28 09:20:00',
        window_start='2026-10-28 09:15:00',window_end='2026-10-28 09:20:00',
        temporal_cutoff_safe=True,last_price=10,prev_close_price=10,volume=0,turnover=0,bar_count=1)
    RawStore(tmp_path/'raw').publish(trade_date='20261028',stage_id='STAGE_0925',market='HK_CONNECT',
        source_id='SYNTHETIC_HK_FIXTURE',source_status='READY',rows=[row],
        source_evidence=('available_at=2026-10-28T09:24:00+08:00',),cutoff_at='09:25:05')
    stage=service(tmp_path).get(date='20261028',symbol='00001.HK')['stages'][0]
    assert stage['cutoff_at']=='09:20:05' and stage['scheduled_cutoff_at']=='09:25:05'
    assert stage['temporal_state']=='LATE'
    early=OpeningObservationService(raw_root=tmp_path/'raw',now=lambda:datetime.fromisoformat('2026-10-28T09:24:30+08:00'))
    assert early.get(date='20261028',symbol='00001.HK')['stages'][0]['availability']=='AVAILABLE'
