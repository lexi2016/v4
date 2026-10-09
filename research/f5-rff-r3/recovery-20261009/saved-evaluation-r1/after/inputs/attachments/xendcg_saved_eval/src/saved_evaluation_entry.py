"""Saved-artifact evaluation seam AFTER the existing owner's zero-fit claim.

No registry implementation, guard replacement, model loader, or CLI is added.
The local owner supplies its original locked official adapter and native monitor.
This module verifies the durable claim, runs one evaluation worker, and uses that
same adapter to append/read back the evaluation terminal. Prelaunch exceptions
remain the owner's responsibility; never automatically retry a claimed run.
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import evaluation_worker as worker


class SavedEntryError(RuntimeError):
    pass


class SavedEntryTerminalizationError(SavedEntryError):
    """The owner adapter was called; do not retry terminalization blindly."""


RECOVERY_ROOT = Path(__file__).resolve().parents[1]


COUNTERS = ("fit_calls", "real_fit_returned_count", "predict_calls",
            "control_fit_calls", "control_predict_calls", "calibrator_fit_calls")
BOUND_FIELDS = (
    "execution_id", "candidate_execution_id", "output_root", "resource_trace_path", "code_files", "code_sha256",
    "executable_helpers", "input_files", "identity_only_files", "evaluation_contract",
    "score_aware_metrics_path", "score_aware_metrics_sha256", "synthetic_only",
)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict):
        raise SavedEntryError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _events(adapter: Any) -> list[dict[str, Any]]:
    # Methods already used by the packaged candidate_entry's official adapter.
    with adapter._locked():
        _raw, events = adapter._read_validated()
        return list(events)


def _zero_status(value: Mapping[str, Any], execution_id: str) -> bool:
    return (value.get("execution_id") == execution_id
            and all(type(value.get(k)) is int and value[k] == 0 for k in COUNTERS)
            and value.get("fit_call_entered") is False
            and value.get("candidate_model_loaded") is False)


def _snapshot_unchanged(payload: Mapping[str, Any]) -> None:
    for category in ("code_files", "executable_helpers", "input_files", "identity_only_files"):
        for name, item in payload[category].items():
            path = Path(item["path"])
            if not path.is_file() or worker.sha256_file(path) != item["sha256"]:
                raise SavedEntryError(f"BOUND_SNAPSHOT_CHANGED:{category}:{name}")


def _safe_json(path: Path) -> tuple[dict[str, Any], dict[str, str] | None]:
    try:
        return _json(path), None
    except Exception as exc:
        return {}, {"type": type(exc).__name__, "message": str(exc)}


def _evidence_ref(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        return {"path": str(path.resolve(strict=False)), "sha256": None, "status": "MISSING"}
    return {"path": str(path.resolve()), "sha256": worker.sha256_file(path), "status": "PRESENT"}


def _failure_source_files(payload: Mapping[str, Any], resource_tree: Any) -> dict[str, Any]:
    sources: dict[str, Any] = {}
    for name, path in (("saved_evaluation_entry", Path(__file__)),
                       ("evaluation_worker", Path(worker.__file__)),
                       ("resource_tree", Path(resource_tree.__file__))):
        sources[name] = {"path": str(path.resolve()), "sha256": worker.sha256_file(path)}
    target = worker.run_saved_evaluation
    target_module = sys.modules.get(getattr(target, "__module__", ""))
    target_path = Path(getattr(target_module, "__file__", "")) if target_module is not None else None
    if target_path is not None and str(target_path):
        try:
            resolved = target_path.resolve()
        except Exception:
            resolved = target_path
        for name, item in payload.get("code_files", {}).items():
            try:
                if Path(item.get("path", "")).resolve() == resolved:
                    sources["monitored_target"] = {
                        "name": name, "path": str(resolved), "sha256": item.get("sha256"),
                    }
                    break
            except Exception:
                continue
    return sources


def _target_descriptor(payload: Mapping[str, Any]) -> dict[str, Any]:
    target = worker.run_saved_evaluation
    target_module = sys.modules.get(getattr(target, "__module__", ""))
    target_path = Path(getattr(target_module, "__file__", "")) if target_module is not None else None
    if target_path is None or not str(target_path):
        raise SavedEntryError("MONITORED_TARGET_MODULE_PATH_UNAVAILABLE")
    resolved = target_path.resolve()
    expected_sha = None
    matched_name = None
    for name, item in payload.get("code_files", {}).items():
        try:
            if Path(item.get("path", "")).resolve() == resolved:
                expected_sha = item.get("sha256")
                matched_name = name
                break
        except Exception:
            continue
    if not expected_sha or worker.sha256_file(resolved) != expected_sha:
        raise SavedEntryError("MONITORED_TARGET_NOT_HASH_BOUND")
    return {
        "path": str(resolved),
        "sha256": str(expected_sha),
        "module_name": f"f5_saved_eval_target_{payload['execution_id']}",
        "callable": getattr(target, "__name__", "run_saved_evaluation"),
        "binding_name": matched_name,
    }


def _truth_read_start_evidence(output: Path, execution_id: str) -> dict[str, Any]:
    path = Path(output) / "EVALUATION_TRUTH_READ_START.json"
    if not path.is_file():
        return {"path": str(path.resolve(strict=False)), "sha256": None, "valid": False, "started": False, "parse_error": None}
    value, parse_error = _safe_json(path)
    valid = (parse_error is None and value.get("execution_id") == execution_id
             and value.get("label_values_decode_started") is True
             and value.get("fit_calls") == 0 and value.get("predict_calls") == 0)
    return {
        "path": str(path.resolve()),
        "sha256": worker.sha256_file(path),
        "valid": bool(valid),
        "started": bool(valid),
        "parse_error": parse_error,
    }


def _ensure_failure_evidence(
    *, resource_tree: Any, path: Path, stage: str, exc: BaseException,
    monitor: Mapping[str, Any] | None, source_files: Mapping[str, Any],
    truth_read_start: Mapping[str, Any],
) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        resource_tree.write_failure_evidence_atomic(path, {
            "schema": "F5_SAVED_EVALUATION_FAILURE_EVIDENCE_V1",
            "status": "FAILED",
            "stage": stage,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
            "exit_code": monitor.get("worker_exitcode") if isinstance(monitor, Mapping) else None,
            "exit_code_state": "JOINED" if isinstance(monitor, Mapping) and monitor.get("worker_exitcode") is not None else "CANNOT_CONFIRM",
            "terminal_reason": monitor.get("terminal_reason") if isinstance(monitor, Mapping) else None,
            "source_files": dict(source_files),
            "truth_read_start": dict(truth_read_start),
        })
    return _evidence_ref(path)


def _assert_scoped_paths(output_root: Path, trace_path: Path, execution_id: str) -> tuple[Path, Path]:
    """Require all mutable run files to live in this recovery's private roots."""
    configured_root = Path(RECOVERY_ROOT)
    if configured_root.is_symlink():
        raise SavedEntryError("RECOVERY_OUTPUT_DIRECTORY_MUST_NOT_BE_SYMLINK")
    root = configured_root.resolve()
    execution_dir = root / "execution"
    evidence_dir = root / "evidence"
    if execution_dir.is_symlink() or evidence_dir.is_symlink():
        raise SavedEntryError("RECOVERY_OUTPUT_DIRECTORY_MUST_NOT_BE_SYMLINK")
    if not execution_dir.is_dir() or not evidence_dir.is_dir():
        raise SavedEntryError("RECOVERY_OUTPUT_DIRECTORIES_MUST_EXIST")

    resolved_output = Path(output_root).resolve(strict=False)
    resolved_execution_dir = execution_dir.resolve(strict=True)
    if (resolved_execution_dir.parent != root
            or resolved_output.parent != resolved_execution_dir
            or resolved_output.name != execution_id
            or not resolved_output.is_relative_to(root)):
        raise SavedEntryError("OUTPUT_ROOT_OUTSIDE_RECOVERY_EXECUTION_DIRECTORY")
    if Path(output_root).is_symlink():
        raise SavedEntryError("OUTPUT_ROOT_MUST_NOT_BE_SYMLINK")

    resolved_trace = Path(trace_path).resolve(strict=False)
    resolved_evidence_dir = evidence_dir.resolve(strict=True)
    if (resolved_evidence_dir.parent != root
            or resolved_trace.parent != resolved_evidence_dir
            or not resolved_trace.is_relative_to(root)):
        raise SavedEntryError("RESOURCE_TRACE_OUTSIDE_RECOVERY_EVIDENCE_DIRECTORY")
    if Path(trace_path).exists() or Path(trace_path).is_symlink():
        raise SavedEntryError("RESOURCE_TRACE_MUST_BE_NEW")
    if resolved_trace.is_relative_to(resolved_output):
        raise SavedEntryError("RESOURCE_TRACE_MUST_BE_OUTSIDE_WORKER_OUTPUT")
    return resolved_output, resolved_trace


