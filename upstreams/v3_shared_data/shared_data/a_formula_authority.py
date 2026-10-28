"""Pure V4 A-share formula authority.

The calculation bodies are migrated from the reviewed canonical formula builder;
this module deliberately has no default data root, network client, pointer, or
producer side effect. Inputs and optional ex-rights columns are supplied by the
caller as explicit DataFrames.

Origin evidence (reference-only, never imported at runtime):
- canonical formula builder SHA256: 074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258
- migrated pure regions: source lines 47-164, 167-170, 206-218, 221-517
"""
from __future__ import annotations

from typing import Any
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

FORMULA_VERSION = "v1.9.2"
FORMULA_SOURCE = "computed_main_chart_formula_20260515"
ORIGIN_SHA256 = "074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258"

def ema_by_group(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=1).mean()

def rec_sma(series: pd.Series) -> pd.Series:
    out: list[float] = []
    prev = 50.0
    for value in series.astype(float).fillna(50.0):
        prev = (2.0 * prev + value) / 3.0
        out.append(prev)
    return pd.Series(out, index=series.index)

def tdx_sma(series: pd.Series, n: int, m: int, init: float | None = None) -> pd.Series:
    out: list[float] = []
    prev: float | None = init
    for raw in series.astype(float):
        value = float(raw) if pd.notna(raw) else prev
        if value is None or pd.isna(value):
            value = 0.0
        if prev is None or pd.isna(prev):
            prev = value
        else:
            prev = (m * value + (n - m) * prev) / n
        out.append(float(prev))
    return pd.Series(out, index=series.index)

def bool_int(value: pd.Series) -> pd.Series:
    return value.fillna(False).astype(np.int8)

def rolling_count(value: pd.Series, window: int) -> pd.Series:
    return value.fillna(False).astype(int).rolling(window, min_periods=1).sum()

def rolling_exist(value: pd.Series, window: int) -> pd.Series:
    return rolling_count(value, window).gt(0)

def rolling_every(value: pd.Series, window: int) -> pd.Series:
    return value.fillna(False).astype(int).rolling(window, min_periods=window).sum().eq(window)

def rolling_count_prev(series: pd.Series, window: int) -> pd.Series:
    return series.shift(1).rolling(window, min_periods=window).sum()

def ref_by_offset(values: np.ndarray, offsets: np.ndarray, default: np.ndarray | float) -> np.ndarray:
    out = np.full(len(values), np.nan, dtype="float64")
    if np.isscalar(default):
        out[:] = float(default)
    else:
        out[:] = default
    for i, off in enumerate(offsets.astype(int)):
        if off > 0 and i - off >= 0:
            out[i] = values[i - off]
    return out

def ref_series_by_offsets(series: pd.Series, offsets: pd.Series | np.ndarray, default: float = np.nan) -> pd.Series:
    values = series.to_numpy(dtype="float64")
    offset_values = pd.Series(offsets, index=series.index).fillna(0).astype(int).to_numpy()
    return pd.Series(ref_by_offset(values, offset_values, default), index=series.index)

def barslast_bool(series: pd.Series) -> pd.Series:
    arr = series.fillna(False).to_numpy(dtype=bool)
    out = np.full(len(arr), np.nan, dtype="float64")
    last = -1
    for i, flag in enumerate(arr):
        if flag:
            last = i
            out[i] = 0
        elif last >= 0:
            out[i] = i - last
    return pd.Series(out, index=series.index)

def cross_over(a: pd.Series, b: pd.Series | float) -> pd.Series:
    if np.isscalar(b):
        b_series = pd.Series(float(b), index=a.index)
    else:
        b_series = b
    return a.gt(b_series) & a.shift(1).le(b_series.shift(1))

def hhvbars(series: pd.Series, window: int) -> pd.Series:
    values = series.to_numpy(dtype="float64")
    out = np.zeros(len(values), dtype="int64")
    for i in range(len(values)):
        start = max(0, i - window + 1)
        part = values[start : i + 1]
        if len(part) == 0 or np.all(np.isnan(part)):
            out[i] = 0
            continue
        max_value = np.nanmax(part)
        positions = np.where(part == max_value)[0]
        out[i] = len(part) - 1 - int(positions[-1])
    return pd.Series(out, index=series.index)

def safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)

def ts_code_from_gbbq(market: Any, code: Any) -> str:
    code_s = str(code).strip().zfill(6)
    if code_s.startswith(("4", "8", "9")):
        return f"{code_s}.BJ"
    if code_s.startswith(("0", "2", "3")):
        return f"{code_s}.SZ"
    if code_s.startswith(("5", "6", "7")):
        return f"{code_s}.SH"
    try:
        return f"{code_s}.SH" if int(market) == 1 else f"{code_s}.SZ"
    except Exception:
        return f"{code_s}.SZ"

def empty_xdxr_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["ts_code", "_xdxr_trade_date", "xdxr_fenhong", "xdxr_peigujia", "xdxr_songzhuangu", "xdxr_peigu"]
    )

