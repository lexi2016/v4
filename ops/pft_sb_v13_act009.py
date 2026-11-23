"""ACT-009 V1.3 research-only rebuild and B-ranker study.

Reuses the bound V4 A-share logical Reader and V1.2 causal feature/gate path.
All setup rules are formed from D and earlier observations; only frozen T+5
outcomes are used as the two train-only B-ranker labels.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Callable

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ops import pft_s_v12_full_a as v12

SCHEMA = "pft_sb_v13_act009.v1"
MODEL_SCHEMA = "pft_sb_v13_act009_b_rankers.v1"
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}
START_DATE = "20251101"
ASOF_DATE = "20261120"
TRAIN_END = "20260831"
OOS_START = "20260901"
STATS_START = "20260506"
REFERENCE_D = "20261119"
OOS_DATE_COUNT = 53
HALF_YEAR_SESSION_COUNT = 136
BOUNDARY_EPS = 1e-12
EVAL_HORIZONS = (3, 5, 10)
TOP_K = (10, 20, 50)
PREP_CALENDAR_DAYS = 120
EXPECTED_BINDING = {
    "generation_id": "4ed1e1e3ccc2f1045a83527a470f111b81d96771b105ba92e8348bf7f967b268",
    "anchor_sha256": "2ce50ea1ec19be7e7011f8326d5daba8f32f6029e33dba6022d650f862c124ec",
    "manifest_sha256": "e00b0cbffbd36a80242facc74db583845d3466ae8fe9590f7920cfc6e5b6e633",
    "asof_date": ASOF_DATE,
    "price_basis": "QFQ_ASOF",
    "volume_basis": "QFQ_EVENT_VOLUME",
}
EXPECTED_OFFICIAL_TOP200 = {
    "sha256": "5b416727adcbcd0ee31973cbf4d2ce5b1316d0b2d6993221cdd70c6c284d37d3",
    "bytes": 9126132,
    "rows": 200,
    "asof_date": "20261120",
}
B_FEATURE_NAMES = tuple(v12.FEATURE_NAMES) + (
    "s_rule_score", "pullback_candidate", "readvance_candidate", "rebuild_v13_candidate",
    "b1_candidate_feature", "b1_known_feature", "b1_bbi_above_white_feature",
    "b1_j_le_13_feature", "b2_candidate_feature", "b2_known_feature",
    "b2_bullish_feature", "b2_compacted_feature", "b3_candidate_feature",
    "b3_known_feature", "b3_bullish_feature", "b3_compacted_feature",
    "d_amp_exact", "exact_vr5", "breadth_known_feature", "activity_timing_known_feature",
    "market_breadth_up_fraction", "market_activity_fraction",
    "market_activity_prior20_median", "breadth_over_50_feature",
    "activity_over_prior20_median_feature", "timing_gate_feature",
    "exact_d_return", "exact_trailing5_return", "relative_d_return",
    "relative_trailing5_return",
)
BRANCH_FLAGS = ("pullback", "readvance", "rebuild_v13")


class Act009Error(RuntimeError):
    """Input, data-continuity, or acceptance-contract error."""


def _day(value: Any, name: str) -> str:
    return v12._day(value, name)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"UNSUPPORTED_JSON_VALUE:{type(value).__name__}")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _write_rows(path: Path, frame: Any) -> int:
    import pandas as pd
    data = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame(frame)
    data.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
    return int(len(data))


def _append_progress(path: Path, stage: str, status: str,
                     details: dict[str, Any] | None = None) -> None:
    event = {"at_utc": datetime.now(timezone.utc).isoformat(), "stage": stage,
             "status": status, "details": details or {}}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True,
                                allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _valid_trade_rows(frame: Any) -> Any:
    return (
        frame[["open", "high", "low", "close", "vol"]].notna().all(axis=1)
        & frame[["open", "high", "low", "close"]].gt(0).all(axis=1)
        & frame["vol"].gt(0)
        & frame["high"].ge(frame[["open", "close", "low"]].max(axis=1))
        & frame["low"].le(frame[["open", "close", "high"]].min(axis=1))
    )


def _attach_exact_market_features(frame: Any, market_dates: list[str]) -> tuple[Any, dict[str, Any]]:
    """Exact D/D-5 close returns, equal-weight cross-section, breadth/activity timing."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    session_by_day = {day: i for i, day in enumerate(market_dates)}
    out["_market_session"] = out["trade_date"].map(session_by_day)
    if out["_market_session"].isna().any():
        raise Act009Error("MARKET_SESSION_MAPPING_GAP")
    out["_market_session"] = out["_market_session"].astype("int32")
    valid = _valid_trade_rows(out)
    lookup = out.loc[valid].set_index(["ts_code", "_market_session"])[["close", "vol"]]
    codes = out["ts_code"].to_numpy()
    sessions = out["_market_session"].to_numpy()
    for offset, name in ((1, "exact_d_return"), (5, "exact_trailing5_return")):
        target = pd.MultiIndex.from_arrays([codes, sessions - offset],
                                           names=["ts_code", "_market_session"])
        prior = lookup.reindex(target)["close"].to_numpy(dtype=float)
        current = out["close"].to_numpy(dtype=float)
        value = current / prior - 1.0
        out[name] = np.where(valid.to_numpy() & np.isfinite(prior) & (prior > 0), value, np.nan)
    previous5_volumes = []
    for offset in range(1, 6):
        prior_index = pd.MultiIndex.from_arrays([codes, sessions - offset],
                                                names=["ts_code", "_market_session"])
        previous5_volumes.append(lookup.reindex(prior_index)["vol"].to_numpy(dtype=float))
    prior5_matrix = np.column_stack(previous5_volumes)
    complete_prior5 = np.isfinite(prior5_matrix).all(axis=1)
    exact_prior5_mean = np.divide(
        np.nansum(prior5_matrix, axis=1), 5.0,
        out=np.full(len(out), np.nan, dtype=float), where=complete_prior5)
    current_volume = out["vol"].to_numpy(dtype=float)
    exact_vr5 = current_volume / exact_prior5_mean
    out["exact_vr5"] = np.where(valid.to_numpy() & complete_prior5 & (exact_prior5_mean > 0),
                                 exact_vr5, np.nan)
    out["d_amp_exact"] = np.nan
    prev_index = pd.MultiIndex.from_arrays([codes, sessions - 1],
                                           names=["ts_code", "_market_session"])
    prior_close = lookup.reindex(prev_index)["close"].to_numpy(dtype=float)
    amplitude = (out["high"].to_numpy(dtype=float) - out["low"].to_numpy(dtype=float)) / prior_close
    out["d_amp_exact"] = np.where(valid.to_numpy() & np.isfinite(prior_close) & (prior_close > 0),
                                  amplitude, np.nan)

    daily_return = out.groupby("trade_date", sort=True)[["exact_d_return", "exact_trailing5_return"]].mean()
    out["all_a_equal_weight_d_return"] = out["trade_date"].map(daily_return["exact_d_return"])
    out["all_a_equal_weight_trailing5_return"] = out["trade_date"].map(daily_return["exact_trailing5_return"])
    out["relative_d_return"] = out["exact_d_return"] - out["all_a_equal_weight_d_return"]
    out["relative_trailing5_return"] = (
        out["exact_trailing5_return"] - out["all_a_equal_weight_trailing5_return"]
    )

    breadth_known = (out["pct_chg"].notna() & valid)
    positive = out.loc[breadth_known].assign(_up=lambda data: data["pct_chg"].gt(0))
    breadth = positive.groupby("trade_date", sort=True)["_up"].agg(["sum", "count"])
    breadth["fraction"] = breadth["sum"] / breadth["count"].replace(0, np.nan)

    vr5 = pd.to_numeric(out.get("_d_vr5"), errors="coerce")
    activity_known = valid & vr5.notna() & out["_prior5v"].gt(0)
    activity = out.loc[activity_known].assign(_active=vr5[activity_known].ge(1.0))
    activity = activity.groupby("trade_date", sort=True)["_active"].agg(["sum", "count"])
    activity["fraction"] = activity["sum"] / activity["count"].replace(0, np.nan)
    all_days = pd.Index(market_dates, name="trade_date")
    breadth_fraction = breadth["fraction"].reindex(all_days)
    activity_fraction = activity["fraction"].reindex(all_days)
    activity_median20 = activity_fraction.shift(1).rolling(20, min_periods=20).median()
    breadth_fraction.index = breadth_fraction.index.astype(str)
    activity_fraction.index = activity_fraction.index.astype(str)
    activity_median20.index = activity_median20.index.astype(str)
    out["market_breadth_up_fraction"] = out["trade_date"].map(breadth_fraction)
    out["market_breadth_denominator"] = out["trade_date"].map(breadth["count"])
    out["market_activity_fraction"] = out["trade_date"].map(activity_fraction)
    out["market_activity_denominator"] = out["trade_date"].map(activity["count"])
    out["market_activity_prior20_median"] = out["trade_date"].map(activity_median20)
    out["breadth_known"] = out["market_breadth_up_fraction"].notna()
    out["activity_timing_known"] = out["market_activity_fraction"].notna() & out["market_activity_prior20_median"].notna()
    out["breadth_over_50"] = out["market_breadth_up_fraction"].gt(0.5)
    out["activity_over_prior20_median"] = out["market_activity_fraction"].gt(
        out["market_activity_prior20_median"])
    out["timing_gate"] = (out["breadth_known"] & out["activity_timing_known"]
                          & out["breadth_over_50"] & out["activity_over_prior20_median"])
    return out, {"relative_d_return": "exact market-session D close / D-1 close minus same-D all-A EW mean",
                 "relative_trailing5_return": "exact D close / D-5 market-session close minus same-D all-A EW mean",
                 "breadth": "pct_chg positive among valid traded rows",
                 "activity": "valid current D V1.2 VR5 >= 1 fraction",
                 "timing": "breadth > 50% AND activity > previous 20 exact market-session median, shifted 1"}


