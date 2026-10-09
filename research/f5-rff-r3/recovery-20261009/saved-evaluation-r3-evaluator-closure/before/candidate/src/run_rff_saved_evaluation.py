#!/usr/bin/env python3
"""Prepare an unsigned binding, or run one explicitly released saved evaluation.

Imports are inert. The CLI run path validates the real RFF binding and native
runtime before a zero-debit official RUN_STARTED. The internal execution seam
also supports generated fixtures; it is not a local-review or release issuer.
No append, worker invocation, truth decode, or failed execution is retried.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import signal
import sys
import tempfile
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ARM = "SAVED_RFF_EVALUATION_ONLY"
TRUTH_KEYS = ("evaluation_truth_artifact_read_attempts", "evaluation_truth_artifact_reads_completed",
              "evaluation_truth_decode_attempts", "evaluation_truth_decodes_completed",
              "control_label_artifacts_decoded", "evaluation_label_values_decoded")


def _common():
    path = Path(__file__).resolve().with_name("rff_saved_eval_contracts.py")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    name = "_rff_launcher_contracts_" + digest[:16]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        exec(compile(raw, str(path), "exec"), module.__dict__)
    return sys.modules[name]


@contextlib.contextmanager
def _fresh_source_imports():
    """Original importlib helpers and spawned imports cannot reuse old pyc files."""
    keys = ("PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE")
    before_env = {key: os.environ.get(key) for key in keys}
    before_prefix, before_flag = sys.pycache_prefix, sys.dont_write_bytecode
    with tempfile.TemporaryDirectory(prefix="rff-saved-eval-imports-") as directory:
        sys.pycache_prefix = directory
        sys.dont_write_bytecode = True
        os.environ["PYTHONPYCACHEPREFIX"] = directory
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            yield
        finally:
            sys.pycache_prefix, sys.dont_write_bytecode = before_prefix, before_flag
            for key, value in before_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _identity(binding, input_binding_sha256):
    return {"execution_id": binding["execution_id"], "route_id": binding["route_id"],
            "candidate_execution_id": binding["candidate_execution_id"],
            "run_spec_sha256": binding["run_spec_sha256"],
            "input_binding_sha256": input_binding_sha256,
            "source_code_sha256": binding["code_sha256"]}


def _error(exc, stage):
    detail = {"stage": stage, "type": type(exc).__name__, "message": str(exc),
              "traceback": traceback.format_exc()}
    abort = getattr(exc, "rff_monitor_abort", None)
    if isinstance(abort, Mapping):
        detail["monitor_abort"] = dict(abort)
    return detail


def _optional_json(common, path):
    path = Path(path)
    try:
        if not path.exists():
            return None, {"path": str(path), "sha256": None, "status": "MISSING"}
        ref = common.file_record(path)
        doc = common.json_object(common.checked_read(ref), name=path.name)
        common.canonical_bytes(doc)  # reject NaN/Infinity in malformed evidence
        return doc, {**ref, "status": "PRESENT"}
    except Exception as exc:
        return None, {"path": str(path), "status": "INVALID", "error": str(exc)}


def _readback(common, adapter, binding, binding_sha, *, terminal_status=None):
    """One validated readback of an exact prefix plus this execution's events."""
    with adapter._locked():
        raw, events = adapter._read_validated()
    own = [(i, row) for i, row in enumerate(events) if row.get("execution_id") == binding["execution_id"]]
    expected_types = ["RUN_STARTED"] if terminal_status is None else ["RUN_STARTED", "TERMINAL"]
    if [row.get("event_type") for _, row in own] != expected_types:
        raise RuntimeError("DURABLE_LIFECYCLE_READBACK_NOT_UNIQUE")
    index, start = own[0]
    prefix = b"".join(raw.splitlines(keepends=True)[:index])
    if (len(events) != index + len(own)
            or common.sha256_bytes(prefix) != binding["official_registry_sha256_before_start"]
            or start.get("previous_event_sha256") != binding["expected_previous_event_sha256"]):
        raise RuntimeError("DURABLE_LIFECYCLE_READBACK_PREFIX_MISMATCH")
    expected = {"experiment_id": binding["route_id"], "route_id": binding["route_id"],
        "execution_id": binding["execution_id"], "arm": ARM,
        "contract_sha256": binding["run_spec_sha256"], "input_binding_sha256": binding_sha,
        "code_sha256": binding["code_sha256"], "candidate_execution_id": binding["candidate_execution_id"]}
    for _, row in own:
        if any(common.canonical_bytes(row.get(key)) != common.canonical_bytes(value) for key, value in expected.items()):
            raise RuntimeError("DURABLE_LIFECYCLE_READBACK_IDENTITY_MISMATCH")
        metrics = row.get("deterministic_metrics") or {}
        if (metrics.get("execution_kind") != "NO_FIT_ENGINEERING_CANARY"
                or any(type(metrics.get(key)) is not int or metrics[key] != 0
                       for key in ("real_fit_budget_debit", "planned_real_fit_count"))
                or row.get("authorization_records", {}) != adapter._authorization_snapshot()):
            raise RuntimeError("DURABLE_LIFECYCLE_READBACK_DEBIT_OR_AUTHORIZATION_MISMATCH")
    route = [row["event_sha256"] for row in events
             if row.get("route_id") == binding["route_id"] or row.get("experiment_id") == binding["route_id"]]
    if route != binding["expected_route_event_sha256_before_start"] + [row["event_sha256"] for _, row in own]:
        raise RuntimeError("DURABLE_LIFECYCLE_READBACK_ROUTE_MISMATCH")
    if terminal_status is not None:
        terminal = own[1][1]
        if (terminal.get("previous_event_sha256") != start["event_sha256"]
                or terminal.get("decision") != terminal_status):
            raise RuntimeError("DURABLE_TERMINAL_READBACK_STATUS_MISMATCH")
    return raw, [row for _, row in own]