def apply_xdxr_pre_close(group: pd.DataFrame, raw_pre_close: pd.Series) -> pd.Series:
    required = ["xdxr_fenhong", "xdxr_peigujia", "xdxr_songzhuangu", "xdxr_peigu"]
    if not set(required).issubset(group.columns):
        return raw_pre_close
    event_present = group[required].notna().any(axis=1)
    fenhong = pd.to_numeric(group["xdxr_fenhong"], errors="coerce").fillna(0.0)
    peigujia = pd.to_numeric(group["xdxr_peigujia"], errors="coerce").fillna(0.0)
    songzhuangu = pd.to_numeric(group["xdxr_songzhuangu"], errors="coerce").fillna(0.0)
    peigu = pd.to_numeric(group["xdxr_peigu"], errors="coerce").fillna(0.0)
    denominator = 1.0 + songzhuangu / 10.0 + peigu / 10.0
    adjusted = (raw_pre_close - fenhong / 10.0 + peigujia * peigu / 10.0) / denominator.replace(0, np.nan)
    use_adjusted = event_present & raw_pre_close.notna() & raw_pre_close.ne(0) & denominator.gt(0)
    return raw_pre_close.mask(use_adjusted, adjusted)

def compute_group_formula(group: pd.DataFrame) -> pd.DataFrame:
    # The reviewed implementation adds many derived columns.  Pandas emits a
    # PerformanceWarning for that intentional shape; keep it out of the public
    # authority protocol without changing any values.
    warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)
    group = group.copy()
    open_ = group["open"]
    high = group["high"]
    low = group["low"]
    close = group["close"]
    volume = group["volume"]
    pre_close = apply_xdxr_pre_close(group, close.shift(1))
    prev_volume = volume.shift(1)

    for n in [3, 5, 6, 10, 12, 14, 20, 24, 28, 30, 40, 57, 60, 114]:
        group[f"ma{n}"] = close.rolling(n, min_periods=1).mean()

    group["BBI"] = (group["ma3"] + group["ma6"] + group["ma12"] + group["ma24"]) / 4.0
    ema10 = ema_by_group(close, 10)
    group["zge_white_line"] = ema_by_group(ema10, 10)
    group["zge_yellow_line"] = (group["ma14"] + group["ma28"] + group["ma57"] + group["ma114"]) / 4.0

    bar_range = (high - low).replace(0, np.nan)
    group["bar_close_pos"] = (close - low) / bar_range
    group["amplitude_pct"] = (high - low) / pre_close * 100.0
    group["upper_shadow_pct"] = (high - np.maximum(open_, close)) / pre_close * 100.0
    group["lower_shadow_pct"] = (np.minimum(open_, close) - low) / pre_close * 100.0
    group["pre_close"] = pre_close
    group["pct_chg"] = (close / pre_close - 1.0) * 100.0

    group["vol_ratio_60"] = volume / volume.rolling(60, min_periods=1).mean().replace(0, np.nan)
    group["amount_ratio_20"] = group["amount"] / group["amount"].rolling(20, min_periods=1).mean().replace(0, np.nan)
    group["high_20"] = high.rolling(20, min_periods=1).max()
    group["high_20_prev"] = group["high_20"].shift(1)

    low9 = low.rolling(9, min_periods=1).min()
    high9 = high.rolling(9, min_periods=1).max()
    rsv = ((close - low9) / (high9 - low9).replace(0, np.nan) * 100.0).fillna(50.0)
    group["kdj_k"] = rec_sma(rsv)
    group["kdj_d"] = rec_sma(group["kdj_k"])
    group["J"] = 3.0 * group["kdj_k"] - 2.0 * group["kdj_d"]

    delta = close.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    group["zge_rsi3"] = up.rolling(3, min_periods=1).mean() / (
        up.rolling(3, min_periods=1).mean() + down.rolling(3, min_periods=1).mean()
    ).replace(0, np.nan) * 100.0

    macd_dif = ema_by_group(close, 12) - ema_by_group(close, 26)
    group["macd_dif"] = macd_dif
    group["macd_dea"] = ema_by_group(macd_dif, 9)
    group["macd_hist"] = (group["macd_dif"] - group["macd_dea"]) * 2.0

    group["up_gap"] = bool_int(low > high.shift(1))
    group["lowest_key_price"] = np.where(group["up_gap"].eq(1), high.shift(1), np.minimum(low, pre_close))
    group["hold_yesterday_keyline"] = bool_int(close >= group["lowest_key_price"].shift(1))
    group["break_yesterday_keyline"] = bool_int(close < group["lowest_key_price"].shift(1))

    group["close_higher_than_prev"] = bool_int(close > pre_close)
    group["close_lower_than_prev"] = bool_int(close < pre_close)
    group["yang_line"] = bool_int(close > open_)
    group["yin_line"] = bool_int(close < open_)
    group["volume_up"] = bool_int(volume > prev_volume)
    group["strong_volume_up"] = bool_int(volume >= prev_volume * 1.75)
    true_yin = (close < pre_close) & (volume > prev_volume * 1.1)
    group["true_yin"] = bool_int(true_yin)
    group["ref_score_close_up"] = bool_int(close > pre_close)
    group["ref_score_above_bbi"] = bool_int(close >= group["BBI"])
    group["ref_score_no_giant_true_yin"] = bool_int(~true_yin)
    group["ref_score_trend_up"] = bool_int(close > group["ma20"])
    group["j_dead_cross"] = bool_int((group["kdj_d"] > group["J"]) & (group["kdj_d"].shift(1) <= group["J"].shift(1)))
    group["ref_score_j_no_dead_cross"] = bool_int(group["j_dead_cross"].eq(0))
    group["ref_hold_score"] = (
        group["ref_score_close_up"] + group["ref_score_above_bbi"] + group["ref_score_no_giant_true_yin"] +
        group["ref_score_trend_up"] + group["ref_score_j_no_dead_cross"]
    ).astype(np.int8)

    yv = close.gt(open_) & volume.gt(prev_volume)
    yn = close.lt(open_) & volume.gt(prev_volume)
    al = yv | yn
    group["fd_volume_yin"] = bool_int(close.lt(pre_close) & volume.gt(prev_volume))
    group["jyzy_fake_yang"] = bool_int(close.gt(open_) & close.lt(pre_close))
    group["jyzy2_yin_strong"] = bool_int(close.lt(open_) & close.gt(pre_close) & volume.gt(prev_volume))
    plry = volume.gt(volume.rolling(40, min_periods=1).mean()) & volume.gt(prev_volume * 1.8) & close.gt(open_)
    group["plry_volume_burst"] = bool_int(plry)
    plry_prev = plry.shift(1, fill_value=False)
    group["plry_first"] = bool_int(plry & ~plry_prev)
    group["plry_cont"] = bool_int(plry & plry_prev)

    yn_i = yn.astype(int)
    al_i = al.astype(int)
    c_values = {}
    for n, max_yin in [(10, 3), (9, 3), (8, 2), (7, 2), (6, 2), (5, 1), (4, 1), (3, 1)]:
        c = (np.arange(len(group)) + 1 > n) & (rolling_count_prev(al_i, n).eq(n)) & (rolling_count_prev(yn_i, n).le(max_yin))
        c_values[n] = c.fillna(False)
        group[f"c{n}_continuous_volume_price"] = bool_int(c_values[n])
    bl = np.zeros(len(group), dtype="int64")
    for n in [10, 9, 8, 7, 6, 5, 4, 3]:
        bl = np.where((bl == 0) & c_values[n].to_numpy(dtype=bool), n, bl)
    group["bl_volume_price_length"] = bl

    to = ref_by_offset(open_.to_numpy(dtype="float64"), bl, open_.to_numpy(dtype="float64"))
    ol = open_.rolling(56, min_periods=1).min()
    oh = open_.rolling(56, min_periods=1).max()
    op = to <= (ol + (oh - ol) * 0.25).to_numpy(dtype="float64")
    ref_j_by_bl = ref_by_offset(group["J"].to_numpy(dtype="float64"), bl, group["J"].shift(1).to_numpy(dtype="float64"))
    jok = ref_j_by_bl <= 55
    dt1 = (pre_close <= close.shift(2) * 0.901) & (pre_close == low.shift(1))
    ty = close.gt(pre_close) & close.gt(open_)
    vr = volume.ge(prev_volume * 1.75)
    group["BG"] = bool_int(ty & vr & ~dt1.fillna(False) & jok & op)

    j_lt_13_3 = group["J"].lt(13).rolling(3, min_periods=1).max().astype(bool)
    vol_ref_ma4 = volume.shift(1).rolling(4, min_periods=1).mean()
    group["B1"] = bool_int(group["BBI"].gt(group["zge_white_line"]) & group["zge_white_line"].gt(group["zge_yellow_line"]) & group["J"].le(13))
    group["B2"] = bool_int(j_lt_13_3 & volume.gt(vol_ref_ma4 * 1.25) & group["pct_chg"].gt(4) & group["J"].lt(70) & group["zge_white_line"].gt(group["zge_yellow_line"]))
    vol_ratio = volume / prev_volume.replace(0, np.nan)
    non_three_quarter = vol_ratio.lt(0.6) | vol_ratio.gt(0.9)
    true_break = group["pct_chg"].gt(0) | (group["pct_chg"].gt(-3) & non_three_quarter)
    yest_volume_up = volume.shift(1).gt(volume.shift(2).rolling(4, min_periods=1).mean() * 1.15)
    group["B3"] = bool_int(group["J"].shift(2).lt(20) & yest_volume_up & group["pct_chg"].shift(1).gt(3) & group["zge_white_line"].gt(group["zge_yellow_line"]) & true_break)
    route_context = pd.Series("", index=group.index, dtype="object")
    route_context = route_context.mask(group["B1"].eq(1), route_context + "B1|")
    route_context = route_context.mask(group["B2"].eq(1), route_context + "B2|")
    route_context = route_context.mask(group["B3"].eq(1), route_context + "B3|")
    group["route_context"] = route_context.str.rstrip("|")

    group["break_prev_high"] = bool_int(close.gt(group["high_20_prev"]) & volume.gt(prev_volume * 0.8) & group["pct_chg"].gt(4))
    group["breakout"] = bool_int(group["break_prev_high"].eq(1) & group["break_prev_high"].rolling(8, min_periods=1).sum().eq(1))
    group["double_breakout"] = bool_int(group["breakout"].rolling(20, min_periods=1).sum().ge(2) & group["breakout"].eq(1) & (group["zge_white_line"].gt(group["zge_yellow_line"])))
    y_break_prev_high = close.shift(1).ge(group["high_20"].shift(2)) & yest_volume_up & group["pct_chg"].shift(1).gt(4)
    group["breakout_cross_star"] = bool_int(y_break_prev_high.rolling(8, min_periods=1).sum().eq(1) & y_break_prev_high & group["pct_chg"].lt(4) & true_break)
    three_quarter = vol_ratio.le(0.9) & vol_ratio.ge(0.6) & yest_volume_up & group["pct_chg"].shift(1).gt(4)
    group["three_quarter_volume"] = bool_int(three_quarter)
    group["three_quarter_yin_volume_line"] = bool_int(y_break_prev_high.rolling(8, min_periods=1).sum().eq(1) & y_break_prev_high & group["pct_chg"].lt(0) & three_quarter)
    short3 = 100 * (close - low.rolling(3, min_periods=1).min()) / (close.rolling(3, min_periods=1).max() - low.rolling(3, min_periods=1).min()).replace(0, np.nan)
    long21 = 100 * (close - low.rolling(21, min_periods=1).min()) / (close.rolling(21, min_periods=1).max() - low.rolling(21, min_periods=1).min()).replace(0, np.nan)
    group["single_needle_under20"] = bool_int(long21.ge(75) & short3.le(25))
    group["didi_break_prev_low"] = bool_int(close / np.minimum(close.shift(2), low.shift(1)).replace(0, np.nan) < 0.99)
    group["under_yellow_not_break"] = bool_int(group["J"].lt(13).rolling(10, min_periods=1).max().astype(bool) & close.shift(2).gt(group["zge_yellow_line"]) & close.shift(1).lt(group["zge_yellow_line"]) & close.lt(group["zge_yellow_line"]) & group["zge_white_line"].gt(group["zge_yellow_line"]))
    cost_price = ref_by_offset(close.to_numpy(dtype="float64"), barslast_bool(group["J"].lt(13)).fillna(0).to_numpy(dtype="int64"), close.to_numpy(dtype="float64"))
    bars_b1 = barslast_bool(group["B1"].eq(1))
    group["first_fly"] = bool_int(bars_b1.le(20) & (high / cost_price - 1).gt(0.15) & (high.shift(1) / cost_price - 1).lt(0.15))
    group["second_fly"] = bool_int(bars_b1.le(25) & (high / cost_price - 1).gt(0.25) & (high.shift(1) / cost_price - 1).lt(0.25))
    group["white_yellow_death_cross"] = bool_int(group["zge_white_line"].lt(group["zge_yellow_line"]) & group["zge_white_line"].shift(1).gt(group["zge_yellow_line"].shift(1)))

    code_text = group["ts_code"].astype(str).str.split(".").str[0].fillna("")
    market_relaxed = (
        code_text.str.startswith(("68", "30", "4", "8", "9")) |
        rolling_exist(close / pre_close.replace(0, np.nan) > 1.15, 200)
    )

    high4 = high.rolling(4, min_periods=1).max()
    low4 = low.rolling(4, min_periods=1).min()
    group["brick_var1a"] = safe_div(high4 - close, high4 - low4) * 100.0 - 90.0
    group["brick_var2a"] = tdx_sma(group["brick_var1a"], 4, 1) + 100.0
    group["brick_var3a"] = safe_div(close - low4, high4 - low4) * 100.0
    group["brick_var4a"] = tdx_sma(group["brick_var3a"], 6, 1)
    group["brick_var5a"] = tdx_sma(group["brick_var4a"], 6, 1) + 100.0
    group["brick_var6a"] = group["brick_var5a"] - group["brick_var2a"]
    group["brick_type_value"] = np.where(group["brick_var6a"].gt(4), group["brick_var6a"] - 4.0, 0.0)

    group["brick_short"] = (safe_div(close - low.rolling(3, min_periods=1).min(), close.rolling(3, min_periods=1).max() - low.rolling(3, min_periods=1).min()) * 100.0).fillna(0.0)
    group["brick_long"] = (safe_div(close - low.rolling(21, min_periods=1).min(), close.rolling(21, min_periods=1).max() - low.rolling(21, min_periods=1).min()) * 100.0).fillna(0.0)

    group["brick_special_board"] = bool_int(market_relaxed)
    group["brick_amp_range"] = np.where(market_relaxed, 8.0, 5.0)
    brick_relax = np.where(market_relaxed, 0.9, 1.0)
    group["brick_day_amplitude"] = safe_div(high - low, low) * 100.0
    group["brick_abs_pct_relaxed"] = (close.sub(pre_close).abs() / pre_close.replace(0, np.nan) * 100.0 * brick_relax)
    group["brick_rising_cross_star"] = bool_int(close.gt(pre_close) & ((close - open_).abs() / open_.replace(0, np.nan) * 100.0 * brick_relax).lt(1.8))

    group["brick_single_needle_under20"] = bool_int(group["brick_short"].le(20) & group["brick_long"].ge(75) | (group["brick_long"] - group["brick_short"]).ge(70))
    group["brick_treasure_bowl"] = bool_int(rolling_count(group["brick_long"].ge(75), 8).ge(6) & rolling_count(group["brick_short"].le(70), 7).ge(4) & rolling_count(group["brick_short"].le(50), 8).ge(1))
    group["brick_double_fork"] = bool_int(rolling_every(group["brick_long"].ge(75), 8) & rolling_count(group["brick_short"].le(50), 6).ge(2) & rolling_count(group["brick_short"].le(20), 7).ge(1))
    group["brick_red_fat_green_thin"] = bool_int(rolling_count(close.ge(open_), 15).gt(7) | rolling_count(close.gt(pre_close), 11).gt(5))

    group["brick_vday"] = hhvbars(volume, 40)
    brick_vday_close = ref_series_by_offsets(close, group["brick_vday"])
    brick_vday_prev_close = ref_series_by_offsets(close, group["brick_vday"] + 1)
    brick_vday_open = ref_series_by_offsets(open_, group["brick_vday"])
    brick_not_big_green = brick_vday_close.ge(brick_vday_prev_close) | brick_vday_close.ge(brick_vday_open)
    brick_big_green = ~brick_not_big_green.fillna(False)
    brick_big_green_far = group["brick_vday"].ge(15) & brick_big_green

    group["brick_shrink"] = bool_int(volume.lt(volume.rolling(20, min_periods=1).max() * 0.416) | volume.lt(volume.rolling(50, min_periods=1).max() / 3.0))
    group["brick_pullback_shrink"] = bool_int(volume.lt(volume.rolling(20, min_periods=1).max() * 0.45) | volume.lt(volume.rolling(50, min_periods=1).max() / 3.0))
    group["brick_fit_shrink"] = bool_int(volume.lt(volume.rolling(20, min_periods=1).max() * 0.618) | volume.lt(volume.rolling(50, min_periods=1).max() / 3.0))
    group["brick_super_shrink"] = bool_int(volume.lt(volume.rolling(30, min_periods=1).max() / 4.0) | volume.lt(volume.rolling(50, min_periods=1).max() / 6.0))

    brick_temp1 = (close - pre_close).clip(lower=0)
    brick_temp2 = (close - pre_close).abs()
    group["brick_rsi3"] = safe_div(tdx_sma(brick_temp1, 3, 1), tdx_sma(brick_temp2, 3, 1)) * 100.0

    brick_low20 = low.rolling(20, min_periods=1).min()
    brick_high20 = high.rolling(20, min_periods=1).max()
    group["brick_recent_amp"] = safe_div(brick_high20 - brick_low20, brick_low20) * 100.0
    group["brick_recent_active"] = bool_int(group["brick_recent_amp"].ge(15) | safe_div(high.rolling(12, min_periods=1).max() - low.rolling(14, min_periods=1).min(), low.rolling(14, min_periods=1).min()).mul(100.0).ge(11))
    brick_low50 = low.rolling(50, min_periods=1).min()
    brick_high50 = high.rolling(50, min_periods=1).max()
    group["brick_far_amp"] = safe_div(brick_high50 - brick_low50, brick_low50) * 100.0
    group["brick_far_active"] = bool_int(group["brick_far_amp"].ge(30))
    group["brick_super_active"] = bool_int(group["brick_recent_amp"].ge(60))
    group["brick_wash_active"] = bool_int(rolling_count(group["brick_single_needle_under20"].eq(1), 10).ge(2) | group["brick_treasure_bowl"].eq(1) | group["brick_double_fork"].eq(1))

    group["brick_uptrend"] = bool_int(group["zge_white_line"].ge(group["zge_yellow_line"] * 0.999) & (close.ge(group["zge_yellow_line"]) | (close.gt(group["zge_yellow_line"] * 0.975) & close.gt(open_))))
    group["brick_strong_trend"] = bool_int(rolling_every(group["zge_yellow_line"].ge(group["zge_yellow_line"].shift(1) * 0.999), 13) & group["zge_white_line"].ge(group["zge_white_line"].shift(1)) & rolling_every(group["zge_white_line"].gt(group["zge_yellow_line"]), 20) & rolling_every(group["zge_white_line"].ge(group["zge_white_line"].shift(1)), 11) & group["brick_red_fat_green_thin"].eq(1))
    cross_close_yellow = cross_over(close, group["zge_yellow_line"])
    group["brick_super_bull"] = bool_int((rolling_every(group["BBI"].ge(group["BBI"].shift(1) * 0.999), 20) | rolling_count(group["BBI"].ge(group["BBI"].shift(1)), 25).ge(23)) & (group["brick_recent_amp"].ge(30) | group["brick_far_amp"].gt(80)) & barslast_bool(cross_close_yellow).fillna(np.inf).gt(12))

    group["brick_dist_white"] = safe_div((close - group["zge_white_line"]).abs(), close) * 100.0
    group["brick_l_dist_white"] = safe_div((low - group["zge_white_line"]).abs(), group["zge_white_line"]) * 100.0
    group["brick_dist_bbi"] = safe_div((close - group["BBI"]).abs(), close) * 100.0
    group["brick_l_dist_bbi"] = safe_div((low - group["BBI"]).abs(), group["BBI"]) * 100.0
    brick_pullback_white_line = (
        (close.ge(group["zge_white_line"]) & group["brick_dist_white"].le(2)) |
        (close.lt(group["zge_white_line"]) & group["brick_dist_white"].lt(0.8)) |
        (close.ge(group["BBI"]) & group["brick_dist_bbi"].lt(2.5) & group["brick_l_dist_bbi"].lt(1) & group["brick_dist_white"].le(3) & group["brick_abs_pct_relaxed"].lt(1) & close.gt(pre_close))
    )
    brick_white_support = close.ge(group["zge_white_line"]) & group["brick_dist_white"].lt(1.5)
    brick_strong_pullback_hold = (group["brick_l_dist_white"].lt(1) | group["brick_l_dist_bbi"].lt(0.5)) & close.gt(group["zge_white_line"]) & group["brick_dist_white"].le(3.5)

    group["brick_dist_yellow"] = safe_div((close - group["zge_yellow_line"]).abs(), group["zge_yellow_line"]) * 100.0
    brick_pullback_yellow_line = (
        (close.ge(group["zge_yellow_line"]) & (group["brick_dist_yellow"].le(1.5) | (group["brick_dist_yellow"].le(2) & group["brick_abs_pct_relaxed"].lt(1)))) |
        (close.lt(group["zge_yellow_line"]) & group["brick_dist_yellow"].le(0.8))
    )
    brick_good_green = brick_not_big_green | brick_big_green_far
    brick_active_any = group["brick_recent_active"].eq(1) | group["brick_far_active"].eq(1) | group["brick_wash_active"].eq(1)
    brick_small_body = ((close - open_).abs() * 100.0 / open_.replace(0, np.nan)).lt(1.5)

    group["brick_oversold_shrink_turn_b"] = bool_int(group["brick_uptrend"].eq(1) & (group["brick_rsi3"] - 15).ge(group["brick_rsi3"].shift(1)) & (group["brick_rsi3"].shift(1).lt(20) | group["J"].shift(1).lt(14)) & group["brick_day_amplitude"].lt(group["brick_amp_range"] + 0.5) & (group["brick_abs_pct_relaxed"].lt(2.3) | (group["brick_rising_cross_star"].eq(1) & group["brick_abs_pct_relaxed"].lt(4))) & brick_good_green & brick_active_any & close.ge(group["zge_yellow_line"]))
    group["brick_oversold_shrink_b"] = bool_int(group["brick_uptrend"].eq(1) & (group["J"].lt(14) | group["brick_rsi3"].lt(23)) & ((group["brick_rsi3"] + group["J"]).lt(55) | group["J"].eq(group["J"].rolling(20, min_periods=1).min())) & group["brick_day_amplitude"].lt(group["brick_amp_range"]) & (group["brick_abs_pct_relaxed"].lt(2.5) | group["brick_rising_cross_star"].eq(1)) & brick_good_green & (group["brick_shrink"].eq(1) | (group["brick_fit_shrink"].eq(1) & group["brick_abs_pct_relaxed"].lt(1))) & brick_active_any)
    group["brick_original_b1"] = bool_int(group["zge_white_line"].gt(group["zge_yellow_line"]) & close.ge(group["zge_yellow_line"] * 0.99) & group["zge_yellow_line"].ge(group["zge_yellow_line"].shift(1)) & (group["J"].lt(13) | group["brick_rsi3"].lt(21)) & (group["brick_rsi3"] + group["J"]).lt((group["brick_rsi3"] + group["J"]).rolling(15, min_periods=1).min() * 1.5) & group["brick_fit_shrink"].eq(1) & brick_good_green & (brick_small_body | group["brick_super_shrink"].eq(1) | (group["brick_fit_shrink"].eq(1) & volume.lt(volume.rolling(20, min_periods=1).min() * 1.1) & group["J"].eq(group["J"].rolling(20, min_periods=1).min())) | (group["brick_fit_shrink"].eq(1) & (group["brick_dist_white"].lt(1.8) | group["brick_dist_bbi"].lt(1.5) | group["brick_dist_yellow"].lt(2.8)))) & brick_active_any)
    group["brick_oversold_super_shrink_b"] = bool_int(group["brick_uptrend"].eq(1) & (group["J"].lt(14) | group["brick_rsi3"].lt(23)) & (group["brick_rsi3"] + group["J"]).lt(60) & group["brick_far_amp"].ge(45) & (group["brick_day_amplitude"].lt(group["brick_amp_range"]) | (group["brick_super_active"].eq(1) & group["brick_day_amplitude"].lt(group["brick_amp_range"] + 3.2) & close.gt(open_) & close.gt(group["zge_white_line"]))) & (((close.lt(open_) & volume.lt(prev_volume) & close.ge(group["zge_yellow_line"])) | close.ge(open_))) & (group["brick_abs_pct_relaxed"].lt(2) | group["brick_rising_cross_star"].eq(1)) & brick_good_green & group["brick_super_shrink"].eq(1) & brick_active_any)
    group["brick_pullback_white_b"] = bool_int(group["brick_strong_trend"].eq(1) & (group["J"].lt(30) | group["brick_rsi3"].lt(40) | group["brick_wash_active"].eq(1)) & (group["brick_rsi3"] + group["J"]).lt(70) & (group["brick_day_amplitude"].lt(group["brick_amp_range"] + 0.5) | group["brick_dist_white"].lt(1) | group["brick_dist_bbi"].lt(1)) & brick_pullback_white_line & (group["brick_abs_pct_relaxed"].lt(2) | (group["brick_abs_pct_relaxed"].lt(5) & brick_white_support)) & brick_good_green & group["brick_pullback_shrink"].eq(1) & brick_active_any & low.le(pre_close))
    group["brick_pullback_super_b"] = bool_int(group["brick_super_bull"].eq(1) & (group["J"].lt(35) | group["brick_rsi3"].lt(45) | group["brick_wash_active"].eq(1)) & (group["brick_rsi3"] + group["J"]).lt(80) & (group["brick_rsi3"] + group["J"]).eq((group["brick_rsi3"] + group["J"]).rolling(25, min_periods=1).min()) & group["brick_day_amplitude"].lt(group["brick_amp_range"] + 1) & (group["brick_abs_pct_relaxed"].lt(2.5) | group["brick_dist_white"].lt(2)) & brick_strong_pullback_hold & brick_good_green & brick_active_any & group["brick_fit_shrink"].eq(1))
    group["brick_pullback_yellow_b"] = bool_int(group["zge_white_line"].ge(group["zge_yellow_line"]) & close.ge(group["zge_yellow_line"] * 0.975) & (group["J"].lt(13) | group["brick_rsi3"].lt(18)) & brick_pullback_yellow_line & brick_good_green & (group["brick_shrink"].eq(1) | (group["brick_fit_shrink"].eq(1) & (group["J"].eq(group["J"].rolling(20, min_periods=1).min()) | group["brick_rsi3"].eq(group["brick_rsi3"].rolling(14, min_periods=1).min())))) & group["zge_yellow_line"].ge(group["zge_yellow_line"].shift(1) * 0.997) & group["ma60"].ge(group["ma60"].shift(1)) & group["brick_recent_amp"].ge(11.9) & group["brick_far_amp"].ge(19.5))

    group["brick_exist_b"] = bool_int(
        group["brick_oversold_shrink_turn_b"].eq(1) |
        group["brick_oversold_shrink_b"].eq(1) |
        group["brick_original_b1"].eq(1) |
        group["brick_oversold_super_shrink_b"].eq(1) |
        group["brick_pullback_white_b"].eq(1) |
        group["brick_pullback_super_b"].eq(1) |
        group["brick_pullback_yellow_b"].eq(1)
    )

    brick_mom_j = group["J"] - group["J"].shift(1)
    brick_mom_r = group["brick_rsi3"] - group["brick_rsi3"].shift(1)
    brick_volume_coef = np.where(volume.lt(prev_volume * 0.99), (1 - 5 * (prev_volume - volume) / prev_volume.replace(0, np.nan)) * 0.8, 1.0)
    brick_multi_coef = np.where(prev_volume.gt(0), np.where(volume / prev_volume >= 4, 1.4, 0.1 * volume / prev_volume + 1.0), 1.0)
    brick_multi_bonus = np.where(close.gt(open_) & close.gt(pre_close) & volume.gt(prev_volume * 1.8), brick_multi_coef, 1.0)
    brick_shadow_base = np.maximum(high - np.minimum(open_, pre_close), 0.01)
    brick_shadow_coef = np.where(close.gt(pre_close) & close.gt(open_), (0.75 - (high - close) / brick_shadow_base) * 1.3, 1.0)
    group["brick_yellow_value"] = (brick_mom_j + brick_mom_r) / 2.0 * brick_shadow_coef * brick_multi_bonus
    group["brick_x_power"] = np.where(close.gt(open_) & close.gt(pre_close) & ((brick_mom_j + brick_mom_r).gt((brick_mom_j.shift(1) + brick_mom_r.shift(1)))), ((brick_mom_j + brick_mom_r) - (brick_mom_j.shift(1) + brick_mom_r.shift(1))) / 2.0 * brick_shadow_coef * brick_volume_coef * brick_multi_bonus, 0.0)
    group["brick_red_today"] = group["brick_type_value"].gt(group["brick_type_value"].shift(1))
    brick_green_today = ~group["brick_red_today"].fillna(False)
    brick_green_yesterday = brick_green_today.shift(1, fill_value=False)
    group["brick_red_length"] = np.where(group["brick_red_today"], group["brick_type_value"] - group["brick_type_value"].shift(1), 0.0)
    group["brick_length"] = group["brick_type_value"] - group["brick_type_value"].shift(1)
    brick_prev_green_length = np.where(brick_green_yesterday, group["brick_type_value"].shift(2) - group["brick_type_value"].shift(1), 0.0)
    brick_red_green_ratio = np.where(brick_prev_green_length > 0, group["brick_red_length"] / brick_prev_green_length, 0.0)
    group["brick_strong_red"] = bool_int(group["brick_red_today"] & brick_green_yesterday & pd.Series(brick_red_green_ratio, index=group.index).gt(0.666))
    brick_trend_condition = group["zge_white_line"].ge(group["zge_yellow_line"] * 0.995) & group["zge_yellow_line"].ge(group["zge_yellow_line"].shift(1) * 0.997) & close.ge(group["zge_yellow_line"] * 0.997)
    brick_upper_shadow_base = np.maximum(high - np.minimum(low, pre_close), 0.01)
    brick_upper_shadow_condition = (close.ge(open_) | close.gt(pre_close)) & (1 - (high - close) / brick_upper_shadow_base).gt(0.618)
    brick_turnover_condition = group["amount"].gt(0)
    group["brick_turnover_proxy"] = bool_int(brick_turnover_condition)
    group["brick_resonance1"] = bool_int(group["brick_strong_red"].eq(1) & ((group["brick_yellow_value"].ge(10)) | (group["brick_x_power"].ge(10))) & (rolling_exist(group["brick_exist_b"].eq(1), 2) | (group["brick_long"].shift(1).gt(85) & group["brick_short"].shift(1).lt(30))))
    group["brick_resonance2"] = bool_int(group["brick_strong_red"].eq(1) & ((group["brick_yellow_value"].ge(10)) | (group["brick_x_power"].ge(10))) & ((rolling_exist((group["brick_long"] - group["brick_short"]).gt(60), 4) & group["brick_long"].gt(98) & group["brick_short"].gt(98)) | (group["brick_yellow_value"].gt(20) & close.gt(group["zge_white_line"])) | group["brick_yellow_value"].gt(30) | (group["brick_yellow_value"] + group["brick_length"]).gt(50) | group["brick_x_power"].gt(40)))
    group["brick_resonance"] = bool_int(group["brick_resonance1"].eq(1) | group["brick_resonance2"].eq(1))
    group["brick_buy1_low_absorb"] = bool_int(group["brick_resonance1"].eq(1) & brick_upper_shadow_condition & brick_trend_condition & brick_turnover_condition)
    group["brick_buy2_attack"] = bool_int(group["brick_resonance2"].eq(1) & brick_upper_shadow_condition & brick_trend_condition & brick_turnover_condition)
    group["brick_buy"] = bool_int(group["brick_resonance"].eq(1) & brick_upper_shadow_condition & brick_trend_condition & brick_turnover_condition)
    group["gold_brick_context"] = np.where(group["brick_exist_b"].eq(1), "old_gold_candidate", "none")
    group["brick_resonance_context"] = bool_int(group["brick_resonance"].eq(1) | group["brick_buy"].eq(1))
    group["brick_context"] = "none"
    group.loc[group["brick_exist_b"].eq(1), "brick_context"] = "candidate"
    group.loc[group["brick_resonance"].eq(1), "brick_context"] = "resonance"
    group.loc[group["brick_buy"].eq(1), "brick_context"] = "buy"
    group.loc[group["brick_buy1_low_absorb"].eq(1), "brick_context"] = "buy_low_absorb"
    group.loc[group["brick_buy2_attack"].eq(1), "brick_context"] = "buy_attack"
    group.loc[group["brick_buy1_low_absorb"].eq(1) & group["brick_buy2_attack"].eq(1), "brick_context"] = "buy_low_absorb|buy_attack"

    group["macd_below_zero_second_gold"] = bool_int((group["macd_dif"] > group["macd_dea"]) & group["macd_dea"].lt(0) & group["macd_dif"].shift(1).le(group["macd_dea"].shift(1)))
    group["macd_above_zero_second_gold"] = bool_int((group["macd_dif"] > group["macd_dea"]) & group["macd_dea"].gt(0) & group["macd_dif"].shift(1).le(group["macd_dea"].shift(1)))
    group["macd_top_divergence"] = bool_int((high.rolling(21, min_periods=1).max().eq(high)) & high.gt(high.rolling(21, min_periods=1).max().shift(1)) & group["macd_hist"].lt(group["macd_hist"].rolling(21, min_periods=1).max().shift(1)) & group["macd_hist"].gt(0))
    group["macd_bottom_divergence"] = bool_int((low.rolling(21, min_periods=1).min().eq(low)) & low.lt(low.rolling(21, min_periods=1).min().shift(1)) & group["macd_hist"].gt(group["macd_hist"].rolling(21, min_periods=1).min().shift(1)) & group["macd_hist"].lt(0))

    return group

def compute_partition_formula(partition: pd.DataFrame) -> pd.DataFrame:
    computed_parts = []
    for _, part in partition.groupby("ts_code", sort=False):
        computed_parts.append(compute_group_formula(part))
    return pd.concat(computed_parts, ignore_index=True) if computed_parts else pd.DataFrame()
