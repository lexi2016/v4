from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.research_lane_router import create_research_lane_router
from infrastructure.data_store import NativeDataStore
from infrastructure.zsxq_pdf_ingestion import (
    STATE_RELATIVE,
    ZsxqPdfError,
    _cli_json,
    read_pdf_document_detail,
    read_pdf_ingestion_projection,
)
from infrastructure.zsxq_pdf_local import (
    HOUR_LEDGER_RELATIVE,
    LocalPdfError,
    local_admissions_remaining,
    process_local_pdf_tick,
    record_13607_pause,
    require_upstream_available,
    reserve_local_admission,
    reserve_upstream_url_request,
    scan_local_pdfs,
    submit_local_pdf_batch,
    upstream_pause_until,
    validate_classification,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 18, 9, 30, tzinfo=SHANGHAI)
PDF_BYTES = b"%PDF-1.7\nlocal fixture\n%%EOF\n"


def _classification(page_count: int) -> dict:
    return {
        "document_type": "策略",
        "industry_tags": [],
        "companies": [],
        "document_date": "2026-10-16",
        "evidence_page_refs": [1] if page_count else [],
        "classification_status": "CLASSIFIED",
    }


def test_hourly_ledgers_persist_restart_safe_caps_and_13607_pause(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    hashes = [hashlib.sha256(f"pdf-{i}".encode()).hexdigest() for i in range(11)]

    for digest in hashes:
        assert reserve_local_admission(data_root, digest, now=NOW) == "RESERVED"
    assert local_admissions_remaining(data_root, now=NOW) is None
    # The persisted per-file idempotency record survives a fresh store instance.
    assert reserve_local_admission(data_root, hashes[0], now=NOW) == "ALREADY_ADMITTED"
    assert reserve_local_admission(data_root, hashes[10], now=NOW) == "ALREADY_ADMITTED"

    assert reserve_upstream_url_request(data_root, "url-1", now=NOW) == "RESERVED"
    assert reserve_upstream_url_request(data_root, "url-2", now=NOW) == "RESERVED"
    with pytest.raises(LocalPdfError, match="UPSTREAM_URL_HOURLY_LIMIT"):
        reserve_upstream_url_request(data_root, "url-3", now=NOW)

    blocked_until = record_13607_pause(data_root, now=NOW)
    assert blocked_until == "2026-10-19T00:00:00+08:00"
    assert upstream_pause_until(data_root) == datetime(2026, 10, 19, 0, 0, tzinfo=SHANGHAI)
    with pytest.raises(LocalPdfError, match="ZSXQ_UPSTREAM_PAUSED_13607"):
        require_upstream_available(data_root, now=NOW)
    with pytest.raises(LocalPdfError, match="ZSXQ_UPSTREAM_PAUSED_13607"):
        reserve_upstream_url_request(data_root, "url-after-pause", now=NOW)

    ledger = NativeDataStore(data_root)._read(HOUR_LEDGER_RELATIVE)
    assert len(ledger["hours"]["2026101809"]["local_admissions"]) == 11
    assert len(ledger["hours"]["2026101809"]["upstream_url_requests"]) == 2


def test_local_import_stays_available_during_pause_and_projects_without_topic_or_pit_claims(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    local_root = tmp_path / "local-pdfs"
    data_root.mkdir()
    local_root.mkdir()
    (local_root / "ambiguous-date.pdf").write_bytes(PDF_BYTES)
    store = NativeDataStore(data_root)
    store._write(STATE_RELATIVE, {
        "schema_version": "v4.zsxq_pdf_ingestion_index.v1",
        "sources": {}, "documents": {}, "ocr_cache": {},
        "recovery_consumed": {"frozen-old-document": {"status": "CLAIMED"}},
    })
    record_13607_pause(data_root, now=NOW)
    batch = submit_local_pdf_batch(data_root, local_root, now=NOW)
    assert batch["status"] == "BATCH_SUBMITTED"

    from infrastructure import zsxq_pdf_ingestion as ingestion
    monkeypatch.setattr(ingestion, "_load_vision_module", lambda: pytest.fail("local native-text fixture invoked OCR"))
    pages = [{"page_number": 1, "status": "NATIVE_TEXT", "method": "fixture", "text": "正文有印刷日期歧义"}]
    result = process_local_pdf_tick(
        data_root,
        local_root,
        announcement_queue_root=None,
        now=NOW,
        page_extractor=lambda _raw: [dict(row) for row in pages],
        classifier=lambda *_args, **_kwargs: {"status": "CLASSIFIED", "classification": _classification(1)},
    )

    assert result["status"] == "CLASSIFICATION_CLASSIFIED"
    assert result["admitted_count"] == 1
    assert result["production_allowed"] is False
    index = NativeDataStore(data_root)._read(STATE_RELATIVE)
    assert index["recovery_consumed"] == {"frozen-old-document": {"status": "CLAIMED"}}
    local_doc = index["local_pdf"]["documents"][result["document_id"]]
    assert local_doc["source"]["source_kind"] == "BAIDU_NETDISK_LOCAL"
    assert local_doc["source"]["document_date"] is None
    assert local_doc["source"]["linked_document_id"] is None

    projection = read_pdf_ingestion_projection(data_root, "20261018")
    item = next(row for row in projection["items"] if row["document_id"] == result["document_id"])
    assert item["local_source"] is True
    assert item["source"]["document_date"] is None
    assert "topic_id" not in item["source"]
    assert item["can_open_detail"] is True
    assert item["classification"]["classification"]["document_date"] == "2026-10-16"
    assert item["classification"]["classification"]["companies"] == []
    assert item["classification"]["classification"]["evidence_page_refs"] == [1]
    detail = read_pdf_document_detail(data_root, result["document_id"], "20261018")
    assert detail["research_date"] == "20261018"
    assert detail["classification"]["classification"]["document_date"] == "2026-10-16"
    assert detail["pages"][0]["text"] == "正文有印刷日期歧义"
    assert detail["processing"]["full_page_coverage"] is True
    assert detail["processing"]["full_text_coverage"] is True

    app = FastAPI()
    app.include_router(create_research_lane_router(data_root))
    client = TestClient(app)
    lane = client.get("/api/v3/research/lane?research_date=20261018")
    assert lane.status_code == 200
    api_item = next(
        row for row in lane.json()["ocr_ingestion"]["items"]
        if row["document_id"] == result["document_id"]
    )
    assert api_item["local_source"] is True
    api_detail = client.get(
        f"/api/v3/research/pdf-documents/{result['document_id']}?research_date=20261018"
    )
    assert api_detail.status_code == 200
    assert api_detail.json()["research_date"] == "20261018"


def test_native_extractor_uses_pinned_pdf_helper_and_fails_closed_for_invalid_fixture():
    from infrastructure.zsxq_pdf_local import extract_native_pdf_pages

    with pytest.raises(LocalPdfError):
        extract_native_pdf_pages(b"%PDF-1.7\nnot a valid PDF")


def test_classification_schema_rejects_date_without_page_evidence():
    value = _classification(1)
    value["document_date"] = "2026-10-16"
    value["evidence_page_refs"] = []
    with pytest.raises(LocalPdfError, match="PDF_CLASSIFICATION_DATE_WITHOUT_PAGE_EVIDENCE"):
        validate_classification(value, page_count=1)


def test_classification_timeout_terminates_isolated_worker(monkeypatch, tmp_path):
    from infrastructure import zsxq_pdf_local as local_pdf

    class ParentPipe:
        def poll(self, _timeout):
            return False

        def close(self):
            pass

    class ChildPipe:
        def close(self):
            pass

    class Child:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.daemon = kwargs.get("daemon")
            self.alive = False
            self.terminated = False
            self.pid = 1

        def start(self):
            self.alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            pass

        def terminate(self):
            self.terminated = True
            self.alive = False

        def kill(self):
            self.alive = False

    class Context:
        def Pipe(self, duplex=False):
            assert duplex is False
            return ParentPipe(), ChildPipe()

        def Process(self, **kwargs):
            children.append(Child(**kwargs))
            return children[-1]

    children = []
    monkeypatch.setattr(local_pdf.multiprocessing, "get_context", lambda _name: Context())
    ticks = iter([0.0, 121.0])
    monkeypatch.setattr(local_pdf.time, "monotonic", lambda: next(ticks))

    queue_root = tmp_path / "announcement_flash" / "queue"
    queue_root.mkdir(parents=True)
    monkeypatch.setattr(local_pdf, "PINNED_ANNOUNCEMENT_QUEUE_ROOT", queue_root)
    result = local_pdf.classify_with_existing_model(
        tmp_path,
        announcement_queue_root=queue_root,
        import_date="20261018",
        document_id="a" * 64,
        pdf_sha256="b" * 64,
        pages=[{"page_number": 1, "text": "body"}],
    )

    assert result == {"status": "FAILED", "reason_code": "LOCAL_MODEL_TIMEOUT"}
    assert children[0].terminated is True
    assert children[0].daemon is False
    assert children[0].kwargs["args"][0] == str(queue_root)


def test_classifier_defers_without_explicit_shared_announcement_queue(tmp_path, monkeypatch):
    from infrastructure import zsxq_pdf_local as local_pdf

    monkeypatch.setattr(local_pdf, "_classification_worker", lambda *_args: pytest.fail("missing lock root must not spawn a model worker"))
    result = local_pdf.classify_with_existing_model(
        tmp_path,
        announcement_queue_root=None,
        import_date="20261018",
        document_id="a" * 64,
        pdf_sha256="b" * 64,
        pages=[{"page_number": 1, "text": "body"}],
    )
    assert result == {"status": "DEFERRED", "reason_code": "LOCAL_ANNOUNCEMENT_QUEUE_ROOT_UNCONFIGURED"}


def test_classifier_rejects_unpinned_queue_root_before_worker_spawn(tmp_path, monkeypatch):
    from infrastructure import zsxq_pdf_local as local_pdf

    queue_root = tmp_path / "announcement_flash" / "queue"
    queue_root.mkdir(parents=True)
    monkeypatch.setattr(local_pdf, "PINNED_ANNOUNCEMENT_QUEUE_ROOT", tmp_path / "other" / "announcement_flash" / "queue")
    monkeypatch.setattr(local_pdf, "_classification_worker", lambda *_args: pytest.fail("wrong lock root must not spawn model"))
    result = local_pdf.classify_with_existing_model(
        tmp_path,
        announcement_queue_root=queue_root,
        import_date="20261018",
        document_id="a" * 64,
        pdf_sha256="b" * 64,
        pages=[{"page_number": 1, "text": "body"}],
    )
    assert result == {"status": "DEFERRED", "reason_code": "LOCAL_ANNOUNCEMENT_QUEUE_ROOT_NOT_PINNED"}


def test_local_batch_submits_all_hashes_once_then_canary_gates_continuation(tmp_path):
    data_root = tmp_path / "data"
    local_root = tmp_path / "local"
    data_root.mkdir()
    local_root.mkdir()
    first = b"%PDF-1.7\nfirst\n%%EOF\n"
    second = b"%PDF-1.7\nsecond\n%%EOF\n"
    (local_root / "a.pdf").write_bytes(first)
    (local_root / "b.pdf").write_bytes(second)
    first_sha = hashlib.sha256(first).hexdigest()
    second_sha = hashlib.sha256(second).hexdigest()

    submitted = submit_local_pdf_batch(data_root, local_root, canary_sha256=second_sha, now=NOW)
    assert submitted["status"] == "BATCH_SUBMITTED"
    assert submitted["file_count"] == 2
    repeated = submit_local_pdf_batch(data_root, local_root, canary_sha256=second_sha, now=NOW)
    assert repeated["status"] == "ALREADY_SUBMITTED"

    calls = []
    def classifier(_data_root, **kwargs):
        calls.append(kwargs["pdf_sha256"])
        return {"status": "CLASSIFIED", "classification": _classification(1)}

    page = [{"page_number": 1, "status": "NATIVE_TEXT", "method": "fixture", "text": "evidence"}]
    canary = process_local_pdf_tick(data_root, local_root, now=NOW, page_extractor=lambda _raw: [dict(page[0])], classifier=classifier)
    assert canary["pdf_sha256"] == second_sha
    assert calls == [second_sha]
    local_state = NativeDataStore(data_root)._read(STATE_RELATIVE)["local_pdf"]
    stored_batch = local_state["batches"][submitted["batch_id"]]
    assert stored_batch["canary_status"] == "PASSED"
    next_item = process_local_pdf_tick(data_root, local_root, now=NOW, page_extractor=lambda _raw: [dict(page[0])], classifier=classifier)
    assert next_item["pdf_sha256"] == first_sha
    assert len(calls) == 2
    assert len(local_state["batches"][submitted["batch_id"]]["files"]) == 2


def test_local_batch_terminalizes_same_sha_aliases_after_one_classification(tmp_path):
    data_root = tmp_path / "data"
    local_root = tmp_path / "local"
    data_root.mkdir()
    alias_dir = local_root / "券商" / "个股资料"
    alias_dir.mkdir(parents=True)
    first = local_root / "report.pdf"
    alias = alias_dir / "report-copy.pdf"
    first.write_bytes(PDF_BYTES)
    alias.write_bytes(PDF_BYTES)
    digest = hashlib.sha256(PDF_BYTES).hexdigest()

    submitted = submit_local_pdf_batch(data_root, local_root, canary_sha256=digest, now=NOW)
    assert submitted["file_count"] == 2
    calls = []

    def classifier(_data_root, **kwargs):
        calls.append(kwargs["pdf_sha256"])
        return {"status": "CLASSIFIED", "classification": _classification(1)}

    page = {"page_number": 1, "status": "NATIVE_TEXT", "method": "fixture", "text": "evidence"}
    result = process_local_pdf_tick(
        data_root,
        local_root,
        now=NOW,
        page_extractor=lambda _raw: [dict(page)],
        classifier=classifier,
    )
    assert result["pdf_sha256"] == digest
    assert calls == [digest]

    state = NativeDataStore(data_root)._read(STATE_RELATIVE)["local_pdf"]
    batch = state["batches"][submitted["batch_id"]]
    rows = {row["relative_path"]: row for row in batch["files"]}
    assert rows["report.pdf"]["status"] == "IMPORTED"
    assert rows["券商/个股资料/report-copy.pdf"]["status"] == "ALREADY_IMPORTED"
    assert batch["canary_status"] == "PASSED"
    assert batch["status"] == "COMPLETE"

    no_op = process_local_pdf_tick(data_root, local_root, now=NOW, classifier=classifier)
    assert no_op["status"] == "LOCAL_BATCH_COMPLETE"
    assert calls == [digest]


def test_batch_manifest_detects_same_size_same_mtime_replacement(tmp_path):
    data_root = tmp_path / "data"
    local_root = tmp_path / "local"
    data_root.mkdir()
    local_root.mkdir()
    target = local_root / "same.pdf"
    target.write_bytes(b"%PDF-1.7\nold\n%%EOF\n")
    before = target.stat()
    old_batch = submit_local_pdf_batch(data_root, local_root, now=NOW)
    target.write_bytes(b"%PDF-1.7\nnew\n%%EOF\n")
    import os
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = target.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns
    rescanned = scan_local_pdfs(local_root)
    assert rescanned[0]["pdf_sha256"] != old_batch["canary_sha256"]


def test_ocr_page_failure_never_calls_classifier_on_incomplete_text(tmp_path, monkeypatch):
    from infrastructure import zsxq_pdf_local as local_pdf

    data_root = tmp_path / "data"
    local_root = tmp_path / "local"
    data_root.mkdir()
    local_root.mkdir()
    (local_root / "scan.pdf").write_bytes(PDF_BYTES)
    submit_local_pdf_batch(data_root, local_root, now=NOW)
    empty_page = [{"page_number": 1, "status": "NATIVE_TEXT_EMPTY", "method": "fixture", "text": ""}]
    monkeypatch.setattr(local_pdf, "_ocr_missing_pages", lambda _path, pages, max_pages=2: pages)
    first = process_local_pdf_tick(
        data_root, local_root, now=NOW,
        page_extractor=lambda _raw: [dict(empty_page[0])],
        classifier=lambda *_args, **_kwargs: pytest.fail("incomplete text must not be classified"),
    )
    assert first["classification_status"] == "DEFERRED"

    monkeypatch.setattr(local_pdf, "_ocr_missing_pages", lambda _path, pages, max_pages=2: [dict(pages[0], status="OCR_ERROR", error_code="fixture")])
    second = process_local_pdf_tick(
        data_root, local_root, now=NOW,
        classifier=lambda *_args, **_kwargs: pytest.fail("OCR failure must not be classified"),
    )
    assert second["status"] == "OCR_FAILED"
    state = NativeDataStore(data_root)._read(STATE_RELATIVE)["local_pdf"]
    doc = next(iter(state["documents"].values()))
    assert doc["classification_status"] == "FAILED"
    batch = state["batches"][state["active_batch_id"]]
    assert batch["canary_status"] == "BLOCKED"


def test_single_batch_admits_all_369_local_pdfs_without_hourly_cap(tmp_path):
    data_root = tmp_path / "data"
    local_root = tmp_path / "local"
    data_root.mkdir()
    local_root.mkdir()
    for index in range(369):
        if index < 172:
            target_dir = local_root
        elif index < 298:
            target_dir = local_root / "券商"
        else:
            target_dir = local_root / "券商" / "个股资料"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / f"{index:03d}.pdf").write_bytes(b"%PDF-1.7\n" + str(index).encode() + b"\n%%EOF\n")
    result = submit_local_pdf_batch(data_root, local_root, now=NOW)
    assert result["status"] == "BATCH_SUBMITTED"
    assert result["file_count"] == 369
    state = NativeDataStore(data_root)._read(STATE_RELATIVE)["local_pdf"]
    batch = state["batches"][result["batch_id"]]
    assert sum(row["status"] == "PENDING" for row in batch["files"]) == 369
    assert sum("/" not in row["relative_path"] for row in batch["files"]) == 172
    assert sum("/" in row["relative_path"] for row in batch["files"]) == 197
    assert not (data_root / HOUR_LEDGER_RELATIVE).exists()


def test_local_pdf_scan_recurses_and_rejects_symlink_escape(tmp_path):
    from infrastructure.zsxq_pdf_local import _resolve_local_pdf_path

    local_root = tmp_path / "local"
    outside_root = tmp_path / "outside"
    nested = local_root / "券商" / "个股资料"
    nested.mkdir(parents=True)
    outside_root.mkdir()
    (local_root / "direct.pdf").write_bytes(PDF_BYTES)
    (nested / "nested.pdf").write_bytes(b"%PDF-1.7\nnested\n%%EOF\n")
    (outside_root / "outside.pdf").write_bytes(b"%PDF-1.7\noutside\n%%EOF\n")
    try:
        (local_root / "escape-link").symlink_to(outside_root, target_is_directory=True)
        (local_root / "escape.pdf").symlink_to(outside_root / "outside.pdf")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable in this test environment")

    rows = scan_local_pdfs(local_root)
    assert [row["relative_path"] for row in rows] == ["direct.pdf", "券商/个股资料/nested.pdf"]
    assert all(row["status"] == "CANDIDATE" for row in rows)
    assert scan_local_pdfs(local_root) == rows
    with pytest.raises(LocalPdfError, match="LOCAL_PDF_RELATIVE_PATH_INVALID"):
        _resolve_local_pdf_path(local_root, "../outside/outside.pdf")
    with pytest.raises(LocalPdfError, match="LOCAL_PDF_PATH_SYMLINK"):
        _resolve_local_pdf_path(local_root, "escape.pdf")


def test_existing_queue_cli_submits_batch_without_processing_or_model_call(tmp_path, capsys, monkeypatch):
    from ops import run_zsxq_hourly_delta as runner

    data_root = tmp_path / "data"
    local_root = tmp_path / "local"
    data_root.mkdir()
    local_root.mkdir()
    pdf_path = local_root / "one.pdf"
    pdf_path.write_bytes(PDF_BYTES)
    before = pdf_path.read_bytes()
    monkeypatch.setattr(runner, "process_next_pdf_task", lambda **_kwargs: pytest.fail("batch submission must not drain"))
    rc = runner.main(["--data-root", str(data_root), "--pdf-local-batch", "--pdf-local-root", str(local_root)])
    output = json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert output["status"] == "BATCH_SUBMITTED"
    assert pdf_path.read_bytes() == before


def test_queue_cli_passes_only_explicit_shared_announcement_queue_root(tmp_path, capsys, monkeypatch):
    from ops import run_zsxq_hourly_delta as runner

    data_root = tmp_path / "data"
    local_root = tmp_path / "local"
    queue_root = tmp_path / "announcement_flash" / "queue"
    data_root.mkdir()
    local_root.mkdir()
    queue_root.mkdir(parents=True)
    captured = {}
    def process(**kwargs):
        captured.update(kwargs)
        return {"status": "NO_RETRYABLE_TASKS", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    monkeypatch.setattr(runner, "process_next_pdf_task", process)
    rc = runner.main([
        "--data-root", str(data_root), "--pdf-queue-tick", "--pdf-local-root", str(local_root),
        "--pdf-classification-queue-root", str(queue_root),
    ])
    json.loads(capsys.readouterr().out.strip())
    assert rc == 0
    assert captured["announcement_queue_root"] == queue_root


def test_cli_business_layer_13607_is_not_treated_as_transport_success():
    class Completed:
        returncode = 0
        stdout = json.dumps({"success": True, "body": {"succeeded": False, "code": "13607"}})

    with pytest.raises(ZsxqPdfError, match="ZSXQ_DOWNLOAD_PAUSED_13607"):
        _cli_json(Path("zsxq"), ["api", "raw"], process_runner=lambda *_args, **_kwargs: Completed())