def _observations(common, binding, binding_sha, start_sha, *, monitor_entered, descriptor, monitor_error=None):
    output = Path(binding["output_root"])
    status, status_ref = _optional_json(common, output / "EVALUATION_WORKER_STATUS.json")
    marker, marker_ref = _optional_json(common, output / "EVALUATION_TRUTH_READ_START.json")
    spawn, spawn_ref = _optional_json(common, output / "EVALUATION_MONITOR_FAILURE.json")
    abort_file, abort_ref = _optional_json(common, output / "EVALUATION_MONITOR_ABORT.json")
    expected = {**_identity(binding, binding_sha), "start_receipt_sha256": start_sha}
    zero = lambda value: all(common.canonical_bytes(value.get(key)) == common.canonical_bytes(item)
                             for key, item in common.ZERO_COUNTS.items())
    valid_status = (status is not None and status.get("schema") == "F5_RFF_SAVED_EVAL_WORKER_STATUS_V1"
                    and status.get("status") in {"COMPLETED", "FAILED"}
                    and all(status.get(key) == item for key, item in expected.items())
                    and zero(status) and status.get("safety") == common.SAFETY)
    valid_marker = (marker is not None
                    and marker.get("schema") == "F5_RFF_SAVED_EVAL_TRUTH_READ_START_V1"
                    and all(marker.get(key) == item for key, item in expected.items())
                    and marker.get("truth_sha256") == binding["input_files"]["eval_truth"]["sha256"]
                    and marker.get("prediction_seal_sha256") == binding["metadata_files"]["prediction_seal"]["sha256"]
                    and marker.get("label_values_decode_started") is True
                    and type(marker.get("evaluation_truth_decode_attempts")) is int
                    and marker["evaluation_truth_decode_attempts"] == 1
                    and marker.get("evaluation_truth_decodes_completed") is None
                    and zero(marker) and marker.get("safety") == common.SAFETY)
    truth_valid = False
    if valid_status:
        limits = dict(zip(TRUTH_KEYS[:5], (1, 1, 1, 1, 2)))
        truth_valid = all(type(status.get(key)) is int and 0 <= status[key] <= limit for key, limit in limits.items())
        if truth_valid:
            ra, rc, da, dc, controls = [status[key] for key in TRUTH_KEYS[:5]]
            truth_valid = (ra >= rc >= da >= dc and (controls == 0 or dc == 1)
                           and status.get("evaluation_label_values_decoded") is (dc == 1)
                           and (valid_marker if da else marker_ref["status"] == "MISSING"))
    expected_sources = {**binding["code_files"], "resource_tree": binding["executable_helpers"]["resource_tree"]}
    def source_identity_matches(reported):
        return (isinstance(reported, dict) and set(reported) == set(expected_sources)
            and all(isinstance(reported[name], dict)
                    and all(reported[name].get(key) == ref.get(key) for key in ("path", "sha256"))
                    for name, ref in expected_sources.items()))
    # The original SPAWN_START try also contains context-manager exit. Its
    # PROCESS_NOT_STARTED label alone can be wrong after start() returned.
    # Require the wrapper's actual start observations; an in-memory abort
    # remains authoritative even when its evidence file could not be written.
    aborts = [abort_file] if abort_file is not None else []
    attached_abort = (monitor_error or {}).get("monitor_abort")
    if isinstance(attached_abort, dict):
        aborts.append(attached_abort)
    def verified_no_start(abort):
        workers = abort.get("workers")
        return (abort.get("schema") == "F5_RFF_SAVED_EVAL_MONITOR_ABORT_V1"
            and abort.get("status") == "MONITOR_ABORT"
            and abort.get("stage") == "UNEXPECTED_MONITOR_EXCEPTION"
            and all(abort.get(key) == value for key, value in _identity(binding, binding_sha).items())
            and abort.get("target_descriptor") == descriptor
            and abort.get("resource_trace_path") == binding["resource_trace_path"]
            and source_identity_matches(abort.get("source_files"))
            and abort.get("exit_code_state") == "PROCESS_NOT_STARTED"
            and abort.get("process_tree_termination_confirmed") is True
            and type(abort.get("process_creation_count")) is int
            and isinstance(workers, list) and len(workers) == abort["process_creation_count"]
            and all(type(abort.get(key)) is int and abort[key] == 0
                    for key in ("process_start_attempted_count", "process_start_returned_count"))
            and all(isinstance(worker, dict) and worker.get("pid") is None
                    and worker.get("process_state") == "PROCESS_NOT_STARTED"
                    and worker.get("process_start_attempted") is False
                    and worker.get("process_start_returned") is False for worker in workers))
    proven_abort_no_start = bool(aborts) and all(verified_no_start(abort) for abort in aborts)
    proven_no_spawn = not monitor_entered or proven_abort_no_start
    proven_no_spawn = proven_no_spawn and status_ref["status"] == "MISSING" and marker_ref["status"] == "MISSING"
    observed = {"status": "KNOWN" if valid_status else "KNOWN_NOT_LAUNCHED" if proven_no_spawn else "UNKNOWN",
                **{key: value if valid_status or proven_no_spawn else None for key, value in common.ZERO_COUNTS.items()}}
    if status is not None and not valid_status:
        observed["reported_activity_not_validated"] = {key: status.get(key) for key in common.ZERO_COUNTS}
    if truth_valid:
        truth = {"status": "WORKER_STATUS_VERIFIED", **{key: status[key] for key in TRUTH_KEYS}}
    elif valid_marker:
        truth = {"status": "ATTEMPT_DURABLE_COMPLETION_UNKNOWN", **{key: None for key in TRUTH_KEYS},
                 "evaluation_truth_artifact_read_attempts": 1, "evaluation_truth_artifact_reads_completed": 1,
                 "evaluation_truth_decode_attempts": 1}
    elif proven_no_spawn:
        truth = {"status": "KNOWN_NOT_LAUNCHED", **{key: 0 for key in TRUTH_KEYS[:5]},
                 "evaluation_label_values_decoded": False}
    else:
        truth = {"status": "CANNOT_CONFIRM", **{key: None for key in TRUTH_KEYS}}
    if status is not None and not truth_valid:
        truth["reported_truth_counts_not_validated"] = {key: status.get(key) for key in TRUTH_KEYS}
    return observed, truth, status if valid_status and truth_valid else None, {
        "worker_status": status_ref, "truth_read_start": marker_ref, "monitor_failure": spawn_ref,
        "monitor_abort": abort_ref}


