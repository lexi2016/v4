import pandas as pd
import pytest

from ops import pft_act031_frozen_forward as forward


A, B, C = "600001.SH", "000001.SZ", "920001.BJ"


def test_frozen_calendar_and_outcome_before_seal_fails(tmp_path, monkeypatch):
    expected = pd.bdate_range("2026-10-26", "2026-11-23").strftime("%Y%m%d").tolist()
    path = tmp_path / "inputs.json"
    inputs = {"signal_dates": expected[:-1], "observation_dates": expected, "cutoff": expected[-1],
              "days": dict.fromkeys(expected, {})}
    forward.json_atomic(path, inputs)
    loaded, sessions = forward.load_inputs(path)
    assert loaded == inputs and len(expected) == 21
    assert sessions.age("20261116", "20261120")[0] == 4
    monkeypatch.setattr(forward, "load_outcomes", lambda *_: pytest.fail("outcomes before seal"))
    with pytest.raises(forward.ContractError, match="MUST_BE_SEALED"):
        forward.outcome_phase(inputs, forward.ref(path), tmp_path)


def test_exact_eligibility_keeps_k_count_and_bse_distinct():
    names = {A: "样本", B: "Ｓ＊ＳＴ样本", C: "样本", "000002.SZ": "样本", "000003.SZ": "样本"}
    exact = pd.DataFrame([{"ts_code": code, "tradeable_basic": 1, "zge_white_line": 2, "zge_yellow_line": 1}
                          for code in names if code != "000003.SZ"])
    quotes = {code: {"name": name, "eligible_for_daily_gain_rank": code != "000003.SZ"} for code, name in names.items()}
    eligible, counts = forward.select_eligible(exact, quotes, {A: 65, B: 80, C: 64})
    assert list(eligible) == [A]
    assert counts == {"ELIGIBLE": 1, "D_ST": 1, "D_LT_65_K": 1, "D_K_COUNT_UNKNOWN": 1, "D_NONTRADABLE_OR_INVALID": 1}


def test_signals_use_exact_g1_then_frozen_route_and_repair_age(monkeypatch):
    day = "20261120"
    eligible = {A: {"white": 9, "yellow": 10}, B: {"white": 12, "yellow": 10}, C: {"white": 12, "yellow": 10}}
    evidence = [
        {"status": "READY", "white": 12, "yellow": 10, "yellow_extension": .1,
         "anchors": {"events": [{"role": "repair", "date": "20261110"}, {"role": "repair", "date": "20261117"}]}},
        {"status": "READY", "white": 12, "yellow": 10, "yellow_extension": .1,
         "anchors": {"events": [{"role": "repair", "date": "20261116"}],
                     "active": {"low": 10.4, "date": "20261119", "anchor_id": "active-management"}}},
    ]

    def extract(_, requested_day, codes):
        assert codes == [B, C] and requested_day == day
        return None, evidence

    monkeypatch.setattr(forward.prior, "extract_structure", extract)
    monkeypatch.setattr(forward.prior, "batch_predict", lambda *_: {i: (.9, [.02, .03, .9, .05]) for i in range(2)})
    rows = forward.route_signals(eligible, None, day, {}, forward.act028.ExchangeSessions()).set_index("ts_code")
    assert rows.loc[A, "route_reasons"] == "STRICT_OBSERVED_W_BELOW_Y"
    assert pd.isna(rows.loc[A, "raw_p_s"])
    assert rows.loc[B, "act025_state"] == "CONFIRMED_S"
    assert rows.loc[B, "repair_anchor_date"] == "20261117"
    assert rows.loc[B, "repair_age_sessions"] == 3
    assert rows.loc[B, "UNKNOWN_PROJECTED_GE_045"]
    assert rows.loc[C, "rebuild"] and rows.loc[C, "repair_age_sessions"] == 4
    assert rows.loc[C, "invalidation_price"] == 10.4
    assert rows.loc[C, "invalidation_anchor_date"] == "20261119"
    assert rows.loc[C, "invalidation_price_source"] == "ACT021_ACTIVE_ANCHOR_LOW_QFQ_ASOF_D"
    assert pd.isna(rows.loc[B, "invalidation_price"]) and rows.loc[B, "invalidation_price_source"] == "CANNOT_CONFIRM"


