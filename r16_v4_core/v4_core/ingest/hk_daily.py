"""Clean HK daily bar ingester with 64-bit volume storage & UInt32 overflow quarantine."""
from __future__ import annotations

from typing import Any

from v4_core.ingest.a_share_tdx import IngestSummary
from v4_core.storage.db import V4Store

UINT32_MAX = 4_294_967_295


def ingest_hk_bars(
    store: V4Store,
    trade_date: str,
    raw_rows: list[dict[str, Any]],
    *,
    quarantine_uint32_overflow: bool = True,
) -> IngestSummary:
    """Ingest HK bars without ever crashing the whole batch on UInt32 volume overflow (e.g. 03033.HK)."""
    accepted: list[dict[str, Any]] = []
    quarantined = 0

    for row in raw_rows:
        sym = str(row["symbol"])
        vol = int(row.get("volume", 0))
        if row.get("trade_date") != trade_date:
            store.record_quarantine("HK", trade_date, sym, "TARGET_DATE_MISSING", row)
            quarantined += 1
            continue
        if min(float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])) <= 0:
            store.record_quarantine("HK", trade_date, sym, "NON_POSITIVE_OHLC", row)
            quarantined += 1
            continue
        if quarantine_uint32_overflow and (vol < 0 or vol > UINT32_MAX):
            # Preserve exact raw volume in quarantine_events without truncating or crashing the batch
            store.record_quarantine("HK", trade_date, sym, "VOLUME_UINT32_OVERFLOW", row)
            quarantined += 1
            continue
        accepted.append(
            {
                "market": "HK",
                "symbol": sym,
                "trade_date": trade_date,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": vol,
                "amount": float(row["amount"]),
                "pre_close": float(row["pre_close"]) if row.get("pre_close") is not None else None,
            }
        )

    store.upsert_daily_bars(accepted)
    total = len(raw_rows)
    cov = round(len(accepted) / total, 6) if total > 0 else 0.0
    return IngestSummary(
        market="HK",
        trade_date=trade_date,
        nominal_count=total,
        excluded_count=0,
        eligible_count=total,
        accepted_count=len(accepted),
        quarantined_count=quarantined,
        coverage_rate=cov,
    )
