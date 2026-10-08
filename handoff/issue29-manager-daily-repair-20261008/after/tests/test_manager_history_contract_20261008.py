"""Synthetic original-owner history regressions; no Mac or natural-run claim."""
from copy import deepcopy
from datetime import datetime, timedelta
import io
from pathlib import Path

import pytest

from v4.manager_research import workspace as w
from v4.manager_research import workspace_history as h
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore


READ_CONTRACT = '20260923.workspace-history-read.r1'
AFTER = datetime.fromisoformat('2026-10-08T16:00:00+08:00')


@pytest.fixture
def service(tmp_path):
    owner = ManagerResearchJobService(ManagerResearchStore(tmp_path/'manager'), None, None)
    try:
        yield owner
    finally:
        owner.close()


def _save(service, monkeypatch, date='20260930', *, kind='MANUAL_REFRESH'):
    hhmm = '08:00:00' if kind == 'SCHEDULED_MORNING' else '09:27:00'
    cutoff = datetime.fromisoformat(f'{date[:4]}-{date[4:6]}-{date[6:]}T{hhmm}+08:00')
    options = dict(now=cutoff, execution_kind=kind)
    if kind != 'MANUAL_REFRESH':
        deadline = '09:25:00' if kind == 'SCHEDULED_MORNING' else '09:30:00'
        options['deadline'] = datetime.fromisoformat(
            f'{date[:4]}-{date[4:6]}-{date[6:]}T{deadline}+08:00')
    with monkeypatch.context() as clock:
        clock.setattr(w, '_now', lambda:(cutoff+timedelta(seconds=1)).isoformat())
        service.refresh_workspace_plan(date, **options)
    saved = service.store._read(service.store.root/'workspace_plans'/date/'latest.json')
    # This field is produced and sealed by the original writer, not added by
    # a compatibility fixture to make an otherwise unknown contract pass.
    assert saved['workspace']['read_context']['contract'] == READ_CONTRACT
    return saved


def _source_comment(monkeypatch):
    """Expose changed source bytes to the real hasher without writing code."""
    target = Path(h.__file__)
    original = Path.open
    def opened(path, *args, **kwargs):
        if path == target and args and args[0] == 'rb':
            with original(path, 'rb') as handle:
                raw = handle.read()
            return io.BytesIO(raw + b'\n# Simulated source comment revision.\n')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', opened)
    return h.contract_identity()


def _files(store):
    return {str(path.relative_to(store.root)): path.read_bytes()
            for path in store.root.rglob('*') if path.is_file()}


def _reseal_latest(service, saved):
    saved['sha256'] = w.digest({key:value for key,value in saved.items() if key != 'sha256'})
    service.store._write_atomic(
        service.store.root/'workspace_plans'/saved['target_trade_date']/'latest.json', saved)


