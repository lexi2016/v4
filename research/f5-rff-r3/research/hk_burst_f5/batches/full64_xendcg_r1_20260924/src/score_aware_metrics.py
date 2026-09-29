"""Explicit score-kind dispatch around the frozen F5 evaluator helpers.

Binary defaults delegate directly to the accepted ``spike5.metrics`` API and
return its unmodified objects.  Raw rank margins use that same selector and
arm/episode math without ever presenting margins to its probability metrics.
"""
from __future__ import annotations

import hashlib
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score


F5_SOURCE_ROOT = Path(
    "/Users/lexi/Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an/"
    "work/hk_spike_f5_v1/HK_SPIKE_F5_TRAIN_V1"
)
FROZEN_METRICS_PATH = F5_SOURCE_ROOT / "spike5/metrics.py"
FROZEN_METRICS_SHA256 = "c8ffabf345069d64a82ac686e6747afda8c22433f1309eecdc999a7ad1eac763"
BINARY_PROBABILITY = "BINARY_PROBABILITY"
RAW_RANKING_SCORE = "RAW_RANKING_SCORE"
NO_PROBABILITY_STATUS = "NOT_EVALUATED_NO_EVENT_PROBABILITY_MODEL"


class ScoreKindError(ValueError):
    """The requested metric interface does not match the score semantics."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def frozen_metrics() -> Any:
    if not FROZEN_METRICS_PATH.is_file() or sha256_file(FROZEN_METRICS_PATH) != FROZEN_METRICS_SHA256:
        raise ScoreKindError("FROZEN_F5_METRICS_SOURCE_IDENTITY_MISMATCH")
    # Do not create bytecode files beside the immutable original evaluator.
    sys.dont_write_bytecode = True
    source_text = str(F5_SOURCE_ROOT)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    import spike5.metrics as metrics  # imported only after the source SHA check

    if Path(metrics.__file__).resolve() != FROZEN_METRICS_PATH.resolve():
        raise ScoreKindError("FROZEN_F5_METRICS_IMPORT_PATH_MISMATCH")
    return metrics


def _require_raw_score_grid(frame: pd.DataFrame, *, score_column: str) -> np.ndarray:
    required = {"session_id", "code", "scoreable", score_column}
    if not required.issubset(frame.columns):
        raise ScoreKindError("RAW_SCORE_FRAME_MISSING_REQUIRED_COLUMN")
    scoreable = pd.to_numeric(frame["scoreable"], errors="coerce").to_numpy(dtype=np.float64)
    if not np.isfinite(scoreable).all() or not np.isin(scoreable, (0.0, 1.0)).all():
        raise ScoreKindError("SCOREABLE_MASK_MUST_BE_BINARY")
    scoreable_mask = scoreable.astype(bool)
    scores = pd.to_numeric(frame[score_column], errors="coerce").to_numpy(dtype=np.float64)
    if np.isinf(scores).any():
        raise ScoreKindError("RAW_SCORE_INFINITY_FORBIDDEN")
    if not np.isfinite(scores[scoreable_mask]).all():
        raise ScoreKindError("SCOREABLE_RAW_SCORE_MUST_BE_FINITE")
    if np.isfinite(scores[~scoreable_mask]).any():
        raise ScoreKindError("UNSCOREABLE_RAW_SCORE_MUST_BE_NAN")
    if frame[["session_id", "code"]].isna().any().any():
        raise ScoreKindError("RAW_SCORE_KEY_MISSING")
    if frame.duplicated(["session_id", "code"]).any():
        raise ScoreKindError("RAW_SCORE_KEY_DUPLICATE")
    return scoreable_mask


def select_top3(
    frame: pd.DataFrame,
    *,
    score_kind: str = BINARY_PROBABILITY,
    score_column: str | None = None,
) -> pd.DataFrame:
    """Select by the named score while preserving binary default behavior."""
    metrics = frozen_metrics()
    if score_kind == BINARY_PROBABILITY:
        if score_column not in (None, "probability"):
            raise ScoreKindError("BINARY_SCORE_COLUMN_MUST_BE_PROBABILITY")
        return metrics.select_top3(frame)
    if score_kind != RAW_RANKING_SCORE:
        raise ScoreKindError("UNKNOWN_SCORE_KIND")
    if score_column != "ranking_score":
        raise ScoreKindError("RAW_SCORE_COLUMN_MUST_BE_RANKING_SCORE")

    scoreable = _require_raw_score_grid(frame, score_column=score_column)
    selected = frame.loc[scoreable].copy()
    selected = selected.sort_values(
        ["session_id", score_column, "code"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    selected = selected.groupby("session_id", sort=False, group_keys=False).head(3).copy()
    selected["rank"] = selected.groupby("session_id", sort=False).cumcount() + 1
    selected["weight"] = "1/3"
    return selected


def paired_precision(candidate: pd.DataFrame, control: pd.DataFrame, sessions: Any) -> dict[str, Any]:
    """Call the exact frozen paired helper; no route-local formula is added."""
    return frozen_metrics().paired_precision(candidate, control, sessions)


def probability_metrics(
    frame: pd.DataFrame,
    *,
    score_kind: str = BINARY_PROBABILITY,
    score_column: str | None = None,
) -> dict[str, Any]:
    """Use frozen probability metrics only for true binary probabilities."""
    metrics = frozen_metrics()
    if score_kind == BINARY_PROBABILITY:
        if score_column not in (None, "probability"):
            raise ScoreKindError("BINARY_SCORE_COLUMN_MUST_BE_PROBABILITY")
        return metrics.probability_metrics(frame)
    if score_kind != RAW_RANKING_SCORE:
        raise ScoreKindError("UNKNOWN_SCORE_KIND")
    if score_column != "ranking_score":
        raise ScoreKindError("RAW_SCORE_COLUMN_MUST_BE_RANKING_SCORE")

    scoreable_mask = _require_raw_score_grid(frame, score_column=score_column)
    raw = pd.to_numeric(frame[score_column], errors="coerce").to_numpy(dtype=np.float64)
    labels = pd.to_numeric(frame["y"], errors="coerce").to_numpy(dtype=np.float64)
    known = scoreable_mask & np.isfinite(raw) & np.isfinite(labels)
    known_labels = labels[known]
    average_precision = (
        float(average_precision_score(known_labels, raw[known]))
        if len(np.unique(known_labels)) == 2
        else None
    )
    scored = int(scoreable_mask.sum())
    known_count = int(known.sum())
    return {
        "scored": scored,
        "known": known_count,
        "unknown": scored - known_count,
        "positive_known": int(known_labels.sum()) if known_count else 0,
        "average_precision_known": average_precision,
        "pr_auc_definition": "noninterpolated_average_precision_known_labels_only",
        "score_kind": "RAW_RANKING_MARGIN_NOT_EVENT_PROBABILITY",
        "brier_known": None,
        "brier_all_lower": None,
        "brier_all_upper": None,
        "logloss_known": None,
        "logloss_all_lower": None,
        "logloss_all_upper": None,
        "calibration_bins": None,
        "probability_status": NO_PROBABILITY_STATUS,
        "probabilities_calibrated_claim": False,
    }


def arm_metrics(
    frame: pd.DataFrame,
    selected: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    score_kind: str = BINARY_PROBABILITY,
    score_column: str | None = None,
) -> dict[str, Any]:
    """Preserve the frozen arm/episode calculation and branch only its score API."""
    metrics = frozen_metrics()
    if score_kind == BINARY_PROBABILITY:
        if score_column not in (None, "probability"):
            raise ScoreKindError("BINARY_SCORE_COLUMN_MUST_BE_PROBABILITY")
        return metrics.arm_metrics(frame, selected, calendar)
    if score_kind != RAW_RANKING_SCORE:
        raise ScoreKindError("UNKNOWN_SCORE_KIND")
    if score_column != "ranking_score":
        raise ScoreKindError("RAW_SCORE_COLUMN_MUST_BE_RANKING_SCORE")

    _require_raw_score_grid(frame, score_column=score_column)
    probability_free = frame.copy()
    probability_free["probability"] = np.full(len(frame), np.nan, dtype=np.float64)
    # The original helper continues to own all paired-independent arm and
    # episode calculations.  Its probability routine sees only an empty score
    # domain, never the raw ranking margins; those metrics are then explicit
    # nulls with the route's declared reason.
    result = metrics.arm_metrics(probability_free, selected, calendar)
    result["probability"] = probability_metrics(
        frame,
        score_kind=RAW_RANKING_SCORE,
        score_column=score_column,
    )
    result["score_kind"] = "RAW_RANKING_MARGIN_NOT_EVENT_PROBABILITY"
    return result