def _evaluation_terminal_fields(
    *, worker_status: Mapping[str, Any], metrics: Mapping[str, Any] | None,
    metrics_validated: bool, evaluation_contract: Mapping[str, Any], worker_status_valid: bool,
    truth_read_started: bool = False,
) -> dict[str, Any]:
    """Build truthful terminal exposure and metric fields without guessing."""
    decoded = worker_status.get("evaluation_label_values_decoded")
    if worker_status_valid and decoded is True:
        truth_access = "EVAL_LABELS_DECODED_AFTER_SAVED_PREDICTION_SEAL"
        sealed_status = "EXPOSED_2024_POST_SEAL_EVALUATION"
    elif worker_status_valid and decoded is False:
        truth_access = "EVAL_LABELS_NOT_DECODED"
        sealed_status = "SAVED_PREDICTION_SEAL_UNCHANGED_NO_TRUTH_DECODE"
    elif truth_read_started:
        truth_access = "EVAL_LABEL_DECODE_STARTED_COMPLETION_CANNOT_CONFIRM"
        sealed_status = "POST_SEAL_TRUTH_READ_STARTED_EVALUATION_INCOMPLETE"
    else:
        truth_access = "CANNOT_CONFIRM"
        sealed_status = "CANNOT_CONFIRM_POST_SEAL_EXPOSURE"

    summary: dict[str, Any] = {
        "metrics_computed": False,
        "metrics_sha256": None,
        "bound_scope": {
            "grid_rows": evaluation_contract.get("grid_rows"),
            "scoreable_rows": evaluation_contract.get("scoreable_rows"),
            "sessions": evaluation_contract.get("sessions"),
            "selection_slots": evaluation_contract.get("selection_slots"),
            "known_positive_denominator": evaluation_contract.get("known_positive_denominator"),
        },
        "truth_positive_denominator": None,
        "confirmed_new_episode_denominator": None,
        "selection_slots": None,
        "primary_metric": None,
        "paired_precision": None,
    }
    if metrics_validated and isinstance(metrics, Mapping):
        pairs = metrics.get("paired_precision")
        primary = metrics.get("primary_metric")
        arms = metrics.get("arms")
        if not isinstance(pairs, Mapping) or not isinstance(primary, Mapping) or not isinstance(arms, Mapping):
            raise SavedEntryError("VALIDATED_METRICS_MISSING_PAIRED_OR_ARM_SUMMARY")
        summary.update({
            "metrics_computed": True,
            "metrics_sha256": metrics.get("metrics_sha256"),
            "grid_rows": metrics.get("grid_rows"),
            "scoreable_rows": metrics.get("scoreable_rows"),
            "sessions": metrics.get("sessions"),
            "truth_positive_denominator": metrics.get("confirmed_new_episode_denominator"),
            "confirmed_new_episode_denominator": metrics.get("confirmed_new_episode_denominator"),
            "selection_slots": metrics.get("selection_slots"),
            "known_positive_rows_full_g": metrics.get("known_positive_rows_full_g"),
            "episode_denominator_check": metrics.get("episode_denominator_check"),
            "primary_metric": dict(primary),
            "paired_precision": {
                name: {
                    "lower": value.get("lower"),
                    "upper": value.get("upper"),
                    "denominator": value.get("denominator"),
                    "daily_gain_loss": value.get("daily_gain_loss"),
                }
                for name, value in pairs.items() if isinstance(value, Mapping)
            },
            "arms_confirmed_new_events": {
                name: arm.get("confirmed_new_events")
                for name, arm in arms.items() if isinstance(arm, Mapping)
            },
        })
    return {
        "truth_access": truth_access,
        "sealed_status": sealed_status,
        "truth_positive_denominator": summary["truth_positive_denominator"],
        "selection_slots": summary["selection_slots"],
        "evaluation_metrics": summary,
    }


