from __future__ import annotations

import json
import hashlib
from pathlib import Path

from domains.daily_research_review import (
    GENERATOR_GAP,
    V4_GENERATION_DECLARED,
    V4_GENERATION_OWNER,
    V4_GENERATION_READ_ONLY,
    V4_GENERATION_SCHEMA,
    V4_NATURAL_GENERATION_GAP,
    V4_PROVENANCE_GAP,
    V4_SHARED_AUTHORITY_ID,
    load_daily_research_review,
)


def _artifact(target_date: str = "2026-09-11") -> dict:
    return {
        "schema_version": 1,
        "run_type": "daily_review",
        "target_date": target_date,
        "trade_date": target_date,
        "data_as_of": "2026-09-11 17:25 CST",
        "generated_at": "2026-09-11 21:10 CST",
        "focus": {"emotion_phase": "修复", "market_oneliner": "fixture"},
        "emotion_metrics": {
            "money_effect": {"available": True, "avg": 0.57, "median": -1.9},
            "promotion": {"available": True, "overall": {"base": 35, "promoted": 7, "rate": 0.2}},
            "ladder_gap": {"available": True, "highest": 4, "gaps": [], "continuous": True},
        },
        "market_facts": {
            "breadth": {"available": True, "up": 619, "down": 4619, "flat": 46},
            "feedback_matrix": {"available": True, "order": ["A", "B"], "matrix": {"A": {"B": 1}}},
            "loss_effect": {"available": True, "deep_loss_5_count": 8, "deep_loss_5_rate": 0.23},
            "theme_tree": {"available": True, "tag_count": 109, "themes": [{"tag": "算力", "limit_up": 2}]},
            "event_ledger": {"available": True, "count": 1, "events": [{"tag": "算力", "code": "000001"}]},
        },
    }


def _v4_generation_metadata() -> dict:
    authority_sha = "d" * 64
    return {
        "schema_version": V4_GENERATION_SCHEMA,
        "owner": V4_GENERATION_OWNER,
        "mode": "v4_owned_graph_candidate",
        "generated_at_utc": "2026-09-13T18:07:49Z",
        "write_policy": "exact_date_only_no_latest_pointer",
        "production_allowed": False,
        "research_only": True,
        "natural_generation": "CANNOT_CONFIRM",
        "source_provenance": {
            "authority_receipt_independently_verified": True,
            "authority_receipt_sha256": authority_sha,
            "natural_generation": "CANNOT_CONFIRM",
            "shared_authority_id": V4_SHARED_AUTHORITY_ID,
            "source_role": "VIBE_DUANXIAN_DAILY_REVIEW",
            "assembly": {
                "schema": "v4.vibe_assembly.v1",
                "configuration_sha256": "a" * 64,
                "profile_sha256": "b" * 64,
                "cache_manifest_sha256": "c" * 64,
                "model_and_data_materialization_under_public_task_lock": True,
            },
            "evidence_validation": {
                "authority_receipt_independently_verified": True,
                "receipt_sha256": authority_sha,
            },
            "input_snapshot": {
                "path": "/v4/state/vibe/inputs/2026-09-11.json",
                "bytes": 128,
                "sha256": "e" * 64,
            },
            "source": {
                "status": "HASH_BOUND",
                "manifest_sha256": "f" * 64,
                "files": {"generation.py": {"bytes": 1, "sha256": "1" * 64}},
            },
            "section_and_function_sources": {
                "market_facts.breadth": {"status": "READY"},
                "get_capital_data": {"status": "CANNOT_CONFIRM"},
            },
        },
    }


def _v4_artifact(target_date: str = "2026-09-11") -> dict:
    payload = _artifact(target_date)
    payload["v4_generation"] = _v4_generation_metadata()
    return payload


