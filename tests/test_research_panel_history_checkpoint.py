import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import research_daily_product_parallel as parallel
from ops import research_panel_daily_product as owner
from ops import research_panel_history_checkpoint as history


SYMBOL = '600809.SH'
DAY1, DAY2, DAY3 = 20261110, 20261111, 20261112


def cache(day, values, *, rules='rules'):
    evaluations = {str(date): {'groups': dict.fromkeys(owner.GROUPS, state)} for date, state in values.items()}
    return dict(rule_sha256='rule', rules_signature=rules, source_identity=dict(asof=day),
                evaluations=evaluations, prefix_sha256='example-prefix',
                coverage=dict(evaluated_dates=sorted(values), evaluated_count=len(values)))


def physical(ref):
    return json.loads(Path(ref['path']).read_bytes())


def test_dated_sparse_append_and_revision_keep_previous_refs_and_seed(tmp_path):
    path = tmp_path / 'checkpoint.json'
    before = cache(DAY1, {DAY1: 'TRUE'})
    legacy_ref = owner.save(path, before)
    original_bytes = path.read_bytes()
    append = cache(DAY2, {DAY1: 'TRUE', DAY2: 'UNKNOWN'})
    first_ref = history.write_checkpoint(path, append, base_ref=legacy_ref, base_cache=before,
                                         expected_ref=legacy_ref, retain_base=True)
    first_delta = physical(first_ref)
    assert set(first_delta['upserts']) == {str(DAY2)}
    assert 'evaluated_dates' not in first_delta['metadata']['coverage']
    retained = Path(first_delta['base']['path'])
    assert retained.stat().st_ino == path.stat().st_ino and path.read_bytes() == original_bytes
    assert history.read_checkpoint(path, asof=DAY1) == before
    assert history.load_checkpoint_ref(first_ref) == append
    revised = cache(DAY2, {DAY1: 'FALSE', DAY2: 'UNKNOWN'})
    second_ref = history.write_checkpoint(path, revised, base_ref=first_ref, base_cache=append, expected_ref=first_ref)
    assert set(physical(second_ref)['upserts']) == {str(DAY1)}
    assert history.load_checkpoint_ref(first_ref) == append
    assert history.read_checkpoint(path) == revised
    assert history.write_checkpoint(path, revised, base_ref=second_ref, base_cache=revised, expected_ref=second_ref) == second_ref
    assert len(list(tmp_path.glob('delta-*.json'))) == 2
    # An older binary replaces its original file by rename. Pinned migrated
    # history still resolves through the retained inode.
    owner.save(path, cache(DAY3, {DAY3: 'FALSE'}))
    assert retained.read_bytes() == original_bytes and history.load_checkpoint_ref(second_ref) == revised
    with pytest.raises(history.HistoryCheckpointError, match='LEGACY_REPLACED'):
        history.read_checkpoint(path)
    with pytest.raises(history.HistoryCheckpointError, match='LEGACY_REPLACED'):
        history.write_checkpoint(path, cache(DAY3, {DAY3: 'FALSE'}), expected_ref=second_ref)


def test_invalidated_history_is_not_referenced_or_resurrected(tmp_path):
    path = tmp_path / 'checkpoint.json'
    old = cache(DAY1, {DAY1: 'TRUE'})
    first = history.write_checkpoint(path, old, expected_ref=None)
    new = cache(DAY2, {DAY2: 'UNKNOWN'})
    new['invalidated_previous_source'] = True
    second = history.write_checkpoint(path, new, base_ref=first, base_cache=old, expected_ref=first)
    assert physical(second)['base'] is None
    assert set(physical(second)['upserts']) == {str(DAY2)}
    assert history.read_checkpoint(path) == new
    assert history.read_checkpoint(path, asof=DAY1) == old


def test_removals_and_backdated_head_do_not_override_newer_view(tmp_path):
    path = tmp_path / 'checkpoint.json'
    initial = cache(DAY2, {DAY1: 'TRUE', DAY2: 'TRUE'})
    second_day = history.write_checkpoint(path, initial, expected_ref=None)
    later = cache(DAY3, {DAY2: 'TRUE', DAY3: 'FALSE'})
    third_day = history.write_checkpoint(path, later, base_ref=second_day, expected_ref=second_day)
    assert physical(third_day)['removed'] == [str(DAY1)]
    old = cache(DAY1, {DAY1: 'UNKNOWN'})
    history.write_checkpoint(path, old, expected_ref=None)
    assert history.read_checkpoint(path, asof=DAY1) == old
    assert history.read_checkpoint(path, asof=DAY2) == initial
    assert history.read_checkpoint(path) == later
    with pytest.raises(history.HistoryCheckpointError, match='FUTURE_BASE'):
        history.write_checkpoint(path, old, base_ref=third_day)


