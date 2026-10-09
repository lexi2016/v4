"""Exact ordinary-page bindings recheck the real saved owner context."""
from datetime import datetime
from zoneinfo import ZoneInfo

from test_manager_announcement_parity_20261008 import _FixtureService, _client, _fixture, _import
from v4.manager_research import workspace as workspace_owner


HK = ZoneInfo('Asia/Hong_Kong')
TARGET = '20261008'


def test_manual_refresh_replays_only_the_saved_full_page_binding(tmp_path, monkeypatch):
    actual = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    import test_manager_announcement_parity_20261008 as fixture_module

    class FrozenRouterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return actual.astimezone(tz) if tz else actual.replace(tzinfo=None)

    monkeypatch.setattr(fixture_module.api, 'datetime', FrozenRouterClock)
    monkeypatch.setattr(fixture_module, 'NOW', datetime(2026, 10, 8, 10, 0, 3, tzinfo=HK))
    monkeypatch.setattr(workspace_owner, '_now', lambda: '2026-10-08T02:00:02+00:00')
    service = _FixtureService(tmp_path / 'manager-state')
    try:
        with _client(service) as client:
            default_refresh = client.post('/api/v4/manager/research/workspace/refresh',
                params={'date': TARGET}, headers={'Origin': 'http://testserver'})
            assert default_refresh.status_code == 200, default_refresh.text
            default_run = default_refresh.json()['plan_product']['run_id']

            default_read = client.get('/api/v4/manager/research/workspace',
                params={'date': TARGET, 'view': 'dynamic'})
            page_default_read = client.get('/api/v4/manager/research/workspace',
                params={'date': TARGET, 'view': 'dynamic', 'selection_date': TARGET,
                    'announcement_date': '20261007'})
            different_publication_read = client.get('/api/v4/manager/research/workspace',
                params={'date': TARGET, 'view': 'dynamic', 'selection_date': TARGET,
                    'announcement_date': '20261006'})
            assert default_read.status_code == page_default_read.status_code == 200
            assert different_publication_read.status_code == 200

            default_value = default_read.json()
            page_value = page_default_read.json()
            different_value = different_publication_read.json()
            assert default_value['plan_product']['run_id'] == default_run
            assert default_value['plan_product']['status'] == 'CURRENT'
            assert default_value['plan_product']['consumed'] is True
            default_readback = default_value['plan_product']['run_readback']
            assert default_readback['status'] == 'VERIFIED'
            assert default_readback['read_at'] == '2026-10-08T10:00:03+08:00'
            assert default_readback['read_at'] >= default_value['plan_product']['generated_at']
            assert page_value['date_bindings'] == {
                'plan_date': TARGET, 'selection_date': TARGET,
                'announcement_date': '20261007'}
            assert page_value['plan_product']['run_id'] == default_run
            assert page_value['plan_product']['status'] == 'CURRENT'
            assert page_value['plan_product']['consumed'] is True
            assert page_value['plan_context']['research_cutoff'] == '2026-10-08T10:00:00+08:00'
            assert 'announcement_publication_date' not in page_value['plan_context']
            assert different_value['plan_product']['status'] == 'STALE_INPUTS_CHANGED'
            assert different_value['plan_product']['consumed'] is False
            assert different_value['plan_context']['announcement_publication_date'] == '2026-10-06'

            explicit_refresh = client.post('/api/v4/manager/research/workspace/refresh',
                params={'date': TARGET, 'selection_date': TARGET,
                    'announcement_date': '20261006'},
                headers={'Origin': 'http://testserver'})
            assert explicit_refresh.status_code == 200, explicit_refresh.text
            explicit_run = explicit_refresh.json()['plan_product']['run_id']
            explicit_read = client.get('/api/v4/manager/research/workspace',
                params={'date': TARGET, 'view': 'dynamic', 'selection_date': TARGET,
                    'announcement_date': '20261006'})
            assert explicit_read.status_code == 200, explicit_read.text
            explicit_value = explicit_read.json()
            assert explicit_value['plan_product']['run_id'] == explicit_run
            assert explicit_value['plan_product']['status'] == 'CURRENT'
            assert explicit_value['plan_product']['consumed'] is True
            assert explicit_value['plan_context']['announcement_publication_date'] == '2026-10-06'
    finally:
        service.close()


