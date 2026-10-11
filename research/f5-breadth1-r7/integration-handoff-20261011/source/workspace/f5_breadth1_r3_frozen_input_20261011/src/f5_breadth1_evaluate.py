"""Saved candidate artifact evaluation with report-only diagnostics."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from f5_breadth1_budget import (
    BATCH_ROOT,
    BREADTH1OfficialActionAdapter,
    VerifiedActionContext,
    VerifiedActionRelease,
)
from f5_breadth1_core import (
    GATES, ArtifactContractError, load_bound_csv_snapshot, load_csv_snapshot, load_frozen_metrics,
    strict_integer_values, validate_calendar_date_map, validate_exact_top3,
    validate_saved_top3_keys, validate_top3_scores, write_json_exclusive,
)
from f5_breadth1_inputs import AdmissionBlocked


class EvaluationError(ValueError):
    pass


class RealTruthBudgetUnavailable(AdmissionBlocked):
    pass


def evaluate_synthetic_artifacts(
    *,
    candidate_scores: pd.DataFrame,
    candidate_top3: pd.DataFrame,
    plus_path_top3: pd.DataFrame,
    base34_top3: pd.DataFrame,
    synthetic_truth: pd.DataFrame,
    calendar: pd.DataFrame,
    metrics: Any,
) -> dict[str, Any]:
    """Use saved Top3 artifacts; no baseline or candidate is reselected."""

    return _evaluate_frames(
        candidate_scores=candidate_scores,
        candidate_top3=candidate_top3,
        plus_path_top3=plus_path_top3,
        base34_top3=base34_top3,
        truth=synthetic_truth,
        calendar=calendar,
        metrics=metrics,
        synthetic=True,
        truth_access="SYNTHETIC_FIXTURE_ONLY",
        truth_decode_calls=0,
        sealed_status="NOT_ENTERED",
    )


def evaluate_real_truth_once(
    *,
    release: VerifiedActionRelease | None,
    budget_adapter: BREADTH1OfficialActionAdapter | None,
    candidate_scores_path: Path | None,
    candidate_scores_sha256: str | None,
    candidate_top3_path: Path | None,
    candidate_top3_sha256: str | None,
    plus_path_scores_path: Path | None,
    plus_path_scores_sha256: str | None,
    plus_path_top3_path: Path | None,
    plus_path_top3_sha256: str | None,
    base34_scores_path: Path | None,
    base34_scores_sha256: str | None,
    base34_top3_path: Path | None,
    base34_top3_sha256: str | None,
    calendar_path: Path | None,
    calendar_sha256: str | None,
    report_path: Path | None,
) -> dict[str, Any]:
    """Read the five bound control/calendar snapshots and evaluate under one debit.

    The five control/calendar files, candidate score/Top3 files, truth column
    projection, metric calls, and gate calculation are all inside the official
    one-shot truth_decode callback.  The current batch has no real release or
    admission binding and is blocked before any of those artifact reads.
    """

    if (
        release is None or budget_adapter is None
        or candidate_scores_path is None or candidate_scores_sha256 is None
        or candidate_top3_path is None or candidate_top3_sha256 is None
        or plus_path_scores_path is None or plus_path_scores_sha256 is None
        or plus_path_top3_path is None or plus_path_top3_sha256 is None
        or base34_scores_path is None or base34_scores_sha256 is None
        or base34_top3_path is None or base34_top3_sha256 is None
        or calendar_path is None or calendar_sha256 is None or report_path is None
    ):
        raise RealTruthBudgetUnavailable("REAL_TRUTH_RELEASE_FIVE_CONTROL_SNAPSHOTS_AND_CANDIDATE_SNAPSHOTS_REQUIRED")
    if budget_adapter.synthetic:
        raise RealTruthBudgetUnavailable("REAL_TRUTH_EVALUATION_REQUIRES_OFFICIAL_REAL_ACTION_ADAPTER")
    try:
        action_context = budget_adapter.verify_real_action_context(release)
        release_value = dict(action_context.release_value)
    except Exception as exc:
        raise RealTruthBudgetUnavailable(f"REAL_TRUTH_RELEASE_INVALID:{type(exc).__name__}") from exc
    _require_real_evaluation_binding(
        action_context.input_binding_value,
        release_value,
        report_path=report_path,
        candidate_scores_path=candidate_scores_path,
        candidate_scores_sha256=candidate_scores_sha256,
        candidate_top3_path=candidate_top3_path,
        candidate_top3_sha256=candidate_top3_sha256,
        plus_path_scores_path=plus_path_scores_path,
        plus_path_scores_sha256=plus_path_scores_sha256,
        plus_path_top3_path=plus_path_top3_path,
        plus_path_top3_sha256=plus_path_top3_sha256,
        base34_scores_path=base34_scores_path,
        base34_scores_sha256=base34_scores_sha256,
        base34_top3_path=base34_top3_path,
        base34_top3_sha256=base34_top3_sha256,
        calendar_path=calendar_path,
        calendar_sha256=calendar_sha256,
    )

    # Real evaluation cannot accept a caller-supplied metric implementation.
    # It always loads the exact frozen helper and transitive dependencies.
    metrics = load_frozen_metrics()

    def _read_and_evaluate(context: VerifiedActionContext) -> dict[str, Any]:
        # The official debit is durable before any candidate, control,
        # calendar, or truth-bearing bytes are opened.  Failure stays consumed.
        if (
            context.contract_sha256 != action_context.contract_sha256
            or context.input_binding_sha256 != action_context.input_binding_sha256
            or context.release_sha256 != action_context.release_sha256
        ):
            raise RealTruthBudgetUnavailable("REAL_TRUTH_ACTION_CONTEXT_CHANGED_AFTER_PREFLIGHT")
        candidate_scores_frame, _, _ = _load_required_snapshot(candidate_scores_path, candidate_scores_sha256)
        candidate_top3_frame, _, _ = _load_required_snapshot(candidate_top3_path, candidate_top3_sha256)
        plus_scores_frame, _, _ = _load_bound_control_scores(plus_path_scores_path, plus_path_scores_sha256)
        base_scores_frame, _, _ = _load_bound_control_scores(base34_scores_path, base34_scores_sha256)
        plus_top3_frame, _, _ = _load_bound_control_top3(plus_path_top3_path, plus_path_top3_sha256)
        base_top3_frame, _, _ = _load_bound_control_top3(base34_top3_path, base34_top3_sha256)
        calendar_frame, _, _ = _load_bound_csv(calendar_path, calendar_sha256)

        identity_columns = ("session_id", "code", "scoreable", "y", "episode_state", "first_exact")
        _require_columns(plus_scores_frame, identity_columns, "PLUS_PATH scores")
        _require_columns(base_scores_frame, identity_columns, "BASE34 scores")
        plus_identity = plus_scores_frame.loc[:, list(identity_columns)].copy()
        base_identity = base_scores_frame.loc[:, list(identity_columns)].copy()
        plus_identity["session_id"] = strict_integer_values(plus_identity["session_id"], "PLUS_PATH.session_id")
        base_identity["session_id"] = strict_integer_values(base_identity["session_id"], "BASE34.session_id")
        plus_identity["code"] = plus_identity["code"].astype(str)
        base_identity["code"] = base_identity["code"].astype(str)
        if not plus_identity.equals(base_identity):
            raise EvaluationError("PLUS_PATH and BASE34 control score identities/truth differ")
        candidate_identity_columns = ("session_id", "code", "scoreable")
        _require_columns(candidate_scores_frame, (*candidate_identity_columns, "probability"), "candidate scores")
        candidate_identity = candidate_scores_frame.loc[:, list(candidate_identity_columns)].copy()
        candidate_identity["session_id"] = strict_integer_values(candidate_identity["session_id"], "candidate.session_id")
        candidate_identity["code"] = candidate_identity["code"].astype(str)
        plus_candidate_identity = plus_identity.loc[:, list(candidate_identity_columns)].copy()
        if not candidate_identity.equals(plus_candidate_identity):
            raise EvaluationError("candidate score key/mask/order differs from frozen control evaluation domain")

        truth_frame = plus_identity.loc[:, ["session_id", "code", "y", "episode_state", "first_exact"]].copy()
        report_value = _evaluate_frames(
            candidate_scores=candidate_scores_frame,
            candidate_top3=candidate_top3_frame,
            plus_path_top3=plus_top3_frame,
            base34_top3=base_top3_frame,
            truth=truth_frame,
            calendar=calendar_frame,
            metrics=metrics,
            synthetic=False,
            truth_access="OPENED_EXPOSED_HISTORY",
            truth_decode_calls=1,
            sealed_status=str(context.release_value["sealed_status"]),
        )
        report_value["input_binding_sha256"] = context.input_binding_sha256
        report_value["action_budget_release_sha256"] = context.release_sha256
        report_sha = write_json_exclusive(report_value, report_path)
        report_value["sealed_report_path"] = str(report_path)
        report_value["sealed_report_sha256"] = report_sha
        return report_value

    try:
        report = budget_adapter.execute_once(
            "truth_decode",
            verified_context_callback=_read_and_evaluate,
            release=release,
            terminal_artifact_paths=(
                candidate_scores_path,
                candidate_top3_path,
                plus_path_scores_path,
                plus_path_top3_path,
                base34_scores_path,
                base34_top3_path,
                calendar_path,
                report_path,
            ),
        )
    except Exception as exc:
        raise RealTruthBudgetUnavailable(f"REAL_TRUTH_ACTION_NOT_COMPLETED:{type(exc).__name__}") from exc
    return report


def _load_bound_control_scores(path: Path, expected_sha256: str) -> tuple[pd.DataFrame, str, int]:
    try:
        # This matches the frozen control-score parser: pandas default float
        # parsing and explicit string codes, from the SHA-checked byte snapshot.
        return load_bound_csv_snapshot(path, expected_sha256, dtype={"code": str})
    except (OSError, ArtifactContractError, ValueError) as exc:
        raise EvaluationError(f"control score snapshot is invalid: {Path(path).name}") from exc


def _load_bound_control_top3(path: Path, expected_sha256: str) -> tuple[pd.DataFrame, str, int]:
    try:
        # Controls are read only for fixed membership keys; their saved choice
        # is never recomputed from control scores.
        return load_bound_csv_snapshot(
            path,
            expected_sha256,
            dtype={"code": str},
            usecols=("session_id", "code"),
        )
    except (OSError, ArtifactContractError, ValueError) as exc:
        raise EvaluationError(f"control Top3 key snapshot is invalid: {Path(path).name}") from exc


def _load_bound_csv(path: Path, expected_sha256: str) -> tuple[pd.DataFrame, str, int]:
    try:
        return load_bound_csv_snapshot(path, expected_sha256)
    except (OSError, ArtifactContractError, ValueError) as exc:
        raise EvaluationError(f"calendar snapshot is invalid: {Path(path).name}") from exc


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise EvaluationError(f"{label} missing columns: {missing}")


def _require_real_evaluation_binding(
    input_binding: dict[str, Any] | Any,
    release: dict[str, Any],
    *,
    report_path: Path,
    candidate_scores_path: Path,
    candidate_scores_sha256: str,
    candidate_top3_path: Path,
    candidate_top3_sha256: str,
    plus_path_scores_path: Path,
    plus_path_scores_sha256: str,
    plus_path_top3_path: Path,
    plus_path_top3_sha256: str,
    base34_scores_path: Path,
    base34_scores_sha256: str,
    base34_top3_path: Path,
    base34_top3_sha256: str,
    calendar_path: Path,
    calendar_sha256: str,
) -> None:
    try:
        resolved_report = Path(report_path).resolve()
        resolved_report.relative_to(BATCH_ROOT.resolve())
    except ValueError as exc:
        raise RealTruthBudgetUnavailable("REAL_EVALUATION_REPORT_MUST_STAY_INSIDE_NEW_BATCH") from exc
    if resolved_report.exists():
        raise RealTruthBudgetUnavailable("REAL_EVALUATION_REPORT_ALREADY_EXISTS_NO_OVERWRITE")
    bound = input_binding.get("evaluation_artifacts") if isinstance(input_binding, dict) else None
    if not isinstance(bound, dict):
        raise RealTruthBudgetUnavailable("REAL_EVALUATION_INPUT_BINDING_MISSING")
    supplied = {
        "PLUS_PATH_scores": (plus_path_scores_path, plus_path_scores_sha256, "CONTROL_SCORE_PANDAS_DEFAULT_CODE_STRING"),
        "PLUS_PATH_top3": (plus_path_top3_path, plus_path_top3_sha256, "CONTROL_TOP3_KEY_ONLY_PANDAS_DEFAULT_CODE_STRING"),
        "BASE34_scores": (base34_scores_path, base34_scores_sha256, "CONTROL_SCORE_PANDAS_DEFAULT_CODE_STRING"),
        "BASE34_top3": (base34_top3_path, base34_top3_sha256, "CONTROL_TOP3_KEY_ONLY_PANDAS_DEFAULT_CODE_STRING"),
        "calendar": (calendar_path, calendar_sha256, "CALENDAR_PANDAS_DEFAULT"),
    }
    if set(bound) != set(supplied):
        raise RealTruthBudgetUnavailable("REAL_EVALUATION_INPUT_BINDING_FILE_SET_MISMATCH")
    for name, (path, digest, parser_id) in supplied.items():
        item = bound.get(name)
        if not isinstance(item, dict):
            raise RealTruthBudgetUnavailable(f"REAL_EVALUATION_INPUT_BINDING_INVALID:{name}")
        if (
            item.get("path") != str(Path(path).resolve())
            or item.get("sha256") != digest
            or item.get("parser_id") != parser_id
        ):
            raise RealTruthBudgetUnavailable(f"REAL_EVALUATION_INPUT_BINDING_MISMATCH:{name}")

    candidate_artifacts = release.get("candidate_artifacts")
    if not isinstance(candidate_artifacts, dict):
        raise RealTruthBudgetUnavailable("REAL_CANDIDATE_SCORE_SEAL_MISSING_FROM_TRUTH_RELEASE")
    for name, path, digest in (
        ("candidate_scores", candidate_scores_path, candidate_scores_sha256),
        ("candidate_top3", candidate_top3_path, candidate_top3_sha256),
    ):
        item = candidate_artifacts.get(name)
        if not isinstance(item, dict) or (
            item.get("path") != str(Path(path).resolve()) or item.get("sha256") != digest
        ):
            raise RealTruthBudgetUnavailable(f"REAL_CANDIDATE_SCORE_SEAL_MISMATCH:{name}")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _load_required_snapshot(path: Path, expected_sha256: str) -> tuple[pd.DataFrame, str, int]:
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise EvaluationError("saved artifact SHA256 is missing or invalid")
    try:
        return load_csv_snapshot(path, expected_sha256)
    except (OSError, ArtifactContractError, ValueError) as exc:
        raise EvaluationError(f"saved artifact snapshot is invalid: {Path(path).name}") from exc


def _evaluate_frames(
    *,
    candidate_scores: pd.DataFrame,
    candidate_top3: pd.DataFrame,
    plus_path_top3: pd.DataFrame,
    base34_top3: pd.DataFrame,
    truth: pd.DataFrame,
    calendar: pd.DataFrame,
    metrics: Any,
    synthetic: bool,
    truth_access: str,
    truth_decode_calls: int,
    sealed_status: str,
) -> dict[str, Any]:
    if not callable(getattr(metrics, "arm_metrics", None)) or not callable(
        getattr(metrics, "paired_precision", None)
    ):
        raise EvaluationError("frozen metrics helper interface is incomplete")
    calendar = calendar.copy()
    calendar["session_id"] = strict_integer_values(calendar["session_id"], "calendar.session_id")
    candidate_scores = candidate_scores.copy()
    candidate_scores["session_id"] = strict_integer_values(candidate_scores["session_id"], "candidate_scores.session_id")
    truth = truth.copy()
    truth["session_id"] = strict_integer_values(truth["session_id"], "truth.session_id")
    candidate_scores["code"] = candidate_scores["code"].astype(str)
    truth["code"] = truth["code"].astype(str)
    if candidate_scores["code"].isin({"nan", "None", ""}).any() or truth["code"].isin({"nan", "None", ""}).any():
        raise EvaluationError("candidate scores or truth contains an empty code key")
    candidate_top3 = candidate_top3.copy()
    plus_path_top3 = plus_path_top3.copy()
    base34_top3 = base34_top3.copy()
    for label, selected_frame in (
        ("candidate_top3", candidate_top3),
        ("plus_path_top3", plus_path_top3),
        ("base34_top3", base34_top3),
    ):
        # Normalize only after verifying exact integer identities; this keeps
        # downstream merges stable without admitting float truncation.
        selected_frame["session_id"] = strict_integer_values(selected_frame["session_id"], f"{label}.session_id")
        selected_frame["code"] = selected_frame["code"].astype(str)
    date_map = validate_calendar_date_map(calendar)
    sessions = tuple(int(v) for v in calendar["session_id"].tolist())
    validate_exact_top3(candidate_top3, calendar, expected_sessions=sessions)
    validate_saved_top3_keys(plus_path_top3, calendar, expected_sessions=sessions)
    validate_saved_top3_keys(base34_top3, calendar, expected_sessions=sessions)
    validate_top3_scores(candidate_top3, candidate_scores)

    keys = ["session_id", "code"]
    if candidate_scores.duplicated(keys).any() or truth.duplicated(keys).any():
        raise EvaluationError("candidate scores or truth contains duplicate row keys")
    if not {"scoreable", "probability"} <= set(candidate_scores.columns):
        raise EvaluationError("candidate score artifact is missing scoreable/probability")
    if set(candidate_scores.session_id.astype(int)) != set(sessions):
        raise EvaluationError("candidate score sessions do not exactly match the frozen calendar")
    scoreable_values = pd.to_numeric(candidate_scores["scoreable"], errors="raise").to_numpy(dtype=float)
    if not np.isin(scoreable_values, [0.0, 1.0]).all():
        raise EvaluationError("candidate scoreable mask must be binary")
    probabilities = pd.to_numeric(candidate_scores["probability"], errors="raise").to_numpy(dtype=float)
    if np.isinf(probabilities).any():
        raise EvaluationError("candidate scores contain infinite probabilities")
    scoreable = scoreable_values.astype(bool)
    if not np.isfinite(probabilities[scoreable]).all() or np.any(
        (probabilities[scoreable] < 0.0) | (probabilities[scoreable] > 1.0)
    ):
        raise EvaluationError("scoreable rows have invalid probabilities")
    if not np.isnan(probabilities[~scoreable]).all():
        raise EvaluationError("unscoreable rows must retain NaN probabilities")
    if not {"y", "episode_state", "first_exact"} <= set(truth.columns):
        raise EvaluationError("truth contract is incomplete")
    expected = set(zip(candidate_scores.session_id.astype(int), candidate_scores.code.astype(str)))
    truth_keys = set(zip(truth.session_id.astype(int), truth.code.astype(str)))
    if expected != truth_keys:
        raise EvaluationError("truth does not cover the exact candidate score domain")

    full = candidate_scores.merge(truth, on=keys, how="left", validate="one_to_one", sort=False, indicator=True)
    if not full["_merge"].eq("both").all():
        raise EvaluationError("truth merge lost candidate score row keys")
    full = full.drop(columns="_merge")
    full["market_date"] = full["session_id"].astype(int).map(date_map)
    if full["market_date"].isna().any():
        raise EvaluationError("candidate score session is outside unique calendar map")

    candidate_selected = _attach_selection(candidate_top3, candidate_scores, truth)
    plus_selected = _attach_truth(plus_path_top3, truth)
    base_selected = _attach_truth(base34_top3, truth)

    arm = metrics.arm_metrics(full, candidate_selected, calendar)
    paired_plus = metrics.paired_precision(candidate_selected, plus_selected, calendar.session_id)
    paired_base = metrics.paired_precision(candidate_selected, base_selected, calendar.session_id)
    plus_lower = paired_plus.get("lower")
    base_lower = paired_base.get("lower")
    gates_known = plus_lower is not None and base_lower is not None
    g1 = bool(float(plus_lower) > 0.0) if gates_known else False
    g2 = bool(float(base_lower) >= 0.03) if gates_known else False

    status = (
        "SYNTHETIC_GATES_ONLY_NO_REAL_ACCEPTANCE" if synthetic else
        "EFFECT_CANNOT_CONFIRM" if not gates_known else
        "DIRECTION_ONLY" if g1 and g2 else
        "NO_BREAKTHROUGH"
    )
    return {
        "schema": "F5_BREADTH1_EVALUATION_V1",
        "status": status,
        "synthetic_only": bool(synthetic),
        "truth_access": truth_access,
        "sealed_status": sealed_status,
        "truth_decode_calls": int(truth_decode_calls),
        "fit_calls": 0,
        "model_load_calls": 0,
        "predict_calls": 0,
        "calendar_sessions": len(sessions),
        "candidate_top3_slots": len(candidate_selected),
        "control_top3_slots": {"PLUS_PATH": len(plus_selected), "BASE34": len(base_selected)},
        "current_gates_only": {
            "G1_candidate_minus_PLUS_PATH_lower_gt_zero": g1,
            "G2_candidate_minus_BASE34_lower_at_least_0_03": g2,
            "passed": bool(g1 and g2) if gates_known else None,
            "thresholds": dict(GATES),
        },
        "paired_precision_identification_bounds": {
            "vs_PLUS_PATH": paired_plus,
            "vs_BASE34": paired_base,
        },
        "report_only_diagnostics": {
            "candidate_arm_metrics": arm,
            "rank_buckets": {
                "scoreable_S": _rank_buckets(full.loc[full["scoreable"].eq(1)]),
                "unscoreable_G": _unscoreable_summary(full.loc[full["scoreable"].eq(0)]),
            },
            "quarter_half_year": _period_summary(
                {"candidate": candidate_selected, "PLUS_PATH": plus_selected, "BASE34": base_selected},
                calendar,
            ),
            "replacements_vs_PLUS_PATH": _replacement_counts(candidate_selected, plus_selected, sessions),
            "replacements_vs_BASE34": _replacement_counts(candidate_selected, base_selected, sessions),
            "daily_opportunities_and_capacity": _daily_opportunities(full, calendar),
            "unknown_identification_bounds_only": True,
            "not_confidence_intervals_or_strategy_returns": True,
        },
    }


def _attach_truth(selected: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    if selected.duplicated(["session_id", "code"]).any():
        raise EvaluationError("saved Top3 has duplicate row key")
    merged = selected.merge(
        truth[["session_id", "code", "y", "episode_state", "first_exact"]],
        on=["session_id", "code"], how="left", validate="one_to_one", sort=False, indicator=True,
    )
    if len(merged) != len(selected) or not merged["_merge"].eq("both").all():
        raise EvaluationError("saved Top3 failed truth key binding")
    return merged.drop(columns="_merge")


def _attach_selection(selected: pd.DataFrame, scores: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    truth_rows = _attach_truth(selected, truth)
    score_mask = scores[["session_id", "code", "scoreable"]]
    result = truth_rows.merge(score_mask, on=["session_id", "code"], how="left", validate="one_to_one", sort=False)
    if result["scoreable"].isna().any() or not result["scoreable"].eq(1).all():
        raise EvaluationError("candidate Top3 does not map to scoreable saved rows")
    return result


def _rank_buckets(frame: pd.DataFrame) -> dict[str, Any]:
    """Rank only scoreable S rows; G rows without a score are not rankable."""

    ranked = frame.sort_values(
        ["session_id", "probability", "code"],
        ascending=[True, False, True], kind="mergesort",
    ).copy()
    ranked["rank"] = ranked.groupby("session_id", sort=False).cumcount() + 1
    result: dict[str, Any] = {}
    for name, lower, upper in (("1-3", 1, 3), ("4-10", 4, 10), (">10", 11, None)):
        part = ranked.loc[ranked["rank"].ge(lower)]
        if upper is not None:
            part = part.loc[part["rank"].le(upper)]
        y = pd.to_numeric(part["y"], errors="coerce").to_numpy(dtype=float)
        known = np.isfinite(y)
        result[name] = {
            "rows": len(part),
            "known_labels": int(known.sum()),
            "unknown_labels": int((~known).sum()),
            "known_positive_hits": int(y[known].sum()),
        }
    return result


def _unscoreable_summary(frame: pd.DataFrame) -> dict[str, int]:
    y = pd.to_numeric(frame["y"], errors="coerce").to_numpy(dtype=float)
    known = np.isfinite(y)
    return {
        "rows": int(len(frame)),
        "known_labels": int(known.sum()),
        "known_positive_hits": int((y[known] == 1).sum()),
        "known_negative": int((y[known] == 0).sum()),
        "unknown_labels": int((~known).sum()),
    }


def _period_summary(selected: dict[str, pd.DataFrame], calendar: pd.DataFrame) -> dict[str, Any]:
    date_map = validate_calendar_date_map(calendar)
    by_period: dict[str, dict[str, dict[str, int]]] = {"quarters": {}, "half_years": {}}
    for arm, frame in selected.items():
        for row in frame.itertuples():
            date = pd.Timestamp(date_map[int(row.session_id)])
            keys = (f"{date.year}-Q{date.quarter}", f"{date.year}-H{1 if date.month <= 6 else 2}")
            y = float(row.y) if np.isfinite(row.y) else np.nan
            for period_key, target in zip(keys, (by_period["quarters"], by_period["half_years"])):
                arms = target.setdefault(period_key, {})
                counts = arms.setdefault(arm, {"slots": 0, "known_positive_hits": 0, "known_negative": 0, "unknown": 0})
                counts["slots"] += 1
                counts["known_positive_hits"] += int(np.isfinite(y) and y == 1)
                counts["known_negative"] += int(np.isfinite(y) and y == 0)
                counts["unknown"] += int(not np.isfinite(y))
    for periods in by_period.values():
        for arms in periods.values():
            candidate = arms.get("candidate", {})
            for control in ("PLUS_PATH", "BASE34"):
                control_counts = arms.get(control, {})
                arms[f"candidate_minus_{control}"] = {
                    key: candidate.get(key, 0) - control_counts.get(key, 0)
                    for key in ("slots", "known_positive_hits", "known_negative", "unknown")
                }
    return by_period


def _replacement_counts(candidate: pd.DataFrame, control: pd.DataFrame, sessions: tuple[int, ...]) -> dict[str, int]:
    candidate_rows = candidate.set_index(["session_id", "code"])
    control_rows = control.set_index(["session_id", "code"])
    candidate_keys = set(candidate_rows.index)
    control_keys = set(control_rows.index)
    common = candidate_keys & control_keys
    candidate_only = candidate_keys - control_keys
    control_only = control_keys - candidate_keys

    def label_counts(keys: set[tuple[Any, Any]]) -> dict[str, int]:
        selected = pd.concat(
            [candidate_rows.loc[[key]] if key in candidate_rows.index else control_rows.loc[[key]] for key in sorted(keys)],
            ignore_index=True,
        ) if keys else pd.DataFrame(columns=["y"])
        y = pd.to_numeric(selected["y"], errors="coerce").to_numpy(dtype=float)
        known = np.isfinite(y)
        return {
            "slots": int(len(keys)),
            "known_positive": int((y[known] == 1).sum()),
            "known_negative": int((y[known] == 0).sum()),
            "unknown": int((~known).sum()),
        }

    return {
        "common": label_counts(common),
        "candidate_only": label_counts(candidate_only),
        "control_only": label_counts(control_only),
        "candidate_minus_control": {
            key: label_counts(candidate_only)[key] - label_counts(control_only)[key]
            for key in ("slots", "known_positive", "known_negative", "unknown")
        },
        "fixed_union_slots": int(len(common | candidate_only | control_only)),
        "expected_union_slots": int(3 * len(sessions) + len(control_only)),
        "candidate_only_slots": int(len(candidate_only)),
        "control_only_slots": int(len(control_only)),
        "same_code_slots": int(len(common)),
    }


def _daily_opportunities(full: pd.DataFrame, calendar: pd.DataFrame) -> dict[str, Any]:
    scoreable = full.loc[full["scoreable"].eq(1)].copy()
    scoreable["y_num"] = pd.to_numeric(scoreable["y"], errors="coerce")
    by_day = scoreable.groupby("session_id", sort=False)["y_num"].agg(
        known_positive=lambda x: int((np.isfinite(x.to_numpy(dtype=float)) & (x.to_numpy(dtype=float) == 1)).sum()),
        known_negative=lambda x: int((np.isfinite(x.to_numpy(dtype=float)) & (x.to_numpy(dtype=float) == 0)).sum()),
        unknown=lambda x: int((~np.isfinite(x.to_numpy(dtype=float))).sum()),
    )
    calendar_rows = calendar.loc[:, ["session_id", "market_date"]].copy()
    rows = []
    for row in calendar_rows.itertuples(index=False):
        values = by_day.loc[int(row.session_id)] if int(row.session_id) in by_day.index else None
        m = int(values["known_positive"]) if values is not None else 0
        u = int(values["unknown"]) if values is not None else 0
        rows.append({
            "session_id": int(row.session_id),
            "market_date": str(row.market_date),
            "m_known_positive_S": m,
            "u_unknown_S": u,
            "zero_known_and_zero_unknown": bool(m == 0 and u == 0),
            "O_known_day": min(3, m),
            "O_upper_day": min(3, m + u),
        })
    return {
        "days": rows,
        "zero_known_and_zero_unknown_dates": [row["market_date"] for row in rows if row["zero_known_and_zero_unknown"]],
        "O_known": int(sum(row["O_known_day"] for row in rows)),
        "O_upper": int(sum(row["O_upper_day"] for row in rows)),
        "interpretation": "report_only_label_capacity_not_model_performance_or_confidence_bound",
    }
