from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import base64
from types import ModuleType
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

WORKTREE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE_ROOT))
from ops import run_pdf_research_batch as batch

DISPATCHER_PATH = Path(__file__).resolve().parents[1] / "ops" / "run_pdf_research_remaining_once.py"
_spec = importlib.util.spec_from_file_location("remaining_once_dispatcher_test", DISPATCHER_PATH)
assert _spec is not None and _spec.loader is not None
dispatcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dispatcher)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_dispatcher_pins_the_current_batch_runner_bytes() -> None:
    runner_path = Path(__file__).resolve().parents[1] / "ops" / "run_pdf_research_batch.py"
    assert _sha(runner_path.read_bytes()) == dispatcher.EXPECTED_RUNNER_SHA256


def _synthetic_documents() -> list[dict[str, str]]:
    rows = [
        {"document_id": f"{index:064x}", "pdf_sha256": f"{index:064x}"}
        for index in range(1, 2210)
    ]
    rows[-1] = {
        "document_id": dispatcher.QUARANTINE_DOCUMENT_ID,
        "pdf_sha256": dispatcher.QUARANTINE_DOCUMENT_ID,
    }
    return rows


def _synthetic_statuses(documents: list[dict[str, str]]) -> dict[str, str]:
    return {row["document_id"]: "UNPROCESSED" for row in documents}


class _MonkeyPatch:
    def __init__(self, test_case: unittest.TestCase):
        self.test_case = test_case

    def setattr(self, target: object, name: str, value: object) -> None:
        old = getattr(target, name)
        setattr(target, name, value)
        self.test_case.addCleanup(setattr, target, name, old)


def _synthetic_context(
    monkeypatch: _MonkeyPatch,
    tmp_path: Path,
    *,
    max_documents: int = 4,
) -> tuple[list[dict[str, str]], dict[str, dict[str, str]], set[str], dict[str, str], dict[str, object]]:
    monkeypatch.setattr(dispatcher, "_assert_runtime", lambda: None)
    monkeypatch.setattr(dispatcher, "_verify_static_bindings", lambda: {"scope_sha256": "a" * 64, "runner_sha256": "b" * 64})
    monkeypatch.setattr(batch, "DEFAULT_STATE_ROOT", tmp_path / "state" / "r3")
    docs = _synthetic_documents()
    original = {row["document_id"]: {"status": "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"} for row in docs[:142]}
    pilot = {docs[position - 1]["document_id"] for position in (155, 168, 171, 176, 177, 188, 193, 199, 208, 210)}
    statuses = _synthetic_statuses(docs)
    statuses.update({document_id: row["status"] for document_id, row in original.items()})
    frozen_inventory_statuses = dict(statuses)
    statuses.update({document_id: "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING" for document_id in pilot})
    statuses[docs[142]["document_id"]] = "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    statuses[docs[143]["document_id"]] = "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    statuses[docs[144]["document_id"]] = "FAILED_NO_RETRY"
    for row in docs[145:148]:
        statuses[row["document_id"]] = "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    auth = {
        "authorization": {
            "authorization_id": "test-auth",
            "max_documents": max_documents,
            "model_settings_sha256": batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        },
        "authorization_sha256": "c" * 64,
        "pilot_document_ids": pilot,
        "pilot_progress_sha256": "d" * 64,
        "pilot_plan": {"continuation_id": "test-pilot"},
    }
    monkeypatch.setattr(dispatcher, "load_and_validate_authorization", lambda _path: auth)
    monkeypatch.setattr(dispatcher, "_load_original_r3", lambda _path: (dispatcher.EXPECTED_MANIFEST_SHA256, docs, original))
    summary: dict[str, object] = {
        "inventory_sha256": dispatcher.EXPECTED_REMAINING_INVENTORY_SHA256,
        "frozen_inventory_statuses": frozen_inventory_statuses,
        "completed_count": 87,
        "outstanding_count": 2122,
        "outstanding_status_counts": {},
        "runnable_unprocessed_count": 2050,
        "quarantine_document_id": dispatcher.QUARANTINE_DOCUMENT_ID,
        "terminal_receipts": {},
        "current_tool_canary": {},
    }
    monkeypatch.setattr(dispatcher, "load_current_completion_statuses", lambda *_args, **_kwargs: (statuses, summary))
    return docs, original, pilot, statuses, summary


def _halt_resume_fixture(tmp_path: Path) -> tuple[dispatcher.DurableJournal, dict[str, object], dict[str, object]]:
    document_id = "a" * 64
    queue_key = "b" * 64
    auth = {
        "authorization_id": "resume-test-auth",
        "model_settings_sha256": batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        "adoption_receipt": {"sha256": "c" * 64},
    }
    context: dict[str, object] = {
        "authorization": auth,
        "authorization_sha256": "d" * 64,
        "manifest_sha256": dispatcher.EXPECTED_MANIFEST_SHA256,
        "pilot_progress_sha256": "f" * 64,
        "documents": [],
        "inventory_summary": {"inventory_sha256": "e" * 64, "outstanding_count": 2122},
    }
    descriptor: dict[str, object] = {
        "journal_event_count": 2,
        "journal_prefix_sha256": "1" * 64,
        "previous_authorization_sha256": "2" * 64,
        "old_dispatcher_sha256": "3" * 64,
        "old_runner_sha256": "4" * 64,
        "new_dispatcher_sha256": "5" * 64,
        "new_runner_sha256": "6" * 64,
        "document_id": document_id,
        "continuation_id": "resume-test-prior",
        "plan_sha256": "f" * 64,
        "recovery_generation": 1,
        "prior_state_root": str(tmp_path / "prior-state"),
        "queue_key": queue_key,
        "failure_sample": {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 10_000},
        "recovery_plan": {
            "continuation_id": "memory-recovery-test",
            "state_root": str(tmp_path / "recovery-state"),
            "selected_documents": [{"document_id": document_id, "recovery": {"prior_queue_idempotency_key": queue_key}}],
        },
        "recovery_raw": b'{"test":"recovery"}',
    }
    journal = dispatcher.DurableJournal(tmp_path / "journal")
    journal.root.mkdir(parents=True)
    journal.events = [
        {"event": "binding", "at_utc": "fixed"},
        {"event": "halt", "reason": "FAILED_NO_RETRY", "document_id": document_id, "at_utc": "fixed"},
    ]
    journal.events.append({"at_utc": "fixed", **dispatcher._source_adoption_event(context, descriptor)})
    return journal, context, descriptor


def test_halt_resume_recovery_wait_and_plan_are_append_only_and_restart_safe(
    tmp_path: Path,
) -> None:
    journal, context, descriptor = _halt_resume_fixture(tmp_path)
    samples = iter(
        [
            {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES + 2_000_000_000, "swap_used_bytes": 10_000},
            {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES + 2_000_000_000, "swap_used_bytes": 10_000},
            {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES + 2_000_000_000, "swap_used_bytes": 10_000},
        ]
    )
    plan_sha = _sha(descriptor["recovery_raw"])
    with (
        mock.patch.object(dispatcher, "_halt_resume_descriptor", return_value=descriptor),
        mock.patch.object(batch, "validate_continuation_plan", return_value={"plan_sha256": plan_sha}),
    ):
        result = dispatcher._prepare_halt_resume(
            journal,
            context,
            sampler=lambda: next(samples),
            sleep_fn=lambda _seconds: None,
            samples_path=journal.root / "resource-samples.jsonl",
        )
        assert result == descriptor["document_id"]
        assert [event["event"] for event in journal.events[3:]] == [
            "memory_recovery_wait",
            "halt_resolution",
            "plan_created",
        ]
        event_count = len(journal.events)
        result = dispatcher._prepare_halt_resume(
            journal,
            context,
            sampler=lambda: (_ for _ in ()).throw(AssertionError("restart must reuse durable resource evidence")),
            sleep_fn=lambda _seconds: None,
            samples_path=journal.root / "resource-samples.jsonl",
        )
    assert result == descriptor["document_id"]
    assert len(journal.events) == event_count
    assert journal.events[3]["status"] == "RESOURCE_CHANGE_OBSERVED"
    assert journal.events[4]["wait_event_line_sha256"] == _sha(
        dispatcher.canonical_json(journal.events[3]) + b"\n"
    )


