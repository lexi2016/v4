"""Numerical-bound regressions for stage scoring and ordering (audit F11).

Converted from the independent audit probes R16/R17: non-finite inputs must
not be promoted to maximum scores, and a real zero score must sort between
positive and negative scores instead of being treated as missing.
"""
from __future__ import annotations

from domains.stage_scoring import _number, rank_a_stage_rows, score_a_stage, score_hk_stage
from stage_center.selection import stage_row_sort_key


def test_number_rejects_bool_and_nonfinite() -> None:
    assert _number(True) is None
    assert _number(False) is None
    assert _number(float("nan")) is None
    assert _number(float("inf")) is None
    assert _number(float("-inf")) is None
    assert _number("nan") is None
    assert _number("2.5") == 2.5
    assert _number(0) == 0.0


def test_hk_nan_close_position_is_missing_not_maximum() -> None:
    base = {"pct_chg": 6.0, "stage_window_change_pct": 3.0, "source_universe": ""}
    clean = score_hk_stage(base)
    poisoned = score_hk_stage({**base, "stage_close_position": float("nan")})
    assert poisoned == clean
    assert poisoned < 100.0


def _a_row(**extra: object) -> dict:
    row = {
        "open_price": 10.0,
        "last_price": 10.4,
        "prev_close_price": 10.0,
        "high_price": 10.6,
        "low_price": 9.9,
        "turnover": 500_000_000.0,
        "stage_window_complete": True,
    }
    row.update(extra)
    return row


def test_a_stage_nan_last_price_is_missing_not_maximum() -> None:
    clean = score_a_stage(_a_row(), "STAGE_0930_0935")
    poisoned = score_a_stage(_a_row(last_price=float("nan")), "STAGE_0930_0935")
    assert poisoned <= 100.0
    assert poisoned == score_a_stage(_a_row(last_price=None), "STAGE_0930_0935")
    assert clean == score_a_stage(_a_row(), "STAGE_0930_0935")


def test_zero_score_sorts_between_positive_and_negative() -> None:
    rows = [
        {"stage_score": -1.0, "qmt_gap_pct": 0.0, "qmt_amount": 0.0, "stage_id": "STAGE_0930_0935"},
        {"stage_score": 0.0, "qmt_gap_pct": 0.0, "qmt_amount": 0.0, "stage_id": "STAGE_0930_0935"},
        {"stage_score": 5.0, "qmt_gap_pct": 0.0, "qmt_amount": 0.0, "stage_id": "STAGE_0930_0935"},
    ]
    ordered = sorted(rows, key=stage_row_sort_key)
    assert [row["stage_score"] for row in ordered] == [5.0, 0.0, -1.0]


def test_missing_score_still_sorts_last() -> None:
    rows = [
        {"stage_score": None, "qmt_gap_pct": 0.0, "qmt_amount": 0.0, "stage_id": "STAGE_0930_0935"},
        {"stage_score": 0.0, "qmt_gap_pct": 0.0, "qmt_amount": 0.0, "stage_id": "STAGE_0930_0935"},
        {"stage_score": 1.0, "qmt_gap_pct": 0.0, "qmt_amount": 0.0, "stage_id": "STAGE_0930_0935"},
    ]
    ordered = sorted(rows, key=stage_row_sort_key)
    assert [row["stage_score"] for row in ordered] == [1.0, 0.0, None]


def test_rank_a_rows_survives_nonfinite_metrics() -> None:
    rows = [
        {
            "symbol": "A.000001",
            "stage_window_change_pct": float("nan"),
            "last_price": float("nan"),
            "open_price": float("inf"),
            "prev_close_price": 10.0,
            "high_price": float("nan"),
            "low_price": 9.0,
            "turnover": float("nan"),
            "pool_score": float("inf"),
        }
    ]
    ranked = rank_a_stage_rows(rows, "STAGE_0930_0935")
    assert len(ranked) == 1
    assert 0.0 <= ranked[0]["stage_score"] <= 100.0
