"""Focused BJ market predicate/unchanged row-gate tests; fixtures are synthetic."""
import hashlib,json,shutil,importlib.util
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
SOURCE = Path(__file__).resolve().parents[1]/'apps/api/v35_api/a_share_panel_history.py'
spec=importlib.util.spec_from_file_location('owned_bj_api_under_test', SOURCE)
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())

@pytest.fixture
def accepted(tmp_path, request):
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
    for symbol,date,market in [('920047.BJ',str(day),'BJ') for day in range(20261019,20261024)] + [('920002.BJ','20261019','BJ'),('000001.SZ','20261023','A_SHARE'),('600000.SH','20261023','A_SHARE')]:
        row={k:1.25 for k in h.COLUMNS};row.update({k:False for k in h.SIGNALS})
        row.update(ts_code=symbol,trade_date=date,market_type=market,name='fixture',user_v1_B3=date=='20261022',user_v1_level1_buy_signal=date=='20261022')
        rows.append(row)
    changes = getattr(request, 'param', {})
    for row in rows:
        row['market_type'] = changes.get('market_overrides', {}).get(row['ts_code'], row['market_type'])
    if changes.get('null_signal'):
        rows[0]['user_v1_B1'] = None
    if changes.get('formula_conflict'):
        meta['user_formula_contract']['source_sha256'] = 'wrong'
    table=pa.Table.from_pylist(rows).replace_schema_metadata({h.META:json.dumps(meta).encode()});pq.write_table(table,panel)
    sha=hashlib.sha256(panel.read_bytes()).hexdigest();pointer.write_text(str(panel)+'\n')
    manifest={k:meta[k] for k in ('generation_id','input_sha256','snapshot_file_sha256','asof_date','price_basis','volume_basis','convention')}
    manifest.update(candidates=dict(selector=str(panel)),candidate_sha256=dict(selector=sha))
    if changes.get('manifest_conflict'): manifest['input_sha256'] = 'wrong'
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

def read(accepted, code='920047.BJ', **kw):
    return h.read_history(accepted['root'],code,'20261019',kw.get('end','20261023'),kw.get('version',h.VERSION))

@pytest.mark.parametrize('code,count',[('920047.BJ',5),('920002.BJ',1),('000001.SZ',1),('600000.SH',1)])
def test_exact_market_mapping_preserves_real_window_shape(accepted,code,count):
    result=read(accepted,code)
    assert result['status']=='READY' and len(result['rows'])==count
    assert all(x['market_type']==('BJ' if code.endswith('.BJ') else 'A_SHARE') for x in result['rows'])
    assert all(x[s] is not None for x in result['rows'] for s in h.SIGNALS)

@pytest.mark.parametrize('accepted,code',[(dict(market_overrides={'920047.BJ':'A_SHARE'}),'920047.BJ'),(dict(market_overrides={'000001.SZ':'BJ'}),'000001.SZ'),(dict(market_overrides={'600000.SH':'BJ'}),'600000.SH')],indirect=['accepted'])
def test_wrong_market_marker_is_rejected(accepted,code):
    result=read(accepted,code)
    assert result['status']=='CANNOT_CONFIRM' and result['cannot_confirm']==['EXACT_HISTORY_OR_LABEL_COVERAGE_CONFLICT']

@pytest.mark.parametrize('accepted',[dict(null_signal=True)],indirect=True)
def test_bj_missing_original_signal_still_rejected(accepted):
    assert read(accepted)['cannot_confirm']==['EXACT_HISTORY_OR_LABEL_COVERAGE_CONFLICT']

def test_cross_code_reader_leak_still_rejected(accepted,monkeypatch):
    original=h.importlib.util.spec_from_file_location
    def leaking_spec(name,path):
        spec=original(name,path)
        if name=='a_share_default_history_reader':
            execute=spec.loader.exec_module
            def load(module):
                execute(module);real=module.load_selector_ready
                def leak(**kwargs):
                    frame=real(**kwargs);frame.loc[0,'ts_code']='920002.BJ';return frame
                module.load_selector_ready=leak
            spec.loader.exec_module=load
        return spec
    monkeypatch.setattr(h.importlib.util,'spec_from_file_location',leaking_spec)
    assert read(accepted)['cannot_confirm']==['EXACT_HISTORY_OR_LABEL_COVERAGE_CONFLICT']

def test_bj_future_end_gate_still_rejected(accepted):
    assert read(accepted,end='20261026')['cannot_confirm']==['REQUEST_END_AFTER_ACCEPTED_PANEL_ASOF']

@pytest.mark.parametrize('accepted',[dict(formula_conflict=True)],indirect=True)
def test_bj_formula_namespace_gate_still_rejected(accepted):
    assert read(accepted)['cannot_confirm']==['ORIGINAL_FORMULA_NAMESPACE_UNCONFIRMED']

@pytest.mark.parametrize('accepted',[dict(manifest_conflict=True)],indirect=True)
def test_bj_original_source_binding_gate_still_rejected(accepted):
    assert read(accepted)['cannot_confirm']==['PRODUCER_MANIFEST_IDENTITY_CONFLICT']
