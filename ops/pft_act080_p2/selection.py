"""Deterministic VAL-only operating point selection."""

import numpy as np

from .contracts import METHOD
from .outcomes import summarize


def threshold_rows(family, feature_set, scores, val_events):
    if len(scores) != len(val_events) or not np.isfinite(scores).all():
        raise ValueError("VAL score shape/validity mismatch")
    for quantile in METHOD["quantiles"]:
        threshold = float(np.quantile(scores, quantile, method="linear"))
        rows = [event for score, event in zip(scores, val_events, strict=True) if score >= threshold]
        metrics = summarize(rows)
        coverage = len(rows) / len(val_events)
        qualifies = (
            metrics["tail_std_mature"] >= METHOD["minimum_val_selected_mature"]
            and coverage >= METHOD["minimum_val_coverage"]
            and metrics["T5_median"] is not None and metrics["T5_mean"] is not None
        )
        yield {
            "family": family, "feature_set": feature_set, "VAL_quantile": quantile,
            "threshold": threshold, "VAL_coverage": coverage, "eligible": qualifies, **metrics,
        }


def choose(rows):
    eligible = [row for row in rows if row["eligible"]]
    if not eligible:
        raise ValueError("no VAL-only operating point cleared frozen coverage and maturity floors")
    return min(eligible, key=lambda row: (
        row["tail_std_rate"], -row["T5_median"], -row["T5_mean"], -row["VAL_coverage"],
        METHOD["family_order"].index(row["family"]), METHOD["feature_order"].index(row["feature_set"]),
        METHOD["quantiles"].index(row["VAL_quantile"]),
    ))