def _validate_completion(common, binding, binding_sha, start_sha, monitor, status, truth):
    if (not isinstance(monitor, dict) or type(monitor.get("worker_exitcode")) is not int
            or monitor["worker_exitcode"] != 0 or monitor.get("terminal_reason") is not None
            or (monitor.get("post_trace_fsync_terminal_check") or {}).get("after_trace_fsync") is not True
            or (monitor.get("final_post_fsync_check") or {}).get("after_final_trace_fsync") is not True):
        raise RuntimeError("MONITOR_COMPLETION_AND_FINAL_FSYNC_NOT_CONFIRMED")
    trace, trace_ref = _optional_json(common, binding["resource_trace_path"])
    if (trace is None or trace.get("terminal_reason") is not None or trace.get("worker_exitcode") != 0
            or monitor.get("threads") != binding["resources"]["cpu_threads"]
            or monitor.get("wall_seconds_max") != binding["resources"]["wall_seconds_max"]
            or monitor.get("aggregate_rss_bytes_max") != binding["resources"]["aggregate_process_tree_rss_bytes_max"]):
        raise RuntimeError("DURABLE_RESOURCE_TRACE_MISSING_OR_SCOPE_MISMATCH")
    if (status is None or status.get("status") != "COMPLETED" or status.get("metrics_computed") is not True
            or type(status.get("native_runtime_check_attempts")) is not int
            or status["native_runtime_check_attempts"] != 1
            or type(status.get("native_runtime_checks_completed")) is not int
            or status["native_runtime_checks_completed"] != 1
            or not isinstance(status.get("native_runtime_observation"), dict)
            or truth.get("evaluation_truth_decode_attempts") != 1
            or truth.get("evaluation_truth_decodes_completed") != 1
            or truth.get("control_label_artifacts_decoded") != 2):
        raise RuntimeError("WORKER_COMPLETION_AND_ACTUAL_COUNTERS_NOT_CONFIRMED")
    output = Path(binding["output_root"])
    result_ref = common.file_record(output / "EVALUATION_RESULT_RECEIPT.json", status["result_receipt_sha256"])
    result = common.json_object(common.checked_read(result_ref), name="result_receipt")
    expected = {**_identity(binding, binding_sha), "start_receipt_sha256": start_sha,
        "schema": "F5_RFF_SAVED_EVAL_RESULT_V1", "status": "COMPLETED", "metrics_computed": True,
        "metrics_sha256": status["metrics_sha256"], "evidence_ceiling": "DIRECTION_ONLY",
        "historical_candidate_mutation": False, "automatic_retry": False, "safety": common.SAFETY,
        "prediction_seal_sha256": binding["metadata_files"]["prediction_seal"]["sha256"],
        "input_sha256": {name: ref["sha256"] for name, ref in binding["input_files"].items()},
        "native_runtime_check_attempts": 1, "native_runtime_checks_completed": 1,
        "native_runtime_observation": status["native_runtime_observation"],
        **common.ZERO_COUNTS, **{key: truth[key] for key in TRUTH_KEYS}}
    if any(common.canonical_bytes(result.get(key)) != common.canonical_bytes(value) for key, value in expected.items()):
        raise RuntimeError("SAVED_RESULT_RECEIPT_IDENTITY_OR_COUNTERS_MISMATCH")
    metrics_ref = common.file_record(output / "METRICS.json", status["metrics_sha256"])
    metrics = common.json_object(common.checked_read(metrics_ref), name="metrics")
    expected_metrics = {**{key: expected[key] for key in ("execution_id", "route_id", "candidate_execution_id",
                          "run_spec_sha256", "input_binding_sha256", "prediction_seal_sha256",
                          "source_code_sha256", "start_receipt_sha256", "native_runtime_check_attempts",
                          "native_runtime_checks_completed", "native_runtime_observation")},
        "schema": "F5_FULL64_RFF_LOGISTIC_FULL2024_METRICS_V1", "evidence_ceiling": "DIRECTION_ONLY",
        "evidence_status": "DIRECTION_ONLY", "promotion_decision": "BLOCKED_SINGLE_EXPOSED_YEAR",
        "safety": common.SAFETY, "accepted_worker_sha256": common.PINS["accepted_worker"],
        **{key: binding["evaluation_contract"][key] for key in ("year", "grid_rows", "scoreable_rows", "sessions", "selection_slots")},
        "truth_positive_denominator": binding["evaluation_contract"]["known_positive_denominator"],
        **common.ZERO_COUNTS, **{key: truth[key] for key in TRUTH_KEYS}}
    if any(common.canonical_bytes(metrics.get(key)) != common.canonical_bytes(value) for key, value in expected_metrics.items()):
        raise RuntimeError("SAVED_METRICS_IDENTITY_DENOMINATOR_OR_SAFETY_MISMATCH")
    if set(metrics["arms"]) != {"CANDIDATE_RFF_LOGISTIC", *common.CONTROLS}:
        raise RuntimeError("SAVED_METRICS_ARM_SET_MISMATCH")
    if (metrics.get("binary_control_evaluator_outputs_deep_equal_to_original") != {arm: True for arm in common.CONTROLS}
            or metrics.get("episode_denominator_check", {}).get("all_equal") is not True
            or any(metrics["paired_precision"][arm]["denominator"] != binding["evaluation_contract"]["selection_slots"]
                   for arm in common.CONTROLS)):
        raise RuntimeError("SAVED_METRICS_PARITY_OR_PAIRED_DENOMINATOR_MISMATCH")
    paired = metrics["paired_precision"]
    gates = metrics["development_gates"]
    if (gates["paired_lower_vs_plus_gt_zero"] is not (paired[common.CONTROLS[0]]["lower"] > 0)
            or gates["paired_lower_vs_base34_ge_003"] is not (paired[common.CONTROLS[1]]["lower"] >= .03)):
        raise RuntimeError("SAVED_METRICS_DEVELOPMENT_GATE_MISMATCH")
    fields = ("slots", "hits_known", "unknown_selected", "precision_lower", "precision_upper",
              "confirmed_new_events", "hit_unique_episodes", "episode_coverage_confirmed")
    summary = {"metrics_computed": True, "metrics_sha256": metrics_ref["sha256"],
        "evidence_ceiling": "DIRECTION_ONLY", "arms": {name: {key: arm[key] for key in fields}
        for name, arm in metrics["arms"].items()}, "paired_precision": {
            name: {key: value for key, value in row.items() if key != "daily"} for name, row in paired.items()},
        "development_gates": gates, "original_promotion_gates": metrics["original_promotion_gates"],
        "promotion_decision": metrics["promotion_decision"]}
    return summary, {"metrics": metrics_ref, "result_receipt": result_ref, "resource_trace": trace_ref}


