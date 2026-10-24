from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import threading
from types import SimpleNamespace

import pytest

from infrastructure import local_document_model as local_model
from infrastructure import pdf_research
from infrastructure import pdf_research_tools
from ops import run_pdf_research_batch as batch
from infrastructure import pdf_text_source as text_source


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _install_fake_prepared_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    documents: list[dict[str, object]],
    *,
    parent_sha: str,
    pages_by_document: dict[str, list[pdf_research.PageText]] | None = None,
    sources_by_document: dict[str, dict[str, object]] | None = None,
    revision_ids: set[str] | None = None,
) -> tuple[Path, str]:
    """Synthetic prepared/input tests isolate admission; dedicated admission tests use its real loader."""
    monkeypatch.setattr(batch, "load_analysis_admission", lambda *args, **kwargs: None)
    manifest_path = tmp_path / "prepared-text-manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    verified_rows: dict[str, dict[str, object]] = {}
    pages_by_document = pages_by_document or {}
    sources_by_document = sources_by_document or {}
    revision_ids = revision_ids or set()
    for document in documents:
        document_id = str(document["document_id"])
        row: dict[str, object] = {"status": "READY"}
        if document_id in revision_ids:
            row["revision"] = {"reason": "PREPARED_SOURCE_TEXT_CHANGED", "supersedes": []}
        entry: dict[str, object] = {"document": document, "manifest_row": row}
        if document_id in pages_by_document:
            pages = pages_by_document[document_id]
            source = sources_by_document[document_id]
            page_input = {
                "schema": batch.pdf_text_preparation.PAGE_INPUT_SCHEMA,
                "manifest_sha256": parent_sha,
                "document_id": document_id,
                "pdf_sha256": document["pdf_sha256"],
                "source": source,
                "pages": [
                    {
                        "page_number": page.page_number,
                        "text": page.text,
                        "text_sha256": page.text_sha256 or _sha(page.text),
                        "status": page.status,
                        "extraction_method": page.extraction_method,
                    }
                    for page in pages
                ],
            }
            page_input_raw = batch.pdf_text_preparation.canonical_json(page_input) + b"\n"
            entry.update(
                {
                    "page_input": page_input,
                    "page_input_raw": page_input_raw,
                    "page_input_sha256": hashlib.sha256(page_input_raw).hexdigest(),
                }
            )
        verified_rows[document_id] = entry
    verified = {
        "manifest_sha256": manifest_sha,
        "parent_manifest_sha256": parent_sha,
        "documents": verified_rows,
        "path": manifest_path,
    }

    def fake_verify(_batch, _path, *, expected_sha256: str, expected_parent_sha256: str):
        assert expected_sha256 == manifest_sha
        assert expected_parent_sha256 == parent_sha
        return verified

    monkeypatch.setattr(batch.pdf_text_preparation, "verify_frozen_manifest", fake_verify)
    return manifest_path, manifest_sha


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


def test_temporal_prompts_keep_each_source_item_on_its_own_period_and_status() -> None:
    source_text = (
        "报告发布日期：2026-10-14。报告为2026Q3业绩前瞻。"
        "原文记载7月至9月的商品价格变化，同时将公司盈利和EPS列为预测。"
    )
    chunk = batch._build_document_chunks("e" * 64, [_page(1, 1, source_text)])[0]

    report_messages = batch._document_messages(
        {"document_id": "e" * 64, "title": "通用季度研究样例"}, chunk, partial_source=False
    )
    report_system = report_messages[0]["content"]
    assert "重要事项按原文明确表述和报告发布日期区分事实性质" in report_system
    assert "报告标题、年份、同一期间还包含预测或先验知识" in report_system
    assert "商品或燃料价格等市场观察，应保留为对应期间的事实" in report_system
    assert "公司盈利、EPS或估值预测仍应标为预测" in report_system
    assert "公司整体、分部、业务/产品、混合产品和子公司数据" in report_system
    assert "保留原文定性的供货与交付进展" in report_system
    assert "无需按固定财务清单逐项补齐" in report_system
    assert pdf_research_tools.ACTION_SYSTEM_PROMPT in report_system
    assert "不联网、不调用工具" not in report_system
    assert source_text in report_messages[1]["content"]

    synthesis_messages = batch._synthesis_messages(
        "e" * 64,
        [{"report_id": "part-1", "text": "商品价格为该期观察；公司盈利和EPS为预测。"}],
        1,
    )
    synthesis_system = synthesis_messages[0]["content"]
    assert "逐项保留每个数字或事项在原文明确给出的期间和事实性质" in synthesis_system
    assert "不跨事项传播预测或未来标签" in synthesis_system
    assert "只有原文明示事项发生在报告发布日期之后时" in synthesis_system
    assert "商品或燃料价格等市场观察应保留为相应期间的事实" in synthesis_system
    assert "应用执行有限工具" not in synthesis_system


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
        "status": "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
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
    prepared_path, prepared_sha = _install_fake_prepared_manifest(
        tmp_path, monkeypatch, documents, parent_sha=manifest_sha
    )
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
    monkeypatch.setattr(batch, "EXPECTED_CANARY_DOCUMENT_IDS", ("1" * 64, "2" * 64))
    monkeypatch.setattr(batch, "_run_document", lambda doc, **_kwargs: (_ for _ in ()).throw(batch.BatchError("FIRST_DOC_FAILED")) if doc["document_id"].startswith("1") else {"status": "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"})

    result = batch.run_batch(
        manifest_path,
        state_root=tmp_path / "state",
        prepared_text_manifest_path=prepared_path,
        prepared_text_manifest_sha256=prepared_sha,
        queue_factory=lambda root: (fake_queue, Path("/shared/model.lock")),
        identity_fn=lambda: pytest.fail("no request was attempted in this isolation test"),
        priority_reader=lambda: pytest.fail("no request was attempted in this isolation test"),
        sleep_fn=lambda _seconds: None,
    )

    assert [item["status"] for item in result["documents"]] == [
        "FAILED_DOCUMENT_ISOLATED",
        "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
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
        self.run_attempts = 0

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
        self.run_attempts += 1
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


def _configure_single_doc_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, object],
    pages: list[pdf_research.PageText],
    source: dict[str, object],
    *,
    queue: _ResumableFakeQueue | None = None,
) -> tuple[_ResumableFakeQueue, dict[str, object]]:
    pdf_sha = str(document["pdf_sha256"])
    state_root = tmp_path / "state"
    manifest = {"schema": "v4.pdf_research_simple_batch.manifest.v1", "status": "FROZEN", "documents": [document]}
    manifest_sha = "b" * 64
    queue = queue or _ResumableFakeQueue(state_root / "queue")
    monkeypatch.setattr(batch, "load_manifest", lambda _path: (manifest, manifest_sha, [document]))
    monkeypatch.setattr(batch.local_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(batch, "EXPECTED_CANARY_DOCUMENT_IDS", (pdf_sha,))
    monkeypatch.setattr(batch, "_load_pages", lambda _document, **_kwargs: (pages, source))
    monkeypatch.setattr(batch, "_read_r1_success", lambda *_args: None)
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
    prepared_path, prepared_sha = _install_fake_prepared_manifest(
        tmp_path,
        monkeypatch,
        [document],
        parent_sha=manifest_sha,
        pages_by_document={str(document["document_id"]): pages},
        sources_by_document={str(document["document_id"]): source},
    )
    run_kwargs: dict[str, object] = {
        "manifest_path": tmp_path / "manifest.json",
        "state_root": state_root,
        "prepared_text_manifest_path": prepared_path,
        "prepared_text_manifest_sha256": prepared_sha,
        "queue_factory": lambda _root: (queue, Path("/shared/model.lock")),
        "identity_fn": lambda: {"status": "MATCH", "expected_model_id": local_model.MODEL_ID},
        "priority_reader": lambda: {"status": "ALLOW", "same_model_pending_count": 0},
        "request_fn": lambda *, job, **_kwargs: json.dumps({"analysis_markdown": f"已分析 {job.payload['article_id']}（原文第1页）"}, ensure_ascii=False),
        "sleep_fn": lambda _seconds: None,
    }
    return queue, run_kwargs


def test_model_runner_consumes_frozen_prepared_pages_without_reextracting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_sha = "a" * 64
    page = _page(1, 1, "公司主营业务和行业变化：" + "收入增长、市场份额改善，" * 40)
    source = {
        "page_count": 1,
        "page_extraction_status": "COMPLETE",
        "all_pages_nonempty": True,
        "selected_pages_complete": True,
        "source_page_text_sha256": _sha(page.text),
        "source_repair_status": "NOT_REQUIRED",
        "page_extraction_sources": [{"page_number": 1, "selected": "PINNED_PYPDF_NATIVE"}],
        "source_text_acceptance": {"semantic_source_acceptance_status": "SOURCE_REVIEW_PENDING", "unreviewed_ocr_pages": []},
    }
    document = {"document_id": pdf_sha, "pdf_sha256": pdf_sha, "title": "prepared page fixture"}
    _queue, run_kwargs = _configure_single_doc_batch(tmp_path, monkeypatch, document, [page], source)
    monkeypatch.setattr(batch, "_load_pages", lambda *_args, **_kwargs: pytest.fail("model stage must not extract or OCR pages"))

    result = batch.run_batch(**run_kwargs)

    assert result["documents"][0]["status"] == "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    assert result["documents"][0]["prepared_text_manifest_sha256"] == run_kwargs["prepared_text_manifest_sha256"]


def test_pending_source_snapshot_does_not_conflict_when_next_tick_repairs_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc, _pdf_path, _cache_path, pdf_sha = _low_resolution_load_pages_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(text_source, "_read_source_text_canary_review", lambda: {"reviewer": "independent"})
    ocr_calls: list[int] = []

    def fake_ocr(_path: Path, page_number: int, _scale: int):
        ocr_calls.append(page_number)
        text = "本页恢复文字"
        return text, {
            "pdf_sha256": pdf_sha,
            "page_number": page_number,
            "rendered_dimensions_pixels": {"width_pixels": 1560, "height_pixels": 13000},
            "source_text_sha256": _sha(text),
        }

    monkeypatch.setattr(text_source, "_perform_page_ocr", fake_ocr)
    state_root = tmp_path / "state"
    queue = _ResumableFakeQueue(state_root / "queue")
    monkeypatch.setattr(batch, "_read_r1_success", lambda *_args: None)
    monkeypatch.setattr(batch, "_queue_read_result", lambda _queue, item: queue.results.get(str(item["idempotency_key"])))
    binding = {"configuration_sha256": "c" * 64, "evidence_root": str(state_root / "evidence"), "request_schema_sha256": "d" * 64}

    first = batch._run_document(
        doc,
        manifest_sha="b" * 64,
        state_root=state_root,
        queue=queue,
        binding=binding,
        identity={"status": "NOT_CHECKED"},
        priority_reader=lambda: pytest.fail("pending source must defer before priority inspection"),
        identity_reader=lambda: pytest.fail("pending source must not inspect API identity"),
        identity_state={"status": "NOT_CHECKED"},
        request_fn=lambda **_kwargs: pytest.fail("pending source must not request a model"),
        sleep_fn=lambda _seconds: pytest.fail("pending source must not sleep"),
        repair_budget={"remaining": 0},
    )
    assert first["status"] == "DEFERRED_SOURCE_REPAIR_PENDING"
    assert first["page_input"]["kind"] == "PENDING_SOURCE_SNAPSHOT"
    pending_input = Path(first["page_input"]["path"])
    assert pending_input.is_file()
    assert not (state_root / "documents" / pdf_sha / "page-input.json").exists()

    second = batch._run_document(
        doc,
        manifest_sha="b" * 64,
        state_root=state_root,
        queue=queue,
        binding=binding,
        identity={"status": "NOT_CHECKED"},
        priority_reader=lambda: {"status": "DEFER", "reason": "SAME_MODEL_ANNOUNCEMENT_ACTIVE"},
        identity_reader=lambda: pytest.fail("priority defer must not inspect identity"),
        identity_state={"status": "NOT_CHECKED"},
        request_fn=lambda **_kwargs: pytest.fail("priority defer must not request a model"),
        sleep_fn=lambda _seconds: pytest.fail("no model request means no yield"),
        repair_budget={"remaining": 2},
    )

    assert second["status"] == "DEFERRED_ANNOUNCEMENT_PRIORITY"
    assert second["page_input"]["kind"] == "FINAL_SOURCE_INPUT"
    assert Path(second["page_input"]["path"]).is_file()
    assert second["source"]["source_repair_status"] == "COMPLETE"
    assert ocr_calls == [1]
    assert queue.requested_articles == []


def test_rendered_then_reused_derived_ocr_keeps_same_final_input_and_model_call_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc, _pdf_path, _cache_path, pdf_sha = _low_resolution_load_pages_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(text_source, "_read_source_text_canary_review", lambda: {"reviewer": "independent"})
    monkeypatch.setattr(text_source, "_perform_page_ocr", lambda _path, page_number, _scale: (
        "唯一一次恢复后的OCR文本",
        {
            "pdf_sha256": pdf_sha,
            "page_number": page_number,
            "rendered_dimensions_pixels": {"width_pixels": 1560, "height_pixels": 13000},
            "source_text_sha256": _sha("唯一一次恢复后的OCR文本"),
        },
    ))
    state_root = tmp_path / "state"
    queue = _ResumableFakeQueue(state_root / "queue")
    monkeypatch.setattr(batch, "_read_r1_success", lambda *_args: None)
    monkeypatch.setattr(batch, "_queue_read_result", lambda _queue, item: queue.results.get(str(item["idempotency_key"])))
    binding = {"configuration_sha256": "c" * 64, "evidence_root": str(state_root / "evidence"), "request_schema_sha256": "d" * 64}
    priorities = iter([
        {"status": "DEFER", "reason": "SAME_MODEL_ANNOUNCEMENT_ACTIVE"},
        {"status": "ALLOW", "same_model_pending_count": 0},
    ])
    model_calls: list[str] = []

    def run_tick() -> dict[str, object]:
        return batch._run_document(
            doc,
            manifest_sha="b" * 64,
            state_root=state_root,
            queue=queue,
            binding=binding,
            identity={"status": "NOT_CHECKED"},
            priority_reader=lambda: next(priorities),
            identity_reader=lambda: {"status": "MATCH", "expected_model_id": local_model.MODEL_ID},
            identity_state={"status": "NOT_CHECKED"},
            request_fn=lambda *, job, **_kwargs: (model_calls.append(str(job.payload["article_id"])) or json.dumps({"analysis_markdown": "OCR文本分析（原文第1页）"}, ensure_ascii=False)),
            sleep_fn=lambda _seconds: None,
            repair_budget={"remaining": 2},
        )

    first = run_tick()
    first_input_sha = first["page_input"]["sha256"]
    first_input = json.loads(Path(first["page_input"]["path"]).read_text(encoding="utf-8"))
    assert first["status"] == "DEFERRED_ANNOUNCEMENT_PRIORITY"
    assert first["source"]["page_extraction_sources"][0]["selected"] == "RENDERED_DERIVED_OCR"
    assert "new_ocr_attempts_this_tick" not in first_input["source"]

    second = run_tick()
    second_input = json.loads(Path(second["page_input"]["path"]).read_text(encoding="utf-8"))
    assert second["status"] == "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    assert second["page_input"]["sha256"] == first_input_sha
    assert second["source"]["new_ocr_attempts_this_tick"] == 0
    assert second["source"]["page_extraction_sources"][0]["selected"] == "REUSED_DERIVED_OCR"
    assert second_input["source"]["page_extraction_sources"][0]["selected"] == "DERIVED_OCR"
    assert second_input["source"]["page_extraction_sources"][0]["repair_provenance"]["status"] == "DERIVED_OCR"
    assert model_calls == queue.requested_articles
    assert len(model_calls) == 1

    third = run_tick()
    assert third["status"] == "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    assert model_calls == queue.requested_articles
    assert len(model_calls) == 1


@pytest.mark.parametrize("defer_kind", ["priority", "lock"])
def test_runner_waits_then_resumes_same_request_once_after_priority_or_lock_defer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    defer_kind: str,
) -> None:
    pdf_sha = "a" * 64
    page = _page(1, 1, "原生正文" + "甲" * 50)
    document = {"document_id": pdf_sha, "pdf_sha256": pdf_sha, "title": "native text fixture"}
    source = {
        "page_count": 1,
        "page_extraction_status": "COMPLETE",
        "all_pages_nonempty": True,
        "selected_pages_complete": True,
        "source_page_text_sha256": _sha(page.text),
        "source_repair_status": "NOT_REQUIRED",
        "page_extraction_sources": [{"page_number": 1, "selected": "PINNED_PYPDF_NATIVE"}],
        "source_text_acceptance": {"semantic_source_acceptance_status": "SOURCE_REVIEW_PENDING", "unreviewed_ocr_pages": []},
    }

    class ModelSlotBusy(RuntimeError):
        pass

    class BusyOnceQueue(_ResumableFakeQueue):
        def __init__(self, state_root: Path):
            super().__init__(state_root)
            self.busy_attempts = 0

        def run_next(self, executor, validator, *, wait_for_model_slot: bool, idempotency_keys):
            self.busy_attempts += 1
            if defer_kind == "lock" and self.busy_attempts == 1:
                raise ModelSlotBusy()
            return super().run_next(executor, validator, wait_for_model_slot=wait_for_model_slot, idempotency_keys=idempotency_keys)

    queue = BusyOnceQueue(tmp_path / "state" / "queue")
    _queue, run_kwargs = _configure_single_doc_batch(tmp_path, monkeypatch, document, [page], source, queue=queue)
    priority_calls = 0

    def priority_reader():
        nonlocal priority_calls
        priority_calls += 1
        if defer_kind == "priority" and priority_calls == 1:
            return {"status": "DEFER", "reason": "SAME_MODEL_ANNOUNCEMENT_ACTIVE"}
        return {"status": "ALLOW", "same_model_pending_count": 0}

    waits: list[float] = []
    model_calls: list[str] = []
    run_kwargs.update(
        {
            "priority_reader": priority_reader,
            "request_fn": lambda *, job, **_kwargs: (model_calls.append(str(job.payload["article_id"])) or json.dumps({"analysis_markdown": "原生文本报告（原文第1页）"}, ensure_ascii=False)),
            "wait_fn": lambda event, seconds: (waits.append(seconds) or event.is_set()),
        }
    )

    result = batch.run_batch(**run_kwargs)

    assert result["status"] == "COMPLETED_WITH_PER_DOCUMENT_STATES"
    assert result["retryable_defer_waits"][0]["reason"] == ("ANNOUNCEMENT_PRIORITY" if defer_kind == "priority" else "SHARED_MODEL_LOCK_BUSY")
    assert result["retryable_defer_waits"][0]["wait_status"] == "ELAPSED"
    assert waits == [batch.RETRYABLE_DEFER_BACKOFF_BASE_SECONDS]
    assert model_calls == queue.requested_articles
    assert len(model_calls) == 1
    assert len(set(queue.requested_articles)) == 1
    assert queue.busy_attempts == (2 if defer_kind == "lock" else 1)


