"""Model worker for BREADTH1; no synthetic path imports or fits LightGBM."""
from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from typing import Any, Mapping

import numpy as np
import pandas as pd

from f5_breadth1_budget import (
    BATCH_ROOT,
    BREADTH1OfficialActionAdapter,
    VerifiedActionContext,
    VerifiedActionRelease,
)
from f5_breadth1_core import (
    FEATURE_NAME,
    FEATURES64,
    FROZEN_BCE_PARAMS,
    FROZEN_ROUNDS,
    ArtifactContractError,
    load_frozen_metrics,
    npy_array_sha256,
    persist_csv_snapshot,
    persist_probability_snapshot,
    row_keys_sha256,
    score_to_top3,
    strict_integer_values,
    validate_calendar_date_map,
    validate_exact_top3,
    validate_top3_scores,
    write_json_exclusive,
    write_text_exclusive,
)


class RealRunBlocked(RuntimeError):
    """A later authorized real run lacks verified arrays, outputs, or budgets."""


REAL_FIT_WORKER_MAX_WALL_SECONDS = None
REAL_FIT_WORKER_MAX_RSS_BYTES = None
REAL_FIT_WORKER_COUNT = 1


def available_logical_cpu_count() -> int:
    """Return this process's effective logical CPU count, with safe fallbacks."""

    process_count = getattr(os, "process_cpu_count", None)
    count = process_count() if callable(process_count) else None
    if count is None:
        count = os.cpu_count()
    return max(1, int(count or 1))


def _fit_in_monitored_process(
    train_x: np.ndarray,
    labels: np.ndarray,
    model_path: Path,
    *,
    on_fit_entered: Any = None,
) -> tuple[Any, dict[str, Any]]:
    """Fit in the calling process and retain the live model for one prediction.

    Only the already-debited fit callback may enter this helper. A monitoring
    thread observes this process and its children; it never fits, reads input,
    enforces a resource limit, or loads a model. No child training process or
    model-file reload is needed to continue with the cached input arrays.
    """

    import psutil

    thread_count = available_logical_cpu_count()
    samples: list[dict[str, Any]] = []
    rss_observation_complete = True
    started = time.monotonic()
    process_id = os.getpid()
    stop_observer = threading.Event()
    fit_entered = False
    fit_returned = False
    failure: BaseException | None = None
    trace: dict[str, Any] = {}
    environment_names = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
    prior_environment = {name: os.environ.get(name) for name in environment_names}

    def observe_rss() -> None:
        nonlocal rss_observation_complete
        rss: int | None = None
        try:
            process = psutil.Process(process_id)
            rss = process.memory_info().rss
            for child in process.children(recursive=True):
                rss += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            rss = None
            rss_observation_complete = False
        samples.append({"elapsed_seconds": time.monotonic() - started, "rss_bytes": rss})

    def observe_until_stopped() -> None:
        while not stop_observer.wait(0.2):
            observe_rss()

    observer = threading.Thread(
        target=observe_until_stopped, name="f5-breadth1-fit-rss-observer", daemon=True,
    )
    observer_started = False
    try:
        observe_rss()
        observer.start()
        observer_started = True
        for name in environment_names:
            os.environ[name] = str(thread_count)
        lgb = _load_lightgbm_46()
        train_set = lgb.Dataset(
            train_x, label=labels, feature_name=[*FEATURES64, FEATURE_NAME], free_raw_data=False,
        )
        params = dict(FROZEN_BCE_PARAMS)
        params["num_threads"] = thread_count
        fit_entered = True
        if callable(on_fit_entered):
            on_fit_entered()
        model = lgb.train(params, train_set, num_boost_round=FROZEN_ROUNDS)
        fit_returned = True
        model_text = model.model_to_string(num_iteration=FROZEN_ROUNDS)
        if not isinstance(model_text, str) or not model_text:
            raise RealRunBlocked("LIGHTGBM_MODEL_SERIALIZATION_EMPTY")
        write_text_exclusive(model_text, model_path)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            stop_observer.set()
            if observer_started:
                observer.join()
            observe_rss()
            trace = {
                "schema": "F5_BREADTH1_REAL_FIT_RESOURCE_TRACE_V1",
                "worker_count": REAL_FIT_WORKER_COUNT,
                "worker_execution_mode": "SAME_PROCESS_LIVE_MODEL",
                "worker_process_id": process_id,
                "rss_scope": "CURRENT_PROCESS_AND_CHILDREN_INCLUDES_CACHED_INPUTS",
                "worker_wall_limit_seconds": None,
                "worker_wall_observation": "OBSERVE_ONLY",
                "worker_tree_rss_limit_bytes": None,
                "worker_tree_rss_observation": "OBSERVE_ONLY",
                "rss_observation_complete": rss_observation_complete,
                "actual_thread_count": thread_count,
                "thread_count_source": "os.process_cpu_count_fallback_os.cpu_count_clamped_at_one",
                "peak_worker_tree_rss_bytes": max(
                    (row["rss_bytes"] for row in samples if row["rss_bytes"] is not None), default=None,
                ),
                "samples": samples,
                "terminal_reason": f"{type(failure).__name__}:{failure}" if failure is not None else None,
                "fit_call_entered": fit_entered,
                "fit_call_returned": fit_returned,
                "worker_exit_code": None,
                "model_load_calls": 0,
            }
            try:
                write_json_exclusive(trace, model_path.with_name("FIT_RESOURCE_TRACE.json"))
            except BaseException as trace_error:
                if failure is None:
                    raise
                failure.add_note(f"FIT_RESOURCE_TRACE_WRITE_FAILED:{type(trace_error).__name__}:{trace_error}")
        finally:
            for name, value in prior_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
    return model, trace