def test_failed_head_write_reuses_orphan_delta_on_retry(tmp_path, monkeypatch):
    path = tmp_path / 'checkpoint.json'
    first = history.write_checkpoint(path, cache(DAY1, {DAY1: 'TRUE'}), expected_ref=None)
    later = cache(DAY2, {DAY1: 'TRUE', DAY2: 'FALSE'})
    real_publish = history._publish

    def fail_head(destination, raw):
        if destination.name.startswith('head-'):
            raise OSError('simulated head failure')
        return real_publish(destination, raw)

    with monkeypatch.context() as patch:
        patch.setattr(history, '_publish', fail_head)
        with pytest.raises(history.HistoryCheckpointError, match='WRITE_FAILED'):
            history.write_checkpoint(path, later, base_ref=first, expected_ref=first)
    assert history.checkpoint_reference(path) == first
    orphan, = set(tmp_path.glob('delta-*.json')) - {Path(first['path'])}
    before = orphan.stat()
    second = history.write_checkpoint(path, later, base_ref=first, expected_ref=first)
    assert orphan == Path(second['path']) and orphan.stat() == before
    assert history.read_checkpoint(path) == later


def test_concurrent_same_day_writers_cas_and_idempotent_retry(tmp_path):
    path = tmp_path / 'checkpoint.json'
    before = cache(DAY1, {DAY1: 'TRUE'})
    first = history.write_checkpoint(path, before, expected_ref=None)
    next_a = cache(DAY2, {DAY1: 'TRUE', DAY2: 'TRUE'})
    next_b = cache(DAY2, {DAY1: 'TRUE', DAY2: 'FALSE'})

    def write(next_cache):
        try:
            return history.write_checkpoint(path, next_cache, base_ref=first, base_cache=before, expected_ref=first)
        except history.HistoryCheckpointError as error:
            assert 'CAS_MOVED' in str(error)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.map(write, [next_a, next_b])
    assert (a is None) != (b is None)
    assert write(next_a if a else next_b) == (a or b)
    assert history.read_checkpoint(path) == (next_a if a else next_b)


def test_missing_or_bad_dependency_stops_read_instead_of_legacy_fallback(tmp_path):
    base = tmp_path / 'accepted' / 'checkpoint.json'
    prior = cache(DAY1, {DAY1: 'TRUE'})
    base_ref = owner.save(base, prior)
    path = tmp_path / 'new' / 'checkpoint.json'
    owner.save(path, prior)
    next_cache = cache(DAY2, {DAY1: 'TRUE', DAY2: 'FALSE'})
    ref = history.write_checkpoint(path, next_cache, base_ref=base_ref)
    assert physical(ref)['base'] == base_ref
    base.write_bytes(b'{}')
    with pytest.raises(history.HistoryCheckpointError, match='SHA_DRIFT'):
        history.read_checkpoint(path)
    base.unlink()
    with pytest.raises(history.HistoryCheckpointError, match='UNREADABLE'):
        history.read_checkpoint(path)


def test_accepted_result_requires_exact_index_identity_and_coverage(tmp_path):
    previous = cache(DAY1, {DAY1: 'TRUE'}, rules=owner.digest({}))
    previous['source_identity'].update(generation='old', input_sha256='input', historical_PIT=False)
    previous['coverage'].update(requested_end=DAY1, historical_PIT=False, known_full_history=True, missing=[])
    base_ref = owner.save(tmp_path / 'accepted' / 'checkpoint.json', previous)
    contract = {'path': '/proof/contract.json', 'sha256': 'a'*64}
    result_ref = owner.save(tmp_path / 'RESULT.json', dict(status='COMPLETE_DESCRIPTIVE_NONPIT', symbol=SYMBOL,
        historical_PIT=False, history_cache=base_ref, evaluated_dates=1, available_dates=1, remaining_dates=[],
        contract=contract, **owner.FLAGS))
    context = SimpleNamespace(target=DAY2, config={}, label_results={SYMBOL: result_ref},
                              label_bindings={SYMBOL: (DAY1, 'old', 'input', contract)})
    inputs = {}
    assert owner.accepted_label_cache(context, SYMBOL, 'rule', {'evaluations': {}}, checkpoint_input=inputs) == previous
    assert inputs['base_ref'] == base_ref and not inputs['retain_base']
    assert set(inputs['base_dependencies']) == {base_ref['path']}
    with pytest.raises(ValueError, match='RULE_IDENTITY_CONFLICT') as incompatible:
        owner.accepted_label_cache(context, SYMBOL, 'new-rule', {'evaluations': {}})
    assert not isinstance(incompatible.value, history.HistoryCheckpointError)
    context.label_bindings[SYMBOL] = (DAY2, 'old', 'input', contract)
    with pytest.raises(history.HistoryCheckpointError, match='DATE_OR_COVERAGE'):
        owner.accepted_label_cache(context, SYMBOL, 'rule', {'evaluations': {}})


