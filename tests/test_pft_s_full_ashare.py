from __future__ import annotations

import csv

import pandas as pd
import pytest

from ops.pft_s_full_ashare import _candidate_rank, _deduplicate_alias_history, _apportion
from ops.pft_s_full_ashare_features import FEATURES, _tri_window, feature_frame, weak_label_strata
from ops.pft_s_full_ashare_fit import FitError, _auc, _matrix, _metrics, _save_prediction_outputs


def _history(count: int = 90) -> pd.DataFrame:
    days = pd.bdate_range("2026-01-01", periods=count)
    return pd.DataFrame({
        "trade_date": days.strftime("%Y%m%d"),
        "open": 10.0,
        "high": 10.2,
        "low": 9.9,
        "close": 10.0,
        "vol": 100.0,
        "bbi": 9.8,
        "zge_white_line": 9.8,
        "zge_yellow_line": 9.6,
    })


def _prior_surge(frame: pd.DataFrame, index: int) -> None:
    frame.loc[index, ["open", "high", "low", "close", "vol"]] = [10.2, 10.8, 9.8, 10.5, 130.0]


def test_prefix_cumsum_keeps_interior_consolidation_when_d_is_low_volume() -> None:
    frame = _history()
    anchor, d = 55, 58
    _prior_surge(frame, anchor)
    frame.loc[anchor + 1, "vol"] = 50.0  # the only quiet bar strictly between anchor and D
    frame.loc[d, "vol"] = 50.0  # D is quiet too, but is excluded from prior consolidation

    result = feature_frame(frame)
    row = result.loc[d]

    assert row["prior_consolidation"] == 1.0
    assert row["d_vr5"] <= 0.90
    assert "d_low_vs_recent_anchor_low_pct" in FEATURES
    assert row["d_low_vs_recent_anchor_low_pct"] == pytest.approx((9.9 / 9.8 - 1.0) * 100.0)


def test_prior_consolidation_is_unknown_when_intervening_volume_ratio_is_missing() -> None:
    frame = _history()
    anchor, d = 55, 58
    _prior_surge(frame, anchor)
    frame.loc[anchor + 1, "vol"] = 250.0  # observed nonquiet ratio
    frame.loc[anchor + 2, "vol"] = float("nan")  # missing ratio, not proof of no quiet bar

    result = feature_frame(frame)
    assert result.loc[d, "prior_consolidation"] != result.loc[d, "prior_consolidation"]
    assert result.loc[d, "prior_consolidation"] != 0.0


def test_truncated_yellow_window_is_unknown_unless_a_below_pair_is_proven() -> None:
    close = pd.Series([10.0, 9.0, 9.0, 10.0])
    yellow = pd.Series([10.0, 10.0, 10.0, 10.0])
    proven_pair = _tri_window(close, yellow, 14)
    no_pair = _tri_window(pd.Series([10.0] * 14), pd.Series([10.0] * 14), 14)
    full_window_no_pair = _tri_window(pd.Series([10.0] * 15), pd.Series([10.0] * 15), 14)

    assert proven_pair.iloc[-1] == 1.0
    assert pd.isna(no_pair.iloc[-1])
    assert full_window_no_pair.iloc[-1] == 0.0


def test_hard_first_breakout_does_not_consume_unknown_consolidation() -> None:
    row = {"g1_wy_pass": 1.0, "g2_s26_reject": 0.0, "gate_pass": 1.0,
           "y_consec2_active_5b": 0.0, "y_below_at_d": 0.0, "y_consec2_break_15b": 0.0,
           "no_old_yellow_break_26b": 1.0, "has_prior_surge_40b": 1.0,
           "recent_anchor_low_intact": 1.0, "prior_consolidation": float("nan"),
           "d_ret_pct": 3.0, "d_vr5": 1.4, "brk_prev10_high": 1.0, "brk_prev20_high": 0.0,
           "c_vs_recent_anchor_low_pct": 3.0, "c_vs_white_pct": 2.0, "last5_low_slope_pct": 0.0}

    assert weak_label_strata(row) == []


