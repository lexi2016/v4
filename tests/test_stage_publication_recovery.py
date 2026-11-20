"""Fault injection in isolated stores; never calls a provider or deployed writer."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from stage_center import raw_store as raw, selection as selection, runner as runner_module
from stage_center._runner_parts.slot_idempotency import _StageCenterRunner__existing_slot_body

DATE = '20261120'
STAGE = 'STAGE_0930_0935'
SHA = 'a' * 64
MARKETS = ('A_SHARE', 'HK_CONNECT')


def raw_kwargs(market='A_SHARE'):
    row = dict(batch_index=0, code='A.000001' if market == 'A_SHARE' else 'HK.00001',
        name='fixture', update_time='2026-11-20 09:35:00', last_price=11,
        open_price=10, high_price=12, low_price=9, prev_close_price=10,
        turnover=1_000_000, volume=10000, bid_price=10.9, ask_price=11.1,
        bid_vol=100, ask_vol=100, window_start='2026-11-20 09:31:00',
        window_end='2026-11-20 09:35:00', bar_count=5, temporal_cutoff_safe=True)
    return dict(trade_date=DATE, stage_id=STAGE, market=market, source_id='fixture',
        source_status='READY', rows=[row], cannot_confirm=(), requested_rows=1,
        source_evidence=(f'candidate_current_sha256={SHA}',), missing_symbols=(),
        window='09:31-09:35', cutoff_at='09:35:00')


def envelope(market, raw_sha):
    evidence = [f'candidate_current_sha256={SHA}']
    if market == 'A_SHARE':
        env = selection.select_a_stage([dict(code='A.000001', first_open=10, last_close=11,
            high=12, low=9, amount=1_000_000, bar_count=5, expected_rows=5, formal_eligible=True)],
            DATE, STAGE, raw_sha)
    else:
        env = selection.select_hk_four_lane([dict(code='HK.00001', candidate_lanes=['LIVE_HKCONNECT_GAINER'],
            pct_chg=4, volume_ratio=1.5, turnover_hkd_yi=0.2, turnover_rate=3,
            platform_circular_market_cap_hkd_yi=80, offer_float_market_cap_hkd_yi=15,
            stage_id=STAGE)], DATE, STAGE, raw_sha)
    env['source_evidence'] = [*env['source_evidence'], *evidence]
    return env


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.name.endswith('.lock')}


def fail_once(monkeypatch, module, suffix):
    original = module._atomic_write_json
    failed = False
    def write(path, data):
        nonlocal failed
        if not failed and str(path).endswith(suffix):
            failed = True
            raise OSError('injected publication cutpoint ' + suffix)
        return original(path, data)
    monkeypatch.setattr(module, '_atomic_write_json', write)
    return original


@pytest.mark.parametrize('cutpoint', ['manifest.json', 'receipt.json', 'latest.json'])
def test_raw_identical_retry_fills_missing_only(monkeypatch, tmp_path, cutpoint):
    store = raw.RawStore(tmp_path)
    original = fail_once(monkeypatch, raw, cutpoint)
    with pytest.raises(OSError, match='injected'):
        store.publish(**raw_kwargs())
    surviving = snapshot(tmp_path)
    monkeypatch.setattr(raw, '_atomic_write_json', original)
    result = store.publish(**raw_kwargs())
    assert result['status'] == 'READY'
    after = snapshot(tmp_path)
    for name, content in surviving.items():
        if name.endswith('/artifact.pending.csv'):
            assert after[name.removesuffix('artifact.pending.csv') + 'artifact.csv'] == content
        else:
            assert after[name] == content
    assert store.publish(**raw_kwargs())['already_exists'] is True


@pytest.mark.parametrize('cutpoint', ['manifest.json', 'receipt.json', 'selection_latest.json'])
def test_selection_identical_retry_fills_missing_only(monkeypatch, tmp_path, cutpoint):
    store = selection.SelectionStore(tmp_path)
    env = envelope('A_SHARE', SHA)
    original = fail_once(monkeypatch, selection, cutpoint)
    with pytest.raises(OSError, match='injected'):
        store.publish(env, market='A_SHARE')
    surviving = snapshot(tmp_path)
    monkeypatch.setattr(selection, '_atomic_write_json', original)
    result = store.publish(env, market='A_SHARE')
    assert result['rows'] == env['rows']
    after = snapshot(tmp_path)
    for name, content in surviving.items():
        if name.endswith('/artifact.pending.csv'):
            assert after[name.removesuffix('artifact.pending.csv') + 'artifact.csv'] == content
        else:
            assert after[name] == content
    assert store.publish(env, market='A_SHARE') == result


@pytest.mark.parametrize('kind', ['raw', 'selection'])
def test_csv_failure_can_resume_explicit_identical_input(monkeypatch, tmp_path, kind):
    module = raw if kind == 'raw' else selection
    store = raw.RawStore(tmp_path) if kind == 'raw' else selection.SelectionStore(tmp_path)
    call = lambda: store.publish(**raw_kwargs()) if kind == 'raw' else store.publish(envelope('A_SHARE', SHA), market='A_SHARE')
    original = module._atomic_write_csv
    monkeypatch.setattr(module, '_atomic_write_csv', lambda *a, **kw: (_ for _ in ()).throw(OSError('CSV failed')))
    with pytest.raises(OSError, match='CSV failed'):
        call()
    monkeypatch.setattr(module, '_atomic_write_csv', original)
    assert call()


@pytest.mark.parametrize('kind', ['raw', 'selection'])
def test_store_retry_recovers_exact_staged_artifact_before_intent(monkeypatch, tmp_path, kind):
    module = raw if kind == 'raw' else selection
    store = raw.RawStore(tmp_path) if kind == 'raw' else selection.SelectionStore(tmp_path)
    call = lambda: store.publish(**raw_kwargs()) if kind == 'raw' else store.publish(envelope('A_SHARE', SHA), market='A_SHARE')
    original = fail_once(monkeypatch, module, 'publication-intent.json')
    with pytest.raises(OSError, match='injected'):
        call()
    staged = list(tmp_path.rglob('artifact.pending.csv'))
    assert len(staged) == 1 and staged[0].is_file()
    run_dir = staged[0].parent
    assert {path.name for path in run_dir.iterdir()} == {'artifact.pending.csv'}
    monkeypatch.setattr(module, '_atomic_write_json', original)
    assert call()
    assert not staged[0].exists()
    assert (run_dir / 'artifact.csv').is_file()


@pytest.mark.parametrize('kind', ['raw', 'selection'])
def test_changed_request_cannot_adopt_staged_artifact(monkeypatch, tmp_path, kind):
    module = raw if kind == 'raw' else selection
    store = raw.RawStore(tmp_path) if kind == 'raw' else selection.SelectionStore(tmp_path)
    if kind == 'raw':
        original_call = lambda: store.publish(**raw_kwargs())
        changed = raw_kwargs()
        changed['rows'][0]['last_price'] = 12
        changed_call = lambda: store.publish(**changed)
    else:
        env = envelope('A_SHARE', SHA)
        original_call = lambda: store.publish(env, market='A_SHARE')
        changed = envelope('A_SHARE', SHA)
        changed['rows'][0]['score'] += 0.1
        changed_call = lambda: store.publish(changed, market='A_SHARE')
    original = fail_once(monkeypatch, module, 'publication-intent.json')
    with pytest.raises(OSError, match='injected'):
        original_call()
    before = snapshot(tmp_path)
    monkeypatch.setattr(module, '_atomic_write_json', original)
    expected_error = 'pending publication slot request conflict' if kind == 'raw' else 'selection identity mismatch'
    with pytest.raises(ValueError, match=expected_error):
        changed_call()
    assert snapshot(tmp_path) == before


def seeded(tmp_path, *, a_selection_raw_sha=None):
    raw_root, selection_root = tmp_path / 'raw', tmp_path / 'selection'
    rs, ss = raw.RawStore(raw_root), selection.SelectionStore(selection_root)
    results = {market: rs.publish(**raw_kwargs(market)) for market in MARKETS}
    bundle = rs.publish_bundle(trade_date=DATE, stage_id=STAGE, status='READY', markets=results)
    for market in MARKETS:
        selection_raw_sha = a_selection_raw_sha if market == 'A_SHARE' and a_selection_raw_sha is not None else results[market]['artifact_sha256']
        ss.publish(envelope(market, selection_raw_sha), market=market)
    dummy = SimpleNamespace(config=SimpleNamespace(raw_root=raw_root, selection_root=selection_root, backfill_run_id=None))
    return rs, ss, dummy, bundle


def existing(dummy, markets=MARKETS, sha=SHA):
    return _StageCenterRunner__existing_slot_body(runner_module.__dict__, dummy, DATE, STAGE, markets, {m: sha for m in markets})


@pytest.mark.parametrize('loss', ['raw', 'bundle', 'selection', 'all'])
def test_runner_restores_complete_artifacts_without_source_or_builder(tmp_path, loss):
    rs, ss, dummy, bundle = seeded(tmp_path)
    before = snapshot(tmp_path)
    for kind, path in [('raw', rs.latest_path), ('bundle', rs.root / 'bundle_latest.json'), ('selection', ss.latest_path)]:
        if loss in {kind, 'all'}:
            path.unlink()
    state, result = existing(dummy)
    assert state == 'VERIFIED'
    assert result['raw']['receipt']['bundle_id'] == bundle['bundle_id']
    assert snapshot(tmp_path) == before
    assert existing(dummy)[0] == 'VERIFIED'


@pytest.mark.parametrize('kind', ['raw', 'selection'])
def test_runner_finishes_receipt_after_durable_artifact(tmp_path, kind):
    rs, ss, dummy, _ = seeded(tmp_path)
    root = rs.root if kind == 'raw' else ss.root
    pointer = rs.latest_path if kind == 'raw' else ss.latest_path
    entries = json.loads(pointer.read_text())['entries']
    entry = entries[f'{DATE}/{STAGE}/A_SHARE']
    receipt_path = root / str(Path(entry['artifact_relative']).parent / 'receipt.json')
    receipt = receipt_path.read_bytes()
    receipt_path.unlink()
    pointer.unlink()
    assert existing(dummy)[0] == 'VERIFIED'
    assert receipt_path.read_bytes() == receipt


@pytest.mark.parametrize('kind', ['raw', 'selection'])
def test_normal_runner_recovers_v2_intent_before_manifest(monkeypatch, tmp_path, kind):
    raw_root, selection_root = tmp_path / 'raw', tmp_path / 'selection'
    rs, ss = raw.RawStore(raw_root), selection.SelectionStore(selection_root)
    if kind == 'raw':
        original = fail_once(monkeypatch, raw, 'manifest.json')
        with pytest.raises(OSError, match='injected'):
            rs.publish(**raw_kwargs())
        lane = next((raw_root / 'runs' / DATE).rglob('publication-intent.json'))
        expected_files = {'publication-intent.json', 'artifact.pending.csv'}
    else:
        results = {market: rs.publish(**raw_kwargs(market)) for market in MARKETS}
        rs.publish_bundle(trade_date=DATE, stage_id=STAGE, status='READY', markets=results)
        ss.publish(envelope('HK_CONNECT', results['HK_CONNECT']['artifact_sha256']), market='HK_CONNECT')
        original = fail_once(monkeypatch, selection, 'manifest.json')
        with pytest.raises(OSError, match='injected'):
            ss.publish(envelope('A_SHARE', results['A_SHARE']['artifact_sha256']), market='A_SHARE')
        lane = next((selection_root / 'selection_runs' / DATE).rglob('publication-intent.json'))
        expected_files = {'publication-intent.json', 'artifact.pending.csv'}
    run_dir = lane.parent
    assert {path.name for path in run_dir.iterdir()} == expected_files
    intent_sha = hashlib.sha256(lane.read_bytes()).hexdigest()
    monkeypatch.setattr(raw if kind == 'raw' else selection, '_atomic_write_json', original)
    if kind == 'raw':
        dummy = SimpleNamespace(config=SimpleNamespace(raw_root=raw_root, selection_root=selection_root, backfill_run_id=None))
        state, result = existing(dummy, markets=('A_SHARE',))
        assert state == 'PARTIAL'
    else:
        from stage_center.candidate_input import CandidateInput
        candidate = CandidateInput(tmp_path, DATE, 'current.json', SHA, 'fixture-run',
            ('A.000001',), SHA, SHA, SHA, SHA, ())
        monkeypatch.setattr(runner_module, 'read_candidate_input', lambda *args, **kwargs: candidate)
        calls = []
        def forbidden(*args, **kwargs):
            calls.append('collector-or-builder')
            raise AssertionError('verified recovery called a collector or selection builder')
        config = runner_module.RunnerConfig(tmp_path / 'candidate', raw_root, selection_root,
            tmp_path / 'receipts', selection_builders={market: forbidden for market in MARKETS})
        instance = runner_module.StageCenterRunner(config, collectors={market: forbidden for market in MARKETS})
        runner_calls = []
        run_one = instance._run_one
        def once(decision, **kwargs):
            runner_calls.append(decision)
            return run_one(decision, **kwargs)
        instance._run_one = once
        result = instance._run_one(SimpleNamespace(trade_date=DATE, stage_id=STAGE, status='LATE_CATCHUP_REPLAY'))
        assert result['status'] == 'NOOP_ALREADY_VERIFIED'
        assert result['write_performed'] is True
        assert len(runner_calls) == 1
        assert calls == []
        assert hashlib.sha256(lane.read_bytes()).hexdigest() == intent_sha
    assert f'{kind.upper()}:A_SHARE' in result['recovered_publications']
    assert (run_dir / 'manifest.json').is_file()
    assert (run_dir / 'artifact.csv').is_file()
    assert (run_dir / 'receipt.json').is_file()
    assert not (run_dir / 'artifact.pending.csv').exists()
    if kind == 'raw':
        assert (raw_root / 'latest.json').is_file()
    else:
        assert (selection_root / 'selection_latest.json').is_file()


@pytest.mark.parametrize('mutation', ['candidate', 'intent'])
def test_runner_rejects_cross_identity_or_corrupt_v2_intent_before_mutation(monkeypatch, tmp_path, mutation):
    raw_root, selection_root = tmp_path / 'raw', tmp_path / 'selection'
    store = raw.RawStore(raw_root)
    original = fail_once(monkeypatch, raw, 'manifest.json')
    with pytest.raises(OSError, match='injected'):
        store.publish(**raw_kwargs())
    intent_path = next((raw_root / 'runs' / DATE).rglob('publication-intent.json'))
    if mutation == 'intent':
        intent = json.loads(intent_path.read_text())
        intent['manifest_sha256'] = '0' * 64
        intent_path.write_text(json.dumps(intent))
    before = snapshot(tmp_path)
    monkeypatch.setattr(raw, '_atomic_write_json', original)
    dummy = SimpleNamespace(config=SimpleNamespace(raw_root=raw_root, selection_root=selection_root, backfill_run_id=None))
    state, result = existing(dummy, markets=('A_SHARE',), sha='b' * 64 if mutation == 'candidate' else SHA)
    assert state == 'PARTIAL'
    assert 'A_SHARE' in result['pending_errors']
    assert snapshot(tmp_path) == before
    run_dir = intent_path.parent
    assert not (run_dir / 'manifest.json').exists()
    assert not (run_dir / 'artifact.csv').exists()
    assert not (raw_root / 'latest.json').exists()


def test_legacy_v1_intent_without_manifest_or_artifact_stays_fail_closed(monkeypatch, tmp_path):
    raw_root, selection_root = tmp_path / 'raw', tmp_path / 'selection'
    store = raw.RawStore(raw_root)
    original = fail_once(monkeypatch, raw, 'manifest.json')
    with pytest.raises(OSError, match='injected'):
        store.publish(**raw_kwargs())
    intent_path = next((raw_root / 'runs' / DATE).rglob('publication-intent.json'))
    intent = json.loads(intent_path.read_text())
    legacy = {key: intent[key] for key in ('manifest_sha256', 'receipt_sha256', 'receipt')}
    legacy['schema_version'] = 'stage_center.publication_intent.v1'
    intent_path.write_text(json.dumps(legacy))
    (intent_path.parent / 'artifact.pending.csv').unlink()
    before = snapshot(tmp_path)
    monkeypatch.setattr(raw, '_atomic_write_json', original)
    dummy = SimpleNamespace(config=SimpleNamespace(raw_root=raw_root, selection_root=selection_root, backfill_run_id=None))
    state, result = existing(dummy, markets=('A_SHARE',))
    assert state == 'PARTIAL' and 'A_SHARE' in result['pending_errors']
    assert snapshot(tmp_path) == before
    assert not (raw_root / 'latest.json').exists()


@pytest.mark.parametrize('mutation', ['candidate', 'artifact', 'intent', 'symlink'])
def test_pending_recovery_rejects_mismatch_without_advancing_pointers(tmp_path, mutation):
    rs, ss, dummy, _ = seeded(tmp_path)
    entry = json.loads(rs.latest_path.read_text())['entries'][f'{DATE}/{STAGE}/A_SHARE']
    run_dir = (rs.root / entry['artifact_relative']).parent
    rs.latest_path.unlink()
    if mutation == 'artifact':
        (run_dir / 'artifact.csv').write_bytes(b'corrupt')
    elif mutation == 'intent':
        (run_dir / 'publication-intent.json').write_text('{}')
    elif mutation == 'symlink':
        (run_dir / 'receipt.json').unlink()
        (run_dir / 'receipt.json').symlink_to(run_dir / 'manifest.json')
    before = snapshot(tmp_path)
    state, result = existing(dummy, markets=('A_SHARE',), sha='b' * 64 if mutation == 'candidate' else SHA)
    assert state == 'PARTIAL'
    assert 'A_SHARE' in result['pending_errors']
    assert result['raw_verified'] == {} and result['selections'] == {}
    assert snapshot(tmp_path) == before
    assert not rs.latest_path.exists()


def test_pending_bundle_cannot_cross_narrowed_market_scope(tmp_path):
    rs, ss, dummy, _ = seeded(tmp_path)
    (rs.root / 'bundle_latest.json').unlink()
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match='market scope mismatch'):
        existing(dummy, markets=('HK_CONNECT',))
    assert snapshot(tmp_path) == before


def test_historical_namespace_does_not_repair_pointers(tmp_path):
    rs, ss, dummy, _ = seeded(tmp_path)
    rs.latest_path.unlink()
    ss.latest_path.unlink()
    (rs.root / 'bundle_latest.json').unlink()
    dummy.config.backfill_run_id = 'historical-fixture'
    before = snapshot(tmp_path)
    assert existing(dummy) == ('ABSENT', None)
    assert snapshot(tmp_path) == before


def test_bundle_retry_after_latest_failure_keeps_receipt_bytes(monkeypatch, tmp_path):
    rs = raw.RawStore(tmp_path)
    results = {market: rs.publish(**raw_kwargs(market)) for market in MARKETS}
    original = fail_once(monkeypatch, raw, 'bundle_latest.json')
    with pytest.raises(OSError, match='injected'):
        rs.publish_bundle(trade_date=DATE, stage_id=STAGE, status='READY', markets=results)
    before = snapshot(tmp_path)
    monkeypatch.setattr(raw, '_atomic_write_json', original)
    assert rs.publish_bundle(trade_date=DATE, stage_id=STAGE, status='READY', markets=results)['ok']
    assert all(snapshot(tmp_path)[name] == content for name, content in before.items())


def test_rejected_pending_lane_preserves_healthy_sibling(tmp_path):
    rs, ss, dummy, _ = seeded(tmp_path)
    entry = json.loads(rs.latest_path.read_text())['entries'][f'{DATE}/{STAGE}/A_SHARE']
    (rs.root / entry['artifact_relative']).write_bytes(b'corrupt')
    latest = json.loads(rs.latest_path.read_text())
    del latest['entries'][f'{DATE}/{STAGE}/A_SHARE']
    rs.latest_path.write_text(json.dumps(latest))
    before = snapshot(tmp_path)
    state, result = existing(dummy)
    assert state == 'PARTIAL'
    assert set(result['pending_errors']) == {'A_SHARE'}
    assert set(result['raw_verified']) == set(result['selections']) == {'HK_CONNECT'}
    assert snapshot(tmp_path) == before


def test_missing_original_csv_returns_explicit_pending_error_without_recapture(tmp_path):
    rs, ss, dummy, _ = seeded(tmp_path)
    entry = json.loads(rs.latest_path.read_text())['entries'][f'{DATE}/{STAGE}/A_SHARE']
    (rs.root / entry['artifact_relative']).unlink()
    latest = json.loads(rs.latest_path.read_text())
    del latest['entries'][f'{DATE}/{STAGE}/A_SHARE']
    rs.latest_path.write_text(json.dumps(latest))
    state, result = existing(dummy)
    assert state == 'PARTIAL'
    assert 'durable artifact unavailable' in result['pending_errors']['A_SHARE']
    assert 'HK_CONNECT' in result['selections']


def test_runner_replay_restores_all_pointers_and_never_recollects(monkeypatch, tmp_path):
    from stage_center.candidate_input import CandidateInput
    rs, ss, _dummy, _bundle = seeded(tmp_path)
    rs.latest_path.unlink()
    ss.latest_path.unlink()
    (rs.root / 'bundle_latest.json').unlink()
    candidate = CandidateInput(tmp_path, DATE, 'current.json', SHA, 'fixture-run', ('A.000001',), SHA, SHA, SHA, SHA, ())
    monkeypatch.setattr(runner_module, 'read_candidate_input', lambda *args, **kwargs: candidate)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append('source-or-builder')
        raise AssertionError('recovery called a source or builder')
    config = runner_module.RunnerConfig(tmp_path / 'candidate', rs.root, ss.root,
        tmp_path / 'receipts', selection_builders={market: forbidden for market in MARKETS})
    instance = runner_module.StageCenterRunner(config, collectors={market: forbidden for market in MARKETS})
    decision = SimpleNamespace(trade_date=DATE, stage_id=STAGE, status='LATE_CATCHUP_REPLAY')
    result = instance._run_one(decision)
    assert result['status'] == 'NOOP_ALREADY_VERIFIED'
    assert result['write_performed'] is True
    assert result['commit_recovery_performed'] is True
    assert len(result['recovered_publications']) == 5
    assert calls == []
    assert result['RESEARCH_ONLY'] is True
    assert all(result[flag] is False for flag in raw.SAFETY_FLAGS)
    result2 = instance._run_one(decision)
    assert result2['status'] == 'NOOP_ALREADY_VERIFIED'
    assert result2['write_performed'] is False
    assert calls == []


def test_natural_timing_attaches_to_original_owner_receipt_and_counter(tmp_path):
    from stage_center import end_to_end_deadline as deadline
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo
    config = runner_module.RunnerConfig(tmp_path / 'candidate', tmp_path / 'raw',
        tmp_path / 'selection', tmp_path / 'receipts', selection_builders={})
    instance = runner_module.StageCenterRunner(config)
    trace = deadline.Trace(entry_ns=time.monotonic_ns(), entry_wall_ns=time.time_ns())
    deadline.set_current(trace)
    try:
        trace.event('SCHEDULER_WAKE', evaluated_at_is_synthetic=False)
        trace.due(datetime(2026,11,20,9,35,tzinfo=ZoneInfo('Asia/Shanghai')), dispatch_mode='NATURAL')
        for phase in ('INPUT_VALIDATION_START', 'INPUT_VALIDATION_END'):
            trace.checkpoint(phase)
        for market in MARKETS:
            trace.checkpoint('COLLECTOR_START', market=market)
            trace.checkpoint('COLLECTOR_END', market=market)
            trace.begin_write('RAW_PUBLISH', market=market)
            trace.end_write('RAW_PUBLISH', market=market)
        result = instance._write_receipt(dict(status='CANNOT_CONFIRM', dispatch_mode='NATURAL',
            node_attempt_count=2, write_performed=False), DATE, STAGE)
        path = instance._receipt_path(DATE, STAGE)
        result = deadline.complete_receipt(path, result,
            rewrite=lambda payload: instance._write_receipt(payload, DATE, STAGE))
        persisted = json.loads(path.read_text())
        timing = persisted['end_to_end_deadline']
        phases = [event['phase'] for event in timing['events']]
        assert all(phase in phases for phase in ['SCHEDULER_WAKE', 'INPUT_VALIDATION_START',
            'COLLECTOR_END', 'RAW_PUBLISH_COMPLETED', 'FINAL_RECEIPT_COMPLETED'])
        assert timing['receipt_endpoint_scope'] == 'DURABLE_BUSINESS_RECEIPT_BEFORE_TIMING_ATTACHMENT'
        assert timing['final_receipt']['receipt_path'] == str(path)
        assert timing['deadline_met'] is None and timing['natural_verified'] is False
        assert timing['due_to_final_receipt_wall_ns'] is not None
        assert persisted['node_attempt_count'] == result['node_attempt_count'] == 2
        assert persisted['status'] == 'CANNOT_CONFIRM'
        assert not list(tmp_path.rglob('*.deadline-pending'))
    finally:
        deadline.set_current(None)
        trace.close()


@pytest.mark.parametrize('kind', ['raw', 'selection'])
def test_changed_request_cannot_replace_pointerless_slot(tmp_path, kind):
    rs, ss, _dummy, _ = seeded(tmp_path)
    before = None
    if kind == 'raw':
        rs.latest_path.unlink()
        kwargs = raw_kwargs()
        kwargs['rows'][0]['last_price'] = 11.5
        before = snapshot(tmp_path)
        with pytest.raises(ValueError, match='request conflict'):
            rs.publish(**kwargs)
    else:
        entry = json.loads(rs.latest_path.read_text())['entries'][f'{DATE}/{STAGE}/A_SHARE']
        env = envelope('A_SHARE', entry['artifact_sha256'])
        env['rows'][0]['score'] += 1
        env.pop('run_id', None)
        env.pop('artifact_id', None)
        ss.latest_path.unlink()
        before = snapshot(tmp_path)
        with pytest.raises(ValueError, match='request conflict'):
            ss.publish(env, market='A_SHARE')
    assert snapshot(tmp_path) == before


def test_legacy_complete_trios_recover_without_a_new_journal(tmp_path):
    rs, ss, dummy, _ = seeded(tmp_path)
    for path in tmp_path.rglob('publication-intent.json'):
        path.unlink()
    rs.latest_path.unlink()
    ss.latest_path.unlink()
    before = snapshot(tmp_path)
    assert existing(dummy)[0] == 'VERIFIED'
    assert not list(tmp_path.rglob('publication-intent.json'))
    assert all(snapshot(tmp_path)[name] == content for name, content in before.items())


def test_legacy_incomplete_trio_stays_fail_closed(tmp_path):
    rs, ss, dummy, _ = seeded(tmp_path)
    entry = json.loads(rs.latest_path.read_text())['entries'][f'{DATE}/{STAGE}/A_SHARE']
    run_dir = (rs.root / entry['artifact_relative']).parent
    (run_dir / 'publication-intent.json').unlink()
    (run_dir / 'receipt.json').unlink()
    rs.latest_path.unlink()
    before = snapshot(tmp_path)
    state, result = existing(dummy, markets=('A_SHARE',))
    assert state == 'PARTIAL' and 'A_SHARE' in result['pending_errors']
    assert snapshot(tmp_path) == before
    with pytest.raises(ValueError, match='legacy incomplete'):
        rs.publish(**raw_kwargs())
    assert snapshot(tmp_path) == before


def test_unstarted_lane_does_not_report_publication_recovery(tmp_path):
    from stage_center._runner_parts.slot_idempotency import _recover_pending_lanes
    dummy = SimpleNamespace(config=SimpleNamespace(raw_root=tmp_path / 'raw', selection_root=tmp_path / 'selection', backfill_run_id=None))
    errors, recovered = _recover_pending_lanes(runner_module.__dict__, dummy, DATE, STAGE, MARKETS, {m: SHA for m in MARKETS})
    assert errors == {} and recovered == []


def test_unverified_predecessor_cannot_bypass_pending_identity_guard(tmp_path):
    from stage_center._selection_parts.store_publication import _SelectionStore_publish_body
    rs, ss, _dummy, _ = seeded(tmp_path)
    entry = json.loads(ss.latest_path.read_text())['entries'][f'{DATE}/{STAGE}/A_SHARE']
    ss.latest_path.unlink()
    env = envelope('A_SHARE', 'b' * 64)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match='request conflict'):
        _SelectionStore_publish_body(selection.__dict__, ss, env, market='A_SHARE', replace_failed_run_id=entry['run_id'])
    assert snapshot(tmp_path) == before


def test_pending_directory_lookup_is_bounded(tmp_path):
    dummy = SimpleNamespace(config=SimpleNamespace(raw_root=tmp_path / 'raw', selection_root=tmp_path / 'selection', backfill_run_id=None))
    role = raw.RawStore(dummy.config.raw_root)._role(STAGE, 'A_SHARE')
    for index in range(33):
        (dummy.config.raw_root / 'runs' / DATE / role / f'run-{index}').mkdir(parents=True)
    state, result = existing(dummy, markets=('A_SHARE',))
    assert state == 'PARTIAL'
    assert 'bounded run count' in result['pending_errors']['A_SHARE']
    assert not (dummy.config.raw_root / 'latest.json').exists()


def test_runner_rejects_bad_pending_lane_without_recollecting_healthy_lane(monkeypatch, tmp_path):
    from stage_center.candidate_input import CandidateInput
    rs, ss, _dummy, _ = seeded(tmp_path)
    latest = json.loads(rs.latest_path.read_text())
    entry = latest['entries'].pop(f'{DATE}/{STAGE}/A_SHARE')
    rs.latest_path.write_text(json.dumps(latest))
    (rs.root / entry['artifact_relative']).write_bytes(b'corrupt')
    candidate = CandidateInput(tmp_path, DATE, 'current.json', SHA, 'fixture-run', ('A.000001',), SHA, SHA, SHA, SHA, ())
    monkeypatch.setattr(runner_module, 'read_candidate_input', lambda *args, **kwargs: candidate)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append('source-or-builder')
        raise AssertionError('pending recovery called a source or builder')
    config = runner_module.RunnerConfig(tmp_path / 'candidate', rs.root, ss.root,
        tmp_path / 'receipts', selection_builders={market: forbidden for market in MARKETS})
    instance = runner_module.StageCenterRunner(config, collectors={market: forbidden for market in MARKETS})
    result = instance._run_one(SimpleNamespace(trade_date=DATE, stage_id=STAGE, status='LATE_CATCHUP_REPLAY'))
    assert result['status'] == 'PARTIAL_WITH_ROWS'
    assert result['markets']['HK_CONNECT']['selected_rows'] == 1
    assert result['markets']['A_SHARE']['selection_status'] == 'CANNOT_CONFIRM'
    assert 'PENDING_PUBLICATION_UNRECOVERABLE' in result['markets']['A_SHARE']['cannot_confirm'][0]
    assert calls == []
    assert f'{DATE}/{STAGE}/A_SHARE' not in json.loads(rs.latest_path.read_text())['entries']


@pytest.mark.parametrize('kind', ['raw', 'selection'])
def test_corrupt_pending_receipt_metadata_is_rejected_before_filling_file(tmp_path, kind):
    rs, ss, dummy, _ = seeded(tmp_path)
    root = rs.root if kind == 'raw' else ss.root
    pointer = rs.latest_path if kind == 'raw' else ss.latest_path
    entry = json.loads(pointer.read_text())['entries'][f'{DATE}/{STAGE}/A_SHARE']
    run_dir = (root / entry['artifact_relative']).parent
    (run_dir / 'receipt.json').unlink()
    intent_path = run_dir / 'publication-intent.json'
    intent = json.loads(intent_path.read_text())
    intent['receipt']['idempotency_key'] = 'b' * 64
    intent_path.write_text(json.dumps(intent))
    pointer.unlink()
    before = snapshot(tmp_path)
    state, result = existing(dummy, markets=('A_SHARE',))
    assert state == 'PARTIAL' and 'A_SHARE' in result['pending_errors']
    assert not (run_dir / 'receipt.json').exists()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('recover_raw_pointer', [False, True])
def test_same_candidate_selection_requires_exact_verified_raw_generation(tmp_path, recover_raw_pointer):
    rs, ss, dummy, _ = seeded(tmp_path, a_selection_raw_sha='b' * 64)
    if recover_raw_pointer:
        latest = json.loads(rs.latest_path.read_text())
        del latest['entries'][f'{DATE}/{STAGE}/A_SHARE']
        rs.latest_path.write_text(json.dumps(latest))
    before = snapshot(tmp_path)
    state, result = existing(dummy)
    assert state == 'PARTIAL'
    assert set(result['selections']) == {'HK_CONNECT'}
    assert set(result['raw_verified']) == set(MARKETS)
    assert result['pending_errors']['A_SHARE'].startswith('EXISTING_SELECTION_RAW_IDENTITY_MISMATCH:')
    assert result['commit_recovery_performed'] is recover_raw_pointer
    after = snapshot(tmp_path)
    for name, data in before.items():
        if recover_raw_pointer and name == 'raw/latest.json':
            continue
        assert after[name] == data
    assert set(after) == set(before)
    # Neither an existing pointer nor a recovered raw may adopt the stale
    # selection on the next attempt, and rejection does not rewrite it.
    second_before = snapshot(tmp_path)
    second_state, second = existing(dummy)
    assert second_state == 'PARTIAL' and set(second['selections']) == {'HK_CONNECT'}
    assert snapshot(tmp_path) == second_before


@pytest.mark.parametrize('recover_raw_pointer', [False, True])
def test_runner_same_candidate_cross_raw_selection_fails_lane_without_recapture(monkeypatch, tmp_path, recover_raw_pointer):
    from stage_center.candidate_input import CandidateInput
    rs, ss, _dummy, _ = seeded(tmp_path, a_selection_raw_sha='b' * 64)
    if recover_raw_pointer:
        latest = json.loads(rs.latest_path.read_text())
        del latest['entries'][f'{DATE}/{STAGE}/A_SHARE']
        rs.latest_path.write_text(json.dumps(latest))
    selection_before = snapshot(ss.root)
    candidate = CandidateInput(tmp_path, DATE, 'current.json', SHA, 'fixture-run', ('A.000001',), SHA, SHA, SHA, SHA, ())
    monkeypatch.setattr(runner_module, 'read_candidate_input', lambda *args, **kwargs: candidate)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append('source-or-builder')
        raise AssertionError('cross-raw recovery called a source or builder')
    config = runner_module.RunnerConfig(tmp_path / 'candidate', rs.root, ss.root,
        tmp_path / 'receipts', selection_builders={market: forbidden for market in MARKETS})
    instance = runner_module.StageCenterRunner(config, collectors={market: forbidden for market in MARKETS})
    result = instance._run_one(SimpleNamespace(trade_date=DATE, stage_id=STAGE, status='LATE_CATCHUP_REPLAY'))
    assert result['status'] == 'PARTIAL_WITH_ROWS'
    assert result['markets']['A_SHARE']['selection_status'] == 'CANNOT_CONFIRM'
    assert result['markets']['A_SHARE']['selected_rows'] == 0
    assert result['markets']['A_SHARE']['cannot_confirm'][0].startswith('EXISTING_SELECTION_RAW_IDENTITY_MISMATCH:')
    assert result['markets']['HK_CONNECT']['selected_rows'] == 1
    assert calls == []
    assert snapshot(ss.root) == selection_before