def test_event_case_lineage_tracks_accepted_result_identity_without_rewriting_cache(tmp_path):
    rule_sha = 'f' * 64
    config = {'frozen_rule_fixture': 'main-a-share-event-return'}
    rules_signature = owner.digest(config)
    previous = cache(DAY1, {DAY1: 'TRUE'}, rules=rules_signature)
    previous['rule_sha256'] = rule_sha
    previous['source_identity'].update(generation='frozen-generation', input_sha256='frozen-input',
                                       asof=DAY1, historical_PIT=False)
    previous['coverage'].update(requested_end=DAY1, historical_PIT=False, known_full_history=True, missing=[])
    checkpoint_path = tmp_path / 'accepted' / 'checkpoint.json'
    checkpoint_ref = owner.save(checkpoint_path, previous)
    contract = {'path': str(tmp_path / 'frozen-manifest.json'), 'sha256': 'a' * 64}
    binding = (DAY1, 'frozen-generation', 'frozen-input', contract)
    refs = []
    for result_id in ('accepted-a', 'accepted-b'):
        refs.append(owner.save(tmp_path / f'{result_id}.json', dict(
            status='COMPLETE_DESCRIPTIVE_NONPIT', symbol=SYMBOL, historical_PIT=False,
            history_cache=checkpoint_ref, evaluated_dates=1, available_dates=1, remaining_dates=[],
            contract=contract, accepted_result_id=result_id, **owner.FLAGS)))
    original_checkpoint = checkpoint_path.read_bytes()

    def accepted_cases(result_ref):
        context = SimpleNamespace(target=DAY2, config=config, label_results={SYMBOL: result_ref},
                                  label_bindings={SYMBOL: binding})
        local = history.load_checkpoint_ref(checkpoint_ref)
        candidate = {}
        accepted = owner.accepted_label_cache(context, SYMBOL, rule_sha, local,
            checkpoint_input={'base_ref': checkpoint_ref}, lineage_out=candidate)
        assert accepted is local
        lineage = owner.contributing_label_lineage(candidate, local['evaluations'],
            accepted['evaluations'], target=DAY2)
        groups = {'original': {'d2': {'cases': [
            {'event_date': owner.iso(DAY1), 'target_date': owner.iso(DAY2), 'return_pct': 2.0},
            {'event_date': owner.iso(DAY2), 'target_date': owner.iso(DAY3), 'return_pct': 3.0},
        ]}}}
        shard = {'symbol': SYMBOL, 'numeric_manifest': contract, 'groups': groups,
                 'accepted_label_lineage': lineage}
        return accepted, candidate, lineage, shard

    accepted_a, candidate_a, lineage_a, cases_a = accepted_cases(refs[0])
    accepted_b, candidate_b, lineage_b, cases_b = accepted_cases(refs[1])
    assert refs[0]['sha256'] != refs[1]['sha256']
    assert accepted_a == accepted_b == previous
    assert candidate_a['history_checkpoint_ref'] == candidate_b['history_checkpoint_ref'] == checkpoint_ref
    assert candidate_a['label_result_ref'] == refs[0]
    assert candidate_b['label_result_ref'] == refs[1]
    assert candidate_a['rule_identity'] == candidate_b['rule_identity'] == {
        'rule_sha256': rule_sha, 'rules_signature': rules_signature,
    }
    assert candidate_a['historical_asof'] == candidate_b['historical_asof'] == DAY1
    assert lineage_a['label_result_ref'] == refs[0]
    assert lineage_b['label_result_ref'] == refs[1]
    assert lineage_a['history_checkpoint_ref'] == lineage_b['history_checkpoint_ref'] == checkpoint_ref
    assert lineage_a['result_contract'] == contract
    assert lineage_a['historical_asof'] == DAY1
    assert lineage_a['rule_identity'] == lineage_b['rule_identity']
    assert lineage_a['group_event_dates']['original'] == lineage_b['group_event_dates']['original'] == [owner.iso(DAY1)]
    assert cases_a['groups'] == cases_b['groups']
    assert all('label_lineage' not in case for case in cases_b['groups']['original']['d2']['cases'])
    invalidated = owner.contributing_label_lineage(candidate_b, accepted_b['evaluations'],
        {str(DAY2): {'groups': dict.fromkeys(owner.GROUPS, 'TRUE')}}, target=DAY2)
    assert invalidated == {}
    assert checkpoint_path.read_bytes() == original_checkpoint