def test_sigterm_during_retryable_wait_stops_without_another_document_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_sha = "a" * 64
    document = {"document_id": pdf_sha, "pdf_sha256": pdf_sha}
    page = _page(1, 1, "原生正文")
    source = {"page_count": 1, "page_extraction_status": "COMPLETE", "all_pages_nonempty": True, "selected_pages_complete": True, "source_page_text_sha256": _sha(page.text)}
    _queue, run_kwargs = _configure_single_doc_batch(tmp_path, monkeypatch, document, [page], source)
    document_calls: list[str] = []

    def defer_once(doc, **_kwargs):
        document_calls.append(str(doc["document_id"]))
        return {"status": "DEFERRED_MODEL_LOCK_BUSY", "attempted": False}

    monkeypatch.setattr(batch, "_run_document", defer_once)

    def interrupt_wait(event: threading.Event, _seconds: float) -> bool:
        event.set()
        return True

    run_kwargs.update(
        {
            "priority_reader": lambda: pytest.fail("mock deferral must not inspect priority"),
            "wait_fn": interrupt_wait,
            "request_fn": lambda **_kwargs: pytest.fail("no request during lock wait"),
        }
    )

    result = batch.run_batch(**run_kwargs)

    assert result["status"] == "STOPPED_GRACEFULLY"
    assert len(document_calls) == 1
    assert result["retryable_defer_waits"][0]["wait_status"] == "STOPPED"
    assert result["stop_reason"] == "SIGTERM_REQUESTED"


def test_preparation_resumes_only_unfinished_pages_after_a_repair_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "three-long-pages.pdf"
    pdf_raw = b"%PDF-1.4\nthree synthetic long pages\n"
    pdf_path.write_bytes(pdf_raw)
    pdf_sha = hashlib.sha256(pdf_raw).hexdigest()
    cache_path = tmp_path / "three-page-cache.json"
    cache_value = {
        "pages": [
            {"page_number": page, "rendered_dimensions_pixels": {"width_pixels": 312, "height_pixels": 2600}}
            for page in range(1, 4)
        ]
    }
    cache_raw = json.dumps(cache_value).encode("utf-8")
    cache_path.write_bytes(cache_raw)
    blank_pages = [pdf_research.PageText(page, 3, "", "BLANK", _sha(""), "pypdf-6.10.0-native") for page in range(1, 4)]
    cached_pages = [
        pdf_research.PageText(page, 3, f"cache OCR {page}", "OCR_OK", _sha(f"cache OCR {page}"), "macOS Vision")
        for page in range(1, 4)
    ]
    monkeypatch.setattr(batch.pdf_research, "_validate_pdf_path", lambda _path: pdf_path)
    monkeypatch.setattr(batch.pdf_research, "extract_native_pdf_pages", lambda _path, _count: (blank_pages, "PARTIAL_OR_BLANK"))
    monkeypatch.setattr(batch.pdf_research, "load_page_cache", lambda **_kwargs: (cached_pages, {"status": "VALIDATED_THREE_PAGE_CACHE"}))
    monkeypatch.setattr(
        text_source,
        "_page_geometry",
        lambda _path, _count, _sha: [
            {"width_points": 600.0, "height_points": 5001.0, "rotation_degrees": 0.0} for _page in range(3)
        ],
    )
    monkeypatch.setattr(text_source, "_read_source_text_canary_review", lambda: {"reviewer": "independent"})
    ocr_calls: list[int] = []

    def fake_ocr(_path: Path, page_number: int, _scale: int):
        ocr_calls.append(page_number)
        text = f"恢复后的长页文字 {page_number}"
        return text, {
            "pdf_sha256": pdf_sha,
            "page_number": page_number,
            "rendered_dimensions_pixels": {"width_pixels": 1560, "height_pixels": 13000},
            "source_text_sha256": _sha(text),
        }

    monkeypatch.setattr(text_source, "_perform_page_ocr", fake_ocr)
    document = {
        "document_id": pdf_sha,
        "pdf_sha256": pdf_sha,
        "pdf_bytes": len(pdf_raw),
        "local_pdf_path": str(pdf_path),
        "page_count": 3,
        "source_paths": [],
        "cache_candidates": [
            {
                "path": str(cache_path),
                "sha256": hashlib.sha256(cache_raw).hexdigest(),
                "page_count": 3,
                "coverage_status": "COMPLETE",
            }
        ],
    }
    state_root = tmp_path / "preparation-state"
    resumed_pages: dict[int, tuple[pdf_research.PageText, dict[str, object]]] = {}

    def checkpoint(page: pdf_research.PageText, source_row: dict[str, object]) -> None:
        resumed_pages[page.page_number] = (page, source_row)

    first_pages, first_source = batch._load_pages(
        document,
        state_root=state_root,
        repair_budget={"remaining": 2},
        preparation_mode=True,
        resume_pages={},
        page_callback=checkpoint,
    )
    assert first_source["source_repair_status"] == "PENDING"
    assert list(resumed_pages) == [1, 2]
    assert [page.text for page in first_pages[:2]] == ["恢复后的长页文字 1", "恢复后的长页文字 2"]
    assert ocr_calls == [1, 2]

    final_pages, final_source = batch._load_pages(
        document,
        state_root=state_root,
        repair_budget={"remaining": 2},
        preparation_mode=True,
        resume_pages=resumed_pages,
        page_callback=checkpoint,
    )

    assert final_source["source_repair_status"] == "COMPLETE"
    assert [page.text for page in final_pages] == ["恢复后的长页文字 1", "恢复后的长页文字 2", "恢复后的长页文字 3"]
    assert list(resumed_pages) == [1, 2, 3]
    assert ocr_calls == [1, 2, 3]


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
    monkeypatch.setattr(batch, "EXPECTED_CANARY_DOCUMENT_IDS", (pdf_sha,))
    monkeypatch.setattr(batch, "_load_pages", lambda _document, **_kwargs: ([page], source))
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
    prepared_path, prepared_sha = _install_fake_prepared_manifest(
        tmp_path,
        monkeypatch,
        documents,
        parent_sha=manifest_sha,
        pages_by_document={pdf_sha: [page]},
        sources_by_document={pdf_sha: source},
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
        "prepared_text_manifest_path": prepared_path,
        "prepared_text_manifest_sha256": prepared_sha,
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
    assert final_receipt["status"] == "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    assert len(queue.requested_articles) >= 3
    assert len(queue.requested_articles) == len(set(queue.requested_articles))
    assert queue.requested_articles[0].startswith(f"{pdf_sha}:chunk:000001:")
    assert queue.requested_articles.count(queue.requested_articles[0]) == 1
    assert all(queue.requested_articles.count(article_id) == 1 for article_id in first_request_articles)
    if signal_stage == "simple_batch_synthesis_v1":
        assert queue.requested_articles == first_request_articles


def _low_resolution_load_pages_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    render_dimensions: tuple[int, int] = (312, 2600),
    cached_text: str = "稀疏错误OCR",
) -> tuple[dict[str, object], Path, Path, str]:
    pdf_path = tmp_path / "source.pdf"
    pdf_bytes = b"%PDF-1.4\nsynthetic test fixture\n"
    pdf_path.write_bytes(pdf_bytes)
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
    cache_path = tmp_path / "cache.json"
    cache_value = {
        "pages": [
            {
                "page_number": 1,
                "rendered_dimensions_pixels": {"width_pixels": render_dimensions[0], "height_pixels": render_dimensions[1]},
            }
        ]
    }
    cache_raw = json.dumps(cache_value, ensure_ascii=False).encode("utf-8")
    cache_path.write_bytes(cache_raw)
    cache_page = _page(1, 1, cached_text)
    cache_page = pdf_research.PageText(1, 1, cached_text, "OCR_OK", _sha(cached_text), "macOS Vision")
    monkeypatch.setattr(batch.pdf_research, "_validate_pdf_path", lambda _path: pdf_path)
    blank_native = pdf_research.PageText(1, 1, "", "BLANK", _sha(""), "pypdf-6.10.0-native")
    monkeypatch.setattr(batch.pdf_research, "extract_native_pdf_pages", lambda _path, _count: ([blank_native], "PARTIAL_OR_BLANK"))
    monkeypatch.setattr(batch.pdf_research, "load_page_cache", lambda **_kwargs: ([cache_page], {"status": "VALIDATED_TEST_CACHE"}))
    monkeypatch.setattr(
        text_source,
        "_page_geometry",
        lambda _path, _count, _sha: [{"width_points": 600.0, "height_points": 5001.0, "rotation_degrees": 0.0}],
    )
    doc = {
        "document_id": pdf_sha,
        "pdf_sha256": pdf_sha,
        "pdf_bytes": len(pdf_bytes),
        "local_pdf_path": str(pdf_path),
        "page_count": 1,
        "source_paths": [],
        "cache_candidates": [{"path": str(cache_path), "sha256": hashlib.sha256(cache_raw).hexdigest(), "page_count": 1, "coverage_status": "COMPLETE"}],
    }
    return doc, pdf_path, cache_path, pdf_sha


def test_long_geometry_bypasses_sparse_cache_and_reuses_derived_ocr_on_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc, _pdf_path, _cache_path, pdf_sha = _low_resolution_load_pages_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(text_source, "_read_source_text_canary_review", lambda: {"reviewer": "independent"})
    ocr_calls: list[tuple[int, int]] = []

    def fake_ocr(_path: Path, page_number: int, scale: int):
        ocr_calls.append((page_number, scale))
        return "恢复后的保守叙事文字", {
            "pdf_sha256": pdf_sha,
            "page_number": page_number,
            "rendered_dimensions_pixels": {"width_pixels": 1560, "height_pixels": 13000},
            "source_text_sha256": _sha("恢复后的保守叙事文字"),
        }

    monkeypatch.setattr(text_source, "_perform_page_ocr", fake_ocr)
    state_root = tmp_path / "r2-state"
    budget = {"remaining": 2}
    pages, source = batch._load_pages(doc, state_root=state_root, repair_budget=budget)

    assert pages[0].text == "恢复后的保守叙事文字"
    assert source["source_repair_status"] == "COMPLETE"
    assert source["new_ocr_attempts_this_tick"] == 1
    assert source["ocr_invoked"] is True
    assert source["page_extraction_sources"][0]["selected"] == "RENDERED_DERIVED_OCR"
    assert source["source_text_acceptance"]["unreviewed_ocr_pages"] == [1]
    assert ocr_calls == [(1, 13000)]
    derived_path = state_root / "documents" / pdf_sha / "derived-ocr/page-0001.json"
    assert derived_path.is_file()

    monkeypatch.setattr(text_source, "_perform_page_ocr", lambda *_args: pytest.fail("resume must reuse derived OCR"))
    resumed, resumed_source = batch._load_pages(doc, state_root=state_root, repair_budget={"remaining": 2})
    assert resumed[0].text == pages[0].text
    assert resumed_source["new_ocr_attempts_this_tick"] == 0
    assert resumed_source["page_extraction_sources"][0]["selected"] == "REUSED_DERIVED_OCR"


def test_low_resolution_sparse_cache_without_source_gate_is_deferred_before_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc, _pdf_path, _cache_path, _pdf_sha = _low_resolution_load_pages_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(text_source, "_read_source_text_canary_review", lambda: None)
    monkeypatch.setattr(text_source, "_perform_page_ocr", lambda *_args: pytest.fail("source gate is required before OCR"))
    state_root = tmp_path / "r2-state"
    pages, source = batch._load_pages(doc, state_root=state_root, repair_budget={"remaining": 2})
    assert pages[0].text == ""
    assert source["source_repair_status"] == "PENDING"
    assert source["page_extraction_sources"][0]["selected"] == "SOURCE_REPAIR_PENDING_CANARY_REVIEW"

    monkeypatch.setattr(batch, "_load_pages", lambda _document, **_kwargs: (pages, source))
    outcome = batch._run_document(
        doc,
        manifest_sha="b" * 64,
        state_root=state_root,
        queue=object(),
        binding={},
        identity={"status": "NOT_CHECKED"},
        priority_reader=lambda: pytest.fail("pending source must defer before model priority"),
        identity_reader=lambda: pytest.fail("pending source must not inspect API identity"),
        identity_state={"status": "NOT_CHECKED"},
        request_fn=lambda **_kwargs: pytest.fail("pending source must not call model"),
        sleep_fn=lambda _seconds: pytest.fail("pending source must not sleep"),
    )
    assert outcome["status"] == "DEFERRED_SOURCE_REPAIR_PENDING"


def test_single_failed_repair_is_isolated_and_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc, _pdf_path, _cache_path, _pdf_sha = _low_resolution_load_pages_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(text_source, "_read_source_text_canary_review", lambda: {"reviewer": "independent"})
    calls: list[int] = []

    def fail_ocr(_path: Path, page_number: int, _scale: int):
        calls.append(page_number)
        raise batch.BatchError("VISION_TIMEOUT")

    monkeypatch.setattr(text_source, "_perform_page_ocr", fail_ocr)
    state_root = tmp_path / "r2-state"
    first_pages, first_source = batch._load_pages(doc, state_root=state_root, repair_budget={"remaining": 2})
    assert first_source["source_repair_status"] == "FAILED_SINGLE_ATTEMPT"
    assert first_source["page_extraction_sources"][0]["failure_code"] == "VISION_TIMEOUT"
    assert first_pages[0].text == ""
    failed_path = state_root / "documents" / doc["document_id"] / "derived-ocr/page-0001.failed.json"
    assert failed_path.is_file()

    second_pages, second_source = batch._load_pages(doc, state_root=state_root, repair_budget={"remaining": 2})
    assert second_source["source_repair_status"] == "FAILED_PREVIOUS_ATTEMPT"
    assert second_pages[0].text == ""
    assert calls == [1]


def test_verified_adequate_existing_long_page_cache_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc, _pdf_path, _cache_path, _pdf_sha = _low_resolution_load_pages_fixture(
        tmp_path,
        monkeypatch,
        render_dimensions=(1560, 13000),
        cached_text="已存在的高分辨率缓存文本",
    )
    monkeypatch.setattr(text_source, "_read_source_text_canary_review", lambda: None)
    monkeypatch.setattr(text_source, "_perform_page_ocr", lambda *_args: pytest.fail("adequate cache must be preserved"))

    pages, source = batch._load_pages(doc, state_root=tmp_path / "state", repair_budget={"remaining": 2})

    assert pages[0].text == "已存在的高分辨率缓存文本"
    assert source["source_repair_status"] == "NOT_REQUIRED"
    assert source["page_extraction_sources"][0]["cache_render_metadata_verified_adequate"] is True
    assert source["page_extraction_sources"][0]["semantic_source_review_status"] == "SOURCE_REVIEW_PENDING"
    assert source["source_text_acceptance"]["unreviewed_ocr_pages"] == [1]
    chunk = batch._build_document_chunks(doc["document_id"], pages)[0]
    prompt = batch._document_messages(
        {
            "document_id": doc["document_id"],
            "_has_unreviewed_ocr": bool(source["source_text_acceptance"]["unreviewed_ocr_pages"]),
        },
        chunk,
        partial_source=False,
    )[-1]["content"]
    assert "unreviewed_ocr_qualification" in prompt
    assert "姓名、代码、表格行和精确数字可能存在转录误差" in prompt


def test_unsupported_geometry_is_truthfully_isolated_without_an_ocr_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc, _pdf_path, _cache_path, _pdf_sha = _low_resolution_load_pages_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(text_source, "_read_source_text_canary_review", lambda: {"reviewer": "independent"})
    monkeypatch.setattr(
        text_source,
        "_page_geometry",
        lambda *_args: (_ for _ in ()).throw(batch.BatchError("PAGE_GEOMETRY_UNSUPPORTED")),
    )
    monkeypatch.setattr(text_source, "_perform_page_ocr", lambda *_args: pytest.fail("unknown geometry must not trigger OCR"))

    pages, source = batch._load_pages(doc, state_root=tmp_path / "state", repair_budget={"remaining": 2})

    assert pages[0].text == ""
    assert source["source_repair_status"] == "FAILED_UNSUPPORTED_GEOMETRY"
    failure = json.loads((tmp_path / "state/documents" / doc["document_id"] / "derived-ocr/page-0001.failed.json").read_text())
    assert failure["attempts_used_for_page"] == 0


