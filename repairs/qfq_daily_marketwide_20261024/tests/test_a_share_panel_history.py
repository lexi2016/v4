"""Exact read-only consumer contract; all fixtures use temporary accepted data."""
import hashlib
import json
from pathlib import Path
import shutil

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from apps.api.v35_api import a_share_panel_history as h
from apps.api.v35_api.research_router import create_research_router


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def accepted(tmp_path):
    root = tmp_path/'shared'
    cache = root/'runtime/cache/data_layer_daily_formula_increment_update_v1';cache.mkdir(parents=True)
    (cache/'qfq_publish.lock').touch()
    pointer = root/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt';pointer.parent.mkdir()
    reader = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/data_layer_interface_current/DATA_LAYER_INTERFACE.py')
    assert hashlib.sha256(reader.read_bytes()).hexdigest() == '5fd9024fc4ee858a62eaac050532187b171289eac82837bc7ca406e938509ded'
    shutil.copyfile(reader,pointer.with_name('DATA_LAYER_INTERFACE.py'))
    panel = tmp_path/'accepted.parquet'
    generation='a'*64;input_sha='b'*64
    code={k:hashlib.sha256(k.encode()).hexdigest() for k in h.CODE_KEYS};code['user_formula_sha256']=h.FORMULA_SHA
    formula=dict(version=h.VERSION,source_sha256=h.FORMULA_SHA,signal_fields=list(h.SIGNALS),level1='B3 OR STRICT_ABOVE_ZERO_SECOND_GOLD',legacy_primary='unchanged model legacy')
    manifest_path=tmp_path/'producer.json'
    meta=dict(schema='a_share_qfq_panel_v1',price_basis='QFQ_ASOF',volume_basis='QFQ_EVENT_VOLUME',
              snapshot_file_sha256='c'*64,generation_id=generation,input_sha256=input_sha,user_formula_contract=formula,
              generation_manifest_path=str(manifest_path),asof_date=20261023,convention='existing_convention',**code)
    rows=[]
    for symbol,date,market in [('000156.SZ','20261021','A_SHARE'),('000156.SZ','20261022','A_SHARE'),('000156.SZ','20261023','A_SHARE'),('002612.SZ','20261023','A_SHARE')]:
        row={k:1.25 for k in h.COLUMNS};row.update({k:False for k in h.SIGNALS})
        row.update(ts_code=symbol,trade_date=date,market_type=market,name='fixture',user_v1_B3=date=='20261022',user_v1_level1_buy_signal=date=='20261022')
        rows.append(row)
    table=pa.Table.from_pylist(rows).replace_schema_metadata({h.META:json.dumps(meta).encode()});pq.write_table(table,panel)
    sha=hashlib.sha256(panel.read_bytes()).hexdigest();pointer.write_text(str(panel)+'\n')
    manifest={k:meta[k] for k in ('generation_id','input_sha256','snapshot_file_sha256','asof_date','price_basis','volume_basis','convention')}
    manifest.update(candidates=dict(selector=str(panel)),candidate_sha256=dict(selector=sha))
    save(manifest_path,manifest)
    backtest_pointer=root/'backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt'
    backtest_pointer.parent.mkdir();backtest_pointer.write_text(str(panel)+'\n')
    save(cache/'qfq_publication.json',dict(status='COMMITTED'))
    binding=save(tmp_path/'accounting_binding.json',dict(candidate_roles=dict(selector=dict(path=str(panel),sha256=sha,stat_binding=h._stat(panel)))))
    audit=save(tmp_path/'audit.json',dict(identity=dict(audit_input_binding_sha256=binding['sha256']),evidence_paths=[binding]))
    composite=save(tmp_path/'composite.json',dict(verdict='REVIEWED/PASS_LOCAL_PANEL_HISTORY_CANDIDATE',candidate_generation=generation,input_sha256=input_sha,candidate_sha256=dict(selector=sha),A_receipt=dict(report_path=audit['path'],report_sha256=audit['sha256'])))
    receipt=save(tmp_path/'oracle_receipt.json',dict(generation_id=generation,asof_date=20261023,code_binding=code,status='PASS_FUTU_DISPLAY_ORACLE',independent_review=composite))
    save(cache/'qfq_convention_acceptance.json',dict(status='PASS',reviewer_id='independent',initial_oracle_receipt=receipt,code_binding=code,convention='existing_convention',initial_asof_date=20261023))
    save(cache/'qfq_expected_current.json',dict(schema='qfq_expected_current_v1',roles=dict(selector=dict(pointer_path=str(pointer),pointer_sha256=hashlib.sha256(pointer.read_bytes()).hexdigest(),target_path=str(panel),target_sha256=sha))))
    return dict(root=root,cache=cache,pointer=pointer,panel=panel,manifest=manifest_path,binding=Path(binding['path']),composite=Path(composite['path']))


