from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure import pdf_research
from ops import run_pdf_research_batch as batch


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configure_failure_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    message: str,
    queue_status: str | None = None,
    queue_message: str | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    document: dict[str, object] = {"document_id": "1" * 64, "pdf_sha256": "1" * 64}
    page_text = "研报正文与关键财务数据。" * 100
    page = pdf_research.PageText(1, 1, page_text, "NATIVE_TEXT", _sha(page_text), "test-fixture")
    source: dict[str, object] = {
        "page_count": 1,
        "page_extraction_status": "COMPLETE",
        "all_pages_nonempty": True,
        "source_repair_status": "NOT_REQUIRED",
        "page_extraction_sources": [
            {"page_number": 1, "selected": "PINNED_PYPDF_NATIVE", "preparation_gate": "READY"}
        ],
    }
    manifest = {"schema": "v4.pdf_research_simple_batch.manifest.v1", "status": "FROZEN", "documents": [document]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha = _file_sha(manifest_path)
    page_input = batch._page_input_value({**document, "_manifest_sha256": manifest_sha}, [page], source)
    page_input_raw = batch._json_bytes(page_input, newline=True)
    page_input_sha = hashlib.sha256(page_input_raw).hexdigest()
    prepared = {
        "path": str(manifest_path),
        "manifest_sha256": "b" * 64,
        "parent_manifest_sha256": manifest_sha,
        "documents": {
            "1" * 64: {
                "manifest_row": {"status": "READY"},
                "page_input": page_input,
                "page_input_raw": page_input_raw,
                "page_input_sha256": page_input_sha,
            }
        },
    }
    monkeypatch.setattr(batch, "load_manifest", lambda _path: (manifest, manifest_sha, [document]))
    monkeypatch.setattr(batch, "load_analysis_admission", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch, "_read_r1_success", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(batch.pdf_text_preparation, "verify_frozen_manifest", lambda *_args, **_kwargs: prepared)
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
            "request_schema_sha256": "d" * 64,
        },
    )
    monkeypatch.setattr(batch, "EXPECTED_CANARY_DOCUMENT_IDS", ("1" * 64,))

    if queue_status is None:
        def fail_request(*_args, **_kwargs):
            raise RuntimeError(message)

        monkeypatch.setattr(batch, "_perform_request", fail_request)
        queue = SimpleNamespace(state_root=tmp_path / "state" / "queue")
    else:
        def enqueue(_payload):
            item: dict[str, object] = {
                "status": queue_status,
                "idempotency_key": "e" * 64,
                "attempt_count": 0,
                "max_attempts": 1,
                "queue_id": "v4-pdf-simple-batch",
                "model_id": batch.local_model.MODEL_ID,
            }
            if queue_message is not None:
                item["last_error"] = {
                    "code": "QUEUE_FAILED",
                    "type": "QueueFailure",
                    "message": queue_message,
                }
                item["raw_path"] = "/Users/lexi/Desktop/学习/secret/queue.raw"
                item["validated_path"] = "/Users/lexi/Desktop/学习/secret/queue.validated.json"
                item["attempts"] = [
                    {
                        "number": 1,
                        "status": "FAILED",
                        "raw_path": "/Users/lexi/Desktop/学习/secret/attempt.raw",
                        "validated_path": "/Users/lexi/Desktop/学习/secret/attempt.validated.json",
                        "error": {
                            "stage": "executor",
                            "code": "QUEUE_FAILED",
                            "type": "QueueFailure",
                            "message": queue_message,
                        },
                    }
                ]
            return item

        queue = SimpleNamespace(state_root=tmp_path / "state" / "queue", enqueue=enqueue)
        monkeypatch.setattr(batch, "_read_r1_success", lambda *_args, **_kwargs: None)
    run_kwargs: dict[str, object] = {
        "manifest_path": manifest_path,
        "state_root": tmp_path / "state",
        "prepared_text_manifest_path": manifest_path,
        "prepared_text_manifest_sha256": "b" * 64,
        "queue_factory": lambda _root: (queue, Path("/shared/model.lock")),
        "identity_fn": lambda: {"status": "MATCH", "expected_model_id": batch.local_model.MODEL_ID},
        "priority_reader": lambda: {"status": "ALLOW", "same_model_pending_count": 0},
        "request_fn": lambda **_kwargs: pytest.fail("_perform_request is patched to fail"),
        "sleep_fn": lambda _seconds: None,
    }
    return document, run_kwargs, {"manifest_sha": manifest_sha}


def test_queue_failure_persists_chunk_error_and_failed_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, run_kwargs, _context = _configure_failure_run(tmp_path, monkeypatch, message="unused")
    outcome = {
        "status": "FAILED_NO_RETRY",
        "attempted": True,
        "queue_item": {
            "last_error": {
                "code": "SYNTHESIS_OUTPUT_CHARACTER_BUDGET_EXCEEDED",
                "type": "LocalModelError",
                "message": "budget exceeded at /Users/lexi/Desktop/学习/secret/report.json",
            }
        },
    }
    monkeypatch.setattr(batch, "_perform_request", lambda *_args, **_kwargs: dict(outcome))

    result = batch.run_batch(**run_kwargs)

    assert [item["status"] for item in result["documents"]] == ["FAILED_NO_RETRY"]
    receipt_path = tmp_path / "state/documents" / document["document_id"] / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "FAILED_NO_RETRY"
    assert receipt["failure_code"] == "SYNTHESIS_OUTPUT_CHARACTER_BUDGET_EXCEEDED"
    assert "<redacted-path>" in receipt["failure_summary"]
    assert "/Users/" not in receipt["failure_summary"]
    assert receipt["failed_chunk_indexes"] == [1]
    chunk = receipt["chunks"][0]
    assert chunk["error_code"] == "SYNTHESIS_OUTPUT_CHARACTER_BUDGET_EXCEEDED"
    assert "<redacted-path>" in chunk["error_summary"]
    assert "/Users/" not in chunk["error_summary"]
    assert isinstance(chunk["failed_at_utc"], str) and chunk["failed_at_utc"].endswith("Z")


