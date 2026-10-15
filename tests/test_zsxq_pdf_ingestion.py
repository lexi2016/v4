import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from infrastructure.data_store import NativeDataStore
from infrastructure.zsxq_pdf_ingestion import (
    STATE_RELATIVE,
    ZsxqPdfError,
    enumerate_pdf_documents,
    process_pdf_batch,
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
):
    calls = counters if counters is not None else {"metadata": 0, "url": 0, "download": 0, "ocr": 0}

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

    now_value = datetime(2026, 10, 16, 1, 30, tzinfo=SHANGHAI)
    result = process_pdf_batch(
        data_root=root,
        trade_date=DATE,
        slot=SLOT,
        source_run_id=RUN_ID,
        file_id=target,
        limit=1,
        metadata_lookup=metadata,
        url_lookup=url,
        downloader=download,
        page_counter=lambda _pdf: page_count,
        page_renderer=render,
        ocr_page=ocr_page,
        engine_info=ENGINE,
        now=lambda: now_value,
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
    assert first["status"] == "READY"
    assert first["pending_total"] == 2
    assert first["processed_this_batch"][0]["full_page_coverage"] is True
    assert calls["ocr"] == 2
    assert calls["download"] == 1

    second, _ = _process(root, files, counters=calls)
    assert second["status"] == "READY"
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
    assert second["status"] == "READY"
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