def _load_lightgbm_46():
    """Lazy import used only from the explicitly released real fit callback."""

    try:
        import lightgbm as lgb  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RealRunBlocked("LIGHTGBM_4_6_REQUIRED") from exc
    if str(getattr(lgb, "__version__", "")) != "4.6.0":
        raise RealRunBlocked(f"LIGHTGBM_VERSION_MISMATCH:{getattr(lgb, '__version__', None)}")
    return lgb


def assemble_full_g_scores(
    *,
    eval_row_keys: pd.DataFrame,
    score_row_keys: pd.DataFrame,
    scoreable_mask: np.ndarray,
    scoreable_probabilities: np.ndarray,
) -> pd.DataFrame:
    """Map one full S-domain prediction back to the exact full-G row order."""

    _require_key_frame(eval_row_keys, "eval_row_keys")
    _require_key_frame(score_row_keys, "score_row_keys")
    if not isinstance(scoreable_mask, np.ndarray) or scoreable_mask.dtype != np.bool_ or scoreable_mask.ndim != 1:
        raise RealRunBlocked("SCOREABLE_MASK_MUST_BE_ONE_DIMENSIONAL_BOOL")
    if scoreable_mask.shape[0] != len(eval_row_keys):
        raise RealRunBlocked("SCOREABLE_MASK_ROW_COUNT_MISMATCH")
    if not isinstance(scoreable_probabilities, np.ndarray) or scoreable_probabilities.dtype != np.float64 or scoreable_probabilities.ndim != 1:
        raise RealRunBlocked("SCOREABLE_PREDICTIONS_MUST_BE_ONE_DIMENSIONAL_FLOAT64")
    if len(scoreable_probabilities) != int(scoreable_mask.sum()):
        raise RealRunBlocked("SCOREABLE_PREDICTION_COUNT_MISMATCH")
    if not np.isfinite(scoreable_probabilities).all() or np.any(
        (scoreable_probabilities < 0.0) | (scoreable_probabilities > 1.0)
    ):
        raise RealRunBlocked("SCOREABLE_PREDICTIONS_INVALID")

    eval_keys = _normalized_keys(eval_row_keys, "eval_row_keys")
    score_keys = _normalized_keys(score_row_keys, "score_row_keys")
    expected_score_keys = eval_keys.loc[scoreable_mask].reset_index(drop=True)
    if not expected_score_keys.equals(score_keys.reset_index(drop=True)):
        raise RealRunBlocked("SCOREABLE_KEYS_DO_NOT_MATCH_FULL_G_MASK_ORDER")
    if eval_keys.duplicated(["session_id", "code"]).any() or score_keys.duplicated(["session_id", "code"]).any():
        raise RealRunBlocked("DUPLICATE_SCORE_ROW_KEY")

    probabilities = np.full(len(eval_keys), np.nan, dtype=np.float64)
    probabilities[scoreable_mask] = scoreable_probabilities
    return pd.DataFrame({
        "session_id": eval_keys["session_id"].to_numpy(dtype=np.int64),
        "code": eval_keys["code"].to_numpy(dtype=object),
        "scoreable": scoreable_mask.astype(np.int8),
        "probability": probabilities,
    })


