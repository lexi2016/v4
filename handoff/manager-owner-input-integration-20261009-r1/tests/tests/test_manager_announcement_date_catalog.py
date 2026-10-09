"""Focused contract tests for explicit-date Eastmoney listing catalogs."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.manager_research_router import create_manager_research_router
from v4.manager_research.ports import SourceResponse
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.materials import MaterialStore
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master
from v4.manager_research import announcement_catalog as catalog
from v4.manager_research import announcement_source


TARGET = '20260930'
PUBLICATION = '2026-09-29'
MASTER_NAMES = {'HK.00001': {'name': 'Fixture One'}, 'HK.00002': {'name': 'Fixture Two'}}
MASTER_WITNESS = dict(owner='load_verified_hk_security_master', source_date='20260929',
                      artifact_sha256='a' * 64)


def _row(index: int, *, art_code: str | None = None, notice_date: str = '2026-09-29 00:00:00',
         display_date: str = '2026-09-29', stock_code: str = '00001') -> dict:
    return dict(art_code=art_code or f'AN20260929{index:010d}', title=f'notice {index}',
        notice_date=notice_date, display_time=f'{display_date} 09:00:00:000',
        codes=[dict(market_code='116', stock_code=stock_code, ann_type='H', short_name='Fixture One')])


def _response(page: int, total: int, rows: list[dict], *, total_override: int | None = None) -> bytes:
    return json.dumps(dict(success=1, data=dict(page_index=page, page_size=20,
        total_hits=total if total_override is None else total_override, list=rows))).encode()


class _MemoryStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}


class _CaptureFixture:
    def __init__(self, monkeypatch, pages: dict[int, bytes], *, fail_pages: set[int] | None = None) -> None:
        self.store = _MemoryStore()
        self.pages = pages
        self.fail_pages = fail_pages or set()
        self.calls: list[tuple[int, str, bool]] = []

        def capture(provider, url, *, force=False):
            query = parse_qs(urlsplit(url).query)
            page = int(query['page_index'][0])
            self.calls.append((page, url, force))
            if page in self.fail_pages:
                raise RuntimeError('fixture request failed')
            raw = self.pages[page]
            body_sha = sha256(raw).hexdigest()
            blob_sha = sha256(b'envelope:' + raw).hexdigest()
            self.store.blobs[blob_sha] = raw
            return dict(request=dict(source='EASTMONEY_HK', method='GET', url=url),
                source_key='fixture:' + blob_sha, blob_sha256=blob_sha, body_sha256=body_sha,
                retrieved_at='2026-10-05T01:00:00+00:00', http_status=200,
                final_url=url, from_cache=False)

        def read(store, ref):
            return store.blobs[ref['blob_sha256']]

        monkeypatch.setattr(announcement_source, 'capture_eastmoney', capture)
        monkeypatch.setattr(announcement_source, 'read_eastmoney_response', read)


def _collect(fixture: _CaptureFixture, **kwargs):
    return catalog.collect_date_scoped_catalog(object(), fixture.store,
        target_trade_date=TARGET, publication_date=PUBLICATION,
        master_names=MASTER_NAMES, identity_witness=MASTER_WITNESS, **kwargs)


def test_date_url_uses_proven_query_and_does_not_use_latest_five_filter():
    url = catalog.date_scoped_url(PUBLICATION, 7)
    assert url == ('https://np-anotice-stock.eastmoney.com/api/security/ann?'
        'ann_type=H&client_source=web&f_node=0&begin_time=2026-09-29&end_time=2026-09-29'
        '&page_size=20&page_index=7')
    assert 'stock_list=' not in url and 'sr=' not in url
    with pytest.raises(ValueError, match='NOTICE_DATE_INVALID'):
        catalog.date_scoped_url('2026--09--29', 1)


def test_dynamic_pagination_proves_empty_terminal_and_preserves_display_mismatch(monkeypatch):
    rows = [_row(i, display_date='2026-09-30' if i == 1 else '2026-09-29') for i in range(1, 21)]
    rows2 = [_row(21)]
    fixture = _CaptureFixture(monkeypatch, {1: _response(1, 21, rows),
        2: _response(2, 21, rows2), 3: _response(3, 21, [])})
    result = _collect(fixture)

    assert result['status'] == 'COMPLETE'
    assert result['total_hits'] == result['captured_row_count'] == result['unique_art_code_count'] == 21
    assert result['expected_data_page_count'] == 2
    assert result['expected_terminal_page_index'] == 3 and result['terminal_empty_seen'] is True
    assert [call[0] for call in fixture.calls] == [1, 2, 3]
    assert all(call[2] is True for call in fixture.calls)
    assert result['display_notice_date_mismatch_count'] == 1
    assert len(result['source_rows']) == 21
    assert len(result['manager_consumer_rows']) == 21
    assert result['source_rows'][0]['display_notice_date_mismatch'] is True
    assert result['source_rows'][0]['notice_date'] == '2026-09-29 00:00:00'
    assert result['manager_consumer_use'] == 'CODE_INTERSECTION_ONLY_NOT_SELECTION_RESULT'
    assert result['content_body_fetch'] == result['attachment_fetch'] == 'NOT_REQUESTED'


def test_zero_total_is_complete_only_with_empty_page_one(monkeypatch):
    fixture = _CaptureFixture(monkeypatch, {1: _response(1, 0, [])})
    result = _collect(fixture)
    assert result['status'] == 'COMPLETE_EMPTY'
    assert result['expected_terminal_page_index'] == 1
    assert result['terminal_empty_seen'] is True
    assert result['captured_page_count'] == 1
    assert fixture.calls[0][0] == 1


def test_source_116_h_identifiers_are_preserved_even_when_not_numeric_master_tickers(monkeypatch):
    fixture = _CaptureFixture(monkeypatch, {1: _response(1, 1, [_row(1, stock_code='H5354')]),
        2: _response(2, 1, [])})
    result = _collect(fixture)
    assert result['status'] == 'COMPLETE'
    assert result['source_rows'][0]['source_codes_116_H'][0]['stock_code'] == 'H5354'
    assert 'EASTMONEY_CATALOG_HK_116_H_STOCK_CODE_MISSING' not in result['gaps']
    assert result['manager_consumer_rows'] == []


@pytest.mark.parametrize('stock_case', ['missing', 'null', 'empty'])
def test_missing_hk_source_stock_code_forces_partial_and_retains_original_row(monkeypatch, stock_case):
    row = _row(1)
    if stock_case == 'missing':
        row['codes'][0].pop('stock_code')
    elif stock_case == 'null':
        row['codes'][0]['stock_code'] = None
    else:
        row['codes'][0]['stock_code'] = ''
    original = json.loads(json.dumps(row))
    fixture = _CaptureFixture(monkeypatch, {1: _response(1, 1, [row]), 2: _response(2, 1, [])})

    result = _collect(fixture)

    assert result['status'] == 'PARTIAL'
    assert result['captured_row_count'] == 1
    assert result['source_rows'][0]['raw_row'] == original
    assert result['source_rows'][0]['source_codes_116_H'][0]['stock_code'] == original['codes'][0].get('stock_code')
    assert 'EASTMONEY_CATALOG_HK_116_H_STOCK_CODE_MISSING' in result['gaps']
    assert result['manager_consumer_rows'] == []


def test_duplicate_art_code_keeps_rows_but_forces_partial(monkeypatch):
    same = _row(1)
    fixture = _CaptureFixture(monkeypatch, {1: _response(1, 2, [same, dict(same)]),
        2: _response(2, 2, [])})
    result = _collect(fixture)
    assert result['status'] == 'PARTIAL'
    assert result['captured_row_count'] == 2 and result['unique_art_code_count'] == 1
    assert result['duplicate_art_codes'] == [same['art_code']]
    assert 'EASTMONEY_CATALOG_ART_CODE_DUPLICATE' in result['gaps']


def test_total_drift_and_cross_notice_date_are_partial_and_rows_are_retained(monkeypatch):
    fixture = _CaptureFixture(monkeypatch, {
        1: _response(1, 21, [_row(i, notice_date='2026-09-28 00:00:00' if i == 1 else '2026-09-29 00:00:00')
                            for i in range(1, 21)]),
        2: _response(2, 21, [_row(21)], total_override=22),
        3: _response(3, 21, []),
    })
    result = _collect(fixture)
    assert result['status'] == 'PARTIAL'
    assert result['captured_row_count'] == 21
    assert result['source_rows'][0]['notice_date'] == '2026-09-28 00:00:00'
    assert 'EASTMONEY_CATALOG_TOTAL_HITS_DRIFT' in result['gaps']
    assert 'EASTMONEY_CATALOG_NOTICE_DATE_MISMATCH' in result['gaps']


def test_missing_terminal_page_is_partial_without_retry(monkeypatch):
    fixture = _CaptureFixture(monkeypatch, {1: _response(1, 1, [_row(1)])}, fail_pages={2})
    result = _collect(fixture)
    assert result['status'] == 'PARTIAL'
    assert 'EASTMONEY_CATALOG_TERMINAL_PAGE_MISSING' in result['gaps']
    assert [call[0] for call in fixture.calls] == [1, 2]
    assert sum(call[0] == 2 for call in fixture.calls) == 1


def test_explicit_resume_reuses_verified_refs_and_only_requests_missing_page(monkeypatch):
    initial = _CaptureFixture(monkeypatch, {1: _response(1, 21, [_row(i) for i in range(1, 21)]),
        2: _response(2, 21, [_row(21)]), 3: _response(3, 21, [])}, fail_pages={2})
    first = _collect(initial)
    assert first['status'] == 'PARTIAL'
    refs = {page['page_index']: page['source_ref'] for page in first['page_receipts']
            if page['source_ref'] is not None and page['capture_status'] == 'PASS'}
    # Keep the same blob store but allow the missing page to be fetched now.
    initial.fail_pages.clear()
    resumed = _collect(initial, resume_refs=refs)
    assert resumed['status'] == 'COMPLETE'
    assert [call[0] for call in initial.calls].count(1) == 1
    assert [call[0] for call in initial.calls].count(3) == 1
    assert [call[0] for call in initial.calls].count(2) == 2


def test_catalog_product_readback_rederives_from_refs(monkeypatch):
    fixture = _CaptureFixture(monkeypatch, {1: _response(1, 1, [_row(1)]), 2: _response(2, 1, [])})
    result = _collect(fixture)
    validated = catalog.validate_product(result, target_trade_date=TARGET, publication_date=PUBLICATION)
    verified = catalog.verify_product_sources(validated, fixture.store)
    assert verified['status'] == 'COMPLETE'
    tampered = dict(validated)
    tampered['manager_consumer_row_count'] = 0
    tampered = catalog._seal(tampered)
    with pytest.raises(ValueError, match='PRODUCT_IDENTITY_INVALID|SOURCE_DERIVATION_MISMATCH'):
        catalog.verify_product_sources(tampered, fixture.store)


def test_api_requires_explicit_publication_date_and_routes_date_catalog_scope():
    class Owner:
        def __init__(self):
            self.refresh_calls = []
            self.read_calls = []

        def refresh_announcements(self, target_trade_date, **kwargs):
            self.refresh_calls.append((target_trade_date, kwargs))
            return {'target_trade_date': target_trade_date, **kwargs}

        def get_announcement_date_catalog(self, target_trade_date, publication_date):
            self.read_calls.append((target_trade_date, publication_date))
            return {'target_trade_date': target_trade_date, 'publication_date': publication_date}

    owner = Owner()
    app = FastAPI()
    app.include_router(create_manager_research_router(owner))
    with TestClient(app) as client:
        missing_date = client.post('/api/v4/manager/research/announcements/refresh', params={
            'date': TARGET, 'source_scope': catalog.SOURCE_SCOPE})
        assert missing_date.status_code == 422
        assert owner.refresh_calls == []
        refreshed = client.post('/api/v4/manager/research/announcements/refresh', params={
            'date': TARGET, 'source_scope': catalog.SOURCE_SCOPE,
            'publication_date': PUBLICATION, 'resume': 'true'})
        assert refreshed.status_code == 200, refreshed.text
        assert owner.refresh_calls == [(TARGET, {'resume': True, 'source_scope': catalog.SOURCE_SCOPE,
                                                   'publication_date': PUBLICATION})]
        readback = client.get('/api/v4/manager/research/announcements', params={
            'date': TARGET, 'source_scope': catalog.SOURCE_SCOPE, 'publication_date': PUBLICATION})
        assert readback.status_code == 200, readback.text
        assert owner.read_calls == [(TARGET, PUBLICATION)]


def test_existing_owner_persists_and_reuses_date_catalog_without_refetch(tmp_path, monkeypatch):
    trade_day = '20260924'
    now = datetime(2026, 9, 24, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    master_root = tmp_path / 'master'
    publish_hk_security_master(master_root, trade_date='20260923',
        rows=[dict(code='HK.00001', name='Fixture One')], universe_codes_sha256='a' * 64,
        captured_at='2026-09-23T16:10:00+08:00')
    materials = MaterialStore(tmp_path / 'state' / 'materials')
    provider = HkexOfficialProvider(timeout=5, material_store=materials)
    service = ManagerResearchJobService(ManagerResearchStore(tmp_path / 'state'), None, provider,
        material_store=materials, workspace_security_master_root=master_root)
    import v4.manager_research.workspace_announcements as owner
    monkeypatch.setattr(owner, '_now', lambda: now.isoformat())
    rows = [_row(1, notice_date='2026-09-23 00:00:00', stock_code='00001')]
    calls = []

    def eastmoney_transport(url, *, timeout, method='GET'):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query)['page_index'][0])
        raw = _response(page, 1, rows if page == 1 else [])
        return SourceResponse(url=url, final_url=url, status_code=200, headers={}, body=raw,
                              retrieved_at=now.isoformat())

    provider._eastmoney_transport = eastmoney_transport
    first = service.refresh_announcements(trade_day, source_scope=catalog.SOURCE_SCOPE,
        publication_date='2026-09-23')
    assert first['readback_status'] == 'VERIFIED'
    assert first['status'] == 'COMPLETE'
    assert first['catalog']['total_hits'] == 1
    assert first['catalog']['manager_consumer_row_count'] == 1
    assert len(calls) == 2 and all('page_size=20' in url for url in calls)
    assert all('stock_list=' not in url and 'sr=' not in url for url in calls)

    product_path = (service.store.root / 'workspace_announcements' / trade_day
        / 'eastmoney_date_catalog' / '20260923' / 'latest.json')
    product = service.store._read(product_path)
    assert product['source_scope'] == catalog.SOURCE_SCOPE
    assert product['page_receipts'][0]['owner_attempt_path']
    assert product['page_receipts'][0]['owner_receipt_path']
    attempt_path = (service.store.root / 'workspace_announcement_runs' / trade_day
        / 'eastmoney_date_catalog' / '20260923' / 'latest.json')
    assert service.store._read(attempt_path)['state'] == 'COMPLETE'

    reused = service.refresh_announcements(trade_day, source_scope=catalog.SOURCE_SCOPE,
        publication_date='2026-09-23')
    readback = service.get_announcement_date_catalog(trade_day, '2026-09-23')
    assert reused['catalog']['run_id'] == product['run_id']
    assert readback['readback_status'] == 'VERIFIED'
    assert len(calls) == 2
    service.close()


def test_owner_accepts_saved_refs_without_network_and_rejects_bad_ref_closed(tmp_path, monkeypatch):
    trade_day = '20260924'
    now = datetime(2026, 9, 24, 8, 0, tzinfo=timezone(timedelta(hours=8)))
    master_root = tmp_path / 'master'
    publish_hk_security_master(master_root, trade_date='20260923',
        rows=[dict(code='HK.00001', name='Fixture One')], universe_codes_sha256='a' * 64,
        captured_at='2026-09-23T16:10:00+08:00')
    materials = MaterialStore(tmp_path / 'shared' / 'materials')
    provider = HkexOfficialProvider(timeout=5, material_store=materials)
    import v4.manager_research.workspace_announcements as owner
    monkeypatch.setattr(owner, '_now', lambda: now.isoformat())
    rows = [_row(1, notice_date='2026-09-23 00:00:00', stock_code='00001')]
    calls = []

    def eastmoney_transport(url, *, timeout, method='GET'):
        calls.append(url)
        page = int(parse_qs(urlsplit(url).query)['page_index'][0])
        raw = _response(page, 1, rows if page == 1 else [])
        return SourceResponse(url=url, final_url=url, status_code=200, headers={}, body=raw,
                              retrieved_at=now.isoformat())

    provider._eastmoney_transport = eastmoney_transport
    source_service = ManagerResearchJobService(ManagerResearchStore(tmp_path / 'source-state'), None,
        provider, material_store=materials, workspace_security_master_root=master_root)
    source = source_service.refresh_announcements(trade_day, source_scope=catalog.SOURCE_SCOPE,
        publication_date='2026-09-23')
    assert source['readback_status'] == 'VERIFIED' and source['status'] == 'COMPLETE'
    refs = {page['page_index']: page['source_ref'] for page in source['catalog']['page_receipts']}
    original_retrieved_at = [ref['retrieved_at'] for ref in refs.values()]
    assert len(calls) == 2

    import_service = ManagerResearchJobService(ManagerResearchStore(tmp_path / 'import-state'), None,
        provider, material_store=materials, workspace_security_master_root=master_root)
    imported = import_service.accept_saved_date_catalog_refs(trade_day, '2026-09-23', refs)
    assert imported['readback_status'] == 'VERIFIED'
    assert imported['status'] == 'COMPLETE'
    assert imported['catalog']['capture_mode'] == 'SAVED_REFERENCE_IMPORT'
    assert [page['retrieved_at'] for page in imported['catalog']['page_receipts']] == original_retrieved_at
    assert import_service.get_announcement_date_catalog(trade_day, '2026-09-23')['readback_status'] == 'VERIFIED'
    assert import_service.refresh_announcements(trade_day, source_scope=catalog.SOURCE_SCOPE,
        publication_date='2026-09-23')['catalog']['run_id'] == imported['catalog']['run_id']
    assert len(calls) == 2

    for scenario in ('wrong_date_url', 'wrong_sha', 'missing_page'):
        wrong_service = ManagerResearchJobService(
            ManagerResearchStore(tmp_path / f'wrong-state-{scenario}'), None,
            provider, material_store=materials, workspace_security_master_root=master_root)
        wrong_refs = {page: json.loads(json.dumps(ref)) for page, ref in refs.items()}
        if scenario == 'wrong_date_url':
            wrong_refs[1]['request']['url'] += '&wrong_date=1'
        elif scenario == 'wrong_sha':
            wrong_refs[1]['body_sha256'] = 'f' * 64
        else:
            wrong_refs.pop(1)
        rejected = wrong_service.accept_saved_date_catalog_refs(trade_day, '2026-09-23', wrong_refs)
        assert rejected['status'] == 'PARTIAL'
        assert rejected['readback_status'] == 'VERIFIED'
        assert 'EASTMONEY_CATALOG_PAGE_CAPTURE_OR_READ_FAILED' in rejected['gaps']
        assert len(calls) == 2
        wrong_service.close()

    source_service.close()
    import_service.close()
