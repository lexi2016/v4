import hashlib
import json
import threading
import time
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
    STATE_RELATIVE,
    ZsxqPdfError,
    enumerate_pdf_documents,
    process_pdf_batch,
    process_pdf_continuation,
    process_next_pdf_task,
    pending_pdf_tasks,
    read_pdf_document_detail,
    read_pdf_ingestion_projection,
    verify_pdf_bytes,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
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

    monkeypatch.setattr(pdf_module, "_pdfinfo_page_count", lambda _path: 51)
    source = document["source"]
    source_meta = index["sources"][source["source_run_id"]]
    expected_processing_run_id = (
        f"pdfproc_{source['source_run_id']}_{source_meta['source_signature'][:12]}_{first['engine_identity'][:12]}"
    )
    assert source_meta.get("processing_run_id") == expected_processing_run_id
    verified_recovery = pdf_module._verified_page_limit_recovery(
        NativeDataStore(root),
        source,
        first_run,
        f"external_sources/zsxq_hourly/{expected_processing_run_id}",
    )
    assert verified_recovery is not None
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

    recovered, _ = _process(
        root,
        files,
        counters=calls,
        page_count=51,
        page_counter=lambda _path: 51,
        downloader=download,
        now_value=datetime(2026, 10, 16, 1, 36, tzinfo=SHANGHAI),
    )
    assert recovered["processed_this_batch"][0]["status"] == "PARTIAL"
    assert calls["url"] == calls["download"] == 1

    final_index = NativeDataStore(root)._read(STATE_RELATIVE)
    run = final_index["documents"][document_id]["engine_runs"][recovered["engine_identity"]]
    assert run["status"] == "PARTIAL"
    assert run["page_count"] == 51
    assert run["downloaded_at"] == first_run["downloaded_at"]
    recovery = run["page_limit_recovery"]
    assert recovery["prior_error_code"] == "PDF_PAGE_LIMIT_EXCEEDED"
    assert recovery["observed_page_count"] == 51
    assert recovery["pdf_sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert recovery["source_run_id"] == RUN_ID
    assert recovery["processing_run_id"] == first["processing_run_id"]
    assert recovery["verified_at"]


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
    ticks = [
        process_next_pdf_task(root, time_budget_seconds=90, now=lambda: now_value)
        for _ in range(3)
    ]

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

    resumed, _calls = _process(root, files)
    assert resumed["processed_this_batch"][0]["status"] == "READY"