def test_halt_resume_does_not_resolve_when_resource_change_is_unobserved(tmp_path: Path) -> None:
    journal, context, descriptor = _halt_resume_fixture(tmp_path)
    with (
        mock.patch.object(dispatcher, "_halt_resume_descriptor", return_value=descriptor),
        mock.patch.object(
            dispatcher,
            "_wait_for_recovery_resource_change",
            return_value={"status": "RESOURCE_CHANGE_NOT_OBSERVED_WITHIN_BOUND"},
        ),
    ):
        with unittest.TestCase().assertRaisesRegex(
            dispatcher.DispatcherError,
            "HALT_RESUME_RESOURCE_CHANGE_NOT_OBSERVED",
        ):
            dispatcher._prepare_halt_resume(
                journal,
                context,
                sampler=lambda: {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 10_000},
                sleep_fn=lambda _seconds: None,
                samples_path=journal.root / "resource-samples.jsonl",
            )
    assert [event["event"] for event in journal.events] == ["binding", "halt", "source_adoption"]


def test_halt_resume_source_adoption_preserves_prefix_and_restarts_idempotently(tmp_path: Path) -> None:
    journal, context, descriptor = _halt_resume_fixture(tmp_path)
    journal.events.pop()
    prefix_raw = b"".join(dispatcher.canonical_json(event) + b"\n" for event in journal.events)
    journal.path.write_bytes(prefix_raw)
    descriptor["journal_prefix_sha256"] = _sha(prefix_raw)
    with mock.patch.object(dispatcher, "_halt_resume_descriptor", return_value=descriptor):
        dispatcher._verify_or_create_binding(journal, context)
        adopted_raw = journal.path.read_bytes()
        assert adopted_raw.startswith(prefix_raw)
        assert len(journal.events) == 3
        dispatcher._verify_or_create_binding(journal, context)
    assert journal.path.read_bytes() == adopted_raw
    assert journal.events[2]["event"] == "source_adoption"


def test_halt_resume_rejects_incomplete_root_descriptor(tmp_path: Path) -> None:
    journal = dispatcher.DurableJournal(tmp_path / "journal")
    context = {"adoption_evidence": {"halt_resume": {"schema": dispatcher.HALT_RESUME_SCHEMA}}}
    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "HALT_RESUME_DESCRIPTOR_INVALID"):
        dispatcher._halt_resume_descriptor(context, journal)


def test_halt_resume_only_exempts_the_exact_original_reconciled_halt(tmp_path: Path) -> None:
    document_id = "a" * 64
    continuation_id = "resume-original"
    reconciled = {
        "event": "reconciled",
        "document_id": document_id,
        "continuation_id": continuation_id,
        "decision": "HALT",
        "status": "FAILED_NO_RETRY",
    }
    terminal_halt = {"event": "halt", "document_id": document_id, "reason": "FAILED_NO_RETRY"}
    journal = dispatcher.DurableJournal(tmp_path / "journal")
    journal.events = [{"event": "binding"}, reconciled, terminal_halt]
    descriptor = {
        "reconciled_event_index": 1,
        "reconciled_event_line_sha256": _sha(dispatcher.canonical_json(reconciled) + b"\n"),
        "continuation_id": continuation_id,
        "document_id": document_id,
        "halt_event_index": 2,
    }

    dispatcher._halt_if_required(
        journal,
        dispatcher._latest_document_events(journal.events),
        halt_resume_descriptor=descriptor,
    )

    # A generation-one retry can crash after reconciliation but before its
    # terminal halt event. Same-document identity must not exempt this HALT.
    journal.events.append({
        "event": "reconciled",
        "document_id": document_id,
        "continuation_id": "memory-recovery-new-attempt",
        "decision": "HALT",
        "status": "FAILED_NO_RETRY",
    })
    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "DISPATCHER_PREVIOUSLY_HALTED"):
        dispatcher._halt_if_required(
            journal,
            dispatcher._latest_document_events(journal.events),
            halt_resume_descriptor=descriptor,
        )


def test_halt_resume_requires_original_reconciled_line_hash_and_continuation(tmp_path: Path) -> None:
    document_id = "a" * 64
    reconciled = {
        "event": "reconciled",
        "document_id": document_id,
        "continuation_id": "resume-original",
        "decision": "HALT",
        "status": "FAILED_NO_RETRY",
    }
    journal = dispatcher.DurableJournal(tmp_path / "journal")
    journal.events = [{"event": "binding"}, reconciled, {"event": "halt", "document_id": document_id}]
    descriptor = {
        "reconciled_event_index": 1,
        "reconciled_event_line_sha256": "f" * 64,
        "continuation_id": "resume-original",
        "document_id": document_id,
        "halt_event_index": 2,
    }
    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "HALT_RESUME_TERMINAL_BINDING_MISMATCH"):
        dispatcher._halt_if_required(
            journal,
            dispatcher._latest_document_events(journal.events),
            halt_resume_descriptor=descriptor,
        )


def test_duplicate_guard_accepts_only_resource_bound_generation_one_after_adopted_halt() -> None:
    document_id = "a" * 64
    queue_key = "b" * 64
    prior_plan = {
        "continuation_id": "prior",
        "state_root": "/tmp/prior-state",
        "selected_documents": [{"document_id": document_id, "prior_status": "UNPROCESSED", "source_sha256": document_id}],
    }
    prior_raw = dispatcher._json_bytes(prior_plan)
    prior_sha = _sha(prior_raw)
    recovery = {
        "generation": 1,
        "prior_state_root": prior_plan["state_root"],
        "prior_queue_idempotency_key": queue_key,
        "prior_artifact_sha256": {"receipt.json": "c" * 64},
    }
    recovery_plan = {
        "continuation_id": "memory-recovery-test",
        "state_root": "/tmp/recovery-state",
        "selected_documents": [{
            "document_id": document_id,
            "prior_status": "FAILED_NO_RETRY",
            "source_sha256": document_id,
            "recovery": recovery,
        }],
    }
    recovery_raw = dispatcher._json_bytes(recovery_plan)
    before = {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 2_000_000_000}
    after = {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES + 2_000_000_000, "swap_used_bytes": 2_000_000_000}
    measured = {
        "before": before,
        "after": after,
        "available_gain_bytes": 2_000_000_000,
        "swap_reduction_bytes": 0,
        "stable_samples": dispatcher.MEMORY_RECOVERY_STABLE_SAMPLE_COUNT,
    }
    wait_event = {
        "event": "memory_recovery_wait",
        "document_id": document_id,
        "status": "RESOURCE_CHANGE_OBSERVED",
        "decision": "CONTINUE",
        "prior_plan_sha256": prior_sha,
        "prior_state_root": prior_plan["state_root"],
        "prior_queue_idempotency_key": queue_key,
        **measured,
    }
    resolution_event = {
        "event": "halt_resolution",
        "document_id": document_id,
        "status": "RESOURCE_CHANGE_OBSERVED",
        "prior_plan_sha256": prior_sha,
        "recovery_generation": 1,
        "wait_event_line_sha256": _sha(dispatcher.canonical_json(wait_event) + b"\n"),
        **measured,
    }
    events = [
        {"event": "binding"},
        {
            "event": "plan_created",
            "document_id": document_id,
            "continuation_id": "prior",
            "state_root": prior_plan["state_root"],
            "plan_sha256": prior_sha,
            "plan_bytes_b64": base64.b64encode(prior_raw).decode("ascii"),
        },
        {"event": "plan_only_pass"},
        {"event": "dispatch_intent"},
        {
            "event": "reconciled",
            "document_id": document_id,
            "continuation_id": "prior",
            "plan_sha256": prior_sha,
            "status": "FAILED_NO_RETRY",
            "decision": "HALT",
        },
        {"event": "halt", "document_id": document_id, "reason": "FAILED_NO_RETRY"},
        {"event": "source_adoption", "document_id": document_id, "plan_sha256": prior_sha},
        wait_event,
        resolution_event,
        {
            "event": "plan_created",
            "document_id": document_id,
            "continuation_id": recovery_plan["continuation_id"],
            "state_root": recovery_plan["state_root"],
            "plan_sha256": _sha(recovery_raw),
            "plan_bytes_b64": base64.b64encode(recovery_raw).decode("ascii"),
            "recovery_generation": 1,
            "recovery_of_plan_sha256": prior_sha,
        },
    ]
    dispatcher._assert_no_duplicate_document_ids(events)
    events[6] = {"event": "source_adoption", "document_id": "b" * 64, "plan_sha256": prior_sha}
    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "CROSS_PLAN_DUPLICATE_DOCUMENT"):
        dispatcher._assert_no_duplicate_document_ids(events)


