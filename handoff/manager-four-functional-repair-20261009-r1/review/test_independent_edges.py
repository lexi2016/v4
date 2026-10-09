"""Independent offline probes. Every owner artifact is a labelled fixture.

Production validators, create_app, readers, POST owner, and GET are unchanged.
Only source transport/files and clocks are test-bound. This is not Mac evidence.
"""
from datetime import datetime, timedelta
import hashlib
import importlib

from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api import manager_research_router as api
from domains import manager_research_evidence as authority_evidence
from tests.test_manager_four_app_wiring import (
    PARAMS, build_app, configure_environment, membership,
)
from tests.test_manager_four_hk_readers import (
    ENV_KEYS, publish_test_v2, synthetic_hk_calendar,
    synthetic_authority_observation_clock,
)
from tests.test_manager_four_plan_owner_readback import _bind_nonempty_original_archive
from tests.test_manager_four_announcement_integration import (
    app_lane, _capture, _register, _import, _workspace,
)
from v4.manager_research.workspace_projection import FLAGS


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def read(client, **changes):
    result = client.get('/api/v4/manager/research/workspace',
                        params={**PARAMS, 'view': 'dynamic', **changes})
    assert result.status_code == 200, result.text
    value = result.json()
    assert all(value[key] is flag for key, flag in FLAGS.items())
    return value


def refresh(client):
    result = client.post('/api/v4/manager/research/workspace/refresh',
                         params=PARAMS, headers={'Origin': 'http://testserver'})
    assert result.status_code == 200, result.text
    return result.json()


def channel(value, name):
    return next(row for row in value['daily_channels']['channels']
                if row['channel'] == name)


def test_app_constructed_unbound_stays_unbound_after_late_environment_binding(
        tmp_path, monkeypatch, build_app):
    first_app, first_service = build_app('started-before-config')
    binding, built = publish_test_v2(tmp_path / 'late-authority')
    configure_environment(monkeypatch, binding)
    second_app, _ = build_app('started-after-config')
    with TestClient(first_app) as client:
        scope = membership(read(client))
        assert scope['gaps'] == ['HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND']
        assert scope['status'] == 'CANNOT_CONFIRM'
        assert first_service._workspace_connect_binding['universe_root'] == ''
    with TestClient(second_app) as client:
        scope = membership(read(client))
        assert scope['status'] == 'OWNER_VERIFIED'
        assert scope['source']['run_id'] == built['run_id']


@pytest.mark.parametrize('case', [
    'false', 'string', 'owner_root_type', 'owner_sha_type',
    'nul_root', 'invalid_d1_roots',
])
def test_app_explicit_invalid_configuration_never_borrows_a_valid_environment(
        tmp_path, monkeypatch, build_app, case):
    valid, _ = publish_test_v2(tmp_path / 'valid-ambient-authority')
    configure_environment(monkeypatch, valid)
    binding = dict(valid)
    if case == 'false':
        binding = False
    elif case == 'string':
        binding = 'invalid-config'
    elif case == 'owner_root_type':
        binding['authority_owner_root'] = {'invalid': 'type'}
    elif case == 'owner_sha_type':
        binding['authority_owner_sha256'] = ['a' * 64]
    elif case == 'nul_root':
        binding['universe_root'] = str(tmp_path / 'invalid') + '\x00'
    else:
        binding['authority_owner_sha256'] = '0' * 64
        binding['capture_receipt_root'] = ['bad-path-type']
        binding['dispatch_receipt_root'] = {'bad': 'path-type'}
    application, service = build_app('invalid-' + case, workspace_connect_binding=binding)
    before = snapshot(service.store.root)
    with TestClient(application) as client:
        value = read(client)
    scope = membership(value)
    assert scope['status'] == 'CANNOT_CONFIRM'
    assert scope['codes'] == []
    assert scope['identity'] is None
    assert scope['gaps']
    hk = channel(value, 'HK_CONNECT')
    assert hk['status'] == 'CANNOT_CONFIRM'
    assert hk['candidate_count'] is None
    assert snapshot(service.store.root) == before


