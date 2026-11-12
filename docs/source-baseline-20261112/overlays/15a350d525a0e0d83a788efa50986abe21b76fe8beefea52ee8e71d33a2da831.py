from __future__ import annotations

import io
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from infrastructure.http_transport import (
    HTTPContractError,
    ProxyAwareHTTPTransport,
    TransportError,
    _system_proxy_url,
    apply_proxy_environment,
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


def test_launchd_proxy_environment_removes_legacy_fallback_and_keeps_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("urllib.request.getproxies_macosx_sysconf", lambda: {})
    environment = build_proxy_environment({"HTTP_PROXY": "http://old.invalid"})

    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        assert key not in environment
    for key in ("NO_PROXY", "no_proxy"):
        assert environment[key] == "127.0.0.1,localhost,::1"


def test_launchd_proxy_environment_removes_stale_proxy_when_no_proxy_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    monkeypatch.setattr("urllib.request.getproxies_macosx_sysconf", lambda: {})

    environment = build_proxy_environment(
        {
            "HTTP_PROXY": "http://127.0.0.1:7890",
            "http_proxy": "http://127.0.0.1:7890",
            "HTTPS_PROXY": "http://127.0.0.1:7890",
            "https_proxy": "http://127.0.0.1:7890",
            "NO_PROXY": "existing.invalid",
            "no_proxy": "existing.invalid",
        }
    )

    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        assert key not in environment
    for key in ("NO_PROXY", "no_proxy"):
        assert environment[key] == "127.0.0.1,localhost,::1"


def test_launchd_proxy_environment_removes_all_mixed_case_generic_proxy_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    monkeypatch.setattr("urllib.request.getproxies_macosx_sysconf", lambda: {})

    environment = build_proxy_environment(
        {
            "HTTP_PROXY": "http://stale.invalid:8080",
            "http_proxy": "http://stale.invalid:8080",
            "HTTPS_PROXY": "http://stale.invalid:8080",
            "https_proxy": "http://stale.invalid:8080",
            "ALL_PROXY": "http://stale.invalid:8080",
            "all_proxy": "http://stale.invalid:8080",
            "Http_Proxy": "http://stale.invalid:8080",
            "hTtPs_PrOxY": "http://stale.invalid:8080",
            "No_Proxy": "existing.invalid",
            "NO_PROXY": "existing.invalid",
            "no_proxy": "existing.invalid",
        }
    )

    generic_proxy_keys = [
        key
        for key in environment
        if key.upper().endswith("_PROXY") and key.upper() not in {"NO_PROXY"}
    ]
    assert generic_proxy_keys == []
    assert "No_Proxy" not in environment
    assert environment["NO_PROXY"] == "127.0.0.1,localhost,::1"
    assert environment["no_proxy"] == "127.0.0.1,localhost,::1"


def test_system_proxy_resolution_does_not_mutate_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://stale.invalid:8080")
    monkeypatch.setenv("ALL_PROXY", "http://stale.invalid:8080")
    monkeypatch.setenv("Http_Proxy", "http://stale.invalid:8080")
    before = dict(os.environ)
    observed: list[dict[str, str]] = []

    def system_proxy() -> dict[str, str]:
        observed.append(dict(os.environ))
        return {"https": "http://system.invalid:8080"}

    def forbidden_environment_lookup() -> dict[str, str]:
        raise AssertionError("system lookup must not use environment getproxies")

    monkeypatch.setattr("urllib.request.getproxies", forbidden_environment_lookup)
    monkeypatch.setattr("urllib.request.getproxies_macosx_sysconf", system_proxy)

    assert _system_proxy_url() == "http://system.invalid:8080"
    assert observed == [before]
    assert dict(os.environ) == before


def test_apply_proxy_environment_replaces_process_proxy_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("urllib.request.getproxies_macosx_sysconf", lambda: {})
    for key in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "Http_Proxy",
        "hTtPs_PrOxY",
        "No_Proxy",
    ):
        monkeypatch.setenv(key, "http://127.0.0.1:7890")

    applied = apply_proxy_environment()

    generic_proxy_keys = [
        key
        for key in os.environ
        if key.upper().endswith("_PROXY") and key.upper() not in {"NO_PROXY"}
    ]
    assert generic_proxy_keys == []
    assert os.environ["NO_PROXY"] == "127.0.0.1,localhost,::1"
    assert os.environ["no_proxy"] == "127.0.0.1,localhost,::1"
    assert applied["NO_PROXY"] == "127.0.0.1,localhost,::1"


