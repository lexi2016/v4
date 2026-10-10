from __future__ import annotations

import hashlib

import pytest

from v4.manager_research.announcement_analysis import _validated_terminal_body_capture
from v4.manager_research.workspace_announcements import _failed_capture_page_counts


def _page(art_code: str, *, page_index: int = 1, page_total: int = 3) -> dict:
    text = "synthetic captured page; remaining pages were not captured"
    raw_sha = hashlib.sha256(b"synthetic provider response").hexdigest()
    blob_sha = hashlib.sha256(b"synthetic stored blob").hexdigest()
    url = ("https://np-cnotice-stock.eastmoney.com/api/content/ann"
           f"?art_code={art_code}&page_index={page_index}")
    return {
        "page_index": page_index,
        "page_total": page_total,
        "notice_date": "2026-10-08 09:00:00",
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "raw_body_sha256": raw_sha,
        "blob_sha256": blob_sha,
        "source_ref": {
            "request": {"url": url},
            "body_sha256": raw_sha,
            "blob_sha256": blob_sha,
        },
    }


def _terminal(art_code: str, receipt_sha: str, *, captured: int = 1,
              total: int = 3) -> dict:
    return {
        "schema_version": "v4.manager_research.announcement_terminal_body_capture.v1",
        "status": "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS",
        "article_count": 1,
        "body_status_counts": {"BODY_CAPTURE_FAILED": 1},
        "input_identity_sha256": "1" * 64,
        "body_corpus_sha256": "2" * 64,
        "body_corpus_manifest_sha256": "3" * 64,
        "body_batch_receipt_sha256": "4" * 64,
        "capture_receipt_sha256": "5" * 64,
        "failed_articles": [{
            "art_code": art_code,
            "error_code": "ProviderError",
            "receipt_sha256": receipt_sha,
            "content_api_pages_captured": captured,
            "content_api_page_total": total,
        }],
    }


def test_partial_failed_body_pages_are_bound_but_never_upgraded_to_complete() -> None:
    code = "AN202610081830200001"
    page = _page(code)
    body = {
        "body_status": "BODY_CAPTURE_FAILED",
        "pages": [page],
        "content_page_count": 3,
        "body_text": None,
        "body_text_sha256": None,
    }
    original = {"content_api_pages": [page]}

    assert _failed_capture_page_counts(
        {"content_api_pages_captured": 1}, body, original, code, "2026-10-08"
    ) == (1, 3)

    receipt = "f" * 64
    terminal = _terminal(code, receipt)
    raw_body = {
        **body,
        "pdf_sha256": None,
        "capture_receipt_sha256": receipt,
    }
    normalized, failures = _validated_terminal_body_capture(
        terminal, {code: raw_body}, {code}
    )
    assert normalized == terminal
    assert failures[code] == {
        "error_code": "ProviderError",
        "receipt_sha256": receipt,
        "content_api_pages_captured": 1,
        "content_api_page_total": 3,
    }
    assert raw_body["body_status"] == "BODY_CAPTURE_FAILED"

    # A published analysis projection hides partial page text but binds the
    # captured-page summary to the same terminal receipt.
    projected = {
        "body_status": "BODY_CAPTURE_FAILED",
        "pages": [],
        "content_page_count": None,
        "body_text": None,
        "body_text_sha256": None,
        "pdf_sha256": None,
        "capture_receipt_sha256": receipt,
        "capture_page_summary": {
            "content_api_pages_captured": 1,
            "content_api_page_total": 3,
        },
    }
    assert _validated_terminal_body_capture(
        terminal, {code: projected}, {code}
    )[1] == failures

    projected["capture_page_summary"]["content_api_pages_captured"] = 2
    with pytest.raises(ValueError, match="ANNOUNCEMENT_ANALYSIS_BODY_CAPTURE_FAILURE_ROW_INVALID"):
        _validated_terminal_body_capture(terminal, {code: projected}, {code})


def test_partial_capture_count_and_page_total_mismatches_fail_closed() -> None:
    code = "AN202610081830200002"
    page = _page(code)
    body = {"pages": [page], "content_page_count": 3}
    original = {"content_api_pages": [page]}

    with pytest.raises(ValueError, match="ANNOUNCEMENT_BODY_CAPTURE_FAILURE_PAGES_INVALID"):
        _failed_capture_page_counts(
            {"content_api_pages_captured": 2}, body, original, code, "2026-10-08"
        )
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BODY_CAPTURE_FAILURE_PAGE_TOTAL_INVALID"):
        _failed_capture_page_counts(
            {"content_api_pages_captured": 1},
            {**body, "content_page_count": 0}, original, code, "2026-10-08"
        )


def test_legacy_zero_page_failure_contract_remains_valid() -> None:
    code = "AN202610081830200003"
    receipt = "a" * 64
    terminal = _terminal(code, receipt, captured=0, total=0)
    terminal["failed_articles"][0].pop("content_api_pages_captured")
    terminal["failed_articles"][0].pop("content_api_page_total")
    body = {
        "body_status": "BODY_CAPTURE_FAILED",
        "pages": [],
        "content_page_count": None,
        "body_text": None,
        "body_text_sha256": None,
        "pdf_sha256": None,
        "capture_receipt_sha256": receipt,
    }
    assert _validated_terminal_body_capture(terminal, {code: body}, {code})[1] == {
        code: {"error_code": "ProviderError", "receipt_sha256": receipt}
    }
