# -*- coding: utf-8 -*-
"""Current selector_ready panel interface.

This module intentionally does not hardcode a parquet path. It reads
CURRENT_SELECTOR_READY_PANEL.txt at call time, so daily pointer updates are
picked up automatically.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Iterable, Optional, Sequence

POINTER_FILE = Path(__file__).resolve().parent / "CURRENT_SELECTOR_READY_PANEL.txt"
FORBIDDEN_FUTURE_PATTERNS = (
    "future", "fwd", "forward", "next_", "nextopen", "nextclose",
    "target", "label_", "winner", "posthoc", "max_future", "future_ret", "ret_future",
)
DEFAULT_REQUIRED_COLUMNS = (
    "trade_date", "ts_code", "name", "open", "high", "low", "close", "volume", "amount",
)
REQUIRED_BASE_COLUMNS = (
    "trade_date", "ts_code", "name", "market_type", "exchange",
    "open", "high", "low", "close", "volume", "amount",
)
REQUIRED_PRICEVOL_COLUMNS = (
    "pre_close", "pct_chg", "vol_ratio_60", "ma5", "ma10", "ma20",
    "high_20", "high_20_prev", "amount_ratio_20",
    "bar_close_pos", "amplitude_pct", "upper_shadow_pct", "lower_shadow_pct",
)
REQUIRED_SIGNAL_COLUMNS = (
    "B1", "B2", "B3", "BG", "BBI", "zge_white_line", "zge_yellow_line",
    "J", "macd_dif", "macd_dea", "macd_hist",
)
NAME_MISSING_TOKENS = {"", "nan", "none", "null", "--", "<na>", "na", "n/a"}
DEFAULT_TDX_HQ_HOST = "119.147.212.81"
DEFAULT_TDX_HQ_PORT = 7709
DEFAULT_TDX_EXHQ_HOST = "119.147.212.81"
DEFAULT_TDX_EXHQ_PORT = 7727
TDX_LOCAL_ROOT = Path(r"C:\new_tdx_mock")
TDX_VIPDOC_ROOT = TDX_LOCAL_ROOT / "vipdoc"
TDX_HQ_CACHE_ROOT = TDX_LOCAL_ROOT / "T0002" / "hq_cache"
TDX_CUSTOM_BLOCK_ROOT = TDX_LOCAL_ROOT / "T0002" / "blocknew"
TDX_BLOCK_FILES = {
    "default": "block.dat",
    "index": "block_zs.dat",
    "style": "block_fg.dat",
    "concept": "block_gn.dat",
}
FUTU_QFQ_PROFILE_ID = "FUTU_QFQ_ASOF"
FUTU_QFQ_PROFILE_DIR = (
    Path(__file__).resolve().parents[3]
    / "research_panel_daily" / "formula_profiles" / "futu_qfq"
)
_FUTU_PROJECTION_MODULE = None


def _load_futu_projection_module():
    """Load the colocated offline projection helper without changing sys.path."""
    global _FUTU_PROJECTION_MODULE
    if _FUTU_PROJECTION_MODULE is not None:
        return _FUTU_PROJECTION_MODULE
    import importlib.util
    import sys

    helper_path = Path(__file__).resolve().with_name("futu_formula_projection.py")
    if not helper_path.is_file():
        raise RuntimeError(f"FUTU_PROFILE_HELPER_MISSING: {helper_path}")
    module_name = "_v4_futu_formula_projection"
    module = sys.modules.get(module_name)
    if module is None or Path(getattr(module, "__file__", "")).resolve() != helper_path:
        spec = importlib.util.spec_from_file_location(module_name, helper_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"FUTU_PROFILE_HELPER_LOAD_FAILED: {helper_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
    _FUTU_PROJECTION_MODULE = module
    return module


def _read_pointer(pointer_file: Path = POINTER_FILE) -> Path:
    raw = pointer_file.read_bytes()
    text = raw.decode("utf-8-sig", errors="strict").strip().lstrip("\ufeff").strip().strip('"')
    if not text:
        raise RuntimeError(f"Empty selector_ready pointer: {pointer_file}")
    fixed = _repair_mojibake_path(text)
    if fixed is not None:
        return fixed
    path = Path(text)
    if not path.exists():
        fixed = _repair_mojibake_path(text)
        if fixed is not None:
            return fixed
    if not path.exists():
        raise FileNotFoundError(f"Selector_ready panel not found: {path}")
    return path


def _repair_mojibake_path(text: str) -> Optional[Path]:
    try:
        fixed_text = text.encode("cp936").decode("utf-8")
    except UnicodeError:
        return None
    fixed_path = Path(fixed_text)
    return fixed_path if fixed_path.exists() else None


def _resolve_panel_path(panel_path: Optional[str | Path] = None) -> Path:
    if panel_path is None:
        return _read_pointer()
    fixed = _repair_mojibake_path(str(panel_path))
    if fixed is not None:
        return fixed
    path = Path(panel_path)
    if not path.exists():
        raise FileNotFoundError(f"Selector_ready panel not found: {path}")
    return path


def _date_values(path: Path) -> list[int]:
    import pyarrow.parquet as pq

    arr = pq.read_table(path, columns=["trade_date"]).column("trade_date").to_pylist()
    vals = []
    for value in arr:
        if value is None:
            continue
        text = str(value).replace("-", "")[:8]
        if text.isdigit():
            vals.append(int(text))
    return vals


def _name_missing_mask(series):
    text = series.astype("string").str.strip().str.lower()
    return series.isna() | text.isin(NAME_MISSING_TOKENS)


def _trade_date_text(series):
    return series.astype("string").str.replace("-", "", regex=False).str[:8]


def get_current_selector_panel_path() -> str:
    return str(_read_pointer())


def get_current_panel_path() -> str:
    return get_current_selector_panel_path()


def get_selector_ready_path() -> str:
    return get_current_selector_panel_path()


def list_columns(panel_path: Optional[str | Path] = None) -> list[str]:
    import pyarrow.parquet as pq
    path = _resolve_panel_path(panel_path)
    return list(pq.ParquetFile(path).schema_arrow.names)


def _canonical_basis(path: Path, parquet_file=None) -> dict:
    """Read the same generation's saved contract; no network or price rewrite."""
    import pyarrow.parquet as pq
    pf = parquet_file or pq.ParquetFile(path)
    raw = (pf.schema_arrow.metadata or {}).get(b"a_share_qfq_contract_v1")
    if raw is None:
        return {"profile_id": "CANONICAL_CURRENT", "price_basis": "UNKNOWN_UNCERTIFIED",
                "volume_basis": "UNKNOWN_UNCERTIFIED", "price_adjustment_asof": None,
                "historical_pit_certified": False}
    try:
        contract = json.loads(raw)
        manifest_path = Path(contract["generation_manifest_path"])
        if not manifest_path.is_absolute():
            raise ValueError("manifest must be absolute")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        required = ("generation_id", "input_sha256", "snapshot_file_sha256", "asof_date", "price_basis", "volume_basis", "convention")
        if (contract.get("schema") != "a_share_qfq_panel_v1" or contract.get("price_basis") not in ("QFQ_ASOF", "MIXED_BY_MARKET")
                or any(not contract.get(key) or manifest.get(key) != contract[key] for key in required)
                or Path(manifest["candidates"]["selector"]).resolve() != path.resolve()):
            raise ValueError("generation identity conflict")
        if contract["price_basis"] == "MIXED_BY_MARKET":
            markets = contract.get("market_basis", {})
            if markets != manifest.get("market_basis") or markets.get("A", {}).get("price_basis") != "QFQ_ASOF":
                raise ValueError("market basis binding conflict")
        if contract.get("field_basis", {}) != manifest.get("field_basis", {}):
            raise ValueError("field basis binding conflict")
        # Cooperating CURRENT readers refuse the short two-file transition.
        if POINTER_FILE.is_file() and Path(POINTER_FILE.read_text(encoding="utf-8-sig").strip()).resolve() == path.resolve():
            data_root = POINTER_FILE.parent.parent
            journal = json.loads((data_root / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json").read_text())
            backtest_pointer = data_root / "backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt"
            backtest_path = Path(backtest_pointer.read_text(encoding="utf-8-sig").strip())
            backtest_raw = (pq.ParquetFile(backtest_path).schema_arrow.metadata or {}).get(b"a_share_qfq_contract_v1")
            backtest = json.loads(backtest_raw or b"{}")
            if journal.get("status") not in ("COMMITTED", "ROLLED_BACK", "ROLLED_BACK_AFTER_INTERRUPTION") or backtest.get("generation_id") != contract["generation_id"]:
                raise ValueError("paired CURRENT generation unavailable or publication pending")
        return {"profile_id": "CANONICAL_CURRENT", "price_basis": contract["price_basis"],
                "volume_basis": contract["volume_basis"], "market_basis": contract.get("market_basis", {}), "amount_basis": contract.get("amount_basis"),
                "price_adjustment_asof": str(contract["asof_date"]) if contract["price_basis"] == "QFQ_ASOF" else None,
                "a_share_price_adjustment_asof": str(contract["asof_date"]), "generation_id": contract["generation_id"],
                "price_provider": contract.get("price_provider"),
                "adjustment_provider_contract": contract.get("adjustment_provider_contract"),
                "adjustment_convention": contract["convention"], "manifest_path": str(manifest_path),
                "field_basis": contract.get("field_basis", {}),
                "quarantine_manifest_path": contract.get("quarantine_manifest_path"), "coverage": manifest.get("counts", {}),
                "adjustment_snapshot": contract.get("adjustment_snapshot"),
                "input_sha256": contract["input_sha256"], "historical_pit_certified": False}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError(f"CANNOT_CONFIRM_QFQ_GENERATION_BINDING: {path}: {exc}") from exc


def _raw_profile_gate(profile, basis: dict) -> None:
    if profile == "RAW" and basis["price_basis"] != "RAW_VERIFIED":
        raise ValueError(f"RAW_PROFILE_NOT_AVAILABLE_FOR_CURRENT_BASIS: {basis['price_basis']}")


def get_panel_meta(
    panel_path: Optional[str | Path] = None,
    include_dates: bool = True,
    profile: Optional[str] = None,
    asof: Optional[str] = None,
) -> dict:
    import pyarrow.parquet as pq
    if isinstance(panel_path, bool):
        include_dates = panel_path
        panel_path = None
    path = _resolve_panel_path(panel_path)
    pf = pq.ParquetFile(path)
    basis = _canonical_basis(path, pf)
    _raw_profile_gate(profile, basis)
    cols = list(pf.schema_arrow.names)
    future_cols = [c for c in cols if any(p in c.lower() for p in FORBIDDEN_FUTURE_PATTERNS)]
    meta = {
        "panel_role": "SELECTOR_READY_CURRENT",
        "path": str(path),
        "panel_path": str(path),
        "rows": pf.metadata.num_rows,
        "columns": len(cols),
        "cols": len(cols),
        "column_names": cols,
        "future_forbidden_columns": future_cols,
        "future_like_columns": future_cols,
        "future_like_count": len(future_cols),
        **basis,
        "read_profile": basis,
    }
    if include_dates and "trade_date" in cols:
        vals = _date_values(path)
        meta["trade_date_min"] = min(vals) if vals else None
        meta["trade_date_max"] = max(vals) if vals else None
        meta["latest_date"] = str(meta["trade_date_max"]) if meta["trade_date_max"] is not None else None
        meta["trade_date_count"] = len(set(vals)) if vals else 0
    if profile not in (None, "RAW"):
        if profile != FUTU_QFQ_PROFILE_ID:
            raise ValueError(f"UNSUPPORTED_SELECTOR_PROFILE: {profile}")
        projection = _load_futu_projection_module()
        bound = projection.validate_profile_for_panel(
            FUTU_QFQ_PROFILE_DIR, path, asof,
        )
        meta["read_profile"] = projection.profile_metadata(bound)
        meta["read_profile"]["legacy_chart_profile"] = True
    return meta


def get_panel_metadata(
    include_dates: bool = True,
    panel_path: Optional[str | Path] = None,
    profile: Optional[str] = None,
    asof: Optional[str] = None,
) -> dict:
    return get_panel_meta(
        panel_path=panel_path,
        include_dates=include_dates,
        profile=profile,
        asof=asof,
    )


def validate_required_columns(
    required_columns: Optional[Sequence[str]] = None,
    panel_path: Optional[str | Path] = None,
    raise_on_missing: bool = True,
) -> dict:
    required = list(required_columns or DEFAULT_REQUIRED_COLUMNS)
    cols = list_columns(panel_path=panel_path)
    missing = [c for c in required if c not in cols]
    result = {
        "ok": not missing,
        "panel_path": str(_resolve_panel_path(panel_path)),
        "exists": True,
        "column_count": len(cols),
        "required_columns": required,
        "missing_columns": missing,
        "present_columns": [c for c in required if c in cols],
        "missing_base": [c for c in REQUIRED_BASE_COLUMNS if c not in cols],
        "missing_pricevol": [c for c in REQUIRED_PRICEVOL_COLUMNS if c not in cols],
        "missing_signal": [c for c in REQUIRED_SIGNAL_COLUMNS if c not in cols],
    }
    if missing and raise_on_missing:
        raise RuntimeError(f"Selector panel missing required columns: {missing}")
    return result


def load_selector_ready(
    columns: Optional[Sequence[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ts_codes: Optional[Iterable[str]] = None,
    filters=None,
    panel_path: Optional[str | Path] = None,
    profile: Optional[str] = None,
    asof: Optional[str] = None,
):
    import pandas as pd
    path = _resolve_panel_path(panel_path)
    if profile not in (None, "RAW", FUTU_QFQ_PROFILE_ID):
        raise ValueError(f"UNSUPPORTED_SELECTOR_PROFILE: {profile}")
    if profile == FUTU_QFQ_PROFILE_ID:
        projection = _load_futu_projection_module()
        bound = projection.validate_profile_for_panel(
            FUTU_QFQ_PROFILE_DIR, path, asof,
        )
        result = projection.load_profile_rows(
            bound,
            columns=columns,
            start_date=start_date,
            end_date=end_date,
            ts_codes=ts_codes,
            filters=filters,
        )
        result.attrs["legacy_chart_profile"] = True
        return result
    basis = _canonical_basis(path)
    _raw_profile_gate(profile, basis)
    if columns is None:
        read_columns = None
    else:
        read_columns = list(dict.fromkeys(["trade_date", "ts_code", *columns]))
    df = pd.read_parquet(path, columns=read_columns, filters=filters)
    if start_date is not None:
        df = df[df["trade_date"].astype(str) >= str(start_date)]
    if end_date is not None:
        df = df[df["trade_date"].astype(str) <= str(end_date)]
    if ts_codes is not None:
        code_set = set(map(str, ts_codes))
        df = df[df["ts_code"].astype(str).isin(code_set)]
    df = df.reset_index(drop=True)
    if basis["price_basis"] == "MIXED_BY_MARKET" and not df.empty:
        import re
        scopes = {"A" if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", str(c)) else str(c).rsplit(".", 1)[-1]
                  for c in df.ts_code}
        if len(scopes) == 1:
            market = basis["market_basis"].get(next(iter(scopes)))
            if market is None:
                raise RuntimeError("CANNOT_CONFIRM_MARKET_BASIS")
            basis = dict(basis, price_basis=market["price_basis"], volume_basis=market["volume_basis"], amount_basis=market.get("amount_basis"),
                         price_adjustment_asof=str(market["asof_date"]) if market.get("asof_date") else None)
    df.attrs["panel_metadata"] = basis
    return df


def load_selector_panel(columns: Optional[Sequence[str]] = None, filters=None):
    return load_selector_ready(columns=columns, filters=filters)


def load_current_panel(columns: Optional[Sequence[str]] = None, filters=None):
    return load_selector_ready(columns=columns, filters=filters)


def read_panel(columns: Optional[Sequence[str]] = None, filters=None):
    return load_selector_ready(columns=columns, filters=filters)


def load_latest(
    columns: Optional[Sequence[str]] = None,
    panel_path: Optional[str | Path] = None,
):
    import pandas as pd

    path = _resolve_panel_path(panel_path)
    vals = _date_values(path)
    if not vals:
        raise RuntimeError("Selector panel has no valid trade_date values")
    latest = str(max(vals))
    load_cols = list(columns) if columns is not None else None
    return pd.read_parquet(path, columns=load_cols, filters=[("trade_date", "==", latest)])


def smoke_check(panel_path: Optional[str | Path] = None) -> dict:
    import pandas as pd

    path = _resolve_panel_path(panel_path)
    meta = get_panel_meta(panel_path=path, include_dates=True)
    required = validate_required_columns(panel_path=path, raise_on_missing=False)
    latest = meta.get("trade_date_max")
    latest_rows = 0
    name_missing_total_count = None
    latest_name_missing_count = None
    latest_core_name_missing_count = None
    latest_hk_connect_name_missing_count = None
    if "name" in meta["column_names"]:
        name_cols = ["trade_date", "name"]
        for optional_col in ("market_type", "exchange"):
            if optional_col in meta["column_names"]:
                name_cols.append(optional_col)
        name_df = pd.read_parquet(path, columns=name_cols)
        date_text = _trade_date_text(name_df["trade_date"])
        latest_mask = date_text == str(latest) if latest is not None else pd.Series(False, index=name_df.index)
        missing_mask = _name_missing_mask(name_df["name"])
        if "exchange" in name_df.columns:
            hk_connect_mask = name_df["exchange"].astype("string").str.upper().eq("HK_CONNECT")
        elif "market_type" in name_df.columns:
            hk_connect_mask = name_df["market_type"].astype("string").str.upper().eq("HK")
        else:
            hk_connect_mask = pd.Series(False, index=name_df.index)
        latest_rows = int(latest_mask.sum())
        name_missing_total_count = int(missing_mask.sum())
        latest_name_missing_count = int((missing_mask & latest_mask).sum())
        latest_hk_connect_name_missing_count = int((missing_mask & latest_mask & hk_connect_mask).sum())
        latest_core_name_missing_count = int((missing_mask & latest_mask & ~hk_connect_mask).sum())
    elif latest is not None:
        dates = pd.read_parquet(path, columns=["trade_date"])["trade_date"]
        latest_rows = int((_trade_date_text(dates) == str(latest)).sum())
    warnings = []
    if name_missing_total_count and name_missing_total_count > 0:
        warnings.append("historical_name_missing")
    if latest_hk_connect_name_missing_count and latest_hk_connect_name_missing_count > 0:
        warnings.append("latest_hk_connect_name_missing")
    name_gate_ok = latest_core_name_missing_count == 0
    ok = required["ok"] and not meta["future_like_columns"] and name_gate_ok
    return {
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "path": str(path),
        "panel_path": str(path),
        "rows": meta["rows"],
        "total_rows": meta["rows"],
        "cols": meta["cols"],
        "total_columns": meta["cols"],
        "trade_date_min": meta.get("trade_date_min"),
        "trade_date_max": latest,
        "latest_date": str(latest) if latest is not None else None,
        "trade_date_count": meta.get("trade_date_count"),
        "latest_rows": int(latest_rows),
        "name_blank_aware_missing_count": name_missing_total_count,
        "name_missing_total_count": name_missing_total_count,
        "latest_name_missing_count": latest_name_missing_count,
        "latest_core_name_missing_count": latest_core_name_missing_count,
        "latest_hk_connect_name_missing_count": latest_hk_connect_name_missing_count,
        "warnings": warnings,
        "future_like_count": meta["future_like_count"],
        "future_like_columns": meta["future_like_columns"],
        "required_columns": required,
        "schema_check": required,
    }


def assert_no_future_columns() -> bool:
    bad = get_panel_meta(include_dates=False)["future_forbidden_columns"]
    if bad:
        raise RuntimeError(f"Selector panel contains forbidden future-like columns: {bad}")
    return True


def get_tdx_local_paths() -> dict:
    return {
        "tdx_root": str(TDX_LOCAL_ROOT),
        "vipdoc": str(TDX_VIPDOC_ROOT),
        "sh_lday": str(TDX_VIPDOC_ROOT / "sh" / "lday"),
        "sz_lday": str(TDX_VIPDOC_ROOT / "sz" / "lday"),
        "bj_lday": str(TDX_VIPDOC_ROOT / "bj" / "lday"),
        "ds_lday": str(TDX_VIPDOC_ROOT / "ds" / "lday"),
        "hq_cache": str(TDX_HQ_CACHE_ROOT),
        "blocknew": str(TDX_CUSTOM_BLOCK_ROOT),
        "name_cache": str(TDX_HQ_CACHE_ROOT / "ds_stk.dat"),
    }


def _import_pytdx_hq():
    try:
        from pytdx.hq import TdxHq_API
    except Exception as exc:
        raise ImportError("pytdx.hq is not available. Install with: pip install pytdx") from exc
    return TdxHq_API


def _import_pytdx_exhq():
    try:
        from pytdx.exhq import TdxExHq_API
    except Exception as exc:
        raise ImportError("pytdx.exhq is not available. Install with: pip install pytdx") from exc
    return TdxExHq_API


def get_pytdx_classes() -> dict:
    reader_classes = get_pytdx_reader_classes()
    return {
        "TdxHq_API": _import_pytdx_hq(),
        "TdxExHq_API": _import_pytdx_exhq(),
        **reader_classes,
    }


def get_pytdx_reader_classes() -> dict:
    try:
        from pytdx.reader import (
            BlockReader,
            CustomerBlockReader,
            GbbqReader,
            HistoryFinancialReader,
            TdxDailyBarReader,
            TdxExHqDailyBarReader,
            TdxLCMinBarReader,
            TdxMinBarReader,
        )
    except Exception as exc:
        raise ImportError("pytdx.reader is not available. Install with: pip install pytdx") from exc
    return {
        "BlockReader": BlockReader,
        "CustomerBlockReader": CustomerBlockReader,
        "GbbqReader": GbbqReader,
        "HistoryFinancialReader": HistoryFinancialReader,
        "TdxDailyBarReader": TdxDailyBarReader,
        "TdxExHqDailyBarReader": TdxExHqDailyBarReader,
        "TdxLCMinBarReader": TdxLCMinBarReader,
        "TdxMinBarReader": TdxMinBarReader,
    }


def get_pytdx_method_inventory() -> dict:
    inventory = {}
    for name, cls in get_pytdx_classes().items():
        methods = []
        for attr in dir(cls):
            if attr.startswith("_"):
                continue
            value = getattr(cls, attr, None)
            if callable(value):
                methods.append(attr)
        inventory[name] = sorted(methods)
    return inventory


def create_tdx_hq_api(multithread: bool = True):
    return _import_pytdx_hq()(multithread=multithread)


def create_tdx_exhq_api():
    return _import_pytdx_exhq()()


def connect_tdx_hq(
    host: str = DEFAULT_TDX_HQ_HOST,
    port: int = DEFAULT_TDX_HQ_PORT,
    multithread: bool = True,
):
    api = create_tdx_hq_api(multithread=multithread)
    if not api.connect(host, int(port)):
        raise ConnectionError(f"pytdx TdxHq_API connect failed: {host}:{port}")
    return api


def connect_tdx_exhq(
    host: str = DEFAULT_TDX_EXHQ_HOST,
    port: int = DEFAULT_TDX_EXHQ_PORT,
):
    api = create_tdx_exhq_api()
    if not api.connect(host, int(port)):
        raise ConnectionError(f"pytdx TdxExHq_API connect failed: {host}:{port}")
    return api


@contextmanager
def tdx_hq_session(
    host: str = DEFAULT_TDX_HQ_HOST,
    port: int = DEFAULT_TDX_HQ_PORT,
    multithread: bool = True,
):
    api = connect_tdx_hq(host=host, port=port, multithread=multithread)
    try:
        yield api
    finally:
        api.disconnect()


@contextmanager
def tdx_exhq_session(
    host: str = DEFAULT_TDX_EXHQ_HOST,
    port: int = DEFAULT_TDX_EXHQ_PORT,
):
    api = connect_tdx_exhq(host=host, port=port)
    try:
        yield api
    finally:
        api.disconnect()


def fetch_tdx_security_bars(
    category: int,
    market: int,
    code: str,
    start: int = 0,
    count: int = 800,
    host: str = DEFAULT_TDX_HQ_HOST,
    port: int = DEFAULT_TDX_HQ_PORT,
    as_dataframe: bool = True,
):
    with tdx_hq_session(host=host, port=port) as api:
        rows = api.get_security_bars(int(category), int(market), str(code), int(start), int(count))
        return api.to_df(rows) if as_dataframe else rows


def fetch_tdx_daily_bars(
    market: int,
    code: str,
    start: int = 0,
    count: int = 800,
    host: str = DEFAULT_TDX_HQ_HOST,
    port: int = DEFAULT_TDX_HQ_PORT,
    as_dataframe: bool = True,
):
    return fetch_tdx_security_bars(
        category=9,
        market=market,
        code=code,
        start=start,
        count=count,
        host=host,
        port=port,
        as_dataframe=as_dataframe,
    )


def fetch_tdx_markets(
    host: str = DEFAULT_TDX_EXHQ_HOST,
    port: int = DEFAULT_TDX_EXHQ_PORT,
    as_dataframe: bool = True,
):
    with tdx_exhq_session(host=host, port=port) as api:
        rows = api.get_markets()
        return api.to_df(rows) if as_dataframe else rows


def _tdx_block_result_type(result_type: str | int) -> int:
    from pytdx.reader.block_reader import BlockReader_TYPE_FLAT, BlockReader_TYPE_GROUP

    if isinstance(result_type, int):
        return result_type
    value = str(result_type).strip().lower()
    if value in {"flat", "row", "rows", "detail", "details"}:
        return BlockReader_TYPE_FLAT
    if value in {"group", "groups", "summary"}:
        return BlockReader_TYPE_GROUP
    raise ValueError("result_type must be flat/details or group/summary")


def _group_block_frame(df):
    import pandas as pd

    if df.empty or "blockname" not in df.columns or "code" not in df.columns:
        return df
    grouped = (
        df.groupby(["blockname", "block_type"], dropna=False)["code"]
        .apply(lambda x: ",".join(str(v) for v in x if str(v)))
        .reset_index(name="code_list")
    )
    grouped["stock_count"] = grouped["code_list"].apply(lambda x: 0 if not x else len(x.split(",")))
    return grouped[["blockname", "block_type", "stock_count", "code_list"]]


def list_tdx_block_file_names() -> dict:
    return dict(TDX_BLOCK_FILES)


def list_tdx_local_block_files() -> list[dict]:
    roots = [TDX_HQ_CACHE_ROOT, TDX_CUSTOM_BLOCK_ROOT]
    rows = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*block*.dat")):
            rows.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "size_bytes": path.stat().st_size,
                    "mtime": path.stat().st_mtime,
                    "pytdx_block_reader_supported": path.name in set(TDX_BLOCK_FILES.values()),
                }
            )
    return rows


def resolve_tdx_block_file(block_file: str | Path) -> Path:
    path = Path(block_file)
    if path.exists():
        return path
    if not path.is_absolute():
        for root in [TDX_HQ_CACHE_ROOT, TDX_CUSTOM_BLOCK_ROOT, TDX_LOCAL_ROOT]:
            candidate = root / path
            if candidate.exists():
                return candidate
    raise FileNotFoundError(f"TDX block file not found locally: {block_file}")


def read_tdx_local_block_file(
    block_file: str | Path,
    result_type: str | int = "flat",
):
    from pytdx.reader import BlockReader

    path = resolve_tdx_block_file(block_file)
    return BlockReader().get_df(str(path), _tdx_block_result_type(result_type))


def read_tdx_custom_blocks(
    blocknew_dir: str | Path = TDX_CUSTOM_BLOCK_ROOT,
    result_type: str | int = "flat",
):
    from pytdx.reader import CustomerBlockReader

    path = Path(blocknew_dir)
    if not path.exists():
        raise FileNotFoundError(f"TDX custom block directory not found: {path}")
    return CustomerBlockReader().get_df(str(path), _tdx_block_result_type(result_type))


def list_tdx_custom_block_groups(blocknew_dir: str | Path = TDX_CUSTOM_BLOCK_ROOT):
    return read_tdx_custom_blocks(blocknew_dir=blocknew_dir, result_type="group")


def get_tdx_custom_block_codes(
    blockname: Optional[str] = None,
    block_type: Optional[str] = None,
    blocknew_dir: str | Path = TDX_CUSTOM_BLOCK_ROOT,
) -> list[str]:
    df = read_tdx_custom_blocks(blocknew_dir=blocknew_dir, result_type="flat")
    if blockname is not None:
        df = df[df["blockname"].astype(str) == str(blockname)]
    if block_type is not None:
        df = df[df["block_type"].astype(str) == str(block_type)]
    if "code" not in df.columns:
        return []
    return [str(x) for x in df["code"].dropna().tolist()]


def fetch_tdx_block_info(
    block_file: str = TDX_BLOCK_FILES["concept"],
    result_type: str | int = "flat",
    host: str = DEFAULT_TDX_HQ_HOST,
    port: int = DEFAULT_TDX_HQ_PORT,
):
    import pandas as pd

    with tdx_hq_session(host=host, port=port) as api:
        rows = api.get_and_parse_block_info(str(block_file))
    df = pd.DataFrame(rows)
    if _tdx_block_result_type(result_type) == _tdx_block_result_type("group"):
        return _group_block_frame(df)
    return df


def fetch_tdx_block_groups(
    block_file: str = TDX_BLOCK_FILES["concept"],
    host: str = DEFAULT_TDX_HQ_HOST,
    port: int = DEFAULT_TDX_HQ_PORT,
):
    return fetch_tdx_block_info(block_file=block_file, result_type="group", host=host, port=port)


def search_tdx_block_groups(
    keyword: str,
    source: str = "custom",
    block_file: str = TDX_BLOCK_FILES["concept"],
):
    source_value = str(source).strip().lower()
    if source_value == "custom":
        df = list_tdx_custom_block_groups()
    elif source_value == "online":
        df = fetch_tdx_block_groups(block_file=block_file)
    elif source_value == "local":
        df = read_tdx_local_block_file(block_file=block_file, result_type="group")
    else:
        raise ValueError("source must be custom, online, or local")
    if "blockname" not in df.columns:
        return df
    return df[df["blockname"].astype(str).str.contains(str(keyword), case=False, na=False)].reset_index(drop=True)


if __name__ == "__main__":
    import json
    print(json.dumps(get_panel_metadata(include_dates=True), ensure_ascii=False, indent=2))
