"""Bounded official HKEX subset capture through the existing owner; offline fixture only."""
from datetime import datetime
from datetime import timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from announcement_autorun_fixtures import DAY, OwnerFixture
from apps.api.v35_api.manager_research_router import create_manager_research_router
from v4.manager_research.workspace_plan import plan_context


HK = timezone(timedelta(hours=8))


def _app(fixture):
    app = FastAPI()
    app.include_router(create_manager_research_router(fixture.service))
    return app


def test_targeted_route_uses_master_names_exact_bound_and_late_capture_cutoff(tmp_path, monkeypatch):
    fixture = OwnerFixture(tmp_path, monkeypatch, ('HK.00001', 'HK.09690', 'HK.00003'))
    fixture.now = datetime(2026, 9, 25, 12, 0, tzinfo=HK)
    fixture.add(code='HK.00001', text='The Company entered into an agreement.', slug='target-window')
    bounds = []
    original = fixture.provider.collect_announcement_batch

    def tracked_batch(**kwargs):
        bounds.append(kwargs['max_issuers'])
        return original(**kwargs)

    monkeypatch.setattr(fixture.provider, 'collect_announcement_batch', tracked_batch)
    params = [('date', DAY), ('issuer_codes', 'HK.00001'), ('issuer_codes', 'HK.09690')]
    with TestClient(_app(fixture)) as client:
        response = client.post('/api/v4/manager/research/announcements/refresh', params=params)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['source_scope'] == 'HKEX_OFFICIAL_EXPLICIT_ISSUER_SUBSET'
        assert result['coverage']['scope_type'] == 'EXPLICIT_ISSUER_LIST'
        assert result['coverage']['selected_issuer_count'] == 2
        assert result['coverage']['native_master_count'] == 3
        assert result['coverage']['all_master_issuers_included'] is False
        assert result['scope_coverage']['selected_issuer_codes'] == ['HK.00001', 'HK.09690']
        assert result['source_window']['start'] == plan_context(DAY, now=fixture.now)['market_session_close']
        assert result['source_window']['source_dates'] == ['20260923', DAY]
        assert result['product_identity']['query_as_of'] == '2026-09-24T23:59:59.999999+08:00'
        assert result['product_identity']['capture_cutoff'] == fixture.now.isoformat()
        assert len(result['official_documents']) == 1
        document = result['official_documents'][0]
        assert document['symbol'] == 'HK.00001'
        assert document['name'] == 'Fixture 00001'
        assert document['late_acquisition'] is True
        assert document['available_at'] == fixture.now.isoformat()
        assert bounds == [2]
        request_count = len(fixture.calls)
        readback = client.get('/api/v4/manager/research/announcements', params={
            'date': DAY, 'scope_id': result['scope_id']})
        assert readback.status_code == 200
        assert readback.json()['scope_id'] == result['scope_id']
        assert len(readback.json()['official_documents']) == 1
        assert len(fixture.calls) == request_count
        assert client.get('/api/v4/manager/research/announcements', params={
            'date': DAY, 'scope_id': 'bad-scope'}).status_code == 422
        too_many = [('date', DAY), *[('issuer_codes', f'HK.{i:05d}') for i in range(1, 26)]]
        assert client.post('/api/v4/manager/research/announcements/refresh', params=too_many).status_code == 422
        assert len(fixture.calls) == request_count
    fixture.service.close()


def test_resume_continues_pending_bodies_only_in_the_same_scope(tmp_path, monkeypatch):
    fixture = OwnerFixture(tmp_path, monkeypatch, ('HK.00001', 'HK.09690', 'HK.00003'))
    fixture.now = datetime(2026, 9, 25, 12, 0, tzinfo=HK)
    for index in range(5):
        fixture.add(code='HK.00001', minute=index, slug=f'pending-{index}')
    fixture.add(code='HK.09690', slug='scope-peer')
    bounds = []
    original = fixture.provider.collect_announcement_batch

    def tracked_batch(**kwargs):
        bounds.append((kwargs['max_issuers'], [row['code'] for row in kwargs['issuers']]))
        return original(**kwargs)

    monkeypatch.setattr(fixture.provider, 'collect_announcement_batch', tracked_batch)
    codes = ['HK.00001', 'HK.09690']
    first = fixture.service.refresh_announcements(DAY, issuer_codes=codes)
    assert first['coverage']['pending_document_count'] == 2
    scope_id = first['scope_id']
    request_count = len(fixture.calls)

    resumed = fixture.service.refresh_announcements(DAY, issuer_codes=codes, resume=True)
    assert resumed['scope_id'] == scope_id
    assert resumed['coverage']['pending_document_count'] == 0
    assert len(resumed['official_documents']) == 6
    assert bounds == [(2, codes), (2, [])]
    assert not [call for call in fixture.calls[request_count:] if call['method'] == 'POST']

    calls_before_wrong_scope = len(fixture.calls)
    with pytest.raises(ValueError, match='ANNOUNCEMENT_TARGETED_RESUME_PRODUCT_MISSING'):
        fixture.service.refresh_announcements(DAY, issuer_codes=['HK.00001'], resume=True)
    assert len(fixture.calls) == calls_before_wrong_scope
    scoped_product = fixture.service.store._read(
        fixture.service.store.root / 'workspace_announcements' / DAY / 'issuer_subsets' / scope_id / 'latest.json')
    assert scoped_product['scope'] == codes
    assert scoped_product['scope_coverage']['all_master_issuers_included'] is False
    fixture.service.close()


def test_targeted_capture_keeps_existing_unscoped_daily_partition_separate(tmp_path, monkeypatch):
    fixture = OwnerFixture(tmp_path, monkeypatch, ('HK.00001', 'HK.09690', 'HK.00003'))
    fixture.now = datetime(2026, 9, 25, 12, 0, tzinfo=HK)
    fixture.add(code='HK.00001', slug='same-owner')
    targeted = fixture.service.refresh_announcements(DAY, issuer_codes=['HK.00001'])
    ordinary = fixture.service.refresh_announcements(DAY)
    assert targeted['coverage']['native_master_count'] == 3
    assert targeted['coverage']['selected_issuer_count'] == 1
    daily_product = fixture.service.store._read(
        fixture.service.store.root / 'workspace_announcements' / DAY / 'latest.json')
    assert daily_product['context']['publication_window_mode'] == 'HK_CALENDAR_DAY_V1'
    assert daily_product['scope'] == ['HK.00001', 'HK.00003', 'HK.09690']
    assert 'scope_id' not in ordinary
    assert 'scope_id' not in fixture.service.get_announcements(DAY)
    scoped = fixture.service.get_announcements(DAY, scope_id=targeted['scope_id'])
    assert scoped['coverage']['selected_issuer_count'] == 1
    assert scoped['coverage']['all_master_issuers_included'] is False
    fixture.service.close()