def test_hard_local_reclaim_separates_probe_recovery_from_close_loss() -> None:
    frame = _history()
    anchor, d = 60, 67
    _prior_surge(frame, anchor)
    frame.loc[anchor + 1, "vol"] = 50.0
    frame.loc[d - 5:d, "low"] = [10.0, 9.9, 9.8, 9.7, 9.6, 9.5]
    frame.loc[d - 2, "close"] = 9.7  # prior close broke the anchor low
    frame.loc[d - 1, "close"] = 10.0
    frame.loc[d, ["close", "high", "low", "zge_white_line", "zge_yellow_line"]] = [9.9, 10.0, 9.5, 10.1, 9.5]

    result = feature_frame(frame)
    row = result.loc[d]

    assert row["prior_anchor_recent_break_5b"] == 1.0
    assert row["recent_anchor_low_intact"] == 0.0
    assert row["d_intraday_probe_recovered"] == 1.0
    assert row["d_low_held_above_anchor"] == 0.0
    assert row["d_close_below_anchor_low"] == 0.0
    assert row["w_below_consec_at_d"] >= 1.0
    assert len(result["gate_reasons"]) == len(frame)
    assert weak_label_strata(row)[0] == ("FALSE", "hard_local_reclaim_below_support")

    frame.loc[d, "close"] = 9.7
    lost = feature_frame(frame).loc[d]
    assert lost["d_close_below_anchor_low"] == 1.0
    assert lost["d_intraday_probe_recovered"] == 0.0


def test_gate_reasons_are_row_aligned_and_gates_remain_fixed() -> None:
    frame = _history(32)
    frame["zge_white_line"] = 9.5
    frame["zge_yellow_line"] = 9.6
    result = feature_frame(frame)

    assert len(result["gate_reasons"]) == len(frame)
    assert result.loc[len(frame) - 1, "g1_wy_pass"] == 0.0
    assert "G1_WHITE_NOT_ABOVE_YELLOW" in result.loc[len(frame) - 1, "gate_reasons"]
    assert result.loc[len(frame) - 1, "gate_pass"] == 0.0


def test_alias_duplicate_uses_crosswalk_effective_date() -> None:
    old = {"ts_code": "872931.BJ", "trade_date": "20251008", "close": 10.0}
    new = {"ts_code": "920931.BJ", "trade_date": "20251008", "close": 11.0}
    before = _deduplicate_alias_history({"872931.BJ": [old], "920931.BJ": [new]},
                                        [{"old": "872931.BJ", "new": "920931.BJ", "effective": "20251009"}])
    old_after = {**old, "trade_date": "20251009"}
    new_after = {**new, "trade_date": "20251009"}
    after = _deduplicate_alias_history({"872931.BJ": [old_after], "920931.BJ": [new_after]},
                                       [{"old": "872931.BJ", "new": "920931.BJ", "effective": "20251009"}])

    assert before[0]["ts_code"] == "872931.BJ"
    assert after[0]["ts_code"] == "920931.BJ"


def test_sampling_rank_and_apportionment_are_deterministic() -> None:
    expected = _candidate_rank("TRAIN", "positive_pullback", "000001.SZ", "20251120")
    assert expected == _candidate_rank("TRAIN", "positive_pullback", "000001.SZ", "20251120")
    assert _apportion(40, (14, 13, 13)) == (14, 13, 13)
    assert _apportion(60, (1, 1, 1)) == (20, 20, 20)


def test_metrics_count_all_missed_positives_as_zero_f1() -> None:
    assert _auc([0, 1], [0.1, 0.9]) == 1.0
    metrics = _metrics([1, 1], [0.1, 0.2], [0, 0])
    assert metrics["TP"] == 0
    assert metrics["FN"] == 2
    assert metrics["F1"] == 0.0


