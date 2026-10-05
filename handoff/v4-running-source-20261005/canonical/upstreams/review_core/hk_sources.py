"""Trusted shared-data loaders and normalizers for HK close review."""
from __future__ import annotations

import csv
import hashlib
import importlib
import inspect
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:
    from .pool_store import StoreError
except ImportError:  # direct focused invocation from review_core/
    from pool_store import StoreError

HK_02_ROLE = "HK_CONNECT_D1_TOP100_0_2"
STAGE_IDS = (
    "STAGE_0925",
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
    "STAGE_0945_1030",
    "STAGE_1300_1315",
    "STAGE_1445_1500",
    "STAGE_1545_1555",
)
STAGE_ROLES = (
    "HK_CONNECT_AUCTION_REFERENCE_STAGE_0925",
    *(f"HK_CONNECT_1MIN_{item}" for item in STAGE_IDS[1:]),
)
CODE_RE = re.compile(r"^HK\.(\d{1,5})$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

def normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.endswith(".HK"):
        text = f"HK.{text[:-3]}"
    elif not text.startswith("HK."):
        text = f"HK.{''.join(c for c in text if c.isdigit())}"
    match = CODE_RE.fullmatch(text)
    return f"HK.{int(match.group(1)):05d}" if match else ""

def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError): return None
    return result if math.isfinite(result) else None

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError as error:
        raise StoreError(f"evidence file cannot be read: {path}") from error
    return digest.hexdigest()

