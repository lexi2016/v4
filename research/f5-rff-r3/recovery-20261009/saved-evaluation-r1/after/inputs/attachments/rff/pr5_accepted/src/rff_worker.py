"""Single-fit RFF logistic worker used by the frozen F5 R5 owner seam.

The outer owner launches this function only after durable RUN_STARTED.  Module
import is side-effect free; bound inputs are opened only inside the worker.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping


SUCCESS_STATUS = "CANDIDATE_FIT_PREDICT_AND_FULL2024_EVALUATION_COMPLETED"


class RFFWorkerError(RuntimeError):
    pass


def _route_source(payload: Mapping[str, Any]) -> Path:
    item = payload["code_files"].get("rff_worker")
    if not isinstance(item, Mapping):
        raise RFFWorkerError("RFF_WORKER_SOURCE_NOT_BOUND")
    path = Path(str(item["path"])).resolve(strict=True)
    if path.name != "rff_worker.py":
        raise RFFWorkerError("RFF_WORKER_SOURCE_PATH_INVALID")
    return path.parent


def _training_row_count(evidence: Any, *, expected_rows: int) -> int:
    """The original prefit API returns (GroupingPlan, evidence), not a row int."""
    if not isinstance(evidence, Mapping) or type(evidence.get("rows")) is not int:
        raise RFFWorkerError("RFF_PREFIT_TRAINING_EVIDENCE_SCHEMA_MISMATCH")
    rows = evidence["rows"]
    if rows <= 0 or rows != expected_rows:
        raise RFFWorkerError("RFF_PREFIT_TRAINING_ROW_COUNT_MISMATCH")
    return rows


def _require_bound_import(module: Any, payload: Mapping[str, Any], label: str) -> None:
    """A sys.path edit must not silently select an unbound cached project module."""
    origin = getattr(module, "__file__", None)
    if not isinstance(origin, str):
        raise RFFWorkerError(f"RFF_IMPORTED_MODULE_ORIGIN_MISSING:{label}")
    path = Path(origin)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RFFWorkerError(f"RFF_IMPORTED_MODULE_PATH_INVALID:{label}")
    records = []
    for field in ("code_files", "executable_helpers"):
        values = payload.get(field, {})
        if isinstance(values, Mapping):
            records.extend(item for item in values.values()
                           if isinstance(item, Mapping) and item.get("path") == str(path))
    if not records:
        raise RFFWorkerError(f"RFF_IMPORTED_MODULE_NOT_BOUND:{label}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if any(item.get("sha256") != digest.hexdigest() for item in records):
        raise RFFWorkerError(f"RFF_IMPORTED_MODULE_SHA_MISMATCH:{label}")


def _call_budget(*, fit_calls: int, fit_entered: bool, fit_returned: int,
                 predict_calls: int, truth_decodes: int, truth_decoded: bool) -> dict[str, Any]:
    """Actual counters observed by this single worker; not authorization values."""
    return {
        "fit_calls": fit_calls, "fit_call_entered": fit_entered,
        "real_fit_returned_count": fit_returned, "predict_calls": predict_calls,
        "control_fit_calls": 0, "control_predict_calls": 0, "calibrator_fit_calls": 0,
        "evaluation_truth_decodes": truth_decodes,
        "evaluation_label_values_decoded": truth_decoded,
    }


def _join_truth(scores: Any, truth: Any):
    """Attach outcomes by this left frame's keys, not global null-label counts.

    A present key with unknown y is valid. Positional assignment preserves all
    left columns, score bits, row order and index, including a non-unique index.
    """
    import pandas as pd

    keys = ["code", "session_id"]
    outcomes = ["y", "label_status", "first_exact", "episode_state"]
    if not scores.columns.is_unique or not truth.columns.is_unique or set(outcomes).intersection(scores.columns):
        raise RFFWorkerError("RFF_TRUTH_JOIN_AMBIGUOUS_COLUMNS")
    if not set(keys).issubset(scores.columns) or not set(keys + outcomes).issubset(truth.columns):
        raise RFFWorkerError("RFF_TRUTH_JOIN_SCHEMA_MISMATCH")
    for name, frame in (("scores", scores), ("truth", truth)):
        if frame[keys].isna().any().any():
            raise RFFWorkerError(f"RFF_TRUTH_JOIN_NULL_KEY:{name}")
        if frame.duplicated(keys).any():
            raise RFFWorkerError(f"RFF_TRUTH_JOIN_DUPLICATE_KEY:{name}")

    positions = pd.MultiIndex.from_frame(truth[keys]).get_indexer(pd.MultiIndex.from_frame(scores[keys]))
    if (positions < 0).any():
        raise RFFWorkerError("RFF_TRUTH_JOIN_UNMATCHED_KEY")
    joined = scores.copy()
    for column in outcomes:
        joined[column] = truth[column].iloc[positions].array
    if joined["label_status"].isna().any() or joined["episode_state"].isna().any():
        raise RFFWorkerError("EVALUATION_OUTCOME_METADATA_MISSING")
    return joined


def run_candidate_worker(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run one classifier fit, one full-S prediction, then the frozen evaluator."""
    import io
    import numpy as np
    import pandas as pd

    import candidate_worker as original_worker_module
    from candidate_worker import (
        _csv_bytes,
        _deep_equal,
        _load_bound_inputs,
        _load_control_artifacts,
        _read_csv_bytes,
        _sha256_bytes,
        _sha256_file,
        _top3_identity,
        _validate_candidate_prediction_grid,
        _write_bytes_exclusive,
        _write_exclusive,
        _write_npy_exclusive,
    )

    route_src = _route_source(payload)
    if str(route_src) not in sys.path:
        sys.path.insert(0, str(route_src))
    import rff_logistic_core as core
    import score_aware_metrics

    output = Path(str(payload["output_root"])).resolve(strict=True)
    start_path = Path(str(payload["start_receipt_path"])).resolve(strict=True)
    if start_path.parent != output or _sha256_file(start_path) != payload.get("start_receipt_sha256"):
        raise RFFWorkerError("RFF_START_RECEIPT_IDENTITY_MISMATCH")
    allowed_names = {start_path.name}
    trace_path = Path(str(payload.get("resource_trace_path", "")))
    if trace_path.parent.resolve() == output:
        allowed_names.add(trace_path.name)
    if {path.name for path in output.iterdir()} - allowed_names:
        raise RFFWorkerError("RFF_OUTPUT_DIRECTORY_NOT_EXCLUSIVE")

    execution_id = str(payload["execution_id"])
    spec = payload["run_spec"]
    binding = payload
    fit_entered = False
    fit_returned = 0
    fit_calls = 0
    predict_calls = 0
    truth_decoded = False
    truth_decodes = 0
    started = time.monotonic()
    try:
        code_files = payload["code_files"]
        canonical_sources = json.dumps(dict(code_files), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if _sha256_bytes(canonical_sources) != payload["source_code_sha256"]:
            raise RFFWorkerError("RFF_SOURCE_MANIFEST_SHA_MISMATCH")
        for name, item in code_files.items():
            path = Path(str(item["path"]))
            if path.is_symlink() or not path.is_file() or _sha256_file(path) != item.get("sha256"):
                raise RFFWorkerError(f"RFF_SOURCE_SHA_MISMATCH:{name}")
        for name, item in payload["executable_helpers"].items():
            path = Path(str(item["path"]))
            if path.is_symlink() or not path.is_file() or _sha256_file(path) != item.get("sha256"):
                raise RFFWorkerError(f"RFF_EXECUTABLE_HELPER_SHA_MISMATCH:{name}")

        for module, label in ((original_worker_module, "candidate_worker"), (core, "rff_logistic_core"),
                              (score_aware_metrics, "score_aware_metrics")):
            _require_bound_import(module, payload, label)
        route_root = Path(str(payload["route_source_root"])).resolve(strict=True)
        recovery_src = Path(str(payload["recovery_source_root"])).resolve(strict=True)
        for source_root in (recovery_src, route_root):
            if str(source_root) not in sys.path:
                sys.path.insert(0, str(source_root))
        import prefit_runner
        import recovery_prefit_entry
        _require_bound_import(prefit_runner, payload, "prefit_runner")
        _require_bound_import(recovery_prefit_entry, payload, "recovery_prefit_entry")
        _load_module = recovery_prefit_entry._load_module

        snapshots, observed = _load_bound_inputs(payload)
        expected = {name: item["sha256"] for name, item in payload["input_files"].items()}
        if observed != expected:
            raise RFFWorkerError("RFF_BOUND_INPUT_SET_MISMATCH")
        _write_exclusive(output / "CANDIDATE_INPUT_HASH_RECEIPT.json", {
            "schema": "F5_FULL64_RFF_INPUT_HASH_RECEIPT_V1",
            "route_id": spec["route_id"],
            "execution_id": execution_id,
            "input_sha256": observed,
            "all_six_frozen_inputs_verified": True,
            "eval_meta_pretruth_columns_only": ["code", "session_id", "market_date", "scoreable"],
            "evaluation_label_values_decoded": False,
        })

        x_train = np.load(io.BytesIO(snapshots["X_train.npy"]), allow_pickle=False)
        y_train = np.load(io.BytesIO(snapshots["y_train.npy"]), allow_pickle=False)
        train_keys = _read_csv_bytes(
            snapshots["train_keys.csv.gz"],
            usecols=["code", "session_id", "market_date", "label_end", "label_mature_ns", "y"],
            code_as_string=True,
        )
        x_eval = np.load(io.BytesIO(snapshots["X_eval.npy"]), allow_pickle=False)
        calendar = _read_csv_bytes(snapshots["eval_calendar.csv.gz"], usecols=["session_id", "market_date"])
        eval_meta_raw = snapshots["eval_meta.csv.gz"]
        eval_pretruth = _read_csv_bytes(
            eval_meta_raw,
            usecols=["code", "session_id", "market_date", "scoreable"],
            code_as_string=True,
        )
        del snapshots

        training = payload["training_contract"]
        grouping = _load_module(Path(payload["grouping_path"]), "f5_rff_original_grouping")
        plan, training_evidence = prefit_runner.validate_training_rows(
            x_train,
            y_train,
            train_keys,
            expected_rows=int(training["expected_rows"]),
            expected_features=int(training["feature_count"]),
            expected_positive_rows=int(training["expected_positive_rows"]),
            expected_groups=int(training["expected_groups"]),
            expected_label_dtype=str(training["expected_label_dtype"]),
            cutoff_ns=int(training["cutoff_ns"]),
            purge_label_end_strictly_before=int(training["purge_label_end_strictly_before"]),
            grouping_module=grouping,
        )
        training_rows = _training_row_count(training_evidence, expected_rows=int(training["expected_rows"]))
        prefit = payload["prefit_artifacts"]
        for artifact_key, payload_key in (
            ("train_permutation", "train_permutation"),
            ("train_inverse_permutation", "train_inverse_permutation"),
            ("train_group_sizes", "train_group_sizes"),
        ):
            item = prefit[payload_key]
            path = Path(item["path"])
            if _sha256_file(path) != item["sha256"]:
                raise RFFWorkerError(f"RFF_PREFIT_ARTIFACT_SHA_MISMATCH:{payload_key}")
            stored = np.load(path, allow_pickle=False)
            if artifact_key == "train_permutation" and not np.array_equal(plan.permutation, stored):
                raise RFFWorkerError("RFF_PREFIT_PERMUTATION_CHANGED")
            if artifact_key == "train_inverse_permutation" and not np.array_equal(plan.inverse_permutation, stored):
                raise RFFWorkerError("RFF_PREFIT_INVERSE_PERMUTATION_CHANGED")
            if artifact_key == "train_group_sizes" and not np.array_equal(plan.group_sizes, stored):
                raise RFFWorkerError("RFF_PREFIT_GROUP_SIZES_CHANGED")

        evaluation = payload["evaluation_contract"]
        if x_train.shape != (int(training["expected_rows"]), int(training["feature_count"])):
            raise RFFWorkerError("RFF_TRAIN_MATRIX_SHAPE_MISMATCH")
        if x_eval.shape != (int(evaluation["grid_rows"]), int(payload["feature_count"])):
            raise RFFWorkerError("RFF_EVAL_MATRIX_SHAPE_MISMATCH")
        if len(eval_pretruth) != len(x_eval) or len(calendar) != int(evaluation["sessions"]):
            raise RFFWorkerError("RFF_EVAL_METADATA_SHAPE_MISMATCH")
        if int(eval_pretruth["scoreable"].sum()) != int(evaluation["scoreable_rows"]):
            raise RFFWorkerError("RFF_SCOREABLE_COUNT_MISMATCH")
        if eval_pretruth.duplicated(["session_id", "code"]).any():
            raise RFFWorkerError("RFF_EVAL_KEY_DUPLICATE")

        means, scales = core.fit_preprocessor(x_train)
        projection, phase = core.make_rff_parameters(n_features=x_train.shape[1])
        training_rff = core.transform_rff(
            x_train, means, scales, projection, phase,
            chunk_rows=int(spec["random_fourier_features"]["chunk_rows"]),
        )
        del x_train
        fit_started = time.monotonic()
        fit_calls = 1
        fit_entered = True
        try:
            coefficients, intercept, optimizer = core.fit_logistic(training_rff, y_train)
            fit_returned = 1
        except core.OptimizerNotConverged as exc:
            fit_returned = 0
            optimizer = dict(exc.optimizer_result)
            _write_exclusive(output / "OPTIMIZER_RESULT.json", {
                "schema": "F5_FULL64_RFF_OPTIMIZER_RESULT_V1",
                "route_id": spec["route_id"],
                "execution_id": execution_id,
                **optimizer,
            })
            _write_exclusive(output / "CANDIDATE_WORKER_STATUS.json", {
                "schema": "F5_FULL64_RFF_WORKER_STATUS_V1",
                "status": "STOP_OPTIMIZER_NOT_CONVERGED",
                "route_id": spec["route_id"],
                "execution_id": execution_id,
                **_call_budget(fit_calls=fit_calls, fit_entered=fit_entered, fit_returned=fit_returned,
                               predict_calls=predict_calls, truth_decodes=truth_decodes, truth_decoded=truth_decoded),
                "error_type": "STOP_OPTIMIZER_NOT_CONVERGED",
            })
            raise
        fit_seconds = time.monotonic() - fit_started
        optimizer_path = output / "OPTIMIZER_RESULT.json"
        _write_exclusive(optimizer_path, {
            "schema": "F5_FULL64_RFF_OPTIMIZER_RESULT_V1",
            "route_id": spec["route_id"],
            "execution_id": execution_id,
            **optimizer,
        })
        model_doc = {
            "schema": "F5_FULL64_RFF_LOGISTIC_MODEL_V1",
            "route_id": spec["route_id"],
            "execution_id": execution_id,
            "input_feature_count": int(projection.shape[0]),
            "random_feature_count": int(projection.shape[1]),
            "gamma": core.RFF_GAMMA,
            "seed": core.RFF_SEED,
            "means": means.tolist(),
            "scales": scales.tolist(),
            "projection": projection.tolist(),
            "phase": phase.tolist(),
            "coefficients": coefficients.tolist(),
            "intercept": intercept,
            "preprocessing_fit_fold": "ORIGINAL_2018_TO_2023_TRAINING_ROWS_ONLY",
        }
        model_path = output / "CANDIDATE_MODEL.txt"
        model_sha = _write_exclusive(model_path, model_doc)
        fit_receipt = {
            "schema": "F5_FULL64_RFF_CANDIDATE_FIT_RECEIPT_V1",
            "status": "FIT_COMPLETED",
            "route_id": spec["route_id"],
            "execution_id": execution_id,
            "objective": "mean_BCE_plus_l2_w_over_2Cn_unpenalized_intercept",
            "optimizer": "SCIPY_LBFGSB_ANALYTIC_GRADIENT",
            "optimizer_options": dict(core.L_BFGS_B_OPTIONS),
            "training_rows": int(training_rows),
            "feature_count": 64,
            "random_feature_count": 256,
            "fit_calls": 1,
            "fit_call_entered": True,
            "real_fit_returned_count": 1,
            "fit_seconds": fit_seconds,
            "optimizer_result_path": str(optimizer_path.resolve()),
            "optimizer_result_sha256": _sha256_file(optimizer_path),
            "model_path": str(model_path.resolve()),
            "model_sha256": model_sha,
            "control_fit_calls": 0,
            "calibrator_fit_calls": 0,
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        fit_receipt_sha = _write_exclusive(output / "CANDIDATE_FIT_RECEIPT.json", fit_receipt)
        del training_rff, y_train

        scoreable = eval_pretruth["scoreable"].to_numpy(dtype=np.int8).astype(bool)
        if int(scoreable.sum()) != int(evaluation["scoreable_rows"]):
            raise RFFWorkerError("RFF_SCOREABLE_MASK_CHANGED")
        predict_calls += 1
        margins, probabilities = core.predict_full_eval(
            x_eval[scoreable], means, scales, projection, phase, coefficients, intercept,
            chunk_rows=int(spec["random_fourier_features"]["chunk_rows"]),
        )
        if len(margins) != int(evaluation["scoreable_rows"]):
            raise RFFWorkerError("RFF_FULL_S_PREDICTION_COUNT_MISMATCH")
        raw = np.full(len(x_eval), np.nan, dtype=np.float64)
        probability = np.full(len(x_eval), np.nan, dtype=np.float64)
        raw[scoreable] = margins
        probability[scoreable] = probabilities
        eval_scores = eval_pretruth.copy()
        eval_scores["ranking_score"] = raw
        eval_scores["probability"] = probability
        _validate_candidate_prediction_grid(
            eval_scores,
            expected_rows=int(evaluation["grid_rows"]),
            expected_scored=int(evaluation["scoreable_rows"]),
            score_column="ranking_score",
        )
        if eval_scores["session_id"].nunique() != int(evaluation["sessions"]):
            raise RFFWorkerError("RFF_SESSION_COUNT_MISMATCH")
        selected_pretruth = score_aware_metrics.select_top3(
            eval_scores,
            score_kind=score_aware_metrics.RAW_RANKING_SCORE,
            score_column="ranking_score",
        )
        scores_sha = _write_bytes_exclusive(output / "CANDIDATE_SCORES.csv.gz", _csv_bytes(eval_scores))
        top3_sha = _write_bytes_exclusive(output / "CANDIDATE_TOP3.csv.gz", _csv_bytes(selected_pretruth))
        raw_sha = _write_npy_exclusive(output / "CANDIDATE_RAW_SCORES.npy", raw)
        seal_sha = _write_exclusive(output / "PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json", {
            "schema": "F5_FULL64_RFF_PREDICTION_SEAL_V1",
            "status": "PREDICTION_FROZEN_BEFORE_EVALUATION_TRUTH_READ",
            "route_id": spec["route_id"],
            "execution_id": execution_id,
            "score_kind": "RAW_LOGISTIC_DECISION_MARGIN",
            "probability_kind": "FITTED_LOGISTIC_SIGMOID_NO_CALIBRATOR",
            "grid_rows": len(eval_scores),
            "scoreable_rows": int(scoreable.sum()),
            "evaluation_sessions": int(eval_scores["session_id"].nunique()),
            "predict_calls": predict_calls,
            "chunk_rows": int(spec["random_fourier_features"]["chunk_rows"]),
            "candidate_scores_sha256": scores_sha,
            "candidate_raw_scores_sha256": raw_sha,
            "candidate_top3_sha256": top3_sha,
            "evaluation_label_values_decoded": False,
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        })
        _write_exclusive(output / "EVALUATION_TRUTH_READ_START.json", {
            "schema": "F5_FULL64_RFF_EVAL_TRUTH_READ_START_V1",
            "route_id": spec["route_id"],
            "execution_id": execution_id,
            "first_eval_truth_decode_after_prediction_seal": True,
            "prediction_seal_sha256": seal_sha,
            "candidate_scores_sha256": scores_sha,
            "candidate_raw_scores_sha256": raw_sha,
            "candidate_top3_sha256": top3_sha,
        })
        truth_decodes += 1
        truth_decoded = True
        truth = _read_csv_bytes(
            eval_meta_raw,
            usecols=["code", "session_id", "market_date", "scoreable", "y", "label_status", "first_exact", "episode_state"],
            code_as_string=True,
        )
        del eval_meta_raw
        if len(truth) != int(evaluation["grid_rows"]) or int(truth["scoreable"].sum()) != int(evaluation["scoreable_rows"]):
            raise RFFWorkerError("RFF_EVAL_TRUTH_DOMAIN_MISMATCH")
        candidate_frame = _join_truth(eval_scores, truth)
        selected = _join_truth(selected_pretruth, truth)
        controls = _load_control_artifacts(binding, truth)
        metric_module = score_aware_metrics.frozen_metrics()
        calendar["session_id"] = pd.to_numeric(calendar["session_id"], errors="raise").astype(np.int64)
        arms = {
            "CANDIDATE_RFF_LOGISTIC": score_aware_metrics.arm_metrics(
                candidate_frame, selected, calendar,
                score_kind=score_aware_metrics.RAW_RANKING_SCORE,
                score_column="ranking_score",
            )
        }
        # The same classifier emits sigmoid probabilities.  Use the original
        # probability helper for probability diagnostics; Top3/AP remain based
        # on the raw decision margin above.
        arms["CANDIDATE_RFF_LOGISTIC"]["probability"] = score_aware_metrics.probability_metrics(candidate_frame)
        by_arm = {"CANDIDATE_RFF_LOGISTIC": selected}
        binary_compatibility: dict[str, bool] = {}
        for key in ("FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_BASE34"):
            control_frame = controls[key]["scores"]
            control_selected = score_aware_metrics.select_top3(control_frame)
            original_selected = metric_module.select_top3(control_frame)
            pd.testing.assert_frame_equal(control_selected, original_selected, check_dtype=False, check_exact=True)
            stored_top3 = pd.read_csv(controls[key]["top3_path"], dtype={"code": "string"})
            if not _top3_identity(control_selected, stored_top3, score_column="probability"):
                raise RFFWorkerError(f"RFF_FROZEN_CONTROL_TOP3_CHANGED:{key}")
            wrapped = score_aware_metrics.arm_metrics(control_frame, control_selected, calendar)
            original = metric_module.arm_metrics(control_frame, control_selected, calendar)
            if not _deep_equal(wrapped, original):
                raise RFFWorkerError(f"RFF_FROZEN_CONTROL_METRICS_CHANGED:{key}")
            arms[key] = wrapped
            by_arm[key] = control_selected
            binary_compatibility[key] = True
        paired = {
            key: score_aware_metrics.paired_precision(selected, by_arm[key], calendar["session_id"])
            for key in ("FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_BASE34")
        }
        if any(value["denominator"] != int(evaluation["selection_slots"]) for value in paired.values()):
            raise RFFWorkerError("RFF_PAIRED_SLOT_DENOMINATOR_MISMATCH")
        primary = paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["lower"] > 0.0
        practical = paired["FROZEN_BASE34"]["lower"] >= 0.03
        metrics = {
            "schema": "F5_FULL64_RFF_LOGISTIC_FULL2024_METRICS_V1",
            "status": "EXPOSED_RETROSPECTIVE_DEVELOPMENT_EVALUATION",
            "route_id": spec["route_id"],
            "execution_id": execution_id,
            "year": 2024,
            "grid_rows": len(candidate_frame),
            "scoreable_rows": int(candidate_frame["scoreable"].sum()),
            "sessions": int(len(calendar)),
            "selection_slots": int(evaluation["selection_slots"]),
            "truth_positive_denominator": int(evaluation["known_positive_denominator"]),
            "arms": arms,
            "paired_precision": paired,
            "development_gates": {
                "paired_lower_vs_plus_gt_zero": primary,
                "paired_lower_vs_base34_ge_003": practical,
                "all_development_gates_pass": bool(primary and practical),
                "development_decision": "DEVELOPMENT_PASS" if primary and practical else "DIRECTION_ONLY",
            },
            "original_promotion_gates": dict(spec["decision_gates"]["original_promotion_gates_unchanged"]),
            "promotion_decision": "BLOCKED_SINGLE_EXPOSED_YEAR",
            "decision_scope": "EXPOSED_2024_DEVELOPMENT_ONLY_Direction_ONLY_MAX",
            "raw_score_contract": {
                "top3_and_average_precision_score": "RAW_LOGISTIC_DECISION_MARGIN",
                "event_probability": "FITTED_LOGISTIC_SIGMOID",
                "separate_calibrator": False,
            },
            "binary_control_evaluator_outputs_deep_equal_to_original": binary_compatibility,
            **_call_budget(fit_calls=fit_calls, fit_entered=fit_entered, fit_returned=fit_returned,
                           predict_calls=predict_calls, truth_decodes=truth_decodes, truth_decoded=truth_decoded),
            "prediction_seal_sha256": seal_sha,
            "fit_receipt_sha256": fit_receipt_sha,
            "optimizer_result_sha256": _sha256_file(optimizer_path),
            "candidate_model_sha256": model_sha,
            "candidate_scores_sha256": scores_sha,
            "candidate_raw_scores_sha256": raw_sha,
            "candidate_top3_sha256": top3_sha,
            "baseline_score_sha256": {key: value["scores_sha256"] for key, value in binding["baseline_artifacts"].items()},
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        metrics_sha = _write_exclusive(output / "METRICS.json", metrics)
        result = {
            "schema": "F5_FULL64_RFF_LOGISTIC_RESULT_V1",
            "status": SUCCESS_STATUS,
            "execution_id": execution_id,
            "route_id": spec["route_id"],
            "run_spec_sha256": payload["run_spec_sha256"],
            "input_binding_sha256": payload["input_binding_sha256"],
            "source_code_sha256": payload["source_code_sha256"],
            "input_sha256": observed,
            "training_rows": int(training_rows),
            **_call_budget(fit_calls=fit_calls, fit_entered=fit_entered, fit_returned=fit_returned,
                           predict_calls=predict_calls, truth_decodes=truth_decodes, truth_decoded=truth_decoded),
            "prediction_sealed_before_eval_truth_read": True,
            "prediction_seal_sha256": seal_sha,
            "fit_receipt_sha256": fit_receipt_sha,
            "optimizer_result_sha256": _sha256_file(optimizer_path),
            "metrics_sha256": metrics_sha,
            "candidate_model_sha256": model_sha,
            "candidate_scores_sha256": scores_sha,
            "candidate_raw_scores_sha256": raw_sha,
            "candidate_top3_sha256": top3_sha,
            "resource_runtime_identity": {"python": sys.executable, "numpy": np.__version__},
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        _write_exclusive(output / "CANDIDATE_RESULT_RECEIPT.json", result)
        _write_exclusive(output / "CANDIDATE_WORKER_STATUS.json", {
            "schema": "F5_FULL64_RFF_WORKER_STATUS_V1",
            "status": SUCCESS_STATUS,
            "route_id": spec["route_id"],
            "execution_id": execution_id,
            **_call_budget(fit_calls=fit_calls, fit_entered=fit_entered, fit_returned=fit_returned,
                           predict_calls=predict_calls, truth_decodes=truth_decodes, truth_decoded=truth_decoded),
        })
        return result
    except BaseException as exc:
        status_path = output / "CANDIDATE_WORKER_STATUS.json"
        if not status_path.exists():
            try:
                _write_exclusive(status_path, {
                    "schema": "F5_FULL64_RFF_WORKER_STATUS_V1",
                    "status": "FAILED",
                    "route_id": spec.get("route_id"),
                    "execution_id": execution_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    **_call_budget(fit_calls=fit_calls, fit_entered=fit_entered, fit_returned=fit_returned,
                                   predict_calls=predict_calls, truth_decodes=truth_decodes, truth_decoded=truth_decoded),
                })
            except BaseException:
                pass
        raise
