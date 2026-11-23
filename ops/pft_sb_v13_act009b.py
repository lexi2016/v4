"""ACT-009B frozen F1-F5 clean-pool, candidate export, and B-ranker run."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ops import pft_s_v12_full_a as v12
from ops import pft_sb_v13_act009 as act009

SCHEMA = "pft_sb_v13_act009b.v1"
RUN_ID = "PFT_SB_V13_ACT009B_FULL_A_20261123"
START_DATE = "20251101"
ASOF_DATE = "20261120"
TRAIN_END = "20260831"
OOS_START = "20260901"
EXPECTED_SESSIONS = 256
MAX_SHARD_BYTES_EXCLUSIVE = 8_000_000
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}
F5_B_FEATURE_NAMES = tuple(act009.B_FEATURE_NAMES) + (
    "crowding", "crowding_rolling_p25", "crowding_rolling_p75",
)


class Act009BError(RuntimeError):
    """Fail-closed ACT-009B input, feature, or artifact contract error."""


def _add_f1_f4(frame: Any) -> tuple[Any, dict[str, Any]]:
    """Export exact F1-F4 states and build the clean three-branch union."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    names = ("anchor_age", "low_held_anchor", "recent_below_pair", "close_bbi_pct",
             "vol5_vs_prior15", "range5_vs_prior15", "d_open_close_prev_close", "d_vr5",
             "close_vs_prior10_high", "ret_1", "ret_5", "close_white_pct",
             "d_upper_wick_prev_close", "close_yellow_pct", "ret_20", "white_yellow_spread_pct",
             "d_range_prev_close", "close_vs_trailing30_high")
    values = {name: pd.to_numeric(out[name], errors="coerce") for name in names}
    def known(*cols: str) -> Any:
        mask = pd.Series(True, index=out.index)
        for col in cols:
            mask &= np.isfinite(values[col])
        return mask
    f1_known = known("anchor_age", "low_held_anchor", "recent_below_pair", "close_bbi_pct",
                     "vol5_vs_prior15", "range5_vs_prior15", "d_open_close_prev_close",
                     "d_vr5", "close_vs_prior10_high")
    f1_structure = ((values["anchor_age"].ge(0) & values["low_held_anchor"].eq(1)
                     & values["recent_below_pair"].eq(0) & values["close_bbi_pct"].ge(0))
                    & ((values["vol5_vs_prior15"].le(1) & values["range5_vs_prior15"].le(1))
                       | (values["d_open_close_prev_close"].ge(0) & values["d_vr5"].ge(1.2)
                          & values["close_vs_prior10_high"].ge(0))))
    f1_exact = f1_known & out["rebuild"].fillna(False).astype(bool) & f1_structure
    f1_with_repair = f1_exact & out["rebuild_v13"].fillna(False).astype(bool)
    f2_known = known("ret_1", "ret_5", "close_white_pct")
    f2 = f2_known & out["pullback"].fillna(False).astype(bool) & values["ret_1"].ge(-0.03) & values["ret_5"].ge(-0.05) & values["close_white_pct"].ge(-0.02)
    f3_known = known("d_vr5", "d_upper_wick_prev_close", "close_yellow_pct", "ret_20", "anchor_age")
    f3_veto = ((values["d_vr5"].gt(3) & values["d_upper_wick_prev_close"].ge(0.025))
               | (values["close_yellow_pct"].gt(0.25) & values["ret_20"].gt(0.30))
               | values["d_upper_wick_prev_close"].ge(0.035) | values["anchor_age"].gt(25))
    spread_ok = values["white_yellow_spread_pct"].ge(0.005)
    f4_pb_known = known("white_yellow_spread_pct", "d_range_prev_close", "d_open_close_prev_close")
    f4_ra_known = known("white_yellow_spread_pct", "d_open_close_prev_close", "d_vr5",
                        "close_vs_trailing30_high")
    f4_rebuild_known = known("white_yellow_spread_pct", "d_open_close_prev_close", "d_range_prev_close")
    f4_pb = f4_pb_known & out["pullback"].fillna(False).astype(bool) & spread_ok & values["d_range_prev_close"].le(0.045) & values["d_open_close_prev_close"].ge(-0.015)
    f4_ra = f4_ra_known & out["readvance"].fillna(False).astype(bool) & spread_ok & values["d_open_close_prev_close"].gt(0) & values["d_vr5"].le(3) & values["close_vs_trailing30_high"].ge(-0.08)
    f4_rebuild = f4_rebuild_known & out["rebuild_v13"].fillna(False).astype(bool) & spread_ok & values["d_open_close_prev_close"].ge(0) & values["d_range_prev_close"].le(0.06)
    out["f1_known"], out["f1_exact"] = f1_known, f1_exact
    out["f1_with_repair"] = f1_with_repair
    out["f2_known"], out["f2_exact"] = f2_known, f2
    out["f3_known"], out["f3_global_veto"] = f3_known, (f3_known & f3_veto)
    out["f4_pullback_known"], out["f4_readvance_known"] = f4_pb_known, f4_ra_known
    out["f4_rebuild_known"] = f4_rebuild_known
    out["f4_pullback_confirmed"], out["f4_readvance_confirmed"], out["f4_rebuild_confirmed"] = f4_pb, f4_ra, f4_rebuild
    for name, known_mask, pass_mask in (("f1", f1_known, f1_exact), ("f2", f2_known, f2)):
        out[f"{name}_state"] = np.where(known_mask, np.where(pass_mask, "PASS", "FAIL"), "UNKNOWN")
    out["f1_with_repair_state"] = np.where(f1_known, np.where(f1_with_repair, "PASS", "FAIL"), "UNKNOWN")
    out["f3_state"] = np.where(f3_known, np.where(f3_veto, "VETO", "ALLOW"), "UNKNOWN")
    no_veto = f3_known & ~f3_veto
    out["clean_pullback"] = f2 & no_veto & f4_pb
    out["clean_readvance"] = out["readvance"].fillna(False).astype(bool) & no_veto & f4_ra
    out["clean_rebuild"] = f1_with_repair & no_veto & f4_rebuild
    out["clean_union"] = out[["clean_pullback", "clean_readvance", "clean_rebuild"]].any(axis=1)
    return out, {"F1": "ACT008 exact: V12 rebuild plus anchor age/hold/recent-pair/BBI checks plus contraction OR bullish-volume alternative; separate ACT009 repair confirmation is required for clean V1.3 rebuild",
                 "F2": "PB ret1 >= -0.03 AND ret5 >= -0.05 AND close_white_pct >= -0.02",
                 "F3": "global veto from fixed four branches; unknown required inputs retained as UNKNOWN",
                 "F4": "spread >= 0.005, with per-branch frozen confirmations",
                 "clean_union_rows": int(out["clean_union"].sum()),
                 "f1_exact_rows": int(f1_exact.sum()),
                 "f1_with_repair_rows": int(f1_with_repair.sum()),
                 "f1_unknown_rows": int((~f1_known).sum()),
                 "f2_rows": int(f2.sum()),
                 "f2_unknown_rows": int((~f2_known).sum()),
                 "f3_veto_rows": int((f3_known & f3_veto).sum()),
                 "f3_allow_rows": int((f3_known & ~f3_veto).sum()),
                 "f3_unknown_rows": int((~f3_known).sum()),
                 "f4_pullback_rows": int(f4_pb.sum()), "f4_readvance_rows": int(f4_ra.sum()),
                 "f4_rebuild_rows": int(f4_rebuild.sum())}