def test_cache_render_geometry_comes_from_the_candidate_that_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc, _pdf_path, _cache_path, _pdf_sha = _low_resolution_load_pages_fixture(
        tmp_path,
        monkeypatch,
        render_dimensions=(1560, 13000),
        cached_text="已存在的高分辨率缓存文本",
    )
    invalid_cache = tmp_path / "invalid-cache.json"
    invalid_cache.write_text("{}", encoding="utf-8")
    doc["cache_candidates"] = [
        {
            "path": str(invalid_cache),
            "sha256": hashlib.sha256(invalid_cache.read_bytes()).hexdigest(),
            "page_count": 1,
            "coverage_status": "COMPLETE",
        },
        doc["cache_candidates"][0],
    ]
    def load_candidate(*, pages_cache_path: Path, **_kwargs):
        if pages_cache_path == invalid_cache:
            raise batch.BatchError("INVALID_TEST_CACHE")
        return [
            pdf_research.PageText(1, 1, "已存在的高分辨率缓存文本", "OCR_OK", _sha("已存在的高分辨率缓存文本"), "macOS Vision")
        ], {"status": "SECOND_VALIDATED_TEST_CACHE"}

    monkeypatch.setattr(batch.pdf_research, "load_page_cache", load_candidate)
    monkeypatch.setattr(text_source, "_read_source_text_canary_review", lambda: None)
    monkeypatch.setattr(text_source, "_perform_page_ocr", lambda *_args: pytest.fail("valid second cache candidate must be preserved"))

    pages, source = batch._load_pages(doc, state_root=tmp_path / "state", repair_budget={"remaining": 2})

    assert pages[0].text == "已存在的高分辨率缓存文本"
    assert source["source_repair_status"] == "NOT_REQUIRED"
    assert source["page_extraction_sources"][0]["cache_render_metadata_verified_adequate"] is True
    assert source["cache"]["status"] == "SECOND_VALIDATED_TEST_CACHE"


def test_reviewed_scale_canary_bounds_prompt_and_input_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "阿斯利康与Insitro合作；OCR额外付款金额不确定；表格逐行内容不采用。"
    text = prefix + "叙" * (5_353 - len(prefix))
    text_sha = _sha(text)
    attempt = {
        "schema": "v4.pdf_simple_batch.ocr_scale_canary_attempt.v1",
        "status": "NEW_TEXT_REVIEW_REQUIRED",
        "document_id": text_source.FIRST_CONTENT_FAIL_PDF_SHA256,
        "scope_sha256": text_source.SOURCE_CANARY_SCOPE_SHA256,
        "source_pdf": {"sha256": text_source.FIRST_CONTENT_FAIL_PDF_SHA256, "page_count": 1},
        "page": {
            "page_number": 1,
            "original_dimensions_points": {"height_points": 5001.0, "width_points": 600.0},
            "rendered_dimensions_pixels": {"height_pixels": 13000, "width_pixels": 1560},
        },
        "ocr_attempt": {"full_vision_result": {"status": "OCR_OK"}},
        "render_identity": {
            "render_scale_to": 13000,
            "renderer_sha256": text_source.EXPECTED_RENDERER_SHA256,
            "render_image": {"sha256": "e" * 64},
        },
        "text": {"value": text, "sha256": text_sha},
    }
    attempt_path = tmp_path / "attempt.json"
    attempt_raw = json.dumps(attempt, ensure_ascii=False).encode("utf-8")
    attempt_path.write_bytes(attempt_raw)
    attempt_sha = hashlib.sha256(attempt_raw).hexdigest()
    boundary = {
        "adequate_for": "Conservative AstraZeneca-Insitro primary narrative only.",
        "can_report_from_text": ["AZN.US printed code", "USD 1.86 billion headline maximum", "USD 40 million upfront"],
        "must_mark_uncertain_or_unknown": ["14.G亿美元 is not an exact confirmed amount", "condition wording is uncertain", "do not infer an Insitro code"],
        "exclude_or_bound": ["Do not extract row-level announcement tables", "Do not report footer chips or market metrics as exact"],
    }
    review = {
        "schema": text_source.SOURCE_CANARY_REVIEW_SCHEMA,
        "status": "SOURCE_CONTENT_PASS",
        "reviewer": "independent-reviewer",
        "scope": {"document_id": text_source.FIRST_CONTENT_FAIL_PDF_SHA256, "page_number": 1},
        "pdf_sha256": text_source.FIRST_CONTENT_FAIL_PDF_SHA256,
        "attempt_sha256": attempt_sha,
        "text_sha256": text_sha,
        "text_characters": len(text),
        "acceptance": {"source_content_pass": True, "full_page_row_level_transcription_pass": False},
        "accepted_markdown_boundary": boundary,
    }
    review_path = tmp_path / "source-review.json"
    review_raw = json.dumps(review, ensure_ascii=False).encode("utf-8")
    review_path.write_bytes(review_raw)
    monkeypatch.setattr(text_source, "SOURCE_CANARY_ATTEMPT_PATH", attempt_path)
    monkeypatch.setattr(text_source, "SOURCE_CANARY_ATTEMPT_SHA256", attempt_sha)
    monkeypatch.setattr(text_source, "SOURCE_CANARY_TEXT_SHA256", text_sha)
    monkeypatch.setattr(text_source, "SOURCE_CANARY_REVIEW_DEFAULT", review_path)
    monkeypatch.setattr(text_source, "SOURCE_CANARY_REVIEW_SHA256", hashlib.sha256(review_raw).hexdigest())

    recovered = text_source._read_scale_canary_page(text_source.FIRST_CONTENT_FAIL_PDF_SHA256, 1)
    assert recovered is not None
    page, provenance = recovered
    assert page.text == text
    assert provenance["accepted_markdown_boundary"] == boundary
    with pytest.raises(batch.BatchError, match="SOURCE_TEXT_CANARY_ATTEMPT_BINDING_MISMATCH"):
        text_source._read_scale_canary_page(text_source.FIRST_CONTENT_FAIL_PDF_SHA256, 1, expected_page_count=2)

    chunk = batch._build_document_chunks(text_source.FIRST_CONTENT_FAIL_PDF_SHA256, [page])[0]
    messages = batch._document_messages(
        {"document_id": text_source.FIRST_CONTENT_FAIL_PDF_SHA256, "_accepted_ocr_boundary": boundary},
        chunk,
        partial_source=False,
    )
    user_message = messages[-1]["content"]
    assert "14.G亿美元 is not an exact confirmed amount" in user_message
    assert "do not infer an Insitro code" in user_message
    assert "Do not extract row-level announcement tables" in user_message


def test_reviewed_slice_canary_reuse_and_high_priority_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = "腾讯上线绿泡泡短剧；航展计划在珠海举行。" + "文" * (5_202 - len("腾讯上线绿泡泡短剧；航展计划在珠海举行。"))
    text_path = tmp_path / "ordered-text.txt"
    text_path.write_text(text, encoding="utf-8")
    text_sha = _sha(text)
    attempt = {
        "schema": "v4.pdf_research_simple_batch.longscan_slice_ocr_canary.v1",
        "status": "OCR_COMPLETE_SOURCE_REVIEW_PENDING",
        "scope_sha256": "a" * 64,
        "document": {"pdf_sha256": text_source.SECOND_CONTENT_FAIL_PDF_SHA256, "page_count": 1, "page_number": 1},
        "helper_identity": {
            "prepare_crop_sha256": text_source.EXPECTED_V3_PREPARE_OCR_SHA256,
            "common_sha256": text_source.EXPECTED_V3_COMMON_SHA256,
            "renderer_sha256": text_source.EXPECTED_RENDERER_SHA256,
            "renderer_version": text_source.EXPECTED_RENDERER_VERSION,
            "vision_source_sha256": text_source.EXPECTED_VISION_SOURCE_SHA256,
            "vision_config_sha256": text_source.EXPECTED_VISION_CONFIG_SHA256,
            "slice_height": 9000,
        },
        "render": {"width_pixels": 1541, "height_pixels": 13000, "sha256": "b" * 64},
        "segmentation": {"gap_free": True, "overlap": 0},
        "result": {"status": "OCR_OK_SLICED", "part_text_order": [1, 2], "sha256": text_sha, "characters": len(text)},
    }
    manifest = {
        "source_pdf_sha256": text_source.SECOND_CONTENT_FAIL_PDF_SHA256,
        "source_image_sha256": "b" * 64,
        "width": 1541,
        "height": 13000,
        "geometry_validation": "PASS_GAP_FREE_CONTIGUOUS_NONOVERLAPPING",
        "parts": [
            {"part": 1, "top": 0, "bottom": 9000},
            {"part": 2, "top": 9000, "bottom": 13000},
        ],
    }
    boundary = {
        "adequate_for": "仅限绿泡泡叙述与航展日程地点。",
        "can_report_from_text": ["腾讯上线绿泡泡短剧", "航展计划在珠海举行"],
        "uncertainties_to_preserve": ["未核验外部事实"],
        "exclude_or_bound": ["不报告市场数字和表格映射"],
    }
    review = {
        "schema": text_source.SOURCE_CANARY_REVIEW_SCHEMA,
        "status": "SOURCE_CONTENT_PASS",
        "reviewer": "independent-reviewer",
        "pdf_sha256": text_source.SECOND_CONTENT_FAIL_PDF_SHA256,
        "scope_sha256": "c" * 64,
        "accepted_markdown_boundary": boundary,
    }
    paths = [tmp_path / "attempt.json", tmp_path / "manifest.json", text_path, tmp_path / "review.json"]
    paths[0].write_text(json.dumps(attempt), encoding="utf-8")
    paths[1].write_text(json.dumps(manifest), encoding="utf-8")
    paths[3].write_text(json.dumps(review), encoding="utf-8")
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    for name, value in zip(
        ("SLICE_CANARY_ATTEMPT_PATH", "SLICE_CANARY_MANIFEST_PATH", "SLICE_CANARY_TEXT_PATH", "SLICE_CANARY_REVIEW_DEFAULT"),
        paths,
    ):
        monkeypatch.setattr(text_source, name, value)
    for name, value in zip(
        ("SLICE_CANARY_ATTEMPT_SHA256", "SLICE_CANARY_MANIFEST_SHA256", "SLICE_CANARY_TEXT_SHA256", "SLICE_CANARY_REVIEW_SHA256"),
        hashes,
    ):
        monkeypatch.setattr(text_source, name, value)
    monkeypatch.setattr(text_source, "SLICE_CANARY_SCOPE_SHA256", "a" * 64)
    monkeypatch.setattr(text_source, "SLICE_SOURCE_REVIEW_SCOPE_SHA256", "c" * 64)

    recovered = text_source._read_slice_canary_page(text_source.SECOND_CONTENT_FAIL_PDF_SHA256, 1, expected_page_count=1)

    assert recovered is not None
    page, provenance = recovered
    assert page.text == text
    assert provenance["accepted_markdown_boundary"] == boundary
    chunk = batch._build_document_chunks(
        text_source.SECOND_CONTENT_FAIL_PDF_SHA256,
        [page],
        prompt_source={"document_id": text_source.SECOND_CONTENT_FAIL_PDF_SHA256, "_accepted_ocr_boundary": boundary},
    )[0]
    user_message = batch._document_messages(
        {"document_id": text_source.SECOND_CONTENT_FAIL_PDF_SHA256, "_accepted_ocr_boundary": boundary},
        chunk,
        partial_source=False,
    )[-1]["content"]
    assert user_message.startswith("【最高优先级：第1页已审核来源边界】")
    assert "优先于“覆盖全部内容”“覆盖所有页面”或“保留全部数字”的要求" in user_message
    synthesis = batch._synthesis_messages("d" * 64, [{"text": "测试分段报告"}], 1, boundary)[-1]["content"]
    assert synthesis.startswith("【最高优先级：第1页已审核来源边界】")
    assert "不得恢复" in batch.SYNTHESIS_SYSTEM_PROMPT


def test_long_render_uses_existing_two_slice_geometry_and_vision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def png(width: int, height: int) -> bytes:
        return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"

    renderer = tmp_path / "pdftoppm"
    renderer.write_bytes(b"test-renderer")
    prepare_path = tmp_path / "wechat_prepare_ocr.py"
    common_path = tmp_path / "wechat_common.py"
    prepare_path.write_text("# pinned test helper\n", encoding="utf-8")
    common_path.write_text("# pinned test geometry helper\n", encoding="utf-8")
    prepare = SimpleNamespace(
        __file__=str(prepare_path),
        _image_size=lambda path: (
            int.from_bytes(path.read_bytes()[16:20], "big"),
            int.from_bytes(path.read_bytes()[20:24], "big"),
        ),
    )

    def crop(source: Path, output: Path, *, width: int, top: int, height: int) -> None:
        output.write_bytes(png(width, height) + f"crop:{top}".encode())

    prepare._crop_image = crop

    def validate_geometry(item: dict) -> None:
        assert item["sliced"] is True
        assert [(p["top"], p["bottom"]) for p in item["parts"]] == [(0, 9000), (9000, 13000)]

    common = SimpleNamespace(__file__=str(common_path), validate_slice_geometry=validate_geometry)
    calls: list[Path] = []

    class Vision:
        OCR_TIMEOUT_SECONDS = 30

        @staticmethod
        def _compile_vision_helper(_root: Path) -> Path:
            return tmp_path / "compiled-helper"

        @staticmethod
        def _vision_ocr(_exe: Path, image_path: Path) -> dict[str, str]:
            calls.append(image_path)
            return {"status": "OCR_OK", "text": f"切片{len(calls)}"}

    def _write_render(root: Path) -> Path:
        path = root / "full.png"
        path.write_bytes(png(1541, 13000))
        return path

    vision = Vision()
    ingestion_path = Path(__file__).resolve().parents[1] / "infrastructure/zsxq_pdf_ingestion.py"
    monkeypatch.setattr(text_source, "EXPECTED_RENDERER_SHA256", _sha("test-renderer"))
    monkeypatch.setattr(text_source, "EXPECTED_RENDERER_VERSION", "test-renderer-version")
    monkeypatch.setattr(text_source, "EXPECTED_VISION_SOURCE_SHA256", "v" * 64)
    monkeypatch.setattr(text_source, "EXPECTED_VISION_CONFIG_SHA256", "c" * 64)
    monkeypatch.setattr(text_source, "V3_OCR_SCRIPTS_ROOT", tmp_path)
    monkeypatch.setattr(text_source, "V3_PREPARE_OCR_PATH", prepare_path)
    monkeypatch.setattr(text_source, "V3_COMMON_PATH", common_path)
    monkeypatch.setattr(text_source, "EXPECTED_V3_PREPARE_OCR_SHA256", hashlib.sha256(prepare_path.read_bytes()).hexdigest())
    monkeypatch.setattr(text_source, "EXPECTED_V3_COMMON_SHA256", hashlib.sha256(common_path.read_bytes()).hexdigest())
    fake_ingestion = SimpleNamespace(
        DEFAULT_PDFTOPPM=str(renderer),
        RENDER_SCALE_TO=2600,
        _renderer_version=lambda _path: "test-renderer-version",
        _load_vision_module=lambda: (vision, "v" * 64, "c" * 64),
        _render_pdf_page=lambda _pdf, _page, root, pdftoppm: _write_render(root),
    )
    monkeypatch.setitem(sys.modules, "infrastructure.zsxq_pdf_ingestion", fake_ingestion)
    monkeypatch.setitem(sys.modules, "wechat_prepare_ocr", prepare)
    monkeypatch.setitem(sys.modules, "wechat_common", common)
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"test-pdf")

    text, provenance = text_source._perform_page_ocr(pdf, 1, 13000)

    assert text == "切片1\n切片2"
    assert len(calls) == 2
    assert [(row["top"], row["bottom"], row["height_pixels"]) for row in provenance["slice_provenance"]] == [
        (0, 9000, 9000), (9000, 13000, 4000)
    ]
    assert all(len(row["crop_sha256"]) == len(row["text_sha256"]) == 64 for row in provenance["slice_provenance"])
    assert provenance["slice_geometry_status"] == "GAP_FREE_CONTIGUOUS_NONOVERLAPPING"
    assert provenance["vision_aggregate_elapsed_seconds"] <= text_source.MAX_REPAIR_VISION_AGGREGATE_SECONDS


