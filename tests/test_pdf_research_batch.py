from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
from types import SimpleNamespace

import pytest

from infrastructure import local_document_model as local_model
from infrastructure import pdf_research
from ops import run_pdf_research_batch as batch


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _page(number: int, total: int, text: str) -> pdf_research.PageText:
    return pdf_research.PageText(
        page_number=number,
        page_total=total,
        text=text,
        status="NATIVE_TEXT",
        text_sha256=_sha(text),
        extraction_method="test-fixture",
    )


def test_document_chunking_keeps_exact_page_text_and_budgets() -> None:
    pages = [
        _page(1, 3, "宁德时代（300750.SZ）\n" + "甲" * 8_400),
        _page(2, 3, "关键变化（第2页）" + "B" * 740),
        _page(3, 3, "风险及未知（第3页）" + "丙" * 8_250),
    ]

    chunks = batch._build_document_chunks("a" * 64, pages)

    assert len(chunks) >= 3
    assert pdf_research.verify_chunk_reconstruction(pages, chunks)
    assert [page.page_number for page in pages] == [1, 2, 3]
    rebuilt = {page.page_number: [] for page in pages}
    for chunk in chunks:
        assert sum(len(unit.text) for unit in chunk.units) <= batch.MAX_SOURCE_CHARACTERS
        messages = batch._document_messages({"document_id": "a" * 64}, chunk, partial_source=False)
        assert len(batch._request_envelope(messages)) <= batch.MAX_REQUEST_ENVELOPE_BYTES
        for unit in chunk.units:
            rebuilt[unit.page_number].append((unit.page_offset_start, unit.text))
    for page in pages:
        assert "".join(text for _offset, text in sorted(rebuilt[page.page_number])) == page.text
    assert "宁德时代（300750.SZ）" in "".join(unit.text for chunk in chunks for unit in chunk.units)


def test_synthesis_packing_is_bounded_and_preserves_text_order() -> None:
    reports = [
        {"report_id": f"part-{i}", "text": f"第{i}页（作者观点）" + chr(64 + i) * 2_450}
        for i in range(1, 7)
    ]

    groups = batch._pack_synthesis_groups("b" * 64, reports, 1)

    flattened = [item for group in groups for item in group]
    assert "".join(item["text"] for item in flattened) == "".join(item["text"] for item in batch._split_report_items(reports))
    assert any(len(group) > 1 for group in groups)
    for group in groups:
        assert sum(len(item["text"]) for item in group) <= batch.MAX_SOURCE_CHARACTERS
        assert len(batch._request_envelope(batch._synthesis_messages("b" * 64, group, 1))) <= batch.MAX_REQUEST_ENVELOPE_BYTES
    assert all(len(item["text"]) <= batch.MAX_SYNTHESIS_PART_CHARACTERS for item in flattened)


def _write_queue_state(path: Path, jobs: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "v4.announcement-engine-queue/v1", "jobs": jobs, "events": []}),
        encoding="utf-8",
    )


def _job(model: str, status: str) -> dict[str, object]:
    return {"queue_id": "announcement_flash", "model_id": model, "status": status, "identity": {"role": "announcement_reader"}}


def test_frozen_manifest_sha_allows_absent_status_and_rejects_nonfrozen(tmp_path: Path, monkeypatch) -> None:
    document = {
        "document_id": "a" * 64,
        "pdf_sha256": "a" * 64,
        "pdf_bytes": 123,
        "local_pdf_path": "/tmp/sample.pdf",
        "source_paths": [],
        "cache_candidates": [],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "v4.pdf_research_simple_batch.manifest.v1",
                "documents": [document],
            }
        ),
        encoding="utf-8",
    )
    expected_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    monkeypatch.setattr(batch, "EXPECTED_BATCH_MANIFEST_SHA256", expected_hash)

    manifest, digest, documents = batch.load_manifest(manifest_path)

    assert "status" not in manifest
    assert digest == expected_hash
    assert documents == [document]

    manifest["status"] = "BUILDING"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(batch, "EXPECTED_BATCH_MANIFEST_SHA256", hashlib.sha256(manifest_path.read_bytes()).hexdigest())
    with pytest.raises(batch.BatchError, match="BATCH_MANIFEST_CONTRACT_INVALID"):
        batch.load_manifest(manifest_path)

    monkeypatch.setattr(batch, "EXPECTED_BATCH_MANIFEST_SHA256", "f" * 64)
    with pytest.raises(batch.BatchError, match="BATCH_MANIFEST_SHA_MISMATCH"):
        batch.load_manifest(manifest_path)