def test_failure_reason_persists_on_chunk_and_document_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, run_kwargs, _context = _configure_failure_run(
        tmp_path,
        monkeypatch,
        message="model transport failed at /Users/lexi/Desktop/学习/secret/failure.json",
    )

    result = batch.run_batch(**run_kwargs)

    assert [item["status"] for item in result["documents"]] == ["FAILED_DOCUMENT_ISOLATED"]
    receipt_path = tmp_path / "state/documents" / document["document_id"] / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "FAILED_DOCUMENT_ISOLATED"
    assert receipt["failure_code"] == "RuntimeError"
    assert "<redacted-path>" in receipt["failure_summary"]
    assert "/Users/" not in receipt["failure_summary"]
    assert receipt["failed_chunk_indexes"] == [1]
    assert len(receipt["chunks"]) == 1
    chunk = receipt["chunks"][0]
    assert chunk["chunk_index"] == 1
    assert chunk["status"] == "FAILED_NO_RETRY"
    assert chunk["error_code"] == "RuntimeError"
    assert "<redacted-path>" in chunk["error_summary"]
    assert "/Users/" not in chunk["error_summary"]
    assert isinstance(chunk["failed_at_utc"], str) and chunk["failed_at_utc"].endswith("Z")


@pytest.mark.parametrize("queue_status", ["OVERSIZE", "MISSING_MATERIAL"])
def test_queue_refusal_preserves_distinct_failure_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    queue_status: str,
) -> None:
    document, run_kwargs, _context = _configure_failure_run(
        tmp_path,
        monkeypatch,
        message="unused",
        queue_status=queue_status,
    )

    result = batch.run_batch(**run_kwargs)

    assert [item["status"] for item in result["documents"]] == ["FAILED_NO_RETRY"]
    receipt_path = tmp_path / "state/documents" / document["document_id"] / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "FAILED_NO_RETRY"
    assert receipt["failure_code"] == queue_status
    assert receipt["failed_chunk_indexes"] == [1]
    assert receipt["chunks"][0]["error_code"] == queue_status
    assert receipt["chunks"][0]["status"] == "FAILED_NO_RETRY"


def test_queue_failure_receipt_does_not_leak_unsanitized_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, run_kwargs, _context = _configure_failure_run(
        tmp_path,
        monkeypatch,
        message="unused",
        queue_status="FAILED",
        queue_message="queue rejected at /Users/lexi/Desktop/学习/secret/queue.json",
    )

    result = batch.run_batch(**run_kwargs)

    assert [item["status"] for item in result["documents"]] == ["FAILED_NO_RETRY"]
    receipt_path = tmp_path / "state/documents" / document["document_id"] / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert "/Users/lexi" not in json.dumps(receipt, ensure_ascii=False)
    chunk = receipt["chunks"][0]
    assert chunk["error_code"] == "QUEUE_FAILED"
    assert chunk["error_summary"] == "queue rejected at <redacted-path>"
    assert chunk["queue_item"]["last_error"]["message"] == "queue rejected at <redacted-path>"
    assert chunk["queue_item"]["attempts"][0]["error"]["message"] == "queue rejected at <redacted-path>"
    assert "raw_path" not in json.dumps(chunk["queue_item"])
    assert receipt["failure_code"] == "QUEUE_FAILED"
    assert receipt["failure_summary"] == "queue rejected at <redacted-path>"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("failed:/opt/secret/data.bin", "failed:<redacted-path>"),
        ("open /tmp failed", "open <redacted-path> failed"),
        ("error at /tmp", "error at <redacted-path>"),
        ("/Users/lexi/x/y.json", "<redacted-path>"),
        ("path=/tmp/x", "path=<redacted-path>"),
        ('"/tmp/x"', '"<redacted-path>"'),
    ],
)
def test_failure_summary_redacts_absolute_paths_without_duplicates(message: str, expected: str) -> None:
    summary = batch._sanitize_failure_summary(message, roots=(Path("/Users/lexi"),))

    assert summary == expected
    assert summary.count("<redacted-path>") == 1


def test_failure_summary_redacts_path_after_parenthesis() -> None:
    summary = batch._sanitize_failure_summary("at (/opt/secret/data.bin)", roots=())

    assert "/opt/secret" not in summary
    assert summary.count("<redacted-path>") == 1


@pytest.mark.parametrize(
    "message",
    [
        "see http://host/path now",
        "https://example.com/a/b?x=1",
        "file:///tmp/x",
        "see git+ssh://host/x now",
        "see http://host/Users/lexi/x now",
        "and/or",
        "2026/10/16",
        "ratio 1/2",
        "文件 A/B 测试",
        "a/b",
    ],
)
def test_failure_summary_preserves_urls_and_relative_paths(message: str) -> None:
    assert batch._sanitize_failure_summary(message, roots=(Path("/Users/lexi"),)) == message


def test_failure_summary_keeps_windows_path_rule() -> None:
    summary = batch._sanitize_failure_summary(r"open C:\secret\data.bin", roots=())

    assert summary == r"open <redacted-path>"
