from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared_data.public_morning_news import (
    _BASE,
    _KEYWORDS,
    _SLOTS,
    _default_fetcher,
    _article_publication,
    _search_title,
    _search_url,
    MorningNewsNotReady,
    _homepage_records,
    collect_public_morning_news,
)
from shared_data.morning_news import publish_morning_news, read_morning_news


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "exact-search-morning-news-20260824"


def _fixture_fetcher() -> tuple[dict[str, str], dict[str, object]]:
    manifest = json.loads((FIXTURE_ROOT / "capture-manifest.json").read_text(encoding="utf-8"))
    mapping = {"https://www.jiuyangongshe.com/": (FIXTURE_ROOT / "homepage.html").read_text(encoding="utf-8")}
    for record in manifest["records"]:
        mapping[record["search_url"]] = (FIXTURE_ROOT / Path(record["search_path"]).name).read_text(encoding="utf-8")
        mapping[record["article_url"]] = (FIXTURE_ROOT / Path(record["article_path"]).name).read_text(encoding="utf-8")
    return mapping, manifest


def _search_card(slot: str, article_id: str, published_at: str = "2026-08-24 07:00:00") -> str:
    title = _search_title(slot, "20260824")
    return f'<div>{published_at} {title}<a href="/a/{article_id}">{title}</a></div>'


def _article_html(title: str, published_at: str, body: str, article_id: str) -> str:
    return (
        f"<html><head><title>{title}-韭研公社</title></head>"
        f'<body>content:"{body}"</body>'
        f'<script>window.__NUXT__=(function(){{return {{data:[{{data:{{article_id:"{article_id}",'
        f'title:"{title}",create_time:"{published_at}"}},commendPage:{{result:[]}}}}],'
        f'routePath:"\\u002Fa\\u002F{article_id}"}};}})();</script></html>'
    )


def test_frozen_homepage_reproduces_real_one_of_three_discovery_gap() -> None:
    mapping, _manifest = _fixture_fetcher()
    homepage_records = _homepage_records(mapping["https://www.jiuyangongshe.com/"])
    exact_morning = [
        row
        for row in homepage_records
        if row["published_at"].startswith("2026-08-24")
        and any(keyword in row["title"] for keyword in _KEYWORDS)
    ]

    assert len(exact_morning) == 1
    assert exact_morning[0]["title"] == "8月24日盘前纪要"


def test_frozen_exact_search_fallback_materializes_all_three_required_slots() -> None:
    mapping, manifest = _fixture_fetcher()

    def fetcher(url: str) -> str:
        return mapping[url]

    payload = collect_public_morning_news("20260824", fetcher=fetcher)

    expected_records = manifest["records"]
    assert payload["status"] == "MORNING_NEWS_READY"
    assert payload["required_news_contract"]["ok"] is True
    assert payload["required_news_contract"]["article_count"] == 3
    assert payload["required_news_contract"]["missing_required_slots"] == []
    assert {row["url"] for row in payload["articles"]} == {
        record["article_url"] for record in expected_records
    }
    assert {row["category"] for row in payload["articles"]} == {
        "开盘必读",
        "盘前纪要",
        "盘前解读",
    }
    assert all(row["published_at"].startswith("2026-08-24") for row in payload["articles"])
    assert all(row["body_status"] == "ARTICLE_BODY_READ" for row in payload["articles"])
    assert all(len(row["body_text"]) >= 300 for row in payload["articles"])


def test_capture_time_is_utc_and_article_publication_keeps_unknown_timezone() -> None:
    mapping, _manifest = _fixture_fetcher()
    fixed_capture = datetime(2026, 10, 15, 6, 44, 36, 848785, tzinfo=timezone.utc)

    payload = collect_public_morning_news(
        "20260824",
        fetcher=mapping.__getitem__,
        clock=lambda: fixed_capture,
    )

    for article in payload["articles"]:
        assert article["fetched_at"] == "2026-10-15T06:44:36.848785+00:00"
        assert article["capture_time_source"] == "SUCCESSFUL_ARTICLE_RESPONSE_BODY_READ"
        assert article["capture_time_evidence_sha256"] == payload["source_hashes"][article["url"]]
        assert article["source_published_at_field"] == "window.__NUXT__.data[0].data.create_time"
        assert article["source_published_at_raw"] == article["published_at"]
        assert article["source_published_at_timezone_status"] == "TIMEZONE_UNKNOWN"
        assert "published_at_utc" not in article
        assert article["published_at"] != article["fetched_at"]