def _case_original_progress_status_is_checked_against_frozen_inventory_not_live_receipts(
    monkeypatch: _MonkeyPatch,
    tmp_path: Path,
) -> None:
    docs, original, _pilot, statuses, summary = _synthetic_context(monkeypatch, tmp_path, max_documents=1)
    document_id = docs[0]["document_id"]
    original[document_id]["status"] = "FAILED_NO_RETRY"
    frozen_inventory_statuses = summary["frozen_inventory_statuses"]
    assert isinstance(frozen_inventory_statuses, dict)
    frozen_inventory_statuses[document_id] = "FAILED_NO_RETRY"
    # The live receipt-bound view is already advanced to completion; the frozen
    # inventory still records the prior failure that the original progress file
    # must match.
    assert statuses[document_id] == "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    executed: list[str] = []

    def child_runner(path: Path, **_kwargs: object) -> dict[str, object]:
        plan = json.loads(path.read_text(encoding="utf-8"))
        executed.append(plan["selected_documents"][0]["document_id"])
        _write_terminal_state(plan, "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING", model_requests=1)
        return {"returncode": 0, "resource_stop_reason": None, "child_started": True}

    result = dispatcher.execute_once(
        authorization_path=tmp_path / "unused-auth.json",
        manifest_path=tmp_path / "unused-manifest.json",
        evidence_root=tmp_path / "evidence",
        max_documents=1,
        sampler=lambda: {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 100},
        plan_only=lambda _path: None,
        child_runner=child_runner,
        continuation_id_factory=lambda: "resume-history-overlay",
    )

    assert result["status"] == "READY_FOR_NEXT_INVOCATION"
    assert executed and executed[0] != document_id


def _case_original_progress_must_match_frozen_inventory_history(
    monkeypatch: _MonkeyPatch,
    tmp_path: Path,
) -> None:
    docs, original, _pilot, statuses, summary = _synthetic_context(monkeypatch, tmp_path, max_documents=1)
    document_id = docs[0]["document_id"]
    original[document_id]["status"] = "FAILED_NO_RETRY"
    frozen_inventory_statuses = summary["frozen_inventory_statuses"]
    assert isinstance(frozen_inventory_statuses, dict)
    frozen_inventory_statuses[document_id] = "UNPROCESSED"
    child_called = False

    def child_runner(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal child_called
        child_called = True
        raise AssertionError("source mismatch must fail before dispatch")

    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "ORIGINAL_PROGRESS_INVENTORY_STATUS_MISMATCH"):
        dispatcher.execute_once(
            authorization_path=tmp_path / "unused-auth.json",
            manifest_path=tmp_path / "unused-manifest.json",
            evidence_root=tmp_path / "evidence",
            max_documents=1,
            sampler=lambda: {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 100},
            plan_only=lambda _path: None,
            child_runner=child_runner,
        )
    assert child_called is False
    assert not (tmp_path / "evidence" / "dispatch.jsonl").exists()


def _write_terminal_state(plan: dict[str, object], status: str, *, model_requests: int | None = 1) -> None:
    document = plan["selected_documents"][0]  # type: ignore[index]
    document_id = document["document_id"]
    plan_sha = _sha(dispatcher._json_bytes(plan))
    continuation = {
        "continuation_id": plan["continuation_id"],
        "plan_sha256": plan_sha,
        "manifest_sha256": dispatcher.EXPECTED_MANIFEST_SHA256,
        "model_settings_sha256": plan["expected_model_settings_sha256"],
    }
    receipt: dict[str, object] = {
        "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
        "document_id": document_id,
        "pdf_sha256": document_id,
        "status": status,
        "manifest_sha256": dispatcher.EXPECTED_MANIFEST_SHA256,
        "continuation": continuation,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if model_requests is not None:
        receipt["model_request_count"] = model_requests
    root = Path(str(plan["state_root"]))
    receipt_path = root / "documents" / str(document_id) / "receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    progress = {
        "status": "DEFERRED" if status.startswith("DEFERRED") else "COMPLETED_WITH_PER_DOCUMENT_STATES",
        "continuation_id": plan["continuation_id"],
        "continuation_plan_sha256": plan_sha,
        "manifest_sha256": dispatcher.EXPECTED_MANIFEST_SHA256,
        "model_settings_sha256": plan["expected_model_settings_sha256"],
        "documents": [{"document_id": document_id, "status": status}],
    }
    (root / "run-progress.json").write_text(json.dumps(progress), encoding="utf-8")


def _case_runtime_guard_requires_exact_configured_312(monkeypatch: _MonkeyPatch, tmp_path: Path) -> None:
    python = Path(sys.executable).resolve()
    monkeypatch.setattr(dispatcher, "EXPECTED_RUNTIME_PYTHON", python)

    dispatcher._assert_runtime(python, dispatcher.EXPECTED_RUNTIME_VERSION)

    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "NATIVE_PYTHON_312_REQUIRED"):
        dispatcher._assert_runtime(python, "3.14.6")


