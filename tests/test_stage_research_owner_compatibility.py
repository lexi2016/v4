"""Synthetic owner selection boundaries; real completion witness, no producer runs.

Only the already-validated publication metadata and Stage trust setup are test
seams. Owner manifest/file validation and scheduler completion checks are real.
"""
import copy
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from infrastructure import manager_input_attestation as m


@pytest.fixture
def owners(tmp_path, monkeypatch):
    current, previous, oldest = [tmp_path / name / 'app' for name in ('current', 'previous', 'oldest')]
    bindings = []
    for app in (current, previous, oldest):
        for rel in m._MAIN_RESEARCH_FILES:
            path = app / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic-owner-code')
        (app / 'ops/run_hourly_research.py').write_bytes(b'same-materializer')
        entries = [dict(path=rel, kind='file', size=(app / rel).stat().st_size,
                        sha256=m.digest((app / rel).read_bytes())) for rel in sorted(m._MAIN_RESEARCH_FILES)]
        manifest = dict(schema_version='v4.runtime_graph_repair_release.v1', app_root=str(app),
            release_id=app.parent.name, RESEARCH_ONLY=True, production_allowed=False,
            buy_gate_updated=False, orders_sent=False,
            application_inventory=dict(entries=entries, entry_count=len(entries), aggregate_sha256=m.digest(
                json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())))
        raw = m.encoded(manifest)
        (app.parent / 'release-manifest.json').write_bytes(raw)
        bindings.append(dict(app_root=str(app), release_id=app.parent.name, manifest_sha256=m.digest(raw)))
    stage, data, ledger = [tmp_path / name for name in ('stage', 'data', 'ledger')]
    stage.mkdir()
    config = {'research_historical_owner_bindings': bindings[1:]}
    config_path = stage / 'stage_center_tick_config.json'
    config_path.write_text(json.dumps(config))
    payload = {'synthetic': 'no business output or source data'}
    artifact_ref = 'research/hourly/live/20261029/1300.json'
    payload_path = data / artifact_ref
    payload_path.parent.mkdir(parents=True)
    payload_path.write_bytes(m.encoded(payload)[:-1])
    record = dict(trade_date='20261029', slot='1300', mode='LIVE', artifact_ref=artifact_ref,
        artifact_sha256=m.digest(payload_path.read_bytes()), source_input_sha256='a' * 64,
        materializer_sha256=m.digest(b'same-materializer'), available_at='2026-10-29T13:00:01+08:00')
    publication = data / 'research/hourly/publication/live/20261029/1300.json'
    publication.parent.mkdir(parents=True)
    publication.write_bytes(m.encoded(record))
    cutoff = datetime(2026, 10, 29, 13, 5, tzinfo=ZoneInfo('Asia/Hong_Kong'))
    metadata_calls = []
    monkeypatch.setattr(m, 'trusted_research_owner', lambda *args: (current, ledger, ('current-pin',)))

    def metadata(**kwargs):
        assert kwargs['as_of'] is cutoff
        assert kwargs['data_root'] == data
        metadata_calls.append(kwargs['owner_root'])
        return copy.deepcopy(record)

    monkeypatch.setattr(m, '_read_hourly_publication_metadata', metadata)

    def dispatch(owner=previous, status='SUCCEEDED', mutation=None):
        workload = dict(workload_id='hourly_research', status='SUCCEEDED', exit_code=0,
            modules=['ops.run_zsxq_hourly_delta', 'ops.collect_hourly_research_input', 'ops.run_hourly_research'],
            production_allowed=False, buy_gate_updated=False, orders_sent=False,
            _authoritative_payload=dict(schema_version='v3_5.hourly_research_run.v1', status='SUCCEEDED',
                capture_origin='ORIGINAL_SLOT', business_date='20261029', target_date='20261029',
                slot='1300', mode='LIVE', payload_path=artifact_ref,
                payload_sha256=m.digest(m.encoded(payload)[:-1]), external_source_sha256='a' * 64,
                hourly_publication=copy.deepcopy(record), production_allowed=False,
                buy_gate_updated=False, orders_sent=False))
        receipt_ref = 'receipts/live/20261029/1300/' + 'b' * 32 + '.dispatch-receipt.json'
        value = dict(schema_version='v3_5.dispatch.v1', business_date='20261029', scheduled_date='20261029',
            target_date='20261029', slot='1300', mode='LIVE', run_id='b' * 32, receipt_path=receipt_ref,
            release_id=owner.parent.name, status=status, finished_at='2026-10-29T13:00:02+08:00',
            production_allowed=False, buy_gate_updated=False, orders_sent=False,
            workload_results=[workload], prev_ledger_sha256='')
        for key in ('selected_workload_ids', 'invoked_workload_ids', 'started_workload_ids', 'succeeded_workload_ids'):
            value[key] = ['hourly_research']
        if mutation:
            mutation(value)
        value['ledger_sha256'] = m.digest(m.encoded(value)[:-1])
        path = ledger / receipt_ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(m.encoded(value))
        return path

    def read():
        return m.read_stage_hourly_attestation(stage_app=stage, data_root=data, date='20261029',
            slot='1300', mode='LIVE', as_of=cutoff)

    return SimpleNamespace(**locals())