def _derive_rebuild_v13(frame: Any, market_dates: list[str]) -> tuple[Any, dict[str, Any]]:
    """Find one first eligible consolidation signal per repaired below-Y episode."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    out["_act009_row_position"] = np.arange(len(out), dtype=np.int64)
    session_by_day = {day: i for i, day in enumerate(market_dates)}
    session = out["trade_date"].map(session_by_day)
    if session.isna().any():
        raise Act009Error("MARKET_SESSION_MAPPING_GAP_FOR_REBUILD")
    sid_all = session.to_numpy(dtype=np.int32)
    valid_trade = _valid_trade_rows(out)
    lines_valid = (out["zge_white_line"].notna() & out["zge_yellow_line"].notna()
                   & out["zge_white_line"].gt(0) & out["zge_yellow_line"].gt(0))
    valid_lines = valid_trade & lines_valid
    below_all = (valid_lines & out["close"].lt(out["zge_yellow_line"])).to_numpy(dtype=bool)
    above_all = (valid_lines & out["close"].gt(out["zge_white_line"])
                 & out["close"].gt(out["zge_yellow_line"])).to_numpy(dtype=bool)
    vr_all = pd.to_numeric(out.get("exact_vr5"), errors="coerce").to_numpy(dtype=float)
    amp_all = pd.to_numeric(out.get("d_amp_exact"), errors="coerce").to_numpy(dtype=float)
    low_all = pd.to_numeric(out["low"], errors="coerce").to_numpy(dtype=float)
    close_all = pd.to_numeric(out["close"], errors="coerce").to_numpy(dtype=float)
    eligible_all = out["rebuild"].fillna(False).to_numpy(dtype=bool)
    valid_all = valid_trade.to_numpy(dtype=bool)
    days_all = out["trade_date"].astype(str).to_numpy()
    codes_all = out["ts_code"].astype(str).to_numpy()
    n = len(out)
    rebuild = np.zeros(n, dtype=bool)
    state = np.full(n, "CANNOT_CONFIRM_NO_REPAIR_WINDOW", dtype=object)
    episode_ids = np.full(n, "", dtype=object)
    break_start = np.full(n, "", dtype=object)
    break_end = np.full(n, "", dtype=object)
    anchor_date = np.full(n, "", dtype=object)
    confirmation_date = np.full(n, "", dtype=object)
    anchor_low = np.full(n, np.nan, dtype=float)
    consolidation_sessions = np.full(n, np.nan, dtype=float)

    for _code, group in out.groupby("ts_code", sort=False):
        positions = group["_act009_row_position"].to_numpy(dtype=int)
        if len(positions) < 6:
            continue
        sid = sid_all[positions]
        below = below_all[positions]
        above = above_all[positions]
        below_ends: list[int] = []
        above_ends: list[int] = []
        for pos in range(1, len(positions)):
            adjacent = sid[pos] == sid[pos - 1] + 1
            if adjacent and below[pos] and below[pos - 1]:
                below_ends.append(pos)
            if adjacent and above[pos] and above[pos - 1]:
                above_ends.append(pos)
        if not below_ends or not above_ends:
            continue

        # Consecutive pair endpoints within one below run describe one collapse episode.
        episodes: list[dict[str, int]] = []
        for end_pos in below_ends:
            if episodes and sid[end_pos] == sid[episodes[-1]["last_end"]] + 1:
                episodes[-1]["last_end"] = end_pos
            else:
                episodes.append({"first_end": end_pos, "last_end": end_pos})

        for episode_index, episode in enumerate(episodes):
            collapse_end = episode["last_end"]
            # Keep the earlier repair active through the first below-Y D. The
            # next episode begins only when its second below-Y bar confirms the pair.
            next_collapse_start = (episodes[episode_index + 1]["first_end"]
                                   if episode_index + 1 < len(episodes) else len(positions))
            repair_end = next((pos for pos in above_ends
                               if pos > collapse_end and pos < next_collapse_start), None)
            if repair_end is None:
                continue
            repair_row = positions[repair_end]
            key_low = low_all[repair_row]
            if not math.isfinite(key_low) or key_low <= 0:
                continue
            event_id = (f"{_code}|YPAIR|{days_all[positions[episode['first_end'] - 1]]}|"
                        f"{days_all[positions[collapse_end]]}")
            streak = 0
            previous_sid = sid[repair_end]
            first_confirmation = ""
            for pos in range(repair_end + 1, next_collapse_start):
                row_position = positions[pos]
                if sid[pos] != previous_sid + 1:
                    state[row_position] = "CONTINUITY_BROKEN_MISSING_MARKET_SESSION"
                    episode_ids[row_position] = event_id
                    break_start[row_position] = days_all[positions[episode["first_end"] - 1]]
                    break_end[row_position] = days_all[positions[collapse_end]]
                    anchor_date[row_position] = days_all[repair_row]
                    anchor_low[row_position] = key_low
                    break
                previous_sid = sid[pos]
                if not valid_all[row_position]:
                    state[row_position] = "CONTINUITY_BROKEN_INVALID_TRADE"
                    episode_ids[row_position] = event_id
                    break_start[row_position] = days_all[positions[episode["first_end"] - 1]]
                    break_end[row_position] = days_all[positions[collapse_end]]
                    anchor_date[row_position] = days_all[repair_row]
                    anchor_low[row_position] = key_low
                    break
                if low_all[row_position] < key_low:
                    state[row_position] = "CONTINUITY_BROKEN_ANCHOR_LOW_LOST"
                    episode_ids[row_position] = event_id
                    break_start[row_position] = days_all[positions[episode["first_end"] - 1]]
                    break_end[row_position] = days_all[positions[collapse_end]]
                    anchor_date[row_position] = days_all[repair_row]
                    anchor_low[row_position] = key_low
                    break

                vr_known = math.isfinite(vr_all[row_position]) and vr_all[row_position] >= 0
                amp_known = math.isfinite(amp_all[row_position]) and amp_all[row_position] >= 0
                condition = ((vr_known and vr_all[row_position] < 1.0)
                             or (amp_known and amp_all[row_position] <= 0.05 + BOUNDARY_EPS))
                streak = streak + 1 if condition else 0
                episode_ids[row_position] = event_id
                break_start[row_position] = days_all[positions[episode["first_end"] - 1]]
                break_end[row_position] = days_all[positions[collapse_end]]
                anchor_date[row_position] = days_all[repair_row]
                anchor_low[row_position] = key_low
                consolidation_sessions[row_position] = streak
                if first_confirmation:
                    confirmation_date[row_position] = first_confirmation
                    state[row_position] = "REBUILD_EPISODE_CONFIRMED_ACTIVE"
                elif streak >= 3:
                    state[row_position] = "CONSOLIDATION_CONFIRMED_AWAITING_ELIGIBLE_D"
                    if eligible_all[row_position]:
                        rebuild[row_position] = True
                        first_confirmation = days_all[row_position]
                        confirmation_date[row_position] = first_confirmation
                        state[row_position] = "CONFIRMED_FIRST_ELIGIBLE_D"
                else:
                    state[row_position] = "PENDING_THREE_SESSION_CONSOLIDATION"

    out.drop(columns=["_act009_row_position"], inplace=True)
    out["_valid_repair_bar"] = valid_lines.to_numpy(dtype=bool)
    out["_below_yellow"] = below_all
    out["_above_both"] = above_all
    out["rebuild_v13"] = rebuild
    out["rebuild_state"] = state
    out["rebuild_episode_id"] = episode_ids
    out["rebuild_break_pair_start_date"] = break_start
    out["rebuild_break_pair_end_date"] = break_end
    out["rebuild_anchor_date"] = anchor_date
    out["rebuild_confirmation_date"] = confirmation_date
    out["rebuild_anchor_low"] = anchor_low
    out["rebuild_consolidation_sessions"] = consolidation_sessions
    out["v13_candidate_union"] = out["pullback"].fillna(False).astype(bool) | out[
        "readvance"].fillna(False).astype(bool) | out["rebuild_v13"]
    return out, {"rebuild_definition": "first valid above-W-and-Y pair after a below-Y pair run; second bar is K; first eligible D after three consecutive exact valid post-K sessions with each VR5 < 1 or amplitude <= 5%, while every low >= K low",
                 "rebuild_vr5_amp_basis": "exact market-session VR5 from five prior valid sessions; exact D-1 close amplitude",
                 "postrepair_missing_or_invalid_policy": "missing session, invalid trade row, or K-low breach ends the repair episode; no forward fill",
                 "v13_rebuild_candidates_are_subset_of_v12_rebuild_on_D": True,
                 "one_confirmation_per_repair_episode": True,
                 "active_episode_id_persists_after_first_confirmation": True,
                 "rebuild_v13_count": int(rebuild.sum())}


def _apply_s_rule(frame: Any) -> tuple[Any, dict[str, Any]]:
    """Percentile-normalize V1.2 branch scores by D, then take the strongest branch."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    score_columns = {
        "pullback": "hard_score_pullback",
        "readvance": "hard_score_readvance",
        "rebuild_v13": "hard_score_rebuild",
    }
    percentile_columns = []
    for branch, raw_column in score_columns.items():
        percentile_column = f"s_{branch}_percentile"
        percentile_columns.append(percentile_column)
        score = pd.to_numeric(out[raw_column], errors="coerce")
        candidate = out[branch].fillna(False).astype(bool) & np.isfinite(score)
        out[percentile_column] = np.nan
        if candidate.any():
            ranks = score.loc[candidate].groupby(out.loc[candidate, "trade_date"], sort=False).rank(
                pct=True, method="average")
            out.loc[ranks.index, percentile_column] = ranks.astype(float)
    normalized = out[percentile_columns]
    out["s_rule_score"] = normalized.max(axis=1, skipna=True)
    out["s_rule_branch"] = ""
    has_score = out["v13_candidate_union"].fillna(False).astype(bool) & normalized.notna().any(axis=1)
    if has_score.any():
        # DataFrame.idxmax keeps the declared pullback/readvance/rebuild order on a score tie.
        winner_columns = normalized.loc[has_score].idxmax(axis=1)
        winner = winner_columns.map({column: branch for branch, column in zip(
            score_columns, percentile_columns)})
        out.loc[winner.index, "s_rule_branch"] = winner
    out["s_rule_rank"] = np.nan
    for _day, group in out.loc[out["v13_candidate_union"].fillna(False)].groupby("trade_date", sort=True):
        ranked = group.loc[group["s_rule_score"].notna()].sort_values(
            ["s_rule_score", "ts_code"], ascending=[False, True], kind="mergesort")
        if len(ranked):
            out.loc[ranked.index, "s_rule_rank"] = np.arange(1, len(ranked) + 1, dtype=int)
    return out, {"hard_scores": score_columns,
                 "normalization": "within D and branch candidate pool, ascending percentile rank",
                 "combined_score": "maximum available branch percentile",
                 "tie_order": ["s_rule_score desc", "ts_code asc"],
                 "score_missing_union_rows": int((out["v13_candidate_union"]
                     & out["s_rule_rank"].isna()).sum())}


