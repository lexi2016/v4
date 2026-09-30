"""Local V1.9.2 oracle closure for the V4 shared-data selector.

Only the functions actually called by the selector are present here. Their
calculation bodies are copied from the three frozen reference sources; runtime
code never imports or opens those source files. The origin map below binds the
semantic contract, while ``local_bundle_sha256`` separately identifies these
canonical bundle bytes.
"""
from __future__ import annotations

import datetime as _datetime
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ORACLE_CONTRACT_VERSION = "v1.9.2_FMLA04_TRACE_AWARE_WAIT_SPLIT"
ORACLE_ORIGIN_SHA256S: dict[str, str] = {
    "feature_vector": "1685327e016ce7a12ff7982379b91463c7c2bfb311e0b892385e692926970e74",
    "score_v19_multihead": "2a28049399043194b2f8523c8a2da7248708bf49e01f1d7e167fed933b92e4f2",
    "fmla04_role": "950b14447cb61049fb44efa46a10dfa6b3d5374188e212f8aff06fee1ab326c1",
}
ORIGIN_BUNDLE_SHA256 = "d356394cc163851e5b5b1fbd3c1f491bfc5a264a21bd589fc962764e814698e9"


def local_bundle_sha256() -> str:
    digest = hashlib.sha256()
    with Path(__file__).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def origin_bundle_sha256() -> str:
    raw = json.dumps(ORACLE_ORIGIN_SHA256S, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def required_local_symbols() -> tuple[str, ...]:
    return (
        "read_window",
        "vector_prepare_features",
        "score_v19",
        "score_multi_head",
        "entry_pool",
        "base_fmla04_role",
    )


REQUIRED_BASE_COLUMNS = [
    "trade_date",
    "ts_code",
    "name",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pre_close",
    "pct_chg",
    "amplitude_pct",
    "bar_close_pos",
    "upper_shadow_pct",
    "lower_shadow_pct",
    "amount_ratio_20",
    "high_20_prev",
    "BBI",
    "zge_white_line",
    "zge_yellow_line",
    "J",
    "zge_rsi3",
    "macd_dif",
    "macd_dea",
    "macd_hist",
    "ma20",
    "is_st_snapshot",
    "is_one_word_limit_up_est",
    "B1",
    "B2",
    "B3",
    "BG",
    "primary_buy_signal",
    "secondary_buy_signal",
    "brick_buy1_low_absorb",
    "brick_buy2_attack",
    "brick_buy",
    "brick_resonance_context",
    "gold_brick_context",
    "brick_original_b1",
    "brick_pullback_white_b",
    "brick_pullback_yellow_b",
    "brick_oversold_shrink_b",
    "brick_oversold_super_shrink_b",
    "brick_exist_b",
    "brick_strong_red",
    "brick_red_today",
    "breakout",
    "break_prev_high",
    "double_breakout",
    "fd_volume_yin",
    "break_yesterday_keyline",
    "white_yellow_death_cross",
    "macd_above_zero_second_gold",
    "macd_top_divergence",
    "ref_score_close_up",
    "ref_score_above_bbi",
    "ref_score_no_giant_true_yin",
    "ref_score_trend_up",
    "ref_score_j_no_dead_cross",
    "plry_first",
]

BOOL_COLUMNS = [
    "is_st_snapshot",
    "is_one_word_limit_up_est",
    "B1",
    "B2",
    "B3",
    "BG",
    "primary_buy_signal",
    "secondary_buy_signal",
    "brick_buy1_low_absorb",
    "brick_buy2_attack",
    "brick_buy",
    "brick_resonance_context",
    "gold_brick_context",
    "brick_original_b1",
    "brick_pullback_white_b",
    "brick_pullback_yellow_b",
    "brick_oversold_shrink_b",
    "brick_oversold_super_shrink_b",
    "brick_exist_b",
    "brick_strong_red",
    "brick_red_today",
    "breakout",
    "break_prev_high",
    "double_breakout",
    "fd_volume_yin",
    "break_yesterday_keyline",
    "white_yellow_death_cross",
    "macd_above_zero_second_gold",
    "macd_top_divergence",
    "ref_score_close_up",
    "ref_score_above_bbi",
    "ref_score_no_giant_true_yin",
    "ref_score_trend_up",
    "ref_score_j_no_dead_cross",
    "plry_first",
]

def feature_truthy(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).ne(0)
    return series.fillna("").astype(str).str.strip().str.lower().isin(
        {"1", "true", "t", "yes", "y"}
    )

def rolling(
    series: pd.Series,
    keys: pd.Series,
    window: int,
    min_periods: int,
    operation: str,
) -> pd.Series:
    grouped = series.groupby(keys, sort=False)
    result = getattr(grouped.rolling(window, min_periods=min_periods), operation)()
    return result.reset_index(level=0, drop=True).sort_index()

def vector_prepare_features(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw
    df["date8"] = pd.to_numeric(
        df["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8],
        errors="coerce",
    ).astype("Int64")
    df["stock_code"] = df["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    df["stock_name"] = df["name"].fillna("")
    for col in BOOL_COLUMNS:
        df[col] = feature_truthy(df[col]) if col in df else False
    numeric = [c for c in REQUIRED_BASE_COLUMNS if c not in BOOL_COLUMNS and c not in {"trade_date", "ts_code", "name"}]
    for col in numeric:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values(["stock_code", "date8"]).reset_index(drop=True)
    keys = df["stock_code"]
    gb = df.groupby(keys, sort=False)

    df["prev_close_calc"] = gb["close"].shift(1)
    df["pc_calc"] = df["pct_chg"].where(
        df["pct_chg"].notna(), (df["close"] / df["prev_close_calc"] - 1.0) * 100.0
    )
    df["vol_prev"] = gb["volume"].shift(1)
    df["volr"] = df["volume"] / df["vol_prev"]
    df["vma20"] = rolling(df["volume"], keys, 20, 5, "mean")
    df["vma20r"] = df["volume"] / df["vma20"]
    df["hhv_vol20"] = rolling(df["volume"], keys, 20, 5, "max")
    df["vsp20_hhv"] = df["volume"] / df["hhv_vol20"]
    close1 = gb["close"].shift(1)
    close21 = gb["close"].shift(21)
    df["ret_pre20"] = (close1 / close21 - 1.0) * 100.0
    low1 = gb["low"].shift(1)
    high1 = gb["high"].shift(1)
    df["low20_prev"] = rolling(low1, keys, 20, 5, "min")
    df["low60_prev"] = rolling(low1, keys, 60, 20, "min")
    df["high60_prev"] = rolling(high1, keys, 60, 20, "max")
    df["low120_prev"] = rolling(low1, keys, 120, 40, "min")
    df["high120_prev"] = rolling(high1, keys, 120, 40, "max")
    df["low20_to_close"] = (df["close"] / df["low20_prev"] - 1.0) * 100.0
    df["gain_from_low60_pct"] = (df["close"] / df["low60_prev"] - 1.0) * 100.0
    df["range60_pct"] = (df["high60_prev"] / df["low60_prev"] - 1.0) * 100.0
    df["range120_pct"] = (df["high120_prev"] / df["low120_prev"] - 1.0) * 100.0
    df["line_above_count"] = (
        (df["close"] >= df["BBI"]).astype("int8")
        + (df["close"] >= df["zge_white_line"]).astype("int8")
        + (df["close"] >= df["zge_yellow_line"]).astype("int8")
    )
    df["line_touch_bbi"] = df["low"] <= df["BBI"] * 1.015
    df["line_touch_white"] = df["low"] <= df["zge_white_line"] * 1.02
    df["line_touch_yellow"] = df["low"] <= df["zge_yellow_line"] * 1.02
    df["line_reclaim_white"] = df["close"] >= df["zge_white_line"]
    df["brick_exist"] = df[
        [
            "brick_exist_b",
            "brick_buy1_low_absorb",
            "brick_buy2_attack",
            "brick_buy",
            "brick_resonance_context",
            "gold_brick_context",
        ]
    ].any(axis=1)
    df["brick_red"] = df["brick_red_today"]
    df["brick_strong_red_calc"] = df["brick_strong_red"] | df["brick_buy2_attack"]
    df["breakout_event"] = df["breakout"] | df["break_prev_high"] | df["double_breakout"]
    df["funding_k"] = (
        (df["pc_calc"] >= 4.0)
        & (df["close"] >= df["open"])
        & ((df["volr"] >= 1.45) | (df["vma20r"] >= 1.35) | df["plry_first"])
        & (df["bar_close_pos"] >= 0.45)
    )
    df["strong_funding_k"] = (
        (df["pc_calc"] >= 7.0)
        & (df["close"] >= df["open"])
        & ((df["volr"] >= 1.7) | (df["vma20r"] >= 1.6))
        & (df["bar_close_pos"] >= 0.55)
    )
    df["funding_count_30"] = rolling(df["funding_k"].astype("int8"), keys, 30, 1, "sum")
    df["strong_funding_count_30"] = rolling(
        df["strong_funding_k"].astype("int8"), keys, 30, 1, "sum"
    )
    green15 = rolling((df["close"] >= df["open"]).astype("int8"), keys, 15, 5, "sum")
    up_day = df["close"] > gb["close"].shift(1)
    up11 = rolling(up_day.astype("int8"), keys, 11, 5, "sum")
    df["red_fat_green_thin"] = (green15 >= 8) | (up11 >= 6)
    up_vol = rolling(df["volume"].where(up_day, 0.0), keys, 30, 5, "sum")
    down_day = df["close"] < gb["close"].shift(1)
    down_vol = rolling(df["volume"].where(down_day, 0.0), keys, 30, 5, "sum")
    df["volume_price_path"] = (up_vol > down_vol * 1.05) | df["red_fat_green_thin"]
    df["key_half_proxy"] = (
        (df["funding_count_30"] >= 1)
        & (df["close"] >= df["BBI"] * 0.98)
        & (df["low20_to_close"].fillna(0) >= 0)
        & (df["ret_pre20"].fillna(0) <= 45)
    )
    df["long_base_quality"] = (
        (df["range60_pct"] <= 45)
        & (df["funding_count_30"] >= 1)
        & (df["close"] >= df["BBI"] * 0.95)
    ) | (
        (df["range120_pct"] <= 85)
        & (df["funding_count_30"] >= 1)
        & (df["close"] >= df["BBI"] * 0.90)
    )
    df["b2_prior5"] = rolling(gb["B2"].shift(1).fillna(False).astype("int8"), keys, 5, 1, "max").fillna(0).astype(bool)
    df["b1_prior5"] = rolling(gb["B1"].shift(1).fillna(False).astype("int8"), keys, 5, 1, "max").fillna(0).astype(bool)

    depth = np.select(
        [
            df["line_touch_yellow"] & (df["close"] >= df["zge_yellow_line"] * 0.96),
            (df["low"] <= ((df["zge_white_line"] + df["zge_yellow_line"]) / 2.0))
            & (df["close"] >= df["zge_yellow_line"] * 0.93),
            df["line_touch_white"] & (df["close"] >= df["zge_white_line"] * 0.96),
            df["line_touch_bbi"],
        ],
        [8, 7, 5, 3],
        default=0,
    )
    shrink = np.select(
        [df["vsp20_hhv"] <= 0.60, df["vsp20_hhv"] <= 0.70, df["vsp20_hhv"] <= 0.80, df["vsp20_hhv"] <= 0.90],
        [8, 6, 4, 2],
        default=0,
    )
    low_j = np.select(
        [
            (df["J"] <= 5) | (df["zge_rsi3"] <= 15),
            (df["J"] <= 13) | (df["zge_rsi3"] <= 21),
            (df["J"] <= 30) | (df["zge_rsi3"] <= 40),
        ],
        [5, 4, 2],
        default=0,
    )
    structure = np.where(
        (df["close"] >= df["zge_yellow_line"] * 0.95)
        | (df["low"] >= df["zge_yellow_line"] * 0.90),
        3,
        0,
    )
    long_yin_short = np.where(
        (df["pc_calc"] <= -3) & (df["vsp20_hhv"] <= 0.80), 4, 0
    )
    df["wash0v1"] = depth + shrink + low_j + structure + long_yin_short
    df["wash_recent_score_5"] = rolling(
        gb["wash0v1"].shift(1), keys, 5, 1, "max"
    ).fillna(0)
    df["valid_wash_override"] = (
        (df["wash_recent_score_5"] >= 12)
        & (df["close"] >= df["BBI"] * 0.995)
        & (
            (df["pc_calc"] >= 3.0)
            | df["line_reclaim_white"]
            | (df["bar_close_pos"] >= 0.60)
        )
        & (df["ret_pre20"].fillna(0) <= 45)
        & (df["B2"] | df["b2_prior5"] | (df["pc_calc"] >= 4.0))
        & (df["low20_to_close"].fillna(0) <= 45)
        & (df["macd_hist"].fillna(-999) > -2.0)
    )
    df["strong_control_quality"] = (
        (
            df["long_base_quality"]
            | (df["funding_count_30"] >= 2)
            | (df["strong_funding_count_30"] >= 1)
        )
        & (df["close"] >= df["BBI"] * 0.98)
        & (df["bar_close_pos"] >= 0.50)
    )
    df["late_extension_flag"] = (
        (df["ret_pre20"] >= 30)
        & (df["low20_to_close"] >= 35)
        & (df["J"] >= 75)
        & (~df["valid_wash_override"])
        & (~df["strong_control_quality"])
    )
    df["weak_standline_flag"] = (
        (df["line_above_count"] >= 2)
        & (df["pc_calc"] >= 3)
        & (df["J"] >= 55)
        & (df["macd_hist"] < 0)
        & (~df["valid_wash_override"])
        & (~df["strong_control_quality"])
    )

    anchor = df[
        [
            "B1",
            "brick_original_b1",
            "brick_pullback_white_b",
            "brick_pullback_yellow_b",
            "brick_oversold_shrink_b",
            "brick_oversold_super_shrink_b",
        ]
    ].any(axis=1)
    df["prior_B1_20"] = rolling(gb["B1"].shift(1).fillna(False).astype("int8"), keys, 20, 1, "max").fillna(0).astype(bool)
    df["prior_anchor_20"] = rolling(anchor.groupby(keys).shift(1).fillna(False).astype("int8"), keys, 20, 1, "max").fillna(0).astype(bool)
    df["prior_lowJ_20"] = (
        rolling(gb["J"].shift(1), keys, 20, 1, "min") <= 20
    ).fillna(False)
    vol5 = rolling(df["volume"], keys, 5, 5, "mean")
    df["prior_volume_dryup_proxy"] = (
        gb["volume"].shift(1) <= vol5.groupby(keys).shift(1) * 0.9
    ).fillna(False)
    df["b1_precondition_score"] = (
        df["prior_B1_20"].astype("int8") * 7
        + df["prior_anchor_20"].astype("int8") * 7
        + df["prior_lowJ_20"].astype("int8") * 4
        + df["prior_volume_dryup_proxy"].astype("int8") * 2
    )
    health_cols = [
        "ref_score_close_up",
        "ref_score_above_bbi",
        "ref_score_no_giant_true_yin",
        "ref_score_trend_up",
        "ref_score_j_no_dead_cross",
    ]
    df["formula_5point_health"] = df[health_cols].astype("int8").sum(axis=1)
    df["line_reclaim_quality_score"] = (
        (df["close"] >= df["BBI"]).astype("int8") * 4
        + (df["close"] >= df["zge_white_line"]).astype("int8") * 4
        + (df["close"] >= df["zge_yellow_line"]).astype("int8") * 2
        + (df["bar_close_pos"] >= 0.55).astype("int8") * 3
    )
    prior_b2_60 = rolling(gb["B2"].shift(1).fillna(False).astype("int8"), keys, 60, 1, "sum").fillna(0)
    df["prior_B2_count60"] = prior_b2_60
    route_now = df["B2"] | df["B3"] | df["brick_buy"] | df["macd_above_zero_second_gold"]
    df["prior_route_count60"] = rolling(
        route_now.groupby(keys).shift(1).fillna(False).astype("int8"), keys, 60, 1, "sum"
    ).fillna(0)
    df["stable_volume_continuation_context"] = (
        (rolling(gb["B2"].shift(1).fillna(False).astype("int8"), keys, 60, 1, "sum").fillna(0)
         + rolling(gb["B3"].shift(1).fillna(False).astype("int8"), keys, 60, 1, "sum").fillna(0) > 0)
        & df["amount_ratio_20"].between(0.7, 1.6)
        & (df["close"] >= df["BBI"])
        & (df["close"] >= df["zge_white_line"])
        & (df["upper_shadow_pct"] <= 6)
    )
    df["volume_price_confirm_score"] = (
        df["pc_calc"].between(4, 12).astype("int8") * 5
        + df["amount_ratio_20"].between(0.8, 3.2).astype("int8") * 4
        + df["stable_volume_continuation_context"].astype("int8") * 2
        + (df["bar_close_pos"] >= 0.65).astype("int8") * 3
        + (df["upper_shadow_pct"] <= 6).astype("int8") * 2
    )
    df["macd_confirm_score"] = (
        df["macd_above_zero_second_gold"].astype("int8") * 5
        + (df["macd_dif"] > df["macd_dea"]).astype("int8") * 3
        + (df["macd_hist"] > gb["macd_hist"].shift(1)).astype("int8") * 2
    )
    df["dist_white_pct"] = (df["close"] / df["zge_white_line"] - 1.0) * 100.0
    df["dist_bbi_pct"] = (df["close"] / df["BBI"] - 1.0) * 100.0
    df["position_quality_score"] = (
        (df["dist_white_pct"].abs() <= 8).astype("int8") * 4
        + (df["dist_bbi_pct"].abs() <= 8).astype("int8") * 3
        + df["J"].between(10, 78).astype("int8") * 3
    )
    position = pd.Series(np.arange(len(df), dtype=float), index=df.index)
    last_b2 = position.where(df["B2"]).groupby(keys).ffill().groupby(keys).shift(1)
    df["days_since_prior_B2"] = (position - last_b2).fillna(999)
    df["new_lowJ_after_prior_B2"] = (
        (rolling(gb["J"].shift(1), keys, 12, 1, "min") <= 20).fillna(False)
        & (df["prior_B2_count60"] > 0)
    )
    df["new_anchor_after_prior_B2"] = (
        rolling(anchor.groupby(keys).shift(1).fillna(False).astype("int8"), keys, 12, 1, "max")
        .fillna(0)
        .astype(bool)
        & (df["prior_B2_count60"] > 0)
    )
    return df

def _trade_date_filters(
    trade_type: pa.DataType, start: int, end: int
) -> list[tuple[str, str, object]]:
    """Build parquet filters with literals matching the stored date type."""

    if pa.types.is_dictionary(trade_type):
        trade_type = trade_type.value_type
    if pa.types.is_integer(trade_type):
        return [
            ("trade_date", ">=", int(start)),
            ("trade_date", "<=", int(end)),
        ]
    if pa.types.is_string(trade_type) or pa.types.is_large_string(trade_type):
        return [
            ("trade_date", ">=", f"{start:08d}"),
            ("trade_date", "<=", f"{end:08d}"),
        ]
    if pa.types.is_date(trade_type):
        return [
            ("trade_date", ">=", _datetime.date(
                int(f"{start:08d}"[:4]), int(f"{start:08d}"[4:6]), int(f"{start:08d}"[6:])
            )),
            ("trade_date", "<=", _datetime.date(
                int(f"{end:08d}"[:4]), int(f"{end:08d}"[4:6]), int(f"{end:08d}"[6:])
            )),
        ]
    if pa.types.is_timestamp(trade_type):
        start_value = _datetime.datetime.strptime(f"{start:08d}", "%Y%m%d")
        end_value = _datetime.datetime.strptime(f"{end:08d}", "%Y%m%d") + _datetime.timedelta(days=1)
        timezone_name = trade_type.tz
        if timezone_name:
            try:
                start_value = pd.Timestamp(start_value, tz=timezone_name).to_pydatetime()
                end_value = pd.Timestamp(end_value, tz=timezone_name).to_pydatetime()
            except (TypeError, ValueError) as error:
                raise RuntimeError(
                    f"unsupported trade_date timestamp timezone: {timezone_name}"
                ) from error
        return [
            ("trade_date", ">=", start_value),
            ("trade_date", "<", end_value),
        ]
    raise RuntimeError(f"unsupported trade_date Arrow type: {trade_type}")


def read_window(panel_path: Path, start: int, end: int) -> pd.DataFrame:
    schema = pq.ParquetFile(panel_path).schema_arrow
    available = set(schema.names)
    missing = sorted(set(REQUIRED_BASE_COLUMNS) - available)
    if missing:
        raise RuntimeError(f"missing required columns: {missing}")
    return pd.read_parquet(
        panel_path,
        columns=REQUIRED_BASE_COLUMNS,
        filters=_trade_date_filters(schema.field("trade_date").type, start, end),
        engine="pyarrow",
    )

def score_v19(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["funding_score"] = (
        (out["funding_count_30"] >= 1).astype(int) * 6
        + (out["funding_count_30"] >= 2).astype(int) * 5
        + (out["strong_funding_count_30"] >= 1).astype(int) * 4
        + out["volume_price_path"].astype(int) * 5
        + out["key_half_proxy"].astype(int) * 4
        + out["long_base_quality"].astype(int) * 5
    ).clip(upper=25)
    line_depth = np.select(
        [
            out["line_touch_yellow"] & (out["close"] >= out["zge_yellow_line"] * 0.96),
            out["low"] <= ((out["zge_white_line"] + out["zge_yellow_line"]) / 2.0),
            out["line_touch_white"],
            out["line_touch_bbi"],
        ],
        [8, 7, 5, 3],
        default=0,
    )
    shrink = np.select([out["vsp20_hhv"] <= 0.60, out["vsp20_hhv"] <= 0.70, out["vsp20_hhv"] <= 0.80, out["vsp20_hhv"] <= 0.90], [8, 6, 4, 2], default=0)
    low_j = np.select([(out["J"] <= 5) | (out["zge_rsi3"] <= 15), (out["J"] <= 13) | (out["zge_rsi3"] <= 21), (out["J"] <= 30) | (out["zge_rsi3"] <= 40)], [5, 4, 2], default=0)
    recent = np.select([out["wash_recent_score_5"] >= 18, out["wash_recent_score_5"] >= 12], [10, 6], default=0)
    long_yin_short = ((out["pc_calc"] <= -3) & (out["vsp20_hhv"] <= 0.8)).astype(int) * 4
    out["wash_score"] = (line_depth + shrink + low_j + recent + long_yin_short).clip(upper=30)

    funding_entry = out["funding_k"] & ((out["low20_to_close"] <= 35) | out["long_base_quality"]) & (out["ret_pre20"] <= 45)
    b1_low = (out["funding_count_30"] >= 1) & ((out["J"] <= 35) | (out["zge_rsi3"] <= 40) | out["brick_exist"]) & (out["vsp20_hhv"] <= 1.05) & (out["line_touch_white"] | out["line_touch_bbi"] | out["line_touch_yellow"])
    strict_b2 = (out["B2"] | ((out["pc_calc"] >= 4) & (out["close"] >= out["open"]))) & (out["valid_wash_override"] | (out["wash_recent_score_5"] >= 14) | out["b1_prior5"]) & (out["line_above_count"] >= 1) & (out["J"] <= 90)
    wash_rebreak = out["valid_wash_override"] & (out["pc_calc"] >= 3) & (out["close"] >= out["BBI"] * 0.995) & (out["bar_close_pos"] >= 0.55)
    strong_control = out["strong_control_quality"] & ((out["pc_calc"] >= 3.5) | out["breakout_event"] | out["brick_strong_red_calc"]) & ((out["volr"] >= 0.75) | (out["vma20r"] >= 0.75) | out["brick_red"])
    b2_cont = out["b2_prior5"] & (out["line_above_count"] >= 2) & (out["pc_calc"] > -2) & (out["bar_close_pos"] >= 0.45)
    b3_cont = (out["B3"] | out["breakout_event"] | ((out["pc_calc"] >= 4) & (out["close"] >= out["high_20_prev"] * 0.98))) & (out["funding_count_30"] >= 1) & (out["line_above_count"] >= 2) & (~out["late_extension_flag"])
    keybrick = (out["brick_exist"] | out["brick_strong_red_calc"] | out["brick_red"]) & (out["funding_count_30"] >= 1) & ((out["wash_recent_score_5"] >= 10) | b1_low | strict_b2 | strong_control)
    route_df = pd.DataFrame(
        {
            "FUNDING_ENTRY_KEYK": np.where(funding_entry & out["strong_funding_k"], 20, np.where(funding_entry, 16, 0)),
            "B1_LOW_ABSORB_ANCHOR": np.where(b1_low & (out["wash_score"] >= 12), 21, np.where(b1_low, 17, 0)),
            "STRICT_B2_CHAIN": np.where(strict_b2 & (out["wash_recent_score_5"] >= 12), 23, np.where(strict_b2, 18, 0)),
            "WASH_RESET_REBREAK": np.where(wash_rebreak, 24, 0),
            "STRONG_CONTROL_RECLAIM": np.where(strong_control, 22, 0),
            "B2_CONFIRMATION_CONTINUATION": np.where(b2_cont, 18, 0),
            "B3_CONTINUATION": np.where(b3_cont, 18, 0),
            "KEY_K_GOLD_BRICK_CONFIRMATION": np.where(keybrick, 15, 0),
        },
        index=out.index,
    )
    out["route_score"] = route_df.max(axis=1).astype(float)
    out["route_type"] = route_df.idxmax(axis=1)
    out.loc[out["route_score"] <= 0, "route_type"] = "NO_VALID_ROUTE"
    route_context = (out["route_score"] >= 12) | (out["funding_score"] >= 18) | (out["wash_score"] >= 18)
    line_confirm = np.select([(out["line_above_count"] >= 3) & (out["bar_close_pos"] >= 0.60), out["line_above_count"] >= 2, out["line_above_count"] >= 1], [6, 4, 2], default=0)
    volume_confirm = np.where((out["pc_calc"] > 0) & (out["close"] >= out["open"]) & ((out["volr"] >= 1.5) | (out["vma20r"] >= 1.5)), 4, np.where((out["pc_calc"] > 0) & (out["close"] >= out["open"]) & ((out["volr"] >= 1.05) | (out["vma20r"] >= 1.0)), 2, 0))
    macd_point = np.where((out["macd_hist"] >= 0) & (out["macd_hist"] >= out["macd_hist"].shift(1)), 3, np.where(out["macd_hist"] > out["macd_hist"].shift(1), 1, 0))
    brick_point = np.where(out["brick_strong_red_calc"], 3, np.where(out["brick_red"] | out["brick_exist"], 2, 0))
    close_point = np.where(out["bar_close_pos"] >= 0.8, 4, np.where(out["bar_close_pos"] >= 0.6, 2, 0))
    breakout_point = out["breakout_event"].astype(int) * 3
    out["confirmation_score"] = np.clip(
        np.where(route_context, line_confirm + volume_confirm + macd_point + brick_point + close_point + breakout_point, 0),
        None,
        20,
    )
    not_overheated = (out["ret_pre20"] <= 30) | out["valid_wash_override"] | out["strong_control_quality"]
    position_low = (out["low20_to_close"] <= 30) | out["long_base_quality"]
    stop_anchor = out["line_touch_bbi"] | out["line_touch_white"] | out["line_touch_yellow"] | (out["wash_recent_score_5"] >= 12)
    out["timing_score"] = (not_overheated.astype(int) * 4 + position_low.astype(int) * 3 + stop_anchor.astype(int) * 3).clip(upper=10)
    out["raw_score"] = (out["funding_score"] + out["wash_score"] + out["route_score"] + out["confirmation_score"] + out["timing_score"]).clip(upper=100)
    risk_cap = pd.Series(100.0, index=out.index)
    out["v19_risk_reasons"] = ""
    late = out["late_extension_flag"]
    weak = out["weak_standline_flag"] & out["route_type"].isin(["NO_VALID_ROUTE", "B3_CONTINUATION"])
    dist = ((out["upper_shadow_pct"] >= 8) & (out["bar_close_pos"] < 0.55) & (out["ret_pre20"] >= 20) & (out["volr"] >= 1.2)) | out["macd_top_divergence"] | out["white_yellow_death_cross"]
    for mask, reason in [(late, "LATE_EXTENSION"), (weak, "FALSE_WEAK_STANDLINE"), (dist & (~out["valid_wash_override"]), "DISTRIBUTION_OR_CHASE")]:
        risk_cap = risk_cap.mask(mask, np.minimum(risk_cap, 69.0))
        out.loc[mask, "v19_risk_reasons"] = out.loc[mask, "v19_risk_reasons"].astype(str).str.cat(pd.Series([reason] * int(mask.sum()), index=out.index[mask]), sep=";").str.strip(";")
    out["risk_cap"] = risk_cap
    out["final_score"] = np.minimum(out["raw_score"], out["risk_cap"])
    out["actual_level"] = np.select([out["final_score"] >= 85, out["final_score"] >= 80, out["final_score"] >= 70], ["S", "A", "WATCH"], default="NO")
    return out

def score_multi_head(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "risk_penalty" not in out.columns:
        out["risk_penalty"] = np.maximum(0.0, 100.0 - out.get("risk_cap", 100.0))
    route_handle = out["primary_buy_signal"] | out["secondary_buy_signal"] | out["brick_buy2_attack"] | out["double_breakout"] | out["B2"] | out["brick_buy"]
    direct_b2 = out["B2"] | out["secondary_buy_signal"]
    level1 = out["primary_buy_signal"]
    brick_route = out["brick_buy"] | out["brick_buy2_attack"] | out["brick_resonance_context"]
    new_reset = out["new_lowJ_after_prior_B2"] | out["new_anchor_after_prior_B2"]
    amount = out["amount_ratio_20"].fillna(0)
    dist_white = out["dist_white_pct"].abs().fillna(999)
    dist_bbi = out["dist_bbi_pct"].abs().fillna(999)
    j = out["J"].fillna(999)
    upper = out["upper_shadow_pct"].fillna(999)
    ret20 = out["ret_pre20"].fillna(0)
    gain60 = out["gain_from_low60_pct"].fillna(0)
    b1_pre = out["b1_precondition_score"].fillna(0)
    line_score = out["line_reclaim_quality_score"].fillna(0)
    macd_score = out["macd_confirm_score"].fillna(0)
    position_score = out["position_quality_score"].fillna(0)
    health = out["formula_5point_health"].fillna(0)
    stable_hold = out["stable_volume_continuation_context"]
    trend_intact = (line_score >= 10) & (health >= 4) & (upper <= 6) & (dist_white <= 10)
    volume_stable = amount.between(0.7, 1.6)
    volume_healthy = amount.between(0.8, 3.2)
    same_wave = (out["prior_B2_count60"] >= 1) & (out["days_since_prior_B2"] <= 12) & (~new_reset)
    multi_b2_ext = (out["prior_B2_count60"] >= 2) & (gain60 >= 60)
    hot_far = (j >= 88) & (dist_white >= 12)
    late_extension = (gain60 >= 90) | (ret20 >= 45)
    weak_level1_only = route_handle & (~direct_b2) & (b1_pre <= 2) & ((j >= 78) | (dist_white >= 8))

    fresh = (
        route_handle.astype(int) * 12
        + direct_b2.astype(int) * 16
        + level1.astype(int) * 8
        + brick_route.astype(int) * 5
        + np.minimum(b1_pre, 18)
        + (health >= 4).astype(int) * 12
        + np.where(line_score >= 8, np.minimum(line_score, 12), 0)
        + volume_healthy.astype(int) * 10
        + np.minimum(macd_score, 8)
        + np.minimum(position_score, 10)
    ).clip(upper=100)
    continuation = (
        direct_b2.astype(int) * 8
        + level1.astype(int) * 8
        + brick_route.astype(int) * 6
        + out["B3"].astype(int) * 20
        + (out["prior_route_count60"] > 0).astype(int) * 12
        + new_reset.astype(int) * 10
        + stable_hold.astype(int) * 16
        + np.minimum(b1_pre, 8)
        + (health >= 4).astype(int) * 12
        + np.where(line_score >= 8, np.minimum(line_score, 12), 0)
        + volume_healthy.astype(int) * 10
        + np.minimum(macd_score + out["macd_above_zero_second_gold"].astype(int) * 4, 10)
        + np.minimum(position_score, 8)
        + out["pc_calc"].between(4, 12).astype(int) * 5
    ).clip(upper=100)
    hold = (
        level1.astype(int) * 5
        + out["B3"].astype(int) * 8
        + (out["prior_route_count60"] > 0).astype(int) * 12
        + stable_hold.astype(int) * 25
        + (health >= 4).astype(int) * 15
        + np.where(line_score >= 8, np.minimum(line_score * 1.4, 18), 0)
        + volume_stable.astype(int) * 12
        + np.minimum(macd_score, 6)
        + np.minimum(position_score, 5)
        + (upper <= 6).astype(int) * 8
        + ((dist_white <= 8) & (dist_bbi <= 8)).astype(int) * 5
    ).clip(upper=100)
    risk = (
        (j >= 88).astype(int) * 50
        + hot_far.astype(int) * 20
        + (amount >= 4).astype(int) * 20
        + (upper >= 8).astype(int) * 15
        + (dist_white >= 12).astype(int) * 10
        + (ret20 >= 45).astype(int) * 20
        + (gain60 >= 90).astype(int) * 30
        + (gain60 >= 120).astype(int) * 35
        + np.where(same_wave, np.where(stable_hold | trend_intact | volume_stable, 8, 25), 0)
        + np.where(multi_b2_ext, np.where(stable_hold | trend_intact | volume_stable, 8, 20), 0)
        + np.where((out["risk_penalty"] >= 14) & (~(stable_hold | trend_intact)), 15, 0)
        + weak_level1_only.astype(int) * 55
    ).clip(upper=100)
    out["fresh_b2_entry_score"] = fresh.round(4)
    out["continuation_entry_score"] = continuation.round(4)
    out["hold_through_main_wave_score"] = hold.round(4)
    out["risk_chase_score"] = risk.round(4)
    out["multi_entry_score"] = np.maximum(out["fresh_b2_entry_score"], out["continuation_entry_score"])
    out["multi_entry_risk_adjusted_score"] = out["multi_entry_score"] - out["risk_chase_score"]
    fresh_context = route_handle & (direct_b2 | (b1_pre >= 4)) & ((out["prior_B2_count60"] == 0) | (out["days_since_prior_B2"] > 20) | new_reset)
    continuation_context = (out["prior_route_count60"] > 0) | out["B3"] | (out["prior_B2_count60"] > 0)
    roles = np.full(len(out), "NEED_MANUAL_REVIEW", dtype=object)
    risk_reject = (risk >= 60) & (out["break_yesterday_keyline"] | out["white_yellow_death_cross"] | out["fd_volume_yin"] | late_extension)
    roles[(risk >= 60) & (~risk_reject)] = "AVOID_CHASE"
    roles[risk_reject] = "RISK_REJECT"
    roles[(risk < 60) & multi_b2_ext & (stable_hold | trend_intact | volume_stable) & (hold >= 70)] = "MAIN_WAVE_HOLD"
    roles[(risk < 60) & multi_b2_ext & (stable_hold | trend_intact | volume_stable) & (hold < 70)] = "WAIT_PULLBACK"
    mask = (risk < 45) & (fresh >= 70) & fresh_context
    roles[mask] = "B2_FRESH_ENTRY"
    mask = (roles == "NEED_MANUAL_REVIEW") & (risk < 50) & (continuation >= 70) & continuation_context
    roles[mask] = "B3_CONTINUATION_ENTRY"
    mask = (roles == "NEED_MANUAL_REVIEW") & (risk < 60) & (hold >= 70)
    roles[mask] = "MAIN_WAVE_HOLD"
    mask = (roles == "NEED_MANUAL_REVIEW") & (risk < 60) & (hold >= 60) & (fresh < 70) & (continuation < 70)
    roles[mask] = "WAIT_PULLBACK"
    out["multi_head_final_role"] = roles
    out["same_wave_repeat_flag"] = same_wave
    out["multi_b2_extension_flag"] = multi_b2_ext
    out["stable_trend_hold_flag"] = stable_hold | trend_intact
    return out

def _role_truthy(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "1.0", "true", "yes", "y", "t"}
    try:
        return float(value) != 0.0
    except Exception:
        return bool(value)

def entry_pool(df: pd.DataFrame) -> pd.Series:
    cols = [
        "gold_brick_context",
        "brick_resonance_context",
        "brick_buy",
        "brick_buy1_low_absorb",
        "brick_buy2_attack",
        "primary_buy_signal",
        "secondary_buy_signal",
    ]
    out = pd.Series(False, index=df.index)
    for c in cols:
        if c in df.columns:
            out = out | df[c].map(_role_truthy).astype(bool)
    return out

def role_series(df: pd.DataFrame) -> pd.Series:
    return df["multi_head_final_role"].astype(str).str.upper()

def base_fmla04_role(df: pd.DataFrame) -> pd.Series:
    role = role_series(df)
    risk = pd.to_numeric(df["risk_chase_score"], errors="coerce").fillna(0)
    fresh = pd.to_numeric(df["fresh_b2_entry_score"], errors="coerce").fillna(0)
    cont = pd.to_numeric(df["continuation_entry_score"], errors="coerce").fillna(0)
    v19 = pd.to_numeric(df["final_score"], errors="coerce")
    hold_score = pd.to_numeric(df["hold_through_main_wave_score"], errors="coerce").fillna(0)
    heat = (
        (pd.to_numeric(df.get("dist_white_pct", 0), errors="coerce").fillna(0) >= 10)
        | (pd.to_numeric(df.get("dist_bbi_pct", 0), errors="coerce").fillna(0) >= 10)
        | (pd.to_numeric(df.get("low20_to_close", 0), errors="coerce").fillna(0) >= 20)
        | (pd.to_numeric(df.get("ret_pre20", 0), errors="coerce").fillna(0) >= 25)
        | (pd.to_numeric(df.get("upper_shadow_pct", 0), errors="coerce").fillna(0) >= 4)
    )
    b2 = role.str.contains("B2_FRESH", na=False)
    b3 = role.str.contains("B3_CONTINUATION", na=False)
    hold = role.str.contains("MAIN_WAVE_HOLD|HOLD_THROUGH", regex=True, na=False)
    wait = role.str.contains("WAIT_PULLBACK", na=False)
    need_manual = role.str.contains("NEED_MANUAL", na=False)
    risk_role = role.str.contains("RISK|AVOID|CHASE|FAIL", regex=True, na=False)
    high_quality_b2 = b2 & (risk < 45) & ((fresh >= 70) | (v19 >= 85))
    high_quality_b3 = b3 & (risk < 45) & ((cont >= 70) | (v19 >= 85))
    b2_hot_rescue = high_quality_b2 & ((~heat) | (fresh >= 88) | (v19 >= 85))
    b3_hot_rescue = high_quality_b3 & ((~heat) | (cont >= 75) | (v19 >= 85))
    hot_buy_rescue = b2_hot_rescue | b3_hot_rescue

    pred = pd.Series("TEST_ONLY_POLLUTION_OR_BOUNDARY", index=df.index, dtype=object)
    pred[hold & (risk < 60)] = "TEST_ONLY_HOLD_CONTEXT"
    pred[wait] = "TEST_ONLY_POLLUTION_OR_BOUNDARY"
    manual_risk = need_manual & ((risk >= 55) | (pd.to_numeric(df.get("upper_shadow_pct", 0), errors="coerce").fillna(0) >= 6))
    pred[manual_risk] = "TEST_ONLY_RISK_OR_CHASE"
    hard_risk = ((risk >= 60) | risk_role) & (~hot_buy_rescue) & (~hold) & (~wait) & (~need_manual)
    pred[hard_risk] = "TEST_ONLY_RISK_OR_CHASE"
    heat_risk = heat & (~hot_buy_rescue) & (~hold) & (~wait) & (~need_manual)
    pred[heat_risk] = "TEST_ONLY_RISK_OR_CHASE"
    pred[high_quality_b2 | high_quality_b3] = "TEST_ONLY_BUY_CANDIDATE"
    pred[(pred == "TEST_ONLY_POLLUTION_OR_BOUNDARY") & (risk >= 45)] = "TEST_ONLY_RISK_OR_CHASE"
    pred[~entry_pool(df)] = "TEST_ONLY_POLLUTION_OR_BOUNDARY"
    return pred
