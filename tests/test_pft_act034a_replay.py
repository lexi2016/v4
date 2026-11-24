from types import SimpleNamespace

import pandas as pd
import pytest

from ops import pft_act034a_replay as replay
from ops import pft_act034a_rules as rules


CODE = "600000.SH"
DATES = ["20261116", "20261117", "20261118", "20261119", "20261120"]
CONTEXT = ["20261112", "20261113", *DATES]


def signal(**overrides):
    return SimpleNamespace(**{
        "ts_code": CODE, "final_state": "CONFIRMED_S", "stage": "POST_REPAIR", "route_reasons": "GROUP",
        "projected_p_s": .85, "anchor_age_calendar_days": 8, "cushion": .18, "float_mv_d_cny": 50e9,
        "amplitude_ma20": .029, "vol_d": 115, "vol_ma5_d": 100, "return_d": .085, "raw_bullish": True,
        "amount_d_cny": 100e6, "return_5d": .15, **overrides,
    })


def quote(**overrides):
    return {"eligible_for_daily_gain_rank": True, "name": "样本", "zero_volume": False,
            "prev_close": 10., "open": 10., "high": 10.3, "low": 9.8, "close": 10.1, **overrides}


def path(closes, opens=None):
    opens = opens or {}
    return {day: {"open": opens.get(day, 10.), "close": close, "low": min(close, 9.8)}
            for day, close in zip(DATES, closes)}


def test_b2_confirmed_boundaries_and_slow_dividend_missing_cap():
    assert rules.selection_atoms(signal(), .03)["b2_eligible"] is True
    assert rules.selection_atoms(signal(cushion=.05), .03)["b2_eligible"] is False
    assert rules.selection_atoms(signal(cushion=.18001), .03)["b2_eligible"] is False
    assert rules.selection_atoms(signal(float_mv_d_cny=51e9), .03)["b2_eligible"] is False
    assert rules.selection_atoms(signal(float_mv_d_cny=51e9, amplitude_ma20=.03), .03)["b2_eligible"] is True
    assert rules.selection_atoms(signal(float_mv_d_cny=None), .03)["b2_eligible"] is True
    assert rules.selection_atoms(signal(ts_code="300001.SZ"), .03)["b2_eligible"] is False
    assert rules.selection_atoms(signal(vol_d=114.99), .03)["b2_eligible"] is False


def test_b2_exact_pure_head_golden_and_c1_veto_precedence():
    pulse = dict(final_state="UNKNOWN_BORDERLINE", route_reasons="RAW_HEAD_DECISION_CONTRADICTION",
                 stage=pd.NA, projected_p_s=None, cushion=.10)
    atoms = rules.selection_atoms(signal(**pulse), .03)
    assert (atoms["b2_eligible"], atoms["b2_golden_priority"], atoms["c1_pass"]) == (True, True, True)
    atoms = rules.selection_atoms(signal(**{**pulse, "cushion": .15, "amount_d_cny": None}), .035)
    assert atoms["b2_golden_priority"] is False
    assert atoms["c1_pass"] is None
    atoms = rules.selection_atoms(signal(**{**pulse, "route_reasons": pulse["route_reasons"] + "|OTHER",
                                             "amount_d_cny": None, "return_5d": .150001}), .035)
    assert atoms["b2_eligible"] is False
    assert atoms["c1_pass"] is False
    assert atoms["c1_veto_reasons"] == "return5_above_15pct"
    assert atoms["c1_unknown_atoms"] == "amount_below_100m"


def test_rebase_anchor_composes_events_and_rechecks_selected_fields():
    item = {"history_start_date": 20260101, "event_coverage_complete": True,
            "events": [{"ex_date": 20261113, "a": .5, "b": -.1},
                       {"ex_date": 20261117, "a": .8, "b": -.5},
                       {"ex_date": 20261118, "a": .9, "b": -.2}]}
    events = rules.affine_events(item, "20261113")
    assert rules.to_cutoff_basis(10, "20261113", events) == pytest.approx(6.55)
    assert rules.to_cutoff_basis(10, "20261117", events) == pytest.approx(8.8)
    cutoff, state = rules.verified_bar({"tradeable_basic": 1, "vol": 10, "open": 8.8, "close": 8.9, "low": 8.6},
                                       quote(close=10.1), "20261117", events)
    assert cutoff["open"] == 8.8
    assert "close" not in cutoff
    assert state == "CUTOFF_QFQ_RAW_AFFINE_MISMATCH"
    assert rules.affine_events(None, "20261113") is None
    with pytest.raises(replay.act031.ContractError, match="EVENT_ORDER"):
        rules.affine_events({**item, "events": item["events"][::-1]}, "20261113")