def _case_singleton_plan_matches_integrated_runner_contract(tmp_path: Path, monkeypatch: _MonkeyPatch) -> None:
    doc = {"document_id": "a" * 64, "pdf_sha256": "a" * 64}
    plan, raw = dispatcher.build_singleton_plan(
        doc,
        manifest_sha256=dispatcher.EXPECTED_MANIFEST_SHA256,
        prior_progress_sha256=dispatcher.ORIGINAL_PROGRESS_SHA256,
        model_settings_sha256=batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        continuation_id="resume-test-001",
    )

    assert json.loads(raw) == plan
    assert plan["schema"] == batch.CONTINUATION_PLAN_SCHEMA
    assert plan["selected_documents"] == [{"document_id": "a" * 64, "prior_status": "UNPROCESSED", "source_sha256": "a" * 64}]
    assert plan["state_root"].endswith("/continuation-resume-test-001")
    assert plan["research_only"] == {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    assert len(plan["excluded_prior_statuses"]) == len(batch.CONTINUATION_EXCLUDED_PRIOR_STATUSES)


def _case_selection_uses_statuses_and_keeps_failures_outstanding() -> None:
    docs = _synthetic_documents()
    statuses = _synthetic_statuses(docs)
    statuses[docs[0]["document_id"]] = "FAILED_NO_RETRY"
    statuses[docs[1]["document_id"]] = "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    statuses[docs[2]["document_id"]] = "SOURCE_REPAIR_FAILED_NO_MODEL"
    pilot = {docs[position - 1]["document_id"] for position in (155, 168, 171, 176, 177, 188, 193, 199, 208, 210)}
    statuses.update({document_id: "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING" for document_id in pilot})
    prior = {docs[3]["document_id"]}

    selected, remaining = dispatcher.select_next_document(docs, statuses, pilot, prior)

    assert selected == docs[4]
    assert statuses[docs[0]["document_id"]] == "FAILED_NO_RETRY"
    assert statuses[docs[2]["document_id"]] == "SOURCE_REPAIR_FAILED_NO_MODEL"
    assert remaining == len(docs) - 3 - len(pilot) - len(prior) - 1


def _case_unprocessed_canary_selection_rejects_held_statuses() -> None:
    docs = _synthetic_documents()
    statuses = _synthetic_statuses(docs)
    statuses[docs[0]["document_id"]] = "FAILED_NO_RETRY"

    selected = dispatcher.validate_unprocessed_selection(
        [docs[1]["document_id"], docs[2]["document_id"], docs[3]["document_id"]],
        docs,
        statuses,
        expected_count=3,
    )
    assert [row["document_id"] for row in selected] == [row["document_id"] for row in docs[1:4]]

    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "FROZEN_SELECTION_DOCUMENT_NOT_RUNNABLE"):
        dispatcher.validate_unprocessed_selection(
            [docs[0]["document_id"], docs[2]["document_id"], docs[3]["document_id"]],
            docs,
            statuses,
            expected_count=3,
        )


def _case_multi_document_unprocessed_plan_is_bounded_and_runner_compatible() -> None:
    docs = [
        {"document_id": f"{index:064x}", "pdf_sha256": f"{index:064x}"}
        for index in range(1, 4)
    ]
    plan, raw = dispatcher.build_unprocessed_continuation_plan(
        docs,
        manifest_sha256=dispatcher.EXPECTED_MANIFEST_SHA256,
        prior_progress_sha256=dispatcher.ORIGINAL_PROGRESS_SHA256,
        model_settings_sha256=batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        continuation_id="three-doc-canary-test",
    )
    assert json.loads(raw) == plan
    assert len(plan["selected_documents"]) == 3
    assert all(row["prior_status"] == "UNPROCESSED" for row in plan["selected_documents"])
    assert plan["one_time_recovery_limit"] == 1


def _case_document_plan_journal_rejects_cross_plan_duplicate() -> None:
    first, first_raw = dispatcher.build_singleton_plan(
        {"document_id": "a" * 64, "pdf_sha256": "a" * 64},
        manifest_sha256=dispatcher.EXPECTED_MANIFEST_SHA256,
        prior_progress_sha256=dispatcher.ORIGINAL_PROGRESS_SHA256,
        model_settings_sha256=batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        continuation_id="duplicate-first",
    )
    second, second_raw = dispatcher.build_singleton_plan(
        {"document_id": "a" * 64, "pdf_sha256": "a" * 64},
        manifest_sha256=dispatcher.EXPECTED_MANIFEST_SHA256,
        prior_progress_sha256=dispatcher.ORIGINAL_PROGRESS_SHA256,
        model_settings_sha256=batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        continuation_id="duplicate-second",
    )
    events = [
        {"event": "binding"},
        {
            "event": "plan_created",
            "document_id": "a" * 64,
            "continuation_id": first["continuation_id"],
            "state_root": first["state_root"],
            "plan_bytes_b64": base64.b64encode(first_raw).decode("ascii"),
        },
        {
            "event": "plan_created",
            "document_id": "a" * 64,
            "continuation_id": second["continuation_id"],
            "state_root": second["state_root"],
            "plan_bytes_b64": base64.b64encode(second_raw).decode("ascii"),
        },
    ]

    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "CROSS_PLAN_DUPLICATE_DOCUMENT"):
        dispatcher._assert_no_duplicate_document_ids(events)


def _case_failure_receipt_stops_before_next_document(monkeypatch: _MonkeyPatch, tmp_path: Path) -> None:
    _synthetic_context(monkeypatch, tmp_path, max_documents=3)
    plans: list[dict[str, object]] = []

    def child_runner(path: Path, **_kwargs: object) -> dict[str, object]:
        plan = json.loads(path.read_text(encoding="utf-8"))
        plans.append(plan)
        _write_terminal_state(plan, "FAILED_NO_RETRY", model_requests=1)
        return {"returncode": 0, "resource_stop_reason": None, "child_started": True}

    result = dispatcher.execute_once(
        authorization_path=tmp_path / "unused-auth.json",
        manifest_path=tmp_path / "unused-manifest.json",
        evidence_root=tmp_path / "evidence",
        max_documents=3,
        sampler=lambda: {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 100},
        plan_only=lambda _path: None,
        child_runner=child_runner,
        continuation_id_factory=lambda: "resume-test-fail",
    )

    assert len(plans) == 1
    assert result["status"] == "HALTED"
    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "DISPATCHER_PREVIOUSLY_HALTED"):
        dispatcher.execute_once(
            authorization_path=tmp_path / "unused-auth.json",
            manifest_path=tmp_path / "unused-manifest.json",
            evidence_root=tmp_path / "evidence",
            max_documents=1,
            sampler=lambda: {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 100},
            plan_only=lambda _path: None,
            child_runner=child_runner,
        )


def _case_deferred_resume_reuses_same_plan_and_state_root(monkeypatch: _MonkeyPatch, tmp_path: Path) -> None:
    _synthetic_context(monkeypatch, tmp_path, max_documents=2)
    seen_paths: list[Path] = []
    seen_ids: list[str] = []
    statuses = iter(("DEFERRED_ANNOUNCEMENT_PRIORITY", "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"))

    def child_runner(path: Path, **_kwargs: object) -> dict[str, object]:
        plan = json.loads(path.read_text(encoding="utf-8"))
        seen_paths.append(path)
        seen_ids.append(str(plan["continuation_id"]))
        _write_terminal_state(plan, next(statuses), model_requests=0 if len(seen_paths) == 1 else 1)
        return {"returncode": 0, "resource_stop_reason": None, "child_started": True}

    common = {
        "authorization_path": tmp_path / "unused-auth.json",
        "manifest_path": tmp_path / "unused-manifest.json",
        "evidence_root": tmp_path / "evidence",
        "max_documents": 1,
        "sampler": lambda: {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 100},
        "plan_only": lambda _path: None,
        "child_runner": child_runner,
        "continuation_id_factory": lambda: "resume-same-plan",
    }
    first = dispatcher.execute_once(**common)
    second = dispatcher.execute_once(**common)

    assert first["latest_terminal_status"] == "DEFERRED_ANNOUNCEMENT_PRIORITY"
    assert second["latest_terminal_status"] == "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
    assert seen_paths[0] == seen_paths[1]
    assert seen_ids == ["resume-same-plan", "resume-same-plan"]
    events = [json.loads(line) for line in (tmp_path / "evidence/dispatch.jsonl").read_text().splitlines()]
    assert sum(event.get("event") == "plan_created" for event in events) == 1
    assert sum(event.get("event") == "dispatch_intent" for event in events) == 2