def test_default_fetcher_timestamps_immediately_after_response_body_read(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    response_bytes = "<html>响应文本</html>".encode("gbk")
    fixed = datetime(2026, 10, 15, 6, 44, 36, 848785, tzinfo=timezone.utc)

    class FakeResponse:
        headers = {"content-type": "text/html; charset=gbk"}

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            events.append("read")
            return response_bytes

    monkeypatch.setattr(
        "shared_data.public_morning_news.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    page = _default_fetcher("https://example.test/article", clock=lambda: events.append("clock") or fixed)

    assert events == ["read", "clock"]
    assert page.text == response_bytes.decode("gbk")
    assert page.response_sha256 == hashlib.sha256(page.text.encode("utf-8")).hexdigest()
    assert page.response_sha256 != hashlib.sha256(response_bytes).hexdigest()
    assert page.captured_at_utc == "2026-10-15T06:44:36.848785+00:00"


def test_article_publication_uses_bound_main_record_and_explicit_offset() -> None:
    article_id = "extraopenlegal"
    raw = _article_html(
        "8月24日开盘必读资讯",
        "2026-08-24T07:54:00+08:00",
        "无关正文日期 2026-08-23 23:59:59 " + "合法额外开盘正文 " * 80,
        article_id,
    )

    publication = _article_publication(raw, article_id)

    assert publication is not None
    assert publication["published_at"] == "2026-08-24T07:54:00+08:00"
    assert publication["source_published_at_raw"] == "2026-08-24T07:54:00+08:00"
    assert publication["source_published_at_timezone_status"] == "EXPLICIT_OFFSET"
    assert publication["published_at_utc"] == "2026-08-23T23:54:00.000000+00:00"
    assert _article_publication(raw, "differentarticle") is None


def test_article_publication_ignores_server_epoch_and_body_date() -> None:
    raw = (
        '<body>2026-08-24 07:00:00 content:"正文日期"</body>'
        '<script>window.__NUXT__=(function(){return {data:[{data:{article_id:"id12345678",'
        'title:"8月24日开盘必读资讯"},commendPage:{result:[]}}],serverTime:1792046676,'
        'routePath:"\\u002Fa\\u002Fid12345678"};})();</script>'
    )

    assert _article_publication(raw, "id12345678") is None


def test_article_bound_epoch_is_normalized_to_utc() -> None:
    article_id = "epocharticle123"
    raw = _article_html("8月24日盘前纪要", "2026-08-24 07:00:00", "正文 " * 200, article_id)
    raw = raw.replace('create_time:"2026-08-24 07:00:00"', "create_time:1792046676")

    publication = _article_publication(raw, article_id)

    assert publication is not None
    assert publication["source_published_at_raw"] == "1792046676"
    assert publication["source_published_at_timezone_status"] == "EXPLICIT_EPOCH_UTC"
    assert publication["published_at_utc"] == "2026-10-15T06:44:36.000000+00:00"


def test_successful_article_retry_gets_capture_time_only_on_success() -> None:
    mapping, manifest = _fixture_fetcher()
    article_url = next(record["article_url"] for record in manifest["records"] if record["slot"] == "盘前纪要")
    calls: Counter[str] = Counter()
    successful_responses = 0
    clock_calls = 0
    start = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)

    def fetcher(url: str) -> str:
        nonlocal successful_responses
        calls[url] += 1
        if url == article_url and calls[url] == 1:
            raise TimeoutError("fixture first attempt timeout")
        successful_responses += 1
        return mapping[url]

    def clock() -> datetime:
        nonlocal clock_calls
        value = start + timedelta(seconds=clock_calls)
        clock_calls += 1
        return value

    payload = collect_public_morning_news("20260824", fetcher=fetcher, clock=clock)

    article = next(row for row in payload["articles"] if row["url"] == article_url)
    assert calls[article_url] == 2
    assert clock_calls == successful_responses
    assert article["fetched_at"] == "2026-10-15T06:00:01.000000+00:00"


def test_capture_metadata_survives_immutable_publish_and_read(tmp_path: Path) -> None:
    mapping, _manifest = _fixture_fetcher()
    fixed_capture = datetime(2026, 10, 15, 6, 44, 36, tzinfo=timezone.utc)
    payload = collect_public_morning_news(
        "20260824",
        fetcher=mapping.__getitem__,
        clock=lambda: fixed_capture,
    )

    published = publish_morning_news(tmp_path, payload)
    restored = read_morning_news(tmp_path, "20260824")
    artifact_path = tmp_path / published["payload_relative"]
    original_bytes = artifact_path.read_bytes()
    retried = publish_morning_news(tmp_path, payload)

    assert published["payload_sha256"]
    assert retried["already_exists"] is True
    assert artifact_path.read_bytes() == original_bytes
    assert restored["articles"] == payload["articles"]
    assert all(row["fetched_at"].endswith("+00:00") for row in restored["articles"])


def test_search_fallback_retries_once_and_retains_source_hashes() -> None:
    mapping, manifest = _fixture_fetcher()
    search_url = next(record["search_url"] for record in manifest["records"] if record["slot"] == "开盘必读")
    calls = Counter()

    def fetcher(url: str) -> str:
        calls[url] += 1
        if url == search_url and calls[url] == 1:
            raise TimeoutError("fixture timeout")
        return mapping[url]

    payload = collect_public_morning_news("20260824", fetcher=fetcher)

    assert calls[search_url] == 2
    assert payload["status"] == "MORNING_NEWS_READY"
    for url in payload["discovery"]["search_fallback_urls"] + [
        record["article_url"] for record in manifest["records"]
    ]:
        assert payload["source_hashes"][url] == hashlib.sha256(mapping[url].encode("utf-8")).hexdigest()


def test_search_retry_exhaustion_fails_closed() -> None:
    mapping, manifest = _fixture_fetcher()
    search_url = next(record["search_url"] for record in manifest["records"] if record["slot"] == "开盘必读")
    calls = Counter()
    successful_responses = 0
    clock_calls = 0

    def fetcher(url: str) -> str:
        nonlocal successful_responses
        calls[url] += 1
        if url == search_url:
            raise TimeoutError("fixture timeout")
        successful_responses += 1
        return mapping[url]

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)

    with pytest.raises(MorningNewsNotReady, match="fetch retries exhausted"):
        collect_public_morning_news("20260824", fetcher=fetcher, clock=clock)

    assert calls[search_url] == 2
    assert clock_calls == successful_responses