def _add_b_confirmations(frame: Any) -> tuple[Any, dict[str, Any]]:
    """Add B1/B2/B3 confirmations and explicit known/unknown states, using D-only data."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    valid = _valid_trade_rows(out)
    numeric = {}
    for name in ("open", "close", "bbi", "j", "zge_white_line", "zge_yellow_line",
                 "d_vr5", "d_amp_exact", "prior5_vol_vs_prior15", "prior5_range_vs_prior15",
                 "close_vs_prior10_high", "close_vs_prior20_high"):
        numeric[name] = pd.to_numeric(out[name], errors="coerce")
    compact_known = (np.isfinite(numeric["prior5_vol_vs_prior15"])
                     & np.isfinite(numeric["prior5_range_vs_prior15"]))
    compact = (numeric["prior5_vol_vs_prior15"].le(1.0)
               & numeric["prior5_range_vs_prior15"].le(1.0))
    bullish_known = valid
    bullish = numeric["close"].gt(numeric["open"])

    b1_known = (valid & numeric["bbi"].gt(0) & numeric["zge_white_line"].gt(0)
                & numeric["zge_yellow_line"].gt(0) & numeric["j"].notna()
                & numeric["d_vr5"].notna() & numeric["d_amp_exact"].notna())
    b1 = (numeric["bbi"].gt(numeric["zge_white_line"])
          & numeric["zge_white_line"].gt(numeric["zge_yellow_line"])
          & numeric["j"].le(13.0) & numeric["d_vr5"].lt(1.0)
          & numeric["d_amp_exact"].le(0.05 + BOUNDARY_EPS))
    b2_known = (valid & compact_known & numeric["close_vs_prior10_high"].notna()
                & numeric["d_vr5"].notna())
    b2 = (bullish & compact & numeric["close_vs_prior10_high"].gt(0.0)
          & numeric["d_vr5"].ge(1.2))
    b3_known = (valid & compact_known & numeric["close_vs_prior20_high"].notna()
                & numeric["d_vr5"].notna())
    b3 = (bullish & compact & numeric["close_vs_prior20_high"].gt(0.0)
          & numeric["d_vr5"].ge(1.5))
    for name, known, condition in (("b1", b1_known, b1), ("b2", b2_known, b2), ("b3", b3_known, b3)):
        out[f"{name}_known"] = known.astype(bool)
        out[f"{name}_candidate"] = (known & condition).astype(bool)
        out[f"{name}_state"] = np.where(~known, "UNKNOWN", np.where(condition, "YES", "NO"))
        out[f"{name}_candidate_feature"] = np.where(known, condition.astype(float), np.nan)
        out[f"{name}_known_feature"] = known.astype(float)
    out["b1_bbi_above_white_feature"] = np.where(
        b1_known, numeric["bbi"].gt(numeric["zge_white_line"]).astype(float), np.nan)
    out["b1_j_le_13_feature"] = np.where(b1_known, numeric["j"].le(13.0).astype(float), np.nan)
    out["b2_bullish_feature"] = np.where(bullish_known, bullish.astype(float), np.nan)
    out["b3_bullish_feature"] = np.where(bullish_known, bullish.astype(float), np.nan)
    out["b2_compacted_feature"] = np.where(compact_known, compact.astype(float), np.nan)
    out["b3_compacted_feature"] = np.where(compact_known, compact.astype(float), np.nan)

    any_confirmed = out[["b1_candidate", "b2_candidate", "b3_candidate"]].any(axis=1)
    all_known = out[["b1_known", "b2_known", "b3_known"]].all(axis=1)
    out["b_confirmed"] = pd.Series(
        np.where(any_confirmed, True, np.where(all_known, False, np.nan)), index=out.index, dtype="object")
    out["b_confirmed_state"] = np.where(any_confirmed, "CONFIRMED",
                                        np.where(all_known, "UNCONFIRMED", "UNKNOWN"))
    out["b_confirmed_feature"] = np.where(any_confirmed, 1.0,
                                          np.where(all_known, 0.0, np.nan))
    for source, target in (("pullback", "pullback_candidate"),
                           ("readvance", "readvance_candidate"),
                           ("rebuild_v13", "rebuild_v13_candidate")):
        out[target] = out[source].fillna(False).astype(float)
    category = np.full(len(out), "UNKNOWN", dtype=object)
    category[all_known.to_numpy()] = "NONE"
    category[out["b1_candidate"].to_numpy()] = "B1"
    category[out["b2_candidate"].to_numpy()] = "B2"
    category[out["b3_candidate"].to_numpy()] = "B3"
    out["b_category"] = category  # B3 has explicit highest priority on overlap.
    for column in ("breadth_known", "activity_timing_known", "breadth_over_50",
                   "activity_over_prior20_median", "timing_gate"):
        out[f"{column}_feature"] = out[column].map({True: 1.0, False: 0.0}).astype(float)
    return out, {"b1": "BBI > W > Y AND J <= 13 AND V1.2 VR5 < 1 AND exact D amplitude <= 5%",
                 "b2": "bullish D AND prior-5 volume/range both compact versus preceding 15 AND close > prior-10 high AND V1.2 VR5 >= 1.2",
                 "b3": "bullish D AND prior-5 volume/range both compact versus preceding 15 AND close > prior-20 high AND V1.2 VR5 >= 1.5",
                 "overlap_priority": ["B3", "B2", "B1"],
                 "unknown_policy": "retain UNKNOWN when required D inputs are missing; do not coerce unknown to negative",
                 "b1_unknown_rows": int((~b1_known).sum()),
                 "b2_unknown_rows": int((~b2_known).sum()),
                 "b3_unknown_rows": int((~b3_known).sum())}


def _add_b_training_labels(frame: Any, market_dates: list[str]) -> tuple[Any, dict[str, Any]]:
    """Label only exact, complete T+5 paths matured by the frozen TRAIN cutoff."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    date_to_session = {day: index for index, day in enumerate(market_dates)}
    session = out["trade_date"].map(date_to_session)
    if session.isna().any():
        raise Act009Error("MARKET_SESSION_MAPPING_GAP_FOR_B_LABEL")
    session_values = session.to_numpy(dtype=int)
    target_index = session_values + 5
    target_dates = np.full(len(out), "", dtype=object)
    available = target_index < len(market_dates)
    target_dates[available] = np.asarray(market_dates, dtype=object)[target_index[available]]
    out["b_target_t5_date"] = target_dates
    ret5 = pd.to_numeric(out["return_t5"], errors="coerce")
    dd5 = pd.to_numeric(out["min_path_dd_t5"], errors="coerce")
    path = out["path_observable_t5"].fillna(False).astype(bool)
    train_d = out["trade_date"].between(START_DATE, TRAIN_END)
    mature = pd.Series(target_dates, index=out.index).ne("") & pd.Series(target_dates, index=out.index).le(TRAIN_END)
    target_known = (out["v13_candidate_union"].fillna(False).astype(bool) & train_d & mature & path
                    & np.isfinite(ret5) & np.isfinite(dd5))
    out["b_training_target"] = np.nan
    labels = ((ret5.ge(0.03)) & (dd5.ge(-0.05))).astype(float)
    out.loc[target_known, "b_training_target"] = labels.loc[target_known]
    return out, {"target": "exact T+5 close return >= 3% AND complete D-to-T+5 close-path MDD >= -5%",
                 "trainer_D_window": [START_DATE, TRAIN_END],
                 "latest_mature_target_date": TRAIN_END,
                 "eligible_labeled_rows": int(target_known.sum()),
                 "positive_rows": int(out.loc[target_known, "b_training_target"].sum()),
                 "negative_rows": int(target_known.sum() - out.loc[target_known, "b_training_target"].sum()),
                 "unknown_or_censored_training_candidates": int((out["v13_candidate_union"]
                     & train_d & ~target_known).sum())}


