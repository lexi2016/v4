"""Next-day raw daily bar & adjustment factor ingestion entry point (--step ingest)."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from v4_core.ingest.a_share_tdx import ingest_a_share_bars, parse_tdx_day_bytes
from v4_core.ingest.hk_daily import ingest_hk_bars
from v4_core.storage.db import V4Store, normalize_symbol

_TDX_FILENAME_RE = re.compile(r"^(sh|sz|bj)(\d{6})\.day$", re.IGNORECASE)


def discover_tdx_day_files(tdx_dir: Path) -> list[tuple[str, Path]]:
    """Discover standard TDX .day files under tdx_dir (flat or sh/sz/bj subdirectories)."""
    root = Path(tdx_dir)
    if not root.exists():
        return []
    found: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*.day")):
        m = _TDX_FILENAME_RE.match(path.name)
        if not m:
            continue
        exch, code = m.group(1).upper(), m.group(2)
        found.append((f"{code}.{exch}", path))
    return found


def ingest_from_tdx_dir(
    store: V4Store,
    trade_date: str,
    tdx_dir: Path,
    *,
    verified_exclusions: set[str] | None = None,
) -> dict[str, Any]:
    """Parse 32-byte TDX .day files and ingest target trade_date (plus any earlier prefix bars)."""
    files = discover_tdx_day_files(tdx_dir)
    target_rows: list[dict[str, Any]] = []
    prefix_rows: list[dict[str, Any]] = []
    for symbol, path in files:
        parsed = parse_tdx_day_bytes(path.read_bytes(), symbol)
        for idx, row in enumerate(parsed):
            if idx > 0 and row.get("pre_close") is None:
                row["pre_close"] = parsed[idx - 1]["close"]
            if row["trade_date"] == trade_date:
                target_rows.append(row)
            elif row["trade_date"] < trade_date:
                prefix_rows.append(row)
    if prefix_rows:
        store.upsert_daily_bars(prefix_rows)
    summary = ingest_a_share_bars(store, trade_date, target_rows, verified_exclusions=verified_exclusions)
    return {
        "source": "tdx_dir",
        "tdx_dir": str(tdx_dir),
        "files_scanned": len(files),
        "prefix_rows_upserted": len(prefix_rows),
        "accepted_count": summary.accepted_count,
        "quarantined_count": summary.quarantined_count,
        "excluded_count": summary.excluded_count,
        "coverage_rate": summary.coverage_rate,
    }


def ingest_trade_date(
    store: V4Store,
    trade_date: str,
    *,
    tdx_dir: Path | None = None,
    bars_json: Path | None = None,
    factors_json: Path | None = None,
    hk_bars_json: Path | None = None,
    security_master_json: Path | None = None,
    verified_exclusions: set[str] | None = None,
) -> dict[str, Any]:
    """Unified next-day ingestion for A-share TDX bars, adj_factors, HK bars, and security_master."""
    result: dict[str, Any] = {
        "trade_date": trade_date,
        "a_share_accepted": 0,
        "adj_factors_upserted": 0,
        "hk_accepted": 0,
        "security_master_upserted": 0,
        "sources": [],
    }

    if tdx_dir is not None:
        tdx_res = ingest_from_tdx_dir(store, trade_date, tdx_dir, verified_exclusions=verified_exclusions)
        result["tdx"] = tdx_res
        result["a_share_accepted"] += int(tdx_res["accepted_count"])
        result["sources"].append("tdx_dir")

    if bars_json is not None and Path(bars_json).exists():
        raw_bars = json.loads(Path(bars_json).read_text(encoding="utf-8"))
        if isinstance(raw_bars, list):
            normalized_bars = [
                {**r, "symbol": normalize_symbol(str(r["symbol"]))}
                for r in raw_bars
                if isinstance(r, dict) and r.get("symbol")
            ]
            target_only = [r for r in normalized_bars if r.get("trade_date") == trade_date]
            prefix_only = [
                {
                    "market": str(r.get("market", "A")),
                    "symbol": r["symbol"],
                    "trade_date": str(r["trade_date"]),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": int(r["volume"]),
                    "amount": float(r["amount"]),
                    "pre_close": float(r["pre_close"]) if r.get("pre_close") is not None else None,
                }
                for r in normalized_bars
                if str(r.get("trade_date", "")) < trade_date
            ]
            if prefix_only:
                store.upsert_daily_bars(prefix_only)
            summary = ingest_a_share_bars(store, trade_date, target_only, verified_exclusions=verified_exclusions)
            result["bars_json"] = {
                "accepted_count": summary.accepted_count,
                "quarantined_count": summary.quarantined_count,
                "prefix_rows_upserted": len(prefix_only),
            }
            result["a_share_accepted"] += int(summary.accepted_count)
            result["sources"].append("bars_json")

    if factors_json is not None and Path(factors_json).exists():
        raw_factors = json.loads(Path(factors_json).read_text(encoding="utf-8"))
        if isinstance(raw_factors, list):
            clean_factors = [
                {
                    "market": str(f.get("market", "A")),
                    "symbol": normalize_symbol(str(f["symbol"])),
                    "trade_date": str(f["trade_date"]),
                    "adj_factor": float(f["adj_factor"]),
                }
                for f in raw_factors
                if isinstance(f, dict) and f.get("symbol")
            ]
            result["adj_factors_upserted"] = store.upsert_adj_factors(clean_factors)
            result["sources"].append("factors_json")

    if hk_bars_json is not None and Path(hk_bars_json).exists():
        raw_hk = json.loads(Path(hk_bars_json).read_text(encoding="utf-8"))
        if isinstance(raw_hk, list):
            hk_summary = ingest_hk_bars(store, trade_date, raw_hk, quarantine_uint32_overflow=True)
            result["hk_accepted"] = hk_summary.accepted_count
            result["hk_quarantined"] = hk_summary.quarantined_count
            result["sources"].append("hk_bars_json")

    if security_master_json is not None and Path(security_master_json).exists():
        raw_sm = json.loads(Path(security_master_json).read_text(encoding="utf-8"))
        if isinstance(raw_sm, list):
            result["security_master_upserted"] = store.upsert_security_master(raw_sm)
            result["sources"].append("security_master_json")

    existing_bars = store.get_date_bars("A", trade_date, table="daily_bars")
    result["db_a_share_bar_count"] = len(existing_bars)
    if not result["sources"] and existing_bars:
        result["status"] = "ALREADY_PRESENT"
    elif existing_bars:
        result["status"] = "INGESTED"
    else:
        result["status"] = "EMPTY"
    return result
