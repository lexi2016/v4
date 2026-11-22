"""Pure, causal V4 full-A-share PFT-S features and weak-label rules.

The formulas port the fixed Gemini R2 feature contract to V4's directly
observed white/yellow/BBI columns. No file, network, or panel access occurs in
this module.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


FEATURE_SCHEMA = "pft_s_full_ashare_r2_features.v2"
LABEL_RULE_SCHEMA = "pft_s_full_ashare_weak_labels.v1"
FEATURES = (
    "wy_spread_pct", "c_vs_white_pct", "c_vs_yellow_pct", "c_vs_bbi_pct",
    "l_vs_yellow_pct", "y_consec2_active_5b", "y_below_at_d",
    "repaired_prior_y_break", "w_below_consec_at_d", "recent_anchor_low_intact",
    "c_vs_recent_anchor_low_pct", "d_low_vs_recent_anchor_low_pct",
    "c_vs_recent_anchor_mid_pct", "has_prior_surge_40b",
    "pb_vol_contraction_score", "pb_narrow_amp_score", "pb_support_hold_score",
    "pb_affinity", "ra_breakout_vol_score", "ra_prior_consol_score", "ra_affinity",
    "max_branch_affinity", "dd_from_pk30_pct", "pos_in_60bar_pct",
    "last5_low_slope_pct", "red_green_vol_ratio_10b", "brk_prev10_high",
    "brk_prev20_high",
)

GATE_COLUMNS = ("g1_wy_pass", "g2_s26_reject", "gate_pass")
EVIDENCE_COLUMNS = (
    "d_ret_pct", "d_amp_pct", "d_vr5", "d_upper_shadow_pct", "bars_since_pk30",
    "y_consec2_break_15b", "no_old_yellow_break_26b", "prior_anchor_date",
    "prior_anchor_low", "prior_anchor_mid", "prior_anchor_return_pct",
    "prior_anchor_relative_volume", "prior_anchor_intact", "prior_consolidation",
    "prior_anchor_recent_break_5b", "prior_anchor_d_low_vs_low_pct",
    "d_intraday_probe_recovered", "d_low_held_above_anchor", "d_close_below_anchor_low",
    "d_reclaim_anchor_low", "w_below_days_15b", "history_rows_available",
)

WEAK_LABEL_RULES: dict[str, Any] = {
    "schema": LABEL_RULE_SCHEMA,
    "asof": "all features, weak labels, and evidence use rows with trade_date <= D",
    "positive_pullback": {
        "g1": "white > yellow", "g2": "not rejected", "recent_yellow_break": "none in last 15 closes",
        "prior_surge": "strictly before D in R2 last-40-row window; return >= 3.5%; volume/prior-5-volume >= 1.2",
        "anchor": "most recent qualifying prior surge low remains unbroken by any close through D",
        "D": "close return in [-3%,2%], amplitude <= 5.5%, D volume/prior-5-volume <= 0.90, close >= white",
    },
    "positive_readvance": {
        "g1": "white > yellow", "g2": "not rejected", "recent_yellow_break": "none in last 15 closes",
        "prior_surge": "qualifying strictly-before-D surge anchor within R2 last-40-row window",
        "consolidation": "at least 2 bars after anchor and at least one intervening volume ratio <= 0.90",
        "D": "return >= 2.5%, volume/prior-5-volume >= 1.25, close breaks prior 10- or 20-bar high",
    },
    "positive_rebuild": {
        "g1": "white > yellow", "g2": "not rejected", "recent_yellow_break": "no active adjacent pair in last 5 closes",
        "old_break_repaired": "R2 prior yellow break in D-25..D-5, D and D-1 close above both white and yellow",
        "rebuild": "prior consolidation, return >= 2.5%, volume/prior-5-volume >= 1.25, close breaks prior 10- or 20-bar high",
    },
    "hard_negative_no_old_yellow_break": {
        "observation_window": "fully observed D-25..D, 26 direct V4 yellow observations",
        "rule": "no adjacent pair of closes below direct yellow; missing values never count as FALSE",
        "near_anchor_broken": "W>Y, prior surge anchor exists, D close below anchor low and below white",
        "local_reclaim_below_support": "W>Y, a close below the prior anchor low in D-5..D-1, D low probes to/below the anchor low and recovers above it at close, D close remains below white, low-slope <= -3.5%",
        "fresh_breakout_without_consolidation": "W>Y, D return >= 2.5%, volume ratio >= 1.25, breaks prior 10/20 high, no qualifying prior consolidation",
    },
    "ordinary_negative": {
        "active_break_or_bear_regime": "active yellow pair in last 5 closes or W<=Y",
        "high_distribution": "fixed R2 G2 rejection",
    },
    "precedence": "hard negative, positive, then ordinary negative; unknown/ambiguous rows remain unlabelled",
    "model_inputs_exclude": ["label", "subtype", "tactic", "stage", "case_id", "source text", "future/outcome fields"],
}


def _tri_window(close: pd.Series, yellow: pd.Series, pair_count: int) -> pd.Series:
    """Any adjacent below pair => TRUE; otherwise FALSE only if all pairs are observed."""
    below = close.lt(yellow)
    known = close.notna() & yellow.notna()
    pair_true = below & below.shift(1, fill_value=False)
    pair_known = known & known.shift(1, fill_value=False)
    true_any = pair_true.astype("int8").rolling(pair_count, min_periods=1).max().fillna(0).to_numpy()
    known_count = pair_known.astype("int8").rolling(pair_count, min_periods=1).sum().fillna(0).to_numpy()
    # FALSE requires the entire requested N-close window (N-1 adjacent
    # comparisons). A proven pair remains TRUE even when other comparisons
    # are missing or the available history is short.
    needed = np.full(len(close), pair_count, dtype=int)
    result = np.full(len(close), np.nan, dtype=float)
    result[true_any > 0] = 1.0
    result[(true_any == 0) & (known_count == needed)] = 0.0
    return pd.Series(result, index=close.index)


def feature_frame(history: pd.DataFrame) -> pd.DataFrame:
    """Build R2 features for each history row, in chronological order."""
    required = ("trade_date", "open", "high", "low", "close", "vol", "bbi", "zge_white_line", "zge_yellow_line")
    missing = [name for name in required if name not in history.columns]
    if missing:
        raise ValueError("FEATURE_COLUMNS_MISSING:" + ",".join(missing))
    frame = history.loc[:, required].copy().sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    if frame["trade_date"].duplicated().any():
        raise ValueError("DUPLICATE_CANONICAL_TRADE_DATE")
    for name in required[1:]:
        frame[name] = pd.to_numeric(frame[name], errors="coerce").astype(float)

    o, h, low, c, v = (frame[name] for name in ("open", "high", "low", "close", "vol"))
    white, yellow, bbi = (frame[name] for name in ("zge_white_line", "zge_yellow_line", "bbi"))
    prev_c = c.shift(1)
    ret = (c / prev_c - 1.0) * 100.0
    amp = (h - low) / prev_c * 100.0
    prior5_volume = v.shift(1).rolling(5, min_periods=5).mean()
    vr5 = v / prior5_volume.replace(0.0, np.nan)

    yellow_active5 = _tri_window(c, yellow, 4)
    yellow_break15 = _tri_window(c, yellow, 14)
    yellow_break26 = _tri_window(c, yellow, 25)
    idx = np.arange(len(frame))
    complete26 = idx >= 25
    no_old_break26 = pd.Series(np.full(len(frame), np.nan), index=frame.index)
    no_old_break26.loc[yellow_break26.eq(1.0)] = 0.0
    no_old_break26.loc[complete26 & yellow_break26.eq(0.0)] = 1.0

    yellow_below = c.lt(yellow).where(yellow.notna() & c.notna(), np.nan).astype(float)
    prior_y_below = yellow_below.shift(5)
    prior_y_known_count = prior_y_below.notna().astype("int8").rolling(21, min_periods=1).sum()
    prior_y_any_break = prior_y_below.fillna(0.0).rolling(21, min_periods=1).max()
    prior_y_state = pd.Series(np.full(len(frame), np.nan), index=frame.index)
    prior_y_state.loc[prior_y_any_break.gt(0.0)] = 1.0
    prior_y_state.loc[(idx >= 25) & prior_y_any_break.eq(0.0) & prior_y_known_count.eq(21)] = 0.0
    recovered2 = (
        c.ge(yellow) & c.ge(white) & c.shift(1).ge(yellow.shift(1)) & c.shift(1).ge(white.shift(1))
    ).where(yellow.notna() & white.notna() & yellow.shift(1).notna() & white.shift(1).notna(), np.nan).astype(float)
    repaired = pd.Series(np.full(len(frame), np.nan), index=frame.index)
    repaired.loc[prior_y_state.eq(0.0)] = 0.0
    repaired.loc[prior_y_state.eq(1.0) & recovered2.eq(1.0) & yellow_active5.eq(0.0)] = 1.0
    repaired.loc[prior_y_state.eq(1.0) & recovered2.eq(0.0)] = 0.0
    repaired.loc[prior_y_state.eq(1.0) & yellow_active5.eq(1.0)] = 0.0

    high30 = h.rolling(30, min_periods=1).max()
    peak_position = h.rolling(30, min_periods=1).apply(lambda values: int(np.argmax(values)), raw=True)
    win_size30 = np.minimum(idx + 1, 30)
    bars_since_peak = win_size30 - 1 - peak_position
    dd_peak = (c / high30 - 1.0) * 100.0
    high60 = h.rolling(60, min_periods=1).max()
    low60 = low.rolling(60, min_periods=1).min()
    pos60 = ((c - low60) / (high60 - low60) * 100.0).where(high60.gt(low60), 50.0)
    low_slope = (low / low.shift(4) - 1.0) * 100.0
    green_volume = v.where(c.gt(o)).rolling(10, min_periods=1).mean()
    red_volume = v.where(c.lt(o)).rolling(10, min_periods=1).mean()
    red_green = green_volume / red_volume.where(red_volume.gt(0.0))

    surge = ret.ge(3.5) & vr5.ge(1.2)
    surge_idx = np.flatnonzero(surge.fillna(False).to_numpy())
    anchor_idx = np.full(len(frame), -1, dtype=int)
    if len(surge_idx):
        prior_pos = np.searchsorted(surge_idx, idx, side="left") - 1
        valid = prior_pos >= 0
        anchor_idx[valid] = surge_idx[prior_pos[valid]]
        too_old = (idx - anchor_idx) > 40
        anchor_idx[too_old] = -1
    has_anchor = anchor_idx >= 0
    has_surge_any = surge.rolling(40, min_periods=1).max().fillna(False).astype(float)
    anchor_low = np.full(len(frame), np.nan)
    anchor_mid = np.full(len(frame), np.nan)
    anchor_ret = np.full(len(frame), np.nan)
    anchor_vr5 = np.full(len(frame), np.nan)
    for i in np.flatnonzero(has_anchor):
        anchor = anchor_idx[i]
        anchor_low[i] = low.iloc[anchor]
        anchor_mid[i] = (o.iloc[anchor] + c.iloc[anchor]) / 2.0
        anchor_ret[i] = ret.iloc[anchor]
        anchor_vr5[i] = vr5.iloc[anchor]
    anchor_break_at: dict[int, int] = {}
    anchor_first_unknown_at: dict[int, int] = {}
    for anchor in surge_idx:
        end = min(len(frame), anchor + 41)
        close_window = c.iloc[anchor + 1:end].to_numpy(dtype=float)
        below_anchor = np.flatnonzero(close_window < low.iloc[anchor])
        unknown_close = np.flatnonzero(~np.isfinite(close_window))
        anchor_break_at[int(anchor)] = (int(anchor + 1 + below_anchor[0]) if len(below_anchor) else len(frame) + 1)
        anchor_first_unknown_at[int(anchor)] = (int(anchor + 1 + unknown_close[0]) if len(unknown_close) else len(frame) + 1)
    anchor_intact = np.full(len(frame), np.nan, dtype=float)
    anchor_recent_break5 = np.full(len(frame), np.nan, dtype=float)
    d_intraday_probe_recovered = np.full(len(frame), np.nan, dtype=float)
    d_low_held_above_anchor = np.full(len(frame), np.nan, dtype=float)
    d_close_below_anchor_low = np.full(len(frame), np.nan, dtype=float)
    d_reclaim_anchor_low = np.full(len(frame), np.nan, dtype=float)
    anchor_d_low_vs_low = np.full(len(frame), np.nan, dtype=float)
    for i in np.flatnonzero(has_anchor):
        anchor_intact[i] = float(anchor_break_at[int(anchor_idx[i])] > i)
        anchor = int(anchor_idx[i])
        if anchor_first_unknown_at[anchor] <= i and anchor_break_at[anchor] > i:
            anchor_intact[i] = np.nan
        recent_close = c.iloc[max(anchor + 1, i - 5):i].to_numpy(dtype=float)
        if np.any(recent_close < low.iloc[anchor]):
            anchor_recent_break5[i] = 1.0
        elif np.isfinite(recent_close).all():
            anchor_recent_break5[i] = 0.0
        d_low, d_close, a_low = low.iloc[i], c.iloc[i], low.iloc[anchor]
        if np.isfinite(d_low) and np.isfinite(d_close) and np.isfinite(a_low) and a_low > 0:
            anchor_d_low_vs_low[i] = (d_low / a_low - 1.0) * 100.0
            d_intraday_probe_recovered[i] = float(d_low <= a_low and d_close > a_low)
            d_low_held_above_anchor[i] = float(d_low > a_low)
            d_close_below_anchor_low[i] = float(d_close < a_low)
            if i > 0 and np.isfinite(c.iloc[i - 1]):
                d_reclaim_anchor_low[i] = float(c.iloc[i - 1] <= a_low and d_close > a_low)
    close_vs_anchor_low = (c.to_numpy() / anchor_low - 1.0) * 100.0
    close_vs_anchor_mid = (c.to_numpy() / anchor_mid - 1.0) * 100.0
    low_vol_ratio = vr5.to_numpy(dtype=float)
    prior_consol = np.zeros(len(frame), dtype=float)
    for i in np.flatnonzero(has_anchor):
        anchor = anchor_idx[i]
        gap_bars = i - anchor - 1
        if gap_bars >= 2:
            # Inspect only the intervening bars [anchor + 1, D). A known quiet
            # bar proves consolidation even if another intervening ratio is
            # missing; otherwise missing ratios keep the state UNKNOWN.
            prior_ratios = low_vol_ratio[anchor + 1:i]
            if np.any(np.isfinite(prior_ratios) & (prior_ratios <= 0.90)):
                prior_consol[i] = 1.0
            elif np.isfinite(prior_ratios).all():
                prior_consol[i] = 0.0
            else:
                prior_consol[i] = np.nan

    prior10 = h.shift(1).rolling(10, min_periods=1).max()
    prior20 = h.shift(1).rolling(20, min_periods=1).max()
    break10 = c.gt(prior10).astype(float)
    break20 = c.gt(prior20).astype(float)
    c_vs_yellow = ((c / yellow - 1.0) * 100.0).where(yellow.gt(0.0))
    c_vs_white = ((c / white - 1.0) * 100.0).where(white.gt(0.0))
    c_vs_bbi = ((c / bbi - 1.0) * 100.0).where(bbi.gt(0.0))
    l_vs_yellow = ((low / yellow - 1.0) * 100.0).where(yellow.gt(0.0))
    wy_spread = ((white / yellow - 1.0) * 100.0).where(yellow.gt(0.0))
    d_up_shadow = (h - pd.concat([o, c], axis=1).max(axis=1)) / prev_c * 100.0
    d_vr5 = vr5
    g1_known = white.notna() & yellow.notna()
    g1_pass = (white.gt(yellow) & g1_known).astype(float).where(g1_known, np.nan)
    g2_known = c_vs_yellow.notna() & d_up_shadow.notna() & d_vr5.notna() & dd_peak.notna() & amp.notna()
    g2_reject_bool = (
        c_vs_yellow.ge(35.0)
        | (c_vs_yellow.ge(25.0) & d_up_shadow.ge(4.0) & d_vr5.ge(1.5))
        | (dd_peak.le(-22.0) & amp.ge(8.0))
    )
    g2_reject = g2_reject_bool.astype(float).where(g2_known, np.nan)
    gate_known = g1_known & g2_known
    gate_pass = pd.Series(np.full(len(frame), np.nan), index=frame.index)
    gate_pass.loc[gate_known] = (g1_pass.eq(1.0) & g2_reject.eq(0.0)).loc[gate_known].astype(float)
    gate_reasons: list[str] = []
    y_at_d = c.lt(yellow).where(yellow.notna() & c.notna(), np.nan).astype(float)
    w_below = c.lt(white).where(white.notna() & c.notna(), np.nan).astype(float)
    w_below_days15 = w_below.rolling(15, min_periods=1).sum()
    w_below_run = pd.Series(np.full(len(frame), np.nan), index=frame.index)
    for i in range(len(frame)):
        run = 0
        for value in reversed(w_below.iloc[max(0, i - 14):i + 1].tolist()):
            if pd.isna(value):
                break
            if value != 1.0:
                w_below_run.iloc[i] = float(run)
                break
            run += 1
        else:
            w_below_run.iloc[i] = float(run)
        if run and pd.isna(w_below_run.iloc[i]):
            w_below_run.iloc[i] = float(run)
    for i in range(len(frame)):
        reasons: list[str] = []
        if not g1_known.iloc[i]:
            reasons.append("G1_INPUT_UNKNOWN")
        elif g1_pass.iloc[i] != 1.0:
            reasons.append("G1_WHITE_NOT_ABOVE_YELLOW")
        if not g2_known.iloc[i]:
            reasons.append("G2_INPUT_UNKNOWN")
        elif g2_reject.iloc[i] == 1.0:
            if c_vs_yellow.iloc[i] >= 35.0:
                reasons.append("G2_CLOSE_YELLOW_GE_35")
            if c_vs_yellow.iloc[i] >= 25.0 and d_up_shadow.iloc[i] >= 4.0 and d_vr5.iloc[i] >= 1.5:
                reasons.append("G2_DISTRIBUTION_GE_25")
            if dd_peak.iloc[i] <= -22.0 and amp.iloc[i] >= 8.0:
                reasons.append("G2_DRAWDOWN_RANGE")
        if not reasons:
            reasons.append("PASS")
        gate_reasons.append("|".join(reasons))
    # Keep the R2 feature's original 40-row window semantics (D may itself be
    # a surge); anchor and support features above remain strictly prior-D.
    repaired_values = repaired.to_numpy(dtype=float)
    features = pd.DataFrame({
        "wy_spread_pct": wy_spread,
        "c_vs_white_pct": c_vs_white,
        "c_vs_yellow_pct": c_vs_yellow,
        "c_vs_bbi_pct": c_vs_bbi,
        "l_vs_yellow_pct": l_vs_yellow,
        "y_consec2_active_5b": yellow_active5,
        "y_below_at_d": y_at_d,
        "repaired_prior_y_break": repaired_values,
        "w_below_consec_at_d": w_below_run,
        "recent_anchor_low_intact": anchor_intact,
        "c_vs_recent_anchor_low_pct": close_vs_anchor_low,
        "d_low_vs_recent_anchor_low_pct": anchor_d_low_vs_low,
        "c_vs_recent_anchor_mid_pct": close_vs_anchor_mid,
        "has_prior_surge_40b": has_surge_any,
        "pb_vol_contraction_score": np.clip((1.0 - d_vr5.fillna(1.5)) / 0.6, 0.0, 1.0) * (bars_since_peak.ge(2)).astype(float),
        "pb_narrow_amp_score": np.clip((5.5 - amp.fillna(5.5)) / 4.0, 0.0, 1.0) * (ret.between(-3.0, 2.0)).astype(float),
        "pb_support_hold_score": (
            (y_at_d.eq(0.0) & yellow_active5.eq(0.0)).astype(float)
            * np.where(anchor_intact == 1.0, 1.0, np.where(has_anchor, 0.3, 0.3))
            * low_slope.ge(-3.5).astype(float)
        ),
        "pb_affinity": np.nan,
        "ra_breakout_vol_score": np.nan,
        "ra_prior_consol_score": np.nan,
        "ra_affinity": np.nan,
        "max_branch_affinity": np.nan,
        "dd_from_pk30_pct": dd_peak,
        "pos_in_60bar_pct": pos60,
        "last5_low_slope_pct": low_slope,
        "red_green_vol_ratio_10b": red_green,
        "brk_prev10_high": break10,
        "brk_prev20_high": break20,
    }, index=frame.index)
    pb_affinity = (
        0.4 * features["pb_vol_contraction_score"]
        + 0.3 * features["pb_narrow_amp_score"]
        + 0.3 * features["pb_support_hold_score"]
    ) * has_anchor.astype(float)
    ra_vol = (
        (ret.ge(2.5) & d_vr5.ge(1.25)).astype(float)
        * np.where((break10.eq(1.0) | break20.eq(1.0)), 1.0, 0.4)
        * (y_at_d.eq(0.0) & yellow_active5.eq(0.0)).astype(float)
    )
    ra_consol = pd.Series(prior_consol, index=frame.index) * np.where(
        (anchor_intact == 1.0) | (repaired_values == 1.0), 1.0, 0.2,
    )
    ra_affinity = (0.55 * ra_vol + 0.45 * ra_consol).where(ra_vol.gt(0.0), 0.0)
    features["pb_affinity"] = pb_affinity
    features["ra_breakout_vol_score"] = ra_vol
    features["ra_prior_consol_score"] = ra_consol
    features["ra_affinity"] = ra_affinity
    features["max_branch_affinity"] = pd.concat([pb_affinity, ra_affinity], axis=1).max(axis=1)

    evidence = pd.DataFrame({
        "d_ret_pct": ret,
        "d_amp_pct": amp,
        "d_vr5": d_vr5,
        "d_upper_shadow_pct": d_up_shadow,
        "bars_since_pk30": bars_since_peak,
        "y_consec2_break_15b": _tri_window(c, yellow, 14),
        "no_old_yellow_break_26b": no_old_break26,
        "prior_anchor_date": [frame.trade_date.iloc[int(a)] if a >= 0 else "" for a in anchor_idx],
        "prior_anchor_low": anchor_low,
        "prior_anchor_mid": anchor_mid,
        "prior_anchor_return_pct": anchor_ret,
        "prior_anchor_relative_volume": anchor_vr5,
        "prior_anchor_intact": anchor_intact,
        "prior_consolidation": prior_consol,
        "prior_anchor_recent_break_5b": anchor_recent_break5,
        "prior_anchor_d_low_vs_low_pct": anchor_d_low_vs_low,
        "d_intraday_probe_recovered": d_intraday_probe_recovered,
        "d_low_held_above_anchor": d_low_held_above_anchor,
        "d_close_below_anchor_low": d_close_below_anchor_low,
        "d_reclaim_anchor_low": d_reclaim_anchor_low,
        "w_below_days_15b": w_below_days15,
        "history_rows_available": idx + 1,
    }, index=frame.index)
    gates = pd.DataFrame({
        "g1_wy_pass": g1_pass,
        "g2_s26_reject": g2_reject,
        "gate_pass": gate_pass,
        "gate_reasons": gate_reasons,
    }, index=frame.index)
    result = pd.concat([features.loc[:, FEATURES], gates, evidence], axis=1)
    result.insert(0, "trade_date", frame["trade_date"].astype(str).str.replace(r"\.0$", "", regex=True))
    result.insert(1, "_close", c)
    result.insert(2, "_volume", v)
    return result


def weak_label_strata(row: pd.Series | dict[str, Any]) -> list[tuple[str, str]]:
    """Return deterministic <=D candidate strata as (label, subtype)."""
    get = row.get
    def number(name: str) -> float | None:
        value = get(name)
        try:
            number_value = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number_value if np.isfinite(number_value) else None

    g1, g2, gate = number("g1_wy_pass"), number("g2_s26_reject"), number("gate_pass")
    ret, amp, vr5 = (number(name) for name in ("d_ret_pct", "d_amp_pct", "d_vr5"))
    active, below_d, repaired = (number(name) for name in ("y_consec2_active_5b", "y_below_at_d", "repaired_prior_y_break"))
    yellow15, no_old = number("y_consec2_break_15b"), number("no_old_yellow_break_26b")
    anchor, anchor_intact = number("has_prior_surge_40b"), number("recent_anchor_low_intact")
    c_white, c_anchor_low, slope = (number(name) for name in ("c_vs_white_pct", "c_vs_recent_anchor_low_pct", "last5_low_slope_pct"))
    prior_consol = number("prior_consolidation")
    break10, break20 = (number(name) for name in ("brk_prev10_high", "brk_prev20_high"))
    if g1 is None or g2 is None or gate is None:
        return []
    g1_pass = g1 == 1.0
    gate_pass = gate == 1.0
    common = g1_pass and gate_pass and active == 0.0 and below_d == 0.0
    no_recent_yellow_break = yellow15 == 0.0
    no_old_yellow = no_old == 1.0
    hard: list[str] = []
    if g1_pass and no_old_yellow and anchor == 1.0 and anchor_intact == 0.0:
        if c_anchor_low is not None and c_anchor_low < 0.0 and c_white is not None and c_white < 0.0:
            hard.append("hard_near_anchor_broken")
    if g1_pass and no_old_yellow and anchor == 1.0 and c_anchor_low is not None and c_white is not None and slope is not None:
        if (c_anchor_low >= 0.0 and c_white < 0.0 and slope <= -3.5
                and number("prior_anchor_recent_break_5b") == 1.0
                and number("d_intraday_probe_recovered") == 1.0):
            hard.append("hard_local_reclaim_below_support")
    breakout = break10 == 1.0 or break20 == 1.0
    if g1_pass and no_old_yellow and ret is not None and vr5 is not None:
        if ret >= 2.5 and vr5 >= 1.25 and breakout and prior_consol == 0.0:
            hard.append("hard_first_breakout_no_consolidation")
    if hard:
        return [("FALSE", subtype) for subtype in hard[:1]]

    positives: list[str] = []
    if common and no_recent_yellow_break and anchor == 1.0 and anchor_intact == 1.0:
        if ret is not None and amp is not None and vr5 is not None and c_white is not None:
            if -3.0 <= ret <= 2.0 and amp <= 5.5 and vr5 <= 0.90 and c_white >= 0.0:
                positives.append("positive_pullback")
        if ret is not None and vr5 is not None and prior_consol == 1.0 and breakout:
            if ret >= 2.5 and vr5 >= 1.25:
                positives.append("positive_readvance")
    if common and repaired == 1.0 and prior_consol == 1.0 and ret is not None and vr5 is not None and breakout:
        if ret >= 2.5 and vr5 >= 1.25:
            positives.append("positive_rebuild")
    if positives:
        return [("TRUE", positives[0])]

    if (active == 1.0) or (g1 == 0.0) or (below_d == 1.0):
        return [("FALSE", "ordinary_active_yellow_or_bear_regime")]
    if g2 == 1.0:
        return [("FALSE", "ordinary_g2_distribution")]
    return []
