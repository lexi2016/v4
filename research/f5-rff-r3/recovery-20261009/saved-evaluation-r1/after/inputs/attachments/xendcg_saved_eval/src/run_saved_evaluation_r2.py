#!/usr/bin/env python3
"""Native R2 launcher using the existing official zero-fit guard and adapter.

Importing this module is inert. Execution requires a controller release bound to
the reviewed source, current registry prefix, and fresh input binding.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


RECOVERY_ROOT = Path(__file__).resolve().parents[1]
BATCH_ROOT = RECOVERY_ROOT.parents[1]
PROJECT_ROOT = RECOVERY_ROOT.parents[5]
HANDOFF_ROOT = PROJECT_ROOT / "handoffs/F5_XENDCG_SAVED_EVAL_FIX_R2_LOCAL_20260924"
SRC = RECOVERY_ROOT / "src"
SUPPORT_SRC = BATCH_ROOT / "recovery_01/src"
RUN_SPEC_PATH = RECOVERY_ROOT / "contracts/RUN_SPEC_R2.json"
INPUT_BINDING_PATH = RECOVERY_ROOT / "contracts/INPUT_BINDING_R2.json"
PARENT_RELEASE_PATH = RECOVERY_ROOT / "contracts/PARENT_RELEASE_R2.json"
START_RECEIPT_NAME = "EVALUATION_START_RECEIPT.json"
RUN_RECEIPT_NAME = "EVALUATION_RUN_RECEIPT.json"
TERMINAL_RECEIPT_NAME = "EVALUATION_TERMINAL_RECEIPT.json"

for directory in (SRC, BATCH_ROOT / "src", SUPPORT_SRC):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import evaluation_worker  # noqa: E402
import saved_evaluation_entry  # noqa: E402
import saved_evaluation_registration as registration  # noqa: E402
from recovery_spawn_support import import_resource_tree  # noqa: E402


class SavedEvaluationR2LauncherError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SavedEvaluationR2LauncherError(f"JSON_OBJECT_REQUIRED:{Path(path).name}")
    return value


def _exclusive_json(path: Path, value: Mapping[str, Any]) -> str:
    return evaluation_worker.write_json_exclusive(Path(path), value)


def _atomic_json_exclusive(path: Path, value: Mapping[str, Any]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = registration.canonical_bytes(dict(value)) + b"\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return registration.sha256_bytes(raw)


def _evidence_ref(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"path": str(path.resolve(strict=False)), "sha256": None, "status": "MISSING"}
    return {"path": str(path.resolve()), "sha256": registration.sha256_file(path), "status": "PRESENT"}


def _write_owner_failure_evidence(
    binding: Mapping[str, Any], *, stage: str, error: BaseException, traceback_text: str,
    worker_invoked: bool,
) -> dict[str, Any]:
    output = Path(binding["output_root"])
    path = output / "EVALUATION_FAILURE_EVIDENCE.json"
    if not path.exists():
        source_files: dict[str, Any] = {}
        for category in ("code_files", "executable_helpers"):
            for name, item in binding.get(category, {}).items():
                if name in {"saved_evaluation_entry", "run_saved_evaluation_r2", "resource_tree",
                            "episode_eq_saved_evaluation_worker", "episode_eq_saved_evaluation"}:
                    source_files[name] = {"path": item.get("path"), "sha256": item.get("sha256")}
        _atomic_json_exclusive(path, {
            "schema": "F5_SAVED_EVALUATION_FAILURE_EVIDENCE_V1",
            "status": "FAILED",
            "stage": stage,
            "exception_type": type(error).__name__,
            "exception_message": str(error),
            "traceback": traceback_text,
            "exit_code": None,
            "exit_code_state": "NOT_AVAILABLE_AT_OWNER_EXCEPTION",
            "worker_invoked": worker_invoked,
            "source_files": source_files,
            "truth_read_start": _evidence_ref(output / "EVALUATION_TRUTH_READ_START.json"),
        })
    return _evidence_ref(path)


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SavedEvaluationR2LauncherError(f"BOUND_MODULE_LOAD_FAILED:{name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verify_manifest(binding: Mapping[str, Any]) -> None:
    code_payload = registration.canonical_bytes(dict(binding["code_files"]))
    if registration.sha256_bytes(code_payload) != binding["code_sha256"]:
        raise SavedEvaluationR2LauncherError("CODE_MANIFEST_SHA_MISMATCH")
    for category in ("code_files", "executable_helpers", "official_helpers"):
        for name, item in binding[category].items():
            path = Path(item["path"])
            if not path.is_file() or registration.sha256_file(path) != item["sha256"]:
                raise SavedEvaluationR2LauncherError(f"BOUND_SOURCE_SHA_MISMATCH:{category}:{name}")


def _load_contracts() -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    spec_bytes = RUN_SPEC_PATH.read_bytes()
    binding_bytes = INPUT_BINDING_PATH.read_bytes()
    spec = json.loads(spec_bytes)
    binding = json.loads(binding_bytes)
    if not isinstance(spec, dict) or not isinstance(binding, dict):
        raise SavedEvaluationR2LauncherError("RUN_SPEC_OR_BINDING_NOT_OBJECT")
    run_sha = registration.sha256_bytes(spec_bytes)
    binding_sha = registration.sha256_bytes(binding_bytes)
    if (spec.get("schema") != "F5_SAVED_EVALUATION_RUN_SPEC_R2_V1"
            or binding.get("schema") != "F5_SAVED_EVALUATION_INPUT_BINDING_R2_V1"):
        raise SavedEvaluationR2LauncherError("R2_CONTRACT_SCHEMA_MISMATCH")
    if (binding.get("run_spec_path") != str(RUN_SPEC_PATH.resolve())
            or binding.get("input_binding_path") != str(INPUT_BINDING_PATH.resolve())
            or binding.get("run_spec_sha256") != run_sha):
        raise SavedEvaluationR2LauncherError("R2_CONTRACT_PATH_OR_SHA_MISMATCH")
    if (spec.get("route_id") != binding.get("route_id")
            or spec.get("execution_id") != binding.get("execution_id")
            or spec.get("execution_id") != "F5_FULL64_XENDCG_R1_20260924_SAVED_EVAL_R2_01"):
        raise SavedEvaluationR2LauncherError("R2_EXECUTION_IDENTITY_MISMATCH")
    if binding.get("route_id") != "F5_FULL64_XENDCG_R1_20260924":
        raise SavedEvaluationR2LauncherError("R2_ROUTE_ID_MISMATCH")
    for key in ("fit_calls_authorized", "predict_calls_authorized",
                "control_fit_calls_authorized", "control_predict_calls_authorized",
                "calibrator_fit_calls_authorized"):
        if type(spec.get(key)) is not int or spec[key] != 0:
            raise SavedEvaluationR2LauncherError(f"NONZERO_AUTHORIZED_CALL_COUNT:{key}")
    if spec.get("candidate_model_load_authorized") is not False:
        raise SavedEvaluationR2LauncherError("CANDIDATE_MODEL_LOAD_MUST_REMAIN_FORBIDDEN")
    if binding.get("synthetic_only") is not False:
        raise SavedEvaluationR2LauncherError("REAL_SAVED_EVALUATION_BINDING_REQUIRED")
    if binding.get("execution_id") != spec["execution_id"]:
        raise SavedEvaluationR2LauncherError("R2_EXECUTION_ID_BINDING_MISMATCH")
    for field in saved_evaluation_entry.BOUND_FIELDS:
        if field not in binding:
            raise SavedEvaluationR2LauncherError(f"R2_BOUND_FIELD_MISSING:{field}")
    if binding.get("parent_release_path") != str(PARENT_RELEASE_PATH.resolve()):
        raise SavedEvaluationR2LauncherError("R2_PARENT_RELEASE_PATH_MISMATCH")
    _verify_manifest(binding)
    return spec, binding, spec_bytes, binding_bytes


def _verify_parent_release(spec: Mapping[str, Any], binding: Mapping[str, Any],
                           spec_bytes: bytes, binding_bytes: bytes) -> dict[str, Any]:
    if not PARENT_RELEASE_PATH.is_file():
        raise SavedEvaluationR2LauncherError("PARENT_RELEASE_REQUIRED_NO_EVALUATION_STARTED")
    release = _json(PARENT_RELEASE_PATH)
    transcript_path = Path(str(release.get("reviewer_transcript_path", ""))).resolve()
    if not transcript_path.is_relative_to(HANDOFF_ROOT.resolve()):
        raise SavedEvaluationR2LauncherError("REVIEW_TRANSCRIPT_OUTSIDE_HANDOFF_ROOT")
    if not transcript_path.is_file():
        raise SavedEvaluationR2LauncherError("INDEPENDENT_REVIEW_TRANSCRIPT_MISSING")
    transcript = _json(transcript_path)
    transcript_sha = registration.sha256_file(transcript_path)
    reviewer = transcript.get("reviewer_agent")
    if (not reviewer or reviewer == "/root/saved_eval_writer"
            or transcript.get("reviewer_verdict") != "PASS"
            or transcript.get("REVIEWED") != "PASS"
            or transcript.get("BEHAVIOR_VERIFIED") != "PASS"):
        raise SavedEvaluationR2LauncherError("INDEPENDENT_REVIEW_NOT_PASS")
    expected = {
        "schema": "F5_SAVED_EVALUATION_PARENT_RELEASE_R2_V1",
        "active": True,
        "execution_id": binding["execution_id"],
        "route_id": binding["route_id"],
        "run_spec_sha256": registration.sha256_bytes(spec_bytes),
        "input_binding_sha256": registration.sha256_bytes(binding_bytes),
        "source_code_sha256": binding["code_sha256"],
        "official_registry_path": binding["official_registry_path"],
        "official_registry_sha256_before_start": binding["official_registry_sha256_before_start"],
        "expected_route_event_sha256_before_start": binding["expected_route_event_sha256_before_start"],
        "reviewer_agent": reviewer,
        "reviewer_verdict": "PASS",
        "reviewer_transcript_path": str(transcript_path),
        "reviewer_transcript_sha256": transcript_sha,
        "fit_calls_authorized": 0,
        "predict_calls_authorized": 0,
        "control_fit_calls_authorized": 0,
        "control_predict_calls_authorized": 0,
        "calibrator_fit_calls_authorized": 0,
        "candidate_model_load_authorized": False,
        "saved_prediction_evaluation_authorized": True,
        "resource_caps": binding["resources"],
        "artifact_sha256": {
            "input_files": {name: item["sha256"] for name, item in binding["input_files"].items()},
            "identity_only_files": {name: item["sha256"] for name, item in binding["identity_only_files"].items()},
        },
    }
    for key, value in expected.items():
        if release.get(key) != value:
            raise SavedEvaluationR2LauncherError(f"PARENT_RELEASE_SCOPE_MISMATCH:{key}")
    if not release.get("parent_authorization_id"):
        raise SavedEvaluationR2LauncherError("PARENT_AUTHORIZATION_ID_MISSING")
    return release


def _adapter_and_guard(binding: Mapping[str, Any], spec_bytes: bytes, binding_bytes: bytes):
    helper_specs = binding["official_helpers"]
    guard_path = Path(helper_specs["execution_guard"]["path"])
    adapter_path = Path(helper_specs["registry_adapter"]["path"])
    if str(guard_path.parent) not in sys.path:
        sys.path.insert(0, str(guard_path.parent))
    adapter_module = _load_module(adapter_path, "f5_xendcg_saved_eval_r2_registry_adapter")
    guard_module = _load_module(guard_path, "f5_xendcg_saved_eval_r2_execution_guard")
    run_sha = registration.sha256_bytes(spec_bytes)
    binding_sha = registration.sha256_bytes(binding_bytes)
    adapter_class = registration.build_official_adapter_class(
        adapter_module, binding=binding, run_spec_path=RUN_SPEC_PATH,
        input_binding_path=INPUT_BINDING_PATH, run_spec_sha256=run_sha,
        input_binding_sha256=binding_sha,
    )
    artifact_paths = [Path(item["path"]) for category in
                      ("code_files", "executable_helpers", "official_helpers")
                      for item in binding[category].values()]
    adapter = adapter_class(
        registry_path=Path(binding["official_registry_path"]),
        contract_path=RUN_SPEC_PATH,
        input_binding_path=INPUT_BINDING_PATH,
        artifact_paths=artifact_paths,
        builder_path=Path(helper_specs["builder"]["path"]),
        validator_path=Path(helper_specs["validator"]["path"]),
        event_profile=registration.event_profile(binding),
    )
    adapter.artifact_paths = tuple(dict.fromkeys((
        *adapter.artifact_paths,
        PARENT_RELEASE_PATH,
    )))
    guard = guard_module.ExecutionGuard(
        adapter, experiment_id=str(binding["route_id"]), max_real_fit_debits=1
    )
    return adapter, guard


def _validate_new_paths(binding: Mapping[str, Any]) -> tuple[Path, Path]:
    output = Path(binding["output_root"])
    trace = Path(binding["resource_trace_path"])
    try:
        saved_evaluation_entry._assert_scoped_paths(output, trace, str(binding["execution_id"]))
    except Exception as exc:
        raise SavedEvaluationR2LauncherError(str(exc)) from exc
    if output.exists() or output.is_symlink():
        raise SavedEvaluationR2LauncherError("R2_OUTPUT_EXISTS_NO_REENTRY")
    if trace.exists() or trace.is_symlink():
        raise SavedEvaluationR2LauncherError("R2_RESOURCE_TRACE_EXISTS_NO_REENTRY")
    return output, trace


def _registry_start_readback(adapter: Any, binding: Mapping[str, Any], claim: Any) -> tuple[dict[str, Any], str]:
    with adapter._locked():
        raw, events = adapter._read_validated()
    start_rows = [row for row in events if row.get("execution_id") == claim.execution_id and row.get("event_type") == "RUN_STARTED"]
    current_route = [row for row in events if row.get("route_id") == binding["route_id"] or row.get("experiment_id") == binding["route_id"]]
    if len(start_rows) != 1:
        raise SavedEvaluationR2LauncherError("R2_DURABLE_START_NOT_UNIQUE")
    start = start_rows[0]
    if [row.get("event_sha256") for row in current_route] != list(binding["expected_route_event_sha256_before_start"]) + [start["event_sha256"]]:
        raise SavedEvaluationR2LauncherError("R2_ROUTE_PREFIX_AFTER_START_MISMATCH")
    return start, registration.sha256_bytes(raw)


def _preworker_terminal_event(claim: Any, *, error: BaseException,
                              run_spec_sha256: str, input_binding_sha256: str,
                              binding: Mapping[str, Any],
                              truth_fields: Mapping[str, Any],
                              observed: Mapping[str, Any],
                              claim_append_recovery: Mapping[str, Any] | None = None) -> dict[str, Any]:
    observed_accounting = dict(observed)
    if claim_append_recovery is not None:
        observed_accounting["claim_append_recovery"] = dict(claim_append_recovery)
    return {
        "event_type": "TERMINAL",
        "experiment_id": claim.experiment_id,
        "execution_id": claim.execution_id,
        "arm": claim.arm,
        "contract_sha256": run_spec_sha256,
        "input_binding_sha256": input_binding_sha256,
        "execution_kind": registration.NO_FIT_KIND,
        "planned_real_fit_count": 0,
        "real_fit_budget_debit": 0,
        "fit_call_entered": observed.get("fit_call_entered"),
        "real_fit_returned_count": observed.get("real_fit_returned_count"),
        "terminal_status": "CANNOT_CONFIRM",
        "truth_access": truth_fields["truth_access"],
        "sealed_status": truth_fields["sealed_status"],
        "truth_positive_denominator": truth_fields["truth_positive_denominator"],
        "selection_slots": truth_fields["selection_slots"],
        "truth_denominator_null_reason": observed.get("null_reason", "WORKER_STATUS_UNAVAILABLE"),
        "selection_slots_null_reason": observed.get("null_reason", "WORKER_STATUS_UNAVAILABLE"),
        "evaluation_metrics": truth_fields["evaluation_metrics"],
        "observed_worker_accounting": observed_accounting,
        "error_type": type(error).__name__,
        "stop_reason": str(error),
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }


def _terminalize_preworker_failure(adapter: Any, claim: Any, binding: Mapping[str, Any],
                                   *, error: BaseException, run_spec_sha256: str,
                                   input_binding_sha256: str, start_receipt: Path,
                                   worker_invoked: bool,
                                   failure_stage: str = "OWNER_PREWORKER",
                                   traceback_text: str | None = None,
                                   claim_append_recovery: Mapping[str, Any] | None = None) -> None:
    output = Path(binding["output_root"])
    output.mkdir(parents=True, exist_ok=True)
    failure_ref = _write_owner_failure_evidence(
        binding, stage=failure_stage, error=error,
        traceback_text=traceback_text or "TRACEBACK_NOT_AVAILABLE",
        worker_invoked=worker_invoked,
    )
    run_path = output / RUN_RECEIPT_NAME
    status_path = output / "EVALUATION_WORKER_STATUS.json"
    worker_status: dict[str, Any] = {}
    if worker_invoked and status_path.is_file():
        try:
            worker_status = _json(status_path)
        except Exception:
            worker_status = {}
    status_valid = (worker_invoked and worker_status.get("execution_id") == claim.execution_id
                    and type(worker_status.get("evaluation_label_values_decoded")) is bool)
    if not worker_invoked:
        observed = {
            "status": "KNOWN_NOT_LAUNCHED", "fit_calls": 0,
            "real_fit_returned_count": 0, "predict_calls": 0,
            "control_fit_calls": 0, "control_predict_calls": 0,
            "calibrator_fit_calls": 0, "fit_call_entered": False,
            "candidate_model_loaded": False, "reason": "WORKER_NOT_LAUNCHED",
        }
    elif status_valid and saved_evaluation_entry._zero_status(worker_status, claim.execution_id):
        observed = {
            "status": "KNOWN", "fit_calls": worker_status.get("fit_calls"),
            "real_fit_returned_count": worker_status.get("real_fit_returned_count"),
            "predict_calls": worker_status.get("predict_calls"),
            "control_fit_calls": worker_status.get("control_fit_calls"),
            "control_predict_calls": worker_status.get("control_predict_calls"),
            "calibrator_fit_calls": worker_status.get("calibrator_fit_calls"),
            "fit_call_entered": worker_status.get("fit_call_entered"),
            "candidate_model_loaded": worker_status.get("candidate_model_loaded"),
            "reason": None,
        }
    else:
        observed = {
            "status": "UNKNOWN", "fit_calls": None,
            "real_fit_returned_count": None, "predict_calls": None,
            "control_fit_calls": None, "control_predict_calls": None,
            "calibrator_fit_calls": None, "fit_call_entered": None,
            "candidate_model_loaded": None,
            "reason": "WORKER_STATUS_MISSING_OR_INVALID",
        }
    truth_fields = saved_evaluation_entry._evaluation_terminal_fields(
        worker_status=worker_status,
        metrics=None,
        metrics_validated=False,
        evaluation_contract=binding["evaluation_contract"],
        worker_status_valid=status_valid,
    )
    if truth_fields["truth_positive_denominator"] is None:
        observed["null_reason"] = ("TRUTH_NOT_READ_BEFORE_WORKER_LAUNCH" if not worker_invoked
                                   else "METRICS_NOT_VALIDATED_AFTER_WORKER_FAILURE")
    if not run_path.exists():
        _exclusive_json(run_path, {
            "schema": "F5_SAVED_EVALUATION_RUN_RECEIPT_R2",
            "execution_id": claim.execution_id,
            "candidate_execution_id": binding["candidate_execution_id"],
            "terminal_status": "CANNOT_CONFIRM",
            "fit_calls": observed["fit_calls"],
            "real_fit_returned_count": observed["real_fit_returned_count"],
            "predict_calls": observed["predict_calls"],
            "control_fit_calls": observed["control_fit_calls"],
            "control_predict_calls": observed["control_predict_calls"],
            "calibrator_fit_calls": observed["calibrator_fit_calls"],
            "fit_call_entered": observed["fit_call_entered"],
            "candidate_model_loaded": observed["candidate_model_loaded"],
            "fit_accounting_status": observed["status"],
            "truth_access": truth_fields["truth_access"],
            "sealed_status": truth_fields["sealed_status"],
            "truth_positive_denominator": truth_fields["truth_positive_denominator"],
            "selection_slots": truth_fields["selection_slots"],
            "observed_worker_accounting": observed,
            "claim_append_recovery": dict(claim_append_recovery) if claim_append_recovery is not None else None,
            "evaluation_metrics": truth_fields["evaluation_metrics"],
            "error": {
                "type": type(error).__name__, "message": str(error),
                "traceback": traceback_text or "TRACEBACK_NOT_AVAILABLE",
            },
            "failure_evidence": failure_ref,
            "evidence_refs": {
                "worker_status": _evidence_ref(status_path),
                "evaluation_result": _evidence_ref(output / "EVALUATION_RESULT_RECEIPT.json"),
                "metrics": _evidence_ref(output / "METRICS.json"),
                "truth_read_start": _evidence_ref(output / "EVALUATION_TRUTH_READ_START.json"),
                "resource_trace": _evidence_ref(Path(binding["resource_trace_path"])),
                "failure_evidence": failure_ref,
            },
            "automatic_retry": False,
            "safety": {"research_only": True, "production_allowed": False,
                       "buy_gate_updated": False, "orders_sent": False},
        })
    artifact_paths = list(adapter.artifact_paths)
    for artifact in (start_receipt, run_path, status_path,
                     output / "EVALUATION_RESULT_RECEIPT.json",
                     output / "METRICS.json", output / "EVALUATION_FAILURE_EVIDENCE.json",
                     output / "EVALUATION_WORKER_ERROR.json", binding["resource_trace_path"]):
        candidate = Path(artifact)
        if candidate.is_file():
            artifact_paths.append(candidate)
    adapter.artifact_paths = tuple(dict.fromkeys(artifact_paths))
    event = _preworker_terminal_event(
        claim, error=error, run_spec_sha256=run_spec_sha256,
        input_binding_sha256=input_binding_sha256, binding=binding,
        truth_fields=truth_fields, observed=observed,
        claim_append_recovery=claim_append_recovery,
    )
    adapter.terminalize(claim, event)
    with adapter._locked():
        raw, events = adapter._read_validated()
    terminals = [row for row in events if row.get("execution_id") == claim.execution_id and row.get("event_type") == "TERMINAL"]
    if len(terminals) != 1:
        raise SavedEvaluationR2LauncherError("R2_PREWORKER_TERMINAL_NOT_DURABLE")
    terminal_path = output / TERMINAL_RECEIPT_NAME
    _exclusive_json(terminal_path, {
        "schema": "F5_SAVED_EVALUATION_TERMINAL_RECEIPT_R2",
        "execution_id": claim.execution_id,
        "terminal_status": "CANNOT_CONFIRM",
        "truth_access": truth_fields["truth_access"],
        "sealed_status": truth_fields["sealed_status"],
        "terminal_event_sha256": terminals[0]["event_sha256"],
        "official_registry_sha256_after_terminal": registration.sha256_bytes(raw),
        "start_receipt_sha256": registration.sha256_file(start_receipt) if start_receipt.is_file() else None,
        "run_receipt_sha256": registration.sha256_file(run_path),
        "failure_evidence": failure_ref,
        "terminal_chain": {
            "run_receipt_path": str(run_path.resolve()),
            "run_receipt_sha256": registration.sha256_file(run_path),
            "failure_evidence": failure_ref,
        },
        "claim_append_recovery": dict(claim_append_recovery) if claim_append_recovery is not None else None,
        "error": {
            "type": type(error).__name__, "message": str(error),
            "traceback": traceback_text or "TRACEBACK_NOT_AVAILABLE",
        },
    })


def _terminal_exists(adapter: Any, execution_id: str) -> bool:
    with adapter._locked():
        _raw, events = adapter._read_validated()
    return any(row.get("execution_id") == execution_id and row.get("event_type") == "TERMINAL" for row in events)


def _inspect_claim_after_append_error(
    adapter: Any, guard_module: Any, binding: Mapping[str, Any], *,
    arm: str, run_spec_sha256: str, input_binding_sha256: str,
) -> tuple[Any | None, dict[str, Any]]:
    """Recover only an exact, validated durable start after a claim call throws.

    This performs one locked readback. It never retries the start append. Any
    missing, duplicate, terminalized, drifted, or unvalidated chain is kept as
    CANNOT_CONFIRM evidence and is left untouched.
    """
    expected_execution_id = str(binding["execution_id"])
    expected_route_id = str(binding["route_id"])
    try:
        with adapter._locked():
            raw, events = adapter._read_validated()
    except BaseException as exc:
        return None, {
            "state": "REGISTRY_READBACK_CANNOT_CONFIRM",
            "readback_error_type": type(exc).__name__,
            "readback_error": str(exc),
            "registry_sha256": None,
            "execution_event_count": None,
            "start_count": None,
            "terminal_count": None,
        }

    execution_rows = [row for row in events if str(row.get("execution_id")) == expected_execution_id]
    starts = [row for row in execution_rows if row.get("event_type") == "RUN_STARTED"]
    terminals = [row for row in execution_rows if row.get("event_type") == "TERMINAL"]
    route_rows = [row for row in events
                  if row.get("route_id") == expected_route_id
                  or row.get("experiment_id") == expected_route_id]
    route_sha = [row.get("event_sha256") for row in route_rows]
    expected_route_sha = list(binding["expected_route_event_sha256_before_start"])
    registry_sha = registration.sha256_bytes(raw)
    detail: dict[str, Any] = {
        "state": "DURABLE_START_NOT_EXACT_OR_LIFECYCLE_AMBIGUOUS",
        "registry_sha256": registry_sha,
        "execution_event_count": len(execution_rows),
        "start_count": len(starts),
        "terminal_count": len(terminals),
        "route_prefix_matches_expected_plus_one_start": False,
        "start_event_sha256": None,
        "start_previous_event_sha256": None,
    }
    if len(execution_rows) != 1 or len(starts) != 1 or terminals:
        detail["reason"] = "EXECUTION_EVENT_SET_NOT_ONE_OPEN_START"
        return None, detail

    start = starts[0]
    identity = start.get("input_identity")
    if not isinstance(identity, Mapping):
        detail["reason"] = "START_INPUT_IDENTITY_MISSING"
        return None, detail
    metrics = start.get("deterministic_metrics")
    if not isinstance(metrics, Mapping):
        detail["reason"] = "START_DETERMINISTIC_METRICS_MISSING"
        return None, detail
    exact_fields = (
        start.get("experiment_id") == expected_route_id,
        start.get("route_id") == expected_route_id,
        start.get("execution_id") == expected_execution_id,
        start.get("arm") == arm,
        start.get("registry_event_id") == f"{expected_execution_id}_RUN_STARTED",
        start.get("event_type") == "RUN_STARTED",
        start.get("config_sha256") == run_spec_sha256,
        start.get("input_binding_sha256") == input_binding_sha256,
        identity.get("experiment_id") == expected_route_id,
        identity.get("arm") == arm,
        identity.get("contract_sha256") == run_spec_sha256,
        identity.get("input_binding_sha256") == input_binding_sha256,
        metrics.get("execution_kind") == registration.NO_FIT_KIND,
        type(metrics.get("planned_real_fit_count")) is int
            and metrics.get("planned_real_fit_count") == 0,
        type(metrics.get("real_fit_budget_debit")) is int
            and metrics.get("real_fit_budget_debit") == 0,
        start.get("decision") == "RUNNING",
        start.get("previous_event_sha256") == binding["expected_previous_event_sha256"],
        route_sha == expected_route_sha + [start.get("event_sha256")],
    )
    detail["route_prefix_matches_expected_plus_one_start"] = (
        route_sha == expected_route_sha + [start.get("event_sha256")]
    )
    detail["start_event_sha256"] = start.get("event_sha256")
    detail["start_previous_event_sha256"] = start.get("previous_event_sha256")
    if not all(exact_fields):
        detail["reason"] = "DURABLE_START_IDENTITY_DEBIT_OR_PREFIX_MISMATCH"
        return None, detail

    detail["state"] = "EXACT_DURABLE_OPEN_START_RECONSTRUCTED"
    detail["reason"] = "OFFICIAL_START_APPEND_RAISED_AFTER_DURABLE_READBACK"
    claim = guard_module.ExecutionClaim(
        experiment_id=expected_route_id,
        execution_id=expected_execution_id,
        arm=arm,
        contract_sha256=run_spec_sha256,
        input_binding_sha256=input_binding_sha256,
        execution_kind=registration.NO_FIT_KIND,
        real_fit_budget_debit=0,
    )
    return claim, detail


def _write_claim_append_recovery_evidence(binding: Mapping[str, Any], *,
                                         original_error: BaseException,
                                         inspection: Mapping[str, Any],
                                         terminalization_error: BaseException | None = None) -> Path:
    evidence_root = RECOVERY_ROOT / "evidence"
    if evidence_root.is_symlink() or not evidence_root.is_dir():
        raise SavedEvaluationR2LauncherError("R2_EVIDENCE_ROOT_NOT_SAFE_FOR_CLAIM_RECOVERY")
    path = evidence_root / f"{binding['execution_id']}_CLAIM_APPEND_RECOVERY_CANNOT_CONFIRM.json"
    payload = {
        "schema": "F5_SAVED_EVALUATION_CLAIM_APPEND_RECOVERY_R2",
        "execution_id": binding["execution_id"],
        "route_id": binding["route_id"],
        "status": "CANNOT_CONFIRM",
        "original_claim_error": {
            "type": type(original_error).__name__,
            "message": str(original_error),
        },
        "readback": dict(inspection),
        "terminalization_error": ({
            "type": type(terminalization_error).__name__,
            "message": str(terminalization_error),
        } if terminalization_error is not None else None),
        "worker_launched": False,
        "truth_data_rows_read": 0,
        "fit_calls": 0,
        "predict_calls": 0,
        "candidate_model_loaded": False,
        "automatic_retry": False,
        "safety": {"research_only": True, "production_allowed": False,
                   "buy_gate_updated": False, "orders_sent": False},
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _exclusive_json(path, payload)
    return path


def _claim_no_fit_or_recover_after_append_error(
    *, guard: Any, guard_module: Any, adapter: Any, binding: Mapping[str, Any],
    arm: str, run_spec_sha256: str, input_binding_sha256: str,
    start_receipt_path: Path,
) -> Any:
    try:
        return guard.claim_no_fit(
            execution_id=str(binding["execution_id"]),
            arm=arm,
            contract_sha256=run_spec_sha256,
            input_binding_sha256=input_binding_sha256,
        )
    except BaseException as original_error:
        try:
            recovered_claim, inspection = _inspect_claim_after_append_error(
                adapter, guard_module, binding, arm=arm,
                run_spec_sha256=run_spec_sha256,
                input_binding_sha256=input_binding_sha256,
            )
        except BaseException as inspect_error:
            recovered_claim = None
            inspection = {
                "state": "REGISTRY_READBACK_CANNOT_CONFIRM",
                "inspection_error_type": type(inspect_error).__name__,
                "inspection_error": str(inspect_error),
            }
        if recovered_claim is not None:
            try:
                _terminalize_preworker_failure(
                    adapter, recovered_claim, binding, error=original_error,
                    run_spec_sha256=run_spec_sha256,
                    input_binding_sha256=input_binding_sha256,
                    start_receipt=start_receipt_path,
                    worker_invoked=False,
                    failure_stage="CLAIM_APPEND_RECOVERY",
                    traceback_text=traceback.format_exc(),
                    claim_append_recovery=inspection,
                )
            except BaseException as terminalization_error:
                try:
                    _post_claim, post_inspection = _inspect_claim_after_append_error(
                        adapter, guard_module, binding, arm=arm,
                        run_spec_sha256=run_spec_sha256,
                        input_binding_sha256=input_binding_sha256,
                    )
                except BaseException as inspect_error:
                    post_inspection = {
                        "state": "POST_TERMINALIZATION_READBACK_CANNOT_CONFIRM",
                        "inspection_error_type": type(inspect_error).__name__,
                        "inspection_error": str(inspect_error),
                    }
                try:
                    _write_claim_append_recovery_evidence(
                        binding, original_error=original_error,
                        inspection={
                            "before_terminalization": inspection,
                            "after_terminalization_exception": post_inspection,
                        },
                        terminalization_error=terminalization_error,
                    )
                except BaseException as evidence_error:
                    raise original_error from evidence_error
                raise original_error from terminalization_error
            raise

        try:
            _write_claim_append_recovery_evidence(
                binding, original_error=original_error, inspection=inspection,
            )
        except BaseException as evidence_error:
            raise original_error from evidence_error
        raise


def run() -> dict[str, Any]:
    spec, binding, spec_bytes, binding_bytes = _load_contracts()
    release = _verify_parent_release(spec, binding, spec_bytes, binding_bytes)
    output, trace = _validate_new_paths(binding)
    adapter, guard = _adapter_and_guard(binding, spec_bytes, binding_bytes)
    reviewer_transcript = Path(release["reviewer_transcript_path"]).resolve()
    adapter.artifact_paths = tuple(dict.fromkeys((
        *adapter.artifact_paths, reviewer_transcript,
    )))
    run_spec_sha = registration.sha256_bytes(spec_bytes)
    binding_sha = registration.sha256_bytes(binding_bytes)

    # This official claim is the first step that can lead to data/PIT checks.
    guard_module = sys.modules.get(guard.__class__.__module__)
    if guard_module is None or not hasattr(guard_module, "ExecutionClaim"):
        raise SavedEvaluationR2LauncherError("R2_EXECUTION_CLAIM_TYPE_UNAVAILABLE")
    start_path = output / START_RECEIPT_NAME
    claim = _claim_no_fit_or_recover_after_append_error(
        guard=guard, guard_module=guard_module, adapter=adapter, binding=binding,
        arm="SAVED_CANDIDATE_FULL2024_EVALUATION_ONLY",
        run_spec_sha256=run_spec_sha,
        input_binding_sha256=binding_sha,
        start_receipt_path=start_path,
    )
    worker_invoked = False
    failure_stage = "OWNER_OUTPUT_SETUP"
    try:
        output.mkdir(parents=True, exist_ok=False)
        start, registry_after_start_sha = _registry_start_readback(adapter, binding, claim)
        start_sha = _exclusive_json(start_path, {
            "schema": "F5_SAVED_EVALUATION_START_RECEIPT_R2",
            "status": "RUN_STARTED_DURABLE",
            "execution_id": claim.execution_id,
            "candidate_execution_id": binding["candidate_execution_id"],
            "route_id": claim.experiment_id,
            "parent_authorization_id": release["parent_authorization_id"],
            "run_spec_sha256": run_spec_sha,
            "input_binding_sha256": binding_sha,
            "source_code_sha256": binding["code_sha256"],
            "start_event_sha256": start["event_sha256"],
            "previous_event_sha256": start["previous_event_sha256"],
            "official_registry_sha256_before_start": binding["official_registry_sha256_before_start"],
            "official_registry_sha256_after_start": registry_after_start_sha,
            "fit_calls_authorized": 0, "predict_calls_authorized": 0,
            "control_fit_calls_authorized": 0, "control_predict_calls_authorized": 0,
            "calibrator_fit_calls_authorized": 0, "candidate_model_load_authorized": False,
            "real_fit_budget_debit": 0,
            "safety": {"research_only": True, "production_allowed": False,
                       "buy_gate_updated": False, "orders_sent": False},
        })
        # Original native runtime and resource monitor are validated after the
        # official no-fit RUN_STARTED and before any saved evaluation artifact.
        helpers = binding["executable_helpers"]
        failure_stage = "NATIVE_RUNTIME_IMPORT_AND_VALIDATE"
        native_runtime_path = Path(helpers["native_runtime"]["path"])
        native_contract = _json(Path(helpers["native_reference_contract"]["path"]))
        native_runtime = _load_module(native_runtime_path, "f5_xendcg_saved_eval_r2_native_runtime")
        native_spec = native_runtime.native_spec_from_contract(native_contract)
        if Path(sys.executable).resolve() != Path(native_spec["python_executable_path"]).resolve():
            raise SavedEvaluationR2LauncherError("LOCKED_NATIVE_PYTHON_MISMATCH")
        native_runtime.validate_native_files(native_spec, require_macos=True)
        failure_stage = "RESOURCE_TREE_IMPORT"
        resource_ref = helpers["resource_tree"]
        resource_tree = import_resource_tree(Path(resource_ref["path"]), str(resource_ref["sha256"]))

        payload = {key: binding[key] for key in saved_evaluation_entry.BOUND_FIELDS}
        payload.update({
            "run_spec_sha256": run_spec_sha,
            "input_binding_sha256": binding_sha,
            "start_receipt_path": str(start_path.resolve()),
            "start_receipt_sha256": start_sha,
        })
        worker_invoked = True
        failure_stage = "SAVED_EVALUATION_OWNER"
        terminal = saved_evaluation_entry.run_after_durable_claim(
            claim=claim, adapter=adapter, payload=payload,
            run_spec_path=RUN_SPEC_PATH, input_binding_path=INPUT_BINDING_PATH,
            native_spec=native_spec,
            native_runtime_helper_path=native_runtime_path,
            resource_tree=resource_tree, resource_trace_path=trace,
        )
    except saved_evaluation_entry.SavedEntryTerminalizationError:
        # The adapter call may have durably appended despite an I/O error; never
        # retry terminalization automatically.
        raise
    except BaseException as exc:
        if _terminal_exists(adapter, claim.execution_id):
            raise
        _terminalize_preworker_failure(
            adapter, claim, binding, error=exc,
            run_spec_sha256=run_spec_sha,
            input_binding_sha256=binding_sha,
            start_receipt=start_path,
            worker_invoked=worker_invoked,
            failure_stage=failure_stage,
            traceback_text=traceback.format_exc(),
        )
        raise
    return terminal


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