def test_default_auto_get_reuses_exact_current_saved_context_but_owner_preview_does_not(tmp_path, monkeypatch):
    actual = datetime(2026, 10, 8, 10, 0, tzinfo=HK)
    import test_manager_announcement_parity_20261008 as fixture_module

    class FrozenRouterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return actual.astimezone(tz) if tz else actual.replace(tzinfo=None)

    monkeypatch.setattr(fixture_module.api, 'datetime', FrozenRouterClock)
    monkeypatch.setattr(fixture_module, 'NOW', datetime(2026, 10, 8, 10, 0, 3, tzinfo=HK))
    monkeypatch.setattr(workspace_owner, '_now', lambda: '2026-10-08T02:00:02+00:00')
    service = _FixtureService(tmp_path / 'manager-state')
    try:
        with _client(service) as client:
            posted = client.post('/api/v4/manager/research/workspace/refresh',
                params={'date': TARGET}, headers={'Origin': 'http://testserver'})
            assert posted.status_code == 200, posted.text
            saved = posted.json()
            saved_run = saved['plan_product']['run_id']

            # This is the browser's ordinary endpoint default: omit `view`,
            # retain all page bindings, and require the same owner run back.
            auto = client.get('/api/v4/manager/research/workspace', params={
                'date': TARGET, 'selection_date': TARGET, 'announcement_date': '20261007'})
            assert auto.status_code == 200, auto.text
            value = auto.json()
            assert value['plan_product']['run_id'] == saved_run
            assert value['plan_product']['status'] == 'CURRENT'
            assert value['plan_product']['consumed'] is True
            assert value['plan_product']['run_readback']['status'] == 'VERIFIED'
            assert value['plan_product']['run_readback']['read_at'] == '2026-10-08T10:00:03+08:00'
            assert value['date_bindings'] == {
                'plan_date': TARGET, 'selection_date': TARGET,
                'announcement_date': '20261007'}
            assert value['plan_context']['research_cutoff'] == '2026-10-08T10:00:00+08:00'

            wrong_selection = client.get('/api/v4/manager/research/workspace', params={
                'date': TARGET, 'selection_date': '20261007', 'announcement_date': '20261007'})
            assert wrong_selection.status_code == 200, wrong_selection.text
            assert wrong_selection.json()['plan_product']['status'] == 'STALE_INPUTS_CHANGED'

            # Import a later, source-bound current-owner product for the same
            # full date binding. The sealed plan must become stale after the
            # ordinary auto read re-runs the owner and compares identities.
            _, registration = _fixture(service, target=TARGET, publication='2026-10-07',
                run_id='f' * 32, reviewed_at='2026-10-08T00:00:00+00:00')
            assert registration is not None
            _import(client, registration)
            changed_source = client.get('/api/v4/manager/research/workspace', params={
                'date': TARGET, 'selection_date': TARGET, 'announcement_date': '20261007'})
            assert changed_source.status_code == 200, changed_source.text
            assert changed_source.json()['plan_product']['status'] == 'STALE_INPUTS_CHANGED'

        # A no-save owner evaluation starts at its actual requested clock and
        # cannot consume the sealed readback cutoff as a shortcut.
        preview_now = datetime(2026, 10, 8, 10, 0, 4, tzinfo=HK)
        preview = workspace_owner.get_workspace(
            service, TARGET, include_saved=False, view='dynamic', now=preview_now,
            selection_date=TARGET, announcement_date='20261007')
        assert preview['plan_context']['research_cutoff'] == '2026-10-08T10:00:04+08:00'
        assert 'plan_product' not in preview
    finally:
        service.close()
