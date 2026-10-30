"""Missing-only scheduling, original math call locking and bounded drain."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from ops import research_panel_daily_product as product
from ops import research_daily_product_parallel as parallel


def observed(cores=18, total=128, free=120, rss=3):
    return dict(cpu_cores=cores, physical_memory_bytes=total * parallel.GIB, available_bytes=free * parallel.GIB,
                cumulative_rss_bytes=rss * parallel.GIB, memory_pressure_free_percent=94)


@pytest.fixture
def context(tmp_path):
    return SimpleNamespace(data_root=tmp_path / 'data', root=tmp_path / 'output', target=20261030,
        scope=['000016.SZ', '002003.SZ', '600025.SH'], identity={'generation': 'same_original_generation'},
        generation='same_original_generation', config_ref={'path': '/same/original/config', 'sha256': 'unchanged'}, unchanged=lambda: None)


def manifest_fixture(tmp_path, monkeypatch):
    app = Path(product.__file__).resolve().parents[1]
    entries = [dict(path=str(Path(m.__file__).resolve().relative_to(app)), sha256=product.sha(m.__file__)) for m in (product, parallel)]
    ref = product.save(tmp_path / 'manifest.json', dict(app_root=str(app), application_inventory={'entries': entries}))
    monkeypatch.setenv('V4_RELEASE_MANIFEST_PATH', ref['path'])
    monkeypatch.setenv('V4_RELEASE_MANIFEST_SHA256', ref['sha256'])


def test_exact_main_dependency_binding_rejects_adapter_drift(tmp_path, monkeypatch):
    manifest_fixture(tmp_path, monkeypatch)
    assert len(parallel.bound_main_sources()['code']) == 2
    original = product.sha
    monkeypatch.setattr(product, 'sha', lambda p: 'drift' if Path(p).resolve() == Path(parallel.__file__).resolve() else original(p))
    with pytest.raises(ValueError, match='MAIN_SOURCE_BINDING'):
        parallel.bound_main_sources()


def test_resources_follow_machine_memory_and_missing_count():
    plan = parallel.resource_plan(observed(), 5808)
    assert plan['workers'] == 14 and plan['max_pending'] == 28
    assert plan['memory_guard_bytes'] == 64 * parallel.GIB and plan['reserve_available_bytes'] == 24 * parallel.GIB
    assert parallel.resource_plan(observed(cores=8), 5808)['workers'] == 4
    assert parallel.resource_plan(observed(free=34), 5808)['workers'] == 1
    assert parallel.resource_plan(observed(), 3)['workers'] == 3


def test_prefill_reuses_same_namespace_and_only_missing(context, tmp_path, monkeypatch):
    manifest_fixture(tmp_path, monkeypatch)
    selected = sorted(context.scope)
    parts = parallel.checkpoint_parts(context, selected)
    existing = parts / (selected[0] + '.json')
    product.save(existing, dict(symbol=selected[0], data_date='20261030', preserved='completed'))
    before = existing.read_bytes()
    monkeypatch.setattr(parallel, 'memory_state', observed)
    calls = []
    monkeypatch.setattr(parallel, 'run_pending', lambda *args, **kw: calls.append((args, kw)) or {'chart_gaps': {}})
    parallel.prefill_missing(context, parts, selected, original_charts=True)
    assert calls[0][0][3] == selected[1:] and calls[0][0][1] == parts
    assert calls[0][1]['original_charts'] is True and existing.read_bytes() == before
    with pytest.raises(ValueError, match='NAMESPACE_CONFLICT'):
        parallel.prefill_missing(context, parts.parent / 'different', selected, original_charts=True)


def test_calling_original_statistics_is_serialized_without_changing_math(tmp_path, monkeypatch):
    store = tmp_path / 'isolated.sqlite3'
    store.write_bytes(b'isolated test store')
    monkeypatch.setenv('V4_RESEARCH_EVENT_CASE_CACHE', str(store))
    shared = threading.Lock()
    counts = {'active': 0, 'peak': 0, 'calls': 0}
    def original_statistics(*args):
        assert shared.locked()
        counts['active'] += 1
        counts['peak'] = max(counts['peak'], counts['active'])
        counts['calls'] += 1
        time.sleep(.01)
        counts['active'] -= 1
        return {}, {}, []
    monkeypatch.setattr(product, 'cached_daily_statistics', original_statistics)
    bars = [dict(trade_date=day, open='1', high='1', low='1', close='1', vol='1') for day in (20261029, 20261030)]
    context = SimpleNamespace(root=tmp_path / 'output', target=20261030, config={'formula': {'sha256': 'same'}},
        calendars={'SZ': [20261029, 20261030]}, generation='same', identity={'basis': {}, 'input_sha256': 'same'}, label_results={}, _event_case_cache_lock=shared,
        read=lambda symbol: (bars, None), qualify=lambda symbol: {'status': 'UNKNOWN'})
    evaluate = lambda **kw: dict(groups={g: {'status': 'UNKNOWN'} for g in product.GROUPS}, risk={'status': 'UNKNOWN'})
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda code: product.compute_stock(context, code, evaluate=evaluate), ['000001.SZ', '000002.SZ', '000003.SZ']))
    assert len(results) == counts['calls'] == 3 and counts['peak'] == 1


def test_worker_uses_original_compute_capture_and_preserves_completed(context, tmp_path, monkeypatch):
    parts = parallel.checkpoint_parts(context, sorted(context.scope))
    monkeypatch.setattr(parallel, '_CONTEXT', context)
    monkeypatch.setattr(parallel, '_PARTS', parts)
    monkeypatch.setattr(parallel, '_CHARTS', True)
    calls = []
    from ops import render_original_formula_projection as charts
    monkeypatch.setattr(charts, 'retain_owner_result', lambda *a: calls.append(('capture', a[2])))
    def compute(ctx, symbol, *, history_dates, chart_capture):
        assert history_dates == ()
        calls.append(('compute', symbol))
        chart_capture(symbol, [], {'original': True})
        return dict(symbol=symbol, data_date='20261030'), {'retained': True}, tmp_path / 'history' / (symbol + '.json')
    monkeypatch.setattr(product, 'compute_stock', compute)
    result = parallel.checkpoint('002003.SZ')
    before = Path(result['ref']['path']).read_bytes()
    parallel.checkpoint('002003.SZ')
    assert calls == [('compute', '002003.SZ'), ('capture', '002003.SZ')]
    assert Path(result['ref']['path']).read_bytes() == before
    def fail(*a, **kw):
        raise sqlite3.OperationalError('original DB timeout')
    monkeypatch.setattr(product, 'compute_stock', fail)
    with pytest.raises(sqlite3.OperationalError):
        parallel.checkpoint('600025.SH')
    assert not (parts / '600025.SH.json').exists()


@pytest.mark.parametrize('failure', ['resource', 'worker', None])
def test_stop_submissions_and_drain_preserves_completed_work(context, monkeypatch, failure):
    selected = sorted(context.scope) + ['600026.SH', '600027.SH']
    context.scope = selected
    parts = parallel.checkpoint_parts(context, selected)
    completed = []
    def task(symbol):
        if failure == 'worker' and symbol == selected[0]:
            raise RuntimeError('original worker failure')
        time.sleep(.02)
        completed.append(symbol)
        ref = product.save(parts / (symbol + '.json'), dict(symbol=symbol, data_date='20261030'))
        return dict(symbol=symbol, ref=ref, chart_gaps={})
    class Pool(ThreadPoolExecutor):
        def __init__(self, *, max_workers, mp_context, initializer, initargs):
            assert mp_context.get_start_method() == 'spawn'
            assert initargs[-2] is not None
            super().__init__(max_workers=max_workers)
    monkeypatch.setattr(parallel, 'ProcessPoolExecutor', Pool)
    monkeypatch.setattr(parallel, 'checkpoint', task)
    monkeypatch.setattr(parallel, 'memory_state', lambda: observed(free=0) if failure == 'resource' else observed())
    resources = parallel.resource_plan(observed(), len(selected))
    resources.update(workers=2, max_pending=2)
    if failure:
        with pytest.raises((RuntimeError, MemoryError)):
            parallel.run_pending(context, parts, selected, selected, original_charts=True, resources=resources, sources={})
        assert set(completed) <= set(selected[:2]) and all((parts / (s + '.json')).is_file() for s in completed)
        assert json.loads(next(parts.glob('parallel_run_*.json')).read_text())['status'] == 'FAILED_DRAINED'
    else:
        result = parallel.run_pending(context, parts, selected, selected, original_charts=True, resources=resources, sources={})
        assert set(completed) == set(selected) and product.checked(result['record']).is_file()
    assert not (context.root / 'index.json').exists() and not (context.root / 'events/latest.json').exists()
