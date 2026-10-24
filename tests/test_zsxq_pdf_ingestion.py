import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure.data_store import NativeDataStore
from apps.api.v35_api.research_lane_router import create_research_lane_router
from infrastructure.zsxq_pdf_ingestion import (
    LOCK_RELATIVE,
    MAX_PDF_BYTES,
    RECOVERY_AUDIT_RELATIVE,
    STATE_RELATIVE,
    ZsxqPdfError,
    enumerate_pdf_documents,
    process_pdf_batch,
    process_pdf_continuation,
    process_next_pdf_task,
    recover_one_pdf,
    pending_pdf_tasks,
    read_pdf_document_detail,
    read_pdf_ingestion_projection,
    verify_pdf_bytes,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_projection_enumerates_each_bound_source_once_and_detail_revalidates(tmp_path, monkeypatch):
    from infrastructure import zsxq_pdf_ingestion as pdf
    root, files = _fixture(tmp_path)
    _process(root, files)
    original = pdf.enumerate_pdf_documents
    calls = []
    def enumerate_once(*args, **kwargs):
        calls.append(kwargs['source_run_id'])
        return original(*args, **kwargs)
    monkeypatch.setattr(pdf, 'enumerate_pdf_documents', enumerate_once)
    result = pdf.read_pdf_ingestion_projection(root, DATE)
    assert calls == [RUN_ID]
    assert result['completed_count'] == 1 and result['pending_count'] == 2
    ready = next(row for row in result['items'] if row['status'] == 'READY')
    pdf.read_pdf_document_detail(root, ready['document_id'], DATE)
    assert calls == [RUN_ID, RUN_ID, RUN_ID]


def test_projection_cached_enumeration_still_checks_each_document_metadata(tmp_path):
    from infrastructure import zsxq_pdf_ingestion as pdf
    root, files = _fixture(tmp_path)
    _process(root, files)
    store = NativeDataStore(root)
    index = store._read(STATE_RELATIVE)
    second = list(index['documents'])[1]
    index['documents'][second]['source']['original_filename'] = 'forged.pdf'
    store._write(STATE_RELATIVE, index)
    result = pdf.read_pdf_ingestion_projection(root, DATE)
    row = next(x for x in result['items'] if x['document_id'] == second)
    assert row['reason_code'] == 'SOURCE_DOCUMENT_METADATA_MISMATCH'


def test_projection_rehashes_request_local_cache_before_return(tmp_path, monkeypatch):
    from infrastructure import zsxq_pdf_ingestion as pdf
    root, files = _fixture(tmp_path)
    _process(root, files)
    original = pdf._verified_document_detail
    def drift(*args, **kwargs):
        detail = original(*args, **kwargs)
        path = root / f'external_sources/zsxq_hourly/{RUN_ID}/zsxq_recent_topics.json'
        path.write_bytes(path.read_bytes() + b' ')
        return detail
    monkeypatch.setattr(pdf, '_verified_document_detail', drift)
    result = pdf.read_pdf_ingestion_projection(root, DATE)
    assert result['status'] == 'CANNOT_CONFIRM' and result['items'] == []
    assert 'SOURCE_INPUT_SHA256_MISMATCH' in result['cannot_confirm']
DATE = "20261015"
SLOT = "2300"
RUN_ID = "20261015_230000_230000300408"
FILE_ID = "181515482484552"
PDF_BYTES = b"%PDF-1.7\nmock-page-content\n%%EOF\n"
SOURCE_HASH = "opaque-source-hash-without-algorithm"
ENGINE = {
    "engine": "macOS Vision Swift executable; one process per image/slice",
    "vision_source_sha256": "a" * 64,
    "vision_config_sha256": "b" * 64,
}


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, dict]]:
    root = tmp_path / "data"
    root.mkdir(parents=True)
    store = NativeDataStore(root)
    run_dir = f"external_sources/zsxq_hourly/{RUN_ID}"
    files = {
        FILE_ID: {
            "file_id": FILE_ID,
            "name": "AI散热系列（二）原文.pdf",
            "size": len(PDF_BYTES),
            "hash": SOURCE_HASH,
            "create_time": "2026-10-15T22:31:20+08:00",
        },
        "181515482484553": {
            "file_id": "181515482484553",
            "name": "noise topic.pdf",
            "size": len(PDF_BYTES),
            "hash": "opaque-hash-2",
            "create_time": "2026-10-15T21:00:00+08:00",
        },
        "181515482484554": {
            "file_id": "181515482484554",
            "name": "image.pdf",
            "size": len(PDF_BYTES),
            "hash": "opaque-hash-3",
            "create_time": "2026-10-15T20:00:00+08:00",
        },
    }
    topics = [
        {
            "topic_id": "55521554411454554",
            "title": "noise source retained",
            "create_time": "2026-10-15T22:31:00+08:00",
            "group": {"group_id": "15555851111822", "name": "小牛研报纪要"},
            "files": [files[FILE_ID], files["181515482484553"]],
        },
        {
            "topic_id": "55521554411454555",
            "title": "another raw topic",
            "create_time": "2026-10-15T21:00:00+08:00",
            "group": {"group_id": "15555851111822", "name": "小牛研报纪要"},
            "files": [files["181515482484554"]],
        },
    ]
    status = {
        "trade_date": DATE,
        "slot": SLOT,
        "latest_run_id": RUN_ID,
        "fetched_at": "2026-10-15T23:00:00+08:00",
        "status": "READY",
        "fetch_ok": True,
        "paths": {"run_dir": run_dir},
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    store._write(
        f"research_module/runtime_outputs/zsxq_hourly/{DATE}/{SLOT}/v35_zsxq_hourly_status_{DATE}_{SLOT}.json",
        status,
    )
    store._write(
        f"{run_dir}/zsxq_recent_topics_fetch_result.json",
        {
            "success": True,
            "count": len(topics),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )
    store._write(
        f"{run_dir}/zsxq_recent_topics.json",
        {"success": True, "count": len(topics), "topics_brief": topics},
    )
    store._write(
        f"{run_dir}/zsxq_summary.json",
        {
            "ok": True,
            "effective_topics": [{"topic_id": "55521554411454555"}],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )
    return root, files


def _process(
    root: Path,
    files: dict[str, dict],
    *,
    target: str = FILE_ID,
    renderer=None,
    page_count=2,
    ocr=None,
    counters=None,
    max_pages_per_document=2,
    downloader=None,
    now_value=None,
    page_counter=None,
):
    calls = counters if counters is not None else {"metadata": 0, "url": 0, "download": 0, "ocr": 0}

    def metadata(_cli, file_id):
        calls["metadata"] += 1
        return files[file_id]

    def url(_cli, _file_id):
        calls["url"] += 1
        return "https://download.invalid/file?token=DO_NOT_PERSIST"

    def default_download(_url, _size):
        calls["download"] += 1
        return PDF_BYTES

    def render(_pdf, page_number, output_dir):
        if renderer:
            return renderer(page_number, output_dir)
        path = output_dir / f"page-{page_number}.png"
        path.write_bytes(b"fake-png-data")
        return path

    def ocr_page(_image):
        calls["ocr"] += 1
        if ocr:
            return ocr(calls["ocr"])
        text = "VC均热板升级与算力散热。" * 50 if calls["ocr"] == 1 else "末页正文证据。" * 20
        return {"status": "OCR_OK", "method": ENGINE["engine"], "text": text, "width": 2000, "height": 2600}

    now_value = now_value or datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI)
    result = process_pdf_batch(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        file_id=target,
        limit=1,
        metadata_lookup=metadata,
        url_lookup=url,
        downloader=downloader or default_download,
        page_counter=page_counter or (lambda _pdf: page_count),
        page_renderer=render,
        ocr_page=ocr_page,
        engine_info=ENGINE,
        now=lambda: now_value,
        max_pages_per_document=max_pages_per_document,
    )
    return result, calls


def test_enumerates_every_raw_topics_brief_pdf_and_preserves_unknown_hash_algorithm(tmp_path):
    root, _ = _fixture(tmp_path)
    source = NativeDataStore(root)._read(
        f"external_sources/zsxq_hourly/{RUN_ID}/zsxq_recent_topics.json"
    )
    documents = enumerate_pdf_documents(source, trade_date=DATE, source_run_id=RUN_ID)

    assert len(documents) == 3
    assert {row["file_id"] for row in documents} == {FILE_ID, "181515482484553", "181515482484554"}
    target = next(row for row in documents if row["file_id"] == FILE_ID)
    assert target["source_hash_raw"] == SOURCE_HASH
    assert target["source_hash_algorithm"] is None
    assert target["pdf_published_at"] is None
    assert target["data_role"] == "CURRENT_KNOWLEDGE_SUPPLEMENT"
    assert target["late_processing"] is True


@pytest.mark.parametrize(
    ("raw", "expected", "code"),
    [
        (b"not-pdf", 7, "PDF_MAGIC_INVALID"),
        (b"%PDF-1.7", 99, "PDF_SIZE_MISMATCH"),
        (b"%PDF-1.7xx", 10, "PDF_SIZE_LIMIT_EXCEEDED"),
    ],
)
def test_rejects_tampered_invalid_or_oversized_pdf(raw, expected, code):
    with pytest.raises(ZsxqPdfError, match=code):
        verify_pdf_bytes(raw, expected, max_bytes=9)


@pytest.mark.parametrize("page_count", [89, 129])
def test_pdfinfo_page_count_accepts_long_positive_counts(monkeypatch, page_count):
    from types import SimpleNamespace

    from infrastructure import zsxq_pdf_ingestion as pdf_module

    monkeypatch.setattr(
        pdf_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=f"Pages:          {page_count}\n",
        ),
    )

    assert pdf_module._pdfinfo_page_count(Path("owned.pdf")) == page_count


def test_pdfinfo_page_count_rejects_zero(monkeypatch):
    from types import SimpleNamespace

    from infrastructure import zsxq_pdf_ingestion as pdf_module

    monkeypatch.setattr(
        pdf_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="Pages:          0\n"),
    )

    with pytest.raises(ZsxqPdfError, match="PDF_PAGE_COUNT_INVALID"):
        pdf_module._pdfinfo_page_count(Path("owned.pdf"))