def test_g1_only_cohort_stays_valid():
    signals = forward.route_signals({A: {"white": 9, "yellow": 10}}, None, "20261120", {}, None)
    assert signals.ELIGIBLE_ALL_A.item()
    assert not signals.UNKNOWN_PROJECTED_GE_045.item()


def quote(opening, close, *, high=None, low=None, prev=10, name="样本"):
    return {"open": opening, "high": max(opening, close) if high is None else high,
            "low": min(opening, close) if low is None else low, "close": close, "prev_close": prev,
            "change_pct": (close / prev - 1) * 100, "eligible_for_daily_gain_rank": True, "name": name}


def test_open_price_proxy_does_not_mistake_one_price_for_fill():
    assert forward.opening_assessment(A, quote(11, 11, name="*ST sample"))["one_price_upper_limit"] is True
    assert forward.opening_assessment(A, quote(11, 10.5))["opening_buyable_proxy"] is False
    assert forward.opening_assessment(A, quote(10.5, 11))["opening_buyable_proxy"] is True
    assert forward.opening_assessment("300001.SZ", quote(12, 12))["one_price_upper_limit"] is True
    assert forward.opening_assessment(C, quote(13, 13))["one_price_upper_limit"] is True
    assert forward.opening_assessment(A, quote(11.5, 11.5))["one_price_upper_limit"] is None
    assert forward.opening_assessment(A, None)["opening_buyable_proxy"] is None


def test_raw_fallback_and_native_rank_are_dated_and_distinct(tmp_path):
    day = "20261123"
    codes = [f"{600000 + i:06d}.SH" for i in range(201)]
    quotes = {code: {"eligible_for_daily_gain_rank": True, "change_pct": 1, "symbol": code} for code in reversed(codes)}
    ranks, source = forward.rank_for_day(day, {}, quotes)
    assert source == "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK"
    assert ranks[codes[0]] == 1 and codes[-1] not in ranks
    payload = {"schema": "V4_A_SHARE_TOP200_V1", "data_date": day, "source_generation": "g",
               "official_input": {"path": "quote", "sha256": "quote-sha"},
               "top200": [{"rank": i, "symbol": code} for i, code in enumerate(codes[1:], 1)]}
    path = tmp_path / "rank.json"
    reference = forward.json_atomic(path, payload)
    source_ref = {"rank_ref": reference, "source_generation": "g", "official_ref": payload["official_input"]}
    ranks, source = forward.rank_for_day(day, source_ref, quotes)
    assert source == "V4_OFFICIAL_TOP200" and ranks[codes[-1]] == 200 and codes[0] not in ranks
    with pytest.raises(forward.ContractError, match="OFFICIAL_RANK_DATE"):
        forward.rank_for_day("20261120", source_ref, quotes)


def test_outcomes_match_exact_calendar_missingness_and_benchmarks():
    days = ["20261116", "20261117", "20261118", "20261119", "20261120", "20261123"]
    signal = pd.DataFrame({"ts_code": [A, B, C]})
    observations = {days[1]: {"quotes": {A: quote(11, 11), B: quote(10, 9.5)}, "ranks": {A: 1},
                              "rank_source": "RAW_ALL_A_DAILY_GAIN_TOP200_FALLBACK"},
                    days[-1]: {"quotes": {A: quote(10, 10.2)}, "ranks": {B: 200}, "rank_source": "V4_OFFICIAL_TOP200"}}
    prices = pd.DataFrame([[10, 11, 12, 13, 13, 14], [10, 9.5, 9, 8.5, 8, 8], [10, 11, None, 12, 13, 14]], index=[A, B, C], columns=days)
    result = forward.day_forward(signal, days[0], days, observations, prices).set_index("ts_code")
    assert result.loc[A, "d1_excess_return"] == pytest.approx(.075)
    assert pd.isna(result.loc[A, "d1_modeled_open_close_return"])
    assert result.loc[B, "d1_modeled_open_close_return"] == pytest.approx(-.05)
    assert result.loc[B, "t3_modeled_open_close_return"] == pytest.approx(-.15)
    assert result.loc[B, "t5_return"] == pytest.approx(-.2)
    assert result.loc[B, "t5_date"] == "20261123"
    assert result.loc[B, "t3_benchmark_min_daily_n"] == 2
    assert pd.isna(result.loc[C, "t3_return"]) and pd.isna(result.loc[C, "t5_return"])
    assert pd.isna(result.loc[C, "d1_top200_hit"])
    metrics = forward.group_metrics(result)
    assert metrics["t5_mature_n"] == 3 and metrics["t5_economic_n"] == 2
    assert metrics["t5_below_minus_10pct_rate"] == .5
    assert metrics["d1_top200_raw_fallback_denominator"] == 2
    late = forward.day_forward(signal, days[-2], days, observations, prices).set_index("ts_code")
    assert late.loc[B, "d1_top200_hit"] and not late.loc[C, "d1_top200_hit"]
    assert not late.t3_mature.any() and not late.t5_mature.any()
    assert late.t3_return.isna().all() and late.t5_return.isna().all()