def test_compute_stock_binds_only_surviving_accepted_history_to_event_cases(tmp_path, monkeypatch):
    import sys
    import types

    symbol = SYMBOL
    target = DAY2
    bars = [
        {'trade_date': DAY1, 'open': 10.0, 'high': 10.0, 'low': 10.0, 'close': 10.0, 'volume': 100.0},
        {'trade_date': DAY2, 'open': 11.0, 'high': 11.0, 'low': 11.0, 'close': 11.0, 'volume': 110.0},
    ]
    config = {'formula': {'sha256': 'c' * 64}, 'frozen_rule_fixture': 'main-a-share-event-return'}
    fixture_root = tmp_path / 'frozen-rule-source'
    rule_path = fixture_root / 'domains' / 'research_daily_product.py'
    rule_path.parent.mkdir(parents=True)
    rule_path.write_bytes(b'frozen main a-share event return rule fixture\n')
    monkeypatch.setattr(owner, '__file__', str(fixture_root / 'ops' / 'research_panel_daily_product.py'))
    rule_sha = owner.sha(rule_path)
    rules_signature = owner.digest(config)
    previous = cache(DAY1, {DAY1: 'TRUE'}, rules=rules_signature)
    previous.update(rule_sha256=rule_sha, prefix_sha256=owner.digest(bars[:1]))
    previous['source_identity'].update(generation='accepted-generation', input_sha256='accepted-input',
                                       asof=DAY1, historical_PIT=False)
    previous['coverage'].update(requested_end=DAY1, historical_PIT=False, known_full_history=True, missing=[])
    checkpoint_ref = owner.save(tmp_path / 'accepted' / 'checkpoint.json', previous)
    contract = {'path': str(tmp_path / 'frozen-manifest.json'), 'sha256': 'd' * 64}
    result_refs = [owner.save(tmp_path / f'accepted-{suffix}.json', dict(
        status='COMPLETE_DESCRIPTIVE_NONPIT', symbol=symbol, historical_PIT=False,
        history_cache=checkpoint_ref, evaluated_dates=1, available_dates=1, remaining_dates=[],
        contract=contract, accepted_result_id=suffix, **owner.FLAGS)) for suffix in ('a', 'b')]
    checkpoint_bytes = Path(checkpoint_ref['path']).read_bytes()
    event_cache_path = tmp_path / 'existing-event-cache.sqlite'
    event_cache_path.write_bytes(b'fixture placeholder; compute is intercepted')
    monkeypatch.setenv('V4_RESEARCH_EVENT_CASE_CACHE', str(event_cache_path))
    domains_package = types.ModuleType('domains')
    domains_package.__path__ = []
    monkeypatch.setitem(sys.modules, 'domains', domains_package)
    statistics_module = types.ModuleType('domains.research_daily_statistics')
    statistics_module.build_daily_event_statistics = lambda **_kwargs: pytest.fail('event cache path must be used')
    monkeypatch.setitem(sys.modules, 'domains.research_daily_statistics', statistics_module)
    product_module = types.ModuleType('domains.research_daily_product')
    product_module.evaluate_daily_product = lambda **_kwargs: {
        'groups': {group: {'status': 'TRUE', 'anchor_date': None, 'reasons': []} for group in owner.GROUPS},
        'risk': {'status': 'CLEAR'},
    }
    monkeypatch.setitem(sys.modules, 'domains.research_daily_product', product_module)

    captured = []

    def capture_cases(_context, _symbol, _bars, _calendar, groups, _store):
        captured.append(groups)
        return {'groups': []}, {group: {'d2': {}, 'd5': {}} for group in owner.GROUPS}, []

    monkeypatch.setattr(owner, 'source_inputs', lambda *_args, **_kwargs: {})
    monkeypatch.setattr(owner, 'cached_daily_statistics', capture_cases)
    context = SimpleNamespace(
        target=target, root=tmp_path / 'current', scope=[symbol], config=config,
        identity={'input_sha256': 'current-input', 'basis': {'asof_date': target, 'price_basis': 'QFQ_ASOF'}},
        generation='current-generation', reader_ref={'path': '/fixture/reader.py', 'sha256': 'e' * 64},
        calendars={'SH': [DAY1, DAY2, DAY3]}, read=lambda _symbol: (bars, 'Fixture stock'),
        qualify=lambda _symbol: {'status': 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH',
                                 'history_start_date': str(DAY1)},
        label_results={symbol: result_refs[0]},
        label_bindings={symbol: (DAY1, 'accepted-generation', 'accepted-input', contract)},
    )
    outputs = []
    for result_ref in result_refs:
        context.label_results = {symbol: result_ref}
        row, _cache, _path = owner.compute_stock(context, symbol)
        outputs.append((row, captured[-1]))
    lineage_a = outputs[0][0]['_daily_accepted_label_lineage']
    lineage_b = outputs[1][0]['_daily_accepted_label_lineage']
    assert lineage_a['label_result_ref'] == result_refs[0]
    assert lineage_b['label_result_ref'] == result_refs[1]
    assert lineage_a['history_checkpoint_ref'] == lineage_b['history_checkpoint_ref'] == checkpoint_ref
    assert lineage_a['group_event_dates']['original'] == lineage_b['group_event_dates']['original'] == [owner.iso(DAY1)]
    assert outputs[0][1] == outputs[1][1]
    checkpoint_payload = owner.daily_checkpoint_payload(outputs[0][0])
    assert '_daily_accepted_label_lineage' not in checkpoint_payload
    assert checkpoint_payload['statistics'] == outputs[0][0]['statistics']
    assert Path(checkpoint_ref['path']).read_bytes() == checkpoint_bytes

    # A changed historical bar prefix invalidates the accepted label cache and
    # must not carry its provenance into the current event cases.
    bars[0]['close'] = 10.5
    row, _cache, _path = owner.compute_stock(context, symbol)
    assert '_daily_accepted_label_lineage' not in row
    assert all(group['event_dates'] == [owner.iso(DAY2)] for group in captured[-1])

    context.qualify = lambda _symbol: {'status': 'UNKNOWN', 'history_start_date': str(DAY1)}
    row, _cache, _path = owner.compute_stock(context, symbol)
    assert '_daily_accepted_label_lineage' not in row
    assert all(group['event_dates'] == [owner.iso(DAY2)] for group in captured[-1])


