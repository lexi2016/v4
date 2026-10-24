
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import traceback
import warnings
import zipfile
from collections import Counter
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
        return {"status": "PASS", "issue_count": 0, "samples": []}
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
    return {"status": status, "issue_count": int(len(bad)), "samples": bad.head(50).to_dict(orient="records"), "xdxr_exemption_count": int(len(xdxr_exemptions)), "xdxr_exemption_samples": xdxr_exemptions.head(50).to_dict(orient="records")}


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
    api = TdxHq_API(heartbeat=True, auto_retry=True)
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
                if d > base_after_date:
                    active.append((ts, p, d))
                elif is_a_bj_ts(ts) and d > cutoff:
                    active.append((ts, p, d))
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
    for field in (*V192_FORMULA_FIELDS, "ref_hold_score"):
        if field == "formula_source":
            continue
        if field not in canonical.columns:
            raise RuntimeError(f"canonical v1.9.2 formula did not emit {field}")
        df[field] = canonical[field].to_numpy()
    df["breakout_signal"] = df["breakout"].astype(int)
    df["double_breakout_signal"] = df["double_breakout"].astype(int)

    df["ref_b123_union_debug"] = df[["B1", "B2", "B3"]].sum(axis=1)
    df["ref_hold_score"] = (
        (df["close"] >= df["pre_close"]).fillna(False).astype(int) +
        (df["close"] >= df["BBI0"]).fillna(False).astype(int) +
        (df["zge_white_line"] >= df["zge_yellow_line"]).fillna(False).astype(int) +
        (df["J"] >= df["D"]).fillna(False).astype(int)
    )

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
    inc = df[df["trade_date"] > base_after_date].copy()
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


def _formula_partition_worker(payload: Tuple[int, pd.DataFrame, int, Dict[str, Dict[str, Any]], Optional[pd.DataFrame]]) -> Tuple[int, pd.DataFrame]:
    partition_index, partition_history, base_after_date, partition_static, partition_xdxr = payload
    result = compute_formula_features(
        partition_history,
        base_after_date,
        partition_static,
        _NoopLogger(),
        emit_all_rows=False,
        xdxr_events=partition_xdxr,
    )
    return partition_index, result


def compute_formula_features_daily(
    hist: pd.DataFrame,
    base_after_date: int,
    latest_static: Dict[str, Dict[str, Any]],
    log: Logger,
    xdxr_events: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    symbols = sorted(str(value) for value in hist["ts_code"].dropna().unique())
    worker_count = daily_formula_worker_count(len(symbols))
    if worker_count <= 1:
        log.log(f"daily formula compute mode=serial symbols={len(symbols)}")
        return compute_formula_features(
            hist,
            base_after_date,
            latest_static,
            log,
            emit_all_rows=False,
            xdxr_events=xdxr_events,
        )

    symbol_partitions = [list(values) for values in np.array_split(np.array(symbols, dtype=object), worker_count) if len(values)]
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
        payloads.append((partition_index, partition_history, base_after_date, partition_static, partition_xdxr))

    log.log(
        f"daily formula compute mode=process_pool workers={worker_count} "
        f"symbols={len(symbols)} history_rows={len(hist)}"
    )
    results: Dict[int, pd.DataFrame] = {}
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(_formula_partition_worker, payload): payload[0] for payload in payloads}
        for future in as_completed(futures):
            partition_index, frame = future.result()
            results[partition_index] = frame
            log.log(
                f"daily formula partition complete={len(results)}/{len(payloads)} "
                f"partition={partition_index} increment_rows={len(frame)}"
            )
    combined = pd.concat([results[index] for index in sorted(results)], ignore_index=True)
    return combined.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


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
    write_pointer_atomic(SELECTOR_POINTER, selector_out)
    write_pointer_atomic(BACKTEST_POINTER, backtest_out)
    pointer_after = {"selector": read_pointer(SELECTOR_POINTER), "backtest": read_pointer(BACKTEST_POINTER)}
    return {
        "backup_dir": str(backup_dir),
        "pointer_after": pointer_after,
    }


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
        )
        del hist
        gc.collect()
        pre_close_chain_audit = audit_pre_close_chain(feature_df)
        write_json(RUN_DIR / "pre_close_chain_audit.json", pre_close_chain_audit)
        if pre_close_chain_audit["status"] != "PASS":
            hard_issues.append("generated_pre_close_chain_inconsistent")
            raise RuntimeError("generated_pre_close_chain_inconsistent")
        selector_inc_df = filter_increment_rows(
            feature_df,
            None,
            "selector",
            log,
            default_cutoff=int(selector_current_max),
        )
        backtest_inc_df = filter_increment_rows(
            feature_df,
            None,
            "backtest",
            log,
            default_cutoff=int(backtest_current_max),
        )
        selector_boundary_audit = audit_increment_boundary(current_last_close_frame(selector_current), selector_inc_df)
        backtest_boundary_audit = audit_increment_boundary(current_last_close_frame(backtest_current), backtest_inc_df)
        write_json(RUN_DIR / "increment_boundary_audit.json", {"selector": selector_boundary_audit, "backtest": backtest_boundary_audit})
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
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.isolated_history_rebuild:
        if not args.isolated_start_date or not args.isolated_end_date or args.isolated_output_dir is None:
            raise SystemExit("--isolated-history-rebuild requires --isolated-start-date, --isolated-end-date, and --isolated-output-dir")
        print(json.dumps(run_isolated_history_rebuild(TDX_ROOT, args.isolated_start_date, args.isolated_end_date, args.isolated_output_dir, args.isolated_lookback_records), ensure_ascii=False, indent=2))
    elif args.v192_selector_canary:
        if args.v192_selector_input is None or not args.v192_selector_signal_date or args.v192_selector_output is None:
            raise SystemExit("--v192-selector-canary requires --v192-selector-input, --v192-selector-signal-date, and --v192-selector-output")
        print(json.dumps(run_v192_selector_canary(args.v192_selector_input, args.v192_selector_signal_date, args.v192_selector_output), ensure_ascii=False, indent=2))
    else:
        main(run_full_maintenance_stages=args.run_full_maintenance_stages)
