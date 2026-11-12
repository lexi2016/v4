from __future__ import annotations

from pathlib import Path

from infrastructure.research_store import HourlyResearchStore, ResearchArchiveStore
from ops.materialize_research_day import materialize_research_day
from test_research_day_product import DATE, FIXTURE_REGISTRY, _fixture_slots


def test_exact_eight_live_slots_materialize_only_after_all_inputs_are_ready(tmp_path: Path) -> None:
    root = tmp_path / "data"
    slots = _fixture_slots()
    hourly = HourlyResearchStore(root)
    for slot, payload in slots.items():
        hourly.publish(payload, slot=slot, mode="LIVE")
    result = materialize_research_day(root, DATE, stock_mentions_registry=FIXTURE_REGISTRY)
    assert result["status"] == "READY_WITH_DECLARED_GAPS"
    assert result["coverage"]["expected_slots"] == 8
    assert result["coverage"]["ready_slots"] == 8
    assert result["payload_path"] == f"research/day/archives/{DATE}.json"
    assert ResearchArchiveStore(root).read_day_exact(DATE)["archive_date"] == DATE


def test_missing_slot_is_typed_and_does_not_advance_day_pointers(tmp_path: Path) -> None:
    root = tmp_path / "data"
    hourly = HourlyResearchStore(root)
    for slot, payload in _fixture_slots().items():
        if slot != "1700":
            hourly.publish(payload, slot=slot, mode="LIVE")
    result = materialize_research_day(root, DATE, stock_mentions_registry=FIXTURE_REGISTRY)
    assert result["status"] == "NOT_MATERIALIZED"
    assert result["missing_slots"] == [
        "1000", "1100", "1200", "1300", "1400", "1500", "1600", "1700"
    ]
    assert result["cannot_confirm"] == ["MISSING_SLOT:1700"]
    assert result["cannot_confirm"] == ["MISSING_SLOT:1700"]
    assert ResearchArchiveStore(root).read_day_exact(DATE) is None
    assert ResearchArchiveStore(root).read_day_latest() is None
    assert ResearchArchiveStore(root).read_day_current() is None
