"""L04 route-specific, read-only evaluation completion evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping


class EvaluationCompletionError(RuntimeError):
    pass


ARTIFACT_NAMES = {
    "start_receipt": "CANDIDATE_START_RECEIPT.json",
    "run_receipt": "CANDIDATE_RUN_RECEIPT.json",
    "resource_trace": "CANDIDATE_RESOURCE_TRACE.json",
    "fit_receipt": "CANDIDATE_FIT_RECEIPT.json",
    "optimizer_result": "OPTIMIZER_RESULT.json",
    "prediction_seal": "PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json",
    "truth_read_start": "EVALUATION_TRUTH_READ_START.json",
    "metrics": "METRICS.json",
    "result_receipt": "CANDIDATE_RESULT_RECEIPT.json",
    "worker_status": "CANDIDATE_WORKER_STATUS.json",
    "model": "CANDIDATE_MODEL.txt",
    "scores": "CANDIDATE_SCORES.csv.gz",
    "raw_scores": "CANDIDATE_RAW_SCORES.npy",
    "top3": "CANDIDATE_TOP3.csv.gz",
    "terminal_receipt": "CANDIDATE_TERMINAL_RECEIPT.json",
    "input_hash_receipt": "CANDIDATE_INPUT_HASH_RECEIPT.json",
}

REQUIRED_ARTIFACTS = tuple(ARTIFACT_NAMES)
PENDING_EVALUATION_STATUS = "CANDIDATE_FIT_PREDICTIONS_SEALED_EVALUATION_PENDING"
COMPLETED_WORKER_STATUS = "CANDIDATE_FIT_PREDICT_AND_FULL2024_EVALUATION_COMPLETED"
FROZEN_CONTRACT_PATH = Path("/Users/lexi/Desktop/学习/因子工厂/research/hk_burst_f5/batches/full64_rff_logistic_r1_20260927/contracts/EXPERIMENT_CONTRACT.json")
FROZEN_CONTRACT_SHA256 = "e6c1509955730a032d183563d6ffcf2501a587dd5734426f35fc59b222491135"
_BOUND_VALIDATORS: dict[tuple[str, str], ModuleType] = {}
_BOUND_ADAPTERS: dict[tuple[str, str], ModuleType] = {}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationCompletionError(f"L04_JSON_UNREADABLE:{label}") from exc
    if not isinstance(value, dict):
        raise EvaluationCompletionError(f"L04_JSON_OBJECT_REQUIRED:{label}")
    return value


def _require_file(path: Path, *, root: Path, label: str) -> Path:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise EvaluationCompletionError(f"L04_ARTIFACT_MISSING_OR_SYMLINK:{label}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise EvaluationCompletionError(f"L04_ARTIFACT_OUTSIDE_EXECUTION_ROOT:{label}") from exc
    return resolved


def _source_manifest_sha(binding: Mapping[str, Any]) -> str:
    files = binding.get("code_files")
    if not isinstance(files, Mapping) or not files:
        raise EvaluationCompletionError("L04_SOURCE_MANIFEST_MISSING")
    canonical = _canonical(dict(files))
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != binding.get("code_sha256"):
        raise EvaluationCompletionError("L04_SOURCE_MANIFEST_IDENTITY_MISMATCH")
    for name, entry in files.items():
        if not isinstance(entry, Mapping):
            raise EvaluationCompletionError(f"L04_SOURCE_BINDING_INVALID:{name}")
        path = Path(str(entry.get("path", "")))
        if path.is_symlink() or not path.is_file() or sha256_file(path) != entry.get("sha256"):
            raise EvaluationCompletionError(f"L04_SOURCE_SHA_MISMATCH:{name}")
    return digest


def _fields(document: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    """Counters are integers, not bool/float values that merely compare equal."""
    for key, value in expected.items():
        actual = document.get(key)
        if actual != value or (isinstance(value, (bool, int)) and type(actual) is not type(value)):
            raise EvaluationCompletionError(f"L04_FIELD_MISMATCH:{label}:{key}")


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise EvaluationCompletionError(f"L04_SHA256_INVALID:{label}")
    return value


def _bound_helper(binding: Mapping[str, Any], name: str) -> tuple[Path, bytes, str]:
    helpers = binding.get("official_helpers")
    item = helpers.get(name) if isinstance(helpers, Mapping) else None
    if not isinstance(item, Mapping):
        raise EvaluationCompletionError(f"L04_OFFICIAL_HELPER_BINDING_MISSING:{name}")
    raw_path = item.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise EvaluationCompletionError(f"L04_OFFICIAL_HELPER_PATH_MISSING:{name}")
    path = Path(raw_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise EvaluationCompletionError(f"L04_OFFICIAL_HELPER_PATH_INVALID:{name}")
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if item.get("sha256") != actual:
        raise EvaluationCompletionError(f"L04_OFFICIAL_HELPER_SHA_MISMATCH:{name}")
    return path.resolve(strict=True), raw, actual


def _exec_bound_source(path: Path, raw: bytes, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise EvaluationCompletionError(f"L04_OFFICIAL_HELPER_LOAD_FAILED:{path.name}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    # Compile the already-checked source bytes. SourceFileLoader.exec_module can
    # otherwise accept a timestamp/size-matched stale .pyc.
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    except BaseException:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        raise
    return module


def _load_bound_validator(binding: Mapping[str, Any]) -> ModuleType:
    path, raw, digest = _bound_helper(binding, "validator")
    key = (str(path), digest)
    cached = _BOUND_VALIDATORS.get(key)
    if cached is not None:
        return cached
    builder_path, builder_raw, builder_digest = _bound_helper(binding, "builder")
    validator = _exec_bound_source(path, raw, f"f5_rff_original_validator_{digest[:12]}")
    if (Path(validator.BUILDER_PATH).resolve() != builder_path
            or validator.EXPECTED_BUILDER_SHA256 != builder_digest):
        raise EvaluationCompletionError("L04_OFFICIAL_VALIDATOR_BUILDER_BINDING_MISMATCH")
    # Use the bound builder source bytes for the validator's canonical event
    # hashing and suffix checks. The validator function itself stays original.
    validator.OFFICIAL = _exec_bound_source(builder_path, builder_raw, f"f5_rff_original_builder_{builder_digest[:12]}")
    _BOUND_VALIDATORS[key] = validator
    return validator


def _load_bound_adapter(binding: Mapping[str, Any]) -> ModuleType:
    path, raw, digest = _bound_helper(binding, "registry_adapter")
    key = (str(path), digest)
    cached = _BOUND_ADAPTERS.get(key)
    if cached is not None:
        return cached
    guard_path, guard_raw, guard_digest = _bound_helper(binding, "execution_guard")
    guard = _exec_bound_source(guard_path, guard_raw, f"f5_rff_original_guard_{guard_digest[:12]}")
    prior_guard = sys.modules.get("execution_guard_core")
    sys.modules["execution_guard_core"] = guard
    inserted = str(path.parent) not in sys.path
    if inserted:
        sys.path.insert(0, str(path.parent))
    try:
        adapter = _exec_bound_source(path, raw, f"f5_rff_original_adapter_{digest[:12]}")
    finally:
        if inserted:
            try:
                sys.path.remove(str(path.parent))
            except ValueError:
                pass
        if prior_guard is None:
            sys.modules.pop("execution_guard_core", None)
        else:
            sys.modules["execution_guard_core"] = prior_guard
    _BOUND_ADAPTERS[key] = adapter
    return adapter


def _validated_registry_snapshot(binding: Mapping[str, Any]) -> dict[str, Any]:
    raw_registry = Path(str(binding.get("official_registry_path", "")))
    if raw_registry.is_symlink() or not raw_registry.is_absolute() or not raw_registry.is_file():
        raise EvaluationCompletionError("L04_OFFICIAL_REGISTRY_PATH_INVALID")
    registry_path = raw_registry.resolve(strict=True)
    validator = _load_bound_validator(binding)
    adapter_module = _load_bound_adapter(binding)
    adapter = object.__new__(adapter_module.OfficialRegistryAdapter)
    adapter.registry_path = registry_path
    adapter.lock_path = registry_path.with_name(f".{registry_path.name}.lock")
    adapter.validator = validator
    try:
        # Reuse the accepted adapter's real lock and _read_validated seam. The
        # second call captures the original validator's returned snapshot from
        # the exact same bytes while the lock is still held.
        with adapter._locked():
            raw, rows = adapter._read_validated()
            result = validator.validate_registry_bytes(raw, source="rff-completion-snapshot")
    except Exception as exc:
        raise EvaluationCompletionError("L04_OFFICIAL_REGISTRY_VALIDATION_FAILED") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if (not isinstance(result, Mapping) or result.get("APPEND_COMPATIBILITY") != "PASS"
            or result.get("registry_sha256") != digest or result.get("registry_bytes") != len(raw)
            or result.get("events") != len(rows)):
        raise EvaluationCompletionError("L04_ORIGINAL_VALIDATOR_SNAPSHOT_MISMATCH")
    validator_path, _, validator_sha = _bound_helper(binding, "validator")
    adapter_path, _, adapter_sha = _bound_helper(binding, "registry_adapter")
    return {
        "path": str(registry_path),
        "sha256": digest,
        "bytes": len(raw),
        "events": rows,
        "validation": dict(result),
        "validator_path": str(validator_path),
        "validator_sha256": validator_sha,
        "adapter_path": str(adapter_path),
        "adapter_sha256": adapter_sha,
    }


def _execution_events(snapshot: Mapping[str, Any], execution_id: str) -> list[dict[str, Any]]:
    events = snapshot.get("events")
    if not isinstance(events, list):
        raise EvaluationCompletionError("L04_VALIDATED_REGISTRY_EVENTS_MISSING")
    return [dict(row) for row in events
            if isinstance(row, Mapping) and row.get("execution_id") == execution_id]


def _input_identities(binding: Mapping[str, Any]) -> dict[str, str]:
    inputs = binding.get("input_files")
    if not isinstance(inputs, Mapping) or not inputs:
        raise EvaluationCompletionError("L04_FROZEN_INPUT_BINDINGS_MISSING")
    result = {}
    for name, item in inputs.items():
        if not isinstance(name, str) or not name or not isinstance(item, Mapping):
            raise EvaluationCompletionError("L04_FROZEN_INPUT_BINDING_INVALID")
        result[name] = _digest(item.get("sha256"), name)
    # Compare the original worker's observations; do not reopen inputs/truth.
    return result


def _assert_completed(
    *, spec: Mapping[str, Any], binding: Mapping[str, Any], artifacts: Mapping[str, Mapping[str, Any]],
    run_summary: Mapping[str, Any], registry_snapshot: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fit = _json(Path(artifacts["fit_receipt"]["path"]), "fit_receipt")
    optimizer = _json(Path(artifacts["optimizer_result"]["path"]), "optimizer_result")
    seal = _json(Path(artifacts["prediction_seal"]["path"]), "prediction_seal")
    truth_read = _json(Path(artifacts["truth_read_start"]["path"]), "truth_read_start")
    metrics = _json(Path(artifacts["metrics"]["path"]), "metrics")
    result = _json(Path(artifacts["result_receipt"]["path"]), "result_receipt")
    run = _json(Path(artifacts["run_receipt"]["path"]), "run_receipt")
    terminal_receipt = _json(Path(artifacts["terminal_receipt"]["path"]), "terminal_receipt")
    status = _json(Path(artifacts["worker_status"]["path"]), "worker_status")

    route_id, execution_id = binding.get("route_id"), binding.get("execution_id")
    if not route_id or not execution_id or run_summary.get("execution_id") != execution_id:
        raise EvaluationCompletionError("L04_RUN_SUMMARY_EXECUTION_MISMATCH")
    for label, document in (("fit", fit), ("optimizer", optimizer), ("seal", seal), ("truth", truth_read), ("metrics", metrics), ("result", result), ("run", run), ("terminal", terminal_receipt), ("worker", status)):
        if document.get("execution_id") != execution_id:
            raise EvaluationCompletionError(f"L04_CROSS_EXECUTION_ARTIFACT:{label}")
    if spec.get("route_id") != route_id:
        raise EvaluationCompletionError("L04_SPEC_ROUTE_MISMATCH")
    if spec.get("execution_id") != execution_id:
        raise EvaluationCompletionError("L04_SPEC_EXECUTION_MISMATCH")
    if (spec.get("experiment_contract_sha256") != FROZEN_CONTRACT_SHA256
            or FROZEN_CONTRACT_PATH.is_symlink() or not FROZEN_CONTRACT_PATH.is_file()
            or sha256_file(FROZEN_CONTRACT_PATH) != FROZEN_CONTRACT_SHA256
            or binding.get("experiment_contract_sha256") != FROZEN_CONTRACT_SHA256):
        raise EvaluationCompletionError("L04_FROZEN_CONTRACT_IDENTITY_MISMATCH")
    if binding.get("experiment_contract_path") != str(FROZEN_CONTRACT_PATH.resolve(strict=True)):
        raise EvaluationCompletionError("L04_FROZEN_CONTRACT_PATH_MISMATCH")
    events = _execution_events(registry_snapshot, str(execution_id))
    start_receipt = _json(Path(artifacts["start_receipt"]["path"]), "start_receipt")
    resource_trace = _json(Path(artifacts["resource_trace"]["path"]), "resource_trace")
    input_hash_receipt = _json(Path(artifacts["input_hash_receipt"]["path"]), "input_hash_receipt")
    for label, document in (("start", start_receipt), ("input_hash", input_hash_receipt)):
        if document.get("execution_id") != execution_id or document.get("route_id") != route_id:
            raise EvaluationCompletionError(f"L04_ROUTE_EXECUTION_IDENTITY_MISMATCH:{label}")
    contract_sha = sha256_file(Path(binding["run_spec_path"]))
    input_sha = sha256_file(Path(binding["input_binding_path"]))
    if binding.get("run_spec_sha256") != contract_sha:
        raise EvaluationCompletionError("L04_BOUND_RUN_SPEC_SHA_MISMATCH")
    _digest(spec.get("model_definition_sha256"), "model_definition_sha256")
    evaluation_definition = spec.get("evaluation_definition")
    if not isinstance(evaluation_definition, Mapping) or spec.get("evaluation_definition_sha256") != hashlib.sha256(_canonical(dict(evaluation_definition))).hexdigest():
        raise EvaluationCompletionError("L04_BOUND_EVALUATION_DEFINITION_SHA_MISMATCH")
    for label, document in (("fit", fit), ("optimizer", optimizer), ("seal", seal), ("truth", truth_read),
                            ("metrics", metrics), ("result", result), ("run", run), ("terminal", terminal_receipt), ("worker", status)):
        _fields(document, {"route_id": route_id, "execution_id": execution_id}, label)
    _fields(start_receipt, {"run_spec_sha256": contract_sha, "input_binding_sha256": input_sha}, "start")
    _fields(terminal_receipt, {"terminal_status": "COMPLETED"}, "terminal")
    expected_inputs = _input_identities(binding)
    if input_hash_receipt.get("input_sha256") != expected_inputs or result.get("input_sha256") != expected_inputs:
        raise EvaluationCompletionError("L04_FROZEN_INPUT_IDENTITY_MISMATCH")
    actual_budget = {
        "fit_calls": 1, "fit_call_entered": True, "real_fit_returned_count": 1,
        "predict_calls": 1, "control_fit_calls": 0, "control_predict_calls": 0,
        "calibrator_fit_calls": 0, "evaluation_truth_decodes": 1,
        "evaluation_label_values_decoded": True,
    }
    for label, document in (("result", result), ("metrics", metrics), ("worker", status)):
        _fields(document, actual_budget, label)
    _fields(fit, {"fit_calls": 1, "fit_call_entered": True, "real_fit_returned_count": 1}, "fit")
    _fields(seal, {"predict_calls": 1, "scoreable_rows": 120084, "grid_rows": 169986, "evaluation_sessions": 246}, "seal")
    _fields(metrics, {"grid_rows": 169986, "scoreable_rows": 120084, "sessions": 246,
                      "selection_slots": 738, "truth_positive_denominator": 126}, "metrics")
    _fields(run_summary, {"terminal_status": "COMPLETED", "real_fit_budget_debit": 1,
                          "fit_call_entered": True, "real_fit_returned_count": 1, "predict_calls": 1}, "summary")
    for label, document in (("result", result), ("metrics", metrics)):
        for field, artifact in (("fit_receipt_sha256", "fit_receipt"), ("optimizer_result_sha256", "optimizer_result"),
                                ("prediction_seal_sha256", "prediction_seal")):
            if document.get(field) != artifacts[artifact]["sha256"]:
                raise EvaluationCompletionError(f"L04_PRODUCER_LINK_MISMATCH:{label}:{field}")
    if input_hash_receipt.get("evaluation_label_values_decoded") is not False:
        raise EvaluationCompletionError("L04_INPUT_READ_RECEIPT_CROSSED_TRUTH_BOUNDARY")
    if fit.get("status") != "FIT_COMPLETED" or fit.get("fit_call_entered") is not True or fit.get("real_fit_returned_count") != 1 or fit.get("fit_calls") != 1:
        raise EvaluationCompletionError("L04_FIT_NOT_COMPLETED_EXACTLY_ONCE")
    if optimizer.get("success") is not True or optimizer.get("status") != 0:
        raise EvaluationCompletionError("L04_OPTIMIZER_NOT_CONVERGED")
    if seal.get("status") != "PREDICTION_FROZEN_BEFORE_EVALUATION_TRUTH_READ" or seal.get("evaluation_label_values_decoded") is not False:
        raise EvaluationCompletionError("L04_PREDICTION_SEAL_NOT_PRETRUTH")
    if seal.get("predict_calls") != 1 or seal.get("scoreable_rows") != 120084 or seal.get("grid_rows") != 169986 or seal.get("evaluation_sessions") != 246:
        raise EvaluationCompletionError("L04_PREDICTION_BUDGET_OR_SHAPE_MISMATCH")
    if truth_read.get("first_eval_truth_decode_after_prediction_seal") is not True or truth_read.get("prediction_seal_sha256") != artifacts["prediction_seal"]["sha256"]:
        raise EvaluationCompletionError("L04_TRUTH_READ_NOT_BOUND_AFTER_SEAL")
    for key, expected in (
        ("candidate_scores_sha256", artifacts["scores"]["sha256"]),
        ("candidate_raw_scores_sha256", artifacts["raw_scores"]["sha256"]),
        ("candidate_top3_sha256", artifacts["top3"]["sha256"]),
    ):
        if seal.get(key) != expected or truth_read.get(key) != expected:
            raise EvaluationCompletionError(f"L04_PREDICTION_ARTIFACT_LINK_MISMATCH:{key}")
    if metrics.get("status") != "EXPOSED_RETROSPECTIVE_DEVELOPMENT_EVALUATION" or metrics.get("selection_slots") != 738 or metrics.get("truth_positive_denominator") != 126:
        raise EvaluationCompletionError("L04_EVALUATION_DEFINITION_OR_DENOMINATOR_MISMATCH")
    if result.get("status") != COMPLETED_WORKER_STATUS or status.get("status") != COMPLETED_WORKER_STATUS:
        raise EvaluationCompletionError("L04_WORKER_EVALUATION_NOT_COMPLETED")
    if result.get("fit_calls") != 1 or result.get("fit_call_entered") is not True or result.get("real_fit_returned_count") != 1 or result.get("predict_calls") != 1 or result.get("evaluation_label_values_decoded") is not True:
        raise EvaluationCompletionError("L04_RESULT_BUDGET_OR_TRUTH_MISMATCH")
    if any(result.get(key) != 0 for key in ("control_fit_calls", "control_predict_calls", "calibrator_fit_calls")):
        raise EvaluationCompletionError("L04_CONTROL_OR_CALIBRATOR_BUDGET_MISMATCH")
    if run.get("terminal_status") != "COMPLETED" or run.get("evaluation_label_values_decoded") is not True:
        raise EvaluationCompletionError("L04_OWNER_RUN_NOT_COMPLETED")
    if run.get("route_id") != route_id or run.get("run_spec_sha256") != sha256_file(Path(binding["run_spec_path"])) or run.get("input_binding_sha256") != sha256_file(Path(binding["input_binding_path"])):
        raise EvaluationCompletionError("L04_OWNER_RUN_CONTRACT_IDENTITY_MISMATCH")
    monitor = run.get("resource_monitor")
    resource_caps = binding.get("resources")
    if not isinstance(monitor, Mapping) or not isinstance(resource_caps, Mapping):
        raise EvaluationCompletionError("L04_RESOURCE_MONITOR_OR_CAPS_MISSING")
    # Fixed limits come from the unchanged EXPERIMENT_CONTRACT in this batch.
    _fields(resource_caps, {"cpu_threads": 4, "aggregate_process_tree_rss_bytes_max": 3221225472,
                           "wall_seconds_max": 1800}, "resource_caps")
    _fields(monitor, {"worker_exitcode": 0, "threads": 4}, "resource_monitor")
    elapsed_value = monitor.get("elapsed_seconds")
    rss_value = monitor.get("peak_aggregate_tree_rss_bytes")
    if (type(elapsed_value) not in (int, float) or not math.isfinite(elapsed_value) or elapsed_value < 0
            or type(rss_value) is not int or rss_value < 0):
        raise EvaluationCompletionError("L04_RESOURCE_VALUE_UNKNOWN_OR_INVALID")
    try:
        elapsed = float(monitor["elapsed_seconds"])
        sampled_rss = int(monitor["peak_aggregate_tree_rss_bytes"])
        wall_cap = float(resource_caps["wall_seconds_max"])
        rss_cap = int(resource_caps["aggregate_process_tree_rss_bytes_max"])
        cpu_threads = int(resource_caps["cpu_threads"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise EvaluationCompletionError("L04_RESOURCE_MONITOR_SCHEMA_INVALID") from exc
    if (
        monitor.get("worker_exitcode") != 0
        or monitor.get("terminal_reason") is not None
        or monitor.get("threads") != cpu_threads
        or monitor.get("wall_seconds_max") != wall_cap
        or monitor.get("aggregate_rss_bytes_max") != rss_cap
        or elapsed > wall_cap
        or sampled_rss > rss_cap
        or monitor.get("hard_peak_memory_guarantee") is not False
    ):
        raise EvaluationCompletionError("L04_RESOURCE_CAP_OR_WORKER_COMPLETION_MISMATCH")
    _fields(resource_trace, {
        "schema": "F5_META2023_RESOURCE_TRACE_V1",
        "worker_exitcode": 0,
        "terminal_reason": None,
        "threads": cpu_threads,
        "wall_seconds_max": wall_cap,
        "aggregate_rss_bytes_max": rss_cap,
        "hard_peak_memory_guarantee": False,
    }, "resource_trace")
    trace_elapsed = resource_trace.get("elapsed_seconds")
    trace_peak = resource_trace.get("peak_aggregate_tree_rss_bytes")
    if (type(trace_elapsed) not in (int, float) or not math.isfinite(trace_elapsed) or trace_elapsed < 0
            or type(trace_peak) is not int or trace_peak < 0
            or trace_elapsed > wall_cap or trace_peak > rss_cap):
        raise EvaluationCompletionError("L04_RESOURCE_TRACE_VALUE_OR_CAP_INVALID")
    post_trace = monitor.get("post_trace_fsync_terminal_check")
    final_post_trace = monitor.get("final_post_fsync_check")
    for label, check, after_key in (
        ("post_trace", post_trace, "after_trace_fsync"),
        ("final_post_trace", final_post_trace, "after_final_trace_fsync"),
    ):
        if not isinstance(check, Mapping) or check.get(after_key) is not True:
            raise EvaluationCompletionError(f"L04_RESOURCE_POST_FSYNC_CHECK_MISSING:{label}")
        check_elapsed = check.get("elapsed_seconds")
        check_rss = check.get("aggregate_tree_rss_bytes")
        if (type(check_elapsed) not in (int, float) or not math.isfinite(check_elapsed) or check_elapsed < 0
                or type(check_rss) is not int or check_rss < 0
                or check_elapsed > wall_cap or check_rss > rss_cap):
            raise EvaluationCompletionError(f"L04_RESOURCE_POST_FSYNC_CAP_EXCEEDED:{label}")
    if result.get("route_id") != route_id or result.get("run_spec_sha256") != sha256_file(Path(binding["run_spec_path"])) or result.get("input_binding_sha256") != sha256_file(Path(binding["input_binding_path"])) or result.get("source_code_sha256") != binding.get("code_sha256"):
        raise EvaluationCompletionError("L04_RESULT_CONTRACT_OR_SOURCE_IDENTITY_MISMATCH")
    if result.get("metrics_sha256") != artifacts["metrics"]["sha256"] or result.get("candidate_model_sha256") != artifacts["model"]["sha256"] or result.get("candidate_scores_sha256") != artifacts["scores"]["sha256"] or result.get("candidate_raw_scores_sha256") != artifacts["raw_scores"]["sha256"] or result.get("candidate_top3_sha256") != artifacts["top3"]["sha256"]:
        raise EvaluationCompletionError("L04_RESULT_ARTIFACT_LINK_MISMATCH")
    if fit.get("model_sha256") != artifacts["model"]["sha256"] or fit.get("optimizer_result_sha256") != artifacts["optimizer_result"]["sha256"]:
        raise EvaluationCompletionError("L04_FIT_ARTIFACT_LINK_MISMATCH")
    if run_summary.get("terminal_status") != "COMPLETED" or run_summary.get("real_fit_budget_debit") != 1 or run_summary.get("fit_call_entered") is not True or run_summary.get("real_fit_returned_count") != 1 or run_summary.get("predict_calls") != 1:
        raise EvaluationCompletionError("L04_OWNER_SUMMARY_BUDGET_OR_TERMINAL_MISMATCH")
    if len(events) != 2 or [event.get("event_type") for event in events] != ["RUN_STARTED", "TERMINAL"]:
        raise EvaluationCompletionError("L04_OFFICIAL_LIFECYCLE_NOT_EXACTLY_ONE")
    start_event, terminal_event = events
    for event in events:
        route_fields = [event[key] for key in ("route_id", "experiment_id") if key in event]
        if not route_fields or any(value != route_id for value in route_fields) or event.get("execution_id") != execution_id:
            raise EvaluationCompletionError("L04_OFFICIAL_ROUTE_IDENTITY_MISMATCH")
        if event.get("contract_sha256") != sha256_file(Path(binding["run_spec_path"])) or event.get("input_binding_sha256") != sha256_file(Path(binding["input_binding_path"])):
            raise EvaluationCompletionError("L04_OFFICIAL_CONTRACT_IDENTITY_MISMATCH")
    if start_event.get("decision") != "RUNNING" or terminal_event.get("decision") != "COMPLETED":
        raise EvaluationCompletionError("L04_OFFICIAL_TERMINAL_NOT_SUCCESS")
    start_metrics = start_event.get("deterministic_metrics") or {}
    terminal_metrics = terminal_event.get("deterministic_metrics") or {}
    _fields(start_metrics, {"planned_real_fit_count": 1, "real_fit_budget_debit": 1}, "official_start")
    _fields(terminal_metrics, {"planned_real_fit_count": 1, "real_fit_budget_debit": 1,
                              "fit_call_entered": True, "real_fit_returned_count": 1, "predict_calls": 1,
                              "control_fit_calls": 0, "control_predict_calls": 0, "calibrator_fit_calls": 0}, "official_terminal")
    if (start_receipt.get("start_event_sha256") != start_event.get("event_sha256")
            or terminal_receipt.get("previous_event_sha256") != start_event.get("event_sha256")):
        raise EvaluationCompletionError("L04_START_TERMINAL_EVENT_LINK_MISMATCH")
    if start_metrics.get("planned_real_fit_count") != 1 or start_metrics.get("real_fit_budget_debit") != 1:
        raise EvaluationCompletionError("L04_OFFICIAL_START_FIT_RESERVATION_MISMATCH")
    if any(terminal_metrics.get(key) != value for key, value in {
        "planned_real_fit_count": 1,
        "real_fit_budget_debit": 1,
        "fit_call_entered": True,
        "real_fit_returned_count": 1,
        "predict_calls": 1,
        "control_fit_calls": 0,
        "control_predict_calls": 0,
        "calibrator_fit_calls": 0,
    }.items()):
        raise EvaluationCompletionError("L04_OFFICIAL_TERMINAL_BUDGET_MISMATCH")
    if terminal_event.get("truth_access") != "EVAL_LABELS_DECODED_AFTER_PREDICTION_SEAL" or terminal_event.get("sealed_status") != "EXPOSED_2024_POST_SEAL_EVALUATION":
        raise EvaluationCompletionError("L04_OFFICIAL_TERMINAL_TRUTH_OR_SEAL_STATUS_MISMATCH")
    if terminal_event.get("previous_event_sha256") != start_event.get("event_sha256"):
        raise EvaluationCompletionError("L04_OFFICIAL_EVENT_CHAIN_MISMATCH")
    event_sha = terminal_event.get("event_sha256")
    if not event_sha or event_sha != terminal_receipt.get("terminal_event_sha256") or event_sha != run_summary.get("terminal_event_sha256"):
        raise EvaluationCompletionError("L04_OFFICIAL_TERMINAL_SHA_MISMATCH")
    if run_summary.get("candidate_terminal_receipt_sha256") != artifacts["terminal_receipt"]["sha256"]:
        raise EvaluationCompletionError("L04_OWNER_TERMINAL_RECEIPT_SHA_MISMATCH")
    if run.get("resource_trace_sha256") != artifacts["resource_trace"]["sha256"]:
        raise EvaluationCompletionError("L04_RESOURCE_TRACE_NOT_BOUND_TO_RUN")
    if terminal_receipt.get("start_receipt_sha256") != artifacts["start_receipt"]["sha256"] or terminal_receipt.get("run_receipt_sha256") != artifacts["run_receipt"]["sha256"]:
        raise EvaluationCompletionError("L04_TERMINAL_RECEIPT_CHAIN_MISMATCH")
    registry_sha = registry_snapshot.get("sha256")
    validation = registry_snapshot.get("validation")
    if (not isinstance(validation, Mapping) or validation.get("APPEND_COMPATIBILITY") != "PASS"
            or validation.get("registry_sha256") != registry_sha
            or validation.get("registry_bytes") != registry_snapshot.get("bytes")
            or validation.get("events") != len(registry_snapshot.get("events", []))):
        raise EvaluationCompletionError("L04_ORIGINAL_VALIDATOR_SNAPSHOT_INVALID")
    if registry_sha != run_summary.get("official_registry_sha256_after_terminal"):
        raise EvaluationCompletionError("L04_OFFICIAL_REGISTRY_SNAPSHOT_MISMATCH")
    return fit, seal, metrics


def write_completion_receipt(
    *, spec_path: Path, binding_path: Path, run_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Create one exclusive L04 completion receipt after official terminalization."""
    spec_path, binding_path = Path(spec_path), Path(binding_path)
    if spec_path.is_symlink() or binding_path.is_symlink():
        raise EvaluationCompletionError("L04_BOUND_CONTRACT_SYMLINK_FORBIDDEN")
    spec_path, binding_path = spec_path.resolve(strict=True), binding_path.resolve(strict=True)
    spec = _json(spec_path, "run_spec")
    binding = _json(binding_path, "input_binding")
    raw_root = Path(str(binding.get("output_root", "")))
    if raw_root.is_symlink():
        raise EvaluationCompletionError("L04_EXECUTION_ROOT_SYMLINK_FORBIDDEN")
    root = raw_root.resolve(strict=True)
    if not root.is_dir():
        raise EvaluationCompletionError("L04_EXECUTION_ROOT_INVALID")
    if Path(str(binding.get("run_spec_path", ""))).resolve() != spec_path or Path(str(binding.get("input_binding_path", ""))).resolve() != binding_path:
        raise EvaluationCompletionError("L04_BOUND_CONTRACT_PATH_MISMATCH")
    code_sha = _source_manifest_sha(binding)
    binding_paths = {
        "start_receipt": binding.get("start_receipt_path"),
        "run_receipt": binding.get("run_receipt_path"),
        "resource_trace": binding.get("resource_trace_path"),
    }
    paths: dict[str, Path] = {}
    for key, filename in ARTIFACT_NAMES.items():
        candidate = Path(str(binding_paths[key])) if binding_paths.get(key) else root / filename
        paths[key] = _require_file(candidate, root=root, label=key)
    artifacts = {
        key: {"path": str(path), "sha256": sha256_file(path)}
        for key, path in paths.items()
    }
    registry_snapshot = _validated_registry_snapshot(binding)
    events = _execution_events(registry_snapshot, str(binding["execution_id"]))
    fit, seal, metrics = _assert_completed(
        spec=spec, binding=binding, artifacts=artifacts, run_summary=run_summary,
        registry_snapshot=registry_snapshot,
    )
    terminal_event = events[-1]
    eval_definition = spec.get("evaluation_definition")
    if not isinstance(eval_definition, Mapping):
        raise EvaluationCompletionError("L04_EVALUATION_DEFINITION_MISSING")
    terminal_receipt = {
        "schema": "F5_FULL64_RFF_LOGISTIC_EVALUATION_COMPLETION_V1",
        "status": "EVALUATION_COMPLETED",
        "route_id": binding["route_id"],
        "execution_id": binding["execution_id"],
        "contract_sha256": sha256_file(spec_path),
        "experiment_contract_path": str(FROZEN_CONTRACT_PATH.resolve(strict=True)),
        "experiment_contract_sha256": FROZEN_CONTRACT_SHA256,
        "input_binding_sha256": sha256_file(binding_path),
        "code_sha256": code_sha,
        "model_definition_sha256": spec["model_definition_sha256"],
        "budget": {
            "candidate_fit_calls": fit["fit_calls"],
            "candidate_fit_call_entered": fit["fit_call_entered"],
            "candidate_fit_returned_count": fit["real_fit_returned_count"],
            "candidate_predict_calls": seal["predict_calls"],
            "control_fit_calls": 0,
            "control_predict_calls": 0,
            "calibrator_fit_calls": 0,
            "evaluation_truth_decodes": _json(paths["result_receipt"], "result_receipt")["evaluation_truth_decodes"],
        },
        "evaluation_definition_sha256": hashlib.sha256(_canonical(dict(eval_definition))).hexdigest(),
        "evaluation_decision": metrics.get("development_gates", {}).get("development_decision"),
        "artifacts": artifacts,
        "official_terminal": {
            "registry_path": registry_snapshot["path"],
            "registry_sha256_after_terminal": registry_snapshot["sha256"],
            "registry_bytes": registry_snapshot["bytes"],
            "registry_event_count": registry_snapshot["validation"]["events"],
            "append_compatibility": registry_snapshot["validation"]["APPEND_COMPATIBILITY"],
            "validator_path": registry_snapshot["validator_path"],
            "validator_sha256": registry_snapshot["validator_sha256"],
            "adapter_path": registry_snapshot["adapter_path"],
            "adapter_sha256": registry_snapshot["adapter_sha256"],
            "start_event_sha256": events[0]["event_sha256"],
            "terminal_event_sha256": terminal_event["event_sha256"],
            "terminal_receipt_sha256": artifacts["terminal_receipt"]["sha256"],
        },
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    completion_path = root / "EVALUATION_COMPLETION_RECEIPT.json"
    raw = json.dumps(terminal_receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    try:
        with completion_path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise EvaluationCompletionError("L04_COMPLETION_RECEIPT_ALREADY_EXISTS_NO_REWRITE") from exc
    return read_completion_receipt(completion_path, spec_path=spec_path, binding_path=binding_path)


def read_completion_receipt(
    receipt_path: Path, *, spec_path: Path, binding_path: Path,
) -> dict[str, Any]:
    """Read-only verify the L04 receipt against its exact contracts and artifacts."""
    receipt_path, spec_path, binding_path = Path(receipt_path), Path(spec_path), Path(binding_path)
    if any(path.is_symlink() for path in (receipt_path, spec_path, binding_path)):
        raise EvaluationCompletionError("L04_READBACK_INPUT_SYMLINK_FORBIDDEN")
    receipt_path, spec_path, binding_path = receipt_path.resolve(strict=True), spec_path.resolve(strict=True), binding_path.resolve(strict=True)
    receipt = _json(receipt_path, "completion_receipt")
    spec = _json(spec_path, "run_spec")
    binding = _json(binding_path, "input_binding")
    if Path(str(binding.get("run_spec_path", ""))).resolve() != spec_path or Path(str(binding.get("input_binding_path", ""))).resolve() != binding_path:
        raise EvaluationCompletionError("L04_BOUND_CONTRACT_PATH_MISMATCH")
    raw_root = Path(str(binding.get("output_root", "")))
    if raw_root.is_symlink():
        raise EvaluationCompletionError("L04_EXECUTION_ROOT_SYMLINK_FORBIDDEN")
    root = raw_root.resolve(strict=True)
    try:
        receipt_path.relative_to(root)
    except ValueError as exc:
        raise EvaluationCompletionError("L04_COMPLETION_RECEIPT_OUTSIDE_EXECUTION_ROOT") from exc
    if receipt.get("schema") != "F5_FULL64_RFF_LOGISTIC_EVALUATION_COMPLETION_V1" or receipt.get("status") != "EVALUATION_COMPLETED":
        raise EvaluationCompletionError("L04_COMPLETION_SCHEMA_OR_STATUS_INVALID")
    identity = {
        "route_id": binding.get("route_id"),
        "execution_id": binding.get("execution_id"),
        "contract_sha256": sha256_file(spec_path),
        "input_binding_sha256": sha256_file(binding_path),
        "code_sha256": _source_manifest_sha(binding),
        "model_definition_sha256": spec.get("model_definition_sha256"),
        "experiment_contract_path": str(FROZEN_CONTRACT_PATH.resolve(strict=True)),
        "experiment_contract_sha256": FROZEN_CONTRACT_SHA256,
    }
    if (spec.get("experiment_contract_sha256") != FROZEN_CONTRACT_SHA256
            or binding.get("experiment_contract_path") != str(FROZEN_CONTRACT_PATH.resolve(strict=True))
            or binding.get("experiment_contract_sha256") != FROZEN_CONTRACT_SHA256
            or FROZEN_CONTRACT_PATH.is_symlink() or not FROZEN_CONTRACT_PATH.is_file()
            or sha256_file(FROZEN_CONTRACT_PATH) != FROZEN_CONTRACT_SHA256):
        raise EvaluationCompletionError("L04_FROZEN_CONTRACT_IDENTITY_MISMATCH")
    if any(receipt.get(key) != value for key, value in identity.items()):
        raise EvaluationCompletionError("L04_COMPLETION_IDENTITY_MISMATCH")
    eval_definition = spec.get("evaluation_definition")
    if not isinstance(eval_definition, Mapping) or receipt.get("evaluation_definition_sha256") != hashlib.sha256(_canonical(dict(eval_definition))).hexdigest():
        raise EvaluationCompletionError("L04_EVALUATION_DEFINITION_IDENTITY_MISMATCH")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(REQUIRED_ARTIFACTS):
        raise EvaluationCompletionError("L04_COMPLETION_ARTIFACT_SET_MISMATCH")
    actual: dict[str, dict[str, str]] = {}
    for key, filename in ARTIFACT_NAMES.items():
        record = artifacts.get(key)
        if not isinstance(record, Mapping):
            raise EvaluationCompletionError(f"L04_COMPLETION_ARTIFACT_RECORD_INVALID:{key}")
        binding_paths = {
            "start_receipt": binding.get("start_receipt_path"),
            "run_receipt": binding.get("run_receipt_path"),
            "resource_trace": binding.get("resource_trace_path"),
        }
        candidate = Path(str(binding_paths[key])) if binding_paths.get(key) else root / filename
        path = _require_file(candidate, root=root, label=key)
        if record.get("path") != str(path) or record.get("sha256") != sha256_file(path):
            raise EvaluationCompletionError(f"L04_COMPLETION_ARTIFACT_SHA_OR_PATH_MISMATCH:{key}")
        actual[key] = {"path": str(path), "sha256": sha256_file(path)}
    input_receipt = _json(Path(actual["input_hash_receipt"]["path"]), "input_hash_receipt")
    expected_inputs = {
        name: item.get("sha256")
        for name, item in binding.get("input_files", {}).items()
        if isinstance(item, Mapping)
    }
    if input_receipt.get("input_sha256") != expected_inputs or input_receipt.get("evaluation_label_values_decoded") is not False:
        raise EvaluationCompletionError("L04_FROZEN_INPUT_IDENTITY_OR_PRETRUTH_READBACK_MISMATCH")
    summary = {
        "execution_id": binding.get("execution_id"),
        "terminal_status": "COMPLETED",
        "real_fit_budget_debit": 1,
        "fit_call_entered": True,
        "real_fit_returned_count": 1,
        "predict_calls": 1,
        "candidate_terminal_receipt_sha256": actual["terminal_receipt"]["sha256"],
        "terminal_event_sha256": receipt.get("official_terminal", {}).get("terminal_event_sha256"),
        "official_registry_sha256_after_terminal": receipt.get("official_terminal", {}).get("registry_sha256_after_terminal"),
    }
    registry_snapshot = _validated_registry_snapshot(binding)
    events = _execution_events(registry_snapshot, str(binding["execution_id"]))
    fit, seal, metrics = _assert_completed(
        spec=spec, binding=binding, artifacts=actual, run_summary=summary,
        registry_snapshot=registry_snapshot,
    )
    event = events[-1]
    if receipt.get("official_terminal") != {
        "registry_path": registry_snapshot["path"],
        "registry_sha256_after_terminal": registry_snapshot["sha256"],
        "registry_bytes": registry_snapshot["bytes"],
        "registry_event_count": registry_snapshot["validation"]["events"],
        "append_compatibility": registry_snapshot["validation"]["APPEND_COMPATIBILITY"],
        "validator_path": registry_snapshot["validator_path"],
        "validator_sha256": registry_snapshot["validator_sha256"],
        "adapter_path": registry_snapshot["adapter_path"],
        "adapter_sha256": registry_snapshot["adapter_sha256"],
        "start_event_sha256": events[0]["event_sha256"],
        "terminal_event_sha256": event["event_sha256"],
        "terminal_receipt_sha256": actual["terminal_receipt"]["sha256"],
    }:
        raise EvaluationCompletionError("L04_OFFICIAL_TERMINAL_IDENTITY_MISMATCH")
    if receipt.get("evaluation_decision") != metrics.get("development_gates", {}).get("development_decision"):
        raise EvaluationCompletionError("L04_EVALUATION_DECISION_READBACK_MISMATCH")
    safety = receipt.get("safety")
    if not isinstance(safety, Mapping):
        raise EvaluationCompletionError("L04_SAFETY_SCHEMA_INVALID")
    _fields(safety, {"research_only": True, "production_allowed": False,
                     "buy_gate_updated": False, "orders_sent": False}, "completion_safety")
    budget = receipt.get("budget")
    if not isinstance(budget, Mapping) or budget != {
        "candidate_fit_calls": 1,
        "candidate_fit_call_entered": True,
        "candidate_fit_returned_count": 1,
        "candidate_predict_calls": 1,
        "control_fit_calls": 0,
        "control_predict_calls": 0,
        "calibrator_fit_calls": 0,
        "evaluation_truth_decodes": 1,
    }:
        raise EvaluationCompletionError("L04_BUDGET_SCHEMA_OR_VALUE_MISMATCH")
    _fields(budget, {"candidate_fit_calls": 1, "candidate_fit_call_entered": True,
                     "candidate_fit_returned_count": 1, "candidate_predict_calls": 1,
                     "control_fit_calls": 0, "control_predict_calls": 0,
                     "calibrator_fit_calls": 0, "evaluation_truth_decodes": 1}, "completion_budget")
    return receipt


def classify_failure(run_receipt: Mapping[str, Any] | None, worker_status: Mapping[str, Any] | None) -> dict[str, str]:
    """Separate entry/engineering, optimizer, evaluation, and model-decision states."""
    run_doc = dict(run_receipt or {})
    worker = dict(worker_status or {})
    fit_entered = worker.get("fit_call_entered", run_doc.get("fit_call_entered")) is True
    fit_returned = worker.get("real_fit_returned_count", run_doc.get("real_fit_returned_count"))
    errors = " ".join(str(doc.get(key) or "") for doc in (run_doc, worker)
                      for key in ("error_type", "error", "terminal_reason"))
    errors += " " + str((run_doc.get("resource_monitor") or {}).get("terminal_reason") or "")
    if any(token in errors.upper() for token in ("RESOURCE", "RSS", "WALL", "TIMEOUT", "SHA", "INPUT")):
        return {"failure_phase": "ENGINEERING", "failure_class": "RESOURCE_OR_INPUT_INTEGRITY_FAILURE"}
    if not run_doc or run_doc.get("terminal_status") not in {"COMPLETED", "CANNOT_CONFIRM"}:
        return {"failure_phase": "ENTRY", "failure_class": "ENTRY_OR_RELEASE_FAILURE"}
    if not fit_entered:
        error_type = str(run_doc.get("error_type") or worker.get("error_type") or "")
        if "RESOURCE" in error_type or "SHA" in error_type or "INPUT" in error_type:
            return {"failure_phase": "ENGINEERING", "failure_class": "RESOURCE_OR_INPUT_INTEGRITY_FAILURE"}
        return {"failure_phase": "ENTRY", "failure_class": "PREFIT_OR_WORKER_LAUNCH_FAILURE"}
    if fit_entered and fit_returned != 1:
        return {"failure_phase": "FIT", "failure_class": "MODEL_OPTIMIZER_FAILURE"}
    if fit_returned == 1 and not worker.get("evaluation_label_values_decoded", False):
        return {"failure_phase": "PREDICTION_OR_SEAL", "failure_class": "MODEL_PREDICTION_OR_SEAL_FAILURE"}
    if fit_returned == 1 and worker.get("evaluation_label_values_decoded") is True and run_doc.get("terminal_status") != "COMPLETED":
        return {"failure_phase": "EVALUATION", "failure_class": "EVALUATION_OR_TERMINAL_FAILURE"}
    if run_doc.get("terminal_status") == "COMPLETED":
        return {"failure_phase": "MODEL_DECISION", "failure_class": "EVALUATED_DEVELOPMENT_RESULT"}
    return {"failure_phase": "ENGINEERING", "failure_class": "ENGINEERING_FAILURE"}
