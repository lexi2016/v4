"""Isolated real Main producer/materializer contracts; no Stage projection shim."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json

import pytest

from ops import run_zsxq_hourly_delta as producer
from ops import collect_hourly_research_input as collector
from ops import run_hourly_research as runner
from infrastructure import research_source_evidence as evidence
from infrastructure import manager_input_attestation as attest
from infrastructure.data_store import NativeDataStore
from infrastructure.research_store import HourlyResearchStore

DAY = '20261028'
SLOT = '0900'
TZ = ZoneInfo('Asia/Shanghai')
OWNER = Path(__file__).resolve().parents[1]


def at(clock):
    return datetime.fromisoformat(f'2026-10-28T{clock}+08:00')


class Clock(datetime):
    current = at('09:00:00')

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)


@pytest.fixture
def setup_clock(monkeypatch):
    Clock.current = at('09:00:00')
    for module in (producer, collector, runner, evidence, attest):
        monkeypatch.setattr(module, 'datetime', Clock)
    return Clock


def seed_source(root, monkeypatch, clock, *, partial=True):
    topic = {
        'topic_id': '12345678901234567', 'group_id': 'g',
        'create_time': '2026-10-28T08:59:00+08:00',
        'title': '平安银行研报', 'content_head': '平安银行业绩增长，只读研究资料。' * 30,
        'companies': [{'code': '000001', 'name': '平安银行'}],
        'themes': [{'theme': '银行'}],
    }
    monkeypatch.setattr(producer, 'collect_paginated_topics', lambda **kw: {
        'topics': [topic], 'bounded_has_more': partial, 'page_count': 1,
        'group_results': [{'group_id': 'g', 'source_has_more': partial, 'reached_since': False}],
    })
    def analyzer(*args):
        clock.current = at('09:01:00')
        return {'raw_topic_count': 1, 'effective_topic_count': 1, 'effective_topics': [topic]}
    return producer.materialize_zsxq_hourly_delta(
        data_root=root, trade_date=DAY, slot=SLOT, analyzer=analyzer,
        now=at('09:00:00'), groups=[('g', 'fixture')],
    )


def collect(root, clock):
    clock.current = at('09:02:00')
    return collector.build_hourly_research_input(data_root=root, business_date=DAY, slot=SLOT)


def materialize(root, clock):
    clock.current = at('09:05:00')
    return runner.run_hourly_research_file(data_root=root, source=None,
        business_date=DAY, target_date=DAY, slot=SLOT, mode='LIVE')


def test_real_partial_materialization_and_publication_cutoff(tmp_path, monkeypatch, setup_clock):
    clock = setup_clock
    source = seed_source(tmp_path, monkeypatch, clock)
    assert source['source_completed_at'] == at('09:01:00').isoformat(timespec='microseconds')
    assert evidence.read_zsxq_slot_evidence(tmp_path, DAY, SLOT) is not None
    original = collector._atomic_json
    def delayed_write(*args, **kwargs):
        result = original(*args, **kwargs)
        clock.current = at('09:04:00')
        return result
    monkeypatch.setattr(collector, '_atomic_json', delayed_write)
    result = collect(tmp_path, clock)
    assert result['status'] == 'PARTIAL_WITH_ROWS' and result['row_count'] == 1
    assert result['manager_publication']['status'] == 'VERIFIED_PUBLICATION'
    assert result['manager_publication']['available_at'] == at('09:04:00').isoformat(timespec='microseconds')
    incoming = tmp_path / result['source_path']
    input_sha = hashlib.sha256(incoming.read_bytes()).hexdigest()
    run = materialize(tmp_path, clock)
    assert run['hourly_artifact_status'] == 'PARTIAL_WITH_ROWS' and run['source_status'] == 'PARTIAL'
    assert run['hourly_publication']['available_at'] == at('09:05:00').isoformat(timespec='microseconds')
    # Same source generated at 09:02, but unavailable at input/publication boundaries.
    for cutoff in ('09:03:00', '09:04:30'):
        with pytest.raises(attest.PublicationError):
            attest._read_hourly_publication_metadata(data_root=tmp_path,owner_root=OWNER,date=DAY,slot=SLOT,mode='LIVE',as_of=at(cutoff))
    publication = attest._read_hourly_publication_metadata(data_root=tmp_path,owner_root=OWNER,date=DAY,slot=SLOT,mode='LIVE',as_of=at('09:06:00'))
    assert publication['source_input_sha256'] == input_sha
    assert hashlib.sha256(incoming.read_bytes()).hexdigest() == input_sha
    assert all(run[key] is False for key in ('production_allowed', 'buy_gate_updated', 'orders_sent'))
    clock.current = at('09:07:00')
    repeated = runner.run_hourly_research_file(data_root=tmp_path, source=None,
        business_date=DAY, target_date=DAY, slot=SLOT, mode='LIVE')
    assert repeated['hourly_publication'] == run['hourly_publication']
    assert repeated['latest_updated'] is False


@pytest.mark.parametrize('change', ['missing_clock', 'future_clock', 'cross_date', 'wrong_sha', 'missing_summary', 'tamper_summary'])
def test_partial_source_corruption_refused(tmp_path, monkeypatch, setup_clock, change):
    clock = setup_clock
    status = seed_source(tmp_path, monkeypatch, clock)
    path = tmp_path / status['status_path']
    if change == 'missing_clock': status.pop('source_completed_at')
    elif change == 'future_clock': status['source_completed_at'] = at('23:00:00').isoformat()
    elif change == 'cross_date': status['source_completed_at'] = '2026-10-29T09:01:00+08:00'
    elif change == 'wrong_sha': status['summary_sha256'] = '0' * 64
    elif change == 'missing_summary': Path(status['paths']['summary']).unlink()
    elif change == 'tamper_summary': Path(status['paths']['summary']).write_text('{}')
    path.write_text(json.dumps(status))
    assert evidence.read_zsxq_slot_evidence(tmp_path, DAY, SLOT) is None
    result = collect(tmp_path, clock)
    assert result['status'] == 'INPUT_MISSING'
    assert not (tmp_path / f'research/incoming/{DAY}/{SLOT}.json').exists()


def test_attestation_failure_does_not_report_published_success(tmp_path, monkeypatch, setup_clock):
    clock = setup_clock
    seed_source(tmp_path, monkeypatch, clock)
    def reject(*args, **kw): raise attest.PublicationError('INJECTED_FAILURE')
    monkeypatch.setattr(attest, 'publish_attestation', reject)
    result = collect(tmp_path, clock)
    assert result['status'] == 'INPUT_MISSING'
    assert result['materialization_status'] == 'PARTIAL_WITH_ROWS' and result['source_status'] == 'PARTIAL'
    with pytest.raises(attest.PublicationError): materialize(tmp_path, clock)
    assert HourlyResearchStore(tmp_path).read_exact(DAY, SLOT, mode='LIVE') is None


def test_full_ready_new_completion_contract_works(tmp_path, monkeypatch, setup_clock):
    clock = setup_clock
    seed_source(tmp_path, monkeypatch, clock, partial=False)
    assert collect(tmp_path, clock)['status'] == 'READY_WITH_RESEARCH_POOL'
    assert materialize(tmp_path, clock)['hourly_artifact_status'] == 'READY_WITH_RESEARCH_POOL'
    assert attest._read_hourly_publication_metadata(data_root=tmp_path,owner_root=OWNER,date=DAY,slot=SLOT,mode='LIVE',as_of=at('09:06:00'))['slot'] == SLOT


@pytest.mark.parametrize('change', ['input_tamper', 'sidecar_tamper', 'missing_archive_publication', 'archive_receipt_tamper', 'missing_source_witness'])
def test_publication_corruption_refused(tmp_path, monkeypatch, setup_clock, change):
    clock = setup_clock
    seed_source(tmp_path, monkeypatch, clock)
    incoming = collect(tmp_path, clock)
    materialize(tmp_path, clock)
    store = HourlyResearchStore(tmp_path)
    if change == 'input_tamper':
        (tmp_path / incoming['source_path']).write_text('{}')
    elif change == 'sidecar_tamper':
        path = tmp_path / (incoming['source_path'] + '.publication.json')
        value = json.loads(path.read_bytes());value['available_at'] = at('08:00:00').isoformat();path.write_text(json.dumps(value))
    elif change == 'missing_archive_publication':
        (tmp_path / f'research/hourly/publication/live/{DAY}/{SLOT}.json').unlink()
    elif change == 'missing_source_witness':
        payload = store.read_exact(DAY, SLOT, mode='LIVE')
        (tmp_path / f"research/hourly/source/{payload['source_input_sha256']}.json").unlink()
    else:
        path = tmp_path / store._receipt_relative(DAY, SLOT, 'LIVE')
        value = json.loads(path.read_bytes());value['fixture_tamper'] = True;path.write_text(json.dumps(value))
    with pytest.raises((OSError, ValueError)):
        attest._read_hourly_publication_metadata(data_root=tmp_path,owner_root=OWNER,date=DAY,slot=SLOT,mode='LIVE',as_of=at('09:06:00'))


def test_old_input_cannot_mint_completion_attestation(tmp_path, monkeypatch, setup_clock):
    clock = setup_clock
    seed_source(tmp_path, monkeypatch, clock)
    result = collect(tmp_path, clock)
    path = tmp_path / result['source_path']
    payload = json.loads(path.read_bytes());payload['source_manifest'].pop('publication_clock_contract')
    path.write_text(json.dumps(payload))
    with pytest.raises(attest.PublicationError, match='COMPLETION_CONTRACT_MISSING'):
        attest.publish_attestation(path, data_root=tmp_path, owner_root=OWNER)


def test_clocks_follow_real_artifact_writes(tmp_path, monkeypatch, setup_clock):
    clock = setup_clock
    original_write = NativeDataStore._write
    write_finished = []
    def write_and_advance(self, relative, value):
        result = original_write(self, relative, value)
        if relative.endswith('/zsxq_summary.json'):
            clock.current = at('09:01:30')
            write_finished.append(clock.current)
        return result
    monkeypatch.setattr(NativeDataStore, '_write', write_and_advance)
    status = seed_source(tmp_path, monkeypatch, clock)
    assert write_finished == [at('09:01:30')]
    assert datetime.fromisoformat(status['source_completed_at']) >= write_finished[0]
    collect(tmp_path, clock)
    original_publish = HourlyResearchStore.publish
    def publish_and_advance(self, *args, **kw):
        result = original_publish(self, *args, **kw)
        clock.current = at('09:05:30')
        write_finished.append(clock.current)
        return result
    monkeypatch.setattr(HourlyResearchStore, 'publish', publish_and_advance)
    run = materialize(tmp_path, clock)
    assert run['hourly_publication']['available_at'] == at('09:05:30').isoformat(timespec='microseconds')
    with pytest.raises(attest.PublicationError):
        attest._read_hourly_publication_metadata(data_root=tmp_path,owner_root=OWNER,date=DAY,slot=SLOT,mode='LIVE',as_of=at('09:05:15'))
    assert attest._read_hourly_publication_metadata(data_root=tmp_path,owner_root=OWNER,date=DAY,slot=SLOT,mode='LIVE',as_of=at('09:05:45'))['slot'] == SLOT


def test_old_ready_source_without_completion_is_unattested(tmp_path, monkeypatch, setup_clock):
    clock = setup_clock
    status = seed_source(tmp_path, monkeypatch, clock, partial=False)
    path = tmp_path / status['status_path']
    status.pop('source_completed_at');status.pop('summary_sha256');status.pop('fetch_result_sha256')
    path.write_text(json.dumps(status))
    result = collect(tmp_path, clock)
    assert result['status'] == 'INPUT_MISSING'
    assert result['manager_publication']['status'] == 'INPUT_MISSING'
    with pytest.raises((attest.PublicationError, ValueError, FileNotFoundError)):
        materialize(tmp_path, clock)


def test_forged_ready_cannot_certify_unfinished_window(tmp_path, monkeypatch, setup_clock):
    clock=setup_clock
    status=seed_source(tmp_path,monkeypatch,clock)
    status['status']='READY';status['cannot_confirm']=[]
    (tmp_path/status['status_path']).write_text(json.dumps(status))
    assert evidence.read_zsxq_slot_evidence(tmp_path,DAY,SLOT) is None
    assert producer._previous_success_time(tmp_path,DAY,'1000') is None
    with pytest.raises(ValueError,match='EXISTING_STATUS_NOT_VERIFIED'):
        producer.materialize_zsxq_hourly_delta(data_root=tmp_path,trade_date=DAY,slot=SLOT)
    assert collect(tmp_path,clock)['status']=='INPUT_MISSING'
    with pytest.raises(FileNotFoundError):materialize(tmp_path,clock)


def test_reached_lower_bound_is_complete_even_if_older_pages_remain(tmp_path,monkeypatch,setup_clock):
    clock=setup_clock
    status=seed_source(tmp_path,monkeypatch,clock)
    fetch_path=Path(status['paths']['fetch_result']);fetch=json.loads(fetch_path.read_bytes())
    fetch['groups'][0]['reached_since']=True
    fetch_path.write_text(json.dumps(fetch));status['fetch_result_sha256']=hashlib.sha256(fetch_path.read_bytes()).hexdigest()
    status['status']='READY';status['cannot_confirm']=[]
    (tmp_path/status['status_path']).write_text(json.dumps(status))
    assert evidence.read_zsxq_slot_evidence(tmp_path,DAY,SLOT).status['status']=='READY'
    assert producer._previous_success_time(tmp_path,DAY,'1000')==at('09:00:59')
    assert collect(tmp_path,clock)['status']=='READY_WITH_RESEARCH_POOL'
    assert materialize(tmp_path,clock)['hourly_artifact_status']=='READY_WITH_RESEARCH_POOL'


def test_metadata_without_original_scheduler_witness_is_not_pit_proof(tmp_path,monkeypatch,setup_clock):
    clock=setup_clock;seed_source(tmp_path,monkeypatch,clock);collect(tmp_path,clock);materialize(tmp_path,clock)
    with pytest.raises(attest.PublicationError,match='TIME_WITNESS_UNAVAILABLE'):
        attest.read_hourly_attestation(data_root=tmp_path,owner_root=OWNER,date=DAY,slot=SLOT,mode='LIVE',as_of=at('09:06:00'))


def test_changing_fetch_groups_without_rebinding_sha_cannot_make_ready(tmp_path,monkeypatch,setup_clock):
    clock=setup_clock;status=seed_source(tmp_path,monkeypatch,clock)
    path=Path(status['paths']['fetch_result']);fetch=json.loads(path.read_bytes())
    fetch['groups'][0]['reached_since']=True;path.write_text(json.dumps(fetch))
    status['status']='READY';status['cannot_confirm']=[]
    (tmp_path/status['status_path']).write_text(json.dumps(status))
    assert evidence.read_zsxq_slot_evidence(tmp_path,DAY,SLOT) is None
    assert producer._previous_success_time(tmp_path,DAY,'1000') is None
