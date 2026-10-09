#!/usr/bin/env python3
"""No-fit recovery for the already persisted F5 XENDCG 2024 score artifacts.

The original candidate worker's outcome join used the full truth frame's NaN
count as a proxy for key coverage.  That is invalid for a selected Top3 subset.
This isolated evaluator proves key coverage with merge indicators and then
delegates every ranking, paired, and episode calculation to the accepted
score-aware wrapper and frozen F5 metrics helper.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


class EvaluationRecoveryError(RuntimeError):
    pass


KEYS = ["code", "session_id"]
OUTCOME_COLUMNS = ["y", "label_status", "first_exact", "episode_state"]
TRUTH_COLUMNS = KEYS + ["market_date", "scoreable", *OUTCOME_COLUMNS]
SCORE_COLUMNS = KEYS + ["market_date", "scoreable", "ranking_score"]
TOP3_COLUMNS = SCORE_COLUMNS + ["rank"]
CONTROL_SCORE_COLUMNS = KEYS + [
    "market_date", "scoreable", "probability", *OUTCOME_COLUMNS,
]


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json_bytes(value)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return sha256_bytes(raw)


def _require_key_integrity(frame: Any, *, name: str) -> None:
    if not set(KEYS).issubset(frame.columns):
        raise EvaluationRecoveryError(f"KEY_COLUMNS_MISSING:{name}")
    if frame[KEYS].isna().any().any():
        raise EvaluationRecoveryError(f"NULL_KEY:{name}")
    if frame.duplicated(KEYS).any():
        raise EvaluationRecoveryError(f"DUPLICATE_KEY:{name}")


def _binary_mask(frame: Any, *, name: str) -> None:
    import numpy as np

    if "scoreable" not in frame.columns:
        raise EvaluationRecoveryError(f"SCOREABLE_COLUMN_MISSING:{name}")
    values = frame["scoreable"].to_numpy()
    if not np.isin(values, (0, 1, False, True)).all():
        raise EvaluationRecoveryError(f"SCOREABLE_MASK_NOT_BINARY:{name}")


def _assert_outcomes_equal(stored: Any, truth: Any, *, name: str) -> None:
    import pandas as pd

    left = stored.loc[:, KEYS + OUTCOME_COLUMNS].sort_values(KEYS, kind="mergesort").reset_index(drop=True)
    right = truth.loc[:, KEYS + OUTCOME_COLUMNS].sort_values(KEYS, kind="mergesort").reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(
            left, right, check_dtype=False, check_exact=True, check_like=False
        )
    except AssertionError as exc:
        raise EvaluationRecoveryError(f"FROZEN_CONTROL_LABEL_OR_DOMAIN_MISMATCH:{name}") from exc


def _attach_truth(
    score_frame: Any,
    truth: Any,
    *,
    name: str,
    exact_domain: bool,
) -> tuple[Any, dict[str, Any]]:
    """Attach truth by key and prove coverage independently of label missingness."""
    import pandas as pd

    _require_key_integrity(score_frame, name=name)
    _require_key_integrity(truth, name="eval_truth")
    _binary_mask(score_frame, name=name)
    _binary_mask(truth, name="eval_truth")

    joined = score_frame.merge(
        truth.loc[:, KEYS + OUTCOME_COLUMNS],
        on=KEYS,
        how="left",
        validate="one_to_one",
        sort=False,
        indicator="_truth_match",
    )
    score_unmatched = int((joined["_truth_match"] == "left_only").sum())
    if score_unmatched:
        raise EvaluationRecoveryError(f"TRUTH_KEY_MISSING_FOR_FRAME:{name}:{score_unmatched}")

    # Reverse coverage catches extra truth keys for a full G/control grid.
    reverse = truth.loc[:, KEYS].merge(
        score_frame.loc[:, KEYS],
        on=KEYS,
        how="left",
        validate="one_to_one",
        sort=False,
        indicator=True,
    )
    truth_unmatched = int((reverse["_merge"] == "left_only").sum())
    if exact_domain and truth_unmatched:
        raise EvaluationRecoveryError(f"TRUTH_HAS_KEYS_OUTSIDE_FULL_G:{name}:{truth_unmatched}")

    flag_alignment = score_frame.loc[:, KEYS + ["scoreable"]].merge(
        truth.loc[:, KEYS + ["scoreable"]],
        on=KEYS,
        how="left",
        validate="one_to_one",
        sort=False,
        indicator=True,
        suffixes=("_score", "_truth"),
    )
    matched = flag_alignment["_merge"] == "both"
    flag_equal = flag_alignment["scoreable_score"].eq(
        flag_alignment["scoreable_truth"]
    ).fillna(False)
    scoreable_mismatch = int((matched & ~flag_equal).sum())
    if scoreable_mismatch:
        raise EvaluationRecoveryError(
            f"SCOREABILITY_FLAG_MISMATCH_BY_KEY:{name}:{scoreable_mismatch}"
        )

    dates = score_frame.loc[:, KEYS + ["market_date"]].merge(
        truth.loc[:, KEYS + ["market_date"]], on=KEYS, how="left",
        validate="one_to_one", sort=False, suffixes=("_score", "_truth"),
    )
    if dates.isna().any().any() or not dates["market_date_score"].eq(
        dates["market_date_truth"]
    ).all():
        raise EvaluationRecoveryError(f"MARKET_DATE_MISMATCH_BY_KEY:{name}")

    # A legitimate unknown label remains NaN.  It is never treated as a join
    # failure; only the explicit key indicators above decide coverage.
    joined = joined.drop(columns=["_truth_match"])
    evidence = {
        "frame": name,
        "rows": int(len(score_frame)),
        "score_keys_unmatched_in_truth": score_unmatched,
        "truth_keys_unmatched_in_score_frame": truth_unmatched,
        "exact_key_domain": bool(score_unmatched == 0 and (not exact_domain or truth_unmatched == 0)),
        "scoreability_mismatch_rows": scoreable_mismatch,
        "scoreable_flags_match_by_key": True,
        "scoreable_rows": int(score_frame["scoreable"].astype(bool).sum()),
        "label_unknown_rows": int(joined["y"].isna().sum()),
    }
    return joined, evidence


def _assert_top3_matches_grid(top3: Any, full_scores: Any, *, score_column: str) -> None:
    import numpy as np

    _require_key_integrity(top3, name="candidate_top3")
    _require_key_integrity(full_scores, name="candidate_full_g")
    _binary_mask(top3, name="candidate_top3")
    merged = top3.merge(
        full_scores.loc[:, KEYS + ["scoreable", score_column]],
        on=KEYS,
        how="left",
        validate="many_to_one",
        sort=False,
        indicator=True,
        suffixes=("_top3", "_grid"),
    )
    if (merged["_merge"] != "both").any():
        missing = int((merged["_merge"] == "left_only").sum())
        raise EvaluationRecoveryError(f"PERSISTED_TOP3_NOT_SUBSET_OF_FULL_G:{missing}")
    if not merged["scoreable_top3"].eq(merged["scoreable_grid"]).all():
        raise EvaluationRecoveryError("PERSISTED_TOP3_SCOREABLE_FLAG_DIFFERS_FROM_FULL_G")
    if not merged["scoreable_top3"].astype(bool).all():
        raise EvaluationRecoveryError("PERSISTED_TOP3_CONTAINS_UNSCOREABLE_ROW")
    left = merged[f"{score_column}_top3"].to_numpy(dtype=np.float64)
    right = merged[f"{score_column}_grid"].to_numpy(dtype=np.float64)
    if not np.array_equal(left, right, equal_nan=True):
        raise EvaluationRecoveryError("PERSISTED_TOP3_SCORE_DIFFERS_FROM_FULL_G")
    if not np.isfinite(left).all():
        raise EvaluationRecoveryError("PERSISTED_TOP3_SCORE_NOT_FINITE")
    if "rank" not in top3 or top3["rank"].isna().any():
        raise EvaluationRecoveryError("PERSISTED_TOP3_RANK_MISSING")
    if not top3["rank"].isin([1, 2, 3]).all() or top3.duplicated(["session_id", "rank"]).any():
        raise EvaluationRecoveryError("PERSISTED_TOP3_RANK_INVALID")

    # Validate each *saved* pick's order statistic; never create/reselect Top3.
    # Count rows preceding it under the frozen score-desc/code-asc rule.
    # This also checks a saved pick against unselected full-G rows and ties.
    grids = {sid: frame for sid, frame in full_scores.groupby("session_id", sort=False)}
    for sid, picks in top3.groupby("session_id", sort=False):
        if len(picks) != 3:
            raise EvaluationRecoveryError("PERSISTED_TOP3_RANK_SET_NOT_123")
        grid = grids[sid]
        eligible = grid["scoreable"].astype(bool).to_numpy()
        values = grid[score_column].to_numpy(dtype=np.float64)
        codes = grid["code"].astype(str).to_numpy()
        for pick in picks.itertuples(index=False):
            value = float(getattr(pick, score_column))
            preceding = eligible & ((values > value) | ((values == value) & (codes < str(pick.code))))
            if int(preceding.sum()) + 1 != pick.rank:
                raise EvaluationRecoveryError("PERSISTED_TOP3_RANK_NOT_ORDER_STATISTIC")


def _top3_identity(left: Any, right: Any, *, score_column: str) -> bool:
    import pandas as pd

    columns = ["session_id", "code", "rank", score_column]
    if not set(columns).issubset(left.columns) or not set(columns).issubset(right.columns):
        return False
    a = left.loc[:, columns].sort_values(
        ["session_id", "rank", "code"], kind="mergesort"
    ).reset_index(drop=True)
    b = right.loc[:, columns].sort_values(
        ["session_id", "rank", "code"], kind="mergesort"
    ).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(a, b, check_dtype=False, check_exact=True)
        return True
    except AssertionError:
        return False


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
        return set(left) == set(right) and all(
            _deep_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            _deep_equal(a, b) for a, b in zip(left, right)
        )
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


def evaluate_frames(
    *,
    candidate_scores: Any,
    candidate_top3: Any,
    truth: Any,
    calendar: Any,
    controls: Mapping[str, Mapping[str, Any]],
    metrics_module: Any,
    evaluation_contract: Mapping[str, Any],
    execution_id: str,
    artifact_sha256: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run the frozen 2024 metric composition over already bound score frames."""
    import numpy as np

    expected_rows = int(evaluation_contract["grid_rows"])
    expected_scoreable = int(evaluation_contract["scoreable_rows"])
    expected_sessions = int(evaluation_contract["sessions"])
    expected_slots = int(evaluation_contract["selection_slots"])
    # Legacy contract name denotes NEW episodes, NOT rows with y == 1.
    expected_episode_denominator = int(evaluation_contract["known_positive_denominator"])
    if len(candidate_scores) != expected_rows or len(truth) != expected_rows:
        raise EvaluationRecoveryError("FULL_G_OR_TRUTH_ROW_COUNT_MISMATCH")
    if int(candidate_scores["scoreable"].astype(bool).sum()) != expected_scoreable:
        raise EvaluationRecoveryError("FULL_G_SCOREABLE_ROW_COUNT_MISMATCH")
    if int(truth["scoreable"].astype(bool).sum()) != expected_scoreable:
        raise EvaluationRecoveryError("TRUTH_SCOREABLE_ROW_COUNT_MISMATCH")

    truth_y = truth["y"].to_numpy(dtype=np.float64)
    if np.isinf(truth_y).any() or not np.isin(truth_y[np.isfinite(truth_y)], (0.0, 1.0)).all():
        raise EvaluationRecoveryError("TRUTH_LABEL_DOMAIN_INVALID")
    if truth[["label_status", "episode_state", "first_exact"]].isna().any().any():
        raise EvaluationRecoveryError("EVALUATION_OUTCOME_METADATA_MISSING")

    candidate_frame, full_join_evidence = _attach_truth(
        candidate_scores, truth, name="candidate_full_g", exact_domain=True
    )
    _assert_top3_matches_grid(candidate_top3, candidate_scores, score_column="ranking_score")
    candidate_selected, top3_join_evidence = _attach_truth(
        candidate_top3, truth, name="candidate_persisted_top3", exact_domain=False
    )
    if len(candidate_selected) != expected_slots:
        raise EvaluationRecoveryError("CANDIDATE_TOP3_SELECTION_SLOT_COUNT_MISMATCH")
    if int(candidate_selected.groupby("session_id", sort=False).size().min()) != 3 or int(
        candidate_selected.groupby("session_id", sort=False).size().max()
    ) != 3:
        raise EvaluationRecoveryError("CANDIDATE_TOP3_NOT_EXACTLY_THREE_PER_SESSION")
    if candidate_frame["session_id"].nunique() != expected_sessions:
        raise EvaluationRecoveryError("FULL_G_SESSION_COUNT_MISMATCH")

    calendar_frame = calendar.loc[:, ["session_id", "market_date"]].copy()
    if len(calendar_frame) != expected_sessions or calendar_frame["session_id"].duplicated().any():
        raise EvaluationRecoveryError("EVALUATION_CALENDAR_KEY_MISMATCH")
    calendar_sessions = set(calendar_frame["session_id"].astype(int))
    if set(candidate_frame["session_id"].astype(int)) != calendar_sessions:
        raise EvaluationRecoveryError("FULL_G_SESSIONS_DIFFER_FROM_CALENDAR")
    calendar_frame["session_id"] = calendar_frame["session_id"].astype("int64")
    calendar_frame["market_date"] = calendar_frame["market_date"].astype(str)

    for name, frame in (("candidate_full_g", candidate_frame), ("truth", truth),
                        ("candidate_top3", candidate_selected)):
        dated = frame.loc[:, ["session_id", "market_date"]].merge(
            calendar_frame, on="session_id", how="left", validate="many_to_one",
            suffixes=("_frame", "_calendar"),
        )
        if dated.isna().any().any() or not dated["market_date_frame"].eq(
            dated["market_date_calendar"]
        ).all():
            raise EvaluationRecoveryError(f"MARKET_DATE_DIFFERS_FROM_CALENDAR:{name}")

    # Reuse the accepted wrapper's exact raw-score dispatch and frozen helper
    # for all candidate ranking, AP, paired, and episode calculations.
    import score_aware_metrics

    candidate_metrics = score_aware_metrics.arm_metrics(
        candidate_frame,
        candidate_selected,
        calendar_frame,
        score_kind=score_aware_metrics.RAW_RANKING_SCORE,
        score_column="ranking_score",
    )
    observed_episodes = candidate_metrics["confirmed_new_events"]
    if observed_episodes != expected_episode_denominator:
        raise EvaluationRecoveryError(
            "CONFIRMED_NEW_EPISODE_DENOMINATOR_MISMATCH:"
            f"CANDIDATE_XENDCG:{observed_episodes}!={expected_episode_denominator}"
        )
    arms: dict[str, Any] = {"CANDIDATE_XENDCG": candidate_metrics}
    selected_by_arm: dict[str, Any] = {"CANDIDATE_XENDCG": candidate_selected}
    control_scores_by_arm: dict[str, Any] = {}
    binary_compatibility: dict[str, bool] = {}

    for binding_name in ("FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_BASE34"):
        if binding_name not in controls:
            raise EvaluationRecoveryError(f"FROZEN_CONTROL_MISSING:{binding_name}")
        control = controls[binding_name]
        raw_frame = control["scores"]
        if len(raw_frame) != expected_rows:
            raise EvaluationRecoveryError(f"FROZEN_CONTROL_GRID_ROW_COUNT_MISMATCH:{binding_name}")
        _require_key_integrity(raw_frame, name=f"control_{binding_name}")
        if not set(OUTCOME_COLUMNS).issubset(raw_frame.columns):
            raise EvaluationRecoveryError(f"FROZEN_CONTROL_OUTCOME_COLUMNS_MISSING:{binding_name}")
        _assert_outcomes_equal(raw_frame, truth, name=binding_name)
        control_base = raw_frame.drop(columns=OUTCOME_COLUMNS)
        control_frame, control_join_evidence = _attach_truth(
            control_base,
            truth,
            name=f"control_{binding_name}",
            exact_domain=True,
        )
        if not control_join_evidence["scoreable_flags_match_by_key"]:
            raise EvaluationRecoveryError(f"FROZEN_CONTROL_SCOREABILITY_MISMATCH:{binding_name}")
        selected = score_aware_metrics.select_top3(control_frame)
        if not _top3_identity(
            selected, control["top3"], score_column="probability"
        ):
            raise EvaluationRecoveryError(
                f"FROZEN_CONTROL_TOP3_ARTIFACT_DIFFERS_FROM_HELPER:{binding_name}"
            )
        wrapped_metrics = score_aware_metrics.arm_metrics(
            control_frame, selected, calendar_frame
        )
        original_metrics = metrics_module.arm_metrics(
            control_frame, selected, calendar_frame
        )
        if not _deep_equal(wrapped_metrics, original_metrics):
            raise EvaluationRecoveryError(
                f"BINARY_CONTROL_ARM_METRICS_CHANGED:{binding_name}"
            )
        if original_metrics["confirmed_new_events"] != observed_episodes:
            raise EvaluationRecoveryError(
                f"CONFIRMED_NEW_EPISODE_DENOMINATOR_MISMATCH:{binding_name}"
            )
        arms[binding_name] = wrapped_metrics
        selected_by_arm[binding_name] = selected
        control_scores_by_arm[binding_name] = control_frame
        binary_compatibility[binding_name] = True
        if binding_name == "FROZEN_UNWEIGHTED_PLUS_PATH":
            full_join_evidence["control_plus_path_full_g_join"] = control_join_evidence
        else:
            full_join_evidence["control_base34_full_g_join"] = control_join_evidence

    paired: dict[str, Any] = {}
    for control_name in ("FROZEN_UNWEIGHTED_PLUS_PATH", "FROZEN_BASE34"):
        delta = score_aware_metrics.paired_precision(
            candidate_selected,
            selected_by_arm[control_name],
            calendar_frame["session_id"],
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
    if paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["denominator"] != expected_slots:
        raise EvaluationRecoveryError("PRIMARY_PAIRED_DENOMINATOR_MISMATCH")

    metrics_doc = {
        "schema": "F5_FULL64_XENDCG_CANDIDATE_FULL2024_METRICS_V1",
        "status": "EXPOSED_RETROSPECTIVE_DEVELOPMENT_EVALUATION_RECOVERED",
        "execution_id": execution_id,
        "year": int(evaluation_contract["year"]),
        "grid_rows": int(len(candidate_frame)),
        "scoreable_rows": int(candidate_frame["scoreable"].astype(bool).sum()),
        "sessions": int(len(calendar_frame)),
        "selection_slots": expected_slots,
        "truth_positive_denominator": observed_episodes,  # backward-compatible episode alias
        "confirmed_new_episode_denominator": observed_episodes,
        "known_positive_rows_full_g": int((candidate_frame["y"] == 1).sum()),
        "episode_denominator_check": {
            "definition": "FULL_G_FROZEN_HELPER_CONFIRMED_NEW_EVENTS_CODE_SESSION",
            "expected": expected_episode_denominator,
            "observed_by_arm": {name: arm["confirmed_new_events"] for name, arm in arms.items()},
            "all_equal": True,
            "positive_y_rows_are_not_episode_denominator": True,
        },
        "arms": arms,
        "paired_precision": paired,
        "primary_metric": {
            "name": "paired lower CANDIDATE minus frozen UNWEIGHTED_PLUS_PATH",
            "control": "FROZEN_UNWEIGHTED_PLUS_PATH",
            "lower": paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["lower"],
            "upper": paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["upper"],
            "denominator": paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["denominator"],
            "pass_threshold": "> 0",
            "development_primary_pass": bool(paired["FROZEN_UNWEIGHTED_PLUS_PATH"]["lower"] > 0),
            "evaluation_purpose": "REPORT_ONLY_NO_BREAKTHROUGH_OR_PROMOTION_GATE_CHANGED",
            "promotion_authorized": False,
        },
        "binary_control_evaluator_outputs_deep_equal_to_original": binary_compatibility,
        "raw_score_contract": {
            "score_kind": "RAW_RANKING_MARGIN_NOT_EVENT_PROBABILITY",
            "AP_uses_raw_scores": True,
            "brier_logloss_calibration": None,
            "probability_metrics_reason": "NOT_EVALUATED_NO_EVENT_PROBABILITY_MODEL",
        },
        "evaluation_recovery_join_integrity": {
            "full_g_exact_truth_key_domain": full_join_evidence["exact_key_domain"],
            "full_g_key_order_equals_truth": bool(
                candidate_scores.loc[:, KEYS].reset_index(drop=True).equals(
                    truth.loc[:, KEYS].reset_index(drop=True)
                )
            ),
            "candidate_full_g": full_join_evidence,
            "candidate_persisted_top3": top3_join_evidence,
            "candidate_top3_is_unique_full_g_subset": True,
            "truth_nan_is_not_used_as_key_coverage_proxy": True,
            "unknown_label_rows_full_g": int(candidate_frame["y"].isna().sum()),
            "unknown_label_rows_candidate_top3": int(candidate_selected["y"].isna().sum()),
        },
        "fit_calls": 0,
        "fit_call_entered": False,
        "real_fit_returned_count": 0,
        "predict_calls": 0,
        "control_fit_calls": 0,
        "control_predict_calls": 0,
        "calibrator_fit_calls": 0,
        "candidate_model_loaded": False,
        "candidate_scores_sha256": (artifact_sha256 or {}).get("candidate_scores"),
        "candidate_top3_sha256": (artifact_sha256 or {}).get("candidate_top3"),
        "baseline_score_sha256": {
            name: (artifact_sha256 or {}).get(f"{name}_scores") for name in controls
        },
        "baseline_top3_sha256": {
            name: (artifact_sha256 or {}).get(f"{name}_top3") for name in controls
        },
        "sealed_forward": False,
        "oof": False,
        "probability_calibration": False,
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    return metrics_doc


def _read_csv_snapshot(raw: bytes, *, name: str, usecols: list[str], string_code: bool = True):
    import pandas as pd

    dtype = {"code": "string"} if string_code else None
    try:
        return pd.read_csv(
            io.BytesIO(raw), compression="gzip", usecols=usecols, dtype=dtype
        )
    except Exception as exc:
        raise EvaluationRecoveryError(
            f"BOUND_GZIP_CSV_PARSE_FAILED:{name}:{type(exc).__name__}"
        ) from exc


def run_saved_evaluation(payload: Mapping[str, Any]) -> None:
    """Spawn target: hash exact bound bytes, decode frozen inputs, write METRICS."""
    output_root = Path(payload["output_root"])
    start_receipt_path = Path(payload["start_receipt_path"])
    expected_start_sha = str(payload["start_receipt_sha256"])
    if not start_receipt_path.is_file() or sha256_file(start_receipt_path) != expected_start_sha:
        raise EvaluationRecoveryError("EVALUATION_START_RECEIPT_SNAPSHOT_MISMATCH")
    if start_receipt_path.parent.resolve() != output_root.resolve():
        raise EvaluationRecoveryError("EVALUATION_START_RECEIPT_OUTPUT_ROOT_MISMATCH")
    if {item.name for item in output_root.iterdir()} != {start_receipt_path.name}:
        raise EvaluationRecoveryError("EVALUATION_OUTPUT_ROOT_NOT_EMPTY_NO_REENTRY")

    status_path = output_root / "EVALUATION_WORKER_STATUS.json"
    truth_values_decoded = False
    try:
        # Validate every source file before decoding any evaluation input.
        for name, item in payload["code_files"].items():
            path = Path(item["path"])
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                raise EvaluationRecoveryError(f"EVALUATION_SOURCE_SHA_MISMATCH:{name}")
        code_manifest = json.dumps(
            dict(payload["code_files"]),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if sha256_bytes(code_manifest) != payload["code_sha256"]:
            raise EvaluationRecoveryError("EVALUATION_CODE_MANIFEST_SHA_MISMATCH")
        for name, item in payload["executable_helpers"].items():
            path = Path(item["path"])
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                raise EvaluationRecoveryError(f"EVALUATION_HELPER_SHA_MISMATCH:{name}")

        snapshots: dict[str, bytes] = {}
        observed: dict[str, str] = {}
        # Identity-only artifacts are streamed as opaque bytes. No model/array
        # deserialization, and no new prediction from these files, is allowed.
        identity_files = payload.get("identity_only_files", {})
        if set(identity_files) != {"candidate_model", "candidate_raw_scores"}:
            raise EvaluationRecoveryError("IDENTITY_ONLY_SCOPE_MISMATCH")
        for name, item in identity_files.items():
            path = Path(item["path"])
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                raise EvaluationRecoveryError(f"IDENTITY_ONLY_SHA_MISMATCH:{name}")
            if "bytes" in item and path.stat().st_size != item["bytes"]:
                raise EvaluationRecoveryError(f"IDENTITY_ONLY_SIZE_MISMATCH:{name}")
            observed[name] = item["sha256"]
        expected_names = {
            "candidate_scores", "candidate_top3", "eval_meta", "eval_calendar",
            "FROZEN_BASE34_scores", "FROZEN_BASE34_top3",
            "FROZEN_UNWEIGHTED_PLUS_PATH_scores", "FROZEN_UNWEIGHTED_PLUS_PATH_top3",
            "candidate_run_receipt", "candidate_worker_status", "candidate_fit_receipt",
            "candidate_terminal_receipt", "prediction_seal", "eval_truth_read_start",
            "join_diagnostic_result", "join_diagnostic_terminal_receipt",
        }
        if set(payload["input_files"]) != expected_names:
            raise EvaluationRecoveryError("EVALUATION_INPUT_SCOPE_MISMATCH")
        for name, item in payload["input_files"].items():
            path = Path(item["path"])
            if not path.is_file():
                raise EvaluationRecoveryError(f"EVALUATION_INPUT_MISSING:{name}")
            raw = path.read_bytes()
            digest = sha256_bytes(raw)
            if digest != item["sha256"]:
                raise EvaluationRecoveryError(f"EVALUATION_INPUT_SHA_MISMATCH:{name}:{digest}")
            snapshots[name] = raw
            observed[name] = digest

        def read_json(name: str) -> dict[str, Any]:
            value = json.loads(snapshots[name].decode("utf-8"))
            if not isinstance(value, dict):
                raise EvaluationRecoveryError(f"EVALUATION_INPUT_JSON_NOT_OBJECT:{name}")
            return value

        previous_run = read_json("candidate_run_receipt")
        previous_status = read_json("candidate_worker_status")
        previous_fit = read_json("candidate_fit_receipt")
        previous_terminal = read_json("candidate_terminal_receipt")
        prediction_seal = read_json("prediction_seal")
        truth_read_marker = read_json("eval_truth_read_start")
        diagnostic = read_json("join_diagnostic_result")
        diagnostic_terminal = read_json("join_diagnostic_terminal_receipt")
        if (
            previous_run.get("execution_id") != payload["candidate_execution_id"]
            or previous_terminal.get("execution_id") != payload["candidate_execution_id"]
            or previous_status.get("error") != "CANDIDATE_TRUTH_JOIN_DOMAIN_MISMATCH"
            or previous_fit.get("status") != "FIT_COMPLETED"
            or previous_fit.get("real_fit_returned_count") != 1
            or previous_run.get("real_fit_returned_count") != 1
            or previous_run.get("predict_calls") != 3
            or prediction_seal.get("status") != "PREDICTION_FROZEN_BEFORE_EVALUATION_TRUTH_READ"
            or truth_read_marker.get("first_eval_truth_decode_after_prediction_seal") is not True
            or diagnostic.get("status") != "DIAGNOSTIC_COMPLETE_NO_METRICS"
            or diagnostic_terminal.get("terminal_status") != "PASS"
        ):
            raise EvaluationRecoveryError("FROZEN_CANDIDATE_FAILURE_OR_SEAL_EVIDENCE_MISMATCH")

        if previous_fit.get("model_sha256") != observed["candidate_model"]:
            raise EvaluationRecoveryError("SAVED_MODEL_FIT_RECEIPT_SHA_MISMATCH")
        for name, field in (
            ("candidate_scores", "candidate_scores_sha256"),
            ("candidate_top3", "candidate_top3_sha256"),
            ("candidate_raw_scores", "candidate_raw_scores_sha256"),
        ):
            if prediction_seal.get(field) != observed[name]:
                raise EvaluationRecoveryError(f"PREDICTION_SEAL_ARTIFACT_SHA_MISMATCH:{name}")
        if any(doc.get("execution_id") != payload["candidate_execution_id"]
               for doc in (previous_fit, prediction_seal, truth_read_marker)):
            raise EvaluationRecoveryError("FROZEN_CANDIDATE_RECEIPT_EXECUTION_ID_MISMATCH")
        if diagnostic.get("candidate_execution_id") != payload["candidate_execution_id"]:
            raise EvaluationRecoveryError("JOIN_DIAGNOSTIC_CANDIDATE_ID_MISMATCH")
        if diagnostic_terminal.get("diagnostic_result_sha256") != observed["join_diagnostic_result"]:
            raise EvaluationRecoveryError("JOIN_DIAGNOSTIC_TERMINAL_SHA_MISMATCH")
        for name, expected_sha in diagnostic.get("worker_result", {}).get("artifact_sha256_verified", {}).items():
            if name in observed and observed[name] != expected_sha:
                raise EvaluationRecoveryError(f"JOIN_DIAGNOSTIC_INPUT_SHA_MISMATCH:{name}")
        if any(previous_run.get(name) != 0 for name in
               ("control_fit_calls", "control_predict_calls", "calibrator_fit_calls")):
            raise EvaluationRecoveryError("FROZEN_CONTROL_CALL_COUNTS_MISMATCH")
        if (prediction_seal.get("score_column") != "ranking_score"
                or prediction_seal.get("score_kind") != "RAW_RANKING_MARGIN_NOT_EVENT_PROBABILITY"
                or prediction_seal.get("score_transform") is not None
                or prediction_seal.get("evaluation_label_values_decoded") is not False):
            raise EvaluationRecoveryError("PREDICTION_SEAL_SCORE_SEMANTICS_MISMATCH")
        for field, contract_field in (("grid_rows", "grid_rows"), ("scoreable_rows", "scoreable_rows"),
                                      ("evaluation_sessions", "sessions")):
            if prediction_seal.get(field) != payload["evaluation_contract"][contract_field]:
                raise EvaluationRecoveryError(f"PREDICTION_SEAL_DOMAIN_MISMATCH:{field}")

        metrics_path = payload.get("score_aware_metrics_path")
        metrics_sha = payload.get("score_aware_metrics_sha256")
        if not metrics_path or sha256_file(Path(metrics_path)) != metrics_sha:
            raise EvaluationRecoveryError("SCORE_AWARE_METRICS_SOURCE_SHA_MISMATCH")
        metrics_source_parent = str(Path(metrics_path).resolve().parent)
        if metrics_source_parent not in sys.path:
            sys.path.insert(0, metrics_source_parent)
        import score_aware_metrics

        if Path(score_aware_metrics.__file__).resolve() != Path(metrics_path).resolve():
            raise EvaluationRecoveryError("SCORE_AWARE_METRICS_IMPORT_PATH_MISMATCH")
        original_metrics = score_aware_metrics.frozen_metrics()

        # The seal and the durable evaluation-truth marker are verified before
        # decoding label values from eval_meta.
        write_json_exclusive(output_root / "EVALUATION_TRUTH_READ_START.json", {
            "schema": "F5_FULL64_XENDCG_EVALUATION_RECOVERY_TRUTH_READ_START_V1",
            "execution_id": payload["execution_id"],
            "candidate_execution_id": payload["candidate_execution_id"],
            "prediction_seal_sha256": observed["prediction_seal"],
            "prior_truth_read_marker_sha256": observed["eval_truth_read_start"],
            "label_values_decoded": False,
            "label_values_decode_started": True,
            "source": "SAME_FROZEN_2024_EVAL_META",
        })

        candidate_scores = _read_csv_snapshot(
            snapshots["candidate_scores"], name="candidate_scores", usecols=SCORE_COLUMNS
        )
        candidate_top3 = _read_csv_snapshot(
            snapshots["candidate_top3"], name="candidate_top3", usecols=TOP3_COLUMNS
        )
        truth = _read_csv_snapshot(
            snapshots["eval_meta"], name="eval_meta", usecols=TRUTH_COLUMNS
        )
        # The worker status is the evidence source for whether label values
        # were actually decoded. The durable READ_START marker only records
        # that decoding was about to begin; it is not proof of successful decode.
        truth_values_decoded = True
        calendar = _read_csv_snapshot(
            snapshots["eval_calendar"],
            name="eval_calendar",
            usecols=["session_id", "market_date"],
            string_code=False,
        )
        control_map: dict[str, dict[str, Any]] = {}
        for name in ("FROZEN_BASE34", "FROZEN_UNWEIGHTED_PLUS_PATH"):
            control_map[name] = {
                "scores": _read_csv_snapshot(
                    snapshots[f"{name}_scores"],
                    name=f"{name}_scores",
                    usecols=CONTROL_SCORE_COLUMNS,
                ),
                "top3": _read_csv_snapshot(
                    snapshots[f"{name}_top3"],
                    name=f"{name}_top3",
                    usecols=KEYS + ["rank", "probability"],
                ),
            }

        metrics_doc = evaluate_frames(
            candidate_scores=candidate_scores,
            candidate_top3=candidate_top3,
            truth=truth,
            calendar=calendar,
            controls=control_map,
            metrics_module=original_metrics,
            evaluation_contract=payload["evaluation_contract"],
            execution_id=str(payload["execution_id"]),
            artifact_sha256=observed,
        )
        metrics_doc["synthetic_only"] = bool(payload.get("synthetic_only", False))
        metrics_sha_value = write_json_exclusive(output_root / "METRICS.json", metrics_doc)
        result_doc = {
            "schema": "F5_FULL64_XENDCG_EVALUATION_RECOVERY_RESULT_V1",
            "synthetic_only": bool(payload.get("synthetic_only", False)),
            "status": "EXPOSED_RETROSPECTIVE_DEVELOPMENT_EVALUATION_RECOVERED",
            "execution_id": payload["execution_id"],
            "candidate_execution_id": payload["candidate_execution_id"],
            "run_spec_sha256": payload["run_spec_sha256"],
            "input_binding_sha256": payload["input_binding_sha256"],
            "source_code_sha256": payload["code_sha256"],
            "input_sha256": observed,
            "metrics_sha256": metrics_sha_value,
            "truth_access": "EVAL_LABELS_DECODED_AFTER_SAVED_PREDICTION_SEAL",
            "sealed_status": "EXPOSED_2024_POST_SEAL_EVALUATION",
            "candidate_model_loaded": False,
            "fit_calls": 0,
            "fit_call_entered": False,
            "real_fit_returned_count": 0,
            "predict_calls": 0,
            "control_fit_calls": 0,
            "control_predict_calls": 0,
            "calibrator_fit_calls": 0,
            "metrics_computed": True,
            "safety": {
                "research_only": True,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        }
        result_sha = write_json_exclusive(
            output_root / "EVALUATION_RESULT_RECEIPT.json", result_doc
        )
        status_doc = {
            "schema": "F5_FULL64_XENDCG_EVALUATION_RECOVERY_WORKER_STATUS_V1",
            "status": result_doc["status"],
            "execution_id": payload["execution_id"],
            "fit_calls": 0,
            "fit_call_entered": False,
            "real_fit_returned_count": 0,
            "predict_calls": 0,
            "control_fit_calls": 0,
            "control_predict_calls": 0,
            "calibrator_fit_calls": 0,
            "candidate_model_loaded": False,
            "evaluation_label_values_decoded": True,
            "truth_access": "EVAL_LABELS_DECODED_AFTER_SAVED_PREDICTION_SEAL",
            "sealed_status": "EXPOSED_2024_POST_SEAL_EVALUATION",
            "metrics_sha256": metrics_sha_value,
            "result_sha256": result_sha,
        }
        write_json_exclusive(status_path, status_doc)
    except BaseException as exc:
        if not status_path.exists():
            try:
                write_json_exclusive(status_path, {
                    "schema": "F5_FULL64_XENDCG_EVALUATION_RECOVERY_WORKER_STATUS_V1",
                    "status": "CANNOT_CONFIRM",
                    "execution_id": payload["execution_id"],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "fit_calls": 0,
                    "fit_call_entered": False,
                    "real_fit_returned_count": 0,
                    "predict_calls": 0,
                    "control_fit_calls": 0,
                    "control_predict_calls": 0,
                    "calibrator_fit_calls": 0,
                    "candidate_model_loaded": False,
                    "evaluation_label_values_decoded": truth_values_decoded,
                    "truth_access": (
                        "EVAL_LABELS_DECODED_AFTER_SAVED_PREDICTION_SEAL"
                        if truth_values_decoded else "EVAL_LABELS_NOT_DECODED"
                    ),
                    "sealed_status": (
                        "EXPOSED_2024_POST_SEAL_EVALUATION"
                        if truth_values_decoded else "SAVED_PREDICTION_SEAL_UNCHANGED_NO_TRUTH_DECODE"
                    ),
                })
            except BaseException:
                pass
        raise