def test_materializer_persists_computed_lineage_across_retry(tmp_path, monkeypatch):
    import sys
    import types
    from ops import research_daily_product_parallel as parallel

    target = DAY2
    root = tmp_path / 'daily'
    event_cache = tmp_path / 'event-cache.sqlite'
    event_cache.write_bytes(b'isolated fixture')
    monkeypatch.setenv('V4_RESEARCH_EVENT_CASE_CACHE', str(event_cache))
    monkeypatch.delenv('V4_WORKBENCH_STATISTICS_ROOT', raising=False)
    monkeypatch.setattr(parallel, 'prefill_missing', lambda *_args, **_kwargs: {'chart_gaps': {}})
    monkeypatch.setattr(owner, 'save_history_checkpoint', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(owner, 'SourceContext', lambda *_args, **_kwargs: context)
    score = types.ModuleType('ops.materialize_workbench_score_action')
    score.materialize = lambda *_args, **_kwargs: {'status': 'READY'}
    assets = types.ModuleType('ops.complete_workbench_v192_assets')
    assets.at_numeric_completion = lambda *_args, **_kwargs: {'status': 'READY', 'module': None}
    assets.attach = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, 'ops.materialize_workbench_score_action', score)
    monkeypatch.setitem(sys.modules, 'ops.complete_workbench_v192_assets', assets)
    real_save = owner.save
    monkeypatch.setattr(owner, 'save', lambda path, value, immutable=False, compress_row=False:
        real_save(path, value, immutable=immutable, compress_row=False))

    row = dict(symbol=SYMBOL, display_name='Fixture', data_date=str(target), groups='original',
        pending_groups='', latest_new_anchor='', reasons='', risk_clear='CLEAR',
        evaluation={'groups': {group: {'status': 'TRUE'} for group in owner.GROUPS}},
        statistics={'groups': [{'sample_count': 1, 'mean_return_pct': 1.0}]},
        historical_coverage={}, qualification={'status': 'READY'},
        _daily_cached_groups={'original': {'d2': {'cases': [{'event_date': owner.iso(DAY1), 'return_pct': 1.0}]},
                                           'd5': {'cases': []}},
                              'nav_smallk': {'d2': {'cases': []}, 'd5': {'cases': []}},
                              'nav_pullback': {'d2': {'cases': []}, 'd5': {'cases': []}},
                              'nav_breakout': {'d2': {'cases': []}, 'd5': {'cases': []}}},
        _daily_cache_reuse=[])
    context = SimpleNamespace(root=root, target=target, d30_projection=None, scope=[SYMBOL],
        source_scope=[SYMBOL], current_universe_exclusions={}, generation='fixture-generation',
        identity={'input_sha256': 'fixture-input'}, config_ref={'path': '/fixture/config', 'sha256': 'a'*64},
        snapshot_ref={'path': '/fixture/snapshot', 'sha256': 'b'*64}, unchanged=lambda: None)
    contract = {'path': '/fixture/manifest.json', 'sha256': 'c'*64}
    result_ref = owner.save(tmp_path / 'accepted-result.json', {'fixture': 'accepted'}, immutable=True)
    cache_ref = owner.save(tmp_path / 'accepted-checkpoint.json', {'fixture': 'cache'}, immutable=True)
    lineage = {'label_result_ref': result_ref, 'result_contract': contract,
        'history_checkpoint_ref': cache_ref, 'historical_asof': DAY1,
        'source_identity': {'asof': DAY1, 'historical_PIT': False},
        'rule_identity': {'rule_sha256': 'd'*64, 'rules_signature': 'e'*64},
        'group_event_dates': {'original': [owner.iso(DAY1)]}}
    row['_daily_accepted_label_lineage'] = lineage
    compute_calls = []
    def compute(_context, symbol, **_kwargs):
        compute_calls.append(symbol)
        return dict(row), {}, tmp_path / 'unused-checkpoint.json'
    monkeypatch.setattr(owner, 'compute_stock', compute)

    first = owner.materialize_daily_product(data_root=tmp_path / 'data', target=target,
        output_root=root, original_charts=False)
    runkey = owner.digest(dict(identity=context.identity, config=context.config_ref,
                               symbols=[SYMBOL], history_dates=[]))
    parts = root / 'checkpoints' / str(target) / runkey
    numeric_row_path = parts / (SYMBOL + '.json')
    numeric_row_bytes = numeric_row_path.read_bytes()
    numeric_row = json.loads(numeric_row_bytes)
    assert '_daily_accepted_label_lineage' not in numeric_row
    binding = json.loads((parts / 'accepted_label_lineage' / (SYMBOL + '.json')).read_bytes())
    payload = json.loads(owner.checked(binding['lineage_ref']).read_bytes())
    assert payload['lineage'] == lineage

    retry = owner.materialize_daily_product(data_root=tmp_path / 'data', target=target,
        output_root=root, original_charts=False)
    assert compute_calls == [SYMBOL]
    assert retry['artifact'] == first['artifact'] and retry['manifest'] == first['manifest']
    assert numeric_row_path.read_bytes() == numeric_row_bytes
    index = json.loads((root / 'index.json').read_bytes())
    cases_index = json.loads(owner.checked(index['event_cases'][str(target)]).read_bytes())
    shard = json.loads(owner.checked(cases_index['items'][SYMBOL]).read_bytes())
    assert shard['accepted_label_lineage'] == lineage
    assert shard['groups'] == numeric_row['_daily_cached_groups']
    assert shard['statistics_sha256'] == owner.digest(numeric_row['statistics'])


