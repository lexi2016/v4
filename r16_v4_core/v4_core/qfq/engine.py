"""Causal, snapshot-isolated QFQ engine.

- Every QFQ snapshot is keyed by asof_date so D25 rebuild NEVER overwrites D24 close.
- Reads persisted adj_factors from V4Store automatically when factor_map is not passed.
"""
from __future__ import annotations

from typing import Any

from v4_core.storage.db import V4Store


class MissingAdjustmentFactorError(ValueError):
    """Raised when required adjustment factors are missing for a symbol/date."""


def compute_qfq_series(
    bars: list[dict[str, Any]],
    adj_factors: dict[str, float] | None,
    *,
    asof_date: str,
    allow_unit_factors: bool = False,
) -> list[dict[str, Any]]:
    causal_bars = sorted([b for b in bars if b["trade_date"] <= asof_date], key=lambda r: r["trade_date"])
    if not causal_bars:
        return []

    factors = adj_factors or {}
    if not allow_unit_factors:
        missing = [b["trade_date"] for b in causal_bars if b["trade_date"] not in factors]
        if missing:
            raise MissingAdjustmentFactorError(
                f"Missing adjustment factors for {causal_bars[0]['symbol']} on dates: {missing[:5]}"
            )
        latest_factor = float(factors[causal_bars[-1]["trade_date"]])
    else:
        latest_factor = float(factors.get(causal_bars[-1]["trade_date"], 1.0))

    if latest_factor <= 0:
        raise MissingAdjustmentFactorError(f"Non-positive latest adjustment factor: {latest_factor}")

    out: list[dict[str, Any]] = []
    for row in causal_bars:
        f = float(factors.get(row["trade_date"], 1.0) if allow_unit_factors else factors[row["trade_date"]])
        if f <= 0:
            raise MissingAdjustmentFactorError(f"Non-positive factor on {row['trade_date']}: {f}")
        ratio = f / latest_factor
        out.append(
            {
                "market": row["market"],
                "asof_date": asof_date,
                "symbol": row["symbol"],
                "trade_date": row["trade_date"],
                "open": round(float(row["open"]) * ratio, 4),
                "high": round(float(row["high"]) * ratio, 4),
                "low": round(float(row["low"]) * ratio, 4),
                "close": round(float(row["close"]) * ratio, 4),
                "volume": int(row["volume"]),
                "amount": float(row["amount"]),
                "adj_factor": ratio,
            }
        )
    return out


def rebuild_qfq_for_date(
    store: V4Store,
    market: str,
    trade_date: str,
    *,
    factor_map: dict[str, dict[str, float]] | None = None,
    allow_unit_factors: bool = False,
) -> dict[str, int]:
    """Causally & idempotently build immutable asof_date=trade_date QFQ snapshot."""
    day_rows = store.get_date_bars(market, trade_date, table="daily_bars")
    factors_by_sym = factor_map if factor_map is not None else store.get_adj_factors_map(market, trade_date)
    updated_rows = 0
    for row in day_rows:
        sym = row["symbol"]
        history = store.get_symbol_bars(market, sym, table="daily_bars", limit=500, asof_date=trade_date)
        qfq_rows = compute_qfq_series(
            history,
            factors_by_sym.get(sym),
            asof_date=trade_date,
            allow_unit_factors=allow_unit_factors,
        )
        updated_rows += store.upsert_qfq_bars(qfq_rows)
    return {"symbols_processed": len(day_rows), "qfq_rows_written": updated_rows}