@pytest.mark.parametrize('date', ['20260929', '20260930'])
def test_source_comment_change_revalidates_same_contract_at_original_cutoff(service, monkeypatch, date):
    saved = _save(service, monkeypatch, date)
    current = _source_comment(monkeypatch)
    assert current != saved['read_contract_sha256']
    before = _files(service.store)
    result = service.get_workspace(date, view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is True, result['read_context']
    assert result['plan_product']['run_id'] == saved['run_id']
    assert result['plan_product']['sha256'] == saved['sha256']
    assert result['plan_product']['generated_at'] == saved['generated_at']
    assert result['plan_context'] == saved['workspace']['plan_context']
    assert result['workspace_plan_attempt']['state'] == 'PARTIAL'
    assert result['read_context']['status'] == 'VERIFIED_WITH_GAPS'
    assert result['read_context']['candidate_count_known'] is False
    proof = result['read_context']['reader_compatibility']
    assert proof['status'] == 'VERIFIED'
    assert proof['mode'] == 'SAME_CONTRACT_SOURCE_CHANGE'
    assert proof['saved_read_contract_sha256'] == saved['read_contract_sha256']
    assert proof['current_read_contract_sha256'] == current
    assert proof['saved_contract'] == READ_CONTRACT
    assert proof['source_stable_during_revalidation'] is True
    assert proof['saved_plan_modified'] is False
    assert 'historical_owner_revalidation' in result['read_metrics']['stages']
    assert _files(service.store) == before
    assert all(channel['natural_run_verified'] is False
               for channel in result['daily_channels']['channels'])


def test_two_saved_dates_never_substitute_each_others_product(service, monkeypatch):
    earlier = _save(service, monkeypatch, '20260929')
    later = _save(service, monkeypatch, '20260930')
    _source_comment(monkeypatch)
    before = _files(service.store)
    for expected in (later, earlier, later):
        date = expected['target_trade_date']
        result = service.get_workspace(date, view='historical', now=AFTER)
        assert result['plan_product']['consumed'] is True
        assert result['target_trade_date'] == date
        assert result['plan_product']['run_id'] == expected['run_id']
        assert result['read_context']['as_of'] == expected['workspace']['plan_context']['research_cutoff']
    absent = service.get_workspace('20260928', view='historical', now=AFTER)
    assert absent['plan_product']['consumed'] is False
    assert absent['plan_product']['run_id'] is None
    assert absent['read_context']['reason'] == 'HISTORY_QUALIFIED_SAVED_PLAN_MISSING'
    assert _files(service.store) == before


def test_cross_date_saved_file_is_rejected_without_replay(service, monkeypatch):
    _save(service, monkeypatch, '20260929')
    later = _save(service, monkeypatch, '20260930')
    # A complete, validly sealed different-day product is still invalid in
    # this date's directory; neither its SHA nor compatibility can admit it.
    service.store._write_atomic(service.store.root/'workspace_plans'/'20260929'/'latest.json', later)
    _source_comment(monkeypatch)
    monkeypatch.setattr(w, '_compute_workspace', lambda *a, **k:pytest.fail('cross-date product replayed'))
    before = _files(service.store)
    result = service.get_workspace('20260929', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is False
    assert result['read_context']['reason'] == 'HISTORY_PLAN_IDENTITY_INVALID'
    assert _files(service.store) == before


@pytest.mark.parametrize('contract, reason', [
    (None, 'HISTORY_READ_CONTRACT_UNPROVEN'),
    ('unrecognized-history-contract', 'HISTORY_READ_CONTRACT_UNSUPPORTED'),
])
def test_source_drift_without_supported_saved_contract_rejects_before_owner_replay(
        service, monkeypatch, contract, reason):
    saved = _save(service, monkeypatch)
    if contract is None:
        saved['workspace'].pop('read_context')
    else:
        saved['workspace']['read_context']['contract'] = contract
    _reseal_latest(service, saved)
    _source_comment(monkeypatch)
    monkeypatch.setattr(w, '_compute_workspace', lambda *a, **k:pytest.fail('unproven contract replayed'))
    result = service.get_workspace('20260930', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is False
    assert result['read_context']['reason'] == reason


@pytest.mark.parametrize('invalid', ['', 'z'*64, 'A'*64, '1'*63, 123, ['a'*64]])
def test_malformed_saved_reader_identity_has_distinct_rejection(service, monkeypatch, invalid):
    saved = _save(service, monkeypatch)
    saved['read_contract_sha256'] = invalid
    _reseal_latest(service, saved)
    monkeypatch.setattr(w, '_compute_workspace', lambda *a, **k:pytest.fail('malformed identity replayed'))
    result = service.get_workspace('20260930', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is False
    assert result['read_context']['reason'] == 'HISTORY_READER_IDENTITY_INVALID'


@pytest.mark.parametrize('field, value, reason', [
    ('input_identity', 'e'*64, 'HISTORY_SOURCE_INPUTS_CHANGED'),
    ('briefing', {'headline':'changed decision'}, 'HISTORY_FROZEN_PROJECTION_CHANGED'),
    ('summary', {'stock_count':99}, 'HISTORY_FROZEN_PROJECTION_CHANGED'),
    ('announcement_review', {'status':'NOT_RUN'}, 'HISTORY_FROZEN_PROJECTION_CHANGED'),
])
def test_source_drift_does_not_admit_changed_owner_inputs_or_business(
        service, monkeypatch, field, value, reason):
    _save(service, monkeypatch)
    _source_comment(monkeypatch)
    compute = w._compute_workspace
    def changed(*args, **kwargs):
        result = compute(*args, **kwargs)
        result[field] = deepcopy(value)
        return result
    monkeypatch.setattr(w, '_compute_workspace', changed)
    before = _files(service.store)
    result = service.get_workspace('20260930', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is False
    assert result['read_context']['reason'] == reason
    assert result['read_context']['reader_compatibility']['status'] == 'FAILED'
    assert result['read_context']['reader_compatibility']['reason'] == reason
    assert _files(service.store) == before


def test_source_change_during_revalidation_is_not_admitted(service, monkeypatch):
    saved = _save(service, monkeypatch)
    calls = iter([saved['read_contract_sha256'], 'd'*64])
    monkeypatch.setattr(h, 'contract_identity', lambda:next(calls, 'd'*64))
    before = _files(service.store)
    result = service.get_workspace('20260930', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is False
    assert result['read_context']['reason'] == 'HISTORY_READER_CHANGED_DURING_REVALIDATION'
    assert _files(service.store) == before


def test_legacy_without_fingerprint_preserves_full_replay(service, monkeypatch):
    saved = _save(service, monkeypatch)
    saved.pop('read_contract_sha256')
    saved['workspace'].pop('read_context')
    _reseal_latest(service, saved)
    before = _files(service.store)
    result = service.get_workspace('20260930', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is True
    assert result['read_context']['legacy_full_revalidation'] is True
    assert result['read_context']['reader_compatibility']['mode'] == 'LEGACY_FULL_REVALIDATION'
    assert result['read_context']['reader_compatibility']['saved_read_contract_sha256'] is None
    assert 'historical_owner_revalidation' in result['read_metrics']['stages']
    assert _files(service.store) == before


@pytest.mark.parametrize('field', ['published_at', 'available_at', 'retrieved_at'])
@pytest.mark.parametrize('invalid_time', [None, AFTER.isoformat()])
def test_source_drift_still_rejects_unproven_or_late_saved_evidence(
        service, monkeypatch, field, invalid_time):
    saved = _save(service, monkeypatch)
    cutoff = saved['workspace']['plan_context']['research_cutoff']
    material = dict(published_at=cutoff, available_at=cutoff, retrieved_at=cutoff)
    material[field] = invalid_time
    saved['workspace']['materials'] = [material]
    _reseal_latest(service, saved)
    _source_comment(monkeypatch)
    monkeypatch.setattr(w, '_compute_workspace', lambda *a, **k:pytest.fail('invalid PIT replayed'))
    result = service.get_workspace('20260930', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is False
    assert result['read_context']['reason'] == 'HISTORY_MATERIAL_PIT_UNVERIFIED'


def test_source_drift_still_rejects_changed_semantic_version(service, monkeypatch):
    saved = _save(service, monkeypatch)
    saved['workspace']['semantic_version'] = 'incompatible-version'
    _reseal_latest(service, saved)
    _source_comment(monkeypatch)
    monkeypatch.setattr(w, '_compute_workspace', lambda *a, **k:pytest.fail('new semantics replayed'))
    result = service.get_workspace('20260930', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is False
    assert result['read_context']['reason'] == 'HISTORY_SEMANTIC_VERSION_CHANGED'


@pytest.mark.parametrize('kind', ['SCHEDULED_PREOPEN', 'SCHEDULED_MORNING'])
def test_source_drift_requires_original_scheduled_attempt_and_preserves_kind(service, monkeypatch, kind):
    saved = _save(service, monkeypatch, kind=kind)
    _source_comment(monkeypatch)
    result = service.get_workspace('20260930', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is True, result['read_context']
    assert result['plan_product']['execution_kind'] == kind
    assert result['workspace_plan_attempt']['execution_kind'] == kind
    assert result['workspace_plan_attempt']['run_id'] == saved['run_id']
    path = service.store.root/'workspace_plan_runs'/'20260930'/(saved['run_id']+'.json')
    attempt = service.store._read(path)
    attempt['state'] = 'FAILED'
    attempt['failure_reasons'] = ['SYNTHETIC_ORIGINAL_OWNER_FAILED']
    service.store._write_atomic(path, w.seal_attempt(attempt))
    result = service.get_workspace('20260930', view='historical', now=AFTER)
    assert result['plan_product']['consumed'] is False
    assert result['read_context']['reason'] == 'HISTORY_PLAN_OWNER_ATTEMPT_INVALID'
