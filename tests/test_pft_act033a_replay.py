from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from ops import pft_act033a_groups as groups
from ops import pft_act033a_outcomes as outcomes
from ops import pft_act033a_replay as replay


def structure(**overrides):
    return SimpleNamespace(**{
        "ts_code": "600000.SH", "final_state": "CONFIRMED_S", "stage": "POST_REPAIR",
        "main_tactic": "pullback", "projected_p_s": .85, "route_reasons": "BASE",
        **overrides,
    })


def gate_data(**overrides):
    return {
        "anchor_age_calendar_days": 8, "cushion": .10, "vol_d": 80, "vol_ma5_d": 100,
        "anchor_vol": None, "return_d": .035, "kdj_j": None, "defended_white_yellow": None,
        "vol_min_prior3": 75, "vol_ma10_d": 100, "vol_ratio_prior_day": 1.30,
        "raw_bullish": True, "close_bar_fraction": .65, "turnover_ma20_pct": 1.5,
        "amplitude_d": .01, "amplitude_ma20": .03, "float_mv_d_cny": 50e9, "return_5d": .15,
        "b2_rank_score": 1.3 * .85, "board_cap_status": "NON_LIMIT_NON_ONE_PRICE",
        **overrides,
    }


def quote(**overrides):
    return {
        "eligible_for_daily_gain_rank": True, "name": "证券",
        "open": 10.5, "high": 10.7, "low": 10.3, "close": 10.65, "prev_close": 10,
        **overrides,
    }


def test_frozen_window_training_overlap_and_regime():
    sessions = replay.act031.act028.ExchangeSessions()
    dates = replay.previous_days(sessions.schedule, replay.CUTOFF, replay.SIGNAL_COUNT)
    assert dates[0] == "20260821"
    assert dates[39:41] == ["20261023", "20261026"]
    assert dates[-2:] == ["20261120", "20261123"]
    assert len([date for date in dates if date <= replay.TRAINING_END]) == 7
    window = replay.previous_days(sessions.schedule, "20261026", 4)
    market = {date: {"equal_weight_return": 0} for date in window}
    assert replay.market_regime("20261026", sessions, market)["name"] == "FLAT"
    market[window[1]] = {"equal_weight_return": .01}
    assert replay.market_regime("20261026", sessions, market)["name"] == "UP"
    market[window[1]] = {"equal_weight_return": -.01}
    assert replay.market_regime("20261026", sessions, market)["name"] == "DOWN"
    del market[window[1]]
    assert replay.market_regime("20261026", sessions, market)["missing_days"] == [window[1]]


@pytest.mark.parametrize("change,expected", [(0, False), (.10, True), (.10001, False), (None, None)])
def test_a0_cushion_edges_and_stage_independence(change, expected):
    row = structure(stage="HOLD")
    actual = groups.structural(row, gate_data(cushion=change))
    assert actual["A0_eligible"] is expected
    assert actual["A1_eligible"] is False


def test_a1_disjunction_preserves_missingness_and_defends_both_lines():
    a1 = lambda **changes: groups.structural(structure(), gate_data(**changes))["A1_eligible"]
    assert a1() is True
    assert a1(vol_ma5_d=None, anchor_vol=None) is None
    assert a1(vol_ma5_d=None, anchor_vol=120) is True
    assert a1(return_d=.04, kdj_j=20, defended_white_yellow=True) is True
    assert a1(return_d=.04, kdj_j=20, defended_white_yellow=False) is False
    assert a1(return_d=.04, kdj_j=20, defended_white_yellow=None) is None


def test_b1_exact_union_and_trigger_atoms():
    assert groups.structural(structure(), gate_data(cushion=.05))["b1_structural_eligible"] is False
    assert groups.structural(structure(), gate_data(cushion=.20))["b1_structural_eligible"] is True
    row = structure(final_state="UNKNOWN_BORDERLINE", stage=None, main_tactic="",
                    route_reasons=groups.CONTRADICTION, projected_p_s=.50)
    assert groups.structural(row, gate_data(cushion=None))["B1_eligible"] is True
    row.route_reasons += ";STRONG_BINARY_FAKE_HEAD_CONTRADICTION"
    assert groups.structural(row, gate_data())["B1_eligible"] is False
    row.route_reasons = groups.CONTRADICTION
    assert groups.structural(row, gate_data(amplitude_ma20=.029))["B1_eligible"] is False
    missing = groups.structural(row, gate_data(turnover_ma20_pct=None))
    assert missing["B1_eligible"] is None and missing["b2_unknown_atoms"] == "turnover_ma20"
    row.ts_code = "300001.SZ"
    assert groups.structural(row, gate_data())["B1_eligible"] is False


def test_crowd_uses_baseline_and_rank_ties_are_deterministic(monkeypatch):
    codes = [f"{600000 + i}.SH" for i in range(121)]
    signal = pd.DataFrame([vars(structure(ts_code=code)) for code in reversed(codes)])
    def fake_evidence(row, history, quotes, days):
        return {**gate_data(cushion=.50 if row.ts_code not in codes[:10] else .08), "dividend_style_proxy": None}
    monkeypatch.setattr(groups, "evidence", fake_evidence)
    selected, summary = groups.select_day(signal, pd.DataFrame(columns=["ts_code", "trade_date"]), {}, [])
    assert summary["a1_confirmed_crowd_count"] == 121
    assert summary["a1_crowd_class"] == "SEVERE"
    assert set(selected.loc[selected.A0, "ts_code"]) == set(codes[:5])
    assert set(selected.loc[selected.A1, "ts_code"]) == set(codes[:3])
    assert set(selected.loc[selected.B1, "ts_code"]) == set(codes[:8])
    assert summary["groups"]["C1"]["selected_n"] is None
    assert selected.C1_eligible.isna().sum() == 8