def test_materializer_retry_restores_sidecar_and_preserves_legacy_event_refs(tmp_path, monkeypatch):
    import sys
    import types
    from ops import research_daily_product_parallel as parallel

    target = DAY2
    root = tmp_path / 'daily'
    event_cache = tmp_path / 'event-cache.sqlite'
    event_cache.write_bytes(b'isolated fixture')
    monkeypatch.setenv('V4_RESEARCH_EVENT_CASE_CACHE', str(event_cache))
    monkeypatch.delenv('V4_WORKBENCH_STATISTICS_ROOT', raising=False)
    monkeypatch.setattr(parallel, 'prefill_missing', lambda *_args, **_kwargs: {'chart_gaps': {}})
    monkeypatch.setattr(owner, 'save_history_checkpoint', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(owner, 'SourceContext', lambda *_args, **_kwargs: context)
    score = types.ModuleType('ops.materialize_workbench_score_action')
    score.materialize = lambda *_args, **_kwargs: {'status': 'READY'}
    assets = types.ModuleType('ops.complete_workbench_v192_assets')
    assets.at_numeric_completion = lambda *_args, **_kwargs: {'status': 'READY', 'module': None}
    assets.attach = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, 'ops.materialize_workbench_score_action', score)
    monkeypatch.setitem(sys.modules, 'ops.complete_workbench_v192_assets', assets)
    real_save = owner.save
    monkeypatch.setattr(owner, 'save', lambda path, value, immutable=False, compress_row=False:
        real_save(path, value, immutable=immutable, compress_row=False))

    row = dict(symbol=SYMBOL, display_name='Fixture', data_date=str(target), groups='original',
        pending_groups='', latest_new_anchor='', reasons='', risk_clear='CLEAR',
        evaluation={'groups': {group: {'status': 'TRUE'} for group in owner.GROUPS}},
        statistics={'groups': []}, historical_coverage={}, qualification={'status': 'READY'},
        _daily_cached_groups={'original': {'d2': {'cases': [{'event_date': owner.iso(DAY1), 'return_pct': 1.0}]},
                                           'd5': {'cases': []}},
                              'nav_smallk': {'d2': {'cases': []}, 'd5': {'cases': []}},
                              'nav_pullback': {'d2': {'cases': []}, 'd5': {'cases': []}},
                              'nav_breakout': {'d2': {'cases': []}, 'd5': {'cases': []}}},
        _daily_cache_reuse=[])
    context = SimpleNamespace(root=root, target=target, d30_projection=None, scope=[SYMBOL],
        source_scope=[SYMBOL], current_universe_exclusions={}, generation='fixture-generation',
        identity={'input_sha256': 'fixture-input'}, config_ref={'path': '/fixture/config', 'sha256': 'a'*64},
        snapshot_ref={'path': '/fixture/snapshot', 'sha256': 'b'*64}, unchanged=lambda: None)
    compute_calls = []
    def compute(_context, symbol, **_kwargs):
        compute_calls.append(symbol)
        return dict(row), {}, tmp_path / 'unused-checkpoint.json'
    monkeypatch.setattr(owner, 'compute_stock', compute)
    first = owner.materialize_daily_product(data_root=tmp_path / 'data', target=target,
        output_root=root, original_charts=False)
    runkey = owner.digest(dict(identity=context.identity, config=context.config_ref,
                               symbols=[SYMBOL], history_dates=[]))
    parts = root / 'checkpoints' / str(target) / runkey
    numeric_row_path = parts / (SYMBOL + '.json')
    numeric_row_bytes = numeric_row_path.read_bytes()
    numeric_row = json.loads(numeric_row_bytes)
    numeric_row_sha = owner.digest(owner.daily_checkpoint_payload(numeric_row))
    version = root / 'versions' / str(target) / context.generation / owner.digest(
        json.loads(owner.checked(first['artifact']).read_text()))
    legacy_shard_path = version / 'event_cases' / (SYMBOL + '.json')
    legacy_index_path = version / 'event_cases_index.json'
    legacy_shard_before = legacy_shard_path.read_bytes()
    legacy_index_before = legacy_index_path.read_bytes()
    contract = {'path': '/fixture/manifest.json', 'sha256': 'c'*64}
    result_ref = owner.save(tmp_path / 'accepted-result.json', {'fixture': 'accepted'}, immutable=True)
    cache_ref = owner.save(tmp_path / 'accepted-checkpoint.json', {'fixture': 'cache'}, immutable=True)
    lineage = {'label_result_ref': result_ref, 'result_contract': contract,
        'history_checkpoint_ref': cache_ref, 'historical_asof': DAY1,
        'source_identity': {'asof': DAY1, 'historical_PIT': False},
        'rule_identity': {'rule_sha256': 'd'*64, 'rules_signature': 'e'*64},
        'group_event_dates': {'original': [owner.iso(DAY1)]}}
    owner.store_daily_label_lineage(parts, SYMBOL, target, context.generation,
        context.identity['input_sha256'], numeric_row_sha, lineage)

    retry = owner.materialize_daily_product(data_root=tmp_path / 'data', target=target,
        output_root=root, original_charts=False)
    assert compute_calls == [SYMBOL]
    assert retry['artifact'] == first['artifact'] and retry['manifest'] == first['manifest']
    index = json.loads((root / 'index.json').read_bytes())
    cases_index_ref = index['event_cases'][str(target)]
    assert cases_index_ref['path'] != str(legacy_index_path)
    cases_index = json.loads(owner.checked(cases_index_ref).read_text())
    shard_ref = cases_index['items'][SYMBOL]
    assert shard_ref['path'] != str(legacy_shard_path)
    shard = json.loads(owner.checked(shard_ref).read_text())
    assert shard['accepted_label_lineage'] == lineage
    assert shard['groups'] == numeric_row['_daily_cached_groups']
    assert legacy_shard_path.read_bytes() == legacy_shard_before
    assert legacy_index_path.read_bytes() == legacy_index_before
    assert numeric_row_path.read_bytes() == numeric_row_bytes