def read_json_file(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error: raise StoreError(f"close snapshot cannot be read: {path}") from error
    if not isinstance(payload, Mapping):
        raise StoreError("close snapshot must be an object")
    return dict(payload), sha256_file(path)

def resolve_shared_root(value: Path | str | None) -> Path | None:
    if value is not None:
        return Path(value)
    for name in ("V3_SHARED_DATA_STORE_ROOT", "V3_SHARED_DATA_ROOT", "HK_REVIEW_SHARED_ROOT"):
        if os.environ.get(name):
            return Path(os.environ[name])
    sibling = Path(__file__).resolve().parent.parent / "v3_shared_data"
    return sibling if sibling.is_dir() else None

def import_shared(module_name: str) -> Any:
    configured = os.environ.get("V3_SHARED_DATA_PACKAGE_ROOT")
    trusted_root = Path(configured) if configured else Path(__file__).resolve().parent.parent / "v3_shared_data"
    trusted_root = trusted_root.resolve()

    def checked(module: Any) -> Any:
        module_file = getattr(module, "__file__", None)
        if not module_file:
            raise StoreError("trusted shared package module has no file")
        try:
            Path(module_file).resolve().relative_to(trusted_root)
        except ValueError as error:
            raise StoreError(f"trusted shared package path mismatch: {module_file}") from error
        return module
    try:
        return checked(importlib.import_module(module_name))
    except ModuleNotFoundError as first_error:
        if trusted_root.is_dir() and str(trusted_root) not in sys.path:
            sys.path.insert(0, str(trusted_root))
        try:
            return checked(importlib.import_module(module_name))
        except ModuleNotFoundError as error:
            raise StoreError(f"trusted shared package unavailable: {module_name}") from first_error

def call_loader(
    loader: Callable[..., Any],
    candidates: Iterable[tuple[tuple[Any, ...], dict[str, Any]]],
) -> Any:
    try:
        signature = inspect.signature(loader)
    except (TypeError, ValueError):
        signature = None
    for args, kwargs in candidates:
        if signature is not None:
            try:
                signature.bind(*args, **kwargs)
            except TypeError:
                continue
        return loader(*args, **kwargs)
    raise StoreError("loader signature unsupported")

def default_model_loader(root: Path | None, target_date: str, signal_date: str) -> Any:
    if root is None: raise StoreError("shared HK 0.2 root unavailable")
    module = import_shared("shared_data.hk_0_2")
    return module.read_verified_hk_0_2_pool(
        root, target_date=target_date, expected_signal_date=signal_date
    )

def default_stage_loader(root: Path | None, trade_date: str, role: str) -> Any:
    if root is None: raise StoreError("shared stage root unavailable")
    module = import_shared("shared_data.consumer")
    return module.read_verified_latest(root, trade_date, role)

def default_close_loader(root: Path | None, trade_date: str) -> tuple[dict[str, Any], str]:
    if root is None: raise StoreError("close root unavailable")
    candidates = (
        root / "hkconnect_close_snapshots" / f"{trade_date}.json",
        root / "close_snapshots" / f"{trade_date}.json",
        root / "close" / f"{trade_date}.json",
    )
    for path in candidates:
        if path.is_file():
            return read_json_file(path)
    raise FileNotFoundError(f"exact close snapshot missing: {trade_date}")

def extract_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        rows = value.get("rows")
        path = value.get("artifact_path")
    else:
        rows = getattr(value, "rows", None)
        path = getattr(value, "artifact_path", None)
    if isinstance(rows, list) or isinstance(rows, tuple):
        return [dict(row) for row in rows if isinstance(row, Mapping)]
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if isinstance(path, (str, Path)):
        try:
            with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except OSError as error:
            raise StoreError(f"artifact cannot be read: {path}") from error
    return []

def source_metadata(value: Any, role: str) -> dict[str, Any]:
    run = value.get("run") if isinstance(value, Mapping) else getattr(value, "run", None)
    run = run or (value.get("verified") if isinstance(value, Mapping) else None) or value

    def get(name: str) -> str:
        nested_names = ("verification", "manifest", "receipt", "latest")
        nested = (
            [run.get(key) for key in nested_names]
            if isinstance(run, Mapping)
            else [getattr(run, key, None) for key in nested_names]
        )
        for item in [run, *nested]:
            if isinstance(item, Mapping) and item.get(name) not in (None, ""):
                return str(item[name])
            if not isinstance(item, Mapping) and getattr(item, name, None) not in (None, ""):
                return str(getattr(item, name))
        return ""
    return {
        "role": get("role") or role,
        "run_id": get("run_id"),
        "artifact_sha256": get("artifact_sha256"),
        "manifest_sha256": get("manifest_sha256"),
        "receipt_sha256": get("receipt_sha256"),
    }

def unwrap_close(value: Any) -> tuple[dict[str, Any], str]:
    if isinstance(value, (str, Path)):
        return read_json_file(Path(value))
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], Mapping):
        return dict(value[0]), str(value[1])
    if isinstance(value, Mapping):
        payload = dict(value.get("payload")) if isinstance(value.get("payload"), Mapping) else dict(value)
        digest = payload.get("file_sha256") or payload.get("source_file_sha256") or payload.get("source_input_sha256") or payload.get("source_sha256") or value.get("sha256") or ""
        return payload, str(digest)
    raise StoreError("close loader returned unsupported value")

