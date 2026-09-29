"""Offline orchestration regressions, not a live provider/Mac acceptance.

The real entrypoint and real final evaluate_us_activation are executed.
Only unavailable app identity, provider and reader boundaries are injected.
The final shared evaluator and exact pinned POSIX SafeRoot are real code. The real shared evaluator must never be replaced by a PASS stub.
Run with CANARY_SOURCE=/absolute/path/to/ops/run_manager_us_activation_canary.py
and CANARY_GATE_SOURCE=/absolute/path/to/v4/manager_research/activation_canary.py
when reviewing against a full immutable Mac app.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('CANARY_SOURCE', PACKAGE / 'ops/run_manager_us_activation_canary.py'))
GATE = Path(os.environ.get('CANARY_GATE_SOURCE', PACKAGE / 'v4/manager_research/activation_canary.py'))
NOW = datetime(2026, 9, 28, 20, 16, 0, tzinfo=timezone.utc)
RUN_ID = '7b957fbaac724f9186f91eb96d1851511a'


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError('NO_NETWORK_IN_OFFLINE_TEST')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    app = tmp_path / 'app'
    (app / 'ops').mkdir(parents=True)
    entry = app / 'ops/run_manager_us_activation_canary.py'
    entry.write_bytes(SOURCE.read_bytes())
    mod = _load(entry, 'fresh_canary_under_test')
    gate = _load(GATE, 'actual_final_activation_gate')
    root = tmp_path / 'sandbox/data'
    root.mkdir(parents=True)
    receipt = tmp_path / 'sandbox/receipt.json'
    identity = {'run_id': RUN_ID, 'data_root': str(root), 'receipt_path': str(receipt)}
    calls = []
    state = SimpleNamespace(
        mod=mod, root=root, receipt=receipt, calls=calls, reused=False, replaced=False,
        retained=False, phase='POST_CLOSE', late=False, origin='ORIGINAL_TIME_CAPTURE',
        original=True, run_override=None, id_override=None, captured_at=NOW.isoformat(),
        session='20260928', snapshot_session='20260928', reader_mismatch=False,
        lineage_status='VERIFIED', bridge_status='READY', producer_status='READY',
        calendar_status='VERIFIED', now=NOW, source_mutation=False,
        missing_captures=False, duplicate_capture=False, missing_reused=False,
        provider_error=False, extra_capture=False, call_started=None,
        future_capture=False, snapshot_time=None, provider_dates=['20260928'],
    )
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state.now.astimezone(tz) if tz else state.now.replace(tzinfo=None)
    monkeypatch.setattr(mod, 'datetime', Clock)
    gate.claim_canary_sandbox_identity = lambda *a, **k: copy.deepcopy(identity)
    for name in ['v4', 'v4.manager_research', 'ops', 'infrastructure']:
        module = ModuleType(name); module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, 'v4.manager_research.activation_canary', gate)
    producer_module = ModuleType('ops.us_market_digest')
    def window(day, phase):
        day = datetime.strptime(day, '%Y%m%d').date()
        from datetime import time
        return (datetime.combine(day, time(16, 15), ZoneInfo('America/New_York')),
                datetime.combine(day, time(16, 20), ZoneInfo('America/New_York')))
    producer_module.us_capture_window = window
    producer_module.us_market_day_certification = lambda day: {'status': state.calendar_status}
    producer_module._is_late_capture_identity = lambda obj: isinstance(obj, dict) and (
        obj.get('late') is True or obj.get('capture_mode') == 'CONTROLLED_LATE_POST_CLOSE')
    def producer(**kwargs):
        calls.append(kwargs)
        if state.provider_error:
            raise ValueError('SECRET-SHOULD-NOT-BE-IN-RECEIPT')
        row = {
            'us_session_date': state.session, 'capture_phase': state.phase,
            'capture_id': state.id_override or kwargs.get('capture_id', 'old-id'),
            'run_id': state.run_override or kwargs.get('run_id', 'old-run'),
            'captured_at': state.captured_at, 'capture_origin': state.origin,
            'original_time_capture': state.original,
            'capture_window_start': window('20260928','POST_CLOSE')[0].isoformat(),
            'capture_window_end': window('20260928','POST_CLOSE')[1].isoformat(),
        }
        if state.late: row['late'] = True
        captures = [] if state.missing_captures else [row]
        if state.duplicate_capture: captures.append(copy.deepcopy(row))
        if state.extra_capture:
            older = copy.deepcopy(row); older['run_id'] = 'old-run'; captures.append(older)
        snapshot = {'status': state.producer_status, 'capture_phase': state.phase,
                    'capture_session_date': state.snapshot_session,
                    'captured_at': state.snapshot_time or state.captured_at,
                    'provider_session_dates': state.provider_dates}
        payload = {'us_session_captures': captures, 'market_snapshot': snapshot,
                   'item_count': 0, 'production_allowed': False, 'buy_gate_updated': False,
                   'orders_sent': False}
        state.payload = payload
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        state.digest = digest
        result = {'payload': payload, 'payload_sha256': digest, 'reused': state.reused,
                  'replaced': state.replaced, 'market_snapshot_status': state.producer_status}
        if state.missing_reused: result.pop('reused')
        if state.retained: result['retained_previous'] = True
        if state.source_mutation: (app / 'changed.py').write_text('# changed')
        return result
    producer_module.materialize_us_market_phase = producer
    monkeypatch.setitem(sys.modules, 'ops.us_market_digest', producer_module)
    reader_module = ModuleType('v4.manager_research.us_market_bridge')
    class Reader:
        def __init__(self, root): pass
        def read_exact_session(self, session):
            payload = copy.deepcopy(state.payload)
            if state.reader_mismatch: payload['item_count'] = 1
            return payload, {'status': state.lineage_status, 'payload_sha256': state.digest,
                             'receipt_sha256': 'a' * 64, 'manifest_sha256': 'b' * 64}
    reader_module.ResearchPeripheralUsMarketReader = Reader
    reader_module.project_us_market = lambda *a: {
        'status': state.bridge_status, 'expected_us_session': '20260928',
        'coverage': {'hk_mapping_count': 0}, 'gaps': []}
    monkeypatch.setitem(sys.modules, 'v4.manager_research.us_market_bridge', reader_module)
    host_module = _load(Path(os.environ.get('OWNED_IO_SOURCE',
        PACKAGE / 'infrastructure/owned_io.py')), 'actual_pinned_owned_io')
    monkeypatch.setitem(sys.modules, 'infrastructure.owned_io', host_module)
    def run(extra=()):
        argv = ['--data-root', str(root), '--us-session-date', '20260928',
                '--target-hk-date','20260929','--manager-cutoff','2026-09-29T09:20:00+08:00',
                '--sandbox-identity', str(root.parent / 'identity.json'), '--receipt', str(receipt)]
        code = mod.main(argv + list(extra))
        return code, json.loads(receipt.read_text())
    state.run = run
    return state


def test_old_reused_payload_cannot_pass_fresh_activation(harness):
    harness.reused = True
    code, out = harness.run()
    assert code == 2
    assert out['decision']['status'] == 'STOP'


def test_nonempty_data_root_stops_before_producer(harness):
    (harness.root / 'old-artifact.json').write_text('{}')
    code, out = harness.run()
    assert code == 2
    assert harness.calls == []
    assert (harness.root / 'old-artifact.json').read_text() == '{}'


def test_fresh_post_close_exact_reader_accepts_zero_hk_mappings(harness):
    code, out = harness.run()
    assert code == 0 and out['decision']['status'] == 'PASS'
    assert len(harness.calls) == 1
    assert out['production_allowed'] is out['orders_sent'] is out['buy_gate_updated'] is False


@pytest.mark.parametrize('field,value', [
    ('replaced', True), ('retained', True), ('missing_reused', True),
    ('run_override', 'another-run'), ('id_override', 'another-capture'),
    ('missing_captures', True), ('duplicate_capture', True), ('extra_capture', True),
    ('origin', 'HISTORICAL_BACKFILL'), ('original', False), ('late', True),
    ('phase', 'PRE_OPEN'), ('session', '20260925'), ('snapshot_session', '20260925'),
    ('captured_at', '2026-09-28T20:15:00+00:00'),
    ('captured_at', '2026-09-28T20:17:00+00:00'),
    ('captured_at', '2026-09-28T20:16:00'),
    ('reader_mismatch', True), ('lineage_status', 'CANNOT_CONFIRM'),
    ('source_mutation', True), ('producer_status', 'FAILED'),
    ('snapshot_time', '2026-09-28T20:15:00+00:00'),
    ('provider_dates', ['20260925']),
])
def test_nonfresh_or_inconsistent_capture_stops(harness, field, value):
    setattr(harness, field, value)
    code, out = harness.run()
    assert code == 2 and out['decision']['status'] == 'STOP'
    assert out['decision']['evidence']['fresh_capture_evidence']['fresh_capture_verified'] is False


@pytest.mark.parametrize('extra',[('--capture-phase','PRE_OPEN'), ('--allow-late-post-close',)])
def test_nonnatural_mode_stops_before_producer(harness, extra):
    code, out = harness.run(extra)
    assert code == 2 and harness.calls == []


@pytest.mark.parametrize('time_string', ['2026-09-28T20:14:59+00:00', '2026-09-28T20:20:00+00:00'])
def test_outside_natural_window_stops_before_producer(harness, time_string):
    harness.now = datetime.fromisoformat(time_string)
    code, out = harness.run()
    assert code == 2 and harness.calls == []


def test_unverified_calendar_stops_before_producer(harness):
    harness.calendar_status = 'CANNOT_CONFIRM'
    code, out = harness.run()
    assert code == 2 and harness.calls == []


def test_ids_forwarded_to_existing_producer_without_clock_override(harness):
    code, out = harness.run()
    kwargs = harness.calls[0]
    assert kwargs['run_id'] == RUN_ID
    assert kwargs['capture_id'] == 'manager-us-canary:' + RUN_ID
    assert not {'now', 'fetched_at', 'captured_at', 'fetch_quotes', 'fetch_rss'} & set(kwargs)


def test_failed_provider_records_sanitized_stop(harness):
    harness.provider_error = True
    code, out = harness.run()
    assert code == 2 and out['decision']['status'] == 'STOP'
    assert 'SECRET-SHOULD-NOT-BE-IN-RECEIPT' not in harness.receipt.read_text()


def test_real_identity_contract_can_bind_preexisting_files(tmp_path, monkeypatch):
    """Identity authenticates input bytes, not freshness. It must stay general.

    Real write/validate/claim and SafeRoot; only unavailable app inventory is
    injected. This establishes why the entrypoint needs its own empty-root gate.
    """
    import tempfile
    gate = _load(GATE, 'real_identity_gate')
    host = _load(Path(os.environ.get('OWNED_IO_SOURCE', PACKAGE / 'infrastructure/owned_io.py')), 'real_owned_io')
    parent = ModuleType('infrastructure'); parent.__path__ = []
    monkeypatch.setitem(sys.modules, 'infrastructure', parent)
    monkeypatch.setitem(sys.modules, 'infrastructure.owned_io', host)
    app = (tmp_path / 'app').resolve(); (app / 'ops').mkdir(parents=True)
    entry = app / 'ops/run_manager_us_activation_canary.py'; entry.write_bytes(SOURCE.read_bytes())
    monkeypatch.setattr(gate, '_canary_app_inventory', lambda a,k: {
        'ops/run_manager_us_activation_canary.py': hashlib.sha256(entry.read_bytes()).hexdigest()})
    with tempfile.TemporaryDirectory(prefix='manager-us-activation-canary-') as tmp:
        sandbox=Path(tmp).resolve(); data=sandbox/'data'; data.mkdir()
        (data/'old-artifact.json').write_text('{}')
        receipt=sandbox/'receipt.json'; identity=sandbox/'identity.json'
        argv=['--data-root',str(data),'--sandbox-identity',str(identity),'--receipt',str(receipt)]
        kwargs=dict(data_root=data,receipt_path=receipt,app_root=app,argv=argv)
        written=gate.write_canary_sandbox_identity(identity,'us',**kwargs)
        checked=gate.claim_canary_sandbox_identity(identity,'us',**kwargs)
        assert checked['status']=='VERIFIED'
        assert checked['run_id']==written['run_id']
        assert (data/'old-artifact.json').read_text()=='{}'
        with pytest.raises(ValueError):
            gate.claim_canary_sandbox_identity(identity,'us',**kwargs)