def test_s18_acceptance_receipt_requires_its_frozen_sha(tmp_path: Path, monkeypatch) -> None:
    report_path = tmp_path / "accepted-report.md"
    report = b"accepted report"
    report_path.write_bytes(report)
    receipt = {
        "schema": "v4.pdf_simple_batch.user_sample_acceptance.v1",
        "status": "USER_ACCEPTED",
        "batch_authorized": True,
        "source_pdf_sha256": "d" * 64,
        "model_report_path": str(report_path),
        "model_report_sha256": hashlib.sha256(report).hexdigest(),
        "independent_content_verdict_sha256": "e" * 64,
    }
    receipt_path = tmp_path / "acceptance.json"
    receipt_raw = json.dumps(receipt).encode()
    receipt_path.write_bytes(receipt_raw)
    monkeypatch.setattr(batch, "USER_ACCEPTANCE_PATH", receipt_path)
    monkeypatch.setattr(batch, "USER_ACCEPTANCE_SHA256", hashlib.sha256(receipt_raw).hexdigest())
    monkeypatch.setattr(batch, "S18_PDF_SHA256", "d" * 64)
    monkeypatch.setattr(batch, "S18_REPORT_PATH", report_path)
    monkeypatch.setattr(batch, "S18_REPORT_SHA256", hashlib.sha256(report).hexdigest())

    observed, observed_report = batch._read_s18_acceptance()
    assert observed["status"] == "USER_ACCEPTED"
    assert observed_report == report

    receipt_path.write_bytes(receipt_raw + b" ")
    with pytest.raises(batch.BatchError, match="S18_USER_ACCEPTANCE_SHA_MISMATCH"):
        batch._read_s18_acceptance()


def test_announcement_pending_is_advisory_but_active_work_defers(tmp_path: Path) -> None:
    queue_state = tmp_path / "queue-state.json"
    pending = {str(i): _job(local_model.MODEL_ID, "PENDING") for i in range(309)}
    pending["other"] = _job("other-model", "RUNNING")
    _write_queue_state(queue_state, pending)

    snapshot = batch._priority_snapshot(queue_state)

    assert snapshot == {"status": "ALLOW", "same_model_pending_count": 309, "pending_is_advisory": True}
    pending["active"] = _job(local_model.MODEL_ID, "RUNNING")
    _write_queue_state(queue_state, pending)
    assert batch._priority_snapshot(queue_state) == {
        "status": "DEFER",
        "reason": "SAME_MODEL_ANNOUNCEMENT_ACTIVE",
        "same_model_pending_count": 309,
    }


def test_announcement_uncertain_queue_defers(tmp_path: Path) -> None:
    missing = batch._priority_snapshot(tmp_path / "missing.json")
    assert missing["status"] == "DEFER"
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{}", encoding="utf-8")
    assert batch._priority_snapshot(malformed)["reason"] == "ANNOUNCEMENT_QUEUE_IDENTITY_UNCONFIRMED"
    uncertain_job = tmp_path / "uncertain-job.json"
    _write_queue_state(uncertain_job, {"same-model": {"model_id": local_model.MODEL_ID, "status": "PENDING"}})
    assert batch._priority_snapshot(uncertain_job)["reason"] == "ANNOUNCEMENT_JOB_IDENTITY_UNCONFIRMED"


