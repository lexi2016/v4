from __future__ import annotations
import asyncio, io, threading
from urllib.request import Request
from unittest.mock import patch
import httpx, pytest
from fastapi import FastAPI
from v4.manager_research import hkex_provider as hk
from v4.manager_research import pdf_parser as pdf
from apps.api.v35_api.manager_research_router import create_manager_research_router

@pytest.mark.parametrize(
    'url',
    [
        'https://user:pass@www.hkexnews.hk/a',
        'https://www.hkexnews.hk:8443/a',
        'https://www.hkexnews.hk:bad/a',
        'https://www.hkexnews.hk.evil.test/a',
        'http://www.hkexnews.hk/a',
    ],
)
def test_official_url_requires_https_host_and_standard_port(url):
    assert hk._safe_official_url(url) is False

def test_redirect_refused_before_following_target():
    handler = hk._HKEXRedirectHandler()
    with pytest.raises(hk.ProviderError):
        handler.redirect_request(
            Request('https://www.hkexnews.hk/a'),
            None,
            302,
            'Found',
            {},
            'http://127.0.0.1/private',
        )

def test_oversized_response_rejected_by_content_length_before_read():

    class Response:
        headers = {'Content-Length': str(32 * 1024 * 1024 + 1)}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def geturl(self):
            return 'https://www.hkexnews.hk/a'

        def read(self, *a):
            raise AssertionError('body must not be read')

    class Opener:

        def open(self, *a, **kw):
            return Response()
    with patch.object(hk, 'build_opener', return_value=Opener()):
        with pytest.raises(hk.ProviderError, match='(SIZE|size|large)'):
            hk._default_transport()('https://www.hkexnews.hk/a', timeout=2)

def test_streaming_response_cannot_cross_actual_byte_limit():

    class Response:
        headers = {}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def geturl(self):
            return 'https://www.hkexnews.hk/a'

        def read(self, n=-1):
            return b'x' * (100 if n < 0 else min(n, 100))

    class Opener:

        def open(self, *a, **kw):
            return Response()
    with patch.object(hk, 'build_opener', return_value=Opener()):
        with pytest.raises(hk.ProviderError):
            hk._default_transport(max_response_bytes=64)('https://www.hkexnews.hk/a', timeout=2)

def test_external_final_url_is_rejected_before_body():
    calls = []

    class Response:
        headers = {}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def geturl(self):
            return 'https://evil.test/a'

        def read(self, *a):
            calls.append('read')
            return b'bad'

    class Opener:

        def open(self, *a, **kw):
            return Response()
    with patch.object(hk, 'build_opener', return_value=Opener()):
        with pytest.raises(hk.ProviderError):
            hk._default_transport()('https://www.hkexnews.hk/a', timeout=2)
    assert calls == []

def test_pdf_page_budget_fails_closed_before_extraction(monkeypatch):

    class Page:

        def extract_text(self):
            raise AssertionError('too many pages; do not extract')

    class Reader:
        pages = [Page(), Page()]
    monkeypatch.setattr(pdf, '_load_pdf_reader', lambda: lambda *a, **kw: Reader())
    with pytest.raises(pdf.PdfParseError, match='BUDGET'):
        pdf.extract_pdf_pages(b'%PDF-fixture', max_pages=1)

def test_pdf_text_budget_never_returns_truncated_facts(monkeypatch):

    class Page:

        def extract_text(self):
            return 'abcdef'

    class Reader:
        pages = [Page(), Page()]
    monkeypatch.setattr(pdf, '_load_pdf_reader', lambda: lambda *a, **kw: Reader())
    with pytest.raises(pdf.PdfParseError, match='BUDGET'):
        pdf.extract_pdf_pages(b'%PDF-fixture', max_text_characters=10)

@pytest.mark.parametrize('route', ['ensure', 'retry', 'events'])
def test_post_storage_work_runs_off_event_loop(route):
    main_thread = threading.get_ident()
    seen = []

    class Service:

        def ensure(self, date):
            seen.append(threading.get_ident())
            return {'status': 'QUEUED'}
        retry = ensure

        def ensure_events(self, date, **kw):
            return self.ensure(date)
    app = FastAPI()
    app.include_router(create_manager_research_router(Service()))

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url='http://testserver',
        ) as client:
            result = await client.post(f'/api/v4/manager/research/{route}?date=20260908')
            assert result.status_code == 200, result.text
    asyncio.run(check())
    assert seen and seen[0] != main_thread

def test_json_log_does_not_dump_exception_secret():
    import logging, sys
    from infrastructure.logging_config import JsonFormatter
    try:
        raise RuntimeError('Authorization: Bearer FAKE_LOG_SECRET')
    except RuntimeError:
        record = logging.LogRecord('test', logging.ERROR, __file__, 1, 'source failed', (), sys.exc_info())
    encoded = JsonFormatter().format(record)
    assert 'FAKE_LOG_SECRET' not in encoded
    assert 'RuntimeError' in encoded