def fit_and_predict_real_once(
    *,
    train_x: np.ndarray,
    train_y: np.ndarray,
    score_x: np.ndarray,
    eval_row_keys: pd.DataFrame,
    score_row_keys: pd.DataFrame,
    scoreable_mask: np.ndarray,
    calendar: pd.DataFrame,
    release: VerifiedActionRelease | None,
    action_budget: BREADTH1OfficialActionAdapter | None,
    model_path: Path | None,
    scoreable_prediction_path: Path | None,
    candidate_scores_path: Path | None,
    candidate_top3_path: Path | None,
) -> tuple[Any, dict[str, Any]]:
    """Fit once, predict the bound S domain once, seal all candidate artifacts.

    All array/hash/domain checks happen before the fit debit.  Then the fit
    claim is durably appended before LightGBM is imported; prediction has a
    distinct durable claim.  Failure never refunds either action.
    """

    if release is None or action_budget is None or action_budget.synthetic:
        raise RealRunBlocked("REAL_FIT_PREDICT_BUDGET_RELEASE_NOT_AVAILABLE")
    if any(path is None for path in (model_path, scoreable_prediction_path, candidate_scores_path, candidate_top3_path)):
        raise RealRunBlocked("REAL_OUTPUT_TARGETS_MUST_BE_PREBOUND")
    try:
        preflight_context = action_budget.verify_real_action_context(release)
    except Exception as exc:
        raise RealRunBlocked(f"REAL_ACTION_RELEASE_INVALID:{type(exc).__name__}") from exc

    if not isinstance(train_x, np.ndarray) or train_x.dtype != np.float32 or train_x.ndim != 2 or train_x.shape[1] != 65:
        raise RealRunBlocked("TRAIN_MATRIX_MUST_BE_FLOAT32_65")
    if not isinstance(score_x, np.ndarray) or score_x.dtype != np.float32 or score_x.ndim != 2 or score_x.shape[1] != 65:
        raise RealRunBlocked("SCORE_MATRIX_MUST_BE_FLOAT32_65")
    labels = np.asarray(train_y)
    if labels.ndim != 1 or len(labels) != len(train_x) or not np.isin(labels, [0, 1]).all():
        raise RealRunBlocked("TRAIN_LABELS_MUST_BE_BINARY_AND_ROW_ALIGNED")
    if not isinstance(scoreable_mask, np.ndarray) or scoreable_mask.dtype != np.bool_ or scoreable_mask.ndim != 1:
        raise RealRunBlocked("SCOREABLE_MASK_MUST_BE_ONE_DIMENSIONAL_BOOL")
    if len(scoreable_mask) != len(eval_row_keys) or int(scoreable_mask.sum()) != len(score_x):
        raise RealRunBlocked("SCORE_DOMAIN_OR_MASK_COUNT_MISMATCH")

    try:
        _require_verified_arrays(
            preflight_context.input_binding_value,
            train_x=train_x,
            train_y=labels,
            score_x=score_x,
            eval_row_keys=eval_row_keys,
            score_row_keys=score_row_keys,
            scoreable_mask=scoreable_mask,
        )
        _validate_score_domain(eval_row_keys, score_row_keys, scoreable_mask, calendar)
        paths = _require_fresh_batch_outputs(
            model=model_path,
            scoreable_prediction=scoreable_prediction_path,
            candidate_scores=candidate_scores_path,
            candidate_top3=candidate_top3_path,
            fit_resource_trace=Path(model_path).with_name("FIT_RESOURCE_TRACE.json"),
        )
        metrics = load_frozen_metrics()
    except (ArtifactContractError, RealRunBlocked, OSError) as exc:
        raise RealRunBlocked(f"REAL_FIT_PREFLIGHT_FAILED:{type(exc).__name__}:{exc}") from exc

    fit_call = {"entered": False, "resource_trace": None}

    def _require_action_context(context: VerifiedActionContext) -> None:
        if (
            context.contract_sha256 != preflight_context.contract_sha256
            or context.input_binding_sha256 != preflight_context.input_binding_sha256
            or context.release_sha256 != preflight_context.release_sha256
        ):
            raise RealRunBlocked("ACTION_CONTEXT_CHANGED_AFTER_FIT_PREDICT_PREFLIGHT")

    def _fit_once(context: VerifiedActionContext):
        _require_action_context(context)
        fitted_model, trace = _fit_in_monitored_process(
            train_x, labels, paths["model"],
            on_fit_entered=lambda: fit_call.__setitem__("entered", True),
        )
        fit_call["entered"] = bool(trace["fit_call_entered"])
        fit_call["resource_trace"] = dict(trace)
        return fitted_model

    model = action_budget.execute_once(
        "fit",
        verified_context_callback=_fit_once,
        release=release,
        fit_call_entered=lambda: fit_call["entered"],
        terminal_artifact_paths=(paths["model"], paths["fit_resource_trace"]),
    )

    def _predict_once(context: VerifiedActionContext) -> dict[str, Any]:
        _require_action_context(context)
        thread_count = available_logical_cpu_count()
        probabilities = np.asarray(
            model.predict(score_x, num_threads=thread_count), dtype=np.float64
        )
        if probabilities.shape != (len(score_x),) or not np.isfinite(probabilities).all():
            raise RealRunBlocked("REAL_PREDICTION_SHAPE_OR_FINITE_CHECK_FAILED")
        if np.any((probabilities < 0.0) | (probabilities > 1.0)):
            raise RealRunBlocked("REAL_PREDICTION_OUTSIDE_PROBABILITY_RANGE")
        vector, vector_sha, vector_bytes = persist_probability_snapshot(
            probabilities, paths["scoreable_prediction"]
        )
        scores = assemble_full_g_scores(
            eval_row_keys=eval_row_keys,
            score_row_keys=score_row_keys,
            scoreable_mask=scoreable_mask,
            scoreable_probabilities=vector,
        )
        saved_scores, scores_sha, scores_bytes = persist_csv_snapshot(scores, paths["candidate_scores"])
        top3 = score_to_top3(saved_scores, metrics)
        validate_exact_top3(top3, calendar)
        validate_top3_scores(top3, saved_scores)
        saved_top3, top3_sha, top3_bytes = persist_csv_snapshot(top3, paths["candidate_top3"])
        validate_exact_top3(saved_top3, calendar)
        validate_top3_scores(saved_top3, saved_scores)
        return {
            "scores": saved_scores,
            "top3": saved_top3,
            "thread_count": thread_count,
            "artifact_receipts": {
                "scoreable_prediction": {"path": str(paths["scoreable_prediction"]), "sha256": vector_sha, "bytes": vector_bytes},
                "candidate_scores": {"path": str(paths["candidate_scores"]), "sha256": scores_sha, "bytes": scores_bytes},
                "candidate_top3": {"path": str(paths["candidate_top3"]), "sha256": top3_sha, "bytes": top3_bytes},
            },
        }

    prediction = action_budget.execute_once(
        "predict",
        verified_context_callback=_predict_once,
        release=release,
        terminal_artifact_paths=(paths["scoreable_prediction"], paths["candidate_scores"], paths["candidate_top3"]),
    )
    return model, {
        "model_path": str(paths["model"]),
        "fit_resource_trace": fit_call["resource_trace"],
        "fit_thread_count": int(
            (fit_call["resource_trace"] or {}).get("actual_thread_count") or available_logical_cpu_count()
        ),
        **prediction,
    }