def test_same_materializer_uses_full_historical_completion_witness(owners):
    owners.dispatch()
    value, evidence = owners.read()
    assert value['completion_witness']['release_id'] == 'previous'
    assert owners.metadata_calls == [owners.current, owners.previous]
    assert 'v4_research_historical_owner_release_id=previous' in evidence
    assert 'v4_research_historical_owner_scope=READ_ONLY_IMMUTABLE_PROVENANCE_NO_EXECUTABLE_FALLBACK' in evidence


@pytest.mark.parametrize('owner_index', [0, 2])
def test_current_and_second_historical_owner_keep_original_reader(owners, owner_index):
    selected = [owners.current, owners.previous, owners.oldest][owner_index]
    owners.dispatch(owner=selected)
    value, evidence = owners.read()
    assert value['completion_witness']['release_id'] == selected.parent.name
    if owner_index == 0:
        assert evidence == ('current-pin',)
    else:
        assert 'v4_research_historical_owner_release_id=oldest' in evidence


@pytest.mark.parametrize('mutation', [
    lambda value: value.update(status='FAILED'),
    lambda value: value.update(release_id='unlisted-owner'),
    *[lambda value, key=key: value.update({key: []}) for key in
      ('selected_workload_ids', 'invoked_workload_ids', 'started_workload_ids', 'succeeded_workload_ids')],
    lambda value: value['workload_results'][0]['_authoritative_payload'].update(external_source_sha256='f' * 64),
    lambda value: value.update(production_allowed=True),
])
def test_no_complete_allowed_witness_still_rejected(owners, mutation):
    owners.dispatch(mutation=mutation)
    with pytest.raises(m.PublicationError, match='^HOURLY_COMPLETION_WITNESS_MISSING$'):
        owners.read()


@pytest.mark.parametrize(('mutation', 'error'), [
    (lambda value: value.update(finished_at='2026-10-29T13:10:00+08:00'), 'HOURLY_COMPLETION_AFTER_AS_OF'),
    (lambda value: value.update(finished_at='2026-10-29T13:00:00+08:00'), 'HOURLY_COMPLETION_CLOCK_INVALID'),
    (lambda value: value['workload_results'][0]['_authoritative_payload']['hourly_publication'].update(available_at='2026-10-29T13:00:00+08:00'), 'HOURLY_COMPLETION_PUBLICATION_RECORD_MISMATCH'),
    (lambda value: value.update(prev_ledger_sha256='c' * 64), 'HOURLY_COMPLETION_LEDGER_CHAIN_INVALID'),
])
def test_completion_errors_are_not_swallowed_by_another_owner(owners, mutation, error):
    owners.dispatch(owner=owners.current, mutation=mutation)
    with pytest.raises(m.PublicationError, match='^' + error + '$'):
        owners.read()
    assert owners.metadata_calls == [owners.current]


@pytest.mark.parametrize('error', ['CATALYST_PUBLICATION_IDENTITY_OR_SHA_MISMATCH',
    'CATALYST_SOURCE_RECEIPT_SHA_MISMATCH', 'HOURLY_PUBLICATION_AFTER_AS_OF'])
def test_publication_source_and_time_errors_do_not_fall_back(owners, monkeypatch, error):
    owners.dispatch()
    calls = []
    def reject(**kwargs):
        calls.append(kwargs['owner_root'])
        raise m.PublicationError(error)
    monkeypatch.setattr(m, '_read_hourly_publication_metadata', reject)
    with pytest.raises(m.PublicationError, match='^' + error + '$'):
        owners.read()
    assert calls == [owners.current]


def test_corrupt_ledger_is_not_swallowed(owners):
    path = owners.dispatch()
    value = json.loads(path.read_bytes())
    value['ledger_sha256'] = '0' * 64
    path.write_bytes(m.encoded(value))
    with pytest.raises(m.PublicationError, match='^HOURLY_COMPLETION_LEDGER_INVALID$'):
        owners.read()
    assert owners.metadata_calls == [owners.current]


@pytest.mark.parametrize('kind', ['too_many', 'duplicate', 'extra_key', 'pin_drift'])
def test_historical_allowlist_is_bounded_explicit_and_validated(owners, kind):
    config = copy.deepcopy(owners.config)
    if kind == 'too_many':
        config['research_historical_owner_bindings'].append(owners.bindings[0])
    elif kind == 'duplicate':
        config['research_historical_owner_bindings'][1] = owners.bindings[1]
    elif kind == 'extra_key':
        config['research_historical_owner_bindings'][0]['discovery'] = 'latest'
    else:
        config['research_historical_owner_bindings'][0]['manifest_sha256'] = '0' * 64
    owners.config_path.write_text(json.dumps(config))
    owners.dispatch(owner=owners.current)
    error = 'RESEARCH_RELEASE_MANIFEST_SHA_MISMATCH' if kind == 'pin_drift' else 'HOURLY_PROVENANCE_ALLOWLIST_INVALID'
    with pytest.raises(m.PublicationError, match='^' + error + '$'):
        owners.read()
    assert owners.metadata_calls == []


def test_unknown_materializer_is_rejected_before_witness_read(owners):
    owners.publication.write_text(json.dumps({**owners.record, 'materializer_sha256': '0' * 64}))
    with pytest.raises(m.PublicationError, match='^HOURLY_PROVENANCE_OWNER_NOT_ALLOWLISTED$'):
        owners.read()
    assert owners.metadata_calls == []