def _write(root: Path, payload: dict, name: str = "2026-09-11.json") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_reads_only_the_requested_dated_artifact_and_projects_research_fields(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    path = _write(root, _artifact())
    before = path.read_bytes()

    result = load_daily_research_review("20260911", review_root=root)

    assert result["status"] == "READY"
    assert result["trade_date"] == "20260911"
    assert result["target_date"] == "2026-09-11"
    assert result["market_breadth"]["up"] == 619
    assert result["feedback_matrix"]["matrix"]["A"]["B"] == 1
    assert result["money_effect"]["median"] == -1.9
    assert result["loss_effect"]["deep_loss_5_count"] == 8
    assert result["promotion"]["overall"]["promoted"] == 7
    assert result["ladder_gap"]["highest"] == 4
    assert result["theme_tree"]["themes"][0]["tag"] == "算力"
    assert result["event_ledger"]["count"] == 1
    assert result["source_artifact_sha256"] == result["artifact_sha256"]
    assert result["generation_status"] == "EXTERNAL_SOURCE_READ_ONLY"
    assert result["generation"]["owner"] == "CANNOT_CONFIRM"
    assert result["generation"]["status"] == "REFERENCE_ONLY"
    assert result["generation"]["reference_only_producer"] == "vibe-astock/main.py -> duanxian.review_store.save"
    assert GENERATOR_GAP in result["cannot_confirm"]
    assert result["research_only"] is True
    assert result["production_allowed"] is False
    assert path.read_bytes() == before


def test_v4_generation_projects_declared_provenance_without_verification(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    payload = _v4_artifact()
    path = _write(root, payload)
    before = path.read_bytes()

    result = load_daily_research_review("20260911", review_root=root)

    assert result["status"] == "READY"
    assert result["generation_status"] == V4_GENERATION_DECLARED
    assert result["generation_status"] == V4_GENERATION_READ_ONLY
    assert result["generation"]["status"] == V4_GENERATION_DECLARED
    assert result["generation"]["owner"] == "CANNOT_CONFIRM"
    assert result["generation"]["declared_owner"] == V4_GENERATION_OWNER
    assert result["generation"]["producer_reference"] == V4_GENERATION_OWNER
    assert result["generation"]["provenance_status"] == "DECLARED_ONLY"
    assert result["generation"]["independently_verified"] is False
    assert result["generation"]["source_provenance"]["shared_authority_id"] == V4_SHARED_AUTHORITY_ID
    assert result["source_provenance"]["assembly"]["schema"] == "v4.vibe_assembly.v1"
    assert "llm_clients" not in result["source_provenance"]
    assert result["source_provenance"]["authority_receipt_independently_verified"] is False
    assert result["source_provenance"]["declared_authority_receipt_independently_verified"] is True
    assert result["source_provenance"]["provenance_status"] == "DECLARED_ONLY"
    assert V4_PROVENANCE_GAP in result["cannot_confirm"]
    assert V4_NATURAL_GENERATION_GAP in result["cannot_confirm"]
    assert "V4_SOURCE_CANNOT_CONFIRM:get_capital_data" in result["cannot_confirm"]
    assert GENERATOR_GAP not in result["cannot_confirm"]
    assert result["research_only"] is True
    assert result["production_allowed"] is False
    expected_sections = {
        "market_breadth": payload["market_facts"]["breadth"],
        "feedback_matrix": payload["market_facts"]["feedback_matrix"],
        "loss_effect": payload["market_facts"]["loss_effect"],
        "theme_tree": payload["market_facts"]["theme_tree"],
        "event_ledger": payload["market_facts"]["event_ledger"],
        "money_effect": payload["emotion_metrics"]["money_effect"],
        "promotion": payload["emotion_metrics"]["promotion"],
        "ladder_gap": payload["emotion_metrics"]["ladder_gap"],
    }
    for key, expected in expected_sections.items():
        assert result[key] == expected
    assert path.read_bytes() == before


def test_missing_v4_generation_metadata_remains_reference_only(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    _write(root, _artifact())

    result = load_daily_research_review("20260911", review_root=root)

    assert result["generation"]["status"] == "REFERENCE_ONLY"
    assert result["generation"]["owner"] == "CANNOT_CONFIRM"
    assert "producer_reference" not in result["generation"]
    assert result["generation"]["reference_only_producer"] == "vibe-astock/main.py -> duanxian.review_store.save"


def test_forged_v4_owner_does_not_relabel_external_artifact(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    payload = _v4_artifact()
    payload["v4_generation"]["owner"] = "vibe-astock/main.py"
    _write(root, payload)

    result = load_daily_research_review("20260911", review_root=root)

    assert result["status"] == "READY"
    assert result["generation_status"] == "EXTERNAL_SOURCE_READ_ONLY"
    assert result["generation"]["status"] == "REFERENCE_ONLY"
    assert result["generation"]["owner"] == "CANNOT_CONFIRM"
    assert "producer_reference" not in result["generation"]
    assert V4_PROVENANCE_GAP in result["cannot_confirm"]
    assert "V4_GENERATION_OWNER_MISMATCH" in result["cannot_confirm"]


def test_missing_v4_source_provenance_does_not_relabel_artifact(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    payload = _v4_artifact()
    del payload["v4_generation"]["source_provenance"]
    _write(root, payload)

    result = load_daily_research_review("20260911", review_root=root)

    assert result["generation"]["status"] == "REFERENCE_ONLY"
    assert result["generation"]["owner"] == "CANNOT_CONFIRM"
    assert V4_PROVENANCE_GAP in result["cannot_confirm"]
    assert "V4_GENERATION_SOURCE_PROVENANCE_MISSING" in result["cannot_confirm"]


def test_real_v4_generation_artifact_projects_declared_provenance_without_writing() -> None:
    root = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/vibe/reviews")
    path = root / "2026-09-11.json"
    assert path.is_file(), path
    before = path.read_bytes()
    expected_sha = hashlib.sha256(before).hexdigest()

    result = load_daily_research_review("20260911", review_root=root)

    assert result["status"] == "READY"
    assert result["generation_status"] == V4_GENERATION_DECLARED
    assert result["generation"]["status"] == V4_GENERATION_DECLARED
    assert result["generation"]["owner"] == "CANNOT_CONFIRM"
    assert result["generation"]["declared_owner"] == V4_GENERATION_OWNER
    assert result["generation"]["producer_reference"] == V4_GENERATION_OWNER
    assert result["generation"]["provenance_status"] == "DECLARED_ONLY"
    assert result["generation"]["independently_verified"] is False
    assert result["source_artifact_sha256"] == expected_sha
    assert result["source_provenance"]["authority_receipt_independently_verified"] is False
    assert result["source_provenance"]["declared_authority_receipt_independently_verified"] is True
    assert result["source_provenance"]["shared_authority_id"] == V4_SHARED_AUTHORITY_ID
    assert result["source_provenance"]["provenance_status"] == "DECLARED_ONLY"
    assert V4_PROVENANCE_GAP in result["cannot_confirm"]
    assert V4_NATURAL_GENERATION_GAP in result["cannot_confirm"]
    assert result["research_only"] is True
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False
    assert "vibe-astock/main.py" not in json.dumps(result["generation"], ensure_ascii=False)
    payload = json.loads(before)
    expected_sections = {
        "market_breadth": payload["market_facts"]["breadth"],
        "feedback_matrix": payload["market_facts"]["feedback_matrix"],
        "loss_effect": payload["market_facts"]["loss_effect"],
        "theme_tree": payload["market_facts"]["theme_tree"],
        "event_ledger": payload["market_facts"]["event_ledger"],
        "money_effect": payload["emotion_metrics"]["money_effect"],
        "promotion": payload["emotion_metrics"]["promotion"],
        "ladder_gap": payload["emotion_metrics"]["ladder_gap"],
    }
    for key, expected in expected_sections.items():
        assert result[key] == expected
    assert path.read_bytes() == before


def test_real_v4_provenance_reaches_public_review_envelope() -> None:
    from apps.api.v35_api.review_router import create_review_router

    root = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/vibe/reviews")
    endpoint = next(
        route.endpoint
        for route in create_review_router(root.parent.parent.parent, review_root=root).routes
        if route.path == "/api/v3/review"
    )

    payload = endpoint("20260911")
    review = payload["research_review"]

    assert review["generation_status"] == V4_GENERATION_DECLARED
    assert review["generation"]["status"] == V4_GENERATION_DECLARED
    assert review["generation"]["owner"] == "CANNOT_CONFIRM"
    assert review["generation"]["declared_owner"] == V4_GENERATION_OWNER
    assert review["generation"]["independently_verified"] is False
    assert review["source_provenance"]["shared_authority_id"] == V4_SHARED_AUTHORITY_ID
    assert review["source_provenance"]["authority_receipt_independently_verified"] is False
    assert review["production_allowed"] is False
    assert review["orders_sent"] is False


def test_public_review_envelope_keeps_receiptless_v4_claim_declared_only(tmp_path: Path) -> None:
    from apps.api.v35_api.review_router import create_review_router

    root = tmp_path / "reviews"
    _write(root, _v4_artifact())
    endpoint = next(
        route.endpoint
        for route in create_review_router(tmp_path / "runtime", review_root=root).routes
        if route.path == "/api/v3/review"
    )

    review = endpoint("20260911")["research_review"]

    assert review["status"] == "READY"
    assert review["generation_status"] == V4_GENERATION_DECLARED
    assert review["generation"]["status"] == V4_GENERATION_DECLARED
    assert review["generation"]["owner"] == "CANNOT_CONFIRM"
    assert review["generation"]["declared_owner"] == V4_GENERATION_OWNER
    assert review["generation"]["provenance_status"] == "DECLARED_ONLY"
    assert review["generation"]["independently_verified"] is False
    assert review["source_provenance"]["authority_receipt_independently_verified"] is False
    assert review["source_provenance"]["declared_authority_receipt_independently_verified"] is True
    assert "evidence_validation" not in review["source_provenance"]
    assert V4_PROVENANCE_GAP in review["cannot_confirm"]


def test_environment_root_is_the_live_api_configuration(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    _write(root, _artifact())
    monkeypatch.setenv("V4_DAILY_REVIEW_ROOT", str(root))

    result = load_daily_research_review("20260911")

    assert result["status"] == "READY"
    assert result["source_path"] == str(root / "2026-09-11.json")


def test_missing_configuration_is_cannot_confirm_without_using_latest(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    _write(root, _artifact(), "latest.json")
    monkeypatch.delenv("V4_DAILY_REVIEW_ROOT", raising=False)

    result = load_daily_research_review("20260911")

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["cannot_confirm"] == ["DAILY_RESEARCH_REVIEW_ROOT_NOT_CONFIGURED"]
    assert result["source_artifact_sha256"] == ""


def test_missing_dated_file_does_not_fallback_to_latest(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    _write(root, _artifact(), "latest.json")

    result = load_daily_research_review("20260911", review_root=root)

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["cannot_confirm"] == ["DAILY_RESEARCH_REVIEW_DATE_FILE_MISSING"]


def test_date_mismatch_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    _write(root, _artifact("2026-09-10"))

    result = load_daily_research_review("20260911", review_root=root)

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["cannot_confirm"][0].startswith("DAILY_RESEARCH_REVIEW_TARGET_DATE_MISMATCH:")


def test_symlinked_dated_file_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_artifact()), encoding="utf-8")
    root.mkdir()
    (root / "2026-09-11.json").symlink_to(outside)

    result = load_daily_research_review("20260911", review_root=root)

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["cannot_confirm"] == ["DAILY_RESEARCH_REVIEW_ARTIFACT_SYMLINK_REJECTED"]


def test_review_router_adds_the_optional_exact_date_field(tmp_path: Path) -> None:
    from apps.api.v35_api.review_router import create_review_router

    root = tmp_path / "reviews"
    _write(root, _artifact())
    endpoint = next(
        route.endpoint
        for route in create_review_router(tmp_path / "runtime", review_root=root).routes
        if route.path == "/api/v3/review"
    )

    payload = endpoint("20260911")

    assert payload["trade_date"] == "20260911"
    assert payload["research_review"]["status"] == "READY"
    assert payload["research_review"]["target_date"] == "2026-09-11"
    assert payload["research_review"]["market_breadth"]["down"] == 4619
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
