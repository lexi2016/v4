"""Only new cache/resource behavior; synthetic tokens and zero estimator fits."""
import copy
from concurrent.futures import Future
import json
import os
from pathlib import Path

import pytest

import model194 as model
import model_input_cache194 as cache
import long_run194 as runner
from long_training_adapter import configure_native_thread_budget, select_safe_fit_workers


def test_readonly_cache_literal_encoder_label_order_and_drift(tmp_path):
    config = dict(technical_features=model.TECHNICAL, top_n=50, seed=194)
    rows = []
    for i, state in enumerate(model.STATES):
        row = {field: str(int(j == i)) for j, field in enumerate(model.TECHNICAL)}
        row.update({lane: model.STATES[(i + j) % 3] for j, lane in enumerate(model.SOURCES)})
        row.update(target_date='2003-09-24', signal_date='2003-09-23', code=f'{i + 1:06d}.SZ',
                   decision_at='2003-09-24T09:25:00+08:00', available_at='2003-09-23T15:00:00+08:00',
                   label=str(i % 2), label_end_at='2003-09-24T15:00:00+08:00',
                   label_available_at='2003-09-24T15:00:00+08:00')
        rows.append(row)
    projection = cache.encode_rows(rows, model, tmp_path / 'projection')
    restored = cache.open_projection(projection, verify_bytes=True)
    assert cache.projection_parity(rows, restored, model, config)['every_X_Y_value_equal']
    assert [dict(row) for row in restored] == rows
    assert [row['source_fupan'] for row in restored] == list(model.STATES)
    assert model.feature_values(restored[2], config, 'candidate')[13] == 1.0  # unknown indicator
    with pytest.raises(ValueError):
        restored.array[0, 0] = 1
    changed = copy.deepcopy(rows)
    changed[0]['code'] = '999999.SZ'
    with pytest.raises(ValueError, match='CACHE_CELL_VALUE_DRIFT'):
        cache.projection_parity(changed, restored, model, config)
    original = cache.stat(projection['files']['codes']['path'])
    os.utime(projection['files']['codes']['path'], ns=(original['mtime_ns'], original['mtime_ns'] + 1000000))
    with pytest.raises(ValueError, match='CACHE_FILE_STAT_DRIFT'):
        cache.open_projection(projection, verify_bytes=False)
    assert all(value == 0 for value in model.FIT_COUNTS.values())


def test_runtime_equivalence_never_waives_nonruntime_identity_and_budget16(tmp_path):
    actual = dict(cache.ORIGINAL_RUNTIME, model_config_sha256='same-frozen-config',
                  first_fold_sha256='same-first-fold', input_manifest_sha256='same-input')
    expected = dict(actual, long_runner_code_sha256='new-runner', adapter_code_sha256='new-adapter')
    compatibility = dict(old_runtime_sources=cache.ORIGINAL_RUNTIME,
                         new_runtime_sources={'long_run194.py': 'new-runner', 'long_training_adapter.py': 'new-adapter'})
    cache.compatible_canary_identity(actual, expected, compatibility)
    for field in ('model_config_sha256', 'first_fold_sha256', 'input_manifest_sha256'):
        with pytest.raises(ValueError, match='CACHE_NONRUNTIME_IDENTITY_DRIFT'):
            cache.compatible_canary_identity(actual, dict(expected, **{field: 'drift'}), compatibility)
    with pytest.raises(ValueError, match='CACHE_OLD_IDENTITY_DRIFT'):
        cache.compatible_canary_identity(dict(actual, adapter_code_sha256='unapproved-old'), expected, compatibility)
    environment = {}
    assert configure_native_thread_budget(processes=16, threads_per_process=1,
                                         total_thread_budget=16, environ=environment)['effective_native_threads'] == 16
    selected = select_safe_fit_workers(requested_workers=16, threads_per_worker=1, total_thread_budget=16,
        canary_peak_rss_bytes=100, available_memory_bytes=2000, memory_safety_fraction=0.8)
    assert selected['actual_workers'] == 16
    with pytest.raises(ValueError, match='THREAD_BUDGET_INVALID'):
        configure_native_thread_budget(processes=17, threads_per_process=1, total_thread_budget=17, environ={})
    with pytest.raises(ValueError, match='FIT_CANARY_EXCEEDS_MEMORY_SAFETY_HEADROOM'):
        select_safe_fit_workers(requested_workers=16, threads_per_worker=1, total_thread_budget=16,
            canary_peak_rss_bytes=1000, available_memory_bytes=1100, memory_safety_fraction=0.8)
    def js(path, value):
        path.write_text(json.dumps(value))
        return dict(path=str(path), sha256=cache.sha(path))
    output = tmp_path / 'output'
    fold = output / 'fold_01'
    fold.mkdir(parents=True)
    freeze = js(output / 'RUN_FREEZE.json', {'identity': 'unchanged-predictive-identity'})
    sealed_file = js(fold / 'FOLD_RESULT.json', {'preserved': True})
    seal = js(fold / 'FOLD_MANIFEST.json', {'files': {'FOLD_RESULT.json': sealed_file['sha256']}})
    parent = dict(input_manifest_path='synthetic-manifest', input_manifest_sha256='synthetic-input-sha',
                  review_receipt_path='synthetic-current-review', review_receipt_sha256='synthetic-review-sha')
    original_canary = {'path': 'synthetic-original-canary', 'sha256': 'synthetic-original-runtime-sha'}
    parity = dict(rows=3, every_literal_cell_equal=True, every_X_Y_value_equal=True)
    cache_ref = js(tmp_path / 'cache.json', dict(predictive_sources=cache.PREDICTIVE_SOURCES,
        input_manifest=dict(path=parent['input_manifest_path'], sha256=parent['input_manifest_sha256']),
        input_review=dict(path=parent['review_receipt_path'], sha256=parent['review_receipt_sha256']),
        parity=parity, projection={'rows': 3}, original_freeze=freeze, original_fold_seal=seal,
        original_canary_runtime=original_canary,
        first_fold_replay=dict(saved_models_exact_prediction_parity=True, train_keys_exact_parity=True, refits=0)))
    sources = {name: cache.sha(Path(cache.__file__).with_name(name)) for name in
               ('long_run194.py', 'long_training_adapter.py', 'model_input_cache194.py')}
    receipt = dict(schema='V194_RUNTIME_CACHE_COMPATIBILITY_V1', status='PASS_RUNTIME_CACHE_EQUIVALENCE',
        maximum_claim='DIRECTION_ONLY', fit_count_delta=0, cache_manifest=cache_ref,
        original_canary_runtime=original_canary, input_manifest_path=parent['input_manifest_path'],
        input_manifest_sha256=parent['input_manifest_sha256'], input_review_path=parent['review_receipt_path'],
        input_review_sha256=parent['review_receipt_sha256'], old_runtime_sources=cache.ORIGINAL_RUNTIME,
        new_runtime_sources=sources, predictive_sources=cache.PREDICTIVE_SOURCES,
        cache_zero_fit_parity=parity, original_freeze=freeze, original_fold_seal=seal)
    cfg = dict(output_dir=str(output), input_cache=cache_ref, fit_canary_runtime=original_canary,
               runtime_compatibility=js(tmp_path / 'receipt.json', receipt))
    canary = {'runtime_budget': {'fit_canary_identity': cache.ORIGINAL_RUNTIME}}
    assert cache.verify_compatibility(cfg, parent, canary)['fit_count_delta'] == 0
    cfg['runtime_compatibility'] = js(tmp_path / 'unapproved.json', dict(receipt, status='PROPOSED'))
    with pytest.raises(ValueError, match='CACHE_COMPATIBILITY_NOT_PASS'):
        cache.verify_compatibility(cfg, parent, canary)
    cfg['runtime_compatibility'] = js(tmp_path / 'drift.json', dict(receipt, input_manifest_sha256='drift'))
    with pytest.raises(ValueError, match='CACHE_COMPATIBILITY_INPUT_DRIFT'):
        cache.verify_compatibility(cfg, parent, canary)