def _execute_bound(*, binding, input_binding_sha256, adapter, guard, guard_module,
                   native_spec, native_observation, monitor):
    """Internal integration seam; CLI must validate release/native metadata first."""
    common = _common()
    resources = common.validate_resources(binding["resources"])
    # The packaged helper's interface explicitly rejects any other value.
    # Never substitute this for the controller's newly approved resource cap.
    if resources["cpu_threads"] != 4:
        raise RuntimeError("PACKAGED_MONITOR_THREAD_PROFILE_UNSUPPORTED_REQUIRES_EXPLICIT_4")
    common.verify_sources(binding)
    common.checked_read({"path": binding["input_binding_path"], "sha256": input_binding_sha256}, name="input_binding")
    common.checked_read({"path": binding["run_spec_path"], "sha256": binding["run_spec_sha256"]}, name="run_spec")
    output, trace = Path(binding["output_root"]), Path(binding["resource_trace_path"])
    protected = {f"{category}:{name}": ref for category in
        ("input_files", "code_files", "executable_helpers", "official_helpers", "metadata_files")
        for name, ref in binding[category].items()}
    for name in ("official_registry_path", "run_spec_path", "input_binding_path", "parent_release_path", "reviewer_transcript_path"):
        if name in binding:
            protected[name] = {"path": binding[name]}
    common.validate_new_paths(output, trace, Path(binding["candidate_output_root"]), protected, require_new=True)
    before_accounting = asdict(guard.accounting())
    if before_accounting["real_fit_budget_debit_count"] != 1:
        raise RuntimeError("HISTORICAL_CANDIDATE_FIT_DEBIT_NOT_ONE")
    output.mkdir(parents=True, exist_ok=False)
    trace.parent.mkdir(parents=True, exist_ok=True)
    identity = _identity(binding, input_binding_sha256)
    descriptor = {**binding["code_files"]["rff_saved_eval_worker"],
                  "module_name": "rff_saved_evaluation_worker_target", "callable": "run_saved_evaluation"}
    claim, start_sha, monitor_result = None, None, None
    monitor_entered, start_error, error = False, None, None
    try:
        claim = guard.claim_no_fit(execution_id=binding["execution_id"], arm=ARM,
            contract_sha256=binding["run_spec_sha256"], input_binding_sha256=input_binding_sha256)
    except BaseException as exc:
        start_error = _error(exc, "OFFICIAL_RUN_STARTED_APPEND")
        try:
            start_raw, own = _readback(common, adapter, binding, input_binding_sha256)
        except BaseException as readback_exc:
            common.write_json_exclusive(output / "EVALUATION_PRESTART_FAILURE.json", {
                **identity, "status": "START_NOT_CONFIRMED_NO_WORKER_LAUNCHED", "error": start_error,
                "readback_error": _error(readback_exc, "RUN_STARTED_SINGLE_READBACK"),
                "automatic_retry": False, "safety": common.SAFETY})
            raise exc
        claim = guard_module.ExecutionClaim(experiment_id=binding["route_id"], execution_id=binding["execution_id"],
            arm=ARM, contract_sha256=binding["run_spec_sha256"], input_binding_sha256=input_binding_sha256,
            execution_kind="NO_FIT_ENGINEERING_CANARY", real_fit_budget_debit=0)
    try:
        if start_error is None:
            start_raw, own = _readback(common, adapter, binding, input_binding_sha256)
        start_sha = common.write_json_exclusive(Path(binding["start_receipt_path"]), {
            "schema": "F5_RFF_SAVED_EVAL_START_RECEIPT_V1", **identity,
            "status": "RUN_STARTED_DURABLE", "start_event_sha256": own[0]["event_sha256"],
            "official_registry_sha256_after_start": common.sha256_bytes(start_raw),
            "real_fit_budget_debit": 0, "planned_real_fit_count": 0, **common.ZERO_COUNTS,
            "historical_candidate_debits": {"fit": 1, "predict": 1, "truth_decode": 1},
            "start_append_raised_after_durable": start_error is not None,
            "safety": common.SAFETY, "automatic_retry": False})
        if start_error is not None:
            error = start_error
        else:
            drift = adapter._verify_contract_snapshots()
            if drift["files"]:
                raise RuntimeError("BOUND_DEPENDENCY_OR_RELEASE_CHANGED_AFTER_START")
            payload = {**binding, "input_binding_sha256": input_binding_sha256,
                       "start_receipt_sha256": start_sha, "native_spec": native_spec}
            monitor_entered = True
            monitor_result = monitor(None, payload, native_spec=native_spec,
                native_runtime_helper_path=Path(binding["executable_helpers"]["native_runtime"]["path"]),
                wall_seconds_max=resources["wall_seconds_max"],
                rss_bytes_max=resources["aggregate_process_tree_rss_bytes_max"], threads=resources["cpu_threads"],
                sample_seconds=resources["sample_seconds"], resource_trace_path=trace,
                target_descriptor=descriptor, failure_evidence_path=output / "EVALUATION_MONITOR_FAILURE.json",
                failure_context={"source_files": binding["code_files"], **identity})
    except BaseException as exc:
        error = _error(exc, "MONITOR_OR_START_RECEIPT")
    try:
        observed, truth, worker_status, evidence = _observations(common, binding, input_binding_sha256, start_sha,
            monitor_entered=monitor_entered, descriptor=descriptor, monitor_error=error)
    except BaseException as exc:
        error = _error(exc, "READ_WORKER_OBSERVATIONS")
        observed = {"status": "UNKNOWN", **{key: None for key in common.ZERO_COUNTS}}
        truth = {"status": "CANNOT_CONFIRM", **{key: None for key in TRUTH_KEYS}}
        worker_status, evidence = None, {"observation_read_error": error}
    evaluation = {"metrics_computed": False, "evidence_ceiling": "DIRECTION_ONLY"}
    terminal_status = "CANNOT_CONFIRM"
    if error is None:
        try:
            evaluation, completed_evidence = _validate_completion(common, binding, input_binding_sha256, start_sha,
                                                                  monitor_result, worker_status, truth)
            common.verify_sources(binding)
            drift = adapter._verify_contract_snapshots()
            if drift["files"]:
                raise RuntimeError("BOUND_DEPENDENCY_OR_RELEASE_CHANGED_AFTER_WORKER")
            evidence.update(completed_evidence)
            terminal_status = "COMPLETED"
        except BaseException as exc:
            error = _error(exc, "VERIFY_SAVED_EVALUATION_COMPLETION")
            evaluation = {"metrics_computed": False, "evidence_ceiling": "DIRECTION_ONLY"}
    try:
        for name in ("METRICS.json", "EVALUATION_RESULT_RECEIPT.json", "EVALUATION_FAILURE_EVIDENCE.json",
                     "EVALUATION_WORKER_ERROR.json", "EVALUATION_MONITOR_ABORT.json"):
            _, ref = _optional_json(common, output / name)
            evidence.setdefault(name, ref)
        _, ref = _optional_json(common, trace)
        evidence.setdefault("resource_trace", ref)
    except BaseException as exc:
        error = _error(exc, "COLLECT_OPTIONAL_EVALUATION_EVIDENCE")
        evidence["collection_error"] = error
        evaluation, terminal_status = {"metrics_computed": False, "evidence_ceiling": "DIRECTION_ONLY"}, "CANNOT_CONFIRM"
    monitor_summary = {key: value for key, value in (monitor_result if isinstance(monitor_result, dict) else {}).items()
                       if key != "samples"}
    run_receipt = {"schema": "F5_RFF_SAVED_EVAL_RUN_RECEIPT_V1", **identity, "status": terminal_status,
        "observed_worker_accounting": observed, "truth_accounting": truth, "evaluation_metrics": evaluation,
        "start_receipt_sha256": start_sha, "error": error, "evidence": evidence,
        "resources": resources, "resource_observation": monitor_summary, "native_observation": native_observation,
        "historical_guard_accounting_before": before_accounting,
        "historical_candidate_debits": {"fit": 1, "predict": 1, "truth_decode": 1},
        "real_fit_budget_debit": 0, "historical_candidate_mutation": False,
        "safety": common.SAFETY, "evidence_ceiling": "DIRECTION_ONLY", "automatic_retry": False,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat()}
    run_sha, run_receipt_error, artifact_collection_error = None, None, None
    try:
        run_sha = common.write_json_exclusive(output / "EVALUATION_RUN_RECEIPT.json", run_receipt)
    except BaseException as exc:
        # A receipt write is not allowed to bypass an already owed terminal.
        # Preserve the observation in the terminal event; do not replace/retry
        # a partially written or pre-existing receipt.
        run_receipt_error = _error(exc, "WRITE_EVALUATION_RUN_RECEIPT")
        error, terminal_status = run_receipt_error, "CANNOT_CONFIRM"
        evaluation = {"metrics_computed": False, "evidence_ceiling": "DIRECTION_ONLY"}
    try:
        adapter.artifact_paths = list(dict.fromkeys([*adapter.artifact_paths,
            *(p for p in output.iterdir() if p.is_file()), *([trace] if trace.is_file() else [])]))
    except BaseException as exc:
        artifact_collection_error = _error(exc, "COLLECT_TERMINAL_ARTIFACT_REFERENCES")
        error, terminal_status = artifact_collection_error, "CANNOT_CONFIRM"
        evaluation = {"metrics_computed": False, "evidence_ceiling": "DIRECTION_ONLY"}
    event = {"event_type": "TERMINAL", **{key: getattr(claim, key) for key in
        ("experiment_id", "execution_id", "arm", "contract_sha256", "input_binding_sha256")},
        "execution_kind": "NO_FIT_ENGINEERING_CANARY", "planned_real_fit_count": 0, "real_fit_budget_debit": 0,
        "terminal_status": terminal_status, "observed_worker_accounting": observed, "truth_accounting": truth,
        "truth_access": "EVAL_LABELS_DECODED_AFTER_SAVED_PREDICTION_SEAL" if truth.get("evaluation_truth_decodes_completed") == 1
                        else "NOT_READ_IN_THIS_EVALUATION" if truth.get("evaluation_truth_decode_attempts") == 0 else "CANNOT_CONFIRM",
        "sealed_status": "EXPOSED_2024_POST_SEAL_EVALUATION",
        "truth_positive_denominator": binding["evaluation_contract"]["known_positive_denominator"] if terminal_status == "COMPLETED" else None,
        "selection_slots": binding["evaluation_contract"]["selection_slots"] if terminal_status == "COMPLETED" else None,
        "evaluation_metrics": evaluation, "stop_reason": error["message"] if error else None,
        **common.SAFETY, "promotion_now": False}
    terminal_error = None
    try:
        adapter.terminalize(claim, event)
    except BaseException as exc:
        terminal_error = _error(exc, "OFFICIAL_TERMINAL_APPEND")
    try:
        after_raw, own = _readback(common, adapter, binding, input_binding_sha256, terminal_status=terminal_status)
        after_accounting = asdict(guard.accounting())
        if after_accounting["real_fit_budget_debit_count"] != before_accounting["real_fit_budget_debit_count"]:
            raise RuntimeError("HISTORICAL_FIT_BUDGET_CHANGED")
    except BaseException as exc:
        common.write_json_exclusive(output / "TERMINALIZATION_BLOCKED.json", {
            **identity, "status": "TERMINALIZATION_UNCONFIRMED", "terminal_append_error": terminal_error,
            "readback_error": _error(exc, "TERMINAL_SINGLE_READBACK"), "run_receipt_sha256": run_sha,
            "observed_worker_accounting": observed, "truth_accounting": truth,
            "automatic_retry": False, "safety": common.SAFETY})
        raise RuntimeError("TERMINALIZATION_UNCONFIRMED_NO_AUTOMATIC_RETRY") from exc
    terminal_receipt = {"schema": "F5_RFF_SAVED_EVAL_TERMINAL_RECEIPT_V1", **identity, "status": terminal_status,
        "start_event_sha256": own[0]["event_sha256"], "terminal_event_sha256": own[1]["event_sha256"],
        "official_registry_sha256_after_terminal": common.sha256_bytes(after_raw),
        "run_receipt_sha256": run_sha, "start_receipt_sha256": start_sha,
        "run_receipt_error": run_receipt_error, "artifact_collection_error": artifact_collection_error,
        "start_and_run_receipts_complete": start_sha is not None and run_sha is not None,
        "terminal_append_raised_after_durable": terminal_error is not None, "terminal_append_error": terminal_error,
        "historical_guard_accounting_after": after_accounting, "real_fit_budget_debit": 0,
        "safety": common.SAFETY, "evidence_ceiling": "DIRECTION_ONLY", "automatic_retry": False}
    common.write_json_exclusive(output / "EVALUATION_TERMINAL_RECEIPT.json", terminal_receipt)
    return terminal_receipt


