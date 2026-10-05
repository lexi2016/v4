from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from shared_data.public_morning_news import (
    _BASE,
    _KEYWORDS,
    _SLOTS,
    _search_title,
    _search_url,
    MorningNewsNotReady,
    _homepage_records,
    collect_public_morning_news,
)


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


def _article_html(title: str, published_at: str, body: str) -> str:
    return (
        f"<html><head><title>{title}-韭研公社</title></head>"
        f'<body>{published_at} content:"{body}"</body></html>'
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

    def fetcher(url: str) -> str:
        calls[url] += 1
        if url == search_url:
            raise TimeoutError("fixture timeout")
        return mapping[url]

    with pytest.raises(MorningNewsNotReady, match="fetch retries exhausted"):
        collect_public_morning_news("20260824", fetcher=fetcher)

    assert calls[search_url] == 2


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
        "2026-08-24 07:54:00",
        "合法额外开盘正文 " * 80,
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


def test_body_shorter_than_300_is_not_readable_and_fails_closed() -> None:
    mapping, manifest = _fixture_fetcher()
    record = next(record for record in manifest["records"] if record["slot"] == "盘前解读")
    mapping[record["article_url"]] = _article_html(
        "8月24日盘前解读",
        "2026-08-24 07:05:24",
        "正文不足三百字",
    )

    with pytest.raises(MorningNewsNotReady, match="2/3|missing required"):
        collect_public_morning_news("20260824", fetcher=mapping.__getitem__)