def test_cached_waves_use_unique_unfinished_folds_and_real_profile_basis(tmp_path, monkeypatch):
    first = tmp_path / 'fold_01'
    first.mkdir()
    (first / 'sealed.txt').write_text('must not refit or rewrite')
    submitted, sizes, checkpoints = [], [], []
    monkeypatch.setattr(model, 'FIT_COUNTS', {key: 0 for key in model.FIT_COUNTS})
    monkeypatch.setattr(model, 'fit_model', lambda *args, **kwargs: pytest.fail('Unexpected fit in zero-fit fixture'))

    class Executor:
        def __init__(self, *, max_workers, **kwargs):
            sizes.append(max_workers)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def submit(self, function, split, temporary):
            submitted.append(split['id'])
            folder = Path(temporary)
            folder.mkdir(parents=True)
            (folder / 'FOLD_RESULT.json').write_text('{}')
            future = Future()
            future.set_result(dict(split_id=split['id'], fit_counts={
                'real_fit_entered': 2, 'real_fit_returned': 2,
                'synthetic_fit_entered': 0, 'synthetic_fit_returned': 0},
                profile=dict(training_rows=1, runtime={'process_peak_rss_bytes': 100})))
            return future

    monkeypatch.setattr(runner, 'ProcessPoolExecutor', Executor)
    monkeypatch.setattr(runner, 'runtime_snapshot', lambda: {'available_memory_bytes': 1000000})
    monkeypatch.setattr(cache, 'pressure_snapshot', lambda: dict(status='OBSERVED', swapins=0, swapouts=0))
    monkeypatch.setattr(runner, 'configure_native_thread_budget', lambda **kwargs: dict(
        processes=kwargs['processes'], threads_per_process=1, effective_native_threads=kwargs['processes']))
    ticks = iter(range(100))
    monkeypatch.setattr(runner.time, 'monotonic', lambda: next(ticks))
    pending = [(dict(id=f'fold_{i:02d}', train_target_dates=['2000-01-01']), tmp_path / '_incomplete' / f'fold_{i:02d}')
               for i in range(2, 43)]
    config = dict(output_dir=str(tmp_path), resource_ramp=[1, 4, 8, 12, 16], input_cache={'path': 'synthetic'},
                  runtime_budget={'memory_safety_fraction': 0.8})
    runner._execute_cached_fold_waves(config, pending, frozen={'identity': {}}, model_config={},
        checkpoint=lambda name, path: checkpoints.append(name), requested_workers=16,
        threads_per_worker=1, total_thread_budget=16, canary={'peak_rss_bytes': 100}, actual_budget={},
        set_runtime_budget=lambda budget: None,
        cache_manifest={'projection': {'row_counts_by_target_date': {'2000-01-01': 1}}})
    assert sizes == [1, 4, 8, 12, 16]
    assert len(submitted) == len(set(submitted)) == 41 and 'fold_01' not in submitted
    assert (first / 'sealed.txt').read_text() == 'must not refit or rewrite'
    start = cache.load(tmp_path / '_resource_waves/WAVE_0002_START.json')
    assert start['runtime_budget']['fit_worker_selection']['profile_basis'] == 'MEASURED_CACHE_FOLD_WORKERS'
    assert len([name for name in checkpoints if name.startswith('RESOURCE_WAVE_')]) == 5
