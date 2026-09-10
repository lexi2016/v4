"""Focused R2 regressions for external finance admission and translation."""
from __future__ import annotations

from ops import materialize_research_peripherals as peripherals


def _rss(*items: str) -> bytes:
    return (
        "<?xml version='1.0'?><rss><channel>"
        + "".join(items)
        + "</channel></rss>"
    ).encode()


def _rss_item(
    *, title: str, link: str, published: str | None, source: str = "South China Morning Post"
) -> str:
    pub = f"<pubDate>{published}</pubDate>" if published is not None else ""
    return (
        "<item>"
        f"<title>{title}</title><link>{link}</link>"
        "<description>Source evidence.</description>"
        f"<source url='https://{source.lower().replace(' ', '')}.example'>{source}</source>"
        f"{pub}</item>"
    )


def test_external_finance_rejects_stale_homepage_directories_and_missing_dates() -> None:
    rss = _rss(
        _rss_item(
            title="SCMP homepage broad news index",
            link="https://www.scmp.com/",
            published="Thu, 30 Aug 2012 18:38:43 GMT",
        ),
        _rss_item(
            title="TradingView ETF directory page",
            link="https://www.tradingview.com/symbols/FWB-ZCH/etfs/",
            published="Sun, 06 Sep 2026 02:03:24 GMT",
            source="TradingView",
        ),
        _rss_item(
            title="Fresh dated article",
            link="https://www.scmp.com/business/article/3367000/fresh",
            published="Sun, 06 Sep 2026 02:03:24 GMT",
        ),
        _rss_item(
            title="Missing publication date",
            link="https://www.scmp.com/business/article/3367001/missing-date",
            published=None,
        ),
    )

    payload = peripherals.build_external_finance_payload(
        "20260907",
        fetched_at="2026-09-07T01:00:00+00:00",
        subscriptions=({"id": "frozen", "query": "frozen", "theme_bucket": "china_hk_stocks"},),
        fetch_rss=lambda _url, _timeout: rss,
        translate_text=None,
        resolve_original_url=None,
        lookback_days=2,
    )

    assert payload["status"] == "READY"
    assert payload["item_count"] == 1
    assert payload["details"][0]["title"] == "Fresh dated article"
    assert payload["details"][0]["url"] == "https://www.scmp.com/business/article/3367000/fresh"
    assert "EXTERNAL_FINANCE_ITEM_STALE" in payload["cannot_confirm"]
    assert "EXTERNAL_FINANCE_PAGE_NOT_ARTICLE" in payload["cannot_confirm"]
    assert "EXTERNAL_FINANCE_PUBLICATION_DATE_MISSING" in payload["cannot_confirm"]


def test_external_finance_all_rejected_rows_stay_cannot_confirm() -> None:
    payload = peripherals.build_external_finance_payload(
        "20260907",
        fetched_at="2026-09-07T01:00:00+00:00",
        subscriptions=({"id": "frozen", "query": "frozen", "theme_bucket": "china_hk_stocks"},),
        fetch_rss=lambda _url, _timeout: _rss(
            _rss_item(
                title="SCMP homepage broad news index",
                link="https://www.scmp.com/",
                published="Thu, 30 Aug 2012 18:38:43 GMT",
            )
        ),
        translate_text=None,
        resolve_original_url=None,
        lookback_days=2,
    )

    assert payload["status"] == "CANNOT_CONFIRM"
    assert payload["item_count"] == 0
    assert "EXTERNAL_FINANCE_ITEM_STALE" in payload["cannot_confirm"]
    assert "EXTERNAL_FINANCE_PAGE_NOT_ARTICLE" in payload["cannot_confirm"]


def test_resolved_homepage_or_directory_is_not_verified_publisher_article() -> None:
    source = {
        "title": "TradingView ETF directory page",
        "url": "https://news.google.com/rss/articles/frozen",
        "source_url": "https://news.google.com/rss/articles/frozen",
        "published_at": "2026-09-06T02:03:24Z",
        "fetched_at": "2026-09-07T01:00:00Z",
    }
    resolved = peripherals._resolve_original_row(
        source,
        resolver=lambda _url, _timeout: "https://www.tradingview.com/symbols/FWB-ZCH/etfs/",
        timeout=1,
    )

    assert resolved["original_url_status"] == "CANNOT_CONFIRM"
    assert resolved["original_url"] == ""
    assert resolved["url"] == ""


def _finance_row(title: str) -> dict[str, str]:
    return {
        "subscription_id": "authority_china_hk",
        "title": title,
        "summary": title,
        "source_name": "Reuters",
        "source_url": "https://www.reuters.com/world/china/frozen-article",
        "url": "https://www.reuters.com/world/china/frozen-article",
        "published_at": "2026-09-07T00:00:00Z",
    }


def test_finance_translation_scale_mismatch_cannot_be_ready() -> None:
    source = _finance_row("China's Moonshot seeks up to $5 Billion in HK IPO this year")
    row = peripherals._translate_row(
        source,
        translate_text=lambda _value, _timeout: "中国的Moonshot今年将在香港IPO寻求高达50 美元",
        timeout=1,
    )

    assert row["translation_status"] == "CANNOT_CONFIRM"
    assert "title_zh" not in row
    assert row["title"] == source["title"]
    assert "ZH_TRANSLATION_AMOUNT_MISMATCH" in row["cannot_confirm"]


def test_finance_translation_preserves_billion_magnitude_before_ready() -> None:
    source = _finance_row("China's Moonshot seeks up to $5 Billion in HK IPO this year")
    row = peripherals._translate_row(
        source,
        translate_text=lambda _value, _timeout: "中国的Moonshot今年将在香港IPO寻求高达50亿美元",
        timeout=1,
    )

    assert row["translation_status"] == "READY"
    assert row["title_zh"] == "中国的Moonshot今年将在香港IPO寻求高达50亿美元"
    assert "ZH_TRANSLATION_AMOUNT_MISMATCH" not in row["cannot_confirm"]


def test_finance_translation_corpus_handles_decimals_units_and_currencies() -> None:
    cases = (
        ("$1.74 billion", "17.4亿美元"),
        ("$1.74 million", "174万美元"),
        ("HK$2 million", "200万港元"),
        ("€2.5 million", "250万欧元"),
        ("JPY 3.2 billion", "32亿日元"),
    )
    for source, translated in cases:
        assert peripherals._validate_finance_translation(source, translated) is True