def test_r1_success_reuse_requires_exact_payload_and_excludes_content_failed_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r1_root = tmp_path / "r1"
    queue_root = r1_root / "queue"
    key = "d" * 64
    payload = {"article_id": "doc:chunk:1", "source_sha256": "e" * 64, "payload": "same"}
    payload_raw = local_model.canonical_json(payload)
    payload_sha = hashlib.sha256(payload_raw).hexdigest()
    monkeypatch.setattr(batch, "R1_STATE_ROOT", r1_root)
    monkeypatch.setattr(batch.pdf_research, "_queue_identity_and_payload_sha256", lambda _queue, _payload: (key, payload_sha))
    queue = SimpleNamespace(queue_id="v4-pdf-simple-batch", model_id=local_model.MODEL_ID)
    job_root = queue_root / "jobs" / key
    job_root.mkdir(parents=True)
    input_path = job_root / "input.json"
    raw_path = job_root / "attempt-0001.raw"
    validated_path = job_root / "attempt-0001.validated.json"
    input_path.write_bytes(payload_raw)
    raw_raw = local_model.canonical_json({"analysis_markdown": "此前成功分析"})
    validated_raw = local_model.canonical_json({"analysis_markdown": "此前成功分析"})
    raw_sha = hashlib.sha256(raw_raw).hexdigest()
    validated_sha = hashlib.sha256(validated_raw).hexdigest()
    raw_path.write_bytes(raw_raw)
    validated_path.write_bytes(validated_raw)
    item = {
        "status": "SUCCEEDED",
        "idempotency_key": key,
        "payload_sha256": payload_sha,
        "queue_id": queue.queue_id,
        "queue_ids": [queue.queue_id],
        "model_id": queue.model_id,
        "attempt_count": 1,
        "max_attempts": 1,
        "queue_policy": {"max_attempts": 1, "max_body_bytes": None},
        "input_path": f"jobs/{key}/input.json",
        "raw_path": f"jobs/{key}/attempt-0001.raw",
        "validated_path": f"jobs/{key}/attempt-0001.validated.json",
        "raw_sha256": raw_sha,
        "validated_sha256": validated_sha,
        "attempts": [
            {
                "number": 1,
                "status": "SUCCEEDED",
                "raw_path": f"jobs/{key}/attempt-0001.raw",
                "validated_path": f"jobs/{key}/attempt-0001.validated.json",
                "raw_sha256": raw_sha,
                "validated_sha256": validated_sha,
            }
        ],
    }
    state_path = queue_root / "queue-state.json"
    state_path.write_text(json.dumps({"schema": "v4.announcement-engine-queue/v1", "jobs": {key: item}}), encoding="utf-8")

    reused = batch._read_r1_success(queue, payload)
    assert reused is not None
    assert reused["status"] == "SUCCEEDED_REUSED_R1"
    assert reused["result"]["analysis_markdown"] == "此前成功分析"

    changed_payload = {**payload, "payload": "changed"}
    assert batch._read_r1_success(queue, changed_payload) is None
    rejected_payload = {**payload, "source_sha256": text_source.FIRST_CONTENT_FAIL_PDF_SHA256}
    assert batch._read_r1_success(queue, rejected_payload) is None


def test_full_batch_isolates_only_bound_report_failures_and_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_root = tmp_path / "state"
    manifest_sha = "f" * 64
    later_document = "4" * 64
    documents = [
        {"document_id": sha, "pdf_sha256": sha}
        for sha in (*batch.EXPECTED_CANARY_DOCUMENT_IDS, later_document)
    ]
    old_bytes: dict[str, dict[str, bytes]] = {}
    review_rows: list[dict[str, str]] = []
    findings: list[dict[str, str]] = []
    for doc_id in batch.EXPECTED_CANARY_DOCUMENT_IDS:
        doc_root = state_root / "documents" / doc_id
        doc_root.mkdir(parents=True)
        page_path = doc_root / "page-input.json"
        report_path = doc_root / "report.md"
        page_path.write_text(json.dumps({"document_id": doc_id}), encoding="utf-8")
        report_path.write_text(f"report {doc_id}", encoding="utf-8")
        page_sha = hashlib.sha256(page_path.read_bytes()).hexdigest()
        report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
        receipt = {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "manifest_sha256": manifest_sha,
            "document_id": doc_id,
            "pdf_sha256": doc_id,
            "status": (
                "USER_ACCEPTED_REUSED_REPORT"
                if doc_id == batch.S18_PDF_SHA256
                else "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
            ),
            "page_input": {"path": str(page_path), "sha256": page_sha},
            "report": {"path": str(report_path), "sha256": report_sha},
        }
        receipt_path = doc_root / "receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        old_bytes[doc_id] = {
            "receipt": receipt_path.read_bytes(),
            "page_input": page_path.read_bytes(),
            "report": report_path.read_bytes(),
        }
        review_rows.append({
            "document_id": doc_id,
            "pdf_sha256": doc_id,
            "page_input_sha256": page_sha,
            "report_sha256": report_sha,
            "verdict": "PASS" if doc_id == batch.S18_PDF_SHA256 else "FAIL",
        })
        if doc_id != batch.S18_PDF_SHA256:
            findings.append({
                "document_id": doc_id,
                "id": f"{doc_id[:4]}_OUT_OF_BOUND_CONTENT",
                "severity": "P1",
                "required_correction": "Preserve only claims allowed by the reviewed source boundary.",
            })
    review = {
        "schema": batch.REPORT_CANARY_REVIEW_SCHEMA,
        "status": "FAIL",
        "reviewer": "independent-report-reviewer",
        "binding_check": "PASS",
        "manifest_sha256": manifest_sha,
        "source_text_review_sha256": text_source.SOURCE_CANARY_REVIEW_SHA256,
        "second_source_text_review_sha256": text_source.SLICE_CANARY_REVIEW_SHA256,
        "documents": review_rows,
        "findings": findings,
    }
    review_path = tmp_path / "report-review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    monkeypatch.setattr(batch, "REPORT_CANARY_REVIEW_DEFAULT", review_path)
    monkeypatch.setattr(batch, "EXPECTED_REPORT_CONTENT_FAIL_REVIEW_SHA256", hashlib.sha256(review_path.read_bytes()).hexdigest(), raising=False)
    monkeypatch.setattr(batch, "EXPECTED_BATCH_MANIFEST_SHA256", manifest_sha)

    manifest = {"schema": "v4.pdf_research_simple_batch.manifest.v1", "status": "FROZEN", "documents": documents}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(batch, "load_manifest", lambda _path: (manifest, manifest_sha, documents))
    monkeypatch.setattr(batch.local_model, "require_runtime_python", lambda: None)
    monkeypatch.setattr(
        batch.local_model,
        "build_request_material",
        lambda _schema: {
            "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
            "model_settings_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
            "runtime_python": str(batch.local_model.RUNTIME_PYTHON),
            "evidence_root": str(state_root / "evidence"),
            "configuration_sha256": "c" * 64,
        },
    )
    prepared_path, prepared_sha = _install_fake_prepared_manifest(
        tmp_path, monkeypatch, documents, parent_sha=manifest_sha
    )
    calls: list[str] = []

    def run_unrelated(document, **_kwargs):
        calls.append(document["document_id"])
        return {
            "document_id": document["document_id"],
            "status": "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING",
        }

    monkeypatch.setattr(batch, "_run_document", run_unrelated)
    fake_queue = SimpleNamespace(state_root=state_root / "queue")

    result = batch.run_batch(
        manifest_path,
        state_root=state_root,
        prepared_text_manifest_path=prepared_path,
        prepared_text_manifest_sha256=prepared_sha,
        queue_factory=lambda root: (fake_queue, Path("/shared/model.lock")),
        request_fn=lambda **_kwargs: pytest.fail("known failed documents must not enqueue a model request"),
        identity_fn=lambda: pytest.fail("known failed documents must not request model identity"),
        priority_reader=lambda: pytest.fail("known failed documents must not enter request handling"),
        sleep_fn=lambda _seconds: None,
        max_documents=4,
    )

    observed = {item["document_id"]: item for item in result["documents"]}
    first = observed[text_source.FIRST_CONTENT_FAIL_PDF_SHA256]
    second = observed[text_source.SECOND_CONTENT_FAIL_PDF_SHA256]
    assert first["status"] == second["status"] == "FAILED_DOCUMENT_ISOLATED"
    assert first["failure_code"] == second["failure_code"] == "REPORT_CONTENT_REVIEW_FAIL"
    assert second["review_reason"]["severity"] == "P1"
    assert first["review_reference"]["sha256"] == second["review_reference"]["sha256"]
    assert calls == [batch.S18_PDF_SHA256, later_document]
    assert result["status"] == "COMPLETED_WITH_PER_DOCUMENT_STATES"
    assert result["research_only"] is True
    persisted = json.loads((state_root / "run-progress.json").read_text(encoding="utf-8"))
    persisted_documents = {item["document_id"]: item for item in persisted["documents"]}
    assert persisted_documents[text_source.FIRST_CONTENT_FAIL_PDF_SHA256]["failure_code"] == "REPORT_CONTENT_REVIEW_FAIL"
    assert persisted_documents[text_source.SECOND_CONTENT_FAIL_PDF_SHA256]["review_reference"]["verdict"] == "FAIL"
    assert persisted_documents[text_source.SECOND_CONTENT_FAIL_PDF_SHA256]["review_reason"]["severity"] == "P1"

    for doc_id, snapshots in old_bytes.items():
        doc_root = state_root / "documents" / doc_id
        assert (doc_root / "receipt.json").read_bytes() == snapshots["receipt"]
        assert (doc_root / "page-input.json").read_bytes() == snapshots["page_input"]
        assert (doc_root / "report.md").read_bytes() == snapshots["report"]
        assert not (doc_root / "progress.json").exists()

    # A post-review artifact mismatch changes only that document's classification.
    first_report = state_root / "documents" / text_source.FIRST_CONTENT_FAIL_PDF_SHA256 / "report.md"
    first_report.write_text("changed after review", encoding="utf-8")
    cannot_confirm = batch._isolate_known_report_content_failure(
        documents[1], state_root=state_root, manifest_sha=manifest_sha
    )
    still_failed = batch._isolate_known_report_content_failure(
        documents[2], state_root=state_root, manifest_sha=manifest_sha
    )
    assert cannot_confirm is not None
    assert cannot_confirm["status"] == "FAILED_DOCUMENT_ISOLATED"
    assert cannot_confirm["failure_code"] == "CANNOT_CONFIRM_REPORT_REVIEW_BINDING"
    assert cannot_confirm["review_reference"]["binding_status"] == "CANNOT_CONFIRM"
    assert still_failed is not None and still_failed["failure_code"] == "REPORT_CONTENT_REVIEW_FAIL"
    monkeypatch.setattr(batch, "REPORT_CANARY_REVIEW_DEFAULT", tmp_path / "missing-review.json")
    missing_review = batch._isolate_known_report_content_failure(
        documents[2], state_root=state_root, manifest_sha=manifest_sha
    )
    assert missing_review is not None
    assert missing_review["status"] == "FAILED_DOCUMENT_ISOLATED"
    assert missing_review["failure_code"] == "CANNOT_CONFIRM_REPORT_REVIEW_BINDING"
    assert missing_review["review_reference"]["binding_status"] == "CANNOT_CONFIRM"
    assert missing_review["review_reason"]["code"] == "REPORT_REVIEW_RECEIPT_UNAVAILABLE"


