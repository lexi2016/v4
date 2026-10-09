"""Offline original-owner continuity checks for the fixed four-issue repair.

The fixture uses real temporary ResearchPeripheralStore/ManagerResearchStore,
the original US reader and owners, and the R2 router. The input prices and
relation files are synthetic. These tests do not run create_app, read Mac
state, prove market coverage, or establish a live/natural-run result.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from test_manager_us_mapping_research import _synthetic_us_payload
from test_manager_four_hk_readers import (
    publish_test_v2, synthetic_hk_calendar, synthetic_authority_observation_clock,
)
from apps.api.v35_api import manager_research_router as api
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from v4.manager_research import us_mapping_research as mapping, workspace
from v4.manager_research.contracts import sha256_json
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader
from v4.manager_research.us_mapping_research import _read_exact_run
from v4.manager_research.workspace_projection import FLAGS, HK, digest


TARGET = '20261009'
SESSION = '20261008'
PAGE = {'date': TARGET, 'view': 'dynamic', 'selection_date': TARGET,
        'announcement_date': SESSION}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for key in ('V4_MANAGER_UNIVERSE_ROOT', 'V4_MANAGER_UNIVERSE_OWNER_ROOT',
                'V4_MANAGER_UNIVERSE_OWNER_SHA256', 'V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT',
                'V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT', 'V4_MANAGER_VIBE_BINDING'):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def owner(tmp_path, monkeypatch):
    clock = {'now': datetime(2026, 10, 9, 7, 0, tzinfo=HK)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            current = clock['now']
            return cls.fromtimestamp(current.timestamp(), tz) if tz else cls.fromtimestamp(current.timestamp())

    for module in (api, mapping, workspace):
        monkeypatch.setattr(module, 'datetime', Clock)
    # Only the external relation-file locations and clock are test-bound.
    # Their integrity/availability readers and the original algorithm run.
    seed = {
        'schema_version': 'v4.manager_research.us_mapping_reviewed.v1',
        'target_trade_date': '20260930', 'report': {'sha256': 'b' * 64},
        'status': 'SYNTHETIC_REGRESSION_ONLY', 'cards': [
            {'daily_match_symbols': [symbol], 'hk_symbol': f'HK.{index:05d}',
             'hk_name': f'Synthetic relation {index}', 'relationship_type': 'PRODUCT_PEER',
             'reason': 'SYNTHETIC_REGRESSION_ONLY', 'official_sources': [],
             'limitations': ['No historical or live evidence']}
            for index, symbol in enumerate(('LITE', 'AVGO', 'COHR', 'CIEN'), 1)
        ], **FLAGS,
    }
    seed['artifact_sha256'] = sha256_json(seed)
    seed_path = tmp_path / 'synthetic-reviewed-relations.json'
    seed_path.write_text(json.dumps(seed, sort_keys=True), encoding='utf-8')
    registry = {
        'schema_version': 'v4.manager_research.us_mapping_relation_registry.v1',
        'source_seed_sha256': hashlib.sha256(seed_path.read_bytes()).hexdigest(),
        'source_report_sha256': seed['report']['sha256'],
        'available_at': '2026-10-01T00:00:00+08:00',
        'availability_basis': 'V4_RELEASE_PUBLICATION', 'release_id': 'SYNTHETIC_REGRESSION_ONLY',
        'release_manifest_sha256': 'c' * 64, 'deployment_receipt_sha256': 'd' * 64,
    }
    registry['artifact_sha256'] = sha256_json(registry)
    registry_path = tmp_path / 'synthetic-relation-registry.json'
    registry_path.write_text(json.dumps(registry, sort_keys=True), encoding='utf-8')
    monkeypatch.setattr(mapping, 'REVIEWED_PATH', seed_path)
    monkeypatch.setattr(mapping, 'RELATION_REGISTRY_PATH', registry_path)
    source_root = tmp_path / 'synthetic-original-us-owner'
    source = ResearchPeripheralStore(source_root)
    master = tmp_path / 'synthetic-missing-hk-authority'
    master.mkdir()
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path / 'isolated-manager-state'), None, None,
        workspace_security_master_root=master,
        workspace_us_market_reader=ResearchPeripheralUsMarketReader(source_root),
    )
    application = FastAPI()
    application.include_router(api.create_manager_research_router(service))
    try:
        with TestClient(application) as client:
            yield service, source, client, clock
    finally:
        service.close()


def _files(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def _run_original_owners(service, clock):
    daily = service.refresh_us_mapping_research(TARGET, now=clock['now'],
        execution_context={'trigger_kind': 'MANUAL', 'timing': 'LATE_CATCHUP'})
    # The plan cutoff is after mapping publication, as the existing page
    # action already requires. Do not reuse an earlier click/start cutoff.
    clock['now'] += timedelta(seconds=2)
    plan = service.refresh_workspace_plan(TARGET, execution_kind='MANUAL_REFRESH',
        now=clock['now'],
        execution_context={'trigger_kind': 'MANUAL', 'timing': 'LATE_CATCHUP'},
        workspace_date_bindings={'selection_date': TARGET, 'announcement_date': SESSION})
    return daily, plan


def _read(client, params=None):
    response = client.get('/api/v4/manager/research/workspace', params=params or PAGE)
    assert response.status_code == 200, response.text
    return response.json()


def _assert_chain(service, value, daily):
    saved = service.get_workspace_plan(TARGET)
    product = value['plan_product']
    assert product['status'] == 'CURRENT'
    assert product['consumed'] is True
    assert product['run_id'] == saved['run_id']
    assert product['sha256'] == saved['sha256']
    assert saved['sha256'] == digest({key: item for key, item in saved.items() if key != 'sha256'})
    assert value['input_identity'] == saved['input_identity'] == saved['workspace']['input_identity']

    exact_attempt = service.store._read(service.store.root / 'workspace_plan_runs' / TARGET /
                                       (saved['run_id'] + '.json'))
    assert exact_attempt['sha256'] == digest({key: item for key, item in exact_attempt.items() if key != 'sha256'})
    assert exact_attempt['run_id'] == saved['run_id']
    assert exact_attempt['input_identity'] == saved['input_identity']
    assert value['workspace_plan_attempt'] == exact_attempt
    readback = product['run_readback']
    assert readback['status'] == 'VERIFIED'
    assert readback['run_id'] == readback['owner_attempt_run_id'] == saved['run_id']
    assert readback['artifact_sha256'] == saved['sha256']
    assert readback['owner_attempt_sha256'] == exact_attempt['sha256']
    assert readback['input_identity'] == saved['input_identity']

    exact_daily = _read_exact_run(service.store, TARGET, daily['run_id'], daily['artifact_sha256'])
    assert exact_daily['artifact_sha256'] == daily['artifact_sha256']
    reference = value['owner_chain']['us_mapping_daily_plan_reference']
    assert reference['status'] == 'CONSUMED'
    assert reference['run_id'] == daily['run_id']
    assert reference['artifact_sha256'] == daily['artifact_sha256']
    assert reference['target_trade_date'] == TARGET
    assert value['date_bindings'] == {'plan_date': TARGET, 'selection_date': TARGET,
                                      'announcement_date': SESSION}
    assert all(value[key] is flag for key, flag in FLAGS.items())


def test_original_daily_owner_to_saved_plan_to_get_preserves_exact_sha_chain(owner):
    service, source, client, clock = owner
    source.publish(_synthetic_us_payload(SESSION, {}))
    store, reader = service.store, service._workspace_us_market_reader
    daily, plan = _run_original_owners(service, clock)
    _assert_chain(service, plan, daily)
    assert daily['coverage']['full_market_coverage'] is False
    assert daily['coverage']['reviewed_us_symbol_count'] == 4
    # Missing announcement/HK inputs still make the original plan PARTIAL.
    assert plan['workspace_plan_attempt']['state'] == 'PARTIAL'
    assert all(channel['status'] == 'CANNOT_CONFIRM'
               for channel in plan['daily_channels']['channels'])

    before = _files(store.root)
    clock['now'] += timedelta(seconds=45)
    read = _read(client)
    _assert_chain(service, read, daily)
    assert service.store is store
    assert service._workspace_us_market_reader is reader
    assert read['plan_context']['research_cutoff'] == plan['plan_context']['research_cutoff']
    assert read['plan_product']['execution_context']['natural_run_verified'] is False
    assert _files(store.root) == before


def test_changed_original_source_stays_stale_until_original_owners_refresh(owner):
    service, source, client, clock = owner
    publication = source.publish(_synthetic_us_payload(SESSION, {}))
    first_daily, first_plan = _run_original_owners(service, clock)
    before = _files(service.store.root)

    # The original CAS replacement preserves source history and receipts.
    # No raw file rewrite or second source/reader is needed to vary the input.
    source.replace(_synthetic_us_payload(SESSION, {'LITE': 4.75}),
        expected_sha256=publication['payload_sha256'], reason='SYNTHETIC_REGRESSION_ONLY')
    clock['now'] += timedelta(seconds=20)
    stale = _read(client)
    assert stale['plan_product']['status'] == 'STALE_INPUTS_CHANGED'
    assert stale['plan_product']['consumed'] is False
    assert stale['plan_product']['run_readback']['status'] == 'CANNOT_CONFIRM'
    assert stale['input_identity'] != first_plan['input_identity']
    assert stale['plan_product']['run_id'] == first_plan['plan_product']['run_id']
    assert _files(service.store.root) == before

    second_daily, second_plan = _run_original_owners(service, clock)
    assert second_daily['run_id'] != first_daily['run_id']
    assert second_daily['artifact_sha256'] != first_daily['artifact_sha256']
    assert second_plan['plan_product']['run_id'] != first_plan['plan_product']['run_id']
    assert second_plan['input_identity'] != first_plan['input_identity']
    clock['now'] += timedelta(seconds=5)
    after = _files(service.store.root)
    _assert_chain(service, _read(client), second_daily)
    assert _files(service.store.root) == after


@pytest.mark.parametrize('different', [
    {'selection_date': '20261008'},
    {'announcement_date': '20261007'},
])
def test_different_selection_or_publication_never_consumes_saved_plan(owner, different):
    service, source, client, clock = owner
    source.publish(_synthetic_us_payload(SESSION, {}))
    _run_original_owners(service, clock)
    before = _files(service.store.root)
    read = _read(client, {**PAGE, **different})
    assert read['plan_product']['status'] == 'STALE_INPUTS_CHANGED'
    assert read['plan_product']['consumed'] is False
    assert read['plan_product']['run_readback']['status'] == 'CANNOT_CONFIRM'
    assert _files(service.store.root) == before


def test_different_target_has_no_saved_plan_fallback(owner):
    service, source, client, clock = owner
    source.publish(_synthetic_us_payload(SESSION, {}))
    _run_original_owners(service, clock)
    before = _files(service.store.root)
    read = _read(client, {**PAGE, 'date': '20261012', 'selection_date': '20261012'})
    assert read['target_trade_date'] == '20261012'
    assert read['plan_product']['status'] == 'NOT_MATERIALIZED'
    assert read['plan_product']['consumed'] is False
    assert read['plan_product']['run_id'] is None
    assert _files(service.store.root) == before


@pytest.mark.parametrize('corruption,expected', [
    ('product_sha', 'READBACK_FAILED'),
    ('missing_exact_attempt', 'OWNER_ATTEMPT_UNVERIFIED'),
    ('attempt_sha', 'OWNER_ATTEMPT_UNVERIFIED'),
])
def test_saved_run_or_product_integrity_failure_cannot_be_current(owner, corruption, expected):
    service, source, client, clock = owner
    source.publish(_synthetic_us_payload(SESSION, {}))
    _daily, plan = _run_original_owners(service, clock)
    run_id = plan['plan_product']['run_id']
    if corruption == 'product_sha':
        path = service.store.root / 'workspace_plans' / TARGET / 'latest.json'
        row = json.loads(path.read_bytes())
        row['workspace']['input_identity'] = 'f' * 64
        path.write_text(json.dumps(row), encoding='utf-8')
    else:
        path = service.store.root / 'workspace_plan_runs' / TARGET / (run_id + '.json')
        if corruption == 'missing_exact_attempt':
            path.unlink()
        else:
            row = json.loads(path.read_bytes())
            row['sha256'] = 'f' * 64
            path.write_text(json.dumps(row), encoding='utf-8')
    before = _files(service.store.root)
    read = _read(client)
    assert read['plan_product']['status'] == expected
    assert read['plan_product'].get('consumed') is not True
    assert _files(service.store.root) == before


def test_get_never_calls_either_original_producer(owner, monkeypatch):
    service, source, client, clock = owner
    source.publish(_synthetic_us_payload(SESSION, {}))
    daily, _plan = _run_original_owners(service, clock)
    before = _files(service.store.root)

    def forbidden(*args, **kwargs):
        pytest.fail('A read-only GET attempted to run an original producer')

    monkeypatch.setattr(service, 'refresh_us_mapping_research', forbidden)
    monkeypatch.setattr(service, 'refresh_workspace_plan', forbidden)
    monkeypatch.setattr(service, 'refresh_announcements', forbidden)
    monkeypatch.setattr(service, 'refresh_catalyst_observations', forbidden)
    _assert_chain(service, _read(client), daily)
    assert _files(service.store.root) == before


def test_workspace_passes_service_connect_binding_to_original_reader(owner):
    service, _source, client, _clock = owner
    # The actual app constructor is tested separately. This integration test
    # checks the next boundary: the existing workspace must use that service
    # binding, and expose the original reader's fail-closed diagnostic.
    service._workspace_connect_binding = {'universe_root': 'relative-invalid-owner-root'}
    before = _files(service.store.root)
    read = _read(client)
    membership = read['selection_diagnostics']['membership']
    assert membership['status'] == 'CANNOT_CONFIRM'
    assert membership['gaps'] == ['HK_CONNECT_TARGET_AUTHORITY_ROOT_INVALID']
    assert _files(service.store.root) == before


def test_changed_connect_authority_binding_is_stale_until_original_plan_owner_refreshes(
        owner, tmp_path, synthetic_hk_calendar, synthetic_authority_observation_clock):
    service, source, client, clock = owner
    binding_a, built_a = publish_test_v2(tmp_path / 'synthetic-authority-a')
    binding_b, built_b = publish_test_v2(tmp_path / 'synthetic-authority-b',
        codes=('HK.08888', 'HK.09999'))
    source.publish(_synthetic_us_payload(SESSION, {}))
    clock['now'] = datetime(2026, 10, 9, 9, 0, tzinfo=HK)
    store, us_reader = service.store, service._workspace_us_market_reader
    service._workspace_connect_binding = binding_a
    daily, first = _run_original_owners(service, clock)
    membership_a = first['selection_diagnostics']['membership']
    assert membership_a['status'] == 'OWNER_VERIFIED', membership_a['gaps']
    assert membership_a['source']['run_id'] == built_a['run_id']
    assert membership_a['source']['sha256'] == built_a['artifact_sha256']
    _assert_chain(service, _read(client), daily)
    before = _files(store.root)

    # A different, fully verified target-date authority is a different plan
    # input. Merely changing the binding must not consume the older plan.
    service._workspace_connect_binding = binding_b
    clock['now'] += timedelta(seconds=10)
    stale = _read(client)
    membership_b = stale['selection_diagnostics']['membership']
    assert membership_b['status'] == 'OWNER_VERIFIED', membership_b['gaps']
    assert membership_b['source']['run_id'] == built_b['run_id']
    assert membership_b['source']['sha256'] == built_b['artifact_sha256']
    assert membership_b['identity'] != membership_a['identity']
    assert stale['input_identity'] != first['input_identity']
    assert stale['plan_product']['status'] == 'STALE_INPUTS_CHANGED'
    assert stale['plan_product']['consumed'] is False
    assert stale['plan_product']['run_readback']['status'] == 'CANNOT_CONFIRM'
    assert _files(store.root) == before

    second = service.refresh_workspace_plan(TARGET, execution_kind='MANUAL_REFRESH',
        now=clock['now'],
        execution_context={'trigger_kind': 'MANUAL', 'timing': 'LATE_CATCHUP'},
        workspace_date_bindings={'selection_date': TARGET, 'announcement_date': SESSION})
    assert second['plan_product']['run_id'] != first['plan_product']['run_id']
    assert second['input_identity'] != first['input_identity']
    assert service.store is store
    assert service._workspace_us_market_reader is us_reader
    _assert_chain(service, second, daily)
    after = _files(store.root)
    _assert_chain(service, _read(client), daily)
    assert _files(store.root) == after


def _bind_nonempty_original_archive(service, root):
    """Make a temporary original archive + exact master, not a fake classifier."""
    from domains.research import build_research_archive
    from infrastructure.research_lane_source import ResearchLaneSource
    from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master

    observed = '2026-10-08T20:00:00+08:00'
    source = {
        'schema_version': 'SYNTHETIC_REGRESSION_ONLY', 'trade_date': SESSION,
        'source_manifest': {'generated_at': observed},
        'stock_research_timeline': [{
            'stock_code': '601099', 'stock_name': 'SYNTHETIC A-SHARE WRAPPER',
            'source_type': 'SYNTHETIC_RESEARCH', 'source_name': 'SYNTHETIC_REGRESSION_ONLY',
            'source_title': '示例制药临床研究进展',
            'source_path': 'synthetic-original-research-source',
            'url': 'https://fixture.invalid/synthetic-research',
            'theme': 'AI制药', 'evidence_sentence': '示例制药关键临床节点需确认。',
            'evidence_level': 'RESEARCH_OPINION', 'confidence': 'UNKNOWN',
            'event_time': observed, 'source_published_at': observed,
            'last_checked_at': observed, 'first_seen_at': observed,
        }],
        'stock_research_daily': [{'stock_code': '601099', 'stock_name': 'SYNTHETIC A-SHARE WRAPPER'}],
    }
    archive = ResearchLaneSource(root, ledger_root=root / 'isolated-ledger')
    archive.store.publish(build_research_archive(source, source_input_sha256=digest(source)), mode='REPLAY')
    service._existing_research_source = archive
    publish_hk_security_master(service._workspace_security_master_root, trade_date=SESSION,
        rows=[{'code': 'HK.01234', 'name': '示例制药-B', 'outstanding_shares': 1000}],
        universe_codes_sha256=digest(['HK.01234']), captured_at='2026-10-08T17:00:00+08:00')


def test_nonempty_plan_stays_current_when_only_connect_observation_clock_advances(
        owner, tmp_path, monkeypatch, synthetic_hk_calendar, synthetic_authority_observation_clock):
    import domains.manager_research_evidence as evidence

    service, source, client, clock = owner
    binding, _built = publish_test_v2(tmp_path / 'synthetic-nonempty-authority')
    service._workspace_connect_binding = binding
    _bind_nonempty_original_archive(service, tmp_path / 'synthetic-original-archive')
    source.publish(_synthetic_us_payload(SESSION, {}))
    clock['now'] = datetime(2026, 10, 9, 9, 0, tzinfo=HK)
    daily, first = _run_original_owners(service, clock)
    assert first['material_discovery_evidence']['cards'], first['material_discovery_evidence']
    assert [row['symbol'] for row in first['stocks']] == ['HK.01234']
    initial_read_at = first['selection_diagnostics']['membership']['source']['read_at']
    before = _files(service.store.root)

    class LaterObservationClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 9, 12, 1, tzinfo=HK).astimezone(tz)

    monkeypatch.setattr(evidence, 'datetime', LaterObservationClock)
    clock['now'] += timedelta(seconds=15)
    current = _read(client)
    assert current['selection_diagnostics']['membership']['source']['read_at'] != initial_read_at
    assert current['input_identity'] == first['input_identity']
    assert [row['symbol'] for row in current['stocks']] == ['HK.01234']
    _assert_chain(service, current, daily)
    assert _files(service.store.root) == before


def test_nonempty_plan_rechecks_changed_persisted_connect_availability(
        owner, tmp_path, synthetic_hk_calendar, synthetic_authority_observation_clock):
    service, source, client, clock = owner
    root = tmp_path / 'synthetic-availability-authority'
    binding, original = publish_test_v2(root)
    service._workspace_connect_binding = binding
    _bind_nonempty_original_archive(service, tmp_path / 'synthetic-availability-archive')
    source.publish(_synthetic_us_payload(SESSION, {}))
    clock['now'] = datetime(2026, 10, 9, 9, 0, tzinfo=HK)
    _daily, first = _run_original_owners(service, clock)
    assert [row['symbol'] for row in first['stocks']] == ['HK.01234']
    before = _files(service.store.root)
    # An internally consistent synthetic publication with a changed persisted
    # time is different evidence, even if still before cutoff and codes match.
    _binding, changed = publish_test_v2(root, available_at='2026-10-09T08:02:00+08:00')
    assert changed['artifact_sha256'] == original['artifact_sha256']
    assert changed['run_id'] == original['run_id']
    stale = _read(client)
    membership = stale['selection_diagnostics']['membership']
    assert membership['status'] == 'OWNER_VERIFIED'
    assert membership['source']['available_at'] == '2026-10-09T08:02:00+08:00'
    assert membership['identity'] == first['selection_diagnostics']['membership']['identity']
    assert stale['input_identity'] != first['input_identity']
    assert stale['plan_product']['status'] == 'STALE_INPUTS_CHANGED'
    assert stale['plan_product']['consumed'] is False
    assert _files(service.store.root) == before
