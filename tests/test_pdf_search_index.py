"""The existing owner's verified detail omits duplicated file metadata."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from infrastructure import zsxq_pdf_ingestion as owner
from infrastructure import zsxq_pdf_search_index as search
from infrastructure.data_store import NativeDataStore


def fixture(root: Path):
    doc_id = "a" * 64
    day = "20261015"
    pages = [{"page_number": 1, "status": "OCR_OK", "method": "existing", "text": "600025 原有研报"}]
    raw = json.dumps(pages, ensure_ascii=False).encode()
    pages_path = "external_sources/zsxq_hourly/fixture/pages.json"
    store = NativeDataStore(root)
    owner._store_io(store).write_bytes(pages_path, raw)
    artifact = {"status": "READY", "pdf_sha256": "b" * 64, "pdf_size": 1234,
                "pages_path": pages_path, "pages_file_sha256": hashlib.sha256(raw).hexdigest()}
    source = {"trade_date": day, "source_run_id": "fixture_run", "topic_title": "研报", "original_filename": "fixture.pdf"}
    index = {"documents": {doc_id: {"source": source, "engine_runs": {"c" * 64: artifact}}}, "sources": {"fixture_run": {}}}
    detail = {"status": "READY", "document_id": doc_id, "research_date": day,
              "source": source, "pages": pages, "processing": {"page_count": 1, "processed_page_count": 1},
              "receipt": {"path": "fixture/receipt.json", "sha256": "d" * 64,
                          "integrity": "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED"}}
    return store, index, doc_id, day, detail, raw


def test_original_owner_detail_indexes_hash_verified_artifact_metadata(tmp_path):
    store, index, doc_id, day, detail, raw = fixture(tmp_path)
    with patch.object(owner, "_verified_document_detail", return_value=detail) as verify:
        result = search._refresh_locked(store, index, day, [doc_id], max_pdf_bytes=search.MAX_PDF_BYTES)
    verify.assert_called_once_with(store, index, doc_id, verify_pdf=True)
    assert result["status"] == "READY"
    assert result["results"][0]["status"] == "INDEXED"
    body, _ = search._read_day(store, day)
    entry = body["entries"][doc_id]
    assert entry["verified_pdf_sha256"] == "b" * 64
    assert entry["verified_pdf_size"] == 1234
    assert entry["verified_pages_size"] == len(raw)
    assert entry["receipt_sha256"] == detail["receipt"]["sha256"]
    assert entry["bloom"]


def test_original_owner_integrity_failures_remain_cannot_confirm(tmp_path):
    store, index, doc_id, day, _, _ = fixture(tmp_path)
    for reason in ("COMPLETED_PDF_INTEGRITY_MISMATCH", "COMPLETED_PAGES_INTEGRITY_MISMATCH", "SOURCE_INPUT_SHA256_MISMATCH"):
        with patch.object(owner, "_verified_document_detail", side_effect=owner.ZsxqPdfError(reason)) as verify:
            result = search._refresh_locked(store, index, day, [doc_id], max_pdf_bytes=search.MAX_PDF_BYTES, force_verify=True)
        verify.assert_called_once_with(store, index, doc_id, verify_pdf=True)
        assert result["status"] == "PARTIAL"
        assert result["results"] == [{"document_id": doc_id, "status": "CANNOT_CONFIRM", "reason": reason}]
        body, _ = search._read_day(store, day)
        assert not body["entries"][doc_id].get("bloom")


def test_changed_pages_or_unverified_detail_never_publish_bloom(tmp_path):
    store, index, doc_id, day, detail, _ = fixture(tmp_path)
    for case in ("pages_drift", "unverified_detail"):
        response = deepcopy(detail)
        if case == "pages_drift":
            artifact = next(iter(index["documents"][doc_id]["engine_runs"].values()))
            owner._store_io(store).write_bytes(artifact["pages_path"], b"[]")
        else:
            response["receipt"]["integrity"] = "SOURCE_AND_PAGE_HASHES_VERIFIED"
        with patch.object(owner, "_verified_document_detail", return_value=response):
            result = search._refresh_locked(store, index, day, [doc_id], max_pdf_bytes=search.MAX_PDF_BYTES, force_verify=True)
        assert result["status"] == "PARTIAL"
        assert result["results"][0]["status"] == "CANNOT_CONFIRM"
        assert result["results"][0]["reason"] == (
            "SEARCH_OWNER_PAGES_SHA_DRIFT" if case == "pages_drift" else "SEARCH_OWNER_DETAIL_INVALID")
        body, _ = search._read_day(store, day)
        assert not body["entries"][doc_id].get("bloom")
