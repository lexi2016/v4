"""Bounded read-only adapter: membership, source identity, and history."""
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from infrastructure import research_workbench_top200 as scoped


def _ref(path):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


@pytest.fixture
def scope(tmp_path, monkeypatch):
    rows = [{'ts_code': '600809.SH', 'trade_date': 20261029},
            {'ts_code': '600809.SH', 'trade_date': 20261030}]
    for row in rows:
        row.update({f'field_{i}': i for i in range(315)})
    path = tmp_path / 'selector.parquet'
    pq.write_table(pa.Table.from_pylist(rows), path)
    company = tmp_path / 'company.json'
    company.write_text(json.dumps({'symbol': '600809.SH', 'historical_PIT': False}))
    stock = {'symbol': '600809.SH', 'rows': 2, 'first_date': 20261029, 'last_date': 20261030,
             'f10_status': 'OBSERVED', 'assets': {'selector': _ref(path), 'backtest': _ref(path),
                                                  'events': _ref(path), 'company': _ref(company)}}
    original = {'data_date': '20261030', 'source_generation': 'g', 'input_sha256': 'i',
                'top200': [{'symbol': '600809.SH', 'name': '测试'}]}
    manifest = {'generation': 'p' * 64, 'identity': {'source_generation': 'g'},
                'calculation_columns': {'selector': 340, 'backtest': 192},
                'display_columns': {'selector': 317, 'backtest': 186}}
    monkeypatch.setattr(scoped, '_stamp', lambda ref: None)
    monkeypatch.setattr(scoped, '_bundle', lambda *args: (manifest, {'core': ['x']}, original,
                                                          {'600809.SH': stock}, {}))
    binding = {'top200_research_panel_r3': {k: {} for k in ('manifest', 'validation', 'field_lock', 'original_top200')}}
    binding['top200_research_panel_r3']['manifest'] = {'sha256': 'a' * 64}
    view = {'source_generation': 'g', 'source_identity': {'input_sha256': 'i'}, 'manifest': {}, 'rows': []}
    current = {'top200': original['top200'][:], 'artifact': {}}
    return binding, view, current, stock


def test_source_identity_and_scope_are_enforced(scope):
    binding, view, current, _ = scope
    value = scoped.metadata(binding, view, current, '2026-10-30', '600809.SH', '2026-11-02')
    assert value['fields_count'] == 107 and value['display_columns'] == {'selector': 317, 'backtest': 186}
    current['top200'] = [{'symbol': '600809.SH', 'name': 'wrong name'}]
    with pytest.raises(ValueError, match='R3_LIVE_TOP200_OR_SOURCE_CONFLICT'):
        scoped.metadata(binding, view, current, '2026-10-30', '600809.SH', '2026-11-02')
    assert scoped.resolve(binding, view, current, '2026-10-30', '002865.SZ') is None


def test_readback_preserves_full_dates_and_rejects_changed_assets(scope):
    binding, view, current, stock = scope
    args = binding, view, current, '2026-10-30', '600809.SH'
    digest = stock['assets']['selector']['sha256']
    dates = json.loads(scoped.asset(*args, 'dates', digest)[0])
    assert dates['dates'] == [20261029, 20261030]
    row = json.loads(scoped.asset(*args, 'row-20261029', digest)[0])
    assert row['column_count'] == 317 and row['fields']['trade_date'] == 20261029
    with pytest.raises(KeyError, match='R3_TRADE_DATE_NOT_IN_HISTORY'):
        scoped.asset(*args, 'row-20261028', digest)
    with pytest.raises(ValueError, match='R3_STOCK_ASSET_SHA_CONFLICT'):
        scoped.asset(*args, 'dates', '0' * 64)
    from pathlib import Path
    Path(stock['assets']['company']['path']).write_text('{}')
    with pytest.raises(ValueError, match='R3_ASSET_SHA_DRIFT'):
        scoped.asset(*args, 'company', stock['assets']['company']['sha256'])


def test_host_rejects_a_stale_panel_revision(monkeypatch):
    from infrastructure.research_workbench_host import ResearchWorkbenchHost
    host = object.__new__(ResearchWorkbenchHost)
    host.binding = {}
    host.single_stock_research = lambda *args: {'schema': 'v4.workbench.scoped_kb_research.v1', 'panel_generation': 'new'}
    with pytest.raises(ValueError, match='SCOPED_PANEL_REVISION_CONFLICT'):
        host.single_stock_asset('2026-10-30', '600809.SH', 'dates', 'a' * 64, 'source', 'old')
    host._view = lambda *args: {}
    host.top200 = lambda *args: {}
    monkeypatch.setattr(scoped, 'asset', lambda *args: (b'new', 'text/plain'))
    assert host.single_stock_asset('2026-10-30', '600809.SH', 'dates', 'a' * 64, 'source', 'new')[0] == b'new'


def test_same_date_diagnostics_are_sha_bound_and_separate_from_wide_fields(scope, tmp_path):
    binding, view, current, stock = scope
    sidecar=tmp_path/'diagnostics.parquet'
    data=[{'ts_code':'600809.SH','trade_date':day,'diagnostics_json':json.dumps({'kb_rebuild_reason':'INSUFFICIENT_HISTORY'}),
           'n_structure_json':json.dumps({'state':'INSUFFICIENT_CONFIRMED_SWINGS','rule_sha256':'a'*64})}
          for day in (20261029,20261030)]
    pq.write_table(pa.Table.from_pylist(data),sidecar);stock['assets']['diagnostics']=_ref(sidecar)
    args=binding,view,current,'2026-10-30','600809.SH'
    meta=scoped.metadata(*args,'2026-11-02')
    assert meta['assets']['diagnostics']['sha256']==stock['assets']['diagnostics']['sha256']
    row=json.loads(scoped.asset(*args,'row-20261029',stock['assets']['selector']['sha256'])[0])
    assert len(row['fields'])==317 and row['diagnostics']['kb_rebuild_reason']=='INSUFFICIENT_HISTORY'
    assert row['kb_n_structure']['state']=='INSUFFICIENT_CONFIRMED_SWINGS'
    assert row['diagnostics_sha256']==stock['assets']['diagnostics']['sha256']
    sidecar.write_bytes(b'changed')
    with pytest.raises(ValueError,match='R3_ASSET_SHA_DRIFT'):
        scoped.asset(*args,'row-20261029',stock['assets']['selector']['sha256'])