def _continuation_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int = 10):
    parent = tmp_path / "batches"
    parent.mkdir()
    prior_root = parent / "simple-20261018-r3"
    prior_root.mkdir()
    monkeypatch.setattr(batch, "DEFAULT_STATE_ROOT", prior_root)
    documents = []
    for index in range(count):
        digest = hashlib.sha256(f"continuation-document-{index}".encode()).hexdigest()
        documents.append({
            "document_id": digest,
            "pdf_sha256": digest,
            "pdf_bytes": index + 100,
            "local_pdf_path": f"/frozen/{digest}.pdf",
            "source_paths": [],
            "cache_candidates": [],
        })
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "schema": "v4.pdf_research_simple_batch.manifest.v1",
        "status": "FROZEN",
        "documents": documents,
    }), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    monkeypatch.setattr(batch, "EXPECTED_BATCH_MANIFEST_SHA256", manifest_sha)
    queue_root = prior_root / "queue"
    queue_root.mkdir()
    (queue_root / "queue-state.json").write_text(json.dumps({
        "schema": "v4.announcement-engine-queue/v1", "jobs": {}, "events": [],
    }), encoding="utf-8")
    progress_path = prior_root / "run-progress.json"
    progress_path.write_text(json.dumps({
        "schema": "v4.pdf_research_simple_batch.run_receipt.v1",
        "status": "STOPPED_GRACEFULLY",
        "manifest_sha256": manifest_sha,
        "documents": [],
    }), encoding="utf-8")
    plan = {
        "schema": batch.CONTINUATION_PLAN_SCHEMA,
        "continuation_id": "pilot10",
        "source_run_id": batch.CONTINUATION_SOURCE_RUN_ID,
        "manifest_sha256": manifest_sha,
        "prior_progress_path": str(progress_path),
        "prior_progress_sha256": hashlib.sha256(progress_path.read_bytes()).hexdigest(),
        "prior_progress_status": "STOPPED_GRACEFULLY",
        "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
        "expected_model_settings_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
        "observed_model_settings_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
        "state_root": str(parent / "continuation-pilot10"),
        "selected_documents": [
            {"document_id": row["document_id"], "prior_status": "UNPROCESSED", "source_sha256": row["pdf_sha256"]}
            for row in documents
        ],
        "one_time_recovery_limit": 1,
        "excluded_prior_statuses": sorted(batch.CONTINUATION_EXCLUDED_PRIOR_STATUSES),
        "research_only": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    plan_path = tmp_path / "continuation-plan.json"
    plan_path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
    return manifest_path, plan_path, plan, documents, parent / "continuation-pilot10"


def test_continuation_plan_only_validates_ten_unprocessed_without_writes_or_model_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, plan_path, _plan, _documents, state_root = _continuation_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(batch.local_model, "build_request_material", lambda *_a, **_kw: pytest.fail("settings read"))
    monkeypatch.setattr(batch.local_model, "inspect_local_api_identity", lambda: pytest.fail("API identity call"))
    monkeypatch.setattr(batch.local_model, "request_document_analysis", lambda **_kw: pytest.fail("inference call"))
    monkeypatch.setattr(batch, "_create_queue", lambda *_a, **_kw: pytest.fail("queue construction"))

    assert batch.main(["--manifest", str(manifest_path), "--continuation-plan", str(plan_path)]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PLAN_ONLY"
    assert result["selected_document_count"] == 10
    assert set(result["selected_prior_statuses"].values()) == {"UNPROCESSED"}
    assert result["execution"] == "NOT_RUN"
    assert not state_root.exists()


def test_tool_canary_plan_binds_one_failed_inventory_document_without_recovery_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, plan_path, plan, documents, _state_root = _continuation_fixture(
        tmp_path, monkeypatch, count=1
    )
    document = documents[0]
    document_id = str(document["document_id"])
    prior_progress_path = batch._continuation_prior_progress_path()
    prior_progress = json.loads(prior_progress_path.read_text(encoding="utf-8"))
    prior_progress["documents"] = [{"document_id": document_id, "status": "FAILED_NO_RETRY"}]
    prior_progress_path.write_text(json.dumps(prior_progress), encoding="utf-8")
    plan["prior_progress_sha256"] = hashlib.sha256(prior_progress_path.read_bytes()).hexdigest()
    plan["selected_documents"] = [{
        "document_id": document_id,
        "prior_status": "FAILED_NO_RETRY",
        "source_sha256": document_id,
        "tool_canary": {"inventory_sha256": "a" * 64},
    }]
    plan["continuation_id"] = "tool-canary"
    plan["state_root"] = str(batch.DEFAULT_STATE_ROOT.parent / "continuation-tool-canary")
    plan_path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
    validated_entries: list[tuple[dict, dict, dict]] = []

    def validate_canary(entry, selected_document, prior_row, queue_jobs):
        validated_entries.append((entry, selected_document, prior_row))
        assert queue_jobs == {}
        return {"inventory_sha256": "a" * 64}

    monkeypatch.setattr(batch, "_validate_fresh_tool_canary", validate_canary)
    _manifest, manifest_sha, loaded_documents = batch.load_manifest(manifest_path)
    validated = batch.validate_continuation_plan(
        plan_path,
        manifest_sha256=manifest_sha,
        documents=loaded_documents,
    )

    assert len(validated_entries) == 1
    assert validated["tool_canary_bindings"][document_id] == {"inventory_sha256": "a" * 64}
    assert validated["recovery_bindings"] == {}
    assert validated["selected_entries"][document_id]["tool_canary"]["inventory_sha256"] == "a" * 64


def _pre_model_tool_canary_evidence_fixture(tmp_path: Path) -> dict[str, object]:
    document_id = batch.TOOL_CANARY_DOCUMENT_ID
    state_root = tmp_path / "continuation-tool-canary-20261019-r2"
    source_failure = batch.TOOL_CANARY_PREMODEL_RETRY_FAILURE_CODE
    return {
        "document_id": document_id,
        "state_root": state_root,
        "plan": {
            "continuation_id": "tool-canary-20261019-r2",
            "state_root": str(state_root),
            "selected_documents": [{
                "document_id": document_id,
                "prior_status": "FAILED_NO_RETRY",
                "source_sha256": document_id,
                "tool_canary": {"page_input_sha256": batch.TOOL_CANARY_PAGE_INPUT_SHA256},
            }],
        },
        "run_progress": {
            "status": "COMPLETED_WITH_PER_DOCUMENT_STATES",
            "continuation_id": "tool-canary-20261019-r2",
            "continuation_plan_sha256": batch.TOOL_CANARY_PREMODEL_RETRY_PLAN_SHA256,
            "manifest_sha256": batch.EXPECTED_BATCH_MANIFEST_SHA256,
            "document_count": 1,
            "documents": [{
                "document_id": document_id,
                "continuation_id": "tool-canary-20261019-r2",
                "continuation_plan_sha256": batch.TOOL_CANARY_PREMODEL_RETRY_PLAN_SHA256,
                "status": "SOURCE_REPAIR_FAILED_NO_MODEL",
            }],
        },
        "document_progress": {
            "document_id": document_id,
            "status": "SOURCE_REPAIR_FAILED_NO_MODEL",
            "model_requests": 0,
        },
        "receipt": {
            "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
            "status": "SOURCE_REPAIR_FAILED_NO_MODEL",
            "document_id": document_id,
            "pdf_sha256": document_id,
            "manifest_sha256": batch.EXPECTED_BATCH_MANIFEST_SHA256,
            "page_input": {
                "path": str(state_root / "documents" / document_id / "page-input.json"),
                "sha256": batch.TOOL_CANARY_PREMODEL_RETRY_ARTIFACT_SHA256S[
                    f"documents/{document_id}/page-input.json"
                ],
            },
            "source": {
                "source_repair_status": "FAILED_UNSUPPORTED_GEOMETRY",
                "new_ocr_attempts_this_tick": 0,
                "ocr_invoked": False,
                "page_extraction_sources": [{"failure_code": source_failure}],
            },
        },
        "page_input": {
            "source": {"source_repair_status": "FAILED_UNSUPPORTED_GEOMETRY"},
            "pages": [{
                "page_number": 1,
                "status": "TEXT_UNAVAILABLE",
                "text": "",
                "text_characters": 0,
            }],
        },
        "failed_page": {
            "schema": text_source.SOURCE_REPAIR_SCHEMA,
            "pdf_sha256": document_id,
            "page_number": 1,
            "status": "SOURCE_REPAIR_UNSUPPORTED_GEOMETRY",
            "failure_code": source_failure,
            "attempts_used_for_page": 0,
        },
        "queue_state": None,
    }


def test_canary_retry_requires_exact_pre_model_failure_and_zero_work(
    tmp_path: Path,
) -> None:
    values = _pre_model_tool_canary_evidence_fixture(tmp_path)
    assert batch._pre_model_tool_canary_abort_is_retryable(**values)

    model_attempt = dict(values)
    model_attempt["document_progress"] = {**values["document_progress"], "model_requests": 1}
    assert not batch._pre_model_tool_canary_abort_is_retryable(**model_attempt)

    queue_claim = dict(values)
    queue_claim["queue_state"] = {"jobs": {"claimed": {"attempt_count": 1}}}
    assert not batch._pre_model_tool_canary_abort_is_retryable(**queue_claim)

    partial_analysis = dict(values)
    partial_analysis["receipt"] = {**values["receipt"], "chunks": [{"status": "SUCCEEDED"}]}
    assert not batch._pre_model_tool_canary_abort_is_retryable(**partial_analysis)

    repair_attempt = dict(values)
    repair_attempt["failed_page"] = {**values["failed_page"], "attempts_used_for_page": 1}
    assert not batch._pre_model_tool_canary_abort_is_retryable(**repair_attempt)


def test_tool_canary_requires_reconstructed_bound_original_page_input() -> None:
    evidence = {
        "page_input_path": str(batch.TOOL_CANARY_PAGE_INPUT_PATH),
        "page_input_sha256": batch.TOOL_CANARY_PAGE_INPUT_SHA256,
    }
    continuation = {"entry": {"tool_canary": evidence}}
    batch._assert_bound_tool_canary_page_input(
        batch.TOOL_CANARY_DOCUMENT_ID,
        continuation,
        batch.TOOL_CANARY_PAGE_INPUT_SHA256,
    )
    with pytest.raises(batch.BatchError, match="TOOL_CANARY_PAGE_INPUT_RECONSTRUCTION_MISMATCH"):
        batch._assert_bound_tool_canary_page_input(
            batch.TOOL_CANARY_DOCUMENT_ID,
            continuation,
            "0" * 64,
        )
    batch._assert_bound_tool_canary_page_input("a" * 64, None, "b" * 64)


def test_tool_canary_instruction_is_added_only_to_selected_chunk_request() -> None:
    page = _page(1, 1, "奥士康2025年四层板产品营收41.78亿元，营业收入55.30亿元，占比75.56%。")
    chunk = pdf_research.build_source_chunks("a" * 64, [page])[0]
    messages = batch._document_messages(
        {"document_id": "a" * 64},
        chunk,
        partial_source=False,
        tool_canary=True,
    )
    assert batch.TOOL_CANARY_INSTRUCTION in messages[-1]["content"]
    ordinary_messages = batch._document_messages(
        {"document_id": "a" * 64},
        chunk,
        partial_source=False,
    )
    assert batch.TOOL_CANARY_INSTRUCTION not in ordinary_messages[-1]["content"]


def test_ppi_partial_recovery_requires_prior_chunk_reuse_before_queue_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = batch.PPI_PARTIAL_RECOVERY_DOCUMENT_ID
    chunks = [
        pdf_research.SourceChunk(
            document_id,
            1,
            2,
            (pdf_research.SourceUnit("p1", 1, 0, 1, "fixture"),),
            batch.PPI_PARTIAL_RECOVERY_SUCCESS_CHUNK_SHA256,
        ),
        pdf_research.SourceChunk(
            document_id,
            2,
            2,
            (pdf_research.SourceUnit("p2", 2, 0, 1, "fixture"),),
            batch.PPI_PARTIAL_RECOVERY_FAILED_CHUNK_SHA256,
        ),
    ]
    prior_payload = {
        "article_id": batch.PPI_PARTIAL_RECOVERY_FAILED_PRIOR_ARTICLE_ID,
        "model_binding": {
            "model_settings_sha256": batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
            "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
        },
    }
    continuation = {
        "plan": {
            "continuation_id": "ppi-chunk2-recovery-20261019-r1",
            "manifest_sha256": batch.EXPECTED_BATCH_MANIFEST_SHA256,
            "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
            "expected_model_settings_sha256": batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        },
        "plan_sha256": "b" * 64,
        "entry": {
            "prior_status": "FAILED_NO_RETRY",
            "recovery": {
                "generation": 1,
                "prior_queue_idempotency_key": batch.PPI_PARTIAL_RECOVERY_FAILED_QUEUE_KEY,
                "prior_payload_sha256": batch.PPI_PARTIAL_RECOVERY_FAILED_PAYLOAD_SHA256,
                "prior_article_id": batch.PPI_PARTIAL_RECOVERY_FAILED_PRIOR_ARTICLE_ID,
                "prior_source_sha256": document_id,
                "prior_raw_sha256": batch.PPI_PARTIAL_RECOVERY_FAILED_RAW_SSE_SHA256,
            },
        },
        "recovery_binding": {"prior_payload": prior_payload},
        "recovery_target_reached": threading.Event(),
    }
    recovery_binding = {"prior_queue_root": tmp_path / "prior-queue"}
    monkeypatch.setattr(
        batch,
        "_document_chunk_request_material",
        lambda _document, chunk, **_kwargs: ([], b"{}", {"article_id": f"{document_id}:chunk:{chunk.chunk_index:06d}:{chunk.chunk_sha256}"}),
    )
    monkeypatch.setattr(batch, "_bind_continuation_payload", lambda payload, _continuation, **_kwargs: (dict(payload), False))
    read_calls: list[Path] = []

    def missing_prior_success(_queue, _payload, prior_queue_root, **_kwargs):
        read_calls.append(prior_queue_root)
        return None

    monkeypatch.setattr(batch, "_read_continuation_prior_outcome", missing_prior_success)

    with pytest.raises(batch.BatchError, match="PPI_PARTIAL_RECOVERY_SUCCESS_CHUNK_REUSE_NOT_VERIFIED"):
        batch._preflight_ppi_partial_chunk_recovery(
            {"document_id": document_id},
            chunks,
            prompt_document={"document_id": document_id},
            partial_source=False,
            binding={},
            page_input_sha256=batch.PPI_PARTIAL_RECOVERY_PAGE_INPUT_SHA256,
            page_count=10,
            queue=object(),
            continuation=continuation,
            recovery_binding=recovery_binding,
        )
    assert read_calls == [recovery_binding["prior_queue_root"]]
    assert not continuation["recovery_target_reached"].is_set()


def test_ppi_partial_recovery_only_rebinds_the_frozen_batch_runner_hash() -> None:
    prior = {
        "article_id": "fixture",
        "model_binding": {
            "source_sha256": {
                "ops/run_pdf_research_batch.py": batch.CONTINUATION_PRIOR_RUNNER_SHA256,
                "infrastructure/local_document_model.py": "a" * 64,
            },
            "model_settings_sha256": batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        },
    }
    current = json.loads(json.dumps(prior))
    current["model_binding"]["source_sha256"]["ops/run_pdf_research_batch.py"] = hashlib.sha256(
        Path(batch.__file__).resolve().read_bytes()
    ).hexdigest()
    assert batch._same_request_payload_ignoring_run_root(
        prior,
        current,
        allow_frozen_runner_source_rebind=True,
    )
    changed_other_source = json.loads(json.dumps(current))
    changed_other_source["model_binding"]["source_sha256"]["infrastructure/local_document_model.py"] = "b" * 64
    assert not batch._same_request_payload_ignoring_run_root(
        prior,
        changed_other_source,
        allow_frozen_runner_source_rebind=True,
    )
    changed_prior_runner = json.loads(json.dumps(prior))
    changed_prior_runner["model_binding"]["source_sha256"]["ops/run_pdf_research_batch.py"] = "c" * 64
    assert not batch._same_request_payload_ignoring_run_root(
        changed_prior_runner,
        current,
        allow_frozen_runner_source_rebind=True,
    )


def test_ppi_partial_recovery_rejects_changed_reconstructed_chunk_before_prior_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = batch.PPI_PARTIAL_RECOVERY_DOCUMENT_ID
    chunks = [
        pdf_research.SourceChunk(
            document_id,
            1,
            2,
            (pdf_research.SourceUnit("p1", 1, 0, 1, "fixture"),),
            "f" * 64,
        ),
        pdf_research.SourceChunk(
            document_id,
            2,
            2,
            (pdf_research.SourceUnit("p2", 2, 0, 1, "fixture"),),
            batch.PPI_PARTIAL_RECOVERY_FAILED_CHUNK_SHA256,
        ),
    ]
    monkeypatch.setattr(
        batch,
        "_read_continuation_prior_outcome",
        lambda *_args: pytest.fail("changed chunk must fail before the prior queue read"),
    )
    with pytest.raises(batch.BatchError, match="PPI_PARTIAL_RECOVERY_RECONSTRUCTED_CHUNKS_MISMATCH"):
        batch._preflight_ppi_partial_chunk_recovery(
            {"document_id": document_id},
            chunks,
            prompt_document={"document_id": document_id},
            partial_source=False,
            binding={},
            page_input_sha256=batch.PPI_PARTIAL_RECOVERY_PAGE_INPUT_SHA256,
            page_count=10,
            queue=object(),
            continuation={},
            recovery_binding={"prior_queue_root": tmp_path / "prior-queue"},
        )


@pytest.mark.parametrize("mutation, expected", [
    ("duplicate", "CONTINUATION_SELECTION_DUPLICATE_OR_INVALID"),
    ("outside", "CONTINUATION_SELECTION_OUTSIDE_MANIFEST"),
    ("source", "CONTINUATION_SOURCE_SHA_MISMATCH"),
    ("settings", "CONTINUATION_MODEL_SETTINGS_SHA_UNSUPPORTED"),
    ("success", "CONTINUATION_PRIOR_STATUS_EXCLUDED"),
])
def test_continuation_plan_fails_closed_on_scope_and_binding_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected: str,
) -> None:
    manifest_path, plan_path, plan, documents, _state_root = _continuation_fixture(tmp_path, monkeypatch)
    rows = plan["selected_documents"]
    if mutation == "duplicate":
        rows[1]["document_id"] = rows[0]["document_id"]
        rows[1]["source_sha256"] = rows[0]["source_sha256"]
    elif mutation == "outside":
        rows[0]["document_id"] = "f" * 64
    elif mutation == "source":
        rows[0]["source_sha256"] = "e" * 64
    elif mutation == "settings":
        plan["expected_model_settings_sha256"] = "c" * 64
        plan["observed_model_settings_sha256"] = "c" * 64
    elif mutation == "success":
        rows[0]["prior_status"] = "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    plan_path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
    _manifest, manifest_sha, loaded_documents = batch.load_manifest(manifest_path)
    assert len(loaded_documents) == len(documents)

    with pytest.raises(batch.BatchError, match=expected):
        batch.validate_continuation_plan(plan_path, manifest_sha256=manifest_sha, documents=loaded_documents)


def test_continuation_recovery_validates_raw_error_and_binds_generation_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, plan_path, plan, documents, _state_root = _continuation_fixture(tmp_path, monkeypatch, count=1)
    document = documents[0]
    document_id = str(document["document_id"])
    article_id = f"{document_id}:chunk:000001:{'a' * 64}"
    prior_state_root = batch.DEFAULT_STATE_ROOT.parent / "continuation-prior-test"
    prior_state_root.mkdir()
    prior_doc_root = prior_state_root / "documents" / document_id
    prior_doc_root.mkdir(parents=True)
    page_input_value = {
        "schema": "v4.pdf_research_simple_batch.page_input.v1",
        "manifest_sha256": plan["manifest_sha256"],
        "document_id": document_id,
        "pdf_sha256": document_id,
        "pages": [{"page_number": 1, "text": "fixture", "text_sha256": _sha("fixture")}],
    }
    page_input_path = prior_doc_root / "page-input.json"
    page_input_path.write_text(json.dumps(page_input_value, sort_keys=True), encoding="utf-8")
    page_input_sha = _sha(page_input_path.read_text(encoding="utf-8"))
    old_payload = {
        "date": "2026-10-18",
        "market": "PDF_RESEARCH",
        "article_id": article_id,
        "model_id": batch.local_model.MODEL_ID,
        "source_sha256": document_id,
        "source_document_id": document_id,
        "source_text_sha256": "a" * 64,
        "stage": "simple_batch_document_chunk_v1",
        "model_binding": {
            "model_settings_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
            "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
            "evidence_root": str(prior_state_root / "evidence"),
        },
        "pdf_tool_binding": {
            "action_prompt_sha256": _sha(pdf_research_tools.ACTION_SYSTEM_PROMPT),
            "page_input_sha256": page_input_sha,
            "page_count": 1,
        },
        "evidence_root": str(prior_state_root / "evidence"),
    }
    identity = {name: old_payload.get(name) for name in ("date", "market", "article_id", "model_id")}
    key = hashlib.sha256(local_model.canonical_json(identity)).hexdigest()
    input_raw = local_model.canonical_json(old_payload)
    payload_sha = hashlib.sha256(input_raw).hexdigest()
    raw = b'{"error":{"code":"prefill_memory_exceeded"}}'
    raw_sha = hashlib.sha256(raw).hexdigest()
    queue_root = prior_state_root / "queue"
    job_root = queue_root / "jobs" / key
    job_root.mkdir(parents=True)
    (job_root / "input.json").write_bytes(input_raw)
    request_value = {
        "model": batch.local_model.MODEL_ID,
        "max_tokens": 32768,
        "temperature": 0.0,
        "stream": True,
        "messages": [{"role": "user", "content": "fixture prompt"}],
    }
    request_path = prior_state_root / "evidence" / "streams" / key / "attempt-0001" / "round-01.request-input.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps(request_value, sort_keys=True), encoding="utf-8")
    raw_path = request_path.parent / "round-01.raw.sse"
    raw_path.write_bytes(raw)
    request_sha = _sha(request_path.read_text(encoding="utf-8"))
    stream_receipt = {
        "status": "FAILED",
        "idempotency_key": key,
        "model_id": batch.local_model.MODEL_ID,
        "model_settings_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
        "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
        "request_settings_bindings": [{
            "status": "MATCH",
            "matches_expected": True,
            "source": "local_disk_read_immediately_before_http_post",
            "bindings": [
                {
                    "setting_name": "runtime_settings",
                    "expected_sha256": batch.EXPECTED_RUNTIME_SHA256,
                    "observed_sha256": batch.EXPECTED_RUNTIME_SHA256,
                    "matches_expected": True,
                    "status": "MATCH",
                    "source": "local_disk_read_immediately_before_http_post",
                },
                {
                    "setting_name": "model_settings",
                    "expected_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
                    "observed_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
                    "matches_expected": True,
                    "status": "MATCH",
                    "source": "local_disk_read_immediately_before_http_post",
                },
            ],
        }],
        "rounds": [{"status": "FAILED", "request_input_sha256": request_sha, "raw_sse_sha256": raw_sha}],
    }
    stream_path = request_path.parent / "stream-receipt.json"
    stream_path.write_text(json.dumps(stream_receipt, sort_keys=True), encoding="utf-8")
    queue_item = {
        "idempotency_key": key,
        "queue_id": "v4-pdf-simple-batch",
        "model_id": batch.local_model.MODEL_ID,
        "identity": identity,
        "status": "FAILED",
        "attempt_count": 1,
        "max_attempts": 1,
        "queue_policy": {"max_attempts": 1, "max_body_bytes": None},
        "payload_sha256": payload_sha,
        "input_path": f"jobs/{key}/input.json",
        "raw_path": None,
        "raw_sha256": None,
        "attempts": [{"number": 1, "status": "FAILED", "error": {"code": "EXECUTOR_ERROR"}, "raw_path": None, "raw_sha256": None}],
    }
    queue_state_path = queue_root / "queue-state.json"
    _write_queue_state(queue_state_path, {key: queue_item})
    receipt = {
        "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
        "status": "FAILED_NO_RETRY",
        "manifest_sha256": plan["manifest_sha256"],
        "document_id": document_id,
        "pdf_sha256": document_id,
        "page_input": {"path": str(page_input_path), "sha256": page_input_sha},
        "chunks": [{"status": "FAILED_NO_RETRY", "chunk_index": 1, "chunk_sha256": "a" * 64, "queue_item": {"idempotency_key": key}}],
        "synthesis": [],
        "report": None,
    }
    receipt_path = prior_doc_root / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True), encoding="utf-8")
    document_progress = {
        "document_id": document_id,
        "pdf_sha256": document_id,
        "manifest_sha256": plan["manifest_sha256"],
        "page_input_sha256": page_input_sha,
        "chunk_total": 1,
        "chunk_states": {"1": "FAILED_NO_RETRY"},
        "model_requests": 1,
        "status": "FAILED_NO_RETRY",
    }
    (prior_doc_root / "progress.json").write_text(json.dumps(document_progress, sort_keys=True), encoding="utf-8")
    prior_plan = {
        "schema": batch.CONTINUATION_PLAN_SCHEMA,
        "continuation_id": "prior-test",
        "source_run_id": batch.CONTINUATION_SOURCE_RUN_ID,
        "manifest_sha256": plan["manifest_sha256"],
        "state_root": str(prior_state_root),
        "runtime_settings_sha256": batch.EXPECTED_RUNTIME_SHA256,
        "expected_model_settings_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
        "selected_documents": [{"document_id": document_id, "source_sha256": document_id, "prior_status": "UNPROCESSED"}],
    }
    prior_plan_path = prior_state_root / "continuation-plan.json"
    prior_plan_path.write_text(json.dumps(prior_plan, sort_keys=True), encoding="utf-8")
    prior_run_progress = {
        "schema": "v4.pdf_research_simple_batch.run_receipt.v1",
        "status": "COMPLETED_WITH_PER_DOCUMENT_STATES",
        "continuation_id": "prior-test",
        "continuation_plan_sha256": _sha(prior_plan_path.read_text(encoding="utf-8")),
        "manifest_sha256": plan["manifest_sha256"],
        "queue_root": str(queue_root),
        "documents": [{"document_id": document_id, "status": "FAILED_NO_RETRY"}],
    }
    prior_run_path = prior_state_root / "run-progress.json"
    prior_run_path.write_text(json.dumps(prior_run_progress, sort_keys=True), encoding="utf-8")
    artifact_paths = {
        "continuation-plan.json": prior_plan_path,
        "run-progress.json": prior_run_path,
        f"documents/{document_id}/progress.json": prior_doc_root / "progress.json",
        f"documents/{document_id}/receipt.json": receipt_path,
        f"documents/{document_id}/page-input.json": page_input_path,
        "queue/queue-state.json": queue_state_path,
        f"queue/jobs/{key}/input.json": job_root / "input.json",
        f"evidence/streams/{key}/attempt-0001/stream-receipt.json": stream_path,
        f"evidence/streams/{key}/attempt-0001/round-01.request-input.json": request_path,
        f"evidence/streams/{key}/attempt-0001/round-01.raw.sse": raw_path,
    }
    prior_artifact_sha = {relative: _sha(path.read_text(encoding="utf-8")) if path.suffix == ".json" else _sha(path.read_bytes().decode("utf-8")) for relative, path in artifact_paths.items()}
    recovery = {
        "generation": 1,
        "prior_document_receipt_sha256": prior_artifact_sha[f"documents/{document_id}/receipt.json"],
        "prior_queue_idempotency_key": key,
        "prior_payload_sha256": payload_sha,
        "prior_article_id": article_id,
        "prior_source_sha256": document_id,
        "prior_raw_sha256": raw_sha,
        "prior_state_root": str(prior_state_root),
        "prior_artifact_sha256": prior_artifact_sha,
    }
    progress_path = batch.DEFAULT_STATE_ROOT / "run-progress.json"
    progress_path.write_text(json.dumps({
        "schema": "v4.pdf_research_simple_batch.run_receipt.v1",
        "status": "STOPPED_GRACEFULLY",
        "manifest_sha256": plan["manifest_sha256"],
        "documents": [{"document_id": document_id, "status": "FAILED_NO_RETRY", "receipt_path": str(receipt_path)}],
    }), encoding="utf-8")
    plan["prior_progress_sha256"] = hashlib.sha256(progress_path.read_bytes()).hexdigest()
    plan["selected_documents"] = [{
        "document_id": document_id,
        "prior_status": "FAILED_NO_RETRY",
        "source_sha256": document_id,
        "recovery": recovery,
    }]
    plan["state_root"] = str(batch.DEFAULT_STATE_ROOT.parent / f"recovery-{key}")
    plan_path.write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
    _manifest, manifest_sha, loaded_documents = batch.load_manifest(manifest_path)

    validated = batch.validate_continuation_plan(plan_path, manifest_sha256=manifest_sha, documents=loaded_documents)
    context = {
        "plan": plan,
        "plan_sha256": validated["plan_sha256"],
        "entry": plan["selected_documents"][0],
        "recovery_binding": validated["recovery_bindings"][document_id],
        "recovery_target_reached": threading.Event(),
    }
    current_payload = dict(old_payload)
    current_payload["evidence_root"] = "/continuation/evidence"
    current_binding = dict(current_payload["model_binding"])
    current_binding["evidence_root"] = "/continuation/evidence"
    current_payload["model_binding"] = current_binding
    bound, is_target = batch._bind_continuation_payload(current_payload, context)

    assert is_target
    assert bound["article_id"] == f"{article_id}:recovery:1"
    assert bound["continuation"]["recovery_of"]["generation"] == 1
    assert context["recovery_target_reached"].is_set()
    assert batch._continuation_recovery_raw_has_exact_error(raw)
    assert not batch._continuation_recovery_raw_has_exact_error(b'{"error":{"message":"prefill_memory_exceeded"}}')
    assert not batch._continuation_recovery_raw_has_exact_error(b"message says prefill_memory_exceeded")
    assert context["recovery_binding"]["prior_queue_root"] == queue_root


    class FakeQueue:
        queue_id = "v4-pdf-simple-batch"
        model_id = batch.local_model.MODEL_ID
        max_attempts = 1
        state_root = tmp_path / "continuation"

        def enqueue(self, payload):
            self.payload = dict(payload)
            return {"status": "PENDING", "idempotency_key": "9" * 64}

        def run_next(self, executor, _validator, **_kwargs):
            self.raw = executor(SimpleNamespace(model_id=self.model_id, payload=self.payload))
            return {"status": "SUCCEEDED", "attempt_count": 1, "idempotency_key": "9" * 64}

    fake_queue = FakeQueue()
    monkeypatch.setattr(batch, "_read_r1_success", lambda *_a, **_kw: None)
    monkeypatch.setattr(batch, "_queue_read_result", lambda *_a, **_kw: {"analysis_markdown": "fixture"})
    result = batch._perform_request(
        fake_queue,
        bound,
        [{"role": "user", "content": "fixture"}],
        binding=bound["model_binding"],
        identity={"status": "MATCH", "expected_model_id": batch.local_model.MODEL_ID},
        identity_reader=lambda: {"status": "MATCH", "expected_model_id": batch.local_model.MODEL_ID},
        priority_reader=lambda: {"status": "ALLOW"},
        request_fn=lambda **_kwargs: "fixture response",
        sleep_fn=lambda _seconds: None,
        tool_context={"page_input_sha256": page_input_sha, "pages": [{"text": "fixture"}]},
    )
    assert fake_queue.max_attempts == 1
    assert fake_queue.payload["article_id"] == f"{article_id}:recovery:1"
    assert fake_queue.payload["continuation"]["recovery_of"]["prior_idempotency_key"] == key
    assert result["status"] == "SUCCEEDED"

    tampered_plan = dict(plan)
    tampered_selection = dict(plan["selected_documents"][0])
    tampered_recovery = dict(tampered_selection["recovery"])
    tampered_hashes = dict(tampered_recovery["prior_artifact_sha256"])
    tampered_hashes["queue/queue-state.json"] = "f" * 64
    tampered_recovery["prior_artifact_sha256"] = tampered_hashes
    tampered_selection["recovery"] = tampered_recovery
    tampered_plan["selected_documents"] = [tampered_selection]
    plan_path.write_text(json.dumps(tampered_plan, sort_keys=True), encoding="utf-8")
    with pytest.raises(batch.BatchError, match="CONTINUATION_RECOVERY_ARTIFACT_SHA_MISMATCH"):
        batch.validate_continuation_plan(plan_path, manifest_sha256=manifest_sha, documents=loaded_documents)


