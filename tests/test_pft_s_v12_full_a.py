from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ops import pft_s_v12_full_a as study


def _panel_frame(*, omit_bj_t1: bool = False, boundary_g2: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range("2026-05-01", periods=80)
    rows = []
    for code, market in (("000001.SZ", "SZ"), ("920001.BJ", "BJ")):
        for index, day in enumerate(dates):
            if omit_bj_t1 and code == "920001.BJ" and index == 61:
                continue
            close = 10.0 + index * 0.01
            open_ = close * 0.999
            high = close * 1.01
            low = close * 0.99
            yellow = close * 0.95
            white = close * 0.97
            if boundary_g2 and index == 60:
                close, open_, high, low, yellow, white = 13.5, 13.4, 14.0, 13.0, 10.0, 10.5
            rows.append({
                "ts_code": code, "market_type": market,
                "trade_date": day.strftime("%Y%m%d"),
                "open": open_, "high": high, "low": low, "close": close,
                "vol": 1000.0, "pct_chg": 0.2,
                "bbi": close * 0.98, "j": 10.0,
                "zge_white_line": white, "zge_yellow_line": yellow,
            })
    return pd.DataFrame(rows).sort_values(["ts_code", "trade_date"], kind="mergesort").reset_index(drop=True)


def _official(day: str = "20260825") -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    rows = {
        "920001.BJ": {"rank": 1, "change_pct": 10.0, "name": "BJ"},
    }
    return rows, {"asof_date": day, "path": "/fixture/official.json", "sha256": "a" * 64,
                  "bytes": 1, "rows": 1}


def test_exchange_identity_keeps_beijing_codes_and_native_suffixes() -> None:
    assert study._code("920001") == "920001.BJ"
    assert study._code("920001.BJ") == "920001.BJ"
    assert study._code("000001.SZ") == "000001.SZ"


def test_market_session_offsets_censor_missing_bar_and_keep_bj() -> None:
    panel = _panel_frame(omit_bj_t1=True)
    dates = sorted(panel["trade_date"].unique())
    start, asof = dates[60], dates[66]
    result, _meta = study._vectorize_rows(panel, start_date=start, asof_date=asof)
    d_day = dates[60]
    sz = result.loc[(result["ts_code"] == "000001.SZ") & (result["trade_date"] == d_day)].iloc[0]
    bj = result.loc[(result["ts_code"] == "920001.BJ") & (result["trade_date"] == d_day)].iloc[0]
    assert sz["market_type"] == "SZ"
    assert bj["market_type"] == "BJ"
    assert sz["model_eligible"]
    assert pd.notna(sz["return_t1"])
    assert pd.isna(bj["return_t1"])
    assert not bj["path_observable_t1"]
    assert not any(name.lower() in {"j", "b1", "b2", "b3", "buy"} for name in study.FEATURE_NAMES)


def test_g2_first_branch_includes_exact_35_percent_and_three_percent_wick() -> None:
    panel = _panel_frame(boundary_g2=True)
    dates = sorted(panel["trade_date"].unique())
    result, _meta = study._vectorize_rows(
        panel, start_date=dates[60], asof_date=dates[62],
    )
    d_day = dates[60]
    sz = result.loc[(result["ts_code"] == "000001.SZ") & (result["trade_date"] == d_day)].iloc[0]
    assert np.isclose(sz["_close_yellow"], 0.35)
    assert sz["_upper_wick"] >= 0.03
    assert bool(sz["g2_veto"])
    assert not bool(sz["model_eligible"])


def test_official_top200_replaces_realized_rank_and_t1_lookup_is_exact() -> None:
    panel = _panel_frame()
    dates = sorted(panel["trade_date"].unique())
    day_index = 61
    day, next_day = dates[day_index], dates[day_index + 1]
    frame, _meta = study._vectorize_rows(panel, start_date=dates[60], asof_date=dates[65])
    official, official_meta = _official(day)
    frame, top_meta = study._apply_top200_ranks(frame, official, official_meta)
    frame = study._join_future_top200(frame)
    day_rows = frame.loc[frame["trade_date"].eq(day)].set_index("ts_code")
    assert day_rows.loc["920001.BJ", "top200_rank"] == 1
    assert bool(day_rows.loc["920001.BJ", "top200_membership"])
    assert pd.isna(day_rows.loc["000001.SZ", "top200_rank"])
    assert not bool(day_rows.loc["000001.SZ", "top200_membership"])
    prior = frame.loc[(frame["trade_date"] == dates[60]) & (frame["ts_code"] == "920001.BJ")].iloc[0]
    assert prior["top200_rank_t1"] == 1
    assert bool(prior["top200_member_t1"])
    assert top_meta["official_rank_override_applied"]
    assert day == official_meta["asof_date"]
    assert next_day != day


def test_training_anchor_overlap_purges_training_side_only() -> None:
    frame = pd.DataFrame({
        "ts_code": ["000001.SZ", "000001.SZ", "000002.SZ", "000003.SZ"],
        "trade_date": ["20260830", "20260902", "20260830", "20260902"],
        "_anchor_date": ["20260801", "20260801", None, None],
        "model_eligible": [True, True, True, True],
    })
    result, guard = study._episode_split(frame)
    assert guard["cross_split_anchor_group_count"] == 1
    assert guard["train_dropped_for_cross_split_anchor"] == 1
    assert guard["oos_retained_after_training_purge"] == 2
    assert not bool(guard["train_mask"].iloc[0])
    assert bool(guard["oos_safe_mask"].iloc[1])
