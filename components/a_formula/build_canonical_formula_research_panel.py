# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA_ROOT = Path(r"C:\Users\huang\Desktop\学习\数据")
POINTER = DATA_ROOT / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"
OUT_ROOT = DATA_ROOT / "selector_ready_panels" / "research_panel_formula_canonical_20260515"
RUN_ROOT = DATA_ROOT / "debug_scripts" / "research_panel_formula_canonical_20260515"
TDX_ROOT = Path(r"C:\new_tdx_mock")
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
RUN_DIR = RUN_ROOT / f"run_{RUN_TS}"


def read_pointer() -> Path:
    raw = POINTER.read_text(encoding="utf-8-sig").strip().lstrip("\ufeff")
    path = Path(raw)
    if path.exists():
        return path
    repaired = raw.replace("瀛︿範", "学习").replace("鏁版嵁", "数据")
    repaired_path = Path(repaired)
    if repaired_path.exists():
        return repaired_path
    raise FileNotFoundError(raw)


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


def load_tdx_xdxr_events(tdx_root: Path = TDX_ROOT) -> pd.DataFrame:
    path = tdx_root / "T0002" / "hq_cache" / "gbbq"
    if not path.exists():
        return empty_xdxr_events()
    try:
        from pytdx.reader import GbbqReader
    except Exception:
        return empty_xdxr_events()
    try:
        raw = GbbqReader().get_df(str(path))
    except Exception:
        return empty_xdxr_events()
    if raw is None or raw.empty or "category" not in raw.columns:
        return empty_xdxr_events()
    raw = raw[pd.to_numeric(raw["category"], errors="coerce").eq(1)].copy()
    if raw.empty:
        return empty_xdxr_events()
    raw["ts_code"] = [ts_code_from_gbbq(market, code) for market, code in zip(raw["market"], raw["code"])]
    raw["_xdxr_trade_date"] = pd.to_numeric(raw["datetime"], errors="coerce").astype("Int64")
    raw = raw.rename(
        columns={
            "hongli_panqianliutong": "xdxr_fenhong",
            "peigujia_qianzongguben": "xdxr_peigujia",
            "songgu_qianzongguben": "xdxr_songzhuangu",
            "peigu_houzongguben": "xdxr_peigu",
        }
    )
    out = raw[["ts_code", "_xdxr_trade_date", "xdxr_fenhong", "xdxr_peigujia", "xdxr_songzhuangu", "xdxr_peigu"]].copy()
    for col in ["xdxr_fenhong", "xdxr_peigujia", "xdxr_songzhuangu", "xdxr_peigu"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    return out.dropna(subset=["ts_code", "_xdxr_trade_date"]).drop_duplicates(["ts_code", "_xdxr_trade_date"], keep="last")


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


def build_canonical(panel_path: Path) -> pd.DataFrame:
    pf = pq.ParquetFile(panel_path)
    cols = set(pf.schema_arrow.names)
    base_cols = [
        "trade_date", "ts_code", "raw_code", "exchange", "market_type", "name",
        "open", "high", "low", "close", "volume", "amount",
    ]
    read_cols = [c for c in base_cols if c in cols]
    if "volume" not in read_cols and "vol" in cols:
        read_cols.append("vol")
    df = pd.read_parquet(panel_path, columns=read_cols)
    if "volume" not in df.columns and "vol" in df.columns:
        df["volume"] = df["vol"]
    df = df.drop(columns=[c for c in ["vol"] if c in df.columns])
    df["_row_id"] = np.arange(len(df), dtype=np.int64)
    df["_sort_date"] = pd.to_numeric(df["trade_date"], errors="coerce").astype("Int64")
    xdxr_events = load_tdx_xdxr_events()
    if not xdxr_events.empty:
        df = df.merge(
            xdxr_events,
            how="left",
            left_on=["ts_code", "_sort_date"],
            right_on=["ts_code", "_xdxr_trade_date"],
        )
        df = df.drop(columns=["_xdxr_trade_date"])
        print(f"loaded xdxr events: rows={len(xdxr_events)}", flush=True)
    else:
        print("warning: no tdx xdxr events loaded; pct_chg uses raw previous close", flush=True)
    df = df.sort_values(["ts_code", "_sort_date", "_row_id"]).reset_index(drop=True)
    unique_codes = df["ts_code"].dropna().drop_duplicates().tolist()
    worker_count = max(1, min(6, os.cpu_count() or 1, len(unique_codes)))
    code_chunks = [chunk.tolist() for chunk in np.array_split(np.array(unique_codes, dtype=object), worker_count) if len(chunk)]
    partitions = [df[df["ts_code"].isin(codes)].copy() for codes in code_chunks]
    computed_parts: list[pd.DataFrame] = []
    print(f"computing canonical formulas: rows={len(df)} codes={len(unique_codes)} workers={worker_count}", flush=True)
    if worker_count == 1:
        for i, partition in enumerate(partitions, start=1):
            computed_parts.append(compute_partition_formula(partition))
            print(f"partition {i}/{len(partitions)} done rows={len(partition)}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {executor.submit(compute_partition_formula, partition): (i, len(partition)) for i, partition in enumerate(partitions, start=1)}
            for future in as_completed(futures):
                i, rows = futures[future]
                computed_parts.append(future.result())
                print(f"partition {i}/{len(partitions)} done rows={rows}", flush=True)
    computed = pd.concat(computed_parts, ignore_index=True)
    computed = computed.reset_index(drop=True).sort_values("_row_id").reset_index(drop=True)

    computed["primary_buy_signal"] = bool_int(
        computed["brick_buy2_attack"].eq(1) |
        computed["B3"].eq(1) |
        computed["double_breakout"].eq(1)
    )
    computed["secondary_buy_signal"] = bool_int(
        computed["brick_buy1_low_absorb"].eq(1) |
        computed["B2"].eq(1) |
        computed["breakout_cross_star"].eq(1)
    )
    computed["sell_signal"] = bool_int(
        computed["break_yesterday_keyline"].eq(1) |
        computed["white_yellow_death_cross"].eq(1) |
        computed["macd_top_divergence"].eq(1) |
        computed["didi_break_prev_low"].eq(1)
    )
    computed["formula_source"] = "computed_main_chart_formula_20260515"
    computed["field_contract_version"] = "formula_signal_v2_reference_score"

    brick_cols = [
        "brick_var1a", "brick_var2a", "brick_var3a", "brick_var4a", "brick_var5a", "brick_var6a",
        "brick_type_value", "brick_short", "brick_long", "brick_special_board", "brick_amp_range",
        "brick_day_amplitude", "brick_abs_pct_relaxed", "brick_rising_cross_star",
        "brick_single_needle_under20", "brick_treasure_bowl", "brick_double_fork",
        "brick_red_fat_green_thin", "brick_vday", "brick_shrink", "brick_pullback_shrink",
        "brick_fit_shrink", "brick_super_shrink", "brick_rsi3", "brick_recent_amp",
        "brick_recent_active", "brick_far_amp", "brick_far_active", "brick_super_active",
        "brick_wash_active", "brick_uptrend", "brick_strong_trend", "brick_super_bull",
        "brick_dist_white", "brick_l_dist_white", "brick_dist_bbi", "brick_l_dist_bbi",
        "brick_dist_yellow", "brick_oversold_shrink_turn_b", "brick_oversold_shrink_b",
        "brick_original_b1", "brick_oversold_super_shrink_b", "brick_pullback_white_b",
        "brick_pullback_super_b", "brick_pullback_yellow_b", "brick_exist_b",
        "brick_yellow_value", "brick_x_power", "brick_red_today", "brick_red_length",
        "brick_length", "brick_strong_red", "brick_turnover_proxy", "brick_resonance1",
        "brick_resonance2", "brick_resonance", "brick_buy1_low_absorb", "brick_buy2_attack",
        "brick_buy",
    ]

    final_cols = [
        "trade_date", "ts_code", "raw_code", "exchange", "market_type", "name",
        "open", "high", "low", "close", "volume", "amount", "pre_close", "pct_chg",
        "amplitude_pct", "bar_close_pos", "upper_shadow_pct", "lower_shadow_pct",
        "vol_ratio_60", "amount_ratio_20", "high_20", "high_20_prev",
        "ma3", "ma5", "ma6", "ma10", "ma12", "ma14", "ma20", "ma24", "ma28",
        "ma30", "ma40", "ma57", "ma60", "ma114", "BBI", "zge_white_line", "zge_yellow_line",
        "kdj_k", "kdj_d", "J", "zge_rsi3", "macd_dif", "macd_dea", "macd_hist",
        "up_gap", "lowest_key_price", "hold_yesterday_keyline", "break_yesterday_keyline",
        "ref_score_close_up", "ref_score_above_bbi", "true_yin", "ref_score_no_giant_true_yin",
        "ref_score_trend_up", "j_dead_cross", "ref_score_j_no_dead_cross", "ref_hold_score",
        "yang_line", "yin_line", "close_higher_than_prev", "close_lower_than_prev",
        "volume_up", "strong_volume_up", "fd_volume_yin", "jyzy_fake_yang", "jyzy2_yin_strong",
        "plry_volume_burst", "plry_first", "plry_cont",
        "c10_continuous_volume_price", "c9_continuous_volume_price", "c8_continuous_volume_price",
        "c7_continuous_volume_price", "c6_continuous_volume_price", "c5_continuous_volume_price",
        "c4_continuous_volume_price", "c3_continuous_volume_price", "bl_volume_price_length", "BG",
        "B1", "B2", "B3", "route_context",
        "gold_brick_context", "brick_context", "brick_resonance_context",
        *brick_cols,
        "break_prev_high", "breakout", "double_breakout", "breakout_cross_star",
        "three_quarter_volume", "three_quarter_yin_volume_line", "single_needle_under20",
        "didi_break_prev_low", "under_yellow_not_break", "first_fly", "second_fly", "white_yellow_death_cross",
        "macd_below_zero_second_gold", "macd_above_zero_second_gold", "macd_top_divergence", "macd_bottom_divergence",
        "primary_buy_signal", "secondary_buy_signal", "sell_signal", "formula_source", "field_contract_version",
    ]
    final_cols = [c for c in dict.fromkeys(final_cols) if c in computed.columns]
    return computed[final_cols]


def validate(path: Path) -> dict[str, Any]:
    pf = pq.ParquetFile(path)
    cols = list(pf.schema_arrow.names)
    keys = pd.read_parquet(path, columns=["ts_code", "trade_date"])
    latest = str(keys["trade_date"].astype(str).max())
    latest_rows = int(keys["trade_date"].astype(str).eq(latest).sum())
    duplicate_keys = int(keys.duplicated(["ts_code", "trade_date"]).sum())
    forbidden = [
        "vol", "bbi", "white_line", "yellow_line", "zge_j", "macd_bar", "MA60",
        "GOLD_BRICK", "JINZHU", "zsig_brick_exist_b", "B2_score", "B3_score",
        "zsig_B2_recalc", "zsig_B3_recalc", "b123_score", "hold_score_formula",
        "score_close_up", "score_above_bbi", "score_no_giant_true_yin",
        "score_trend_up", "score_j_no_dead_cross",
    ]
    present_forbidden = [c for c in forbidden if c in cols]
    must = [
        "ma30", "ma40", "ma60", "BBI", "zge_white_line", "zge_yellow_line", "J",
        "macd_dif", "macd_dea", "macd_hist", "ref_hold_score", "gold_brick_context",
        "brick_context", "brick_resonance_context", "brick_var1a", "brick_var2a",
        "brick_var3a", "brick_var4a", "brick_var5a", "brick_var6a", "brick_short",
        "brick_long", "brick_yellow_value", "brick_x_power", "brick_dist_white",
        "brick_dist_bbi", "brick_dist_yellow", "B1", "B2", "B3", "route_context",
        "primary_buy_signal", "secondary_buy_signal", "sell_signal", "bar_close_pos",
    ]
    data = pd.read_parquet(path, columns=["trade_date", *must])
    latest_df = data[data["trade_date"].astype(str).eq(latest)]
    latest_non_null = {c: int(latest_df[c].notna().sum()) for c in must}
    hard = []
    if duplicate_keys:
        hard.append(f"duplicate_keys:{duplicate_keys}")
    if present_forbidden:
        hard.append(f"forbidden_duplicate_columns_present:{present_forbidden}")
    for c in ["ma30", "ma40", "ma60", "BBI", "zge_white_line", "zge_yellow_line", "J", "macd_dif", "macd_dea", "macd_hist"]:
        if latest_non_null[c] != latest_rows:
            hard.append(f"latest_not_full_non_null:{c}:{latest_non_null[c]}/{latest_rows}")
    for c in ["brick_var1a", "brick_var2a", "brick_var3a", "brick_var4a", "brick_var5a", "brick_var6a", "brick_short", "brick_long", "brick_yellow_value", "brick_x_power", "brick_dist_white", "brick_dist_bbi", "brick_dist_yellow"]:
        numeric = pd.to_numeric(latest_df[c], errors="coerce").fillna(0)
        if int(numeric.ne(0).sum()) == 0:
            hard.append(f"latest_all_zero_formula_core:{c}")
    return {
        "path": str(path),
        "rows": int(pf.metadata.num_rows),
        "columns": len(cols),
        "column_names": cols,
        "latest_date": latest,
        "latest_rows": latest_rows,
        "duplicate_keys": duplicate_keys,
        "present_forbidden_duplicate_columns": present_forbidden,
        "latest_non_null": latest_non_null,
        "status": "PASS" if not hard else "FAIL",
        "hard_issues": hard,
    }


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    panel_path = read_pointer()
    latest = pd.read_parquet(panel_path, columns=["trade_date"])["trade_date"].astype(str).max()
    out_dir = OUT_ROOT / f"selector_ready_current_to_{latest}_canonical_{RUN_TS}"
    out_path = out_dir / f"selector_ready_current_to_{latest}.parquet"
    out_dir.mkdir(parents=True, exist_ok=True)

    before = {
        "path": str(panel_path),
        "rows": pq.ParquetFile(panel_path).metadata.num_rows,
        "columns": len(pq.ParquetFile(panel_path).schema_arrow.names),
    }
    canonical = build_canonical(panel_path)
    canonical.to_parquet(out_path, index=False, engine="pyarrow", compression="snappy")
    after = validate(out_path)
    sample = canonical[canonical["ts_code"].eq("300959.SZ")].sort_values("trade_date").tail(12)
    sample_path = RUN_DIR / "sample_300959_tail_canonical.csv"
    sample.to_csv(sample_path, index=False, encoding="utf-8-sig")
    report = {
        "run_ts": RUN_TS,
        "input": before,
        "output": after,
        "output_path": str(out_path),
        "sample_300959_tail_csv": str(sample_path),
        "removed_duplicate_or_forbidden_columns": [
            "vol", "bbi", "white_line", "yellow_line", "zge_j", "macd_bar", "MA60",
            "GOLD_BRICK", "JINZHU", "zsig_brick_exist_b", "B2_score", "B3_score",
            "zsig_B2_recalc", "zsig_B3_recalc", "b123_score",
        ],
    }
    (RUN_DIR / "canonical_build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    if after["status"] != "PASS":
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        raise SystemExit("canonical validation failed")
    shutil.copy2(POINTER, RUN_DIR / f"CURRENT_SELECTOR_READY_PANEL_before_{RUN_TS}.txt")
    POINTER.write_text(str(out_path), encoding="utf-8-sig")
    report["pointer_updated"] = True
    (RUN_DIR / "canonical_build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
