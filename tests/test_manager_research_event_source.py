from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from v4.manager_research.contracts import cutoff_at
from v4.manager_research.event_source import (
    BoundedMediaTransport,
    EventSourceError,
    _classify_hkex_business_clause,
    build_catalyst_advice,
    collect_hkex_event_directory,
    discover_iccsz_events,
    event_is_focus_eligible,
    merge_event_batches,
    parse_hkex_event_document,
    parse_iccsz_article,
    parse_iccsz_directory,
    _split_event_sentences,
)
from v4.manager_research.ports import SourceResponse


MEDIA_HOME = "http://www.iccsz.com/"
MEDIA_URL = "http://www.iccsz.com/site/cn/news/2026/09/08/20260908052023973552.htm"


def response(url: str, body: bytes, *, retrieved_at: str = "2026-09-08T08:20:00+00:00") -> SourceResponse:
    return SourceResponse(
        url=url,
        final_url=url,
        status_code=200,
        body=body,
        headers={"content-type": "text/html"},
        retrieved_at=retrieved_at,
    )


def media_directory(*, include_external: bool = False) -> bytes:
    external = '<a href="https://evil.example/news.html">外部链接</a>' if include_external else ""
    return (
        "<html><body>"
        f'<a href="/site/cn/news/2026/09/08/20260908052023973552.htm">海光芯正携手格罗方德深化全球战略合作</a>'
        f'<a href="/site/cn/news/2026/09/09/future.htm">未来文章</a>{external}'
        "</body></html>"
    ).encode()


def media_article() -> bytes:
    return (
        "<html><head><title>海光芯正携手格罗方德深化全球战略合作</title></head><body>"
        "<h1>海光芯正携手格罗方德深化全球战略合作</h1>"
        "<div class='ableft'>发布时间：2026/9/8 13:18:14</div>"
        "<div class='article_intro'>据报道，双方于9月7日建立长期战略合作。</div>"
        "<div class='articlecontent'>双方围绕硅光平台、全球制造和6.4T NPO推进工程落地与规模化量产，仍需后续确认订单和收入。</div>"
        "</body></html>"
    ).encode()


def media_article_without_publisher_timestamp() -> bytes:
    return (
        "<html><head><title>海光芯正携手格罗方德深化全球战略合作</title></head><body>"
        "<h1>海光芯正携手格罗方德深化全球战略合作</h1>"
        "<div class='article_intro'>据报道，双方于9月7日建立长期战略合作。</div>"
        "<div class='articlecontent'>双方围绕硅光平台和规模化量产推进工程落地，仍需后续确认订单和收入。</div>"
        "</body></html>"
    ).encode()


def observation(code: str = "HK.01191", name: str = "海光芯正") -> dict[str, str]:
    return {"code": code, "name": name}


def test_iccsz_article_preserves_reported_date_and_unconfirmed_realization() -> None:
    article = parse_iccsz_article(
        media_article(),
        url=MEDIA_URL,
        retrieved_at="2026-09-08T08:20:00+00:00",
    )

    assert article["publisher_timestamp"] == "2026-09-08T13:18:14+08:00"
    assert article["reported_event_date_text"] == "9月7日"
    assert "推进工程落地与规模化量产" in article["business_excerpt"] or "推进工程落地与规模化量产" in article["source_excerpt"]
    assert article["counterparty"] == "格罗方德"


def test_iccsz_directory_discovery_is_bounded_exact_and_date_aware() -> None:
    calls: list[str] = []

    def transport(url: str, **_: Any) -> SourceResponse:
        calls.append(url)
        return response(url, media_directory() if url == MEDIA_HOME else media_article())

    bounded = BoundedMediaTransport(transport, max_requests=3)
    current = discover_iccsz_events(
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation()],
        transport=bounded,
        current_event_as_of="2026-09-08T08:30:00+00:00",
    )
    row = current["rows"]["HK.01191"]
    event = row["events"][0]
    assert row["status"] == "READY"
    assert event["as_of_bucket"] == "current"
    assert event["source_kind"] == "MEDIA"
    assert event["official_confirmation_status"] == "PENDING"
    assert event["first_public_announcement_time"] == "CANNOT_CONFIRM"
    assert "推进工程落地与规模化量产" in event["why_might_affect_business"]
    assert "ORDER_OR_REVENUE_UNCONFIRMED" in event["market_confirmation_gap"]
    assert calls == [MEDIA_HOME, MEDIA_URL]

    historical_target = discover_iccsz_events(
        target_trade_date="20260907",
        cutoff_at=cutoff_at("20260907"),
        observations=[observation()],
        transport=BoundedMediaTransport(transport, max_requests=3),
        current_event_as_of="2026-09-08T08:30:00+00:00",
    )
    assert historical_target["rows"]["HK.01191"]["status"] == "NO_MATCH"
    assert historical_target["rows"]["HK.01191"]["coverage"]["no_match_is_not_complete"] is True