def test_transport_does_not_reuse_stale_proxy_environment_when_no_proxy_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    monkeypatch.setattr("urllib.request.getproxies_macosx_sysconf", lambda: {})
    calls: list[str] = []

    def proxy_opener(request, timeout):
        del request, timeout
        calls.append("proxy")
        raise AssertionError("stale HTTP(S)_PROXY must not select a proxy")

    def direct_opener(request, timeout):
        del request, timeout
        calls.append("direct")
        return _Response(200, b"direct body")

    result = ProxyAwareHTTPTransport(
        env={
            "HTTP_PROXY": "http://127.0.0.1:7890",
            "HTTPS_PROXY": "http://127.0.0.1:7890",
        },
        proxy_opener=proxy_opener,
        direct_opener=direct_opener,
    ).fetch("https://example.test/feed")

    assert calls == ["direct"]
    assert result.receipt["proxy_used"] is False
    assert result.receipt["fallback_used"] is False


def test_transport_without_proxy_surfaces_typed_direct_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    monkeypatch.setattr("urllib.request.getproxies_macosx_sysconf", lambda: {})
    calls: list[str] = []

    def direct_opener(request, timeout):
        del request, timeout
        calls.append("direct")
        raise URLError("direct unavailable")

    with pytest.raises(TransportError) as caught:
        ProxyAwareHTTPTransport(
            env={"HTTP_PROXY": "http://127.0.0.1:7890"},
            proxy_opener=lambda request, timeout: _Response(200, b"must not run"),
            direct_opener=direct_opener,
        ).fetch("https://example.test/feed")

    assert calls == ["direct"]
    assert caught.value.receipt["proxy_used"] is False
    assert caught.value.receipt["fallback_used"] is False
    assert caught.value.receipt["http_status"] is None


def test_transport_prefers_explicit_proxy_environment_over_calling_override_and_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.getproxies_macosx_sysconf",
        lambda: {"https": "http://system.invalid:8080"},
    )
    seen: list[str] = []

    def proxy_opener(request, timeout):
        del timeout
        seen.append(request.full_url)
        return _Response(200, b"explicit body")

    transport = ProxyAwareHTTPTransport(
        env={"V4_RESEARCH_PROXY_URL": "http://explicit.invalid:8080"},
        proxy_url="http://override.invalid:8080",
        proxy_opener=proxy_opener,
        direct_opener=lambda request, timeout: _Response(200, b"must not run"),
    )

    assert transport._proxy_url("https://example.test/feed") == "http://explicit.invalid:8080"
    result = transport.fetch("https://example.test/feed")

    assert seen == ["https://example.test/feed"]
    assert result.body == b"explicit body"
    assert result.receipt["proxy_used"] is True


def test_launchd_proxy_environment_uses_current_system_proxy_and_loopback_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.getproxies_macosx_sysconf",
        lambda: {
            "http": "http://127.0.0.1:7897",
            "https": "http://127.0.0.1:7897",
        },
    )

    environment = build_proxy_environment({})

    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        assert environment[key] == "http://127.0.0.1:7897"
    for key in ("NO_PROXY", "no_proxy"):
        assert environment[key] == "127.0.0.1,localhost,::1"