def _case_ambiguous_dispatch_intent_fails_closed_on_next_invocation(monkeypatch: _MonkeyPatch, tmp_path: Path) -> None:
    _synthetic_context(monkeypatch, tmp_path, max_documents=2)
    common = {
        "authorization_path": tmp_path / "unused-auth.json",
        "manifest_path": tmp_path / "unused-manifest.json",
        "evidence_root": tmp_path / "evidence",
        "max_documents": 1,
        "sampler": lambda: {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 100},
        "plan_only": lambda _path: None,
        "continuation_id_factory": lambda: "resume-ambiguous",
    }

    with unittest.TestCase().assertRaisesRegex(RuntimeError, "simulated crash"):
        dispatcher.execute_once(**common, child_runner=lambda _path, **_kwargs: (_ for _ in ()).throw(RuntimeError("simulated crash")))
    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "DISPATCH_OUTCOME_AMBIGUOUS_FAIL_CLOSED"):
        dispatcher.execute_once(**common, child_runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not resubmit")))


def _case_missing_terminal_receipt_is_recorded_and_halts(monkeypatch: _MonkeyPatch, tmp_path: Path) -> None:
    _synthetic_context(monkeypatch, tmp_path, max_documents=2)
    plans: list[Path] = []

    def child_runner(path: Path, **_kwargs: object) -> dict[str, object]:
        plans.append(path)
        return {"returncode": 2, "resource_stop_reason": None, "child_started": True, "stdout_sha256": "a" * 64}

    result = dispatcher.execute_once(
        authorization_path=tmp_path / "unused-auth.json",
        manifest_path=tmp_path / "unused-manifest.json",
        evidence_root=tmp_path / "evidence",
        max_documents=2,
        sampler=lambda: {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 100},
        plan_only=lambda _path: None,
        child_runner=child_runner,
        continuation_id_factory=lambda: "resume-missing-receipt",
    )

    assert result["status"] == "HALTED"
    assert len(plans) == 1
    events = [json.loads(line) for line in (tmp_path / "evidence/dispatch.jsonl").read_text().splitlines()]
    ambiguous = [event for event in events if event.get("status") == "AMBIGUOUS_TERMINAL_RECEIPT"]
    assert len(ambiguous) == 1
    assert ambiguous[0]["reconciliation_error"] == "EXECUTION_PROGRESS_UNAVAILABLE"


def _case_source_only_receipt_can_continue_only_without_model_activity(tmp_path: Path) -> None:
    doc = {"document_id": "a" * 64, "pdf_sha256": "a" * 64}
    plan, _raw = dispatcher.build_singleton_plan(
        doc,
        manifest_sha256=dispatcher.EXPECTED_MANIFEST_SHA256,
        prior_progress_sha256=dispatcher.ORIGINAL_PROGRESS_SHA256,
        model_settings_sha256=batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        continuation_id="resume-source-only",
    )
    monkeypatch_plan = dict(plan)
    monkeypatch_plan["state_root"] = str(tmp_path / "state")
    receipt = {
        "document_id": "a" * 64,
        "pdf_sha256": "a" * 64,
        "status": "SOURCE_INVALID",
        "manifest_sha256": dispatcher.EXPECTED_MANIFEST_SHA256,
        "continuation": {
            "continuation_id": "resume-source-only",
            "plan_sha256": _sha(dispatcher._json_bytes(plan)),
            "manifest_sha256": dispatcher.EXPECTED_MANIFEST_SHA256,
            "model_settings_sha256": plan["expected_model_settings_sha256"],
        },
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    root = Path(monkeypatch_plan["state_root"])
    (root / "documents" / ("a" * 64)).mkdir(parents=True)
    (root / "documents" / ("a" * 64) / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    (root / "run-progress.json").write_text(json.dumps({
        "status": "COMPLETED_WITH_PER_DOCUMENT_STATES",
        "continuation_id": "resume-source-only",
        "continuation_plan_sha256": _sha(dispatcher._json_bytes(plan)),
        "manifest_sha256": dispatcher.EXPECTED_MANIFEST_SHA256,
        "model_settings_sha256": plan["expected_model_settings_sha256"],
        "documents": [{"document_id": "a" * 64, "status": "SOURCE_INVALID"}],
    }), encoding="utf-8")

    decision = dispatcher._reconcile_singleton(
        monkeypatch_plan,
        _sha(dispatcher._json_bytes(plan)),
        child={"returncode": 0, "resource_stop_reason": None},
    )
    assert decision["decision"] == "CONTINUE"
    receipt["model_request_count"] = 1
    (root / "documents" / ("a" * 64) / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "SOURCE_ONLY_RECEIPT_MODEL_ACTIVITY_UNCLEAR"):
        dispatcher._reconcile_singleton(
            monkeypatch_plan,
            _sha(dispatcher._json_bytes(plan)),
            child={"returncode": 0, "resource_stop_reason": None},
        )


def _case_resource_thresholds_use_only_existing_available_and_swap_metrics() -> None:
    assert dispatcher._resource_stop_reason({"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 100 + dispatcher.MAX_SWAP_GROWTH_BYTES}, 100) is None
    assert dispatcher._resource_stop_reason({"available_bytes": dispatcher.MIN_AVAILABLE_BYTES - 1, "swap_used_bytes": 100}, 100) == "AVAILABLE_MEMORY_BELOW_8_GIB"
    assert dispatcher._resource_stop_reason({"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 101 + dispatcher.MAX_SWAP_GROWTH_BYTES}, 100) == "SWAP_GROWTH_ABOVE_512_MIB"
    assert dispatcher._resource_stop_reason({"available_bytes": None, "swap_used_bytes": 100}, 100) == "RESOURCE_SAMPLE_CANNOT_CONFIRM"


def _case_recovery_wait_requires_a_stable_observed_resource_change() -> None:
    failure_sample = {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 900}
    samples = iter((
        {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES + dispatcher.MEMORY_RECOVERY_AVAILABLE_GAIN_BYTES, "swap_used_bytes": 900},
        {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES + dispatcher.MEMORY_RECOVERY_AVAILABLE_GAIN_BYTES, "swap_used_bytes": 900},
    ))
    sleeps: list[float] = []
    persisted: list[dict[str, object]] = []

    result = dispatcher._wait_for_recovery_resource_change(
        failure_sample,
        baseline_swap_used=900,
        sampler=lambda: next(samples),
        sleep_fn=sleeps.append,
        persist=persisted.append,
        timeout_seconds=dispatcher.MEMORY_RECOVERY_POLL_SECONDS * 3,
    )

    assert result["status"] == "RESOURCE_CHANGE_OBSERVED"
    assert result["available_gain_bytes"] == dispatcher.MEMORY_RECOVERY_AVAILABLE_GAIN_BYTES
    assert result["stable_samples"] == dispatcher.MEMORY_RECOVERY_STABLE_SAMPLE_COUNT
    assert sleeps == [dispatcher.MEMORY_RECOVERY_POLL_SECONDS] * 2
    assert len(persisted) == 2


def _case_memory_recovery_retry_is_bounded_and_second_failure_isolated(
    monkeypatch: _MonkeyPatch,
    tmp_path: Path,
) -> None:
    docs, _original, _pilot, _statuses, _summary = _synthetic_context(monkeypatch, tmp_path, max_documents=2)
    plans: list[dict[str, object]] = []
    def fake_builder(
        prior_plan: dict[str, object],
        prior_raw: bytes,
        document: dict[str, str],
        *,
        model_settings_sha256: str,
    ) -> tuple[dict[str, object], bytes]:
        recovery_plan, _ = dispatcher.build_singleton_plan(
            document,
            manifest_sha256=dispatcher.EXPECTED_MANIFEST_SHA256,
            prior_progress_sha256=dispatcher.ORIGINAL_PROGRESS_SHA256,
            model_settings_sha256=model_settings_sha256,
            continuation_id="memory-recovery-test",
        )
        recovery_plan["selected_documents"][0]["prior_status"] = "FAILED_NO_RETRY"
        recovery_plan["selected_documents"][0]["recovery"] = {
            "generation": 1,
            "prior_state_root": prior_plan["state_root"],
            "prior_queue_idempotency_key": "f" * 64,
            "prior_artifact_sha256": {},
        }
        recovery_plan["state_root"] = str(tmp_path / "state" / "recovery-test")
        recovery_raw = dispatcher._json_bytes(recovery_plan)
        return recovery_plan, recovery_raw

    monkeypatch.setattr(dispatcher, "build_memory_recovery_plan", fake_builder)
    monkeypatch.setattr(batch, "validate_continuation_plan", lambda path, **_kwargs: {
        "plan_sha256": _sha(path.read_bytes()),
    })

    def child_runner(path: Path, **_kwargs: object) -> dict[str, object]:
        plan = json.loads(path.read_text(encoding="utf-8"))
        plans.append(plan)
        status = "FAILED_NO_RETRY" if len(plans) <= 2 else "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"
        _write_terminal_state(plan, status, model_requests=1)
        return {
            "returncode": 0,
            "resource_stop_reason": None,
            "child_started": True,
            "last_resource_sample": {
                "available_bytes": dispatcher.MIN_AVAILABLE_BYTES,
                "swap_used_bytes": 900,
            },
        }

    samples = iter((
        {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 900},
        {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES + dispatcher.MEMORY_RECOVERY_AVAILABLE_GAIN_BYTES, "swap_used_bytes": 900},
        {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES + dispatcher.MEMORY_RECOVERY_AVAILABLE_GAIN_BYTES, "swap_used_bytes": 900},
    ))
    result = dispatcher.execute_once(
        authorization_path=tmp_path / "unused-auth.json",
        manifest_path=tmp_path / "unused-manifest.json",
        evidence_root=tmp_path / "evidence",
        max_documents=2,
        sampler=lambda: next(samples),
        sleep_fn=lambda _seconds: None,
        plan_only=lambda _path: None,
        child_runner=child_runner,
        continuation_id_factory=lambda: f"resume-test-{len(plans)}",
    )

    assert len(plans) == 3
    assert plans[0]["selected_documents"][0]["document_id"] == plans[1]["selected_documents"][0]["document_id"]
    assert plans[1]["selected_documents"][0]["recovery"]["generation"] == 1
    assert plans[2]["selected_documents"][0]["document_id"] != plans[0]["selected_documents"][0]["document_id"]
    assert result["status"] == "READY_FOR_NEXT_INVOCATION"
    events = [json.loads(line) for line in (tmp_path / "evidence/dispatch.jsonl").read_text().splitlines()]
    recovered = [event for event in events if event.get("event") == "reconciled" and event.get("memory_recovery_status") == "SINGLE_RECOVERY_FAILED_ISOLATED"]
    assert len(recovered) == 1
    assert not any(event.get("event") == "halt" for event in events)
    dispatcher._assert_no_duplicate_document_ids(events)
    tampered_events = [dict(event) for event in events]
    wait_event = next(event for event in tampered_events if event.get("event") == "memory_recovery_wait")
    wait_event["available_gain_bytes"] = 0
    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "CROSS_PLAN_DUPLICATE_DOCUMENT"):
        dispatcher._assert_no_duplicate_document_ids(tampered_events)


def _case_resource_failure_sends_one_owned_sigterm_then_waits(tmp_path: Path) -> None:
    class FakeProc:
        pid = 123

        def __init__(self) -> None:
            self.signals: list[int] = []
            self.returncode: int | None = None
            self.stdout = io.StringIO("{}\n")

        def poll(self) -> int | None:
            return self.returncode

        def send_signal(self, value: int) -> None:
            self.signals.append(value)
            self.returncode = -value

        def wait(self, timeout: float | None = None) -> int:
            if self.returncode is None:
                raise dispatcher.subprocess.TimeoutExpired("fake", timeout)
            return self.returncode

    proc = FakeProc()
    samples = iter((
        {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 10},
        {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES - 1, "swap_used_bytes": 10},
    ))
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    result = dispatcher._run_execution_child(
        plan_path,
        baseline_swap_used=10,
        samples_path=tmp_path / "samples.jsonl",
        sampler=lambda: next(samples),
        popen=lambda *_args, **_kwargs: proc,
        sleep_fn=lambda _seconds: None,
        create_time_fn=lambda _pid: 7.0,
        signal_fn=lambda child, owned_time: child.send_signal(signal.SIGTERM) if owned_time == 7.0 else (_ for _ in ()).throw(AssertionError("wrong child identity")),
    )
    assert proc.signals == [signal.SIGTERM]
    assert result["resource_stop_reason"] == "AVAILABLE_MEMORY_BELOW_8_GIB"
    assert result["returncode"] == -signal.SIGTERM


def _case_resource_sampler_failure_before_spawn_never_starts_runner(tmp_path: Path) -> None:
    called = False

    def popen(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        return object()

    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}", encoding="utf-8")
    result = dispatcher._run_execution_child(
        plan_path,
        baseline_swap_used=1,
        samples_path=tmp_path / "samples.jsonl",
        sampler=lambda: (_ for _ in ()).throw(dispatcher.DispatcherError("missing")),
        popen=popen,
    )
    assert called is False
    assert result["child_started"] is False
    assert result["resource_stop_reason"] == "RESOURCE_SAMPLE_CANNOT_CONFIRM"


def _case_predispatch_resource_failure_halts_without_receipt(monkeypatch: _MonkeyPatch, tmp_path: Path) -> None:
    _synthetic_context(monkeypatch, tmp_path, max_documents=2)
    plans: list[Path] = []

    def child_runner(path: Path, **_kwargs: object) -> dict[str, object]:
        plans.append(path)
        return {
            "returncode": None,
            "resource_stop_reason": "RESOURCE_SAMPLE_CANNOT_CONFIRM",
            "child_started": False,
            "stdout_sha256": None,
        }

    result = dispatcher.execute_once(
        authorization_path=tmp_path / "unused-auth.json",
        manifest_path=tmp_path / "unused-manifest.json",
        evidence_root=tmp_path / "evidence",
        max_documents=2,
        sampler=lambda: {"available_bytes": dispatcher.MIN_AVAILABLE_BYTES, "swap_used_bytes": 100},
        plan_only=lambda _path: None,
        child_runner=child_runner,
        continuation_id_factory=lambda: "resume-predispatch-stop",
    )

    assert result["status"] == "HALTED"
    assert len(plans) == 1
    events = [json.loads(line) for line in (tmp_path / "evidence/dispatch.jsonl").read_text().splitlines()]
    assert any(event.get("status") == "PRE_DISPATCH_RESOURCE_STOP" for event in events)
    assert not any(event.get("event") == "plan_created" and event.get("document_id") == "b" * 64 for event in events)


def _case_child_command_uses_native_module_entrypoint() -> None:
    plan_path = Path("/tmp/one-plan.json")

    command = dispatcher._make_command(plan_path, execute=True)

    assert command == [
        str(dispatcher.EXPECTED_RUNTIME_PYTHON),
        "-m",
        "ops.run_pdf_research_batch",
        "--manifest",
        str(batch.DEFAULT_MANIFEST),
        "--continuation-plan",
        str(plan_path),
        "--execute",
    ]


def _case_plan_only_subprocess_requires_singleton_binding(tmp_path: Path) -> None:
    doc = {"document_id": "a" * 64, "pdf_sha256": "a" * 64}
    plan, raw = dispatcher.build_singleton_plan(
        doc,
        manifest_sha256=dispatcher.EXPECTED_MANIFEST_SHA256,
        prior_progress_sha256=dispatcher.ORIGINAL_PROGRESS_SHA256,
        model_settings_sha256=batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        continuation_id="resume-plan-only",
    )
    path = tmp_path / "plan.json"
    path.write_bytes(raw)

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        assert command[:3] == [str(dispatcher.EXPECTED_RUNTIME_PYTHON), "-m", "ops.run_pdf_research_batch"]
        assert kwargs["cwd"] == str(dispatcher.PROJECT_ROOT)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "PLAN_ONLY",
            "continuation_id": plan["continuation_id"],
            "continuation_plan_sha256": _sha(raw),
            "selected_document_count": 1,
            "state_root": plan["state_root"],
        }))

    dispatcher._run_plan_only(path, popen=run)

    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "RUNNER_PLAN_ONLY_BINDING_MISMATCH"):
        dispatcher._run_plan_only(path, popen=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "PLAN_ONLY", "continuation_id": "wrong", "selected_document_count": 1, "state_root": plan["state_root"], "continuation_plan_sha256": _sha(raw)}),
        ))