def test_continuation_recovery_requires_exact_pre_post_settings_bindings() -> None:
    source = "local_disk_read_immediately_before_http_post"
    receipt = {
        "request_settings_bindings": [{
            "status": "MATCH",
            "matches_expected": True,
            "source": source,
            "bindings": [
                {
                    "setting_name": "runtime_settings",
                    "expected_sha256": batch.EXPECTED_RUNTIME_SHA256,
                    "observed_sha256": batch.EXPECTED_RUNTIME_SHA256,
                    "matches_expected": True,
                    "status": "MATCH",
                    "source": source,
                },
                {
                    "setting_name": "model_settings",
                    "expected_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
                    "observed_sha256": batch.EXPECTED_MODEL_SETTINGS_SHA256,
                    "matches_expected": True,
                    "status": "MATCH",
                    "source": source,
                },
            ],
        }],
    }
    assert batch._continuation_recovery_request_settings_confirmed(
        receipt,
        expected_model_settings_sha256=batch.EXPECTED_MODEL_SETTINGS_SHA256,
    )

    changed_observation = json.loads(json.dumps(receipt))
    changed_observation["request_settings_bindings"][0]["bindings"][1]["observed_sha256"] = "f" * 64
    assert not batch._continuation_recovery_request_settings_confirmed(
        changed_observation,
        expected_model_settings_sha256=batch.EXPECTED_MODEL_SETTINGS_SHA256,
    )

    missing_runtime = json.loads(json.dumps(receipt))
    missing_runtime["request_settings_bindings"][0]["bindings"].pop(0)
    assert not batch._continuation_recovery_request_settings_confirmed(
        missing_runtime,
        expected_model_settings_sha256=batch.EXPECTED_MODEL_SETTINGS_SHA256,
    )


def test_continuation_recovery_recognizes_only_typed_terminal_sse_prefill_error() -> None:
    import json

    empty_choice_frames = [
        {
            "id": "synthetic-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "synthetic-model",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
        },
        {
            "id": "synthetic-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "synthetic-model",
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        },
    ]
    error_frame = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "code": "prefill_memory_exceeded",
            "omlx_code": "prefill_memory_exceeded",
            "estimated_bytes": 3,
            "limit_bytes": 2,
        },
    }

    def as_sse(frames: list[dict[str, object]]) -> bytes:
        return b"".join(b"data: " + json.dumps(frame, separators=(",", ":")).encode() + b"\n\n" for frame in frames) + b"data: [DONE]\n\n"

    valid = as_sse([*empty_choice_frames, error_frame])
    assert batch._continuation_recovery_raw_has_exact_error(valid)

    with_model_text = as_sse([
        {**empty_choice_frames[0], "choices": [{"index": 0, "delta": {"role": "assistant", "content": "prefill_memory_exceeded"}, "finish_reason": None}]},
        error_frame,
    ])
    assert not batch._continuation_recovery_raw_has_exact_error(with_model_text)

    nested_model_text = as_sse([{
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": {"content": json.dumps(error_frame)}, "finish_reason": None}],
    }])
    assert not batch._continuation_recovery_raw_has_exact_error(nested_model_text)

    unrelated_error = as_sse([{**error_frame, "error": {**error_frame["error"], "code": "invalid_request_error"}}])
    assert not batch._continuation_recovery_raw_has_exact_error(unrelated_error)
    untyped_error = as_sse([{**error_frame, "type": "message"}])
    assert not batch._continuation_recovery_raw_has_exact_error(untyped_error)
    missing_done = valid.removesuffix(b"data: [DONE]\n\n")
    assert not batch._continuation_recovery_raw_has_exact_error(missing_done)
    malformed = b"data: {\"type\":\"error\",\"error\":\n\ndata: [DONE]\n\n"
    assert not batch._continuation_recovery_raw_has_exact_error(malformed)

# Admission is a separate, real fail-closed boundary; the earlier synthetic
# prepared fixtures intentionally isolate it when testing unrelated old logic.
@pytest.fixture
def analysis_fixture(tmp_path, monkeypatch):
    from ops import run_pdf_research_remaining_once as active_dispatcher
    root = tmp_path / 'admission'; root.mkdir()
    selection = root / 'execution-selection18.json'
    monkeypatch.setattr(batch, 'ANALYSIS_ROOT', root)
    monkeypatch.setattr(batch, 'ANALYSIS_SELECTION_PATH', selection)
    monkeypatch.setattr(batch, 'ANALYSIS_REVIEW_PATH', root / 'canary-content-review.json')
    monkeypatch.setattr(active_dispatcher, 'AUTHORIZATION_PATH', root / 'authorization.json')
    monkeypatch.setattr(active_dispatcher, 'EVIDENCE_ROOT', root / 'journal')
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + '\n')
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    rows = []
    ids = [batch.ANALYSIS_CANARY_ID] + [f'{i:064x}' for i in range(1, 18)]
    for did in ids:
        receipt = write(root / did / 'document.json', {'status':'READY','document_id':did,'pdf_sha256':did})
        page_input = write(root / did / 'page-input.json', {'document_id':did,'pages':[{'text':'research body'}]})
        rows.append({'document_id':did, 'prepared_receipt':receipt, 'page_input':page_input,
                     'prior_status':'UNPROCESSED','source_or_content_unverified':False,
                     'reviewer_primary_type':'券商/研究机构研究'})
    base = write(root / 'preflight-selection.json', {'eligible_documents':rows})
    monkeypatch.setattr(batch, 'ANALYSIS_BASE_SELECTION_SHA256', base['sha256'])
    classification = write(root / 'classification.json', {'verdict':'PASS'})
    monkeypatch.setattr(batch, 'ANALYSIS_CLASSIFICATION_REVIEW_PATH', Path(classification['path']))
    monkeypatch.setattr(batch, 'ANALYSIS_CLASSIFICATION_REVIEW_SHA256', classification['sha256'])
    value = {'schema':batch.ANALYSIS_SCHEMA,'status':'ROOT_ADOPTED',
             'parent_manifest_sha256':batch.EXPECTED_BATCH_MANIFEST_SHA256,
             'prepared_text_manifest_sha256':'f'*64,'canary_document_id':batch.ANALYSIS_CANARY_ID,'documents':rows}
    reference = write(selection, value)
    auth = {'analysis_admission':reference,'prepared_text_manifest_sha256':'f'*64}
    auth_ref = write(active_dispatcher.AUTHORIZATION_PATH, auth)
    context = {'authorization':auth,'authorization_sha256':auth_ref['sha256']}
    monkeypatch.setattr(batch, 'verify_analysis_runtime', lambda *a, **k: None)
    return SimpleNamespace(root=root,selection=selection,value=value,reference=reference,context=context,
                           write=write,dispatcher=active_dispatcher,rows=rows)


def _load_test_admission(f):
    return batch.load_analysis_admission(f.selection, f.reference['sha256'], prepared_sha256='f'*64,
                                         authorization_context=f.context)


def test_analysis_missing_selection_stops_before_state_creation(tmp_path):
    target = tmp_path / 'must-not-exist'
    with pytest.raises(batch.BatchError, match='ANALYSIS_ADMISSION_REQUIRED'):
        batch.run_batch(state_root=target, prepared_text_manifest_sha256='f'*64)
    assert not target.exists()


def test_analysis_real_loader_limits_initial_phase_to_canary(analysis_fixture):
    admission = _load_test_admission(analysis_fixture)
    assert len(admission['documents']) == 18
    assert admission['allowed_ids'] == [batch.ANALYSIS_CANARY_ID]
    batch.guard_analysis_document(admission, batch.ANALYSIS_CANARY_ID)
    with pytest.raises(batch.BatchError, match='NOT_ADMITTED'):
        batch.guard_analysis_document(admission, analysis_fixture.rows[1]['document_id'])


@pytest.mark.parametrize('field,wrong', [('prior_status','FAILED_NO_RETRY'),('reviewer_primary_type','新闻/资讯解读'),
                                         ('source_or_content_unverified',True)])
def test_analysis_tampered_admission_cannot_expand_accepted_form(analysis_fixture, field, wrong):
    f = analysis_fixture
    f.value['documents'][1][field] = wrong
    f.reference.update(f.write(f.selection, f.value))
    f.context['authorization']['analysis_admission'] = dict(f.reference)
    with pytest.raises(batch.BatchError, match='ELIGIBILITY'):
        _load_test_admission(f)


def test_analysis_wrong_final_manifest_or_root_selection_rejected(analysis_fixture):
    f = analysis_fixture
    with pytest.raises(batch.BatchError, match='BINDING'):
        batch.load_analysis_admission(f.selection, f.reference['sha256'], prepared_sha256='0'*64, authorization_context=f.context)
    f.context['authorization']['analysis_admission'] = {'path':str(f.selection),'sha256':'0'*64}
    with pytest.raises(batch.BatchError, match='BINDING'):
        _load_test_admission(f)


def test_analysis_source_or_authorization_drift_stops_before_dispatch(analysis_fixture):
    f = analysis_fixture; admission = _load_test_admission(f)
    path = Path(f.rows[0]['page_input']['path']); original = path.read_bytes(); path.write_bytes(b'changed')
    with pytest.raises(batch.BatchError, match='REFERENCE_SHA'):
        batch.guard_analysis_document(admission, batch.ANALYSIS_CANARY_ID)
    path.write_bytes(original)
    f.dispatcher.AUTHORIZATION_PATH.write_bytes(b'changed')
    with pytest.raises(batch.BatchError, match='AUTHORIZATION_DRIFT'):
        batch.guard_analysis_document(admission, batch.ANALYSIS_CANARY_ID)


