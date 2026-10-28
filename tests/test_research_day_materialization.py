from __future__ import annotations

import hashlib
from pathlib import Path

from contracts.research import DEDUPE_KEY_FIELDS, SCHEMA_VERSION
from contracts.research_day_product import EXPECTED_RESEARCH_SLOTS
from infrastructure.research_store import HourlyResearchStore, ResearchArchiveStore
from ops.materialize_research_day import materialize_research_day


DATE = "20260824"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _article(slot: str) -> dict[str, object]:
    identity = f"fixture-{DATE}-{slot}"
    timestamp = f"2026-08-24T{slot[:2]}:{slot[2:]}:00+08:00"
    return {
        "article_id": _sha(f"article-{identity}"),
        "dedupe_key": _sha(f"dedupe-{identity}"),
        "archive_date": DATE,
        "stock_code": "000001",
        "stock_name": "平安银行",
        "source_type": "hourly_research",
        "source_name": "V4 materializer fixture",
        "source_title": "exact-date fixture",
        "source_path_sha256": _sha(f"path-{identity}"),
        "url": f"https://example.test/{identity}",
        "theme": "银行",
        "catalyst": "业绩",
        "evidence_sentence": "一个 exact-date 研究证据。",
        "evidence_level": "L2_MEDIUM",
        "confidence": "MEDIUM",
        "published_at": timestamp,
        "collected_at": f"2026-08-24T{slot[:2]}:{slot[2:]}:30+08:00",
        "first_seen_at": timestamp,
        "duplicate_evidence_count": 1,
        "source_dedup_keys": [_sha(f"source-dedup-{identity}")],
        "recommendation_status": "RESEARCH_ONLY",
    }


def _stock_pool() -> dict[str, object]:
    return {
        "stock_code": "000001",
        "stock_name": "平安银行",
        "archive_date": DATE,
        "research_score": 0,
        "research_status": "OBSERVED",
        "evidence_count": 1,
        "source_count": 1,
        "strong_evidence_count": 0,
        "medium_evidence_count": 1,
        "weak_evidence_count": 0,
        "source_types": ["hourly_research"],
        "themes": ["银行"],
        "top_catalysts": ["业绩"],
        "first_seen_at": "2026-08-24T10:00:00+08:00",
        "collected_at": "2026-08-24T10:00:30+08:00",
        "formal_overlap": False,
        "stage_overlap": False,
        "recommendation_status": "RESEARCH_ONLY",
    }


def _slot_payload(slot: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "archive_date": DATE,
        "status": "READY",
        "timezone": "Asia/Shanghai",
        "source_input_sha256": _sha(f"input-{DATE}-{slot}"),
        "source_schema_version": "v3_research_lane.v2",
        "source_generated_at": f"2026-08-24T{slot[:2]}:{slot[2:]}:00+08:00",
        "dedupe_key_fields": list(DEDUPE_KEY_FIELDS),
        "article_count": 1,
        "stock_pool_count": 1,
        "source_counts": {"fixture": 1},
        "articles": [_article(slot)],
        "stock_pool": [_stock_pool()],
        "cannot_confirm": [],
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _seed(root: Path, *, omit: str | None = None) -> None:
    store = HourlyResearchStore(root)
    for slot in EXPECTED_RESEARCH_SLOTS:
        if slot != omit:
            store.publish(_slot_payload(slot), slot=slot, mode="LIVE")


def test_eight_exact_live_slots_publish_day_namespace(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _seed(root)

    result = materialize_research_day(root, DATE)

    assert result["status"] == "READY_WITH_DECLARED_GAPS"
    assert result["archive_date"] == DATE
    assert result["date_mode"] == "EXACT"
    assert result["coverage"] == {
        "expected_slots": 8,
        "ready_slots": 8,
        "missing_slots": [],
        "complete": True,
        "slot_matrix": result["coverage"]["slot_matrix"],
    }
    assert len(result["lineage"]["source_refs"]) == 8
    assert result["payload_path"] == f"research/day/archives/{DATE}.json"
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False
    assert ResearchArchiveStore(root).read_day_exact(DATE)["archive_date"] == DATE
    assert ResearchArchiveStore(root).read_day_latest()["archive_date"] == DATE
    assert ResearchArchiveStore(root).read_day_current()["archive_date"] == DATE
    assert not (root / "research" / "archives" / f"{DATE}.json").exists()


def test_missing_live_slot_stays_not_materialized_without_day_pointer(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _seed(root, omit="1700")

    result = materialize_research_day(root, DATE)

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["date_mode"] == "EXACT"
    assert result["missing_slots"] == list(EXPECTED_RESEARCH_SLOTS)
    assert result["cannot_confirm"] == ["MISSING_SLOT:1700"]
    archive = ResearchArchiveStore(root)
    assert archive.read_day_exact(DATE) is None
    assert archive.read_day_latest() is None
    assert archive.read_day_current() is None
    assert not (root / "research" / "day" / "archives" / f"{DATE}.json").exists()
    assert not (root / "receipts" / "research" / "day" / "archives" / f"{DATE}.json").exists()
