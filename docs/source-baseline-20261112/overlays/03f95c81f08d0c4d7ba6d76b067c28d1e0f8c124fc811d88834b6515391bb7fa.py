from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlsplit

from ops import materialize_research_peripherals as peripherals


_FETCHED_AT = datetime(2026, 8, 27, 4, 0, tzinfo=timezone.utc)
_DUPLICATE_TITLE = "Markets digest: China and US equities react to policy update"


def _rss(title: str, *, source: str = "Reuters", published: str = "Thu, 27 Aug 2026 03:55:00 GMT") -> bytes:
    return f"""<?xml version='1.0'?>
<rss><channel><item>
<title>{title} - {source}</title>
<link>https://example.test/{title.replace(' ', '-').lower()}</link>
<description>Market evidence for a research-only discovery feed.</description>
<pubDate>{published}</pubDate>
<source url="https://{source.lower()}.example.test">{source}</source>
</item></channel></rss>""".encode("utf-8")


def test_default_subscriptions_keep_eight_and_add_three_market_groups() -> None:
    subscriptions = peripherals.DEFAULT_SUBSCRIPTIONS
    ids = [str(item["id"]) for item in subscriptions]

    assert len(ids) == 11
    assert len(ids) == len(set(ids))
    assert {
        "authority_china_hk",
        "china_hk_stocks",
        "china_tech_ai_semis",
        "hk_ipo_new_economy",
        "ai_compute_chip",
        "robotics_autonomous",
        "commercial_space",
        "biopharma_ma",
    }.issubset(ids)
    assert {"A_SHARE", "HK_CONNECT_RELATED", "US_EQUITY"}.issubset(ids)

    by_id = {str(item["id"]): item for item in subscriptions}
    assert by_id["A_SHARE"]["market_scopes"] == ["A_SHARE"]
    assert by_id["HK_CONNECT_RELATED"]["market_scopes"] == ["HK_CONNECT_RELATED"]
    assert by_id["US_EQUITY"]["market_scopes"] == ["US_EQUITY"]
    assert all("market_scopes" in item for item in subscriptions)


def test_market_scope_and_subscription_union_survive_cross_feed_dedupe() -> None:
    calls: list[str] = []

    def fetch_rss(url: str, timeout: int) -> bytes:
        calls.append(url)
        query = unquote(parse_qs(urlsplit(url).query)["q"][0])
        if "A-share" in query or "Hong Kong Stock Connect" in query or "US stocks" in query:
            return _rss(_DUPLICATE_TITLE)
        return _rss(f"{len(calls)} market earnings report")

    payload = peripherals.build_external_finance_payload(
        "20260827",
        fetched_at=_FETCHED_AT,
        fetch_rss=fetch_rss,
        translate_text=None,
        resolve_original_url=None,
        limit_per_feed=2,
        max_items=36,
    )

    assert len(calls) == 11
    assert len(payload["feed_receipts"]) == 11
    assert len({receipt["feed_id"] for receipt in payload["feed_receipts"]}) == 11
    receipt_by_id = {receipt["feed_id"]: receipt for receipt in payload["feed_receipts"]}
    assert receipt_by_id["A_SHARE"]["market_scopes"] == ["A_SHARE"]
    assert receipt_by_id["HK_CONNECT_RELATED"]["market_scopes"] == ["HK_CONNECT_RELATED"]
    assert receipt_by_id["US_EQUITY"]["market_scopes"] == ["US_EQUITY"]

    duplicates = [row for row in payload["details"] if row["title"] == _DUPLICATE_TITLE]
    assert len(duplicates) == 1
    row = duplicates[0]
    assert row["subscription_ids"] == ["A_SHARE", "HK_CONNECT_RELATED", "US_EQUITY"]
    assert row["market_scopes"] == ["A_SHARE", "HK_CONNECT_RELATED", "US_EQUITY"]
    assert row["recommendation_status"] == "RESEARCH_ONLY"
    overview_row = next(item for item in payload["overview"] if item["title"] == _DUPLICATE_TITLE)
    assert overview_row["subscription_ids"] == row["subscription_ids"]
    assert overview_row["market_scopes"] == row["market_scopes"]
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_missing_market_scope_is_explicit_unknown_not_inferred() -> None:
    payload = peripherals.build_external_finance_payload(
        "20260827",
        fetched_at=_FETCHED_AT,
        subscriptions=({"id": "legacy_without_scope", "query": "legacy market"},),
        fetch_rss=lambda url, timeout: _rss("Legacy market report"),
        translate_text=None,
        resolve_original_url=None,
    )

    row = payload["details"][0]
    assert row["market_scopes"] == ["UNKNOWN"]
    assert row["subscription_ids"] == ["legacy_without_scope"]
    assert "MARKET_SCOPE_UNKNOWN" in row["cannot_confirm"]
    assert "MARKET_SCOPE_UNKNOWN" in payload["cannot_confirm"]
