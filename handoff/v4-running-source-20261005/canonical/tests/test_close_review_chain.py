from __future__ import annotations

import pytest

from domains.close_review_chain import CHAIN_TASKS, build_close_review_chain, validate_close_review_chain


def _source(date: str = "20260731") -> list[dict]:
    return [{"source_id": "selector_ready_panel", "trade_date": date, "raw_sha256": "a" * 64}]


def test_missing_same_day_video_stays_typed_in_legacy_order() -> None:
    chain = build_close_review_chain("20260731", close_source_evidence=_source())

    assert [row["task_id"] for row in chain["nodes"]] == [row[0] for row in CHAIN_TASKS]
    assert [row["status"] for row in chain["nodes"][:3]] == ["READY", "READY", "READY"]
    assert chain["nodes"][3]["reason"] == "SAME_DAY_VIDEO_NOT_LOCKED"
    assert chain["nodes"][4]["status"] == "NOT_MATERIALIZED"
    assert chain["nodes"][8]["status"] == "NOT_MATERIALIZED"
    assert chain["nodes"][8]["reason"] == "DETERMINISTIC_REVIEW_NOT_PUBLISHED_PENDING_DEPENDENCIES"
    assert chain["nodes"][9]["status"] == "NOT_MATERIALIZED"
    assert chain["nodes"][9]["reason"] == "DEPENDENCY_FUPAN_V3_PUBLISH_NOT_READY"
    assert chain["status"] == "PARTIAL_REVIEW"
    assert chain["production_allowed"] is False
    validate_close_review_chain(chain, "20260731")


def test_video_acceptance_cannot_cross_dates() -> None:
    with pytest.raises(ValueError, match="date"):
        build_close_review_chain(
            "20260731",
            close_source_evidence=_source(),
            video_acceptance={"trade_date": "20260730", "checks": {}},
        )


def test_locked_video_with_raw_asr_stays_review_required_until_stockdict() -> None:
    chain = build_close_review_chain(
        "20260731",
        close_source_evidence=_source(),
        video_acceptance={
            "trade_date": "20260731", "status": "VIDEO_METADATA_READY",
            "today_bv_status": "TODAY_BV_LOCKED", "asr_status": "NOT_USED",
            "checks": {"same_day_video_count": 1},
        },
        video_capture={
            "trade_date": "20260731", "status": "ASR_REVIEW_REQUIRED",
            "videos": [{"bv_id": "BV1sameDay"}],
        },
    )

    assert chain["nodes"][3]["status"] == "READY"
    assert chain["nodes"][4]["status"] == "PARTIAL_REVIEW_REQUIRED"
    assert chain["nodes"][5]["status"] == "NOT_MATERIALIZED"


def test_exact_match_stockdict_completes_only_its_own_node() -> None:
    chain = build_close_review_chain(
        "20260731",
        close_source_evidence=_source(),
        video_acceptance={
            "trade_date": "20260731", "status": "VIDEO_METADATA_READY",
            "today_bv_status": "TODAY_BV_LOCKED", "checks": {"same_day_video_count": 1},
        },
        video_capture={"trade_date": "20260731", "status": "ASR_REVIEW_REQUIRED", "videos": [{}]},
        stockdict_pointer={"trade_date": "20260731", "status": "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY"},
    )

    assert chain["nodes"][5]["status"] == "READY_WITH_REVIEW_BOUNDARY"
    assert chain["nodes"][6]["status"] == "NOT_MATERIALIZED"


def test_ocr_alignment_completes_only_its_own_node() -> None:
    chain = build_close_review_chain(
        "20260731",
        close_source_evidence=_source(),
        video_acceptance={
            "trade_date": "20260731", "status": "VIDEO_METADATA_READY",
            "today_bv_status": "TODAY_BV_LOCKED", "checks": {"same_day_video_count": 1},
        },
        video_capture={"trade_date": "20260731", "status": "ASR_REVIEW_REQUIRED", "videos": [{}]},
        stockdict_pointer={"trade_date": "20260731", "status": "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY"},
        ocr_alignment_pointer={
            "trade_date": "20260731",
            "status": "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY",
            "row_count": 1,
        },
    )

    assert chain["nodes"][6]["status"] == "READY_WITH_REVIEW_BOUNDARY"
    assert chain["nodes"][7]["status"] == "NOT_MATERIALIZED"