def test_analysis_only_bound_independent_complete_canary_opens_remaining(analysis_fixture):
    f = analysis_fixture
    state = f.root / 'state'; doc = state / 'documents' / batch.ANALYSIS_CANARY_ID
    receipt = f.write(doc / 'receipt.json', {'status':'MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING'})
    report_path = doc / 'report.md'; report_path.write_text('事实 [第1页]\n预测 [第2页]\n风险 [第3页]\n')
    report = {'path':str(report_path),'sha256':hashlib.sha256(report_path.read_bytes()).hexdigest()}
    event = {'event':'reconciled','document_id':batch.ANALYSIS_CANARY_ID,'status':'MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING',
             'receipt_path':receipt['path'],'receipt_sha256':receipt['sha256'],'state_root':str(state)}
    journal = f.dispatcher.EVIDENCE_ROOT / 'dispatch.jsonl'; journal.parent.mkdir(); journal.write_text(json.dumps(event)+'\n')
    review = {'schema':'v4.pdf_research.canary_content_review.v1','status':'REPORT_CONTENT_PASS',
              'reviewer':'/root/pdf_model_analysis_reviewer','selection_sha256':f.reference['sha256'],
              'document_id':batch.ANALYSIS_CANARY_ID,'page_input':f.rows[0]['page_input'],
              'receipt':receipt,'report':report,'source_pages_reviewed':[1,2,3]}
    with pytest.raises(batch.BatchError, match='CONTENT_REVIEW_REQUIRED'):
        _load_test_admission(f)
    f.write(batch.ANALYSIS_REVIEW_PATH, {**review,'status':'FAIL'})
    with pytest.raises(batch.BatchError, match='CONTENT_PASS'):
        _load_test_admission(f)
    f.write(batch.ANALYSIS_REVIEW_PATH, review)
    admission = _load_test_admission(f)
    assert admission['allowed_ids'] == [r['document_id'] for r in f.rows]
    report_path.write_text('tampered')
    with pytest.raises(batch.BatchError, match='REPORT_MISMATCH'):
        _load_test_admission(f)


def test_analysis_direct_child_cannot_replay_completed_or_unowned_plan(analysis_fixture):
    f = analysis_fixture; path = f.dispatcher.EVIDENCE_ROOT / 'dispatch.jsonl'
    with pytest.raises(batch.BatchError, match='RETAINED_DISPATCH'):
        batch.verify_analysis_dispatch(batch.ANALYSIS_CANARY_ID, 'a'*64)
    path.parent.mkdir()
    events = [{'event':'plan_created','document_id':batch.ANALYSIS_CANARY_ID,'plan_sha256':'a'*64},
              {'event':'dispatch_intent','document_id':batch.ANALYSIS_CANARY_ID,'plan_sha256':'a'*64}]
    path.write_text(''.join(json.dumps(e)+'\n' for e in events))
    batch.verify_analysis_dispatch(batch.ANALYSIS_CANARY_ID,'a'*64)
    with pytest.raises(batch.BatchError, match='NOT_CURRENT'):
        batch.verify_analysis_dispatch(batch.ANALYSIS_CANARY_ID,'b'*64)
    with path.open('a') as stream: stream.write(json.dumps({**events[-1],'event':'reconciled','status':'COMPLETE'})+'\n')
    with pytest.raises(batch.BatchError, match='NOT_CURRENT'):
        batch.verify_analysis_dispatch(batch.ANALYSIS_CANARY_ID,'a'*64)


def test_analysis_settings_drift_under_model_lock_consumes_zero_attempt(monkeypatch):
    calls=[]
    def guard(*a, **k):
        calls.append('guard')
        if len(calls)==2: raise batch.BatchError('ANALYSIS_RUNTIME_DRIFT')
    monkeypatch.setattr(batch,'guard_analysis_document',guard)
    monkeypatch.setattr(batch,'verify_analysis_dispatch',lambda *a:None)
    monkeypatch.setattr(batch,'verify_analysis_plan_runtime',lambda *a:None)
    monkeypatch.setattr(batch,'_read_r1_success',lambda *a,**k:None)
    class Queue:
        attempts=0
        def enqueue(self,p):return {'status':'PENDING','idempotency_key':'k'}
        def _claim_next_locked(self,state,allowed_keys=None):self.attempts+=1
        def run_next(self,*a,**k):self._claim_next_locked({}, {'k'});raise AssertionError('POST must not execute')
    q=Queue(); original=q._claim_next_locked
    with pytest.raises(batch.BatchError,match='RUNTIME_DRIFT'):
        batch._perform_request(q,{'source_document_id':batch.ANALYSIS_CANARY_ID},[{'role':'user','content':'body'}],
                               binding={},identity={'status':'MATCH','expected_model_id':local_model.MODEL_ID},
                               identity_reader=lambda:{},priority_reader=lambda:{'status':'ALLOW'},request_fn=lambda **k:'',
                               sleep_fn=lambda _:None,analysis_admission={})
    assert q.attempts == 0
    assert q._claim_next_locked == original


def test_analysis_busy_shared_lock_does_not_claim_or_post(monkeypatch):
    monkeypatch.setattr(batch,'guard_analysis_document',lambda *a,**k:None)
    monkeypatch.setattr(batch,'verify_analysis_dispatch',lambda *a:None)
    monkeypatch.setattr(batch,'verify_analysis_plan_runtime',lambda *a:None)
    monkeypatch.setattr(batch,'_read_r1_success',lambda *a,**k:None)
    class ModelSlotBusy(Exception): pass
    class Queue:
        attempts=0
        def enqueue(self,p):return {'status':'PENDING','idempotency_key':'k'}
        def _claim_next_locked(self,state,allowed_keys=None):self.attempts+=1
        def run_next(self,*a,**k):raise ModelSlotBusy()
    q=Queue()
    out=batch._perform_request(q,{'source_document_id':batch.ANALYSIS_CANARY_ID},[{'role':'user','content':'body'}],
                               binding={},identity={'status':'MATCH','expected_model_id':local_model.MODEL_ID},
                               identity_reader=lambda:{},priority_reader=lambda:{'status':'ALLOW'},request_fn=lambda **k:'',
                               sleep_fn=lambda _:None,analysis_admission={})
    assert out['status']=='DEFERRED_MODEL_LOCK_BUSY' and q.attempts==0 and out['attempted'] is False


def test_analysis_runtime_adopts_only_exact_existing_memory_transition(tmp_path, monkeypatch):
    settings_root=tmp_path/'runtime'/'omlx-state';settings_root.mkdir(parents=True)
    def ref(path,value):
        path.write_text(json.dumps(value,sort_keys=True)+'\n');return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    memory={'prefill_memory_guard':True,'memory_guard_custom_ceiling_gb':96.0}
    settings={'memory':memory,'sampling':{'temperature':1.0}}
    sr=ref(settings_root/'settings.json',settings); mr=ref(settings_root/'model_settings.json',{'model':'retained'})
    launcher=settings_root.parent/'start_omlx.sh';launcher.write_text('# existing launcher\n')
    transition={'status':'APPLIED_HEALTH_CEILING_VERIFIED','settings_before_sha256':batch.EXPECTED_RUNTIME_SHA256,
                'settings_after_sha256':sr['sha256'],'memory_after':memory,
                'non_memory_settings_sha256':hashlib.sha256(local_model.canonical_json({'sampling':settings['sampling']})).hexdigest(),
                'launcher_sha256':hashlib.sha256(launcher.read_bytes()).hexdigest()}
    tr=ref(tmp_path/'transition.json',transition)
    proof={'schema':'v4.pdf_research.runtime_adoption.v1','status':'ROOT_ADOPTED','identity_runtime_sha256':batch.EXPECTED_RUNTIME_SHA256,
           'execution_runtime_sha256':sr['sha256'],'model_settings_sha256':mr['sha256'],'transition':tr}
    pr=ref(tmp_path/'proof.json',proof)
    monkeypatch.setattr(batch,'ANALYSIS_RUNTIME_SHA256',sr['sha256'])
    monkeypatch.setattr(batch,'ANALYSIS_RUNTIME_RECEIPT_SHA256',tr['sha256'])
    monkeypatch.setattr(batch,'CONTINUATION_CANDIDATE_SETTINGS_SHA256',mr['sha256'])
    monkeypatch.setattr(local_model,'load_shared_modules',lambda:SimpleNamespace(runner=SimpleNamespace(OMLX_SETTINGS_PATH=Path(sr['path']),OMLX_MODEL_SETTINGS_PATH=Path(mr['path']))))
    admission={'value':{'runtime_adoption':pr}}
    batch.verify_analysis_runtime(admission)
    Path(sr['path']).write_text(json.dumps({**settings,'sampling':{'temperature':0.5}}))
    with pytest.raises(batch.BatchError,match='REFERENCE_SHA'):
        batch.verify_analysis_runtime(admission)


@pytest.mark.parametrize('execution_sha',[None,'0'*64,batch.EXPECTED_RUNTIME_SHA256])
def test_analysis_plan_missing_or_forged_execution_runtime_rejects_before_adoption(monkeypatch,execution_sha):
    calls=[]
    monkeypatch.setattr(batch,'verify_analysis_runtime',lambda *a:calls.append('adoption'))
    plan={} if execution_sha is None else {'execution_runtime_settings_sha256':execution_sha}
    with pytest.raises(batch.BatchError,match='PLAN_EXECUTION_RUNTIME_MISMATCH'):
        batch.verify_analysis_plan_runtime(plan,{})
    assert calls==[]


def test_analysis_plan_current_execution_field_still_requires_actual_adoption_and_settings(monkeypatch):
    def drift(*args):raise batch.BatchError('ANALYSIS_RUNTIME_DRIFT')
    monkeypatch.setattr(batch,'verify_analysis_runtime',drift)
    with pytest.raises(batch.BatchError,match='RUNTIME_DRIFT'):
        batch.verify_analysis_plan_runtime({'execution_runtime_settings_sha256':batch.ANALYSIS_RUNTIME_SHA256},{})
    calls=[];monkeypatch.setattr(batch,'verify_analysis_runtime',lambda *a:calls.append(a))
    batch.verify_analysis_plan_runtime({'execution_runtime_settings_sha256':batch.ANALYSIS_RUNTIME_SHA256},{'value':'adopted'})
    assert len(calls)==1


def test_analysis_payload_records_identity_and_execution_runtime_separately():
    plan={'continuation_id':'new','manifest_sha256':'a'*64,'runtime_settings_sha256':batch.EXPECTED_RUNTIME_SHA256,
          'execution_runtime_settings_sha256':batch.ANALYSIS_RUNTIME_SHA256,'expected_model_settings_sha256':batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256}
    payload,_=batch._bind_continuation_payload({}, {'entry':{'prior_status':'UNPROCESSED'},'plan':plan,'plan_sha256':'b'*64})
    assert payload['continuation']['runtime_settings_sha256']==batch.EXPECTED_RUNTIME_SHA256
    assert payload['continuation']['execution_runtime_settings_sha256']==batch.ANALYSIS_RUNTIME_SHA256


def test_pilot_erratum_preserves_raw_fail_and_checks_display_bytes(analysis_fixture,monkeypatch):
    f=analysis_fixture
    state=f.root/'state';doc=state/'documents'/batch.ANALYSIS_CANARY_ID
    receipt=f.write(doc/'receipt.json',{'status':'MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING'})
    report=doc/'report.md';report.write_text('原始评级遗漏期限；其他数据保留 [第1页]\n')
    report_ref={'path':str(report),'sha256':hashlib.sha256(report.read_bytes()).hexdigest()}
    original={'schema':'v4.pdf_research.canary_content_review.v1','status':'REPORT_CONTENT_FAIL','reviewer':'/root/pdf_model_analysis_reviewer',
              'document_id':batch.ANALYSIS_CANARY_ID,'selection_sha256':f.reference['sha256'],'page_input':f.rows[0]['page_input'],
              'receipt':receipt,'report':report_ref,'source_pages_reviewed':[1,2,3]}
    original_ref=f.write(batch.ANALYSIS_REVIEW_PATH,original)
    monkeypatch.setattr(batch,'PILOT_ORIGINAL_REVIEW_SHA256',original_ref['sha256'])
    journal=f.dispatcher.EVIDENCE_ROOT/'dispatch.jsonl';journal.parent.mkdir()
    journal.write_text(json.dumps({'event':'reconciled','document_id':batch.ANALYSIS_CANARY_ID,'status':'MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING',
                                  'receipt_path':receipt['path'],'receipt_sha256':receipt['sha256'],'state_root':str(state)})+'\n')
    folder=f.root/'first-report-execution';folder.mkdir()
    prefix='未来6个月内 原PDF第2页 验收补充 非重新模型生成'.encode();prefix+=b' '*(448-len(prefix))
    display=folder/'report-with-erratum.md';display.write_bytes(prefix+report.read_bytes())
    combined={'status':'REPORT_WITH_ERRATUM_PASS','reviewer':'/root/pdf_model_analysis_reviewer',
              'original_model_content_review':{**original_ref,'status':'REPORT_CONTENT_FAIL'},'checks':{'prefix_bytes':448},
              'original_model_report':report_ref,'display':{'path':str(display),'sha256':hashlib.sha256(display.read_bytes()).hexdigest()}}
    combined_ref=f.write(folder/'erratum-content-review.json',combined)
    monkeypatch.setattr(batch,'PILOT_ERRATUM_REVIEW_SHA256',combined_ref['sha256'])
    admission={'reference':f.reference,'documents':{r['document_id']:r for r in f.rows}}
    assert batch.verify_source_erratum_pair(admission)=={'original':'REPORT_CONTENT_FAIL','display':'REPORT_WITH_ERRATUM_PASS'}
    assert json.loads(batch.ANALYSIS_REVIEW_PATH.read_bytes())['status']=='REPORT_CONTENT_FAIL'
    display.write_bytes(prefix+report.read_bytes()+b'changed')
    with pytest.raises(batch.BatchError,match='REFERENCE_SHA'):
        batch.verify_source_erratum_pair(admission)


@pytest.mark.parametrize('reason',['PACKAGE_DEFER_ANNOUNCEMENT_PRIORITY','AVAILABLE_MEMORY_BELOW_MINIMUM','ANALYSIS_RUNTIME_DRIFT'])
def test_pilot_package_guard_runs_under_lock_before_attempt(monkeypatch,reason):
    calls=[]
    def guard():
        calls.append('checked')
        if len(calls)==2:raise batch.BatchError(reason)
    monkeypatch.setattr(batch,'_read_r1_success',lambda *a,**k:None)
    class Queue:
        attempts=0
        def enqueue(self,p):return {'status':'PENDING','idempotency_key':'k'}
        def _claim_next_locked(self,state,allowed_keys=None):self.attempts+=1
        def run_next(self,*a,**k):self._claim_next_locked({}, {'k'});raise AssertionError('POST must not execute')
    q=Queue();original=q._claim_next_locked
    with pytest.raises(batch.BatchError,match=reason):
        batch._perform_request(q,{'source_document_id':'company-xindairy-profit-20261020-r1'},[{'role':'user','content':'source'}],binding={},
            identity={'status':'MATCH','expected_model_id':local_model.MODEL_ID},identity_reader=lambda:{},priority_reader=lambda:{'status':'ALLOW'},
            request_fn=lambda **k:pytest.fail('POST'),sleep_fn=lambda _:None,request_guard=guard)
    assert q.attempts==0 and q._claim_next_locked==original and len(calls)==2


def test_pilot_first3_review_rejects_missing_or_foreign_coverage(analysis_fixture):
    f=analysis_fixture
    admission={'reference':f.reference,'documents':{r['document_id']:{**r,'page_count':2} for r in f.rows}}
    review=f.root/'review.json'
    f.write(review,{'status':'FIRST3_CONTENT_PASS','reviewer':'/root/pdf_model_analysis_reviewer','selection_sha256':f.reference['sha256'],
                    'stratified17_sha256':batch.PILOT_STRATA_SHA256,'documents':[{'document_id':'foreign'}]})
    with pytest.raises(batch.BatchError,match='FIRST3_CONTENT_PASS_REQUIRED'):
        batch.verify_pilot_content_review(review,[r['document_id'] for r in f.rows[1:4]],admission)


def test_pilot_phase_is_hash_bound_first3_then_reviewer_gated_remaining14(analysis_fixture,monkeypatch):
    f=analysis_fixture
    from ops import run_pdf_research_package_once as package
    pilot_root=f.root/'pilot';pilot_root.mkdir()
    monkeypatch.setattr(batch,'RESEARCH_PILOT_ROOT',pilot_root)
    continuation=f.root/'continuation';continuation.mkdir()
    monkeypatch.setattr(f.dispatcher,'CONTINUATION_ROOT',continuation)
    old=f.write(continuation/'ROOT_REMAINING_EXECUTION_AUTHORIZATION_PRE_PILOT_20261020_R1.json',{'old':'preserved'})
    monkeypatch.setattr(batch,'PILOT_PREVIOUS_AUTH_SHA256',old['sha256'])
    ids=[r['document_id'] for r in f.rows[1:]];first=[ids[1],ids[7],ids[14]];rest=[i for i in ids if i not in first]
    strata=f.write(pilot_root/'model/stratified17.json',{'first_group_document_ids':first,'remaining14_document_ids':rest})
    monkeypatch.setattr(batch,'PILOT_STRATA_SHA256',strata['sha256'])
    package_plan=f.write(pilot_root/'model/package-input-plan.json',{'packages':[]})
    monkeypatch.setattr(batch,'PILOT_PACKAGE_PLAN_SHA256',package_plan['sha256'])
    decision=f.write(pilot_root/'controller-model-implementation-decision.json',{'status':'approved'})
    monkeypatch.setattr(batch,'PILOT_DECISION_SHA256',decision['sha256'])
    sources={'ops/run_pdf_research_batch.py':hashlib.sha256(Path(batch.__file__).read_bytes()).hexdigest(),
             'ops/run_pdf_research_remaining_once.py':hashlib.sha256(Path(f.dispatcher.__file__).read_bytes()).hexdigest(),
             'ops/run_pdf_research_package_once.py':hashlib.sha256(Path(package.__file__).read_bytes()).hexdigest()}
    independent=f.write(pilot_root/'independent-review/code-review.json',{'status':'REVIEWED_PASS','reviewer':'/root/pdf_model_analysis_reviewer','sources':sources})
    review=f.write(continuation/'source-review.json',{'status':'REVIEWED_PASS','sources':sources,'independent_review':independent})
    adoption={'schema':'v4.pdf_research.pilot_adoption.v1','status':'ROOT_ADOPTED','previous_authorization':old,
              'journal_event_count':45,'journal_prefix_sha256':batch.PILOT_JOURNAL_PREFIX_SHA256,'selection':f.reference,
              'prepared_text_manifest_sha256':'f'*64,'stratified17':strata,'package_input_plan':package_plan,'sources':sources}
    adoption_ref=f.write(continuation/'ROOT_PDF_PILOT17_EXECUTION_ADOPTION_20261020_R1.json',adoption)
    context={'authorization':{'pilot17_adoption':adoption_ref,'reviewer_receipt':review}}
    admission={'reference':f.reference,'value':f.value,'documents':{r['document_id']:r for r in f.rows}}
    monkeypatch.setattr(batch,'verify_source_erratum_pair',lambda a:{'original':'REPORT_CONTENT_FAIL','display':'REPORT_WITH_ERRATUM_PASS'})
    assert batch.load_research_pilot(admission,context)['allowed_ids']==first
    review_path=pilot_root/'independent-review/stratified-first3-content-review.json';review_path.parent.mkdir(exist_ok=True)
    review_path.write_text(json.dumps({'status':'REPORT_CONTENT_FAIL'}))
    with pytest.raises(batch.BatchError,match='FIRST3_CONTENT_PASS_REQUIRED'):
        batch.load_research_pilot(admission,context)
    checked=[]
    monkeypatch.setattr(batch,'verify_pilot_content_review',lambda path,ordered,adm:checked.append(ordered))
    assert batch.load_research_pilot(admission,context)['allowed_ids']==rest and checked==[first]
    adoption['sources']['ops/run_pdf_research_batch.py']='0'*64
    context['authorization']['pilot17_adoption']=f.write(Path(adoption_ref['path']),adoption)
    with pytest.raises(batch.BatchError,match='SOURCE_SHA_MISMATCH'):
        batch.load_research_pilot(admission,context)


