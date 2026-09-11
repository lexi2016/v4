"""Regression tests for audit F01-F06/F11-F15; no network or production roots."""
from __future__ import annotations
import os, time, threading, copy
from pathlib import Path
from unittest.mock import patch
import pytest
from infrastructure import trading_safety
from infrastructure.data_store import NativeDataStore, _assert_watch_only
from v4.manager_research.contracts import normalise_observation_input, ContractError
from v4.manager_research.store import ManagerResearchStore
from domains.stage_scoring import _number, score_a_stage, score_hk_stage
from stage_center.selection import stage_row_sort_key
DATE = '20260908'

def raw():
    return {
        'target_trade_date': DATE,
        'stage_id': 'STAGE_0935_0940',
        'market': 'HK_CONNECT',
        'status': 'READY',
        'rows': [{
            'code': 'HK.00001',
            'name': '测试',
            'rank': 1,
            'source_last_bar_time': '2026-09-08 09:40:00',
        }],
    }

@pytest.mark.parametrize(
    'guard',
    [
        trading_safety.assert_safe_tree,
        lambda p: _assert_watch_only(p, expected_lane='lane', expected_selector='selector'),
    ],
)
@pytest.mark.parametrize('key', ['orders_sent', 'production_allowed', 'buy_gate_updated', 'action'])
def test_tuple_cannot_hide_trading_state(guard, key):
    with pytest.raises(ValueError):
        guard({'meta': ({key: True},)})

@pytest.mark.parametrize(
    'stamp',
    ['2026-09-08 16:00:00', 'bad', '', '20260908', '2026-09-07 09:40:00', '2026-09-08T01:40:01Z'],
)
def test_observation_rejects_unproven_or_late_time(stamp):
    p = raw()
    p['rows'][0]['source_last_bar_time'] = stamp
    with pytest.raises(ContractError):
        normalise_observation_input(p)

@pytest.mark.parametrize(
    'stamp',
    ['2026-09-08 09:40:00', '2026-09-08T09:40:00+08:00', '2026-09-08T01:40:00Z'],
)
def test_observation_accepts_exact_cutoff(stamp):
    p = raw()
    p['rows'][0]['source_last_bar_time'] = stamp
    assert normalise_observation_input(p)['input_row_count'] == 1

@pytest.mark.parametrize('level', ['top', 'row'])
@pytest.mark.parametrize(
    'field,value',
    [('market', 'A_SHARE'), ('target_trade_date', '20260907'), ('stage_id', 'STAGE_1545_1555')],
)
def test_observation_does_not_relabel_conflicting_identity(level, field, value):
    p = raw()
    (p if level == 'top' else p['rows'][0])[field] = value
    with pytest.raises(ContractError):
        normalise_observation_input(p)

@pytest.mark.parametrize('field', ['orders_sent', 'production_allowed', 'buy_gate_updated'])
def test_manager_input_rejects_nested_unsafe_state(field):
    p = raw()
    p['rows'][0]['meta'] = {field: True}
    with pytest.raises(ValueError):
        normalise_observation_input(p)

@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), 'NaN', 'Infinity', True, False])
def test_score_number_requires_finite_nonboolean(value):
    assert _number(value) is None

def test_nan_is_missing_not_full_marks():
    assert score_hk_stage({'stage_close_position': float('nan')}) == score_hk_stage({})
    assert score_a_stage(
        {'last_price': float('nan')},
        'STAGE_0935_0940',
    ) == score_a_stage({}, 'STAGE_0935_0940')

def test_valid_zero_ranks_ahead_of_negative():
    rows = [{'stage_score': -1, 'stock_code': 'A'}, {'stage_score': 0, 'stock_code': 'B'}]
    assert sorted(rows, key=stage_row_sort_key)[0]['stock_code'] == 'B'

def test_native_store_rejects_symlink_write(tmp_path):
    root = tmp_path / 'native'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (root / 'receipts').symlink_to(outside, target_is_directory=True)
    catalog = {
        'schema_version': 'v3_trade_calendar.v1',
        'system_date': DATE,
        'stage_dates': [DATE],
        'future_target_dates': [],
        'materialized_rows': {DATE: 1},
    }
    with pytest.raises((ValueError, OSError)):
        NativeDataStore(root).import_catalog(catalog)
    assert not list(outside.iterdir())

def test_manager_store_rejects_symlink_write(tmp_path):
    store = ManagerResearchStore(tmp_path / 'manager')
    out = tmp_path / 'outside'
    out.mkdir()
    (store.products_root / DATE).symlink_to(out, target_is_directory=True)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        store.write_product({'target_trade_date': DATE, 'input_identity': 'same'})
    assert not list(out.iterdir())

@pytest.mark.parametrize('method', ['write_product', 'replace_product', 'write_job', 'write_receipt'])
def test_manager_store_checks_all_writes(tmp_path, method):
    store = ManagerResearchStore(tmp_path)
    value = {
        'job_id': 'job',
        'target_trade_date': DATE,
        'input_identity': 'same',
        'nested': {'orders_sent': True},
    }
    with pytest.raises((ValueError, RuntimeError)):
        fn = getattr(store, method)
        fn(DATE, 'job', value) if method == 'write_receipt' else fn(value)

@pytest.mark.parametrize(
    'module_name,class_name,root_attr',
    [('stage_center.selection', 'SelectionStore', 'root'), ('stage_center.raw_store', 'RawStore', 'root')],
)
def test_active_owner_not_stolen_after_30_seconds(tmp_path, module_name, class_name, root_attr):
    import importlib
    mod = importlib.import_module(module_name)
    cls = getattr(mod, class_name)
    a = cls(tmp_path)
    b = cls(tmp_path)
    with patch.object(mod, '_LOCK_TIMEOUT_SECONDS', 0.04):
        with a._lock():
            os.utime(a.lock_path, (time.time() - 31, time.time() - 31))
            with pytest.raises(Exception):
                with b._lock():
                    pass

def test_runner_honors_stage_root_environment(monkeypatch, tmp_path):
    from apps.api.v35_api import run
    seen = {}
    monkeypatch.setenv('V35_STAGE_CENTER_SELECTION_ROOT', str(tmp_path))
    monkeypatch.setattr('sys.argv', ['run'])
    monkeypatch.setattr(run, 'create_app', lambda **kw: seen.update(kw) or object())
    monkeypatch.setattr(run.uvicorn, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(run, 'setup_json_logging', lambda: None)
    run.main()
    assert seen['stage_center_selection_root'] == tmp_path
