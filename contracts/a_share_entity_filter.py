"""Read-side quarantine for A-share rows whose code is not an A-share code.

The pools are published evidence and are never rewritten. A row that carries a
date in its code field is therefore still on disk; this module keeps it out of
what a consumer treats as a valid A-share entity while preserving every
original row, rank and count for the audit record.

Filtering must happen after the payload's SHA has been verified, and it must
never rewrite the counts the producer published - the response carries the
original and the effective numbers side by side.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from contracts.a_share_code import is_a_share_code

FILTER_RULE_VERSION = "a_share_code.v1"


def _is_a_market_row(row: Mapping[str, Any], pool_market: str | None) -> bool:
    market = str(row.get("market") or pool_market or "").strip().upper()
    return market in {"", "A", "A_SHARE"}


def quarantine_invalid_a_rows(
    rows: Iterable[Any],
    *,
    pool_id: str = "",
    pool_market: str | None = None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Split rows into (kept, quarantined) without touching either in place."""
    kept: list[Any] = []
    quarantined: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            kept.append(row)
            continue
        code = str(row.get("code") or "").strip()
        if not code or not _is_a_market_row(row, pool_market) or is_a_share_code(code):
            kept.append(row)
            continue
        quarantined.append({
            "pool_id": pool_id or str(row.get("pool_id") or ""),
            "code": code,
            "symbol": str(row.get("symbol") or ""),
            "stock_name": str(row.get("stock_name") or row.get("name") or ""),
            "reason": "A_SHARE_CODE_INVALID",
            "rule_version": FILTER_RULE_VERSION,
        })
    return kept, quarantined


def filter_pool_rows(pools: Iterable[Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    """Apply the quarantine to every pool's rows, keeping pool order and shape."""
    kept_pools: list[Any] = []
    quarantined: list[dict[str, Any]] = []
    for pool in pools:
        if not isinstance(pool, Mapping) or not isinstance(pool.get("rows"), list):
            kept_pools.append(pool)
            continue
        kept_rows, dropped = quarantine_invalid_a_rows(
            pool["rows"],
            pool_id=str(pool.get("pool_id") or ""),
            pool_market=str(pool.get("market") or "") or None,
        )
        if dropped:
            quarantined.extend(dropped)
            pool = {
                **pool,
                "rows": kept_rows,
                "original_pool_size": len(pool["rows"]),
                "quarantined_row_count": len(dropped),
            }
        kept_pools.append(pool)
    return kept_pools, quarantined


def invalid_a_share_symbols(symbols: Iterable[Any]) -> list[str]:
    """Return the entries that cannot be an A-share symbol (``SZ.261029``).

    HK symbols are left alone: this rule is about A-share identity only.
    """
    bad: list[str] = []
    for symbol in symbols:
        text = str(symbol or "").strip().upper()
        if not text or text.startswith("HK."):
            continue
        prefix, _, rest = text.partition(".")
        code = rest if rest and prefix in {"A", "SZ", "SH", "BJ"} else text
        if not is_a_share_code(code):
            bad.append(text)
    return bad
