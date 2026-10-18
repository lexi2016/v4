from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from types import ModuleType
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

CANONICAL_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
sys.path.insert(0, str(CANONICAL_ROOT))
from ops import run_pdf_research_batch as batch

DISPATCHER_PATH = Path(__file__).resolve().parents[1] / "ops" / "run_pdf_research_remaining_once.py"
_spec = importlib.util.spec_from_file_location("remaining_once_dispatcher_test", DISPATCHER_PATH)
assert _spec is not None and _spec.loader is not None
dispatcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dispatcher)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _synthetic_documents() -> list[dict[str, str]]:
    rows = [
        {"document_id": f"{index:064x}", "pdf_sha256": f"{index:064x}"}
        for index in range(1, 2210)
    ]
    rows[dispatcher.QUARANTINE_POSITION_1_BASED - 1] = {
        "document_id": dispatcher.QUARANTINE_DOCUMENT_ID,
        "pdf_sha256": dispatcher.QUARANTINE_DOCUMENT_ID,
    }
    return rows


class _MonkeyPatch:
    def __init__(self, test_case: unittest.TestCase):
        self.test_case = test_case

    def setattr(self, target: object, name: str, value: object) -> None:
        old = getattr(target, name)
        setattr(target, name, value)
        self.test_case.addCleanup(setattr, target, name, old)


def _synthetic_context(monkeypatch: _MonkeyPatch, tmp_path: Path, *, max_documents: int = 4) -> tuple[list[dict[str, str]], dict[str, dict[str, str]], set[str]]:
    monkeypatch.setattr(dispatcher, "_assert_runtime", lambda: None)
    monkeypatch.setattr(dispatcher, "_verify_static_bindings", lambda: {"scope_sha256": "a" * 64, "runner_sha256": "b" * 64})
    monkeypatch.setattr(batch, "DEFAULT_STATE_ROOT", tmp_path / "state" / "r3")
    docs = _synthetic_documents()
    original = {row["document_id"]: {"status": "MODEL_GENERATED_TEXT_COMPLETE_SOURCE_REVIEW_PENDING"} for row in docs[:142]}
    pilot = {docs[position - 1]["document_id"] for position in (155, 168, 171, 176, 177, 188, 193, 199, 208, 210)}
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
    return docs, original, pilot


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


def _case_selection_excludes_original_pilot_quarantine_and_prior_dispatch() -> None:
    docs = _synthetic_documents()
    original = {row["document_id"]: {"status": "any-terminal"} for row in docs[:142]}
    pilot = {docs[position - 1]["document_id"] for position in (155, 168, 171, 176, 177, 188, 193, 199, 208, 210)}
    prior = {docs[143]["document_id"]}

    selected, remaining = dispatcher.select_next_document(docs, original, pilot, prior)

    assert selected == docs[144]
    assert remaining == 2209 - 142 - 10 - 1 - 1


def _case_document_plan_journal_rejects_cross_plan_duplicate() -> None:
    events = [
        {"event": "binding"},
        {"event": "plan_created", "document_id": "a" * 64},
        {"event": "plan_created", "document_id": "a" * 64},
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

    def test_singleton_plan(self) -> None:
        _case_singleton_plan_matches_integrated_runner_contract(self.tmp_path, self.monkeypatch)

    def test_selection_exclusions(self) -> None:
        _case_selection_excludes_original_pilot_quarantine_and_prior_dispatch()

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
