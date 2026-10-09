"""One saved-score evaluation after an official durable start; no model producer.

The native launcher owns the real release and registry validation. This generic
worker also runs on synthetic snapshots in tests, but its caller-supplied payload
must equal the immutable binding and start receipt byte identities. It never
imports the candidate entry, calls a training/prediction API, or opens a model.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping


def _common(payload):
    record = payload["code_files"]["rff_saved_eval_contracts"]
    path = Path(record["path"])
    if path.resolve() != Path(__file__).resolve().parent / "rff_saved_eval_contracts.py":
        raise RuntimeError("WORKER_COMMON_SOURCE_PATH_MISMATCH")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise RuntimeError("WORKER_COMMON_SOURCE_SHA_MISMATCH")
    name = "_rff_saved_common_" + record["sha256"][:16]
    module = sys.modules.get(name)
    if module is not None and (
            Path(str(getattr(module, "__file__", ""))).resolve() != path.resolve()
            or getattr(module, "__rff_source_sha256__", None) != record["sha256"]):
        raise RuntimeError("WORKER_COMMON_CACHED_SOURCE_IDENTITY_MISMATCH")
    if module is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            exec(compile(raw, str(path), "exec"), module.__dict__)
            module.__rff_source_sha256__ = record["sha256"]
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return module


def _read_csv(raw: bytes, *, name: str, columns: list[str]):
    import pandas as pd
    dtype = {"code": "string"} if "code" in columns else None
    try:
        return pd.read_csv(io.BytesIO(raw), compression="gzip", usecols=columns,
                           dtype=dtype, float_precision="round_trip")
    except Exception as exc:
        raise RuntimeError(f"SAVED_CSV_PARSE_FAILED:{name}:{type(exc).__name__}:{exc}") from exc


def _check_frozen_package_cache(common, closure, *, require_closure):
    modules = closure["modules"]
    present = {name: module for name, module in list(sys.modules.items())
               if name == "spike5" or name.startswith("spike5.")}
    for name, module in present.items():
        if name not in modules:
            raise common.SavedEvaluationError(f"UNBOUND_FROZEN_PACKAGE_DEPENDENCY:{name}")
        record = modules[name]
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if (getattr(module, "__file__", None) != record["path"] or origin != record["path"]
                or getattr(module, "__rff_source_sha256__", None) != record["sha256"]):
            raise common.SavedEvaluationError(f"FROZEN_EVALUATOR_MODULE_IDENTITY_MISMATCH:{name}")
        if require_closure and getattr(module, "__rff_evaluator_closure_sha256__", None) != closure["closure_sha256"]:
            raise common.SavedEvaluationError(f"FROZEN_EVALUATOR_CACHED_CLOSURE_MISMATCH:{name}")
    if present and set(present) != set(modules):
        raise common.SavedEvaluationError("FROZEN_EVALUATOR_CACHED_CLOSURE_INCOMPLETE")


def _load_evaluators(common, binding):
    helpers = binding["executable_helpers"]
    # Reject a wrong accepted identity before executing its module body.
    if helpers["accepted_worker"]["sha256"] != common.PINS["accepted_worker"]:
        raise common.SavedEvaluationError("ACCEPTED_PR5_JOIN_SHA_MISMATCH")
    if helpers["score_aware_metrics"]["sha256"] != common.PINS["score_aware_metrics"]:
        raise common.SavedEvaluationError("SCORE_AWARE_METRICS_SOURCE_SHA_MISMATCH")
    closure = common.validate_frozen_evaluator(binding)
    # Reject unknown or stale cached modules before executing any package body.
    _check_frozen_package_cache(common, closure, require_closure=True)
    accepted = common.load_bound_module(helpers["accepted_worker"], "_rff_saved_accepted_pr5")
    score_aware = common.load_bound_module(helpers["score_aware_metrics"], "_rff_saved_score_aware")
    if (helpers["frozen_metrics"]["sha256"] != score_aware.FROZEN_METRICS_SHA256
            or Path(helpers["frozen_metrics"]["path"]).resolve() != score_aware.FROZEN_METRICS_PATH.resolve()):
        raise common.SavedEvaluationError("FROZEN_EVALUATOR_PATH_OR_SHA_MISMATCH")
    # Preload the exact historical transitive modules, so normal relative
    # imports in the original settings/metrics never execute an unbound body.
    modules = closure["modules"]
    package = common.load_bound_module(modules["spike5"], "spike5", package=True)
    for name in ("spike5.common", "spike5.features"):
        module = common.load_bound_module(modules[name], name)
        setattr(package, name.rsplit(".", 1)[1], module)
    frozen_common = sys.modules["spike5.common"]
    original_read_json = frozen_common.read_json

    def read_bound_configuration(path):
        resolved = str(common.plain_path(path))
        record = closure["configs"].get(resolved)
        if record is None:
            raise common.SavedEvaluationError(f"UNBOUND_FROZEN_EVALUATOR_CONFIG:{resolved}")
        return json.loads(common.checked_read(record, name=resolved).decode("utf-8"))

    try:
        # Preserve the original settings and JSON semantics; only its two
        # configuration reads are restricted to historically verified bytes.
        frozen_common.read_json = read_bound_configuration
        settings = common.load_bound_module(modules["spike5.settings"], "spike5.settings")
    finally:
        frozen_common.read_json = original_read_json
    package.settings = settings
    metrics = common.load_bound_module(modules["spike5.metrics"], "spike5.metrics")
    package.metrics = metrics
    if score_aware.frozen_metrics() is not metrics:
        raise common.SavedEvaluationError("FROZEN_EVALUATOR_IMPORT_IDENTITY_MISMATCH")
    _check_frozen_package_cache(common, closure, require_closure=False)
    for name in modules:
        sys.modules[name].__rff_evaluator_closure_sha256__ = closure["closure_sha256"]
    frames = common.load_bound_module(binding["code_files"]["rff_saved_eval_frames"], "_rff_saved_frames")
    return frames, score_aware, accepted


def preflight_evaluators(common, binding):
    """Run the same source/config loader before the owner can create a start."""
    _load_evaluators(common, binding)
    return {"status": "PASS_FROZEN_EVALUATOR_CODE_AND_CONFIG",
            "closure_sha256": sys.modules["spike5"].__rff_evaluator_closure_sha256__}


def _validate_child_runtime(common, binding, payload):
    """Use the bound native verifier in this child; never repair its environment."""
    native = common.load_bound_module(binding["executable_helpers"]["native_runtime"],
                                      "_rff_saved_native_runtime")
    reference = common.json_object(common.checked_read(binding["metadata_files"]["native_reference"],
        name="native_reference"), name="native_reference")
    expected = native.native_spec_from_contract(reference)
    supplied = payload.get("native_spec")
    if not isinstance(supplied, Mapping) or common.canonical_bytes(supplied) != common.canonical_bytes(expected):
        raise common.SavedEvaluationError("CHILD_NATIVE_SPEC_BINDING_MISMATCH")
    # Preserve all original observation fields, including the explicit False
    # for distribution-lock coverage. No synthetic/skip branch exists here.
    return native.verify_child_launch_environment(supplied)


def _start_and_binding(common, payload):
    binding_raw = common.checked_read({"path": payload["input_binding_path"],
        "sha256": payload["input_binding_sha256"]}, name="input_binding")
    binding = common.json_object(binding_raw, name="input_binding")
    for key, value in binding.items():
        if common.canonical_bytes(payload.get(key)) != common.canonical_bytes(value):
            raise common.SavedEvaluationError(f"PAYLOAD_BINDING_MISMATCH:{key}")
    spec_raw = common.checked_read({"path": binding["run_spec_path"],
        "sha256": binding["run_spec_sha256"]}, name="run_spec")
    spec = common.json_object(spec_raw, name="run_spec")
    for key in common.ZERO_AUTHORIZATIONS:
        if type(spec.get(key)) is not int or spec[key] != 0:
            raise common.SavedEvaluationError(f"WORKER_ZERO_AUTHORIZATION_REQUIRED:{key}")
    if (spec.get("candidate_model_load_authorized") is not False
            or type(spec.get("evaluation_truth_decode_authorized")) is not int
            or spec["evaluation_truth_decode_authorized"] != 1
            or spec.get("automatic_retry") is not False
            or spec.get("safety") != common.SAFETY):
        raise common.SavedEvaluationError("WORKER_AUTHORIZATION_SCOPE_MISMATCH")
    output = common.plain_path(binding["output_root"], exists=False)
    start_path = common.plain_path(binding["start_receipt_path"])
    if start_path.parent != output or start_path.name != "EVALUATION_START_RECEIPT.json":
        raise common.SavedEvaluationError("START_RECEIPT_OUTPUT_ROOT_MISMATCH")
    if not output.is_dir() or {p.name for p in output.iterdir()} != {start_path.name}:
        raise common.SavedEvaluationError("WORKER_OUTPUT_NOT_EMPTY_NO_REENTRY")
    start = common.json_object(common.checked_read({"path": str(start_path),
        "sha256": payload["start_receipt_sha256"]}, name="start_receipt"), name="start_receipt")
    expected = {"status": "RUN_STARTED_DURABLE", "execution_id": binding["execution_id"], "candidate_execution_id": binding["candidate_execution_id"],
        "route_id": binding["route_id"], "run_spec_sha256": binding["run_spec_sha256"],
        "input_binding_sha256": payload["input_binding_sha256"],
        "source_code_sha256": binding["code_sha256"], "real_fit_budget_debit": 0,
        "planned_real_fit_count": 0, **common.ZERO_COUNTS}
    for key, value in expected.items():
        if common.canonical_bytes(start.get(key)) != common.canonical_bytes(value):
            raise common.SavedEvaluationError(f"WORKER_DURABLE_START_IDENTITY_MISMATCH:{key}")
    if not isinstance(start.get("start_event_sha256"), str) or len(start["start_event_sha256"]) != 64:
        raise common.SavedEvaluationError("WORKER_DURABLE_START_EVENT_ID_MISSING")
    return binding, output


def run_saved_evaluation(payload: Mapping[str, Any]) -> dict[str, Any]:
    common = _common(payload)
    binding, output = _start_and_binding(common, payload)
    execution_id = binding["execution_id"]
    counts = {**common.ZERO_COUNTS, "evaluation_truth_artifact_read_attempts": 0,
        "evaluation_truth_artifact_reads_completed": 0, "evaluation_truth_decode_attempts": 0,
        "evaluation_truth_decodes_completed": 0, "control_label_artifacts_decoded": 0,
        "evaluation_label_values_decoded": False}
    status = {"schema": "F5_RFF_SAVED_EVAL_WORKER_STATUS_V1", "execution_id": execution_id,
        "candidate_execution_id": binding["candidate_execution_id"], "route_id": binding["route_id"],
        "safety": dict(common.SAFETY), "automatic_retry": False,
        "run_spec_sha256": binding["run_spec_sha256"], "source_code_sha256": binding["code_sha256"],
        "input_binding_sha256": payload["input_binding_sha256"],
        "start_receipt_sha256": payload["start_receipt_sha256"], "metrics_computed": False,
        "native_runtime_check_attempts": 0, "native_runtime_checks_completed": 0,
        "native_runtime_observation": None}
    try:
        common.verify_sources(binding)
        if set(binding["input_files"]) != common.INPUT_NAMES:
            raise common.SavedEvaluationError("SAVED_EVALUATION_INPUT_SET_MISMATCH")
        status["native_runtime_check_attempts"] = 1
        status["native_runtime_observation"] = _validate_child_runtime(common, binding, payload)
        status["native_runtime_checks_completed"] = 1
        frames, score_aware, accepted = _load_evaluators(common, binding)
        metadata = {name: common.json_object(common.checked_read(record, name=name), name=name)
                    for name, record in binding["metadata_files"].items()
                    if name in ("experiment_contract", "prediction_seal")}
        seal = metadata["prediction_seal"]
        common.validate_seal(seal, binding["evaluation_contract"], binding["candidate_execution_id"])
        for name in ("candidate_scores", "candidate_top3"):
            if seal.get(name + "_sha256") != binding["input_files"][name]["sha256"]:
                raise common.SavedEvaluationError(f"PREDICTION_SEAL_ARTIFACT_MISMATCH:{name}")
        # All saved non-truth bytes are checked before any label decode. A bad
        # candidate CSV must fail without even opening the evaluation truth.
        snapshots = {name: common.checked_read(record, name=name)
                     for name, record in binding["input_files"].items() if name != "eval_truth"}
        scores = _read_csv(snapshots["candidate_scores"], name="candidate_scores", columns=frames.SCORE_COLUMNS)
        selected = _read_csv(snapshots["candidate_top3"], name="candidate_top3", columns=frames.TOP3_COLUMNS)
        calendar = _read_csv(snapshots["eval_calendar"], name="eval_calendar", columns=["session_id", "market_date"])
        frames._require_schema(scores, frames.SCORE_COLUMNS, name="candidate_scores")
        frames._require_keys(scores, name="candidate_scores")
        frames._candidate_score_domain(scores, name="candidate_scores")
        frames._require_schema(selected, frames.TOP3_COLUMNS, name="candidate_top3")
        frames._require_keys(selected, name="candidate_top3")
        frames._check_saved_candidate_top3(selected, scores, slots=binding["evaluation_contract"]["selection_slots"])
        counts["evaluation_truth_artifact_read_attempts"] = 1
        truth_raw = common.checked_read(binding["input_files"]["eval_truth"], name="eval_truth")
        counts["evaluation_truth_artifact_reads_completed"] = 1
        common.write_json_exclusive(output / "EVALUATION_TRUTH_READ_START.json", {
            "schema": "F5_RFF_SAVED_EVAL_TRUTH_READ_START_V1", "execution_id": execution_id,
            "candidate_execution_id": binding["candidate_execution_id"], "route_id": binding["route_id"],
            "label_values_decode_started": True, "evaluation_truth_decode_attempts": 1,
            "evaluation_truth_decodes_completed": None,
            "completion_status": "NOT_YET_OBSERVED", "truth_sha256": binding["input_files"]["eval_truth"]["sha256"],
            "run_spec_sha256": binding["run_spec_sha256"], "source_code_sha256": binding["code_sha256"],
            "input_binding_sha256": payload["input_binding_sha256"],
            "start_receipt_sha256": payload["start_receipt_sha256"],
            "prediction_seal_sha256": binding["metadata_files"]["prediction_seal"]["sha256"],
            **common.ZERO_COUNTS, "safety": dict(common.SAFETY)})
        counts["evaluation_truth_decode_attempts"] = 1
        truth = _read_csv(truth_raw, name="eval_truth", columns=frames.TRUTH_COLUMNS)
        del truth_raw
        counts["evaluation_truth_decodes_completed"] = 1
        counts["evaluation_label_values_decoded"] = True
        controls = {}
        for arm in common.CONTROLS:
            controls[arm] = {"scores": _read_csv(snapshots[f"{arm}_scores"], name=f"{arm}_scores",
                columns=frames.TRUTH_COLUMNS + ["probability"])}
            counts["control_label_artifacts_decoded"] += 1
            controls[arm]["top3"] = _read_csv(snapshots[f"{arm}_top3"], name=f"{arm}_top3",
                columns=["code", "session_id", "rank", "probability"])
        artifact_sha = {name: record["sha256"] for name, record in binding["input_files"].items()}
        metrics = frames.evaluate_frames(candidate_scores=scores, candidate_top3=selected,
            truth=truth, calendar=calendar, controls=controls, score_aware=score_aware,
            accepted_worker=accepted, evaluation_contract=binding["evaluation_contract"],
            experiment_contract=metadata["experiment_contract"], execution_id=execution_id,
            artifact_sha256=artifact_sha)
        status["metrics_computed"] = True
        metrics.update(counts)
        metrics.update({"candidate_execution_id": binding["candidate_execution_id"],
            "evaluation_truth_decodes": counts["evaluation_truth_decode_attempts"],
            "prediction_seal_sha256": binding["metadata_files"]["prediction_seal"]["sha256"],
            "accepted_worker_sha256": common.PINS["accepted_worker"],
            "run_spec_sha256": binding["run_spec_sha256"],
            "input_binding_sha256": payload["input_binding_sha256"],
            "start_receipt_sha256": payload["start_receipt_sha256"],
            "source_code_sha256": binding["code_sha256"], "metrics_computed": True,
            "native_runtime_check_attempts": status["native_runtime_check_attempts"],
            "native_runtime_checks_completed": status["native_runtime_checks_completed"],
            "native_runtime_observation": status["native_runtime_observation"]})
        # Recheck sources/metadata only. Evaluation inputs are consumed from the
        # exact verified snapshots above; no second truth read is performed.
        common.verify_sources(binding)
        metrics_sha = common.write_json_exclusive(output / "METRICS.json", metrics)
        status["metrics_sha256"] = metrics_sha
        result = {"schema": "F5_RFF_SAVED_EVAL_RESULT_V1", "status": "COMPLETED",
            **status, **counts, "metrics_sha256": metrics_sha,
            "input_sha256": artifact_sha, "source_code_sha256": binding["code_sha256"],
            "prediction_seal_sha256": binding["metadata_files"]["prediction_seal"]["sha256"],
            "evidence_ceiling": "DIRECTION_ONLY", "historical_candidate_mutation": False}
        result["schema"] = "F5_RFF_SAVED_EVAL_RESULT_V1"
        result_sha = common.write_json_exclusive(output / "EVALUATION_RESULT_RECEIPT.json", result)
        common.write_json_exclusive(output / "EVALUATION_WORKER_STATUS.json", {
            **status, **counts, "status": "COMPLETED", "metrics_sha256": metrics_sha,
            "result_receipt_sha256": result_sha})
        return result
    except BaseException as exc:
        common.write_json_exclusive(output / "EVALUATION_WORKER_STATUS.json", {
            **status, **counts, "status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)})
        common.write_json_exclusive(output / "EVALUATION_FAILURE_EVIDENCE.json", {
            **status, "schema": "F5_RFF_SAVED_EVAL_FAILURE_V1", "status": "FAILED",
            "stage": "SAVED_EVALUATION_WORKER", "error_type": type(exc).__name__,
            "error": str(exc), "traceback": traceback.format_exc(), **counts,
            "automatic_retry": False, "safety": dict(common.SAFETY)})
        raise
