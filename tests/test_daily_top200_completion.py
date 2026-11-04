"""A missing old bootstrap panel must not suppress a bound daily ranking."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def daily_owner(tmp_path, monkeypatch):
    from ops import research_panel_daily_product as product
    from ops import research_panel_top200 as owner
    from ops import sync_stock_history_completion as sync
    from ops import a_share_daily_sync as source
    from infrastructure import research_classification_view as classification

    root = tmp_path / 'daily'
    receipts = tmp_path / 'receipts'
    day = '20261104'
    identity = dict(generation='a' * 64, input_sha256='b' * 64, asof=int(day))
    context = SimpleNamespace(target=int(day), generation=identity['generation'], identity=identity, panel=tmp_path/'panel.parquet',
        calendars={'SH': list(range(20260001, 20260062))}, unchanged=lambda: None)
    row = dict(symbol='000001.SZ', groups='original|nav_smallk')
    numeric = product.save(root / 'product.json', dict(source_identity=identity, rows=[row],
        group_counts=dict(original=1, nav_smallk=1, nav_pullback=0, nav_breakout=0)))
    manifest = product.save(root / 'manifest.json', dict(artifact=numeric))
    product.save(root / 'index.json', dict(dates={day: manifest}))
    product.save(root / 'events/latest.json', dict(data_date=day, source_generation=context.generation,
        manifest=manifest, artifact=numeric))
    official = product.save(receipts / 'a_sync_authority/official_daily' / day / 'input.json', {})
    trial = tmp_path / 'trial'
    product.save(trial / 'SOURCE_MANIFEST.json', [])
    product.save(trial / 'RUN_RECEIPT.json', {})
    lock = tmp_path / 'A_LONG.lock'
    lock.touch()
    monkeypatch.setattr(sync, 'DEFAULT_OWNER_LOCK', lock)
    # No inherited scheduler lease in private tests. The deployed publisher
    # provides this helper; the historical source baseline predates it.
    if not hasattr(sync, '_inherited_owner_duplicate'):
        monkeypatch.setattr(sync, '_inherited_owner_duplicate', lambda *args: None, raising=False)
    monkeypatch.setattr(product, 'SourceContext', lambda *args: context)
    monkeypatch.delenv('V4_WORKBENCH_STATISTICS_ROOT', raising=False)
    monkeypatch.delenv('V4_SCHEDULER_LANE_FD', raising=False)

    class Store:
        def __init__(self, path): pass
        def catalog(self, market):
            return dict(rows=[dict(symbol='000001.SZ', name='甲', reference_date='20261104')]
                if market == 'A_SHARE' else [], source_ref={})
        def version(self): return 'test-classification'
        def close(self): pass

    monkeypatch.setattr(classification, 'ReceivedClassificationStore', Store)
    quote = dict(symbol='000001.SZ', name='甲', open=10, high=11, low=9, close=11,
        change_pct=10, eligible_for_daily_gain_rank=True, amount_cny=100, volume_shares=10)
    monkeypatch.setattr(owner, 'official_quotes', lambda *args: (
        {'000001.SZ': quote.copy()}, SimpleNamespace(previous=20260061, package_ref=official)))
    # The deployed daily source supplies these runtime dependencies; this
    # isolated continuation test supplies empty received dispositions.
    monkeypatch.setattr(source, '_daily_source_policy_additions', lambda: {}, raising=False)
    monkeypatch.setattr(source, '_load_verified_lifecycle_facts', lambda: {}, raising=False)
    computations = []
    def histories(*args):
        computations.append('bounded_structure_window')
        return {}
    monkeypatch.setattr(owner, 'structure_histories', histories)
    def frozen(name, environment, trial):
        if name == 'feature': return lambda symbol: dict(structure='UNKNOWN')
        return lambda kind, members, axis, label: dict(label=label, top200_count=len(members), amount_cny=100)
    monkeypatch.setattr(owner, 'frozen_function', frozen)
    real_build = owner.build
    monkeypatch.setattr(owner, 'build', lambda *args: real_build(*args, trial=trial))

    # Reproduce the actual failure at the old-generation panel.stat(), rather
    # than replacing it with an arbitrary exception from a mock.
    old_snapshot = product.save(tmp_path / 'old/adjustment_snapshot.json', {})
    old_identity = dict(generation='old', input_sha256='old-input', snapshot=old_snapshot,
        selector_artifact_sha256='c' * 64, asof=20261029)
    missing_panel = tmp_path / 'old/selector_ready_current_to_20261029.parquet'
    product.save(tmp_path / 'old/candidate_receipt.json', dict(generation_id='old',
        input_sha256='old-input', adjustment_snapshot=old_snapshot,
        candidate_sha256={'selector': 'c' * 64}, candidates={'selector': str(missing_panel)}))
    def history(*args):
        return owner._prior_generation_proofs(context,
            {'000001.SZ': {'evaluations': {'20261029': {'source_identity': old_identity}}}}, {})
    monkeypatch.setattr(owner, 'run_incremental_history', history)
    monkeypatch.setattr(owner, 'publish_current_history_view',
        lambda *args: pytest.fail('Incomplete history cannot be published'))
    monkeypatch.setattr(product, 'compute_stock', lambda *args, **kwargs: pytest.fail('No formula work'))
    return SimpleNamespace(owner=owner, product=product, root=root, receipts=receipts, context=context,
        numeric=numeric, manifest=manifest, computations=computations, missing_panel=missing_panel,
        run=lambda: owner.complete_daily_derivatives(tmp_path, int(day), root, receipts, tmp_path))


def test_missing_prior_panel_keeps_gap_and_publishes_bound_top200_with_four_groups(daily_owner):
    f = daily_owner
    result = f.run()
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['history']['status'] == 'CANNOT_CONFIRM'
    assert str(f.missing_panel) in result['history']['reason']
    assert result['history_view'] is None
    assert result['top200']['status'] in {'PUBLISHED_TOP200', 'PUBLISHED_HISTORY_SYNC'}
    index = json.loads((f.root / 'index.json').read_bytes())
    top = f.owner.load(index['top200']['20261104'])
    assert top['numeric_manifest'] == f.manifest
    assert top['source_generation'] == f.context.generation
    groups = top['comparison']['same_day']['groups']
    assert set(groups) == set(f.owner.GROUPS)
    assert groups['original']['hits'] == groups['nav_smallk']['hits'] == 1
    assert groups['nav_pullback']['hits'] == groups['nav_breakout']['hits'] == 0
    saved = f.owner.load(index['attempts']['20261104'])
    assert saved['history'] == result['history'] and saved['status'] == 'CANNOT_CONFIRM'
    assert all(top[key] == value for key, value in f.product.FLAGS.items())


def test_repeat_reuses_materialized_top200_without_structure_or_formula_work(daily_owner):
    f = daily_owner
    f.run()
    before = json.loads((f.root / 'index.json').read_bytes())['top200']['20261104']
    f.computations.clear()
    again = f.run()
    assert again['top200'] == dict(status='REUSED', artifact=before)
    assert again['computation']['computed_structures'] == 0
    assert f.computations == []
    assert again['history']['status'] == 'CANNOT_CONFIRM'


@pytest.mark.parametrize('mutation', ['identity', 'missing_date', 'event_manifest', 'event_date'])
def test_invalid_same_day_binding_never_publishes(daily_owner, mutation):
    f = daily_owner
    index_path = f.root / 'index.json'
    if mutation == 'identity':
        f.context.identity = {**f.context.identity, 'input_sha256': 'changed'}
    elif mutation == 'missing_date':
        f.product.save(index_path, {'dates': {}})
    else:
        event = json.loads((f.root / 'events/latest.json').read_bytes())
        if mutation == 'event_manifest': event['manifest'] = {'path': 'wrong', 'sha256': '0' * 64}
        else: event['data_date'] = '20261103'
        f.product.save(f.root / 'events/latest.json', event)
    before_event = (f.root / 'events/latest.json').read_bytes()
    result = f.run()
    assert result['status'] == 'CANNOT_CONFIRM' and 'error' in result
    assert '20261104' not in json.loads(index_path.read_bytes()).get('top200', {})
    assert (f.root / 'events/latest.json').read_bytes() == before_event


def test_upstream_failure_still_prevents_all_derivative_work(daily_owner, monkeypatch):
    f = daily_owner
    monkeypatch.setattr(f.owner, 'build', lambda *args: pytest.fail('Upstream failure must stop Top200'))
    result = f.owner.complete_daily_derivatives(f.root, 20261104, f.root, f.receipts, f.root,
        upstream_failure={'status': 'FAILED'})
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['error'] == 'UPSTREAM_DAILY_SOURCE_FAILED:FAILED'
    assert not json.loads((f.root / 'index.json').read_bytes()).get('top200')


def test_partial_history_result_remains_unconfirmed_while_top200_continues(daily_owner, monkeypatch):
    f = daily_owner
    monkeypatch.setattr(f.owner, 'run_incremental_history', lambda *args: {'status': 'RUNNING', 'remaining': 1})
    result = f.run()
    assert result['status'] == 'CANNOT_CONFIRM'
    assert result['history'] == dict(status='CANNOT_CONFIRM', reason='DAILY_HISTORY_PARTIAL')
    assert result['top200']['status'] in {'PUBLISHED_TOP200', 'PUBLISHED_HISTORY_SYNC'}


def test_complete_history_retains_success_and_f10_continuation(daily_owner, monkeypatch):
    from ops import research_panel_f10 as f10
    f = daily_owner
    monkeypatch.setattr(f.owner, 'run_incremental_history', lambda *args: {'status': 'COMPLETE_NO_HISTORY_GAPS'})
    monkeypatch.setattr(f.owner, 'publish_current_history_view', lambda *args: {'status': 'NO_NEW_COMPLETION'})
    monkeypatch.setattr(f10, 'complete_f10', lambda *args, **kwargs: {'status': 'COMPLETE', 'receipt': {}})
    monkeypatch.setattr(f10, 'publish_f10_completion', lambda *args: {'status': 'PUBLISHED'})
    result = f.run()
    assert result['status'] == 'COMPLETE_DESCRIPTIVE_NONPIT'
    assert result['history_view']['status'] == 'NO_NEW_COMPLETION'
    assert result['top200']['status'] in {'PUBLISHED_TOP200', 'PUBLISHED_HISTORY_SYNC'}
    assert result['f10']['publication']['status'] == 'PUBLISHED'
