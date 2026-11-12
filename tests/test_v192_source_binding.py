"""Regression for exact logical selector binding and immutable V192 repair."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as physical
import pytest

from infrastructure.formula_generation import read_selector_source_binding
from infrastructure.isolated_package_loader import load_isolated_package_module
from ops.daily_materialize import resolve_selector_panel
from ops import materialize_shared_v192_preselection as wrapper
from ops import research_panel_logical as logical

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'upstreams/v3_shared_data'
IDENTITY_KEYS = {'run_id', 'artifact_sha256', 'manifest_sha256', 'receipt_sha256',
                 'artifact_relative', 'manifest_relative', 'receipt_relative'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def selector(tmp_path, day='20261112', *, suffix='', table=None):
    directory = tmp_path / ('source' + suffix)
    directory.mkdir()
    if table is None:
        table = pa.table({'ts_code': ['600000.SH'], 'trade_date': [day]})
    block = directory / 'block.parquet'
    physical.write_table(table, block)
    snapshot = directory / 'snapshot.json'
    snapshot.write_text(json.dumps({'asof_date': int(day)}))
    receipt = directory / 'candidate_receipt.json'
    generation, input_sha = 'a' * 64, 'b' * 64
    metadata = dict(table.schema.metadata or {})
    metadata[b'a_share_qfq_contract_v1'] = json.dumps(dict(asof_date=int(day),
        generation_id=generation, input_sha256=input_sha, generation_manifest_path=str(receipt),
        snapshot_file_sha256=sha(snapshot))).encode()
    panel = directory / 'selector.parquet'
    panel.write_bytes(logical.anchor_bytes(table.schema.with_metadata(metadata),
        [logical.descriptor(block)], rows=len(table)))
    receipt.write_text(json.dumps(dict(status='CANDIDATE_READY', target_date=int(day),
        generation_id=generation, input_sha256=input_sha, candidates={'selector': str(panel)},
        candidate_sha256={'selector': sha(panel)}, adjustment_snapshot={'path': str(snapshot), 'sha256': sha(snapshot)})))
    return panel


def owner():
    return load_isolated_package_module(Path(os.environ.get("V192_TEST_PACKAGE", PACKAGE)), package_directory='shared_data',
        module_leaf='v192_selector', namespace_prefix='test_exact_source')


def proof(verified):
    return {key: verified.run.verification[key] for key in IDENTITY_KEYS}


def test_logical_pointer_wins_and_invalid_identity_never_falls_back(tmp_path):
    panel = selector(tmp_path)
    pointer = tmp_path / 'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt'
    pointer.parent.mkdir()
    pointer.write_text(str(panel))
    old = tmp_path / 'selector_ready_panels/old.parquet'
    old.parent.mkdir()
    physical.write_table(pa.table({'trade_date': ['20261112']}), old)
    assert resolve_selector_panel(tmp_path, '20261112') == panel
    assert read_selector_source_binding(panel, expected_signal_date='20261112')['sha256'] == sha(panel)
    with pytest.raises(FileNotFoundError, match='asof date mismatch'):
        resolve_selector_panel(tmp_path, '20261111')
    panel.write_bytes(panel.read_bytes() + b' ')
    with pytest.raises(FileNotFoundError, match='receipt identity mismatch'):
        resolve_selector_panel(tmp_path, '20261112')


def test_logical_block_mutation_is_rejected(tmp_path):
    panel = selector(tmp_path)
    block = panel.parent / 'block.parquet'
    physical.write_table(pa.table({'ts_code': ['000001.SZ'], 'trade_date': ['20261112']}), block)
    with pytest.raises(ValueError, match='LOGICAL_BLOCK_CHANGED'):
        read_selector_source_binding(panel, expected_signal_date='20261112')


@pytest.mark.filterwarnings("ignore:DataFrame is highly fragmented:pandas.errors.PerformanceWarning")
def test_exact_oracle_outputs_match_physical_for_logical_input(tmp_path):
    spec = importlib.util.spec_from_file_location('v192_fixture_source', PACKAGE / 'tests/test_v192_selector.py')
    # Fixture module imports the already-isolated shared package through its
    # canonical package name only within this test process.
    import sys
    monkey = pytest.MonkeyPatch()
    monkey.syspath_prepend(str(PACKAGE))
    try:
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        physical_panel = tmp_path / 'physical.parquet'
        dates = fixture._write_long_oracle_fixture(physical_panel)
        table = physical.read_table(physical_panel)
        panel = selector(tmp_path, dates[-1], table=table)
        module = owner()
        assert module.run_frozen_v192_oracle(panel, dates[-1]) == module.run_frozen_v192_oracle(physical_panel, dates[-1])
        fields = module._read_selector_panel_source_rows(panel, dates[-1])
        assert fields == module._read_selector_panel_source_rows(physical_panel, dates[-1])
    finally:
        monkey.undo()


def test_empty_csv_new_source_uses_original_store_cas_and_preserves_old_run(tmp_path):
    module = owner()
    first = selector(tmp_path, suffix='old')
    second = selector(tmp_path, suffix='new')
    store = tmp_path / 'store'
    options = dict(signal_date='20261112', target_date='20261113', rows=[],
                   oracle_sha256s=module.verify_oracle_sources())
    module.publish_v192_rows(store, panel_path=first, **options)
    old = module.read_verified_v192_pool(store, target_date='20261113', expected_signal_date='20261112')
    identity = proof(old)
    old_bytes = {p: p.read_bytes() for p in old.run.artifact_path.parent.iterdir()}
    before = (store / 'latest.json').read_bytes()
    with pytest.raises(module.StoreError):
        module.publish_v192_rows(store, panel_path=second, **options)
    assert (store / 'latest.json').read_bytes() == before
    with pytest.raises(module.StoreError):
        module.publish_v192_rows(store, panel_path=second, historical_backfill=True,
            expected_previous={**identity, 'manifest_sha256': '0' * 64}, **options)
    assert (store / 'latest.json').read_bytes() == before
    module.publish_v192_rows(store, panel_path=second, historical_backfill=True,
        expected_previous=identity, **options)
    new = module.read_verified_v192_pool(store, target_date='20261113', expected_signal_date='20261112')
    assert old.run.verification['artifact_sha256'] == new.run.verification['artifact_sha256']
    assert old.run.verification['run_id'] != new.run.verification['run_id']
    assert new.run.manifest['provenance']['panel_sha256'] == sha(second)
    assert new.run.receipt['supersedes'] == identity
    assert all(p.read_bytes() == data for p, data in old_bytes.items())


def test_wrapper_exact_conflict_replacement_reuse_and_stale_cas(tmp_path, monkeypatch, capsys):
    module = owner()
    old_panel = selector(tmp_path, suffix='old')
    panel = selector(tmp_path, suffix='new')
    store = tmp_path / 'store'
    module.publish_v192_rows(store, panel_path=old_panel, signal_date='20261112', target_date='20261113',
        rows=[], oracle_sha256s=module.verify_oracle_sources())
    old = module.read_verified_v192_pool(store, target_date='20261113', expected_signal_date='20261112')
    previous = tmp_path / 'previous.json'
    previous.write_text(json.dumps(proof(old)))
    calls = []
    def materialize(store, **options):
        calls.append(options)
        return module.materialize_frozen_v192_selector(store, runner=lambda *_: [], **options)
    monkeypatch.setattr(wrapper, 'load_isolated_package_module', lambda *_a, **_k:
        SimpleNamespace(StoreError=module.StoreError, read_verified_v192_pool=module.read_verified_v192_pool,
                        materialize_frozen_v192_selector=materialize))
    monkeypatch.setenv('V4_SHARED_PACKAGE_ROOT', str(PACKAGE))
    monkeypatch.setenv('V3_SHARED_DATA_STORE_ROOT', str(store))
    args = ['--signal-date', '20261112', '--target-date', '20261113', '--source-panel', str(panel)]
    assert wrapper.main(args) == 1
    assert 'does not match exact selector_source' in json.loads(capsys.readouterr().out)['error']
    assert calls == []
    assert wrapper.main(args + ['--historical-backfill']) == 1
    assert calls == []
    capsys.readouterr()
    repair = args + ['--historical-backfill', '--expected-previous-json', str(previous)]
    assert wrapper.main(repair) == 0
    assert json.loads(capsys.readouterr().out)['source_panel']['sha256'] == sha(panel)
    assert len(calls) == 1
    assert wrapper.main(repair) == 0
    assert json.loads(capsys.readouterr().out)['already_exists'] is True
    assert len(calls) == 1
    wrong = proof(old)
    wrong['manifest_sha256'] = '0' * 64
    previous.write_text(json.dumps(wrong))
    assert wrapper.main(repair) == 1
    assert 'expected_previous identity mismatch' in json.loads(capsys.readouterr().out)['error']
    assert len(calls) == 1


def test_wrapper_missing_input_never_reuses_unbound_old_run(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('V3_SHARED_SELECTOR_READY_PANEL', raising=False)
    monkeypatch.setenv('V4_SHARED_PACKAGE_ROOT', str(PACKAGE))
    monkeypatch.setenv('V3_SHARED_DATA_STORE_ROOT', str(tmp_path / 'unused'))
    monkeypatch.setattr(wrapper, 'load_isolated_package_module',
        lambda *_a, **_k: pytest.fail('missing exact source must fail before reader/producer'))
    assert wrapper.main(['--signal-date', '20261111', '--target-date', '20261112']) == 1
    assert 'EXACT_INPUT_MISSING' in json.loads(capsys.readouterr().out)['error']


def test_nonempty_scheduler_reuse_checks_current_selector_before_ready(tmp_path, monkeypatch):
    # Load only the changed split body. The frozen maintenance branch's
    # unrelated scheduler facade imports a missing notifications module.
    import sys, types
    package_name = '_v192_regression_parts'
    package = types.ModuleType(package_name)
    package.__path__ = [str(ROOT/'infrastructure/scheduling/_executor_registry_parts')]
    sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(package_name+'.preselection', Path(package.__path__[0])/'preselection.py')
    body = importlib.util.module_from_spec(spec);spec.loader.exec_module(body)
    read = body._FixedExecutorRegistry__verified_preselection_source_body
    panel = selector(tmp_path)
    pointer = tmp_path / 'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt'
    pointer.parent.mkdir(); pointer.write_text(str(panel))
    pool = SimpleNamespace(run=SimpleNamespace(
        manifest={'provenance': {'panel_sha256': sha(panel)}},
        receipt=dict(status='READY', run_id='nonempty', production_allowed=False, buy_gate_updated=False, orders_sent=False),
        verification=dict(run_id='nonempty',artifact_sha256='c'*64,row_count=1,artifact_relative='runs/20261113/A_SHARE_V192_PREMARKET_POOL_V3/nonempty/artifact.csv',manifest_sha256='d'*64,receipt_sha256='e'*64)), rows=[{'ts_code':'600000.SH'}])
    module = SimpleNamespace(read_verified_v192_pool=lambda *_a, **_k: pool)
    scope = dict(load_isolated_package_module=lambda *_a, **_k: module, os=os)
    registry = SimpleNamespace(shared_data_root=tmp_path/'store', shared_package_root=PACKAGE,selector_data_root=tmp_path)
    kwargs=dict(module_leaf='v192_selector',reader_name='read_verified_v192_pool',target_date='20261113',signal_date='20261112')
    ready, reason=read(scope,registry,**kwargs)
    assert ready['run_id']=='nonempty' and reason==''
    from infrastructure import preselection_pool_store
    cached=dict(source_run_id='nonempty',source_sha256='c'*64,
        source_path=pool.run.verification['artifact_relative'],rows=[{'symbol':'A.600000'}])
    class Cache:
        def __init__(self,*_a):pass
        def read_pool(self,*_a):return cached
    monkeypatch.setattr(preselection_pool_store,'PreselectionPoolStore',Cache)
    registry.data_root=tmp_path/'native'
    ready,reason=read(scope,registry,**kwargs)
    assert ready['run_id']=='nonempty' and reason==''
    cached['source_path']='wrong'
    rejected,reason=read(scope,registry,**kwargs)
    assert rejected is None and 'V192_FORMAL_CACHE_SOURCE_IDENTITY_CONFLICT' in reason
    cached['source_path']=pool.run.verification['artifact_relative']
    pool.run.manifest['provenance']['panel_sha256']='0'*64
    ready, reason=read(scope,registry,**kwargs)
    assert ready is None and 'V192_CURRENT_SELECTOR_SOURCE_IDENTITY_CONFLICT' in reason


def test_native_v192_repair_uses_original_builder_cas_and_keeps_siblings(tmp_path):
    from domains.preselection_materializer import build_shared_v192_premarket_pool
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    module=owner();package=Path(os.environ.get('V192_TEST_PACKAGE',PACKAGE))
    shared=tmp_path/'shared';native=PreselectionPoolStore(tmp_path/'native')
    old_panel=selector(tmp_path,suffix='old');panel=selector(tmp_path,suffix='new')
    args=dict(signal_date='20261112',target_date='20261113',rows=[],oracle_sha256s=module.verify_oracle_sources())
    module.publish_v192_rows(shared,panel_path=old_panel,**args)
    old=module.read_verified_v192_pool(shared,target_date='20261113',expected_signal_date='20261112')
    old_payload=build_shared_v192_premarket_pool(shared,trade_date='20261113',signal_date='20261112',shared_package_root=package)
    # Reproduce the actual old native pool, which did not retain these fields.
    old_payload.pop('source_manifest_sha256');old_payload.pop('source_receipt_sha256')
    native.materialize(old_payload)
    sibling=dict(schema_version='v3_5.preselection_pool.v1',trade_date='20261113',pool_id='a_share_baimao_research_map',display_name='sibling',market='A',status='VALID_EMPTY',producer_id='fixture',source_role='RAW_SOURCE',source_path='fixture',source_sha256='d'*64,rows=[],cannot_confirm=[],production_allowed=False,buy_gate_updated=False,orders_sent=False)
    native.materialize(sibling)
    sibling_before=native.read_pool_snapshot('20261113',sibling['pool_id'])
    snap=native.read_pool_snapshot('20261113','a_d1_premarket_pool')
    expected={k:snap[k]for k in ['artifact_raw_sha256','receipt_raw_sha256','manifest_raw_sha256']}
    module.publish_v192_rows(shared,panel_path=panel,historical_backfill=True,expected_previous=proof(old),**args)
    payload=build_shared_v192_premarket_pool(shared,trade_date='20261113',signal_date='20261112',shared_package_root=package)
    assert payload['source_manifest_sha256'] and payload['source_receipt_sha256']
    options=dict(shared_root=shared,shared_package_root=package,selector_panel=panel,signal_date='20261112')
    with pytest.raises(ValueError,match='PREIMAGE_MISMATCH'):
        native.refresh_verified_v192_source(payload,expected_previous={**expected,'receipt_raw_sha256':'0'*64},**options)
    with pytest.raises(ValueError,match='SELECTOR_IDENTITY_CONFLICT'):
        native.refresh_verified_v192_source(payload,expected_previous=expected,**{**options,'selector_panel':old_panel})
    bad={**payload,'display_name':'wrong projection'}
    with pytest.raises(ValueError,match='ORIGINAL_BUILDER_MISMATCH'):
        native.refresh_verified_v192_source(bad,expected_previous=expected,**options)
    result=native.refresh_verified_v192_source(payload,expected_previous=expected,**options)
    current=native.read_pool('20261113','a_d1_premarket_pool')
    assert current==payload and current['stage_selection_eligible'] is False
    assert current['source_sha256']==old_payload['source_sha256']
    assert current['source_run_id']!=old_payload['source_run_id']
    assert native.read_pool_snapshot('20261113',sibling['pool_id'])['artifact_raw_sha256']==sibling_before['artifact_raw_sha256']
    revision=tmp_path/'native/preselection_revisions/20261113/a_d1_premarket_pool'/f"{result['previous_sha256']}.json"
    assert json.loads(revision.read_bytes())==old_payload
    assert not list((tmp_path/'native/preselection_pending_commits').rglob('*.json'))
    with pytest.raises(ValueError,match='PREIMAGE_MISMATCH'):
        native.refresh_verified_v192_source(payload,expected_previous=expected,**options)


def test_actual_legacy_nonempty_cache_guard_accepts_match_and_rejects_wrong_generation(tmp_path,monkeypatch):
    path=os.environ.get('V192_RUNTIME_PRESELECTION')
    if not path:pytest.skip('actual live-base delta is supplied for runtime acceptance')
    import ast
    from infrastructure import isolated_package_loader
    panel=selector(tmp_path)
    pointer=tmp_path/'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt';pointer.parent.mkdir();pointer.write_text(str(panel))
    verification=dict(run_id='correct',artifact_sha256='c'*64,manifest_sha256='d'*64,receipt_sha256='e'*64,artifact_relative='runs/20261113/A_SHARE_V192_PREMARKET_POOL_V3/correct/artifact.csv')
    verified=SimpleNamespace(run=SimpleNamespace(manifest={'provenance':{'panel_sha256':sha(panel)}},verification=verification))
    monkeypatch.setattr(isolated_package_loader,'load_isolated_package_module',lambda *_a,**_k:SimpleNamespace(read_verified_v192_pool=lambda *_a,**_k:verified))
    payload=dict(pool_id='a_d1_premarket_pool',market='A',trade_date='20261113',target_date='20261113',source_role='SHARED_VERIFIED_V192',stage_selection_eligible=True,status='V192_CANDIDATE_READY',rows=[dict(symbol='A.600000')],source_sha256=verification['artifact_sha256'],source_run_id='correct',source_path=verification['artifact_relative'],source_manifest_sha256=verification['manifest_sha256'],source_receipt_sha256=verification['receipt_sha256'],production_allowed=False,buy_gate_updated=False,orders_sent=False)
    class Store:
        def __init__(self,*_a):pass
        def read_pool(self,day,pool_id):
            if pool_id=='a_d1_premarket_pool':return payload
            raise FileNotFoundError(pool_id)
    tree=ast.parse(Path(path).read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='_verified_formal_pool_reuse')
    namespace=dict(PreselectionPoolStore=Store,json=json)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
    registry=SimpleNamespace(data_root=tmp_path/'native',shared_data_root=tmp_path/'shared',shared_package_root=PACKAGE,selector_data_root=tmp_path)
    match=namespace['_verified_formal_pool_reuse'](registry,'20261113')
    assert match['hk_missing_retry']is True and match['a_identity']['source_sha256']==verification['artifact_sha256']
    # Reproduce the review failure: a valid old native cache omitted both
    # optional hashes. It must reuse without writing an upgraded artifact.
    payload.pop('source_manifest_sha256');payload.pop('source_receipt_sha256')
    match=namespace['_verified_formal_pool_reuse'](registry,'20261113')
    assert match['hk_missing_retry'] is True
    for field in ['source_run_id','source_sha256','source_path','source_manifest_sha256','source_receipt_sha256']:
        before=dict(payload);payload[field]='wrong'
        assert namespace['_verified_formal_pool_reuse'](registry,'20261113') is None
        assert registry._v192_source_reuse_conflict=='V192_FORMAL_CACHE_SOURCE_IDENTITY_CONFLICT'
        payload.clear();payload.update(before)
    payload['source_manifest_sha256']=None
    assert namespace['_verified_formal_pool_reuse'](registry,'20261113') is None
    payload.pop('source_manifest_sha256')
    verified.run.manifest['provenance']['panel_sha256']='0'*64
    assert namespace['_verified_formal_pool_reuse'](registry,'20261113')is None
    assert registry._v192_source_reuse_conflict=='V192_CURRENT_SELECTOR_SOURCE_IDENTITY_CONFLICT'
