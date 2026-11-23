from __future__ import annotations

import numpy as np
import pandas as pd

from ops import pft_sb_v13_act009 as study


def _rebuild_fixture() -> tuple[pd.DataFrame, list[str]]:
    dates = pd.bdate_range("2026-10-01", periods=10).strftime("%Y%m%d").tolist()
    rows = []
    for index, day in enumerate(dates):
        if index in (0, 1, 7, 8):
            open_, high, low, close = 9.1, 9.6, 8.2, 9.3
        elif index in (2, 3):
            open_, high, low, close = 12.0, 13.0, 8.0, 12.6
        else:
            open_, high, low, close = 12.2, 13.0, 8.1, 12.6
        rows.append({
            "ts_code": "000001.SZ", "trade_date": day, "market_type": "SZ",
            "open": open_, "high": high, "low": low, "close": close, "vol": 100.0,
            "zge_white_line": 11.0, "zge_yellow_line": 10.0,
            "model_eligible": True,
            # V1.2 rebuild is the frozen base mask for the V1.3 subset.
            "rebuild": index == 6, "pullback": False, "readvance": False,
            "exact_vr5": 0.8, "d_amp_exact": 0.05,
        })
    return pd.DataFrame(rows), dates


def test_rebuild_is_first_v12_subset_signal_and_episode_id_persists_causally() -> None:
    frame, dates = _rebuild_fixture()
    full, _meta = study._derive_rebuild_v13(frame, dates)
    prefix, _prefix_meta = study._derive_rebuild_v13(frame.iloc[:8].copy(), dates[:8])

    assert full.loc[6, "rebuild_v13"]
    assert full["rebuild_v13"].sum() == 1
    assert full.loc[6, "rebuild_anchor_date"] == dates[3]
    assert full.loc[6, "rebuild_anchor_low"] == 8.0
    assert full.loc[7, "rebuild_episode_id"] == full.loc[6, "rebuild_episode_id"]
    assert full.loc[7, "rebuild_state"] == "REBUILD_EPISODE_CONFIRMED_ACTIVE"
    # Tomorrow confirming the next below-Y pair must not rewrite D's prior episode assignment.
    assert full.loc[:7, "rebuild_episode_id"].tolist() == prefix["rebuild_episode_id"].tolist()
    assert full.loc[:7, "rebuild_state"].tolist() == prefix["rebuild_state"].tolist()
    assert full.loc[8, "rebuild_episode_id"] == ""


def test_rebuild_stops_on_missing_or_invalid_market_session_or_anchor_low_breach() -> None:
    frame, dates = _rebuild_fixture()

    missing = frame.drop(index=4).reset_index(drop=True)
    result, _meta = study._derive_rebuild_v13(missing, dates)
    assert not result["rebuild_v13"].any()
    missing_row = result.loc[result["trade_date"].eq(dates[5])].iloc[0]
    assert missing_row["rebuild_state"] == "CONTINUITY_BROKEN_MISSING_MARKET_SESSION"

    invalid = frame.copy()
    invalid.loc[4, "vol"] = 0.0
    result, _meta = study._derive_rebuild_v13(invalid, dates)
    assert not result["rebuild_v13"].any()
    assert result.loc[4, "rebuild_state"] == "CONTINUITY_BROKEN_INVALID_TRADE"

    breached = frame.copy()
    breached.loc[4, "low"] = 7.9
    result, _meta = study._derive_rebuild_v13(breached, dates)
    assert not result["rebuild_v13"].any()
    assert result.loc[4, "rebuild_state"] == "CONTINUITY_BROKEN_ANCHOR_LOW_LOST"


def test_rebuild_requires_three_consecutive_days_and_v12_base_mask() -> None:
    frame, dates = _rebuild_fixture()
    frame.loc[6, "exact_vr5"] = 1.0
    frame.loc[6, "d_amp_exact"] = 0.051
    result, _meta = study._derive_rebuild_v13(frame, dates)
    assert not result["rebuild_v13"].any()

    frame, dates = _rebuild_fixture()
    frame.loc[6, "rebuild"] = False
    result, _meta = study._derive_rebuild_v13(frame, dates)
    assert not result["rebuild_v13"].any()