def test_single_real_input_binding_writes_full_pages_and_duplicate_reuses_ocr(tmp_path):
    root, files = _fixture(tmp_path)
    first, calls = _process(root, files)
    assert first["status"] == "PARTIAL"
    assert first["pending_total"] == 2
    assert first["processed_this_batch"][0]["full_page_coverage"] is True
    assert calls["ocr"] == 2
    assert calls["download"] == 1

    second, _ = _process(root, files, counters=calls)
    assert second["status"] == "PARTIAL"
    assert second["processed_this_batch"][0]["reused"] is True
    assert calls["ocr"] == 2
    assert calls["download"] == 1

    store = NativeDataStore(root)
    index = store._read(STATE_RELATIVE)
    doc = next(row for row in index["documents"].values() if row["source"]["file_id"] == FILE_ID)
    artifact = doc["engine_runs"][first["engine_identity"]]
    receipt = store._read(artifact["receipt_path"])
    assert receipt["body_length_chars"] > 240
    assert receipt["last_page_excerpt"].startswith("末页正文证据")
    assert receipt["full_page_coverage"] is True
    assert receipt["source_fetched_at"] == "2026-10-15T23:00:00+08:00"
    assert receipt["pdf_published_at"] is None
    assert Path(receipt["real_pdf_path"]).is_file()

    root_bytes = b"".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
    assert b"DO_NOT_PERSIST" not in root_bytes
    assert b"download.invalid" not in root_bytes


def test_rejects_cross_run_status_binding(tmp_path):
    root, _ = _fixture(tmp_path)
    with pytest.raises(ZsxqPdfError, match="SOURCE_STATUS_BINDING_MISMATCH"):
        process_pdf_batch(
            data_root=root,
            trade_date=DATE,
            slot=SLOT,
            source_run_id="20261014_230000_wrong",
            file_id=FILE_ID,
            engine_info=ENGINE,
            page_counter=lambda _pdf: 1,
            page_renderer=lambda _pdf, _page, _out: Path("unused"),
            ocr_page=lambda _image: {},
        )


def test_rejects_path_traversal_run_id_and_out_of_range_batch_limit(tmp_path):
    root, _ = _fixture(tmp_path)
    with pytest.raises(ZsxqPdfError, match="SOURCE_RUN_ID_INVALID"):
        process_pdf_batch(
            data_root=root,
            trade_date=DATE,
            slot=SLOT,
            source_run_id="../outside",
            engine_info=ENGINE,
        )
    for limit in (0, 101):
        with pytest.raises(ZsxqPdfError, match="PDF_BATCH_LIMIT_INVALID"):
            process_pdf_batch(
                data_root=root,
                trade_date=DATE,
                slot=SLOT,
                source_run_id=RUN_ID,
                limit=limit,
                engine_info=ENGINE,
            )


def test_missing_rendered_page_remains_pending_and_never_claims_ready(tmp_path):
    root, files = _fixture(tmp_path)

    def missing_second_page(page_number, output_dir):
        if page_number == 2:
            raise ZsxqPdfError("PDF_PAGE_RENDER_MISSING")
        path = output_dir / "page-1.png"
        path.write_bytes(b"fake-png")
        return path

    result, _ = _process(root, files, renderer=missing_second_page)
    assert result["status"] == "PARTIAL"
    assert result["processed_this_batch"][0]["status"] == "PENDING"
    store = NativeDataStore(root)
    index = store._read(STATE_RELATIVE)
    doc = next(row for row in index["documents"].values() if row["source"]["file_id"] == FILE_ID)
    artifact = doc["engine_runs"][result["engine_identity"]]
    assert artifact["status"] == "PENDING"
    assert artifact["full_page_coverage"] is False
    pages = store._read(artifact["pages_path"])
    assert [row["page_number"] for row in pages] == [1, 2]
    assert pages[1]["status"] == "PDF_PAGE_RENDER_MISSING"
    assert artifact.get("available_at") is None