def test_iccsz_previous_first_seen_and_name_collision_are_explicit() -> None:
    def transport(url: str, **_: Any) -> SourceResponse:
        return response(url, media_directory() if url == MEDIA_HOME else media_article())

    previous = {
        "HK.01191": {
            "events": [{"source_url": MEDIA_URL, "first_seen_at": "2026-09-08T08:00:00+00:00"}]
        }
    }
    result = discover_iccsz_events(
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation()],
        transport=BoundedMediaTransport(transport, max_requests=3),
        previous_rows=previous,
        current_event_as_of="2026-09-08T14:00:00+00:00",
    )
    assert result["rows"]["HK.01191"]["events"][0]["first_seen_at"] == "2026-09-08T08:00:00+00:00"

    collision = discover_iccsz_events(
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation("HK.01191", "海光芯正"), observation("HK.02222", "海光芯正")],
        transport=BoundedMediaTransport(transport, max_requests=3),
        current_event_as_of="2026-09-08T14:00:00+00:00",
    )
    assert collision["rows"]["HK.01191"]["status"] == "NO_MATCH"
    assert collision["rows"]["HK.02222"]["status"] == "NO_MATCH"
    assert collision["coverage"]["no_match_is_not_complete"] is True


def test_iccsz_parsed_body_without_publisher_timestamp_is_retained_as_unconfirmed() -> None:
    def transport(url: str, **_: Any) -> SourceResponse:
        return response(
            url,
            media_directory() if url == MEDIA_HOME else media_article_without_publisher_timestamp(),
        )

    result = discover_iccsz_events(
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation()],
        transport=BoundedMediaTransport(transport, max_requests=3),
        current_event_as_of="2026-09-08T14:00:00+00:00",
    )
    row = result["rows"]["HK.01191"]
    assert row["status"] == "CANNOT_CONFIRM"
    assert row["reason"] == "PUBLISHER_TIMESTAMP_UNAVAILABLE"
    assert len(row["events"]) == 1
    event = row["events"][0]
    assert event["body_parsed"] is True
    assert event["publisher_timestamp"] == "CANNOT_CONFIRM"
    assert event["as_of_bucket"] is None
    assert event["event_status"] == "CANNOT_CONFIRM"
    assert "PUBLISHER_TIMESTAMP_UNAVAILABLE" in event["market_confirmation_gap"]
    receipt = row["source_receipts"][0]
    assert receipt["status"] == "CANNOT_CONFIRM"
    assert receipt["source_sha256"]
    assert receipt["body_sha256"] == receipt["source_sha256"]
    assert receipt["locator"] == MEDIA_URL
    assert result["source_counts"]["timestamp_unconfirmed"] == 1


def test_unresolved_event_bucket_cannot_enter_focus_or_advice() -> None:
    event = {
        "event_type": "COOPERATION",
        "source_kind": "MEDIA",
        "source_excerpt": "The parties will deliver products under a cooperation agreement.",
        "publisher_timestamp": "2026-09-08T08:00:00+08:00",
        "body_parsed": True,
        "event_relevant": True,
        "event_status": "READY",
        "summary_status": "INTERPRETABLE",
        "as_of_bucket": None,
    }

    assert event_is_focus_eligible(event, target_trade_date="20260908") is False
    advice = build_catalyst_advice([event], target_trade_date="20260908")
    assert advice["status"] == "CANNOT_CONFIRM"
    assert advice["label"] == "CANNOT_CONFIRM（催化时间）"
    assert advice["priority_rank"] is None