def test_exact_market_return_and_vr5_do_not_skip_missing_sessions() -> None:
    dates = pd.bdate_range("2026-10-01", periods=8).strftime("%Y%m%d").tolist()
    rows = []
    for code in ("000001.SZ", "000002.SZ"):
        for index, day in enumerate(dates):
            if code == "000002.SZ" and index == 4:
                continue
            close = 10.0 + index
            rows.append({"ts_code": code, "trade_date": day, "market_type": "SZ",
                         "open": close, "high": close + 0.5, "low": close - 0.5,
                         "close": close, "vol": 100.0 + index, "pct_chg": 1.0,
                         "_d_vr5": 0.9, "_prior5v": 100.0})
    result, _meta = study._attach_exact_market_features(pd.DataFrame(rows), dates)
    b_day5 = result.loc[(result["ts_code"] == "000002.SZ")
                        & (result["trade_date"] == dates[5])].iloc[0]
    b_day6 = result.loc[(result["ts_code"] == "000002.SZ")
                        & (result["trade_date"] == dates[6])].iloc[0]
    a_day6 = result.loc[(result["ts_code"] == "000001.SZ")
                        & (result["trade_date"] == dates[6])].iloc[0]
    assert pd.isna(b_day5["exact_d_return"])
    assert pd.isna(b_day6["exact_vr5"])
    assert pd.notna(a_day6["exact_vr5"])
    assert not bool(a_day6["activity_timing_known"])
    assert not bool(a_day6["timing_gate"])


def test_s_rule_uses_per_branch_day_percentiles_then_code_tiebreak() -> None:
    frame = pd.DataFrame({
        "trade_date": ["20261119"] * 3,
        "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
        "pullback": [True, True, False], "readvance": [False, False, True],
        "rebuild_v13": [False, False, False], "v13_candidate_union": [True] * 3,
        "hard_score_pullback": [1.0, 2.0, np.nan],
        "hard_score_readvance": [np.nan, np.nan, 4.0],
        "hard_score_rebuild": [np.nan] * 3,
    })
    result, _meta = study._apply_s_rule(frame)
    assert np.isclose(result.loc[0, "s_pullback_percentile"], 0.5)
    assert np.isclose(result.loc[1, "s_pullback_percentile"], 1.0)
    assert np.isclose(result.loc[2, "s_readvance_percentile"], 1.0)
    assert result["s_rule_rank"].tolist() == [3.0, 1.0, 2.0]
    assert result.loc[1, "s_rule_branch"] == "pullback"
    assert result.loc[2, "s_rule_branch"] == "readvance"