def _require_verified_arrays(
    binding: Mapping[str, Any],
    *,
    train_x: np.ndarray,
    train_y: np.ndarray,
    score_x: np.ndarray,
    eval_row_keys: pd.DataFrame,
    score_row_keys: pd.DataFrame,
    scoreable_mask: np.ndarray,
) -> None:
    receipt = binding.get("verified_arrays")
    if not isinstance(receipt, Mapping) or receipt.get("status") != "PASS":
        raise RealRunBlocked("REAL_ARRAY_IDENTITY_RECEIPT_MISSING")
    expected = {
        "train_x65_npy_sha256": npy_array_sha256(train_x),
        "train_y_npy_sha256": npy_array_sha256(train_y),
        "score_x65_npy_sha256": npy_array_sha256(score_x),
        "eval_row_keys_sha256": row_keys_sha256(eval_row_keys),
        "score_row_keys_sha256": row_keys_sha256(score_row_keys),
        "scoreable_mask_npy_sha256": npy_array_sha256(scoreable_mask),
    }
    for name, actual in expected.items():
        if receipt.get(name) != actual:
            raise RealRunBlocked(f"REAL_ARRAY_IDENTITY_SHA_MISMATCH:{name}")
    expected_counts = {
        "train_rows": len(train_x),
        "train_positive_rows": int(np.count_nonzero(np.asarray(train_y) == 1)),
        "evaluation_G_rows": len(eval_row_keys),
        "evaluation_S_rows": len(score_x),
    }
    for name, actual in expected_counts.items():
        if receipt.get(name) != actual:
            raise RealRunBlocked(f"REAL_ARRAY_IDENTITY_COUNT_MISMATCH:{name}")
    if expected_counts["train_rows"] != 539_631 or expected_counts["train_positive_rows"] != 899:
        raise RealRunBlocked("FROZEN_TRAINING_ROW_OR_POSITIVE_COUNT_MISMATCH")
    if expected_counts["evaluation_G_rows"] != 169_986 or expected_counts["evaluation_S_rows"] != 120_084:
        raise RealRunBlocked("FROZEN_EVALUATION_G_OR_S_COUNT_MISMATCH")