def test_off_date_search_candidate_is_rejected_fail_closed() -> None:
    mapping, manifest = _fixture_fetcher()
    off_date_mapping = dict(mapping)
    record = next(record for record in manifest["records"] if record["slot"] == "盘前解读")
    off_date_mapping[record["search_url"]] = mapping[record["search_url"]].replace("2026-08-24", "2026-08-23")
    off_date_mapping[record["article_url"]] = mapping[record["article_url"]].replace("2026-08-24", "2026-08-23")

    with pytest.raises(MorningNewsNotReady):
        collect_public_morning_news("20260824", fetcher=off_date_mapping.__getitem__)


def test_missing_required_slot_never_returns_incomplete_payload() -> None:
    mapping, manifest = _fixture_fetcher()
    missing_slot_mapping = dict(mapping)
    record = next(record for record in manifest["records"] if record["slot"] == "盘前解读")
    missing_slot_mapping[record["search_url"]] = "<html><body>no exact-date result</body></html>"

    with pytest.raises(MorningNewsNotReady):
        collect_public_morning_news("20260824", fetcher=missing_slot_mapping.__getitem__)


def test_empty_homepage_and_search_fail_closed_without_article_materialization() -> None:
    calls: list[str] = []

    def fetcher(url: str) -> str:
        calls.append(url)
        return ""

    with pytest.raises(MorningNewsNotReady, match="0/3"):
        collect_public_morning_news("20260824", fetcher=fetcher)

    assert calls == [_BASE] + [_search_url(slot, "20260824") for slot in _SLOTS]
    assert not any("/a/" in url for url in calls)