def test_b_confirmations_preserve_unknown_and_prefer_b3() -> None:
    frame = pd.DataFrame([
        {"ts_code": "000001.SZ", "trade_date": "20261119", "open": 9.8, "high": 10.0,
         "low": 9.7, "close": 9.9, "vol": 100.0, "bbi": 9.5,
         "zge_white_line": 9.3, "zge_yellow_line": 9.0, "j": 10.0,
         "d_vr5": 0.9, "d_amp_exact": 0.05, "prior5_vol_vs_prior15": 0.5,
         "prior5_range_vs_prior15": 0.5, "close_vs_prior10_high": -0.01,
         "close_vs_prior20_high": -0.02, "pullback": True, "readvance": False,
         "rebuild_v13": False, "breadth_known": True, "activity_timing_known": True,
         "breadth_over_50": True, "activity_over_prior20_median": True, "timing_gate": True},
        {"ts_code": "000002.SZ", "trade_date": "20261119", "open": 10.0, "high": 11.2,
         "low": 9.8, "close": 11.0, "vol": 100.0, "bbi": 10.0,
         "zge_white_line": 10.5, "zge_yellow_line": 9.9, "j": 20.0,
         "d_vr5": 1.2, "d_amp_exact": 0.1, "prior5_vol_vs_prior15": 0.9,
         "prior5_range_vs_prior15": 0.9, "close_vs_prior10_high": 0.01,
         "close_vs_prior20_high": -0.01, "pullback": False, "readvance": True,
         "rebuild_v13": False, "breadth_known": True, "activity_timing_known": True,
         "breadth_over_50": True, "activity_over_prior20_median": True, "timing_gate": True},
        {"ts_code": "000003.SZ", "trade_date": "20261119", "open": 10.0, "high": 11.2,
         "low": 9.8, "close": 11.0, "vol": 100.0, "bbi": 10.0,
         "zge_white_line": 10.5, "zge_yellow_line": 9.9, "j": 20.0,
         "d_vr5": 1.5, "d_amp_exact": 0.1, "prior5_vol_vs_prior15": 0.9,
         "prior5_range_vs_prior15": 0.9, "close_vs_prior10_high": 0.01,
         "close_vs_prior20_high": 0.01, "pullback": False, "readvance": False,
         "rebuild_v13": True, "breadth_known": True, "activity_timing_known": True,
         "breadth_over_50": True, "activity_over_prior20_median": True, "timing_gate": True},
        {"ts_code": "000004.SZ", "trade_date": "20261119", "open": 10.0, "high": 10.5,
         "low": 9.8, "close": 10.0, "vol": 100.0, "bbi": 10.0,
         "zge_white_line": 10.5, "zge_yellow_line": 9.9, "j": np.nan,
         "d_vr5": 1.0, "d_amp_exact": 0.08, "prior5_vol_vs_prior15": 1.2,
         "prior5_range_vs_prior15": 1.2, "close_vs_prior10_high": -0.01,
         "close_vs_prior20_high": -0.01, "pullback": False, "readvance": False,
         "rebuild_v13": False, "breadth_known": True, "activity_timing_known": True,
         "breadth_over_50": True, "activity_over_prior20_median": True, "timing_gate": True},
    ])
    result, _meta = study._add_b_confirmations(frame)
    assert result.loc[0, "b1_state"] == "YES"
    assert result.loc[1, "b2_state"] == "YES"
    assert result.loc[2, "b2_state"] == "YES"
    assert result.loc[2, "b3_state"] == "YES"
    assert result.loc[2, "b_category"] == "B3"
    assert result.loc[3, "b1_state"] == "UNKNOWN"
    assert pd.isna(result.loc[3, "b1_candidate_feature"])
    assert result.loc[3, "b_confirmed_state"] == "UNKNOWN"


def test_train_target_requires_mature_exact_t5_path() -> None:
    dates = pd.bdate_range("2026-08-24", "2026-09-04").strftime("%Y%m%d").tolist()
    frame = pd.DataFrame({
        "trade_date": ["20260824", "20260827", "20260901"],
        "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
        "v13_candidate_union": [True, True, True],
        "return_t5": [0.03, 0.10, 0.20],
        "min_path_dd_t5": [-0.05, -0.01, -0.02],
        "path_observable_t5": [True, True, True],
    })
    result, meta = study._add_b_training_labels(frame, dates)
    assert result.loc[0, "b_target_t5_date"] == "20260831"
    assert result.loc[0, "b_training_target"] == 1.0
    assert result.loc[1, "b_target_t5_date"] > study.TRAIN_END
    assert pd.isna(result.loc[1, "b_training_target"])
    assert pd.isna(result.loc[2, "b_training_target"])
    assert meta["eligible_labeled_rows"] == 1