@pytest.mark.parametrize("model_id", [None, "", "   ", 42])
@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "CLAIMED"])
def test_active_announcement_with_invalid_model_identity_defers(
    tmp_path: Path,
    model_id: object,
    status: str,
) -> None:
    path = tmp_path / "queue-state.json"
    _write_queue_state(path, {"uncertain": {"model_id": model_id, "status": status}})

    snapshot = batch._priority_snapshot(path)

    assert snapshot == {"status": "DEFER", "reason": "ANNOUNCEMENT_JOB_IDENTITY_UNCONFIRMED"}


def test_priority_skips_only_explicit_other_model_and_terminal_history(tmp_path: Path) -> None:
    path = tmp_path / "queue-state.json"
    _write_queue_state(
        path,
        {
            "other-model-pending": _job("other-model", "PENDING"),
            "terminal-unknown": {"status": "SUCCEEDED"},
            "terminal-failure-unknown": {"status": "FAILED"},
        },
    )

    assert batch._priority_snapshot(path) == {
        "status": "ALLOW",
        "same_model_pending_count": 0,
        "pending_is_advisory": True,
    }


def test_batch_singleton_lock_rejects_a_second_runner(tmp_path: Path) -> None:
    with batch._batch_singleton_lock(tmp_path):
        with pytest.raises(batch.BatchError, match="BATCH_ALREADY_RUNNING"):
            with batch._batch_singleton_lock(tmp_path):
                pytest.fail("a second batch runner acquired the singleton lock")


class _FakeQueue:
    def __init__(self, *, lock_busy: bool = False):
        self.lock_busy = lock_busy
        self.run_called = False

    def enqueue(self, payload):
        return {"status": "PENDING", "idempotency_key": "f" * 64, "payload": dict(payload)}

    def run_next(self, executor, validator, *, wait_for_model_slot, idempotency_keys):
        self.run_called = True
        assert wait_for_model_slot is False
        assert idempotency_keys == ["f" * 64]
        if self.lock_busy:
            class ModelSlotBusy(RuntimeError):
                pass

            raise ModelSlotBusy()
        job = SimpleNamespace(model_id=local_model.MODEL_ID, payload={"model_binding": self.payload_binding})
        raw = executor(job)
        accepted = validator(job, json.loads(raw))
        self.accepted = accepted
        return {
            "status": "SUCCEEDED",
            "attempt_count": 1,
            "idempotency_key": "f" * 64,
            "raw_path": None,
            "validated_path": None,
        }


def _request_args(tmp_path: Path):
    evidence_root = tmp_path / "evidence"
    binding = {
        "configuration_sha256": "c" * 64,
        "evidence_root": str(evidence_root),
        "request_schema_sha256": "a" * 64,
    }
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "read source page 1"}]
    payload = batch._request_payload(
        {"document_id": "d" * 64, "pdf_sha256": "d" * 64},
        stage="simple_batch_document_chunk_v1",
        article_id="doc:chunk:1",
        messages=messages,
        binding=binding,
        envelope=batch._request_envelope(messages),
        source_characters=16,
        source_text_sha256="e" * 64,
    )
    return binding, messages, payload


def test_each_actual_request_uses_nonblocking_shared_lock_and_yields(monkeypatch, tmp_path: Path) -> None:
    binding, messages, payload = _request_args(tmp_path)
    queue = _FakeQueue()
    queue.payload_binding = binding
    sleep_calls: list[float] = []
    monkeypatch.setattr(batch.pdf_research, "_read_validated_result", lambda *_args: {"analysis_markdown": "报告（第1页）"})

    outcome = batch._perform_request(
        queue,
        payload,
        messages,
        binding=binding,
        identity={"status": "MATCH", "expected_model_id": local_model.MODEL_ID},
        identity_reader=lambda: pytest.fail("identity was already checked"),
        priority_reader=lambda: {"status": "ALLOW", "same_model_pending_count": 309},
        request_fn=lambda **_kwargs: json.dumps({"analysis_markdown": "报告（第1页）"}, ensure_ascii=False),
        sleep_fn=sleep_calls.append,
    )

    assert outcome["status"] == "SUCCEEDED"
    assert outcome["attempted"] is True
    assert sleep_calls == [batch.ANNOUNCEMENT_IDLE_GAP_SECONDS]
    assert queue.run_called is True


