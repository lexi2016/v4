"""Research decision-desk (v3 research lane) adapter tests."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from apps.api.v35_api.research_lane_router import _lane_response, create_research_lane_router
from apps.api.v35_api.research_router import create_research_router
from apps.api.v35_api.app import create_app
from apps.api.v35_api import research_router as legacy_research_router
from domains.research import build_research_archive
from domains.research_day_product import build_research_day_product
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infrastructure.data_store import _sha256
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from infrastructure.research_store import ResearchArchiveStore
from infrastructure.research_store import HourlyResearchStore


def _write_lane_snapshot(
    root: Path,
    date: str,
    *,
    morning_status: str = "GENERATED_SNAPSHOT",
    hourly: bool = False,
) -> Path:
    # Freeze the old producer-shaped input in the test only, then exercise the
    # same public normalization/publication path used by V3.5.  The router
    # must consume the owned archive, not the removed V3 module-root adapter.
    base_time = f"{date[:4]}-{date[4:6]}-{date[6:]}T08:30:00+08:00"
    timeline = [
        {
            "stock_code": "600970",
            "stock_name": "中材国际",
            "event_time": base_time,
            "source_published_at": base_time,
            "first_seen_at": base_time,
            "last_checked_at": base_time,
            "source_type": "research",
            "source_name": "research_feed",
            "source_title": "中材国际研究更新",
            "source_path": f"research/{date}/e1.json",
            "url": f"https://example.invalid/{date}/e1",
            "theme": "基建",
            "catalyst": "订单",
            "evidence_sentence": "研究证据一",
            "evidence_level": "L2_MEDIUM",
            "confidence": "MEDIUM",
            "dedup_key": f"{date}-e1",
        },
        {
            "stock_code": "600970",
            "stock_name": "中材国际",
            "event_time": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:31:00+08:00",
            "source_published_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:31:00+08:00",
            "first_seen_at": base_time,
            "last_checked_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:31:00+08:00",
            "source_type": "research",
            "source_name": "research_feed",
            "source_title": "中材国际研究更新二",
            "source_path": f"research/{date}/e2.json",
            "url": f"https://example.invalid/{date}/e2",
            "theme": "基建",
            "catalyst": "订单",
            "evidence_sentence": "研究证据二",
            "evidence_level": "L3_STRONG",
            "confidence": "HIGH",
            "dedup_key": f"{date}-e2",
        },
        {
            "stock_code": "000037",
            "stock_name": "深南电A",
            "event_time": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:32:00+08:00",
            "source_published_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:32:00+08:00",
            "first_seen_at": base_time,
            "last_checked_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:32:00+08:00",
            "source_type": "research",
            "source_name": "research_feed",
            "source_title": "深南电A研究更新",
            "source_path": f"research/{date}/e3.json",
            "url": f"https://example.invalid/{date}/e3",
            "theme": "电力",
            "catalyst": "供需",
            "evidence_sentence": "研究证据三",
            "evidence_level": "L2_MEDIUM",
            "confidence": "MEDIUM",
            "dedup_key": f"{date}-e3",
        },
    ]
    legacy = {
        "schema_version": "v3_research_lane.v2",
        "trade_date": date,
        "source_manifest": {"generated_at": base_time},
        "stock_research_daily": [
            {
                "stock_code": "600970",
                "stock_name": "中材国际",
                "first_seen_time": base_time,
                "last_seen_time": base_time,
                "research_score": 100,
                "research_status": "RESEARCH_ONLY",
                "evidence_count": 2,
                "source_count": 1,
                "strong_evidence_count": 1,
                "medium_evidence_count": 1,
                "weak_evidence_count": 0,
                "source_types": ["research"],
                "themes": ["基建"],
                "top_catalysts": ["订单"],
            },
            {
                "stock_code": "000037",
                "stock_name": "深南电A",
                "first_seen_time": base_time,
                "last_seen_time": base_time,
                "research_score": 90,
                "research_status": "RESEARCH_ONLY",
                "evidence_count": 1,
                "source_count": 1,
                "strong_evidence_count": 0,
                "medium_evidence_count": 1,
                "weak_evidence_count": 0,
                "source_types": ["research"],
                "themes": ["电力"],
                "top_catalysts": ["供需"],
            },
        ],
        "stock_research_timeline": timeline,
        "research_pool_bridge": [
            {"stock_code": "600970", "formal_overlap": True, "stage_overlap": True},
            {"stock_code": "000037", "formal_overlap": False, "stage_overlap": True},
        ],
        "cannot_confirm": [],
    }
    # Keep the parameter because callers use it to vary the fixture's producer
    # status; the owned archive deliberately carries only validated fields.
    assert morning_status
    archive = build_research_archive(legacy, source_input_sha256="a" * 64)
    if hourly:
        published = HourlyResearchStore(root).publish(
            archive,
            slot="1700",
            mode="LIVE",
        )
    else:
        published = ResearchArchiveStore(root).publish(archive, mode="LIVE")
    return root / published["payload_path"]


def _write_bound_zsxq_hourly(
    root: Path,
    date: str,
    *,
    slot: str = "1800",
    fetched_at: str | None = None,
    status_overrides: dict[str, object] | None = None,
    include_source_receipt_sha: bool = True,
    source_receipt_sha_override: str | None = None,
) -> Path:
    fetched_at = fetched_at or f"{date[:4]}-{date[4:6]}-{date[6:]}T18:00:00+08:00"
    source_path = (
        f"research_module/runtime_outputs/zsxq_hourly/{date}/{slot}/"
        f"v35_zsxq_hourly_status_{date}_{slot}.json"
    )
    title = "知识星球研究记录"
    url = f"https://wx.zsxq.com/dweb2/index/topic_detail/{date}{slot}"
    source = {
        "schema_version": "v3_research_lane.v2",
        "trade_date": date,
        "slot": slot,
        "source_manifest": {
            "trade_date": date,
            "hourly_slot": slot,
            "generated_at": fetched_at,
            "source_receipts": [source_path],
        },
        "stock_research_daily": [
            {
                "stock_code": "000001",
                "stock_name": "测试股票",
                "first_seen_time": fetched_at,
                "last_seen_time": fetched_at,
                "research_score": 10,
                "research_status": "RESEARCH_ONLY",
                "evidence_count": 1,
                "source_count": 1,
                "source_types": ["zsxq"],
                "themes": [],
                "top_catalysts": [],
            }
        ],
        "stock_research_timeline": [
            {
                "stock_code": "000001",
                "stock_name": "测试股票",
                "event_time": fetched_at,
                "source_published_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T17:50:00+08:00",
                "first_seen_at": fetched_at,
                "last_checked_at": fetched_at,
                "source_type": "zsxq",
                "source_name": "知识星球",
                "source_title": title,
                "source_path": source_path,
                "url": url,
                "evidence_sentence": title,
                "evidence_level": "L2_MEDIUM",
                "confidence": "MEDIUM",
            }
        ],
        "raw_items": [
            {
                "source_type": "zsxq",
                "source_path": source_path,
                "trade_date": date,
                "crawl_time": fetched_at,
                "raw_payload": {
                    "source_type": "zsxq",
                    "source_path": source_path,
                    "trade_date": date,
                    "slot": slot,
                    "crawl_time": fetched_at,
                },
            }
        ],
        "cannot_confirm": [
            {
                "reason": "STOCK_CANDIDATE_ENTITY_NOT_VERIFIED",
                "stock_code": f"{index:06d}",
                "stock_name": f"待核验{index}",
                "item_id": f"gap-{index}",
                "source_path": source_path,
                "url": f"https://wx.zsxq.com/dweb2/index/topic_detail/gap{index}",
            }
            for index in range(1, 8)
        ]
        + [{"module": "research_intelligence", "reason": "RESEARCH_ONLY_NO_BUY_GATE"}],
    }
    run_id = f"{date}_{slot}00_run123"
    run_relative = f"external_sources/zsxq_hourly/{run_id}"
    status = {
        "schema_version": "v3_5.zsxq_hourly_delta.v1",
        "source": "zsxq",
        "trade_date": date,
        "slot": slot,
        "status_path": source_path,
        "status": "READY",
        "fetch_ok": True,
        "fetched_at": fetched_at,
        "source_cutoff": f"{date[:4]}-{date[4:6]}-{date[6:]}T{slot[:2]}:{slot[2:]}:59+08:00",
        "latest_run_id": run_id,
        "paths": {
            "run_dir": run_relative,
            "summary": f"{run_relative}/zsxq_summary.json",
            "fetch_result": f"{run_relative}/zsxq_recent_topics_fetch_result.json",
        },
        "topic_count": 1,
        "effective_topic_count": 1,
        "page_count": 2,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    status.update(status_overrides or {})
    run_dir = root / run_relative
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "zsxq_summary.json").write_text(
        json.dumps({"ok": True, "raw_topic_count": 1, "effective_topic_count": 1}),
        encoding="utf-8",
    )
    (run_dir / "zsxq_recent_topics_fetch_result.json").write_text(
        json.dumps({"ok": True, "success": True, "page_count": 2}),
        encoding="utf-8",
    )
    status_path = root / source_path
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status), encoding="utf-8")
    if include_source_receipt_sha:
        source["source_manifest"]["source_receipt_sha256"] = (
            source_receipt_sha_override
            or hashlib.sha256(status_path.read_bytes()).hexdigest()
        )
    incoming = root / "research" / "incoming" / date / f"{slot}.json"
    incoming.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    incoming.write_bytes(raw)
    archive = build_research_archive(
        source,
        source_input_sha256=hashlib.sha256(raw).hexdigest(),
    )
    published = HourlyResearchStore(root).publish(
        archive,
        slot=slot,
        mode="LIVE",
    )
    return incoming


def _write_authoritative_day(root: Path, date: str) -> Path:
    slots = {
        slot: {
            "evidence_rows": [
                {
                    "url": f"https://example.test/day/{slot}",
                    "stock_code": "00001.HK",
                    "stock_name": "Task Three Holdings",
                    "published_at": (
                        f"{date[:4]}-{date[4:6]}-{date[6:]}"
                        f"T{9 + index:02d}:00:00+08:00"
                    ),
                    "article_id": f"article-{slot}",
                    "evidence_level": "L2",
                    "confidence": "HIGH",
                    "evidence_sentence": f"evidence from slot {slot}",
                }
            ]
        }
        for index, slot in enumerate(
            ("1000", "1100", "1200", "1300", "1400", "1500", "1600", "1700")
        )
    }
    product = build_research_day_product(
        date,
        slots,
        stock_mentions_registry={
            "status": "VALIDATED",
            "rule_id": "research-lane-test",
            "high_priority": [
                {
                    "stock_code": "00001.HK",
                    "rank": 1,
                    "reason": "test evidence",
                    "rule_id": "research-lane-test",
                }
            ],
            "jyg_coverage": {
                "articles": 8,
                "expected_articles": 8,
                "stock_mentions": 8,
            },
        },
    )
    published = ResearchArchiveStore(root).publish_day_product(product)
    return root / published["payload_path"]


def _write_shared_morning_news(root: Path, date: str) -> None:
    run_id = f"{date}-morning-news-fixture"
    relative_root = f"morning_news/runs/{date}/{run_id}"
    payload_relative = f"{relative_root}/payload.json"
    manifest_relative = f"{relative_root}/manifest.json"
    receipt_relative = f"{relative_root}/receipt.json"
    articles = [
        {
            "source": "fixture",
            "title": f"晨间资讯 {index}",
            "published_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:0{index}:00+08:00",
            "url": f"https://example.invalid/{date}/{index}",
        }
        for index in range(1, 4)
    ]
    payload = {
        "schema_version": "v3_shared_data.morning_news.v1",
        "trade_date": date,
        "source_role": "JIUYANGONGSHE_MORNING_NEWS",
        "status": "MORNING_NEWS_READY",
        "articles": articles,
        "article_count": len(articles),
        "stock_mentions": [
            {"stock_code": "600000", "stock_name": "浦发银行"}
        ],
        "mention_count": 1,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    payload_sha256 = _sha256(payload)
    manifest = {
        "schema_version": "v3_shared_data.morning_news.v1",
        "trade_date": date,
        "run_id": run_id,
        "payload_relative": payload_relative,
        "payload_sha256": payload_sha256,
        "article_count": len(articles),
        "mention_count": 1,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    receipt = {
        "schema_version": "v3_shared_data.morning_news.v1",
        "trade_date": date,
        "run_id": run_id,
        "payload_relative": payload_relative,
        "payload_sha256": payload_sha256,
        "manifest_relative": manifest_relative,
        "manifest_sha256": _sha256(manifest),
        "receipt_relative": receipt_relative,
        "status": "MORNING_NEWS_READY",
        "article_count": len(articles),
        "mention_count": 1,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    latest = {
        "schema_version": "v3_shared_data.morning_news_latest.v1",
        "entries": {
            date: {
                "trade_date": date,
                "run_id": run_id,
                "payload_relative": payload_relative,
                "payload_sha256": payload_sha256,
                "manifest_relative": manifest_relative,
                "receipt_relative": receipt_relative,
            }
        },
    }
    for relative, value in (
        (payload_relative, payload),
        (manifest_relative, manifest),
        (receipt_relative, receipt),
        ("morning_news/latest.json", latest),
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _make_client(data_root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_research_lane_router(data_root))
    return TestClient(app)


def _make_day_client(data_root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_research_router(data_root))
    return TestClient(app)


def test_lane_reader_reads_owned_archive(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    source = ResearchLaneSource(data_root=tmp_path)
    payload, hourly_slot, hourly_count = source.read_exact_lane("20260804")
    assert payload is not None
    assert hourly_slot == ""
    assert hourly_count == 0
    assert payload["schema_version"] == "v3_5.research_archive.v1"
    assert payload["write_policy"] == "read_only"
    assert len(payload["stock_pool"]) == 2
    assert payload["article_count"] == 3


def test_lane_reader_rejects_unsafe_snapshot(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    target = tmp_path / "research" / "archives" / "20260804.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["write_policy"] = "read_write"
    target.write_text(json.dumps(payload), encoding="utf-8")
    source = ResearchLaneSource(data_root=tmp_path)
    with pytest.raises(ValueError, match="manifest or receipt mismatch"):
        source.read_exact_archive("20260804")


def test_lane_reader_rejects_traversal(tmp_path: Path) -> None:
    source = ResearchLaneSource(data_root=tmp_path)
    with pytest.raises(ValueError):
        source._resolve("../outside.json")


def test_lane_reader_restores_bound_fetch_time_and_source_gap_traces(tmp_path: Path) -> None:
    _write_bound_zsxq_hourly(tmp_path, "20260805")

    payload, slot, _ = ResearchLaneSource(data_root=tmp_path).read_exact_lane("20260805")

    assert payload is not None
    assert slot == "1800"
    article = payload["articles"][0]
    assert article["fetched_at"] == "2026-08-05T18:00:00+08:00"
    assert article["published_at"] == "2026-08-05T17:50:00+08:00"
    assert article["collected_at"] == "2026-08-05T18:00:00+08:00"
    assert article["first_seen_at"] == "2026-08-05T18:00:00+08:00"
    assert article["capture_time_evidence"]["status"] == "VERIFIED"
    assert article["capture_time_evidence"]["source_receipt_sha_binding"] == "DECLARED_MATCH"
    assert article["capture_time_evidence"]["integrity_status"] == "VERIFIED"
    gaps = [item for item in payload["cannot_confirm"] if item.startswith("STOCK_CANDIDATE_ENTITY_NOT_VERIFIED:")]
    assert len(gaps) == 7
    assert all("item_id=gap-" in item and "source_path=research_module/runtime_outputs/zsxq_hourly/" in item for item in gaps)
    assert all("url=https://wx.zsxq.com/" in item for item in gaps)
    assert "LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:8" not in payload["cannot_confirm"]
    assert "RESEARCH_ONLY_NO_BUY_GATE" not in payload["cannot_confirm"]


def test_lane_reader_restores_bound_time_with_unbound_original_receipt_sha_diagnostic(
    tmp_path: Path,
) -> None:
    _write_bound_zsxq_hourly(
        tmp_path, "20260805", include_source_receipt_sha=False
    )

    payload, _, _ = ResearchLaneSource(data_root=tmp_path).read_exact_lane("20260805")

    assert payload is not None
    article = payload["articles"][0]
    evidence = article["capture_time_evidence"]
    assert article["fetched_at"] == "2026-08-05T18:00:00+08:00"
    assert evidence["status"] == "VERIFIED"
    assert evidence["verification_basis"] == "EXACT_BOUND_INPUT_AND_RUN_RECEIPT"
    assert evidence["measured_status_receipt_sha256"] == hashlib.sha256(
        (tmp_path / "research_module/runtime_outputs/zsxq_hourly/20260805/1800/"
         "v35_zsxq_hourly_status_20260805_1800.json").read_bytes()
    ).hexdigest()
    assert evidence["source_receipt_sha_binding"] == "ORIGINAL_RECEIPT_SHA_NOT_DECLARED"
    assert evidence["integrity_status"] == "CANNOT_CONFIRM"
    assert evidence["cannot_confirm"] == ["ORIGINAL_RECEIPT_SHA_NOT_DECLARED"]
    assert "source_receipt_sha256" not in evidence
    assert "ORIGINAL_RECEIPT_SHA_NOT_DECLARED" in payload["cannot_confirm"]


def test_lane_reader_does_not_restore_fetch_time_from_unbound_input(tmp_path: Path) -> None:
    incoming = _write_bound_zsxq_hourly(tmp_path, "20260805")
    incoming.write_text("{}", encoding="utf-8")

    payload, _, _ = ResearchLaneSource(data_root=tmp_path).read_exact_lane("20260805")

    assert payload is not None
    assert "fetched_at" not in payload["articles"][0]
    assert "collected_at" not in payload["articles"][0]
    assert "first_seen_at" not in payload["articles"][0]
    assert payload["articles"][0]["capture_time_evidence"]["reason"] == "SOURCE_INPUT_NOT_SHA_BOUND"
    assert len([item for item in payload["cannot_confirm"] if item.startswith("STOCK_CANDIDATE_ENTITY_NOT_VERIFIED:")]) == 7


@pytest.mark.parametrize(
    ("tamper", "status_overrides", "expected_reason"),
    [
        ("missing", None, "SOURCE_RECEIPT_MISSING"),
        ("receipt_mismatch", {"slot": "1700"}, "SOURCE_RECEIPT_RUN_EVIDENCE_UNVERIFIED"),
        ("receipt_tampered", {"topic_count": 999}, "SOURCE_RECEIPT_RUN_EVIDENCE_UNVERIFIED"),
    ("receipt_sha_mismatch", None, "SOURCE_RECEIPT_SHA_MISMATCH"),
        ("failed_fetch", {"fetch_ok": False}, "SOURCE_RECEIPT_NOT_READY"),
        ("cross_day", {"trade_date": "20260806"}, "SOURCE_RECEIPT_RUN_EVIDENCE_UNVERIFIED"),
        ("future_auth", {"fetched_at": "2026-08-06T00:30:00+08:00"}, "SOURCE_RECEIPT_FETCHED_AFTER_SLOT"),
    ],
)
def test_lane_response_suppresses_unverified_acquisition_times(
    tmp_path: Path,
    tamper: str,
    status_overrides: dict[str, object] | None,
    expected_reason: str,
) -> None:
    _write_bound_zsxq_hourly(
        tmp_path,
        "20260805",
        fetched_at=(
            "2026-08-06T00:30:00+08:00"
            if tamper == "future_auth"
            else None
        ),
        status_overrides=status_overrides,
        source_receipt_sha_override=(
            "0" * 64 if tamper == "receipt_sha_mismatch" else None
        ),
    )
    receipt = tmp_path / (
        "research_module/runtime_outputs/zsxq_hourly/20260805/1800/"
        "v35_zsxq_hourly_status_20260805_1800.json"
    )
    if tamper == "missing":
        receipt.unlink()

    payload, _, _ = ResearchLaneSource(data_root=tmp_path).read_exact_lane("20260805")

    assert payload is not None
    response = _lane_response(
        payload,
        research_date="20260805",
        endpoint_mode="EXACT",
        hourly_slot="1800",
        hourly_slot_count=1,
        peripherals={},
    )
    article = response["stock_research_timeline"][0]
    assert "fetched_at" not in article
    assert "collected_at" not in article
    assert "first_seen_at" not in article
    assert article["published_at"] == "2026-08-05T17:50:00+08:00"
    assert article["capture_time_evidence"]["status"] == "UNVERIFIED"
    assert article["capture_time_evidence"]["reason"] == expected_reason
    raw_values = article["capture_time_evidence"]["raw_values"]
    assert raw_values["collected_at"] == (
        "2026-08-06T00:30:00+08:00" if tamper == "future_auth" else "2026-08-05T18:00:00+08:00"
    )
    assert raw_values["first_seen_at"] == raw_values["collected_at"]
    assert raw_values["source_capture_times"] == [{
        "crawl_time": "2026-08-06T00:30:00+08:00" if tamper == "future_auth" else "2026-08-05T18:00:00+08:00",
        "nested_crawl_time": "2026-08-06T00:30:00+08:00" if tamper == "future_auth" else "2026-08-05T18:00:00+08:00",
    }]


def test_lane_router_exact_date(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    client = _make_client(tmp_path)
    response = client.get("/api/v3/research/lane?research_date=20260804")
    assert response.status_code == 200
    body = response.json()
    assert body["research_date"] == "20260804"
    assert body["schema_version"] == "v3_5.research_lane.v1"
    assert body["endpoint_mode"] == "EXACT"
    assert len(body["stock_research_daily"]) == 2
    assert body["daily_archive_status"] == "NOT_MATERIALIZED"
    assert "RESEARCH_DAY_PRODUCT_NOT_MATERIALIZED:20260804" in body["cannot_confirm"]
    assert body["production_allowed"] is False
    assert body["external_finance"]["feed_receipts"] == []
    assert body["external_finance"]["us_session_captures"] == []


def test_lane_router_live_hourly_missing_key_messages_is_explicit(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260805", hourly=True)

    body = _make_client(tmp_path).get(
        "/api/v3/research/lane?research_date=20260805"
    ).json()

    assert body["status"] == "LIVE_HOURLY"
    assert "key_investment_messages" not in body
    assert "LANE_PERIPHERAL_NOT_MATERIALIZED:key_investment_messages" in body[
        "cannot_confirm"
    ]
    assert "LANE_PERIPHERAL_NOT_MATERIALIZED:ocr_ingestion" in body["cannot_confirm"]
    assert body["ocr_ingestion"]["status"] == "NOT_ASSESSED"
    assert body["ocr_ingestion"]["items"] == []
    assert "PDF_SOURCE_ENUMERATION_MISSING" in body["ocr_ingestion"]["cannot_confirm"]
    assert "completed_count" not in body["ocr_ingestion"]
    assert body["write_policy"] == "read_only"
    assert body["production_allowed"] is False


def test_lane_router_marks_authoritative_day_ready(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260805", hourly=True)
    _write_authoritative_day(tmp_path, "20260805")

    body = _make_client(tmp_path).get(
        "/api/v3/research/lane?research_date=20260805"
    ).json()

    assert body["endpoint_mode"] == "EXACT"
    assert body["daily_archive_status"] == "READY"
    assert body["hourly_research"]["daily_archive_status"] == "READY"


def test_lane_router_projects_us_session_capture_provenance(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260820")
    ResearchPeripheralStore(tmp_path).publish(
        {
            "schema_version": "v3_5.research_peripheral.v1",
            "trade_date": "20260820",
            "source": "external_finance",
            "status": "READY_EMPTY",
            "source_url": "https://news.google.com/rss/search",
            "fetched_at": "2026-08-20T12:00:00+00:00",
            "raw_item_count": 0,
            "item_count": 0,
            "overview": [],
            "details": [],
            "items": [],
            "cannot_confirm": [],
            "us_session_captures": [
                {
                    "us_session_date": "20260820",
                    "capture_phase": "PRE_OPEN",
                    "session_timezone": "America/New_York",
                    "capture_window_start": "2026-08-20T09:00:00-04:00",
                    "capture_window_end": "2026-08-20T09:05:00-04:00",
                    "capture_id": "live-20260820-pre-open",
                    "run_id": "live-run-20260820",
                    "capture_origin": "ORIGINAL_TIME_CAPTURE",
                    "original_time_capture": True,
                }
            ],
            "capture_origin": "ORIGINAL_TIME_CAPTURE",
            "original_time_capture": True,
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    )

    body = _make_client(tmp_path).get(
        "/api/v3/research/lane?research_date=20260820"
    ).json()
    finance = body["external_finance"]

    assert finance["capture_origin"] == "ORIGINAL_TIME_CAPTURE"
    assert finance["original_time_capture"] is True
    assert finance["us_session_captures"][0]["capture_phase"] == "PRE_OPEN"
    assert finance["us_session_captures"][0]["capture_id"] == (
        "live-20260820-pre-open"
    )


def test_lane_router_missing_date(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    client = _make_client(tmp_path)
    response = client.get("/api/v3/research/lane?research_date=20260901")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NOT_MATERIALIZED"
    assert body["reason"] == "RESEARCH_LANE_SNAPSHOT_NOT_FOUND"
    assert body["endpoint_mode"] == "EXACT"


def test_lane_router_invalid_date(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    response = client.get("/api/v3/research/lane?research_date=20261399")
    assert response.status_code == 422


def test_lane_router_latest_uses_newest(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260803")
    _write_lane_snapshot(tmp_path, "20260804")
    client = _make_client(tmp_path)
    response = client.get("/api/v3/research/lane")
    assert response.status_code == 200
    assert response.json()["research_date"] == "20260804"
    assert response.json()["endpoint_mode"] == "LATEST"


def test_lane_router_latest_missing_is_typed_latest(tmp_path: Path) -> None:
    body = _make_client(tmp_path).get("/api/v3/research/lane").json()
    assert body["status"] == "NOT_MATERIALIZED"
    assert body["research_date"] == ""
    assert body["endpoint_mode"] == "LATEST"


def test_lane_dates_endpoint(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    client = _make_client(tmp_path)
    response = client.get("/api/v3/research/dates")
    assert response.status_code == 200
    assert response.json()["research_dates"] == ["20260804"]


def test_lane_source_binding_discloses_exact_hourly_artifact(tmp_path: Path) -> None:
    producer_root = tmp_path / "producer"
    _write_lane_snapshot(producer_root, "20260920", hourly=True)
    client = _make_client(producer_root)

    exact = client.get(
        "/api/v3/research/lane?research_date=20260920"
    ).json()
    latest = client.get("/api/v3/research/lane").json()
    dates = client.get("/api/v3/research/dates").json()

    for body in (exact, latest):
        binding = body["source_binding"]
        assert body["research_date"] == "20260920"
        assert binding["source_root"] == str(producer_root)
        assert binding["status"] == "VERIFIED"
        assert binding["source_date"] == "20260920"
        assert binding["slot"] == "1700"
        assert binding["payload_path"] == (
            "research/hourly/live/20260920/1700.json"
        )
        assert len(binding["payload_sha256"]) == 64
        assert len(binding["receipt_sha256"]) == 64
        assert binding["write_policy"] == "read_only"
        assert binding["production_allowed"] is False
    assert dates["research_dates"] == ["20260920"]
    assert dates["research_source"]["source_root"] == str(producer_root)


def test_app_binds_research_lane_to_explicit_producer_root(tmp_path: Path) -> None:
    producer_root = tmp_path / "producer"
    _write_lane_snapshot(producer_root, "20260920", hourly=True)
    client = TestClient(
        create_app(
            data_root=tmp_path / "consumer",
            current_date="20260920",
            stage_center_selection_root=tmp_path / "stage",
            shared_data_root=tmp_path / "shared",
            manager_research_state_root=tmp_path / "manager",
            research_data_root=producer_root,
            research_ledger_root=tmp_path / "research-ledger",
        )
    )

    catalog = client.get("/api/v1/runs/date-list")
    exact = client.get("/api/v3/research/lane?research_date=20260920")

    assert catalog.status_code == 200
    assert "20260920" in catalog.json()["research_dates"]
    assert catalog.json()["research_source"]["source_root"] == str(producer_root)
    assert exact.status_code == 200
    assert exact.json()["research_date"] == "20260920"
    assert exact.json()["source_binding"]["source_root"] == str(producer_root)


def test_lane_morning_news_root_is_exact_and_keeps_the_shared_root_default(
    tmp_path: Path,
) -> None:
    shared_root = tmp_path / "shared-root"
    morning_root = tmp_path / "morning-root"
    research_root = tmp_path / "research"
    _write_shared_morning_news(shared_root, "20260919")
    _write_shared_morning_news(morning_root, "20260920")
    _write_lane_snapshot(research_root, "20260919")
    _write_lane_snapshot(research_root, "20260920")

    explicit_app = FastAPI()
    explicit_app.include_router(
        create_research_lane_router(
            research_root,
            shared_data_root=shared_root,
            morning_news_data_root=morning_root,
        )
    )
    with TestClient(explicit_app) as client:
        exact = client.get("/api/v3/research/lane?research_date=20260920").json()
        old_root_only = client.get(
            "/api/v3/research/lane?research_date=20260919"
        ).json()
        missing = client.get(
            "/api/v3/research/lane?research_date=20260921"
        ).json()

    assert exact["morning_news"]["status"] == "MORNING_NEWS_READY"
    assert exact["morning_news"]["articles_count"] == 3
    assert [item["title"] for item in exact["morning_news"]["articles"]] == [
        "晨间资讯 1",
        "晨间资讯 2",
        "晨间资讯 3",
    ]
    assert old_root_only["morning_news"]["status"] == "NOT_MATERIALIZED"
    assert old_root_only["morning_news"]["articles"] == []
    assert old_root_only["morning_news"]["articles_count"] == 0
    assert missing["status"] == "NOT_MATERIALIZED"
    assert "morning_news" not in missing

    default_app = FastAPI()
    default_app.include_router(
        create_research_lane_router(research_root, shared_data_root=shared_root)
    )
    with TestClient(default_app) as client:
        default = client.get(
            "/api/v3/research/lane?research_date=20260919"
        ).json()
    assert default["morning_news"]["articles_count"] == 3


@pytest.mark.parametrize("binding_mode", ["argument", "environment"])
def test_app_morning_news_root_override_is_independent_of_shared_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_mode: str,
) -> None:
    morning_root = tmp_path / "morning-owner"
    previous_root = tmp_path / "shared-default"
    research_root = tmp_path / "research"
    _write_shared_morning_news(morning_root, "20260920")
    _write_shared_morning_news(previous_root, "20260919")
    _write_lane_snapshot(research_root, "20260919")
    _write_lane_snapshot(research_root, "20260920")
    if binding_mode == "environment":
        monkeypatch.setenv("V35_MORNING_NEWS_DATA_ROOT", str(morning_root))
        morning_news_data_root = None
    else:
        monkeypatch.delenv("V35_MORNING_NEWS_DATA_ROOT", raising=False)
        morning_news_data_root = morning_root

    client = TestClient(
        create_app(
            data_root=tmp_path / "consumer",
            current_date="20260920",
            stage_center_selection_root=tmp_path / "stage",
            shared_data_root=previous_root,
            manager_research_state_root=tmp_path / "manager",
            research_data_root=research_root,
            research_ledger_root=tmp_path / "research-ledger",
            morning_news_data_root=morning_news_data_root,
        )
    )
    exact = client.get("/api/v3/research/lane?research_date=20260920").json()
    previous_only = client.get(
        "/api/v3/research/lane?research_date=20260919"
    ).json()

    assert exact["morning_news"]["articles_count"] == 3
    assert previous_only["morning_news"]["articles"] == []
    assert previous_only["morning_news"]["status"] == "NOT_MATERIALIZED"


def test_app_distinct_research_reads_use_producer_and_keep_selection_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    producer_root = tmp_path / "producer"
    consumer_root = tmp_path / "consumer"
    _write_lane_snapshot(producer_root, "20260920", hourly=True)
    _write_lane_snapshot(producer_root, "20260920")
    _write_authoritative_day(producer_root, "20260920")
    _write_lane_snapshot(consumer_root, "20260919", hourly=True)
    _write_lane_snapshot(consumer_root, "20260919")

    selection_roots: list[Path] = []

    class SelectionStoreSpy:
        def __init__(self, root: Path) -> None:
            selection_roots.append(Path(root))

    monkeypatch.setattr(legacy_research_router, "ResearchSelectionStore", SelectionStoreSpy)
    client = TestClient(
        create_app(
            data_root=consumer_root,
            current_date="20260920",
            stage_center_selection_root=tmp_path / "stage",
            shared_data_root=tmp_path / "shared",
            manager_research_state_root=tmp_path / "manager",
            research_data_root=producer_root,
            research_ledger_root=tmp_path / "research-ledger",
        )
    )

    lane = client.get("/api/v3/research/lane?research_date=20260920")
    dates = client.get("/api/v3/research/dates")
    articles = client.get("/api/v3/research/articles?archive_date=20260920")
    latest_articles = client.get("/api/v3/research/articles/latest")
    day = client.get("/api/v3/research/day?archive_date=20260920")
    hourly = client.get(
        "/api/v3/research/hourly?archive_date=20260920&slot=1700"
    )
    latest_hourly = client.get("/api/v3/research/hourly/latest")

    assert lane.status_code == 200
    assert lane.json()["research_date"] == "20260920"
    assert lane.json()["source_binding"]["source_root"] == str(producer_root)
    assert dates.status_code == 200
    assert "20260920" in dates.json()["research_dates"]
    assert articles.status_code == 200
    assert articles.json()["archive_date"] == "20260920"
    assert latest_articles.status_code == 200
    assert latest_articles.json()["archive_date"] == "20260920"
    assert day.status_code == 200
    assert day.json()["archive_date"] == "20260920"
    assert hourly.status_code == 200
    assert hourly.json()["archive_date"] == "20260920"
    assert latest_hourly.status_code == 200
    assert latest_hourly.json()["archive_date"] == "20260920"
    assert selection_roots == [consumer_root]


def test_day_only_product_stays_out_of_legacy_date_catalog(tmp_path: Path) -> None:
    date = "20260824"
    _write_authoritative_day(tmp_path, date)

    assert ResearchArchiveStore(tmp_path).list_dates() == []
    dates_response = _make_client(tmp_path).get("/api/v3/research/dates")
    assert dates_response.status_code == 200
    assert dates_response.json()["research_dates"] == []

    day_response = _make_day_client(tmp_path).get(
        f"/api/v3/research/day?archive_date={date}"
    )
    assert day_response.status_code == 200
    day_body = day_response.json()
    assert day_body["archive_date"] == date
    assert day_body["schema_version"] == "v3_5.research_day_product.v1"


def _write_latest_event(root: Path) -> Path:
    target = root / "research_module" / "runtime_outputs" / "events"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "latest_research_event.json"
    path.write_text(json.dumps({
        "ok": True,
        "schema_version": "v3_5.research_event.v1",
        "module_id": "research_intelligence",
        "trade_date": "20260804",
        "event_id": "research:20260804:20260804230027-4961953b",
        "front_end_action": "reload_page_once",
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }), encoding="utf-8")
    return path


def test_latest_event_endpoint(tmp_path: Path) -> None:
    _write_latest_event(tmp_path)
    client = _make_client(tmp_path)
    response = client.get("/api/v3/research/latest-event")
    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == "research:20260804:20260804230027-4961953b"
    assert body["trade_date"] == "20260804"
    assert body["write_policy"] == "read_only"
    assert body["production_allowed"] is False


def test_latest_event_missing(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    response = client.get("/api/v3/research/latest-event")
    assert response.status_code == 200
    assert response.json()["status"] == "NO_RESEARCH_EVENT"


def test_events_stream_starts_and_emits_generation_event(tmp_path: Path) -> None:
    _write_latest_event(tmp_path)
    app = FastAPI()
    app.include_router(create_research_lane_router(tmp_path))

    collected = asyncio.run(_collect_sse(app))

    text = collected.decode("utf-8", errors="replace")
    assert ": connected" in text
    assert "id: research:20260804:20260804230027-4961953b" in text
    assert "event: research_generation_completed" in text
    assert '"production_allowed": false' in text or '"production_allowed":false' in text


async def _collect_sse(app: FastAPI) -> bytes:
    """Drive the SSE endpoint directly through ASGI.

    TestClient/httpx transports in current starlette wait for the infinite
    event-stream generator to finish, so they hang on this endpoint. Calling the
    app's ASGI interface directly lets us stop once the first generation event
    is observed.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/api/v3/research/events",
        "query_string": b"since=",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
        "scheme": "http",
    }
    body = bytearray()

    async def receive() -> dict:
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    try:
        await asyncio.wait_for(app(scope, receive, send), timeout=15)
    except asyncio.TimeoutError:
        pass
    return bytes(body)