def test_parallel_does_not_publish_a_row_if_history_write_fails(tmp_path, monkeypatch):
    context = SimpleNamespace(target=DAY2, scope=[SYMBOL], engine=lambda: SimpleNamespace(compute=lambda *_: None),
                              unchanged=lambda: None)
    parts = tmp_path / 'rows'
    path = tmp_path / 'history' / 'checkpoint.json'
    value = cache(DAY2, {DAY2: 'TRUE'})

    def compute(context_arg, symbol, *, history_dates, checkpoint_input):
        assert context_arg is context and symbol == SYMBOL and not history_dates
        checkpoint_input.update(expected_ref=None)
        return {'symbol': symbol, 'data_date': str(DAY2)}, value, path

    monkeypatch.setattr(parallel, '_CONTEXT', context)
    monkeypatch.setattr(parallel, '_PARTS', parts)
    monkeypatch.setattr(owner, 'compute_stock', compute)
    real_publish = history._publish
    with monkeypatch.context() as patch:
        def fail_publish(*args):
            raise OSError('simulated interruption')
        patch.setattr(history, '_publish', fail_publish)
        with pytest.raises(history.HistoryCheckpointError, match='WRITE_FAILED'):
            parallel.checkpoint(SYMBOL)
    assert not (parts / (SYMBOL + '.json')).exists()
    assert history._publish is real_publish
    assert parallel.checkpoint(SYMBOL)['ref']['path'] == str(parts / (SYMBOL + '.json'))
    assert history.read_checkpoint(path) == value


def test_independent_close_reads_original_seed_without_history_write(tmp_path, monkeypatch):
    root = tmp_path / 'close'
    original = tmp_path / 'original'
    source = original / 'history' / 'rule' / SYMBOL / 'checkpoint.json'
    prior = cache(DAY1, {DAY1: 'TRUE'})
    owner.save(source, prior)
    source_before = {p.relative_to(original): p.read_bytes() for p in original.rglob('*.json')}
    context = SimpleNamespace(root=root, target=DAY2, scope=[SYMBOL],
                              engine=lambda: SimpleNamespace(compute=lambda *_: None),
                              unchanged=lambda: None)
    calls = []

    def compute(context_arg, symbol, *, history_dates, checkpoint_input):
        assert context_arg is context and symbol == SYMBOL and not history_dates
        detached_path = context.root / source.relative_to(original)
        loaded = history.read_checkpoint(context.history_checkpoint_seed_root / detached_path.relative_to(root))
        calls.append(loaded)
        return {'symbol': symbol, 'data_date': str(DAY2), 'seed_asof': loaded['source_identity']['asof']}, loaded, detached_path

    def unexpected_history_write(*args):
        pytest.fail('independent close must not call the history writer')

    monkeypatch.setattr(parallel, '_CONTEXT', context)
    monkeypatch.setattr(parallel, '_PARTS', root / 'rows')
    monkeypatch.setattr(owner, 'compute_stock', compute)
    monkeypatch.setattr(owner, 'save_history_checkpoint', unexpected_history_write)
    first = parallel.checkpoint_independent_close(SYMBOL, history_root=original)
    repeat = parallel.checkpoint_independent_close(SYMBOL, history_root=original)
    assert calls == [prior]
    assert first == repeat
    assert json.loads(owner.checked(first['ref']).read_bytes())['seed_asof'] == DAY1
    assert not hasattr(context, 'history_checkpoint_seed_root')
    assert not (root / 'history').exists()
    assert {p.relative_to(original): p.read_bytes() for p in original.rglob('*.json')} == source_before
    with pytest.raises(ValueError, match='HISTORY_NAMESPACE_CONFLICT'):
        parallel.checkpoint_independent_close(SYMBOL, history_root=root)


