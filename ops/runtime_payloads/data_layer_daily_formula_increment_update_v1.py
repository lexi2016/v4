
from __future__ import annotations

import argparse
import ast
import csv
import base64
import gc
import hashlib
import importlib.util
import json
import math
import os
import re
import runpy
import shutil
import struct
import subprocess
import sys
import time
import traceback
import warnings
import zipfile
from collections import Counter
from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

try:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
except Exception as exc:
    print("pyarrow import failed:", repr(exc))
    raise

try:
    import psutil
except Exception:
    psutil = None


TASK_NAME = "data_layer_daily_formula_increment_update_v1"
DAILY_FORMULA_LOOKBACK_RECORDS = 260
DAILY_FORMULA_MAX_WORKERS = 4
DAILY_FORMULA_PARALLEL_MIN_SYMBOLS = 500
MAX_CROSS_DAY_CLOSE_RATIO = 1.5

TDX_ROOT = Path(r"C:\new_tdx_mock")
DATA_ROOT = Path(r"C:\Users\huang\Desktop\学习\数据")
TDX_INDUSTRY_NAMES = TDX_ROOT / "T0002" / "hq_cache" / "tdxzs.cfg"
TDX_STOCK_INDUSTRIES = TDX_ROOT / "T0002" / "hq_cache" / "tdxhy.cfg"
XDXR_CACHE_ROOT = DATA_ROOT / "runtime" / "cache" / TASK_NAME / "tdx_xdxr"
RULES_FILE = Path(r"C:\Users\huang\Desktop\学习\agents调试\数据层\DATA_LAYER_AGENTS_RULES.md")
RETURN_ROOT = Path(r"C:\Users\huang\Desktop\学习\agents调试\数据层") / TASK_NAME

SELECTOR_POINTER = DATA_ROOT / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"
BACKTEST_POINTER = DATA_ROOT / "backtest_panel_interface_current" / "CURRENT_BACKTEST_BASE_PANEL.txt"

SCRIPT_DIR = DATA_ROOT / "tools" / "debug_scripts" / TASK_NAME
PROMOTED_SELECTOR_ROOT = DATA_ROOT / "selector_ready_panels" / TASK_NAME
PROMOTED_BACKTEST_ROOT = DATA_ROOT / "backtest_panels" / TASK_NAME
CONTRACT_DIR = DATA_ROOT / "tools" / "debug_scripts" / "research_panel_contract_20260528_authoritative_v0"
CONTRACT_CSV = CONTRACT_DIR / "authoritative_field_contract_v0.csv"

# The v1.9.2 selector consumes the canonical main-chart formula fields.  Keep
# the authority read-only and load only its pure partition function; do not
# invoke its pointer/output-producing ``main`` entry point.
CANONICAL_FORMULA_PATH = Path(
    r"C:\Users\huang\Desktop\学习\数据\tools\debug_scripts\research_panel_formula_canonical_20260515\build_canonical_formula_research_panel.py"
)
CANONICAL_FORMULA_SOURCE = "computed_main_chart_formula_20260515"
V192_ENTRY_FIELDS = (
    "gold_brick_context",
    "brick_resonance_context",
    "brick_buy",
    "brick_buy1_low_absorb",
    "brick_buy2_attack",
    "primary_buy_signal",
    "secondary_buy_signal",
)
V192_INTERMEDIATE_FIELDS = (
    "brick_exist_b",
    "brick_resonance1",
    "brick_resonance2",
    "brick_resonance",
)
V192_FORMULA_FIELDS = (
    *V192_ENTRY_FIELDS,
    *V192_INTERMEDIATE_FIELDS,
    "BG",
    "B1",
    "B2",
    "B3",
    "route_context",
    "brick_context",
    "break_prev_high",
    "breakout",
    "double_breakout",
    "breakout_cross_star",
    "formula_source",
)
V192_REQUIRED_CANONICAL_PROJECTION_FIELDS = (
    "kdj_d",
    "ref_score_close_up",
    "ref_score_above_bbi",
    "ref_score_no_giant_true_yin",
    "ref_score_trend_up",
    "ref_score_j_no_dead_cross",
    "ref_hold_score",
    "brick_original_b1",
    "brick_pullback_white_b",
    "brick_pullback_yellow_b",
    "brick_oversold_shrink_b",
    "brick_oversold_super_shrink_b",
    "brick_strong_red",
    "brick_red_today",
    "macd_above_zero_second_gold",
    "macd_top_divergence",
    "white_yellow_death_cross",
    "fd_volume_yin",
    "break_yesterday_keyline",
    "plry_first",
)

# Output directory: timestamped run_dir under RETURN_ROOT to avoid stale failure_report/run.log mixing.
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
RUN_DIR = RETURN_ROOT / RUN_TS

FORBIDDEN_FUTURE_PATTERNS = [
    "future", "fwd", "forward", "next_", "nextopen", "nextclose",
    "winner", "label_", "target", "posthoc", "max_future", "future_ret",
]

CRITICAL_SELECTOR_FORMULA_COLUMNS = [
    "BG", "B1", "B2", "B3", "route_context",
    "brick_context", "brick_resonance_context", "gold_brick_context", "ref_hold_score",
    "ma30", "ma40", "ma60", "bar_close_pos",
    "BBI", "zge_white_line", "zge_yellow_line", "J", "macd_dif", "macd_dea", "macd_hist",
    *V192_ENTRY_FIELDS,
    *V192_INTERMEDIATE_FIELDS,
]

CRITICAL_BASE_COLUMNS = ["ts_code", "trade_date", "open", "high", "low", "close"]

STATIC_MAP_CANDIDATES = [
    "name", "stock_name", "industry", "sub_industry", "concept",
    "tdx_industry_code", "tdx_industry_name",
    "market_type", "exchange", "trade_currency", "is_a_share", "is_bj", "is_hk_connect",
    "list_date", "area", "sector", "board", "market_cap", "float_market_cap",
    "is_st", "is_new_stock", "bars_since_list",
]

FORMULA_LIKE_TOKENS = [
    "zsig", "BG", "B1", "B2", "B3", "BUY", "PRE_", "KEY_", "BASEOK",
    "GOLD", "BRICK", "brick", "breakout", "score", "formula",
    "hold", "macd", "kdj", "rsi", "white", "yellow", "bbi", "trend",
    "DOUBLE", "double", "signal", "zge_", "HAS_B",
]

CONTRACT_ALLOWED_CURRENT = {"yes"}
CONTRACT_REVIEW_CURRENT = {"review"}
CONTRACT_CONTEXT_ACTIONS = {"context_only"}
CONTRACT_SIDECAR_ACTIONS = {"sidecar_only", "compat_only", "manifest_only"}
CONTRACT_OFFICIAL_ACTIONS = {"official_current", "official_guarded"}
CONTRACT_RUNTIME_DROP_COLUMNS = {
    "ref_b123_union_debug",
    "ref_hold_score",
    "BUY1",
    "BUY2",
    "HAS_B",
    "DOUBLE_BREAK",
    "KEY_K",
    "BASEOK",
    "PRE_ABN",
    "source_panel_path",
    "panel_role",
    "formula_source",
}

CONTRACT_ALIAS_DROP_CANDIDATES = {
    "close_higher_than_prev",
    "close_lower_than_prev",
    "breakout",
    "double_breakout",
}

CONTRACT_REQUIRED_CONTEXT_COLUMNS = {
    "BG",
    "B1",
    "B2",
    "B3",
    "route_context",
    "brick_context",
    "brick_resonance_context",
    "gold_brick_context",
}

CONTRACT_REQUIRED_V192_SELECTOR_COLUMNS = {
    *V192_ENTRY_FIELDS,
    *V192_INTERMEDIATE_FIELDS,
    "formula_source",
}

CONTRACT_PROVENANCE_FIELD_DEFAULTS = {
    "formula_source": CANONICAL_FORMULA_SOURCE,
    "field_contract_version": "authoritative_field_contract_v0_2_phase1",
    "source_panel_path": "",
    "panel_role": "AUTO_UPDATE_DAILY_FORMULA_INCREMENT_V1",
}

CONTRACT_LINEAGE_FIELDS = set(CONTRACT_PROVENANCE_FIELD_DEFAULTS)

CONTRACT_ENFORCED_DROP_REPORT_COLUMNS = sorted(
    CONTRACT_RUNTIME_DROP_COLUMNS | CONTRACT_ALIAS_DROP_CANDIDATES | CONTRACT_LINEAGE_FIELDS
)

_CANONICAL_FORMULA_MODULE: Any = None