def test_successful_page_chunk_is_partial_and_reports_real_page_progress(tmp_path):
    root, files = _fixture(tmp_path)
    first, _ = _process(root, files, max_pages_per_document=1)
    assert first["status"] == "PARTIAL"
    assert first["processed_this_batch"][0]["status"] == "PARTIAL"

    store = NativeDataStore(root)
    index = store._read(STATE_RELATIVE)
    document_id, document = next(
        (key, row) for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    artifact = document["engine_runs"][first["engine_identity"]]
    assert artifact["status"] == "PARTIAL"
    assert artifact["processed_page_count"] == 1
    assert artifact["page_count"] == 2
    assert any(task["document_id"] == document_id for task in pending_pdf_tasks(root))

    projection = read_pdf_ingestion_projection(root, DATE)
    item = next(row for row in projection["items"] if row["document_id"] == document_id)
    assert item["status"] == "PARTIAL"
    assert item["processed_page_count"] == 1
    assert item["page_count"] == 2

    resumed, _ = _process(root, files)
    assert resumed["processed_this_batch"][0]["status"] == "READY"
    ready_index = store._read(STATE_RELATIVE)
    ready = ready_index["documents"][document_id]["engine_runs"][first["engine_identity"]]
    assert ready["status"] == "READY"
    assert ready["processed_page_count"] == ready["page_count"] == 2


def test_partial_resume_reuses_verified_pdf_and_preserves_recent_download_time(tmp_path):
    root, files = _fixture(tmp_path)
    calls = {"metadata": 0, "url": 0, "download": 0, "ocr": 0}
    first_time = datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI)
    later_time = datetime(2026, 10, 16, 1, 31, tzinfo=SHANGHAI)

    first, _ = _process(
        root, files, counters=calls, max_pages_per_document=1, now_value=first_time
    )
    first_index = NativeDataStore(root)._read(STATE_RELATIVE)
    document_id, document = next(
        (key, row) for key, row in first_index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    first_artifact = document["engine_runs"][first["engine_identity"]]
    recent_download_time = first_artifact["downloaded_at"]
    assert recent_download_time == first_time.isoformat()
    assert calls["url"] == calls["download"] == 1

    resumed, _ = _process(
        root, files, counters=calls, max_pages_per_document=1, now_value=later_time
    )
    resumed_index = NativeDataStore(root)._read(STATE_RELATIVE)
    artifact = resumed_index["documents"][document_id]["engine_runs"][resumed["engine_identity"]]
    assert resumed["processed_this_batch"][0]["status"] == "READY"
    assert calls["url"] == calls["download"] == 1
    assert artifact["downloaded_at"] == recent_download_time

    detail = read_pdf_document_detail(root, document_id, DATE)
    assert detail["processing"]["downloaded_at"] == recent_download_time
    assert detail["receipt"]["integrity"] == "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED"


def test_page_retry_resumes_covered_pages_and_stops_after_two_attempts(tmp_path):
    root, files = _fixture(tmp_path)
    calls = {"metadata": 0, "url": 0, "download": 0, "ocr": 0}

    def missing_second_page(page_number, output_dir):
        if page_number == 2:
            raise ZsxqPdfError("PDF_PAGE_RENDER_MISSING")
        path = output_dir / "page-1.png"
        path.write_bytes(b"fake-png")
        return path

    first, _ = _process(root, files, renderer=missing_second_page, counters=calls)
    assert first["status"] == "PARTIAL"
    assert calls["ocr"] == 1

    second, _ = _process(root, files, counters=calls)
    assert second["status"] == "PARTIAL"
    assert calls["ocr"] == 2
    assert second["processed_this_batch"][0]["full_page_coverage"] is True

    other_root, other_files = _fixture(tmp_path / "bounded")
    def fail_all_retries(page_number, output_dir):
        if page_number == 2:
            raise ZsxqPdfError("PDF_PAGE_RENDER_MISSING")
        return _write_fake_page(output_dir, page_number)
    first, _ = _process(other_root, other_files, renderer=fail_all_retries)
    assert first["status"] == "PARTIAL"
    second, _ = _process(other_root, other_files, renderer=fail_all_retries)
    assert second["status"] == "PARTIAL"
    calls_before_third = {"metadata": 0, "url": 0, "download": 0, "ocr": 0}
    third, calls_after_third = _process(
        other_root, other_files, renderer=fail_all_retries, counters=calls_before_third
    )
    assert third["processed_this_batch"][0]["status"] == "FAILED"
    assert calls_after_third == {"metadata": 0, "url": 0, "download": 0, "ocr": 0}


def _write_fake_page(output_dir: Path, page_number: int) -> Path:
    path = output_dir / f"page-{page_number}.png"
    path.write_bytes(b"fake-png")
    return path


def test_completed_pdf_tampering_is_detected_before_reuse(tmp_path):
    root, files = _fixture(tmp_path)
    result, _ = _process(root, files)
    store = NativeDataStore(root)
    index = store._read(STATE_RELATIVE)
    doc = next(row for row in index["documents"].values() if row["source"]["file_id"] == FILE_ID)
    artifact = doc["engine_runs"][result["engine_identity"]]
    pdf_path = root / artifact["pdf_path"]
    pdf_path.write_bytes(b"%PDF-tampered")

    with pytest.raises(ZsxqPdfError, match="COMPLETED_PDF_INTEGRITY_MISMATCH"):
        _process(root, files)


def test_ocr_timeout_diagnostic_is_preserved_in_page_and_document_state(tmp_path):
    root, files = _fixture(tmp_path)
    result, _ = _process(root, files, ocr=lambda _attempt: {"status": "OCR_TIMEOUT"})

    assert result["processed_this_batch"][0]["status"] == "PENDING"
    assert result["processed_this_batch"][0]["error_code"] == "OCR_TIMEOUT"
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    document = next(row for row in index["documents"].values() if row["source"]["file_id"] == FILE_ID)
    artifact = document["engine_runs"][result["engine_identity"]]
    pages = NativeDataStore(root)._read(artifact["pages_path"])
    assert pages[0]["status"] == "OCR_TIMEOUT"
    assert artifact["last_error_code"] == "OCR_TIMEOUT"


def test_empty_pdf_inventory_is_ready_empty_not_zero_count_pending(tmp_path):
    root, _files = _fixture(tmp_path)
    store = NativeDataStore(root)
    relative = f"external_sources/zsxq_hourly/{RUN_ID}/zsxq_recent_topics.json"
    source = store._read(relative)
    source["topics_brief"] = []
    store._write(relative, source)

    result = process_pdf_batch(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        engine_info=ENGINE,
        page_counter=lambda _pdf: 1,
        page_renderer=lambda _pdf, _page, _out: Path("unused"),
        ocr_page=lambda _image: {},
    )

    assert result["status"] == "READY_EMPTY"
    assert result["pdf_reference_count"] == 0
    assert result["pending_total"] == 0
    assert result["failed_total"] == 0
    receipt = store._read(result["receipt_path"])
    assert receipt["status"] == "READY_EMPTY"
    index = store._read(STATE_RELATIVE)
    assert index["sources"][RUN_ID]["enumeration_complete"] is True
    projection = read_pdf_ingestion_projection(root, DATE)
    assert projection["status"] == "READY_EMPTY"
    assert projection["completed_count"] == projection["total_count"] == 0
    assert projection["enumeration_source_run_count"] == 1

    index["sources"][RUN_ID]["enumeration_complete"] = False
    store._write(STATE_RELATIVE, index)
    unverified = read_pdf_ingestion_projection(root, DATE)
    assert unverified["status"] == "CANNOT_CONFIRM"
    assert "PDF_SOURCE_ENUMERATION_MISSING" in unverified["cannot_confirm"]
    assert "completed_count" not in unverified


def test_raw_pdf_missing_group_topic_or_file_identity_is_not_counted_as_empty(tmp_path):
    root, _files = _fixture(tmp_path)
    store = NativeDataStore(root)
    relative = f"external_sources/zsxq_hourly/{RUN_ID}/zsxq_recent_topics.json"
    source = store._read(relative)
    source["topics_brief"] = [
        {"title": "unbound PDF", "files": [{"name": "orphan.pdf", "size": len(PDF_BYTES)}]}
    ]
    store._write(relative, source)

    result = process_pdf_batch(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        engine_info=ENGINE,
        page_counter=lambda _pdf: 1,
        page_renderer=lambda _pdf, _page, _out: Path("unused"),
        ocr_page=lambda _image: {},
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["cannot_confirm"] == ["PDF_SOURCE_ENUMERATION_INCOMPLETE"]
    assert "pdf_reference_count" not in result
    source_entry = store._read(STATE_RELATIVE)["sources"][RUN_ID]
    assert source_entry["enumeration_complete"] is False
    assert source_entry["enumeration_error"] == "PDF_SOURCE_ENUMERATION_INCOMPLETE"
    assert "pdf_reference_count" not in source_entry

    projection = read_pdf_ingestion_projection(root, DATE)
    assert projection["status"] == "CANNOT_CONFIRM"
    assert "PDF_SOURCE_ENUMERATION_MISSING" in projection["cannot_confirm"]
    assert "completed_count" not in projection
    assert "total_count" not in projection


def test_missing_exact_date_pdf_enumeration_is_unassessed_without_zero_counts(tmp_path):
    root, files = _fixture(tmp_path)
    _process(root, files)

    missing = read_pdf_ingestion_projection(root, "20261014")
    assert missing["status"] == "NOT_ASSESSED"
    assert "PDF_SOURCE_ENUMERATION_MISSING" in missing["cannot_confirm"]
    assert "completed_count" not in missing
    assert "total_count" not in missing

    empty_index_root = tmp_path / "no-index"
    empty_index_root.mkdir()
    no_index = read_pdf_ingestion_projection(empty_index_root, DATE)
    assert no_index["status"] == "NOT_ASSESSED"
    assert "PDF_SOURCE_ENUMERATION_MISSING" in no_index["cannot_confirm"]
    assert "completed_count" not in no_index
    assert "total_count" not in no_index


def test_pdf_projection_and_detail_are_read_only_and_bind_all_artifacts(tmp_path, monkeypatch):
    root, files = _fixture(tmp_path)
    batch, _ = _process(root, files)
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    document_id = next(
        key for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )

    from infrastructure import zsxq_pdf_ingestion as pdf_module
    monkeypatch.setattr(pdf_module, "_download_pdf_bytes", lambda *_args: pytest.fail("read path downloaded a PDF"))
    monkeypatch.setattr(pdf_module, "_load_vision_module", lambda: pytest.fail("read path invoked local OCR"))
    projection = read_pdf_ingestion_projection(root, DATE)
    detail = read_pdf_document_detail(root, document_id, DATE)

    assert projection["status"] == "PARTIAL"
    assert projection["completed_count"] == 1
    assert projection["pending_count"] == 2
    item = next(row for row in projection["items"] if row["document_id"] == document_id)
    assert item["status"] == "READY"
    assert len(item["excerpt"]) <= 400
    assert "pages" not in item
    assert detail["status"] == "READY"
    assert detail["source"]["pdf_published_at"] is None
    assert detail["source"]["pit_status"] == "NON_PIT_CURRENT_KNOWLEDGE_SUPPLEMENT"
    assert detail["processing"]["downloaded_at"]
    assert detail["processing"]["ocr_completed_at"]
    assert detail["pages"][-1]["page_number"] == 2
    assert detail["pages"][-1]["text"].startswith("末页正文证据")
    assert detail["receipt"]["integrity"] == "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED"
    assert batch["source_run_id"] == RUN_ID


def test_pdf_detail_rejects_pages_sha_mismatch(tmp_path):
    root, files = _fixture(tmp_path)
    batch, _ = _process(root, files)
    store = NativeDataStore(root)
    index = store._read(STATE_RELATIVE)
    document_id = next(
        key for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    artifact = index["documents"][document_id]["engine_runs"][batch["engine_identity"]]
    pages_path = root / artifact["pages_path"]
    pages_path.write_bytes(pages_path.read_bytes() + b" ")

    with pytest.raises(ZsxqPdfError, match="COMPLETED_PAGES_INTEGRITY_MISMATCH"):
        read_pdf_document_detail(root, document_id, DATE)


def test_lane_includes_exact_date_pdf_projection_and_detail_route(tmp_path):
    root, files = _fixture(tmp_path)
    _process(root, files)
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    document_id = next(
        key for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    app = FastAPI()
    app.include_router(create_research_lane_router(root))
    client = TestClient(app)

    lane_response = client.get(f"/api/v3/research/lane?research_date={DATE}")
    assert lane_response.status_code == 200
    lane = lane_response.json()
    assert lane["ocr_ingestion"]["research_date"] == DATE
    assert lane["ocr_ingestion"]["completed_count"] == 1
    assert lane["ocr_ingestion"]["pending_count"] == 2

    detail_response = client.get(
        f"/api/v3/research/pdf-documents/{document_id}?research_date={DATE}"
    )
    assert detail_response.status_code == 200
    assert detail_response.headers["cache-control"] == "no-store"
    assert detail_response.json()["pages"][-1]["page_number"] == 2
    mismatch = client.get(
        f"/api/v3/research/pdf-documents/{document_id}?research_date=20261014"
    )
    assert mismatch.status_code == 404


def test_permanent_size_limit_is_not_retried_by_continuation(tmp_path, monkeypatch):
    root, files = _fixture(tmp_path)
    store = NativeDataStore(root)
    run_dir = f"external_sources/zsxq_hourly/{RUN_ID}"
    recent_path = f"{run_dir}/zsxq_recent_topics.json"
    recent = store._read(recent_path)
    topic = recent["topics_brief"][0]
    topic["files"] = [dict(files[FILE_ID], size=MAX_PDF_BYTES + 1)]
    recent["topics_brief"] = [topic]
    recent["count"] = 1
    store._write(recent_path, recent)
    fetch = store._read(f"{run_dir}/zsxq_recent_topics_fetch_result.json")
    fetch["count"] = 1
    store._write(f"{run_dir}/zsxq_recent_topics_fetch_result.json", fetch)

    from infrastructure import zsxq_pdf_ingestion as pdf_module
    from types import SimpleNamespace

    monkeypatch.setattr(
        pdf_module,
        "_load_vision_module",
        lambda: (SimpleNamespace(ENGINE=ENGINE["engine"]), "a" * 64, "b" * 64),
    )
    monkeypatch.setattr(pdf_module, "_renderer_version", lambda _path: "TEST_INJECTED")
    batch, calls = _process(root, files)
    assert calls == {"metadata": 0, "url": 0, "download": 0, "ocr": 0}
    assert batch["processed_this_batch"][0]["error_code"] == "PDF_SIZE_LIMIT_EXCEEDED"
    index = store._read(STATE_RELATIVE)
    document = next(iter(index["documents"].values()))
    run = document["engine_runs"][batch["engine_identity"]]
    assert run["status"] == "FAILED"
    assert run["attempts"] == 1
    assert run["failure_class"] == "PERMANENT"
    assert pending_pdf_tasks(root) == []

    explicit_retry = process_pdf_batch(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        file_id=FILE_ID,
        page_counter=lambda _path: 2,
        page_renderer=lambda _pdf, _page, _out: Path("unused"),
    )
    assert explicit_retry["processed_this_batch"] == []
    assert explicit_retry["failed_total"] == 1

    continuation = process_pdf_continuation(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
    )
    assert continuation["status"] == "FAILED"
    assert continuation["processed_document_count"] == 0
    assert continuation["failed_total"] == 1
    final_index = store._read(STATE_RELATIVE)
    final_run = next(iter(final_index["documents"].values()))["engine_runs"][batch["engine_identity"]]
    assert final_run["attempts"] == 1


def test_verified_page_limit_failure_recovers_once_from_owned_cached_pdf(tmp_path, monkeypatch):
    from infrastructure import zsxq_pdf_ingestion as pdf_module

    root, files = _fixture(tmp_path)
    calls = {"metadata": 0, "url": 0, "download": 0, "ocr": 0}

    def old_page_limit(_path):
        raise ZsxqPdfError("PDF_PAGE_LIMIT_EXCEEDED")

    first, _ = _process(root, files, counters=calls, page_counter=old_page_limit)
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    document_id, document = next(
        (key, row) for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    first_run = document["engine_runs"][first["engine_identity"]]
    assert first_run["status"] == "FAILED"
    assert first_run["last_error_code"] == "PDF_PAGE_LIMIT_EXCEEDED"
    assert first_run["attempts"] == 1
    assert Path(first_run["real_pdf_path"]).is_file()

    monkeypatch.setattr(pdf_module, "_pdfinfo_page_count", lambda _path: 89)
    source = document["source"]
    source_meta = index["sources"][source["source_run_id"]]
    expected_processing_run_id = (
        f"pdfproc_{source['source_run_id']}_{source_meta['source_signature'][:12]}_{first['engine_identity'][:12]}"
    )
    assert source_meta.get("processing_run_id") == expected_processing_run_id
    assert any(task["document_id"] == document_id for task in pending_pdf_tasks(root))

    source_file = files[FILE_ID]

    def metadata(_cli, _file_id):
        calls["metadata"] += 1
        return source_file

    def url(_cli, _file_id):
        calls["url"] += 1
        return "https://download.invalid/file?token=DO_NOT_PERSIST"

    def download(_url, _size):
        calls["download"] += 1
        return PDF_BYTES

    def render(_pdf, page_number, output_dir):
        path = output_dir / f"page-{page_number}.png"
        path.write_bytes(b"fake-png-data")
        return path

    expected_pdf_sha = hashlib.sha256(PDF_BYTES).hexdigest()

    def ocr_after_sha_persisted(_ocr_call):
        current_index = NativeDataStore(root)._read(STATE_RELATIVE)
        current_run = current_index["documents"][document_id]["engine_runs"][first["engine_identity"]]
        assert current_run["pdf_sha256"] == expected_pdf_sha
        assert current_run["page_limit_recovery"]["status"] == "VERIFIED"
        return {"status": "OCR_OK", "method": ENGINE["engine"], "text": "revalidated page text"}

    recovered, _ = _process(
        root,
        files,
        counters=calls,
        page_count=89,
        page_counter=lambda _path: 89,
        ocr=ocr_after_sha_persisted,
        downloader=download,
        now_value=datetime(2026, 10, 16, 1, 36, tzinfo=SHANGHAI),
    )
    assert recovered["processed_this_batch"][0]["status"] == "PARTIAL"
    assert calls["url"] == calls["download"] == 2

    while recovered["processed_this_batch"][0]["status"] != "READY":
        recovered, _ = _process(
            root,
            files,
            counters=calls,
            page_count=89,
            page_counter=lambda _path: 89,
            ocr=ocr_after_sha_persisted,
            downloader=download,
            now_value=datetime(2026, 10, 16, 1, 36, tzinfo=SHANGHAI),
        )
        assert recovered["processed_this_batch"][0]["status"] in {"PARTIAL", "READY"}
    assert calls["url"] == calls["download"] == 2

    final_index = NativeDataStore(root)._read(STATE_RELATIVE)
    run = final_index["documents"][document_id]["engine_runs"][recovered["engine_identity"]]
    assert run["status"] == "READY"
    assert run["page_count"] == run["processed_page_count"] == 89
    assert run["downloaded_at"] == first_run["downloaded_at"]
    recovery = run["page_limit_recovery"]
    assert recovery["prior_error_code"] == "PDF_PAGE_LIMIT_EXCEEDED"
    assert recovery["observed_page_count"] == 89
    assert recovery["pdf_sha256"] == expected_pdf_sha
    assert recovery["verification_method"] == "METADATA_VALIDATED_REFETCH_SHA256_MATCH"
    assert recovery["source_run_id"] == RUN_ID
    assert recovery["processing_run_id"] == first["processing_run_id"]
    assert recovery["verified_at"]
    detail = read_pdf_document_detail(root, document_id, DATE)
    assert detail["processing"]["page_count"] == 89
    assert detail["receipt"]["integrity"] == "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED"


def test_page_limit_recovery_rejects_same_size_tampered_cached_pdf(tmp_path):
    root, files = _fixture(tmp_path)
    calls = {"metadata": 0, "url": 0, "download": 0, "ocr": 0}

    def old_page_limit(_path):
        raise ZsxqPdfError("PDF_PAGE_LIMIT_EXCEEDED")

    first, _ = _process(root, files, counters=calls, page_counter=old_page_limit)
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    document_id, document = next(
        (key, row) for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    first_run = document["engine_runs"][first["engine_identity"]]
    cached_path = Path(first_run["real_pdf_path"])
    tampered = b"%PDF-1.7\n" + b"X" * (len(PDF_BYTES) - len(b"%PDF-1.7\n"))
    assert len(tampered) == len(PDF_BYTES)
    assert tampered.startswith(b"%PDF-")
    assert hashlib.sha256(tampered).hexdigest() != hashlib.sha256(PDF_BYTES).hexdigest()
    cached_path.write_bytes(tampered)

    retry, _ = _process(
        root,
        files,
        counters=calls,
        page_count=89,
        page_counter=lambda _path: 89,
    )

    assert retry["processed_this_batch"] == []
    assert retry["failed_total"] == 1
    assert calls["url"] == calls["download"] == 2
    assert calls["ocr"] == 0
    final_index = NativeDataStore(root)._read(STATE_RELATIVE)
    final_run = final_index["documents"][document_id]["engine_runs"][first["engine_identity"]]
    assert final_run["status"] == "FAILED"
    assert final_run["failure_class"] == "PERMANENT"
    assert final_run["last_error_code"] == "PDF_PAGE_LIMIT_EXCEEDED"
    recovery = final_run["page_limit_recovery"]
    assert recovery["status"] == "REJECTED"
    assert recovery["prior_error_code"] == "PDF_PAGE_LIMIT_EXCEEDED"
    assert recovery["reason_code"] == "PDF_RECOVERY_SOURCE_REVALIDATION_FAILED"
    assert recovery["checked_at"]
    assert not any(task["document_id"] == document_id for task in pending_pdf_tasks(root))
    assert final_run.get("pdf_sha256") is None
    assert cached_path.read_bytes() == tampered


def test_page_limit_recovery_retries_transient_source_failure_then_drains_89_pages(tmp_path, monkeypatch):
    from infrastructure import zsxq_pdf_ingestion as pdf_module

    root, files = _fixture(tmp_path)
    store = NativeDataStore(root)
    run_dir = f"external_sources/zsxq_hourly/{RUN_ID}"
    recent_path = f"{run_dir}/zsxq_recent_topics.json"
    recent = store._read(recent_path)
    source_topic = next(
        topic
        for topic in recent["topics_brief"]
        if any(row.get("file_id") == FILE_ID for row in topic.get("files", []))
    )
    source_file = next(row for row in source_topic["files"] if row["file_id"] == FILE_ID)
    recent["topics_brief"] = [dict(source_topic, files=[source_file])]
    recent["count"] = 1
    store._write(recent_path, recent)
    fetch_path = f"{run_dir}/zsxq_recent_topics_fetch_result.json"
    fetch = store._read(fetch_path)
    fetch["count"] = 1
    store._write(fetch_path, fetch)

    def old_page_limit(_path):
        raise ZsxqPdfError("PDF_PAGE_LIMIT_EXCEEDED")

    first, _ = _process(
        root,
        files,
        page_counter=old_page_limit,
        now_value=datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI),
    )
    index = store._read(STATE_RELATIVE)
    document_id, document = next(
        (key, row) for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    original_run = document["engine_runs"][first["engine_identity"]]
    assert original_run["status"] == "FAILED"
    assert original_run["last_error_code"] == "PDF_PAGE_LIMIT_EXCEEDED"
    assert original_run["attempts"] == 1
    assert original_run.get("pdf_sha256") is None

    clock = [datetime(2026, 10, 16, 1, 36, tzinfo=SHANGHAI)]
    calls = {"revalidation_download": 0, "ocr": 0}
    original_batch = pdf_module.process_pdf_batch

    def download_once_after_backoff(_url, _size):
        calls["revalidation_download"] += 1
        if calls["revalidation_download"] == 1:
            raise ConnectionError("temporary network failure token=DO_NOT_PERSIST")
        return PDF_BYTES

    def render(_pdf, page_number, output_dir):
        return _write_fake_page(output_dir, page_number)

    def ocr(_image):
        calls["ocr"] += 1
        return {"status": "OCR_OK", "method": ENGINE["engine"], "text": "recovered page text"}

    def batch_with_local_fakes(**kwargs):
        return original_batch(
            **kwargs,
            metadata_lookup=lambda _cli, _file_id: source_file,
            url_lookup=lambda _cli, _file_id: "https://download.invalid/file?token=DO_NOT_PERSIST",
            downloader=download_once_after_backoff,
            page_counter=lambda _path: 89,
            page_renderer=render,
            ocr_page=ocr,
            engine_info=ENGINE,
        )

    monkeypatch.setattr(pdf_module, "process_pdf_batch", batch_with_local_fakes)
    first_tick = process_next_pdf_task(root, time_budget_seconds=90, now=lambda: clock[0])
    assert first_tick["status"] == "RETRY_BACKOFF"
    assert first_tick["document_status"] == "FAILED"
    assert first_tick["last_error_code"] == "PDF_PAGE_LIMIT_EXCEEDED"
    assert first_tick["before_attempts"] == 1
    assert calls == {"revalidation_download": 1, "ocr": 0}

    failed_index = store._read(STATE_RELATIVE)
    failed_run = failed_index["documents"][document_id]["engine_runs"][first["engine_identity"]]
    recovery = failed_run["page_limit_recovery"]
    assert failed_run["status"] == "FAILED"
    assert failed_run["failure_class"] == "PERMANENT"
    assert failed_run["last_error_code"] == "PDF_PAGE_LIMIT_EXCEEDED"
    assert failed_run["attempts"] == 1
    assert failed_run.get("pdf_sha256") is None
    assert recovery["status"] == "RETRYABLE"
    assert recovery["revalidation_attempts"] == 1
    assert recovery["reason_code"] == "PDF_RECOVERY_SOURCE_TEMPORARILY_UNAVAILABLE"
    assert any(task["document_id"] == document_id for task in pending_pdf_tasks(root))

    immediate = process_next_pdf_task(root, time_budget_seconds=90, now=lambda: clock[0])
    assert immediate["status"] == "RETRY_BACKOFF"
    assert immediate["processed_document_count"] == 0
    assert calls == {"revalidation_download": 1, "ocr": 0}

    # The failed first URL reservation uses one slot in the 01:00 hour. The
    # successful page-limit revalidation plus the subsequent download need two
    # request slots, so resume in the next local hour.
    clock[0] = clock[0].replace(hour=2, minute=0)
    tick = process_next_pdf_task(root, time_budget_seconds=90, now=lambda: clock[0])
    while tick["document_status"] != "READY":
        assert tick["status"] in {"PARTIAL", "READY"}
        tick = process_next_pdf_task(root, time_budget_seconds=90, now=lambda: clock[0])

    assert tick["status"] == "READY"
    assert calls["revalidation_download"] == 2
    assert calls["ocr"] == 89
    final_index = store._read(STATE_RELATIVE)
    final_run = final_index["documents"][document_id]["engine_runs"][first["engine_identity"]]
    assert final_run["status"] == "READY"
    assert final_run["page_count"] == final_run["processed_page_count"] == 89
    assert final_run["full_page_coverage"] is True
    assert final_run["attempts"] == 2
    assert final_run["page_limit_recovery"]["status"] == "VERIFIED"
    assert final_run["page_limit_recovery"]["revalidation_attempts"] == 2
    assert final_run["page_limit_recovery"]["pdf_sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    detail = read_pdf_document_detail(root, document_id, DATE)
    assert detail["receipt"]["integrity"] == "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED"
    persisted = b"".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
    assert b"DO_NOT_PERSIST" not in persisted


def test_long_pdf_resumes_in_two_page_batches_beyond_128_pages(tmp_path):
    page_count = 129
    root, files = _fixture(tmp_path)
    calls = {"metadata": 0, "url": 0, "download": 0, "ocr": 0}
    batch, _ = _process(root, files, counters=calls, page_count=page_count)
    outcome = batch["processed_this_batch"][0]
    assert outcome["status"] == "PARTIAL"
    assert outcome["page_count"] == page_count
    assert calls["ocr"] == 2

    completed_batches = 1
    while outcome["status"] != "READY":
        batch, _ = _process(
            root,
            files,
            counters=calls,
            page_count=page_count,
        )
        outcome = batch["processed_this_batch"][0]
        completed_batches += 1
        assert outcome["status"] in {"PARTIAL", "READY"}
        assert calls["ocr"] <= page_count

    assert completed_batches == (page_count + 1) // 2
    assert calls["url"] == calls["download"] == 1
    assert calls["ocr"] == page_count

    store = NativeDataStore(root)
    index = store._read(STATE_RELATIVE)
    document_id, document = next(
        (key, row) for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    artifact = document["engine_runs"][batch["engine_identity"]]
    assert artifact["status"] == "READY"
    assert artifact["page_count"] == artifact["processed_page_count"] == page_count
    assert artifact["attempts"] == 1
    assert artifact["pdf_sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert read_pdf_document_detail(root, document_id, DATE)["processing"]["page_count"] == page_count
    projection = read_pdf_ingestion_projection(root, DATE)
    item = next(row for row in projection["items"] if row["document_id"] == document_id)
    assert item["status"] == "READY"
    assert item["page_count"] == item["processed_page_count"] == page_count


def test_download_size_mismatch_remains_retryable(tmp_path):
    root, files = _fixture(tmp_path)
    first, _ = _process(root, files, downloader=lambda _url, _size: PDF_BYTES[:-1])
    assert first["processed_this_batch"][0]["error_code"] == "PDF_SIZE_MISMATCH"
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    document = next(row for row in index["documents"].values() if row["source"]["file_id"] == FILE_ID)
    run = document["engine_runs"][first["engine_identity"]]
    assert run["status"] == "PENDING"
    assert run["failure_class"] == "TRANSIENT"
    assert any(task["file_id"] == FILE_ID for task in pending_pdf_tasks(root))

    second, _ = _process(root, files)
    assert second["processed_this_batch"][0]["status"] == "READY"
    final = NativeDataStore(root)._read(STATE_RELATIVE)
    final_run = next(row for row in final["documents"].values() if row["source"]["file_id"] == FILE_ID)
    assert final_run["engine_runs"][first["engine_identity"]]["attempts"] == 2


def test_queue_tick_advances_multiple_documents_across_bounded_calls(tmp_path, monkeypatch):
    root, files = _fixture(tmp_path)
    from infrastructure import zsxq_pdf_ingestion as pdf_module

    original = pdf_module.process_pdf_batch
    original(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        engine_info=ENGINE,
        page_counter=lambda _pdf: 2,
        page_renderer=lambda _pdf, page, output_dir: _write_fake_page(output_dir, page),
        enqueue_only=True,
    )
    calls = {"batch": 0, "download": 0, "ocr": 0}
    now_value = datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI)

    def batch_with_local_fakes(**kwargs):
        calls["batch"] += 1

        def render(_pdf, page_number, output_dir):
            return _write_fake_page(output_dir, page_number)

        def ocr(_image):
            calls["ocr"] += 1
            return {"status": "OCR_OK", "method": ENGINE["engine"], "text": "verified page text"}

        def download(_url, _size):
            calls["download"] += 1
            return PDF_BYTES

        return original(
            **kwargs,
            metadata_lookup=lambda _cli, file_id: files[file_id],
            url_lookup=lambda _cli, _file_id: "https://download.invalid/file?token=DO_NOT_PERSIST",
            downloader=download,
            page_counter=lambda _pdf: 2,
            page_renderer=render,
            ocr_page=ocr,
            engine_info=ENGINE,
        )

    monkeypatch.setattr(pdf_module, "process_pdf_batch", batch_with_local_fakes)
    ticks = [process_next_pdf_task(root, time_budget_seconds=90, now=lambda: now_value) for _ in range(2)]
    now_value = now_value.replace(hour=2)
    ticks.append(process_next_pdf_task(root, time_budget_seconds=90, now=lambda: now_value))

    assert [tick["status"] for tick in ticks] == ["READY", "READY", "READY"]
    assert [tick["processed_document_count"] for tick in ticks] == [1, 1, 1]
    assert calls == {"batch": 3, "download": 3, "ocr": 6}
    assert process_next_pdf_task(root, now=lambda: now_value)["status"] == "NO_RETRYABLE_TASKS"
    projection = read_pdf_ingestion_projection(root, DATE)
    assert projection["completed_count"] == 3
    assert projection["pending_count"] == 0
    assert all(tick["pdf_sha256"] and tick["pages_file_sha256"] for tick in ticks)
    assert all(row["can_open_detail"] for row in projection["items"])
    persisted = b"".join(path.read_bytes() for path in root.rglob("*") if path.is_file())
    assert b"DO_NOT_PERSIST" not in persisted
    assert b"download.invalid" not in persisted


def test_queue_tick_backs_off_transient_failure_before_one_bounded_retry(tmp_path, monkeypatch):
    root, _files = _fixture(tmp_path)
    store = NativeDataStore(root)
    run_dir = f"external_sources/zsxq_hourly/{RUN_ID}"
    recent_path = f"{run_dir}/zsxq_recent_topics.json"
    recent = store._read(recent_path)
    recent["topics_brief"] = [dict(recent["topics_brief"][0], files=[recent["topics_brief"][0]["files"][0]])]
    recent["count"] = 1
    store._write(recent_path, recent)
    fetch_path = f"{run_dir}/zsxq_recent_topics_fetch_result.json"
    fetch = store._read(fetch_path)
    fetch["count"] = 1
    store._write(fetch_path, fetch)
    source_file = recent["topics_brief"][0]["files"][0]
    clock = [datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI)]
    attempts = {"download": 0}
    from infrastructure import zsxq_pdf_ingestion as pdf_module

    original = pdf_module.process_pdf_batch
    original(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        engine_info=ENGINE,
        page_counter=lambda _pdf: 2,
        page_renderer=lambda _pdf, page, output_dir: _write_fake_page(output_dir, page),
        enqueue_only=True,
    )

    def batch_with_bounded_download(**kwargs):
        def download(_url, _size):
            attempts["download"] += 1
            return PDF_BYTES[:-1] if attempts["download"] == 1 else PDF_BYTES

        return original(
            **kwargs,
            metadata_lookup=lambda _cli, _file_id: source_file,
            url_lookup=lambda _cli, _file_id: "https://download.invalid/file?token=DO_NOT_PERSIST",
            downloader=download,
            page_counter=lambda _pdf: 2,
            page_renderer=lambda _pdf, page, output_dir: _write_fake_page(output_dir, page),
            ocr_page=lambda _image: {"status": "OCR_OK", "method": ENGINE["engine"], "text": "verified"},
            engine_info=ENGINE,
        )

    monkeypatch.setattr(pdf_module, "process_pdf_batch", batch_with_bounded_download)
    first = process_next_pdf_task(root, time_budget_seconds=90, now=lambda: clock[0])
    assert first["status"] == "RETRY_BACKOFF"
    assert first["document_status"] == "PENDING"
    assert first["last_error_code"] == "PDF_SIZE_MISMATCH"
    assert attempts["download"] == 1

    immediate = process_next_pdf_task(root, time_budget_seconds=90, now=lambda: clock[0])
    assert immediate["status"] == "RETRY_BACKOFF"
    assert immediate["processed_document_count"] == 0
    assert attempts["download"] == 1

    clock[0] = clock[0].replace(minute=36)
    resumed = process_next_pdf_task(root, time_budget_seconds=90, now=lambda: clock[0])
    assert resumed["status"] == "READY"
    assert resumed["document_status"] == "READY"
    assert attempts["download"] == 2
    index = store._read(STATE_RELATIVE)
    document = next(row for row in index["documents"].values() if row["source"]["file_id"] == FILE_ID)
    latest = pdf_module._latest_engine_run(document)
    assert latest[1]["attempts"] == 2
    assert pending_pdf_tasks(root) == []


def test_kernel_lock_wait_uses_remaining_pdf_budget_and_queue_stays_retryable(tmp_path):
    root, files = _fixture(tmp_path)
    store = NativeDataStore(root)
    queued = process_pdf_batch(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        engine_info=ENGINE,
        page_counter=lambda _path: 2,
        page_renderer=lambda _pdf, _page, _out: Path("unused"),
        enqueue_only=True,
        time_budget_seconds=10,
    )
    assert queued["pending_total"] == 3

    lock_ready = threading.Event()
    release_lock = threading.Event()
    from infrastructure import zsxq_pdf_ingestion as pdf_module

    def hold_lock():
        with pdf_module._store_io(store).kernel_lock(LOCK_RELATIVE, timeout=5, poll=0.01):
            lock_ready.set()
            release_lock.wait(5)

    holder = threading.Thread(target=hold_lock, daemon=True)
    holder.start()
    assert lock_ready.wait(2)
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="OWNED_LOCK_TIMEOUT"):
            process_pdf_batch(
                data_root=root,
                trade_date=DATE,
                slot=SLOT,
                source_run_id=RUN_ID,
                engine_info=ENGINE,
                page_counter=lambda _path: 2,
                page_renderer=lambda _pdf, _page, _out: Path("unused"),
                time_budget_seconds=1,
            )
    finally:
        release_lock.set()
        holder.join(timeout=2)
    assert time.monotonic() - started < 1.5
    assert len(pending_pdf_tasks(root)) == 3


def _seed_recovery_failed(root: Path, files: dict[str, dict], *, target: str = FILE_ID):
    calls = {"metadata": 0, "url": 0, "download": 0, "ocr": 0}

    def no_download(_url, _size):
        calls["download"] += 1
        raise ZsxqPdfError("ZSXQ_DOWNLOAD_URL_MISSING")

    first, _ = _process(root, files, target=target, downloader=no_download, counters=calls)
    second, _ = _process(root, files, target=target, downloader=no_download, counters=calls)
    assert first["processed_this_batch"][0]["status"] == "PENDING"
    assert second["processed_this_batch"][0]["status"] == "FAILED"
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    document_key, document = next(
        (key, row) for key, row in index["documents"].items() if row["source"]["file_id"] == target
    )
    artifact = document["engine_runs"][second["engine_identity"]]
    assert artifact["status"] == "FAILED"
    assert artifact["attempts"] == 2
    assert not artifact.get("pdf_sha256")
    return document_key, second["engine_identity"], calls


def _recovery_args(root, files, document_key, authorization_id, calls, **overrides):
    def metadata(_cli, file_id):
        calls["metadata"] += 1
        return files[file_id]

    def url(_cli, _file_id):
        calls["url"] += 1
        return "https://download.invalid/file?token=DO_NOT_PERSIST"

    def download(_url, _size):
        calls["download"] += 1
        return PDF_BYTES

    def render(_pdf, page_number, output_dir):
        return _write_fake_page(output_dir, page_number)

    def ocr(_image):
        calls["ocr"] += 1
        return {"status": "OCR_OK", "method": ENGINE["engine"], "text": f"page {calls['ocr']} evidence"}

    values = {
        "data_root": root,
        "trade_date": DATE,
        "source_run_id": RUN_ID,
        "document_key": document_key,
        "authorization_id": authorization_id,
        "metadata_lookup": metadata,
        "url_lookup": url,
        "downloader": download,
        "page_counter": lambda _pdf: 2,
        "page_renderer": render,
        "ocr_page": ocr,
        "engine_info": ENGINE,
        # Recovery starts in a later local hour than the two bounded setup
        # failures in _seed_recovery_failed.
        "now": lambda: datetime(2026, 10, 16, 2, 30, tzinfo=SHANGHAI),
    }
    values.update(overrides)
    return values


def test_process_pdf_batch_rejects_unclaimed_recovery_id_before_processing_io(tmp_path):
    root, files = _fixture(tmp_path)
    document_key, _engine_identity, calls = _seed_recovery_failed(root, files)
    callbacks_before = dict(calls)
    args = _recovery_args(root, files, document_key, "unclaimed-id", calls)

    with pytest.raises(ZsxqPdfError, match="PDF_RECOVERY_CLAIM_INCOMPLETE"):
        process_pdf_batch(
            data_root=root,
            trade_date=DATE,
            slot=SLOT,
            source_run_id=RUN_ID,
            document_key=document_key,
            metadata_lookup=args["metadata_lookup"],
            url_lookup=args["url_lookup"],
            downloader=args["downloader"],
            page_counter=args["page_counter"],
            page_renderer=args["page_renderer"],
            ocr_page=args["ocr_page"],
            engine_info=ENGINE,
            _recovery_authorization_id="unclaimed-id",
        )

    assert calls == callbacks_before
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    assert document_key not in index["recovery_consumed"]
    assert not (root / RECOVERY_AUDIT_RELATIVE).exists()


def test_recovery_url_hourly_limit_defers_without_consuming_claim_or_attempt(tmp_path):
    from infrastructure.zsxq_pdf_local import HOUR_LEDGER_RELATIVE

    root, files = _fixture(tmp_path)
    document_key, engine_identity, calls = _seed_recovery_failed(root, files)
    before_callbacks = dict(calls)
    before_index = NativeDataStore(root)._read(STATE_RELATIVE)
    authorization_id = "auth-deferred-cap-20261016"

    # The two setup failures already reserved this hour's URL request slots.
    args = _recovery_args(root, files, document_key, authorization_id, calls)
    args["now"] = lambda: datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI)
    result = recover_one_pdf(**args)

    assert result["status"] == "DEFERRED"
    assert result["recovery_status"] == "DEFERRED"
    assert result["error_code"] == "UPSTREAM_URL_HOURLY_LIMIT"
    assert calls == before_callbacks
    after_index = NativeDataStore(root)._read(STATE_RELATIVE)
    assert after_index["documents"][document_key]["engine_runs"][engine_identity]["attempts"] == 2
    assert after_index["recovery_consumed"] == before_index["recovery_consumed"]
    audit_path = root / RECOVERY_AUDIT_RELATIVE
    assert not audit_path.exists()
    ledger = NativeDataStore(root)._read(HOUR_LEDGER_RELATIVE)
    assert len(ledger["hours"]["2026101601"]["upstream_url_requests"]) == 2


def test_recovery_known_13607_pause_defers_without_claim_or_callback(tmp_path):
    from infrastructure.zsxq_pdf_local import record_13607_pause

    root, files = _fixture(tmp_path)
    document_key, engine_identity, calls = _seed_recovery_failed(root, files)
    before_callbacks = dict(calls)
    before_index = NativeDataStore(root)._read(STATE_RELATIVE)
    record_13607_pause(root, now=datetime(2026, 10, 16, 1, 45, tzinfo=SHANGHAI))
    authorization_id = "auth-deferred-13607-20261016"
    args = _recovery_args(root, files, document_key, authorization_id, calls)
    args["now"] = lambda: datetime(2026, 10, 16, 1, 46, tzinfo=SHANGHAI)

    result = recover_one_pdf(**args)

    assert result["status"] == "DEFERRED"
    assert result["recovery_status"] == "DEFERRED"
    assert result["error_code"] == "ZSXQ_UPSTREAM_PAUSED_13607"
    assert calls == before_callbacks
    after_index = NativeDataStore(root)._read(STATE_RELATIVE)
    assert after_index["documents"][document_key]["engine_runs"][engine_identity]["attempts"] == 2
    assert after_index["recovery_consumed"] == before_index["recovery_consumed"]
    assert not (root / RECOVERY_AUDIT_RELATIVE).exists()


def test_recovery_continuation_url_limit_defers_without_consuming_checkpoint(tmp_path):
    from infrastructure.zsxq_pdf_local import reserve_upstream_url_request

    root, files = _fixture(tmp_path)
    document_key, engine_identity, calls = _seed_recovery_failed(root, files)
    authorization_id = "auth-deferred-continuation-20261016"
    args = _recovery_args(root, files, document_key, authorization_id, calls)
    args["page_counter"] = lambda _pdf: 5
    first = recover_one_pdf(**args)
    assert first["status"] == "PARTIAL"
    assert first["continuation_ready"] is True

    stamp = datetime(2026, 10, 16, 2, 30, tzinfo=SHANGHAI)
    reserve_upstream_url_request(root, "fill-second-slot", now=stamp)
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    artifact = index["documents"][document_key]["engine_runs"][engine_identity]
    (root / artifact["pdf_path"]).unlink()
    audit_before = NativeDataStore(root)._read(RECOVERY_AUDIT_RELATIVE)
    record_before = audit_before["authorizations"][authorization_id]
    callbacks_before = dict(calls)

    args["now"] = lambda: stamp
    args["continue_existing"] = True
    result = recover_one_pdf(**args)

    assert result["status"] == "DEFERRED"
    assert result["recovery_status"] == "DEFERRED"
    assert result["error_code"] == "UPSTREAM_URL_HOURLY_LIMIT"
    assert result["continuation_ready"] is True
    assert calls == callbacks_before
    after_index = NativeDataStore(root)._read(STATE_RELATIVE)
    assert after_index["documents"][document_key]["engine_runs"][engine_identity]["attempts"] == 2
    assert after_index["documents"][document_key]["engine_runs"][engine_identity]["status"] == "PARTIAL"
    record_after = NativeDataStore(root)._read(RECOVERY_AUDIT_RELATIVE)["authorizations"][authorization_id]
    assert record_after["continuation_count"] == record_before["continuation_count"]
    assert record_after["checkpoint"] == record_before["checkpoint"]


def test_recovery_continuation_requires_consumed_checkpoint_and_matching_claim_copies(tmp_path):
    from infrastructure import zsxq_pdf_ingestion as pdf_module

    root, files = _fixture(tmp_path)
    document_key, _engine_identity, calls = _seed_recovery_failed(root, files)
    authorization_id = "auth-claim-checkpoint-20261016"
    args = _recovery_args(root, files, document_key, authorization_id, calls)
    args["page_counter"] = lambda _pdf: 5
    partial = recover_one_pdf(**args)
    assert partial["recovery_status"] == "CLAIMED"
    assert partial["continuation_ready"] is True
    callbacks_before = dict(calls)

    with pytest.raises(ZsxqPdfError, match="PDF_RECOVERY_CONTINUATION_UNSAFE"):
        process_pdf_batch(
            data_root=root,
            trade_date=DATE,
            slot=SLOT,
            source_run_id=RUN_ID,
            document_key=document_key,
            metadata_lookup=args["metadata_lookup"],
            url_lookup=args["url_lookup"],
            downloader=args["downloader"],
            page_counter=args["page_counter"],
            page_renderer=args["page_renderer"],
            ocr_page=args["ocr_page"],
            engine_info=ENGINE,
            _recovery_authorization_id=authorization_id,
            _recovery_continuation=True,
        )
    assert calls == callbacks_before

    store = NativeDataStore(root)
    audit = store._read(RECOVERY_AUDIT_RELATIVE)
    record = audit["authorizations"][authorization_id]
    pdf_module._consume_recovery_checkpoint(
        store,
        document_key=document_key,
        authorization_id=authorization_id,
        binding={
            "source_signature": record["source_signature"],
            "engine_identity": record["engine_identity"],
            "input_sha256": record["input_sha256"],
            "source_metadata_sha256": record["source_metadata_sha256"],
            "source_file_hash_raw": record["source_file_hash_raw"],
        },
    )
    index = store._read(STATE_RELATIVE)
    index["recovery_consumed"][document_key]["consumed_checkpoint_sha256"] = "0" * 64
    store._write(STATE_RELATIVE, index)

    with pytest.raises(ZsxqPdfError, match="PDF_RECOVERY_CLAIM_INCOMPLETE"):
        process_pdf_batch(
            data_root=root,
            trade_date=DATE,
            slot=SLOT,
            source_run_id=RUN_ID,
            document_key=document_key,
            metadata_lookup=args["metadata_lookup"],
            url_lookup=args["url_lookup"],
            downloader=args["downloader"],
            page_counter=args["page_counter"],
            page_renderer=args["page_renderer"],
            ocr_page=args["ocr_page"],
            engine_info=ENGINE,
            _recovery_authorization_id=authorization_id,
            _recovery_continuation=True,
        )
    assert calls == callbacks_before


def test_recover_one_binds_full_identity_and_source_hashes_before_processing_io(tmp_path):
    for case in ("document", "run", "date", "source_hash"):
        case_root, files = _fixture(tmp_path / case)
        document_key, _engine_identity, calls = _seed_recovery_failed(case_root, files)
        if case == "source_hash":
            store = NativeDataStore(case_root)
            index = store._read(STATE_RELATIVE)
            index["documents"][document_key]["source"]["source_hash_raw"] = "changed-original-hash"
            store._write(STATE_RELATIVE, index)

        kwargs = _recovery_args(case_root, files, document_key, f"auth-{case}-01", calls)
        if case == "document":
            kwargs["document_key"] = "f" * 64
            expected = "DOCUMENT_NOT_FOUND"
        elif case == "run":
            kwargs["source_run_id"] = "20261014_230000_wrong"
            expected = "PDF_RECOVERY_SOURCE_IDENTITY_MISMATCH"
        elif case == "date":
            kwargs["trade_date"] = "20261014"
            expected = "PDF_RECOVERY_SOURCE_IDENTITY_MISMATCH"
        else:
            expected = "SOURCE_DOCUMENT_METADATA_MISMATCH"
        before_callbacks = dict(calls)
        with pytest.raises(ZsxqPdfError, match=expected):
            recover_one_pdf(**kwargs)
        assert calls == before_callbacks
        # The two prior fake failed downloads are the only callbacks; recovery made none.
        audit_path = case_root / RECOVERY_AUDIT_RELATIVE
        assert not audit_path.exists()


def test_recover_one_long_pdf_uses_safe_two_page_checkpoints_without_redownload_or_retry_reset(tmp_path):
    root, files = _fixture(tmp_path)
    document_key, engine_identity, calls = _seed_recovery_failed(root, files)
    arguments = _recovery_args(root, files, document_key, "auth-long-20261016", calls)
    arguments["page_counter"] = lambda _pdf: 5

    first = recover_one_pdf(**arguments)
    assert first["status"] == "PARTIAL"
    assert first["recovery_status"] == "CLAIMED"
    assert first["continuation_ready"] is True
    assert first["processed_page_count"] == 2
    assert calls["ocr"] == 2
    assert calls["download"] == 3  # two exhausted prior fake failures plus one recovery download

    replay = recover_one_pdf(**arguments)
    assert replay["recovery_status"] == "CANNOT_CONFIRM"
    assert replay["error_code"] == "PDF_RECOVERY_ALREADY_CLAIMED"
    assert calls["ocr"] == 2

    second = recover_one_pdf(**{**arguments, "continue_existing": True})
    assert second["status"] == "PARTIAL"
    assert second["processed_page_count"] == 4
    assert second["continuation_ready"] is True
    third = recover_one_pdf(**{**arguments, "continue_existing": True})
    assert third["status"] == "READY"
    assert third["recovery_status"] == "SUCCEEDED"
    assert third["continuation_ready"] is False
    assert calls["ocr"] == 5
    assert calls["download"] == 3

    index = NativeDataStore(root)._read(STATE_RELATIVE)
    artifact = index["documents"][document_key]["engine_runs"][engine_identity]
    assert artifact["attempts"] == 2
    assert artifact["page_count"] == artifact["processed_page_count"] == 5
    assert artifact["pdf_sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    audit = NativeDataStore(root)._read(RECOVERY_AUDIT_RELATIVE)
    auth = audit["authorizations"]["auth-long-20261016"]
    assert auth["status"] == "SUCCEEDED"
    assert auth["continuation_count"] == 2
    assert auth["source_signature"] == index["sources"][RUN_ID]["source_signature"]
    assert set(auth["input_sha256"]) == {"status", "fetch_result", "recent_topics", "summary"}
    assert auth["source_metadata_sha256"]
    assert auth["source_file_hash_raw"] == SOURCE_HASH
    assert auth["result_artifacts"]["document_key"] == document_key
    assert auth["result_artifacts"]["pdf_sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert auth["result_artifacts"]["page_count"] == 5
    assert auth["result_artifacts"]["receipt_sha256"]
    assert all(task["document_id"] != document_key for task in pending_pdf_tasks(root))


def test_recovery_ocr_failure_keeps_verified_download_and_cannot_be_reauthorized(tmp_path):
    root, files = _fixture(tmp_path)
    document_key, engine_identity, calls = _seed_recovery_failed(root, files)
    arguments = _recovery_args(root, files, document_key, "auth-fail-20261016", calls)

    def fail_ocr(_image):
        calls["ocr"] += 1
        return {"status": "OCR_TIMEOUT", "method": ENGINE["engine"], "text": ""}

    arguments["ocr_page"] = fail_ocr
    result = recover_one_pdf(**arguments)
    assert result["status"] == "FAILED"
    assert result["recovery_status"] == "FAILED_FINAL"
    assert result["pdf_sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert result["pages_file_sha256"]
    assert result["receipt_sha256"]
    assert calls["download"] == 3
    assert calls["ocr"] == 1

    detail = read_pdf_document_detail(root, document_key, DATE)
    final_index = NativeDataStore(root)._read(STATE_RELATIVE)
    assert final_index["documents"][document_key]["engine_runs"][engine_identity]["attempts"] == 2
    assert final_index["documents"][document_key]["engine_runs"][engine_identity]["last_error_code"] == "OCR_TIMEOUT"
    assert detail["receipt"]["integrity"] == "SOURCE_PDF_AND_PAGE_HASHES_VERIFIED"
    receipt = NativeDataStore(root)._read(final_index["documents"][document_key]["engine_runs"][engine_identity]["receipt_path"])
    assert receipt["document_key"] == document_key
    audit = NativeDataStore(root)._read(RECOVERY_AUDIT_RELATIVE)
    artifact_evidence = audit["authorizations"]["auth-fail-20261016"]["result_artifacts"]
    assert artifact_evidence["pdf_sha256"] == result["pdf_sha256"]
    assert artifact_evidence["receipt_sha256"] == result["receipt_sha256"]
    replay = recover_one_pdf(**{**arguments, "authorization_id": "auth-fail-new-20261016"})
    assert replay["recovery_status"] == "CANNOT_CONFIRM"
    assert replay["error_code"] == "PDF_RECOVERY_ALREADY_CLAIMED"
    assert calls["ocr"] == 1


def test_recovery_cache_reuses_verified_complete_pages_without_ocr_or_download(tmp_path):
    root, files = _fixture(tmp_path)
    completed, _ = _process(root, files, page_count=2)
    store = NativeDataStore(root)
    index = store._read(STATE_RELATIVE)
    document_key, document = next(
        (key, row) for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    engine_identity = completed["engine_identity"]
    artifact = document["engine_runs"][engine_identity]
    artifact.update(
        status="FAILED",
        attempts=2,
        last_error_code="PRIOR_FAILURE",
        failure_class="TRANSIENT",
        processed_page_count=None,
        full_page_coverage=False,
    )
    store._write(STATE_RELATIVE, index)
    calls = {"metadata": 0, "url": 0, "download": 0, "ocr": 0}
    result = recover_one_pdf(**_recovery_args(root, files, document_key, "auth-cache-20261016", calls))
    assert result["status"] == "READY"
    assert result["recovery_status"] == "SUCCEEDED"
    assert result["reused"] is True
    assert calls["metadata"] == 1
    assert calls["url"] == calls["download"] == calls["ocr"] == 0
    recovered_artifact = NativeDataStore(root)._read(STATE_RELATIVE)["documents"][document_key]["engine_runs"][engine_identity]
    assert recovered_artifact["attempts"] == 2
    assert recovered_artifact["page_count"] == recovered_artifact["processed_page_count"] == 2
    assert recovered_artifact["full_page_coverage"] is True
    assert recovered_artifact["page_statuses"] == ["OCR_OK", "OCR_OK"]
    receipt = NativeDataStore(root)._read(recovered_artifact["receipt_path"])
    assert receipt["full_page_coverage"] is True


def test_recovery_concurrent_same_authorization_has_one_processing_winner(tmp_path):
    root, files = _fixture(tmp_path)
    document_key, _identity, calls = _seed_recovery_failed(root, files)
    before = dict(calls)
    arguments = _recovery_args(root, files, document_key, "auth-concurrent-20261016", calls)
    ready = threading.Barrier(2)

    def invoke():
        ready.wait(timeout=3)
        try:
            return recover_one_pdf(**arguments)
        except ZsxqPdfError as error:
            return {"status": "CANNOT_CONFIRM", "error_code": error.code}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _slot: invoke(), range(2)))
    assert sum(row.get("recovery_status") == "SUCCEEDED" for row in results) == 1
    assert calls["metadata"] == before["metadata"] + 1
    assert calls["url"] == before["url"] + 1
    assert calls["download"] == before["download"] + 1
    assert calls["ocr"] == before["ocr"] + 2
    final_index = NativeDataStore(root)._read(STATE_RELATIVE)
    artifact = final_index["documents"][document_key]["engine_runs"][_identity]
    assert artifact["status"] == "READY"
    assert artifact["attempts"] == 2


def test_recovery_url_missing_http_error_unsafe_url_and_redirect_fail_closed(tmp_path, monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    from urllib.request import Request

    from infrastructure import zsxq_pdf_ingestion as pdf_module

    with pytest.raises(ZsxqPdfError, match="ZSXQ_DOWNLOAD_URL_UNSAFE"):
        pdf_module._validate_download_url("https://user:pass@example.invalid/file")
    with pytest.raises(ZsxqPdfError, match="DOWNLOAD_REDIRECT_DOWNGRADE"):
        pdf_module._HttpsRedirectHandler().redirect_request(
            Request("https://example.invalid/file"), None, 302, "Found", {}, "http://example.invalid/file"
        )
    with pytest.raises(ZsxqPdfError, match="DOWNLOAD_REDIRECT_UNSAFE"):
        pdf_module._HttpsRedirectHandler().redirect_request(
            Request("https://example.invalid/file"), None, 302, "Found", {}, "https://user:pass@example.invalid/file"
        )
    def raise_http_error(*_args, **_kwargs):
        raise HTTPError("https://example.invalid/file", 503, "unavailable", {}, BytesIO(b""))

    monkeypatch.setattr(pdf_module, "build_opener", lambda *_args: type("Opener", (), {"open": raise_http_error})())
    with pytest.raises(ZsxqPdfError, match="PDF_HTTP_ERROR_503"):
        pdf_module._download_pdf_bytes("https://example.invalid/file", len(PDF_BYTES))

    for bad_url, expected in ((None, "ZSXQ_DOWNLOAD_URL_MISSING"), ("http://example.invalid/file", "ZSXQ_DOWNLOAD_URL_UNSAFE")):
        root, files = _fixture(tmp_path / expected.replace(":", "_"))
        document_key, _identity, calls = _seed_recovery_failed(root, files)
        args = _recovery_args(root, files, document_key, f"auth-{expected.replace(':', '-')}", calls)

        def selected_url(_cli, _file_id):
            calls["url"] += 1
            if bad_url is None:
                raise ZsxqPdfError(expected)
            return bad_url

        args["url_lookup"] = selected_url
        outcome = recover_one_pdf(**args)
        assert outcome["recovery_status"] == "FAILED_FINAL"
        assert outcome["error_code"] == expected
        assert calls["download"] == 2
        assert calls["ocr"] == 0


def test_recovery_index_or_audit_commit_error_and_interrupt_never_reopen_claim(tmp_path, monkeypatch):
    from infrastructure import zsxq_pdf_ingestion as pdf_module

    root, files = _fixture(tmp_path / "index-write")
    document_key, _identity, calls = _seed_recovery_failed(root, files)
    callbacks_before = dict(calls)
    original_write = pdf_module._write_json
    failed_once = {"value": False}

    def fail_index_once(store, relative, value):
        if relative == STATE_RELATIVE and not failed_once["value"]:
            failed_once["value"] = True
            raise OSError("simulated index write failure")
        return original_write(store, relative, value)

    monkeypatch.setattr(pdf_module, "_write_json", fail_index_once)
    result = recover_one_pdf(**_recovery_args(root, files, document_key, "auth-index-write-20261016", calls))
    assert result["recovery_status"] == "CANNOT_CONFIRM"
    assert calls == callbacks_before
    monkeypatch.setattr(pdf_module, "_write_json", original_write)
    replay = recover_one_pdf(**_recovery_args(root, files, document_key, "auth-index-new-20261016", calls))
    assert replay["recovery_status"] == "CANNOT_CONFIRM"
    assert replay["error_code"] == "PDF_RECOVERY_ALREADY_CLAIMED"
    assert calls == callbacks_before

    root2, files2 = _fixture(tmp_path / "audit-write")
    document_key2, _identity2, calls2 = _seed_recovery_failed(root2, files2)
    original_write2 = pdf_module._write_json
    audit_writes = {"count": 0}

    def fail_final_audit_once(store, relative, value):
        if relative == RECOVERY_AUDIT_RELATIVE:
            audit_writes["count"] += 1
            if audit_writes["count"] == 3:
                raise OSError("simulated final audit write failure")
        return original_write2(store, relative, value)

    monkeypatch.setattr(pdf_module, "_write_json", fail_final_audit_once)
    failed = recover_one_pdf(**_recovery_args(root2, files2, document_key2, "auth-audit-write-20261016", calls2))
    assert failed["recovery_status"] == "CANNOT_CONFIRM"
    assert calls2["ocr"] == 2
    monkeypatch.setattr(pdf_module, "_write_json", original_write2)
    callbacks_after_audit_failure = dict(calls2)
    replay = recover_one_pdf(**_recovery_args(root2, files2, document_key2, "auth-audit-new-20261016", calls2))
    assert replay["recovery_status"] == "CANNOT_CONFIRM"
    assert replay["error_code"] == "PDF_RECOVERY_ALREADY_CLAIMED"
    assert calls2 == callbacks_after_audit_failure
    assert calls2["ocr"] == 2

    root3, files3 = _fixture(tmp_path / "interrupt")
    document_key3, _identity3, calls3 = _seed_recovery_failed(root3, files3)
    callbacks_before3 = dict(calls3)
    monkeypatch.setattr(pdf_module, "process_pdf_batch", lambda **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        recover_one_pdf(**_recovery_args(root3, files3, document_key3, "auth-interrupt-20261016", calls3))
    monkeypatch.setattr(pdf_module, "process_pdf_batch", process_pdf_batch)
    interrupted = recover_one_pdf(
        **_recovery_args(root3, files3, document_key3, "auth-interrupt-20261016", calls3, continue_existing=True)
    )
    assert interrupted["recovery_status"] == "CANNOT_CONFIRM"
    assert calls3 == callbacks_before3


def test_missing_audit_row_or_changed_authorization_cannot_grant_another_claim(tmp_path):
    root, files = _fixture(tmp_path)
    document_key, _identity, calls = _seed_recovery_failed(root, files)
    arguments = _recovery_args(root, files, document_key, "auth-missing-audit-20261016", calls)

    def fail_ocr(_image):
        calls["ocr"] += 1
        return {"status": "OCR_TIMEOUT", "method": ENGINE["engine"], "text": ""}

    arguments["ocr_page"] = fail_ocr
    result = recover_one_pdf(**arguments)
    assert result["recovery_status"] == "FAILED_FINAL"
    audit_store = NativeDataStore(root)
    audit = audit_store._read(RECOVERY_AUDIT_RELATIVE)
    audit["authorizations"].pop("auth-missing-audit-20261016")
    audit_store._write(RECOVERY_AUDIT_RELATIVE, audit)

    changed = recover_one_pdf(**{**arguments, "authorization_id": "auth-changed-20261016"})
    assert changed["recovery_status"] == "CANNOT_CONFIRM"
    assert changed["error_code"] == "PDF_RECOVERY_ALREADY_CLAIMED"
    assert calls["ocr"] == 1


def test_recovery_cli_selects_the_full_document_key_not_the_queue_first_file(tmp_path, monkeypatch, capsys):
    from infrastructure import zsxq_pdf_ingestion as pdf_module
    from ops import run_zsxq_hourly_delta as hourly

    root, files = _fixture(tmp_path)
    target = "181515482484554"
    document_key, _identity, calls = _seed_recovery_failed(root, files, target=target)
    real_recover = pdf_module.recover_one_pdf
    selected_ids = []

    def offline_recover(**kwargs):
        original_metadata = kwargs.pop("metadata_lookup", None)
        if original_metadata is not None:
            raise AssertionError("CLI must not inject callbacks")

        def metadata(_cli, file_id):
            selected_ids.append(file_id)
            return files[file_id]

        return real_recover(
            **kwargs,
            metadata_lookup=metadata,
            url_lookup=lambda _cli, _file_id: "https://download.invalid/file?token=DO_NOT_PERSIST",
            downloader=lambda _url, _size: PDF_BYTES,
            page_counter=lambda _pdf: 1,
            page_renderer=lambda _pdf, page, output_dir: _write_fake_page(output_dir, page),
            ocr_page=lambda _image: {"status": "OCR_OK", "method": ENGINE["engine"], "text": "cli-selected"},
            engine_info=ENGINE,
        )

    monkeypatch.setattr(hourly, "recover_one_pdf", offline_recover)
    rc = hourly.main(
        [
            "--data-root", str(root),
            "--date", DATE,
            "--source-run-id", RUN_ID,
            "--pdf-recover-one",
            "--pdf-document-key", document_key,
            "--pdf-authorization-id", "auth-cli-20261016",
        ]
    )
    output = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert output["status"] == "READY"
    assert output["document_key"] == document_key
    assert output["authorization_id"] == "auth-cli-20261016"
    assert selected_ids == [target]

    resumed, _calls = _process(
        root,
        files,
        now_value=datetime(2026, 10, 16, 2, 30, tzinfo=SHANGHAI),
    )
    assert resumed["processed_this_batch"][0]["status"] == "READY"


def test_local_pdf_reuses_matching_verified_cache_without_url_or_ocr(tmp_path, monkeypatch):
    from infrastructure import zsxq_pdf_ingestion as pdf_module
    from infrastructure.zsxq_pdf_local import process_local_pdf_tick, submit_local_pdf_batch

    root, files = _fixture(tmp_path)
    _process(root, files)
    index = NativeDataStore(root)._read(STATE_RELATIVE)
    canonical_id = next(
        key for key, row in index["documents"].items() if row["source"]["file_id"] == FILE_ID
    )
    local_root = tmp_path / "netdisk"
    local_root.mkdir()
    (local_root / files[FILE_ID]["name"]).write_bytes(PDF_BYTES)
    submit_local_pdf_batch(root, local_root, now=datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI))
    monkeypatch.setattr(pdf_module, "_load_vision_module", lambda: pytest.fail("verified-cache reuse invoked OCR"))

    result = process_local_pdf_tick(
        root,
        local_root,
        now=datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI),
        page_extractor=lambda _raw: pytest.fail("verified-cache reuse reparsed pages"),
        classifier=lambda *_args, **_kwargs: {
            "status": "CLASSIFIED",
            "classification": {
                "document_type": "行业", "industry_tags": ["散热"], "companies": [],
                "document_date": None, "evidence_page_refs": [1], "classification_status": "CLASSIFIED",
            },
        },
    )

    assert result["status"] == "CLASSIFICATION_CLASSIFIED"
    assert result["linked_document_id"] == canonical_id
    assert result["admitted_count"] == 1
    local_index = NativeDataStore(root)._read(STATE_RELATIVE)["local_pdf"]
    stored = local_index["documents"][result["document_id"]]
    assert stored["source"]["source_file_sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert stored["source"]["linked_document_id"] == canonical_id


def test_upstream_13607_metadata_failure_persists_pause_and_blocks_next_metadata_call(tmp_path):
    from infrastructure.zsxq_pdf_local import upstream_pause_until

    root, _files = _fixture(tmp_path)
    stamp = datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI)
    first_calls = []

    def quota_failure(_cli, _file_id):
        first_calls.append("called")
        raise ZsxqPdfError("ZSXQ_DOWNLOAD_PAUSED_13607")

    process_pdf_batch(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        metadata_lookup=quota_failure,
        engine_info=ENGINE,
        page_counter=lambda _pdf: 1,
        page_renderer=lambda *_args: None,
        now=lambda: stamp,
    )
    assert first_calls == ["called"]
    assert upstream_pause_until(root) == datetime(2026, 10, 17, 0, 0, tzinfo=SHANGHAI)

    second_calls = []
    second = process_pdf_batch(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        metadata_lookup=lambda *_args: second_calls.append("called") or {},
        engine_info=ENGINE,
        page_counter=lambda _pdf: 1,
        page_renderer=lambda *_args: None,
        now=lambda: stamp,
    )
    assert second_calls == []
    assert second["status"] in {"CANNOT_CONFIRM", "PARTIAL", "FAILED"}