def test_iccsz_failure_and_transport_bounds_are_not_silent() -> None:
    def failing(url: str, **_: Any) -> SourceResponse:
        raise OSError("fixture unavailable")

    failed = discover_iccsz_events(
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation()],
        transport=BoundedMediaTransport(failing, max_requests=1),
    )
    assert failed["rows"]["HK.01191"]["status"] == "CANNOT_CONFIRM"
    assert failed["coverage"]["status"] == "CANNOT_CONFIRM"

    bounded = BoundedMediaTransport(lambda url, **_: response(url, b"<html></html>"), max_requests=1)
    bounded.request(MEDIA_HOME)
    with pytest.raises(EventSourceError, match="bound exceeded"):
        bounded.request(MEDIA_URL)
    with pytest.raises(EventSourceError, match="refused"):
        bounded.request("https://evil.example/article.html")


def test_hkex_directory_keeps_nonfinancial_rows_directory_only() -> None:
    html = """
    <table>
      <tr><td class="release-time">Release Time: 08/09/2026 08:30</td><td class="stock-short-code">Stock Code: 01191</td><td class="stock-short-name">Stock Short Name: 海光芯正</td><td><div class="headline">Cooperation agreement with partner</div><div class="doc-link"><a href="/listedco/listconews/sehk/2026/0908/demo.pdf">Announcement</a></div></td></tr>
      <tr><td class="release-time">Release Time: 08/09/2026 09:00</td><td class="stock-short-code">Stock Code: 01191</td><td class="stock-short-name">Stock Short Name: 海光芯正</td><td><div class="headline">Annual Results Announcement</div><div class="doc-link"><a href="/listedco/listconews/sehk/2026/0908/results.pdf">Results</a></div></td></tr>
    </table>
    """.encode()

    class Provider:
        def __init__(self) -> None:
            self.payload = html

        def _load_active_stocks(self):
            return ({"01191": {"stock_id": "42", "issuer": "海光芯正"}}, "mapping-sha", "2026-09-08T08:00:00+00:00")

        def _request(self, url: str, **kwargs: Any) -> SourceResponse:
            method = kwargs.get("method", "GET")
            return response(url, self.payload if method == "POST" else b"<html></html>")

    batch = collect_hkex_event_directory(
        Provider(),
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation()],
        current_event_as_of="2026-09-08T14:00:00+00:00",
    )
    row = batch["rows"]["HK.01191"]
    assert row["status"] == "DIRECTORY_ONLY"
    assert len(row["events"]) == 1
    assert row["events"][0]["source_kind"] == "OFFICIAL"
    assert row["events"][0]["body_parsed"] is False
    assert row["events"][0]["as_of_bucket"] == "historical"


def test_hkex_event_pdf_parser_keeps_page_excerpt_and_excludes_routine_body(monkeypatch: pytest.MonkeyPatch) -> None:
    import v4.manager_research.event_source as event_source

    monkeypatch.setattr(
        event_source,
        "extract_pdf_pages",
        lambda _body: [{"page": 7, "text": "The issuer entered into a cooperation agreement with a customer for product mass production."}],
    )
    parsed = parse_hkex_event_document(b"%PDF-fixture", title="Voluntary Announcement")
    assert parsed["body_parsed"] is True
    assert parsed["event_relevant"] is True
    assert parsed["event_kind"] == "COOPERATION"
    assert parsed["evidence_page"] == 7
    assert "cooperation agreement" in parsed["source_excerpt"]

    monkeypatch.setattr(
        event_source,
        "extract_pdf_pages",
        lambda _body: [{"page": 1, "text": "The document is published for information only. Registered office details follow."}],
    )
    routine = parse_hkex_event_document(b"%PDF-fixture", title="Voluntary Announcement")
    assert routine["body_parsed"] is True
    assert routine["event_relevant"] is False
    assert routine["parse_status"] == "BODY_PARSED_NON_SUBSTANTIVE"
    assert "不计重大催化" in routine["exclusion_reason"]

    governance = parse_hkex_event_document(b"%PDF-fixture", title="POLL RESULTS OF THE EXTRAORDINARY GENERAL MEETING")
    assert governance["body_parsed"] is True
    assert governance["event_relevant"] is False
    assert governance["parse_reason"] == "HKEX_EVENT_ROUTINE_DOCUMENT_EXCLUDED"

    oversized = parse_hkex_event_document(b"%PDF" + b"x" * 32, title="Announcement", max_bytes=8)
    assert oversized["body_parsed"] is False
    assert oversized["parse_reason"] == "HKEX_EVENT_PDF_BYTE_BUDGET_EXCEEDED"


