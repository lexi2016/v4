"""Synthetic exact-date files consumed by the real research-context loader.

The archive intentionally uses the existing missing-source-witness contract;
that gap remains visible. Research scores are observed zero, not a stubbed
loader result, so they cannot change the quote ranking fixture.
"""
from __future__ import annotations

from pathlib import Path

from domains.research import build_research_archive
from infrastructure.data_store import NativeDataStore, _sha256
from infrastructure.research_store import HourlyResearchStore


def publish_research_fixture(root: Path, date: str, codes: tuple[str, ...]):
    dashed = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    generated = f"{dashed}T09:00:00+08:00"
    timeline, daily, items = [], [], []
    for canonical in codes:
        code = canonical.split(".")[-1]
        timeline.append({
            "stock_code": code, "stock_name": "synthetic",
            "event_time": generated, "source_published_at": generated,
            "first_seen_at": generated, "last_checked_at": generated,
            "source_type": "hourly_research", "source_name": "synthetic",
            "source_title": "synthetic quote regression context",
            "source_path": "synthetic/source.json", "url": "https://example.test/research",
            "theme": "synthetic", "catalyst": "synthetic",
            "evidence_sentence": "synthetic offline quote regression only",
            "evidence_level": "L2_MEDIUM", "confidence": "MEDIUM",
            "dedup_key": f"source-{code}", "evidence_id": f"evidence-{code}",
            "is_new_since_last_slot": False, "is_recheck_duplicate": False,
        })
        daily.append({
            "stock_code": code, "stock_name": "synthetic",
            "first_seen_time": generated, "last_seen_time": generated,
            "research_score": 0, "research_status": "REPEATED",
            "evidence_count": 1, "source_count": 1, "strong_evidence_count": 0,
            "medium_evidence_count": 1, "weak_evidence_count": 0,
            "source_types": ["hourly_research"], "themes": ["synthetic"],
            "top_catalysts": ["synthetic"],
        })
        items.append({
            "item_id": f"item-{code}", "raw_id": f"raw-{code}",
            "stock_code": code, "item_quality": "OK", "quality_score": 0,
            "quality_score_raw": "0", "is_new_since_last_slot": False,
            "is_recheck_duplicate": False, "source_path": "synthetic/source.json",
            "source_title": "synthetic", "url": "https://example.test/research",
            "cannot_confirm": [],
        })
    source = {
        "schema_version": "v3_research_lane.v2", "trade_date": date,
        "source_manifest": {
            "generated_at": generated, "hourly_slot": "0900",
            "manifest_sha256": "b" * 64, "receipt_sha256": "c" * 64,
        },
        "stock_research_timeline": timeline, "stock_research_daily": daily,
        "research_items": items, "research_pool_bridge": [], "cannot_confirm": [],
    }
    payload = build_research_archive(source, source_input_sha256="a" * 64)
    HourlyResearchStore(root).publish(payload, slot="0900", mode="LIVE")

    flags = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    morning = {
        "schema_version": "v3_shared_data.morning_news.v1", "trade_date": date,
        "source_role": "JIUYANGONGSHE_MORNING_NEWS",
        "articles": [{"article_id": "synthetic-article", "title": "synthetic"}],
        "article_count": 1,
        "stock_mentions": [{"stock_code": code.split(".")[-1], "news_quality_score": 0,
                            "intersection_summary": "synthetic"} for code in codes],
        "mention_count": len(codes), **flags,
    }
    manifest = {"schema_version": "v3_shared_data.morning_news_manifest.v1", "trade_date": date,
                "payload_sha256": _sha256(morning), **flags}
    receipt = {"schema_version": "v3_shared_data.morning_news_receipt.v1", "trade_date": date,
               "manifest_sha256": _sha256(manifest), **flags}
    store = NativeDataStore(root)
    payload_rel = f"morning_news/{date}.json"
    manifest_rel = f"morning_news/{date}.manifest.json"
    receipt_rel = f"morning_news/{date}.receipt.json"
    store._write(payload_rel, morning)
    store._write(manifest_rel, manifest)
    store._write(receipt_rel, receipt)
    store._write("morning_news/latest.json", {
        "schema_version": "v3_shared_data.morning_news_latest.v1",
        "entries": {date: {"payload_relative": payload_rel, "manifest_relative": manifest_rel,
                           "receipt_relative": receipt_rel, "payload_sha256": _sha256(morning)}},
    })
