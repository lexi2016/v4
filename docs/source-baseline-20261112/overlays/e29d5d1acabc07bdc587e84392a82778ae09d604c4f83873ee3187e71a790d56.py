"""Focused R2 regressions for external finance admission and translation."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from infrastructure.data_store import _sha256
from infrastructure.research_peripheral_store import ResearchPeripheralStore
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


def _captured_finance_row(
    row_id: str,
    *,
    title: str = "Valid finance article",
    published_at: str = "2026-09-07T00:00:00Z",
    fetched_at: str = "2026-09-07T01:00:00Z",
    original_url: str = "https://www.reuters.com/world/china/valid-article/",
    original_url_status: str = "VERIFIED_PUBLISHER_URL",
    title_zh: str = "有效财经文章",
    translation_status: str = "READY",
) -> dict[str, object]:
    return {
        "id": row_id,
        "title": title,
        "summary": title,
        "title_zh": title_zh,
        "summary_zh": title_zh,
        "translation_status": translation_status,
        "translation_source": "PUBLIC_MACHINE_TRANSLATION",
        "published_at": published_at,
        "fetched_at": fetched_at,
        "original_url": original_url,
        "original_url_status": original_url_status,
        "url": original_url,
        "source_url": original_url,
        "source_page_url": "https://www.reuters.com",
        "discovery_url": "https://news.google.com/rss/articles/captured",
        "source_name": "Reuters",
        "source": "Reuters",
        "source_tier": "T1: Reuters",
        "subscription_id": "authority_china_hk",
        "theme_bucket": "china_hk_stocks",
        "cannot_confirm": [],
        "recommendation_status": "RESEARCH_ONLY",
        "capture_id": "capture-fixed",
        "capture_origin": "ORIGINAL_TIME_CAPTURE",
        "original_time_capture": True,
        "session_timezone": "America/New_York",
        "run_id": "capture-run",
    }


def _captured_finance_payload() -> dict[str, object]:
    rows = [
        _captured_finance_row("valid-1"),
        _captured_finance_row(
            "stale-money",
            title="Moonshot seeks up to $5 Billion",
            title_zh="月之暗面寻求高达50美元",
            published_at="2026-09-04T00:00:00Z",
        ),
        _captured_finance_row(
            "pending-url",
            original_url="",
            original_url_status="PENDING_RESOLUTION",
            title_zh="",
            translation_status="",
        ),
        _captured_finance_row("duplicate-1"),
        _captured_finance_row(
            "duplicate-1",
            original_url="https://www.reuters.com/",
        ),
    ]
    payload = peripherals._base_payload(
        trade_date="20260907",
        source="external_finance",
        status="READY",
        source_url=peripherals.GOOGLE_NEWS_RSS,
        fetched_at="2026-09-07T13:00:01Z",
        raw_item_count=135,
        item_count=len(rows),
        overview=peripherals.overview_from_details(rows),
        details=rows,
        items=[],
        cannot_confirm=["US_MARKET_CALENDAR_NOT_BOUND"],
        feed_receipts=[
            {
                "feed_id": "captured",
                "url": "https://news.google.com/rss/search?q=captured",
                "elapsed_ms": 1,
                "http_status": 200,
                "error": None,
                "proxy_used": True,
                "fallback_used": False,
            }
        ],
    )
    payload.update(
        {
            "capture_origin": "ORIGINAL_TIME_CAPTURE",
            "original_time_capture": True,
            "us_session_captures": [
                {
                    "us_session_date": "20260907",
                    "capture_phase": "PRE_OPEN",
                    "session_timezone": "America/New_York",
                    "capture_window_start": "2026-09-07T09:00:00-04:00",
                    "capture_window_end": "2026-09-07T09:05:00-04:00",
                    "capture_id": "capture-fixed",
                    "run_id": "capture-run",
                    "capture_origin": "ORIGINAL_TIME_CAPTURE",
                    "original_time_capture": True,
                }
            ],
        }
    )
    return payload


def test_existing_finance_revalidation_uses_row_fetched_at_and_zero_loss() -> None:
    payload = _captured_finance_payload()
    repaired, row_refs, quarantined = peripherals.revalidate_existing_external_finance_payload(
        payload
    )

    assert len(row_refs) == 5
    assert len(quarantined) == 4
    assert repaired["status"] == "CANNOT_CONFIRM"
    assert repaired["item_count"] == 1
    assert repaired["raw_item_count"] == 135
    assert [row["id"] for row in repaired["details"]] == ["valid-1"]
    assert repaired["details"][0]["original_url"].endswith("/")
    assert sum(item["decision"] == "ACCEPTED" for item in row_refs) + len(
        quarantined
    ) == 5
    assert any(
        item["source_row_ref"].endswith("/stale-money")
        and "EXTERNAL_FINANCE_ITEM_STALE" in item["reason_codes"]
        and "ZH_TRANSLATION_AMOUNT_MISMATCH" in item["reason_codes"]
        for item in row_refs
    )
    assert sum(
        "DUPLICATE_SOURCE_KEY_AMBIGUOUS" in item["reason_codes"]
        for item in row_refs
    ) == 2
    assert repaired["capture_origin"] == payload["capture_origin"]
    assert repaired["original_time_capture"] == payload["original_time_capture"]
    assert repaired["us_session_captures"] == payload["us_session_captures"]
    assert repaired["fetched_at"] == payload["fetched_at"]
    assert repaired["feed_receipts"] == payload["feed_receipts"]


def test_existing_finance_revalidation_rejects_row_after_capture_pit() -> None:
    payload = _captured_finance_payload()
    row = copy.deepcopy(payload["details"][0])
    row["fetched_at"] = "2026-09-08T00:00:00Z"
    row["published_at"] = "2026-09-07T23:00:00Z"
    payload["details"] = [row]
    payload["overview"] = peripherals.overview_from_details([row])
    payload["item_count"] = 1

    repaired, row_refs, quarantined = peripherals.revalidate_existing_external_finance_payload(
        payload
    )

    assert len(quarantined) == 1
    assert repaired["status"] == "CANNOT_CONFIRM"
    assert repaired["item_count"] == 0
    assert "PIT_FETCHED_AT_AFTER_CAPTURE" in row_refs[0]["reason_codes"]


def test_existing_finance_revalidation_keeps_fractional_pit_precision() -> None:
    payload = _captured_finance_payload()
    row = copy.deepcopy(payload["details"][0])
    row["fetched_at"] = "2026-09-07T13:00:01.250Z"
    row["published_at"] = "2026-09-07T12:00:00Z"
    payload["details"] = [row]
    payload["overview"] = peripherals.overview_from_details([row])
    payload["item_count"] = 1
    payload["fetched_at"] = "2026-09-07T13:00:01.500Z"

    repaired, row_refs, quarantined = peripherals.revalidate_existing_external_finance_payload(
        payload
    )

    assert quarantined == []
    assert repaired["status"] == "READY"
    assert repaired["item_count"] == 1
    assert row_refs[0]["decision"] == "ACCEPTED"

    row["fetched_at"] = "2026-09-07T13:00:01.750Z"
    payload["details"] = [row]
    payload["overview"] = peripherals.overview_from_details([row])
    repaired, row_refs, quarantined = peripherals.revalidate_existing_external_finance_payload(
        payload
    )
    assert len(quarantined) == 1
    assert repaired["status"] == "CANNOT_CONFIRM"
    assert "PIT_FETCHED_AT_AFTER_CAPTURE" in row_refs[0]["reason_codes"]


def test_existing_finance_revalidation_rejects_missing_amount_summary_translation() -> None:
    payload = _captured_finance_payload()
    row = copy.deepcopy(payload["details"][0])
    row["title"] = "Deal seeks up to $5 Billion"
    row["summary"] = "Deal seeks up to $5 Billion"
    row["title_zh"] = "交易公告"
    row["summary_zh"] = ""
    row["translation_status"] = "READY"
    payload["details"] = [row]
    payload["overview"] = peripherals.overview_from_details([row])
    payload["item_count"] = 1

    repaired, row_refs, quarantined = peripherals.revalidate_existing_external_finance_payload(
        payload
    )

    assert len(quarantined) == 1
    assert repaired["status"] == "CANNOT_CONFIRM"
    assert repaired["item_count"] == 0
    assert "ZH_TRANSLATION_NOT_READY" in row_refs[0]["reason_codes"]


def test_existing_finance_revalidation_rejects_google_news_publisher_redirect() -> None:
    payload = _captured_finance_payload()
    row = copy.deepcopy(payload["details"][0])
    row["original_url"] = "https://news.google.com/rss/articles/abc"
    row["url"] = row["original_url"]
    row["source_url"] = row["original_url"]
    row["original_url_status"] = "VERIFIED_PUBLISHER_URL"
    payload["details"] = [row]
    payload["overview"] = peripherals.overview_from_details([row])
    payload["item_count"] = 1

    repaired, row_refs, quarantined = peripherals.revalidate_existing_external_finance_payload(
        payload
    )

    assert len(quarantined) == 1
    assert repaired["status"] == "CANNOT_CONFIRM"
    assert repaired["item_count"] == 0
    assert "EXTERNAL_FINANCE_ORIGINAL_URL_DISCOVERY_ONLY" in row_refs[0]["reason_codes"]


def test_existing_finance_revalidation_never_calls_translation_or_network() -> None:
    payload = _captured_finance_payload()
    calls: list[str] = []

    def should_not_call(*_args: object, **_kwargs: object) -> str:
        calls.append("called")
        raise AssertionError("existing finance revalidation must not translate")

    repaired = peripherals.translate_existing_payload(
        payload,
        translate_text=should_not_call,
    )

    assert calls == []
    assert repaired["status"] == "CANNOT_CONFIRM"
    assert repaired["item_count"] == 1
    assert repaired["details"][0]["id"] == "valid-1"


def test_existing_finance_repair_writes_sidecar_before_cas_and_preserves_history(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    payload = _captured_finance_payload()
    store = ResearchPeripheralStore(data_root)
    original = store.publish(payload)

    result = peripherals.materialize_existing_translations(
        data_root=data_root,
        trade_date="20260907",
        source="external_finance",
        translate_text=lambda *_args: (_ for _ in ()).throw(
            AssertionError("must not translate existing finance")
        ),
    )
    repaired = result["payload"]
    assert result["repair_receipt_path"]
    receipt = json.loads(
        (data_root / result["repair_receipt_path"]).read_text(encoding="utf-8")
    )
    assert receipt["source_payload_sha256"] == original["payload_sha256"]
    assert receipt["repaired_payload_sha256"] == result["payload_sha256"]
    assert receipt["natural_execution_verified"] is False
    assert receipt["reconciliation"] == {
        "source_detail_row_count": 5,
        "accepted_count": 1,
        "quarantined_count": 4,
        "assigned_count": 5,
        "raw_item_count_preserved": 135,
    }
    assert len(receipt["source_row_refs"]) == 5
    assert repaired["status"] == "CANNOT_CONFIRM"
    assert store.read_exact("20260907", "external_finance")["item_count"] == 1
    history = data_root / result["previous_payload_path"]
    assert history.is_file()
    assert _sha256(json.loads(history.read_text(encoding="utf-8"))) == original[
        "payload_sha256"
    ]

    repeated = peripherals.materialize_existing_translations(
        data_root=data_root,
        trade_date="20260907",
        source="external_finance",
        translate_text=lambda *_args: (_ for _ in ()).throw(
            AssertionError("repeat must not translate existing finance")
        ),
    )
    assert repeated["payload_sha256"] == result["payload_sha256"]
    assert repeated["replaced"] is False
    repeated_receipt = json.loads(
        (data_root / repeated["repair_receipt_path"]).read_text(encoding="utf-8")
    )
    assert repeated_receipt["source_detail_row_count"] == 5
    assert repeated_receipt["reconciliation"]["assigned_count"] == 5


def test_existing_finance_reuse_rejects_valid_alternate_history_payload(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    store = ResearchPeripheralStore(data_root)
    store.publish(_captured_finance_payload())
    first = peripherals.materialize_existing_translations(
        data_root=data_root,
        trade_date="20260907",
        source="external_finance",
    )

    sidecar_path = data_root / first["repair_receipt_path"]
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    original_history_path = data_root / first["previous_payload_path"]
    original_history = json.loads(original_history_path.read_text(encoding="utf-8"))
    alternate_history = copy.deepcopy(original_history)
    alternate_history["details"][0]["id"] = "alternate-valid-history"
    alternate_history["overview"] = peripherals.overview_from_details(
        alternate_history["details"]
    )
    alternate_sha = _sha256(alternate_history)
    alternate_path = original_history_path.with_name(f"{alternate_sha}.json")
    alternate_path.write_text(
        json.dumps(alternate_history, sort_keys=True), encoding="utf-8"
    )
    sidecar["source_payload_sha256"] = alternate_sha
    sidecar_path.write_text(json.dumps(sidecar, sort_keys=True), encoding="utf-8")

    before = _sha256(store.read_exact("20260907", "external_finance"))
    with pytest.raises(ValueError, match="source row binding"):
        peripherals.materialize_existing_translations(
            data_root=data_root,
            trade_date="20260907",
            source="external_finance",
        )
    assert _sha256(store.read_exact("20260907", "external_finance")) == before


def test_existing_finance_repair_rejects_hash_only_target_sidecar_before_cas(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    payload = _captured_finance_payload()
    store = ResearchPeripheralStore(data_root)
    original = store.publish(payload)
    repaired, _source_refs, _quarantined = (
        peripherals.revalidate_existing_external_finance_payload(payload)
    )
    target_sha = _sha256(repaired)
    target_relative = peripherals._revalidation_receipt_relative(
        "20260907", "external_finance", target_sha
    )
    target_path = data_root / target_relative
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps({"repaired_payload_sha256": target_sha}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="receipt"):
        peripherals.materialize_existing_translations(
            data_root=data_root,
            trade_date="20260907",
            source="external_finance",
        )
    assert _sha256(store.read_exact("20260907", "external_finance")) == original[
        "payload_sha256"
    ]
    assert json.loads(target_path.read_text(encoding="utf-8")) == {
        "repaired_payload_sha256": target_sha
    }
    assert not list(
        (data_root / "research/peripherals/history/20260907/external_finance").glob(
            "*.json"
        )
    )


@pytest.mark.parametrize("missing_field", ("captured_at", "natural_execution_verified"))
def test_existing_finance_reuse_rejects_missing_receipt_provenance(
    tmp_path: Path, missing_field: str
) -> None:
    data_root = tmp_path / "data"
    store = ResearchPeripheralStore(data_root)
    store.publish(_captured_finance_payload())
    first = peripherals.materialize_existing_translations(
        data_root=data_root,
        trade_date="20260907",
        source="external_finance",
    )
    sidecar_path = data_root / first["repair_receipt_path"]
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    del sidecar[missing_field]
    sidecar_path.write_text(json.dumps(sidecar, sort_keys=True), encoding="utf-8")

    before = _sha256(store.read_exact("20260907", "external_finance"))
    with pytest.raises(ValueError, match="receipt"):
        peripherals.materialize_existing_translations(
            data_root=data_root,
            trade_date="20260907",
            source="external_finance",
        )
    assert _sha256(store.read_exact("20260907", "external_finance")) == before


def test_reuse_existing_cannot_confirm_finance_revalidates_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    payload = _captured_finance_payload()
    store = ResearchPeripheralStore(data_root)
    first = store.publish(payload)
    repaired = peripherals.materialize_existing_translations(
        data_root=data_root,
        trade_date="20260907",
        source="external_finance",
        translate_text=lambda *_args: (_ for _ in ()).throw(
            AssertionError("existing finance must not translate")
        ),
    )
    assert repaired["payload"]["status"] == "CANNOT_CONFIRM"
    assert repaired["payload"]["item_count"] == 1
    assert first["payload_sha256"] != repaired["payload_sha256"]

    ai_payload = peripherals._base_payload(
        trade_date="20260907",
        source="ai_news",
        status="READY_EMPTY",
        source_url=peripherals.AIHOT_URL,
        fetched_at="2026-09-07T13:00:01Z",
        raw_item_count=0,
        item_count=0,
        overview=[],
        details=[],
        items=[],
        cannot_confirm=["AIHOT_PUBLIC_PAGE_DISCOVERY_ONLY"],
    )
    store.publish(ai_payload)

    def should_not_fetch(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("reused existing finance must not fetch")

    monkeypatch.setattr(peripherals, "materialize_external_finance", should_not_fetch)
    monkeypatch.setattr(peripherals, "materialize_ai_news", should_not_fetch)
    monkeypatch.setattr(peripherals, "fetch_url", should_not_fetch)

    assert peripherals.main(
        [
            "--data-root",
            str(data_root),
            "--trade-date",
            "20260907",
            "--source",
            "external_finance",
            "--reuse-existing",
        ]
    ) == 2
    assert peripherals.main(
        [
            "--data-root",
            str(data_root),
            "--trade-date",
            "20260907",
            "--source",
            "both",
            "--reuse-existing",
        ]
    ) == 2
    current = ResearchPeripheralStore(data_root).read_exact(
        "20260907", "external_finance"
    )
    assert current["status"] == "CANNOT_CONFIRM"
    assert current["item_count"] == 1
    assert current["raw_item_count"] == 135


def test_existing_finance_reuse_rejects_incomplete_receipt_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    store = ResearchPeripheralStore(data_root)
    store.publish(_captured_finance_payload())
    first = peripherals.materialize_existing_translations(
        data_root=data_root,
        trade_date="20260907",
        source="external_finance",
    )
    sidecar = data_root / first["repair_receipt_path"]
    valid = json.loads(sidecar.read_text(encoding="utf-8"))
    sidecar.write_text(
        json.dumps({"repaired_payload_sha256": valid["repaired_payload_sha256"]}),
        encoding="utf-8",
    )
    calls: list[str] = []

    def should_not_fetch(**_kwargs: object) -> object:
        calls.append("fetch")
        raise AssertionError("malformed finance receipt must not refetch")

    monkeypatch.setattr(peripherals, "materialize_external_finance", should_not_fetch)
    monkeypatch.setattr(peripherals, "fetch_url", should_not_fetch)
    before = _sha256(store.read_exact("20260907", "external_finance"))
    with pytest.raises(ValueError, match="receipt"):
        peripherals.main(
            [
                "--data-root",
                str(data_root),
                "--trade-date",
                "20260907",
                "--source",
                "external_finance",
                "--reuse-existing",
            ]
        )
    assert calls == []
    assert _sha256(store.read_exact("20260907", "external_finance")) == before
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {
        "repaired_payload_sha256": valid["repaired_payload_sha256"]
    }
    sidecar.unlink()
    with pytest.raises(ValueError, match="receipt is missing"):
        peripherals.main(
            [
                "--data-root",
                str(data_root),
                "--trade-date",
                "20260907",
                "--source",
                "external_finance",
                "--reuse-existing",
            ]
        )
    assert calls == []
    assert _sha256(store.read_exact("20260907", "external_finance")) == before


def test_existing_finance_stale_cas_does_not_leave_revalidation_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    payload = _captured_finance_payload()
    ResearchPeripheralStore(data_root).publish(payload)

    def stale_cas(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ValueError("research peripheral expected SHA mismatch")

    monkeypatch.setattr(ResearchPeripheralStore, "replace", stale_cas)
    with pytest.raises(ValueError, match="expected SHA mismatch"):
        peripherals.materialize_existing_translations(
            data_root=data_root,
            trade_date="20260907",
            source="external_finance",
            translate_text=lambda *_args: (_ for _ in ()).throw(
                AssertionError("must not translate existing finance")
            ),
        )
    repair_root = data_root / "receipts/research/peripherals/revalidation/20260907/external_finance"
    assert not repair_root.exists()
    assert ResearchPeripheralStore(data_root).read_exact(
        "20260907", "external_finance"
    )["status"] == "READY"


def test_existing_finance_stale_cas_has_no_writes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    payload = _captured_finance_payload()
    store = ResearchPeripheralStore(data_root)
    published = store.publish(payload)
    before = _sha256(store.read_exact("20260907", "external_finance"))

    changed = copy.deepcopy(payload)
    changed["status"] = "CANNOT_CONFIRM"
    with pytest.raises(ValueError, match="expected SHA mismatch"):
        store.replace(
            changed,
            expected_sha256="0" * 64,
            reason="EXISTING_CAPTURE_REVALIDATION",
        )
    assert _sha256(store.read_exact("20260907", "external_finance")) == before
    assert not list(
        (data_root / "research/peripherals/history/20260907/external_finance").glob(
            "*.json"
        )
    )
    assert published["payload_sha256"] == before


def test_reuse_existing_ready_finance_is_revalidated_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path / "data"
    ResearchPeripheralStore(data_root).publish(_captured_finance_payload())

    def should_not_fetch(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("READY existing finance must not use live materialization")

    monkeypatch.setattr(peripherals, "materialize_external_finance", should_not_fetch)
    monkeypatch.setattr(peripherals, "fetch_url", should_not_fetch)

    assert peripherals.main(
        [
            "--data-root",
            str(data_root),
            "--trade-date",
            "20260907",
            "--source",
            "external_finance",
            "--reuse-existing",
        ]
    ) == 2
    repaired = ResearchPeripheralStore(data_root).read_exact(
        "20260907", "external_finance"
    )
    assert repaired["status"] == "CANNOT_CONFIRM"
    assert repaired["item_count"] == 1


def test_ai_existing_list_keeps_bare_publication_time_and_capture_display() -> None:
    payload = peripherals._base_payload(
        trade_date="20260907",
        source="ai_news",
        status="READY",
        source_url=peripherals.AIHOT_URL,
        fetched_at="2026-09-07T01:00:23Z",
        raw_item_count=15,
        item_count=1,
        overview=[],
        details=[],
        items=[
            {
                "id": "ai-captured",
                "title": "AI item",
                "summary": "AI summary",
                "title_zh": "AI条目",
                "summary_zh": "AI摘要",
                "translation_status": "NOT_REQUIRED",
                "published_at": "08:10",
                "fetched_at": "2026-09-07 09:00:23 +08:00",
                "source_url": peripherals.AIHOT_URL,
                "original_url": peripherals.AIHOT_URL,
                "recommendation_status": "RESEARCH_ONLY",
                "cannot_confirm": ["AIHOT_PUBLIC_PAGE_DISCOVERY_ONLY"],
            }
        ],
        cannot_confirm=["AIHOT_PUBLIC_PAGE_DISCOVERY_ONLY"],
    )
    translated = peripherals.translate_existing_payload(
        payload,
        translate_text=lambda *_args: (_ for _ in ()).throw(
            AssertionError("existing AI row already has derived fields")
        ),
    )
    assert translated["item_count"] == 1
    assert translated["items"][0]["published_at"] == "08:10"
    assert translated["items"][0]["fetched_at"] == "2026-09-07 09:00:23 +08:00"