def test_v2_source_hold_rechecked_before_enqueue_and_attempt(analysis_fixture,monkeypatch):
    f=analysis_fixture;held=f.rows[1]['document_id'];admission=_load_test_admission(f)
    admission['allowed_ids']=[held]
    admission['pilot']={'reference':{'path':'adoption','sha256':'a'*64}}
    monkeypatch.setattr(f.dispatcher,'load_and_validate_authorization',lambda :f.context)
    monkeypatch.setattr(batch,'load_research_pilot',lambda *a:{'reference':admission['pilot']['reference'],'allowed_ids':[],'source_hold_ids':[held]})
    monkeypatch.setattr(batch,'verify_analysis_plan_runtime',lambda *a:None)
    class Queue:
        attempts=0;enqueues=0
        def enqueue(self,p):self.enqueues+=1;raise AssertionError('held source must not enqueue')
    q=Queue()
    with pytest.raises(batch.BatchError,match='PHASE_OR_ADOPTION_DRIFT'):
        batch._perform_request(q,{'source_document_id':held},[{'role':'user','content':'body'}],binding={},identity={},identity_reader=lambda:{},
            priority_reader=lambda:{'status':'ALLOW'},request_fn=lambda **k:pytest.fail('POST'),sleep_fn=lambda _:None,analysis_admission=admission)
    assert q.attempts==0 and q.enqueues==0


def test_v2_dispatch_accepts_only_exact_reviewed_second_plan(analysis_fixture):
    f=analysis_fixture;did=batch.PILOT_TOOL_BUDGET_DOCUMENT_ID
    path=f.dispatcher.EVIDENCE_ROOT/'dispatch.jsonl';path.parent.mkdir()
    events=[{'event':'plan_created','document_id':did,'plan_sha256':'a'*64},
            {'event':'plan_created','document_id':did,'plan_sha256':'b'*64},
            {'event':'dispatch_intent','document_id':did,'plan_sha256':'b'*64}]
    path.write_text(''.join(json.dumps(e)+'\n' for e in events))
    admission={'pilot':{'recovery':{'plan_reference':{'sha256':'b'*64}}}}
    batch.verify_analysis_dispatch(did,'b'*64,admission)
    with pytest.raises(batch.BatchError,match='RECOVERY_PLAN_NOT_CURRENT'):
        batch.verify_analysis_dispatch(did,'a'*64,admission)
    with pytest.raises(batch.BatchError,match='DISPATCH_NOT_CURRENT'):
        batch.verify_analysis_dispatch(did,'b'*64)
    events.insert(2,{'event':'plan_created','document_id':did,'plan_sha256':'c'*64});path.write_text(''.join(json.dumps(e)+'\n' for e in events))
    with pytest.raises(batch.BatchError,match='DISPATCH_NOT_CURRENT'):
        batch.verify_analysis_dispatch(did,'b'*64,admission)


def test_synthesis_v3_rejects_actual_stagnant_vector_and_reserves_contraction_bytes():
    reports=[{'report_id':'first','text':'a'*6265},{'report_id':'carry','text':'b'*1888}]
    with pytest.raises(batch.BatchError,match='NONCONVERGENT'):
        batch._require_synthesis_progress(reports,[{'report_id':'new-name','text':'a'*6265},reports[1]])
    shorter=[{'report_id':'shorter','text':'a'*4385},reports[1]]
    batch._require_synthesis_progress(reports,shorter)
    q={'finding':'C4/C5/C6 independent, unknown table mappings'}
    groups=batch._pack_synthesis_groups('a'*64,reports,1,None,reserve_contraction=True,source_qualifications=q)
    assert [len(g) for g in groups]==[4,1]
    assert batch._synthesis_output_budget(groups[0])==4385
    msg=batch._synthesis_messages('a'*64,groups[0],1,None,4385,q)
    value=json.loads(msg[1]['content'].split('\n',1)[1])
    assert value['intermediate_output_character_limit']==4385 and value['independently_verified_source_qualifications']==q
    assert len(batch._request_envelope(msg))<=32768


def test_synthesis_v3_actual_frozen_stage_loader_and_qualified_plan():
    recovery=batch.load_synthesis_recovery()
    assert [len(x['text']) for x in recovery['seed_reports']]==[6265,1888]
    assert len(recovery['descriptor']['source_chunks'])==3
    assert recovery['descriptor']['model_request_limit']==2
    assert recovery['descriptor']['source_model_rePOST_limit']==0
    assert [r['id'] for r in recovery['source_qualifications']['findings']]==['C4','C5','C6']
    _manifest,manifest_sha,documents=batch.load_manifest(batch.DEFAULT_MANIFEST)
    validated=batch.validate_continuation_plan(Path(recovery['plan_reference']['path']),manifest_sha256=manifest_sha,documents=documents)
    assert validated['synthesis_stage_recovery']['plan_raw']==recovery['plan_raw']


@pytest.mark.parametrize('oversize',[False,True])
def test_synthesis_v3_reuses_all_source_stages_and_at_most_two_requests(tmp_path,monkeypatch,oversize):
    recovery=batch.load_synthesis_recovery();did=batch.PILOT_TOOL_BUDGET_DOCUMENT_ID
    value=json.loads(Path(recovery['descriptor']['stopped_page_input']['path']).read_bytes())
    raw=Path(recovery['descriptor']['stopped_page_input']['path']).read_bytes()
    pages=[_page(p['page_number'],len(value['pages']),p['text']) for p in value['pages']]
    prepared={'manifest_sha256':'b'*64,'documents':{did:{'page_input':value,'page_input_raw':raw,'page_input_sha256':hashlib.sha256(raw).hexdigest()}}}
    monkeypatch.setattr(batch.pdf_text_preparation,'pages_from_frozen_manifest',lambda *_:(pages,value['source'],{}))
    calls=[];persisted=[]
    def perform(_queue,payload,messages,**kwargs):
        assert payload['stage']=='simple_batch_synthesis_v1','no source rePOST permitted'
        data=json.loads(messages[1]['content'].split('\n',1)[1]);calls.append(data)
        assert data['independently_verified_source_qualifications']==recovery['source_qualifications']
        answer='x'*(4386 if oversize else 4385) if len(calls)==1 else 'Final cited report pending independent semantic review'
        return {'status':'SUCCEEDED','attempted':True,'result':{'analysis_markdown':answer}}
    monkeypatch.setattr(batch,'_perform_request',perform)
    def persist(state,doc,source,outcome,*,name):
        p=doc/'partials'/(name+'.md');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(outcome['result']['analysis_markdown']);persisted.append(p)
        return {'report':{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}}
    monkeypatch.setattr(batch,'_persist_model_result',persist)
    continuation={'plan':recovery['plan'],'plan_sha256':recovery['plan_reference']['sha256'],'entry':recovery['plan']['selected_documents'][0],'synthesis_stage_recovery':recovery}
    kwargs=dict(manifest_sha=batch.EXPECTED_BATCH_MANIFEST_SHA256,state_root=tmp_path/'new-state',queue=object(),binding={'configuration_sha256':'c'*64,'request_schema_sha256':'d'*64,'evidence_root':str(tmp_path/'evidence')},identity={},priority_reader=lambda:{},identity_reader=lambda:{},identity_state={},request_fn=lambda **_:pytest.fail('offline only'),sleep_fn=lambda _:None,prepared_manifest=prepared,continuation=continuation)
    document={'document_id':did,'pdf_sha256':did}
    if oversize:
        with pytest.raises(batch.BatchError,match='CHARACTER_BUDGET'):batch._run_document(document,**kwargs)
        assert len(calls)==1 and persisted[0].read_text()=='x'*4386
        assert not (tmp_path/'new-state/documents'/did/'report.md').exists()
    else:
        result=batch._run_document(document,**kwargs)
        assert result['status']=='MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING'
        assert len(calls)==2 and len(result['chunks'])==3 and all(c['source_stage_reused'] for c in result['chunks'])
        assert calls[0]['intermediate_output_character_limit']==4385
        assert 'intermediate_output_character_limit' not in calls[1]
    assert all(p.exists() for p in persisted)


def test_sectioned_v4_real_complete_inputs_and_zero_network_projection(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket,'connect',lambda *a:pytest.fail('no network allowed'))
    value=batch.load_sectioned_reuse_v4()['value']
    assert [r['initial_input_pages'] for r in value['source_rows']]==[list(range(1,6)),list(range(6,14)),list(range(14,21))]
    assert [r['tool_requested_pages'] for r in value['source_rows']]==[list(range(6,11)),[],[]]
    output=batch.build_sectioned_reuse_v4(persist=False)
    assert output['new_model_POSTs']==0 and output['status']=='REUSED_SOURCE_STAGE_SECTIONED_REPORT_SOURCE_REVIEW_PENDING'
    assert value['new_model_POST_limit']==0
    for row in value['source_rows']:
        original=Path(row['source_chunk']['report']['path']).read_text()
        projected=batch._project_sectioned_text(original,row['edits'])
        # Verify untouched runs explicitly, and retain the full original under its SHA.
        cursor=0;scan=0
        for e in row['edits']:
            prefix=original[cursor:e['start_character']]
            assert projected[scan:scan+len(prefix)]==prefix
            scan+=len(prefix);assert projected[scan:scan+len(e['replacement'])]==e['replacement'];scan+=len(e['replacement']);cursor=e['end_character']
        assert projected[scan:]==original[cursor:]
        assert hashlib.sha256(Path(row['source_chunk']['report']['path']).read_bytes()).hexdigest()==row['source_chunk']['report']['sha256']


def test_sectioned_v4_projection_rejects_forged_range_and_false_known():
    text='before BAD after';edit={'start_character':7,'end_character':10,'finding':'C4','original_text_sha256':_sha('BAD'),'replacement':'CANNOT_CONFIRM'}
    assert batch._project_sectioned_text(text,[edit])=='before CANNOT_CONFIRM after'
    for changed in ({'start_character':6},{'original_text_sha256':'a'*64},{'replacement':'verified fact'},{'finding':'new'}):
        with pytest.raises(batch.BatchError,match='PROJECTION_RANGE'):batch._project_sectioned_text(text,[{**edit,**changed}])


def test_sectioned_v4_absent_review_never_means_content_pass(monkeypatch,tmp_path):
    loaded=batch.load_sectioned_reuse_v4()
    monkeypatch.setattr(batch,'RESEARCH_PILOT_ROOT',tmp_path)
    monkeypatch.setattr(batch,'load_sectioned_reuse_v4',lambda: {'value':{**loaded['value'],'content_review_path':str(tmp_path/'independent-review/sectioned667-content-review-v4.json')}})
    with pytest.raises(batch.BatchError,match='CONTENT_REVIEW_REQUIRED'):batch.verify_sectioned_content_v4()


def test_sectioned_long_builder_is_finite_and_has_no_synthesis():
    reports=[{'report_id':str(i),'text':f'chunk{i} [1]'} for i in range(11)]
    index=[{'initial_input_pages':[i+1],'tool_requested_pages':[]} for i in range(11)]
    output=batch._sectioned_text(batch.PILOT_LONG_DOCUMENT_ID,reports,index,None)
    assert all(r['text'] in output for r in reports)
    assert output.count('## 原模型分块 ')==11
    assert '初始输入页' in output and '工具请求页' in output


def test_sectioned_v4_long_actual11_source_chunks_never_recursive(tmp_path,monkeypatch):
    did=batch.PILOT_LONG_DOCUMENT_ID
    selection=json.loads(batch.ANALYSIS_SELECTION_PATH.read_text());row=next(r for r in selection['documents'] if r['document_id']==did)
    raw=Path(row['page_input']['path']).read_bytes();value=json.loads(raw)
    pages=[_page(p['page_number'],len(value['pages']),p['text']) for p in value['pages']]
    prepared={'manifest_sha256':'b'*64,'documents':{did:{'page_input':value,'page_input_raw':raw,'page_input_sha256':hashlib.sha256(raw).hexdigest()}}}
    monkeypatch.setattr(batch.pdf_text_preparation,'pages_from_frozen_manifest',lambda *_:(pages,value['source'],{}))
    calls=[]
    def perform(_queue,payload,messages,**kwargs):
        assert payload['stage']!='simple_batch_synthesis_v1'
        calls.append(payload);return {'status':'SUCCEEDED','attempted':True,'result':{'analysis_markdown':f'Original source stage {len(calls)} pending all16page content review'}}
    monkeypatch.setattr(batch,'_perform_request',perform)
    def persist(state,doc,source,outcome,*,name):
        p=doc/'partials'/(name+'.md');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(outcome['result']['analysis_markdown'])
        return {'report':{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()},'queue_idempotency_key':'synthetic'}
    monkeypatch.setattr(batch,'_persist_model_result',persist)
    monkeypatch.setattr(batch,'_sectioned_stage_index',lambda state,c,r:{'initial_input_pages':sorted({u.page_number for u in c.units}),'tool_requested_pages':[]})
    monkeypatch.setattr(batch,'_pack_synthesis_groups',lambda *a,**k:pytest.fail('recursive synthesis forbidden'))
    admission={'pilot':{'sectioned_reuse':{}}}
    monkeypatch.setattr(batch,'guard_analysis_document',lambda a,x,**k: None if x==did else pytest.fail('foreigndocument'))
    result=batch._run_document({'document_id':did,'pdf_sha256':did},manifest_sha=batch.EXPECTED_BATCH_MANIFEST_SHA256,state_root=tmp_path/'long-state',queue=object(),binding={'configuration_sha256':'c'*64,'request_schema_sha256':'d'*64,'evidence_root':str(tmp_path/'evidence')},identity={},priority_reader=lambda:{},identity_reader=lambda:{},identity_state={},request_fn=lambda **_:pytest.fail('offline only'),sleep_fn=lambda _:None,prepared_manifest=prepared,analysis_admission=admission)
    assert len(calls)==11 and len(result['chunks'])==11 and result['synthesis_levels']==0
    assert result['status']=='SECTIONED_SOURCE_STAGE_REPORT_SOURCE_REVIEW_PENDING'
    assert (tmp_path/'long-state/documents'/did/'sectioned-components.json').is_file()


def test_sectioned_v4_single_entity_source_erratum_exact1_preserves_old_candidate(monkeypatch):
    import socket
    monkeypatch.setattr(socket.socket,'connect',lambda *a:pytest.fail('no model or OCR'))
    old=batch.RESEARCH_PILOT_ROOT/'model/sectioned-reuse-v4/667/report.md';before=old.read_bytes()
    loaded=batch.load_sectioned_reuse_v4();v=loaded['value'];row=v['source_rows'][0]
    raw=Path(row['source_chunk']['report']['path']).read_text();projected=batch._project_sectioned_text(raw,row['edits'])
    entity=[e for e in row['edits'] if e['finding']=='V4-CONTENT-ENTITY-P1'];assert len(entity)==1
    assert raw[entity[0]['start_character']:entity[0]['end_character']]=='吴帆生物'
    assert '昊帆生物〔人工来源勘误：原PDF第1页；原OCR为“吴帆生物”〕' in projected
    candidate=batch.build_sectioned_reuse_v4(persist=False)
    assert candidate['new_model_POSTs']==0 and '667-name-erratum' in candidate['report']['path']
    assert old.read_bytes()==before and hashlib.sha256(before).hexdigest()=='d2563373f6c35a62dff50faa7f6a78e01e30c3a4c69147730c2d2a080e2acac5'
    bad={**entity[0],'replacement':'其他公司'}
    with pytest.raises(batch.BatchError,match='PROJECTION_RANGE'):batch._project_sectioned_text(raw,[bad])
    bad={**entity[0],'start_character':entity[0]['start_character']+1}
    with pytest.raises(batch.BatchError,match='PROJECTION_RANGE'):batch._project_sectioned_text(raw,[bad])