def test_exact_looking_external_search_link_is_rejected() -> None:
    calls: list[str] = []
    external_id = "evilabc123"

    def fetcher(url: str) -> str:
        calls.append(url)
        if url == _BASE:
            return "<html><body>homepage has no exact-date readable result</body></html>"
        for slot in _SLOTS:
            if url == _search_url(slot, "20260824"):
                title = _search_title(slot, "20260824")
                return (
                    f'<div>2026-08-24 07:00:00 {title}'
                    f'<a href="https://evil.example/a/{external_id}">{title}</a></div>'
                )
        raise AssertionError(f"unexpected fetch URL: {url}")

    with pytest.raises(MorningNewsNotReady, match="0/3"):
        collect_public_morning_news("20260824", fetcher=fetcher)

    assert all(not url.startswith("https://evil.example/") for url in calls)
    assert calls == [_BASE] + [_search_url(slot, "20260824") for slot in _SLOTS]


def test_duplicate_search_candidates_and_article_ids_are_fetched_once() -> None:
    mapping, manifest = _fixture_fetcher()
    record = next(record for record in manifest["records"] if record["slot"] == "开盘必读")
    search_url = record["search_url"]
    article_url = record["article_url"]
    mapping[search_url] += _search_card("开盘必读", record["article_url"].rsplit("/", 1)[-1]) * 2
    calls: Counter[str] = Counter()

    def fetcher(url: str) -> str:
        calls[url] += 1
        return mapping[url]

    payload = collect_public_morning_news("20260824", fetcher=fetcher)

    assert payload["status"] == "MORNING_NEWS_READY"
    assert calls[article_url] == 1
    assert len(payload["articles"]) == len({row["url"] for row in payload["articles"]})


def test_extra_legal_candidate_keeps_three_slot_contract_and_allows_at_least_three() -> None:
    mapping, manifest = _fixture_fetcher()
    record = next(record for record in manifest["records"] if record["slot"] == "开盘必读")
    extra_id = "extraopenlegal"
    mapping[record["search_url"]] += _search_card("开盘必读", extra_id)
    mapping[f"{_BASE}a/{extra_id}"] = _article_html(
        "8月24日开盘必读资讯",
        "2026-08-24T07:54:00+08:00",
        "无关正文日期 2026-08-23 23:59:59 " + "合法额外开盘正文 " * 80,
        extra_id,
    )

    payload = collect_public_morning_news("20260824", fetcher=mapping.__getitem__)

    assert payload["status"] == "MORNING_NEWS_READY"
    assert payload["required_news_contract"]["ok"] is True
    assert payload["required_news_contract"]["article_count"] == 4
    assert payload["required_news_contract"]["slot_counts"] == {
        "开盘必读": 2,
        "盘前纪要": 1,
        "盘前解读": 1,
    }
    assert f"{_BASE}a/{extra_id}" in {row["url"] for row in payload["articles"]}
    extra_article = next(row for row in payload["articles"] if row["url"].endswith(extra_id))
    assert extra_article["published_at"] == "2026-08-24T07:54:00+08:00"
    assert extra_article["source_published_at_timezone_status"] == "EXPLICIT_OFFSET"
    assert extra_article["published_at_utc"] == "2026-08-23T23:54:00.000000+00:00"


def test_body_shorter_than_300_is_not_readable_and_fails_closed() -> None:
    mapping, manifest = _fixture_fetcher()
    record = next(record for record in manifest["records"] if record["slot"] == "盘前解读")
    mapping[record["article_url"]] = _article_html(
        "8月24日盘前解读",
        "2026-08-24 07:05:24",
        "正文不足三百字",
        record["article_url"].rsplit("/", 1)[-1],
    )

    with pytest.raises(MorningNewsNotReady, match="2/3|missing required"):
        collect_public_morning_news("20260824", fetcher=mapping.__getitem__)