def _episode_split(frame: Any) -> tuple[Any, dict[str, Any]]:
    """Purge train groups that share canonical V1.2 K or V1.3 repair episodes with OOS."""
    import pandas as pd

    out = frame.copy()
    anchor = out.get("_anchor_date", pd.Series("", index=out.index)).fillna("").astype(str)
    out["_canonical_k_group"] = ""
    has_anchor = anchor.ne("")
    out.loc[has_anchor, "_canonical_k_group"] = (
        out.loc[has_anchor, "ts_code"].astype(str) + "|K|" + anchor.loc[has_anchor])
    repair = out.get("rebuild_episode_id", pd.Series("", index=out.index)).fillna("").astype(str)
    out["_repair_episode_group"] = repair
    train = out["b_training_target"].notna()
    oos = (out["v13_candidate_union"].fillna(False).astype(bool)
           & out["trade_date"].between(OOS_START, ASOF_DATE))
    cross_k = (set(out.loc[train & out["_canonical_k_group"].ne(""), "_canonical_k_group"])
               & set(out.loc[oos & out["_canonical_k_group"].ne(""), "_canonical_k_group"]))
    cross_repair = (set(out.loc[train & out["_repair_episode_group"].ne(""), "_repair_episode_group"])
                    & set(out.loc[oos & out["_repair_episode_group"].ne(""), "_repair_episode_group"]))
    purge = (train & (out["_canonical_k_group"].isin(cross_k)
                      | out["_repair_episode_group"].isin(cross_repair)))
    train_keep = train & ~purge
    remain_k = (set(out.loc[train_keep & out["_canonical_k_group"].ne(""), "_canonical_k_group"])
                & set(out.loc[oos & out["_canonical_k_group"].ne(""), "_canonical_k_group"]))
    remain_repair = (set(out.loc[train_keep & out["_repair_episode_group"].ne(""), "_repair_episode_group"])
                     & set(out.loc[oos & out["_repair_episode_group"].ne(""), "_repair_episode_group"]))
    if remain_k or remain_repair:
        raise Act009Error("TRAIN_OOS_GROUP_OVERLAP_AFTER_PURGE")
    return out, {"train_labeled_before_purge": int(train.sum()),
                 "train_labeled_after_purge": int(train_keep.sum()),
                 "train_rows_purged": int(purge.sum()),
                 "oos_candidate_rows": int(oos.sum()),
                 "cross_split_canonical_k_groups": len(cross_k),
                 "cross_split_repair_episode_groups": len(cross_repair),
                 "post_purge_canonical_k_overlap": len(remain_k),
                 "post_purge_repair_episode_overlap": len(remain_repair),
                 "train_mask": train_keep, "oos_mask": oos}


def _build_b_estimators() -> dict[str, Any]:
    """Fixed two-estimator B policy; all imputation/scaling fit inside TRAIN-only LR pipeline."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    lr = Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("scale", StandardScaler()),
        ("classifier", LogisticRegression(C=1.0, penalty="l2", solver="lbfgs",
                                           class_weight="balanced", random_state=0,
                                           max_iter=1000, tol=1e-8)),
    ])
    hgb = HistGradientBoostingClassifier(max_iter=100, learning_rate=0.05,
                                         max_leaf_nodes=7, max_depth=3,
                                         l2_regularization=1.0,
                                         early_stopping=False, random_state=0)
    return {"b_lr": lr, "b_hgb": hgb}


def _save_model_state(path: Path, models: dict[str, Any], report: dict[str, Any],
                      panel_source: dict[str, Any], official_meta: dict[str, Any]) -> None:
    import joblib

    payload = {"schema": MODEL_SCHEMA, "models": models,
               "feature_names": list(B_FEATURE_NAMES), "fit_report": report,
               "panel_source": panel_source, "official_top200_source": official_meta,
               **FLAGS}
    temporary = path.with_name(path.name + ".tmp")
    joblib.dump(payload, temporary, compress=3)
    temporary.replace(path)


def _fit_b_rankers(frame: Any, split: dict[str, Any], *,
                   panel_source: dict[str, Any], official_meta: dict[str, Any],
                   checkpoint_path: Path | None = None,
                   progress: Callable[[str, str, dict[str, Any] | None], None] | None = None
                   ) -> tuple[dict[str, Any], dict[str, Any], Any]:
    """Fit exactly LR and HGB once on purged TRAIN candidates; predict only fixed OOS candidates."""
    import numpy as np
    import pandas as pd
    import sklearn

    train_mask = split["train_mask"]
    oos_mask = split["oos_mask"]
    y = frame.loc[train_mask, "b_training_target"].astype(int).to_numpy()
    if not len(y):
        raise Act009Error("B_TRAIN_EMPTY_AFTER_GROUP_PURGE")
    if len(np.unique(y)) != 2:
        raise Act009Error("B_TRAIN_TARGET_REQUIRES_BOTH_CLASSES")
    x_train = frame.loc[train_mask, list(B_FEATURE_NAMES)].apply(pd.to_numeric, errors="coerce")
    x_train = x_train.replace([np.inf, -np.inf], np.nan).to_numpy(dtype=float)
    x_oos = frame.loc[oos_mask, list(B_FEATURE_NAMES)].apply(pd.to_numeric, errors="coerce")
    x_oos = x_oos.replace([np.inf, -np.inf], np.nan).to_numpy(dtype=float)
    weights = np.where(y == 1, len(y) / (2.0 * y.sum()),
                       len(y) / (2.0 * (len(y) - y.sum())))
    models = _build_b_estimators()
    report: dict[str, Any] = {
        "schema": MODEL_SCHEMA, "feature_names": list(B_FEATURE_NAMES),
        "sklearn_version": sklearn.__version__, "fit_count": 0,
        "S_fit_count": 0, "B_fit_count": 0, "hyperparameter_search_count": 0,
        "training": {"n": int(len(y)), "positive": int(y.sum()),
                     "negative": int(len(y) - y.sum()), "positive_fraction": float(y.mean())},
        "split_guard": {key: value for key, value in split.items() if not key.endswith("mask")},
        "target_contract": "exact T+5 return >= 0.03 AND complete close-path MDD >= -0.05; matured by 20260831",
        "fit_policy": {"total_fits": 2, "S_fits": 0, "B_fits": 2,
                       "tuning_or_search_fits": 0,
                       "lr": {"type": "LogisticRegression", "C": 1.0, "penalty": "l2",
                              "solver": "lbfgs", "class_weight": "balanced", "random_state": 0,
                              "max_iter": 1000, "tol": 1e-8,
                              "transform": "median imputer and StandardScaler fit on TRAIN only"},
                       "hgb": {"type": "HistGradientBoostingClassifier", "max_iter": 100,
                               "learning_rate": 0.05, "max_leaf_nodes": 7, "max_depth": 3,
                               "l2_regularization": 1.0, "early_stopping": False,
                               "random_state": 0, "balanced_sample_weight": True}},
    }
    predictions = pd.DataFrame(index=frame.index,
                               data={"p_b_lr": np.nan, "p_b_hgb": np.nan})
    for name, model in models.items():
        if progress:
            progress(name, "FIT_STARTED", {"fit_count": report["fit_count"],
                                             "training_rows": int(len(y)),
                                             "positive": int(y.sum())})
        if name == "b_hgb":
            model.fit(x_train, y, sample_weight=weights)
        else:
            model.fit(x_train, y)
        report["fit_count"] += 1
        report["B_fit_count"] += 1
        if checkpoint_path is not None:
            _save_model_state(checkpoint_path, models={k: models[k] for k in models
                                                       if k == name or report["fit_count"] > 1},
                              report=report, panel_source=panel_source,
                              official_meta=official_meta)
        if progress:
            progress(name, "FIT_COMPLETED_CHECKPOINTED", {
                "fit_count": report["fit_count"], "B_fit_count": report["B_fit_count"],
                "checkpoint": str(checkpoint_path) if checkpoint_path else None})
    if report["fit_count"] != 2 or report["B_fit_count"] != 2 or report["S_fit_count"] != 0:
        raise Act009Error("B_FIT_COUNT_CONTRACT_MISMATCH")
    if len(x_oos):
        for name, model in models.items():
            predictions.loc[oos_mask, f"p_{name}"] = model.predict_proba(x_oos)[:, 1]
    report["prediction_rows"] = int(oos_mask.sum())
    return models, report, predictions


def _attach_horizon_benchmarks(frame: Any) -> tuple[Any, dict[str, Any]]:
    """Build each same-D, exact-target all-active-A equal-weight benchmark."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    valid_current = _valid_trade_rows(out)
    descriptions = {}
    for horizon in EVAL_HORIZONS:
        ret_column = f"return_t{horizon}"
        benchmark_column = f"benchmark_return_t{horizon}"
        excess_column = f"excess_return_t{horizon}"
        returns = pd.to_numeric(out[ret_column], errors="coerce")
        observed = valid_current & np.isfinite(returns)
        valid_rows = out.loc[observed].assign(_target_return=returns.loc[observed])
        benchmark = valid_rows.groupby("trade_date", sort=True)["_target_return"].mean()
        benchmark_count = valid_rows.groupby("trade_date", sort=True).size()
        out[benchmark_column] = out["trade_date"].map(benchmark)
        out[f"benchmark_count_t{horizon}"] = out["trade_date"].map(benchmark_count).fillna(0).astype("int32")
        out[excess_column] = returns - out[benchmark_column]
        out[f"return_observable_t{horizon}"] = np.isfinite(returns)
        out[f"benchmark_observable_t{horizon}"] = out[benchmark_column].notna()
        descriptions[str(horizon)] = {
            "benchmark": "same-D arithmetic equal-weight mean exact T+N return among valid active A-share rows",
            "benchmark_known_dates": int(benchmark.notna().sum()),
            "valid_rows": int(observed.sum()),
        }
    return out, descriptions