def _load_canonical_formula_module() -> Any:
    """Load the read-only canonical module without invoking its I/O entrypoint."""

    global _CANONICAL_FORMULA_MODULE
    if _CANONICAL_FORMULA_MODULE is not None:
        return _CANONICAL_FORMULA_MODULE
    if not CANONICAL_FORMULA_PATH.is_file():
        raise RuntimeError(f"canonical v1.9.2 formula authority missing: {CANONICAL_FORMULA_PATH}")
    spec = importlib.util.spec_from_file_location("v192_canonical_formula_authority", CANONICAL_FORMULA_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load canonical v1.9.2 formula authority")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "compute_partition_formula"):
        raise RuntimeError("canonical v1.9.2 formula authority lacks compute_partition_formula")
    _CANONICAL_FORMULA_MODULE = module
    return module


def _compute_canonical_v192_formula(hist: pd.DataFrame) -> pd.DataFrame:
    if hist.empty:
        return hist.copy()
    canonical_input = hist.copy()
    if "volume" not in canonical_input.columns:
        if "vol" not in canonical_input.columns:
            raise RuntimeError("canonical v1.9.2 formula requires volume/vol input")
        canonical_input["volume"] = canonical_input["vol"]
    canonical = _load_canonical_formula_module().compute_partition_formula(canonical_input)
    canonical = canonical.reset_index(drop=True)
    if len(canonical) != len(canonical_input):
        raise RuntimeError(
            f"canonical v1.9.2 formula row count mismatch: input={len(canonical_input)} output={len(canonical)}"
        )
    key_input = canonical_input[["ts_code", "trade_date"]].reset_index(drop=True).astype(str)
    key_output = canonical[["ts_code", "trade_date"]].reset_index(drop=True).astype(str)
    if not key_input.equals(key_output):
        raise RuntimeError("canonical v1.9.2 formula changed input row order")
    canonical["primary_buy_signal"] = (
        canonical["brick_buy2_attack"].eq(1)
        | canonical["B3"].eq(1)
        | canonical["double_breakout"].eq(1)
    ).astype(np.int8)
    canonical["secondary_buy_signal"] = (
        canonical["brick_buy1_low_absorb"].eq(1)
        | canonical["B2"].eq(1)
        | canonical["breakout_cross_star"].eq(1)
    ).astype(np.int8)
    canonical["formula_source"] = CANONICAL_FORMULA_SOURCE
    return canonical


def _v192_truthy(value: Any) -> bool:
    """Match the frozen feature/role oracle scalar truthy contract."""

    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value.strip().lower() in {"1", "1.0", "true", "t", "yes", "y"}
    try:
        return float(value) != 0.0
    except (TypeError, ValueError):
        return False


def v192_entry_pool(frame: pd.DataFrame) -> pd.Series:
    """Return the frozen seven-entry OR mask with gold text kept non-truthy."""

    result = pd.Series(False, index=frame.index, dtype=bool)
    for field in V192_ENTRY_FIELDS:
        if field in frame.columns:
            result = result | frame[field].map(_v192_truthy).astype(bool)
    return result


def _v192_contract_issues(frame: pd.DataFrame) -> list[str]:
    missing = sorted(CONTRACT_REQUIRED_V192_SELECTOR_COLUMNS - set(frame.columns))
    issues = [f"v1.9.2 entry fields missing:{','.join(missing)}"] if missing else []
    if "formula_source" in frame.columns:
        source = frame["formula_source"].fillna("").astype(str).str.strip()
        if source.ne(CANONICAL_FORMULA_SOURCE).any():
            issues.append("v1.9.2 formula_source must be computed_main_chart_formula_20260515")
    numeric_fields = [field for field in (*V192_ENTRY_FIELDS, *V192_INTERMEDIATE_FIELDS) if field != "gold_brick_context"]
    for field in numeric_fields:
        if field not in frame.columns:
            continue
        values = pd.to_numeric(frame[field], errors="coerce")
        if values.isna().any() or (~values.isin([0, 1])).any():
            issues.append(f"v1.9.2 signal field invalid:{field}")
    if "gold_brick_context" in frame.columns:
        gold = frame["gold_brick_context"].fillna("").astype(str).str.strip()
        if (~gold.isin(["none", "old_gold_candidate"])).any():
            issues.append("v1.9.2 gold_brick_context must be none/old_gold_candidate")
    return issues


def load_authoritative_contract_rows(contract_csv: Path) -> list[dict[str, str]]:
    if not contract_csv.exists():
        raise FileNotFoundError(f"contract csv missing: {contract_csv}")
    with contract_csv.open("r", encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if row.get("column")]


def build_contract_policy(contract_rows: list[dict[str, str]], contract_csv: Path) -> dict[str, Any]:
    by_column = {row["column"]: row for row in contract_rows}
    official_current_columns = {
        row["column"]
        for row in contract_rows
        if row.get("allowed_in_current") in CONTRACT_ALLOWED_CURRENT
        and row.get("script_action") in CONTRACT_OFFICIAL_ACTIONS | CONTRACT_CONTEXT_ACTIONS
    }
    review_columns = {
        row["column"]
        for row in contract_rows
        if row.get("allowed_in_current") in CONTRACT_REVIEW_CURRENT
    }
    sidecar_columns = {
        row["column"]
        for row in contract_rows
        if row.get("script_action") in CONTRACT_SIDECAR_ACTIONS
    }
    context_columns = {
        row["column"]
        for row in contract_rows
        if row.get("script_action") in CONTRACT_CONTEXT_ACTIONS
    }
    lineage_columns = {
        row["column"]
        for row in contract_rows
        if row.get("draft_role") == "lineage_meta"
    }
    alias_columns = {
        row["column"]
        for row in contract_rows
        if row.get("draft_role") == "alias_compat"
    }
    debug_columns = {
        row["column"]
        for row in contract_rows
        if row.get("draft_role") == "debug_only"
    }
    reference_columns = {
        row["column"]
        for row in contract_rows
        if row.get("draft_role") == "reference_only"
    }
    forced_drop_columns = set(CONTRACT_RUNTIME_DROP_COLUMNS)
    forced_drop_columns.update(sidecar_columns)
    forced_drop_columns.update(alias_columns & CONTRACT_ALIAS_DROP_CANDIDATES)
    forced_drop_columns.update(lineage_columns & CONTRACT_LINEAGE_FIELDS)
    return {
        "contract_csv": str(contract_csv),
        "contract_row_count": len(contract_rows),
        "by_column": by_column,
        "official_current_columns": official_current_columns,
        "review_columns": review_columns,
        "sidecar_columns": sidecar_columns,
        "context_columns": context_columns,
        "lineage_columns": lineage_columns,
        "alias_columns": alias_columns,
        "debug_columns": debug_columns,
        "reference_columns": reference_columns,
        "forced_drop_columns": forced_drop_columns,
    }


def apply_contract_to_selector_frame(df: pd.DataFrame, policy: dict[str, Any], log: Logger) -> tuple[pd.DataFrame, dict[str, Any]]:
    before_cols = list(df.columns)
    forced_drop_present = [c for c in before_cols if c in policy["forced_drop_columns"]]
    official_missing = sorted(c for c in CONTRACT_REQUIRED_CONTEXT_COLUMNS if c not in df.columns)
    official_missing.extend(sorted(c for c in policy["official_current_columns"] if c not in df.columns and c in CRITICAL_SELECTOR_FORMULA_COLUMNS))
    if official_missing:
        raise RuntimeError(f"contract_required_selector_columns_missing:{'|'.join(official_missing)}")
    keep_columns = [c for c in before_cols if c not in policy["forced_drop_columns"]]
    pruned = df.loc[:, keep_columns].copy()
    role_counter = Counter()
    for col in pruned.columns:
        role = policy["by_column"].get(col, {}).get("draft_role", "unclassified")
        role_counter[role] += 1
    report = {
        "before_column_count": len(before_cols),
        "after_column_count": len(pruned.columns),
        "dropped_columns": forced_drop_present,
        "dropped_column_count": len(forced_drop_present),
        "kept_context_columns": sorted(c for c in CONTRACT_REQUIRED_CONTEXT_COLUMNS if c in pruned.columns),
        "remaining_review_columns": sorted(c for c in pruned.columns if c in policy["review_columns"]),
        "remaining_sidecar_columns": sorted(c for c in pruned.columns if c in policy["sidecar_columns"]),
        "remaining_lineage_columns": sorted(c for c in pruned.columns if c in policy["lineage_columns"]),
        "remaining_alias_columns": sorted(c for c in pruned.columns if c in policy["alias_columns"]),
        "remaining_debug_columns": sorted(c for c in pruned.columns if c in policy["debug_columns"]),
        "remaining_reference_columns": sorted(c for c in pruned.columns if c in policy["reference_columns"]),
        "kept_role_counts": dict(sorted(role_counter.items())),
    }
    log.log(
        "applied selector contract pruning: "
        f"before={report['before_column_count']} after={report['after_column_count']} dropped={report['dropped_column_count']}"
    )
    return pruned, report


def contract_schema_gate(schema: pa.Schema, policy: dict[str, Any], role: str) -> dict[str, Any]:
    schema_cols = set(schema.names)
    forbidden_present = sorted(c for c in schema.names if c in policy["forced_drop_columns"])
    required_missing = sorted(c for c in CONTRACT_REQUIRED_CONTEXT_COLUMNS if c not in schema_cols)
    current_allowed_missing = sorted(
        c for c in policy["official_current_columns"]
        if c in CRITICAL_SELECTOR_FORMULA_COLUMNS and c not in schema_cols
    )
    status = "PASS" if not forbidden_present and not required_missing and not current_allowed_missing else "FAIL"
    return {
        "role": role,
        "schema_columns": len(schema.names),
        "forbidden_present": forbidden_present,
        "required_missing": required_missing,
        "critical_allowed_missing": current_allowed_missing,
        "status": status,
    }


def contract_dataframe_gate(df: pd.DataFrame, policy: dict[str, Any], role: str) -> dict[str, Any]:
    cols = set(df.columns)
    forbidden_present = sorted(c for c in df.columns if c in policy["forced_drop_columns"])
    required_missing = sorted(c for c in CONTRACT_REQUIRED_CONTEXT_COLUMNS if c not in cols)
    lingering_review = sorted(c for c in df.columns if c in policy["review_columns"])
    status = "PASS" if not forbidden_present and not required_missing and not lingering_review else "FAIL"
    return {
        "role": role,
        "column_count": len(df.columns),
        "forbidden_present": forbidden_present,
        "required_missing": required_missing,
        "lingering_review_columns": lingering_review,
        "status": status,
    }


def contract_column_summary(columns: list[str], policy: dict[str, Any]) -> dict[str, Any]:
    role_counter = Counter()
    for col in columns:
        role = policy["by_column"].get(col, {}).get("draft_role", "unclassified")
        role_counter[role] += 1
    return {
        "column_count": len(columns),
        "role_counts": dict(sorted(role_counter.items())),
        "lineage_columns_present": sorted(c for c in columns if c in policy["lineage_columns"]),
        "alias_columns_present": sorted(c for c in columns if c in policy["alias_columns"]),
        "reference_columns_present": sorted(c for c in columns if c in policy["reference_columns"]),
    }


def validate_selector_null_policy(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty or "bar_close_pos" not in df.columns or "high" not in df.columns or "low" not in df.columns:
        return {
            "field": "bar_close_pos",
            "status": "PASS",
            "nullable_by_design_count": 0,
            "unexpected_null_count": 0,
            "unexpected_null_samples": [],
        }
    null_mask = df["bar_close_pos"].isna()
    flat_mask = df["high"].eq(df["low"])
    allowed_null_mask = null_mask & flat_mask
    unexpected_null_mask = null_mask & ~flat_mask
    samples = []
    if unexpected_null_mask.any():
        sample_cols = [c for c in ["trade_date", "ts_code", "high", "low", "bar_close_pos"] if c in df.columns]
        samples = df.loc[unexpected_null_mask, sample_cols].head(20).to_dict(orient="records")
    return {
        "field": "bar_close_pos",
        "status": "PASS" if not unexpected_null_mask.any() else "FAIL",
        "nullable_by_design_count": int(allowed_null_mask.sum()),
        "unexpected_null_count": int(unexpected_null_mask.sum()),
        "unexpected_null_samples": samples,
    }


def append_contract_provenance(df: pd.DataFrame, selector_current: Path, contract_version: str) -> pd.DataFrame:
    out = df.copy()
    if "field_contract_version" not in out.columns:
        out["field_contract_version"] = contract_version
    else:
        out["field_contract_version"] = out["field_contract_version"].fillna(contract_version).replace("", contract_version)
    if "formula_source" in out.columns:
        out["formula_source"] = out["formula_source"].fillna(CONTRACT_PROVENANCE_FIELD_DEFAULTS["formula_source"]).replace("", CONTRACT_PROVENANCE_FIELD_DEFAULTS["formula_source"])
    if "source_panel_path" in out.columns:
        out["source_panel_path"] = str(selector_current)
    if "panel_role" in out.columns:
        out["panel_role"] = CONTRACT_PROVENANCE_FIELD_DEFAULTS["panel_role"]
    return out


def append_backtest_provenance_and_tradeability(df: pd.DataFrame, backtest_current: Path) -> pd.DataFrame:
    """Populate required backtest fields explicitly instead of schema-alignment defaults."""
    out = df.copy()
    out["source"] = "tdx_vipdoc_daily_increment"
    out["source_panel_path"] = str(backtest_current)
    out["panel_role"] = "BACKTEST_BASE_DAILY_INCREMENT"
    required_price = out[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce").gt(0).all(axis=1)
    positive_activity = pd.to_numeric(out.get("amount", 0), errors="coerce").fillna(0).gt(0) & pd.to_numeric(out.get("vol", 0), errors="coerce").fillna(0).gt(0)
    out["tradeable_basic"] = (required_price & positive_activity).astype(int)
    return out


def audit_cross_day_continuity(frame: pd.DataFrame, max_close_ratio: float = MAX_CROSS_DAY_CLOSE_RATIO, strict: bool = False) -> Dict[str, Any]:
    required = {"ts_code", "trade_date", "close"}
    if not required.issubset(frame.columns):
        return {"status": "FAIL", "issue_count": 1, "issues": ["cross_day_columns_missing"]}
    work = frame.copy()
    work["trade_date"] = pd.to_numeric(work["trade_date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    if {"open", "high", "low"}.issubset(frame.columns):
        for col in ("open", "high", "low"):
            work[col] = pd.to_numeric(work[col], errors="coerce")
    # All masks must be computed on the SAME row set. Keeping OHLC in `work`
    # before dropna guarantees close/high/low masks align with close_ratio;
    # otherwise a dropped row makes work/ohlc indexes diverge and pandas
    # silently reindexes, producing wrong invalid_ohlc rows.
    work = work.dropna(subset=["ts_code", "trade_date", "close"]).sort_values(["ts_code", "trade_date"])
    work["previous_close"] = work.groupby("ts_code", sort=False)["close"].shift(1)
    work["close_ratio"] = work["close"] / work["previous_close"]
    cross_day_jump = work["previous_close"].gt(0) & ((work["close_ratio"] > max_close_ratio) | (work["close_ratio"] < 1.0 / max_close_ratio))
    # Structurally-impossible OHLC is the only hard blocker. Cross-day jumps
    # are legitimate for ex-dividend / splits / halts (e.g. 002594 BYD 1:3
    # split on 20250729 dropped 337->111), so they are reported as edge
    # warnings and do not block panel generation - matching the panel audit.
    invalid_ohlc = work["close"].le(0)
    if {"open", "high", "low"}.issubset(frame.columns):
        invalid_ohlc = (
            invalid_ohlc
            | work["open"].le(0)
            | work["high"].le(0)
            | work["low"].le(0)
            | work["high"].lt(work["low"])
            | work["close"].gt(work["high"])
            | work["close"].lt(work["low"])
        )
    if strict:
        # Isolated rebuild path: cross-day jumps are treated as corruption so
        # the symbol is excluded from the candidate rebuild.
        bad = work[cross_day_jump].copy()
        edge = work[invalid_ohlc & ~cross_day_jump].copy()
    else:
        # Increment gate: cross-day jumps are legitimate ex-dividend / splits /
        # halts, so only structurally-impossible OHLC blocks. Matches the panel audit.
        bad = work[invalid_ohlc].copy()
        edge = work[cross_day_jump & ~invalid_ohlc].copy()
    samples = bad.head(50).to_dict(orient="records")
    return {
        "status": "PASS" if bad.empty else "FAIL",
        "issue_count": int(len(bad)),
        "edge_warning_count": int(len(edge)),
        "max_close_ratio": max_close_ratio,
        "bad_symbols": sorted(bad["ts_code"].astype(str).unique().tolist()),
        "edge_warning_symbols": sorted(edge["ts_code"].astype(str).unique().tolist()),
        "samples": samples,
        "edge_warning_samples": edge.head(50).to_dict(orient="records"),
    }


def audit_formal_panel_history_frame(frame: pd.DataFrame, role: str) -> Dict[str, Any]:
    required = {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        return {"status": "BLOCKED_CURRENT_FORMAL_HISTORY_CORRUPT", "role": role, "issue_count": 1, "bad_symbols": [], "issues": [f"missing_columns:{'|'.join(missing)}"], "samples": []}
    work = frame.copy()
    work["trade_date"] = pd.to_numeric(work["trade_date"], errors="coerce")
    for col in ("open", "high", "low", "close", "pre_close"):
        work[col] = pd.to_numeric(work[col], errors="coerce")
    # A-share continuity audit only; HK / HK_FUND / other non-A rows (float
    # stored, different market) are excluded because they are not part of the
    # A-share continuity chain.
    work = work[work["ts_code"].astype(str).str.endswith((".SH", ".SZ"))].copy()
    work = work.sort_values(["ts_code", "trade_date"])
    expected = work.groupby("ts_code", sort=False)["close"].shift(1)
    if "pct_chg_source" in work.columns:
        raw_source = work["pct_chg_source"].astype(str).eq("tdx_day_raw_previous_close")
    else:
        # No source column: a row whose pre_close diverges from the previous
        # close is an ex-dividend/ex-rights adjustment (the panel pre_close is
        # already restated), so it must not be flagged as corrupt. Rows whose
        # pre_close equals the previous close are raw and stay audited.
        has_pre_close_chain = expected.notna() & work["pre_close"].notna()
        adjusted = has_pre_close_chain & (work["pre_close"] - expected).abs().gt(1e-9)
        raw_source = ~adjusted
    close_ratio = work["close"] / expected
    cross_day_break = raw_source & expected.gt(0) & ((close_ratio > MAX_CROSS_DAY_CLOSE_RATIO) | (close_ratio < 1.0 / MAX_CROSS_DAY_CLOSE_RATIO))
    invalid_ohlc = (work[["open", "high", "low", "close"]] <= 0).any(axis=1) | work["high"].lt(work["low"]) | work["close"].gt(work["high"]) | work["close"].lt(work["low"])
    preclose_break = raw_source & expected.notna() & work["pre_close"].notna() & (work["pre_close"] - expected).abs().gt(1e-9)
    # Only structurally-impossible OHLC is a hard blocker. cross-day jumps and
    # pre_close deltas are legitimate for ex-dividend / halted / low-float
    # symbols (especially without pct_chg_source), so they are reported as
    # warnings and do not block panel generation.
    bad = work[invalid_ohlc].copy()
    edge = work[cross_day_break | preclose_break].copy()
    return {"status": "PASS" if bad.empty else "BLOCKED_CURRENT_FORMAL_HISTORY_CORRUPT", "role": role, "issue_count": int(len(bad)), "cross_day_issue_count": int(cross_day_break.sum()), "edge_warning_count": int(len(edge)), "bad_symbols": sorted(bad["ts_code"].astype(str).unique().tolist()), "dates": sorted(bad["trade_date"].dropna().astype(int).unique().tolist()), "samples": bad.head(50).to_dict(orient="records")}


def audit_increment_boundary(current: pd.DataFrame, increment: pd.DataFrame) -> Dict[str, Any]:
    if current.empty or increment.empty:
        return {
            "status": "PASS",
            "issue_count": 0,
            "bad_symbols": [],
            "bad_keys": [],
            "samples": [],
            "xdxr_exemption_count": 0,
            "xdxr_exemption_samples": [],
        }
    current_last = current.copy().sort_values(["ts_code", "trade_date"]).groupby("ts_code", as_index=False).tail(1).set_index("ts_code")["close"]
    first = increment.copy().sort_values(["ts_code", "trade_date"]).groupby("ts_code", as_index=False).head(1).copy()
    first["expected_pre_close"] = first["ts_code"].map(current_last)
    source = first.get("pct_chg_source", pd.Series("tdx_day_raw_previous_close", index=first.index)).astype(str)
    first["pre_close"] = pd.to_numeric(first.get("pre_close"), errors="coerce")
    expected = first["expected_pre_close"].notna()
    preclose_missing = expected & first["pre_close"].isna()
    # Tolerance must accommodate float32 panel storage (e.g. 33.81 stored as
    # 33.810001373291016). At tens-of-yuan prices float32 quantizes to ~1e-5,
    # so 1e-9 / 1e-6 tolerances false-positive on every float32 panel row.
    # 1e-4 sits 10x above the observed quantization noise and far below any
    # real pre_close discontinuity (which is > 1 yuan).
    tolerance = 1e-4
    different = expected & first["pre_close"].notna() & (first["pre_close"] - first["expected_pre_close"]).abs().gt(tolerance)
    raw_mismatch = source.eq("tdx_day_raw_previous_close") & different
    mismatch = preclose_missing | raw_mismatch
    bad = first[mismatch]
    xdxr_exemptions = first[~source.eq("tdx_day_raw_previous_close") & different]
    status = "BLOCKED_INCREMENT_BOUNDARY_DISCONTINUITY" if not bad.empty else ("PASS_WITH_XDXR_EXEMPTION" if not xdxr_exemptions.empty else "PASS")
    bad_keys = []
    for _index, row in bad.iterrows():
        generated_pre_close = row.get("pre_close")
        expected_pre_close = row.get("expected_pre_close")
        try:
            difference = float(generated_pre_close) - float(expected_pre_close)
        except (TypeError, ValueError):
            difference = None
        try:
            generated_missing = bool(pd.isna(generated_pre_close))
        except (TypeError, ValueError):
            generated_missing = False
        bad_keys.append({
            "ts_code": str(row.get("ts_code")),
            "trade_date": int(row.get("trade_date")),
            "before_pre_close": _boundary_json_scalar(expected_pre_close),
            "generated_pre_close": _boundary_json_scalar(generated_pre_close),
            "source": str(source.loc[_index]),
            "current_close": _boundary_json_scalar(row.get("close")),
            "difference": _boundary_json_scalar(difference),
            "reason": "PRE_CLOSE_MISSING" if generated_missing else "RAW_PRE_CLOSE_DISCONTINUITY",
        })
    return {
        "status": status,
        "issue_count": int(len(bad)),
        "bad_symbols": sorted({item["ts_code"] for item in bad_keys}),
        # Keep the complete issue set separate from the legacy display sample.
        # The isolation receipt must never inherit the old head(50) truncation.
        "bad_keys": bad_keys,
        "samples": bad.head(50).to_dict(orient="records"),
        "xdxr_exemption_count": int(len(xdxr_exemptions)),
        "xdxr_exemption_samples": xdxr_exemptions.head(50).to_dict(orient="records"),
    }


def _boundary_json_scalar(value: Any) -> Any:
    """Convert one boundary value to a deterministic JSON scalar."""

    if isinstance(value, np.generic):
        value = value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (float, np.floating)):
        return float(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (str, bool)) or value is None:
        return value
    return str(value)


def _validate_increment_boundary_frame(
    frame: pd.DataFrame,
    label: str,
    *,
    require_pre_close: bool,
) -> None:
    """Reject malformed owner/storage input before any symbol isolation."""

    if not isinstance(frame, pd.DataFrame):
        raise RuntimeError(f"increment_boundary_{label}_not_dataframe")
    required = {"ts_code", "trade_date", "close"}
    if require_pre_close:
        required.add("pre_close")
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"increment_boundary_{label}_schema_missing:{','.join(missing)}")
    if frame.empty:
        return
    if frame["ts_code"].isna().any():
        raise RuntimeError(f"increment_boundary_{label}_symbol_missing")
    for column in ("trade_date", "close"):
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.isna().any():
            raise RuntimeError(f"increment_boundary_{label}_{column}_invalid")
    if frame.duplicated(["ts_code", "trade_date"]).any():
        raise RuntimeError(f"increment_boundary_{label}_duplicate_key")
    if not require_pre_close:
        return
    pre_close = frame["pre_close"]
    pre_close_numeric = pd.to_numeric(pre_close, errors="coerce")
    malformed_pre_close = pre_close.notna() & pre_close_numeric.isna()
    if malformed_pre_close.any():
        raise RuntimeError(f"increment_boundary_{label}_pre_close_invalid")


def isolate_increment_boundary_bad_symbols(
    current_by_role: Mapping[str, pd.DataFrame],
    increment_by_role: Mapping[str, pd.DataFrame],
    *,
    target_date: Optional[int] = None,
) -> Dict[str, Any]:
    """Quarantine boundary-broken symbols atomically across both roles.

    Boundary failures are stock-local only after both owner frames pass the
    shared schema/key checks.  Every generated increment row for the union of
    bad symbols is removed from both roles, while the old formal rows remain
    untouched in the caller's current panels.  The original boundary audit is
    rerun on the remaining rows so xdxr exemptions keep their existing rules.
    """

    roles = ("selector", "backtest")
    for role in roles:
        if role not in current_by_role or role not in increment_by_role:
            raise RuntimeError(f"increment_boundary_{role}_input_missing")
        _validate_increment_boundary_frame(
            current_by_role[role], f"current_{role}", require_pre_close=False
        )
        _validate_increment_boundary_frame(
            increment_by_role[role], f"increment_{role}", require_pre_close=True
        )
        if current_by_role[role].empty and not increment_by_role[role].empty:
            raise RuntimeError(f"increment_boundary_current_{role}_empty")

    before = {
        role: audit_increment_boundary(current_by_role[role], increment_by_role[role])
        for role in roles
    }
    bad_symbols = sorted({
        str(symbol)
        for role in roles
        for symbol in before[role].get("bad_symbols", [])
    })
    bad_symbol_set = set(bad_symbols)
    after_increments: Dict[str, pd.DataFrame] = {}
    isolation_by_role: Dict[str, Any] = {}
    bad_keys = []
    for role in roles:
        for key in before[role].get("bad_keys", []):
            bad_keys.append({"role": role, **key})
        increment = increment_by_role[role]
        symbols = increment["ts_code"].astype(str)
        removed_mask = symbols.isin(bad_symbol_set)
        after = increment.loc[~removed_mask].copy().reset_index(drop=True)
        if after["ts_code"].astype(str).isin(bad_symbol_set).any():
            raise RuntimeError(f"increment_boundary_{role}_isolation_incomplete")
        after_increments[role] = after
        isolation_by_role[role] = {
            "before_row_count": int(len(increment)),
            "removed_row_count": int(removed_mask.sum()),
            "remaining_row_count": int(len(after)),
            "removed_symbols": sorted(set(symbols.loc[removed_mask].tolist())),
            "remaining_symbols": sorted(set(after["ts_code"].astype(str).tolist())),
            "remaining_target_date_row_count": (
                int(pd.to_numeric(after["trade_date"], errors="raise").eq(int(target_date)).sum())
                if target_date is not None else None
            ),
        }

    if target_date is not None:
        for role in roles:
            if isolation_by_role[role]["remaining_row_count"] == 0:
                raise RuntimeError("increment_boundary_all_rows_isolated")
            if isolation_by_role[role]["remaining_target_date_row_count"] == 0:
                raise RuntimeError(f"increment_boundary_{role}_target_date_absent_after_isolation:{target_date}")

    after_audit = {
        role: audit_increment_boundary(current_by_role[role], after_increments[role])
        for role in roles
    }
    boundary_ok = {"PASS", "PASS_WITH_XDXR_EXEMPTION"}
    invalid_after = [role for role in roles if after_audit[role]["status"] not in boundary_ok]
    if invalid_after:
        raise RuntimeError(
            "increment_boundary_remaining_rows_failed:"
            + ",".join(invalid_after)
        )

    return {
        "status": "PASS_WITH_SYMBOL_ISOLATION" if bad_symbols else "PASS",
        "bad_symbol_count": len(bad_symbols),
        "bad_symbols": bad_symbols,
        "bad_keys": bad_keys,
        "before": before,
        "after": after_audit,
        "isolation_by_role": isolation_by_role,
        "target_date": int(target_date) if target_date is not None else None,
        "xdxr_exemption_count_before": sum(
            int(before[role].get("xdxr_exemption_count", 0)) for role in roles
        ),
        "xdxr_exemption_count_after": sum(
            int(after_audit[role].get("xdxr_exemption_count", 0)) for role in roles
        ),
        "increments": after_increments,
    }


def audit_formal_panel_history(path: Path, role: str, start_date: int | None = None, end_date: int | None = None) -> Dict[str, Any]:
    pf = pq.ParquetFile(path)
    wanted = [c for c in ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "pct_chg_source"] if c in pf.schema_arrow.names]
    required = {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close"}
    if not required.issubset(wanted):
        return {"status": "BLOCKED_CURRENT_FORMAL_HISTORY_CORRUPT", "role": role, "issue_count": 1, "bad_symbols": [], "dates": [], "samples": [], "issues": ["required_continuity_columns_missing"]}
    parts = []
    for batch in pf.iter_batches(batch_size=262144, columns=wanted):
        part = batch.to_pandas()
        if start_date is not None or end_date is not None:
            trade_date = pd.to_numeric(part["trade_date"], errors="coerce")
            if start_date is not None:
                part = part.loc[trade_date.ge(int(start_date))]
            if end_date is not None:
                part = part.loc[trade_date.le(int(end_date))]
        if not part.empty:
            parts.append(part)
    result = audit_formal_panel_history_frame(pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=wanted), role)
    result["audit_start_date"] = start_date
    result["audit_end_date"] = end_date
    return result


def current_last_close_frame(path: Path) -> pd.DataFrame:
    table = pq.read_table(path, columns=["ts_code", "trade_date", "close"])
    return table.to_pandas()


def latest_trade_dates_by_ts(path: Path) -> Dict[str, int]:
    """Return each symbol's actual panel cutoff, not only the global max date."""

    table = pq.read_table(path, columns=["ts_code", "trade_date"])
    frame = table.to_pandas()
    if frame.empty:
        return {}
    frame["trade_date"] = pd.to_numeric(frame["trade_date"], errors="coerce")
    frame = frame.dropna(subset=["ts_code", "trade_date"])
    return {
        str(symbol): int(value)
        for symbol, value in frame.groupby("ts_code", sort=False)["trade_date"].max().items()
    }


def minimum_role_cutoffs(
    selector_latest_by_ts: Dict[str, int],
    backtest_latest_by_ts: Dict[str, int],
) -> Dict[str, int]:
    """Return the earliest role cutoff so one formula pass can repair both roles."""

    symbols = set(selector_latest_by_ts) | set(backtest_latest_by_ts)
    return {
        symbol: min(
            int(selector_latest_by_ts.get(symbol, 0) or 0),
            int(backtest_latest_by_ts.get(symbol, 0) or 0),
        )
        for symbol in symbols
    }


def audit_pre_close_chain(frame: pd.DataFrame, tolerance: float = 1e-9) -> Dict[str, Any]:
    required = {"ts_code", "trade_date", "close", "pre_close"}
    if not required.issubset(frame.columns):
        return {"status": "PASS", "issue_count": 0, "samples": [], "skipped": "pre_close_not_in_frame"}
    work = frame.loc[:, ["ts_code", "trade_date", "close", "pre_close", *(["pct_chg_source"] if "pct_chg_source" in frame.columns else [])]].copy()
    work["trade_date"] = pd.to_numeric(work["trade_date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work["pre_close"] = pd.to_numeric(work["pre_close"], errors="coerce")
    work = work.sort_values(["ts_code", "trade_date"])
    work["expected_pre_close"] = work.groupby("ts_code", sort=False)["close"].shift(1)
    raw_source = work.get("pct_chg_source", pd.Series("tdx_day_raw_previous_close", index=work.index)).eq("tdx_day_raw_previous_close")
    bad = work[raw_source & work["expected_pre_close"].notna() & work["pre_close"].notna() & (work["expected_pre_close"] - work["pre_close"]).abs().gt(tolerance)]
    return {"status": "PASS" if bad.empty else "FAIL", "issue_count": int(len(bad)), "samples": bad.head(50).to_dict(orient="records")}


def rebuild_ohlc_preclose_chain(frame: pd.DataFrame, start_date: int, end_date: int, max_close_ratio: float = MAX_CROSS_DAY_CLOSE_RATIO) -> pd.DataFrame:
    """Build a date-windowed, non-promoted OHLC return chain with explicit segment breaks."""
    required = ["ts_code", "trade_date", "open", "high", "low", "close"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"isolated_rebuild_columns_missing:{'|'.join(missing)}")
    work = frame.copy()
    work["trade_date"] = pd.to_numeric(work["trade_date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["ts_code", "trade_date", "close"]).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    prior_close = work.groupby("ts_code", sort=False)["close"].shift(1)
    ratio = work["close"] / prior_close
    work["continuity_break"] = np.select(
        [prior_close.isna(), ratio.gt(max_close_ratio) | ratio.lt(1.0 / max_close_ratio)],
        ["first_observation", "cross_day_close_ratio"],
        default="",
    )
    work["pre_close"] = prior_close.where(work["continuity_break"].eq(""))
    work["pct_chg"] = (work["close"] / work["pre_close"] - 1.0) * 100.0
    work.loc[work["pre_close"].isna() | work["pre_close"].eq(0), "pct_chg"] = np.nan
    return work[work["trade_date"].between(int(start_date), int(end_date))].reset_index(drop=True)


def run_isolated_history_rebuild(tdx_root: Path, start_date: int, end_date: int, output_dir: Path, lookback_records: int = 300) -> Dict[str, Any]:
    """Create a review-only repair candidate; it never writes .day, parquet pointers, or formal panels."""
    if int(end_date) < int(start_date):
        raise ValueError("isolated_rebuild_end_before_start")
    parts: List[pd.DataFrame] = []
    files = [(ts_code, path) for ts_code, path in discover_day_files(tdx_root) if is_a_bj_ts(ts_code)]
    for ts_code, path in files:
        tail = read_day_tail(ts_code, path, tail_records=lookback_records)
        if not tail.empty:
            parts.append(tail)
    history = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    before = audit_cross_day_continuity(history, strict=True)
    bad_symbols = list(before.get("bad_symbols", []))
    safe_history = history[~history["ts_code"].astype(str).isin(bad_symbols)].copy() if not history.empty else history
    candidate = rebuild_ohlc_preclose_chain(safe_history, int(start_date), int(end_date)) if not safe_history.empty else safe_history
    after = audit_pre_close_chain(candidate)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "isolated_ohlc_preclose_pct_chg_candidate.parquet"
    candidate.to_parquet(candidate_path, index=False)
    result = {
        "status": "PASS_WITH_EXCLUSIONS" if after["status"] == "PASS" and bad_symbols else ("PASS" if after["status"] == "PASS" else "BLOCKED_SOURCE_CORRUPT_OHLC"),
        "mode": "ISOLATED_REBUILD_NO_PROMOTE",
        "tdx_root": str(tdx_root),
        "start_date": int(start_date),
        "end_date": int(end_date),
        "lookback_records": int(lookback_records),
        "source_day_file_count": len(files),
        "excluded_symbol_count": len(bad_symbols),
        "excluded_symbols": bad_symbols,
        "candidate_rows": int(len(candidate)),
        "candidate_path": str(candidate_path),
        "source_cross_day_audit": before,
        "candidate_pre_close_chain_audit": after,
        "pointer_modified": False,
        "formal_parquet_modified": False,
    }
    write_json(output_dir / "isolated_rebuild_manifest.json", result)
    return result


def allowed_missing_default_for_field(col: str, policy: dict[str, Any]) -> bool:
    return col in policy["forced_drop_columns"]


def runtime_default_for_field(col: str) -> Any:
    return CONTRACT_PROVENANCE_FIELD_DEFAULTS.get(col)


def build_new_schema_from_current(current_schema: pa.Schema, policy: dict[str, Any], role: str) -> pa.Schema:
    fields = [field for field in current_schema if field.name not in policy["forced_drop_columns"]]
    schema = pa.schema(fields)
    gate = contract_schema_gate(schema, policy, role)
    if gate["status"] != "PASS":
        raise RuntimeError(f"contract_schema_gate_failed:{role}:{json.dumps(gate, ensure_ascii=False)}")
    return schema


def parse_tdx_industry_names(path: Path) -> dict[str, str]:
    text = path.read_bytes().decode("gb18030")
    names: dict[str, str] = {}
    for line in text.splitlines():
        fields = [field.strip() for field in line.split("|")]
        if len(fields) >= 6 and fields[-1].startswith("T") and fields[0]:
            names[fields[-1]] = fields[0]
    if not names:
        raise RuntimeError(f"no TDX industry names parsed from {path}")
    return names


def parse_tdx_stock_industries(path: Path) -> dict[str, str]:
    text = path.read_bytes().decode("gb18030")
    mappings: dict[str, str] = {}
    for line in text.splitlines():
        fields = [field.strip() for field in line.split("|")]
        if len(fields) >= 3 and len(fields[1]) == 6 and fields[2].startswith("T"):
            mappings[fields[1]] = fields[2]
    if not mappings:
        raise RuntimeError(f"no TDX stock industries parsed from {path}")
    return mappings


def attach_tdx_industry_name(
    frame: pd.DataFrame,
    mapping_path: Path = TDX_INDUSTRY_NAMES,
    stock_mapping_path: Path = TDX_STOCK_INDUSTRIES,
) -> pd.DataFrame:
    if "tdx_industry_code" not in frame.columns:
        raise RuntimeError("tdx_industry_code missing while attaching tdx_industry_name")
    result = frame.copy()
    names = parse_tdx_industry_names(mapping_path)
    stock_industries = parse_tdx_stock_industries(stock_mapping_path)
    codes = result["tdx_industry_code"].fillna("").astype(str).str.strip()
    missing = codes.eq("")
    codes.loc[missing] = (
        result.loc[missing, "ts_code"].fillna("").astype(str).str[:6].map(stock_industries).fillna("")
    )
    result["tdx_industry_code"] = codes
    result["tdx_industry_name"] = codes.map(names).fillna("")
    return result


def build_official_selector_frame(selector_inc_df: pd.DataFrame, policy: dict[str, Any], selector_current: Path, log: Logger) -> tuple[pd.DataFrame, dict[str, Any]]:
    enriched = append_contract_provenance(selector_inc_df, selector_current, CONTRACT_PROVENANCE_FIELD_DEFAULTS["field_contract_version"])
    pruned, report = apply_contract_to_selector_frame(enriched, policy, log)
    frame_gate = contract_dataframe_gate(pruned, policy, "selector_official_frame")
    report["frame_gate"] = frame_gate
    if frame_gate["status"] != "PASS":
        raise RuntimeError(f"contract_dataframe_gate_failed:selector:{json.dumps(frame_gate, ensure_ascii=False)}")
    report["column_summary"] = contract_column_summary(list(pruned.columns), policy)
    return pruned, report


def build_contract_policy_or_fail() -> dict[str, Any]:
    rows = load_authoritative_contract_rows(CONTRACT_CSV)
    return build_contract_policy(rows, CONTRACT_CSV)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def mem_mb() -> Optional[float]:
    if psutil is None:
        return None
    try:
        return round(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024, 2)
    except Exception:
        return None


class Logger:
    def __init__(self, path: Path) -> None:
        self.path = path
        ensure_dir(path.parent)
        self.f = path.open("w", encoding="utf-8", newline="\n")
        self.stdout_available = True

    def log(self, msg: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] [rss_mb={mem_mb()}] {msg}"
        if self.stdout_available:
            try:
                print(line, flush=True)
            except OSError:
                self.stdout_available = False
        self.f.write(line + "\n")
        self.f.flush()

    def close(self) -> None:
        self.f.close()


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: Optional[List[str]] = None) -> None:
    ensure_dir(path.parent)
    if fieldnames is None:
        keys = []
        for r in rows:
            for k in r.keys():
                if k not in keys:
                    keys.append(k)
        fieldnames = keys
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})


def sha256_file(path: Path, max_mb: float = 100.0) -> Optional[str]:
    try:
        if not path.exists() or path.stat().st_size > max_mb * 1024 * 1024:
            return None
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def read_pointer(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes() if path.exists() else b""
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig", errors="replace").strip().lstrip("\ufeff")
    return {
        "pointer": str(path),
        "exists": path.exists(),
        "has_bom": has_bom,
        "target": text,
        "target_exists": Path(text).exists() if text else False,
    }


def run_v192_selector_canary(
    selector_input: Path,
    signal_date: int,
    output_path: Path,
    *,
    selector_pointer: Optional[Path] = None,
    backtest_pointer: Optional[Path] = None,
    lookback_records: int = DAILY_FORMULA_LOOKBACK_RECORDS,
) -> Dict[str, Any]:
    """Recompute one selector date into an explicit, non-promoted output only."""
    source = Path(selector_input).resolve()
    if not source.is_file():
        raise RuntimeError(f"v192_selector_canary_input_missing:{source}")
    target_date = int(normalize_trade_date_value(signal_date) or 0)
    if not 10000101 <= target_date <= 99991231:
        raise RuntimeError(f"v192_selector_canary_invalid_signal_date:{signal_date}")
    output = Path(output_path)
    if output.suffix.lower() != ".parquet":
        output = output / f"selector_v192_canary_{target_date}.parquet"
    output = output.resolve()
    protected = {source, Path(SELECTOR_POINTER).resolve(), Path(BACKTEST_POINTER).resolve()}; protected_roots = {Path(PROMOTED_SELECTOR_ROOT).resolve(), Path(PROMOTED_BACKTEST_ROOT).resolve()}
    if output in protected or any(root in output.parents for root in protected_roots):
        raise RuntimeError(f"v192_selector_canary_output_forbidden:{output}")
    selector_ptr = Path(selector_pointer).resolve() if selector_pointer is not None else Path(SELECTOR_POINTER).resolve(); backtest_ptr = Path(backtest_pointer).resolve() if backtest_pointer is not None else Path(BACKTEST_POINTER).resolve()
    if output in {selector_ptr, backtest_ptr}:
        raise RuntimeError(f"v192_selector_canary_output_forbidden:{output}")
    pointer_paths = (selector_ptr, backtest_ptr); pointer_before = {path: (path.read_bytes() if path.is_file() else None) for path in pointer_paths}
    if selector_ptr.is_file() and (pointer_target := read_pointer(selector_ptr)["target"]) and Path(pointer_target).resolve() != source:
        raise RuntimeError("v192_selector_canary_selector_pointer_input_mismatch")
    parquet = pq.ParquetFile(source)
    schema = parquet.schema_arrow
    row_group_count, input_row_count = parquet.metadata.num_row_groups, parquet.metadata.num_rows
    canary_fields = (*V192_ENTRY_FIELDS, *V192_INTERMEDIATE_FIELDS, "formula_source")
    required = {"ts_code", "trade_date", "open", "high", "low", "close", "amount", *canary_fields}
    volume_field = "volume" if "volume" in schema.names else "vol" if "vol" in schema.names else ""
    if not volume_field:
        parquet.close()
        raise RuntimeError("v192_selector_canary_missing_columns:volume|vol")
    required.add(volume_field)
    missing = sorted(required - set(schema.names))
    if missing:
        parquet.close()
        raise RuntimeError(f"v192_selector_canary_missing_columns:{','.join(missing)}")
    gold_type = schema.field("gold_brick_context").type
    gold_is_string = pa.types.is_string(gold_type) or pa.types.is_large_string(gold_type)
    gold_is_numeric = pa.types.is_integer(gold_type) or pa.types.is_floating(gold_type)
    if not (gold_is_string or gold_is_numeric):
        parquet.close()
        raise RuntimeError("v192_selector_canary_schema_incompatible:gold_brick_context")
    for field in canary_fields:
        if field == "gold_brick_context":
            continue
        arrow_type = schema.field(field).type
        string_type = field == "formula_source"
        valid_type = (pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type)) if string_type else (pa.types.is_integer(arrow_type) or pa.types.is_floating(arrow_type))
        if not valid_type:
            parquet.close()
            raise RuntimeError(f"v192_selector_canary_schema_incompatible:{field}")
    schema_changes = []
    output_schema = schema
    if gold_is_numeric:
        output_schema = schema.set(schema.get_field_index("gold_brick_context"), schema.field("gold_brick_context").with_type(pa.string()))
        schema_changes = [{"field": "gold_brick_context", "before": str(gold_type), "after": "string"}]

    raw_columns = ["ts_code", "trade_date", "open", "high", "low", "close", "amount", volume_field]; parquet.close()
    raw = pd.read_parquet(source, columns=raw_columns)
    raw["_v192_date"] = pd.to_numeric(raw["trade_date"], errors="coerce")
    if raw["_v192_date"].isna().any() or raw["ts_code"].isna().any() or raw.duplicated(["ts_code", "_v192_date"]).any():
        raise RuntimeError("v192_selector_canary_invalid_keys")
    signal_mask = raw["_v192_date"].eq(target_date)
    if not signal_mask.any():
        raise RuntimeError(f"v192_selector_canary_signal_date_missing:{target_date}")
    history = raw.loc[raw["_v192_date"].le(target_date)].drop(columns=["_v192_date"]).rename(columns={volume_field: "volume"})
    history = history.sort_values(["ts_code", "trade_date"]).groupby("ts_code", sort=False, group_keys=False).tail(max(1, int(lookback_records))).reset_index(drop=True)
    canonical = _compute_canonical_v192_formula(history)
    canonical["trade_date"] = pd.to_numeric(canonical["trade_date"], errors="raise").astype(int)
    updates = canonical[canonical["trade_date"].eq(target_date)].set_index(["ts_code", "trade_date"])[list(canary_fields)].to_dict("index")
    expected_rows = raw.loc[signal_mask, ["ts_code", "_v192_date"]]; expected_keys = set(zip(expected_rows["ts_code"].astype(str), expected_rows["_v192_date"].astype(int)))
    if set(updates) != expected_keys:
        raise RuntimeError("v192_selector_canary_canonical_key_mismatch")
    if any((pointer.read_bytes() if pointer.is_file() else None) != pointer_before[pointer] for pointer in pointer_paths):
        raise RuntimeError("v192_selector_canary_pointer_changed_before_write")

    ensure_dir(output.parent); temp_output = output.with_name(f".{output.name}.tmp_{os.getpid()}"); changed_rows = 0
    parquet = pq.ParquetFile(source)
    try:
        with pq.ParquetWriter(temp_output, schema=output_schema) as writer:
            for row_group_index in range(row_group_count):
                table = parquet.read_row_group(row_group_index)
                dates = pd.to_numeric(table["trade_date"].to_pandas(), errors="coerce")
                row_mask = dates.eq(target_date)
                if not row_mask.any() and not gold_is_numeric:
                    writer.write_table(table)
                    continue
                frame = table.to_pandas()
                if gold_is_numeric:
                    frame["gold_brick_context"] = frame["gold_brick_context"].map(lambda value: "" if pd.isna(value) else str(value))
                if not row_mask.any():
                    writer.write_table(pa.Table.from_pandas(frame, schema=output_schema, preserve_index=False, safe=False))
                    continue
                for row_index in frame.index[row_mask]:
                    key = (str(frame.at[row_index, "ts_code"]), int(dates.at[row_index]))
                    update = updates.get(key)
                    if update is None:
                        raise RuntimeError("v192_selector_canary_output_key_missing")
                    for field, value in update.items():
                        frame.at[row_index, field] = value
                    changed_rows += 1
                writer.write_table(pa.Table.from_pandas(frame, schema=output_schema, preserve_index=False, safe=False))
        os.replace(str(temp_output), str(output))
    except Exception:
        parquet.close()
        if temp_output.exists():
            temp_output.unlink()
        raise
    parquet.close()
    pointer_unchanged = all((path.read_bytes() if path.is_file() else None) == pointer_before[path] for path in pointer_paths)
    if not pointer_unchanged:
        raise RuntimeError("v192_selector_canary_pointer_changed_after_write")
    output_parquet = pq.ParquetFile(output); output_row_count = output_parquet.metadata.num_rows; output_parquet.close()
    return {
        "status": "PASS",
        "mode": "V1_9_2_SELECTOR_CANARY_ISOLATED",
        "selector_input": str(source),
        "output_path": str(output),
        "signal_date": target_date,
        "input_rows": int(input_row_count),
        "recomputed_rows": changed_rows,
        "output_rows": int(output_row_count),
        "recomputed_fields": list(canary_fields),
        "formula_source": CANONICAL_FORMULA_SOURCE,
        "schema_changes": schema_changes,
        "pointer_unchanged": pointer_unchanged,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def write_pointer_atomic(path: Path, target: Path) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + f".tmp_{RUN_TS}")
    tmp.write_text(str(target), encoding="utf-8", newline="\n")
    os.replace(str(tmp), str(path))


def snapshot_paths(paths: List[Path]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for p in paths:
        try:
            out[str(p)] = {
                "exists": p.exists(),
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
                "size": p.stat().st_size if p.exists() and p.is_file() else None,
                "mtime": p.stat().st_mtime if p.exists() else None,
                "sha256": sha256_file(p) if p.exists() and p.is_file() and p.stat().st_size < 50 * 1024 * 1024 else None,
            }
        except Exception as exc:
            out[str(p)] = {"error": repr(exc)}
    return out


def compare_snapshots(before: Dict[str, Any], after: Dict[str, Any], allowed_changed: List[Path]) -> Dict[str, Any]:
    allowed = {str(p) for p in allowed_changed}
    changed = []
    for k in sorted(set(before.keys()) | set(after.keys())):
        if k in allowed:
            continue
        if before.get(k) != after.get(k):
            changed.append({"path": k, "before": before.get(k), "after": after.get(k)})
    return {
        "protected_changed_count": len(changed),
        "protected_changed": changed,
        "allowed_pointer_changes": [str(p) for p in allowed_changed],
    }


def parquet_basic_audit(path: Path, role: str, include_date_scan: bool = True) -> Dict[str, Any]:
    info: Dict[str, Any] = {"role": role, "path": str(path), "exists": path.exists()}
    if not path.exists():
        info["status"] = "MISSING"
        return info
    try:
        pf = pq.ParquetFile(path)
        schema = pf.schema_arrow
        cols = list(schema.names)
        info.update({
            "columns": len(cols),
            "row_count": pf.metadata.num_rows,
            "future_forbidden_columns": [c for c in cols if any(tok.lower() in c.lower() for tok in FORBIDDEN_FUTURE_PATTERNS)],
            "schema": [{"name": f.name, "type": str(f.type)} for f in schema],
        })
        if include_date_scan and "trade_date" in cols:
            mn, mx, nulls, strategy = scan_trade_date_min_max_with_strategy(path)
            info.update({
                "trade_date_min": mn,
                "trade_date_max": mx,
                "trade_date_null_count": nulls,
                "date_scan_strategy": strategy,
            })
        info["status"] = "PASS"
    except Exception as exc:
        info["status"] = "ERROR"
        info["error"] = repr(exc)
    return info


def normalize_trade_date_value(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except Exception:
        pass
    s = str(x).strip()
    if not s:
        return None
    s = re.sub(r"\.0$", "", s)
    s = re.sub(r"[^0-9]", "", s)
    if len(s) >= 8:
        return int(s[:8])
    return None


def scan_trade_date_min_max_with_strategy(path: Path) -> Tuple[Optional[int], Optional[int], int, str]:
    pf = pq.ParquetFile(path)
    if "trade_date" not in pf.schema_arrow.names:
        return None, None, 0, "column_missing"
    column_index = pf.schema_arrow.names.index("trade_date")
    metadata_min: Optional[int] = None
    metadata_max: Optional[int] = None
    metadata_nulls = 0
    metadata_complete = pf.metadata.num_row_groups > 0
    for row_group_index in range(pf.metadata.num_row_groups):
        column = pf.metadata.row_group(row_group_index).column(column_index)
        statistics = column.statistics
        if statistics is None or not statistics.has_min_max:
            metadata_complete = False
            break
        value_min = normalize_trade_date_value(statistics.min)
        value_max = normalize_trade_date_value(statistics.max)
        if value_min is None or value_max is None:
            metadata_complete = False
            break
        metadata_min = value_min if metadata_min is None else min(metadata_min, value_min)
        metadata_max = value_max if metadata_max is None else max(metadata_max, value_max)
        metadata_nulls += int(statistics.null_count or 0)
    if metadata_complete:
        return metadata_min, metadata_max, metadata_nulls, "row_group_statistics"

    mn = None
    mx = None
    nulls = 0
    for batch in pf.iter_batches(batch_size=262144, columns=["trade_date"]):
        arr = batch.column(0).to_pandas()
        vals = arr.map(normalize_trade_date_value)
        nulls += int(vals.isna().sum())
        if vals.notna().any():
            vmin = int(vals.min())
            vmax = int(vals.max())
            mn = vmin if mn is None else min(mn, vmin)
            mx = vmax if mx is None else max(mx, vmax)
    return mn, mx, nulls, "column_batch_scan_fallback"


def scan_trade_date_min_max(path: Path) -> Tuple[Optional[int], Optional[int], int]:
    mn, mx, nulls, _strategy = scan_trade_date_min_max_with_strategy(path)
    return mn, mx, nulls


def should_run_full_maintenance(requested: bool) -> bool:
    """Keep full rebuild/enrichment/audits outside the default daily SLA."""
    return bool(requested)


def read_ts_latest_map(path: Path, log: Logger, role: str) -> Dict[str, int]:
    pf = pq.ParquetFile(path)
    required = {"ts_code", "trade_date"}
    if not required.issubset(set(pf.schema_arrow.names)):
        raise RuntimeError(f"{role}_missing_ts_code_or_trade_date")
    latest: Dict[str, int] = {}
    rows = 0
    for batch in pf.iter_batches(batch_size=262144, columns=["ts_code", "trade_date"]):
        df = batch.to_pandas()
        df["trade_date"] = df["trade_date"].map(normalize_trade_date_value)
        df = df.dropna(subset=["ts_code", "trade_date"])
        for ts, value in df.groupby("ts_code", observed=True)["trade_date"].max().items():
            if pd.isna(value):
                continue
            v = int(value)
            if v > latest.get(str(ts), 0):
                latest[str(ts)] = v
        rows += len(df)
    log.log(f"read latest date map role={role}: codes={len(latest)} rows={rows}")
    return latest


def scalar_for_trade_date(schema: pa.Schema, value: int) -> Any:
    f = schema.field("trade_date")
    if pa.types.is_string(f.type) or pa.types.is_large_string(f.type):
        return str(value)
    return value


def read_latest_static_map(
    path: Path,
    date_value: int,
    wanted_cols: List[str],
    log: Logger,
    active_ts_codes: Optional[Iterable[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow
    cols = [c for c in wanted_cols if c in schema.names]
    if "ts_code" not in cols:
        cols = ["ts_code"] + cols
    if "trade_date" not in cols:
        cols = ["trade_date"] + cols
    cols = list(dict.fromkeys(cols))
    best: Dict[str, Dict[str, Tuple[int, Any]]] = {c: {} for c in cols if c not in ("ts_code", "trade_date")}
    trade_date_index = schema.names.index("trade_date")
    latest_row_groups = []
    for row_group_index in range(pf.metadata.num_row_groups):
        statistics = pf.metadata.row_group(row_group_index).column(trade_date_index).statistics
        if statistics is None or not statistics.has_min_max:
            latest_row_groups = []
            break
        group_max = normalize_trade_date_value(statistics.max)
        if group_max is not None and group_max >= int(date_value):
            latest_row_groups.append(row_group_index)
    active = {str(value) for value in (active_ts_codes or [])}
    if latest_row_groups:
        table = pf.read_row_groups(latest_row_groups, columns=cols)
        batch_source = table.to_batches(max_chunksize=131072)
        strategy = "latest_row_groups"
    else:
        batch_source = pf.iter_batches(batch_size=131072, columns=cols)
        strategy = "full_scan_fallback"
    log.log(
        f"read latest static rows: columns={len(cols)} max_date={date_value} "
        f"strategy={strategy} row_groups={len(latest_row_groups)} active_codes={len(active)}"
    )
    for batch in batch_source:
        df = batch.to_pandas()
        df["trade_date"] = df["trade_date"].map(normalize_trade_date_value)
        df = df.dropna(subset=["ts_code", "trade_date"])
        if active:
            df = df[df["ts_code"].astype(str).isin(active)]
        if df.empty:
            continue
        df = df.sort_values(["ts_code", "trade_date"])
        for col in best:
            part = df[["ts_code", "trade_date", col]].dropna(subset=[col])
            if part.empty:
                continue
            text = part[col].astype(str).str.strip()
            part = part[~text.isin(["", "nan", "None", "<NA>"])]
            for row in part.itertuples(index=False):
                ts = str(row.ts_code)
                date_i = int(row.trade_date)
                prev = best[col].get(ts)
                if prev is None or date_i >= prev[0]:
                    best[col][ts] = (date_i, getattr(row, col))
    maps: Dict[str, Dict[str, Any]] = {}
    for col, values in best.items():
        maps[col] = {ts: value for ts, (_date_i, value) in values.items()}
    return maps


EXT_MARKET_SUFFIX_BY_ID = {
    31: "HK",
    49: "HK_FUND",
    71: "HK_CONNECT",
    48: "HK_ETF",
    43: "HK_OTHER",
    27: "HK_OTHER",
    98: "HK_OTHER",
}
EXT_MARKET_ID_BY_SUFFIX = {suffix: market_id for market_id, suffix in EXT_MARKET_SUFFIX_BY_ID.items()}
EQUITY_CODE_PREFIXES_BY_MARKET = {
    "sh": ("600", "601", "603", "605", "688", "689"),
    "sz": ("000", "001", "002", "003", "300", "301", "302"),
    "bj": ("8", "9"),
}
PYTDX_HQ_HOSTS = [
    ("上证云成都电信一", "218.6.170.47", 7709),
    ("武汉电信主站1", "202.100.166.27", 7709),
    ("深圳双线主站1", "119.147.212.81", 7709),
]


def clean_tdx_text(raw: bytes) -> str:
    raw = raw.split(b"\x00", 1)[0].strip()
    if not raw:
        return ""
    for enc in ("gb18030", "gbk", "utf-8"):
        try:
            return raw.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return ""


def lookup_tdx_ds_name(data: bytes, code: str, suffix: str) -> str:
    if suffix == "BJ":
        marker = bytes([0x01, 0x2C, 0x02, 0x00, 0x00])
    else:
        market_id = EXT_MARKET_ID_BY_SUFFIX.get(suffix)
        if market_id is None:
            return ""
        marker = bytes([0x02, market_id, 0x03, 0x00, 0x00])
    code_field = code.encode("ascii") + b"\x00" * (23 - len(code))
    idx = data.find(marker + code_field)
    if idx < 0:
        return ""
    name_start = idx + len(marker) + len(code_field)
    return clean_tdx_text(data[name_start:name_start + 48])


def build_tdx_static_name_map(tdx_root: Path, wanted_ts_codes: Optional[Iterable[str]] = None) -> Dict[str, str]:
    ds_path = tdx_root / "T0002" / "hq_cache" / "ds_stk.dat"
    if not ds_path.exists():
        ds_path = tdx_root / "T0002" / "T0002" / "hq_cache" / "ds_stk.dat"
    if not ds_path.exists():
        return {}
    data = ds_path.read_bytes()
    result: Dict[str, str] = {}
    if wanted_ts_codes is not None:
        for ts_code in sorted({str(value) for value in wanted_ts_codes}):
            code, separator, suffix = ts_code.partition(".")
            if not separator or suffix not in {"BJ", *EXT_MARKET_ID_BY_SUFFIX}:
                continue
            name = lookup_tdx_ds_name(data, code, suffix)
            if name:
                result[ts_code] = name
        return result
    for p in (tdx_root / "vipdoc" / "ds" / "lday").glob("*.day"):
        ts_code = _parse_ext_market_file(p.name.lower())
        if not ts_code:
            continue
        code, suffix = ts_code.split(".", 1)
        name = lookup_tdx_ds_name(data, code, suffix)
        if name:
            result[ts_code] = name
    for p in (tdx_root / "vipdoc" / "bj" / "lday").glob("bj*.day"):
        m = re.match(r"^bj(\d{6})\.day$", p.name.lower())
        if not m:
            continue
        code = m.group(1)
        name = lookup_tdx_ds_name(data, code, "BJ")
        if name:
            result[f"{code}.BJ"] = name
    return result


def fetch_pytdx_static_names(ts_codes: Iterable[str], log: Logger) -> Dict[str, str]:
    wanted_by_market: Dict[int, Dict[str, str]] = {0: {}, 1: {}, 2: {}}
    for ts in ts_codes:
        code, _, suffix = str(ts).partition(".")
        if suffix == "SZ":
            wanted_by_market[0][code] = ts
        elif suffix == "SH":
            wanted_by_market[1][code] = ts
        elif suffix == "BJ":
            wanted_by_market[2][code] = ts
    wanted_by_market = {market: codes for market, codes in wanted_by_market.items() if codes}
    if not wanted_by_market:
        return {}
    try:
        from pytdx.hq import TdxHq_API
    except Exception as exc:
        log.log(f"warning pytdx import failed for static names: {repr(exc)}")
        return {}
    api = TdxHq_API(heartbeat=False, auto_retry=True)
    connected = False
    host_used = ""
    for name, host, port in PYTDX_HQ_HOSTS:
        try:
            if api.connect(host, port, time_out=2):
                connected = True
                host_used = f"{name} {host}:{port}"
                break
        except Exception:
            continue
    if not connected:
        log.log("warning no pytdx host available for static names")
        return {}
    found: Dict[str, str] = {}
    try:
        for market, wanted in wanted_by_market.items():
            remaining = set(wanted)
            try:
                count = api.get_security_count(market)
            except Exception as exc:
                log.log(f"warning pytdx security count failed market={market}: {repr(exc)}")
                continue
            for start in range(0, int(count), 1000):
                try:
                    rows = api.get_security_list(market, start) or []
                except Exception as exc:
                    log.log(f"warning pytdx security list failed market={market} start={start}: {repr(exc)}")
                    continue
                for row in rows:
                    code = str(row.get("code", ""))
                    if code in remaining:
                        name = str(row.get("name", "")).strip()
                        if name:
                            found[wanted[code]] = name
                        remaining.discard(code)
                if not remaining:
                    break
    finally:
        try:
            api.disconnect()
        except Exception:
            pass
    log.log(f"loaded pytdx static names: requested={sum(len(v) for v in wanted_by_market.values())} found={len(found)} host={host_used}")
    return found


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


def load_tdx_xdxr_events(
    tdx_root: Path,
    log: Logger,
    min_trade_date: Optional[int] = None,
    wanted_ts_codes: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    path = tdx_root / "T0002" / "hq_cache" / "gbbq"
    if not path.exists():
        log.log(f"warning tdx xdxr cache missing: {path}")
        return empty_xdxr_events()
    source_stat = path.stat()
    fingerprint = {
        "source_path": str(path),
        "source_size": int(source_stat.st_size),
        "source_mtime_ns": int(source_stat.st_mtime_ns),
        "cache_schema_version": 1,
    }
    cache_path = XDXR_CACHE_ROOT / "tdx_xdxr_category1.parquet"
    manifest_path = XDXR_CACHE_ROOT / "manifest.json"
    out: Optional[pd.DataFrame] = None
    if cache_path.exists() and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if all(manifest.get(key) == value for key, value in fingerprint.items()):
                out = pd.read_parquet(cache_path)
                log.log(f"loaded tdx xdxr persistent cache: rows={len(out)}")
        except Exception as exc:
            log.log(f"warning tdx xdxr persistent cache invalid: {repr(exc)}")
    if out is None:
        try:
            from pytdx.reader import GbbqReader
        except Exception as exc:
            log.log(f"warning pytdx GbbqReader import failed: {repr(exc)}")
            return empty_xdxr_events()
        try:
            raw = GbbqReader().get_df(str(path))
        except Exception as exc:
            log.log(f"warning tdx xdxr cache read failed: {repr(exc)}")
            return empty_xdxr_events()
        if raw is None or raw.empty or "category" not in raw.columns:
            log.log("warning tdx xdxr cache empty or missing category")
            return empty_xdxr_events()
        raw = raw[pd.to_numeric(raw["category"], errors="coerce").eq(1)].copy()
        if raw.empty:
            log.log("warning tdx xdxr cache has no category=1 dividend/split rows")
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
        out = out.dropna(subset=["ts_code", "_xdxr_trade_date"]).drop_duplicates(["ts_code", "_xdxr_trade_date"], keep="last")
        ensure_dir(XDXR_CACHE_ROOT)
        cache_tmp = cache_path.with_suffix(".tmp.parquet")
        out.to_parquet(cache_tmp, index=False)
        os.replace(str(cache_tmp), str(cache_path))
        write_json(manifest_path, {**fingerprint, "row_count": int(len(out))})
        log.log(f"rebuilt tdx xdxr persistent cache: rows={len(out)}")
    if min_trade_date is not None:
        out = out[pd.to_numeric(out["_xdxr_trade_date"], errors="coerce").ge(int(min_trade_date))]
    if wanted_ts_codes is not None:
        wanted = {str(value) for value in wanted_ts_codes}
        out = out[out["ts_code"].astype(str).isin(wanted)]
    log.log(f"selected tdx xdxr events for daily window: rows={len(out)}")
    return out


def apply_xdxr_pre_close(df: pd.DataFrame, raw_pre_close: pd.Series) -> tuple[pd.Series, pd.Series]:
    required = ["xdxr_fenhong", "xdxr_peigujia", "xdxr_songzhuangu", "xdxr_peigu"]
    if not set(required).issubset(df.columns):
        return raw_pre_close, pd.Series(False, index=df.index)
    event_present = df[required].notna().any(axis=1)
    fenhong = pd.to_numeric(df["xdxr_fenhong"], errors="coerce").fillna(0.0)
    peigujia = pd.to_numeric(df["xdxr_peigujia"], errors="coerce").fillna(0.0)
    songzhuangu = pd.to_numeric(df["xdxr_songzhuangu"], errors="coerce").fillna(0.0)
    peigu = pd.to_numeric(df["xdxr_peigu"], errors="coerce").fillna(0.0)
    denominator = 1.0 + songzhuangu / 10.0 + peigu / 10.0
    adjusted = (raw_pre_close - fenhong / 10.0 + peigujia * peigu / 10.0) / denominator.replace(0, np.nan)
    use_adjusted = event_present & raw_pre_close.notna() & raw_pre_close.ne(0) & denominator.gt(0)
    return raw_pre_close.mask(use_adjusted, adjusted), use_adjusted


def blank_or_missing(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).str.strip().isin(["", "nan", "None", "<NA>"])


def _parse_ext_market_file(name: str) -> Optional[str]:
    """Parse extended market filenames like 31#00700.day → 00700.HK"""
    m = re.match(r"^(\d+)#(\d{5})\.day$", name)
    if not m:
        return None
    market_id = int(m.group(1))
    code = m.group(2)
    # 31=香港主板, 49=香港基金, 71=港股通, 48/43/27/98=其他港股板块
    suffix = EXT_MARKET_SUFFIX_BY_ID.get(market_id)
    if suffix is None:
        return None
    return f"{code}.{suffix}"


def discover_day_files(tdx_root: Path) -> List[Tuple[str, Path]]:
    candidates = []
    vipdoc = tdx_root / "vipdoc"
    if not vipdoc.exists():
        return candidates
    for p in vipdoc.rglob("*.day"):
        name = p.name.lower()
        # A股标准格式: sh600000.day / sz000001.day / bj8xxxxx.day
        m = re.match(r"^(sh|sz|bj)(\d{6})\.day$", name)
        if m:
            prefix, code = m.group(1), m.group(2)
            if not code.startswith(EQUITY_CODE_PREFIXES_BY_MARKET[prefix]):
                continue
            if prefix == "sh":
                ts = f"{code}.SH"
            elif prefix == "sz":
                ts = f"{code}.SZ"
            else:
                ts = f"{code}.BJ"
            candidates.append((ts, p))
            continue
        # 扩展市场格式: 31#00700.day (港股/港股通/基金)
        ts = _parse_ext_market_file(name)
        if ts:
            candidates.append((ts, p))
    return candidates


DAY_STRUCT = struct.Struct("<IIIIIfII")
EXT_MARKET_DAY_STRUCT = struct.Struct("<IfffffII")


def is_ext_market_ts(ts_code: str) -> bool:
    return ts_code.endswith((".HK", ".HK_FUND", ".HK_CONNECT", ".HK_ETF", ".HK_OTHER"))


def is_a_bj_ts(ts_code: str) -> bool:
    return bool(re.match(r"^\d{6}\.(SH|SZ|BJ)$", ts_code))


def read_day_tail(ts_code: str, path: Path, tail_records: int = 360) -> pd.DataFrame:
    size = path.stat().st_size
    rec_size = DAY_STRUCT.size
    n = size // rec_size
    if n <= 0:
        return pd.DataFrame()
    start = max(0, n - tail_records)
    rows = []
    with path.open("rb") as f:
        f.seek(start * rec_size)
        data = f.read((n - start) * rec_size)
    for i in range(0, len(data), rec_size):
        chunk = data[i:i + rec_size]
        if len(chunk) < rec_size:
            continue
        if is_ext_market_ts(ts_code):
            date_i, open_i, high_i, low_i, close_i, amount_f, vol_u, _reserved = EXT_MARKET_DAY_STRUCT.unpack(chunk)
        else:
            date_i, open_i, high_i, low_i, close_i, amount_f, vol_u, _reserved = DAY_STRUCT.unpack(chunk)
            open_i = open_i / 100.0
            high_i = high_i / 100.0
            low_i = low_i / 100.0
            close_i = close_i / 100.0
        if date_i <= 19000101:
            continue
        rows.append({
            "ts_code": ts_code,
            "trade_date": int(date_i),
            "open": float(open_i),
            "high": float(high_i),
            "low": float(low_i),
            "close": float(close_i),
            "amount": float(amount_f),
            "vol": int(vol_u),
            "volume": int(vol_u),
        })
    return pd.DataFrame(rows)


def collect_increment_history(
    tdx_root: Path,
    base_after_date: int,
    log: Logger,
    selector_latest_by_ts: Optional[Dict[str, int]] = None,
    backtest_latest_by_ts: Optional[Dict[str, int]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    files = discover_day_files(tdx_root)
    log.log(f"discovered valid .day files: {len(files)}")
    max_date = None
    latest_files = 0
    active = []
    symbol_gap_files = 0
    for ts, p in files:
        try:
            if p.stat().st_size < DAY_STRUCT.size:
                continue
            with p.open("rb") as f:
                f.seek(-DAY_STRUCT.size, os.SEEK_END)
                rec = DAY_STRUCT.unpack(f.read(DAY_STRUCT.size))
            d = int(rec[0])
            if max_date is None or d > max_date:
                max_date = d
            if selector_latest_by_ts is not None and backtest_latest_by_ts is not None:
                selector_cutoff = selector_latest_by_ts.get(ts, 0)
                backtest_cutoff = backtest_latest_by_ts.get(ts, 0)
                cutoff = min(selector_cutoff, backtest_cutoff)
                if is_a_bj_ts(ts) and d > cutoff:
                    active.append((ts, p, d))
                    if cutoff < base_after_date:
                        symbol_gap_files += 1
            elif d > base_after_date:
                active.append((ts, p, d))
        except Exception:
            continue
    if max_date is not None:
        latest_files = sum(1 for _ts, _p, d in active if d == max_date)
    log.log(
        f"tdx max date={max_date}, active files needing append/repair: {len(active)}, "
        f"symbol_gap_files={symbol_gap_files}, base_after_date={base_after_date}, latest_files={latest_files}"
    )

    parts = []
    for idx, (ts, p, _d) in enumerate(active, 1):
        try:
            df = read_day_tail(ts, p, tail_records=DAILY_FORMULA_LOOKBACK_RECORDS)
            if not df.empty:
                parts.append(df)
        except Exception as exc:
            log.log(f"warning read failed: {ts} {p} {repr(exc)}")
        if idx % 500 == 0:
            log.log(f"read tails: {idx}/{len(active)}")
    if parts:
        hist = pd.concat(parts, ignore_index=True)
        hist = hist.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")
        hist = hist.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    else:
        hist = pd.DataFrame()
    continuity = audit_cross_day_continuity(hist)
    if continuity["status"] != "PASS":
        log.log(f"cross-day continuity rejected: issues={continuity['issue_count']} samples={continuity.get('samples', [])[:3]}")
    summary = {
        "tdx_root": str(tdx_root),
        "day_file_count": len(files),
        "active_file_count_gt_current": len(active),
        "symbol_gap_file_count": symbol_gap_files,
        "tdx_max_trade_date": max_date,
        "latest_files_count": latest_files,
        "history_rows_read": int(len(hist)),
        "daily_formula_lookback_records": DAILY_FORMULA_LOOKBACK_RECORDS,
        "cross_day_continuity": continuity,
    }
    return hist, summary


def ema_by_group(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=1).mean()


def compute_formula_features(
    hist: pd.DataFrame,
    base_after_date: int,
    latest_static: Dict[str, Dict[str, Any]],
    log: Logger,
    emit_all_rows: bool = False,
    xdxr_events: Optional[pd.DataFrame] = None,
    emit_after_by_ts: Optional[Dict[str, int]] = None,
) -> pd.DataFrame:
    if hist.empty:
        return hist
    df = hist.copy()
    df["_sort_trade_date"] = pd.to_numeric(df["trade_date"], errors="coerce").astype("Int64")
    if xdxr_events is not None and not xdxr_events.empty:
        df = df.merge(
            xdxr_events,
            how="left",
            left_on=["ts_code", "_sort_trade_date"],
            right_on=["ts_code", "_xdxr_trade_date"],
        )
        df = df.drop(columns=["_xdxr_trade_date"])
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    g = df.groupby("ts_code", group_keys=False)

    raw_pre_close = g["close"].shift(1)
    df["pre_close"], xdxr_adjusted = apply_xdxr_pre_close(df, raw_pre_close)
    df["pct_chg"] = (df["close"] / df["pre_close"] - 1.0) * 100.0
    df.loc[df["pre_close"].isna() | (df["pre_close"] == 0), "pct_chg"] = np.nan

    for n in [1, 3, 5, 10, 20]:
        df[f"ret_{n}"] = (df["close"] / g["close"].shift(n) - 1.0) * 100.0
        df[f"ret_{n}d"] = df[f"ret_{n}"]

    df["amp_1d"] = (df["high"] - df["low"]) / df["pre_close"] * 100.0
    df["amplitude_pct"] = df["amp_1d"]
    df["zge_daily_amplitude_pct"] = df["amp_1d"]

    df["bar_range"] = (df["high"] - df["low"]).replace(0, np.nan)
    df["close_pos"] = (df["close"] - df["low"]) / df["bar_range"]
    df["bar_close_pos"] = df["close_pos"]
    df["body_pct"] = (df["close"] - df["open"]).abs() / df["pre_close"] * 100.0
    df["upper_shadow_pct"] = (df["high"] - np.maximum(df["open"], df["close"])) / df["pre_close"] * 100.0
    df["lower_shadow_pct"] = (np.minimum(df["open"], df["close"]) - df["low"]) / df["pre_close"] * 100.0

    for n in [3, 5, 6, 10, 12, 14, 20, 24, 28, 30, 40, 57, 60, 114]:
        df[f"ma{n}"] = g["close"].transform(lambda s, n=n: s.rolling(n, min_periods=1).mean())
        df[f"ma_close_{n}"] = df[f"ma{n}"]
    df["MA60"] = df["ma60"]

    for n in [5, 10, 20]:
        df[f"amp_{n}d_mean"] = g["amp_1d"].transform(lambda s, n=n: s.rolling(n, min_periods=1).mean())
        df[f"vol_ma{n}"] = g["vol"].transform(lambda s, n=n: s.rolling(n, min_periods=1).mean())
        df[f"vol_ratio_{n}"] = df["vol"] / df[f"vol_ma{n}"].replace(0, np.nan)

    df["vol_ma60"] = g["vol"].transform(lambda s: s.rolling(60, min_periods=1).mean())
    df["vol_ratio_60"] = df["vol"] / df["vol_ma60"].replace(0, np.nan)
    df["amount_ma20"] = g["amount"].transform(lambda s: s.rolling(20, min_periods=1).mean())
    df["amount_ratio_20"] = df["amount"] / df["amount_ma20"].replace(0, np.nan)

    df["high_20"] = g["high"].transform(lambda s: s.rolling(20, min_periods=1).max())
    df["high_20_prev"] = g["high"].transform(lambda s: s.rolling(20, min_periods=1).max().shift(1))
    df["close_to_high20_prev"] = df["close"] / df["high_20_prev"].replace(0, np.nan)
    df["close_to_ma20"] = df["close"] / df["ma20"].replace(0, np.nan) - 1.0
    df["close_to_ma60"] = df["close"] / df["ma60"].replace(0, np.nan) - 1.0

    df["BBI0"] = (df["ma3"] + df["ma6"] + df["ma12"] + df["ma24"]) / 4.0
    df["BBI"] = df["BBI0"]
    df["zge_bbi"] = df["BBI0"]
    df["bbi"] = df["BBI0"]

    # Z哥白线：EMA(EMA(C,10),10)
    df["ema10"] = g["close"].transform(lambda s: ema_by_group(s, 10))
    df["zge_white_line"] = df.groupby("ts_code", group_keys=False)["ema10"].transform(lambda s: ema_by_group(s, 10))
    df["white_line"] = df["zge_white_line"]

    # 大哥/黄线：MA14/28/57/114 average.
    df["zge_yellow_line"] = (df["ma14"] + df["ma28"] + df["ma57"] + df["ma114"]) / 4.0
    df["yellow_line"] = df["zge_yellow_line"]

    df["zge_is_uptrend"] = (df["zge_white_line"] > df["zge_yellow_line"]).astype(int)
    df["zge_is_uptrend_basic"] = df["zge_is_uptrend"]

    # KDJ
    low9 = g["low"].transform(lambda s: s.rolling(9, min_periods=1).min())
    high9 = g["high"].transform(lambda s: s.rolling(9, min_periods=1).max())
    rsv = (df["close"] - low9) / (high9 - low9).replace(0, np.nan) * 100.0
    rsv = rsv.fillna(50.0)
    df["RSV"] = rsv
    # Approximate TDX SMA(X,3,1) recursively: k=2/3 prev + 1/3 rsv
    def rec_sma(s: pd.Series) -> pd.Series:
        out = []
        prev = 50.0
        for x in s.astype(float).fillna(50.0):
            prev = (2.0 * prev + x) / 3.0
            out.append(prev)
        return pd.Series(out, index=s.index)
    df["K"] = g["RSV"].transform(rec_sma)
    df["D"] = df.groupby("ts_code", group_keys=False)["K"].transform(rec_sma)
    df["J"] = 3.0 * df["K"] - 2.0 * df["D"]
    df["zge_k"] = df["K"]
    df["zge_d"] = df["D"]
    df["zge_j"] = df["J"]
    df["kdj_j"] = df["J"]

    # RSI3
    delta = g["close"].diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    df["rsi3"] = up.groupby(df["ts_code"]).transform(lambda s: s.rolling(3, min_periods=1).mean()) / (
        up.groupby(df["ts_code"]).transform(lambda s: s.rolling(3, min_periods=1).mean()) +
        down.groupby(df["ts_code"]).transform(lambda s: s.rolling(3, min_periods=1).mean())
    ).replace(0, np.nan) * 100.0
    df["zge_rsi3"] = df["rsi3"]

    # MACD
    ema12 = g["close"].transform(lambda s: ema_by_group(s, 12))
    ema26 = g["close"].transform(lambda s: ema_by_group(s, 26))
    df["macd_dif"] = ema12 - ema26
    df["macd_dea"] = df.groupby("ts_code", group_keys=False)["macd_dif"].transform(lambda s: ema_by_group(s, 9))
    df["macd_bar"] = (df["macd_dif"] - df["macd_dea"]) * 2.0
    df["macd_hist"] = df["macd_bar"]
    df["DIF"] = df["macd_dif"]
    df["DEA"] = df["macd_dea"]
    df["MACD"] = df["macd_bar"]

    # Use the read-only canonical v1.9.2 main-chart formula for all selector
    # entries.  The former local approximation omitted the brick buy fields,
    # changed gold text into a numeric flag, and altered B3 semantics.
    canonical = _compute_canonical_v192_formula(df)
    missing_projection = [
        field for field in V192_REQUIRED_CANONICAL_PROJECTION_FIELDS
        if field not in canonical.columns
    ]
    if missing_projection:
        raise RuntimeError(
            f"canonical v1.9.2 formula authority missing required projection fields: {missing_projection}"
        )
    invalid_projection = [
        field for field in V192_REQUIRED_CANONICAL_PROJECTION_FIELDS
        if not np.isfinite(pd.to_numeric(canonical[field], errors="coerce").to_numpy(dtype=float, na_value=np.nan)).all()
    ]
    if invalid_projection:
        raise RuntimeError(
            f"canonical v1.9.2 formula authority invalid required projection fields: {invalid_projection}"
        )
    for field in (*V192_FORMULA_FIELDS, *V192_REQUIRED_CANONICAL_PROJECTION_FIELDS):
        if field == "formula_source":
            continue
        if field not in canonical.columns:
            raise RuntimeError(f"canonical v1.9.2 formula did not emit {field}")
        df[field] = canonical[field].to_numpy()
    df["breakout_signal"] = df["breakout"].astype(int)
    df["double_breakout_signal"] = df["double_breakout"].astype(int)

    df["ref_b123_union_debug"] = df[["B1", "B2", "B3"]].sum(axis=1)

    # Common aliases / gate fields.
    df["BASEOK"] = ((df["close"] > 0) & (df["vol"] >= 0)).astype(int)
    df["HAS_B"] = ((df["B1"] == 1) | (df["B2"] == 1) | (df["B3"] == 1)).astype(int)
    df["DOUBLE_BREAK"] = df["double_breakout_signal"]
    df["BUY1"] = df["B2"]
    df["BUY2"] = df["B3"]
    df["KEY_K"] = df["breakout_signal"]
    df["PRE_ABN"] = ((df["vol_ratio_20"] > 1.2) | (df["amount_ratio_20"] > 1.2)).astype(int)

    df["feature_available_date"] = df["trade_date"]
    df["formula_source"] = CANONICAL_FORMULA_SOURCE
    df["source_panel_path"] = ""
    df["pct_chg_source"] = np.where(xdxr_adjusted, "tdx_xdxr_adjusted_pre_close", "tdx_day_raw_previous_close")
    df = df.drop(columns=[c for c in ["_sort_trade_date", "xdxr_fenhong", "xdxr_peigujia", "xdxr_songzhuangu", "xdxr_peigu"] if c in df.columns])

    # Static mapping from latest selector row.
    for col, mapping in latest_static.items():
        if col in df.columns:
            continue
        df[col] = df["ts_code"].map(mapping)
    ts_suffix = df["ts_code"].astype(str).str.split(".").str[-1]
    hk_mask = df["ts_code"].astype(str).str.match(r"^\d{5}\.(HK|HK_FUND|HK_CONNECT|HK_ETF|HK_OTHER)$")
    if "exchange" not in df.columns:
        df["exchange"] = ts_suffix
    else:
        mask = blank_or_missing(df["exchange"])
        df.loc[mask, "exchange"] = ts_suffix[mask]
    market_values = np.where(df["ts_code"].str.endswith(".BJ"), "BJ", np.where(hk_mask, "HK", "A_SHARE"))
    if "market_type" not in df.columns:
        df["market_type"] = market_values
    else:
        mask = blank_or_missing(df["market_type"]) | (hk_mask & (df["market_type"].astype(str) != "HK"))
        df.loc[mask, "market_type"] = pd.Series(market_values, index=df.index)[mask]
    currency_values = np.where(hk_mask, "HKD", "CNY")
    if "trade_currency" not in df.columns:
        df["trade_currency"] = currency_values
    else:
        mask = blank_or_missing(df["trade_currency"]) | (hk_mask & (df["trade_currency"].astype(str) != "HKD"))
        df.loc[mask, "trade_currency"] = pd.Series(currency_values, index=df.index)[mask]
    is_a_share_values = df["ts_code"].str.match(r"^\d{6}\.(SH|SZ|BJ)$")
    if "is_a_share" not in df.columns:
        df["is_a_share"] = is_a_share_values
    else:
        mask = df["is_a_share"].isna() | hk_mask
        df.loc[mask, "is_a_share"] = is_a_share_values[mask]
    is_bj_values = df["ts_code"].str.endswith(".BJ")
    if "is_bj" not in df.columns:
        df["is_bj"] = is_bj_values
    else:
        mask = df["is_bj"].isna() | is_bj_values
        df.loc[mask, "is_bj"] = is_bj_values[mask]
    is_hk_connect_values = df["ts_code"].str.endswith(".HK_CONNECT")
    if "is_hk_connect" not in df.columns:
        df["is_hk_connect"] = is_hk_connect_values
    else:
        mask = df["is_hk_connect"].isna() | hk_mask
        df.loc[mask, "is_hk_connect"] = is_hk_connect_values[mask]

    # If bars_since_list is available from latest snapshot, increment by new sequence within stock.
    if "bars_since_list" in latest_static and "bars_since_list" not in df.columns:
        base_map = latest_static["bars_since_list"]
        seq = df.groupby("ts_code").cumcount() + 1
        df["bars_since_list"] = pd.to_numeric(df["ts_code"].map(base_map), errors="coerce").fillna(0) + seq

    if emit_all_rows:
        log.log(f"computed formula features: history_rows={len(df)}, generated_rows={len(df)}")
        return df.reset_index(drop=True)
    inc = select_generated_increment_rows(
        df,
        base_after_date=base_after_date,
        latest_by_ts=emit_after_by_ts,
    )
    log.log(f"computed formula features: history_rows={len(df)}, increment_rows={len(inc)}")
    return inc.reset_index(drop=True)


class _NoopLogger:
    def log(self, _msg: str) -> None:
        return None


def daily_formula_worker_count(symbol_count: int) -> int:
    if symbol_count < DAILY_FORMULA_PARALLEL_MIN_SYMBOLS:
        return 1
    workers = min(DAILY_FORMULA_MAX_WORKERS, max(1, int(os.cpu_count() or 1)))
    if psutil is not None:
        available_gb = psutil.virtual_memory().available / (1024 ** 3)
        if available_gb < 6:
            return 1
        if available_gb < 12:
            workers = min(workers, 2)
    return workers


def _formula_error_is_batch_level(exc: BaseException) -> bool:
    """Keep owner, schema, storage and runtime binding failures fail-closed."""

    if isinstance(exc, (KeyError, ImportError, MemoryError, OSError, PermissionError)):
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "canonical v1.9.2 formula authority",
            "cannot load canonical",
            "compute_partition_formula",
            "schema",
            "contract",
            "storage",
            "permission",
            "manifest",
            "owner",
        )
    )


def _formula_worker_context(schema_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Capture parent-bound paths required by a spawned formula worker."""

    context: Dict[str, Any] = {
        "canonical_formula_path": str(Path(CANONICAL_FORMULA_PATH).resolve()),
        "data_root": str(Path(DATA_ROOT).resolve()),
        "tdx_root": str(Path(TDX_ROOT).resolve()),
        "contract_csv": str(Path(CONTRACT_CSV).resolve()),
        "selector_pointer": str(Path(SELECTOR_POINTER).resolve()),
        "backtest_pointer": str(Path(BACKTEST_POINTER).resolve()),
    }
    if schema_context is not None:
        context["schema_context"] = {
            str(key): list(value) if isinstance(value, (tuple, list)) else value
            for key, value in schema_context.items()
        }
    return context


def _apply_formula_worker_context(context: Dict[str, Any]) -> None:
    """Restore the parent POSIX bindings before computing in a spawn child."""

    global CANONICAL_FORMULA_PATH, DATA_ROOT, TDX_ROOT, CONTRACT_CSV
    global SELECTOR_POINTER, BACKTEST_POINTER, XDXR_CACHE_ROOT, _CANONICAL_FORMULA_MODULE
    CANONICAL_FORMULA_PATH = Path(context["canonical_formula_path"]).resolve()
    DATA_ROOT = Path(context["data_root"]).resolve()
    TDX_ROOT = Path(context["tdx_root"]).resolve()
    CONTRACT_CSV = Path(context["contract_csv"]).resolve()
    SELECTOR_POINTER = Path(context["selector_pointer"]).resolve()
    BACKTEST_POINTER = Path(context["backtest_pointer"]).resolve()
    XDXR_CACHE_ROOT = DATA_ROOT / "runtime" / "cache" / TASK_NAME / "tdx_xdxr"
    _CANONICAL_FORMULA_MODULE = None


def _formula_partition_worker(
    payload: Tuple[
        int,
        pd.DataFrame,
        int,
        Dict[str, Dict[str, Any]],
        Optional[pd.DataFrame],
        Optional[Dict[str, int]],
        Tuple[str, ...],
        Dict[str, Any],
    ]
) -> Tuple[int, pd.DataFrame, List[Dict[str, Any]], int]:
    partition_index, partition_history, base_after_date, partition_static, partition_xdxr, partition_cutoffs, partition_symbols, context = payload
    _apply_formula_worker_context(context)
    try:
        result = compute_formula_features(
            partition_history,
            base_after_date,
            partition_static,
            _NoopLogger(),
            emit_all_rows=False,
            xdxr_events=partition_xdxr,
            emit_after_by_ts=partition_cutoffs,
        )
        return partition_index, result, [], os.getpid()
    except Exception as partition_error:
        if _formula_error_is_batch_level(partition_error):
            raise

        # A malformed/formula-bad stock is retried alone. A successful stock
        # keeps its generated rows; the failed stock is omitted from the shared
        # feature frame, so selector and backtest cannot create a half-updated
        # pair or a new signal for it.
        recovered: List[pd.DataFrame] = []
        failures: List[Dict[str, Any]] = []
        for symbol in partition_symbols:
            symbol = str(symbol)
            symbol_history = partition_history.loc[
                partition_history["ts_code"].astype(str).eq(symbol)
            ].copy()
            symbol_static = {
                column: {symbol: mapping[symbol]}
                for column, mapping in partition_static.items()
                if symbol in mapping
            }
            symbol_xdxr = None
            if partition_xdxr is not None and not partition_xdxr.empty:
                symbol_xdxr = partition_xdxr.loc[
                    partition_xdxr["ts_code"].astype(str).eq(symbol)
                ].copy()
            symbol_cutoffs = None
            if partition_cutoffs is not None:
                symbol_cutoffs = {symbol: int(partition_cutoffs.get(symbol, base_after_date))}
            try:
                recovered.append(
                    compute_formula_features(
                        symbol_history,
                        base_after_date,
                        symbol_static,
                        _NoopLogger(),
                        emit_all_rows=False,
                        xdxr_events=symbol_xdxr,
                        emit_after_by_ts=symbol_cutoffs,
                    )
                )
            except Exception as symbol_error:
                if _formula_error_is_batch_level(symbol_error):
                    raise
                failures.append({
                    "symbol": symbol,
                    "status": "ISOLATED",
                    "exception_type": type(symbol_error).__name__,
                    "reason": str(symbol_error),
                    "roles": ["selector", "backtest"],
                    "new_signal_rows": 0,
                })
        if recovered:
            result = pd.concat(recovered, ignore_index=True)
        else:
            result = partition_history.iloc[0:0].copy()
        return partition_index, result, failures, os.getpid()


def compute_formula_features_daily(
    hist: pd.DataFrame,
    base_after_date: int,
    latest_static: Dict[str, Dict[str, Any]],
    log: Logger,
    xdxr_events: Optional[pd.DataFrame] = None,
    emit_after_by_ts: Optional[Dict[str, int]] = None,
    worker_schema_context: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    symbols = sorted(str(value) for value in hist["ts_code"].dropna().unique())
    worker_count = daily_formula_worker_count(len(symbols))
    if worker_count <= 1:
        log.log(f"daily formula compute mode=serial symbols={len(symbols)}")
        result = compute_formula_features(
            hist,
            base_after_date,
            latest_static,
            log,
            emit_all_rows=False,
            xdxr_events=xdxr_events,
            emit_after_by_ts=emit_after_by_ts,
        )
        result.attrs["daily_formula_metadata"] = {
            "mode": "serial",
            "workers": 1,
            "symbols": len(symbols),
            "history_rows": len(hist),
            "local_failures": [],
            "worker_pids": [os.getpid()],
        }
        return result

    symbol_partitions = [list(values) for values in np.array_split(np.array(symbols, dtype=object), worker_count) if len(values)]
    worker_context = _formula_worker_context(worker_schema_context)
    payloads = []
    for partition_index, partition_symbols in enumerate(symbol_partitions):
        symbol_set = set(partition_symbols)
        partition_history = hist[hist["ts_code"].astype(str).isin(symbol_set)].copy()
        partition_static = {
            column: {symbol: value for symbol, value in mapping.items() if symbol in symbol_set}
            for column, mapping in latest_static.items()
        }
        partition_xdxr = None
        if xdxr_events is not None and not xdxr_events.empty:
            partition_xdxr = xdxr_events[xdxr_events["ts_code"].astype(str).isin(symbol_set)].copy()
        partition_cutoffs = None
        if emit_after_by_ts is not None:
            partition_cutoffs = {
                symbol: int(emit_after_by_ts.get(symbol, base_after_date))
                for symbol in symbol_set
            }
        payloads.append((
            partition_index,
            partition_history,
            base_after_date,
            partition_static,
            partition_xdxr,
            partition_cutoffs,
            tuple(str(symbol) for symbol in partition_symbols),
            worker_context,
        ))

    log.log(
        f"daily formula compute mode=process_pool workers={worker_count} "
        f"symbols={len(symbols)} history_rows={len(hist)}"
    )
    results: Dict[int, pd.DataFrame] = {}
    local_failures: List[Dict[str, Any]] = []
    worker_pids: set[int] = set()
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(_formula_partition_worker, payload): payload[0] for payload in payloads}
        for future in as_completed(futures):
            partition_index, frame, failures, worker_pid = future.result()
            results[partition_index] = frame
            local_failures.extend(failures)
            worker_pids.add(int(worker_pid))
            log.log(
                f"daily formula partition complete={len(results)}/{len(payloads)} "
                f"partition={partition_index} increment_rows={len(frame)} local_failures={len(failures)}"
            )
    combined = pd.concat([results[index] for index in sorted(results)], ignore_index=True)
    combined = combined.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    combined.attrs["daily_formula_metadata"] = {
        "mode": "process_pool",
        "workers": int(worker_count),
        "symbols": len(symbols),
        "history_rows": len(hist),
        "partitions": len(payloads),
        "local_failures": sorted(local_failures, key=lambda item: item["symbol"]),
        "worker_context": worker_context,
        "worker_pids": sorted(worker_pids),
    }
    return combined


def select_generated_increment_rows(
    features: pd.DataFrame,
    *,
    base_after_date: int,
    latest_by_ts: Optional[Dict[str, int]] = None,
) -> pd.DataFrame:
    """Select generated rows after each symbol's true panel cutoff."""

    if features.empty:
        return features.copy()
    if latest_by_ts is None:
        cutoff = pd.Series(int(base_after_date), index=features.index, dtype="int64")
    else:
        cutoff = features["ts_code"].map(latest_by_ts).fillna(int(base_after_date)).astype(int)
    return features[features["trade_date"].astype(int) > cutoff].copy()


def filter_increment_rows(
    features: pd.DataFrame,
    latest_by_ts: Optional[Dict[str, int]],
    role: str,
    log: Logger,
    default_cutoff: int = 0,
) -> pd.DataFrame:
    if features.empty:
        return features.copy()
    if latest_by_ts is None:
        cutoff = pd.Series(default_cutoff, index=features.index, dtype="int64")
    else:
        cutoff = features["ts_code"].map(latest_by_ts).fillna(default_cutoff).astype(int)
    inc = features[features["trade_date"].astype(int) > cutoff].copy()
    log.log(f"filtered increment rows role={role}: rows={len(inc)} codes={inc['ts_code'].nunique() if len(inc) else 0}")
    return inc.reset_index(drop=True)


def is_formula_like_column(col: str) -> bool:
    cl = col.lower()
    return any(tok.lower() in cl for tok in FORMULA_LIKE_TOKENS)


def default_series_for_field(field: pa.Field, n: int, col: str, base_df: pd.DataFrame, policy: Optional[Dict[str, Any]] = None) -> pd.Series:
    if col == "trade_date" and "trade_date" in base_df.columns:
        return base_df["trade_date"]
    if col == "ts_code" and "ts_code" in base_df.columns:
        return base_df["ts_code"]
    if col == "feature_available_date" and "trade_date" in base_df.columns:
        return base_df["trade_date"]
    if policy and allowed_missing_default_for_field(col, policy):
        value = runtime_default_for_field(col)
        if value is not None:
            return pd.Series([value] * n)

    t = field.type
    if pa.types.is_boolean(t):
        return pd.Series([False] * n)
    if pa.types.is_integer(t):
        if is_formula_like_column(col):
            return pd.Series([0] * n)
        return pd.Series([pd.NA] * n)
    if pa.types.is_floating(t):
        if is_formula_like_column(col):
            return pd.Series([0.0] * n)
        return pd.Series([np.nan] * n)
    if pa.types.is_string(t) or pa.types.is_large_string(t):
        return pd.Series([""] * n)
    return pd.Series([None] * n)


def coerce_series_to_arrow(series: pd.Series, field: pa.Field) -> pa.Array:
    t = field.type
    if pa.types.is_boolean(t):
        s = series.fillna(False)
        if s.dtype != bool:
            s = s.map(lambda x: bool(int(x)) if str(x).strip() not in ("", "nan", "None", "False", "false") else False)
        return pa.array(s.tolist(), type=t)
    if pa.types.is_integer(t):
        s = pd.to_numeric(series, errors="coerce").fillna(0)
        # Preserve YYYYMMDD as int if trade_date/feature_available_date.
        return pa.array(s.astype(np.int64).tolist(), type=t)
    if pa.types.is_floating(t):
        s = pd.to_numeric(series, errors="coerce")
        return pa.array(s.astype(float).tolist(), type=t)
    if pa.types.is_string(t) or pa.types.is_large_string(t) or pa.types.is_dictionary(t):
        s = series.where(~series.isna(), "")
        s = s.astype(str)
        s = s.replace({"nan": "", "None": "", "<NA>": ""})
        return pa.array(s.tolist(), type=pa.string())
    # Fallback.
    return pa.array(series.tolist(), type=t)


def build_table_for_schema(new_df: pd.DataFrame, schema: pa.Schema, role: str, policy: Optional[Dict[str, Any]] = None) -> Tuple[pa.Table, Dict[str, Any]]:
    if role == "selector":
        contract_issues = _v192_contract_issues(new_df)
        if contract_issues:
            raise RuntimeError(";".join(contract_issues))
        schema_missing = sorted(CONTRACT_REQUIRED_V192_SELECTOR_COLUMNS - set(schema.names))
        if schema_missing:
            raise RuntimeError(f"v1.9.2 selector schema missing:{','.join(schema_missing)}")
    n = len(new_df)
    arrays = []
    fill_rows = []
    generated_cols = set(new_df.columns)
    for field in schema:
        col = field.name
        if col in new_df.columns:
            s = new_df[col]
            source = "computed_or_mapped"
        else:
            s = default_series_for_field(field, n, col, new_df, policy=policy)
            if policy and allowed_missing_default_for_field(col, policy):
                source = "contract_runtime_default"
            else:
                source = "formula_default_zero" if is_formula_like_column(col) else "type_default_or_null"
        try:
            arrays.append(coerce_series_to_arrow(s.reset_index(drop=True), field))
        except Exception as exc:
            raise RuntimeError(f"failed to coerce column {col} ({field.type}) for {role}: {repr(exc)}") from exc
        if source != "computed_or_mapped":
            fill_rows.append({"role": role, "column": col, "source": source, "arrow_type": str(field.type)})
    table = pa.Table.from_arrays(arrays, schema=schema)
    info = {
        "role": role,
        "new_rows": n,
        "schema_columns": len(schema.names),
        "computed_or_mapped_columns": len([c for c in schema.names if c in generated_cols]),
        "default_filled_columns_count": len(fill_rows),
        "default_filled_columns": fill_rows,
    }
    return table, info


def write_appended_parquet(current_path: Path, new_table: pa.Table, output_path: Path, log: Logger) -> Dict[str, Any]:
    ensure_dir(output_path.parent)
    pf = pq.ParquetFile(current_path)
    schema = pf.schema_arrow
    if new_table.schema.names != schema.names:
        raise RuntimeError("new table schema names do not match current schema")
    _current_min, current_max, _current_nulls, _strategy = scan_trade_date_min_max_with_strategy(current_path)
    new_date_values = new_table.column("trade_date").to_pandas().map(normalize_trade_date_value)
    new_min = int(new_date_values.min()) if new_date_values.notna().any() else None
    append_only_fast = current_max is not None and new_min is not None and new_min > int(current_max)
    new_keys: set[tuple[str, int]] = set()
    seen_keys: set[tuple[str, int]] = set()
    if not append_only_fast:
        new_keys_df = new_table.select(["ts_code", "trade_date"]).to_pandas()
        new_keys_df["trade_date"] = new_keys_df["trade_date"].map(normalize_trade_date_value)
        new_keys = set(zip(new_keys_df["ts_code"].astype(str), new_keys_df["trade_date"].astype(int)))
    tmp = output_path.with_suffix(".tmp.parquet")
    if tmp.exists():
        tmp.unlink()
    writer = pq.ParquetWriter(tmp, schema=schema, compression="snappy")
    current_rows = 0
    current_rows_written = 0
    current_duplicate_or_replaced_rows_dropped = 0
    for idx, batch in enumerate(pf.iter_batches(batch_size=65536)):
        if append_only_fast:
            out_table = pa.Table.from_batches([batch], schema=schema)
        else:
            df = batch.to_pandas()
            trade_dates = df["trade_date"].map(normalize_trade_date_value).astype(int)
            keys = list(zip(df["ts_code"].astype(str), trade_dates))
            keep = []
            for key in keys:
                if key in new_keys or key in seen_keys:
                    keep.append(False)
                    current_duplicate_or_replaced_rows_dropped += 1
                else:
                    seen_keys.add(key)
                    keep.append(True)
            if all(keep):
                out_table = pa.Table.from_batches([batch], schema=schema)
            else:
                out_table = pa.Table.from_pandas(df.loc[keep], schema=schema, preserve_index=False)
        if out_table.num_rows:
            writer.write_table(out_table)
            current_rows_written += out_table.num_rows
        current_rows += batch.num_rows
        if idx % 50 == 0:
            log.log(f"copy current parquet batches role={output_path.name} batch={idx} rows={current_rows} written={current_rows_written} dropped={current_duplicate_or_replaced_rows_dropped}")
    writer.write_table(new_table)
    writer.close()
    os.replace(str(tmp), str(output_path))
    return {
        "output_path": str(output_path),
        "write_mode": "append_only_fast" if append_only_fast else "replace_or_dedupe",
        "current_rows_copied": current_rows,
        "current_rows_written": current_rows_written,
        "current_duplicate_or_replaced_rows_dropped": current_duplicate_or_replaced_rows_dropped,
        "new_rows_appended": new_table.num_rows,
        "total_rows_expected": current_rows_written + new_table.num_rows,
        "size_mb": round(output_path.stat().st_size / 1024 / 1024, 3),
    }


def validate_new_selector_rows(df: pd.DataFrame, current_schema: pa.Schema, latest_date: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    latest = df[df["trade_date"] == latest_date].copy()
    out["latest_date"] = latest_date
    out["latest_rows"] = int(len(latest))
    out["duplicate_key_rows"] = int(df.duplicated(["ts_code", "trade_date"]).sum()) if len(df) else 0
    out["ohlc_positive_bad"] = int(((df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0) | (df["close"] <= 0)).sum()) if len(df) else 0
    out["high_low_bad"] = int((df["high"] < df["low"]).sum()) if len(df) else 0
    close_outside = ((df["close"] > df["high"]) | (df["close"] < df["low"])) if len(df) else pd.Series(dtype=bool)
    ext_market = df["ts_code"].astype(str).str.match(r"^\d{5}\.(HK|HK_FUND|HK_CONNECT|HK_ETF|HK_OTHER)$") if len(df) else pd.Series(dtype=bool)
    out["close_outside_high_low_bad"] = int(close_outside.sum()) if len(df) else 0
    out["close_outside_high_low_bad_a_share"] = int((close_outside & ~ext_market).sum()) if len(df) else 0
    out["close_outside_high_low_bad_ext_market"] = int((close_outside & ext_market).sum()) if len(df) else 0
    out["vol_negative_count"] = int((df["vol"] < 0).sum()) if "vol" in df else 0
    out["amount_negative_count"] = int((df["amount"] < 0).sum()) if "amount" in df else 0
    schema_cols = set(current_schema.names)
    out["future_forbidden_generated_columns"] = [c for c in df.columns if any(tok.lower() in c.lower() for tok in FORBIDDEN_FUTURE_PATTERNS)]
    critical_rows = []
    hard = []
    hard.extend(_v192_contract_issues(df))
    for col in CRITICAL_SELECTOR_FORMULA_COLUMNS:
        if col not in schema_cols:
            # Some columns are intentionally generated for audit/debug but are not part of the
            # authoritative selector schema (they will be dropped at runtime by contract policy).
            # These must not block the daily increment update.
            critical_rows.append({"column": col, "in_schema": False, "in_generated": col in df.columns, "latest_non_null": None, "latest_null_count": None, "value_counts_sample": ""})
            if col not in CONTRACT_RUNTIME_DROP_COLUMNS:
                hard.append(f"critical_formula_column_not_in_schema:{col}")
            continue
        if col not in df.columns:
            critical_rows.append({"column": col, "in_schema": True, "in_generated": False, "latest_non_null": 0, "latest_null_count": int(len(latest)), "value_counts_sample": ""})
            hard.append(f"critical_formula_column_not_generated:{col}")
            continue
        s = latest[col]
        nulls = int(s.isna().sum())
        vc = s.fillna("__NULL__").value_counts(dropna=False).head(8).to_dict()
        critical_rows.append({"column": col, "in_schema": True, "in_generated": True, "latest_non_null": int(len(s) - nulls), "latest_null_count": nulls, "value_counts_sample": json.dumps(vc, ensure_ascii=False)})
        if nulls > 0:
            if col == "bar_close_pos":
                flat_nulls = int((latest[col].isna() & latest["high"].eq(latest["low"])).sum())
                non_flat_nulls = nulls - flat_nulls
                if non_flat_nulls > 0:
                    hard.append(f"critical_formula_column_has_null:{col}:{nulls};non_flat_nulls:{non_flat_nulls}")
            else:
                hard.append(f"critical_formula_column_has_null:{col}:{nulls}")
    out["critical_formula_column_audit"] = critical_rows
    out["critical_formula_hard_issues"] = hard
    out["status"] = "PASS" if not hard and out["latest_rows"] > 0 and out["duplicate_key_rows"] == 0 and out["ohlc_positive_bad"] == 0 and out["high_low_bad"] == 0 and out["close_outside_high_low_bad_a_share"] == 0 and not out["future_forbidden_generated_columns"] else "FAIL"
    return out


def quick_audit_promoted(path: Path, role: str) -> Dict[str, Any]:
    return parquet_basic_audit(path, role, include_date_scan=True)


def zip_run_dir(run_dir: Path, zip_path: Path) -> None:
    ensure_dir(zip_path.parent)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in run_dir.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(run_dir.parent))


def stage_status_payload(stage: str, status: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "stage": stage,
        "status": status,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    payload.update(extra)
    return payload


def write_stage_status(run_dir: Path, stage: str, status: str, **extra: Any) -> Dict[str, Any]:
    payload = stage_status_payload(stage, status, **extra)
    write_json(run_dir / f"stage_{stage}.json", payload)
    return payload


def build_candidate_artifacts(
    selector_current: Path,
    backtest_current: Path,
    selector_target_schema: pa.Schema,
    backtest_schema: pa.Schema,
    selector_new_table: pa.Table,
    backtest_new_table: pa.Table,
    tdx_max: int,
    run_ts: str,
    log: Logger,
) -> Dict[str, Any]:
    selector_out_dir = PROMOTED_SELECTOR_ROOT / f"selector_ready_current_to_{tdx_max}_{run_ts}"
    backtest_out_dir = PROMOTED_BACKTEST_ROOT / f"tdx_backtest_base_panel_5y_v3_current_to_{tdx_max}_{run_ts}" / "panel"
    selector_out = selector_out_dir / f"selector_ready_current_to_{tdx_max}.parquet"
    backtest_out = backtest_out_dir / f"tdx_backtest_base_panel_5y_v3_current_to_{tdx_max}.parquet"

    log.log("candidate parquet write mode=parallel selector+backtest workers=2")
    with ThreadPoolExecutor(max_workers=2) as executor:
        selector_future = executor.submit(
            write_appended_parquet,
            selector_current,
            selector_new_table,
            selector_out,
            log,
        )
        backtest_future = executor.submit(
            write_appended_parquet,
            backtest_current,
            backtest_new_table,
            backtest_out,
            log,
        )
        selector_write = selector_future.result()
        backtest_write = backtest_future.result()
    selector_after_candidate_audit = quick_audit_promoted(selector_out, "selector_candidate_after_write")
    backtest_after_candidate_audit = quick_audit_promoted(backtest_out, "backtest_candidate_after_write")
    return {
        "selector_out": selector_out,
        "backtest_out": backtest_out,
        "selector_write": selector_write,
        "backtest_write": backtest_write,
        "selector_after_candidate_audit": selector_after_candidate_audit,
        "backtest_after_candidate_audit": backtest_after_candidate_audit,
        "selector_target_schema_columns": len(selector_target_schema.names),
        "backtest_schema_columns": len(backtest_schema.names),
    }


def validate_candidate_stage(
    tdx_max: int,
    selector_target_schema: pa.Schema,
    backtest_schema: pa.Schema,
    candidate_outputs: Dict[str, Any],
    contract_policy: Dict[str, Any],
    selector_increment_df: pd.DataFrame,
) -> Dict[str, Any]:
    hard_issues: List[str] = []
    soft_issues: List[str] = []
    failure_classes: List[str] = []
    selector_after_candidate_audit = candidate_outputs["selector_after_candidate_audit"]
    backtest_after_candidate_audit = candidate_outputs["backtest_after_candidate_audit"]
    selector_candidate_schema = pq.ParquetFile(candidate_outputs["selector_out"]).schema_arrow
    selector_candidate_contract_gate = contract_schema_gate(selector_candidate_schema, contract_policy, "selector_candidate_table")
    selector_candidate_dataframe_gate = contract_dataframe_gate(
        selector_increment_df,
        contract_policy,
        "selector_candidate_increment_dataframe",
    )
    selector_candidate_null_policy = validate_selector_null_policy(selector_increment_df)

    # Append-only update: candidate schema matches the target (current) schema exactly.
    # Contract compliance requires a rebuild/migration; it must not block same-schema appends.
    append_only_schema = list(selector_candidate_schema.names) == list(selector_target_schema.names)

    if selector_after_candidate_audit.get("trade_date_max") != int(tdx_max):
        hard_issues.append("selector_candidate_max_date_not_tdx_max")
        failure_classes.append("candidate_validation_failure")
    if backtest_after_candidate_audit.get("trade_date_max") != int(tdx_max):
        hard_issues.append("backtest_candidate_max_date_not_tdx_max")
        failure_classes.append("candidate_validation_failure")
    if selector_after_candidate_audit.get("columns") != len(selector_target_schema.names):
        hard_issues.append("selector_candidate_column_count_mismatch")
        failure_classes.append("schema_mismatch")
    if backtest_after_candidate_audit.get("columns") != len(backtest_schema.names):
        hard_issues.append("backtest_candidate_column_count_mismatch")
        failure_classes.append("schema_mismatch")
    if selector_candidate_contract_gate.get("status") != "PASS":
        if append_only_schema:
            soft_issues.append("selector_candidate_contract_gate_failed_append_only")
        else:
            hard_issues.append("selector_candidate_contract_gate_failed")
            failure_classes.append("contract_violation")
    if selector_candidate_dataframe_gate.get("status") != "PASS":
        if append_only_schema:
            soft_issues.append("selector_candidate_dataframe_gate_failed_append_only")
        else:
            hard_issues.append("selector_candidate_dataframe_gate_failed")
            failure_classes.append("contract_violation")
    if selector_candidate_null_policy.get("status") != "PASS":
        hard_issues.append("selector_candidate_null_policy_failed")
        failure_classes.append("contract_violation")
    if selector_after_candidate_audit.get("future_forbidden_columns"):
        hard_issues.append("selector_candidate_future_forbidden_columns")
        failure_classes.append("schema_mismatch")
    if backtest_after_candidate_audit.get("future_forbidden_columns"):
        hard_issues.append("backtest_candidate_future_forbidden_columns")
        failure_classes.append("schema_mismatch")

    return {
        "status": "PASS" if not hard_issues else "FAIL",
        "hard_issues": hard_issues,
        "soft_issues": soft_issues,
        "failure_classes": sorted(set(failure_classes)),
        "selector_candidate_contract_gate": selector_candidate_contract_gate,
        "selector_candidate_dataframe_gate": selector_candidate_dataframe_gate,
        "selector_candidate_null_policy": selector_candidate_null_policy,
        "selector_candidate_audit": selector_after_candidate_audit,
        "backtest_candidate_audit": backtest_after_candidate_audit,
    }


def promote_candidate_outputs(
    selector_out: Path,
    backtest_out: Path,
    run_dir: Path,
) -> Dict[str, Any]:
    backup_dir = run_dir / "pointer_backups_before_promote"
    ensure_dir(backup_dir)
    shutil.copy2(SELECTOR_POINTER, backup_dir / f"CURRENT_SELECTOR_READY_PANEL_before_promote_{RUN_TS}.txt")
    shutil.copy2(BACKTEST_POINTER, backup_dir / f"CURRENT_BACKTEST_BASE_PANEL_before_promote_{RUN_TS}.txt")
    with _same_day_pointer_lock([SELECTOR_POINTER, BACKTEST_POINTER]):
        write_pointer_atomic(SELECTOR_POINTER, selector_out)
        write_pointer_atomic(BACKTEST_POINTER, backtest_out)
    pointer_after = {"selector": read_pointer(SELECTOR_POINTER), "backtest": read_pointer(BACKTEST_POINTER)}
    return {
        "backup_dir": str(backup_dir),
        "pointer_after": pointer_after,
    }


def _same_day_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _same_day_file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_day_ref(ref: Dict[str, Any]) -> Path:
    path = Path(ref["path"])
    if not path.is_absolute() or not path.is_file() or _same_day_file_sha(path) != ref["sha256"]:
        raise RuntimeError(f"same-day bound file missing or changed: {path}")
    return path


def _same_day_bound_list(bound: Dict[str, Any], *, keys: bool = False) -> list:
    items = bound["items"]
    if not isinstance(items, list):
        raise RuntimeError("same-day scope must be an explicit list")
    if keys:
        valid = all(isinstance(x, list) and len(x) == 2 and isinstance(x[0], str)
                    and type(x[1]) is int and x[1] > 0 for x in items)
        normalized = [tuple(x) for x in items] if valid else []
    else:
        valid = all(isinstance(x, str) and x for x in items)
        normalized = items
    if not valid or len(set(normalized)) != len(items) or items != sorted(items):
        raise RuntimeError("same-day scope must be sorted, typed and unique")
    if bound["count"] != len(items) or bound["sha256"] != _same_day_digest(items):
        raise RuntimeError("same-day scope count/SHA mismatch")
    return normalized


def _same_day_key_index(frame: pd.DataFrame) -> pd.MultiIndex:
    dates = frame["trade_date"].map(normalize_trade_date_value)
    if dates.isna().any():
        raise RuntimeError("same-day invalid trade_date")
    index = pd.MultiIndex.from_arrays([frame["ts_code"].astype(str), dates.astype(int)])
    if index.has_duplicates:
        raise RuntimeError("same-day duplicate keys")
    return index


def _same_day_atomic_json(path: Path, value: Dict[str, Any]) -> None:
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


@contextmanager
def _same_day_pointer_lock(pointers: list[Path]):
    # Same-day revision is Mac/POSIX only. Keep the ordinary Windows path usable.
    if os.name == "nt":
        yield
        return
    import fcntl
    handles = []
    try:
        for pointer in sorted(set(pointers), key=str):
            handle = pointer.with_name("." + pointer.name + ".revision.lock").open("a+b")
            handles.append(handle)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        for handle in reversed(handles):
            handle.close()


def _same_day_scope(contract: Dict[str, Any]) -> Dict[str, Any]:
    if contract["schema"] != "V192_SAME_DAY_PANEL_REVISION_V1" or not contract["revision_id"]:
        raise RuntimeError("same-day revision contract identity missing")
    if contract["research_only"] is not True or any(contract[k] is not False for k in (
        "production_allowed", "buy_gate_updated", "orders_sent",
    )):
        raise RuntimeError("same-day research boundary violated")
    signal = contract["signal_date"]
    if type(signal) is not int or type(contract["target_date"]) is not int or contract["target_date"] <= signal:
        raise RuntimeError("same-day signal/target boundary invalid")
    universe = contract["universe"]
    target = set(_same_day_bound_list(universe["target_symbols"]))
    accepted = set(_same_day_bound_list(universe["accepted_symbols"]))
    excluded = set(_same_day_bound_list(universe["excluded_symbols"]))
    boundary = set(_same_day_bound_list(universe["boundary_excluded_symbols"]))
    if not target or not accepted or accepted & excluded or accepted | excluded != target or not boundary <= accepted:
        raise RuntimeError("same-day target/accepted/exclusion partition mismatch")
    if not universe["original_target_fingerprint"] or universe["coverage_status"] != "ACCEPTED_ONLY_EXCLUDED_PRESERVED":
        raise RuntimeError("same-day full-target coverage must not be claimed")
    consumer = contract["consumer_history"]
    if not consumer["consumer_sha256"] or consumer["signal_end_date"] != signal:
        raise RuntimeError("same-day consumer history binding missing")
    rkeys = set(_same_day_bound_list(consumer["keys"], keys=True))
    if not rkeys or any(code not in accepted or date < consumer["signal_start_date"] or date > signal for code, date in rkeys):
        raise RuntimeError("same-day consumer history outside accepted/date boundary")
    if consumer["recurrence_start_date"] > consumer["signal_start_date"]:
        raise RuntimeError("same-day recurrence starts after consumer history")
    ukeys = {(code, signal) for code in accepted - boundary}
    projection = set(_same_day_bound_list(contract["projection_keys"], keys=True))
    raw = set(_same_day_bound_list(contract["raw_repair_keys"], keys=True))
    if projection != ukeys | rkeys or not raw <= projection:
        raise RuntimeError("same-day projection must cover exact U union R; raw keys must be within it")
    if any(code in boundary and date == signal for code, date in projection):
        raise RuntimeError("same-day boundary-excluded signal keys cannot be revised")
    raw_fields = contract["raw_repair_fields"]
    allowed_raw = {"open", "high", "low", "close", "vol", "volume", "amount", "pre_close", "pct_chg"}
    if len(set(raw_fields)) != len(raw_fields) or not set(raw_fields) <= allowed_raw or bool(raw) != bool(raw_fields):
        raise RuntimeError("same-day raw repair fields invalid")
    derived_fields = contract["raw_repair_derived_fields"]
    # A raw correction must replace every producer-derived value consumed from
    # that row, including local rolling features as well as canonical fields.
    minimum_derived = set(V192_FORMULA_FIELDS) | set(V192_REQUIRED_CANONICAL_PROJECTION_FIELDS)
    if raw and (len(set(derived_fields)) != len(derived_fields) or not minimum_derived <= set(derived_fields)):
        raise RuntimeError("same-day raw/derived replacement closure incomplete")
    if set(derived_fields) & (allowed_raw | {"ts_code", "trade_date"}):
        raise RuntimeError("same-day derived field scope overlaps raw/keys")
    if set(derived_fields) & set(STATIC_MAP_CANDIDATES):
        raise RuntimeError("same-day derived field scope cannot modify static names/qualification")
    role_fields = {}
    for role in ("selector", "backtest"):
        item = contract["roles"][role]
        pfields = item["projection_fields"]
        rfields = item["raw_fields"]
        dfields = item["derived_fields"]
        for fields in (pfields, rfields, dfields):
            if not isinstance(fields, list) or len(set(fields)) != len(fields):
                raise RuntimeError("same-day role fields must be explicit unique lists")
        if (not set(pfields) <= set(V192_REQUIRED_CANONICAL_PROJECTION_FIELDS)
                or not set(rfields) <= set(raw_fields) or not set(dfields) <= set(derived_fields)):
            raise RuntimeError("same-day role fields exceed approved replacement scope")
        if role == "selector" and (set(pfields) != set(V192_REQUIRED_CANONICAL_PROJECTION_FIELDS)
                                   or set(rfields) != set(raw_fields) or set(dfields) != set(derived_fields)):
            raise RuntimeError("same-day selector repair closure incomplete")
        role_fields[role] = {"projection_fields": set(pfields), "raw_fields": set(rfields), "derived_fields": set(dfields)}
    return {"projection": projection, "raw": raw, "raw_fields": raw_fields,
            "derived_fields": derived_fields, "accepted": accepted, "ukeys": ukeys, "rkeys": rkeys,
            "role_fields": role_fields}


def _same_day_overlay_parquet(
    source: Path, output: Path, generated: pd.DataFrame, scope: Dict[str, Any], role: str,
) -> Dict[str, Any]:
    """Preserve source order, row count, schema and every unapproved cell."""
    parquet = pq.ParquetFile(source)
    schema = parquet.schema_arrow
    role_fields = scope["role_fields"][role]
    projection_fields = role_fields["projection_fields"]
    fields = projection_fields | role_fields["raw_fields"] | role_fields["derived_fields"]
    # Schema additions need a separately frozen full-history policy. Never
    # silently invent values for rows outside the approved repair keys.
    if not fields <= set(schema.names) or not fields <= set(generated.columns):
        raise RuntimeError(f"same-day {role} missing frozen replacement columns: {sorted(fields - (set(schema.names) & set(generated.columns)))}")
    generated = generated.copy()
    generated.index = _same_day_key_index(generated)
    if not scope["projection"] <= set(generated.index):
        raise RuntimeError("same-day generated history misses approved keys")
    patch = generated.loc[sorted(scope["projection"]), sorted(fields)]
    for field in fields:
        arrow_type = schema.field(field).type
        keys = sorted(scope["projection"] if field in projection_fields else scope["raw"])
        values = patch.loc[keys, field]
        if (pa.types.is_boolean(arrow_type) or pa.types.is_integer(arrow_type) or pa.types.is_floating(arrow_type)) and not np.isfinite(pd.to_numeric(values, errors="coerce").to_numpy(dtype=float, na_value=np.nan)).all():
            raise RuntimeError(f"same-day invalid replacement value: {field}")
        if field == "formula_source" and not values.eq(CANONICAL_FORMULA_SOURCE).all():
            raise RuntimeError("same-day canonical formula_source mismatch")
    seen = set()
    rows = 0
    changed_cells = 0
    temporary = output.with_suffix(".tmp.parquet")
    try:
        with pq.ParquetWriter(temporary, schema=schema, compression="snappy") as writer:
            for batch in parquet.iter_batches(batch_size=65536):
                table = pa.Table.from_batches([batch], schema=schema)
                key_frame = table.select(["ts_code", "trade_date"]).to_pandas()
                index = _same_day_key_index(key_frame)
                relevant = set(index) & scope["projection"]
                if seen & relevant:
                    raise RuntimeError("same-day duplicate approved source key across batches")
                seen.update(relevant)
                projection_positions = [i for i, key in enumerate(index) if key in scope["projection"]]
                raw_positions = [i for i, key in enumerate(index) if key in scope["raw"]]
                for field in fields:
                    positions = projection_positions if field in projection_fields else raw_positions
                    if not positions:
                        continue
                    target_type = schema.field(field).type
                    values = []
                    for position in positions:
                        value = generated.at[index[position], field]
                        value = value.item() if isinstance(value, np.generic) else value
                        if pa.types.is_boolean(target_type):
                            if value not in (0, 1, False, True):
                                raise RuntimeError(f"same-day non-binary boolean replacement: {field}")
                            value = bool(value)
                        elif pa.types.is_integer(target_type):
                            if isinstance(value, (int, bool)):
                                value = int(value)
                            elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
                                value = int(value)
                            else:
                                raise RuntimeError(f"same-day non-integral integer replacement: {field}")
                        values.append(value)
                    # Convert only approved replacements to the original field
                    # type. Unapproved Arrow values never pass through Python
                    # inference (which can coerce bools or round large int64s).
                    if pa.types.is_boolean(target_type):
                        # The admitted Arrow runtime produced an invalid bool
                        # buffer through replace_with_mask for nullable bools.
                        # This source is already bool/null: rebuild explicitly
                        # as bool, preserving every unapproved value verbatim.
                        boolean_values = table[field].to_pylist()
                        for position, value in zip(positions, values):
                            boolean_values[position] = value
                        replacement = pa.array(boolean_values, type=pa.bool_())
                    else:
                        typed_values = pa.array(values, type=target_type, safe=True)
                        mask = np.zeros(table.num_rows, dtype=bool)
                        mask[positions] = True
                        replacement = pc.replace_with_mask(table[field], pa.array(mask), typed_values)
                    table = table.set_column(schema.get_field_index(field), schema.field(field), replacement)
                    changed_cells += len(positions)
                writer.write_table(table)
                rows += table.num_rows
        if seen != scope["projection"]:
            raise RuntimeError(f"same-day {role} source misses approved keys")
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        directory = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"path": str(output), "sha256": _same_day_file_sha(output), "rows": rows,
            "replacement_cells": changed_cells, "replacement_key_count": len(seen),
            "write_mode": "EXACT_KEY_FIELD_OVERLAY_SOURCE_ORDER_PRESERVED"}


def run_same_day_revision_candidate(contract_path: Path, contract_sha256: str) -> Dict[str, Any]:
    """Explicit same-date path; never invokes ordinary append/main or pointers."""
    global CANONICAL_FORMULA_PATH, _CANONICAL_FORMULA_MODULE
    contract_path = _same_day_ref({"path": str(contract_path), "sha256": contract_sha256})
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("schema") == "V192_SAME_DAY_PANEL_REVISION_V2":
        return _same_day_v2_candidate(contract_path, contract_sha256, contract)
    scope = _same_day_scope(contract)
    binding_path = _same_day_ref(contract["input_binding_receipt"])
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    expected_binding = {key: contract[key] for key in (
        "revision_id", "signal_date", "target_date",
        "input_history", "xdxr_events", "canonical_source", "roles", "universe", "consumer_history",
        "projection_keys", "raw_repair_keys", "raw_repair_fields", "raw_repair_derived_fields", "approved_overlays",
    )}
    if (binding.get("decision") != "PASS_SAME_DAY_REVISION_INPUT_BINDING"
            or binding.get("binding_sha256") != _same_day_digest(expected_binding)
            or binding.get("raw_and_derived_same_input") is not True
            or binding.get("derived_closure_confirmed") is not True
            or binding.get("producer_sha256") != _same_day_file_sha(Path(__file__))):
        raise RuntimeError("same-day independent U/R/raw/derived input binding missing or changed")
    canonical = _same_day_ref(contract["canonical_source"])
    sources = {}
    pointer_states = {}
    for role in ("selector", "backtest"):
        item = contract["roles"][role]
        sources[role] = _same_day_ref(item["source"])
        pointer = _same_day_ref(item["pointer"])
        old = pointer.read_bytes()
        if old.decode("utf-8-sig").strip() != str(sources[role]):
            raise RuntimeError("same-day pointer/source mismatch")
        pointer_states[role] = {"path": str(pointer), "old_b64": base64.b64encode(old).decode("ascii"),
                                "old_sha256": hashlib.sha256(old).hexdigest()}
    if len({str(sources[r]) for r in sources}) != 2 or len({s["path"] for s in pointer_states.values()}) != 2:
        raise RuntimeError("same-day selector/backtest identities must be distinct")
    output_dir = Path(contract["candidate_dir"])
    if not output_dir.is_absolute() or output_dir.exists():
        raise RuntimeError("same-day candidate directory must be new and absolute")
    partitions = []
    approved_keys = set()
    for overlay in contract["approved_overlays"]:
        keys = set(_same_day_bound_list(overlay["keys"], keys=True))
        if not keys or not keys <= scope["projection"] or approved_keys & keys:
            raise RuntimeError("same-day approved overlays overlap or exceed U/R")
        # Existing independently accepted results retain their exact raw/event/
        # window/producer identity. They are reused rather than recomputed.
        for name in ("artifact", "source_binding", "review_receipt"):
            _same_day_ref(overlay[name])
        identity = overlay["origin"]
        if (not all(identity.get(name) for name in ("raw_sha256", "event_sha256", "window_sha256", "producer_sha256", "canonical_sha256"))
                or identity["canonical_sha256"] != contract["canonical_source"]["sha256"]
                or overlay["raw_and_derived_same_input"] is not True):
            raise RuntimeError("same-day approved raw/derived provenance incomplete")
        part = pd.read_parquet(overlay["artifact"]["path"])
        if set(_same_day_key_index(part)) != keys:
            raise RuntimeError("same-day approved overlay key mismatch")
        approved_keys.update(keys)
        partitions.append(part)
    compute_keys = scope["projection"] - approved_keys
    if compute_keys:
        history_path = _same_day_ref(contract["input_history"])
        xdxr_path = _same_day_ref(contract["xdxr_events"])
        raw_columns = {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"}
        history_columns = set(pq.read_schema(history_path).names)
        if not raw_columns <= history_columns or not history_columns <= raw_columns | {"volume"}:
            raise RuntimeError("same-day computation input must contain only authoritative raw OHLCV/amount keys")
        history = pd.read_parquet(history_path)
        history_index = _same_day_key_index(history)
        consumer = contract["consumer_history"]
        compute_symbols = {code for code, _date in compute_keys}
        if (not compute_keys <= set(history_index)
                or any(code not in compute_symbols or code not in scope["accepted"]
                       or date < consumer["recurrence_start_date"] or date > contract["signal_date"]
                       for code, date in history_index)):
            raise RuntimeError("same-day computation history misses scope or violates recurrence/date/universe bounds")
        events = pd.read_parquet(xdxr_path)
        # Only the remaining U/R partition is computed by this original
        # producer, using one input generation for raw and derived values.
        original_canonical = CANONICAL_FORMULA_PATH
        original_module = _CANONICAL_FORMULA_MODULE
        try:
            # This explicit, independently bound Mac path is actually consumed
            # by the original canonical loader. Never fall back to Windows.
            CANONICAL_FORMULA_PATH = canonical
            _CANONICAL_FORMULA_MODULE = None
            fresh = compute_formula_features(history, 0, {}, _NoopLogger(), emit_all_rows=True, xdxr_events=events)
        finally:
            CANONICAL_FORMULA_PATH = original_canonical
            _CANONICAL_FORMULA_MODULE = original_module
        fresh.index = _same_day_key_index(fresh)
        if set(fresh.index) != set(history_index):
            raise RuntimeError("same-day producer changed input keys")
        partitions.append(fresh.loc[sorted(compute_keys)].reset_index(drop=True))
    elif contract["input_history"] is not None or contract["xdxr_events"] is not None:
        raise RuntimeError("same-day fully approved scope must not request unnecessary recomputation")
    generated = pd.concat(partitions, ignore_index=True)
    if set(_same_day_key_index(generated)) != scope["projection"]:
        raise RuntimeError("same-day approved/computed partitions do not cover exact U union R")
    output_dir.mkdir(parents=True, exist_ok=False)
    artifacts = {}
    for role in ("selector", "backtest"):
        artifacts[role] = _same_day_overlay_parquet(sources[role], output_dir / f"{role}.parquet", generated, scope, role)
        new = artifacts[role]["path"].encode("utf-8")
        pointer_states[role].update(new_b64=base64.b64encode(new).decode("ascii"), new_sha256=hashlib.sha256(new).hexdigest())
    # Detect any upstream drift during the potentially long candidate write.
    for role in ("selector", "backtest"):
        _same_day_ref(contract["roles"][role]["source"])
        _same_day_ref(contract["roles"][role]["pointer"])
    for dependency in (contract["input_binding_receipt"], contract["canonical_source"],
                       {"path": str(contract_path), "sha256": contract_sha256}):
        _same_day_ref(dependency)
    for overlay in contract["approved_overlays"]:
        for name in ("artifact", "source_binding", "review_receipt"):
            _same_day_ref(overlay[name])
    if compute_keys:
        _same_day_ref(contract["input_history"])
        _same_day_ref(contract["xdxr_events"])
    receipt = {"schema": "V192_SAME_DAY_PANEL_CANDIDATE_V1", "status": "CANDIDATE_ONLY_REQUIRES_INDEPENDENT_REVIEW",
               "revision_id": contract["revision_id"], "signal_date": contract["signal_date"], "target_date": contract["target_date"],
               "contract": {"path": str(contract_path), "sha256": contract_sha256}, "input_binding_receipt": contract["input_binding_receipt"],
               "producer_sha256": _same_day_file_sha(Path(__file__)), "artifacts": artifacts, "pointers": pointer_states,
               "coverage_status": "ACCEPTED_ONLY_EXCLUDED_PRESERVED", "projection_key_count": len(scope["projection"]),
               "u_key_count": len(scope["ukeys"]), "r_key_count": len(scope["rkeys"]), "raw_key_count": len(scope["raw"]),
               "approved_overlay_key_count": len(approved_keys), "computed_key_count": len(compute_keys),
               "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    _same_day_atomic_json(output_dir / "candidate_receipt.json", receipt)
    return receipt


def promote_same_day_revision(candidate_ref: Dict[str, Any], review_ref: Dict[str, Any], owner_ref: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded two-pointer CAS with durable phases; resume only old/new prefix states."""
    if os.name == "nt":
        raise RuntimeError("same-day revision promotion is Mac/POSIX only")
    candidate_path = _same_day_ref(candidate_ref)
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    review = json.loads(_same_day_ref(review_ref).read_text(encoding="utf-8"))
    owner = json.loads(_same_day_ref(owner_ref).read_text(encoding="utf-8"))
    valid_until = datetime.fromisoformat(owner["valid_until"])
    if (owner.get("decision") != "EXCLUSIVE_ORIGINAL_PRODUCER_PUBLISHER_CONFIRMED"
            or owner.get("candidate_receipt_sha256") != candidate_ref["sha256"]
            or owner.get("legacy_publishers_excluded") is not True or not owner.get("publisher_owner")
            or valid_until.tzinfo is None or valid_until <= datetime.now().astimezone()):
        raise RuntimeError("same-day exclusive publisher owner binding missing or expired")
    if (candidate["schema"] != "V192_SAME_DAY_PANEL_CANDIDATE_V1"
            or candidate["status"] != "CANDIDATE_ONLY_REQUIRES_INDEPENDENT_REVIEW"
            or review.get("decision") != "PASS_SAME_DAY_PANEL_REVISION"
            or review.get("candidate_receipt_sha256") != candidate_ref["sha256"]
            or review.get("producer_sha256") != candidate["producer_sha256"]
            or not review.get("reviewer_identity") or not review.get("writer_identity")
            or review["reviewer_identity"] == review["writer_identity"]
            or candidate["producer_sha256"] != _same_day_file_sha(Path(__file__))):
        raise RuntimeError("same-day independent candidate review missing or changed")
    contract = json.loads(_same_day_ref(candidate["contract"]).read_text(encoding="utf-8"))
    if contract.get("schema") == "V192_SAME_DAY_PANEL_REVISION_V2":
        scope = _same_day_v2_scope(contract)
        deleting_roles = {role: {"key_transform_sha256": contract["roles"][role]["approved_key_transform"]["sha256"],
                                 "new_key_sha256": candidate["artifacts"][role]["new_key_sha256"],
                                 "rows": candidate["artifacts"][role]["rows"],
                                 "deleted_rows": candidate["artifacts"][role]["deleted_rows"]}
                          for role, item in scope["roles"].items() if item["deletes"]}
        if deleting_roles and (review.get("approved_delete_transform_verified") is not True
                               or review.get("approved_key_transforms") != deleting_roles):
            raise RuntimeError("same-day independent review did not verify exact deletion/retained-order/new-key transformation")
    else:
        _same_day_scope(contract)
    states = candidate["pointers"]
    for role in ("selector", "backtest"):
        _same_day_ref(candidate["artifacts"][role])
        state = states[role]
        if state["path"] != contract["roles"][role]["pointer"]["path"]:
            raise RuntimeError("same-day pointer path differs from frozen contract")
        old = base64.b64decode(state["old_b64"], validate=True)
        new = base64.b64decode(state["new_b64"], validate=True)
        if (hashlib.sha256(old).hexdigest() != state["old_sha256"]
                or state["old_sha256"] != contract["roles"][role]["pointer"]["sha256"]
                or hashlib.sha256(new).hexdigest() != state["new_sha256"]
                or new != candidate["artifacts"][role]["path"].encode("utf-8") or old == new):
            raise RuntimeError("same-day old/new pointer identity mismatch")
    journal_path = candidate_path.parent / "promote_receipt.json"
    with _same_day_pointer_lock([Path(states[r]["path"]) for r in ("selector", "backtest")]):
        for role in ("selector", "backtest"):
            _same_day_ref(contract["roles"][role]["source"])
        if journal_path.exists():
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if journal["candidate"] != candidate_ref or journal["review"] != review_ref or journal["pointers"] != states:
                raise RuntimeError("same-day existing operation belongs to another revision/review")
        else:
            journal = {"schema": "V192_SAME_DAY_PANEL_PROMOTE_V1", "candidate": candidate_ref, "review": review_ref,
                       "revision_id": candidate["revision_id"], "pointers": states, "phases": [], "owner_bindings": []}
        current = [Path(states[r]["path"]).read_bytes() for r in ("selector", "backtest")]
        old = [base64.b64decode(states[r]["old_b64"]) for r in ("selector", "backtest")]
        new = [base64.b64decode(states[r]["new_b64"]) for r in ("selector", "backtest")]
        if any(value not in (old[i], new[i]) for i, value in enumerate(current)) or current == [old[0], new[1]]:
            raise RuntimeError("same-day third-version or non-prefix pointer state: STOP")
        if not journal_path.exists() and current != old:
            raise RuntimeError("same-day changed pointers without operation receipt: STOP")
        if journal.get("status") == "PROMOTED" and current != new:
            raise RuntimeError("same-day completed operation changed afterwards: STOP")
        if journal.get("status") == "PROMOTED":
            return journal
        journal["owner_bindings"].append(owner_ref)
        journal["phases"].append("PREPARED_OR_RESUMED")
        _same_day_atomic_json(journal_path, journal)
        for i, role in enumerate(("selector", "backtest")):
            if valid_until <= datetime.now().astimezone():
                raise RuntimeError("same-day exclusive publisher owner expired: STOP")
            # Recheck BOTH pointers immediately before each conditional write.
            observed = [Path(states[r]["path"]).read_bytes() for r in ("selector", "backtest")]
            if observed != current:
                raise RuntimeError("same-day pointer CAS lost: STOP")
            if current[i] == old[i]:
                pointer = Path(states[role]["path"])
                temporary = pointer.with_name(pointer.name + ".same_day.tmp")
                if temporary.exists():
                    if temporary.read_bytes() != new[i]:
                        raise RuntimeError("same-day foreign temporary pointer: STOP")
                else:
                    with temporary.open("xb") as stream:
                        stream.write(new[i])
                        stream.flush()
                        os.fsync(stream.fileno())
                os.replace(temporary, pointer)
                current[i] = new[i]
                directory = os.open(pointer.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            journal["phases"].append(role.upper() + "_NEW")
            _same_day_atomic_json(journal_path, journal)
        if [Path(states[r]["path"]).read_bytes() for r in ("selector", "backtest")] != new:
            raise RuntimeError("same-day pointer readback mismatch: STOP")
        journal["status"] = "PROMOTED"
        journal["phases"].append("PROMOTED")
        _same_day_atomic_json(journal_path, journal)
        return journal


def _same_day_v2_declared_columns(ref: Dict[str, Any], symbol: str) -> list[str]:
    """Read a frozen literal field declaration without importing its module."""
    tree = ast.parse(_same_day_ref(ref).read_text(encoding="utf-8"))
    values = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == symbol for target in node.targets):
            values.append(ast.literal_eval(node.value))
    if len(values) != 1 or not isinstance(values[0], (list, tuple)):
        raise RuntimeError(f"same-day V2 missing unique literal consumer declaration: {symbol}")
    fields = list(values[0])
    if not all(isinstance(field, str) and field for field in fields) or len(set(fields)) != len(fields):
        raise RuntimeError("same-day V2 invalid consumer declaration")
    return fields


def _same_day_v2_verify_refs(value: Any, seen: Optional[set] = None) -> None:
    seen = set() if seen is None else seen
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            identity = (value["path"], value["sha256"])
            if identity not in seen:
                _same_day_ref(value)
                seen.add(identity)
        for item in value.values():
            _same_day_v2_verify_refs(item, seen)
    elif isinstance(value, list):
        for item in value:
            _same_day_v2_verify_refs(item, seen)


def _same_day_v2_scope(contract: Dict[str, Any]) -> Dict[str, Any]:
    if (contract["schema"] != "V192_SAME_DAY_PANEL_REVISION_V2" or not contract["revision_id"]
            or contract["research_only"] is not True
            or any(contract[key] is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise RuntimeError("same-day V2 identity/safety boundary invalid")
    signal = contract["signal_date"]
    if type(signal) is not int or type(contract["target_date"]) is not int or contract["target_date"] <= signal:
        raise RuntimeError("same-day V2 signal/target boundary invalid")
    revision_observation_date = contract.get("runtime_binding", {}).get("revision_observation_date", signal)
    if type(revision_observation_date) is not int or revision_observation_date < signal:
        raise RuntimeError("same-day V2 current-revision observation cutoff invalid")
    ledger = contract["admission_ledger"]
    if set(ledger["original_receipts"]) != {"target", "accepted", "boundary"}:
        raise RuntimeError("same-day V2 original admission evidence incomplete")
    for ref in ledger["original_receipts"].values():
        _same_day_ref(ref)
    original = {key: set(_same_day_bound_list(ledger[key])) for key in ("target", "accepted", "excluded", "boundary")}
    if (not original["target"] or original["accepted"] & original["excluded"]
            or original["accepted"] | original["excluded"] != original["target"]
            or not original["boundary"] <= original["accepted"] or not ledger["original_target_fingerprint"]):
        raise RuntimeError("same-day V2 original admission partition invalid")
    admissions, releases = set(), set()
    for change in ledger["approved_changes"]:
        code = change["ts_code"]
        if code in admissions | releases or not change["original_reason"] or not change["current_reason"]:
            raise RuntimeError("same-day V2 duplicate or unexplained admission change")
        _same_day_ref(change["input_review"])
        _same_day_ref(change["derived_review"])
        if change["from"] == "EXCLUDED" and code in original["excluded"]:
            admissions.add(code)
        elif change["from"] == "BOUNDARY_EXCLUDED" and code in original["boundary"]:
            releases.add(code)
        else:
            raise RuntimeError("same-day V2 admission change does not match original ledger")
        if change["to"] != "ACCEPTED_CURRENT_REVISION":
            raise RuntimeError("same-day V2 unsupported admission change")
    accepted = original["accepted"] | admissions
    excluded = original["excluded"] - admissions
    boundary = original["boundary"] - releases
    effective = contract["effective_universe"]
    for name, expected in (("accepted", accepted), ("excluded", excluded), ("boundary", boundary)):
        if set(_same_day_bound_list(effective[name])) != expected:
            raise RuntimeError("same-day V2 effective admission ledger mismatch")
    if effective["coverage_status"] != "APPROVED_CURRENT_REVISION_EXCLUSIONS_RETAINED":
        raise RuntimeError("same-day V2 excluded coverage must remain explicit")
    consumer = contract["consumer_history"]
    rkeys = set(_same_day_bound_list(consumer["keys"], keys=True))
    if (not rkeys or not consumer["consumer_sha256"] or consumer["signal_end_date"] != signal
            or consumer["recurrence_start_date"] > consumer["signal_start_date"]
            or any(code not in accepted or not consumer["signal_start_date"] <= day <= signal for code, day in rkeys)):
        raise RuntimeError("same-day V2 actual consumer history boundary invalid")
    ukeys = {(code, signal) for code in accepted - boundary}
    keys = set(_same_day_bound_list(contract["projection_keys"], keys=True))
    if keys != ukeys | rkeys or any(code in boundary and day == signal for code, day in keys):
        raise RuntimeError("same-day V2 requires complete new U union actual R")
    declarations = contract["consumer_sources"]
    for name, symbols in (("score", {"score_v19", "score_multi_head"}),
                          ("role", {"entry_pool", "base_fmla04_role"}),
                          ("runtime_consumer", {"run_frozen_v192_oracle"})):
        tree = ast.parse(_same_day_ref(declarations[name]).read_text(encoding="utf-8"))
        definitions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if not symbols <= definitions:
            raise RuntimeError(f"same-day V2 bound {name} implementation identity incomplete")
    if consumer["consumer_sha256"] != declarations["runtime_consumer"]["sha256"]:
        raise RuntimeError("same-day V2 actual consumer SHA differs from its bound source")
    feature = _same_day_v2_declared_columns(declarations["feature"], "REQUIRED_BASE_COLUMNS")
    selector = _same_day_v2_declared_columns(declarations["selector"], "_PREMARKET_SOURCE_FIELDS")
    columns = set(feature) | set(selector)
    if set(_same_day_bound_list(contract["consumer_columns"])) != columns:
        raise RuntimeError("same-day V2 consumer closure differs from frozen source declarations")
    projected = columns | set(V192_REQUIRED_CANONICAL_PROJECTION_FIELDS)
    if set(contract["projection_lineage"]) != projected:
        raise RuntimeError("same-day V2 per-field complete consumer/projection provenance missing")
    native_fields = {"open", "high", "low", "close", "volume", "amount"}
    for field, rule in contract["projection_lineage"].items():
        if field in ("ts_code", "trade_date"):
            expected = "key"
        elif field in native_fields:
            expected = "raw"
        elif field == "name":
            expected = "static"
        elif field == "field_contract_version":
            expected = "constant"
        elif field in ("is_st_snapshot", "is_one_word_limit_up_est"):
            expected = "enrichment"
        elif field in set(V192_FORMULA_FIELDS) | set(V192_REQUIRED_CANONICAL_PROJECTION_FIELDS):
            expected = "canonical"
        else:
            expected = "producer"
        if rule.get("kind") != expected or (expected not in ("key", "constant") and rule.get("field") != field):
            raise RuntimeError(f"same-day V2 changed the original consumer field producer: {field}")
        if field == "field_contract_version" and rule.get("value") != CONTRACT_PROVENANCE_FIELD_DEFAULTS[field]:
            raise RuntimeError("same-day V2 field contract version changed")
    if not {"ts_code", "trade_date", "name", "volume", "open", "high", "low", "close", "amount"} <= columns:
        raise RuntimeError("same-day V2 consumer raw/name/key closure incomplete")
    role_scopes = {}
    for role in ("selector", "backtest"):
        item = contract["roles"][role]
        updates = set(_same_day_bound_list(item["existing_update_keys"], keys=True))
        inserts = set(_same_day_bound_list(item["approved_insert_keys"], keys=True))
        deletes = set(_same_day_bound_list(item["approved_delete_keys"], keys=True)) if "approved_delete_keys" in item else set()
        raw_replacements = set(_same_day_bound_list(item["approved_raw_replace_keys"], keys=True))
        if updates & inserts or updates | inserts != keys or not raw_replacements <= updates or deletes & (updates | inserts):
            raise RuntimeError("same-day V2 per-role exact update/insert/raw key partition invalid")
        deletion_evidence = {}
        for evidence in item.get("approved_delete_evidence", []):
            key = tuple(evidence["key"])
            if (key in deletion_evidence or key not in deletes or key[0] not in accepted
                    or evidence.get("policy") != "APPROVED_NATIVE_ABSENT_SUSPENSION_CURRENT_REVISION"
                    or not isinstance(evidence.get("reason"), str) or not evidence["reason"].strip()):
                raise RuntimeError("same-day V2 deletion evidence is duplicate, out of scope or unexplained")
            _same_day_ref(evidence["review_receipt"])
            _same_day_ref(evidence["native_absence_binding"])
            deletion_evidence[key] = evidence
        if set(deletion_evidence) != deletes:
            raise RuntimeError("same-day V2 every approved deletion needs exact independent native-absence evidence")
        raw_map = {field: field for field in ("open", "high", "low", "close", "amount")}
        raw_map["volume" if role == "selector" else "vol"] = "volume"
        if item["raw_field_map"] != raw_map:
            raise RuntimeError("same-day V2 only the exact native volume/vol role mapping is allowed")
        if item["expected_new_rows"] != item["expected_old_rows"] + len(inserts) - len(deletes):
            raise RuntimeError("same-day V2 expected row count is not old plus approved inserts minus approved deletions")
        if not item["source_key_sha256"] or not item["schema_sha256"]:
            raise RuntimeError("same-day V2 source/schema/key identity missing")
        if deletes:
            transform = {"schema": "V192_EXACT_ORDERED_KEY_TRANSFORM_V1", "source_key_sha256": item["source_key_sha256"],
                         "delete_keys_sha256": item["approved_delete_keys"]["sha256"],
                         "insert_keys_sha256": item["approved_insert_keys"]["sha256"],
                         "order": "RETAIN_SOURCE_PHYSICAL_ORDER_THEN_SORTED_APPROVED_INSERTS"}
            if (item.get("expected_new_key_sha256") is not None
                    or item.get("approved_key_transform") != {**transform, "sha256": _same_day_digest(transform)}):
                raise RuntimeError("same-day V2 approved deletion requires an exact frozen key transform, not a guessed new digest")
        elif not item.get("expected_new_key_sha256") or item.get("approved_key_transform") is not None:
            raise RuntimeError("same-day V2 ordinary overlay requires its exact expected new key digest")
        role_scopes[role] = {"updates": updates, "inserts": inserts, "deletes": deletes, "raw_replacements": raw_replacements, "raw_map": raw_map}
    structural = {}
    for item in contract.get("structural_na", []):
        field = item["field"]
        admitted = set(_same_day_bound_list(item["keys"], keys=True))
        if (field in structural or field not in projected - native_fields - {"ts_code", "trade_date", "name", "formula_source", "field_contract_version"}
                or not admitted <= keys or (field != "bar_close_pos" and any(day == signal for _code, day in admitted)) or not item["reason"]):
            raise RuntimeError("same-day V2 invalid original structural-NA admission")
        _same_day_ref(item["review_receipt"])
        structural[field] = admitted
    return {"keys": keys, "ukeys": ukeys, "rkeys": rkeys, "accepted": accepted, "excluded": excluded,
            "columns": columns, "projected": projected, "roles": role_scopes, "structural_na": structural}


def _same_day_v2_frame(ref: Dict[str, Any]) -> pd.DataFrame:
    frame = pd.read_parquet(_same_day_ref(ref))
    frame.index = _same_day_key_index(frame)
    return frame


def _same_day_v2_native_volume(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    if "volume" not in frame and "vol" not in frame:
        raise RuntimeError("same-day V2 native volume missing")
    if "volume" not in frame:
        frame["volume"] = frame["vol"]
    if "vol" in frame:
        for left, right in zip(frame["vol"].tolist(), frame["volume"].tolist()):
            left = left.item() if isinstance(left, np.generic) else left
            right = right.item() if isinstance(right, np.generic) else right
            if pd.isna(left) or pd.isna(right) or left != right:
                raise RuntimeError("same-day V2 native vol/volume mismatch")
    if any(pd.isna(value) or isinstance(value, (bool, np.bool_)) or not math.isfinite(value) or value < 0 for value in frame["volume"]):
        raise RuntimeError("same-day V2 invalid native volume")
    return frame


def _same_day_v2_static(ref: Dict[str, Any], signal: int, revision_observation_date: Optional[int] = None) -> dict:
    data = json.loads(_same_day_ref(ref).read_text(encoding="utf-8"))
    revision_observation_date = signal if revision_observation_date is None else revision_observation_date
    result = {}
    for row in data["records"]:
        identity = (row["ts_code"], row["field"])
        if (identity in result or type(row["observed_date"]) is not int
                or row["status"] != "CURRENT_REVISION_NON_PIT" or not row["reason"]):
            raise RuntimeError("same-day V2 ambiguous/future/unexplained static observation")
        if row["observed_date"] > signal:
            if (row["field"] != "name" or row["observed_date"] > revision_observation_date
                    or not isinstance(row.get("observation_review_receipt"), dict)):
                raise RuntimeError("same-day V2 post-signal name observation needs frozen revision cutoff and independent receipt")
            _same_day_ref(row["observation_review_receipt"])
        _same_day_ref(row["source"])
        result[identity] = row["value"]
    return result


def _same_day_v2_index(keys: Iterable[tuple[str, int]]) -> pd.MultiIndex:
    values = list(keys)
    return pd.MultiIndex.from_tuples(values, names=["ts_code", "trade_date"]) if values else pd.MultiIndex.from_arrays([[], []], names=["ts_code", "trade_date"])


def _same_day_v2_values(field: str, rule: Dict[str, Any], packet: dict, index: pd.MultiIndex,
                        static: dict, consumers: set, *, nullable: bool = False, insertion: bool = False) -> pd.Series:
    kind = rule["kind"]
    if kind == "key":
        if field not in ("ts_code", "trade_date"):
            raise RuntimeError("same-day V2 key provenance used for non-key field")
        return pd.Series(index.get_level_values(0 if field == "ts_code" else 1), index=index)
    if kind in ("producer", "canonical", "raw", "enrichment", "backtest_producer"):
        if rule.get("field") != field or field not in packet[kind].columns:
            raise RuntimeError(f"same-day V2 missing exact admitted {kind} field: {field}")
        if not set(index) <= set(packet[kind].index):
            raise RuntimeError("same-day V2 generation misses exact approved keys")
        values = packet[kind].loc[index, field]
        if field == "bar_close_pos" and values.isna().any():
            missing = values.index[values.isna()]
            raw = packet["raw"].loc[missing]
            if not raw["high"].eq(raw["low"]).all():
                raise RuntimeError("same-day V2 bar_close_pos missingness violates original flat-bar null policy")
        if field == "formula_source" and not values.eq(CANONICAL_FORMULA_SOURCE).all():
            raise RuntimeError("same-day V2 original formula source identity changed")
        return values
    if kind == "static":
        if field in consumers - {"name"} or rule.get("field") != field:
            raise RuntimeError("same-day V2 derived consumer field cannot be static carry")
        values = []
        for code, _day in index:
            if (code, field) not in static:
                raise RuntimeError(f"same-day V2 missing separately bound static value: {code}/{field}")
            value = static[(code, field)]
            if field == "name" and (value is None or not str(value).strip()):
                raise RuntimeError("same-day V2 admitted name must be known")
            values.append(value)
        return pd.Series(values, index=index, dtype=object)
    if kind == "constant":
        if field in consumers - {"field_contract_version", "formula_source"} or not rule.get("reason"):
            raise RuntimeError("same-day V2 formula/raw consumer field cannot be an invented constant")
        _same_day_ref(rule["approval"])
        return pd.Series([rule["value"]] * len(index), index=index, dtype=object)
    if kind == "unknown_null":
        if not insertion or not nullable or field in consumers or not rule.get("reason"):
            raise RuntimeError("same-day V2 unknown value is not an approved nullable nonconsumer insert field")
        _same_day_ref(rule["approval"])
        return pd.Series([None] * len(index), index=index, dtype=object)
    raise RuntimeError(f"same-day V2 unsupported field provenance: {field}/{kind}")


def _same_day_v2_packets(contract: dict, scope: dict) -> list[dict]:
    """Reuse admitted generations; compute only the disjoint remaining partition."""
    global CANONICAL_FORMULA_PATH, _CANONICAL_FORMULA_MODULE, _compute_canonical_v192_formula
    packets, approved = [], set()
    static = _same_day_v2_static(contract["static_rows"], contract["signal_date"],
                                 contract.get("runtime_binding", {}).get("revision_observation_date"))
    for item in contract["approved_generations"]:
        keys = set(_same_day_bound_list(item["keys"], keys=True))
        if not keys or not keys <= scope["keys"] or approved & keys or item["same_input_generation"] is not True:
            raise RuntimeError("same-day V2 approved generations overlap or exceed exact scope")
        for name in ("source_binding", "review_receipt"):
            _same_day_ref(item[name])
        if not all(item["origin"].get(name) for name in ("raw_sha256", "event_sha256", "window_sha256", "producer_sha256", "canonical_sha256")):
            raise RuntimeError("same-day V2 approved generation provenance incomplete")
        if item["origin"]["canonical_sha256"] != contract["canonical_source"]["sha256"]:
            raise RuntimeError("same-day V2 approved canonical identity changed")
        packet = {name: _same_day_v2_frame(item[name]) for name in ("producer", "canonical", "raw", "enrichment")}
        packet["raw"] = _same_day_v2_native_volume(packet["raw"])
        if any(not keys <= set(packet[name].index) for name in ("producer", "canonical", "raw", "enrichment")):
            raise RuntimeError("same-day V2 approved generation missing keys")
        packet.update(keys=keys, approved=True, evidence={name: item[name] for name in (
            "producer", "canonical", "raw", "enrichment", "source_binding", "review_receipt")})
        packets.append(packet)
        approved.update(keys)
    remaining = scope["keys"] - approved
    if remaining:
        fresh = contract["remaining_generation"]
        if set(_same_day_bound_list(fresh["keys"], keys=True)) != remaining:
            raise RuntimeError("same-day V2 remaining generation must equal exact unapproved partition")
        history = _same_day_v2_frame(fresh["input_history"])
        raw_columns = {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"}
        if not raw_columns <= set(history.columns) or not set(history.columns) <= raw_columns | {"volume"}:
            raise RuntimeError("same-day V2 remaining history must contain only authoritative native raw columns")
        history = _same_day_v2_native_volume(history)
        symbols = {code for code, _day in remaining}
        if (not remaining <= set(history.index)
                or any(code not in symbols or code not in scope["accepted"]
                       or not contract["consumer_history"]["recurrence_start_date"] <= day <= contract["signal_date"]
                       for code, day in history.index)):
            raise RuntimeError("same-day V2 remaining raw recurrence/universe coverage invalid")
        events = pd.read_parquet(_same_day_ref(fresh["xdxr_events"]))
        authority = _same_day_ref(contract["canonical_source"])
        captured = []
        previous = (CANONICAL_FORMULA_PATH, _CANONICAL_FORMULA_MODULE, _compute_canonical_v192_formula)
        def same_call(frame):
            if captured:
                raise RuntimeError("same-day V2 unexpected second canonical invocation")
            value = previous[2](frame)
            captured.append(value.copy())
            return value
        latest_static = {"name": {code: static[(code, "name")] for code in symbols if (code, "name") in static}}
        if set(latest_static["name"]) != symbols:
            raise RuntimeError("same-day V2 remaining producer needs separately bound names")
        try:
            CANONICAL_FORMULA_PATH, _CANONICAL_FORMULA_MODULE = authority, None
            _compute_canonical_v192_formula = same_call
            producer = compute_formula_features(history.reset_index(drop=True), 0, latest_static, _NoopLogger(), emit_all_rows=True, xdxr_events=events)
        finally:
            CANONICAL_FORMULA_PATH, _CANONICAL_FORMULA_MODULE, _compute_canonical_v192_formula = previous
        if len(captured) != 1:
            raise RuntimeError("same-day V2 canonical generation was not captured exactly once")
        producer.index = _same_day_key_index(producer)
        canonical = captured[0]
        canonical.index = _same_day_key_index(canonical)
        if set(producer.index) != set(history.index) or set(canonical.index) != set(history.index):
            raise RuntimeError("same-day V2 original producer/canonical changed raw keys")
        functions = runpy.run_path(str(_same_day_ref(contract["enrichment_source"])), run_name="v192_same_day_bound_enrichment")
        _summary, enriched = functions["add_limit_fields"](producer.copy())
        enriched.index = _same_day_key_index(enriched)
        packets.append({"keys": remaining, "approved": False, "producer": producer, "canonical": canonical,
                        "raw": history, "enrichment": enriched, "evidence": {
                            "raw": fresh["input_history"], "xdxr_events": fresh["xdxr_events"],
                            "canonical_source": contract["canonical_source"], "enrichment_source": contract["enrichment_source"]}})
    elif contract["remaining_generation"] is not None:
        raise RuntimeError("same-day V2 must not recompute an entirely approved generation")
    for packet in packets:
        index = _same_day_v2_index(packet["keys"])
        raw = packet["raw"].loc[index]
        produced = packet["producer"].loc[index].copy()
        for channel in ("producer", "canonical", "enrichment"):
            for field in ("open", "high", "low", "close", "volume", "amount"):
                if field not in packet[channel] or packet[channel].loc[index, field].tolist() != raw[field].tolist():
                    raise RuntimeError(f"same-day V2 {channel}/native raw mismatch: {field}")
        needs_backtest_fields = any(rule.get("kind") == "backtest_producer"
                                   for role in contract["roles"].values()
                                   for rules in (role["update_lineage"], role["insert_lineage"])
                                   for rule in rules.values())
        if needs_backtest_fields:
            produced["vol"] = raw["volume"]
            packet["backtest_producer"] = append_backtest_provenance_and_tradeability(produced, Path(contract["roles"]["backtest"]["source"]["path"]))
        else:
            packet["backtest_producer"] = pd.DataFrame(index=index)
        packet["static"] = static
    return packets


def _same_day_v2_array(values: list, field: pa.Field, *, volume: bool = False, structural: Optional[list[bool]] = None) -> pa.Array:
    normalized = []
    for position, value in enumerate(values):
        value = value.item() if isinstance(value, np.generic) else value
        if field.name == "trade_date" and isinstance(value, int):
            if (pa.types.is_string(field.type) or pa.types.is_large_string(field.type)
                    or (pa.types.is_dictionary(field.type) and pa.types.is_string(field.type.value_type))):
                value = str(value)
            elif pa.types.is_date(field.type):
                value = datetime.strptime(str(value), "%Y%m%d").date()
            elif pa.types.is_timestamp(field.type):
                value = pd.Timestamp(datetime.strptime(str(value), "%Y%m%d"), tz=field.type.tz).to_pydatetime()
        if value is None:
            if not field.nullable:
                raise RuntimeError(f"same-day V2 null in nonnullable field: {field.name}")
        elif pa.types.is_boolean(field.type):
            if value not in (0, 1, False, True):
                raise RuntimeError(f"same-day V2 nonbinary field: {field.name}")
            value = bool(value)
        elif pa.types.is_integer(field.type):
            if isinstance(value, (int, bool)):
                value = int(value)
            elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
                value = int(value)
            else:
                raise RuntimeError(f"same-day V2 nonintegral field: {field.name}")
        elif pa.types.is_floating(field.type) and not math.isfinite(value):
            if not (math.isnan(value) and structural is not None and structural[position]):
                raise RuntimeError(f"same-day V2 nonfinite field requires prior explicit structural admission: {field.name}")
        normalized.append(value)
    result = pa.array(normalized, type=field.type, safe=True)
    if volume and any(original is None or original != converted for original, converted in zip(normalized, result.to_pylist())):
        raise RuntimeError("same-day V2 volume cannot be represented exactly in role schema")
    return result


def _same_day_v2_structural_mask(field: pa.Field, values: pd.Series, scope: dict) -> list[bool]:
    approved = scope["structural_na"].get(field.name, set())
    mask = [key in approved for key in values.index]
    missing = values.isna().tolist()
    if any(flag != is_missing for flag, is_missing in zip(mask, missing)) or (any(mask) and (not field.nullable or not pa.types.is_floating(field.type))):
        raise RuntimeError(f"same-day V2 consumer missingness differs from original structural admission: {field.name}")
    return mask


def _same_day_v2_key_digest_update(digest, keys: Iterable[tuple[str, int]]) -> None:
    for code, date in keys:
        digest.update((json.dumps([code, date], ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))


def _same_day_v2_role(contract: dict, scope: dict, packets: list[dict], role: str, output: Path) -> dict:
    item, approved = contract["roles"][role], scope["roles"][role]
    source = _same_day_ref(item["source"])
    parquet = pq.ParquetFile(source)
    schema = parquet.schema_arrow
    schema_identity = [{"name": field.name, "type": str(field.type), "nullable": field.nullable} for field in schema]
    if _same_day_digest(schema_identity) != item["schema_sha256"] or parquet.metadata.num_rows != item["expected_old_rows"]:
        raise RuntimeError("same-day V2 source schema/row identity changed")
    raw_map = approved["raw_map"]
    needed = (scope["projected"] - {"ts_code", "trade_date"}) & set(schema.names)
    needed.update(raw_map)
    needed.update(set(item["required_nonnull_fields"]) - {"ts_code", "trade_date"})
    if role == "selector" and not scope["projected"] <= set(schema.names):
        raise RuntimeError("same-day V2 selector schema misses consumer closure")
    if set(item["update_lineage"]) != needed:
        raise RuntimeError("same-day V2 per-role update field closure incomplete")
    for target, source_field in raw_map.items():
        if item["update_lineage"][target] != {"kind": "raw", "field": source_field}:
            raise RuntimeError("same-day V2 raw role field must use the exact native source")
    for field in needed - set(raw_map):
        rule = item["update_lineage"][field]
        if field in scope["projected"] and rule != contract["projection_lineage"][field]:
            raise RuntimeError("same-day V2 role changed a consumer field's authoritative source")
        if field not in scope["projected"] and (rule.get("kind") not in ("producer", "canonical", "backtest_producer") or rule.get("field") != field):
            raise RuntimeError("same-day V2 extra required role field must have an exact original producer source")
    consumers = scope["projected"] | set(item["required_nonnull_fields"])
    if not set(item["required_nonnull_fields"]) <= set(schema.names):
        raise RuntimeError("same-day V2 required role field absent from schema")
    if approved["inserts"] and set(item["insert_lineage"]) != set(schema.names):
        raise RuntimeError("same-day V2 insertion needs explicit lineage for every schema field")
    updates = {}
    insert_parts = []
    for packet in packets:
        update_index = _same_day_v2_index(packet["keys"] & approved["updates"])
        for target in needed:
            rule = item["update_lineage"][target]
            source_field = raw_map.get(target, target)
            values = _same_day_v2_values(source_field, rule, packet, update_index, packet["static"], consumers)
            updates.setdefault(target, []).append(values)
        insert_index = _same_day_v2_index(packet["keys"] & approved["inserts"])
        if len(insert_index):
            arrays = []
            for field in schema:
                rule = item["insert_lineage"][field.name]
                source_field = raw_map.get(field.name, field.name)
                expected_rule = item["update_lineage"].get(field.name)
                if field.name in ("ts_code", "trade_date"):
                    expected_rule = {"kind": "key"}
                if expected_rule is not None and rule != expected_rule:
                    raise RuntimeError("same-day V2 insert consumer/raw provenance differs from update generation")
                values = _same_day_v2_values(source_field, rule, packet, insert_index, packet["static"], consumers,
                                              nullable=field.nullable, insertion=True)
                structural = _same_day_v2_structural_mask(field, values, scope) if field.name in consumers else None
                arrays.append(_same_day_v2_array(values.tolist(), field, volume=source_field == "volume", structural=structural))
            insert_parts.append(pa.Table.from_arrays(arrays, schema=schema))
    updates = {field: pd.concat(parts) for field, parts in updates.items()}
    insert_table = pa.concat_tables(insert_parts) if insert_parts else pa.Table.from_batches([], schema=schema)
    if insert_table.num_rows:
        key_frame = insert_table.select(["ts_code", "trade_date"]).to_pandas()
        key_values = list(_same_day_key_index(key_frame))
        ordering = sorted(range(len(key_values)), key=lambda position: key_values[position])
        insert_table = insert_table.take(pa.array(ordering, type=pa.int64()))
    old_digest, retained_digest = hashlib.sha256(), hashlib.sha256()
    seen_updates, changed_raw, seen_deletes = set(), set(), set()
    temporary = output.with_suffix(".tmp.parquet")
    rows, source_rows = 0, 0
    try:
        with pq.ParquetWriter(temporary, schema=schema, compression="snappy") as writer:
            for batch in parquet.iter_batches(batch_size=65536):
                table = pa.Table.from_batches([batch], schema=schema)
                key_frame = table.select(["ts_code", "trade_date"]).to_pandas()
                dates = key_frame["trade_date"].map(normalize_trade_date_value)
                if dates.isna().any():
                    raise RuntimeError("same-day V2 invalid source key date")
                keys = list(zip(key_frame["ts_code"].astype(str), dates.astype(int)))
                _same_day_v2_key_digest_update(old_digest, keys)
                source_rows += len(keys)
                deleting = [key for key in keys if key in approved["deletes"]]
                if len(set(deleting)) != len(deleting) or set(deleting) & seen_deletes:
                    raise RuntimeError("same-day V2 approved deletion must match one unique existing source row")
                seen_deletes.update(deleting)
                if deleting:
                    retained_positions = [position for position, key in enumerate(keys) if key not in approved["deletes"]]
                    table = table.take(pa.array(retained_positions, type=pa.int64()))
                    keys = [keys[position] for position in retained_positions]
                _same_day_v2_key_digest_update(retained_digest, keys)
                relevant = [key for key in keys if key in approved["updates"]]
                if len(set(relevant)) != len(relevant) or set(relevant) & seen_updates or set(keys) & approved["inserts"]:
                    raise RuntimeError("same-day V2 duplicate update or approved insert already exists")
                seen_updates.update(relevant)
                positions = [i for i, key in enumerate(keys) if key in approved["updates"]]
                index = _same_day_v2_index([keys[i] for i in positions])
                for field in needed:
                    values = updates[field].reindex(index)
                    structural = _same_day_v2_structural_mask(schema.field(field), values, scope) if field in consumers else None
                    typed = _same_day_v2_array(values.tolist(), schema.field(field), volume=field in raw_map and raw_map[field] == "volume", structural=structural)
                    old_values = [table[field][position].as_py() for position in positions]
                    new_values = typed.to_pylist()
                    if field in raw_map:
                        differences = {keys[position] for position, left, right in zip(positions, old_values, new_values) if left != right}
                        if not differences <= approved["raw_replacements"]:
                            raise RuntimeError("same-day V2 unapproved native raw mismatch")
                        changed_raw.update(differences)
                        selected = [i for i, (left, right) in enumerate(zip(old_values, new_values)) if left != right]
                        field_positions = [positions[i] for i in selected]
                        typed = typed.take(pa.array(selected, type=pa.int64()))
                    else:
                        field_positions = positions
                    if not field_positions:
                        continue
                    if pa.types.is_boolean(schema.field(field).type) or pa.types.is_dictionary(schema.field(field).type):
                        preserved_values = table[field].to_pylist()
                        for position, value in zip(field_positions, typed.to_pylist()):
                            preserved_values[position] = value
                        replacement = pa.array(preserved_values, type=schema.field(field).type, safe=True)
                    else:
                        mask = np.zeros(table.num_rows, dtype=bool)
                        mask[field_positions] = True
                        replacement = pc.replace_with_mask(table[field], pa.array(mask), typed)
                    table = table.set_column(schema.get_field_index(field), schema.field(field), replacement)
                writer.write_table(table)
                rows += table.num_rows
            if (seen_updates != approved["updates"] or changed_raw != approved["raw_replacements"] or seen_deletes != approved["deletes"]
                    or old_digest.hexdigest() != item["source_key_sha256"]):
                raise RuntimeError("same-day V2 exact update/delete/raw/source-key binding mismatch")
            insert_keys_frame = insert_table.select(["ts_code", "trade_date"]).to_pandas()
            insert_keys = list(_same_day_key_index(insert_keys_frame)) if insert_table.num_rows else []
            if set(insert_keys) != approved["inserts"]:
                raise RuntimeError("same-day V2 strict insert table key mismatch")
            new_digest = retained_digest.copy()
            _same_day_v2_key_digest_update(new_digest, insert_keys)
            if ((not approved["deletes"] and new_digest.hexdigest() != item["expected_new_key_sha256"])
                    or rows + len(insert_keys) != item["expected_new_rows"]):
                raise RuntimeError("same-day V2 new ordered-key/row identity mismatch")
            if insert_table.num_rows:
                writer.write_table(insert_table)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, output)
        directory = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"path": str(output), "sha256": _same_day_file_sha(output), "old_rows": source_rows,
            "inserted_rows": insert_table.num_rows, "deleted_rows": len(seen_deletes), "rows": rows + insert_table.num_rows,
            "source_key_sha256": old_digest.hexdigest(), "new_key_sha256": new_digest.hexdigest(),
            "key_transform_sha256": item["approved_key_transform"]["sha256"] if seen_deletes else None,
            "updated_key_count": len(seen_updates), "raw_replaced_key_count": len(changed_raw),
            "write_mode": ("EXACT_CONSUMER_OVERLAY_AND_APPROVED_ABSENT_KEY_APPEND_AND_APPROVED_NATIVE_ABSENCE_DELETE"
                           if seen_deletes else "EXACT_CONSUMER_OVERLAY_AND_APPROVED_ABSENT_KEY_APPEND")}


def _same_day_v2_candidate(contract_path: Path, contract_sha256: str, contract: dict) -> dict:
    scope = _same_day_v2_scope(contract)
    binding = json.loads(_same_day_ref(contract["input_binding_receipt"]).read_text(encoding="utf-8"))
    identity = {key: value for key, value in contract.items() if key != "input_binding_receipt"}
    if (binding.get("decision") != "PASS_SAME_DAY_V2_COMPLETE_INPUT_BINDING"
            or binding.get("binding_sha256") != _same_day_digest(identity)
            or binding.get("producer_sha256") != _same_day_file_sha(Path(__file__))
            or any(binding.get(key) is not True for key in (
                "complete_consumer_closure", "exact_raw_derived_generation", "approved_generation_reviews",
                "effective_admissions", "strict_insert_lineage", "actual_consumer_history"))):
        raise RuntimeError("same-day V2 independent complete input/admission/insert binding missing")
    if any(item["deletes"] for item in scope["roles"].values()) and binding.get("approved_deletions") is not True:
        raise RuntimeError("same-day V2 independent input binder did not approve exact source-row deletions")
    _same_day_v2_verify_refs(identity)
    output_dir = Path(contract["candidate_dir"])
    if not output_dir.is_absolute() or output_dir.exists():
        raise RuntimeError("same-day V2 candidate directory must be new and absolute")
    pointers = {}
    for role in ("selector", "backtest"):
        item = contract["roles"][role]
        raw = _same_day_ref(item["pointer"]).read_bytes()
        if raw.decode("utf-8-sig").strip() != item["source"]["path"]:
            raise RuntimeError("same-day V2 old pointer/source mismatch")
        pointers[role] = {"path": item["pointer"]["path"], "old_b64": base64.b64encode(raw).decode("ascii"),
                          "old_sha256": hashlib.sha256(raw).hexdigest()}
    if len({item["path"] for item in pointers.values()}) != 2:
        raise RuntimeError("same-day V2 selector/backtest pointers must be distinct")
    packets = _same_day_v2_packets(contract, scope)
    output_dir.mkdir(parents=True, exist_ok=False)
    for number, packet in enumerate(packets):
        if packet["approved"]:
            continue
        for channel in ("producer", "canonical", "enrichment"):
            path = output_dir / f"generation_{number}_{channel}.parquet"
            packet[channel].reset_index(drop=True).to_parquet(path, index=False)
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            packet["evidence"][channel] = {"path": str(path), "sha256": _same_day_file_sha(path)}
    directory = os.open(output_dir, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    artifacts = {}
    for role in ("selector", "backtest"):
        artifacts[role] = _same_day_v2_role(contract, scope, packets, role, output_dir / f"{role}.parquet")
        new = artifacts[role]["path"].encode("utf-8")
        pointers[role].update(new_b64=base64.b64encode(new).decode("ascii"), new_sha256=hashlib.sha256(new).hexdigest())
    _same_day_v2_verify_refs(identity)
    _same_day_ref({"path": str(contract_path), "sha256": contract_sha256})
    _same_day_ref(contract["input_binding_receipt"])
    receipt = {"schema": "V192_SAME_DAY_PANEL_CANDIDATE_V1", "status": "CANDIDATE_ONLY_REQUIRES_INDEPENDENT_REVIEW",
               "revision_contract_schema": contract["schema"], "revision_id": contract["revision_id"],
               "signal_date": contract["signal_date"], "target_date": contract["target_date"],
               "revision_observation_date": contract.get("runtime_binding", {}).get("revision_observation_date", contract["signal_date"]),
               "name_observation_status": "CURRENT_REVISION_NON_PIT", "historical_name_pit_claimed": False,
               "contract": {"path": str(contract_path), "sha256": contract_sha256}, "producer_sha256": _same_day_file_sha(Path(__file__)),
               "input_binding_receipt": contract["input_binding_receipt"], "artifacts": artifacts, "pointers": pointers,
               "consumer_columns_sha256": _same_day_digest(sorted(scope["columns"])),
               "projection_key_count": len(scope["keys"]), "u_key_count": len(scope["ukeys"]), "r_key_count": len(scope["rkeys"]),
               "approved_generation_keys": sum(len(packet["keys"]) for packet in packets if packet["approved"]),
               "computed_generation_keys": sum(len(packet["keys"]) for packet in packets if not packet["approved"]),
               "generation_evidence": [{"approved_reused": packet["approved"], "key_count": len(packet["keys"]),
                                        "keys_sha256": _same_day_digest(sorted(packet["keys"])),
                                        "sources": packet["evidence"]} for packet in packets],
               "coverage_status": "APPROVED_CURRENT_REVISION_EXCLUSIONS_RETAINED",
               "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    _same_day_atomic_json(output_dir / "candidate_receipt.json", receipt)
    return receipt


def validate_promoted_outputs(
    pointer_after: Dict[str, Any],
    tdx_max: int,
    selector_target_schema: pa.Schema,
    backtest_schema: pa.Schema,
    contract_policy: Dict[str, Any],
    selector_increment_df: pd.DataFrame,
) -> Dict[str, Any]:
    promoted_audit = {
        "selector": quick_audit_promoted(Path(pointer_after["selector"]["target"]), "selector_current_after_promote"),
        "backtest": quick_audit_promoted(Path(pointer_after["backtest"]["target"]), "backtest_current_after_promote"),
    }
    selector_promoted_schema = pq.ParquetFile(Path(pointer_after["selector"]["target"])).schema_arrow
    selector_promoted_contract_gate = contract_schema_gate(selector_promoted_schema, contract_policy, "selector_promoted_table")
    selector_promoted_dataframe_gate = contract_dataframe_gate(
        selector_increment_df,
        contract_policy,
        "selector_promoted_increment_dataframe",
    )
    selector_promoted_null_policy = validate_selector_null_policy(selector_increment_df)
    hard_issues: List[str] = []
    soft_issues: List[str] = []
    failure_classes: List[str] = []
    append_only_schema = list(selector_promoted_schema.names) == list(selector_target_schema.names)
    if promoted_audit["selector"].get("trade_date_max") != int(tdx_max) or promoted_audit["selector"].get("columns") != len(selector_target_schema.names):
        hard_issues.append("selector_promoted_audit_failed")
        failure_classes.append("promote_failure")
    if promoted_audit["backtest"].get("trade_date_max") != int(tdx_max) or promoted_audit["backtest"].get("columns") != len(backtest_schema.names):
        hard_issues.append("backtest_promoted_audit_failed")
        failure_classes.append("promote_failure")
    if selector_promoted_contract_gate.get("status") != "PASS":
        if append_only_schema:
            soft_issues.append("selector_promoted_contract_gate_failed_append_only")
        else:
            hard_issues.append("selector_promoted_contract_gate_failed")
            failure_classes.append("contract_violation")
    if selector_promoted_dataframe_gate.get("status") != "PASS":
        if append_only_schema:
            soft_issues.append("selector_promoted_dataframe_gate_failed_append_only")
        else:
            hard_issues.append("selector_promoted_dataframe_gate_failed")
            failure_classes.append("contract_violation")
    if selector_promoted_null_policy.get("status") != "PASS":
        hard_issues.append("selector_promoted_null_policy_failed")
        failure_classes.append("contract_violation")
    return {
        "status": "PASS" if not hard_issues else "FAIL",
        "hard_issues": hard_issues,
        "soft_issues": soft_issues,
        "failure_classes": sorted(set(failure_classes)),
        "promoted_audit": promoted_audit,
        "selector_promoted_contract_gate": selector_promoted_contract_gate,
        "selector_promoted_dataframe_gate": selector_promoted_dataframe_gate,
        "selector_promoted_null_policy": selector_promoted_null_policy,
    }


def run_canonical_rebuild_stage() -> Dict[str, Any]:
    canonical_script = DATA_ROOT / "tools" / "debug_scripts" / "research_panel_formula_canonical_20260515" / "build_canonical_formula_research_panel.py"
    canonical_rebuild = {"run": False, "script": str(canonical_script)}
    if not canonical_script.exists():
        canonical_rebuild["status"] = "FAIL"
        canonical_rebuild["hard_issues"] = ["selector_canonical_rebuild_script_missing"]
        return canonical_rebuild
    completed = subprocess.run(
        [sys.executable, str(canonical_script)],
        cwd=str(DATA_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    canonical_rebuild.update({
        "run": True,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-8000:],
        "stderr_tail": completed.stderr[-8000:],
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "hard_issues": [] if completed.returncode == 0 else ["selector_canonical_rebuild_failed"],
    })
    return canonical_rebuild


def run_contract_enrichment_stage() -> Dict[str, Any]:
    enrichment_script = DATA_ROOT / "tools" / "debug_scripts" / "research_panel_contract_enrichment_20260525" / "enrich_research_panel_contract_and_missing_fields.py"
    enrichment = {"run": False, "script": str(enrichment_script)}
    if not enrichment_script.exists():
        enrichment["status"] = "FAIL"
        enrichment["hard_issues"] = ["selector_contract_enrichment_script_missing"]
        return enrichment
    completed = subprocess.run(
        [sys.executable, str(enrichment_script)],
        cwd=str(DATA_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
    )
    enrichment.update({
        "run": True,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-8000:],
        "stderr_tail": completed.stderr[-8000:],
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "hard_issues": [] if completed.returncode == 0 else ["selector_contract_enrichment_failed"],
    })
    return enrichment


def run_post_update_inspection_artifacts_stage() -> Dict[str, Any]:
    scripts = {
        "canonical_audit": DATA_ROOT / "tools" / "debug_scripts" / "research_panel_formula_canonical_20260515" / "audit_canonical_research_panel.py",
        "web_audit": DATA_ROOT / "tools" / "debug_scripts" / "research_panel_web_audit_20260515" / "build_research_panel_web_audit.py",
        "xdxr_independent_check": DATA_ROOT / "ops" / "automation" / "xdxr_independent_check_automation2.py",
    }
    result: Dict[str, Any] = {
        "run": False,
        "status": "PASS",
        "hard_issues": [],
        "scripts": {name: str(path) for name, path in scripts.items()},
        "steps": {},
    }
    for name, script in scripts.items():
        step: Dict[str, Any] = {"script": str(script), "run": False}
        if not script.exists():
            step.update({"status": "FAIL", "hard_issues": [f"{name}_script_missing"]})
            result["steps"][name] = step
            result["hard_issues"].extend(step["hard_issues"])
            result["status"] = "FAIL"
            continue
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(DATA_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
        )
        step.update({
            "run": True,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-8000:],
            "stderr_tail": completed.stderr[-8000:],
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "hard_issues": [] if completed.returncode == 0 else [f"{name}_failed"],
        })
        result["run"] = True
        result["steps"][name] = step
        if step["status"] != "PASS":
            result["hard_issues"].extend(step["hard_issues"])
            result["status"] = "FAIL"
    result["hard_issues"] = list(dict.fromkeys(result["hard_issues"]))
    return result


def main(run_full_maintenance_stages: bool = False) -> None:
    ensure_dir(RUN_DIR)
    log = Logger(RUN_DIR / "run_log.txt")
    started = time.time()
    flags = {
        "delete_operations": False,
        "move_operations": False,
        "parquet_modified": False,
        "candidate_parquet_written": False,
        "pointer_modified": False,
        "promote_run": False,
        "build_run": False,
        "selector_run": False,
        "walkforward_run": False,
        "backtest_run": False,
        "hot_panel_run": False,
        "fetch_restore_run": False,
        "release_chain_run": False,
        "selector_contract_enrichment_run": False,
        "canonical_audit_run": False,
        "web_audit_run": False,
        "xdxr_independent_check_run": False,
    }
    final_status = "FAIL_DATA_LAYER_DAILY_FORMULA_INCREMENT_UPDATE_V1"
    status = "FAIL"
    hard_issues: List[str] = []
    soft_issues: List[str] = []
    summary: Dict[str, Any] = {"task_name": TASK_NAME}

    protected_paths = [
        SELECTOR_POINTER,
        BACKTEST_POINTER,
        DATA_ROOT / "data_layer_interface_current" / "DATA_LAYER_INTERFACE.py",
        DATA_ROOT / "backtest_panel_interface_current" / "BACKTEST_PANEL_INTERFACE.py",
    ]
    before_snapshot = snapshot_paths(protected_paths)

    try:
        log.log("start daily formula increment update")
        rules_exists = RULES_FILE.exists()
        summary["rules_file_exists"] = rules_exists
        if not rules_exists:
            soft_issues.append("rules_file_missing")

        if not TDX_ROOT.exists():
            hard_issues.append("tdx_root_missing")
        if not DATA_ROOT.exists():
            hard_issues.append("data_root_missing")
        if not SELECTOR_POINTER.exists():
            hard_issues.append("selector_pointer_missing")
        if not BACKTEST_POINTER.exists():
            hard_issues.append("backtest_pointer_missing")
        if hard_issues:
            raise RuntimeError(";".join(hard_issues))

        selector_ptr = read_pointer(SELECTOR_POINTER)
        backtest_ptr = read_pointer(BACKTEST_POINTER)
        write_json(RUN_DIR / "pointer_audit_before.json", {"selector": selector_ptr, "backtest": backtest_ptr})
        selector_current = Path(selector_ptr["target"])
        backtest_current = Path(backtest_ptr["target"])
        if not selector_current.exists():
            hard_issues.append("selector_current_target_missing")
        if not backtest_current.exists():
            hard_issues.append("backtest_current_target_missing")
        if hard_issues:
            raise RuntimeError(";".join(hard_issues))

        selector_audit_before = parquet_basic_audit(selector_current, "selector_current_before")
        backtest_audit_before = parquet_basic_audit(backtest_current, "backtest_current_before")
        write_json(RUN_DIR / "current_parquet_audit_before.json", {"selector": selector_audit_before, "backtest": backtest_audit_before})
        selector_history_preflight = audit_formal_panel_history(selector_current, "selector")
        backtest_history_preflight = audit_formal_panel_history(backtest_current, "backtest")
        write_json(RUN_DIR / "current_formal_history_preflight.json", {"selector": selector_history_preflight, "backtest": backtest_history_preflight})
        if selector_history_preflight["status"] != "PASS" or backtest_history_preflight["status"] != "PASS":
            hard_issues.append("BLOCKED_CURRENT_FORMAL_HISTORY_CORRUPT")
            raise RuntimeError("BLOCKED_CURRENT_FORMAL_HISTORY_CORRUPT")

        selector_current_max = selector_audit_before.get("trade_date_max")
        backtest_current_max = backtest_audit_before.get("trade_date_max")
        if selector_current_max is None or backtest_current_max is None:
            hard_issues.append("current_max_date_missing")
            raise RuntimeError(";".join(hard_issues))
        base_after_date = min(int(selector_current_max), int(backtest_current_max))

        selector_latest_by_ts = latest_trade_dates_by_ts(selector_current)
        backtest_latest_by_ts = latest_trade_dates_by_ts(backtest_current)
        shared_generation_cutoffs = minimum_role_cutoffs(
            selector_latest_by_ts,
            backtest_latest_by_ts,
        )

        selector_schema = pq.ParquetFile(selector_current).schema_arrow
        backtest_schema = pq.ParquetFile(backtest_current).schema_arrow
        contract_policy = build_contract_policy_or_fail()
        # For daily append, the new parquet must keep the exact current schema (names + order).
        # Contract-driven column drops require a full rebuild, not an append.
        selector_target_schema = selector_schema
        hist, tdx_summary = collect_increment_history(
            TDX_ROOT,
            base_after_date,
            log,
            selector_latest_by_ts=selector_latest_by_ts,
            backtest_latest_by_ts=backtest_latest_by_ts,
        )
        write_json(RUN_DIR / "tdx_day_latest_summary.json", tdx_summary)
        if tdx_summary.get("cross_day_continuity", {}).get("status") != "PASS":
            hard_issues.append("tdx_cross_day_continuity_failed_rebuild_required")
            raise RuntimeError("tdx_cross_day_continuity_failed_rebuild_required")
        tdx_max = tdx_summary.get("tdx_max_trade_date")
        if tdx_max is None:
            hard_issues.append("tdx_max_trade_date_missing")
            raise RuntimeError(";".join(hard_issues))
        if hist.empty:
            final_status = "PASS_DATA_LAYER_DAILY_FORMULA_INCREMENT_UPDATE_V1_NO_NEW_DATE"
            status = "PASS"
            summary.update({
                "tdx_max_trade_date": tdx_max,
                "selector_current_max_date": selector_current_max,
                "backtest_current_max_date": backtest_current_max,
                "message": "no new TDX date or per-symbol coverage gap beyond current",
            })
            return

        # Read latest static metadata from selector current.
        active_ts_codes = sorted(str(x) for x in hist["ts_code"].dropna().unique()) if "ts_code" in hist.columns else []
        static_cols = [c for c in STATIC_MAP_CANDIDATES if c in selector_schema.names]
        latest_static = read_latest_static_map(
            selector_current,
            int(selector_current_max),
            static_cols,
            log,
            active_ts_codes=active_ts_codes,
        )
        known_names = latest_static.setdefault("name", {})
        missing_local_name_codes = [
            ts for ts in active_ts_codes
            if str(known_names.get(ts, "")).strip() in ("", "nan", "None", "<NA>")
            and (ts.endswith(".BJ") or is_ext_market_ts(ts))
        ]
        tdx_static_names = build_tdx_static_name_map(TDX_ROOT, missing_local_name_codes)
        if tdx_static_names:
            latest_static.setdefault("name", {}).update(tdx_static_names)
            latest_static.setdefault("stock_name", {}).update(tdx_static_names)
            log.log(
                f"loaded missing tdx static names for extended/BJ markets: "
                f"requested={len(missing_local_name_codes)} found={len(tdx_static_names)}"
            )
        known_names = latest_static.setdefault("name", {})
        missing_active_names = [
            ts for ts in active_ts_codes
            if is_a_bj_ts(ts) and str(known_names.get(ts, "")).strip() in ("", "nan", "None", "<NA>")
        ]
        pytdx_static_names = fetch_pytdx_static_names(missing_active_names, log)
        if pytdx_static_names:
            latest_static.setdefault("name", {}).update(pytdx_static_names)
            latest_static.setdefault("stock_name", {}).update(pytdx_static_names)
        history_min_date = int(pd.to_numeric(hist["trade_date"], errors="coerce").min())
        xdxr_events = load_tdx_xdxr_events(
            TDX_ROOT,
            log,
            min_trade_date=history_min_date,
            wanted_ts_codes=active_ts_codes,
        )
        # Only compute/return incremental rows beyond base_after_date.
        # Returning all rows forces a large DataFrame consolidation/reset_index that can OOM (see 20260529 run).
        feature_df = compute_formula_features_daily(
            hist,
            base_after_date,
            latest_static,
            log,
            xdxr_events=xdxr_events,
            emit_after_by_ts=shared_generation_cutoffs,
            worker_schema_context={
                "selector_schema_names": list(selector_target_schema.names),
                "backtest_schema_names": list(backtest_schema.names),
            },
        )
        formula_processing = dict(getattr(feature_df, "attrs", {}).get("daily_formula_metadata", {}))
        summary["formula_processing"] = formula_processing
        write_json(RUN_DIR / "formula_processing_receipt.json", formula_processing)
        del hist
        gc.collect()
        pre_close_chain_audit = audit_pre_close_chain(feature_df)
        write_json(RUN_DIR / "pre_close_chain_audit.json", pre_close_chain_audit)
        if pre_close_chain_audit["status"] != "PASS":
            hard_issues.append("generated_pre_close_chain_inconsistent")
            raise RuntimeError("generated_pre_close_chain_inconsistent")
        selector_inc_df = filter_increment_rows(
            feature_df,
            selector_latest_by_ts,
            "selector",
            log,
            default_cutoff=int(selector_current_max),
        )
        backtest_inc_df = filter_increment_rows(
            feature_df,
            backtest_latest_by_ts,
            "backtest",
            log,
            default_cutoff=int(backtest_current_max),
        )
        boundary_isolation = isolate_increment_boundary_bad_symbols(
            {
                "selector": current_last_close_frame(selector_current),
                "backtest": current_last_close_frame(backtest_current),
            },
            {
                "selector": selector_inc_df,
                "backtest": backtest_inc_df,
            },
            target_date=int(tdx_max),
        )
        selector_inc_df = boundary_isolation["increments"]["selector"]
        backtest_inc_df = boundary_isolation["increments"]["backtest"]
        selector_boundary_audit = boundary_isolation["after"]["selector"]
        backtest_boundary_audit = boundary_isolation["after"]["backtest"]
        boundary_receipt = dict(boundary_isolation)
        boundary_receipt.pop("increments", None)
        write_json(
            RUN_DIR / "increment_boundary_audit.json",
            {
                "selector": selector_boundary_audit,
                "backtest": backtest_boundary_audit,
                "boundary_isolation": boundary_receipt,
            },
        )
        boundary_ok = {"PASS", "PASS_WITH_XDXR_EXEMPTION"}
        if selector_boundary_audit["status"] not in boundary_ok or backtest_boundary_audit["status"] not in boundary_ok:
            hard_issues.append("BLOCKED_INCREMENT_BOUNDARY_DISCONTINUITY")
            raise RuntimeError("BLOCKED_INCREMENT_BOUNDARY_DISCONTINUITY")
        del feature_df
        gc.collect()
        if selector_inc_df.empty and backtest_inc_df.empty:
            if int(tdx_max) <= int(base_after_date):
                final_status = "PASS_DATA_LAYER_DAILY_FORMULA_INCREMENT_UPDATE_V1_NO_NEW_INCREMENT"
                status = "PASS"
                summary.update({
                    "tdx_max_trade_date": tdx_max,
                    "selector_current_max_date": selector_current_max,
                    "backtest_current_max_date": backtest_current_max,
                    "base_after_date": base_after_date,
                    "message": "TDX latest date is already covered; no selector/backtest rows need appending.",
                    "tdx_day_latest_summary": tdx_summary,
                })
                return
            hard_issues.append("increment_rows_empty_after_formula")
            raise RuntimeError(";".join(hard_issues))

        latest_inc_date = int(max(
            selector_inc_df["trade_date"].max() if not selector_inc_df.empty else 0,
            backtest_inc_df["trade_date"].max() if not backtest_inc_df.empty else 0,
        ))
        if latest_inc_date != int(tdx_max):
            hard_issues.append(f"increment_latest_date_not_equal_tdx_max:{latest_inc_date}!={tdx_max}")

        selector_contract_report: Dict[str, Any] = {}
        if not selector_inc_df.empty:
            selector_inc_df = append_contract_provenance(
                selector_inc_df,
                selector_current,
                CONTRACT_PROVENANCE_FIELD_DEFAULTS["field_contract_version"],
            )
            selector_contract_report = {
                "mode": "append_current_schema_no_prune",
                "note": "daily append keeps current schema; contract pruning deferred to rebuild",
            }
        if not backtest_inc_df.empty:
            backtest_inc_df = append_backtest_provenance_and_tradeability(backtest_inc_df, backtest_current)

        formula_gate = validate_new_selector_rows(selector_inc_df, selector_target_schema, latest_inc_date)
        write_json(RUN_DIR / "formula_coverage_gate.json", formula_gate)
        write_csv(RUN_DIR / "critical_formula_column_audit.csv", formula_gate.get("critical_formula_column_audit", []))
        if formula_gate.get("status") != "PASS":
            hard_issues.extend(formula_gate.get("critical_formula_hard_issues", []))
            hard_issues.append("formula_coverage_gate_failed")
            raise RuntimeError(";".join(hard_issues))

        selector_new_table, selector_fill_info = build_table_for_schema(selector_inc_df, selector_target_schema, "selector", policy=None)
        backtest_new_table, backtest_fill_info = build_table_for_schema(backtest_inc_df, backtest_schema, "backtest")
        write_json(RUN_DIR / "schema_alignment_fill_policy.json", {"selector": selector_fill_info, "backtest": backtest_fill_info})
        write_json(RUN_DIR / "selector_contract_prune_report.json", selector_contract_report)
        write_json(RUN_DIR / "selector_contract_policy_summary.json", {
            "contract_csv": contract_policy["contract_csv"],
            "contract_row_count": contract_policy["contract_row_count"],
            "official_current_column_count": len(contract_policy["official_current_columns"]),
            "review_column_count": len(contract_policy["review_columns"]),
            "forced_drop_column_count": len(contract_policy["forced_drop_columns"]),
            "forced_drop_columns": sorted(contract_policy["forced_drop_columns"]),
            "selector_target_schema_summary": contract_column_summary(selector_target_schema.names, contract_policy),
        })

        candidate_outputs = build_candidate_artifacts(
            selector_current=selector_current,
            backtest_current=backtest_current,
            selector_target_schema=selector_target_schema,
            backtest_schema=backtest_schema,
            selector_new_table=selector_new_table,
            backtest_new_table=backtest_new_table,
            tdx_max=int(tdx_max),
            run_ts=RUN_TS,
            log=log,
        )
        flags["candidate_parquet_written"] = True
        flags["parquet_modified"] = False
        flags["build_run"] = True
        write_json(RUN_DIR / "candidate_build_results.json", {
            "selector": candidate_outputs["selector_write"],
            "backtest": candidate_outputs["backtest_write"],
            "tdx_summary": tdx_summary,
            "formula_gate": formula_gate,
        })
        write_json(RUN_DIR / "candidate_parquet_quick_audit.json", {
            "selector": candidate_outputs["selector_after_candidate_audit"],
            "backtest": candidate_outputs["backtest_after_candidate_audit"],
        })

        candidate_stage = validate_candidate_stage(
            tdx_max=int(tdx_max),
            selector_target_schema=selector_target_schema,
            backtest_schema=backtest_schema,
            candidate_outputs=candidate_outputs,
            contract_policy=contract_policy,
            selector_increment_df=selector_inc_df,
        )
        write_json(RUN_DIR / "selector_candidate_contract_gate.json", candidate_stage["selector_candidate_contract_gate"])
        write_stage_status(
            RUN_DIR,
            "candidate_build",
            candidate_stage["status"],
            selector_output=str(candidate_outputs["selector_out"]),
            backtest_output=str(candidate_outputs["backtest_out"]),
            hard_issues=candidate_stage["hard_issues"],
            failure_classes=candidate_stage.get("failure_classes", []),
        )
        if candidate_stage["status"] != "PASS":
            hard_issues.extend(candidate_stage["hard_issues"])
            raise RuntimeError(";".join(hard_issues))

        promote_stage = promote_candidate_outputs(
            selector_out=candidate_outputs["selector_out"],
            backtest_out=candidate_outputs["backtest_out"],
            run_dir=RUN_DIR,
        )
        flags["pointer_modified"] = True
        flags["promote_run"] = True
        write_json(RUN_DIR / "pointer_audit_after.json", promote_stage["pointer_after"])
        write_json(RUN_DIR / "promote_manifest.json", {
            "selector_before": selector_ptr,
            "backtest_before": backtest_ptr,
            "selector_after": promote_stage["pointer_after"]["selector"],
            "backtest_after": promote_stage["pointer_after"]["backtest"],
            "selector_output": str(candidate_outputs["selector_out"]),
            "backtest_output": str(candidate_outputs["backtest_out"]),
            "promoted_at": datetime.now().isoformat(timespec="seconds"),
            "field_contract_version": CONTRACT_PROVENANCE_FIELD_DEFAULTS["field_contract_version"],
            "selector_contract_csv": contract_policy["contract_csv"],
            "selector_contract_prune_report": selector_contract_report,
            "stage_boundary": "promote_only_after_candidate_pass",
        })

        promoted_stage = validate_promoted_outputs(
            pointer_after=promote_stage["pointer_after"],
            tdx_max=int(tdx_max),
            selector_target_schema=selector_target_schema,
            backtest_schema=backtest_schema,
            contract_policy=contract_policy,
            selector_increment_df=selector_inc_df,
        )
        write_json(RUN_DIR / "promoted_parquet_quick_audit.json", promoted_stage["promoted_audit"])
        write_json(RUN_DIR / "selector_promoted_contract_gate.json", promoted_stage["selector_promoted_contract_gate"])
        write_json(RUN_DIR / "selector_promoted_dataframe_gate.json", promoted_stage["selector_promoted_dataframe_gate"])
        write_json(RUN_DIR / "selector_promoted_null_policy.json", promoted_stage["selector_promoted_null_policy"])
        write_stage_status(
            RUN_DIR,
            "promote_current",
            promoted_stage["status"],
            pointer_after=promote_stage["pointer_after"],
            hard_issues=promoted_stage["hard_issues"],
            failure_classes=promoted_stage.get("failure_classes", []),
        )
        if promoted_stage["status"] != "PASS":
            hard_issues.extend(promoted_stage["hard_issues"])
            raise RuntimeError(";".join(hard_issues))

        if should_run_full_maintenance(run_full_maintenance_stages):
            canonical_rebuild = run_canonical_rebuild_stage()
            write_json(RUN_DIR / "selector_canonical_rebuild_after_promote.json", canonical_rebuild)
            flags["selector_canonical_rebuild_run"] = canonical_rebuild.get("run", False)
            if canonical_rebuild.get("status") != "PASS":
                hard_issues.extend(canonical_rebuild.get("hard_issues", []))
                raise RuntimeError(";".join(hard_issues))

            contract_enrichment = run_contract_enrichment_stage()
            write_json(RUN_DIR / "selector_contract_enrichment_after_canonical.json", contract_enrichment)
            flags["selector_contract_enrichment_run"] = contract_enrichment.get("run", False)
            if contract_enrichment.get("status") != "PASS":
                hard_issues.extend(contract_enrichment.get("hard_issues", []))
                raise RuntimeError(";".join(hard_issues))

            selector_current_after_enrichment = Path(read_pointer(SELECTOR_POINTER)["target"])
            selector_final_audit = parquet_basic_audit(
                selector_current_after_enrichment,
                "selector_current_after_contract_enrichment",
            )
            post_update_inspection_artifacts = run_post_update_inspection_artifacts_stage()
            flags["canonical_audit_run"] = bool((post_update_inspection_artifacts.get("steps") or {}).get("canonical_audit", {}).get("run"))
            flags["web_audit_run"] = bool((post_update_inspection_artifacts.get("steps") or {}).get("web_audit", {}).get("run"))
            flags["xdxr_independent_check_run"] = bool((post_update_inspection_artifacts.get("steps") or {}).get("xdxr_independent_check", {}).get("run"))
            if post_update_inspection_artifacts.get("status") != "PASS":
                hard_issues.extend(post_update_inspection_artifacts.get("hard_issues", []))
                raise RuntimeError(";".join(hard_issues))
        else:
            canonical_rebuild = {"status": "SKIPPED_DAILY_INCREMENT", "run": False, "hard_issues": []}
            contract_enrichment = {"status": "SKIPPED_DAILY_INCREMENT", "run": False, "hard_issues": []}
            post_update_inspection_artifacts = {"status": "SKIPPED_DAILY_INCREMENT", "run": False, "hard_issues": []}
            selector_current_after_enrichment = Path(promote_stage["pointer_after"]["selector"]["target"])
            selector_final_audit = promoted_stage["promoted_audit"]["selector"]

        write_json(RUN_DIR / "selector_canonical_rebuild_after_promote.json", canonical_rebuild)
        write_json(RUN_DIR / "selector_contract_enrichment_after_canonical.json", contract_enrichment)
        write_json(RUN_DIR / "post_update_inspection_artifacts.json", post_update_inspection_artifacts)

        promoted_audit = promoted_stage["promoted_audit"]
        summary.update({
            "tdx_max_trade_date": int(tdx_max),
            "selector_before_max": int(selector_current_max),
            "backtest_before_max": int(backtest_current_max),
            "selector_after_max": selector_final_audit.get("trade_date_max"),
            "backtest_after_max": promoted_audit["backtest"].get("trade_date_max"),
            "selector_rows_after": selector_final_audit.get("row_count"),
            "backtest_rows_after": promoted_audit["backtest"].get("row_count"),
            "selector_columns_after": selector_final_audit.get("columns"),
            "backtest_columns_after": promoted_audit["backtest"].get("columns"),
            "selector_increment_rows": int(len(selector_inc_df)),
            "backtest_increment_rows": int(len(backtest_inc_df)),
            "formula_gate_status": formula_gate.get("status"),
            "candidate_stage_status": candidate_stage.get("status"),
            "promote_stage_status": promoted_stage.get("status"),
            "canonical_rebuild_stage_status": canonical_rebuild.get("status"),
            "contract_enrichment_stage_status": contract_enrichment.get("status"),
            "selector_final_path": str(selector_current_after_enrichment),
            "status": "PRE_POST_UPDATE_AUDIT",
            "run_dir": str(RUN_DIR),
        })
        write_json(RUN_DIR / "task_summary.json", summary)

        final_status = "PASS_DATA_LAYER_DAILY_FORMULA_INCREMENT_UPDATE_V1"
        status = "PASS"
        summary.update({
            "post_update_inspection_artifacts_stage_status": post_update_inspection_artifacts.get("status"),
        })

    except Exception as exc:
        if not hard_issues:
            hard_issues.append("exception")
        summary["exception"] = repr(exc)
        summary["traceback"] = traceback.format_exc()
        failure_class_map = {
            "data_root_missing": "data_source_failure",
            "tdx_root_missing": "data_source_failure",
            "tdx_max_trade_date_missing": "data_source_failure",
            "selector_current_target_missing": "data_source_failure",
            "backtest_current_target_missing": "data_source_failure",
            "selector_candidate_column_count_mismatch": "schema_mismatch",
            "backtest_candidate_column_count_mismatch": "schema_mismatch",
            "selector_candidate_future_forbidden_columns": "schema_mismatch",
            "backtest_candidate_future_forbidden_columns": "schema_mismatch",
            "selector_candidate_contract_gate_failed": "contract_violation",
            "selector_candidate_dataframe_gate_failed": "contract_violation",
            "selector_candidate_null_policy_failed": "contract_violation",
            "selector_promoted_contract_gate_failed": "contract_violation",
            "selector_promoted_dataframe_gate_failed": "contract_violation",
            "selector_promoted_null_policy_failed": "contract_violation",
            "selector_promoted_audit_failed": "promote_failure",
            "backtest_promoted_audit_failed": "promote_failure",
            "selector_canonical_rebuild_failed": "downstream_rebuild_failure",
            "selector_contract_enrichment_script_missing": "downstream_rebuild_failure",
            "selector_contract_enrichment_failed": "downstream_rebuild_failure",
            "canonical_audit_script_missing": "downstream_audit_failure",
            "canonical_audit_failed": "downstream_audit_failure",
            "web_audit_script_missing": "downstream_audit_failure",
            "web_audit_failed": "downstream_audit_failure",
            "xdxr_independent_check_script_missing": "downstream_audit_failure",
            "xdxr_independent_check_failed": "downstream_audit_failure",
        }
        summary["failure_classes"] = sorted({failure_class_map.get(issue, "unclassified_failure") for issue in hard_issues})
        write_json(RUN_DIR / "failure_details.json", summary)
        write_json(RUN_DIR / "failure_classification.json", {
            "failure_classes": summary["failure_classes"],
            "hard_issues": list(dict.fromkeys(hard_issues)),
            "exception": repr(exc),
        })
        (RUN_DIR / "failure_report.md").write_text(
            "# failure_report\n\n"
            f"task: {TASK_NAME}\n\n"
            f"error: {repr(exc)}\n\n"
            "hard_issues:\n" + "\n".join(f"- {x}" for x in hard_issues) + "\n\n"
            "traceback:\n\n```text\n" + traceback.format_exc() + "\n```\n",
            encoding="utf-8",
            newline="\n",
        )
        log.log(f"FAILED: {repr(exc)}")
    finally:
        after_snapshot = snapshot_paths(protected_paths)
        allowed = [SELECTOR_POINTER, BACKTEST_POINTER] if flags.get("pointer_modified") else []
        protected_check = compare_snapshots(before_snapshot, after_snapshot, allowed)
        protected_check["flags"] = flags
        write_json(RUN_DIR / "protected_snapshot_before.json", before_snapshot)
        write_json(RUN_DIR / "protected_snapshot_after.json", after_snapshot)
        write_json(RUN_DIR / "protected_modification_check.json", protected_check)

        if protected_check.get("protected_changed_count", 0) > 0 and status == "PASS":
            status = "FAIL"
            final_status = "FAIL_DATA_LAYER_DAILY_FORMULA_INCREMENT_UPDATE_V1"
            hard_issues.append("protected_current_asset_changed")

        failure_class_map_final = {
            "data_root_missing": "data_source_failure",
            "tdx_root_missing": "data_source_failure",
            "tdx_max_trade_date_missing": "data_source_failure",
            "selector_current_target_missing": "data_source_failure",
            "backtest_current_target_missing": "data_source_failure",
            "selector_candidate_column_count_mismatch": "schema_mismatch",
            "backtest_candidate_column_count_mismatch": "schema_mismatch",
            "selector_candidate_future_forbidden_columns": "schema_mismatch",
            "backtest_candidate_future_forbidden_columns": "schema_mismatch",
            "selector_candidate_contract_gate_failed": "contract_violation",
            "selector_candidate_dataframe_gate_failed": "contract_violation",
            "selector_candidate_null_policy_failed": "contract_violation",
            "selector_promoted_contract_gate_failed": "contract_violation",
            "selector_promoted_dataframe_gate_failed": "contract_violation",
            "selector_promoted_null_policy_failed": "contract_violation",
            "selector_promoted_audit_failed": "promote_failure",
            "backtest_promoted_audit_failed": "promote_failure",
            "selector_canonical_rebuild_failed": "downstream_rebuild_failure",
            "selector_contract_enrichment_script_missing": "downstream_rebuild_failure",
            "selector_contract_enrichment_failed": "downstream_rebuild_failure",
            "canonical_audit_script_missing": "downstream_audit_failure",
            "canonical_audit_failed": "downstream_audit_failure",
            "web_audit_script_missing": "downstream_audit_failure",
            "web_audit_failed": "downstream_audit_failure",
            "xdxr_independent_check_script_missing": "downstream_audit_failure",
            "xdxr_independent_check_failed": "downstream_audit_failure",
            "protected_current_asset_changed": "promote_failure",
        }

        elapsed = round(time.time() - started, 2)
        summary.update({
            "task_name": TASK_NAME,
            "final_status": final_status,
            "status": status,
            "hard_issues": list(dict.fromkeys(hard_issues)),
            "soft_issues": list(dict.fromkeys(soft_issues)),
            "failure_classes": sorted({failure_class_map_final.get(issue, "unclassified_failure") for issue in dict.fromkeys(hard_issues)}),
            "started_at": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "elapsed_sec": elapsed,
            "run_dir": str(RUN_DIR),
            "flags": flags,
            "protected_changed_count": protected_check.get("protected_changed_count"),
        })
        write_json(RUN_DIR / "task_summary.json", summary)
        write_json(RUN_DIR / "meta.json", summary)

        report = [
            f"# {TASK_NAME}",
            "",
            f"final_status: {final_status}",
            f"status: {status}",
            "",
            "## hard_issues",
            *[f"- {x}" for x in summary.get("hard_issues", [])],
            "",
            "## 关键说明",
            "- 本脚本默认只计算并追加新交易日；完整历史重建仅由显式维护参数触发。",
            "- 只有 BG/B1/B2/B3/route_context、brick_context、brick_resonance_context、ref_hold_score 等分层字段通过最新日审计，才允许切 current pointer。",
            "- 不执行 release_chain，不执行 selector/backtest/hot_panel，不覆盖旧 parquet。",
            "- 新 current 以新 parquet 文件形式写入专用目录，再原子更新 pointer。",
        ]
        (RUN_DIR / "REPORT.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
        log.log(f"finish {final_status}")
        log.close()

        # Generated files manifest.
        manifest = []
        for p in RUN_DIR.rglob("*"):
            if p.is_file():
                manifest.append({
                    "path": str(p),
                    "relative": str(p.relative_to(RUN_DIR)),
                    "size_mb": round(p.stat().st_size / 1024 / 1024, 6),
                    "sha256": sha256_file(p, max_mb=20),
                })
        write_csv(RUN_DIR / "generated_files_manifest.csv", manifest)

        zip_path = RETURN_ROOT / f"{TASK_NAME}_result.zip"
        zip_run_dir(RUN_DIR, zip_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily incremental A-share formula panel update.")
    parser.add_argument(
        "--run-full-maintenance-stages",
        action="store_true",
        help="Explicitly run historical canonical rebuild, enrichment and full audits after promotion.",
    )
    parser.add_argument("--isolated-history-rebuild", action="store_true", help="Write a review-only OHLC/pre_close/pct_chg repair candidate; never promote it.")
    parser.add_argument("--isolated-start-date", type=int, default=0)
    parser.add_argument("--isolated-end-date", type=int, default=0)
    parser.add_argument("--isolated-output-dir", type=Path, default=None)
    parser.add_argument("--isolated-lookback-records", type=int, default=300)
    parser.add_argument("--v192-selector-canary", action="store_true", help="Recompute one selector date into an explicit isolated parquet; never promote.")
    parser.add_argument("--v192-selector-input", type=Path, default=None)
    parser.add_argument("--v192-selector-signal-date", type=int, default=0)
    parser.add_argument("--v192-selector-output", type=Path, default=None)
    revision_mode = parser.add_mutually_exclusive_group()
    revision_mode.add_argument("--same-day-revision", action="store_true", help="Build only a frozen same-day revision candidate using the original producer.")
    revision_mode.add_argument("--same-day-promote", action="store_true", help="Promote an independently reviewed candidate with an exclusive publisher owner receipt.")
    parser.add_argument("--candidate-only", action="store_true")
    parser.add_argument("--same-day-contract", type=Path)
    parser.add_argument("--same-day-contract-sha256")
    parser.add_argument("--same-day-candidate-receipt", type=Path)
    parser.add_argument("--same-day-candidate-sha256")
    parser.add_argument("--same-day-review-receipt", type=Path)
    parser.add_argument("--same-day-review-sha256")
    parser.add_argument("--same-day-owner-receipt", type=Path)
    parser.add_argument("--same-day-owner-sha256")
    args = parser.parse_args()
    if args.same_day_revision or args.same_day_promote:
        if args.isolated_history_rebuild or args.v192_selector_canary or args.run_full_maintenance_stages:
            parser.error("same-day modes cannot be combined with ordinary/isolated maintenance modes")
        if args.same_day_revision:
            if not args.candidate_only or args.same_day_contract is None or not args.same_day_contract_sha256:
                parser.error("--same-day-revision requires --candidate-only and frozen --same-day-contract/--same-day-contract-sha256")
            if any((args.same_day_candidate_receipt, args.same_day_candidate_sha256, args.same_day_review_receipt,
                    args.same_day_review_sha256, args.same_day_owner_receipt, args.same_day_owner_sha256)):
                parser.error("candidate-only cannot receive promotion arguments")
        elif (args.candidate_only or args.same_day_contract is not None or args.same_day_contract_sha256
              or not all((args.same_day_candidate_receipt, args.same_day_candidate_sha256,
                          args.same_day_review_receipt, args.same_day_review_sha256,
                          args.same_day_owner_receipt, args.same_day_owner_sha256))):
            parser.error("--same-day-promote requires exact candidate/review/owner receipt paths and SHA, without candidate flags")
    elif any((args.candidate_only, args.same_day_contract, args.same_day_contract_sha256,
              args.same_day_candidate_receipt, args.same_day_candidate_sha256, args.same_day_review_receipt,
              args.same_day_review_sha256, args.same_day_owner_receipt, args.same_day_owner_sha256)):
        parser.error("same-day arguments require an explicit same-day mode")
    return args


if __name__ == "__main__":
    args = parse_args()
    if args.same_day_revision:
        print(json.dumps(run_same_day_revision_candidate(args.same_day_contract, args.same_day_contract_sha256), ensure_ascii=False, indent=2))
    elif args.same_day_promote:
        print(json.dumps(promote_same_day_revision(
            {"path": str(args.same_day_candidate_receipt), "sha256": args.same_day_candidate_sha256},
            {"path": str(args.same_day_review_receipt), "sha256": args.same_day_review_sha256},
            {"path": str(args.same_day_owner_receipt), "sha256": args.same_day_owner_sha256},
        ), ensure_ascii=False, indent=2))
    elif args.isolated_history_rebuild:
        if not args.isolated_start_date or not args.isolated_end_date or args.isolated_output_dir is None:
            raise SystemExit("--isolated-history-rebuild requires --isolated-start-date, --isolated-end-date, and --isolated-output-dir")
        print(json.dumps(run_isolated_history_rebuild(TDX_ROOT, args.isolated_start_date, args.isolated_end_date, args.isolated_output_dir, args.isolated_lookback_records), ensure_ascii=False, indent=2))
    elif args.v192_selector_canary:
        if args.v192_selector_input is None or not args.v192_selector_signal_date or args.v192_selector_output is None:
            raise SystemExit("--v192-selector-canary requires --v192-selector-input, --v192-selector-signal-date, and --v192-selector-output")
        print(json.dumps(run_v192_selector_canary(args.v192_selector_input, args.v192_selector_signal_date, args.v192_selector_output), ensure_ascii=False, indent=2))
    else:
        main(run_full_maintenance_stages=args.run_full_maintenance_stages)
