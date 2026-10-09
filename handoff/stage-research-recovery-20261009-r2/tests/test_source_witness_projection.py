"""Offline fixtures only: original pure builder -> original witness validator.

No 2026-10-09 production witness was supplied. These rows are explicit test
data, never a replacement hourly source or a proposed producer output.
"""
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json

import pytest

from domains.research import build_research_archive
from infrastructure.research_store import HourlyResearchStore
from stage_center.research_context import (
    ResearchContextError, _bound_source_rows, _payload_base_sha, _stage_extension,
    _verified_hourly_slot,
)


DAY = "20261009"
SLOT = "0900"
CUTOFF = datetime.fromisoformat("2026-10-09T09:35:00+08:00")


def fixture_source():
    identity = {
        "trade_date": DAY, "source_type": "hourly_research", "source_name": "OFFLINE_FIXTURE",
        "source_path": "/offline-fixture/hourly/source.json", "url": "https://example.invalid/fixture",
        "event_time": "2026-10-09T08:59:00+08:00", "display_event_time": "2026-10-09T08:58:00+08:00",
        "source_published_at": "2026-10-09T08:58:00+08:00",
        "first_seen_at": "2026-10-09T08:59:00+08:00", "last_checked_at": "2026-10-09T09:00:00+08:00",
        "is_new_since_last_slot": True, "is_recheck_duplicate": False, "cannot_confirm": [],
    }
    source = {
        "fixture_only": True, "schema_version": "v3_research_lane.v2", "trade_date": DAY, "slot": SLOT,
        "source_manifest": {"hourly_slot": SLOT, "trade_date": DAY,
            "published_at": "2026-10-09T09:00:00+08:00", "generated_at": "2026-10-09T09:00:00+08:00",
            "pit_cutoff": "2026-10-09T09:00:59+08:00",
            "manifest_sha256": sha256(b"OFFLINE_FIXTURE_MANIFEST").hexdigest(),
            "receipt_sha256": sha256(b"OFFLINE_FIXTURE_RECEIPT").hexdigest()},
        "raw_items": [{"raw_id": "fixture-raw-1", "trade_date": DAY, "raw_payload": {
            "quality_score": 72.5, "is_new_since_last_slot": True, "is_recheck_duplicate": False}}],
        "research_items": [{**identity, "stock_code": "000001", "item_id": "fixture-item-1",
            "raw_id": "fixture-raw-1", "title": "Offline fixture report", "item_quality": "OK", "quality_score": 72.5}],
        "stock_research_timeline": [{**identity, "stock_code": "000001", "stock_name": "OFFLINE_FIXTURE_SECURITY",
            "source_title": "Offline fixture report", "evidence_id": "fixture-evidence-1",
            "evidence_level": "L2_MEDIUM", "confidence": "MEDIUM", "theme": "fixture",
            "catalyst": "fixture", "evidence_sentence": "Offline test data only"}],
        "stock_research_daily": [{"stock_code": "000001", "stock_name": "OFFLINE_FIXTURE_SECURITY",
            "research_score": 97, "research_status": "RESEARCH_ONLY", "evidence_count": 1,
            "source_count": 1, "strong_evidence_count": 0, "medium_evidence_count": 1,
            "weak_evidence_count": 0, "source_types": ["hourly_research"], "themes": ["fixture"],
            "top_catalysts": ["fixture"], "first_seen_time": "2026-10-09T08:59:00+08:00",
            "last_seen_time": "2026-10-09T09:00:00+08:00"}],
        "research_pool_bridge": [], "cannot_confirm": [],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    return source


def publish_fixture(root, source=None, mutate_archive=None):
    source = fixture_source() if source is None else source
    original = deepcopy(source)
    raw = (json.dumps(source, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    source_sha = sha256(raw).hexdigest()
    witness = root / "research" / "hourly" / "source" / f"{source_sha}.json"
    witness.parent.mkdir(parents=True)
    witness.write_bytes(raw)
    archive = build_research_archive(source, source_input_sha256=source_sha)
    assert source == original, "the original builder must remain pure"
    if mutate_archive:
        mutate_archive(archive)
    HourlyResearchStore(root).publish(archive, slot=SLOT, mode="LIVE")
    slot, payload, paths = _verified_hourly_slot(root, trade_date=DAY, cutoff=CUTOFF)
    assert slot == SLOT and paths["source_input_sha256"] == source_sha
    return witness, payload, paths


def test_original_builder_archive_and_source_witness_happy_path(tmp_path):
    witness, payload, paths = publish_fixture(tmp_path)
    rows, evidence = _bound_source_rows(tmp_path, payload=payload, paths=paths,
        trade_date=DAY, slot=SLOT, cutoff=CUTOFF)
    assert rows is not None
    items, stock_evidence, gaps = rows
    assert gaps == []
    assert items[0]["stock_code"] == "A.000001"
    assert items[0]["quality_score"] == 72.5
    assert items[0]["is_new_since_last_slot"] is True
    assert stock_evidence[0]["evidence_id"] == "fixture-evidence-1"
    assert f"v4_hourly_source_witness_sha256={sha256(witness.read_bytes()).hexdigest()}" in evidence
    assert "v4_stage_field_projection=SHA_BOUND_ORIGINAL_SOURCE_NOT_SYNTHETIC_STAGE_EXTENSION" in evidence


def test_internally_verified_archive_with_changed_base_is_still_rejected(tmp_path):
    witness, payload, paths = publish_fixture(tmp_path,
        mutate_archive=lambda archive: archive["stock_pool"][0].update(research_score=98.0))
    assert sha256(witness.read_bytes()).hexdigest() == paths["source_input_sha256"]
    with pytest.raises(ResearchContextError, match="RESEARCH_SOURCE_WITNESS_INVALID:SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH"):
        _bound_source_rows(tmp_path, payload=payload, paths=paths, trade_date=DAY, slot=SLOT, cutoff=CUTOFF)


def test_witness_raw_sha_is_checked_before_projection(tmp_path):
    witness, payload, paths = publish_fixture(tmp_path)
    witness.write_bytes(witness.read_bytes() + b" ")
    with pytest.raises(ResearchContextError, match="^RESEARCH_SOURCE_WITNESS_SHA_MISMATCH$"):
        _bound_source_rows(tmp_path, payload=payload, paths=paths, trade_date=DAY, slot=SLOT, cutoff=CUTOFF)


def test_stage_cutoff_rejects_source_time_discarded_by_archive_projection(tmp_path):
    source = fixture_source()
    source["raw_items"][0]["raw_payload"]["crawl_time"] = "2026-10-09T09:35:01+08:00"
    _, payload, paths = publish_fixture(tmp_path, source)
    with pytest.raises(ResearchContextError, match="HOURLY_SOURCE_ROW_PIT_MISMATCH:raw_items.crawl_time"):
        _bound_source_rows(tmp_path, payload=payload, paths=paths, trade_date=DAY, slot=SLOT, cutoff=CUTOFF)


def test_optional_extension_has_its_own_binding_and_cannot_change_base_comparison(tmp_path):
    _, payload, paths = publish_fixture(tmp_path)
    original_base_sha = _payload_base_sha(payload)
    payload["stage_evidence_v1"]["payload_base_sha256"] = "f" * 64
    assert _payload_base_sha(payload) == original_base_sha
    rows, _ = _bound_source_rows(tmp_path, payload=payload, paths=paths, trade_date=DAY, slot=SLOT, cutoff=CUTOFF)
    assert rows is not None
    _, gaps = _stage_extension(payload, trade_date=DAY, slot=SLOT, paths=paths)
    assert "RESEARCH_STAGE_EVIDENCE_PAYLOAD_BASE_SHA_MISMATCH" in gaps
