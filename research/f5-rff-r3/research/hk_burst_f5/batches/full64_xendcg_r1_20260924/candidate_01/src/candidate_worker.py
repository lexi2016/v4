#!/usr/bin/env python3
"""One-release-gated XENDCG fit, full 2024 raw-score prediction, and evaluation.

This module is deliberately import-safe under multiprocessing ``spawn``.  It
does not touch real inputs at import time; the worker opens them only after its
parent has durably appended the candidate RUN_STARTED/debit event.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping


class CandidateError(RuntimeError):
    pass


def synthetic_exit_without_worker_status(payload: Mapping[str, Any]) -> None:
    """Simulate an abruptly terminated synthetic child before any input access."""
    if payload.get("synthetic_fit_boundary_canary") is not True:
        os._exit(24)
    os._exit(23)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _json_bytes(value)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(path.parent)
    return _sha256_bytes(raw)


def _write_bytes_exclusive(path: Path, raw: bytes) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(path.parent)
    return _sha256_bytes(raw)


def _write_npy_exclusive(path: Path, array: Any) -> str:
    import numpy as np

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        np.save(stream, array, allow_pickle=False)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(path.parent)
    return _sha256_file(path)


def _fsync_dir(path: Path) -> None:
    fd = os.open(Path(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _csv_bytes(frame: Any) -> bytes:
    import gzip
    import io

    text = io.StringIO(newline="")
    frame.to_csv(text, index=False, lineterminator="\n")
    return gzip.compress(text.getvalue().encode("utf-8"), mtime=0)


def _load_bound_inputs(payload: Mapping[str, Any]) -> tuple[dict[str, bytes], dict[str, str]]:
    snapshots: dict[str, bytes] = {}
    observed: dict[str, str] = {}
    items = payload["input_files"]
    if set(items) != {
        "X_train.npy",
        "y_train.npy",
        "train_keys.csv.gz",
        "X_eval.npy",
        "eval_calendar.csv.gz",
        "eval_meta.csv.gz",
    }:
        raise CandidateError("CANDIDATE_INPUT_SCOPE_MISMATCH")
    for name, item in items.items():
        path = Path(item["path"])
        if not path.is_file():
            raise CandidateError(f"BOUND_INPUT_MISSING:{name}")
        raw = path.read_bytes()
        digest = _sha256_bytes(raw)
        if digest != item["sha256"]:
            raise CandidateError(f"BOUND_INPUT_SHA_MISMATCH:{name}:{digest}")
        snapshots[name] = raw
        observed[name] = digest
    return snapshots, observed


def _deep_equal(left: Any, right: Any) -> bool:
    import math
    import numpy as np

    if isinstance(left, np.generic):
        left = left.item()
    if isinstance(right, np.generic):
        right = right.item()
    if isinstance(left, float) and isinstance(right, float):
        if math.isnan(left) and math.isnan(right):
            return True
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(_deep_equal(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_deep_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
        try:
            return bool(np.array_equal(left, right, equal_nan=True))
        except (TypeError, ValueError):
            return False
    try:
        result = left == right
        return bool(result) if not hasattr(result, "all") else bool(result.all())
    except (TypeError, ValueError):
        return False


def _read_csv_bytes(raw: bytes, *, usecols: list[str] | None = None, code_as_string: bool = False):
    import io
    import pandas as pd

    dtype = {"code": "string"} if code_as_string else None
    try:
        return pd.read_csv(io.BytesIO(raw), compression="gzip", usecols=usecols, dtype=dtype)
    except Exception as exc:
        raise CandidateError(f"BOUND_GZIP_CSV_PARSE_FAILED:{type(exc).__name__}") from exc


def _validate_candidate_prediction_grid(frame: Any, *, expected_rows: int, expected_scored: int, score_column: str) -> None:
    import numpy as np

    required = {"code", "session_id", "scoreable", score_column}
    if not required.issubset(frame.columns) or len(frame) != expected_rows:
        raise CandidateError("CANDIDATE_PREDICTION_GRID_SHAPE_OR_SCHEMA_MISMATCH")
    if frame[["code", "session_id"]].isna().any().any() or frame.duplicated(["session_id", "code"]).any():
        raise CandidateError("CANDIDATE_PREDICTION_GRID_KEY_INVALID")
    mask_values = frame["scoreable"].to_numpy()
    if not np.isin(mask_values, (0, 1)).all():
        raise CandidateError("CANDIDATE_SCOREABLE_MASK_NOT_BINARY")
    mask = mask_values.astype(bool)
    values = frame[score_column].to_numpy(dtype=np.float64)
    if int(mask.sum()) != expected_scored or not np.isfinite(values[mask]).all() or np.isfinite(values[~mask]).any():
        raise CandidateError("CANDIDATE_RAW_SCORE_COVERAGE_INVALID")


def _join_truth(scores: Any, truth: Any):
    import pandas as pd

    outcome_columns = ["code", "session_id", "y", "label_status", "first_exact", "episode_state"]
    if not set(outcome_columns).issubset(truth.columns):
        raise CandidateError("EVALUATION_TRUTH_SCHEMA_MISMATCH")
    outcome = truth.loc[:, outcome_columns]
    joined = scores.merge(outcome, on=["code", "session_id"], how="left", validate="one_to_one", sort=False)
    if len(joined) != len(scores) or joined["y"].isna().sum() != truth["y"].isna().sum():
        raise CandidateError("CANDIDATE_TRUTH_JOIN_DOMAIN_MISMATCH")
    if joined["label_status"].isna().any() or joined["episode_state"].isna().any():
        raise CandidateError("EVALUATION_OUTCOME_METADATA_MISSING")
    return joined


def _verify_control_frame(frame: Any, truth: Any, *, name: str):
    import pandas as pd

    keys = ["session_id", "code"]
    columns = ["session_id", "code", "scoreable", "y", "label_status", "first_exact", "episode_state"]
    left = frame.loc[:, columns].sort_values(keys, kind="mergesort").reset_index(drop=True)
    right = truth.loc[:, columns].sort_values(keys, kind="mergesort").reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=True, check_like=False)
    except AssertionError as exc:
        raise CandidateError(f"CONTROL_EVAL_DOMAIN_OR_LABEL_MISMATCH:{name}") from exc


def _load_control_artifacts(binding: Mapping[str, Any], truth: Any) -> dict[str, dict[str, Any]]:
    import pandas as pd

    result: dict[str, dict[str, Any]] = {}
    required = ["code", "session_id", "market_date", "scoreable", "probability", "y", "label_status", "first_exact", "episode_state"]
    for name, item in binding["baseline_artifacts"].items():
        scores_path = Path(item["scores_path"])
        top3_path = Path(item["top3_path"])
        if _sha256_file(scores_path) != item["scores_sha256"]:
            raise CandidateError(f"FROZEN_CONTROL_SCORE_SHA_MISMATCH:{name}")
        if _sha256_file(top3_path) != item["top3_sha256"]:
            raise CandidateError(f"FROZEN_CONTROL_TOP3_SHA_MISMATCH:{name}")
        scores = pd.read_csv(scores_path, dtype={"code": "string"}, usecols=required)
        if len(scores) != int(binding["evaluation_contract"]["grid_rows"]):
            raise CandidateError(f"FROZEN_CONTROL_GRID_ROW_COUNT_MISMATCH:{name}")
        _verify_control_frame(scores, truth, name=name)
        result[name] = {"scores": scores, "top3_path": top3_path}
    if set(result) != {"FROZEN_BASE34", "FROZEN_UNWEIGHTED_PLUS_PATH"}:
        raise CandidateError("FROZEN_CONTROL_SET_MISMATCH")
    return result


def _top3_identity(left: Any, right: Any, *, score_column: str) -> bool:
    import numpy as np
    import pandas as pd

    columns = ["session_id", "code", "rank", score_column]
    if not set(columns).issubset(left.columns) or not set(columns).issubset(right.columns):
        return False
    a = left.loc[:, columns].sort_values(["session_id", "rank", "code"], kind="mergesort").reset_index(drop=True)
    b = right.loc[:, columns].sort_values(["session_id", "rank", "code"], kind="mergesort").reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(a, b, check_dtype=False, check_exact=True)
        return True
    except AssertionError:
        return False


def run_candidate_worker(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run the one released candidate fit and full exposed 2024 evaluation."""
    import io
    import sys

    import numpy as np
    import pandas as pd

    output_root = Path(payload["output_root"])
    output_root.mkdir(parents=True, exist_ok=True)
    start_receipt_path = Path(payload["start_receipt_path"])
    if (
        not start_receipt_path.is_file()
        or _sha256_file(start_receipt_path) != payload["start_receipt_sha256"]
        or start_receipt_path.parent.resolve() != output_root.resolve()
    ):
        raise CandidateError("CANDIDATE_START_RECEIPT_SNAPSHOT_MISMATCH")
    unexpected_output_entries = {
        item.name for item in output_root.iterdir() if item.resolve() != start_receipt_path.resolve()
    }
    if unexpected_output_entries:
        raise CandidateError("CANDIDATE_OUTPUT_NOT_EMPTY_NO_REENTRY")
    eval_truth_read_path = output_root / "EVALUATION_TRUTH_READ_START.json"
    predictions_sealed_path = output_root / "PREDICTION_SEALED_BEFORE_EVAL_TRUTH_READ.json"
    execution_id = str(payload["execution_id"])

    try:
        if payload.get("synthetic_fit_boundary_canary") is True:
            marker = {
                "schema": "F5_FULL64_XENDCG_CANDIDATE_SYNTHETIC_FIT_BOUNDARY_V1",
                "synthetic_only": True,
                "execution_id": execution_id,
                "real_input_rows_read": 0,
                "real_lightgbm_train_calls": 0,
                "predict_calls": 0,
                "candidate_params_sha256": _sha256_bytes(_json_bytes(payload["learner_params"])),
                "num_boost_round_requested": payload["num_boost_round"],
                "fit_boundary_reached": True,
                "stopped_before_native_fit": True,
            }
            _write_exclusive(Path(payload["synthetic_marker_path"]), marker)
            _write_exclusive(output_root / "CANDIDATE_WORKER_STATUS.json", {
                "status": "SYNTHETIC_CANARY_STOPPED_BEFORE_NATIVE_FIT",
                "execution_id": execution_id,
                "fit_calls": 0,
                "fit_call_entered": False,
                "real_fit_returned_count": 0,
                "predict_calls": 0,
                "control_fit_calls": 0,
                "control_predict_calls": 0,
                "calibrator_fit_calls": 0,
                "real_input_rows_read": 0,
                "real_lightgbm_train_calls": 0,
            })
            return {"status": "SYNTHETIC_CANARY_STOPPED_BEFORE_NATIVE_FIT", **marker}

        sys.path.insert(0, str(Path(payload["route_source_root"]).resolve()))
        sys.path.insert(0, str(Path(payload["recovery_source_root"]).resolve()))
        from recovery_prefit_entry import _load_module as recovery_load_module  # type: ignore
        import prefit_runner
        import score_aware_metrics

        source_code_sha = str(payload["source_code_sha256"])
        for name, item in payload["code_files"].items():
            path = Path(item["path"])
            if not path.is_file() or _sha256_file(path) != item["sha256"]:
                raise CandidateError(f"CANDIDATE_SOURCE_SHA_MISMATCH:{name}")
        source_payload = json.dumps(dict(payload["code_files"]), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if _sha256_bytes(source_payload) != source_code_sha:
            raise CandidateError("CANDIDATE_SOURCE_MANIFEST_SHA_MISMATCH")
        for name, item in payload["executable_helpers"].items():
            path = Path(item["path"])
            if not path.is_file() or _sha256_file(path) != item["sha256"]:
                raise CandidateError(f"CANDIDATE_EXECUTABLE_HELPER_SHA_MISMATCH:{name}")

        prefit_snapshots: dict[str, bytes] = {}
        for name, item in payload["prefit_artifacts"].items():
            path = Path(item["path"])
            if not path.is_file():
                raise CandidateError(f"PREFIT_DERIVED_ARTIFACT_MISSING:{name}")
            raw = path.read_bytes()
            if _sha256_bytes(raw) != item["sha256"]:
                raise CandidateError(f"PREFIT_DERIVED_ARTIFACT_SHA_MISMATCH:{name}")
            prefit_snapshots[name] = raw

        native_runtime_path = Path(payload["native_runtime_path"])
        native_runtime = recovery_load_module(native_runtime_path, "f5_full64_xendcg_candidate_native_runtime")
        native_spec = dict(payload["native_spec"])
        child_identity = native_runtime.verify_child_launch_environment(native_spec)
        import lightgbm as lgb
        import lightgbm.libpath

        library_path = Path(lightgbm.libpath._LIB._name).resolve()
        if lightgbm.__version__ != native_spec["lightgbm_version"] or library_path != Path(native_spec["lightgbm_library_path"]).resolve():
            raise CandidateError("CANDIDATE_NATIVE_LIGHTGBM_IDENTITY_MISMATCH")
        if _sha256_file(library_path) != native_spec["lightgbm_library_sha256"]:
            raise CandidateError("CANDIDATE_NATIVE_LIGHTGBM_LIBRARY_SHA_MISMATCH")

        snapshots, observed_inputs = _load_bound_inputs(payload)
        expected_input_hashes = {name: item["sha256"] for name, item in payload["input_files"].items()}
        if observed_inputs != expected_input_hashes:
            raise CandidateError("CANDIDATE_INPUT_HASH_SET_MISMATCH")
        _write_exclusive(output_root / "CANDIDATE_INPUT_HASH_RECEIPT.json", {
            "schema": "F5_FULL64_XENDCG_CANDIDATE_INPUT_HASH_RECEIPT_V1",
            "execution_id": execution_id,
            "input_sha256": observed_inputs,
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
        eval_calendar = _read_csv_bytes(snapshots["eval_calendar.csv.gz"], code_as_string=False)
        eval_meta_raw = snapshots["eval_meta.csv.gz"]
        eval_meta_pretruth = _read_csv_bytes(
            eval_meta_raw,
            usecols=["code", "session_id", "market_date", "scoreable"],
            code_as_string=True,
        )
        del snapshots

        plan_binding = payload["training_contract"]
        grouping_module = recovery_load_module(Path(payload["grouping_path"]), "f5_full64_xendcg_candidate_grouping")
        plan, training_rows = prefit_runner.validate_training_rows(
            x_train,
            y_train,
            train_keys,
            expected_rows=int(plan_binding["expected_rows"]),
            expected_features=int(plan_binding["feature_count"]),
            expected_positive_rows=int(plan_binding["expected_positive_rows"]),
            expected_groups=int(plan_binding["expected_groups"]),
            expected_label_dtype=str(plan_binding["expected_label_dtype"]),
            cutoff_ns=int(plan_binding["cutoff_ns"]),
            purge_label_end_strictly_before=int(plan_binding["purge_label_end_strictly_before"]),
            grouping_module=grouping_module,
        )
        prefit_artifacts = payload["prefit_artifacts"]
        stored_permutation = np.load(io.BytesIO(prefit_snapshots["train_permutation"]), allow_pickle=False)
        stored_inverse = np.load(io.BytesIO(prefit_snapshots["train_inverse_permutation"]), allow_pickle=False)
        stored_groups = np.load(io.BytesIO(prefit_snapshots["train_group_sizes"]), allow_pickle=False)
        if (
            not np.array_equal(plan.permutation, stored_permutation)
            or not np.array_equal(plan.inverse_permutation, stored_inverse)
            or not np.array_equal(plan.group_sizes, stored_groups)
        ):
            raise CandidateError("PREFIT_DERIVED_GROUPING_DIFFERS_FROM_RECOMPUTED_ROWS")

        if x_eval.shape != (int(payload["evaluation_contract"]["grid_rows"]), int(payload["feature_count"])):
            raise CandidateError("CANDIDATE_EVAL_FEATURE_SHAPE_MISMATCH")
        if len(eval_meta_pretruth) != len(x_eval) or len(eval_calendar) != int(payload["evaluation_contract"]["sessions"]):
            raise CandidateError("CANDIDATE_EVAL_META_OR_CALENDAR_ROW_COUNT_MISMATCH")
        if int(eval_meta_pretruth["scoreable"].sum()) != int(payload["evaluation_contract"]["scoreable_rows"]):
            raise CandidateError("CANDIDATE_SCOREABLE_COUNT_MISMATCH")
        if eval_meta_pretruth.duplicated(["session_id", "code"]).any():
            raise CandidateError("CANDIDATE_EVAL_KEY_DUPLICATE")
        if np.isinf(x_eval).any():
            raise CandidateError("CANDIDATE_EVAL_FEATURE_INFINITY_FORBIDDEN")
        scoreable_mask = eval_meta_pretruth["scoreable"].to_numpy(dtype=np.int8).astype(bool)

        params = dict(payload["learner_params"])
        if params != payload["run_spec"]["learner_params"] or payload["num_boost_round"] != 200:
            raise CandidateError("CANDIDATE_FROZEN_LEARNER_PARAMS_OR_ROUNDS_MISMATCH")
        dataset_params = dict(payload["dataset_params"])
        reference, grouped_dataset, dataset_evidence = grouping_module.build_reference_datasets(
            lgb,
            x_train,
            y_train,
            plan,
            dataset_params=dataset_params,
        )
        feature_names = list(payload["feature_names"])
        if len(feature_names) != x_train.shape[1] or len(set(feature_names)) != len(feature_names):
            raise CandidateError("CANDIDATE_FEATURE_ORDER_INVALID")
        reference.set_feature_name(feature_names)
        grouped_dataset.set_feature_name(feature_names)
        if reference.get_feature_name() != feature_names or grouped_dataset.get_feature_name() != feature_names:
            raise CandidateError("CANDIDATE_DATASET_FEATURE_ORDER_MISMATCH")

        fit_started = time.monotonic()
        fit_calls = 0
        fit_entered = False
        fit_returned_count = 0
        fit_calls += 1
        fit_entered = True
        model = lgb.train(params, grouped_dataset, num_boost_round=int(payload["num_boost_round"]))
        fit_returned_count = 1
        fit_seconds = time.monotonic() - fit_started
        model_path = output_root / "CANDIDATE_MODEL.txt"
        model.save_model(str(model_path))
        with model_path.open("rb") as model_stream:
            os.fsync(model_stream.fileno())
        _fsync_dir(output_root)
        model_sha = _sha256_file(model_path)
        fit_receipt = {
            "schema": "F5_FULL64_XENDCG_CANDIDATE_FIT_RECEIPT_V1",
            "status": "FIT_COMPLETED",
            "execution_id": execution_id,
            "objective": "rank_xendcg",
            "params": params,
            "num_boost_round_requested": int(payload["num_boost_round"]),
            "iterations_built": int(model.current_iteration()),
            "fit_calls": fit_calls,
            "fit_call_entered": fit_entered,
            "real_fit_returned_count": fit_returned_count,
            "fit_seconds": fit_seconds,
            "training_rows": training_rows,
            "group_count": int(len(plan.group_sizes)),
            "group_sum": int(plan.group_sizes.sum(dtype=np.int64)),
            "dataset_reference": dataset_evidence,
            "model_path": str(model_path.resolve()),
            "model_sha256": model_sha,
            "sample_weight": None,
            "eval_data_used_during_fit": False,
            "control_fit_calls": 0,
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        fit_receipt_sha = _write_exclusive(output_root / "CANDIDATE_FIT_RECEIPT.json", fit_receipt)

        if model.feature_name() != feature_names:
            raise CandidateError("CANDIDATE_MODEL_FEATURE_ORDER_MISMATCH")
        ranking_score = np.full(len(eval_meta_pretruth), np.nan, dtype=np.float64)
        batch_rows = int(payload["prediction_contract"]["chunk_rows"])
        predict_calls = 0
        for start in range(0, len(eval_meta_pretruth), batch_rows):
            stop = min(start + batch_rows, len(eval_meta_pretruth))
            local_rows = np.flatnonzero(scoreable_mask[start:stop])
            if local_rows.size == 0:
                continue
            row_ids = local_rows + start
            predict_calls += 1
            values = model.predict(x_eval[row_ids], raw_score=True, num_threads=int(params["num_threads"]))
            ranking_score[row_ids] = np.asarray(values, dtype=np.float64)
        eval_scores = eval_meta_pretruth.copy()
        eval_scores["ranking_score"] = ranking_score
        _validate_candidate_prediction_grid(
            eval_scores,
            expected_rows=int(payload["evaluation_contract"]["grid_rows"]),
            expected_scored=int(payload["evaluation_contract"]["scoreable_rows"]),
            score_column="ranking_score",
        )
        if eval_scores["session_id"].nunique() != int(payload["evaluation_contract"]["sessions"]):
            raise CandidateError("CANDIDATE_EVAL_SESSION_COUNT_MISMATCH")
        selected_pretruth = score_aware_metrics.select_top3(
            eval_scores,
            score_kind=score_aware_metrics.RAW_RANKING_SCORE,
            score_column="ranking_score",
        )
        scores_path = output_root / "CANDIDATE_SCORES.csv.gz"
        top3_path = output_root / "CANDIDATE_TOP3.csv.gz"
        raw_scores_path = output_root / "CANDIDATE_RAW_SCORES.npy"
        scores_sha = _write_bytes_exclusive(scores_path, _csv_bytes(eval_scores))
        top3_sha = _write_bytes_exclusive(top3_path, _csv_bytes(selected_pretruth))
        raw_scores_sha = _write_npy_exclusive(raw_scores_path, ranking_score)
        prediction_seal = {
            "schema": "F5_FULL64_XENDCG_PREDICTION_SEAL_V1",
            "status": "PREDICTION_FROZEN_BEFORE_EVALUATION_TRUTH_READ",
            "execution_id": execution_id,
            "score_kind": "RAW_RANKING_MARGIN_NOT_EVENT_PROBABILITY",
            "score_column": "ranking_score",
            "grid_rows": len(eval_scores),
            "scoreable_rows": int(scoreable_mask.sum()),
            "evaluation_sessions": int(eval_scores["session_id"].nunique()),
            "prediction_chunk_rows": batch_rows,
            "predict_calls": predict_calls,
            "score_transform": None,
            "candidate_scores_sha256": scores_sha,
            "candidate_raw_scores_sha256": raw_scores_sha,
            "candidate_top3_sha256": top3_sha,
            "top3_selection": "score_desc_then_code_asc_stable_per_session",
            "evaluation_label_values_decoded": False,
            "control_predict_calls": 0,
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        prediction_seal_sha = _write_exclusive(predictions_sealed_path, prediction_seal)

        # This durable boundary precedes the first decoding of any eval label.
        _write_exclusive(eval_truth_read_path, {
            "schema": "F5_FULL64_XENDCG_EVAL_TRUTH_READ_START_V1",
            "execution_id": execution_id,
            "prediction_seal_sha256": prediction_seal_sha,
            "candidate_scores_sha256": scores_sha,
            "candidate_top3_sha256": top3_sha,
            "candidate_raw_scores_sha256": raw_scores_sha,
            "first_eval_truth_decode_after_prediction_seal": True,
        })
        eval_truth = _read_csv_bytes(
            eval_meta_raw,
            usecols=[
                "code", "session_id", "market_date", "scoreable", "y", "label_status",
                "first_exact", "episode_state",
            ],
            code_as_string=True,
        )
        if len(eval_truth) != int(payload["evaluation_contract"]["grid_rows"]):
            raise CandidateError("EVALUATION_TRUTH_GRID_ROW_COUNT_MISMATCH")
        if int(eval_truth["scoreable"].sum()) != int(payload["evaluation_contract"]["scoreable_rows"]):
            raise CandidateError("EVALUATION_TRUTH_SCOREABLE_COUNT_MISMATCH")
        candidate_frame = _join_truth(eval_scores, eval_truth)
        controls = _load_control_artifacts(payload, eval_truth)

        metric_module = score_aware_metrics.frozen_metrics()
        calendar = eval_calendar.loc[:, ["session_id", "market_date"]].copy()
        if calendar["session_id"].duplicated().any() or len(calendar) != int(payload["evaluation_contract"]["sessions"]):
            raise CandidateError("EVALUATION_CALENDAR_KEY_MISMATCH")
        candidate_selected = _join_truth(selected_pretruth, eval_truth)
        candidate_metrics = score_aware_metrics.arm_metrics(
            candidate_frame,
            candidate_selected,
            calendar,
            score_kind=score_aware_metrics.RAW_RANKING_SCORE,
            score_column="ranking_score",
        )
        arms: dict[str, Any] = {"CANDIDATE_XENDCG": candidate_metrics}
        selected_by_arm: dict[str, Any] = {"CANDIDATE_XENDCG": candidate_selected}
        binary_compatibility: dict[str, bool] = {}
        control_frames: dict[str, Any] = {}
        for binding_name, output_name in (
            ("FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_UNWEIGHTED_PLUS_PATH"),
            ("FROZEN_BASE34", "FROZEN_BASE34"),
        ):
            control_frame = controls[binding_name]["scores"]
            selected = score_aware_metrics.select_top3(control_frame)
            frozen_selected = metric_module.select_top3(control_frame)
            try:
                import pandas as pd

                pd.testing.assert_frame_equal(selected, frozen_selected, check_dtype=False, check_exact=True)
            except AssertionError as exc:
                raise CandidateError(f"BINARY_CONTROL_TOP3_CHANGED:{binding_name}") from exc

            stored_top3 = pd.read_csv(controls[binding_name]["top3_path"], dtype={"code": "string"})
            if not _top3_identity(selected, stored_top3, score_column="probability"):
                raise CandidateError(f"FROZEN_CONTROL_TOP3_ARTIFACT_DIFFERS_FROM_HELPER:{binding_name}")
            wrapped_metrics = score_aware_metrics.arm_metrics(control_frame, selected, calendar)
            original_metrics = metric_module.arm_metrics(control_frame, selected, calendar)
            if not _deep_equal(wrapped_metrics, original_metrics):
                raise CandidateError(f"BINARY_CONTROL_ARM_METRICS_CHANGED:{binding_name}")
            arms[output_name] = wrapped_metrics
            selected_by_arm[output_name] = selected
            control_frames[output_name] = control_frame
            binary_compatibility[output_name] = True

        paired: dict[str, Any] = {}
        for control_name in ("FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_BASE34"):
            delta = score_aware_metrics.paired_precision(
                candidate_selected,
                selected_by_arm[control_name],
                calendar["session_id"],
            )
            daily = delta["daily"]
            paired[control_name] = {
                **delta,
                "daily_gain_loss": {
                    "lower_gain_sessions": sum(row["lower"] > 0 for row in daily),
                    "lower_tie_sessions": sum(row["lower"] == 0 for row in daily),
                    "lower_loss_sessions": sum(row["lower"] < 0 for row in daily),
                    "upper_gain_sessions": sum(row["upper"] > 0 for row in daily),
                    "upper_tie_sessions": sum(row["upper"] == 0 for row in daily),
                    "upper_loss_sessions": sum(row["upper"] < 0 for row in daily),
                },
            }
        if paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["denominator"] != int(payload["evaluation_contract"]["selection_slots"]):
            raise CandidateError("PRIMARY_PAIRED_DENOMINATOR_MISMATCH")

        metrics_doc = {
            "schema": "F5_FULL64_XENDCG_CANDIDATE_FULL2024_METRICS_V1",
            "status": "EXPOSED_RETROSPECTIVE_DEVELOPMENT_EVALUATION",
            "execution_id": execution_id,
            "year": 2024,
            "grid_rows": len(candidate_frame),
            "scoreable_rows": int(candidate_frame["scoreable"].sum()),
            "sessions": int(len(calendar)),
            "selection_slots": int(payload["evaluation_contract"]["selection_slots"]),
            "truth_positive_denominator": int(payload["evaluation_contract"]["known_positive_denominator"]),
            "arms": arms,
            "paired_precision": paired,
            "primary_metric": {
                "name": "paired lower CANDIDATE minus frozen UNWEIGHTED_PLUS_PATH",
                "control": "FROZEN_UNWEIGHTED_PLUS_PATH",
                "lower": paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["lower"],
                "upper": paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["upper"],
                "denominator": paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["denominator"],
                "pass_threshold": "REPORT_ONLY_NO_BREAKTHROUGH_OR_PROMOTION_GATE_CHANGED",
            },
            "binary_control_evaluator_outputs_deep_equal_to_original": binary_compatibility,
            "raw_score_contract": {
                "score_kind": "RAW_RANKING_MARGIN_NOT_EVENT_PROBABILITY",
                "AP_uses_raw_scores": True,
                "brier_logloss_calibration": None,
                "probability_metrics_reason": "NOT_EVALUATED_NO_EVENT_PROBABILITY_MODEL",
            },
            "fit_calls": fit_calls,
            "real_fit_returned_count": fit_returned_count,
            "predict_calls": predict_calls,
            "control_fit_calls": 0,
            "control_predict_calls": 0,
            "calibrator_fit_calls": 0,
            "prediction_seal_sha256": prediction_seal_sha,
            "fit_receipt_sha256": fit_receipt_sha,
            "candidate_model_sha256": model_sha,
            "candidate_scores_sha256": scores_sha,
            "candidate_raw_scores_sha256": raw_scores_sha,
            "candidate_top3_sha256": top3_sha,
            "baseline_score_sha256": {
                key: value["scores_sha256"] for key, value in payload["baseline_artifacts"].items()
            },
            "sealed_forward": False,
            "oof": False,
            "probability_calibration": False,
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        metrics_sha = _write_exclusive(output_root / "METRICS.json", metrics_doc)
        result = {
            "schema": "F5_FULL64_XENDCG_CANDIDATE_RESULT_RECEIPT_V1",
            "status": "CANDIDATE_FIT_PREDICT_AND_FULL2024_EVALUATION_COMPLETED",
            "execution_id": execution_id,
            "run_spec_sha256": payload["run_spec_sha256"],
            "input_binding_sha256": payload["input_binding_sha256"],
            "source_code_sha256": source_code_sha,
            "input_sha256": observed_inputs,
            "training_rows": training_rows,
            "fit_calls": fit_calls,
            "fit_call_entered": fit_entered,
            "real_fit_returned_count": fit_returned_count,
            "predict_calls": predict_calls,
            "control_fit_calls": 0,
            "control_predict_calls": 0,
            "calibrator_fit_calls": 0,
            "evaluation_label_values_decoded": True,
            "prediction_sealed_before_eval_truth_read": predictions_sealed_path.is_file() and eval_truth_read_path.is_file(),
            "prediction_seal_sha256": prediction_seal_sha,
            "fit_receipt_sha256": fit_receipt_sha,
            "metrics_sha256": metrics_sha,
            "candidate_model_sha256": model_sha,
            "candidate_scores_sha256": scores_sha,
            "candidate_raw_scores_sha256": raw_scores_sha,
            "candidate_top3_sha256": top3_sha,
            "resource_runtime_identity": child_identity,
            "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        }
        _write_exclusive(output_root / "CANDIDATE_RESULT_RECEIPT.json", result)
        _write_exclusive(output_root / "CANDIDATE_WORKER_STATUS.json", {
            "status": result["status"],
            "execution_id": execution_id,
            "fit_calls": fit_calls,
            "fit_call_entered": fit_entered,
            "real_fit_returned_count": fit_returned_count,
            "predict_calls": predict_calls,
            "control_fit_calls": 0,
            "control_predict_calls": 0,
            "calibrator_fit_calls": 0,
            "evaluation_label_values_decoded": True,
        })
        return result
    except BaseException as exc:
        try:
            _write_exclusive(output_root / "CANDIDATE_WORKER_STATUS.json", {
                "status": "FAILED",
                "execution_id": execution_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "fit_calls": int(locals().get("fit_calls", 0)),
                "fit_call_entered": bool(locals().get("fit_entered", False)),
                "real_fit_returned_count": int(locals().get("fit_returned_count", 0)),
                "predict_calls": int(locals().get("predict_calls", 0)),
                "control_fit_calls": 0,
                "control_predict_calls": 0,
                "evaluation_label_values_decoded": eval_truth_read_path.exists(),
            })
        except FileExistsError:
            pass
        raise