def _validate_score_domain(
    eval_row_keys: pd.DataFrame,
    score_row_keys: pd.DataFrame,
    scoreable_mask: np.ndarray,
    calendar: pd.DataFrame,
) -> None:
    eval_keys = _normalized_keys(eval_row_keys, "eval_row_keys")
    score_keys = _normalized_keys(score_row_keys, "score_row_keys")
    if eval_keys.duplicated(["session_id", "code"]).any() or score_keys.duplicated(["session_id", "code"]).any():
        raise RealRunBlocked("DUPLICATE_SCORE_ROW_KEY")
    if not eval_keys.loc[scoreable_mask].reset_index(drop=True).equals(score_keys.reset_index(drop=True)):
        raise RealRunBlocked("SCOREABLE_KEY_IDENTITY_OR_ORDER_MISMATCH")
    date_map = validate_calendar_date_map(calendar)
    eval_sessions = set(eval_keys.session_id.astype(int))
    if eval_sessions != set(date_map):
        raise RealRunBlocked("EVALUATION_SESSION_SET_DIFFERS_FROM_FROZEN_CALENDAR")
    counts = eval_keys.loc[scoreable_mask].groupby("session_id").size().to_dict()
    if any(counts.get(session, 0) < 3 for session in date_map):
        raise RealRunBlocked("LESS_THAN_THREE_SCOREABLE_INPUTS_ON_A_CALENDAR_SESSION")


def _normalized_keys(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if not {"code", "session_id"} <= set(frame.columns):
        raise RealRunBlocked(f"{label}_KEY_COLUMNS_MISSING")
    keys = frame.loc[:, ["code", "session_id"]].copy()
    if keys.isna().any().any():
        raise RealRunBlocked(f"{label}_KEYS_CONTAIN_NULL")
    keys["code"] = keys["code"].astype(str)
    keys["session_id"] = strict_integer_values(keys["session_id"], f"{label}.session_id")
    if keys["code"].eq("").any() or keys["code"].isin({"nan", "None"}).any():
        raise RealRunBlocked(f"{label}_KEYS_CONTAIN_EMPTY_CODE")
    return keys


def _require_key_frame(frame: pd.DataFrame, label: str) -> None:
    if not isinstance(frame, pd.DataFrame) or not {"code", "session_id"} <= set(frame.columns):
        raise RealRunBlocked(f"{label.upper()}_KEY_FRAME_INVALID")


def _require_fresh_batch_outputs(**paths: Path) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for name, path in paths.items():
        value = Path(path).resolve()
        try:
            value.relative_to(BATCH_ROOT.resolve())
        except ValueError as exc:
            raise RealRunBlocked(f"{name}_OUTPUT_MUST_STAY_INSIDE_NEW_BATCH") from exc
        if value.exists():
            raise RealRunBlocked(f"{name}_OUTPUT_ALREADY_EXISTS_NO_OVERWRITE")
        value.parent.mkdir(parents=True, exist_ok=True)
        resolved[name] = value
    if len(set(resolved.values())) != len(resolved):
        raise RealRunBlocked("REAL_OUTPUT_PATHS_MUST_BE_UNIQUE")
    return resolved