def test_hkex_event_pdf_parser_keeps_legal_signature_text_unconfirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    import v4.manager_research.event_source as event_source

    monkeypatch.setattr(
        event_source,
        "extract_pdf_pages",
        lambda _body: [{
            "page": 3,
            "text": "By order of the Board, the company will deliver products to customers pursuant to the Listing Rules.",
        }],
    )
    parsed = parse_hkex_event_document(b"%PDF-fixture", title="Announcement")

    assert parsed["body_parsed"] is True
    assert parsed["parse_status"] == "BODY_PARSED_SUMMARY_UNCONFIRMED"
    assert parsed["parse_reason"] == "HKEX_EVENT_LEGAL_OR_SIGNATURE_TEXT"
    assert parsed["event_relevant"] is False
    assert parsed["source_excerpt"]

    monkeypatch.setattr(
        event_source,
        "extract_pdf_pages",
        lambda _body: [{"page": 4, "text": "Cooperation agreement"}],
    )
    short = parse_hkex_event_document(b"%PDF-fixture", title="Announcement")
    assert short["parse_status"] == "BODY_PARSED_SUMMARY_UNCONFIRMED"
    assert short["parse_reason"] == "HKEX_EVENT_BUSINESS_CLAUSE_TOO_SHORT"
    assert short["event_relevant"] is False


@pytest.mark.parametrize(
    ("excerpt", "score", "expected_kind", "expected_reason"),
    [
        (
            "The company is a developer of technology and derives revenue from collaboration agreements.",
            2,
            None,
            "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED",
        ),
        (
            "included in the list of eligible securities for the Stock Connect",
            3,
            None,
            "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED",
        ),
        (
            "to the eligible securities of Hong Kong Stock Connect published on the official website of the",
            2,
            None,
            "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED",
        ),
        (
            "H Shares have been included in the list of eligible securities for",
            3,
            None,
            "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED",
        ),
        (
            "The issuer entered into a cooperation agreement with a customer for product mass production.",
            3,
            "COOPERATION",
            None,
        ),
        (
            "(“H Shares ”) have been included in the list of eligible securities for the Stock Connect ( “Stock",
            3,
            "MARKET_ACCESS",
            None,
        ),
    ],
)
def test_shared_hkex_classifier_requires_action_bridge_before_keyword_score(
    excerpt: str,
    score: int,
    expected_kind: str | None,
    expected_reason: str | None,
) -> None:
    assert _classify_hkex_business_clause(excerpt, score) == (expected_kind, expected_reason)


@pytest.mark.parametrize(
    ("excerpt", "score", "expected_kind"),
    [
        (
            "The company has customers and contracts.",
            2,
            None,
        ),
        (
            "The company is subject to regulatory approval requirements.",
            2,
            None,
        ),
        (
            "The company has products and technology.",
            2,
            None,
        ),
        (
            "The company is a developer. Entered into a cooperation agreement with a customer.",
            3,
            None,
        ),
        (
            "The company owns H Shares. Have been included in the list of eligible securities for the Stock Connect.",
            3,
            None,
        ),
        (
            "The company received orders from a customer.",
            2,
            "ORDER_OR_CUSTOMER",
        ),
        (
            "The company obtained regulatory approval.",
            2,
            "REGULATORY",
        ),
        (
            "The company launched a technology platform.",
            2,
            "PRODUCT_OR_TECHNOLOGY",
        ),
    ],
)
def test_shared_hkex_classifier_uses_kind_specific_single_clause_action_gates(
    excerpt: str,
    score: int,
    expected_kind: str | None,
) -> None:
    expected = (expected_kind, None) if expected_kind else (None, "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED")
    assert _classify_hkex_business_clause(excerpt, score) == expected