def test_a1_d1_cost_stop_cannot_sell_same_day_and_retries_later_open():
    price = path([9.3, 9., 10., 10., 10.], {DATES[1]: 9., DATES[2]: 9.4})
    quotes = dict.fromkeys(DATES, quote())
    quotes[DATES[0]] = quote(close=9.3, low=9.1)
    quotes[DATES[1]] = quote(open=9., close=9., low=9., high=9.)
    out = rules.a1_exit(CODE, DATES, CONTEXT, quotes, price, 10., 9.5, {})
    assert out.signal_date == DATES[0]
    assert out.exit_date == DATES[2] and out.time == "OPEN"
    assert out.reason == "CLOSE_LT_INVALIDATION|CLOSE_LOSS_GTE_7_VS_COST|D1_OPEN_TO_CLOSE_LTE_MINUS_3"
    assert out.status == "MODELED_FILLED_DELAYED"
    assert out.attempts[0]["reason"] == "EXIT_OPEN_AT_LOWER_CAP"
    price[DATES[2]]["low"] = 5.
    assert rules.path_low(DATES, price, out, 10.)["worst_observed_path_gross"] == pytest.approx(-.10)


def test_a1_t3_uses_only_trailing_ma5_and_t5_hard_close_wins():
    quotes = dict.fromkeys(DATES, quote())
    price = path([10.1, 10.2, 10.3, 10.4, 9.3])
    ma = dict(zip(CONTEXT, [10., 10., 10.1, 10.2, 10.3, 100., 100.]))
    out = rules.a1_exit(CODE, DATES, CONTEXT, quotes, price, 10., 9.5, ma)
    assert out.t3_ma5 == pytest.approx(10.12)
    assert out.reason == "T5_HARD_CLOSE"
    assert out.t5_trigger_audit == "CLOSE_LT_INVALIDATION|CLOSE_LOSS_GTE_7_VS_COST"
    assert (out.exit_date, out.time) == (DATES[4], "CLOSE")
    ma[CONTEXT[0]] = 50.
    out = rules.a1_exit(CODE, DATES, CONTEXT, quotes, price, 10., 9.5, ma)
    assert out.reason == "T3_PLANNED_CLOSE"
    assert out.exit_date == DATES[2]


def test_a1_earlier_queue_beats_t5_and_unknown_stays_unknown():
    quotes = dict.fromkeys(DATES, quote())
    price = path([10.1, 10.2, 10.3, 9.3, 10.1])
    ma = dict(zip(CONTEXT, [10., 10., 10.1, 10.2, 10.3, 9.3, 10.1]))
    out = rules.a1_exit(CODE, DATES, CONTEXT, quotes, price, 10., 9.5, ma)
    assert out.exit_date == DATES[4] and out.time == "OPEN"
    assert out.reason == "CLOSE_LT_INVALIDATION|CLOSE_LOSS_GTE_7_VS_COST"
    out = rules.a1_exit(CODE, DATES, CONTEXT, quotes, price, 10., 9.5, {})
    assert out.reason == "T3_EXTENSION_MA5_UNKNOWN" and out.exit_date is None
    price[DATES[1]].pop("close")
    out = rules.a1_exit(CODE, DATES, CONTEXT, quotes, price, 10., 9.5, ma)
    assert out.reason == "A1_INTERMEDIATE_STOP_EVIDENCE_UNKNOWN" and out.exit_date is None


def test_b2_high_trigger_uses_official_prev_close_and_does_not_extend_past_t3():
    price = path([10.3, 9., 9., 10., 10.])
    quotes = dict.fromkeys(DATES, quote())
    quotes[DATES[0]] = quote(open=10.2, high=10.4, close=10.3)
    quotes[DATES[1]] = quotes[DATES[2]] = quote(open=9., high=9., low=9., close=9.)
    out = rules.b2_exit(CODE, DATES, quotes, price)
    assert out.reason == "D1_HIGH_GTE_4_AND_CLOSE_BELOW_CAP"
    assert out.exit_date is None and out.status == "EXIT_BLOCKED_AT_DEADLINE"
    assert [x["date"] for x in out.attempts] == DATES[1:3]
    assert out.cutoff_mark == 9.
    assert rules.b2_exit(CODE, DATES[:1], quotes, price).status == "EXIT_DUE_AFTER_CUTOFF"
    quotes[DATES[0]] = quote(high=11., close=11.)
    quotes[DATES[2]] = quote()
    out = rules.b2_exit(CODE, DATES, quotes, price)
    assert out.reason == "T3_PLANNED_CLOSE"
    quotes[DATES[0]] = quote(open=9.6, high=9.9, low=9.5, close=9.7)
    out = rules.b2_exit(CODE, DATES, quotes, price)
    assert out.reason == "D1_CLOSE_LTE_MINUS_3_VS_OFFICIAL_PREV"


def test_matched_rows_and_fixed_mark_availability_not_laundered_as_trade():
    rows = [{"trade_date": "20261116", "ts_code": CODE,
             "dynamic_gross": -.102, "dynamic_net": -.105,
             "fixed_t3_mark_gross": -.099, "fixed_t3_mark_net": -.102},
            {"trade_date": "20261117", "ts_code": CODE,
             "dynamic_gross": None, "dynamic_net": None,
             "fixed_t3_mark_gross": -.19, "fixed_t3_mark_net": -.193}]
    result = replay.paired(rows, "fixed_t3_mark")
    assert result["n"] == 1
    assert result["dynamic"]["gross_below_minus_10_n"] == 1
    assert result["fixed"]["gross_below_minus_10_n"] == 0
    assert result["fixed"]["net_below_minus_10_n"] == 1
    assert replay.return_metrics(rows, "fixed_t3_mark")["n"] == 2
