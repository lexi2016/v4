"""Pure frame composition for the RFF route's saved prediction evaluation.

The caller owns file identities, the durable execution lifecycle and actual
truth-read counters.  It must pass the SHA-bound accepted RFF worker module and
the unchanged score-aware wrapper.  Only that worker's accepted ``_join_truth``
attaches outcomes.  This module reads no files, loads no model, emits no scores,
and never reselects the saved candidate Top3.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd


KEYS = ["code", "session_id"]
OUTCOMES = ["y", "label_status", "first_exact", "episode_state"]
SCORE_COLUMNS = KEYS + ["market_date", "scoreable", "ranking_score", "probability"]
TOP3_COLUMNS = SCORE_COLUMNS + ["rank", "weight"]
TRUTH_COLUMNS = KEYS + ["market_date", "scoreable", *OUTCOMES]
CONTROL_NAMES = ("FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_BASE34")
ROUTE_ID = "F5_FULL64_RFF_LOGISTIC_R1_20260927"
SAFETY = {"research_only": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}


class RFFSavedEvaluationError(RuntimeError):
    """A saved-frame or frozen metric contract failed; callers must stop."""


def _require_schema(frame: Any, columns: list[str], *, name: str) -> None:
    if (not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique
            or not set(columns).issubset(frame.columns)):
        raise RFFSavedEvaluationError(f"RFF_FRAME_SCHEMA_MISMATCH:{name}")


def _require_sessions(frame: pd.DataFrame, *, name: str) -> None:
    values = frame["session_id"]
    if not pd.api.types.is_numeric_dtype(values.dtype) or pd.api.types.is_bool_dtype(values.dtype):
        raise RFFSavedEvaluationError(f"RFF_SESSION_ID_NOT_INTEGER:{name}")
    numbers = values.to_numpy(dtype=np.float64, na_value=np.nan)
    if not np.isfinite(numbers).all() or not np.equal(numbers, np.floor(numbers)).all():
        raise RFFSavedEvaluationError(f"RFF_SESSION_ID_NOT_INTEGER:{name}")


def _require_keys(frame: pd.DataFrame, *, name: str) -> None:
    if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
        raise RFFSavedEvaluationError(f"RFF_FRAME_KEYS_INVALID:{name}")
    if not frame["code"].map(lambda value: isinstance(value, str)).all():
        raise RFFSavedEvaluationError(f"RFF_CODE_MUST_REMAIN_STRING:{name}")
    _require_sessions(frame, name=name)


def _binary_mask(frame: pd.DataFrame, *, name: str) -> np.ndarray:
    if not frame["scoreable"].isin([0, 1, False, True]).fillna(False).all():
        raise RFFSavedEvaluationError(f"RFF_SCOREABLE_MASK_NOT_BINARY:{name}")
    return frame["scoreable"].to_numpy(dtype=bool)


def _candidate_score_domain(frame: pd.DataFrame, *, name: str) -> None:
    mask = _binary_mask(frame, name=name)
    for column, error_prefix in (("ranking_score", "RAW_SCORE"), ("probability", "PROBABILITY")):
        if not pd.api.types.is_numeric_dtype(frame[column].dtype):
            raise RFFSavedEvaluationError(f"RFF_{error_prefix}_DTYPE_INVALID:{name}")
        values = frame[column].to_numpy(dtype=np.float64, na_value=np.nan)
        if not np.isfinite(values[mask]).all() or not np.isnan(values[~mask]).all():
            raise RFFSavedEvaluationError(f"RFF_{error_prefix}_COVERAGE_INVALID:{name}")
        if column == "probability" and not np.logical_and(values[mask] >= 0, values[mask] <= 1).all():
            raise RFFSavedEvaluationError(f"RFF_PROBABILITY_RANGE_INVALID:{name}")


def _assert_equal(left: pd.DataFrame, right: pd.DataFrame, *, error: str) -> None:
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=True,
                                      check_like=False, check_index_type=False)
    except AssertionError as exc:
        raise RFFSavedEvaluationError(error) from exc


def _check_full_metadata(frame: pd.DataFrame, truth: pd.DataFrame, *, name: str) -> None:
    """Compare full-grid metadata without attaching or replacing any outcome."""
    left = frame.sort_values(KEYS, kind="mergesort").reset_index(drop=True)
    right = truth.sort_values(KEYS, kind="mergesort").reset_index(drop=True)
    _assert_equal(left[KEYS + ["scoreable"]], right[KEYS + ["scoreable"]],
                  error=f"RFF_SCOREABLE_FLAGS_DIFFER_BY_KEY:{name}")
    _assert_equal(left[KEYS + ["market_date"]], right[KEYS + ["market_date"]],
                  error=f"RFF_MARKET_DATE_DIFFERS_BY_KEY:{name}")


def _check_dates(frame: pd.DataFrame, calendar: pd.DataFrame, *, name: str) -> None:
    # This is a session/date consistency check, not an outcome join.
    dates = calendar.set_index("session_id")["market_date"]
    expected = frame["session_id"].map(dates)
    if frame["market_date"].isna().any() or expected.isna().any() or not frame["market_date"].eq(expected).all():
        raise RFFSavedEvaluationError(f"RFF_MARKET_DATE_DIFFERS_FROM_CALENDAR:{name}")


def _check_saved_candidate_top3(top3: pd.DataFrame, scores: pd.DataFrame, *, slots: int) -> None:
    if len(top3) != slots:
        raise RFFSavedEvaluationError("RFF_TOP3_SELECTION_SLOT_COUNT_MISMATCH")
    if not top3["weight"].eq("1/3").all():
        raise RFFSavedEvaluationError("RFF_TOP3_WEIGHT_CHANGED")
    if (top3["rank"].isna().any() or not top3["rank"].isin([1, 2, 3]).all()
            or top3.duplicated(["session_id", "rank"]).any()):
        raise RFFSavedEvaluationError("RFF_TOP3_RANK_INVALID")
    if set(top3["session_id"]) != set(scores["session_id"]):
        raise RFFSavedEvaluationError("RFF_TOP3_SESSION_SET_MISMATCH")
    if not top3.groupby("session_id", sort=False).size().eq(3).all():
        raise RFFSavedEvaluationError("RFF_TOP3_NOT_EXACTLY_THREE_PER_SESSION")

    # Validate saved picks against the saved score grid.  No truth column is
    # present here, and no new Top3 is selected or returned.
    grid = scores.set_index(KEYS, verify_integrity=True)
    pick_keys = pd.MultiIndex.from_frame(top3[KEYS])
    if not pick_keys.isin(grid.index).all():
        raise RFFSavedEvaluationError("RFF_TOP3_NOT_SUBSET_OF_SAVED_GRID")
    values = grid.loc[pick_keys].reset_index()
    picks = top3.reset_index(drop=True)
    for column in ("market_date", "scoreable", "ranking_score", "probability"):
        _assert_equal(picks[[column]], values[[column]],
                      error=f"RFF_TOP3_GRID_VALUE_MISMATCH:{column}")
    if not _binary_mask(top3, name="candidate_top3").all():
        raise RFFSavedEvaluationError("RFF_TOP3_CONTAINS_UNSCOREABLE_ROW")

    grids = {sid: frame for sid, frame in scores.groupby("session_id", sort=False)}
    for sid, selections in top3.groupby("session_id", sort=False):
        frame = grids[sid]
        eligible = frame["scoreable"].to_numpy(dtype=bool)
        margins = frame["ranking_score"].to_numpy(dtype=np.float64)
        codes = frame["code"].to_numpy(dtype=str)
        for pick in selections.itertuples(index=False):
            preceding = eligible & ((margins > pick.ranking_score)
                                    | ((margins == pick.ranking_score) & (codes < pick.code)))
            if int(preceding.sum()) + 1 != pick.rank:
                raise RFFSavedEvaluationError("RFF_TOP3_RANK_NOT_ORDER_STATISTIC")


def _deep_equal(left: Any, right: Any) -> bool:
    """Only a compatibility check; metric arithmetic stays in the frozen code."""
    if isinstance(left, np.generic):
        left = left.item()
    if isinstance(right, np.generic):
        right = right.item()
    if isinstance(left, float) and isinstance(right, float) and math.isnan(left) and math.isnan(right):
        return True
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(_deep_equal(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_deep_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
        return bool(np.array_equal(left, right, equal_nan=True))
    return bool(left == right)


def evaluate_frames(
    *,
    candidate_scores: Any,
    candidate_top3: Any,
    truth: Any,
    calendar: Any,
    controls: Mapping[str, Mapping[str, Any]],
    score_aware: Any,
    accepted_worker: Any,
    evaluation_contract: Mapping[str, Any],
    experiment_contract: Mapping[str, Any],
    execution_id: str,
    artifact_sha256: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate bound saved frames with the original RFF metric composition.

    ``accepted_worker`` must be the module whose complete file SHA256 is
    3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c.
    ``score_aware`` and its frozen evaluator/configuration must already have
    passed the caller's source identity checks.  This pure layer cannot verify
    file hashes or observe how many times labels were decoded.
    """
    expected = {}
    for key in ("year", "grid_rows", "scoreable_rows", "sessions", "selection_slots", "known_positive_denominator"):
        value = evaluation_contract.get(key)
        if type(value) is not int or value < 0:
            raise RFFSavedEvaluationError(f"RFF_EVALUATION_CONTRACT_INVALID:{key}")
        expected[key] = value
    if (expected["year"] != 2024 or expected["sessions"] == 0
            or expected["selection_slots"] != 3 * expected["sessions"]):
        raise RFFSavedEvaluationError("RFF_EVALUATION_SLOT_OR_YEAR_CONTRACT_INVALID")
    if experiment_contract.get("route_id") != ROUTE_ID:
        raise RFFSavedEvaluationError("RFF_EXPERIMENT_ROUTE_MISMATCH")
    gates = experiment_contract["decision_gates"]
    primary_gate, practical_gate = gates["development_primary"], gates["practical_base34"]
    if (primary_gate.get("operator") != ">" or primary_gate.get("value") != 0.0
            or practical_gate.get("operator") != ">=" or practical_gate.get("value") != 0.03):
        raise RFFSavedEvaluationError("RFF_DEVELOPMENT_GATES_CHANGED")
    promotion_gates = gates["original_promotion_gates_unchanged"]
    if promotion_gates.get("promotion_now") is not False or promotion_gates.get("single_exposed_year_blocks_promotion") is not True:
        raise RFFSavedEvaluationError("RFF_PROMOTION_CEILING_CHANGED")

    for name, frame, columns in (("candidate_scores", candidate_scores, SCORE_COLUMNS),
                                 ("candidate_top3", candidate_top3, TOP3_COLUMNS),
                                 ("truth", truth, TRUTH_COLUMNS)):
        _require_schema(frame, columns, name=name)
        _require_keys(frame, name=name)
        _binary_mask(frame, name=name)
    _require_schema(calendar, ["session_id", "market_date"], name="calendar")
    _require_sessions(calendar, name="calendar")
    if (len(candidate_scores) != expected["grid_rows"] or len(truth) != expected["grid_rows"]):
        raise RFFSavedEvaluationError("RFF_FULL_G_OR_TRUTH_ROW_COUNT_MISMATCH")
    for name, frame in (("candidate_scores", candidate_scores), ("truth", truth)):
        if int(_binary_mask(frame, name=name).sum()) != expected["scoreable_rows"]:
            raise RFFSavedEvaluationError(f"RFF_SCOREABLE_ROW_COUNT_MISMATCH:{name}")
    _candidate_score_domain(candidate_scores, name="candidate_scores")
    if (len(calendar) != expected["sessions"] or calendar["session_id"].duplicated().any()
            or calendar["market_date"].isna().any()):
        raise RFFSavedEvaluationError("RFF_CALENDAR_DOMAIN_INVALID")
    if set(candidate_scores["session_id"]) != set(calendar["session_id"]):
        raise RFFSavedEvaluationError("RFF_FULL_G_SESSIONS_DIFFER_FROM_CALENDAR")
    # Match accepted RFF: first_exact may be missing on outcomes for which the
    # original helper does not consume it.  Do not import XENDCG's stricter rule.
    if truth[["label_status", "episode_state"]].isna().any().any():
        raise RFFSavedEvaluationError("RFF_EVALUATION_OUTCOME_METADATA_MISSING")
    for column in ("y", "first_exact"):
        if not pd.api.types.is_numeric_dtype(truth[column].dtype) or pd.api.types.is_bool_dtype(truth[column].dtype):
            raise RFFSavedEvaluationError(f"RFF_TRUTH_NUMERIC_DTYPE_INVALID:{column}")
    labels = truth["y"].to_numpy(dtype=np.float64, na_value=np.nan)
    if np.isinf(labels).any() or not np.isin(labels[np.isfinite(labels)], [0., 1.]).all():
        raise RFFSavedEvaluationError("RFF_TRUTH_LABEL_DOMAIN_INVALID")

    # These are the only outcome attachments in the new evaluation path.
    # Preserve the accepted function, its left-domain rule and its diagnostics.
    candidate_frame = accepted_worker._join_truth(candidate_scores, truth)
    candidate_selected = accepted_worker._join_truth(candidate_top3, truth)
    _check_full_metadata(candidate_scores, truth, name="candidate_scores")
    _check_saved_candidate_top3(candidate_top3, candidate_scores, slots=expected["selection_slots"])
    for name, frame in (("candidate_scores", candidate_scores), ("candidate_top3", candidate_top3), ("truth", truth)):
        _check_dates(frame, calendar, name=name)
    calendar_frame = calendar[["session_id", "market_date"]].copy()
    calendar_frame["session_id"] = calendar_frame["session_id"].astype(np.int64)

    frozen = score_aware.frozen_metrics()
    candidate_metrics = score_aware.arm_metrics(
        candidate_frame, candidate_selected, calendar_frame,
        score_kind=score_aware.RAW_RANKING_SCORE, score_column="ranking_score",
    )
    raw_ap = {key: candidate_metrics["probability"][key]
              for key in ("scored", "known", "unknown", "positive_known", "average_precision_known", "pr_auc_definition")}
    # Exact historical RFF behavior: keep the binary-probability block intact.
    # The raw AP is retained separately, because finite sigmoid outputs can tie.
    candidate_metrics["probability"] = score_aware.probability_metrics(candidate_frame)
    observed_episodes = candidate_metrics["confirmed_new_events"]
    if observed_episodes != expected["known_positive_denominator"]:
        raise RFFSavedEvaluationError("RFF_CONFIRMED_NEW_EPISODE_DENOMINATOR_MISMATCH:CANDIDATE_RFF_LOGISTIC")
    arms = {"CANDIDATE_RFF_LOGISTIC": candidate_metrics}
    selected_by_arm = {}
    binary_compatibility = {}
    if set(controls) != set(CONTROL_NAMES):
        raise RFFSavedEvaluationError("RFF_FROZEN_CONTROL_SET_MISMATCH")
    for name in CONTROL_NAMES:
        control_frame = controls[name]["scores"]
        stored_top3 = controls[name]["top3"]
        _require_schema(control_frame, TRUTH_COLUMNS + ["probability"], name=name)
        _require_keys(control_frame, name=name)
        _binary_mask(control_frame, name=name)
        _check_full_metadata(control_frame, truth, name=name)
        _check_dates(control_frame, calendar_frame, name=name)
        stored = control_frame[KEYS + OUTCOMES].sort_values(KEYS, kind="mergesort").reset_index(drop=True)
        reference = truth[KEYS + OUTCOMES].sort_values(KEYS, kind="mergesort").reset_index(drop=True)
        _assert_equal(stored, reference, error=f"RFF_FROZEN_CONTROL_OUTCOMES_CHANGED:{name}")
        selected = score_aware.select_top3(control_frame)
        original_selected = frozen.select_top3(control_frame)
        _assert_equal(selected, original_selected, error=f"RFF_FROZEN_CONTROL_SELECTOR_CHANGED:{name}")
        identity_columns = KEYS + ["rank", "probability"]
        _require_schema(stored_top3, identity_columns, name=f"{name}_top3")
        _require_keys(stored_top3, name=f"{name}_top3")
        identity = lambda frame: frame[identity_columns].sort_values(["session_id", "rank", "code"], kind="mergesort").reset_index(drop=True)
        _assert_equal(identity(selected), identity(stored_top3), error=f"RFF_FROZEN_CONTROL_TOP3_CHANGED:{name}")
        wrapped = score_aware.arm_metrics(control_frame, selected, calendar_frame)
        original = frozen.arm_metrics(control_frame, selected, calendar_frame)
        if not _deep_equal(wrapped, original):
            raise RFFSavedEvaluationError(f"RFF_FROZEN_CONTROL_METRICS_CHANGED:{name}")
        if wrapped["confirmed_new_events"] != observed_episodes:
            raise RFFSavedEvaluationError(f"RFF_CONFIRMED_NEW_EPISODE_DENOMINATOR_MISMATCH:{name}")
        arms[name] = wrapped
        selected_by_arm[name] = selected
        binary_compatibility[name] = True

    paired = {}
    for name in CONTROL_NAMES:
        delta = score_aware.paired_precision(candidate_selected, selected_by_arm[name], calendar_frame["session_id"])
        if delta["denominator"] != expected["selection_slots"]:
            raise RFFSavedEvaluationError(f"RFF_PAIRED_SLOT_DENOMINATOR_MISMATCH:{name}")
        if (len(delta["daily"]) != expected["sessions"]
                or [row["session_id"] for row in delta["daily"]] != list(calendar_frame["session_id"])):
            raise RFFSavedEvaluationError(f"RFF_PAIRED_SESSION_DOMAIN_MISMATCH:{name}")
        paired[name] = delta
    primary = paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["lower"] > 0.0
    practical = paired["FROZEN_BASE34"]["lower"] >= 0.03
    hashes = artifact_sha256 or {}
    return {
        "schema": "F5_FULL64_RFF_LOGISTIC_FULL2024_METRICS_V1",
        "status": "EXPOSED_RETROSPECTIVE_DEVELOPMENT_EVALUATION_RECOVERED",
        "route_id": ROUTE_ID, "execution_id": execution_id, "year": expected["year"],
        "grid_rows": len(candidate_frame), "scoreable_rows": expected["scoreable_rows"],
        "sessions": len(calendar_frame), "selection_slots": expected["selection_slots"],
        "truth_positive_denominator": observed_episodes,
        "confirmed_new_episode_denominator": observed_episodes,
        "known_positive_rows_full_g": int((candidate_frame["y"] == 1).sum()),
        "arms": arms, "paired_precision": paired,
        "development_gates": {
            "paired_lower_vs_plus_gt_zero": bool(primary),
            "paired_lower_vs_base34_ge_003": bool(practical),
            "all_development_gates_pass": bool(primary and practical),
            "development_decision": "DEVELOPMENT_PASS" if primary and practical else "DIRECTION_ONLY",
        },
        "original_promotion_gates": copy.deepcopy(promotion_gates),
        "promotion_decision": "BLOCKED_SINGLE_EXPOSED_YEAR",
        "decision_scope": "EXPOSED_2024_DEVELOPMENT_ONLY_Direction_ONLY_MAX",
        "evidence_ceiling": "DIRECTION_ONLY", "evidence_status": "DIRECTION_ONLY",
        "raw_score_contract": {
            "top3_and_average_precision_score": "RAW_LOGISTIC_DECISION_MARGIN",
            "event_probability": "FITTED_LOGISTIC_SIGMOID", "separate_calibrator": False,
        },
        "ranking_score_diagnostics": {"score_kind": "RAW_LOGISTIC_DECISION_MARGIN", **raw_ap},
        "binary_control_evaluator_outputs_deep_equal_to_original": binary_compatibility,
        "episode_denominator_check": {
            "definition": "FULL_G_FROZEN_HELPER_CONFIRMED_NEW_EVENTS_CODE_SESSION",
            "expected": expected["known_positive_denominator"],
            "observed_by_arm": {name: arm["confirmed_new_events"] for name, arm in arms.items()},
            "all_equal": True, "positive_y_rows_are_not_episode_denominator": True,
        },
        "evaluation_recovery_join_integrity": {
            "accepted_join_worker_sha256": "3ea10757a81207147e5cfb9e68e69750a0579786153e7ce58ccf342a3184058c",
            "full_g_exact_truth_key_domain": True,
            "full_g_key_order_equals_truth": candidate_scores[KEYS].reset_index(drop=True).equals(truth[KEYS].reset_index(drop=True)),
            "candidate_top3_is_unique_full_g_subset": True,
            "persisted_candidate_top3_reselected": False,
            "truth_nan_is_not_used_as_key_coverage_proxy": True,
            "unknown_label_rows_full_g": int(candidate_frame["y"].isna().sum()),
            "unknown_label_rows_candidate_top3": int(candidate_selected["y"].isna().sum()),
        },
        "fit_calls": 0, "fit_call_entered": False, "real_fit_returned_count": 0,
        "predict_calls": 0, "control_fit_calls": 0, "control_predict_calls": 0,
        "calibrator_fit_calls": 0, "model_load_calls": 0, "candidate_model_loaded": False,
        "candidate_scores_sha256": hashes.get("candidate_scores"),
        "candidate_top3_sha256": hashes.get("candidate_top3"),
        "baseline_score_sha256": {name: hashes.get(f"{name}_scores") for name in CONTROL_NAMES},
        "baseline_top3_sha256": {name: hashes.get(f"{name}_top3") for name in CONTROL_NAMES},
        "sealed_forward": False, "oof": False, "probability_calibration": False,
        "safety": dict(SAFETY),
    }