@pytest.mark.parametrize(
    "excerpt",
    [
        "The company has customers and contracts.",
        "The company is subject to regulatory approval requirements.",
        "The company is a developer. Entered into a cooperation agreement with a customer.",
        "The company owns H Shares. Have been included in the list of eligible securities for the Stock Connect.",
    ],
)
def test_hkex_fresh_parser_keeps_static_and_cross_sentence_fragments_unconfirmed(
    monkeypatch: pytest.MonkeyPatch,
    excerpt: str,
) -> None:
    import v4.manager_research.event_source as event_source

    monkeypatch.setattr(
        event_source,
        "extract_pdf_pages",
        lambda _body, excerpt=excerpt: [{"page": 2, "text": excerpt}],
    )

    parsed = parse_hkex_event_document(b"%PDF-fixture", title="Announcement")

    assert parsed["body_parsed"] is True
    assert parsed["parse_status"] == "BODY_PARSED_SUMMARY_UNCONFIRMED"
    assert parsed["parse_reason"] == "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED"
    assert parsed["event_relevant"] is False
    assert parsed["event_status"] == "CANNOT_CONFIRM"
    assert parsed["summary_status"] == "UNCONFIRMED"


@pytest.mark.parametrize(
    ("excerpt", "expected_kind"),
    [
        ("The company entered into a loan agreement with a bank.", None),
        ("The company signed an employment agreement with its CEO.", None),
        ("The company reached a settlement agreement with a supplier.", None),
        ("The company announced an agreement.", None),
        ("The company received orders worth HK$1.5 billion.", "ORDER_OR_CUSTOMER"),
        ("The company launched a technology platform version 1.0.", "PRODUCT_OR_TECHNOLOGY"),
        ("The company obtained regulatory approval on 2026.09.08.", "REGULATORY"),
        ("The company launched a U.S. technology platform.", "PRODUCT_OR_TECHNOLOGY"),
    ],
)
def test_hkex_shared_gate_handles_agreement_semantics_and_protected_punctuation(
    excerpt: str,
    expected_kind: str | None,
) -> None:
    score = sum(
        1
        for token in (
            "agreement",
            "orders",
            "customer",
            "regulatory",
            "approval",
            "technology",
            "platform",
        )
        if token in excerpt.lower()
    )
    expected = (expected_kind, None) if expected_kind else (None, "HKEX_EVENT_BUSINESS_ACTION_UNCONFIRMED")
    assert _classify_hkex_business_clause(excerpt, score) == expected


@pytest.mark.parametrize(
    ("excerpt", "expected_kind"),
    [
        (
            "The company has customers and contracts. The company received orders from a customer.",
            "ORDER_OR_CUSTOMER",
        ),
        (
            "The company is subject to regulatory approval requirements. The company obtained regulatory approval.",
            "REGULATORY",
        ),
    ],
)
def test_hkex_fresh_parser_selects_valid_action_after_static_background(
    monkeypatch: pytest.MonkeyPatch,
    excerpt: str,
    expected_kind: str,
) -> None:
    import v4.manager_research.event_source as event_source

    monkeypatch.setattr(
        event_source,
        "extract_pdf_pages",
        lambda _body, excerpt=excerpt: [{"page": 4, "text": excerpt}],
    )

    parsed = parse_hkex_event_document(b"%PDF-fixture", title="Announcement")

    assert parsed["parse_status"] == "BODY_PARSED_EVENT"
    assert parsed["parse_reason"] == "HKEX_EVENT_BODY_SUBSTANTIVE_EVENT_TEXT"
    assert parsed["event_relevant"] is True
    assert parsed["event_kind"] == expected_kind
    assert "The company received orders" in parsed["source_excerpt"] or "obtained regulatory approval" in parsed["source_excerpt"]


@pytest.mark.parametrize(
    "excerpt",
    [
        "The company has customers and contracts.” A partner received orders from a customer.",
        "The company has customers and contracts.） A partner received orders from a customer.",
        "The company has customers and contracts.》 A partner received orders from a customer.",
    ],
)
def test_unicode_closing_delimiters_end_the_prior_sentence(excerpt: str) -> None:
    sentences = _split_event_sentences(excerpt)

    assert len(sentences) == 2
    assert sentences[0].endswith((".”", ".）", ".》"))
    assert sentences[1].startswith("A partner")