def test_prediction_output_writes_exact_raw_and_gated_columns_without_fitting(tmp_path) -> None:
    lr, rf = "GEMINI_R2_FIXED_LR", "GEMINI_R2_SHALLOW_RF"
    oos_probabilities = {lr: [0.8, 0.7], rf: [0.6, 0.4]}
    oos_gates = [
        {"episode_id": "OOS-1", "D": "20260102", "g1_wy_pass": 1.0,
         "g2_s26_reject": 0.0, "gate_pass": 1.0, "gate_reasons": ""},
        {"episode_id": "OOS-2", "D": "20260105", "g1_wy_pass": 0.0,
         "g2_s26_reject": 0.0, "gate_pass": 0.0, "gate_reasons": "G1_WHITE_NOT_ABOVE_YELLOW"},
    ]
    external = {
        "JOINT54_VAL18": [
            {"case_id": "J-1", "security_id": "000001.SZ", "canonical_security_id": "000001.SZ",
             "D": "20251120", "g1_wy_pass": 1.0, "g2_s26_reject": 0.0,
             "gate_pass": 1.0, "gate_reasons": ""},
        ],
        "KB11_FROZEN_ORIGINAL_D": [
            {"case_id": "K-1", "security_id": "000002.SZ", "canonical_security_id": "000002.SZ",
             "D": "20251121", "g1_wy_pass": 0.0, "g2_s26_reject": 0.0,
             "gate_pass": 0.0, "gate_reasons": "G1_WHITE_NOT_ABOVE_YELLOW"},
        ],
    }
    external_probs = {
        lr: {"JOINT54_VAL18": [0.9], "KB11_FROZEN_ORIGINAL_D": [0.75]},
        rf: {"JOINT54_VAL18": [0.55], "KB11_FROZEN_ORIGINAL_D": [0.25]},
    }

    _save_prediction_outputs(tmp_path, oos_probabilities, external, external_probs, oos_gates)

    with (tmp_path / "oos_predictions.csv").open(encoding="utf-8", newline="") as stream:
        oos_reader = csv.DictReader(stream)
        assert oos_reader.fieldnames == [
            "feature_row", "episode_id", "D", "g1_wy_pass", "g2_s26_reject", "gate_pass", "gate_reasons",
            "p_lr", "decision_lr_raw", "p_lr_gated", "decision_lr_gated",
            "p_rf", "decision_rf_raw", "p_rf_gated", "decision_rf_gated",
        ]
        oos_rows = list(oos_reader)
    assert len(oos_rows) == 2
    assert oos_rows[0]["p_lr_gated"] == "0.8"
    assert oos_rows[0]["decision_rf_gated"] == "1"
    assert oos_rows[1]["p_lr_gated"] == "0.0"
    assert oos_rows[1]["decision_lr_gated"] == "0"

    with (tmp_path / "external_predictions.csv").open(encoding="utf-8", newline="") as stream:
        external_reader = csv.DictReader(stream)
        assert external_reader.fieldnames == [
            "exam", "feature_row", "case_id", "p_lr", "decision_lr_raw", "p_lr_gated",
            "decision_lr_gated", "p_rf", "decision_rf_raw", "p_rf_gated", "decision_rf_gated",
            "gate_pass", "gate_reasons",
        ]
        external_rows = list(external_reader)
    assert len(external_rows) == 2
    assert external_rows[0]["p_lr_gated"] == "0.9"
    assert external_rows[1]["p_rf_gated"] == "0.0"


def test_matrix_accepts_blank_numeric_cells_for_median_imputation(tmp_path) -> None:
    row = {name: 1.0 for name in FEATURES}
    row[FEATURES[0]] = float("nan")
    path = tmp_path / "train_features.csv"
    pd.DataFrame([row], columns=FEATURES).to_csv(path, index=False)

    result = _matrix(path, pandas=pd)

    assert len(result) == 1
    assert pd.isna(result.loc[0, FEATURES[0]])


@pytest.mark.parametrize("infinity", [float("inf"), float("-inf")])
def test_matrix_rejects_positive_and_negative_infinity(tmp_path, infinity) -> None:
    row = {name: 1.0 for name in FEATURES}
    row[FEATURES[0]] = infinity
    path = tmp_path / "infinite_features.csv"
    pd.DataFrame([row], columns=FEATURES).to_csv(path, index=False)

    with pytest.raises(FitError, match="FEATURE_MATRIX_INFINITY"):
        _matrix(path, pandas=pd)