def test_exact_rolling_sessions_no_compressed_gap():
    dates = [(datetime(2026, 10, 1) + timedelta(days=i)).strftime("%Y%m%d") for i in range(21)]
    hist = {date: {"open": 9, "high": 11, "low": 9, "close": 10, "vol": 50,
                   "turnover_rate_pct": 2, "float_share_10k": 600000, "j": 15}
            for date in dates}
    hist[dates[-1]]["vol"] = 60
    row = structure(invalidation_anchor_date=dates[-9], invalidation_price=9, white=9, yellow=8.5)
    data = groups.evidence(row, hist, quote(), dates)
    assert data["anchor_age_calendar_days"] == 8 and data["vol_ma5_d"] == 52
    assert data["defended_white_yellow"] is True and data["turnover_ma20_pct"] == 2
    assert data["amplitude_ma20"] == .2
    del hist[dates[-2]]
    missing = groups.evidence(row, hist, quote(), dates)
    assert missing["vol_ma5_d"] is None and missing["amplitude_ma20"] is None
    assert missing["turnover_ma20_pct"] is None


def test_open_and_exit_proxies_and_only_b1_gap():
    assert outcomes.opening_outcome("600000.SH", quote(), gap_gate=True)[0] is True
    assert outcomes.opening_outcome("600000.SH", quote(open=10.51), gap_gate=True) == (
        False, "D1_B2_GAP_GT_5_PERCENT", pytest.approx(.051))
    assert outcomes.opening_outcome("600000.SH", quote(open=10.51))[0] is True
    assert outcomes.opening_outcome("600000.SH", quote(open=11, high=11))[0] is False
    assert outcomes.opening_outcome("600000.SH", None)[0] is None
    assert outcomes.selling_outcome("600000.SH", quote(low=9, close=9)) == (False, "EXIT_CLOSE_AT_LOWER_CAP")
    assert groups.main_board_d_cap(quote(open=10, high=10, low=10, close=10)) == "ONE_PRICE"


def test_b1_known_open_fail_remains_cash_and_does_not_refill():
    selection = pd.DataFrame({"trade_date": ["20261120"] * 3, "ts_code": ["A", "B", "C"],
                              "B1": [True, True, False], "dividend_style_proxy": pd.array([False, False, pd.NA], dtype="boolean")})
    realized = pd.DataFrame({
        "trade_date": ["20261120"] * 3, "ts_code": ["A", "B", "C"],
        "opening_fillable": pd.array([True, True, True], dtype="boolean"),
        "opening_gap": [.05, .051, .01], "opening_status": ["OPEN"] * 3,
        "t1_gross": [.01, .02, .03], "t3_gross": [None] * 3, "t5_gross": [None] * 3,
        "d1_top200_label_source": ["V4_OFFICIAL_TOP200"] * 3,
        "d1_top200_hit": pd.array([True, True, False], dtype="boolean"),
    })
    rows, daily = outcomes.apply_strategy(selection, realized, "20261120", "UP", "B1", {"unknown_n": 0}, ["20261123"])
    assert rows.ts_code.tolist() == ["A", "B"]
    assert daily["picked_n"] == 2 and daily["filled_n"] == 1 and daily["known_no_fill_n"] == 1
    assert daily["t1_benchmark_gross"] == pytest.approx(.02)
    assert daily["t1_net"] == pytest.approx(.007)
    assert daily["t1_costed_mtm_cash_weighted"] == pytest.approx(.0035)
    assert daily["top200_official_hits"] == 2 and daily["t3_mature"] is False


def test_nav_does_not_compound_across_missing_days():
    dates = ["20261118", "20261119", "20261120"]
    frame = pd.DataFrame([{"trade_date": date, "group": group, "status": "stub", "t1_costed_mtm_cash_weighted": value}
                          for date, value in zip(dates, [.1, None, -.1]) for group in groups.ALL_GROUPS])
    nav = outcomes.nav_curve(frame, dates)
    base = nav.loc[nav.group.eq("BASE")]
    assert base.t1_costed_mtm_segment_nav.tolist()[::2] == pytest.approx([1.1, .9])
    assert base.t1_costed_mtm_segment_nav.isna().tolist() == [False, True, False]
    assert base.recent20_t1_costed_mtm_nav.isna().tolist() == [False, True, True]


def test_outcome_cannot_open_before_signal_seal(tmp_path):
    with pytest.raises(replay.ContractError, match="ACT033A_SIGNALS_MUST_BE_SEALED_BEFORE_OUTCOMES"):
        outcomes.outcome_phase({}, {}, None, tmp_path)


def test_lower_limit_close_is_flagged_and_kept_in_tail_risk():
    code = "600000.SH"
    prior = pd.DataFrame({"ts_code": [code], "d1_modeled_open_close_return": [.01],
                          "t3_modeled_open_close_return": [-.15], "t5_modeled_open_close_return": [-.17]})
    dates = ["20261113", "20261116", "20261117", "20261118", "20261119"]
    observations = {day: {"quotes": {code: quote()}} for day in dates}
    observations[dates[-1]] = {"quotes": {code: quote(low=9, close=9)}}
    result = outcomes.daily_execution(prior, dates, observations)
    assert result.exit_t5_status.iloc[0] == "EXIT_CLOSE_AT_LOWER_CAP"
    assert result.t5_gross.iloc[0] == -.17