def _add_f5_crowding(frame: Any, market_dates: list[str]) -> tuple[Any, dict[str, Any]]:
    """Count raw full-A V1.2 union per D and add prior-only rolling regime fields."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    daily = out.groupby("trade_date", sort=True)["union"].sum().reindex(market_dates).fillna(0).astype("int64")
    p25 = daily.shift(1).rolling(60, min_periods=60).quantile(0.25)
    p75 = daily.shift(1).rolling(60, min_periods=60).quantile(0.75)
    for series in (daily, p25, p75):
        series.index = series.index.astype(str)
    out["crowding"] = out["trade_date"].map(daily).astype("int64")
    out["crowding_rolling_p25"] = out["trade_date"].map(p25)
    out["crowding_rolling_p75"] = out["trade_date"].map(p75)
    out["f5_fixed_low"] = out["crowding"].le(240)
    out["f5_fixed_high"] = out["crowding"].ge(500)
    out["f5_blocked"] = out["f5_fixed_high"]
    out["f5_pass"] = ~out["f5_blocked"]
    out["f5_rolling_low_known"] = out["crowding_rolling_p25"].notna()
    out["f5_rolling_high_known"] = out["crowding_rolling_p75"].notna()
    out["f5_rolling_low"] = out["f5_rolling_low_known"] & out["crowding"].le(out["crowding_rolling_p25"])
    out["f5_rolling_high"] = out["f5_rolling_high_known"] & out["crowding"].ge(out["crowding_rolling_p75"])
    return out, {"raw_union_count": "full-A V1.2 raw union count by market D",
                 "fixed_block": "crowding >= 500", "fixed_low": "crowding <= 240",
                 "rolling_quantiles": "exact prior 60 market sessions, shift(1), min_periods=60",
                 "rolling_p25_known_dates": int(p25.notna().sum()),
                 "rolling_p75_known_dates": int(p75.notna().sum()),
                 "max_market_union_count": int(daily.max()) if len(daily) else 0}


RAW_INPUT_COLUMNS = (
    "open", "high", "low", "close", "vol", "pct_chg", "bbi", "j",
    "zge_white_line", "zge_yellow_line",
)
REBUILD_LINEAGE_COLUMNS = (
    "_anchor_date", "_anchor_low", "_market_session", "_valid_repair_bar",
    "_below_yellow", "_above_both", "rebuild_state", "rebuild_episode_id",
    "rebuild_break_pair_start_date", "rebuild_break_pair_end_date",
    "rebuild_anchor_date", "rebuild_confirmation_date", "rebuild_anchor_low",
    "rebuild_consolidation_sessions",
)
FORMULA_FLAGS = (
    "feature_ready", "model_eligible", "g1_w_gt_y", "g2_veto",
    "pullback", "readvance", "rebuild", "union", "rebuild_v13",
    "v13_candidate_union", "f1_known", "f1_exact", "f1_with_repair",
    "f1_state", "f1_with_repair_state", "f2_known", "f2_exact", "f2_state",
    "f3_known", "f3_global_veto", "f3_state", "f4_pullback_known",
    "f4_readvance_known", "f4_rebuild_known", "f4_pullback_confirmed",
    "f4_readvance_confirmed", "f4_rebuild_confirmed", "clean_pullback",
    "clean_readvance", "clean_rebuild", "clean_union", "f5_fixed_low",
    "f5_fixed_high", "f5_blocked", "f5_pass", "f5_rolling_low_known",
    "f5_rolling_high_known", "f5_rolling_low", "f5_rolling_high",
    "b1_known", "b1_candidate", "b1_state", "b2_known", "b2_candidate",
    "b2_state", "b3_known", "b3_candidate", "b3_state", "b_category",
    "b_confirmed_state", "breadth_known", "activity_timing_known",
    "breadth_over_50", "activity_over_prior20_median", "timing_gate",
)
FORMULA_SCORE_COLUMNS = (
    "hard_score_pullback", "hard_score_readvance", "hard_score_rebuild",
    "s_pullback_percentile", "s_readvance_percentile", "s_rebuild_v13_percentile",
    "s_rule_score", "s_rule_branch", "s_rule_rank",
)
TARGET_COLUMNS = (
    "t1_ret", "t3_ret", "t5_ret", "t10_ret", "max_dd5", "max_dd10",
    "target_t5_success", "in_next_top200", "benchmark_return_t3",
    "benchmark_return_t5", "benchmark_return_t10", "excess_return_t3",
    "excess_return_t5", "excess_return_t10", "benchmark_count_t3",
    "benchmark_count_t5", "benchmark_count_t10", "path_observable_t1",
    "path_observable_t3", "path_observable_t5", "path_observable_t10",
    "return_observable_t1", "return_observable_t3", "return_observable_t5",
    "return_observable_t10", "target_t1_date", "target_t3_date",
    "target_t5_date", "target_t10_date", "top200_rank_t1", "top200_source_t1",
    "top200_rank", "top200_membership", "top200_rank_source",
)
SPLIT_COLUMNS = (
    "candidate_population", "clean_train_candidate", "train_label_known",
    "train_fit_mask", "clean_oos_candidate", "split_role",
    "canonical_k_group", "repair_episode_group", "target_t5_train_label",
)
BASE_EXPORT_COLUMNS = (
    "trade_date", "ts_code", "market_type", *RAW_INPUT_COLUMNS,
    *v12.FEATURE_NAMES, *REBUILD_LINEAGE_COLUMNS, *FORMULA_FLAGS,
    *FORMULA_SCORE_COLUMNS, "rebuild_episode_id", "crowding",
    "crowding_rolling_p25", "crowding_rolling_p75", *act009.B_FEATURE_NAMES,
    *F5_B_FEATURE_NAMES, *TARGET_COLUMNS, *SPLIT_COLUMNS,
)


def _attach_target_contract(frame: Any, market_dates: list[str]) -> Any:
    """Add explicit T+N date mapping and censored-safe target aliases."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    index_by_day = {day: index for index, day in enumerate(market_dates)}
    sessions = out["trade_date"].astype(str).map(index_by_day)
    if sessions.isna().any():
        raise Act009BError("MARKET_SESSION_MAPPING_GAP_FOR_EXPORT")
    out["market_session_index"] = sessions.astype("int32")
    for horizon in (1, 3, 5, 10):
        target_index = sessions.to_numpy(dtype=np.int64) + horizon
        date_values = np.full(len(out), "", dtype=object)
        available = target_index < len(market_dates)
        date_values[available] = np.asarray(market_dates, dtype=object)[target_index[available]]
        out[f"target_t{horizon}_date"] = date_values
        out[f"t{horizon}_ret"] = pd.to_numeric(out[f"return_t{horizon}"], errors="coerce")
        if horizon in (5, 10):
            out[f"max_dd{horizon}"] = pd.to_numeric(out[f"min_path_dd_t{horizon}"], errors="coerce")
        out[f"return_observable_t{horizon}"] = np.isfinite(out[f"t{horizon}_ret"])
    success_known = (out["path_observable_t5"].fillna(False).astype(bool)
                     & np.isfinite(out["t5_ret"]) & np.isfinite(out["max_dd5"]))
    out["target_t5_success"] = np.nan
    success = out["t5_ret"].ge(0.03) & out["max_dd5"].ge(-0.05)
    out.loc[success_known, "target_t5_success"] = success.loc[success_known].astype(float)
    member = out.get("top200_member_t1", pd.Series(pd.NA, index=out.index))
    out["in_next_top200"] = pd.array(member, dtype="boolean")
    return out


