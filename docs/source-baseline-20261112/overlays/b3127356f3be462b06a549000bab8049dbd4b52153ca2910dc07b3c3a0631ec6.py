"""Bounded, explicit-input A-share formula increment authority for V4.

This module is the V4 producer for the offline/replay path only.  It consumes a
caller-supplied manifest and parquet input, computes the reviewed formula on a
serial 260-row tail, builds one full source frame plus an authoritative
187-column selector and a 12-field auxiliary sidecar, and publishes one
atomic generation pointer only after every gate passes.  The two legacy text
pointer files remain compatibility projections; consumers must read the
generation pointer to obtain a coherent selector/backtest pair.

No network client, default data root, old release import, scheduler, or formal
state path is present here.  The historical implementation remains a
reference-only source for semantics.

Origin evidence (reference-only; never imported at runtime):
- formula builder SHA256: 074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258
- increment implementation SHA256: 901d4802c784decda9d43e757b367496d1171e5e702485a29f4c66fad3c7ae2e
- field contract SHA256: feb845426d7d37aaf63791ff1c799b575b36821d647d0977b890c0b4389b583c
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
# A direct absolute-path invocation can leave another checkout in sys.path[0].
# Put this canonical project first so the child cannot import a same-named legacy
# infrastructure package from its caller's working directory.
_project_text = str(_PROJECT_ROOT)
if sys.path[:1] != [_project_text]:
    sys.path.insert(0, _project_text)

from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.owned_io import SafeRoot
from infrastructure.formula_generation import is_v4_formula_state_path
from upstreams.v3_shared_data.shared_data import a_formula_authority


SCHEMA_VERSION = "v4.a_formula_increment_authority.v1"
FORMULA_SOURCE = a_formula_authority.FORMULA_SOURCE
FORMULA_VERSION = a_formula_authority.FORMULA_VERSION
FORMULA_ORIGIN_SHA256 = a_formula_authority.ORIGIN_SHA256
INCREMENT_ORIGIN_SHA256 = "901d4802c784decda9d43e757b367496d1171e5e702485a29f4c66fad3c7ae2e"
CONTRACT_ORIGIN_SHA256 = "feb845426d7d37aaf63791ff1c799b575b36821d647d0977b890c0b4389b583c"
TAIL_RECORDS = 260
MAX_CLOSE_RATIO = 1.5
FORMULA_GENERATION_SCHEMA = "v4.a_formula.generation_pointer.v1"
FORMULA_GENERATION_POINTER_NAME = "CURRENT_FORMULA_GENERATION.json"
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
SIDEcar_COLUMNS = (
    "breakout",
    "close_higher_than_prev",
    "close_lower_than_prev",
    "double_breakout",
    "field_contract_version",
    "formula_source",
    "ref_hold_score",
    "ref_score_above_bbi",
    "ref_score_close_up",
    "ref_score_j_no_dead_cross",
    "ref_score_no_giant_true_yin",
    "ref_score_trend_up",
)
KEY_COLUMNS = ("ts_code", "trade_date")
BASE_COLUMNS = ("ts_code", "trade_date", "open", "high", "low", "close", "volume", "amount")
V192_ENTRY_FIELDS = (
    "gold_brick_context",
    "brick_resonance_context",
    "brick_buy",
    "brick_buy1_low_absorb",
    "brick_buy2_attack",
    "primary_buy_signal",
    "secondary_buy_signal",
)
V192_INTERMEDIATE_FIELDS = ("brick_exist_b", "brick_resonance1", "brick_resonance2", "brick_resonance")

# The historical selector/backtest seeds contain a small, already-produced
# HK/HK_FUND anomaly set.  Those rows are retained as-is while the new A-share
# increment remains subject to the normal strict row gate.  The counts and
# dates below describe the approved evidence only. Runtime exceptions require
# BOTH the frozen seed SHA and exact anomaly key set; counts never authorize gaps.
KNOWN_HISTORICAL_GAP_MARKETS = ("HK", "HK_FUND")
KNOWN_HISTORICAL_GAP_DATE_RANGE = (20260504, 20260507)
KNOWN_HISTORICAL_GAP_COUNTS = {"HK": 186, "HK_FUND": 168}
APPROVED_HISTORY_CONTRACT_SHA256 = '988e483ded86ed9df6862f4a3317f74394b713c288b8f0df12fdb13ab9c04f02'

# The frozen contract names the two seed roles ``selector`` and ``backtest``.
# Runtime receipts keep their historical ``*_history`` labels, so the alias
# must be explicit rather than allowing an unrecognized role to pass through
# as a no-exception audit.
HISTORY_CONTRACT_ROLE_ALIASES = {
    "selector": "selector",
    "backtest": "backtest",
    "selector_history": "selector",
    "backtest_history": "backtest",
}


class AuthorityError(ValueError):
    """Raised when an offline input or candidate gate cannot be proven."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, (Path,)):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_has_symlink(path: Path, *, stop: Path | None = None) -> bool:
    path = Path(path).expanduser()
    stop = Path(stop).expanduser() if stop else None
    current = path if path.exists() else path.parent
    while True:
        if current.is_symlink():
            return True
        if stop is not None and current == stop:
            break
        if current.parent == current:
            break
        current = current.parent
    return False


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_formal_root(path: Path, label: str) -> None:
    text = str(path)
    if "/releases/" in text:
        raise AuthorityError(f"{label} cannot target formal release/application-support root")
    if "/Library/Application Support/" in text and not is_v4_formula_state_path(path):
        raise AuthorityError(f"{label} cannot target formal release/application-support root")
    if any(part in {"formal_state", "production_state", "current_state"} for part in path.parts):
        raise AuthorityError(f"{label} cannot target formal state root")


def _safe_output_root(data_root: Path, return_root: Path, selector_pointer: Path, backtest_pointer: Path) -> Path:
    raw_values = {
        "data_root": Path(data_root).expanduser(),
        "return_root": Path(return_root).expanduser(),
        "selector_pointer": Path(selector_pointer).expanduser(),
        "backtest_pointer": Path(backtest_pointer).expanduser(),
    }
    for label, raw in raw_values.items():
        if _path_has_symlink(raw):
            raise AuthorityError(f"{label} has a symlinked parent")
    data_root = _resolved(data_root)
    return_root = _resolved(return_root)
    selector_pointer = _resolved(selector_pointer)
    backtest_pointer = _resolved(backtest_pointer)
    output_root = return_root.parent
    if not output_root.is_absolute():
        raise AuthorityError("offline output root must be absolute")
    for label, value in (("data_root", data_root), ("return_root", return_root), ("selector_pointer", selector_pointer), ("backtest_pointer", backtest_pointer)):
        _reject_formal_root(value, label)
        if not _within(value, output_root):
            raise AuthorityError(f"{label} must be under one isolated output root: {value}")
        if _path_has_symlink(value, stop=output_root):
            raise AuthorityError(f"{label} has a symlinked parent")
    if output_root == data_root or output_root == return_root:
        raise AuthorityError("offline output root must contain separate output subdirectories")
    output_root.mkdir(parents=True, exist_ok=True)
    if _path_has_symlink(output_root):
        raise AuthorityError("isolated output root is symlinked")
    return output_root


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuthorityError(f"json unreadable: {path}") from error
    if not isinstance(value, dict):
        raise AuthorityError(f"json object required: {path}")
    return value


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    return _sha256_bytes(_canonical_bytes(payload))


def _require_pass_gate(value: Any, name: str) -> None:
    if not isinstance(value, Mapping) or str(value.get("status", "")).upper() not in {"PASS", "READY"}:
        raise AuthorityError(f"{name} must have status PASS")