def _check_monitor_backend(resource_tree, resources):
    """Observe the real parent-only OS backend once before any RUN_STARTED."""
    try:
        rss, members, _known = resource_tree._tree_rss_bytes(os.getpid(), None, {})
        if type(rss) is not int or rss <= 0 or members != [os.getpid()]:
            raise ValueError("PARENT_RSS_SAMPLE_INVALID_OR_SCOPE_MISMATCH")
        backend = "psutil" if resource_tree._load_psutil() is not None else "posix_ps"
    except Exception as exc:
        raise RuntimeError(f"MONITOR_BACKEND_PREFLIGHT_FAILED:{type(exc).__name__}:{exc}") from exc
    cap = resources["aggregate_process_tree_rss_bytes_max"]
    if rss > cap:
        raise RuntimeError(f"RESOURCE_RSS_ALREADY_EXCEEDS_BOUND:{rss}:{cap}")
    return {"scope": "CALLER_ONLY_BEFORE_RUN_STARTED", "backend": backend,
        "aggregate_process_tree_rss_bytes": rss, "process_ids": list(members),
        "sample_count": 1, "aggregate_process_tree_rss_bytes_max": cap,
        "worker_spawned": False}


@contextlib.contextmanager
def _defer_sigint_during_abort(record):
    """Finish one bounded cleanup despite a second user interrupt, then rethrow."""
    previous = None
    installed = False
    record["sigint_deferred_during_cleanup"] = 0
    def defer(signum, _frame):
        record["sigint_deferred_during_cleanup"] += 1
    try:
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, defer)
        installed = True
    except (ValueError, OSError) as exc:
        # The production CLI runs on the main thread. A non-main-thread caller
        # receives explicit evidence that Python could not defer its signals.
        record["sigint_deferral_error"] = {"type": type(exc).__name__, "message": str(exc)}
    record["sigint_deferral_installed"] = installed
    try:
        yield
    finally:
        if installed:
            signal.signal(signal.SIGINT, previous)


