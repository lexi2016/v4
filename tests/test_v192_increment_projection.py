"""Synthetic-only regression of the admitted live producer's17-field projection."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
BATCH = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_v192_signal_pool_return_stability_v1/batches/v192_logic_input_diagnostic_20261020')
REGISTRY = BATCH.parents[3] / 'contracts' / 'EXPERIMENT_REGISTRY.jsonl'
ORIGINAL = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260910-d1-partial-provenance-v14/app/runtime/v1/data_layer_daily_formula_increment_update_v1.py')
CANONICAL = Path('/Users/lexi/Library/Application Support/com.lexi.research-panel.local/releases/20260821T073000Z-v35-hk0920-materialization-bridge/app/runtime/v1/build_canonical_formula_research_panel.py')
PAYLOAD = ROOT / 'ops/runtime_payloads/data_layer_daily_formula_increment_update_v1.py'
REQUIRED = (
    'kdj_d', 'ref_score_close_up', 'ref_score_above_bbi', 'ref_score_no_giant_true_yin',
    'ref_score_trend_up', 'ref_score_j_no_dead_cross', 'ref_hold_score',
    'brick_original_b1', 'brick_pullback_white_b', 'brick_pullback_yellow_b',
    'brick_oversold_shrink_b', 'brick_oversold_super_shrink_b', 'brick_strong_red',
    'brick_red_today', 'macd_above_zero_second_gold', 'macd_top_divergence',
    'white_yellow_death_cross',
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def history(symbols=1):
    """Pinned arithmetic fixture: no sampled, fetched or historical market values."""
    rows = []
    dates = pd.bdate_range(end='2026-10-20', periods=260).strftime('%Y%m%d')
    for symbol in range(symbols):
        for index, day in enumerate(dates):
            close = (2000 + symbol*500 + index*3 + (index % 17)*7 - (index % 29)*8) / 100.0
            open_ = close + ((index % 5)-2) / 100.0
            vol = 1000 + (index % 17)*50 + ((index//11) % 2)*500
            rows.append({'ts_code':f'{symbol+1:06d}.SZ', 'trade_date':int(day),
                         'open':open_, 'high':max(open_,close)+0.25,
                         'low':min(open_,close)-0.25, 'close':close,
                         'vol':float(vol), 'volume':float(vol), 'amount':vol*close*100.0})
    return pd.DataFrame(rows)


@pytest.fixture(scope='session', autouse=True)
def registered_execution(request):
    started = time.monotonic()
    contract_path = BATCH/'FIX_CONTRACT.json'
    contract = json.loads(contract_path.read_text())
    execution = os.environ['V192_REPAIR_EXECUTION_ID']
    events = [json.loads(line) for line in REGISTRY.read_text().splitlines() if line.strip()]
    same = [event for event in events if event['execution_id'] == execution]
    assert len(same) == 1 and same[0]['event_type'] == 'RUN_STARTED'
    assert same[0]['contract_sha256'] == sha(contract_path)
    assert sha(PAYLOAD) == contract['code_sha256']
    assert sha(__file__) == contract['test_sha256']
    assert sha(ORIGINAL) == contract['origin_sha256']
    assert sha(CANONICAL) == contract['canonical_sha256']
    yield
    elapsed = time.monotonic()-started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    status = 'SYNTHETIC_PROJECTION_PASS' if request.session.testsfailed == 0 else 'FAILED_SYNTHETIC_PROJECTION'
    if elapsed > 60 or peak > 2147483648:
        status = 'FAILED_SYNTHETIC_RESOURCE_BOUND'
    phase = 'CANARY' if execution.endswith('_CANARY_01') else 'REGRESSION'
    result = {'execution_id':execution, 'status':status, 'tests_collected':request.session.testscollected,
              'tests_failed':request.session.testsfailed, 'code_sha256':sha(PAYLOAD),
              'test_sha256':sha(__file__), 'contract_sha256':sha(contract_path),
              'wall_seconds':elapsed, 'peak_rss_bytes':peak,
              'market_input_rows_read':0, 'labels_truth_read':False, 'fit_model_predict_calls':0,
              'network_calls':0, 'formal_data_writes':0, 'pointer_writes':0,
              'research_only':True, 'production_allowed':False,
              'buy_gate_updated':False, 'orders_sent':False}
    with (BATCH/f'FIX_SYNTHETIC_{phase}_RECEIPT.json').open('x') as handle:
        json.dump(result,handle,ensure_ascii=False,sort_keys=True,indent=2);handle.write('\n')
    assert status == 'SYNTHETIC_PROJECTION_PASS'


@pytest.fixture
def modules():
    canonical = load(CANONICAL, 'v192_projection_test_canonical')
    repaired = load(PAYLOAD, 'v192_projection_test_repaired')
    repaired._CANONICAL_FORMULA_MODULE = canonical
    repaired.CANONICAL_FORMULA_PATH = CANONICAL
    return repaired, canonical


def compute(module, frame):
    return module.compute_formula_features_daily(frame,0,{},module._NoopLogger())


def test_canonical_projection_canary(modules):
    repaired, canonical = modules
    frame = history(1)
    actual = compute(repaired, frame)
    expected = canonical.compute_partition_formula(frame.copy()).reset_index(drop=True)
    assert tuple(repaired.V192_REQUIRED_CANONICAL_PROJECTION_FIELDS) == REQUIRED
    pd.testing.assert_frame_equal(actual[list(REQUIRED)], expected[list(REQUIRED)], check_exact=True)
    pd.testing.assert_frame_equal(actual[['ts_code','trade_date']], expected[['ts_code','trade_date']])


def test_full_partition_parity_and_only_target_fields_changed(modules):
    repaired, canonical = modules
    baseline = load(ORIGINAL, 'v192_projection_test_baseline')
    baseline._CANONICAL_FORMULA_MODULE = canonical
    baseline.CANONICAL_FORMULA_PATH = CANONICAL
    frame = history(2)
    actual = compute(repaired, frame)
    original = compute(baseline, frame)
    expected = canonical.compute_partition_formula(frame.copy()).reset_index(drop=True)
    pd.testing.assert_frame_equal(actual[list(REQUIRED)], expected[list(REQUIRED)], check_exact=True)
    pd.testing.assert_frame_equal(actual.drop(columns=list(REQUIRED),errors='ignore'),
                                  original.drop(columns=list(REQUIRED),errors='ignore'), check_exact=True)
    assert actual.ref_hold_score.eq(actual[[name for name in REQUIRED if name.startswith('ref_score_')]].sum(axis=1)).all()
    assert not original.ref_hold_score.equals(actual.ref_hold_score)
    for excluded in ['plry_first','fd_volume_yin','break_yesterday_keyline']:
        assert (excluded in actual.columns) == (excluded in original.columns)


@pytest.mark.parametrize('field', REQUIRED)
def test_missing_required_projection_fails_closed(modules, monkeypatch, field):
    repaired, _ = modules
    real = repaired._compute_canonical_v192_formula
    monkeypatch.setattr(repaired,'_compute_canonical_v192_formula',lambda frame:real(frame).drop(columns=[field]))
    with pytest.raises(RuntimeError,match='authority missing required projection fields') as error:
        compute(repaired,history(1))
    assert field in str(error.value)
    assert repaired._formula_error_is_batch_level(error.value)


@pytest.mark.parametrize('field,value', [('kdj_d',np.nan),('ref_score_close_up',np.inf),('brick_original_b1',np.nan)])
def test_nonfinite_required_projection_fails_closed(modules, monkeypatch, field, value):
    repaired, _ = modules
    real = repaired._compute_canonical_v192_formula
    def invalid(frame):
        result = real(frame)
        result[field] = result[field].astype(float)
        result.loc[result.index[-1],field] = value
        return result
    monkeypatch.setattr(repaired,'_compute_canonical_v192_formula',invalid)
    with pytest.raises(RuntimeError,match='authority invalid required projection fields') as error:
        compute(repaired,history(1))
    assert repaired._formula_error_is_batch_level(error.value)