def _case_invalid_gate_auth_stops_before_reading_actual_pilot_receipts(tmp_path: Path, monkeypatch: _MonkeyPatch) -> None:
    continuation_root = tmp_path / "continuation"
    continuation_root.mkdir()
    monkeypatch.setattr(dispatcher, "CONTINUATION_ROOT", continuation_root)
    auth_path = continuation_root / "ROOT_REMAINING_EXECUTION_AUTHORIZATION.json"
    monkeypatch.setattr(dispatcher, "AUTHORIZATION_PATH", auth_path)
    monkeypatch.setattr(dispatcher, "EXPECTED_SCOPE_SHA256", "a" * 64)
    monkeypatch.setattr(dispatcher, "EXPECTED_RUNNER_SHA256", "b" * 64)
    monkeypatch.setattr(dispatcher, "EXPECTED_MANIFEST_SHA256", "c" * 64)
    monkeypatch.setattr(dispatcher, "ORIGINAL_PROGRESS_SHA256", "d" * 64)
    monkeypatch.setattr(dispatcher, "EXPECTED_RUNTIME_PYTHON", Path("/configured/python"))

    pilot_ids = [f"{index:064x}" for index in range(1, 11)]
    pilot_plan = {
        "schema": dispatcher.PLAN_SCHEMA,
        "continuation_id": "pilot-frozen",
        "observed_model_settings_sha256": batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        "state_root": str(tmp_path / "state" / "pilot"),
        "selected_documents": [{"document_id": item} for item in pilot_ids],
    }
    pilot_plan_path = continuation_root / "pilot-plan.json"
    pilot_plan_raw = json.dumps(pilot_plan).encode()
    pilot_plan_path.write_bytes(pilot_plan_raw)
    monkeypatch.setattr(dispatcher, "PILOT_PLAN_PATH", pilot_plan_path)
    monkeypatch.setattr(dispatcher, "EXPECTED_PILOT_PLAN_SHA256", _sha(pilot_plan_raw))
    selection = {
        "selection": {
            "selection_sha256": "e" * 64,
            "selected_documents": [{"document_id": item} for item in pilot_ids],
        }
    }
    selection_path = continuation_root / "pilot-selection.json"
    selection_raw = json.dumps(selection).encode()
    selection_path.write_bytes(selection_raw)
    monkeypatch.setattr(dispatcher, "PILOT_SELECTION_PATH", selection_path)
    monkeypatch.setattr(dispatcher, "EXPECTED_PILOT_SELECTION_FILE_SHA256", _sha(selection_raw))
    monkeypatch.setattr(dispatcher, "EXPECTED_PILOT_SELECTION_SHA256", "e" * 64)

    resource_path = continuation_root / "resource.json"
    resource = {"status": "FAIL"}
    resource_raw = json.dumps(resource).encode()
    resource_path.write_bytes(resource_raw)
    empty_ref = {"path": str(resource_path), "sha256": _sha(resource_raw)}
    auth = {
        "schema": dispatcher.AUTHORIZATION_SCHEMA,
        "status": "AUTHORIZED",
        "authorization_id": "test-auth",
        "scope_sha256": "a" * 64,
        "dispatcher_sha256": _sha(Path(dispatcher.__file__).read_bytes()),
        "runner_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
        "original_progress_sha256": "d" * 64,
        "runtime_python": "/configured/python",
        "runtime_version": dispatcher.EXPECTED_RUNTIME_VERSION,
        "model_settings_sha256": batch.CONTINUATION_CANDIDATE_SETTINGS_SHA256,
        "max_documents": 1,
        "pilot": {
            "plan_sha256": dispatcher.EXPECTED_PILOT_PLAN_SHA256,
            "selection_file_sha256": dispatcher.EXPECTED_PILOT_SELECTION_FILE_SHA256,
            "selection_sha256": dispatcher.EXPECTED_PILOT_SELECTION_SHA256,
            "progress": {"path": str(tmp_path / "outside" / "run-progress.json"), "sha256": "f" * 64},
            "receipts": [],
        },
        "resource_gate": empty_ref,
        "sentinel_gate": empty_ref,
        "reviewer_receipt": empty_ref,
        "adoption_receipt": empty_ref,
        "research_only": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    auth_path.write_text(json.dumps(auth), encoding="utf-8")
    monkeypatch.setattr(dispatcher, "_validate_pilot_receipts", lambda *_args: (_ for _ in ()).throw(AssertionError("pilot state read before gates")))

    with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "RESOURCE_GATE_EVIDENCE_INVALID"):
        dispatcher.load_and_validate_authorization(auth_path)