def _daily_candidate_counts(frame: Any, market_dates: list[str], *,
                            stats_start: str = STATS_START) -> Any:
    """Emit one candidate-count row per exact market date, retaining empty days."""
    import numpy as np
    import pandas as pd

    dates = [day for day in market_dates if stats_start <= day <= ASOF_DATE]
    by_day = {day: group for day, group in frame.groupby("trade_date", sort=False)}
    rows = []
    boolean_columns = ("feature_ready", "model_eligible", "pullback", "readvance",
                       "rebuild", "union", "rebuild_v13", "v13_candidate_union",
                       "b1_candidate", "b2_candidate", "b3_candidate")
    for day in dates:
        group = by_day.get(day)
        row: dict[str, Any] = {"trade_date": day, "a_share_rows": int(len(group)) if group is not None else 0,
                               "research_only": True}
        for column in boolean_columns:
            row[f"{column}_count"] = int(group[column].fillna(False).astype(bool).sum()) if group is not None else 0
        if group is None:
            row.update({"b_confirmed_union_count": 0, "b_unknown_union_count": 0,
                        "s_scored_union_count": 0, "breadth_known": False,
                        "activity_known": False, "timing_gate": False,
                        "market_breadth_up_fraction": None,
                        "market_activity_fraction": None,
                        "market_activity_prior20_median": None})
        else:
            union = group["v13_candidate_union"].fillna(False).astype(bool)
            row["b_confirmed_union_count"] = int(group.loc[union, "b_confirmed_state"].eq("CONFIRMED").sum())
            row["b_unknown_union_count"] = int(group.loc[union, "b_confirmed_state"].eq("UNKNOWN").sum())
            row["s_scored_union_count"] = int((union & group["s_rule_rank"].notna()).sum())
            row["breadth_known"] = bool(group["breadth_known"].fillna(False).any())
            row["activity_known"] = bool(group["activity_timing_known"].fillna(False).any())
            row["timing_gate"] = bool(group["timing_gate"].fillna(False).any())
            for column in ("market_breadth_up_fraction", "market_activity_fraction",
                           "market_activity_prior20_median"):
                value = pd.to_numeric(group[column], errors="coerce").dropna()
                row[column] = float(value.iloc[0]) if len(value) else None
        for column in ("b1_candidate", "b2_candidate", "b3_candidate"):
            row[f"{column}_hard_union_count"] = (
                int(group.loc[group["v13_candidate_union"].fillna(False), column].fillna(False).sum())
                if group is not None else 0)
        rows.append(row)
    return pd.DataFrame(rows)


def _candidate_count_summary(counts: Any, market_dates: list[str]) -> dict[str, Any]:
    half = counts.loc[counts["trade_date"].between(STATS_START, ASOF_DATE)]
    oos = counts.loc[counts["trade_date"].between(OOS_START, ASOF_DATE)]
    half_dates = [day for day in market_dates if STATS_START <= day <= ASOF_DATE]
    oos_dates = [day for day in market_dates if OOS_START <= day <= ASOF_DATE]
    half_union = float(half["v13_candidate_union_count"].mean()) if len(half) else None
    half_rebuild = float(half["rebuild_v13_count"].mean()) if len(half) else None
    oos_pb_ra = float((oos["pullback_count"] + oos["readvance_count"]).mean()) if len(oos) else None
    return {
        "half_year": {"window": [STATS_START, ASOF_DATE], "market_sessions": len(half_dates),
                      "expected_market_sessions": HALF_YEAR_SESSION_COUNT,
                      "mean_pullback": float(half["pullback_count"].mean()) if len(half) else None,
                      "mean_readvance": float(half["readvance_count"].mean()) if len(half) else None,
                      "mean_rebuild_v13": half_rebuild, "mean_v13_union": half_union,
                      "target_union_mean_range": [20.0, 60.0],
                      "target_rebuild_mean_ceiling": 30.0,
                      "session_coverage_status": "PASS" if len(half_dates) == HALF_YEAR_SESSION_COUNT else "CANNOT_CONFIRM",
                      "candidate_target_status": ("PASS" if half_union is not None and 20 <= half_union <= 60
                                                   and half_rebuild is not None and half_rebuild <= 30
                                                   else "MISS_OR_CANNOT_CONFIRM")},
        "oos": {"window": [OOS_START, ASOF_DATE], "market_sessions": len(oos_dates),
                "expected_market_sessions": OOS_DATE_COUNT,
                "mean_pullback": float(oos["pullback_count"].mean()) if len(oos) else None,
                "mean_readvance": float(oos["readvance_count"].mean()) if len(oos) else None,
                "mean_untouched_pullback_plus_readvance": oos_pb_ra,
                "accepted_v12_pb_plus_ra_floor": 61.84905660377359,
                "pb_plus_ra_floor_status": ("PASS" if oos_pb_ra is not None
                                            and oos_pb_ra >= 61.84905660377359
                                            else "MISS_OR_CANNOT_CONFIRM"),
                "mean_rebuild_v13": float(oos["rebuild_v13_count"].mean()) if len(oos) else None,
                "mean_v13_union": float(oos["v13_candidate_union_count"].mean()) if len(oos) else None,
                "session_coverage_status": "PASS" if len(oos_dates) == OOS_DATE_COUNT else "CANNOT_CONFIRM"},
        "thresholds_changed": False,
    }


def _metric_values(selected: Any, horizon: int) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    returns = pd.to_numeric(selected.get(f"return_t{horizon}"), errors="coerce")
    excess = pd.to_numeric(selected.get(f"excess_return_t{horizon}"), errors="coerce")
    drawdown = pd.to_numeric(selected.get(f"min_path_dd_t{horizon}"), errors="coerce")
    path = selected.get(f"path_observable_t{horizon}", pd.Series(False, index=selected.index)).fillna(False).astype(bool)
    returns = returns[np.isfinite(returns)]
    excess = excess[np.isfinite(excess)]
    dd_observed = drawdown[path & np.isfinite(drawdown)]
    benchmark = pd.to_numeric(selected.get(f"benchmark_return_t{horizon}"), errors="coerce")
    benchmark = benchmark[np.isfinite(benchmark)]
    return {"selected_count": int(len(selected)),
            "benchmark_observed_count": int(len(benchmark)),
            "benchmark_mean_return": float(benchmark.mean()) if len(benchmark) else None,
            "return_observed_count": int(len(returns)),
            "return_censored_count": int(len(selected) - len(returns)),
            "excess_observed_count": int(len(excess)),
            "excess_censored_count": int(len(selected) - len(excess)),
            "path_observable_count": int(len(dd_observed)),
            "mean_return": float(returns.mean()) if len(returns) else None,
            "median_return": float(returns.median()) if len(returns) else None,
            "mean_excess_return": float(excess.mean()) if len(excess) else None,
            "median_excess_return": float(excess.median()) if len(excess) else None,
            "positive_return_count": int((returns > 0).sum()),
            "positive_return_fraction": float((returns > 0).mean()) if len(returns) else None,
            "return_over_5pct_count": int((returns > 0.05).sum()),
            "return_over_5pct_fraction": float((returns > 0.05).mean()) if len(returns) else None,
            "worst_path_drawdown": float(dd_observed.min()) if len(dd_observed) else None}



