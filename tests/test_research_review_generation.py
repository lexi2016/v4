from __future__ import annotations

import json
from pathlib import Path

import pytest

from domains.daily_research_review import load_daily_research_review
from domains.research_review_generation import (
    GenerationRefused,
    inspect_generator_source,
    prepare_payload,
    run_generation,
    write_exact_review,
)


def _payload(date: str = "2026-09-11") -> dict:
    return {
        "schema_version": 1,
        "run_type": "daily_review",
        "review_id": f"daily_{date}",
        "target_date": date,
        "trade_date": date,
        "data_as_of": f"{date} 15:05 CST",
        "generated_at": f"{date} 15:06 CST",
        "warnings": [],
        "emotion_metrics": {
            "money_effect": {"available": True, "sample": 2},
            "promotion": {"available": True, "overall": {"rate": 0.5}},
            "ladder_gap": {"available": True, "continuous": True},
        },
        "market_facts": {
            "breadth": {"available": True, "up": 2, "down": 1},
            "feedback_matrix": {"available": True, "details": []},
            "loss_effect": {"available": True, "deep_loss_5_count": 0},
            "theme_tree": {"available": True, "themes": []},
            "event_ledger": {"available": True, "events": []},
        },
        "macro_sector": "",
        "reflection": None,
        "analysts": [],
    }


def test_mock_generation_writes_one_exact_artifact_consumable_by_m3(tmp_path: Path) -> None:
    result = run_generation(
        "20260911",
        review_root=tmp_path / "reviews",
        backend=lambda date: (_payload(date), {"backend": "fixture"}),
    )

    artifact = tmp_path / "reviews" / "2026-09-11.json"
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["latest_pointer_written"] is False
    assert artifact.is_file()
    assert not (tmp_path / "reviews" / "latest.json").exists()
    loaded = load_daily_research_review("20260911", review_root=tmp_path / "reviews")
    assert loaded["status"] == "READY"
    assert loaded["market_breadth"]["up"] == 2
    assert loaded["production_allowed"] is False
    assert loaded["orders_sent"] is False

    saved = json.loads(artifact.read_text(encoding="utf-8"))
    assert saved["v4_generation"]["natural_generation"] == "CANNOT_CONFIRM"
    assert saved["v4_generation"]["mode"] == "mock_or_injected_backend"


def test_prepare_payload_rejects_date_or_section_mismatch() -> None:
    bad_date = _payload()
    bad_date["target_date"] = "2026-09-10"
    with pytest.raises(GenerationRefused, match="does not match"):
        prepare_payload("20260911", bad_date, mode="mock")

    bad_section = _payload()
    del bad_section["market_facts"]["event_ledger"]
    with pytest.raises(GenerationRefused, match="event_ledger"):
        prepare_payload("20260911", bad_section, mode="mock")


def test_exact_artifact_is_not_overwritten_without_explicit_replace(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    write_exact_review(root, "20260911", _payload())
    with pytest.raises(GenerationRefused, match="already exists"):
        write_exact_review(root, "20260911", _payload())
    write_exact_review(root, "20260911", _payload(), replace=True)


def test_generation_rejects_output_root_overlapping_external_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(GenerationRefused, match="separate"):
        run_generation(
            "20260911",
            review_root=source / "reviews",
            source_root=source,
            backend=lambda date: _payload(date),
        )


def test_external_source_audit_is_bounded_and_has_no_forbidden_explicit_imports() -> None:
    audit = inspect_generator_source(Path("/Users/lexi/Desktop/学习/vibe-astock"))
    assert audit["status"] == "REFERENCE_ONLY"
    assert audit["forbidden_imports"] == []
    assert audit["boundary"]["server_import"] is False
    assert audit["boundary"]["account_import"] is False
    assert audit["boundary"]["lifecycle_import"] is False