def test_republished_view_uses_pinned_original_result_and_rejects_missing_proof(tmp_path):
    previous = cache(DAY1, {DAY1: 'TRUE'}, rules=owner.digest({}))
    original = dict(asof=DAY1, generation='old', input_sha256='old-input', historical_PIT=False)
    previous['source_identity'] = original
    previous['coverage'].update(requested_end=DAY1, historical_PIT=False, known_full_history=True, missing=[])
    cache_ref = owner.save(tmp_path / 'accepted' / 'checkpoint.json', previous)
    contract = {'path': '/proof/contract.json', 'sha256': 'a'*64}
    result_ref = owner.save(tmp_path / 'RESULT.json', dict(status='COMPLETE_DESCRIPTIVE_NONPIT', symbol=SYMBOL,
        historical_PIT=False, history_cache=cache_ref, evaluated_dates=1, available_dates=1, remaining_dates=[],
        contract=contract, **owner.FLAGS))
    manifest = {'path': '/proof/view-manifest.json', 'sha256': 'b'*64}
    view_identity = {**original, 'generation': 'new', 'input_sha256': 'new-input'}
    proof_path = tmp_path / 'proof.json'
    proof = dict(schema='CURRENT_COMPLETED_HISTORY_VIEW_V1', status='VERIFIED_REUSED_NO_COMPUTE',
                 source_identity=view_identity, numeric_manifest=manifest, retained_results={
                     SYMBOL: dict(result=result_ref, original_cache=cache_ref, original_source_identity=original)}, **owner.FLAGS)
    sync = dict(source_generation='new', input_sha256='new-input', numeric_manifest=manifest,
                contract=contract, stock_results={SYMBOL: result_ref})

    def bind(proof_value):
        if proof_value is not None:
            sync['current_view_validation'] = owner.save(proof_path, proof_value)
        else:
            sync.pop('current_view_validation', None)
        owner.save(tmp_path / 'index.json', {'history_sync': {str(DAY1): sync}})
        refs, bindings, retained = owner.label_index_bindings(tmp_path, DAY2)
        return SimpleNamespace(target=DAY2, config={}, label_results=refs, label_bindings=bindings, label_retained=retained)

    assert owner.accepted_label_cache(bind(proof), SYMBOL, 'rule', {'evaluations': {}}) == previous
    with pytest.raises(history.HistoryCheckpointError, match='DATE_OR_COVERAGE'):
        owner.accepted_label_cache(bind(None), SYMBOL, 'rule', {'evaluations': {}})
    with pytest.raises(history.HistoryCheckpointError, match='VIEW_RETAINED_RESULTS_CONFLICT'):
        bind({**proof, 'retained_results': {}})
    wrong_origin = {**proof['retained_results'][SYMBOL], 'original_source_identity': view_identity}
    with pytest.raises(history.HistoryCheckpointError, match='VIEW_ORIGIN_CONFLICT'):
        owner.accepted_label_cache(bind({**proof, 'retained_results': {SYMBOL: wrong_origin}}), SYMBOL, 'rule', {'evaluations': {}})


def test_backdated_head_does_not_shadow_intact_newer_legacy(tmp_path):
    path = tmp_path / 'checkpoint.json'
    newest = cache(DAY3, {DAY2: 'TRUE', DAY3: 'FALSE'})
    newest_ref = owner.save(path, newest)
    assert history.read_checkpoint(path, asof=DAY2) is None
    older = cache(DAY2, {DAY2: 'UNKNOWN'})
    old_ref = history.write_checkpoint(path, older, expected_ref=None)
    assert history.read_checkpoint_state(path, asof=DAY2) == (old_ref, older)
    assert history.read_checkpoint_state(path, asof=DAY3) == (newest_ref, newest)
    assert history.read_checkpoint(path) == newest
    assert path.read_bytes() == owner.canonical(newest) + b'\n'
    corrected = cache(DAY3, {DAY2: 'TRUE', DAY3: 'TRUE'})
    history.write_checkpoint(path, corrected, base_ref=newest_ref, expected_ref=newest_ref, retain_base=True)
    assert history.read_checkpoint(path) == corrected


def test_write_rechecks_transitive_base_after_precommit_observer(tmp_path):
    source = tmp_path / 'accepted' / 'checkpoint.json'
    original = cache(DAY1, {DAY1: 'TRUE'})
    base = owner.save(source, original)
    path = tmp_path / 'daily' / 'checkpoint.json'
    appended = cache(DAY2, {DAY1: 'TRUE', DAY2: 'FALSE'})
    first = history.write_checkpoint(path, appended, base_ref=base, expected_ref=None)
    dependencies = {}
    prior = history.load_checkpoint_ref(first, dependencies=dependencies)

    def remove_accepted_source(destination, size, committed):
        if destination.name.startswith('head-') and not committed:
            source.unlink()

    with pytest.raises(history.HistoryCheckpointError, match='DEPENDENCY_MOVED'):
        history.write_checkpoint(path, cache(DAY3, {DAY1: 'TRUE', DAY2: 'FALSE', DAY3: 'TRUE'}),
                                 base_ref=first, base_cache=prior, base_dependencies=dependencies,
                                 expected_ref=first, observe=remove_accepted_source)
    assert not (path.parent / f'head-{DAY3}.json').exists()
    with pytest.raises(history.HistoryCheckpointError, match='UNREADABLE'):
        history.write_checkpoint(path, appended, base_ref=base, base_cache=original, expected_ref=first)