def _rank_b_probabilities(frame: Any) -> Any:
    """Rank both B probabilities within each OOS D, with stable code tie-breaks."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    union = out["v13_candidate_union"].fillna(False).astype(bool)
    for probability, rank_column in (("p_b_lr", "b_lr_rank"), ("p_b_hgb", "b_hgb_rank")):
        out[rank_column] = np.nan
        score = pd.to_numeric(out[probability], errors="coerce")
        eligible = union & np.isfinite(score)
        for _day, group in out.loc[eligible].groupby("trade_date", sort=True):
            ranked = group.assign(_score=pd.to_numeric(group[probability], errors="coerce")).sort_values(
                ["_score", "ts_code"], ascending=[False, True], kind="mergesort")
            out.loc[ranked.index, rank_column] = np.arange(1, len(ranked) + 1, dtype=int)
    return out

def _build_oos_comparison(frame: Any, market_dates: list[str]) -> tuple[Any, Any, Any]:
    """Compare frozen pools and rankers on every OOS D, including empty dates."""
    import numpy as np
    import pandas as pd

    oos_dates = [day for day in market_dates if OOS_START <= day <= ASOF_DATE]
    by_day = {day: group for day, group in frame.groupby("trade_date", sort=False)}
    method_specs: list[tuple[str, str | None, int | None, str | None]] = [
        ("HARD_UNION", None, None, None),
        ("BREADTH_ONLY_HARD_UNION", "breadth_over_50", None, None),
        ("ACTIVITY_ONLY_HARD_UNION", "activity_over_prior20_median", None, None),
        ("TIMING_ONLY_HARD_UNION", "timing_gate", None, None),
        ("B_CONFIRMED_POOL", "b_confirmed", None, None),
        ("B_TIMING_POOL", "b_confirmed_and_timing", None, None),
    ]
    for top_k in TOP_K:
        method_specs.extend([
            (f"S_RULE_TOP{top_k}", None, top_k, "s_rule_score"),
            (f"B_CONFIRMED_TOP{top_k}", "b_confirmed", top_k, "s_rule_score"),
            (f"B_TIMING_TOP{top_k}", "b_confirmed_and_timing", top_k, "s_rule_score"),
            (f"B_LR_TOP{top_k}", None, top_k, "p_b_lr"),
            (f"B_HGB_TOP{top_k}", None, top_k, "p_b_hgb"),
        ])
    daily_rows = []
    top_detail_rows = []
    pooled_parts: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for day in oos_dates:
        group = by_day.get(day)
        if group is None:
            group = frame.iloc[0:0]
        union = group.loc[group["v13_candidate_union"].fillna(False).astype(bool)]
        for method, filter_column, top_k, score_column in method_specs:
            if method == "HARD_UNION" or (filter_column is None and top_k is None):
                pool = union
            elif method in {"BREADTH_ONLY_HARD_UNION", "ACTIVITY_ONLY_HARD_UNION", "TIMING_ONLY_HARD_UNION"}:
                pool = union.loc[union[filter_column].fillna(False).astype(bool)]
            elif filter_column == "b_confirmed":
                pool = union.loc[union["b_confirmed_state"].eq("CONFIRMED")]
            elif filter_column == "b_confirmed_and_timing":
                timing = union["timing_gate"].fillna(False).astype(bool)
                confirmed = union["b_confirmed_state"].eq("CONFIRMED")
                pool = union.loc[timing & confirmed]
            else:
                pool = union
            rankable = pool
            if score_column is not None:
                score = pd.to_numeric(pool[score_column], errors="coerce")
                rankable = pool.loc[np.isfinite(score)]
                if len(rankable):
                    rankable = rankable.assign(_rank_score=pd.to_numeric(
                        rankable[score_column], errors="coerce")).sort_values(
                            ["_rank_score", "ts_code"], ascending=[False, True], kind="mergesort")
            selected = rankable.head(top_k) if top_k is not None else rankable
            if "_rank_score" in selected:
                selected = selected.drop(columns=["_rank_score"])
            for horizon in EVAL_HORIZONS:
                metrics = _metric_values(selected, horizon)
                benchmark_values = (pd.to_numeric(group.get(f"benchmark_return_t{horizon}"), errors="coerce").dropna()
                                    if len(group) else pd.Series(dtype=float))
                benchmark_counts = (pd.to_numeric(group.get(f"benchmark_count_t{horizon}"), errors="coerce").dropna()
                                    if len(group) else pd.Series(dtype=float))
                row = {"trade_date": day, "method": method,
                       "same_d_benchmark_equal_weight_return": float(benchmark_values.iloc[0])
                           if len(benchmark_values) else None,
                       "same_d_benchmark_valid_a_count": int(benchmark_counts.iloc[0])
                           if len(benchmark_counts) else 0,
                       "candidate_pool_count": int(len(pool)),
                       "rankable_count": int(len(rankable)),
                       "ranker": score_column or "POOL",
                       "top_k": top_k, "horizon_market_sessions": horizon,
                       **metrics, "research_only": True}
                daily_rows.append(row)
                pooled_parts[(method, horizon)].append(selected)
            if method.endswith("TOP20") and len(selected):
                for rank, (_idx, candidate) in enumerate(selected.iterrows(), start=1):
                    top_detail_rows.append({"trade_date": day, "method": method, "rank": rank,
                                            **candidate.to_dict()})

    daily = pd.DataFrame(daily_rows)
    pooled_rows = []
    for method, _filter, top_k, score in method_specs:
        for horizon in EVAL_HORIZONS:
            parts = pooled_parts[(method, horizon)]
            pooled = pd.concat(parts, axis=0) if parts else frame.iloc[0:0]
            metrics = _metric_values(pooled, horizon)
            daily_for_method = daily.loc[(daily["method"] == method)
                                         & (daily["horizon_market_sessions"] == horizon)]
            observed_daily_returns = daily_for_method["mean_return"].dropna()
            observed_daily_excess = daily_for_method["mean_excess_return"].dropna()
            pooled_rows.append({"method": method, "ranker": score or "POOL", "top_k": top_k,
                                "horizon_market_sessions": horizon,
                                "oos_market_sessions": len(oos_dates),
                                "selected_days": int((daily_for_method["selected_count"] > 0).sum()),
                                "observed_return_days": int(len(observed_daily_returns)),
                                "mean_daily_selected_count": float(daily_for_method["selected_count"].mean())
                                    if len(daily_for_method) else 0.0,
                                "date_equal_weight_mean_return": float(observed_daily_returns.mean())
                                    if len(observed_daily_returns) else None,
                                "date_equal_weight_mean_excess_return": float(observed_daily_excess.mean())
                                    if len(observed_daily_excess) else None,
                                **metrics, "research_only": True})
    details = pd.DataFrame(top_detail_rows)
    base_columns = ["trade_date", "method", "rank", "ts_code", "s_rule_score", "s_rule_branch",
                    "s_rule_rank", "pullback", "readvance", "rebuild_v13", "v13_candidate_union",
                    "b1_state", "b2_state", "b3_state", "b_category", "b_confirmed_state",
                    "p_b_lr", "p_b_hgb", "b_lr_rank", "b_hgb_rank",
                    "return_t3", "benchmark_return_t3", "excess_return_t3",
                    "benchmark_count_t3",
                    "min_path_dd_t3", "path_observable_t3", "return_observable_t3",
                    "benchmark_observable_t3",
                    "return_t5", "benchmark_return_t5", "excess_return_t5",
                    "benchmark_count_t5",
                    "min_path_dd_t5", "path_observable_t5", "return_observable_t5",
                    "benchmark_observable_t5",
                    "return_t10", "benchmark_return_t10", "excess_return_t10",
                    "benchmark_count_t10",
                    "min_path_dd_t10", "path_observable_t10", "return_observable_t10",
                    "benchmark_observable_t10", *B_FEATURE_NAMES]
    if len(details):
        available = [name for name in dict.fromkeys(base_columns) if name in details.columns]
        details = details[available].sort_values(["trade_date", "method", "rank"],
                                                 kind="mergesort").reset_index(drop=True)
    else:
        details = pd.DataFrame(columns=base_columns)
    return daily, pd.DataFrame(pooled_rows), details


def _nov19_union_rows(frame: Any, official_meta: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    import pandas as pd

    day = frame.loc[frame["trade_date"].eq(REFERENCE_D)].copy()
    if not len(day):
        raise Act009Error(f"REFERENCE_FULL_A_DAY_MISSING:{REFERENCE_D}")
    next_dates = sorted(value for value in frame["trade_date"].astype(str).unique() if value > REFERENCE_D)
    t1_date = next_dates[0] if next_dates else None
    if t1_date != official_meta["asof_date"]:
        raise Act009Error(f"REFERENCE_T1_OFFICIAL_RANK_DATE_MISMATCH:{t1_date}")
    day["exact_t1_date"] = t1_date
    day["official_rank_date_matches_t1"] = True
    source = day.get("top200_source_t1", pd.Series("", index=day.index)).fillna("").astype(str)
    rank = pd.to_numeric(day.get("top200_rank_t1"), errors="coerce")
    day["official_top200_rank_t1"] = rank
    day["official_top200_member_t1"] = day.get("top200_member_t1")
    day["official_top200_source_t1"] = source
    day["official_top200_rank_status_t1"] = source.map(
        lambda value: "OFFICIAL_RANK_PRESENT" if value == "OFFICIAL_TOP200_OVERRIDE" else
        ("OFFICIAL_NOT_IN_TOP200" if value == "OFFICIAL_TOP200_NOT_IN_LIST" else
         ("T1_CENSORED_OR_UNRANKED" if not value else "NON_OFFICIAL_RANK_SOURCE")))
    day["exact_t1_return"] = pd.to_numeric(day.get("return_t1"), errors="coerce")
    day["exact_t1_return_status"] = day["exact_t1_return"].map(
        lambda value: "OBSERVED" if pd.notna(value) else "CENSORED_OR_MISSING")
    columns = ["trade_date", "ts_code", "market_type", "close", "model_eligible",
               "pullback", "readvance", "rebuild", "union", "rebuild_v13", "v13_candidate_union",
               "feature_ready", "g1_w_gt_y", "g2_veto",
               "b1_state", "b2_state", "b3_state", "b_category", "b_confirmed_state",
               "s_rule_score", "s_rule_branch", "s_rule_rank", "p_b_lr", "p_b_hgb",
               "b_lr_rank", "b_hgb_rank", "breadth_known", "activity_timing_known",
               "timing_gate", "market_breadth_up_fraction", "market_activity_fraction",
               "market_activity_prior20_median",
               "exact_t1_date", "official_rank_date_matches_t1",
               "exact_t1_return", "exact_t1_return_status", "official_top200_rank_t1",
               "official_top200_member_t1", "official_top200_source_t1",
               "official_top200_rank_status_t1", *B_FEATURE_NAMES]
    columns = [name for name in dict.fromkeys(columns) if name in day.columns]
    result = day[columns].sort_values(["s_rule_rank", "ts_code"],
                                      ascending=[True, True], kind="mergesort").reset_index(drop=True)
    official_available = source.eq("OFFICIAL_TOP200_OVERRIDE") & rank.notna()
    official_not_member = source.eq("OFFICIAL_TOP200_NOT_IN_LIST")
    return result, {"reference_date": REFERENCE_D,
                    "official_top200_asof_date": official_meta["asof_date"],
                    "expected_t1_date": official_meta["asof_date"],
                    "full_a_rows": int(len(day)),
                    "v13_union_rows": int(day["v13_candidate_union"].fillna(False).sum()),
                    "exact_t1_return_observed": int(day["exact_t1_return"].notna().sum()),
                    "official_t1_rank_available": int(official_available.sum()),
                    "official_t1_not_in_top200": int(official_not_member.sum()),
                    "official_t1_rank_missing_or_censored": int((~(official_available | official_not_member)).sum())}


def _assert_bound_source(source: dict[str, Any]) -> dict[str, Any]:
    identity = source.get("identity", {})
    backtest = source.get("backtest", {})
    a_basis = identity.get("a_market_basis") or {}
    actual = {
        "generation_id": source.get("generation_id"),
        "anchor_sha256": backtest.get("panel_sha256"),
        "manifest_sha256": backtest.get("generation_manifest_sha256"),
        "asof_date": str(source.get("asof_date")),
        "price_basis": a_basis.get("price_basis") if isinstance(a_basis, dict) else None,
        "volume_basis": a_basis.get("volume_basis") if isinstance(a_basis, dict) else None,
    }
    expected = {**EXPECTED_BINDING, "asof_date": str(EXPECTED_BINDING["asof_date"])}
    if actual != expected:
        raise Act009Error(f"BOUND_INPUT_MISMATCH:expected={expected!r}:actual={actual!r}")
    return actual


def bind_only(data_root: Path) -> dict[str, Any]:
    """Verify the current V4 pointer/generation identity without reading panel rows."""
    data_root = Path(data_root)
    if not data_root.is_absolute():
        raise Act009Error("DATA_ROOT_MUST_BE_ABSOLUTE")
    with v12.bind_current_panels(data_root) as (panel_path, source, recheck):
        binding = _assert_bound_source(source)
        recheck()
    return {"schema": SCHEMA, "status": "PASS", "mode": "INPUT_BINDING_ONLY",
            "panel_path": str(panel_path), "binding": binding,
            "row_read": False, "fit_count": 0, **FLAGS}


def _validate_output_dir(output_dir: Path, data_root: Path) -> Path:
    output_dir = Path(output_dir)
    data_root = Path(data_root)
    if not output_dir.is_absolute() or output_dir.is_symlink():
        raise Act009Error("OUTPUT_DIR_MUST_BE_ABSOLUTE_NON_SYMLINK")
    resolved = output_dir.resolve(strict=False)
    root = data_root.resolve(strict=False)
    if resolved == root or root in resolved.parents or resolved in root.parents:
        raise Act009Error("OUTPUT_DIR_OVERLAPS_PANEL_DATA_ROOT")
    if not resolved.parent.is_dir():
        raise Act009Error("OUTPUT_DIR_PARENT_MISSING")
    if resolved.exists():
        if not resolved.is_dir():
            raise Act009Error("OUTPUT_DIR_IS_NOT_A_DIRECTORY")
        allowed_existing = {"local_run_ledger.json", "writer_scope.md"}
        unexpected = sorted(item.name for item in resolved.iterdir() if item.name not in allowed_existing)
        if unexpected:
            raise Act009Error(f"OUTPUT_DIR_CONTAINS_EXISTING_RESULTS:{','.join(unexpected)}")
    return resolved


def _check_official_source(path: Path, official_meta: dict[str, Any]) -> None:
    actual = {key: official_meta.get(key) for key in ("sha256", "bytes", "rows", "asof_date")}
    if actual != EXPECTED_OFFICIAL_TOP200:
        raise Act009Error(f"OFFICIAL_TOP200_BINDING_MISMATCH:expected={EXPECTED_OFFICIAL_TOP200!r}:actual={actual!r}")


def run_once(*, data_root: Path, official_top200_path: Path,
             output_dir: Path, start_date: str = START_DATE,
             asof_date: str = ASOF_DATE) -> dict[str, Any]:
    """Read the single bound V4 A-share source, run two fixed B fits, and export frozen comparisons."""
    start_date = _day(start_date, "start_date")
    asof_date = _day(asof_date, "asof_date")
    if start_date != START_DATE or asof_date != ASOF_DATE:
        raise Act009Error("ACT009_FIXED_START_OR_ASOF_CHANGED")
    data_root = Path(data_root)
    if not data_root.is_absolute():
        raise Act009Error("DATA_ROOT_MUST_BE_ABSOLUTE")
    output_dir = _validate_output_dir(Path(output_dir), data_root)
    if not output_dir.exists():
        output_dir.mkdir(parents=False, exist_ok=False)
    progress_path = output_dir / "run_progress.jsonl"

    def progress(stage: str, status: str, details: dict[str, Any] | None = None) -> None:
        _append_progress(progress_path, stage, status, details)

    prep_start = (datetime.strptime(START_DATE, "%Y%m%d")
                  - timedelta(days=PREP_CALENDAR_DAYS)).strftime("%Y%m%d")
    run_summary: dict[str, Any] = {
        "schema": SCHEMA, "run_id": "PFT_SB_V13_FULL_ASHARE_20261123",
        "status": "RUNNING", "mode": "fit_and_evaluate",
        "start_date": start_date, "asof_date": asof_date,
        "fixed_windows": {"train_D": [START_DATE, TRAIN_END],
                          "latest_train_target_date": TRAIN_END,
                          "oos_D": [OOS_START, ASOF_DATE],
                          "candidate_statistics_D": [STATS_START, ASOF_DATE]},
        "expected_input_binding": EXPECTED_BINDING,
        "official_top200_expected": EXPECTED_OFFICIAL_TOP200,
        "preparation_calendar_days": PREP_CALENDAR_DAYS,
        "preparation_start_date": prep_start,
        "reader_feature_warmup_days": 180,
        "output_dir": str(output_dir), **FLAGS,
    }
    progress("run", "STARTED", {"start_date": start_date, "asof_date": asof_date,
                                  "fit_plan": {"S": 0, "B": 2, "search": 0}})
    _write_json(output_dir / "run_summary.json", run_summary)
    try:
        official, official_meta = v12.read_official_top200(Path(official_top200_path))
        _check_official_source(Path(official_top200_path), official_meta)
        progress("official_top200", "READ_PASS", official_meta)
        with v12.bind_current_panels(data_root) as (panel_path, source, recheck):
            binding = _assert_bound_source(source)
            if asof_date > source["asof_date"]:
                raise Act009Error("REQUESTED_ASOF_AFTER_BOUND_PANEL_ASOF")
            progress("panel_binding", "BOUND_EXPECTED_GENERATION", {
                "panel_path": str(panel_path), "binding": binding})
            frame, panel_read = v12._read_panel(panel_path, start_date=prep_start,
                                                asof_date=asof_date, warmup_days=180)
            if not len(frame):
                raise Act009Error("A_SHARE_PANEL_ROWS_EMPTY_IN_REQUESTED_WINDOW")
            progress("panel_read", "PROJECTED_READER_PASS", panel_read)
            frame, vector_meta = v12._vectorize_rows(frame, start_date=prep_start,
                                                      asof_date=asof_date)
            market_dates = list(frame.attrs.get("market_dates", []))
            if not market_dates:
                raise Act009Error("MARKET_SESSION_LIST_EMPTY")
            half_dates = [day for day in market_dates if STATS_START <= day <= ASOF_DATE]
            oos_dates = [day for day in market_dates if OOS_START <= day <= ASOF_DATE]
            if len(half_dates) != HALF_YEAR_SESSION_COUNT:
                raise Act009Error(f"HALF_YEAR_SESSION_COUNT_MISMATCH:{len(half_dates)}")
            if len(oos_dates) != OOS_DATE_COUNT:
                raise Act009Error(f"OOS_SESSION_COUNT_MISMATCH:{len(oos_dates)}")

            frame, top200_meta = v12._apply_top200_ranks(frame, official, official_meta)
            frame = v12._join_future_top200(frame)
            frame, market_meta = _attach_exact_market_features(frame, market_dates)
            frame, rebuild_meta = _derive_rebuild_v13(frame, market_dates)
            frame["v13_candidate_union"] = (frame["pullback"].fillna(False).astype(bool)
                                             | frame["readvance"].fillna(False).astype(bool)
                                             | frame["rebuild_v13"].fillna(False).astype(bool))
            frame, s_rule_meta = _apply_s_rule(frame)
            frame, b_confirmation_meta = _add_b_confirmations(frame)
            frame, label_meta = _add_b_training_labels(frame, market_dates)
            frame, benchmark_meta = _attach_horizon_benchmarks(frame)
            progress("causal_features", "BUILD_PASS", {
                **vector_meta, **market_meta, **rebuild_meta,
                "v13_candidate_union_rows": int(frame["v13_candidate_union"].sum()),
                "s_rule": s_rule_meta, "b_confirmations": b_confirmation_meta,
                "b_target": label_meta, "benchmark": benchmark_meta})

            frame, split = _episode_split(frame)
            progress("group_purge", "PASS", {key: value for key, value in split.items()
                                              if not key.endswith("mask")})
            models, model_report, predictions = _fit_b_rankers(
                frame, split, panel_source=source, official_meta=official_meta,
                checkpoint_path=output_dir / "model_state.joblib", progress=progress)
            for column in predictions:
                frame[column] = predictions[column]
            frame = _rank_b_probabilities(frame)
            recheck()
            progress("source_recheck", "PASS_BEFORE_EXPORT", {"binding": binding})

            candidate_counts = _daily_candidate_counts(frame, market_dates)
            candidate_summary = _candidate_count_summary(candidate_counts, market_dates)
            comparison_daily, comparison_pooled, top20_daily = _build_oos_comparison(frame, market_dates)
            nov19_rows, nov19_meta = _nov19_union_rows(frame, official_meta)
            model_report.update({
                "input_binding": binding,
                "panel_read": panel_read,
                "vectorizer": vector_meta,
                "market_features": market_meta,
                "rebuild_v13": rebuild_meta,
                "s_rule": s_rule_meta,
                "b_confirmations": b_confirmation_meta,
                "b_target": label_meta,
                "candidate_count_summary": candidate_summary,
                "benchmark_contract": benchmark_meta,
                "top200_rank_contract": top200_meta,
                "nov19_reference": nov19_meta,
                "output_contract": {
                    "RESEARCH_ONLY": True, "production_allowed": False,
                    "buy_gate_updated": False, "orders_sent": False,
                    "S_fit_count": 0, "B_fit_count": 2,
                    "hyperparameter_search_count": 0,
                    "horizons": list(EVAL_HORIZONS), "top_k": list(TOP_K),
                    "oos_session_count": len(oos_dates),
                },
                "oos_comparison_pooled": comparison_pooled.to_dict(orient="records"),
            })
            outputs = {
                "daily_candidate_counts.csv": candidate_counts,
                "oos_comparison_daily.csv": comparison_daily,
                "oos_comparison_pooled.csv": comparison_pooled,
                "oos_top20_daily.csv": top20_daily,
                "nov19_v13_union_full_a_20261119.csv": nov19_rows,
            }
            output_rows = {}
            for name, value in outputs.items():
                output_rows[name] = _write_rows(output_dir / name, value)
                progress("artifact_write", "TABLE_WRITTEN", {
                    "name": name, "rows": output_rows[name]})

            _write_json(output_dir / "model_metrics.json", model_report)
            _save_model_state(output_dir / "model_state.joblib", models, model_report,
                              source, official_meta)
            progress("artifact_write", "MODEL_AND_METRICS_WRITTEN", {
                "model_fit_count": model_report["fit_count"],
                "model_state": str(output_dir / "model_state.joblib")})
            artifact_names = [*outputs, "model_metrics.json", "model_state.joblib"]
            artifacts = {name: {"bytes": (output_dir / name).stat().st_size,
                                "sha256": _sha_file(output_dir / name)}
                         for name in artifact_names}
            run_summary.update({
                "status": "FIT_COMPLETED", "fit_count": model_report["fit_count"],
                "S_fit_count": model_report["S_fit_count"],
                "B_fit_count": model_report["B_fit_count"],
                "hyperparameter_search_count": model_report["hyperparameter_search_count"],
                "panel_source": source, "panel_read": panel_read,
                "official_top200_source": official_meta,
                "vectorized_run": vector_meta, "market_features": market_meta,
                "candidate_count_summary": candidate_summary,
                "split_guard": model_report["split_guard"],
                "training_rows": model_report["training"],
                "fit_policy": model_report["fit_policy"],
                "oos_comparison_pooled": comparison_pooled.to_dict(orient="records"),
                "nov19_reference": nov19_meta,
                "output_rows": output_rows, "artifact_receipts": artifacts,
                "censor_policy": "EXACT_A_MARKET_SESSION_OFFSETS_ONLY; MISSING_T+n_BAR_REMAINS_CENSORED",
                "drawdown_measure": "MIN_D_TO_T+n_CLOSE_VS_RUNNING_CLOSE_PEAK; EXACT_MARKET_SESSIONS",
                "next_action": "ROOT_RECONCILES_RESULTS_AND_OWNS_DRIVE_DELIVERY; RESEARCH_ONLY",
            })
            _write_json(output_dir / "run_summary.json", run_summary)
            recheck()
            progress("source_recheck", "PASS_AFTER_EXPORT", {"binding": binding})
            progress("run", "OUTPUTS_COMPLETE", {"fit_count": model_report["fit_count"],
                                                   "output_dir": str(output_dir)})
            return run_summary
    except Exception as exc:
        run_summary.update({"status": "FAILED",
                            "failure": {"type": type(exc).__name__, "reason": str(exc)}})
        try:
            progress("run", "FAILED", {"type": type(exc).__name__, "reason": str(exc)})
            _write_json(output_dir / "run_summary.json", run_summary)
        except OSError:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--official-top200", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--asof-date", default=ASOF_DATE)
    parser.add_argument("--bind-only", action="store_true",
                        help="check the expected V4 pointers and generation without reading panel rows")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.bind_only:
            result = bind_only(args.data_root)
            print(json.dumps(_json_safe(result), ensure_ascii=False, sort_keys=True))
            return 0
        if args.official_top200 is None or args.output_dir is None:
            raise Act009Error("OFFICIAL_TOP200_AND_OUTPUT_DIR_REQUIRED_FOR_RUN")
        result = run_once(data_root=args.data_root, official_top200_path=args.official_top200,
                          output_dir=args.output_dir, start_date=args.start_date,
                          asof_date=args.asof_date)
        print(json.dumps({"status": result["status"], "fit_count": result["fit_count"],
                          "output_dir": result["output_dir"], "output_rows": result["output_rows"]},
                         ensure_ascii=False, sort_keys=True))
        return 0
    except (Act009Error, v12.StudyError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