def read(accepted,**kw):
    return h.read_history(accepted['root'],kw.get('code','000156.SZ'),kw.get('start','20261022'),kw.get('end','20261023'),kw.get('version',h.VERSION))


def test_exact_stored_user_namespace_and_accepted_stat_no_payload_hash(accepted,monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('unchanged independently accepted artifact must not rehash')
    monkeypatch.setattr(h,'_hash_new_generation_once',forbidden)
    result=read(accepted)
    assert result['status']=='READY'
    assert [r['trade_date'] for r in result['rows']]==['20261022','20261023']
    assert all(r['ts_code']=='000156.SZ' for r in result['rows'])
    assert result['rows'][0]['user_v1_level1_buy_signal'] is True
    assert result['rows'][1]['user_v1_level1_buy_signal'] is False
    assert sum(k.startswith('user_v1_') for k in result['rows'][0])==23
    assert not any(any(t in k.lower() for t in ('future','target','primary_buy_signal','label_')) for k in result['columns'])
    assert result['identity']['formula_source_sha256']==h.FORMULA_SHA


def test_empty_is_exact_and_never_nearest(accepted):
    result=read(accepted,start='20200101',end='20200102')
    assert result['status']=='EMPTY_EXACT_RANGE' and result['rows']==[]


@pytest.mark.parametrize('change',[dict(code='000156'),dict(code='00700.HK'),dict(start='20260230'),dict(start='20261024',end='20261023'),dict(version='legacy')])
def test_invalid_exact_request_rejected(accepted,change):
    with pytest.raises(ValueError):read(accepted,**change)


def test_missing_binding_is_cannot_confirm_not_raw_fallback(accepted):
    (accepted['cache']/'qfq_convention_acceptance.json').unlink()
    result=read(accepted);assert result['status']=='CANNOT_CONFIRM' and result['rows']==[]


def test_future_end_is_explicit_not_partial_range(accepted):
    result=read(accepted,end='20261026')
    assert result['status']=='CANNOT_CONFIRM' and result['cannot_confirm']==['REQUEST_END_AFTER_ACCEPTED_PANEL_ASOF']


def test_original_quarantine_is_not_reported_as_healthy_empty(accepted,tmp_path):
    x=json.loads(accepted['manifest'].read_text())
    x['quarantine_manifest']=save(tmp_path/'excluded.json',dict(reasons={'301139.SZ':'ORIGINAL_RAW_FOUR_KEY_GAP'}))
    save(accepted['manifest'],x)
    result=read(accepted,code='301139.SZ')
    assert result['status']=='CANNOT_CONFIRM' and 'ORIGINAL_QUARANTINE' in str(result['cannot_confirm'])


def test_default_pointer_conflict_no_candidate_fallback(accepted):
    accepted['pointer'].write_text('/does/not/exist.parquet\n')
    result=read(accepted);assert result['status']=='CANNOT_CONFIRM' and result['rows']==[]


def test_producer_manifest_conflict_rejected(accepted):
    x=json.loads(accepted['manifest'].read_text());x['input_sha256']='wrong';save(accepted['manifest'],x)
    result=read(accepted);assert result['status']=='CANNOT_CONFIRM' and result['rows']==[]


def test_same_file_stat_drift_rejected(accepted):
    accepted['panel'].touch()
    result=read(accepted);assert result['status']=='CANNOT_CONFIRM' and 'STAT_CONFLICT' in str(result['cannot_confirm'])


def test_publication_in_progress_clears_rows(accepted):
    import fcntl
    with (accepted['cache']/'qfq_publish.lock').open('rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=read(accepted)
    assert result['status']=='CANNOT_CONFIRM' and result['cannot_confirm']==['PUBLICATION_IN_PROGRESS'] and result['rows']==[]


def test_route_registered_get_only_and_configuration_required(accepted,tmp_path):
    app=FastAPI();app.include_router(create_research_router(tmp_path/'app',shared_data_root=accepted['root']))
    client=TestClient(app);params=dict(ts_code='000156.SZ',start_date='20261022',end_date='20261023',formula_version=h.VERSION)
    assert client.get('/api/v3/research/a-share/history',params=params).json()['status']=='READY'
    assert client.post('/api/v3/research/a-share/history',params=params).status_code==405
    assert client.get('/api/v3/research/a-share/history',params={**params,'formula_version':'legacy'}).status_code==422
    assert h.read_history(None,'000156.SZ','20261022','20261023',h.VERSION)['status']=='CANNOT_CONFIRM'


def test_later_daily_payload_identity_cached_once_per_stat(accepted,monkeypatch):
    h._hash_new_generation_once.cache_clear()
    panel=accepted['panel'];sha=hashlib.sha256(panel.read_bytes()).hexdigest();before=h._hash_new_generation_once.cache_info()
    meta=dict(generation_id='next-daily-generation')
    for _ in range(2):h._artifact_identity(panel,sha,meta,dict(generation_id='initial-generation'))
    info=h._hash_new_generation_once.cache_info()
    assert info.misses-before.misses==1 and info.hits-before.hits==1


def test_failed_payload_identity_cached_once_per_unchanged_stat(accepted):
    h._hash_new_generation_once.cache_clear()
    meta=dict(generation_id='next-daily-generation');receipt=dict(generation_id='initial-generation')
    for _ in range(2):
        with pytest.raises(h.Unconfirmed,match='ACCEPTED_ARTIFACT_SHA_CONFLICT'):
            h._artifact_identity(accepted['panel'],'0'*64,meta,receipt)
    info=h._hash_new_generation_once.cache_info()
    assert info.misses==1 and info.hits==1


def test_failed_payload_cache_refreshes_on_expected_sha_or_stat_change(accepted):
    h._hash_new_generation_once.cache_clear()
    panel=accepted['panel'];sha=hashlib.sha256(panel.read_bytes()).hexdigest()
    meta=dict(generation_id='next-daily-generation');receipt=dict(generation_id='initial-generation')
    with pytest.raises(h.Unconfirmed):h._artifact_identity(panel,'0'*64,meta,receipt)
    h._artifact_identity(panel,sha,meta,receipt)
    assert h._hash_new_generation_once.cache_info().misses==2
    panel.touch()
    with pytest.raises(h.Unconfirmed):h._artifact_identity(panel,'0'*64,meta,receipt)
    assert h._hash_new_generation_once.cache_info().misses==3


def test_authoritative_uppercase_reader_path_and_basis_contract(accepted):
    assert not accepted['pointer'].with_name('selector_data_layer_interface.py').exists()
    result=read(accepted)
    assert result['status']=='READY'
    assert result['identity']['reader_source_sha256']=='5fd9024fc4ee858a62eaac050532187b171289eac82837bc7ca406e938509ded'
    manifest=json.loads(accepted['manifest'].read_text())
    manifest['price_basis']='RAW_VERIFIED';save(accepted['manifest'],manifest)
    result=read(accepted)
    assert result['status']=='CANNOT_CONFIRM' and not result['rows']
    assert 'CANNOT_CONFIRM_QFQ_GENERATION_BINDING' in str(result['cannot_confirm'])