def _unit_for_column(name: str, dtype: str = "") -> str:
    if name in {"trade_date", "target_t1_date", "target_t3_date", "target_t5_date", "target_t10_date"}:
        return "YYYYMMDD market-session date"
    if name in {"open", "high", "low", "close", "bbi", "zge_white_line", "zge_yellow_line", "_anchor_low", "rebuild_anchor_low"}:
        return "QFQ price at bound as-of basis"
    if name == "vol":
        return "V4 QFQ event-volume units"
    if name in {"crowding", "crowding_rolling_p25", "crowding_rolling_p75"}:
        return "full-A V1.2 union candidate count"
    if name in {"target_t5_success", "target_t5_train_label"}:
        return "binary target in {0,1}; blank when censored/unknown"
    if name in {"s_rule_score", "s_pullback_percentile", "s_readvance_percentile", "s_rebuild_v13_percentile"}:
        return "within-day percentile in [0,1]"
    if name in {"pct_chg"}:
        return "bound V4 percent-change source units"
    if name.endswith("_group") or name.endswith("_state") or name.endswith("_branch") or name in {"market_type", "split_role", "top200_source_t1", "top200_rank_source", "b_category"}:
        return "categorical string"
    if "rank" in name or name == "market_session_index":
        return "integer ordinal"
    if name.endswith("_count") or name.endswith("_rows") or name.endswith("_sessions"):
        return "integer count"
    if name in {"candidate_population", "clean_train_candidate", "train_label_known", "train_fit_mask",
                "clean_oos_candidate", "in_next_top200", "path_observable_t1", "path_observable_t3",
                "path_observable_t5", "path_observable_t10", "return_observable_t1",
                "return_observable_t3", "return_observable_t5", "return_observable_t10"}:
        return "nullable boolean"
    if dtype in {"bool", "boolean"}:
        return "boolean flag"
    if name in {"ret_1", "ret_5", "ret_20", "ret_60", "d_range_prev_close", "d_upper_wick_prev_close",
                "d_open_close_prev_close", "close_yellow_pct", "close_white_pct", "white_yellow_spread_pct",
                "close_bbi_pct", "vol5_vs_prior15", "range5_vs_prior15", "d_vr5", "d_range_vs_prior15",
                "close_vs_prior10_high", "close_vs_prior20_high", "close_vs_trailing30_high", "anchor_return",
                "anchor_vr5", "close_vs_anchor_low", "prior5_vol_vs_prior15", "prior5_range_vs_prior15",
                "t1_ret", "t3_ret", "t5_ret", "t10_ret", "max_dd5", "max_dd10",
                "target_t5_success", "benchmark_return_t3", "benchmark_return_t5", "benchmark_return_t10",
                "excess_return_t3", "excess_return_t5", "excess_return_t10", "exact_d_return",
                "exact_trailing5_return", "relative_d_return", "relative_trailing5_return",
                "market_breadth_up_fraction", "market_activity_fraction", "market_activity_prior20_median"}:
        return "fraction/ratio"
    if name.endswith("_feature"):
        return "unitless numeric indicator or D-known feature; see frozen feature name"
    if name == "anchor_age":
        return "market-session age"
    return "D-known numeric formula feature; units follow named source field"