def run_after_durable_claim(
    *, claim: Any, adapter: Any, payload: Mapping[str, Any],
    run_spec_path: Path, input_binding_path: Path, native_spec: Mapping[str, Any],
    native_runtime_helper_path: Path, resource_tree: Any, resource_trace_path: Path,
) -> dict[str, Any]:
    """Consume the original owner's claim; do not create/debit another claim.

    The owner must have independently bound RUN_SPEC, INPUT_BINDING, reviewed
    source SHA, the original native environment, and its current registry prefix.
    ``payload`` uses the existing evaluation worker schema plus identity-only
    files. INPUT_BINDING holds BOUND_FIELDS verbatim and the resource limits.
    """
    spec = _json(run_spec_path)
    binding = _json(input_binding_path)
    if (worker.sha256_file(run_spec_path) != payload["run_spec_sha256"]
            or worker.sha256_file(input_binding_path) != payload["input_binding_sha256"]):
        raise SavedEntryError("RUN_SPEC_OR_BINDING_SNAPSHOT_MISMATCH")
    if any(binding.get(k) != payload.get(k) for k in BOUND_FIELDS):
        raise SavedEntryError("PAYLOAD_BINDING_MISMATCH")
    if any(type(spec.get(k)) is not int or spec[k] != 0 for k in
           ("fit_calls_authorized", "predict_calls_authorized")):
        raise SavedEntryError("EVALUATION_SPEC_NOT_ZERO_FIT_ZERO_PREDICT")
    if payload["execution_id"] == payload["candidate_execution_id"]:
        raise SavedEntryError("OLD_CANDIDATE_EXECUTION_ID_MUST_NOT_BE_REUSED")
    for field, expected in (("execution_id", payload["execution_id"]),
                            ("contract_sha256", payload["run_spec_sha256"]),
                            ("input_binding_sha256", payload["input_binding_sha256"])):
        if getattr(claim, field) != expected:
            raise SavedEntryError(f"CLAIM_IDENTITY_MISMATCH:{field}")
    registered = [e for e in _events(adapter) if e.get("execution_id") == claim.execution_id]
    starts = [e for e in registered if e.get("event_type") == "RUN_STARTED"]
    if len(starts) != 1 or any(e.get("event_type") == "TERMINAL" for e in registered):
        raise SavedEntryError("CLAIM_NOT_ONE_DURABLE_OPEN_START")
    start = starts[0]
    for field in ("experiment_id", "execution_id", "arm", "contract_sha256", "input_binding_sha256"):
        if start.get(field) != getattr(claim, field):
            raise SavedEntryError(f"REGISTRY_START_IDENTITY_MISMATCH:{field}")
    accounting = start.get("deterministic_metrics", {})
    if any(type(accounting.get(k)) is not int or accounting[k] != 0
           for k in ("planned_real_fit_count", "real_fit_budget_debit")):
        raise SavedEntryError("NOT_ZERO_FIT_START")
    output = Path(payload["output_root"])
    start_path = Path(payload["start_receipt_path"])
    if worker.sha256_file(start_path) != payload["start_receipt_sha256"]:
        raise SavedEntryError("START_RECEIPT_SHA_MISMATCH")
    receipt = _json(start_path)
    expected_receipt = {
        "status": "RUN_STARTED_DURABLE", "execution_id": claim.execution_id,
        "candidate_execution_id": payload["candidate_execution_id"],
        "run_spec_sha256": claim.contract_sha256,
        "input_binding_sha256": claim.input_binding_sha256,
        "source_code_sha256": payload["code_sha256"],
        "start_event_sha256": start["event_sha256"],
        "fit_calls_authorized": 0, "predict_calls_authorized": 0, "real_fit_budget_debit": 0,
    }
    if any(receipt.get(k) != v for k, v in expected_receipt.items()):
        raise SavedEntryError("START_RECEIPT_FIELDS_MISMATCH")
    trace_path = Path(resource_trace_path)
    if Path(payload["resource_trace_path"]).resolve(strict=False) != trace_path.resolve(strict=False):
        raise SavedEntryError("RESOURCE_TRACE_BINDING_MISMATCH")
    output, trace_path = _assert_scoped_paths(output, trace_path, claim.execution_id)
    if start_path.parent.resolve() != output or set(output.iterdir()) != {start_path}:
        raise SavedEntryError("OUTPUT_NOT_START_ONLY_NO_REENTRY")
    for name, path in (("evaluation_worker", Path(worker.__file__)),
                       ("saved_evaluation_entry", Path(__file__))):
        item = payload["code_files"].get(name, {})
        if (Path(item.get("path", "")).resolve() != path.resolve()
                or item.get("sha256") != worker.sha256_file(path)):
            raise SavedEntryError(f"ACTIVE_CODE_IDENTITY_MISMATCH:{name}")
    # The old execution directory and every old artifact are strictly read-only.
    old_root = Path(payload["identity_only_files"]["candidate_model"]["path"]).resolve().parent
    if output.is_relative_to(old_root) or trace_path.is_relative_to(old_root):
        raise SavedEntryError("OUTPUT_OVERLAPS_IMMUTABLE_CANDIDATE_EXECUTION")
    resources = binding["resources"]
    if resources.get("workers") != 1:
        raise SavedEntryError("EXACTLY_ONE_EVALUATION_WORKER_REQUIRED")
    wall = min(float(resources["wall_seconds_max"]), 600.0)
    rss = min(int(resources["aggregate_process_tree_rss_bytes_max"]), 3221225472)
    threads = min(int(resources["cpu_threads"]), 4)
    interval = min(float(resources.get("sampling_interval_seconds", 0.05)), 0.05)
    if threads != 4:
        raise SavedEntryError("ORIGINAL_MONITOR_REQUIRES_FOUR_THREADS")
    if wall <= 0 or rss <= 0 or interval <= 0:
        raise SavedEntryError("INVALID_EVALUATION_RESOURCE_LIMIT")

    status, error, monitor = "CANNOT_CONFIRM", None, None
    ws: dict[str, Any] = {}
    result: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    known_zero = False
    snapshot_checked = False
    metrics_validated = False
    stage = "MONITOR_START"
    status_parse_error: dict[str, str] | None = None
    failure_path = output / "EVALUATION_FAILURE_EVIDENCE.json"
    worker_error_path = output / "EVALUATION_WORKER_ERROR.json"
    source_files = _failure_source_files(payload, resource_tree)
    descriptor = _target_descriptor(payload)

    def verify_snapshot_before_trace(monitor_result: Mapping[str, Any]) -> None:
        nonlocal snapshot_checked
        if monitor_result.get("terminal_reason") is None and monitor_result.get("worker_exitcode") == 0:
            _snapshot_unchanged(payload)
            snapshot_checked = True

    try:
        # Hash-only verification stays inside the existing monitored worker.
        monitor = resource_tree.run_spawn_monitored(
            None, payload, native_spec=native_spec,
            native_runtime_helper_path=native_runtime_helper_path,
            wall_seconds_max=wall, rss_bytes_max=rss, threads=threads,
            resource_trace_path=trace_path, sample_seconds=interval,
            on_worker_exit=verify_snapshot_before_trace,
            target_descriptor=descriptor,
            failure_evidence_path=failure_path,
            failure_context={"source_files": source_files},
        )
        stage = "WORKER_STATUS_READ"
        status_path = output / "EVALUATION_WORKER_STATUS.json"
        if status_path.is_file():
            ws, status_parse_error = _safe_json(status_path)
        known_zero = status_parse_error is None and _zero_status(ws, claim.execution_id)
        if monitor.get("terminal_reason") is not None or monitor.get("worker_exitcode") != 0:
            raise SavedEntryError(f"EVALUATION_WORKER_FAILED:{monitor.get('terminal_reason')}:{monitor.get('worker_exitcode')}")
        if status_parse_error is not None or not ws or ws.get("execution_id") != claim.execution_id:
            raise SavedEntryError("EVALUATION_WORKER_STATUS_MISSING_OR_INVALID")
        stage = "RESOURCE_TRACE_VALIDATE"
        if (not trace_path.is_file()
                or monitor.get("post_trace_fsync_terminal_check", {}).get("after_trace_fsync") is not True
                or monitor.get("final_post_fsync_check", {}).get("after_final_trace_fsync") is not True):
            raise SavedEntryError("RESOURCE_TRACE_DURABILITY_NOT_VERIFIED")
        stage = "RESULT_AND_METRICS_READ"
        result = _json(output / "EVALUATION_RESULT_RECEIPT.json")
        metrics = _json(output / "METRICS.json")
        metric_sha = worker.sha256_file(output / "METRICS.json")
        metrics["metrics_sha256"] = metric_sha
        if (not known_zero or not _zero_status(result, claim.execution_id)
                or result.get("metrics_computed") is not True
                or ws.get("metrics_sha256") != metric_sha
                or result.get("metrics_sha256") != metric_sha
                or ws.get("result_sha256") != worker.sha256_file(output / "EVALUATION_RESULT_RECEIPT.json")
                or result.get("candidate_execution_id") != payload["candidate_execution_id"]
                or result.get("run_spec_sha256") != payload["run_spec_sha256"]
                or result.get("input_binding_sha256") != payload["input_binding_sha256"]
                or result.get("source_code_sha256") != payload["code_sha256"]):
            raise SavedEntryError("RESULT_STATUS_OR_SHA_LINK_MISMATCH")
        stage = "METRICS_VALIDATE"
        if (metrics.get("confirmed_new_episode_denominator") != binding["evaluation_contract"]["known_positive_denominator"]
                or metrics.get("episode_denominator_check", {}).get("all_equal") is not True
                or metrics.get("binary_control_evaluator_outputs_deep_equal_to_original") != {
                    "FROZEN_BASE34": True, "FROZEN_UNWEIGHTED_PLUS_PATH": True}
                or metrics.get("synthetic_only") is not payload["synthetic_only"]):
            raise SavedEntryError("METRICS_SCOPE_OR_DENOMINATOR_MISMATCH")
        stage = "SNAPSHOT_VALIDATE"
        if not snapshot_checked:
            raise SavedEntryError("BOUNDED_POSTWORKER_SNAPSHOT_NOT_VERIFIED")
        metrics_validated = True
        status = "COMPLETED"  # evaluation lifecycle, never a model-effect verdict
    except Exception as exc:
        truth_read_start = _truth_read_start_evidence(output, claim.execution_id)
        failure_ref = _ensure_failure_evidence(
            resource_tree=resource_tree, path=failure_path, stage=stage, exc=exc,
            monitor=monitor, source_files=source_files, truth_read_start=truth_read_start,
        )
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "failure_evidence": failure_ref,
        }

    truth_read_start = _truth_read_start_evidence(output, claim.execution_id)
    counters = {k: 0 if known_zero else None for k in COUNTERS}
    accounting_fields = dict(counters, fit_call_entered=False if known_zero else None,
        candidate_model_loaded=False if known_zero else None,
        fit_accounting_status="KNOWN" if known_zero else "UNKNOWN",
        fit_accounting_source="DURABLE_EVALUATION_WORKER_STATUS" if known_zero else "NO_VALID_WORKER_STATUS",
        fit_accounting_reason="EVALUATION_ONLY_WORKER_READBACK" if known_zero else "WORKER_STATUS_MISSING_OR_INVALID")
    run_path = output / "EVALUATION_RUN_RECEIPT.json"
    truth_fields = _evaluation_terminal_fields(
        worker_status=ws,
        metrics=metrics,
        metrics_validated=metrics_validated,
        evaluation_contract=binding["evaluation_contract"],
        worker_status_valid=bool(ws) and ws.get("execution_id") == claim.execution_id,
        truth_read_started=bool(truth_read_start.get("started")),
    )
    worker_status_valid = bool(ws) and ws.get("execution_id") == claim.execution_id
    observed_worker_accounting = {
        "status": "KNOWN" if known_zero else "UNKNOWN",
        **{key: (ws.get(key) if worker_status_valid else None) for key in COUNTERS},
        "fit_call_entered": ws.get("fit_call_entered") if worker_status_valid else None,
        "candidate_model_loaded": ws.get("candidate_model_loaded") if worker_status_valid else None,
        "reason": None if known_zero else "WORKER_STATUS_MISSING_OR_INVALID",
        "status_parse_error": status_parse_error,
    }
    evidence_refs = {
        "worker_status": _evidence_ref(output / "EVALUATION_WORKER_STATUS.json"),
        "worker_error": _evidence_ref(worker_error_path),
        "failure_evidence": _evidence_ref(failure_path),
        "truth_read_start": _evidence_ref(output / "EVALUATION_TRUTH_READ_START.json"),
        "evaluation_result": _evidence_ref(output / "EVALUATION_RESULT_RECEIPT.json"),
        "metrics": _evidence_ref(output / "METRICS.json"),
        "resource_trace": _evidence_ref(trace_path),
    }
    run_doc = dict(schema="F5_SAVED_EVALUATION_RUN_RECEIPT_R2", execution_id=claim.execution_id,
        candidate_execution_id=payload["candidate_execution_id"], terminal_status=status,
        planned_real_fit_count=0, real_fit_budget_debit=0, automatic_retry=False,
        synthetic_only=payload["synthetic_only"], **accounting_fields,
        metrics_sha256=worker.sha256_file(output / "METRICS.json") if (output / "METRICS.json").is_file() else None,
        resource_trace_sha256=worker.sha256_file(trace_path) if trace_path.is_file() else None,
        resource_monitor=monitor, error=error, metrics_validated=status == "COMPLETED",
        truth_access=truth_fields["truth_access"],
        sealed_status=truth_fields["sealed_status"],
        truth_positive_denominator=truth_fields["truth_positive_denominator"],
        selection_slots=truth_fields["selection_slots"],
        evaluation_metrics=truth_fields["evaluation_metrics"],
        observed_worker_accounting=observed_worker_accounting,
        truth_read_start_evidence=truth_read_start,
        evidence_refs=evidence_refs,
        safety=dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False))
    worker.write_json_exclusive(run_path, run_doc)
    event = dict(event_type="TERMINAL", **{k: getattr(claim, k) for k in
        ("experiment_id", "execution_id", "arm", "contract_sha256", "input_binding_sha256")},
        terminal_status=status, planned_real_fit_count=0, real_fit_budget_debit=0,
        **accounting_fields,
        execution_kind="NO_FIT_ENGINEERING_CANARY",
        truth_access=truth_fields["truth_access"],
        sealed_status=truth_fields["sealed_status"],
        truth_positive_denominator=truth_fields["truth_positive_denominator"],
        selection_slots=truth_fields["selection_slots"],
        evaluation_metrics=truth_fields["evaluation_metrics"],
        observed_worker_accounting=observed_worker_accounting,
        error_type=error["type"] if error else None,
        finished_at=datetime.now(timezone.utc).isoformat())
    paths = [*adapter.artifact_paths, *output.iterdir()]
    if trace_path.is_file():
        paths.append(trace_path)
    adapter.artifact_paths = tuple(dict.fromkeys(Path(p) for p in paths if Path(p).is_file()))
    # Use the SAME official locked adapter; no direct JSONL write or second registry.
    # A failure here is propagated; a worker METRICS file alone is not completion.
    try:
        adapter.terminalize(claim, event)
    except Exception as exc:
        raise SavedEntryTerminalizationError("OFFICIAL_TERMINAL_APPEND_FAILED_NO_RETRY") from exc
    terminals = [e for e in _events(adapter) if e.get("execution_id") == claim.execution_id
                 and e.get("event_type") == "TERMINAL"]
    if len(terminals) != 1 or terminals[0].get("decision") != status:
        raise SavedEntryError("TERMINAL_NOT_DURABLE_OR_STATUS_MISMATCH")
    terminal = dict(run_doc, terminal_event_sha256=terminals[0]["event_sha256"],
        start_event_sha256=start["event_sha256"], run_receipt_sha256=worker.sha256_file(run_path),
        terminal_chain={
            "run_receipt_path": str(run_path.resolve()),
            "run_receipt_sha256": worker.sha256_file(run_path),
            "failure_evidence": evidence_refs["failure_evidence"],
            "worker_status": evidence_refs["worker_status"],
            "evaluation_result": evidence_refs["evaluation_result"],
        })
    worker.write_json_exclusive(output / "EVALUATION_TERMINAL_RECEIPT.json", terminal)
    return terminal