def test_episode_purge_removes_train_rows_on_shared_k_or_repair_groups() -> None:
    frame = pd.DataFrame({
        "ts_code": ["000001.SZ", "000001.SZ", "000002.SZ", "000002.SZ", "000003.SZ", "000003.SZ"],
        "trade_date": ["20260820", "20260902", "20260820", "20260902", "20260820", "20260902"],
        "_anchor_date": ["20260801", "20260801", "", "", "20260701", "20260715"],
        "rebuild_episode_id": ["A|E1", "A|E1", "B|E2", "B|E2", "C|E3", "C|E4"],
        "b_training_target": [1.0, np.nan, 0.0, np.nan, 1.0, np.nan],
        "v13_candidate_union": [True] * 6,
    })
    result, split = study._episode_split(frame)
    assert split["cross_split_canonical_k_groups"] == 1
    assert split["cross_split_repair_episode_groups"] == 2
    assert split["train_rows_purged"] == 2
    assert split["train_labeled_after_purge"] == 1
    assert result.loc[4, "_canonical_k_group"] != result.loc[5, "_canonical_k_group"]
    assert split["post_purge_canonical_k_overlap"] == 0
    assert split["post_purge_repair_episode_overlap"] == 0


def test_confirmed_and_timing_pools_select_from_explicit_state() -> None:
    rows = []
    for code, confirmed, timing, score in (
        ("000003.SZ", "CONFIRMED", True, 0.9),
        ("000001.SZ", "UNCONFIRMED", True, 0.8),
        ("000002.SZ", "CONFIRMED", False, 0.7),
    ):
        row = {"trade_date": study.OOS_START, "ts_code": code,
               "v13_candidate_union": True, "b_confirmed_state": confirmed,
               "timing_gate": timing, "breadth_over_50": True,
               "activity_over_prior20_median": True, "s_rule_score": score,
               "p_b_lr": score, "p_b_hgb": score}
        for horizon in study.EVAL_HORIZONS:
            row[f"return_t{horizon}"] = 0.04
            row[f"benchmark_return_t{horizon}"] = 0.01
            row[f"benchmark_count_t{horizon}"] = 100
            row[f"excess_return_t{horizon}"] = 0.03
            row[f"min_path_dd_t{horizon}"] = -0.02
            row[f"path_observable_t{horizon}"] = True
            row[f"return_observable_t{horizon}"] = True
            row[f"benchmark_observable_t{horizon}"] = True
        rows.append(row)
    daily, pooled, top20 = study._build_oos_comparison(pd.DataFrame(rows), [study.OOS_START])
    day = daily.loc[daily["horizon_market_sessions"].eq(3)].set_index("method")
    assert day.loc["B_CONFIRMED_POOL", "selected_count"] == 2
    assert day.loc["B_TIMING_POOL", "selected_count"] == 1
    assert day.loc["B_CONFIRMED_TOP10", "selected_count"] == 2
    assert day.loc["B_TIMING_TOP10", "selected_count"] == 1
    assert day.loc["B_CONFIRMED_POOL", "same_d_benchmark_equal_weight_return"] == 0.01
    assert day.loc["B_CONFIRMED_POOL", "same_d_benchmark_valid_a_count"] == 100
    assert "benchmark_return_t3" in top20.columns
    assert "excess_return_t5" in top20.columns
    assert "path_observable_t10" in top20.columns
    assert len(top20.loc[top20["method"].eq("B_TIMING_TOP20")]) == 1
    pooled_day = pooled.loc[(pooled["method"] == "B_TIMING_POOL")
                            & pooled["horizon_market_sessions"].eq(3)].iloc[0]
    assert pooled_day["mean_daily_selected_count"] == 1.0


def test_b_probabilities_have_stable_daily_rank_and_features_are_d_only() -> None:
    frame = pd.DataFrame({
        "trade_date": [study.OOS_START] * 3,
        "ts_code": ["000002.SZ", "000001.SZ", "000003.SZ"],
        "v13_candidate_union": [True] * 3,
        "p_b_lr": [0.8, 0.8, 0.4], "p_b_hgb": [0.2, 0.9, 0.9],
    })
    result = study._rank_b_probabilities(frame)
    assert result["b_lr_rank"].tolist() == [2.0, 1.0, 3.0]
    assert result["b_hgb_rank"].tolist() == [3.0, 1.0, 2.0]
    assert not ({"return_t5", "min_path_dd_t5", "b_training_target"}
                & set(study.B_FEATURE_NAMES))
