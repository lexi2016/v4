from __future__ import annotations

import io
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from infrastructure.http_transport import (
    HTTPContractError,
    ProxyAwareHTTPTransport,
    build_proxy_environment,
)
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from ops import materialize_research_peripherals as peripherals


class _Response:
    def __init__(self, status: int, body: bytes = b"ok") -> None:
        self.status = status
        self._body = body

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_proxy_success_does_not_use_direct_fallback() -> None:
    calls: list[str] = []

    def proxy_opener(request, timeout):
        calls.append("proxy")
        return _Response(200, b"proxy body")

    def direct_opener(request, timeout):
        calls.append("direct")
        return _Response(200, b"direct body")

    result = ProxyAwareHTTPTransport(
        proxy_url="http://127.0.0.1:7890",
        proxy_opener=proxy_opener,
        direct_opener=direct_opener,
    ).fetch("https://example.test/feed")

    assert calls == ["proxy"]
    assert result.body == b"proxy body"
    assert result.receipt == {
        "elapsed_ms": result.receipt["elapsed_ms"],
        "http_status": 200,
        "error": None,
        "proxy_used": True,
        "fallback_used": False,
    }


def test_proxy_network_failure_has_one_bounded_direct_fallback() -> None:
    calls: list[str] = []

    def proxy_opener(request, timeout):
        calls.append("proxy")
        raise URLError("proxy unavailable")

    def direct_opener(request, timeout):
        calls.append("direct")
        return _Response(200, b"direct body")

    result = ProxyAwareHTTPTransport(
        proxy_url="http://127.0.0.1:7890",
        proxy_opener=proxy_opener,
        direct_opener=direct_opener,
    ).fetch("https://example.test/feed")

    assert calls == ["proxy", "direct"]
    assert result.body == b"direct body"
    assert result.receipt["http_status"] == 200
    assert result.receipt["proxy_used"] is True
    assert result.receipt["fallback_used"] is True
    assert result.receipt["error"] is None


def test_http_contract_error_does_not_fallback_or_retry_forever() -> None:
    calls: list[str] = []

    def proxy_opener(request, timeout):
        calls.append("proxy")
        raise HTTPError(
            request.full_url,
            503,
            "upstream contract error",
            {},
            io.BytesIO(),
        )

    def direct_opener(request, timeout):
        calls.append("direct")
        return _Response(200, b"must not be used")

    with pytest.raises(HTTPContractError) as caught:
        ProxyAwareHTTPTransport(
            proxy_url="http://127.0.0.1:7890",
            proxy_opener=proxy_opener,
            direct_opener=direct_opener,
        ).fetch("https://example.test/feed")

    assert calls == ["proxy"]
    assert caught.value.receipt["http_status"] == 503
    assert caught.value.receipt["fallback_used"] is False


def test_external_feed_receipts_record_proxy_and_fallback_outcomes() -> None:
    rss = b"""<?xml version='1.0'?><rss><channel><item><title>Feed item</title><link>https://example.test/item</link><description>Market event evidence.</description><pubDate>Wed, 20 Aug 2026 08:00:00 GMT</pubDate></item></channel></rss>"""
    calls: list[tuple[str, str]] = []

    def proxy_opener(request, timeout):
        feed = "feed-two" if "feed-two" in request.full_url else "feed-one"
        calls.append((feed, "proxy"))
        if feed == "feed-two":
            raise URLError("proxy unavailable")
        return _Response(200, rss)

    def direct_opener(request, timeout):
        calls.append(("feed-two", "direct"))
        return _Response(200, rss)

    payload = peripherals.build_external_finance_payload(
        "20260820",
        fetched_at="2026-08-20T08:05:00+08:00",
        subscriptions=(
            {"id": "feed-one", "query": "feed-one", "theme_bucket": "one"},
            {"id": "feed-two", "query": "feed-two", "theme_bucket": "two"},
        ),
        translate_text=None,
        resolve_original_url=None,
        transport=ProxyAwareHTTPTransport(
            proxy_url="http://127.0.0.1:7890",
            proxy_opener=proxy_opener,
            direct_opener=direct_opener,
        ),
    )

    assert calls == [("feed-one", "proxy"), ("feed-two", "proxy"), ("feed-two", "direct")]
    receipts = {item["feed_id"]: item for item in payload["feed_receipts"]}
    assert receipts["feed-one"]["http_status"] == 200
    assert receipts["feed-one"]["proxy_used"] is True
    assert receipts["feed-one"]["fallback_used"] is False
    assert receipts["feed-two"]["http_status"] == 200
    assert receipts["feed-two"]["proxy_used"] is True
    assert receipts["feed-two"]["fallback_used"] is True
    assert receipts["feed-two"]["error"] is None
    assert all(isinstance(item["elapsed_ms"], int) for item in receipts.values())


def test_reuse_existing_retries_only_failed_peripheral_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    failed_external = peripherals.build_external_finance_payload(
        "20260820",
        fetched_at="2026-08-20T08:00:00+08:00",
        subscriptions=({"id": "failed", "query": "failed", "theme_bucket": "failed"},),
        fetch_rss=lambda url, timeout: (_ for _ in ()).throw(URLError("offline")),
        translate_text=None,
        resolve_original_url=None,
    )
    ready_ai = peripherals.build_ai_news_payload(
        "20260820",
        page_html="",
        fetched_at="2026-08-20T08:00:00+08:00",
        translate_text=None,
    )
    store = ResearchPeripheralStore(data_root)
    store.publish(failed_external)
    store.publish(ready_ai)

    retried: list[str] = []

    def retry_external(**kwargs):
        retried.append("external_finance")
        payload = dict(failed_external)
        payload["status"] = "READY_EMPTY"
        payload["cannot_confirm"] = ["GOOGLE_NEWS_RSS_DISCOVERY_ONLY"]
        return {
            "payload": payload,
            "payload_path": "research/peripherals/20260820/external_finance.json",
            "receipt_path": "receipts/research/peripherals/20260820/external_finance.json",
        }

    def should_not_retry_ai(**kwargs):
        raise AssertionError("a verified AI source must not be fetched again")

    monkeypatch.setattr(peripherals, "materialize_external_finance", retry_external)
    monkeypatch.setattr(peripherals, "materialize_ai_news", should_not_retry_ai)

    assert peripherals.main([
        "--data-root", str(data_root),
        "--trade-date", "20260820",
        "--source", "both",
        "--reuse-existing",
    ]) == 0
    assert retried == ["external_finance"]


def test_launchd_proxy_environment_sets_all_case_variants_and_loopback() -> None:
    environment = build_proxy_environment({"HTTP_PROXY": "http://old.invalid"})

    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        assert environment[key] == "http://127.0.0.1:7890"
    for key in ("NO_PROXY", "no_proxy"):
        assert environment[key] == "127.0.0.1,localhost,::1"