def test_launchd_proxy_environment_prefers_explicit_v35_proxy_over_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "urllib.request.getproxies_macosx_sysconf",
        lambda: {"http": "http://127.0.0.1:7897"},
    )

    environment = build_proxy_environment(
        {"V4_RESEARCH_PROXY_URL": "http://127.0.0.1:7901"}
    )

    assert environment["HTTP_PROXY"] == "http://127.0.0.1:7901"
    assert environment["HTTPS_PROXY"] == "http://127.0.0.1:7901"


def test_ai_news_transport_failure_publishes_exact_date_cannot_confirm(
    tmp_path: Path,
) -> None:
    def fail_fetch(_url: str, _timeout: int):
        raise URLError("AIHot unavailable")

    result = peripherals.materialize_ai_news(
        data_root=tmp_path / "data",
        trade_date="20260820",
        fetch_html=fail_fetch,
        translate_text=None,
    )

    payload = result["payload"]
    assert payload["trade_date"] == "20260820"
    assert payload["source"] == "ai_news"
    assert payload["status"] == "CANNOT_CONFIRM"
    assert payload["item_count"] == 0
    assert "AIHOT_PUBLIC_PAGE_FETCH_FAILED" in payload["cannot_confirm"]
    assert result["payload_path"] == "research/peripherals/20260820/ai_news.json"
    assert result["receipt_path"] == "receipts/research/peripherals/20260820/ai_news.json"

    store = ResearchPeripheralStore(tmp_path / "data")
    persisted = store.read_exact("20260820", "ai_news")
    assert persisted is not None
    assert persisted["status"] == "CANNOT_CONFIRM"
    assert persisted["cannot_confirm"] == payload["cannot_confirm"]


def test_ai_news_http_contract_failure_publishes_typed_receipt(
    tmp_path: Path,
) -> None:
    def fail_proxy(request, timeout):
        raise HTTPError(
            request.full_url,
            503,
            "AIHot contract unavailable",
            {},
            io.BytesIO(),
        )

    result = peripherals.materialize_ai_news(
        data_root=tmp_path / "data",
        trade_date="20260820",
        transport=ProxyAwareHTTPTransport(
            proxy_url="http://127.0.0.1:7897",
            proxy_opener=fail_proxy,
            direct_opener=lambda request, timeout: _Response(200, b"must not run"),
        ),
        translate_text=None,
    )

    payload = result["payload"]
    assert payload["status"] == "CANNOT_CONFIRM"
    assert "AIHOT_HTTP_CONTRACT_FAILED" in payload["cannot_confirm"]
    assert payload["feed_receipts"][0]["http_status"] == 503
    assert payload["feed_receipts"][0]["fallback_used"] is False


def test_ai_news_failure_keeps_both_source_summary_auditable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_fetch(_url: str, _timeout: int):
        raise URLError("AIHot unavailable")

    def fake_external(**_kwargs):
        return {
            "payload": {
                "source": "external_finance",
                "status": "READY_EMPTY",
                "item_count": 0,
                "cannot_confirm": [],
            },
            "payload_path": "research/peripherals/20260820/external_finance.json",
            "receipt_path": "receipts/research/peripherals/20260820/external_finance.json",
        }

    real_ai = peripherals.materialize_ai_news

    def fake_ai(**kwargs):
        return real_ai(
            **kwargs,
            fetch_html=fail_fetch,
            translate_text=None,
        )

    monkeypatch.setattr(peripherals, "materialize_external_finance", fake_external)
    monkeypatch.setattr(peripherals, "materialize_ai_news", fake_ai)

    exit_code = peripherals.main(
        [
            "--data-root",
            str(tmp_path / "data"),
            "--trade-date",
            "20260820",
            "--source",
            "both",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert summary["source"] == "both"
    assert [item["source"] for item in summary["outputs"]] == [
        "external_finance",
        "ai_news",
    ]
    assert summary["outputs"][1]["status"] == "CANNOT_CONFIRM"
    assert summary["outputs"][1]["payload_path"].endswith(
        "/20260820/ai_news.json"
    )