def test_video_gap_completes_only_its_own_node() -> None:
    chain = build_close_review_chain(
        "20260731",
        close_source_evidence=_source(),
        video_acceptance={
            "trade_date": "20260731", "status": "VIDEO_METADATA_READY",
            "today_bv_status": "TODAY_BV_LOCKED", "checks": {"same_day_video_count": 1},
        },
        video_capture={"trade_date": "20260731", "status": "ASR_REVIEW_REQUIRED", "videos": [{}]},
        stockdict_pointer={"trade_date": "20260731", "status": "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY"},
        ocr_alignment_pointer={
            "trade_date": "20260731", "status": "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY", "row_count": 1,
        },
        video_gap_pointer={
            "trade_date": "20260731", "status": "VIDEO_GAP_AUDIT_READY", "gap_row_count": 8,
        },
    )

    assert chain["nodes"][7]["status"] == "READY_WITH_REVIEW_BOUNDARY"


def test_publish_and_verify_stay_pending_without_ui_acceptance() -> None:
    chain = build_close_review_chain(
        "20260731",
        close_source_evidence=_source(),
        video_acceptance={
            "trade_date": "20260731", "status": "VIDEO_METADATA_READY",
            "today_bv_status": "TODAY_BV_LOCKED", "asr_status": "ASR_READY",
            "checks": {"same_day_video_count": 1},
        },
        video_capture={"trade_date": "20260731", "status": "ASR_READY", "videos": [{}]},
        stockdict_pointer={"trade_date": "20260731", "status": "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY"},
        ocr_alignment_pointer={
            "trade_date": "20260731", "status": "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY", "row_count": 1,
        },
        video_gap_pointer={
            "trade_date": "20260731", "status": "VIDEO_GAP_AUDIT_READY", "gap_row_count": 8,
        },
    )

    assert [row["status"] for row in chain["nodes"][:8]] == [
        "READY", "READY", "READY", "READY", "READY", "READY_WITH_REVIEW_BOUNDARY",
        "READY_WITH_REVIEW_BOUNDARY", "READY_WITH_REVIEW_BOUNDARY",
    ]
    assert chain["nodes"][8]["status"] == "READY"
    assert chain["nodes"][8]["reason"] == "DETERMINISTIC_REVIEW_READY_ALL_DEPENDENCIES_CLOSED"
    assert chain["nodes"][9]["status"] == "NOT_MATERIALIZED"
    assert chain["nodes"][9]["reason"] == "UI_ACCEPTANCE_PENDING"
    assert chain["status"] == "PARTIAL_REVIEW"


def test_verify_is_ready_only_after_ui_acceptance() -> None:
    chain = build_close_review_chain(
        "20260731",
        close_source_evidence=_source(),
        video_acceptance={
            "trade_date": "20260731", "status": "VIDEO_METADATA_READY",
            "today_bv_status": "TODAY_BV_LOCKED", "asr_status": "ASR_READY",
            "checks": {"same_day_video_count": 1},
        },
        video_capture={"trade_date": "20260731", "status": "ASR_READY", "videos": [{}]},
        stockdict_pointer={"trade_date": "20260731", "status": "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY"},
        ocr_alignment_pointer={
            "trade_date": "20260731", "status": "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY", "row_count": 1,
        },
        video_gap_pointer={
            "trade_date": "20260731", "status": "VIDEO_GAP_AUDIT_READY", "gap_row_count": 8,
        },
        ui_acceptance=True,
    )

    assert chain["nodes"][8]["status"] == "READY"
    assert chain["nodes"][9]["status"] == "READY"
    assert chain["nodes"][9]["reason"] == "ARTIFACT_MANIFEST_API_PAGE_ACCEPTED"
    assert chain["status"] == "READY"