def _monitor_once(resource_tree, target, payload, **kwargs):
    """Call the original monitor once and close its tree on unexpected failure."""
    processes = []
    known_processes = {}
    original_mp = resource_tree.mp
    original_sample = resource_tree._tree_rss_bytes

    class ProcessProxy:
        # The actual SpawnProcess is the object pickled by start(). Attaching a
        # local start closure to that real object would break multiprocessing.
        def __init__(self, process):
            self.process = process
            self.process_start_attempted = False
            self.process_start_returned = False
            self.popen_instances = []
            self.popen_handle_recovered = False
            self.popen_recovery_error = None
            self.sigint_deferred_during_start = 0
            self.start_sigint_guard_installed = False

        def recover_existing_handle(self):
            """Adopt only an observed Popen of this exact existing Process."""
            if self.process._popen is not None:
                return
            launched = [popen for popen in self.popen_instances
                        if type(getattr(popen, "pid", None)) is int and popen.pid > 0]
            if len(launched) == 1:
                popen = launched[0]
                self.process._popen = popen
                if type(getattr(popen, "sentinel", None)) is int:
                    self.process._sentinel = popen.sentinel
                # This is the already spawned child, registered for ordinary
                # multiprocessing ownership, not a new Process or second start.
                from multiprocessing import process as process_module
                process_module._children.add(self.process)
                self.popen_handle_recovered = True
            elif len(launched) > 1:
                self.popen_recovery_error = {
                    "type": "AmbiguousPopenIdentity", "message": "MULTIPLE_OBSERVED_HANDLES_FOR_EXACT_PROCESS"}

        def start(self):
            from multiprocessing import popen_spawn_posix
            original_init = popen_spawn_posix.Popen.__init__
            previous_sigint = signal.getsignal(signal.SIGINT)

            def defer_start_sigint(_signum, _frame):
                self.sigint_deferred_during_start += 1

            def observe_init(popen, process_obj):
                # Observe before __init__: construction can itself raise after
                # launching the OS child but before returning its Popen object.
                if process_obj is self.process:
                    self.popen_instances.append(popen)
                return original_init(popen, process_obj)

            # Fail before any actual start if this CLI cannot establish the
            # short signal guard. A SIGINT return/assignment gap must not lose
            # the only real child handle. The previous handler is always restored.
            signal.signal(signal.SIGINT, defer_start_sigint)
            self.start_sigint_guard_installed = True
            try:
                popen_spawn_posix.Popen.__init__ = observe_init
                try:
                    self.process_start_attempted = True
                    try:
                        result = self.process.start()
                        self.process_start_returned = True
                    except BaseException:
                        try:
                            self.recover_existing_handle()
                        except BaseException as recovery_exc:
                            self.popen_recovery_error = {
                                "type": type(recovery_exc).__name__, "message": str(recovery_exc)}
                        raise
                finally:
                    popen_spawn_posix.Popen.__init__ = original_init
            finally:
                signal.signal(signal.SIGINT, previous_sigint)
            if self.sigint_deferred_during_start:
                raise KeyboardInterrupt("SIGINT_DEFERRED_UNTIL_PROCESS_HANDLE_ASSIGNED")
            return result

        def __getattr__(self, name):
            return getattr(self.process, name)

    class ContextProxy:
        def __init__(self, context):
            self.context = context

        def Process(self, *args, **process_kwargs):
            process = ProcessProxy(self.context.Process(*args, **process_kwargs))
            processes.append(process)
            return process

        def __getattr__(self, name):
            return getattr(self.context, name)

    class MultiprocessingProxy:
        def get_context(self, *args, **context_kwargs):
            return ContextProxy(original_mp.get_context(*args, **context_kwargs))

        def __getattr__(self, name):
            return getattr(original_mp, name)

    def sampled_tree(*args, **sample_kwargs):
        nonlocal known_processes
        result = original_sample(*args, **sample_kwargs)
        # Retain the latest live map, not historical PIDs that can be reused.
        known_processes = dict(result[2])
        return result

    try:
        resource_tree.mp = MultiprocessingProxy()
        resource_tree._tree_rss_bytes = sampled_tree
        try:
            return resource_tree.run_spawn_monitored(target, payload, **kwargs)
        finally:
            resource_tree.mp = original_mp
            resource_tree._tree_rss_bytes = original_sample
    except BaseException as exc:
        context = dict(kwargs.get("failure_context") or {})
        abort = {**{key: value for key, value in context.items() if key != "source_files"},
            "schema": "F5_RFF_SAVED_EVAL_MONITOR_ABORT_V1", "status": "MONITOR_ABORT",
            "stage": "UNEXPECTED_MONITOR_EXCEPTION", "exception_type": type(exc).__name__,
            "exception_message": str(exc), "traceback": traceback.format_exc(),
            "target_descriptor": kwargs.get("target_descriptor"),
            "resource_trace_path": str(Path(kwargs["resource_trace_path"]).resolve()),
            "process_creation_count": len(processes), "workers": [],
            "process_start_attempted_count": sum(process.process_start_attempted for process in processes),
            "process_start_returned_count": sum(process.process_start_returned for process in processes),
            "automatic_retry": False, "worker_restarted": False}
        # The primary exception remains the one raised by the original monitor.
        # A failed evidence write must not erase the only cleanup observation.
        exc.rff_monitor_abort = abort
        with _defer_sigint_during_abort(abort):
            for process in processes:
                worker = {"pid": None, "exit_code": None, "process_state": "CANNOT_CONFIRM",
                    "process_start_attempted": process.process_start_attempted,
                    "process_start_returned": process.process_start_returned,
                    "popen_instances_observed": len(process.popen_instances),
                    "popen_handle_recovered": process.popen_handle_recovered,
                    "popen_recovery_error": process.popen_recovery_error,
                    "start_sigint_guard_installed": process.start_sigint_guard_installed,
                    "sigint_deferred_during_start": process.sigint_deferred_during_start,
                    "cleanup_attempted": False, "termination": None, "cleanup_error": None}
                abort["workers"].append(worker)
                try:
                    worker["pid"] = process.pid
                    if process.pid is None:
                        # _Popen can launch before BaseProcess assigns its
                        # handle. A failed start() with pid=None is not proof
                        # of zero execution or a clean process tree.
                        worker["process_state"] = ("START_ATTEMPTED_PID_UNAVAILABLE"
                            if process.process_start_attempted else "PROCESS_NOT_STARTED")
                        continue
                    worker["cleanup_attempted"] = True
                    try:
                        worker["termination"] = resource_tree._safe_terminate_descendants(
                            process, dict(known_processes))
                    except BaseException as cleanup_exc:
                        worker["cleanup_error"] = {
                            "type": type(cleanup_exc).__name__, "message": str(cleanup_exc)}
                    worker["exit_code"] = process.exitcode
                    worker["worker_alive_after_cleanup"] = process.is_alive()
                    if ((worker["termination"] or {}).get("confirmed") is True
                            and type(worker["exit_code"]) is int
                            and worker["worker_alive_after_cleanup"] is False):
                        worker["process_state"] = "EXIT_CONFIRMED_AFTER_ABORT_CLEANUP"
                    # A joined handle is closed once; no extra terminate call.
                    if type(worker["exit_code"]) is int:
                        process.close()
                except BaseException as observation_exc:
                    worker["observation_error"] = {
                        "type": type(observation_exc).__name__, "message": str(observation_exc)}
            states = [row["process_state"] for row in abort["workers"]]
            never_started = all(state == "PROCESS_NOT_STARTED" for state in states)
            abort["process_tree_termination_confirmed"] = all(
                state in {"PROCESS_NOT_STARTED", "EXIT_CONFIRMED_AFTER_ABORT_CLEANUP"} for state in states)
            abort["exit_code_state"] = ("PROCESS_NOT_STARTED" if never_started else
                "JOINED_AFTER_ABORT_CLEANUP" if abort["process_tree_termination_confirmed"] else "CANNOT_CONFIRM")
            source_files = dict(context.get("source_files") or {})
            monitor_path = Path(resource_tree.__file__).resolve()
            try:
                monitor_sha = resource_tree._sha256_file(monitor_path)
            except BaseException as source_exc:
                monitor_sha = None
                abort["monitor_source_observation_error"] = {
                    "type": type(source_exc).__name__, "message": str(source_exc)}
            source_files.setdefault("resource_tree", {"path": str(monitor_path), "sha256": monitor_sha})
            abort["source_files"] = source_files
            failure_path = kwargs.get("failure_evidence_path")
            if failure_path is not None:
                abort_path = Path(failure_path).with_name("EVALUATION_MONITOR_ABORT.json")
                abort["abort_evidence_path"] = str(abort_path.resolve())
                try:
                    resource_tree.write_failure_evidence_atomic(abort_path, abort)
                except BaseException as write_exc:
                    abort["abort_evidence_write_error"] = {
                        "type": type(write_exc).__name__, "message": str(write_exc)}
                    exc.add_note(f"MONITOR_ABORT_EVIDENCE_WRITE_FAILED:{type(write_exc).__name__}:{write_exc}")
        raise