def _feature_export_frame(frame: Any, market_dates: list[str], split: dict[str, Any]) -> Any:
    """Project candidate-only, auditable rows for the bound A-share universe."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    session_by_day = {day: index for index, day in enumerate(market_dates)}
    session = out["trade_date"].astype(str).map(session_by_day)
    if session.isna().any():
        raise Act009BError("MARKET_SESSION_MAPPING_GAP_FOR_EXPORT_PROJECTION")
    out["market_session_index"] = session.astype("int32")
    in_window = out["trade_date"].between(START_DATE, ASOF_DATE)
    population = in_window & (out["union"].fillna(False).astype(bool)
                              | out["v13_candidate_union"].fillna(False).astype(bool))
    out["candidate_population"] = population
    train_window = out["trade_date"].between(START_DATE, TRAIN_END)
    oos_window = out["trade_date"].between(OOS_START, ASOF_DATE)
    out["clean_train_candidate"] = out["clean_union"].fillna(False).astype(bool) & train_window
    out["clean_oos_candidate"] = out["clean_union"].fillna(False).astype(bool) & oos_window
    out["train_label_known"] = out["b_training_target"].notna()
    out["train_fit_mask"] = split["train_mask"].astype(bool)
    out["target_t5_train_label"] = out["b_training_target"]
    out["canonical_k_group"] = out["_canonical_k_group"].fillna("").astype(str)
    out["repair_episode_group"] = out["_repair_episode_group"].fillna("").astype(str)
    role = np.full(len(out), "OUTSIDE_MODEL_COHORT", dtype=object)
    role[out["candidate_population"].to_numpy(dtype=bool)] = "COHORT_ONLY"
    role[out["clean_train_candidate"].to_numpy(dtype=bool)] = "TRAIN_UNLABELED_OR_PURGED"
    role[out["train_fit_mask"].to_numpy(dtype=bool)] = "TRAIN_FIT"
    role[out["clean_oos_candidate"].to_numpy(dtype=bool)] = "OOS_CANDIDATE"
    out["split_role"] = role
    projection = out.loc[population].copy()
    missing = [name for name in dict.fromkeys(BASE_EXPORT_COLUMNS) if name not in projection.columns]
    if missing:
        raise Act009BError(f"CANDIDATE_EXPORT_REQUIRED_COLUMN_MISSING:{','.join(missing)}")
    columns = list(dict.fromkeys(BASE_EXPORT_COLUMNS + ("market_session_index",)))
    projection = projection.loc[:, columns].sort_values(["trade_date", "ts_code"], kind="mergesort")
    return projection.reset_index(drop=True)


def _csv_gzip_bytes(frame: Any) -> tuple[bytes, int]:
    text = io.StringIO(newline="")
    frame.to_csv(text, index=False, encoding="utf-8", lineterminator="\n",
                 na_rep="", float_format="%.17g")
    raw = text.getvalue().encode("utf-8")
    stream = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=stream, compresslevel=6, mtime=0) as zipped:
        zipped.write(raw)
    return stream.getvalue(), len(raw)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_candidate_shards(projection: Any, output_dir: Path, *,
                            max_shard_bytes_exclusive: int = MAX_SHARD_BYTES_EXCLUSIVE
                            ) -> list[dict[str, Any]]:
    """Write deterministic, row-split train/OOS gzip shards and verify every byte."""
    import pandas as pd

    receipts: list[dict[str, Any]] = []
    split_specs = (("train", projection.loc[projection["trade_date"].between(START_DATE, TRAIN_END)]),
                   ("oos", projection.loc[projection["trade_date"].between(OOS_START, ASOF_DATE)]))
    for split_name, rows in split_specs:
        rows = rows.sort_values(["trade_date", "ts_code"], kind="mergesort").reset_index(drop=True)
        if not len(rows):
            raise Act009BError(f"CANDIDATE_EXPORT_SPLIT_EMPTY:{split_name}")
        offset, part = 0, 1
        chunk_size = len(rows)
        while offset < len(rows):
            chunk_size = min(chunk_size, len(rows) - offset)
            while True:
                chunk = rows.iloc[offset:offset + chunk_size]
                compressed, raw_bytes = _csv_gzip_bytes(chunk)
                if len(compressed) < max_shard_bytes_exclusive:
                    break
                if chunk_size <= 1:
                    raise Act009BError(f"SINGLE_CANDIDATE_ROW_EXCEEDS_SHARD_LIMIT:{split_name}")
                chunk_size = max(1, chunk_size // 2)
            filename = f"CODEX_MAC_ACT-009B_candidate_{split_name}_{part:04d}.csv.gz"
            path = output_dir / filename
            _atomic_bytes(path, compressed)
            written = path.read_bytes()
            if len(written) != len(compressed) or hashlib.sha256(written).hexdigest() != hashlib.sha256(compressed).hexdigest():
                raise Act009BError(f"CANDIDATE_SHARD_READBACK_MISMATCH:{filename}")
            raw = gzip.decompress(written)
            parsed = pd.read_csv(io.BytesIO(raw), usecols=["trade_date"], dtype={"trade_date": "string"})
            if len(parsed) != len(chunk):
                raise Act009BError(f"CANDIDATE_SHARD_ROW_COUNT_MISMATCH:{filename}")
            receipts.append({"split": split_name, "path": filename, "rows": int(len(chunk)),
                             "date_min": str(chunk["trade_date"].min()),
                             "date_max": str(chunk["trade_date"].max()),
                             "bytes": len(written), "sha256": hashlib.sha256(written).hexdigest(),
                             "uncompressed_bytes": raw_bytes,
                             "gzip_mtime": int.from_bytes(written[4:8], "little")})
            offset += len(chunk)
            part += 1
    return receipts


def _publish_dataset_manifest(projection: Any, output_dir: Path, *,
                              binding: dict[str, Any], panel_source: dict[str, Any],
                              official_meta: dict[str, Any], market_dates: list[str],
                              study_dates: list[str],
                              split_guard: dict[str, Any], f1_f4_meta: dict[str, Any],
                              f5_meta: dict[str, Any],
                              max_shard_bytes_exclusive: int = MAX_SHARD_BYTES_EXCLUSIVE
                              ) -> dict[str, Any]:
    """Publish manifest only after all train/OOS shards are final and readable."""
    columns = list(projection.columns)
    feature_allowlist = list(F5_B_FEATURE_NAMES)
    forbidden_feature_names = set(TARGET_COLUMNS) | {"target_t5_train_label", "train_fit_mask",
                                                       "canonical_k_group", "repair_episode_group"}
    if set(feature_allowlist) & forbidden_feature_names:
        raise Act009BError("MODEL_FEATURE_ALLOWLIST_CONTAINS_TARGET_OR_SPLIT_METADATA")
    missing_features = sorted(set(feature_allowlist) - set(columns))
    if missing_features:
        raise Act009BError(f"MODEL_FEATURE_ALLOWLIST_MISSING:{','.join(missing_features)}")
    shards = _write_candidate_shards(projection, output_dir,
                                      max_shard_bytes_exclusive=max_shard_bytes_exclusive)
    if sum(item["rows"] for item in shards) != len(projection):
        raise Act009BError("CANDIDATE_SHARD_TOTAL_ROW_COUNT_MISMATCH")
    for receipt in shards:
        if receipt["bytes"] >= max_shard_bytes_exclusive or receipt["gzip_mtime"] != 0:
            raise Act009BError(f"CANDIDATE_SHARD_CONTRACT_MISMATCH:{receipt['path']}")
    population = {
        "inclusion": "V1.2 raw union OR ACT009 V1.3 candidate union; one V4 security-date row",
        "rows": int(len(projection)), "train_rows": int(projection["trade_date"].between(START_DATE, TRAIN_END).sum()),
        "oos_rows": int(projection["trade_date"].between(OOS_START, ASOF_DATE).sum()),
        "date_min": str(projection["trade_date"].min()), "date_max": str(projection["trade_date"].max()),
        "distinct_dates": int(projection["trade_date"].nunique()),
        "candidate_components": {
            "v12_union_rows": int(projection["union"].fillna(False).astype(bool).sum()),
            "v13_union_rows": int(projection["v13_candidate_union"].fillna(False).astype(bool).sum()),
            "clean_union_rows": int(projection["clean_union"].fillna(False).astype(bool).sum()),
            "clean_train_candidates": int(projection["clean_train_candidate"].sum()),
            "train_fit_mask": int(projection["train_fit_mask"].sum()),
            "clean_oos_candidates": int(projection["clean_oos_candidate"].sum()),
        },
    }
    projection_schema = {name: {"dtype": str(projection[name].dtype),
                                "unit": _unit_for_column(name, str(projection[name].dtype))}
                         for name in columns}
    manifest = {
        "schema": "pft_sb_v13_act009b_candidate_dataset.v1", "run_id": RUN_ID,
        "status": "READY_PREFIT", "input_binding": binding,
        "panel_source": panel_source, "official_top200_source": official_meta,
        "windows": {"dataset_D": [START_DATE, ASOF_DATE], "train_D": [START_DATE, TRAIN_END],
                    "latest_mature_target_date": TRAIN_END, "oos_D": [OOS_START, ASOF_DATE]},
        "market_date_mapping": {"market": "A_SHARE", "offset_basis": "exact consecutive bound A-market session",
                                "dates": list(market_dates), "study_dates": list(study_dates)},
        "censor_semantics": "A missing/invalid target-session bar leaves return/path labels blank; no next-available-bar substitution. Top200 unknown remains blank.",
        "target_definitions": {"target_t5_success": "1 iff exact T+5 close return >= 0.03 AND complete D-to-T+5 close-path maximum drawdown >= -0.05; blank when either path is censored/unknown",
                               "training_label": "same T+5 rule, clean_union only, exact completion date <= 20260831; target_t5_train_label may remain populated on matured rows later purged for group overlap, and train_fit_mask alone selects the actual fit rows after canonical K and repair episode purge",
                               "top200": "exact next market-session realized Top200 membership; 20261120 uses supplied official ranking"},
        "thresholds": {"F1": "ACT008 exact V12 rebuild plus anchor_age>=0, low_held_anchor==1, recent_below_pair==0, close_bbi_pct>=0 and ((vol5_vs_prior15<=1 AND range5_vs_prior15<=1) OR (d_open_close_prev_close>=0 AND d_vr5>=1.2 AND close_vs_prior10_high>=0)); ACT009 repair is an additional clean rebuild requirement",
                       "F2": "pullback AND ret_1>=-0.03 AND ret_5>=-0.05 AND close_white_pct>=-0.02",
                       "F3": "global veto: (d_vr5>3 AND upper_wick>=0.025) OR (close_yellow_pct>0.25 AND ret_20>0.30) OR upper_wick>=0.035 OR anchor_age>25",
                       "F4": "spread>=0.005; PB range<=0.045 and open_close>=-0.015; RA open_close>0 and d_vr5<=3 and close_vs_trailing30_high>=-0.08; Rebuild open_close>=0 and range<=0.06",
                       "F5": "crowding is full-A V1.2 raw union count; fixed brake blocks crowding>=500; fixed low flag crowding<=240; rolling exact prior 60 market-session P25/P75 uses shift(1), min_periods=60"},
        "feature_allowlist": feature_allowlist,
        "target_columns": list(TARGET_COLUMNS) + ["target_t5_train_label"],
        "meta_columns": ["trade_date", "ts_code", "market_type", "market_session_index",
                         "candidate_population", "clean_train_candidate", "train_label_known",
                         "train_fit_mask", "clean_oos_candidate", "split_role",
                         "canonical_k_group", "repair_episode_group"],
        "projection_schema": projection_schema,
        "population": population,
        "split_guard": {key: value for key, value in split_guard.items() if not key.endswith("mask")},
        "formula_counts": {key: value for key, value in f1_f4_meta.items() if isinstance(value, (int, float, str))},
        "f5": f5_meta,
        "shard_limit_bytes_exclusive": max_shard_bytes_exclusive,
        "shards": shards,
        **FLAGS,
    }
    payload = json.dumps(act009._json_safe(manifest), ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False).encode("utf-8") + b"\n"
    _atomic_bytes(output_dir / "dataset_local_manifest.json", payload)
    return manifest


def _rank_clean_probabilities(frame: Any) -> Any:
    """Rank the two fixed B+F5 estimates within the clean OOS pool."""
    import numpy as np
    import pandas as pd

    out = frame.copy()
    clean = out["clean_union"].fillna(False).astype(bool)
    for score_column, rank_column in (("p_b_lr", "b_f5_lr_rank"),
                                      ("p_b_hgb", "b_f5_hgb_rank")):
        out[rank_column] = np.nan
        score = pd.to_numeric(out[score_column], errors="coerce")
        eligible = clean & np.isfinite(score)
        for _day, group in out.loc[eligible].groupby("trade_date", sort=True):
            ranked = group.assign(_rank_score=pd.to_numeric(group[score_column], errors="coerce"))
            ranked = ranked.sort_values(["_rank_score", "ts_code"], ascending=[False, True], kind="mergesort")
            out.loc[ranked.index, rank_column] = np.arange(1, len(ranked) + 1, dtype=int)
    return out


def _comparison_methods() -> list[tuple[str, str | None, int | None, str | None]]:
    methods: list[tuple[str, str | None, int | None, str | None]] = [
        ("CLEAN_HARD_UNION", None, None, None),
        ("CLEAN_HARD_UNION_F5", "f5_pass", None, None),
        ("CLEAN_HARD_ROLLING_LOW", "f5_rolling_low", None, None),
        ("CLEAN_HARD_ROLLING_HIGH", "f5_rolling_high", None, None),
        ("CLEAN_HARD_BREADTH", "breadth_over_50", None, None),
        ("CLEAN_HARD_ACTIVITY", "activity_over_prior20_median", None, None),
        ("CLEAN_HARD_TIMING", "timing_gate", None, None),
        ("CLEAN_B_RULE_ANY", "b_rule_any", None, None),
        ("CLEAN_B_RULE_ANY_F5", "b_rule_any_f5", None, None),
        ("CLEAN_B_RULE_ANY_BREADTH", "b_rule_any_breadth", None, None),
        ("CLEAN_B_RULE_ANY_ACTIVITY", "b_rule_any_activity", None, None),
        ("CLEAN_B_RULE_ANY_TIMING", "b_rule_any_timing", None, None),
        ("CLEAN_B_RULE_ANY_TIMING_F5", "b_rule_any_timing_f5", None, None),
    ]
    for top_k in act009.TOP_K:
        methods.extend([
            (f"CLEAN_S_RULE_TOP{top_k}", None, top_k, "s_rule_score"),
            (f"CLEAN_B_RULE_ANY_TOP{top_k}", "b_rule_any", top_k, "s_rule_score"),
            (f"CLEAN_B_RULE_ANY_F5_TOP{top_k}", "b_rule_any_f5", top_k, "s_rule_score"),
            (f"CLEAN_B_PLUS_F5_LR_TOP{top_k}", None, top_k, "p_b_lr"),
            (f"CLEAN_B_PLUS_F5_HGB_TOP{top_k}", None, top_k, "p_b_hgb"),
        ])
    return methods


def _build_oos_comparison(frame: Any, market_dates: list[str]) -> tuple[Any, Any, Any]:
    """Evaluate frozen clean pools and B+F5 rankings on every OOS market date."""
    import numpy as np
    import pandas as pd

    oos_dates = [day for day in market_dates if OOS_START <= day <= ASOF_DATE]
    by_day = {day: group for day, group in frame.groupby("trade_date", sort=False)}
    methods = _comparison_methods()
    daily_rows: list[dict[str, Any]] = []
    top20_rows: list[dict[str, Any]] = []
    pooled_parts: dict[tuple[str, int], list[Any]] = {(name, horizon): []
        for name, _filter, _top_k, _score in methods for horizon in act009.EVAL_HORIZONS}
    for day in oos_dates:
        group = by_day.get(day, frame.iloc[0:0])
        clean = group.loc[group["clean_union"].fillna(False).astype(bool)]
        for method, filter_column, top_k, score_column in methods:
            if method == "CLEAN_HARD_UNION":
                pool = clean
            elif filter_column is None:
                pool = clean
            else:
                eligible = group.get(filter_column, pd.Series(False, index=group.index))
                pool = clean.loc[eligible.fillna(False).astype(bool)]
            rankable = pool
            if score_column is not None:
                score = pd.to_numeric(pool.get(score_column), errors="coerce")
                rankable = pool.loc[np.isfinite(score)]
                if len(rankable):
                    rankable = rankable.assign(_rank_score=pd.to_numeric(rankable[score_column], errors="coerce"))
                    rankable = rankable.sort_values(["_rank_score", "ts_code"],
                                                    ascending=[False, True], kind="mergesort")
            selected = rankable.head(top_k) if top_k is not None else rankable
            if "_rank_score" in selected.columns:
                selected = selected.drop(columns=["_rank_score"])
            for horizon in act009.EVAL_HORIZONS:
                metrics = act009._metric_values(selected, horizon)
                benchmark = pd.to_numeric(group.get(f"benchmark_return_t{horizon}"), errors="coerce").dropna()
                benchmark_count = pd.to_numeric(group.get(f"benchmark_count_t{horizon}"), errors="coerce").dropna()
                daily_rows.append({"trade_date": day, "method": method,
                                   "candidate_pool_count": int(len(pool)),
                                   "rankable_count": int(len(rankable)),
                                   "ranker": score_column or "POOL", "top_k": top_k,
                                   "horizon_market_sessions": horizon,
                                   "same_d_benchmark_equal_weight_return": float(benchmark.iloc[0]) if len(benchmark) else None,
                                   "same_d_benchmark_valid_a_count": int(benchmark_count.iloc[0]) if len(benchmark_count) else 0,
                                   **metrics, "research_only": True})
                pooled_parts[(method, horizon)].append(selected)
            if method.endswith("TOP20") and len(selected):
                columns = ("trade_date", "ts_code", "market_type", "s_rule_score", "s_rule_branch",
                           "s_rule_rank", "pullback", "readvance", "rebuild", "union", "rebuild_v13",
                           "f1_exact", "f1_with_repair", "f2_exact", "f3_state", "f4_pullback_confirmed",
                           "f4_readvance_confirmed", "f4_rebuild_confirmed", "clean_union", "f5_pass",
                           "f5_rolling_low", "f5_rolling_high", "crowding", "crowding_rolling_p25",
                           "crowding_rolling_p75", "b1_state", "b2_state", "b3_state", "b_category",
                           "b_confirmed_state", "p_b_lr", "p_b_hgb", "b_f5_lr_rank", "b_f5_hgb_rank",
                           "t3_ret", "t5_ret", "t10_ret", "benchmark_return_t3", "benchmark_return_t5",
                           "benchmark_return_t10", "excess_return_t3", "excess_return_t5", "excess_return_t10",
                           "max_dd5", "max_dd10", "path_observable_t3", "path_observable_t5", "path_observable_t10")
                for rank, (_idx, candidate) in enumerate(selected.iterrows(), start=1):
                    top20_rows.append({"method": method, "rank": rank,
                                       **{name: candidate.get(name) for name in columns}})

    daily = pd.DataFrame(daily_rows)
    pooled_rows: list[dict[str, Any]] = []
    for method, _filter, top_k, score in methods:
        for horizon in act009.EVAL_HORIZONS:
            parts = pooled_parts[(method, horizon)]
            pooled = pd.concat(parts, axis=0) if parts else frame.iloc[0:0]
            metrics = act009._metric_values(pooled, horizon)
            daily_for_method = daily.loc[(daily["method"] == method)
                                         & (daily["horizon_market_sessions"] == horizon)]
            observed_returns = daily_for_method["mean_return"].dropna()
            observed_excess = daily_for_method["mean_excess_return"].dropna()
            pooled_rows.append({"method": method, "ranker": score or "POOL", "top_k": top_k,
                                "horizon_market_sessions": horizon, "oos_market_sessions": len(oos_dates),
                                "selected_days": int((daily_for_method["selected_count"] > 0).sum()),
                                "mean_daily_selected_count": float(daily_for_method["selected_count"].mean())
                                    if len(daily_for_method) else 0.0,
                                "date_equal_weight_mean_return": float(observed_returns.mean()) if len(observed_returns) else None,
                                "date_equal_weight_mean_excess_return": float(observed_excess.mean()) if len(observed_excess) else None,
                                **metrics, "research_only": True})
    return daily, pd.DataFrame(pooled_rows), pd.DataFrame(top20_rows)


def _daily_candidate_counts(frame: Any, market_dates: list[str]) -> Any:
    """Emit branch, F1-F5, breadth, and eligibility counts for each D."""
    import pandas as pd

    by_day = {day: group for day, group in frame.groupby("trade_date", sort=False)}
    flags = ("pullback", "readvance", "rebuild", "union", "rebuild_v13", "v13_candidate_union",
             "f1_exact", "f1_with_repair", "f2_exact", "f3_global_veto",
             "f4_pullback_confirmed", "f4_readvance_confirmed", "f4_rebuild_confirmed",
             "clean_pullback", "clean_readvance", "clean_rebuild", "clean_union",
             "b1_candidate", "b2_candidate", "b3_candidate")
    rows = []
    for day in market_dates:
        group = by_day.get(day)
        row: dict[str, Any] = {"trade_date": day, "a_share_rows": int(len(group)) if group is not None else 0,
                               "research_only": True}
        if group is None:
            for column in flags:
                row[f"{column}_count"] = 0
            row.update({"candidate_population_count": 0, "f3_veto_candidate_count": 0,
                        "f3_unknown_candidate_count": 0, "f3_allow_candidate_count": 0,
                        "crowding": 0, "crowding_rolling_p25": None, "crowding_rolling_p75": None,
                        "f5_fixed_low": False, "f5_fixed_high": False, "f5_pass": True,
                        "f5_rolling_low_count": 0, "f5_rolling_high_count": 0,
                        "breadth_known": False, "activity_known": False, "timing_gate": False})
        else:
            for column in flags:
                row[f"{column}_count"] = int(group[column].fillna(False).astype(bool).sum())
            population = group["union"].fillna(False).astype(bool) | group["v13_candidate_union"].fillna(False).astype(bool)
            row["candidate_population_count"] = int(population.sum())
            row["f3_veto_candidate_count"] = int((population & group["f3_state"].eq("VETO")).sum())
            row["f3_unknown_candidate_count"] = int((population & group["f3_state"].eq("UNKNOWN")).sum())
            row["f3_allow_candidate_count"] = int((population & group["f3_state"].eq("ALLOW")).sum())
            row["crowding"] = int(group["crowding"].iloc[0])
            for name in ("crowding_rolling_p25", "crowding_rolling_p75"):
                values = pd.to_numeric(group[name], errors="coerce").dropna()
                row[name] = float(values.iloc[0]) if len(values) else None
            row["f5_fixed_low"] = bool(group["f5_fixed_low"].iloc[0])
            row["f5_fixed_high"] = bool(group["f5_fixed_high"].iloc[0])
            row["f5_pass"] = bool(group["f5_pass"].iloc[0])
            row["f5_rolling_low_count"] = int((group["clean_union"].fillna(False).astype(bool)
                                                    & group["f5_rolling_low"]).sum())
            row["f5_rolling_high_count"] = int((group["clean_union"].fillna(False).astype(bool)
                                                     & group["f5_rolling_high"]).sum())
            row["breadth_known"] = bool(group["breadth_known"].fillna(False).any())
            row["activity_known"] = bool(group["activity_timing_known"].fillna(False).any())
            row["timing_gate"] = bool(group["timing_gate"].fillna(False).any())
            for name in ("market_breadth_up_fraction", "market_activity_fraction",
                         "market_activity_prior20_median"):
                values = pd.to_numeric(group[name], errors="coerce").dropna()
                row[name] = float(values.iloc[0]) if len(values) else None
        rows.append(row)
    return pd.DataFrame(rows)


def _d19_full_a_comparison(frame: Any) -> Any:
    """Export the specifically authorized one-day full-A comparison only."""
    day = frame.loc[frame["trade_date"].eq("20261119")].copy()
    if not len(day):
        raise Act009BError("D19_REFERENCE_FULL_A_ROWS_MISSING")
    day["clean_union_top200_t1_hit"] = (day["clean_union"].fillna(False).astype(bool)
                                        & day["top200_member_t1"].fillna(False).astype(bool))
    columns = ("trade_date", "ts_code", "market_type", *RAW_INPUT_COLUMNS,
               "top200_rank", "top200_membership", "top200_rank_source", "top200_rank_t1",
               "top200_member_t1", "top200_source_t1", "clean_union_top200_t1_hit",
               "pullback", "readvance", "rebuild", "union",
               "rebuild_v13", "v13_candidate_union", "f1_exact", "f1_with_repair", "f2_exact",
               "f3_state", "f4_pullback_confirmed", "f4_readvance_confirmed", "f4_rebuild_confirmed",
               "clean_pullback", "clean_readvance", "clean_rebuild", "clean_union", "crowding",
               "f5_fixed_low", "f5_fixed_high", "f5_pass", "crowding_rolling_p25", "crowding_rolling_p75",
               "b1_state", "b2_state", "b3_state", "b_category", "s_rule_score", "s_rule_rank",
               "b1_candidate", "b2_candidate", "b3_candidate", "b_confirmed_state",
               "f5_rolling_low", "f5_rolling_high", "p_b_lr", "p_b_hgb",
               "b_f5_lr_rank", "b_f5_hgb_rank",
               "t1_ret", "t3_ret", "t5_ret", "t10_ret", "max_dd5", "max_dd10")
    available = [name for name in dict.fromkeys(columns) if name in day.columns]
    return day.loc[:, available].sort_values("ts_code", kind="mergesort").reset_index(drop=True)


def _write_csv(path: Path, frame: Any) -> int:
    temporary = path.with_name(path.name + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8", lineterminator="\n",
                 na_rep="", float_format="%.17g")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    temporary.replace(path)
    return int(len(frame))


def _append_progress(path: Path, stage: str, status: str,
                     details: dict[str, Any] | None = None) -> None:
    event = {"at_utc": datetime.now(timezone.utc).isoformat(), "stage": stage,
             "status": status, "details": details or {}}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(act009._json_safe(event), ensure_ascii=False,
                                sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(act009._json_safe(value), ensure_ascii=False, sort_keys=True,
                         indent=2, allow_nan=False).encode("utf-8") + b"\n"
    _atomic_bytes(path, payload)


def _validate_output_dir(output_dir: Path, data_root: Path) -> Path:
    output_dir, data_root = Path(output_dir), Path(data_root)
    if not output_dir.is_absolute() or output_dir.is_symlink():
        raise Act009BError("OUTPUT_DIR_MUST_BE_ABSOLUTE_NON_SYMLINK")
    resolved, root = output_dir.resolve(strict=False), data_root.resolve(strict=False)
    if resolved == root or root in resolved.parents or resolved in root.parents:
        raise Act009BError("OUTPUT_DIR_OVERLAPS_PANEL_DATA_ROOT")
    if not resolved.parent.is_dir():
        raise Act009BError("OUTPUT_DIR_PARENT_MISSING")
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise Act009BError("OUTPUT_DIR_MUST_BE_EMPTY")
    else:
        resolved.mkdir(parents=False, exist_ok=False)
    return resolved


def _assert_fixed_windows(study_dates: list[str]) -> None:
    half = [day for day in study_dates if "20260506" <= day <= ASOF_DATE]
    oos = [day for day in study_dates if OOS_START <= day <= ASOF_DATE]
    if len(study_dates) != EXPECTED_SESSIONS:
        raise Act009BError(f"MARKET_SESSION_COUNT_MISMATCH:{len(study_dates)}:{EXPECTED_SESSIONS}")
    if len(half) != act009.HALF_YEAR_SESSION_COUNT:
        raise Act009BError(f"HALF_YEAR_SESSION_COUNT_MISMATCH:{len(half)}")
    if len(oos) != act009.OOS_DATE_COUNT:
        raise Act009BError(f"OOS_SESSION_COUNT_MISMATCH:{len(oos)}")


def _apply_study_window_counts(frame: Any, f1_f4_meta: dict[str, Any],
                               f5_meta: dict[str, Any]) -> None:
    """Report formula and rolling counts on the frozen study window, not prep rows."""
    study = frame.loc[frame["trade_date"].between(START_DATE, ASOF_DATE)]
    for column, key in (("clean_union", "clean_union_rows"), ("f1_exact", "f1_exact_rows"),
                        ("f1_with_repair", "f1_with_repair_rows"), ("f2_exact", "f2_rows"),
                        ("f3_global_veto", "f3_veto_rows"),
                        ("f4_pullback_confirmed", "f4_pullback_rows"),
                        ("f4_readvance_confirmed", "f4_readvance_rows"),
                        ("f4_rebuild_confirmed", "f4_rebuild_rows")):
        f1_f4_meta[key] = int(study[column].fillna(False).astype(bool).sum())
    f1_f4_meta["f1_unknown_rows"] = int((~study["f1_known"].fillna(False).astype(bool)).sum())
    f1_f4_meta["f2_unknown_rows"] = int((~study["f2_known"].fillna(False).astype(bool)).sum())
    f1_f4_meta["f3_veto_rows"] = int((study["f3_state"] == "VETO").sum())
    f1_f4_meta["f3_allow_rows"] = int((study["f3_state"] == "ALLOW").sum())
    f1_f4_meta["f3_unknown_rows"] = int((study["f3_state"] == "UNKNOWN").sum())
    f1_f4_meta["count_window"] = [START_DATE, ASOF_DATE]
    by_day = study.drop_duplicates("trade_date")
    f5_meta["study_rolling_p25_known_dates"] = int(by_day["crowding_rolling_p25"].notna().sum())
    f5_meta["study_rolling_p75_known_dates"] = int(by_day["crowding_rolling_p75"].notna().sum())
    f5_meta["study_max_market_union_count"] = int(by_day["crowding"].max()) if len(by_day) else 0
    f5_meta["study_window"] = [START_DATE, ASOF_DATE]


def _run_pipeline(*, data_root: Path, official_top200_path: Path, output_dir: Path,
                  bind_summary: dict[str, Any]) -> dict[str, Any]:
    """Read one bound panel, publish prefit candidate shards, then run the fixed two B fits."""
    import numpy as np
    import pandas as pd

    output_dir = Path(output_dir)
    progress_path = output_dir / "run_progress.jsonl"
    source_summary = dict(bind_summary)
    run_summary: dict[str, Any] = {
        "schema": SCHEMA, "run_id": RUN_ID, "status": "RUNNING",
        "mode": "candidate_export_then_two_fixed_b_fits",
        "windows": {"dataset_D": [START_DATE, ASOF_DATE], "train_D": [START_DATE, TRAIN_END],
                    "oos_D": [OOS_START, ASOF_DATE]},
        "input_binding": source_summary["binding"], "output_dir": str(output_dir),
        "fit_plan": {"S": 0, "B": 2, "search": 0}, **FLAGS,
    }
    _write_json_atomic(output_dir / "run_summary.json", run_summary)
    _append_progress(progress_path, "run", "STARTED", run_summary["fit_plan"])
    try:
        official, official_meta = v12.read_official_top200(Path(official_top200_path))
        _check_official_source(official_meta)
        _append_progress(progress_path, "official_top200", "READ_PASS", official_meta)
        with v12.bind_current_panels(Path(data_root)) as (panel_path, source, recheck):
            binding = act009._assert_bound_source(source)
            if str(source.get("asof_date")) != ASOF_DATE:
                raise Act009BError("BOUND_PANEL_ASOF_MISMATCH")
            _append_progress(progress_path, "panel_binding", "BOUND_EXPECTED_GENERATION",
                             {"panel_path": str(panel_path), "binding": binding})
            prep_start = (datetime.strptime(START_DATE, "%Y%m%d")
                          - timedelta(days=act009.PREP_CALENDAR_DAYS)).strftime("%Y%m%d")
            frame, panel_read = v12._read_panel(panel_path, start_date=prep_start,
                                                asof_date=ASOF_DATE, warmup_days=180)
            if not len(frame):
                raise Act009BError("A_SHARE_PANEL_ROWS_EMPTY_IN_REQUESTED_WINDOW")
            _append_progress(progress_path, "panel_read", "PROJECTED_READER_PASS", panel_read)
            frame, vector_meta = v12._vectorize_rows(frame, start_date=prep_start,
                                                      asof_date=ASOF_DATE)
            market_dates = list(frame.attrs.get("market_dates", []))
            if not market_dates:
                raise Act009BError("MARKET_SESSION_LIST_EMPTY")
            study_dates = [day for day in market_dates if day >= START_DATE]
            _assert_fixed_windows(study_dates)
            frame, top200_meta = v12._apply_top200_ranks(frame, official, official_meta)
            frame = v12._join_future_top200(frame)
            frame, market_meta = act009._attach_exact_market_features(frame, market_dates)
            frame, rebuild_meta = act009._derive_rebuild_v13(frame, market_dates)
            frame["v13_candidate_union"] = (frame["pullback"].fillna(False).astype(bool)
                                             | frame["readvance"].fillna(False).astype(bool)
                                             | frame["rebuild_v13"].fillna(False).astype(bool))
            frame, s_rule_meta = act009._apply_s_rule(frame)
            frame, b_meta = act009._add_b_confirmations(frame)
            frame, f1_f4_meta = _add_f1_f4(frame)
            frame, f5_meta = _add_f5_crowding(frame, market_dates)
            _apply_study_window_counts(frame, f1_f4_meta, f5_meta)
            frame, label_meta = act009._add_b_training_labels(
                frame, market_dates, candidate_column="clean_union")
            frame, benchmark_meta = act009._attach_horizon_benchmarks(frame)
            frame = _attach_target_contract(frame, market_dates)
            frame, split = act009._episode_split(frame, candidate_column="clean_union")
            recheck()
            projection = _feature_export_frame(frame, market_dates, split)
            manifest = _publish_dataset_manifest(
                projection, output_dir, binding=binding, panel_source=source,
                official_meta=official_meta, market_dates=market_dates, study_dates=study_dates,
                split_guard=split, f1_f4_meta=f1_f4_meta, f5_meta=f5_meta)
            _append_progress(progress_path, "dataset_export", "PREFIT_MANIFEST_PUBLISHED",
                             {"path": str(output_dir / "dataset_local_manifest.json"),
                              "rows": len(projection), "shards": len(manifest["shards"]),
                              "max_shard_bytes": max(item["bytes"] for item in manifest["shards"])})
            # Ensure the prefit artifact is complete before either estimator begins.
            if not (output_dir / "dataset_local_manifest.json").is_file():
                raise Act009BError("PREFIT_DATASET_MANIFEST_NOT_PUBLISHED")

            feature_frame = frame.copy()
            population = feature_frame["union"].fillna(False).astype(bool) | feature_frame[
                "v13_candidate_union"].fillna(False).astype(bool)
            feature_frame["b_rule_any"] = (feature_frame[["b1_candidate", "b2_candidate", "b3_candidate"]]
                                           .fillna(False).astype(bool).any(axis=1))
            feature_frame["f5_pass"] = feature_frame["f5_pass"].fillna(False).astype(bool)
            feature_frame["b_rule_any_f5"] = feature_frame["b_rule_any"] & feature_frame["f5_pass"]
            feature_frame["b_rule_any_breadth"] = (feature_frame["b_rule_any"]
                                                    & feature_frame["breadth_over_50"].fillna(False).astype(bool))
            feature_frame["b_rule_any_activity"] = (feature_frame["b_rule_any"]
                                                     & feature_frame["activity_over_prior20_median"].fillna(False).astype(bool))
            feature_frame["b_rule_any_timing"] = (feature_frame["b_rule_any"]
                                                   & feature_frame["timing_gate"].fillna(False).astype(bool))
            feature_frame["b_rule_any_timing_f5"] = feature_frame["b_rule_any_timing"] & feature_frame["f5_pass"]
            models, model_report, predictions = act009._fit_b_rankers(
                feature_frame, split, panel_source=source, official_meta=official_meta,
                checkpoint_path=output_dir / "model_state.joblib",
                progress=lambda stage, status, details: _append_progress(progress_path, stage, status, details),
                feature_names=F5_B_FEATURE_NAMES)
            for column in predictions:
                feature_frame[column] = predictions[column]
            feature_frame = _rank_clean_probabilities(feature_frame)
            recheck()

            candidate_counts = _daily_candidate_counts(feature_frame, study_dates)
            daily, pooled, top20 = _build_oos_comparison(feature_frame, study_dates)
            d19 = _d19_full_a_comparison(feature_frame)
            outputs = {
                "CODEX_MAC_ACT-009B_daily_candidate_counts.csv": candidate_counts,
                "CODEX_MAC_ACT-009B_oos_comparison_daily.csv": daily,
                "CODEX_MAC_ACT-009B_oos_comparison_pooled.csv": pooled,
                "CODEX_MAC_ACT-009B_oos_top20_daily.csv": top20,
                "CODEX_MAC_ACT-009B_d19_full_a_comparison.csv": d19,
            }
            output_rows = {name: _write_csv(output_dir / name, table) for name, table in outputs.items()}
            model_report.update({
                "input_binding": binding, "panel_read": panel_read, "vectorizer": vector_meta,
                "market_features": market_meta, "rebuild_v13": rebuild_meta,
                "s_rule": s_rule_meta, "b_confirmations": b_meta,
                "f1_f4": f1_f4_meta, "f5_crowding": f5_meta,
                "b_target": label_meta, "benchmark_contract": benchmark_meta,
                "top200_rank_contract": top200_meta,
                "dataset_manifest": {"path": str(output_dir / "dataset_local_manifest.json"),
                                     "rows": len(projection), "shards": manifest["shards"]},
                "comparison_methods": [item[0] for item in _comparison_methods()],
                "oos_comparison_pooled": pooled.to_dict(orient="records"),
                "d19_reference": {"date": "20261119", "full_a_rows": len(d19),
                                   "v12_union_rows": int(d19["union"].fillna(False).astype(bool).sum()),
                                   "clean_union_rows": int(d19["clean_union"].fillna(False).astype(bool).sum()),
                                   "official_t1_top200_members_in_full_a": int(d19["top200_member_t1"].fillna(False).astype(bool).sum()),
                                   "clean_union_t1_top200_hits": int(d19["clean_union_top200_t1_hit"].sum())},
                "s_rule_comparison_convention": "ACT009 S percentiles/rank are computed on the pre-clean V1.3 union, then restricted to clean_union for ranking comparisons.",
                "output_contract": {**FLAGS, "S_fit_count": 0, "B_fit_count": 2,
                                    "hyperparameter_search_count": 0,
                                    "horizons": list(act009.EVAL_HORIZONS), "top_k": list(act009.TOP_K),
                                    "oos_session_count": act009.OOS_DATE_COUNT,
                                    "model_feature_names": list(F5_B_FEATURE_NAMES)},
            })
            _write_json_atomic(output_dir / "model_metrics.json", model_report)
            act009._save_model_state(output_dir / "model_state.joblib", models, model_report,
                                     source, official_meta, feature_names=F5_B_FEATURE_NAMES)
            artifacts = {name: {"bytes": (output_dir / name).stat().st_size,
                                "sha256": act009._sha_file(output_dir / name)}
                         for name in [*outputs, "dataset_local_manifest.json", "model_metrics.json", "model_state.joblib"]}
            run_summary.update({"status": "FIT_COMPLETED", "fit_count": model_report["fit_count"],
                                "S_fit_count": model_report["S_fit_count"],
                                "B_fit_count": model_report["B_fit_count"],
                                "hyperparameter_search_count": model_report["hyperparameter_search_count"],
                                "panel_source": source, "panel_read": panel_read,
                                "official_top200_source": official_meta,
                                "dataset_manifest_status": manifest["status"],
                                "dataset_rows": len(projection), "dataset_shards": manifest["shards"],
                                "split_guard": model_report["split_guard"],
                                "training_rows": model_report["training"],
                                "fit_policy": model_report["fit_policy"],
                                "output_rows": output_rows, "artifact_receipts": artifacts,
                                "censor_policy": "EXACT_A_MARKET_SESSION_OFFSETS_ONLY; MISSING_T+n_BAR_REMAINS_CENSORED",
                                "next_action": "ROOT_OWNS_RESULT_REVIEW_AND_DRIVE_DELIVERY; RESEARCH_ONLY"})
            _write_json_atomic(output_dir / "run_summary.json", run_summary)
            recheck()
            _append_progress(progress_path, "source_recheck", "PASS_AFTER_EXPORT", {"binding": binding})
            _append_progress(progress_path, "run", "OUTPUTS_COMPLETE",
                             {"fit_count": model_report["fit_count"], "output_dir": str(output_dir)})
            return run_summary
    except Exception as exc:
        run_summary.update({"status": "FAILED", "failure": {"type": type(exc).__name__, "reason": str(exc)}})
        try:
            _append_progress(progress_path, "run", "FAILED", {"type": type(exc).__name__, "reason": str(exc)})
            _write_json_atomic(output_dir / "run_summary.json", run_summary)
        except OSError:
            pass
        raise


def _check_official_source(official_meta: dict[str, Any]) -> None:
    actual = {key: official_meta.get(key) for key in ("sha256", "bytes", "rows", "asof_date")}
    expected = act009.EXPECTED_OFFICIAL_TOP200
    if actual != expected:
        raise Act009BError(f"OFFICIAL_TOP200_BINDING_MISMATCH:expected={expected!r}:actual={actual!r}")


def bind_only(data_root: Path) -> dict[str, Any]:
    """Verify current V4 source identity without reading panel rows."""
    data_root = Path(data_root)
    if not data_root.is_absolute():
        raise Act009BError("DATA_ROOT_MUST_BE_ABSOLUTE")
    with v12.bind_current_panels(data_root) as (panel_path, source, recheck):
        binding = act009._assert_bound_source(source)
        recheck()
    return {"schema": SCHEMA, "status": "PASS", "mode": "INPUT_BINDING_ONLY",
            "panel_path": str(panel_path), "binding": binding,
            "row_read": False, "fit_count": 0, **FLAGS}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--official-top200", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--bind-only", action="store_true",
                        help="verify the expected V4 generation without reading rows or fitting")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.bind_only:
            result = bind_only(args.data_root)
            print(json.dumps(act009._json_safe(result), ensure_ascii=False, sort_keys=True))
            return 0
        if args.official_top200 is None or args.output_dir is None:
            raise Act009BError("OFFICIAL_TOP200_AND_OUTPUT_DIR_REQUIRED_FOR_RUN")
        if not Path(args.data_root).is_absolute():
            raise Act009BError("DATA_ROOT_MUST_BE_ABSOLUTE")
        output_dir = _validate_output_dir(args.output_dir, args.data_root)
        # This bind is metadata only. The full run reopens once and reads the panel exactly once.
        binding = bind_only(args.data_root)
        result = _run_pipeline(data_root=args.data_root, official_top200_path=args.official_top200,
                               output_dir=output_dir, bind_summary=binding)
        print(json.dumps({"status": result["status"], "fit_count": result["fit_count"],
                          "dataset_rows": result["dataset_rows"], "output_dir": result["output_dir"]},
                         ensure_ascii=False, sort_keys=True))
        return 0
    except (Act009BError, act009.Act009Error, v12.StudyError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
