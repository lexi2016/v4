"""Read-only machine research card projection and API contract tests."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.research_lane_router import create_research_lane_router
from infrastructure.pdf_research_cards import (
    MAX_CARDS_PER_DATE,
    MAX_PREVIEW_CHARS,
    RESEARCH_ROOT_RELATIVE,
    SCHEMA_VERSION,
    read_machine_cards,
)


def _document_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _research_root(root: Path) -> Path:
    return root / RESEARCH_ROOT_RELATIVE


def _receipt_path(root: Path, document_id: str, batch: str) -> Path:
    return _research_root(root) / "batches" / batch / "documents" / document_id / "receipt.json"


def _write_card(
    root: Path,
    *,
    seed: str,
    status: str = "SUCCEEDED",
    source_date_cn: str = "2026年10月16日",
    batch: str = "batch-001",
    report_text: str = "机器生成的研报正文\n仅供研究，不构成买卖建议。",
    page_input_path: Path | None = None,
    report_path: Path | None = None,
    source_review_status: str | None = "SOURCE_REVIEW_PENDING",
    document_id: str | None = None,
    pdf_filename: str = "示例研报.pdf",
    make_page_input: bool = True,
) -> tuple[str, Path, Path]:
    document_id = document_id or _document_id(seed)
    document_dir = _research_root(root) / "batches" / batch / "documents" / document_id
    document_dir.mkdir(parents=True, exist_ok=True)
    page_input = document_dir / "page-input.json"
    if make_page_input:
        page_input.write_text(
            json.dumps({"source": {"pdf_path": f"/外置/知识星球/{source_date_cn}/{pdf_filename}"}}),
            encoding="utf-8",
        )
    report = document_dir / "report.md"
    report.write_text(report_text, encoding="utf-8")
    receipt = {
        "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
        "document_id": document_id,
        "pdf_sha256": document_id,
        "status": status,
        "page_input": {"path": str(page_input_path or page_input), "bytes": 1, "sha256": "a" * 64},
        "report": {
            "path": str(report_path or report),
            "bytes": len(report_text.encode("utf-8")),
            "sha256": "b" * 64,
        },
        "report_metadata": {
            "origin_status": "MODEL_GENERATED",
            "source_review_status": source_review_status,
            "user_acceptance_status": "NOT_ACCEPTED",
        },
    }
    (document_dir / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return document_id, page_input, report


def _make_client(data_root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_research_lane_router(data_root))
    return TestClient(app)


def test_collects_displayable_cards_for_exact_source_date(tmp_path: Path) -> None:
    first_id, _, _ = _write_card(tmp_path, seed="first", report_text="A" * (MAX_PREVIEW_CHARS + 1000))
    second_id, _, _ = _write_card(
        tmp_path,
        seed="second",
        status="MODEL_GENERATED_SOURCE_COMPLETE",
        batch="batch-002",
        pdf_filename="第二篇.pdf",
        source_review_status="SOURCE_REVIEW_COMPLETE",
    )
    excluded_id, _, _ = _write_card(tmp_path, seed="excluded", status="FAILED_NO_RETRY")
    other_date_id, _, _ = _write_card(tmp_path, seed="other-date", source_date_cn="2026年10月15日")

    result = read_machine_cards(tmp_path, "20261016")

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] == "READY"
    assert result["research_date"] == "20261016"
    assert result["card_count"] == 2
    assert result["matched_count"] == 2
    assert result["truncated"] is False
    assert result["cannot_confirm_count"] == 0
    assert result["cannot_confirm"] == []
    assert result["unresolved_document_ids"] == []
    assert result["source_index_used"] is False
    assert result["research_only"] is True
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False
    assert {card["document_id"] for card in result["items"]} == {first_id, second_id}
    assert excluded_id not in {card["document_id"] for card in result["items"]}
    assert other_date_id not in {card["document_id"] for card in result["items"]}

    by_id = {card["document_id"]: card for card in result["items"]}
    first = by_id[first_id]
    assert first["title"] == "示例研报"
    assert first["title_source"] == "PDF_FILENAME_STEM"
    assert first["status"] == "SUCCEEDED"
    assert first["source"]["original_filename"] == "示例研报.pdf"
    assert first["source"]["source_group_name"] is None
    assert first["source"]["source_group_status"] == "CANNOT_CONFIRM_INGESTION_INDEX_NOT_LINKED"
    assert first["review"]["review_status"] == "NOT_REVIEWED"
    assert first["review"]["human_reviewed"] is False
    assert len(first["report"]["preview"]) == MAX_PREVIEW_CHARS
    assert first["report"]["preview_max_chars"] == MAX_PREVIEW_CHARS
    assert first["machine_generated"] is True
    assert first["read_only"] is True
    assert first["production_allowed"] is False
    assert by_id[second_id]["review"]["review_status"] == "REVIEWED"
    assert by_id[second_id]["review"]["human_reviewed"] is True


def test_deduplicates_document_id_preferring_higher_status(tmp_path: Path) -> None:
    document_id = _document_id("dedupe-status")
    _write_card(
        tmp_path,
        seed="dedupe-high",
        batch="batch-001",
        document_id=document_id,
        status="MODEL_GENERATED_SOURCE_COMPLETE",
        pdf_filename="重复研报.pdf",
    )
    _write_card(
        tmp_path,
        seed="dedupe-low",
        batch="batch-002",
        document_id=document_id,
        status="SUCCEEDED",
        pdf_filename="重复研报.pdf",
    )

    result = read_machine_cards(tmp_path, "20261016")

    assert result["status"] == "READY"
    assert result["card_count"] == 1
    assert result["matched_count"] == 1
    assert result["duplicate_count"] == 1
    assert len(result["items"]) == 1
    card = result["items"][0]
    assert card["document_id"] == document_id
    assert card["status"] == "MODEL_GENERATED_SOURCE_COMPLETE"
    assert card["batch_id"] == "batch-001"
    assert card["superseded_batch_ids"] == ["batch-002"]


def test_deduplicates_equal_status_by_newest_receipt_mtime(tmp_path: Path) -> None:
    document_id = _document_id("dedupe-mtime")
    _write_card(
        tmp_path,
        seed="dedupe-older",
        batch="batch-001",
        document_id=document_id,
        status="SUCCEEDED",
        pdf_filename="同一份.pdf",
    )
    _write_card(
        tmp_path,
        seed="dedupe-newer",
        batch="batch-002",
        document_id=document_id,
        status="SUCCEEDED",
        pdf_filename="同一份.pdf",
    )
    os.utime(
        _receipt_path(tmp_path, document_id, "batch-001"),
        ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000),
    )
    os.utime(
        _receipt_path(tmp_path, document_id, "batch-002"),
        ns=(1_700_000_100_000_000_000, 1_700_000_100_000_000_000),
    )

    result = read_machine_cards(tmp_path, "20261016")

    assert result["status"] == "READY"
    assert result["card_count"] == 1
    assert result["matched_count"] == 1
    assert result["duplicate_count"] == 1
    assert len(result["items"]) == 1
    card = result["items"][0]
    assert card["document_id"] == document_id
    assert card["batch_id"] == "batch-002"
    assert card["superseded_batch_ids"] == ["batch-001"]


def test_path_escapes_and_unresolved_dates_are_counted_not_dropped(tmp_path: Path) -> None:
    outside = tmp_path / "outside-research-root"
    outside.mkdir()
    outside_page_input = outside / "page-input.json"
    outside_page_input.write_text(
        json.dumps({"source": {"pdf_path": "/外置/知识星球/2026年10月16日/越界.pdf"}}),
        encoding="utf-8",
    )
    outside_report = outside / "report.md"
    outside_report.write_text("越界报告", encoding="utf-8")

    good_id, _, _ = _write_card(tmp_path, seed="good")
    escaped_page_id, _, _ = _write_card(
        tmp_path, seed="escaped-page", page_input_path=outside_page_input, pdf_filename="越界.pdf"
    )
    escaped_report_id, _, _ = _write_card(
        tmp_path, seed="escaped-report", report_path=outside_report
    )
    unresolved_id, _, _ = _write_card(
        tmp_path, seed="unresolved", source_date_cn="无日期", pdf_filename="无日期.pdf"
    )

    result = read_machine_cards(tmp_path, "20261016")

    assert result["status"] == "READY"
    assert result["card_count"] == 1
    assert result["items"][0]["document_id"] == good_id
    assert result["cannot_confirm_count"] == 3
    assert "PAGE_INPUT_PATH_REJECTED" in result["cannot_confirm"]
    assert "REPORT_PATH_REJECTED" in result["cannot_confirm"]
    assert "DATE_UNRESOLVED" in result["cannot_confirm"]
    assert unresolved_id in result["unresolved_document_ids"]
    assert escaped_page_id in result["cannot_confirm_document_ids"]
    assert escaped_report_id in result["cannot_confirm_document_ids"]


def test_caps_cards_per_date_and_sets_truncated(tmp_path: Path) -> None:
    for index in range(MAX_CARDS_PER_DATE + 1):
        _write_card(tmp_path, seed=f"card-{index}", pdf_filename=f"研报-{index:03d}.pdf")

    result = read_machine_cards(tmp_path, "20261016")

    assert result["status"] == "READY"
    assert result["card_count"] == MAX_CARDS_PER_DATE
    assert result["matched_count"] == MAX_CARDS_PER_DATE + 1
    assert result["truncated"] is True
    assert len(result["items"]) == MAX_CARDS_PER_DATE


def test_missing_research_root_is_explicitly_not_materialized(tmp_path: Path) -> None:
    result = read_machine_cards(tmp_path, "20261016")

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["items"] == []
    assert result["cannot_confirm"] == ["PDF_RESEARCH_NOT_MATERIALIZED"]
    assert result["production_allowed"] is False


def test_missing_data_root_is_cannot_confirm_without_raising(tmp_path: Path) -> None:
    result = read_machine_cards(tmp_path / "absent", "20261016")

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["cannot_confirm"] == ["DATA_ROOT_INVALID"]


def test_corrupt_receipt_is_counted_without_hiding_valid_cards(tmp_path: Path) -> None:
    _write_card(tmp_path, seed="good")
    broken_dir = (
        _research_root(tmp_path) / "batches" / "batch-broken" / "documents" / _document_id("broken")
    )
    broken_dir.mkdir(parents=True)
    (broken_dir / "receipt.json").write_text("{not-json", encoding="utf-8")

    result = read_machine_cards(tmp_path, "20261016")

    assert result["status"] == "READY"
    assert result["card_count"] == 1
    assert result["cannot_confirm_count"] == 1
    assert "RECEIPT_UNREADABLE" in result["cannot_confirm"]


def test_invalid_date_is_structured_not_raised(tmp_path: Path) -> None:
    result = read_machine_cards(tmp_path, "20261301")

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["research_date"] == "20261301"
    assert result["cannot_confirm"] == ["TRADE_DATE_INVALID"]


def test_machine_cards_endpoint_is_read_only_and_no_store(tmp_path: Path) -> None:
    _write_card(tmp_path, seed="api-card")

    with _make_client(tmp_path) as client:
        response = client.get("/api/v3/research/machine-cards?research_date=20261016")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["status"] == "READY"
    assert body["card_count"] == 1
    assert body["research_only"] is True
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


def test_machine_cards_endpoint_returns_not_materialized_with_200(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        response = client.get("/api/v3/research/machine-cards?research_date=20261016")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == "NOT_MATERIALIZED"


@pytest.mark.parametrize("value", ["2026-10-16", "20261301", "abcd1234", ""])
def test_machine_cards_endpoint_rejects_invalid_dates(tmp_path: Path, value: str) -> None:
    with _make_client(tmp_path) as client:
        response = client.get("/api/v3/research/machine-cards", params={"research_date": value})

    assert response.status_code == 422


def test_machine_cards_endpoint_requires_research_date(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        response = client.get("/api/v3/research/machine-cards")

    assert response.status_code == 422