@pytest.mark.parametrize(
    ("excerpt", "expected_kind"),
    [
        (
            "The company has customers and contracts.” A partner received orders from a customer.",
            None,
        ),
        (
            "The company has a business.） A partner launched a technology platform.",
            None,
        ),
        (
            "The company has requirements.》 A regulator obtained regulatory approval.",
            None,
        ),
        (
            "The company has background.” The company received orders from a customer.",
            "ORDER_OR_CUSTOMER",
        ),
        (
            "The company has background.） The company launched a technology platform.",
            "PRODUCT_OR_TECHNOLOGY",
        ),
        (
            "The company has background.》 The company obtained regulatory approval.",
            "REGULATORY",
        ),
    ],
)
def test_hkex_fresh_parser_unicode_closer_keeps_entity_boundary_and_recall(
    monkeypatch: pytest.MonkeyPatch,
    excerpt: str,
    expected_kind: str | None,
) -> None:
    import v4.manager_research.event_source as event_source

    monkeypatch.setattr(
        event_source,
        "extract_pdf_pages",
        lambda _body, excerpt=excerpt: [{"page": 3, "text": excerpt}],
    )

    parsed = parse_hkex_event_document(b"%PDF-fixture", title="Announcement")

    assert parsed["body_parsed"] is True
    if expected_kind is None:
        assert parsed["parse_status"] == "BODY_PARSED_SUMMARY_UNCONFIRMED"
        assert parsed["event_relevant"] is False
        assert parsed["event_status"] == "CANNOT_CONFIRM"
        assert parsed["summary_status"] == "UNCONFIRMED"
    else:
        assert parsed["parse_status"] == "BODY_PARSED_EVENT"
        assert parsed["event_relevant"] is True
        assert parsed["event_kind"] == expected_kind
        assert "The company" in parsed["source_excerpt"]


def test_merge_batches_deduplicates_events_and_keeps_source_boundaries() -> None:
    event = {
        "source_url": MEDIA_URL,
        "source_kind": "MEDIA",
        "body_parsed": True,
        "as_of_bucket": "current",
        "market_confirmation_gap": ["ORDER_OR_REVENUE_UNCONFIRMED"],
    }
    batch = {"source_counts": {"source_id": "media"}, "rows": {"HK.01191": {"events": [event], "source_receipts": [], "coverage": {"source": "media"}}}}
    merged = merge_event_batches(
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation()],
        batches=[batch, batch],
        current_event_as_of="2026-09-08T14:00:00+00:00",
    )
    row = merged["rows"]["HK.01191"]
    assert len(row["events"]) == 1
    assert row["coverage"]["current_event_count"] == 1
    assert "ORDER_OR_REVENUE_UNCONFIRMED" in row["market_confirmation_gap"]


