"""Offline replay of one reviewed Eastmoney HK notice through the existing V4 owner."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import httpx
from fastapi import FastAPI

from apps.api.v35_api.manager_research_router import create_manager_research_router
from v4.manager_research.announcement_observation import event_lane
from v4.manager_research.hkex_provider import HkexOfficialProvider
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_announcements import read as read_announcements
from v4.manager_research.workspace_plan import plan_context
from v4.manager_research.workspace import _announcement_owner_chain
from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master


DAY = '20260929'
HK = timezone(timedelta(hours=8))
NOW = '2026-09-29T13:22:00+08:00'
EVIDENCE = Path('/Users/lexi/Desktop/学习/agents调试/EASTMONEY_HK_ANN_20260929')


def _read(path: str) -> bytes:
    return (EVIDENCE / path).read_bytes()


class EvidenceTransport:
    def __init__(self, *, wrong_market: bool = False, wrong_page2_identity: bool = False):
        self.calls: list[str] = []
        self.timeouts: list[float] = []
        self.wrong_market = wrong_market
        self.wrong_page2_identity = wrong_page2_identity
        self.list_body = _read('tencent_list.raw.json')
        if wrong_market:
            payload = json.loads(self.list_body)
            payload['data']['list'][0]['codes'][0]['market_code'] = '115'
            self.list_body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()

    def __call__(self, url: str, *, timeout: float, method: str = 'GET', body=None, headers=None):
        self.calls.append(url)
        self.timeouts.append(timeout)
        if url == json.loads(_read('list_receipt.json'))['url']:
            raw = self.list_body
            retrieved = json.loads(_read('list_receipt.json'))['finished_at']
        elif url == json.loads(_read('content_receipt.json'))['url']:
            raw = _read('tencent_content.raw.json')
            retrieved = json.loads(_read('content_receipt.json'))['finished_at']
        elif (urlsplit(url).hostname=='np-cnotice-stock.eastmoney.com'
                and parse_qs(urlsplit(url).query).get('page_index')==['2']):
            # Synthetic page 2 exists only to test bounded paging. It is not a
            # saved live response or evidence about the article's actual page 2.
            payload=json.loads(_read('tencent_content.raw.json'))
            payload['data']['notice_content']='[synthetic page two for pagination regression only]'
            if self.wrong_page2_identity:
                payload['data']['art_code']='ANUNRELATED999999999'
            raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
            retrieved='2026-09-29T13:10:30.000000+08:00'
        elif url == json.loads(_read('pdf_receipt.json'))['url']:
            raw = _read('tencent_announcement.pdf')
            retrieved = json.loads(_read('pdf_receipt.json'))['finished_at']
        else:
            # The saved evidence is deliberately only one article. Other in-window
            # rows stay pending instead of being assigned invented response bytes.
            raise RuntimeError('fixture source bytes unavailable')
        return SourceResponse(url=url, final_url=url, status_code=200, headers={}, body=raw,
                              retrieved_at=retrieved)


def _service(tmp_path: Path, monkeypatch, transport: EvidenceTransport):
    master = tmp_path / 'master'
    publish_hk_security_master(master, trade_date='20260928',
        rows=[dict(code='HK.00700', name='腾讯控股')], universe_codes_sha256='a' * 64,
        captured_at='2026-09-28T16:10:00+08:00')
    state = tmp_path / 'state'
    materials = MaterialStore(state / 'materials')
    provider = HkexOfficialProvider(transport=lambda *a, **k: pytest.fail('HKEX transport must not be called'),
        eastmoney_transport=transport, material_store=materials)
    service = ManagerResearchJobService(ManagerResearchStore(state), None, provider,
        material_store=materials, workspace_security_master_root=master)
    import v4.manager_research.workspace_announcements as owner
    monkeypatch.setattr(owner, '_now', lambda: NOW)
    return service, materials


def test_saved_eastmoney_hk_notice_flows_through_original_owner_store_and_workbench_lane(tmp_path, monkeypatch):
    for raw_path, expected in [
        ('tencent_list.raw.json', 'f3af6054cf4c5d5180dbc6755e84398d0fb3810c487ea50bc163df1265cde62b'),
        ('tencent_content.raw.json', '8557b81422e64ad909a159d38c046cb49e604839d439507d75247759b7ab9244'),
        ('tencent_announcement.pdf', '01999cc0581a4472725abd7c5ef0fa73f80cc93f23a70bfd9e72e81ee8be9121'),
    ]:
        assert sha256(_read(raw_path)).hexdigest() == expected
    transport = EvidenceTransport()
    service, materials = _service(tmp_path, monkeypatch, transport)

    review = service.refresh_announcements(DAY, source_scope='EASTMONEY_HK', issuer_code='HK.00700')
    assert transport.calls[:4] == [
        json.loads(_read('list_receipt.json'))['url'],
        json.loads(_read('content_receipt.json'))['url'],
        'https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code=AN202609281829962076&client_source=web&page_index=2',
        json.loads(_read('pdf_receipt.json'))['url'],
    ]
    assert any('AN202609251829903409' in url for url in transport.calls[4:])
    assert review['eastmoney_hk_status'] == 'PARTIAL'
    assert review['official_documents'] == []
    capture_budget=review['eastmoney_hk_capture']['capture_budget']
    assert capture_budget['max_seconds']==45 and capture_budget['max_response_bytes']==64*1024*1024
    assert capture_budget['max_requests']==1+4*(20+1)
    assert 0<=capture_budget['elapsed_seconds']<=45 and all(0<value<=45 for value in transport.timeouts)
    assert capture_budget['requests_used']<=capture_budget['max_requests']
    assert capture_budget['response_bytes_used']<=capture_budget['max_response_bytes']
    assert len(review['eastmoney_hk_documents']) == 1
    doc = review['eastmoney_hk_documents'][0]
    assert (doc['symbol'], doc['market_code'], doc['stock_code'], doc['art_code']) == (
        'HK.00700', '116', '00700', 'AN202609281829962076')
    assert doc['notice_date'] == '2026-09-28 00:00:00'
    assert doc['display_time'] == '2026-09-28 18:02:03:396'
    assert doc['available_at'] == '2026-09-29T13:10:41.252034+08:00'
    assert 'published_at' not in doc
    assert doc['publication_status'] == 'CANNOT_CONFIRM_FIRST_PUBLICATION'
    assert doc['full_pdf_stored'] is True and doc['pdf_page_count'] == 8
    assert doc['pdf_bytes'] == 132997
    assert doc['document_sha256'] == '01999cc0581a4472725abd7c5ef0fa73f80cc93f23a70bfd9e72e81ee8be9121'
    assert doc['source_identity'] == 'EASTMONEY_HK_MIRROR_NOT_HKEX_OFFICIAL'
    assert doc['fresh_catalyst_eligible'] is False and doc['focus_eligible'] is False and doc['buy_allowed'] is False
    assert doc['body_status']=='FULL_CONTENT_API_TEXT_VERIFIED'
    assert doc['body_source']=='EASTMONEY_CONTENT_API_PAGES' and doc['pdf_text_extraction_status']=='UNVERIFIED_ENCODING'
    assert doc['content_page_count']==2 and len(doc['body_pages'])==2
    assert doc['body_pages'][0]['text']==json.loads(_read('tencent_content.raw.json'))['data']['notice_content']
    assert doc['body_pages'][1]['text']=='[synthetic page two for pagination regression only]'
    assert doc['body_sha256']==sha256(doc['body_text'].encode('utf-8')).hexdigest()
    assert doc['body_pages'][0]['source_ref']==doc['source_refs'][1]
    assert doc['body_pages'][1]['source_ref']==doc['source_refs'][2]
    assert len(doc['source_refs'])==4
    assert all(materials.stat_source(ref['source_key']) is not None for ref in doc['source_refs'])

    context = plan_context(DAY, now=datetime.fromisoformat(NOW))
    lane = event_lane(review, {'cards': [], 'strict': [], 'near': [], 'pending': []}, context)
    assert lane['eastmoney_hk_status'] == 'PARTIAL'
    assert len(lane['eastmoney_hk_documents']) == 1
    assert lane['official_documents'] == []
    assert lane['eastmoney_hk_documents'][0]['document_sha256'] == doc['document_sha256']
    assert lane['eastmoney_hk_documents'][0]['body_text']==doc['body_text']
    assert len(lane['eastmoney_hk_documents'][0]['body_pages'])==2
    chain=_announcement_owner_chain(review)
    assert chain['status']=='NOT_RUN' and chain['official_hkex']['status']=='NOT_RUN'
    assert chain['status_by_source']=={'HKEX_OFFICIAL':'NOT_RUN','EASTMONEY_HK':'PARTIAL'}
    assert chain['eastmoney_hk']['source_identity']=='EASTMONEY_HK_MIRROR_NOT_HKEX_OFFICIAL'
    assert chain['eastmoney_hk']['attempt']['state']=='PARTIAL'
    assert chain['eastmoney_hk']['document_count']==1
    assert chain['eastmoney_hk']['readback_identity']['status']=='VERIFIED'
    assert chain['eastmoney_hk']['readback_identity']['verified_documents'][0]['content_page_count']==2


def test_wrong_market_row_is_not_consumed_or_followed_to_content(tmp_path, monkeypatch):
    transport = EvidenceTransport(wrong_market=True)
    service, _ = _service(tmp_path, monkeypatch, transport)
    review = service.refresh_announcements(DAY, source_scope='EASTMONEY_HK', issuer_code='HK.00700')
    assert transport.calls[0] == json.loads(_read('list_receipt.json'))['url']
    assert all('AN202609281829962076' not in url for url in transport.calls[1:])
    assert review['eastmoney_hk_documents'] == []
    product_path = service.store.root / 'workspace_announcements' / DAY / 'eastmoney_hk' / 'latest.json'
    product = service.store._read(product_path)
    assert all(row['art_code'] != 'AN202609281829962076'
        for row in product['queries'][0]['entries'])
    assert any(row.get('art_code') == 'AN202609281829962076'
        for row in product['queries'][0]['rejected'])
    assert review['official_documents'] == []


def test_content_page_identity_mismatch_keeps_document_unreadable(tmp_path, monkeypatch):
    transport=EvidenceTransport(wrong_page2_identity=True)
    service,_=_service(tmp_path,monkeypatch,transport)
    review=service.refresh_announcements(DAY,source_scope='EASTMONEY_HK',issuer_code='HK.00700')
    assert transport.calls[0].endswith('stock_list=00700&page_index=1&page_size=5&sr=-1')
    assert transport.calls[1].endswith('page_index=1') and transport.calls[2].endswith('page_index=2')
    assert all('AN202609281829962076' not in url for url in transport.calls[3:])
    assert review['eastmoney_hk_documents']==[]
    product=service.store._read(service.store.root/'workspace_announcements'/DAY/'eastmoney_hk'/'latest.json')
    assert any(item.get('reason')=='EASTMONEY_HK_CONTENT_IDENTITY_MISMATCH'
        for item in product['pending_documents'])


def test_consumer_cutoff_before_saved_response_keeps_eastmoney_document_out(tmp_path, monkeypatch):
    transport = EvidenceTransport()
    service, _ = _service(tmp_path, monkeypatch, transport)
    service.refresh_announcements(DAY, source_scope='EASTMONEY_HK', issuer_code='HK.00700')
    early = plan_context(DAY, now=datetime(2026, 9, 29, 13, 10, 0, tzinfo=HK))
    review = read_announcements(service, DAY, early)
    assert review['eastmoney_hk_status'] == 'PARTIAL'
    assert review['eastmoney_hk_documents'] == []
    assert 'EASTMONEY_HK_CAPTURE_AFTER_CONSUMER_CUTOFF' in review['eastmoney_hk_gaps']


def test_existing_refresh_route_forwards_explicit_eastmoney_hk_singleton_scope():
    class Owner:
        def __init__(self):
            self.calls = []

        def refresh_announcements(self, date, **kwargs):
            self.calls.append((date, kwargs))
            return {'target_trade_date': date, 'source_scope': kwargs.get('source_scope'),
                    'issuer_code': kwargs.get('issuer_code')}

    service = Owner()
    app = FastAPI()
    app.include_router(create_manager_research_router(service))

    async def post(path):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            return await client.post(path)

    response = asyncio.run(post(
        '/api/v4/manager/research/announcements/refresh?date=20260929&source_scope=EASTMONEY_HK&issuer_code=HK.00700'))
    assert response.status_code == 200
    assert response.json() == {'target_trade_date':'20260929','source_scope':'EASTMONEY_HK','issuer_code':'HK.00700'}
    assert service.calls == [('20260929', {'resume':False,'source_scope':'EASTMONEY_HK','issuer_code':'HK.00700'})]

    rejected = asyncio.run(post(
        '/api/v4/manager/research/announcements/refresh?date=20260929&issuer_code=HK.00700'))
    assert rejected.status_code == 422
    assert len(service.calls) == 1