def test_priority_defer_and_shared_lock_busy_make_no_request(monkeypatch, tmp_path: Path) -> None:
    binding, messages, payload = _request_args(tmp_path)
    queue = _FakeQueue()
    queue.payload_binding = binding
    sleep_calls: list[float] = []
    deferred = batch._perform_request(
        queue,
        payload,
        messages,
        binding=binding,
        identity={"status": "MATCH", "expected_model_id": local_model.MODEL_ID},
        identity_reader=lambda: {"status": "MATCH", "expected_model_id": local_model.MODEL_ID},
        priority_reader=lambda: {"status": "DEFER", "reason": "SAME_MODEL_ANNOUNCEMENT_ACTIVE"},
        request_fn=lambda **_kwargs: pytest.fail("deferred request must not call model"),
        sleep_fn=sleep_calls.append,
    )
    assert deferred["status"] == "DEFERRED_ANNOUNCEMENT_PRIORITY"
    assert queue.run_called is False
    assert sleep_calls == []

    busy_queue = _FakeQueue(lock_busy=True)
    busy_queue.payload_binding = binding
    busy = batch._perform_request(
        busy_queue,
        payload,
        messages,
        binding=binding,
        identity={"status": "MATCH", "expected_model_id": local_model.MODEL_ID},
        identity_reader=lambda: {"status": "MATCH", "expected_model_id": local_model.MODEL_ID},
        priority_reader=lambda: {"status": "ALLOW", "same_model_pending_count": 309},
        request_fn=lambda **_kwargs: pytest.fail("lock-busy request must not call model"),
        sleep_fn=sleep_calls.append,
    )
    assert busy["status"] == "DEFERRED_MODEL_LOCK_BUSY"
    assert busy_queue.run_called is True
    assert sleep_calls == []


def test_completed_document_receipt_is_reused_without_overwrite(tmp_path: Path) -> None:
    doc_sha = "a" * 64
    manifest_sha = "b" * 64
    doc_root = tmp_path / "documents" / doc_sha
    doc_root.mkdir(parents=True)
    receipt = {
        "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
        "status": "MODEL_GENERATED_SOURCE_COMPLETE",
        "manifest_sha256": manifest_sha,
        "document_id": doc_sha,
        "pdf_sha256": doc_sha,
    }
    receipt_path = doc_root / "receipt.json"
    original = json.dumps(receipt).encode()
    receipt_path.write_bytes(original)

    observed = batch._run_document(
        {"document_id": doc_sha, "pdf_sha256": doc_sha},
        manifest_sha=manifest_sha,
        state_root=tmp_path,
        queue=object(),
        binding={},
        identity={"status": "NOT_CHECKED"},
        priority_reader=lambda: pytest.fail("completed document should not resume"),
        identity_reader=lambda: pytest.fail("completed document should not resume"),
        identity_state={"status": "NOT_CHECKED"},
        request_fn=lambda **_kwargs: pytest.fail("completed document should not call model"),
        sleep_fn=lambda _seconds: pytest.fail("completed document should not sleep"),
    )

    assert observed == receipt
    assert receipt_path.read_bytes() == original