def normalize_model(
    value: Any, trade_date: str
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    metadata = source_metadata(value, HK_02_ROLE)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in extract_rows(value):
        if str(source.get("target_date") or source.get("trade_date") or "") != trade_date:
            return [], metadata, "date_mismatch"
        code = normalize_code(source.get("code_norm") or source.get("code") or source.get("symbol"))
        if not code or code in seen:
            return [], metadata, "invalid_or_duplicate_code"
        seen.add(code)
        rank = number(source.get("rank") or source.get("pool_rank"))
        result.append(
            {
                **source,
                "rank": int(rank) if rank and rank > 0 else len(result) + 1,
                "code": code,
                "name": str(source.get("name") or source.get("stock_name") or "").strip(),
                "trade_date": trade_date,
                "target_date": trade_date,
                "source": "HK_0_2",
                "pool_role": HK_02_ROLE,
            }
        )
    result.sort(key=lambda row: (row["rank"], row["code"]))
    if len(result) != 100:
        return result[:100], metadata, f"row_count:{len(result)}/100"
    for rank, row in enumerate(result, 1):
        row["rank"] = rank
    return result, metadata, None


def normalize_stage(
    value: Any, trade_date: str, role: str
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    metadata = source_metadata(value, role)
    stage_id = (
        "STAGE_0925"
        if role == "HK_CONNECT_AUCTION_REFERENCE_STAGE_0925"
        else role.removeprefix("HK_CONNECT_1MIN_")
    )
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    selected_count = 0
    for source in extract_rows(value):
        selected = _selection_state(source)
        if selected is not True:
            continue
        selected_count += 1
        row_date = str(source.get("trade_date") or source.get("trade_date_compact") or "")
        if row_date and row_date != trade_date:
            return [], metadata, "date_mismatch"
        code = normalize_code(source.get("code") or source.get("code_norm") or source.get("symbol"))
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(
            {
                **source,
                "stage_id": stage_id,
                "stage_role": role,
                "stage_rank": len(result) + 1,
                "stage_selected": True,
                "code": code,
                "name": str(source.get("name") or source.get("stock_name") or "").strip(),
                "trade_date": trade_date,
                "source": "SHARED_STAGE",
            }
        )
    if selected_count == 0:
        return [], metadata, "selection_evidence_missing"
    return result, metadata, None


def _selection_state(source: Mapping[str, Any]) -> bool | None:
    for key in ("stage_selected", "selected", "is_selected"):
        if key in source:
            value = source[key]
            return value if isinstance(value, bool) else None
    status = str(source.get("selection_status") or "").strip().upper()
    if status in {"SELECTED", "STAGE_SELECTED"}:
        return True
    if status in {"UNSELECTED", "NOT_SELECTED", "RAW"}:
        return False
    return None


def normalize_close(
    payload: Mapping[str, Any], digest: str, trade_date: str
) -> tuple[list[dict[str, Any]], int, str | None]:
    if payload.get("schema_version") != "v3_5.hkconnect_close_snapshot.v1":
        return [], 0, "schema_mismatch"
    if str(payload.get("trade_date") or "") != trade_date:
        return [], 0, "trade_date_mismatch"
    if any(payload.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return [], 0, "unsafe_flags"
    if not SHA_RE.fullmatch(str(digest).lower()):
        return [], 0, "file_sha_missing"
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return [], 0, "rows_missing"
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in rows:
        if not isinstance(source, Mapping):
            return [], 0, "invalid_row"
        if str(source.get("trade_date") or source.get("trade_date_compact") or "") != trade_date:
            return [], 0, "cross_date_or_invalid_row"
        code = normalize_code(source.get("code") or source.get("code_norm") or source.get("symbol"))
        close = number(source.get("close") or source.get("last_price"))
        previous = number(source.get("pre_close") or source.get("prev_close") or source.get("prev_close_price"))
        if not code or code in seen or close is None or previous in (None, 0.0):
            return [], 0, "invalid_or_duplicate_row"
        seen.add(code)
        pct = number(source.get("pct_chg") or source.get("pct_chg_close"))
        pct = pct if pct is not None else (close / previous - 1) * 100
        result.append(
            {
                **dict(source),
                "trade_date": trade_date,
                "code": code,
                "name": str(source.get("name") or source.get("stock_name") or "").strip(),
                "close": close,
                "pre_close": previous,
                "pct_chg": pct,
                "pct_chg_close": pct,
                "amount": number(source.get("amount") or source.get("turnover")) or 0.0,
            }
        )
    result.sort(key=lambda row: (-row["pct_chg"], row["code"]))
    top20 = [{**row, "rank": rank} for rank, row in enumerate(result[:20], 1)]
    error = None if len(top20) == 20 else f"top20:{len(top20)}/20"
    return top20, len(result), error