def _run_real(spec_path, binding_path):
    common = _common()
    spec, binding, spec_raw, binding_raw = common.load_documents(Path(spec_path), Path(binding_path))
    authorizations = common.verify_review_release(binding, spec_raw, binding_raw)
    if binding["resources"]["cpu_threads"] != 4:
        raise RuntimeError("PACKAGED_MONITOR_THREAD_PROFILE_UNSUPPORTED_REQUIRES_EXPLICIT_4")
    with _fresh_source_imports():
        native = common.load_bound_module(binding["executable_helpers"]["native_runtime"], "_rff_saved_native_runtime")
        native_reference = common.json_object(common.checked_read(binding["metadata_files"]["native_reference"]), name="native_reference")
        native_spec = native.native_spec_from_contract(native_reference)
        native_observation = native.validate_native_files(native_spec, require_macos=True)
        guard_module = common.load_bound_module(binding["official_helpers"]["execution_guard"], "execution_guard_core")
        adapter_module = common.load_bound_module(binding["official_helpers"]["registry_adapter"], "_rff_saved_registry_adapter")
        registration = common.load_bound_module(binding["code_files"]["rff_saved_eval_registration"], "_rff_saved_registration")
        adapter_class = registration.build_official_adapter_class(adapter_module, binding=binding,
            run_spec_path=Path(spec_path), input_binding_path=Path(binding_path),
            run_spec_sha256=common.sha256_bytes(spec_raw), input_binding_sha256=common.sha256_bytes(binding_raw))
        artifact_paths = [Path(ref["path"]) for category in
            ("code_files", "executable_helpers", "official_helpers", "metadata_files") for ref in binding[category].values()]
        artifact_paths += [Path(ref["path"]) for ref in authorizations.values()]
        adapter = adapter_class(registry_path=Path(binding["official_registry_path"]),
            contract_path=Path(spec_path), input_binding_path=Path(binding_path), artifact_paths=artifact_paths,
            builder_path=Path(binding["official_helpers"]["builder"]["path"]),
            validator_path=Path(binding["official_helpers"]["validator"]["path"]),
            event_profile=registration.event_profile(binding))
        adapter.authorization_records = authorizations
        guard = guard_module.ExecutionGuard(adapter, experiment_id=binding["route_id"], max_real_fit_debits=1)
        # multiprocessing spawn must be able to re-import the original module
        # by its actual filename. The fresh pycache directory is inherited.
        monitor_record = binding["executable_helpers"]["resource_tree"]
        monitor_directory = str(Path(monitor_record["path"]).parent)
        if monitor_directory not in sys.path:
            sys.path.insert(0, monitor_directory)
        resource_tree = common.load_bound_module(monitor_record, "resource_tree")
        native_observation["resource_backend_preflight"] = _check_monitor_backend(resource_tree, binding["resources"])
        return _execute_bound(binding=binding, input_binding_sha256=common.sha256_bytes(binding_raw),
            adapter=adapter, guard=guard, guard_module=guard_module, native_spec=native_spec,
            native_observation=native_observation,
            monitor=lambda target, payload, **kwargs: _monitor_once(resource_tree, target, payload, **kwargs))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="metadata only; create unsigned spec/binding, no evaluation")
    prepare.add_argument("--config", required=True)
    run = commands.add_parser("run", help="native Mac controller release required; one saved evaluation")
    run.add_argument("--run-spec", required=True)
    run.add_argument("--input-binding", required=True)
    args = parser.parse_args(argv)
    common = _common()
    try:
        if args.command == "prepare":
            config = common.json_object(Path(args.config).read_bytes(), name="prepare_config")
            result = common.prepare(config)
        else:
            result = _run_real(args.run_spec, args.input_binding)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0 if result.get("status") in {"COMPLETED", "PREPARED_UNSIGNED_REQUIRES_LOCAL_REVIEW_AND_PARENT_RELEASE"} else 1
    except Exception as exc:
        print(json.dumps({"status": "CANNOT_CONFIRM", "error_type": type(exc).__name__, "error": str(exc),
                          "automatic_retry": False, "safety": common.SAFETY}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
