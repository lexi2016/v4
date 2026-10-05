"""Material reuse regressions: fetch once, parse once, reuse everywhere."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from v4.manager_research import hkex_provider as provider_module
from v4.manager_research.hkex_provider import (
    ACTIVE_STOCK_LIST_URL,
    HkexOfficialProvider,
    TITLE_SEARCH_URL,
)
from v4.manager_research.material_transport import MaterialTransport
from v4.manager_research.materials import MaterialStore
from v4.manager_research.ports import SourceResponse
from v4.manager_research.reader_source import (
    ReaderSourceError,
    build_search_url,
    material_reader_fetcher,
)


NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
PDF_URL = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0908/fixture.pdf"


def _response(url: str, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> SourceResponse:
    return SourceResponse(
        url=url,
        status_code=status,
        body=body,
        headers=headers or {"content-type": "text/html; charset=utf-8"},
        retrieved_at=NOW,
        final_url=url,
    )


class CountingTransport:
    def __init__(self, responder):
        self.calls: list[tuple[str, str]] = []
        self._responder = responder

    def __call__(self, url, *, timeout, method="GET", body=None, headers=None):
        self.calls.append((method, url))
        return self._responder(url, method=method)


def test_transport_caches_successful_get_with_provenance(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    inner = CountingTransport(lambda url, *, method: _response(url, b"<html>directory</html>"))
    transport = MaterialTransport(store, inner, namespace="t")

    first = transport("https://example.invalid/a", timeout=5, method="GET")
    second = transport("https://example.invalid/a", timeout=5, method="GET")

    assert len(inner.calls) == 1
    assert second.body == first.body == b"<html>directory</html>"
    assert second.status_code == 200
    assert second.final_url == "https://example.invalid/a"
    assert second.retrieved_at == first.retrieved_at == NOW
    assert second.headers.get("content-type") == "text/html; charset=utf-8"


def test_transport_passes_through_post_and_error_responses_uncached(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")

    def responder(url, *, method):
        if method == "POST":
            return _response(url, b"search-result", status=200)
        return _response(url, b"not found", status=404)

    inner = CountingTransport(responder)
    transport = MaterialTransport(store, inner, namespace="t")

    posted = transport(TITLE_SEARCH_URL, timeout=5, method="POST", body=b"q=1")
    assert posted.status_code == 200 and posted.body == b"search-result"

    first = transport("https://example.invalid/missing", timeout=5, method="GET")
    second = transport("https://example.invalid/missing", timeout=5, method="GET")
    assert first.status_code == second.status_code == 404
    assert second.body == b"not found"
    # POST + both 404 GETs hit the wire; only successful GET bodies are stored.
    assert [call[1] for call in inner.calls].count("https://example.invalid/missing") == 2


def test_transport_ttl_for_classifier_keeps_pdfs_immutable(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    inner = CountingTransport(lambda url, *, method: _response(url, b"body"))
    transport = MaterialTransport(
        store,
        inner,
        namespace="t",
        ttl_for=lambda url: None if url.endswith(".pdf") else 0.0,
    )

    transport(PDF_URL, timeout=5, method="GET")
    transport(PDF_URL, timeout=5, method="GET")
    transport("https://example.invalid/listing", timeout=5, method="GET")
    transport("https://example.invalid/listing", timeout=5, method="GET")

    pdf_calls = [call for call in inner.calls if call[1] == PDF_URL]
    listing_calls = [call for call in inner.calls if call[1].endswith("/listing")]
    assert len(pdf_calls) == 1  # immutable: never refetched
    assert len(listing_calls) == 2  # ttl=0: stale immediately


def test_transport_parsed_params_partition_the_cache(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    inner = CountingTransport(lambda url, *, method: _response(url, b"document"))
    transport = MaterialTransport(store, inner, namespace="t")
    material = transport.material("https://example.invalid/doc", timeout=5)
    assert material is not None
    parses = {"n": 0}

    def parse_fn(body: bytes):
        parses["n"] += 1
        return {"seen": body.decode()}

    first = transport.parsed(material, parser_id="doc", parser_version=1, params={"title": "A"}, parse_fn=parse_fn)
    again = transport.parsed(material, parser_id="doc", parser_version=1, params={"title": "A"}, parse_fn=parse_fn)
    other = transport.parsed(material, parser_id="doc", parser_version=1, params={"title": "B"}, parse_fn=parse_fn)
    upgraded = transport.parsed(material, parser_id="doc", parser_version=2, params={"title": "A"}, parse_fn=parse_fn)

    assert first == again == other == upgraded == {"seen": "document"}
    assert parses["n"] == 3  # title A once, title B once, version 2 once
    assert len(inner.calls) == 1


def test_reader_fetcher_fetches_once_and_reports_raw_digest(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")
    payload = ('jQuery35101792940631092459_1764599530165({"result":{"cmsArticleWebOld":'
               '[{"title":"t","content":"c","date":"2026-09-08 08:00:00","url":"https://x.invalid/1","mediaName":"m"}]}});').encode()
    calls: list[str] = []

    def raw_fetch(url, timeout, referer):
        calls.append(url)
        return 200, payload

    fetch = material_reader_fetcher(store, ttl_seconds=3600, raw_fetch=raw_fetch)
    first_rows, first_meta = fetch(code="HK.06166", market="HK", limit=20)
    second_rows, second_meta = fetch(code="HK.06166", market="HK", limit=20)

    assert len(calls) == 1
    assert first_rows == second_rows
    assert first_meta["url"] == build_search_url("HK.06166", market="HK", limit=20)
    assert first_meta["source_body_sha256"] == hashlib.sha256(payload).hexdigest()
    assert second_meta["source_body_sha256"] == first_meta["source_body_sha256"]
    assert first_meta["http_status"] == 200


def test_reader_fetcher_preserves_reader_error_forms(tmp_path: Path) -> None:
    store = MaterialStore(tmp_path / "materials")

    def failing_http(url, timeout, referer):
        return 503, b""

    fetch_http = material_reader_fetcher(store, raw_fetch=failing_http)
    with pytest.raises(ReaderSourceError, match="PUBLIC_NEWS_HTTP_503"):
        fetch_http(code="HK.06166")

    def exploding(url, timeout, referer):
        raise OSError("boom")

    fetch_boom = material_reader_fetcher(store, raw_fetch=exploding)
    with pytest.raises(ReaderSourceError, match="PUBLIC_NEWS_FETCH_FAILED:OSError"):
        fetch_boom(code="HK.06166")

    # Failures persist nothing: a later success is a real fetch.
    def ok(url, timeout, referer):
        return 200, b'cb({"result":{"cmsArticleWebOld":[]}});'

    fetch_ok = material_reader_fetcher(store, raw_fetch=ok)
    rows, _meta = fetch_ok(code="HK.06166")
    assert rows == []


def _fixture_title_html() -> bytes:
    return (
        "<html><body><table>"
        "<tr>"
        '<td class="release-time">Release Time: 08/09/2026 08:01</td>'
        '<td class="stock-short-code">Stock Code: 06166</td>'
        '<td class="stock-short-name">Stock Short Name: FIXTURE</td>'
        '<td><div class="headline">Interim Results Announcement</div>'
        f'<div class="doc-link"><a href="{PDF_URL}">Interim Results for the six months ended 30 June 2026</a></div></td>'
        "</tr>"
        "</table></body></html>"
    ).encode("utf-8")


def test_provider_reuses_pdf_fetch_and_parsed_facts_across_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MaterialStore(tmp_path / "materials")
    pdf_body = b"%PDF-1.4 fixture bytes that pypdf is never asked to read"
    active_stocks = json.dumps([{"c": "06166", "i": 12345, "n": "Fixture Issuer Ltd"}]).encode()

    def responder(url, *, method):
        if url == ACTIVE_STOCK_LIST_URL:
            return _response(url, active_stocks, headers={"content-type": "application/json"})
        if url.startswith(TITLE_SEARCH_URL) and method == "POST":
            return _response(url, _fixture_title_html())
        if url.startswith(TITLE_SEARCH_URL):
            return _response(url, b"<html>search form</html>")
        if url == PDF_URL:
            return _response(url, pdf_body, headers={"content-type": "application/pdf"})
        return _response(url, b"", status=404)

    parses = {"n": 0}

    def counting_extract(body: bytes, *, title: str = ""):
        parses["n"] += 1
        return (
            [
                {
                    "fact_kind": "financial",
                    "fields": {"label": "Revenue"},
                    "page": 1,
                    "locator": "PDF page 1",
                    "source_excerpt": "Revenue 1,000",
                }
            ],
            [{"page": 1, "text": "Revenue 1,000"}],
        )

    monkeypatch.setattr(provider_module, "extract_pdf_facts", counting_extract)

    observation = {"code": "HK.06166", "name": "Fixture", "market": "HK_CONNECT"}

    inner_one = CountingTransport(responder)
    provider_one = HkexOfficialProvider(transport=inner_one, material_store=store)
    result_one = provider_one.collect(
        target_trade_date="20260908",
        cutoff_at="2026-09-08T09:40:00+08:00",
        observation=observation,
    )
    assert result_one["status"] == "READY"
    assert result_one["reason"] == "OFFICIAL_PDF_FACTS_EXTRACTED"
    assert result_one["source"]["sha256"] == hashlib.sha256(pdf_body).hexdigest()
    assert result_one["source"]["parse_status"] == "STRUCTURED_FACTS"
    assert [url for method, url in inner_one.calls if url == PDF_URL] == [PDF_URL]

    # A second, independent provider instance sharing the same store must not
    # re-download the mapping, the directory form, or the archived PDF, and
    # the cached parse must be reused instead of re-running the extractor.
    inner_two = CountingTransport(responder)
    provider_two = HkexOfficialProvider(transport=inner_two, material_store=store)
    result_two = provider_two.collect(
        target_trade_date="20260908",
        cutoff_at="2026-09-08T09:40:00+08:00",
        observation=observation,
    )

    assert result_two["status"] == "READY"
    assert result_two["facts"] == result_one["facts"]
    assert result_two["source"]["sha256"] == result_one["source"]["sha256"]
    assert [url for method, url in inner_two.calls if url == PDF_URL] == []
    assert [url for method, url in inner_two.calls if url == ACTIVE_STOCK_LIST_URL] == []
    assert parses["n"] == 1  # one parse for both collections