def test_batch_isolates_one_document_failure_and_keeps_processing(tmp_path: Path, monkeypatch) -> None:
    documents = [
        {"document_id": "1" * 64, "pdf_sha256": "1" * 64},
        {"document_id": "2" * 64, "pdf_sha256": "2" * 64},
    ]
    manifest = {"schema": "v4.pdf_research_simple_batch.manifest.v1", "status": "FROZEN", "documents": documents}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    monkeypatch.setattr(batch, "load_manifest", lambda _path: (manifest, manifest_sha, documents))
    monkeypatch.setattr(batch.local_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(
        batch.local_model,
        "build_request_material",
        lambda _schema: {
            "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
            "model_settings_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
            "runtime_python": str(batch.local_model.RUNTIME_PYTHON),
            "evidence_root": str(tmp_path / "state" / "evidence"),
            "configuration_sha256": "c" * 64,
        },
    )
    fake_queue = SimpleNamespace(state_root=tmp_path / "state" / "queue")
    monkeypatch.setattr(batch, "_run_document", lambda doc, **_kwargs: (_ for _ in ()).throw(batch.BatchError("FIRST_DOC_FAILED")) if doc["document_id"].startswith("1") else {"status": "MODEL_GENERATED_SOURCE_COMPLETE"})

    result = batch.run_batch(
        manifest_path,
        state_root=tmp_path / "state",
        queue_factory=lambda root: (fake_queue, Path("/shared/model.lock")),
        identity_fn=lambda: pytest.fail("no request was attempted in this isolation test"),
        priority_reader=lambda: pytest.fail("no request was attempted in this isolation test"),
        sleep_fn=lambda _seconds: None,
    )

    assert [item["status"] for item in result["documents"]] == [
        "FAILED_DOCUMENT_ISOLATED",
        "MODEL_GENERATED_SOURCE_COMPLETE",
    ]
    first_receipt = json.loads((tmp_path / "state/documents" / ("1" * 64) / "receipt.json").read_text())
    assert first_receipt["failure_code"] == "FIRST_DOC_FAILED"
    assert result["research_only"] is True


class _ResumableFakeQueue:
    def __init__(self, state_root: Path):
        self.state_root = state_root
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.pending: dict[str, dict[str, object]] = {}
        self.results: dict[str, dict[str, str]] = {}
        self.items: dict[str, dict[str, object]] = {}
        self.requested_articles: list[str] = []

    def enqueue(self, payload: dict[str, object]) -> dict[str, object]:
        article_id = str(payload["article_id"])
        key = _sha(article_id)
        if key in self.results:
            return dict(self.items[key])
        item = {"status": "PENDING", "idempotency_key": key, "payload": dict(payload)}
        self.pending[key] = dict(payload)
        self.items[key] = item
        return item

    def run_next(self, executor, validator, *, wait_for_model_slot: bool, idempotency_keys):
        assert wait_for_model_slot is False
        key = idempotency_keys[0]
        payload = self.pending[key]
        job = SimpleNamespace(model_id=local_model.MODEL_ID, payload=payload)
        raw = executor(job)
        accepted = validator(job, json.loads(raw))
        raw_path = self.state_root / f"{key}.raw.json"
        validated_path = self.state_root / f"{key}.validated.json"
        raw_path.write_text(raw, encoding="utf-8")
        validated_path.write_text(json.dumps(accepted, ensure_ascii=False), encoding="utf-8")
        self.requested_articles.append(str(payload["article_id"]))
        self.results[key] = accepted
        item = {
            "status": "SUCCEEDED",
            "attempt_count": 1,
            "idempotency_key": key,
            "raw_path": str(raw_path),
            "validated_path": str(validated_path),
        }
        self.items[key] = item
        return item


@pytest.mark.parametrize(
    "signal_stage",
    ["simple_batch_document_chunk_v1", "simple_batch_synthesis_v1"],
)
def test_sigterm_finishes_inflight_chunk_or_synthesis_then_resumes_only_unfinished_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signal_stage: str,
) -> None:
    pdf_sha = "a" * 64
    manifest_sha = "b" * 64
    document = {"document_id": pdf_sha, "pdf_sha256": pdf_sha, "title": "signal fixture"}
    documents = [document]
    manifest = {"schema": "v4.pdf_research_simple_batch.manifest.v1", "status": "FROZEN", "documents": documents}
    page = _page(1, 1, "公司情况：" + "甲" * 16_000)
    assert len(batch._build_document_chunks(pdf_sha, [page])) > 1
    state_root = tmp_path / "state"
    queue = _ResumableFakeQueue(state_root / "queue")
    source = {
        "page_count": 1,
        "page_extraction_status": "COMPLETE",
        "all_pages_nonempty": True,
        "selected_pages_complete": True,
        "source_page_text_sha256": _sha(page.text),
    }

    monkeypatch.setattr(batch, "load_manifest", lambda _path: (manifest, manifest_sha, documents))
    monkeypatch.setattr(batch.local_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(batch, "_load_pages", lambda _document: ([page], source))
    monkeypatch.setattr(batch, "_queue_read_result", lambda _queue, item: queue.results.get(str(item["idempotency_key"])))
    monkeypatch.setattr(
        batch.local_model,
        "build_request_material",
        lambda _schema: {
            "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
            "model_settings_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
            "runtime_python": str(batch.local_model.RUNTIME_PYTHON),
            "evidence_root": str(state_root / "evidence"),
            "configuration_sha256": "c" * 64,
            "request_schema_sha256": "d" * 64,
        },
    )
    prior_handler = signal.getsignal(signal.SIGTERM)
    signal_sent = False

    def fake_request(*, job, **_kwargs) -> str:
        nonlocal signal_sent
        if not signal_sent and job.payload["stage"] == signal_stage:
            signal_sent = True
            os.kill(os.getpid(), signal.SIGTERM)
        return json.dumps({"analysis_markdown": f"已分析 {job.payload['article_id']}（原文第1页）"}, ensure_ascii=False)

    run_kwargs = {
        "manifest_path": tmp_path / "manifest.json",
        "state_root": state_root,
        "queue_factory": lambda _root: (queue, Path("/shared/model.lock")),
        "identity_fn": lambda: {"status": "MATCH", "expected_model_id": local_model.MODEL_ID},
        "priority_reader": lambda: {"status": "ALLOW", "same_model_pending_count": 0},
        "request_fn": fake_request,
        "sleep_fn": lambda _seconds: None,
    }

    first = batch.run_batch(**run_kwargs)

    assert first["status"] == "STOPPED_GRACEFULLY"
    assert signal_sent is True
    first_request_articles = list(queue.requested_articles)
    assert first_request_articles
    if signal_stage == "simple_batch_document_chunk_v1":
        assert len(first_request_articles) == 1
    else:
        assert first_request_articles[-1].startswith(f"{pdf_sha}:synthesis:")
    doc_root = state_root / "documents" / pdf_sha
    first_receipt = json.loads((doc_root / "receipt.json").read_text(encoding="utf-8"))
    assert first_receipt["status"] == "STOPPED_GRACEFULLY"
    assert first_receipt["graceful_stop_requested"] is True
    latest_receipt = first_receipt["chunks"][-1] if signal_stage == "simple_batch_document_chunk_v1" else first_receipt["synthesis"][-1]
    assert latest_receipt["raw"]["sha256"]
    assert Path(latest_receipt["raw"]["path"]).is_file()
    assert Path(latest_receipt["validated_result"]["path"]).is_file()
    if signal_stage == "simple_batch_document_chunk_v1":
        assert len(first_receipt["chunks"]) == 1
        assert first_receipt.get("synthesis", []) == []
    else:
        assert len(first_receipt["chunks"]) > 1
        assert len(first_receipt["synthesis"]) == 1
    assert signal.getsignal(signal.SIGTERM) == prior_handler

    second = batch.run_batch(**run_kwargs)

    assert second["status"] == "COMPLETED_WITH_PER_DOCUMENT_STATES"
    final_receipt = json.loads((doc_root / "receipt.json").read_text(encoding="utf-8"))
    assert final_receipt["status"] == "MODEL_GENERATED_SOURCE_COMPLETE"
    assert len(queue.requested_articles) >= 3
    assert len(queue.requested_articles) == len(set(queue.requested_articles))
    assert queue.requested_articles[0].startswith(f"{pdf_sha}:chunk:000001:")
    assert queue.requested_articles.count(queue.requested_articles[0]) == 1
    assert all(queue.requested_articles.count(article_id) == 1 for article_id in first_request_articles)
    if signal_stage == "simple_batch_synthesis_v1":
        assert queue.requested_articles == first_request_articles