def test_recovered_symbol_projects_exact_d_with_pinned_full_prefix_math(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ops import pft_act031_raw_prefix as recovery

    def ema(series, span):
        return series.ewm(span=span, adjust=False, min_periods=1).mean()

    path = tmp_path / "bound.day"
    path.touch()
    dates = [20261117, 20261118, 20261119, 20261120, 20261123]
    close = [10., 11., 13., 9., -1.]
    raw = pd.DataFrame(dict(ts_code=A, trade_date=dates, open=close, high=close,
                            low=close, close=close, vol=1, volume=1, amount=1))
    monkeypatch.setattr(recovery.qfq, "resolved_raw_history", lambda *_: raw)
    item = {"raw_files": [{"path": str(path)}], "events": [], "history_start_date": dates[0], "event_coverage_complete": True}
    out, reason = recovery.read_symbol(A, item, dates[3], dates[1], None, SimpleNamespace(ema_by_group=ema))
    assert reason is None and out.trade_date.tolist() == [str(day) for day in dates[1:4]]
    assert out.zge_white_line.iloc[-1] == pytest.approx(ema(ema(pd.Series(close[:4]), 10), 10).iloc[-1])
    assert out.bars_since_list.tolist() == [2, 3, 4]
    assert out.tradeable_basic.eq(1).all()
    _, reason = recovery.read_symbol(A, item, 20261122, dates[1], None, SimpleNamespace(ema_by_group=ema))
    assert reason == "NO_EXACT_D_IN_BOUND_RAW_HISTORY"


def test_raw_sha_drift_reuses_only_bound_exact_date_native_alias(tmp_path, monkeypatch):
    import hashlib
    from ops import pft_act031_raw_prefix as recovery

    root = tmp_path / "research_panel_daily"
    live = root / "tdx/vipdoc/sh/lday/sh600001.day"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"newer history")
    pinned = b"raw as of D"
    item = {"raw_files": [{"path": str(live), "sha256": hashlib.sha256(pinned).hexdigest()}]}
    exact_date, next_date = 20261103, 20261104
    locations = [root / "receipts/formula_inputs" / str(day) / "g/vipdoc/sh/lday/sh600001.day"
                 for day in (exact_date, next_date)]
    for location, payload in zip(locations, (b"same date different bytes", pinned)):
        location.parent.mkdir(parents=True)
        location.write_bytes(payload)

    def read(code, recipe, target, driver):
        return recovery.qfq._source(recipe["raw_files"][0], owner=code).read_bytes()

    monkeypatch.setattr(recovery.qfq, "resolved_raw_history", read)
    assert recovery.bound_raw_history(A, item, exact_date, None) == (None, "BOUND_RAW_SHA_UNAVAILABLE", [])
    locations[0].write_bytes(pinned)
    result, reason, substitutions = recovery.bound_raw_history(A, item, exact_date, None)
    assert result == pinned and reason is None
    assert substitutions == [{"symbol": A, "alias_path": str(locations[0]), "original_path": str(live),
                              "sha256": item["raw_files"][0]["sha256"]}]
    assert item["raw_files"][0]["path"] == str(live)

    def broken(*_):
        raise recovery.qfq.QfqGateError("RAW_SOURCE_OVERLAP_CONFLICT:" + A)

    monkeypatch.setattr(recovery.qfq, "resolved_raw_history", broken)
    with pytest.raises(recovery.qfq.QfqGateError, match="RAW_SOURCE_OVERLAP_CONFLICT"):
        recovery.bound_raw_history(A, item, exact_date, None)