def _case_child_signal_requires_creation_time_match() -> None:
    psutil_stub = ModuleType("psutil")
    psutil_stub.Process = lambda _pid: SimpleNamespace(create_time=lambda: 17.0)  # type: ignore[attr-defined]

    class FakeProc:
        pid = 42

        def __init__(self) -> None:
            self.signals: list[int] = []

        def poll(self) -> int | None:
            return None

        def send_signal(self, value: int) -> None:
            self.signals.append(value)

    proc = FakeProc()
    with mock.patch.dict(sys.modules, {"psutil": psutil_stub}):
        dispatcher._signal_owned_child(proc, 17.0)
        assert proc.signals == [signal.SIGTERM]
        proc.signals.clear()
        with unittest.TestCase().assertRaisesRegex(dispatcher.DispatcherError, "CHILD_OWNERSHIP_CHANGED"):
            dispatcher._signal_owned_child(proc, 18.0)
    assert proc.signals == []


class TestRemainingOnce(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.monkeypatch = _MonkeyPatch(self)

    def test_runtime_guard(self) -> None:
        _case_runtime_guard_requires_exact_configured_312(self.monkeypatch, self.tmp_path)

    def test_default_evidence_root_is_versioned_for_this_run(self) -> None:
        self.assertEqual(
            dispatcher.EVIDENCE_ROOT,
            Path("/Users/lexi/Desktop/学习/agents调试/V4_PDF_TOOL_ENABLED_COMPLETION_20261019_R1/remaining-execution-r1"),
        )
        self.assertNotEqual(dispatcher.EVIDENCE_ROOT, dispatcher.CONTINUATION_ROOT / "resume-writer")

    def test_singleton_plan(self) -> None:
        _case_singleton_plan_matches_integrated_runner_contract(self.tmp_path, self.monkeypatch)

    def test_selection_uses_statuses(self) -> None:
        _case_selection_uses_statuses_and_keeps_failures_outstanding()

    def test_unprocessed_canary_selection(self) -> None:
        _case_unprocessed_canary_selection_rejects_held_statuses()

    def test_original_progress_accepts_exact_receipt_bound_status_advance(self) -> None:
        _case_original_progress_status_is_checked_against_frozen_inventory_not_live_receipts(
            self.monkeypatch,
            self.tmp_path,
        )

    def test_original_progress_must_match_frozen_inventory_history(self) -> None:
        _case_original_progress_must_match_frozen_inventory_history(self.monkeypatch, self.tmp_path)

    def test_current_canary_receipts_are_folded_before_dispatch(self) -> None:
        _manifest, manifest_sha, documents = batch.load_manifest(batch.DEFAULT_MANIFEST)
        statuses, summary = dispatcher.load_current_completion_statuses(
            documents,
            manifest_sha256=manifest_sha,
        )
        for document_id in (*dispatcher.THREE_DOCUMENT_CANARY_IDS, dispatcher.TOOL_CANARY_DOCUMENT_ID):
            self.assertEqual(statuses[document_id], "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING")
        self.assertEqual(summary["completed_count"], dispatcher.CURRENT_COMPLETED_DOCUMENT_COUNT)
        self.assertEqual(summary["outstanding_count"], dispatcher.CURRENT_OUTSTANDING_DOCUMENT_COUNT)
        self.assertEqual(summary["runnable_unprocessed_count"], dispatcher.EXPECTED_POST_PILOT_COHORT)
        selected, remaining = dispatcher.select_next_document(documents, statuses, set(), set())
        self.assertIsNotNone(selected)
        self.assertNotIn(selected["document_id"], set(dispatcher.THREE_DOCUMENT_CANARY_IDS))
        self.assertNotEqual(selected["document_id"], dispatcher.TOOL_CANARY_DOCUMENT_ID)
        self.assertEqual(remaining, dispatcher.EXPECTED_POST_PILOT_COHORT)

    def test_multi_document_plan(self) -> None:
        _case_multi_document_unprocessed_plan_is_bounded_and_runner_compatible()

    def test_memory_recovery_plan_reuses_exact_frozen_failure_chain(self) -> None:
        _manifest, manifest_sha, documents = batch.load_manifest(batch.DEFAULT_MANIFEST)
        self.assertEqual(manifest_sha, dispatcher.EXPECTED_MANIFEST_SHA256)
        prior_raw = dispatcher.THREE_DOCUMENT_CANARY_PLAN_PATH.read_bytes()
        prior_plan = json.loads(prior_raw.decode("utf-8"))
        document = next(
            row for row in documents
            if row.get("document_id") == "eeed6e4916c2a8b44d0f3911d9303de754e6164d8d33cc7f11f4c15dae9f49a5"
        )

        plan, raw = dispatcher.build_memory_recovery_plan(
            prior_plan,
            prior_raw,
            document,
            model_settings_sha256=dispatcher.EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256,
            continuation_id=dispatcher.AI_VIDEO_RECOVERY_CONTINUATION_ID,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(_sha(raw), dispatcher.AI_VIDEO_RECOVERY_PLAN_SHA256)
        self.assertEqual(raw, dispatcher.AI_VIDEO_RECOVERY_PLAN_PATH.read_bytes())
        self.assertEqual(plan["selected_documents"][0]["recovery"]["generation"], 1)

    def test_memory_recovery_accepts_missing_round_status_only_for_bound_prefill_failure(self) -> None:
        _manifest, manifest_sha, documents = batch.load_manifest(batch.DEFAULT_MANIFEST)
        self.assertEqual(manifest_sha, dispatcher.EXPECTED_MANIFEST_SHA256)
        journal_events = [
            json.loads(line)
            for line in dispatcher.EVIDENCE_ROOT.joinpath("dispatch.jsonl").read_bytes().splitlines()
        ]
        prior_event = next(
            event for event in journal_events
            if event.get("event") == "plan_created"
            and event.get("document_id") == "e2d660f090a972a43ba68bba37eea0a5889c1c6bef1bb760a0334fd0c4da6813"
        )
        prior_raw = base64.b64decode(prior_event["plan_bytes_b64"], validate=True)
        prior_plan = json.loads(prior_raw.decode("utf-8"))
        document_id = prior_event["document_id"]
        document = next(row for row in documents if row.get("document_id") == document_id)
        state_root = Path(prior_plan["state_root"])
        prior_receipt = json.loads((state_root / "documents" / document_id / "receipt.json").read_bytes())
        failed_chunk = next(
            row for row in prior_receipt["chunks"]
            if row.get("status") == "FAILED_NO_RETRY"
        )
        queue_key = failed_chunk["queue_item"]["idempotency_key"]
        stream_receipt_path = state_root / "evidence" / "streams" / queue_key / "attempt-0001" / "stream-receipt.json"
        original_read = dispatcher._read_regular
        original_stream_receipt = json.loads(original_read(stream_receipt_path, "fixture").decode("utf-8"))
        self.assertEqual(original_stream_receipt.get("status"), "FAILED")
        self.assertNotIn("status", original_stream_receipt["rounds"][0])

        def build_with_round_status(status: str | None, *, omit: bool) -> tuple[dict[str, object] | None, bytes | None]:
            def read_with_round_status(path: Path, code: str) -> bytes:
                raw = original_read(path, code)
                if path == stream_receipt_path:
                    receipt = json.loads(raw.decode("utf-8"))
                    if omit:
                        receipt["rounds"][0].pop("status", None)
                    else:
                        receipt["rounds"][0]["status"] = status
                    return dispatcher._json_bytes(receipt)
                return raw

            with mock.patch.object(dispatcher, "_read_regular", side_effect=read_with_round_status):
                return dispatcher.build_memory_recovery_plan(
                    prior_plan,
                    prior_raw,
                    document,
                    model_settings_sha256=dispatcher.EXPECTED_TOOL_CANARY_MODEL_SETTINGS_SHA256,
                )

        recovered = build_with_round_status(None, omit=True)
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered[0]["selected_documents"][0]["recovery"]["generation"], 1)
        for explicit_status in ("SUCCEEDED", "PENDING", None):
            with self.assertRaisesRegex(dispatcher.DispatcherError, "MEMORY_RECOVERY_PRIOR_EVIDENCE_MISMATCH"):
                build_with_round_status(explicit_status, omit=False)

    def test_duplicate_rejection(self) -> None:
        _case_document_plan_journal_rejects_cross_plan_duplicate()

    def test_failure_stop(self) -> None:
        _case_failure_receipt_stops_before_next_document(self.monkeypatch, self.tmp_path)

    def test_deferred_resume(self) -> None:
        _case_deferred_resume_reuses_same_plan_and_state_root(self.monkeypatch, self.tmp_path)

    def test_ambiguous_dispatch(self) -> None:
        _case_ambiguous_dispatch_intent_fails_closed_on_next_invocation(self.monkeypatch, self.tmp_path)

    def test_missing_receipt_halts(self) -> None:
        _case_missing_terminal_receipt_is_recorded_and_halts(self.monkeypatch, self.tmp_path)

    def test_source_only_accounting(self) -> None:
        _case_source_only_receipt_can_continue_only_without_model_activity(self.tmp_path)

    def test_resource_thresholds(self) -> None:
        _case_resource_thresholds_use_only_existing_available_and_swap_metrics()

    def test_recovery_wait_requires_resource_change(self) -> None:
        _case_recovery_wait_requires_a_stable_observed_resource_change()

    def test_memory_recovery_retries_once_and_isolates_second_failure(self) -> None:
        _case_memory_recovery_retry_is_bounded_and_second_failure_isolated(self.monkeypatch, self.tmp_path)

    def test_resource_owned_sigterm(self) -> None:
        _case_resource_failure_sends_one_owned_sigterm_then_waits(self.tmp_path)

    def test_resource_sample_failure(self) -> None:
        _case_resource_sampler_failure_before_spawn_never_starts_runner(self.tmp_path)

    def test_predispatch_resource_stop(self) -> None:
        _case_predispatch_resource_failure_halts_without_receipt(self.monkeypatch, self.tmp_path)

    def test_native_module_command(self) -> None:
        _case_child_command_uses_native_module_entrypoint()

    def test_plan_only_binding(self) -> None:
        _case_plan_only_subprocess_requires_singleton_binding(self.tmp_path)

    def test_gate_order(self) -> None:
        _case_invalid_gate_auth_stops_before_reading_actual_pilot_receipts(self.tmp_path, self.monkeypatch)

    def test_owned_child_signal(self) -> None:
        _case_child_signal_requires_creation_time_match()


if __name__ == "__main__":
    unittest.main()
