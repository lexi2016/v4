"""Clean A-share TDX 32-byte .day parser & validator (no cross-version _v4_global hacks)."""
from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any

from v4_core.storage.db import V4Store

TDX_DAY_STRUCT = struct.Struct("<IIIIIfII")  # date, open*100, high*100, low*100, close*100, amount, vol, reserved


@dataclass(frozen=True)
class IngestSummary:
    market: str
    trade_date: str
    nominal_count: int
    excluded_count: int
    eligible_count: int
    accepted_count: int
    quarantined_count: int
    coverage_rate: float


def format_tdx_date(raw_yyyymmdd: int) -> str:
    s = str(raw_yyyymmdd)
    if len(s) != 8:
        raise ValueError(f"Invalid TDX date integer: {raw_yyyymmdd}")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def parse_tdx_day_bytes(payload: bytes, symbol: str) -> list[dict[str, Any]]:
    """Parse standard 32-byte TDX .day binary records into normalized OHLCV dicts."""
    if len(payload) % TDX_DAY_STRUCT.size != 0:
        raise ValueError(f"Corrupt TDX .day byte length for {symbol}: {len(payload)}")
    rows: list[dict[str, Any]] = []
    for raw_date, o, h, l, c, amount, volume, _ in TDX_DAY_STRUCT.iter_unpack(payload):
        rows.append(
            {
                "market": "A",
                "symbol": symbol,
                "trade_date": format_tdx_date(raw_date),
                "open": o / 100.0,
                "high": h / 100.0,
                "low": l / 100.0,
                "close": c / 100.0,
                "volume": int(volume),
                "amount": float(amount),
                "pre_close": None,
            }
        )
    return rows


def ingest_a_share_bars(
    store: V4Store,
    trade_date: str,
    raw_rows: list[dict[str, Any]],
    *,
    verified_exclusions: set[str] | None = None,
) -> IngestSummary:
    """Validate and store A-share daily bars; isolate non-positive OHLC & wrong-date rows."""
    excluded = verified_exclusions or set()
    accepted: list[dict[str, Any]] = []
    quarantined = 0
    excluded_hit = 0

    for row in raw_rows:
        sym = str(row["symbol"])
        if sym in excluded:
            excluded_hit += 1
            continue
        if row.get("trade_date") != trade_date:
            store.record_quarantine("A", trade_date, sym, "TARGET_DATE_MISSING", row)
            quarantined += 1
            continue
        if min(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) <= 0:
            store.record_quarantine("A", trade_date, sym, "NON_POSITIVE_OHLC", row)
            quarantined += 1
            continue
        accepted.append(
            {
                "market": "A",
                "symbol": sym,
                "trade_date": trade_date,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "amount": float(row["amount"]),
                "pre_close": float(row["pre_close"]) if row.get("pre_close") is not None else None,
            }
        )

    store.upsert_daily_bars(accepted)
    nominal = len(raw_rows)
    eligible = max(nominal - excluded_hit, 0)
    cov = round(len(accepted) / eligible, 6) if eligible > 0 else 0.0
    return IngestSummary(
        market="A",
        trade_date=trade_date,
        nominal_count=nominal,
        excluded_count=excluded_hit,
        eligible_count=eligible,
        accepted_count=len(accepted),
        quarantined_count=quarantined,
        coverage_rate=cov,
    )