def _safe_manifest_file(input_root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise AuthorityError("manifest file path is unsafe")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise AuthorityError(f"manifest file must be relative: {raw}")
    candidate_raw = input_root / relative
    if _path_has_symlink(candidate_raw):
        raise AuthorityError(f"manifest file has symlink ancestry: {raw}")
    candidate = candidate_raw.resolve(strict=False)
    if not _within(candidate, input_root):
        raise AuthorityError(f"manifest file escapes input root: {raw}")
    if _path_has_symlink(input_root) or _path_has_symlink(candidate):
        raise AuthorityError(f"manifest file has symlink ancestry: {raw}")
    if not candidate.is_file() or candidate.is_symlink():
        raise AuthorityError(f"manifest source file missing or not regular: {raw}")
    return candidate


def _load_input_manifest(input_root: Path | str, manifest_path: Path | str, target_date: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw_root = Path(input_root).expanduser()
    raw_manifest = Path(manifest_path).expanduser()
    if _path_has_symlink(raw_root) or _path_has_symlink(raw_manifest):
        raise AuthorityError("offline manifest or input root has a symlinked parent")
    root = _resolved(input_root)
    manifest_file = _resolved(manifest_path)
    if not root.is_dir() or not manifest_file.is_file() or not _within(manifest_file, root):
        raise AuthorityError("offline manifest must be a regular file inside input root")
    manifest = _read_json(manifest_file)
    if manifest.get("schema") != "v4.a_formula.input_manifest.v1":
        raise AuthorityError("unsupported offline input manifest schema")
    if str(manifest.get("market", "")).upper() != "A":
        raise AuthorityError("offline manifest market must be A")
    try:
        manifest_target = int(str(manifest.get("target_date", "")).replace("-", ""))
    except (TypeError, ValueError) as error:
        raise AuthorityError("offline manifest target_date is invalid") from error
    if manifest_target != target_date:
        raise AuthorityError(f"offline manifest target_date mismatch: {manifest_target} != {target_date}")
    source = manifest.get("source")
    if not isinstance(source, Mapping) or not str(source.get("name", "")).strip():
        raise AuthorityError("offline manifest source identity is missing")
    run_id = str(manifest.get("run_id", "")).strip()
    if not run_id or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", run_id):
        raise AuthorityError("offline manifest run_id is missing or unsafe")
    expected_manifest_sha = str(manifest.get("manifest_sha256", "")).strip()
    if not expected_manifest_sha or expected_manifest_sha != _manifest_digest(manifest):
        raise AuthorityError("offline manifest SHA mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise AuthorityError("offline manifest must list source files")
    _require_pass_gate(manifest.get("coverage"), "coverage")
    _require_pass_gate(manifest.get("duplicate_key_audit"), "duplicate_key_audit")
    _require_pass_gate(manifest.get("future_check"), "future_check")
    if int(manifest["duplicate_key_audit"].get("duplicate_rows", 0) or 0) != 0:
        raise AuthorityError("offline manifest duplicate audit is nonzero")
    if int(manifest["future_check"].get("future_rows", 0) or 0) != 0:
        raise AuthorityError("offline manifest future audit is nonzero")
    frames: list[pd.DataFrame] = []
    file_sha_values: list[str] = []
    total_manifest_rows = 0
    for item in files:
        if not isinstance(item, Mapping):
            raise AuthorityError("offline manifest file entry must be an object")
        path = _safe_manifest_file(root, item.get("path"))
        if path.suffix.lower() != ".parquet":
            raise AuthorityError(f"offline source must be parquet: {path.name}")
        actual_sha = sha256_file(path)
        expected_sha = str(item.get("sha256", "")).strip()
        if not expected_sha or actual_sha != expected_sha:
            raise AuthorityError(f"offline source SHA mismatch: {path.name}")
        try:
            frame = pd.read_parquet(path)
        except Exception as error:
            raise AuthorityError(f"offline parquet unreadable: {path}") from error
        expected_rows = item.get("rows")
        if expected_rows is not None and int(expected_rows) != len(frame):
            raise AuthorityError(f"offline source row count mismatch: {path.name}")
        frames.append(frame)
        file_sha_values.append(actual_sha)
        total_manifest_rows += len(frame)
    source_sha = str(manifest.get("source_sha256", "")).strip()
    if len(file_sha_values) == 1:
        computed_source_sha = file_sha_values[0]
    else:
        computed_source_sha = _sha256_bytes("\n".join(sorted(file_sha_values)).encode("ascii"))
    if not source_sha or source_sha != computed_source_sha:
        raise AuthorityError("offline source_sha256 mismatch")
    frame = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0].copy()
    if manifest.get("coverage", {}).get("rows") is not None and int(manifest["coverage"]["rows"]) != total_manifest_rows:
        raise AuthorityError("offline coverage row count mismatch")
    expected_symbols = manifest.get("coverage", {}).get("symbols")
    if expected_symbols is not None:
        if "ts_code" not in frame.columns or int(expected_symbols) != int(frame["ts_code"].nunique()):
            raise AuthorityError("offline coverage symbol count mismatch")
    manifest["_manifest_path"] = str(manifest_file)
    manifest["_input_root"] = str(root)
    manifest["_source_files_sha256"] = file_sha_values
    manifest["_source_rows"] = total_manifest_rows
    return _normalize_input_frame(frame, target_date), manifest


def _normalize_date_series(series: pd.Series) -> pd.Series:
    raw = series.astype(str).str.strip()
    compact = raw.where(
        raw.str.fullmatch(r"\d{8}"),
        raw.where(raw.str.fullmatch(r"\d{4}-\d{2}-\d{2}")).str.replace("-", "", regex=False),
    )
    if compact.isna().any() or compact.str.fullmatch(r"\d{8}").eq(False).any():
        raise AuthorityError("trade_date contains invalid values")
    parsed = pd.to_datetime(compact, format="%Y%m%d", errors="coerce")
    if parsed.isna().any():
        raise AuthorityError("trade_date contains invalid values")
    return pd.to_numeric(compact, errors="raise").astype("int64")


def _normalize_input_frame(frame: pd.DataFrame, target_date: int) -> pd.DataFrame:
    work = frame.copy()
    if "volume" not in work.columns and "vol" in work.columns:
        work["volume"] = work["vol"]
    if "amount" not in work.columns and "turnover" in work.columns:
        work["amount"] = work["turnover"]
    missing = sorted(set(BASE_COLUMNS) - set(work.columns))
    if missing:
        raise AuthorityError(f"offline input missing base columns: {','.join(missing)}")
    work["ts_code"] = work["ts_code"].astype(str).str.strip()
    if work["ts_code"].eq("").any():
        raise AuthorityError("offline input contains blank ts_code")
    work["trade_date"] = _normalize_date_series(work["trade_date"])
    if work["trade_date"].gt(target_date).any():
        raise AuthorityError("offline input contains future rows")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    if work[list(("open", "high", "low", "close"))].isna().any().any():
        raise AuthorityError("offline input contains nonnumeric OHLC")
    if (work[["open", "high", "low", "close"]] <= 0).any().any():
        raise AuthorityError("offline input contains nonpositive OHLC")
    if work["high"].lt(work["low"]).any() or work["close"].gt(work["high"]).any() or work["close"].lt(work["low"]).any():
        raise AuthorityError("offline input contains structurally invalid OHLC")
    duplicate_count = int(work.duplicated(list(KEY_COLUMNS)).sum())
    if duplicate_count:
        raise AuthorityError(f"offline input duplicate key rows: {duplicate_count}")
    work = work.sort_values(["ts_code", "trade_date"], kind="mergesort").reset_index(drop=True)
    if not (work.groupby("ts_code", sort=False)["trade_date"].diff().dropna() > 0).all():
        raise AuthorityError("offline input dates are not strictly increasing per symbol")
    if not (work["trade_date"] == target_date).any():
        raise AuthorityError("offline input has no target-date row")
    return work


def _read_seed(path: Path | str, role: str) -> pd.DataFrame:
    raw_path = Path(path).expanduser()
    if _path_has_symlink(raw_path):
        raise AuthorityError(f"{role} seed has a symlinked parent: {raw_path}")
    candidate = _resolved(path)
    if not candidate.is_file():
        raise AuthorityError(f"{role} seed missing or not regular: {candidate}")
    if candidate.suffix.lower() != ".parquet":
        raise AuthorityError(f"{role} seed must be parquet: {candidate}")
    try:
        frame = pd.read_parquet(candidate)
    except Exception as error:
        raise AuthorityError(f"{role} seed unreadable: {candidate}") from error
    missing = sorted(set(KEY_COLUMNS) - set(frame.columns))
    if missing:
        raise AuthorityError(f"{role} seed missing key columns: {','.join(missing)}")
    frame = frame.copy()
    frame["ts_code"] = frame["ts_code"].astype(str)
    frame["trade_date"] = _normalize_date_series(frame["trade_date"])
    if frame.duplicated(list(KEY_COLUMNS)).any():
        raise AuthorityError(f"{role} seed has duplicate keys")
    return frame.sort_values(list(KEY_COLUMNS), kind="mergesort").reset_index(drop=True)


def collect_increment_history(frame: pd.DataFrame, *, tail_records: int = TAIL_RECORDS) -> pd.DataFrame:
    """Keep the explicit per-symbol tail used by the reviewed increment path."""
    if tail_records < 1:
        raise AuthorityError("tail_records must be positive")
    return (
        frame.sort_values(["ts_code", "trade_date"], kind="mergesort")
        .groupby("ts_code", sort=False, group_keys=False)
        .tail(int(tail_records))
        .reset_index(drop=True)
    )


def _backfill_increment_contract_columns(
    features: pd.DataFrame,
    *current_frames: pd.DataFrame,
) -> pd.DataFrame:
    """Carry stable source/contract columns from the reviewed seed rows.

    The live ``.day`` adapter intentionally contains only market bars.  The
    existing selector/backtest seeds remain the authority for stable metadata
    (exchange, source, panel constants, and similar contract columns); formula
    values computed for the new rows are never replaced.  A symbol with no
    seed metadata fails closed instead of receiving a guessed default.
    """

    work = features.copy()
    if "ts_code" not in work.columns:
        raise AuthorityError("formula features are missing ts_code")
    keys = work["ts_code"].astype(str)
    for current in current_frames:
        if current is None or current.empty or "ts_code" not in current.columns:
            continue
        ordered = current.sort_values(["ts_code", "trade_date"], kind="mergesort")
        latest = ordered.groupby("ts_code", sort=False).tail(1).set_index("ts_code")
        for column in current.columns:
            if column in work.columns or column in KEY_COLUMNS:
                continue
            work[column] = keys.map(latest[column])
    return work


def compute_formula_features(history: pd.DataFrame) -> pd.DataFrame:
    """Compute the reviewed formula once through the V4 pure authority."""
    if history.empty:
        raise AuthorityError("formula history is empty")
    input_keys = history[list(KEY_COLUMNS)].astype(str).reset_index(drop=True)
    try:
        computed = a_formula_authority.compute_partition_formula(history.copy()).reset_index(drop=True)
    except Exception as error:
        raise AuthorityError(f"formula computation failed: {type(error).__name__}: {error}") from error
    if len(computed) != len(history):
        raise AuthorityError("formula row count changed")
    output_keys = computed[list(KEY_COLUMNS)].astype(str).reset_index(drop=True)
    if not input_keys.equals(output_keys):
        raise AuthorityError("formula changed key order")
    computed["primary_buy_signal"] = (
        computed.get("brick_buy2_attack", 0).eq(1)
        | computed.get("B3", 0).eq(1)
        | computed.get("double_breakout", 0).eq(1)
    ).astype(np.int8)
    computed["secondary_buy_signal"] = (
        computed.get("brick_buy1_low_absorb", 0).eq(1)
        | computed.get("B2", 0).eq(1)
        | computed.get("breakout_cross_star", 0).eq(1)
    ).astype(np.int8)
    computed["formula_source"] = FORMULA_SOURCE
    return computed


def select_generated_increment_rows(features: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    if features.empty:
        return features.copy()
    if current.empty:
        return features.copy().reset_index(drop=True)
    latest = current.groupby("ts_code", sort=False)["trade_date"].max().to_dict()
    cutoff = features["ts_code"].map(latest).fillna(0).astype("int64")
    return features.loc[features["trade_date"].astype("int64") > cutoff].copy().reset_index(drop=True)


def filter_increment_rows(features: pd.DataFrame, current: pd.DataFrame, *, role: str = "selector") -> pd.DataFrame:
    """Compatibility wrapper retaining the reviewed date cutoff semantics."""
    del role
    return select_generated_increment_rows(features, current)


def _audit_increment_boundary(current: pd.DataFrame, increment: pd.DataFrame) -> dict[str, Any]:
    if increment.empty:
        return {"status": "PASS", "rows": 0, "future_rows": 0, "duplicate_rows": 0, "bad_symbols": []}
    if increment.duplicated(list(KEY_COLUMNS)).any():
        return {"status": "FAIL", "rows": len(increment), "future_rows": 0, "duplicate_rows": int(increment.duplicated(list(KEY_COLUMNS)).sum()), "bad_symbols": []}
    future_rows = 0
    bad_symbols: list[str] = []
    if not current.empty:
        latest = current.groupby("ts_code", sort=False)["trade_date"].max().to_dict()
        for code, group in increment.groupby("ts_code", sort=False):
            if int(group["trade_date"].min()) <= int(latest.get(code, 0)):
                bad_symbols.append(str(code))
    result = {
        "status": "PASS" if not bad_symbols else "FAIL",
        "rows": int(len(increment)),
        "future_rows": int(future_rows),
        "duplicate_rows": int(increment.duplicated(list(KEY_COLUMNS)).sum()),
        "bad_symbols": sorted(bad_symbols),
    }
    return result


def _key_sha256(frame: pd.DataFrame) -> str:
    """Hash the sorted authority keys for source/sidecar binding."""
    if any(column not in frame.columns for column in KEY_COLUMNS):
        raise AuthorityError("key digest requires authority key columns")
    rows = [
        [str(row[0]), int(row[1])]
        for row in frame.loc[:, list(KEY_COLUMNS)].sort_values(list(KEY_COLUMNS), kind="mergesort").itertuples(index=False, name=None)
    ]
    return _sha256_bytes(_canonical_bytes(rows))


def _retention_hash_table(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """Build a compact sorted key/row-hash table for large seed frames.

    The seeds are multi-gigabyte parquet inputs.  A Python dict of every cell
    would multiply their memory footprint, so retention is checked with
    pandas' stable row hash and a three-column key table instead.
    """

    selected = list(columns)
    missing = [column for column in selected if column not in frame.columns]
    if missing:
        raise AuthorityError(f"logical row digest missing columns: {','.join(missing)}")
    row_hashes = pd.util.hash_pandas_object(
        frame.loc[:, selected],
        index=False,
        categorize=False,
    ).to_numpy(dtype="uint64", copy=False)
    table = frame.loc[:, list(KEY_COLUMNS)].copy()
    table["_retention_hash"] = pd.array(row_hashes, dtype="UInt64")
    return table.sort_values(list(KEY_COLUMNS), kind="mergesort").reset_index(drop=True)


def _align_retention_hash_frames(
    current: pd.DataFrame,
    combined: pd.DataFrame,
    columns: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize only dtype-promoted columns before hashing two frames.

    ``pd.concat`` may promote a historical integer column to float or a
    string extension column to object when the new increment is appended.  A
    value-preserving common dtype prevents that representation change from
    looking like a historical edit while still retaining changed numeric or
    textual values for comparison.
    """

    left = current.copy(deep=False)
    right = combined.copy(deep=False)
    for column in columns:
        left_dtype = current[column].dtype
        right_dtype = combined[column].dtype
        if left_dtype == right_dtype:
            continue
        left_numeric = pd.api.types.is_numeric_dtype(left_dtype)
        right_numeric = pd.api.types.is_numeric_dtype(right_dtype)
        if left_numeric and right_numeric:
            left[column] = pd.to_numeric(current[column], errors="coerce").astype("float64")
            right[column] = pd.to_numeric(combined[column], errors="coerce").astype("float64")
            continue
        left_datetime = pd.api.types.is_datetime64_any_dtype(left_dtype)
        right_datetime = pd.api.types.is_datetime64_any_dtype(right_dtype)
        if left_datetime and right_datetime:
            left[column] = pd.to_datetime(current[column], errors="coerce")
            right[column] = pd.to_datetime(combined[column], errors="coerce")
            continue
        # String/object columns are compared by their textual values, with
        # all pandas missing sentinels represented by the same nullable value.
        left[column] = current[column].astype("string")
        right[column] = combined[column].astype("string")
    return left, right


def _hash_table_digest(table: pd.DataFrame, columns: Sequence[str], *, hash_column: str = "_retention_hash") -> str:
    digest = hashlib.sha256()
    digest.update(_canonical_bytes({"algorithm": "pandas.hash_pandas_object.v1", "columns": list(columns)}))
    digest.update(b"\0")
    values = table[hash_column].to_numpy(dtype="uint64", na_value=0).astype("<u8", copy=False)
    digest.update(values.tobytes())
    return digest.hexdigest()


def _external_market(ts_code: Any) -> str | None:
    match = re.fullmatch(r"\d{5}\.([A-Za-z_]+)", str(ts_code).strip())
    if not match:
        return None
    market = match.group(1).upper()
    return market if market in KNOWN_HISTORICAL_GAP_MARKETS else None


def _approved_history_gap_keys(role: str, seed_sha256: str, observed: set[tuple[str, int]]) -> dict[str, Any]:
    """Read frozen evidence; no path, row-count or same-window substitution."""
    contract_role = HISTORY_CONTRACT_ROLE_ALIASES.get(role)
    if contract_role is None:
        raise AuthorityError(f"{role} historical role is not approved")
    raw = SafeRoot(_PROJECT_ROOT).read_bytes("contracts/a_known_history_gaps.json", max_bytes=256 * 1024)
    if hashlib.sha256(raw).hexdigest() != APPROVED_HISTORY_CONTRACT_SHA256:
        raise AuthorityError("approved historical gap contract SHA mismatch")
    contract = json.loads(raw)
    if contract.get("schema") != "v4.a_known_history_gaps.v1":
        raise AuthorityError("approved historical gap contract schema mismatch")
    entries = contract.get("seeds")
    if not isinstance(entries, list) or {e.get("role") for e in entries} != {"selector", "backtest"} or len(entries) != 2:
        raise AuthorityError("approved historical gap roles mismatch")
    approved = next((e for e in entries if e["role"] == contract_role), None)
    known_seed = any(e.get("seed_sha256") == seed_sha256 for e in entries)
    if observed or known_seed:
        if approved is None or approved.get("seed_sha256") != seed_sha256:
            raise AuthorityError(f"{role} historical anomaly seed SHA not approved")
        items = approved.get("keys", [])
        expected = {(str(k["ts_code"]), int(k["trade_date"])) for k in items}
        if len(expected) != 354 or len(items) != len(expected):
            raise AuthorityError("approved historical gap key contract invalid")
        if observed != expected:
            raise AuthorityError(f"{role} historical anomaly keys mismatch: "
                                 f"extra={sorted(observed - expected)[:5]}, missing={sorted(expected - observed)[:5]}")
    else:
        expected = set()  # a different clean seed obtains no historical exception
    return {"contract_sha256": APPROVED_HISTORY_CONTRACT_SHA256,
            "contract_role": contract_role,
            "approved_key_count": len(expected),
            "observed_key_count": len(observed),
            "key_sha256": hashlib.sha256(json.dumps(sorted(observed), separators=(",", ":")).encode()).hexdigest(),
            "status": "EXACT_SEED_AND_KEYS_MATCH" if observed else "NO_EXCEPTION_USED"}


def _audit_existing_history(
    current: pd.DataFrame,
    combined: pd.DataFrame,
    *,
    role: str,
    target_date: int,
    seed_sha256: str,
) -> dict[str, Any]:
    """Prove append-only retention without re-gating known old HK anomalies.

    Only rows introduced by the current run are validated by the strict
    selector/backtest gates.  Existing rows must remain present with the same
    logical key/value content.  Known historical HK/HK_FUND close-range rows
    are reported as an unresolved health gap; any other historical structural
    issue still fails closed.
    """

    required = list(KEY_COLUMNS) + ["open", "high", "low", "close"]
    missing = sorted(set(required) - set(current.columns))
    if missing:
        raise AuthorityError(f"{role} existing history missing required columns: {','.join(missing)}")
    missing_combined = sorted(set(required) - set(combined.columns))
    if missing_combined:
        raise AuthorityError(f"{role} appended history missing required columns: {','.join(missing_combined)}")
    if current.duplicated(list(KEY_COLUMNS)).any() or combined.duplicated(list(KEY_COLUMNS)).any():
        raise AuthorityError(f"{role} history contains duplicate keys")

    current_dates = pd.to_numeric(current["trade_date"], errors="coerce")
    combined_dates = pd.to_numeric(combined["trade_date"], errors="coerce")
    if current_dates.isna().any() or combined_dates.isna().any():
        raise AuthorityError(f"{role} history contains invalid trade_date values")
    if current_dates.gt(target_date).any() or combined_dates.gt(target_date).any():
        raise AuthorityError(f"{role} history contains future rows")
    if current["ts_code"].astype(str).str.strip().eq("").any() or combined["ts_code"].astype(str).str.strip().eq("").any():
        raise AuthorityError(f"{role} history contains blank ts_code")

    numeric = current[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    nonpositive_or_non_numeric = numeric.isna().any(axis=1) | numeric.le(0).any(axis=1)
    high_low_bad = numeric["high"].lt(numeric["low"])
    close_outside = numeric["close"].gt(numeric["high"]) | numeric["close"].lt(numeric["low"])
    external_market = current["ts_code"].map(_external_market)
    gap_min, gap_max = KNOWN_HISTORICAL_GAP_DATE_RANGE
    known_gap = (
        external_market.notna()
        & close_outside
        & ~nonpositive_or_non_numeric
        & ~high_low_bad
        & current_dates.between(gap_min, gap_max)
    )
    unexpected = (nonpositive_or_non_numeric | high_low_bad | close_outside) & ~known_gap
    if unexpected.any():
        sample = [
            {"ts_code": str(code), "trade_date": int(day)}
            for code, day in current.loc[unexpected, list(KEY_COLUMNS)].head(5).itertuples(index=False, name=None)
        ]
        raise AuthorityError(f"{role} existing history structural gate failed: {sample}")

    observed_gap_keys = {(str(code), int(day)) for code, day in
                         current.loc[known_gap, list(KEY_COLUMNS)].itertuples(index=False, name=None)}
    gap_binding = _approved_history_gap_keys(role, seed_sha256, observed_gap_keys)

    columns = list(current.columns)
    current_for_hash, combined_for_hash = _align_retention_hash_frames(current, combined, columns)
    current_hashes = _retention_hash_table(current_for_hash, columns)
    combined_hashes = _retention_hash_table(combined_for_hash, columns)
    joined = current_hashes.merge(
        combined_hashes,
        on=list(KEY_COLUMNS),
        how="left",
        sort=False,
        validate="one_to_one",
        suffixes=("_current", "_combined"),
    )
    missing_mask = joined["_retention_hash_combined"].isna()
    changed_mask = (joined["_retention_hash_current"] != joined["_retention_hash_combined"]).fillna(False)
    missing_keys = [
        list(key)
        for key in joined.loc[missing_mask, list(KEY_COLUMNS)].head(5).itertuples(index=False, name=None)
    ]
    changed_keys = [
        list(key)
        for key in joined.loc[changed_mask, list(KEY_COLUMNS)].head(5).itertuples(index=False, name=None)
    ]
    if missing_mask.any() or changed_mask.any():
        details = {
            "missing_keys": missing_keys,
            "changed_keys": changed_keys,
        }
        raise AuthorityError(f"{role} existing history retention failed: {details}")
    before_digest = _hash_table_digest(current_hashes, columns)
    after_digest = _hash_table_digest(joined, columns, hash_column="_retention_hash_combined")
    if before_digest != after_digest:
        raise AuthorityError(f"{role} existing history logical value digest changed")

    gap_reports: list[dict[str, Any]] = []
    for market in KNOWN_HISTORICAL_GAP_MARKETS:
        market_rows = known_gap & external_market.eq(market)
        if not market_rows.any():
            continue
        dates = current.loc[market_rows, "trade_date"].astype(int)
        gap_reports.append(
            {
                "status": "CANNOT_CONFIRM",
                "resolution": "RECORDED_NOT_REPAIRED",
                "market": market,
                "rows": int(market_rows.sum()),
                "expected_reference_rows": int(KNOWN_HISTORICAL_GAP_COUNTS[market]),
                "date_range": [int(dates.min()), int(dates.max())],
                "seed_sha256": seed_sha256,
                "reason": "pre-existing close outside high/low is retained and excluded from the new A increment gate",
            }
        )
    return {
        "status": "PASS",
        "role": role,
        "target_date": int(target_date),
        "existing_rows": int(len(current)),
        "existing_rows_retained": int(len(current)),
        "existing_rows_value_sha256_before": before_digest,
        "existing_rows_value_sha256_after": after_digest,
        "logical_hash_algorithm": "pandas.hash_pandas_object.v1",
        "seed_sha256": str(seed_sha256),
        "known_historical_gaps": gap_reports,
        "known_historical_gap_binding": gap_binding,
        "historical_health": "CANNOT_CONFIRM",
        "full_seed_health": "CANNOT_CONFIRM",
        "retention_scope": "logical key/value retention; physical parquet bytes are not required",
    }


def _historical_seed_health(*audits: Mapping[str, Any]) -> dict[str, Any]:
    """Keep seed health explicitly unresolved outside this increment scope."""

    gaps: list[dict[str, Any]] = []
    roles: dict[str, Any] = {}
    for audit in audits:
        role = str(audit.get("role", "unknown"))
        roles[role] = {
            "seed_sha256": str(audit.get("seed_sha256", "")),
            "existing_rows": int(audit.get("existing_rows", 0)),
            "retained_rows": int(audit.get("existing_rows_retained", 0)),
            "known_historical_gaps": audit.get("known_historical_gaps", []),
        }
        gaps.extend(audit.get("known_historical_gaps", []))
    return {
        "status": "CANNOT_CONFIRM",
        "reason": "historical seed health is outside the new A increment scope; retained rows are not re-authorized as a full-seed health claim",
        "known_historical_gaps": gaps,
        "roles": roles,
    }


def load_authoritative_contract_rows(contract_csv: Path | str) -> list[dict[str, str]]:
    raw_path = Path(contract_csv).expanduser()
    if _path_has_symlink(raw_path):
        raise AuthorityError(f"contract csv has a symlinked parent: {raw_path}")
    path = _resolved(contract_csv)
    if not path.is_file():
        raise AuthorityError(f"contract csv missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("column")]
    if len(rows) != 199:
        raise AuthorityError(f"contract row count must be 199, got {len(rows)}")
    return rows


def build_contract_policy(rows: list[dict[str, str]], contract_csv: Path | str) -> dict[str, Any]:
    official = [row["column"] for row in rows if row.get("allowed_in_current") == "yes"]
    if len(official) != 187 or len(set(official)) != len(official):
        raise AuthorityError("contract official projection is not exactly 187 columns")
    sidecar = [row["column"] for row in rows if row.get("script_action") == "sidecar_only"]
    # The review contract has six explicit sidecar rows; aliases and lineage
    # rows are also retained in the auxiliary artifact, yielding the required 12.
    by_name = {row["column"]: row for row in rows}
    forced = [name for name in SIDEcar_COLUMNS if name in by_name]
    if len(forced) != 12:
        raise AuthorityError("contract auxiliary projection is not exactly 12 columns")
    versions = sorted({row.get("contract_version", "") for row in rows if row.get("contract_version")})
    return {
        "contract_csv": str(_resolved(contract_csv)),
        "rows": rows,
        "official_columns": official,
        "sidecar_columns": forced,
        "contract_version": versions[-1] if versions else "authoritative_field_contract_v0_2_phase1",
        "row_count": len(rows),
        "official_count": len(official),
        "sidecar_count": len(forced),
        "script_sidecar_columns": sidecar,
    }


def build_table_for_schema(new_df: pd.DataFrame, schema_columns: Sequence[str], role: str) -> pd.DataFrame:
    missing = [column for column in schema_columns if column not in new_df.columns]
    if missing:
        raise AuthorityError(f"{role} schema missing generated columns: {','.join(missing)}")
    return new_df.loc[:, list(schema_columns)].copy()


def _validate_signal_fields(frame: pd.DataFrame) -> None:
    for field in V192_ENTRY_FIELDS + V192_INTERMEDIATE_FIELDS:
        if field not in frame.columns:
            raise AuthorityError(f"missing V192 signal field: {field}")
        if field == "gold_brick_context":
            if frame[field].isna().any() or (~frame[field].astype(str).isin({"none", "old_gold_candidate"})).any():
                raise AuthorityError("invalid gold_brick_context")
        else:
            values = pd.to_numeric(frame[field], errors="coerce")
            if values.isna().any() or (~values.isin([0, 1])).any():
                raise AuthorityError(f"invalid V192 signal field: {field}")


def validate_new_selector_rows(frame: pd.DataFrame, target_date: int, *, role: str = "selector") -> dict[str, Any]:
    if frame.empty:
        raise AuthorityError(f"{role} candidate is empty")
    missing = sorted(set(KEY_COLUMNS + ("open", "high", "low", "close")) - set(frame.columns))
    if missing:
        raise AuthorityError(f"{role} candidate missing required columns: {','.join(missing)}")
    duplicate_rows = int(frame.duplicated(list(KEY_COLUMNS)).sum())
    future_rows = int(pd.to_numeric(frame["trade_date"], errors="coerce").gt(target_date).sum())
    ohlc_bad = int((frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce").le(0)).any(axis=1).sum())
    high_low_bad = int(pd.to_numeric(frame["high"], errors="coerce").lt(pd.to_numeric(frame["low"], errors="coerce")).sum())
    close_outside = int((pd.to_numeric(frame["close"], errors="coerce").gt(pd.to_numeric(frame["high"], errors="coerce")) | pd.to_numeric(frame["close"], errors="coerce").lt(pd.to_numeric(frame["low"], errors="coerce"))).sum())
    if duplicate_rows or future_rows or ohlc_bad or high_low_bad or close_outside:
        raise AuthorityError(f"{role} candidate row gate failed: duplicate={duplicate_rows},future={future_rows},ohlc={ohlc_bad},range={high_low_bad},close={close_outside}")
    if not (pd.to_numeric(frame["trade_date"], errors="coerce") == target_date).any():
        raise AuthorityError(f"{role} candidate has no target-date rows")
    _validate_signal_fields(frame)
    return {
        "status": "PASS",
        "role": role,
        "rows": int(len(frame)),
        "target_rows": int((frame["trade_date"] == target_date).sum()),
        "target_date": target_date,
        "duplicate_rows": duplicate_rows,
        "future_rows": future_rows,
        "ohlc_bad": ohlc_bad,
    }


def _validate_backtest_frame(frame: pd.DataFrame, target_date: int) -> dict[str, Any]:
    if frame.empty:
        raise AuthorityError("backtest candidate is empty")
    missing = sorted(set(KEY_COLUMNS + ("open", "high", "low", "close")) - set(frame.columns))
    if missing:
        raise AuthorityError(f"backtest candidate missing required columns: {','.join(missing)}")
    duplicate_rows = int(frame.duplicated(list(KEY_COLUMNS)).sum())
    future_rows = int(pd.to_numeric(frame["trade_date"], errors="coerce").gt(target_date).sum())
    numeric = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    range_bad = int((numeric.le(0)).any(axis=1).sum())
    range_bad += int(numeric["high"].lt(numeric["low"]).sum())
    range_bad += int((numeric["close"].gt(numeric["high"]) | numeric["close"].lt(numeric["low"])).sum())
    if duplicate_rows or future_rows or range_bad:
        raise AuthorityError(f"backtest candidate row gate failed: duplicate={duplicate_rows},future={future_rows},range={range_bad}")
    if not (pd.to_numeric(frame["trade_date"], errors="coerce") == target_date).any():
        raise AuthorityError("backtest candidate has no target-date rows")
    return {"status": "PASS", "role": "backtest", "rows": int(len(frame)), "target_rows": int((frame["trade_date"] == target_date).sum()), "duplicate_rows": duplicate_rows, "future_rows": future_rows}


def build_official_selector_frame(frame: pd.DataFrame, policy: Mapping[str, Any]) -> pd.DataFrame:
    official = list(policy["official_columns"])
    missing = [column for column in official if column not in frame.columns]
    if missing:
        raise AuthorityError(f"official selector missing contract columns: {','.join(missing)}")
    output = frame.loc[:, official].copy()
    if list(output.columns) != official or len(output.columns) != 187:
        raise AuthorityError("official selector projection is not exactly 187 columns")
    return output


def build_sidecar_frame(frame: pd.DataFrame, policy: Mapping[str, Any]) -> pd.DataFrame:
    missing = [column for column in list(KEY_COLUMNS) + list(policy["sidecar_columns"]) if column not in frame.columns]
    if missing:
        raise AuthorityError(f"auxiliary sidecar missing columns: {','.join(missing)}")
    output = frame.loc[:, list(KEY_COLUMNS) + list(policy["sidecar_columns"])].copy()
    if output.duplicated(list(KEY_COLUMNS)).any():
        raise AuthorityError("auxiliary sidecar duplicate keys")
    if output[list(policy["sidecar_columns"])].isna().any().any():
        raise AuthorityError("auxiliary sidecar contains null lineage/formula fields")
    return output


def _append_rows(current: pd.DataFrame, increment: pd.DataFrame, *, role: str) -> pd.DataFrame:
    if increment.empty:
        return current.copy()
    columns = list(current.columns)
    missing = [column for column in columns if column not in increment.columns]
    if missing:
        # Explicit aliases are part of the reviewed daily source schema.
        increment = increment.copy()
        if "vol" in missing and "volume" in increment.columns:
            increment["vol"] = increment["volume"]
        if "turnover" in missing and "amount" in increment.columns:
            increment["turnover"] = increment["amount"]
        missing = [column for column in columns if column not in increment.columns]
    if missing:
        raise AuthorityError(f"{role} increment cannot preserve schema columns: {','.join(missing)}")
    extra = [column for column in increment.columns if column not in columns]
    combined = pd.concat([current, increment.loc[:, columns + extra]], ignore_index=True, sort=False)
    if combined.duplicated(list(KEY_COLUMNS)).any():
        raise AuthorityError(f"{role} append produced duplicate keys")
    return combined.sort_values(list(KEY_COLUMNS), kind="mergesort").reset_index(drop=True)


def _atomic_parquet(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _path_has_symlink(destination.parent):
        raise AuthorityError(f"candidate output parent is symlinked: {destination.parent}")
    fd, raw = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    os.close(fd)
    temporary = Path(raw)
    try:
        frame.to_parquet(temporary, index=False, engine="pyarrow")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_pointer_bytes(pointer: Path) -> bytes | None:
    try:
        raw = pointer.read_bytes()
    except FileNotFoundError:
        return None
    if pointer.is_symlink():
        raise AuthorityError(f"pointer is symlinked: {pointer}")
    return raw


def _pointer_target_bytes(path: Path) -> bytes:
    return (str(path) + "\n").encode("utf-8")


def _generation_pointer_path(output_root: Path) -> Path:
    return _resolved(output_root) / FORMULA_GENERATION_POINTER_NAME


def _generation_target_metadata(path: Path, output_root: Path, role: str) -> dict[str, Any]:
    target = _resolved(path)
    root = _resolved(output_root)
    if not _within(target, root) or _path_has_symlink(path, stop=root) or target.is_symlink() or not target.is_file():
        raise AuthorityError(f"{role} target is missing or outside isolated output root")
    return {"path": str(target), "bytes": target.stat().st_size, "sha256": sha256_file(target)}


def _generation_payload(
    output_root: Path,
    selector_target: Path,
    backtest_target: Path,
    generation_metadata: Mapping[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    selector = _generation_target_metadata(selector_target, output_root, "selector")
    backtest = _generation_target_metadata(backtest_target, output_root, "backtest")
    if selector["path"] == backtest["path"]:
        raise AuthorityError("selector/backtest targets must differ")
    identity = {"selector": selector, "backtest": backtest}
    payload = {
        "schema": FORMULA_GENERATION_SCHEMA,
        "status": "READY",
        "generation_id": _sha256_bytes(_canonical_bytes(identity)),
        "selector": selector,
        "backtest": backtest,
    }
    # The selector/backtest pair remains the stable generation identity.  The
    # optional fields bind that pair to the exact input/source/sidecar used by
    # the V4 runner without changing the legacy identity or its projections.
    if generation_metadata is not None:
        if not isinstance(generation_metadata, Mapping):
            raise AuthorityError("generation metadata must be an object")
        payload.update(_jsonable(dict(generation_metadata)))
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"), payload


def _generation_evidence(raw: bytes | None) -> dict[str, Any]:
    return {
        "exists": raw is not None,
        "sha256": _sha256_bytes(raw) if raw is not None else "",
        "bytes": len(raw) if raw is not None else 0,
    }


def _copy_generation_owned_file(
    source: Path | str,
    destination: Path,
    *,
    role: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Copy one validated input document below the generation output root.

    The strict generation reader intentionally rejects provenance files that
    resolve outside the pointer's output root.  Keep the source bytes intact,
    but publish an owned copy beside the generated artifacts so an offline
    replay remains self-contained and its original digest is still auditable.
    """

    raw_source = Path(source).expanduser()
    if _path_has_symlink(raw_source) or raw_source.is_symlink():
        raise AuthorityError(f"{role} source is symlinked")
    source_path = _resolved(raw_source)
    if not source_path.is_file() or source_path.is_symlink():
        raise AuthorityError(f"{role} source is missing or not regular")
    raw = source_path.read_bytes()
    actual_sha256 = _sha256_bytes(raw)
    if expected_sha256 is not None and actual_sha256 != str(expected_sha256).lower():
        raise AuthorityError(f"{role} source SHA mismatch")

    destination = _resolved(destination)
    if destination.exists() or destination.is_symlink():
        raise AuthorityError(f"{role} owned destination already exists")
    if _path_has_symlink(destination.parent):
        raise AuthorityError(f"{role} owned destination has symlink ancestry")
    destination.parent.mkdir(parents=True, exist_ok=True)
    SafeRoot(destination.parent).write_bytes(destination.name, raw)
    if destination.is_symlink() or not destination.is_file() or destination.read_bytes() != raw:
        raise AuthorityError(f"{role} owned copy readback mismatch")
    return {
        "path": str(destination),
        "bytes": len(raw),
        "sha256": actual_sha256,
        "source_path": str(source_path),
    }


def _prepare_generation_owned_evidence(
    run_dir: Path,
    manifest: Mapping[str, Any],
    *,
    target_date: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Bind the input manifest and its sync receipt to this generation.

    ``a_formula_input_manifest`` records the receipt under
    ``sync_receipt_path``; accepted-only manifests use the older
    ``source_receipt_path`` spelling.  Both names are accepted as source
    provenance, then normalized to the strict generation reader's
    ``sync_receipt_*`` fields while preserving the original source SHA.
    """

    source = manifest.get("source")
    if not isinstance(source, Mapping):
        raise AuthorityError("input manifest source identity is missing")
    receipt_path_value = source.get("sync_receipt_path") or source.get("source_receipt_path")
    receipt_sha_value = source.get("sync_receipt_sha256") or source.get("source_receipt_sha256")
    if not isinstance(receipt_path_value, str) or not receipt_path_value.strip():
        raise AuthorityError("input manifest source sync receipt path is missing")
    if not isinstance(receipt_sha_value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", receipt_sha_value):
        raise AuthorityError("input manifest source sync receipt SHA is invalid")

    manifest_source = _resolved(manifest["_manifest_path"])
    receipt_source = Path(receipt_path_value).expanduser()
    if not receipt_source.is_absolute():
        receipt_source = manifest_source.parent / receipt_source
    if _path_has_symlink(receipt_source) or receipt_source.is_symlink():
        raise AuthorityError("input manifest source sync receipt is missing or symlinked")
    receipt_source = _resolved(receipt_source)
    if _path_has_symlink(receipt_source) or receipt_source.is_symlink() or not receipt_source.is_file():
        raise AuthorityError("input manifest source sync receipt is missing or symlinked")
    try:
        receipt_raw = receipt_source.read_bytes()
    except OSError as error:
        raise AuthorityError("input manifest source sync receipt is unreadable") from error
    try:
        receipt_payload = json.loads(receipt_raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuthorityError("input manifest source sync receipt is unreadable") from error
    if not isinstance(receipt_payload, Mapping) or str(receipt_payload.get("status") or "").upper() not in {"READY", "PASS"}:
        raise AuthorityError("input manifest source sync receipt is not READY")
    try:
        receipt_target = int(str(receipt_payload.get("target_date") or "").replace("-", ""))
    except (TypeError, ValueError) as error:
        raise AuthorityError("input manifest source sync receipt target date is invalid") from error
    if receipt_target != int(target_date):
        raise AuthorityError("input manifest source sync receipt target date mismatch")
    if any(receipt_payload.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise AuthorityError("input manifest source sync receipt safety flags are not false")

    owned_manifest = _copy_generation_owned_file(
        manifest_source,
        run_dir / "input-manifest.json",
        role="input manifest",
    )
    owned_receipt = _copy_generation_owned_file(
        receipt_source,
        run_dir / "sync-receipt.json",
        role="sync receipt",
        expected_sha256=receipt_sha_value,
    )

    normalized_source = dict(source)
    # Keep the generation self-contained for both the current and legacy
    # source field spellings.  The raw input manifest remains byte-identical;
    # this only changes the generation metadata that points to its owned copy.
    normalized_source["sync_receipt_path"] = owned_receipt["path"]
    normalized_source["sync_receipt_sha256"] = owned_receipt["sha256"]
    if "source_receipt_path" in normalized_source:
        normalized_source["source_receipt_path"] = owned_receipt["path"]
    if "source_receipt_sha256" in normalized_source:
        normalized_source["source_receipt_sha256"] = owned_receipt["sha256"]
    return normalized_source, owned_manifest, owned_receipt


def _write_pointer_pair(
    selector_pointer: Path,
    backtest_pointer: Path,
    selector_target: Path,
    backtest_target: Path,
    output_root: Path,
    generation_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    output_root = _resolved(output_root)
    selector_pointer = _resolved(selector_pointer)
    backtest_pointer = _resolved(backtest_pointer)
    for pointer in (selector_pointer, backtest_pointer):
        pointer.parent.mkdir(parents=True, exist_ok=True)
        if _path_has_symlink(pointer.parent, stop=output_root) or pointer.is_symlink():
            raise AuthorityError(f"pointer path is symlinked: {pointer}")
    generation_raw, generation = _generation_payload(
        output_root,
        selector_target,
        backtest_target,
        generation_metadata,
    )
    generation_path = _generation_pointer_path(output_root)
    before: dict[str, bytes | None] = {}
    before_generation: bytes | None = None
    generation_snapshot_captured = False
    written: list[tuple[Path, bytes | None]] = []
    try:
        with owned_interprocess_lock(output_root / ".a_formula_publish", timeout_seconds=5.0, timeout_message="A formula pointer publish lock timeout"):
            before = {"selector": _read_pointer_bytes(selector_pointer), "backtest": _read_pointer_bytes(backtest_pointer)}
            before_generation = _read_pointer_bytes(generation_path)
            generation_snapshot_captured = True
            # The one-file commit is the authority.  SafeRoot writes a fully
            # fsynced temporary file and atomically replaces this document;
            # legacy text pointers are updated only as compatibility views.
            SafeRoot(output_root).write_bytes(FORMULA_GENERATION_POINTER_NAME, generation_raw)
            if _read_pointer_bytes(generation_path) != generation_raw:
                raise AuthorityError("generation pointer readback mismatch")
            for pointer, target, name in ((selector_pointer, selector_target, "selector"), (backtest_pointer, backtest_target, "backtest")):
                old = _read_pointer_bytes(pointer)
                SafeRoot(pointer.parent).write_bytes(pointer.name, _pointer_target_bytes(_resolved(target)))
                written.append((pointer, old))
            after = {"selector": _read_pointer_bytes(selector_pointer), "backtest": _read_pointer_bytes(backtest_pointer)}
            expected = {
                "selector": _pointer_target_bytes(_resolved(selector_target)),
                "backtest": _pointer_target_bytes(_resolved(backtest_target)),
            }
            if any(after[name] != expected[name] for name in expected):
                raise AuthorityError("legacy pointer projection readback mismatch")
    except Exception:
        for pointer, old in reversed(written):
            try:
                if old is None:
                    if pointer.exists() and not pointer.is_symlink():
                        pointer.unlink()
                else:
                    SafeRoot(pointer.parent).write_bytes(pointer.name, old)
            except Exception:
                pass
        if generation_snapshot_captured:
            try:
                if before_generation is None:
                    if generation_path.exists() and not generation_path.is_symlink():
                        generation_path.unlink()
                else:
                    SafeRoot(output_root).write_bytes(FORMULA_GENERATION_POINTER_NAME, before_generation)
            except Exception:
                pass
        raise
    return {
        "before": {name: _generation_evidence(raw) for name, raw in before.items()},
        "after": {name: _generation_evidence(raw) for name, raw in after.items()},
        "generation_pointer": {
            "path": str(generation_path),
            "schema": FORMULA_GENERATION_SCHEMA,
            "generation_id": generation["generation_id"],
            "sha256": _sha256_bytes(generation_raw),
            "bytes": len(generation_raw),
            "selector": generation["selector"],
            "backtest": generation["backtest"],
        },
        "legacy_projection": True,
        "atomic_generation_commit": True,
    }


def _write_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    SafeRoot(path.parent).write_bytes(path.name, (json.dumps(_jsonable(dict(payload)), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def _run_success(
    *,
    target_date: int,
    input_root: Path,
    input_manifest: Path,
    data_root: Path,
    return_root: Path,
    selector_pointer: Path,
    backtest_pointer: Path,
    selector_seed: Path,
    backtest_seed: Path,
    contract_csv: Path,
    legacy_formula_source: str | None = None,
) -> dict[str, Any]:
    output_root = _safe_output_root(data_root, return_root, selector_pointer, backtest_pointer)
    input_frame, manifest = _load_input_manifest(input_root, input_manifest, target_date)
    contract_rows = load_authoritative_contract_rows(contract_csv)
    policy = build_contract_policy(contract_rows, contract_csv)
    selector_current = _read_seed(selector_seed, "selector")
    backtest_current = _read_seed(backtest_seed, "backtest")
    source_seed_sha = sha256_file(_resolved(selector_seed))
    backtest_seed_sha = sha256_file(_resolved(backtest_seed))
    history = collect_increment_history(input_frame)
    features = compute_formula_features(history)
    features = _backfill_increment_contract_columns(
        features,
        selector_current,
        backtest_current,
    )
    contract_version = str(policy["contract_version"])
    features["field_contract_version"] = contract_version
    boundary = _audit_increment_boundary(selector_current, select_generated_increment_rows(features, selector_current))
    if boundary["status"] != "PASS":
        raise AuthorityError(f"increment boundary failed: {boundary}")
    selector_increment = filter_increment_rows(features, selector_current, role="selector")
    backtest_increment = filter_increment_rows(features, backtest_current, role="backtest")
    if selector_increment.empty or backtest_increment.empty:
        if selector_increment.empty and backtest_increment.empty:
            selector_max = int(selector_current["trade_date"].max()) if not selector_current.empty else 0
            backtest_max = int(backtest_current["trade_date"].max()) if not backtest_current.empty else 0
            if selector_max >= target_date and backtest_max >= target_date:
                selector_history_gate = _audit_existing_history(
                    selector_current,
                    selector_current,
                    role="selector_history",
                    target_date=target_date,
                    seed_sha256=source_seed_sha,
                )
                backtest_history_gate = _audit_existing_history(
                    backtest_current,
                    backtest_current,
                    role="backtest_history",
                    target_date=target_date,
                    seed_sha256=backtest_seed_sha,
                )
                return {
                    "status": "READY",
                    "already_current": True,
                    "target_date": target_date,
                    "run_id": str(manifest["run_id"]),
                    "selector_pointer_ready": selector_pointer.exists(),
                    "backtest_pointer_ready": backtest_pointer.exists(),
                    "source_panel_sha256": source_seed_sha,
                    "input_manifest_sha256": str(manifest["manifest_sha256"]),
                    "contract_sha256": sha256_file(contract_csv),
                    "formula_source_sha256": FORMULA_ORIGIN_SHA256,
                    "historical_seed_health": _historical_seed_health(selector_history_gate, backtest_history_gate),
                    "gates": {
                        "selector_history": selector_history_gate,
                        "backtest_history": backtest_history_gate,
                    },
                    "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT",
                    **SAFETY_FLAGS,
                }
        raise AuthorityError("selector/backtest increments do not both contain target rows")
    if not (selector_increment["trade_date"] == target_date).any() or not (backtest_increment["trade_date"] == target_date).any():
        raise AuthorityError("selector/backtest increment target-date coverage failed")
    selector_source = _append_rows(selector_current, selector_increment, role="selector")
    backtest_source = _append_rows(backtest_current, backtest_increment, role="backtest")
    validate_new_selector_rows(selector_increment, target_date, role="selector_increment")
    validate_new_selector_rows(backtest_increment, target_date, role="backtest_increment")
    selector_source_gate = _audit_existing_history(
        selector_current,
        selector_source,
        role="selector_history",
        target_date=target_date,
        seed_sha256=source_seed_sha,
    )
    backtest_source_gate = _audit_existing_history(
        backtest_current,
        backtest_source,
        role="backtest_history",
        target_date=target_date,
        seed_sha256=backtest_seed_sha,
    )
    historical_seed_health = _historical_seed_health(selector_source_gate, backtest_source_gate)
    selector_official = build_official_selector_frame(selector_source, policy)
    selector_sidecar = build_sidecar_frame(selector_source, policy)
    official_key_sha = _key_sha256(selector_official)
    sidecar_key_sha = _key_sha256(selector_sidecar)
    if len(selector_official) != len(selector_sidecar) or official_key_sha != sidecar_key_sha:
        raise AuthorityError("official selector and sidecar key sets differ")
    official_gate = {
        "status": "PASS",
        "column_count": int(len(selector_official.columns)),
        "row_count": int(len(selector_official)),
        "target_rows": int((selector_official["trade_date"] == target_date).sum()),
        "sidecar_column_count": int(len(selector_sidecar.columns) - len(KEY_COLUMNS)),
    }
    if official_gate["target_rows"] < 1 or official_gate["sidecar_column_count"] != 12:
        raise AuthorityError("official selector/sidecar projection gate failed")
    run_id = str(manifest["run_id"])
    run_dir = _resolved(return_root) / f"a_formula_{target_date}_{run_id}"
    if run_dir.exists():
        raise AuthorityError(f"run output already exists; refusing overwrite: {run_dir}")
    run_dir.mkdir(parents=True, mode=0o700)
    if _path_has_symlink(run_dir, stop=output_root):
        raise AuthorityError("run output directory is symlinked")
    source_path = run_dir / "selector_source.parquet"
    official_path = run_dir / "selector_official.parquet"
    sidecar_path = run_dir / "selector_aux_sidecar.parquet"
    backtest_path = run_dir / "backtest_candidate.parquet"
    _atomic_parquet(selector_source, source_path)
    _atomic_parquet(selector_official, official_path)
    _atomic_parquet(selector_sidecar, sidecar_path)
    _atomic_parquet(backtest_source, backtest_path)
    for role, path in (("selector_source", source_path), ("selector_official", official_path), ("selector_sidecar", sidecar_path), ("backtest", backtest_path)):
        if not path.is_file() or _path_has_symlink(path, stop=run_dir):
            raise AuthorityError(f"{role} artifact missing/unsafe after write")
    generation_source, owned_manifest, owned_receipt = _prepare_generation_owned_evidence(
        run_dir,
        manifest,
        target_date=target_date,
    )
    generation_metadata = {
        "target_date": target_date,
        "run_id": run_id,
        "source": {
            **generation_source,
            "sha256": str(manifest["source_sha256"]),
        },
        "input_manifest": {
            "path": owned_manifest["path"],
            "bytes": owned_manifest["bytes"],
            # ``sha256`` is the byte digest of the JSON file.  Keep the
            # manifest's internal canonical digest separate so consumers do
            # not confuse the two provenance layers.
            "sha256": owned_manifest["sha256"],
            "manifest_sha256": str(manifest["manifest_sha256"]),
        },
        "selector_source": _generation_target_metadata(source_path, output_root, "selector_source"),
        "selector_sidecar": _generation_target_metadata(sidecar_path, output_root, "selector_sidecar"),
    }
    pointer_txn = _write_pointer_pair(
        selector_pointer,
        backtest_pointer,
        official_path,
        backtest_path,
        output_root,
        generation_metadata,
    )
    receipt_path = run_dir / "authority-receipt.json"
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "status": "READY",
        "target_date": target_date,
        "market": "A",
        "run_id": run_id,
        "source": manifest["source"],
        "source_sha256": manifest["source_sha256"],
        "input_manifest": str(input_manifest),
        "input_manifest_sha256": manifest["manifest_sha256"],
        "input_source_files": manifest["_source_files_sha256"],
        "input_rows": int(len(input_frame)),
        "input_symbols": int(input_frame["ts_code"].nunique()),
        "history_tail_records": TAIL_RECORDS,
        "source_seed_sha256": source_seed_sha,
        "backtest_seed_sha256": backtest_seed_sha,
        "formula_source": FORMULA_SOURCE,
        "formula_version": FORMULA_VERSION,
        "formula_source_sha256": FORMULA_ORIGIN_SHA256,
        "increment_origin_sha256": INCREMENT_ORIGIN_SHA256,
        "contract_sha256": sha256_file(contract_csv),
        "contract_origin_sha256": CONTRACT_ORIGIN_SHA256,
        "contract_version": contract_version,
        "contract_counts": {"rows": 199, "official_current": 187, "sidecar": 12},
        "coverage": {"selector_source_rows": int(len(selector_source)), "selector_official_rows": int(len(selector_official)), "target_rows": int((selector_official["trade_date"] == target_date).sum()), "symbols": int(selector_official["ts_code"].nunique())},
        "historical_seed_health": historical_seed_health,
        "gates": {"increment_boundary": boundary, "selector_source": selector_source_gate, "backtest_source": backtest_source_gate, "official_projection": official_gate, "sidecar_keys": {"status": "PASS", "rows": int(len(selector_sidecar)), "key_count": int(len(selector_sidecar)), "key_sha256": sidecar_key_sha, "source_key_sha256": official_key_sha, "columns": list(selector_sidecar.columns)}, "existing_207_column_contract": {"status": "RECORDED_FAIL_SOFT", "reason": "historical source schema may retain review/sidecar fields; official projection is separately gated"}},
        "sidecar_binding": {"status": "PASS", "market": "A", "target_date": target_date, "run_id": run_id, "input_manifest_sha256": manifest["manifest_sha256"], "source_panel_sha256": source_seed_sha, "key_count": int(len(selector_sidecar)), "key_sha256": sidecar_key_sha, "auxiliary_columns": list(policy["sidecar_columns"])},
        "artifacts": {role: {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for role, path in (("selector_source", source_path), ("selector_official", official_path), ("selector_aux_sidecar", sidecar_path), ("backtest", backtest_path))},
        "generation_owned_evidence": {
            "input_manifest": {key: owned_manifest[key] for key in ("path", "bytes", "sha256")},
            "sync_receipt": {key: owned_receipt[key] for key in ("path", "bytes", "sha256")},
        },
        "pointers": pointer_txn,
        "legacy_formula_source_recorded": str(legacy_formula_source or ""),
        "process": {"worker_mode": "serial", "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT", "network": "NOT_USED"},
        **SAFETY_FLAGS,
    }
    _write_receipt(receipt_path, payload)
    payload["receipt_path"] = str(receipt_path)
    payload["receipt_sha256"] = sha256_file(receipt_path)
    payload["receipt_bytes"] = receipt_path.stat().st_size
    return payload


def run_increment_authority(
    *,
    target_date: str | int,
    input_root: Path | str,
    input_manifest: Path | str,
    data_root: Path | str,
    return_root: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    selector_seed: Path | str,
    backtest_seed: Path | str,
    contract_csv: Path | str,
    legacy_formula_source: str | None = None,
) -> dict[str, Any]:
    target = 0
    try:
        target = int(str(target_date).replace("-", ""))
    except (TypeError, ValueError) as error:
        return {
            "schema": SCHEMA_VERSION,
            "status": "FAILED",
            "target_date": str(target_date),
            "run_id": "unknown",
            "error_type": type(error).__name__,
            "error": f"invalid target_date: {target_date}",
            "pointers_unchanged": True,
            "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT",
            "network": "NOT_USED",
            **SAFETY_FLAGS,
        }
    raw_return_root = Path(return_root).expanduser()
    return_path = _resolved(raw_return_root)
    run_id = "unknown"
    safe_output = False
    try:
        # Preflight all output ancestry before creating a failure receipt. A
        # caller cannot turn the formal release/state tree into a receipt sink
        # merely by sending an invalid manifest.
        _safe_output_root(
            Path(data_root).expanduser(),
            raw_return_root,
            Path(selector_pointer).expanduser(),
            Path(backtest_pointer).expanduser(),
        )
        safe_output = True
        return_path.mkdir(parents=True, exist_ok=True)
        try:
            maybe_manifest = _read_json(_resolved(input_manifest))
            run_id = str(maybe_manifest.get("run_id", "unknown"))
        except Exception:
            pass
        return _run_success(
            target_date=target,
            input_root=Path(input_root).expanduser(),
            input_manifest=Path(input_manifest).expanduser(),
            data_root=Path(data_root).expanduser(),
            return_root=return_path,
            selector_pointer=Path(selector_pointer).expanduser(),
            backtest_pointer=Path(backtest_pointer).expanduser(),
            selector_seed=Path(selector_seed).expanduser(),
            backtest_seed=Path(backtest_seed).expanduser(),
            contract_csv=Path(contract_csv).expanduser(),
            legacy_formula_source=legacy_formula_source,
        )
    except Exception as error:
        payload = {
            "schema": SCHEMA_VERSION,
            "status": "FAILED",
            "target_date": target,
            "run_id": run_id,
            "error_type": type(error).__name__,
            "error": str(error),
            "pointers_unchanged": True,
            "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT",
            "network": "NOT_USED",
            **SAFETY_FLAGS,
        }
        receipt_path = return_path / f"a_formula_{target}_{run_id}-failure-receipt.json"
        if not safe_output:
            return payload
        try:
            _write_receipt(receipt_path, payload)
            payload["receipt_path"] = str(receipt_path)
            payload["receipt_sha256"] = sha256_file(receipt_path)
            payload["receipt_bytes"] = receipt_path.stat().st_size
        except Exception as receipt_error:
            payload["receipt_write_error"] = f"{type(receipt_error).__name__}: {receipt_error}"
        return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V4 A formula increment authority; explicit offline input only")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--input-manifest", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--return-root", required=True, type=Path)
    parser.add_argument("--selector-pointer", required=True, type=Path)
    parser.add_argument("--backtest-pointer", required=True, type=Path)
    parser.add_argument("--selector-seed", required=True, type=Path)
    parser.add_argument("--backtest-seed", required=True, type=Path)
    parser.add_argument("--contract-csv", required=True, type=Path)
    parser.add_argument("--legacy-formula-source", default="")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    outcome = run_increment_authority(
        target_date=args.target_date,
        input_root=args.input_root,
        input_manifest=args.input_manifest,
        data_root=args.data_root,
        return_root=args.return_root,
        selector_pointer=args.selector_pointer,
        backtest_pointer=args.backtest_pointer,
        selector_seed=args.selector_seed,
        backtest_seed=args.backtest_seed,
        contract_csv=args.contract_csv,
        legacy_formula_source=args.legacy_formula_source,
    )
    print(json.dumps(_jsonable(outcome), ensure_ascii=False, sort_keys=True))
    return 0 if outcome.get("status") == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