def test_real_app_nonempty_plan_keeps_identity_across_midnight_and_get_remains_read_only(
        tmp_path, monkeypatch, build_app):
    binding, built = publish_test_v2(tmp_path / 'nonempty-authority')
    application, service = build_app('nonempty-app', workspace_connect_binding=binding)
    _bind_nonempty_original_archive(service, tmp_path / 'nonempty-original-archive')
    with TestClient(application) as client:
        first = refresh(client)
        assert [row['symbol'] for row in first['stocks']] == ['HK.01234']
        assert first['plan_product']['status'] == 'CURRENT'
        before = snapshot(service.store.root)
        prior_time = membership(first)['source']['read_at']

        class AfterMidnight(datetime):
            @classmethod
            def now(cls, tz=None):
                instant = datetime.fromisoformat('2026-10-10T00:05:00+08:00')
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        runtime = type(service).__module__.rsplit('.', 1)[0]
        monkeypatch.setattr(api, 'datetime', AfterMidnight)
        monkeypatch.setattr(importlib.import_module(runtime + '.workspace'), 'datetime', AfterMidnight)
        monkeypatch.setattr(authority_evidence, 'datetime', AfterMidnight)

        def forbidden(*args, **kwargs):
            pytest.fail('Read-only GET attempted an owner refresh')

        for name in ('refresh_workspace_plan', 'refresh_announcements',
                     'refresh_catalyst_observations', 'refresh_us_mapping_research'):
            monkeypatch.setattr(service, name, forbidden)
        current = read(client)
        assert membership(current)['source']['read_at'] != prior_time
        assert membership(current)['source']['run_id'] == built['run_id']
        assert current['input_identity'] == first['input_identity']
        assert current['plan_context'] == first['plan_context']
        assert current['plan_product']['status'] == 'CURRENT'
        assert current['plan_product']['consumed'] is True
        assert current['plan_product']['run_id'] == first['plan_product']['run_id']
        assert current['plan_product']['sha256'] == first['plan_product']['sha256']
        assert current['plan_product']['run_readback']['status'] == 'VERIFIED'
        assert [row['symbol'] for row in current['stocks']] == ['HK.01234']
        assert current['plan_product']['execution_context']['natural_run_verified'] is False
        assert snapshot(service.store.root) == before


def test_real_app_corrupted_authority_cannot_reuse_an_earlier_nonempty_current_plan(
        tmp_path, build_app):
    binding, built = publish_test_v2(tmp_path / 'later-corrupted-authority')
    application, service = build_app('corrupted-app', workspace_connect_binding=binding)
    _bind_nonempty_original_archive(service, tmp_path / 'corrupted-original-archive')
    with TestClient(application) as client:
        first = refresh(client)
        assert [row['symbol'] for row in first['stocks']] == ['HK.01234']
        artifact = binding['universe_root'] / built['paths']['artifact_relative']
        artifact.write_bytes(artifact.read_bytes() + b' ')
        before = snapshot(service.store.root)
        current = read(client)
    assert membership(current)['status'] == 'CANNOT_CONFIRM'
    assert membership(current)['codes'] == []
    assert current['stocks'] == []
    assert current['input_identity'] != first['input_identity']
    assert current['plan_product']['status'] == 'STALE_INPUTS_CHANGED'
    assert current['plan_product']['consumed'] is False
    assert current['plan_product']['run_id'] == first['plan_product']['run_id']
    assert current['plan_product']['run_readback']['status'] == 'CANNOT_CONFIRM'
    assert channel(current, 'HK_CONNECT')['status'] == 'CANNOT_CONFIRM'
    assert channel(current, 'HK_CONNECT')['candidate_count'] is None
    assert snapshot(service.store.root) == before


def test_registered_announcement_changes_saved_plan_and_original_post_restores_current(app_lane):
    lane = app_lane
    initial = refresh(lane.client)
    assert initial['plan_product']['status'] == 'CURRENT'
    assert channel(initial, 'ANNOUNCEMENT')['status'] == 'CANNOT_CONFIRM'
    registered = _register(lane, _capture(lane))
    imported = _import(lane, registered)
    before, calls_before = snapshot(lane.root), list(lane.source_calls)
    stale, announcement = _workspace(lane)
    assert announcement['status'] == 'READY'
    assert announcement['candidate_count'] == 1
    assert stale['input_identity'] != initial['input_identity']
    assert stale['plan_product']['status'] == 'STALE_INPUTS_CHANGED'
    assert stale['plan_product']['consumed'] is False
    assert snapshot(lane.root) == before
    assert lane.source_calls == calls_before

    lane.clock['now'] += timedelta(seconds=2)
    rebuilt = refresh(lane.client)
    assert rebuilt['plan_product']['status'] == 'CURRENT'
    assert rebuilt['plan_product']['run_id'] != initial['plan_product']['run_id']
    before = snapshot(lane.root)
    current, announcement = _workspace(lane)
    assert current['plan_product']['status'] == 'CURRENT'
    assert current['plan_product']['consumed'] is True
    assert current['plan_product']['run_readback']['status'] == 'VERIFIED'
    assert current['plan_product']['sha256'] == rebuilt['plan_product']['sha256']
    assert current['input_identity'] == rebuilt['input_identity']
    check = announcement['product_checks'][0]
    assert check['evidence_run_id'] == registered['evidence_run_id']
    assert check['product_sha256'] == registered['product_sha256']
    assert check['owner_import_receipt_sha256'] == imported['owner_receipt_sha256']
    assert snapshot(lane.root) == before
    assert lane.source_calls == calls_before