def test_merge_batches_preserves_previous_raw_events_before_current_projection() -> None:
    previous_event = {
        "event_id": "event-preserved",
        "source_url": "https://example.test/old.pdf",
        "source_id": "v4.hkex.official_event_directory.v1",
        "source_kind": "OFFICIAL",
        "source_excerpt": "By order of the Board",
        "source_sha256": "a" * 64,
        "publisher_timestamp": "2026-09-07T09:00:00+08:00",
        "first_seen_at": "2026-09-08T10:00:00+08:00",
        "body_parsed": True,
        "event_status": "CANNOT_CONFIRM",
        "semantic_class": "NON_SUBSTANTIVE",
        "event_relevant": False,
        "as_of_bucket": "historical",
    }
    current_projection = {
        **previous_event,
        "source_excerpt": "A changed parser excerpt must not replace the raw source",
        "source_sha256": "b" * 64,
        "event_status": "READY",
        "event_relevant": True,
    }
    new_event = {
        "event_id": "event-new-lb",
        "source_url": "https://example.test/new.pdf",
        "source_id": "v4.hkex.official_event_directory.v1",
        "source_kind": "OFFICIAL",
        "source_excerpt": "New bounded source material",
        "source_sha256": "c" * 64,
        "publisher_timestamp": "2026-09-08T13:00:00+08:00",
        "first_seen_at": "2026-09-08T13:30:00+08:00",
        "body_parsed": False,
        "event_status": "CANNOT_CONFIRM",
        "event_relevant": False,
        "as_of_bucket": "current",
    }
    previous_receipt = {"source_id": "old", "url": previous_event["source_url"]}
    previous_document = {"source_url": "https://example.test/routine.pdf", "title": "Routine"}
    batch = {
        "status": "READY",
        "source_counts": {"source_id": "hkex", "status": "READY"},
        "rows": {
            "HK.01191": {
                "events": [current_projection, new_event],
                "source_receipts": [{"source_id": "current", "url": new_event["source_url"]}],
                "excluded_documents": [],
                "coverage": {"source": "hkex"},
            }
        },
    }
    merged = merge_event_batches(
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation()],
        batches=[batch],
        previous_rows={
            "HK.01191": {
                "events": [previous_event],
                "source_receipts": [previous_receipt],
                "excluded_documents": [previous_document],
            }
        },
        current_event_as_of="2026-09-08T14:00:00+00:00",
    )

    row = merged["rows"]["HK.01191"]
    by_id = {event["event_id"]: event for event in row["events"]}
    assert set(by_id) == {"event-preserved", "event-new-lb"}
    assert by_id["event-preserved"] == previous_event
    assert by_id["event-preserved"]["source_excerpt"] == previous_event["source_excerpt"]
    assert by_id["event-preserved"]["semantic_class"] == "NON_SUBSTANTIVE"
    assert by_id["event-new-lb"] == new_event
    assert row["coverage"]["event_count"] == 2
    assert row["coverage"]["historical_event_count"] == 1
    assert row["coverage"]["current_event_count"] == 1
    assert row["catalyst_advice"]["focus_eligible"] is False
    assert row["coverage"]["focus_event_count"] == 0
    assert {item["url"] for item in row["source_receipts"]} == {
        previous_event["source_url"],
        new_event["source_url"],
    }
    assert row["excluded_documents"] == [previous_document]

    # A later bounded refresh may return only the new LB window.  Re-run the
    # production merge path with that reduced batch and prove the recovered
    # old object is still retained byte-for-byte.
    next_refresh = merge_event_batches(
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation()],
        batches=[
            {
                "status": "READY",
                "source_counts": {"source_id": "hkex", "status": "READY"},
                "rows": {
                    "HK.01191": {
                        "events": [new_event],
                        "source_receipts": [{"source_id": "current", "url": new_event["source_url"]}],
                        "excluded_documents": [],
                        "coverage": {"source": "hkex"},
                    }
                },
            }
        ],
        previous_rows={"HK.01191": row},
        current_event_as_of="2026-09-08T15:00:00+00:00",
    )
    next_row = next_refresh["rows"]["HK.01191"]
    next_by_id = {event["event_id"]: event for event in next_row["events"]}
    assert next_by_id["event-preserved"] == previous_event
    assert next_by_id["event-new-lb"] == new_event
    assert next_row["coverage"]["event_count"] == 2
    assert next_row["catalyst_advice"]["focus_eligible"] is False


def test_merge_batches_aggregates_all_source_failures_as_cannot_confirm() -> None:
    failed_media = {
        "status": "CANNOT_CONFIRM",
        "source_counts": {"source_id": "media", "status": "CANNOT_CONFIRM", "error": "directory down"},
        "coverage": {"status": "CANNOT_CONFIRM", "completeness": "BOUNDED_SOURCE_FAILED"},
        "rows": {
            "HK.01191": {
                "status": "CANNOT_CONFIRM",
                "reason": "MEDIA_DIRECTORY_FAILED",
                "events": [],
                "source_receipts": [],
                "coverage": {"status": "CANNOT_CONFIRM"},
            }
        },
    }
    failed_hkex = {
        "status": "CANNOT_CONFIRM",
        "source_counts": {"source_id": "hkex", "status": "CANNOT_CONFIRM", "error": "directory down"},
        "coverage": {"status": "CANNOT_CONFIRM", "completeness": "BOUNDED_SAME_ISSUER_DIRECTORY_ONLY"},
        "rows": {
            "HK.01191": {
                "status": "CANNOT_CONFIRM",
                "reason": "HKEX_EVENT_DIRECTORY_FAILED",
                "events": [],
                "source_receipts": [],
                "coverage": {"status": "CANNOT_CONFIRM"},
            }
        },
    }
    merged = merge_event_batches(
        target_trade_date="20260908",
        cutoff_at=cutoff_at("20260908"),
        observations=[observation()],
        batches=[failed_media, failed_hkex],
        current_event_as_of="2026-09-08T14:00:00+00:00",
    )
    assert merged["status"] == "CANNOT_CONFIRM"
    assert merged["reason"] == "ALL_EVENT_SOURCES_FAILED"
    assert merged["coverage"]["status"] == "CANNOT_CONFIRM"
    assert merged["coverage"]["all_sources_failed"] is True
    assert merged["coverage"]["event_count"] == 0
    assert merged["rows"]["HK.01191"]["status"] == "CANNOT_CONFIRM"
