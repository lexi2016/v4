"""Read-side quarantine for A-share rows whose code is not an A-share code.

The pools are published evidence and are never rewritten. A row that carries a
date in its code field is therefore still on disk; this module keeps it out of
what a consumer treats as a valid A-share entity while preserving every
original row, rank and count for the audit record.

Filtering must happen after the payload's SHA has been verified, and it must
never rewrite the counts the producer published - the response carries the
original and the effective numbers side by side.

The rule is A-share identity only. A Hong Kong row never matches it, whatever
its code looks like, so a mixed A/HK input keeps every HK row.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from contracts.a_share_code import a_share_symbol, canonical_a_share_code, is_a_share_code

FILTER_RULE_VERSION = "a_share_code.v1"

_HK_MARKETS = frozenset({"HK", "HK_CONNECT", "HKCONNECT", "港股", "港股通"})
_A_MARKETS = frozenset({"A", "A_SHARE", "ASHARE", "SZ", "SH", "BJ"})

ROOT_ROW_GROUPS = ("rows", "unified_rows", "a_source_only_rows", "a_all_pool_rows")


def row_market(row: Mapping[str, Any], pool_market: str | None = None) -> str:
    """``"HK"``, ``"A"``, or ``""`` when the row declares no market at all."""
    for value in (
        row.get("market"),
        row.get("market_id"),
        row.get("stock_market"),
        pool_market,
    ):
        text = str(value or "").strip().upper()
        if text in _HK_MARKETS:
            return "HK"
        if text in _A_MARKETS:
            return "A"
    for key in ("symbol", "code", "stock_code"):
        text = str(row.get(key) or "").strip().upper()
        if text.startswith("HK."):
            return "HK"
        if text.startswith(("A.", "SZ.", "SH.", "BJ.")):
            return "A"
    return ""


def _is_a_market_row(row: Mapping[str, Any], pool_market: str | None = None) -> bool:
    return row_market(row, pool_market) != "HK"


def _quarantine_record(row: Mapping[str, Any], code: str, *, pool_id: str = "") -> dict[str, Any]:
    return {
        "pool_id": pool_id or str(row.get("pool_id") or ""),
        "code": code,
        "symbol": str(row.get("symbol") or ""),
        "stock_name": str(row.get("stock_name") or row.get("name") or ""),
        "reason": "A_SHARE_CODE_INVALID",
        "rule_version": FILTER_RULE_VERSION,
    }


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
        quarantined.append(_quarantine_record(row, code, pool_id=pool_id))
    return kept, quarantined


def filter_pool_rows(pools: Iterable[Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    """Apply the quarantine to every pool's rows, keeping pool order and shape.

    A pool that lost rows carries ``original_pool_size``, ``quarantined_row_count``
    and the dropped records themselves, so a caller can report the audit trail
    without re-deriving it from the difference.
    """
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
                "quarantined_rows": dropped,
            }
        kept_pools.append(pool)
    return kept_pools, quarantined


def summarize_pool_quarantine(response: Mapping[str, Any]) -> dict[str, Any]:
    """Attach the audit triple to a pool response built from filtered pools."""
    if not isinstance(response, Mapping) or response.get("filter_rule_version"):
        return dict(response) if isinstance(response, Mapping) else response
    pools = response.get("pools")
    if not isinstance(pools, list):
        return dict(response)
    records: list[dict[str, Any]] = []
    for pool in pools:
        if isinstance(pool, Mapping):
            dropped = pool.get("quarantined_rows")
            if isinstance(dropped, list):
                records.extend(record for record in dropped if isinstance(record, Mapping))
    if not records:
        return dict(response)
    out = dict(response)
    effective = int(out.get("row_count") or 0)
    out["quarantined"] = records
    out["quarantined_row_count"] = len(records)
    out["effective_row_count"] = effective
    out["original_row_count"] = effective + len(records)
    out["filter_rule_version"] = FILTER_RULE_VERSION
    return out


def quarantine_research_stock_rows(
    rows: Iterable[Any],
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Apply the rule to ``stock_pool``-shaped rows (``stock_code``/``stock_name``)."""
    kept: list[Any] = []
    quarantined: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            kept.append(row)
            continue
        code = str(row.get("stock_code") or row.get("code") or "").strip()
        if (
            not code
            or row_market(row) == "HK"
            or is_a_share_code(code)
            or canonical_a_share_code(code)
            or a_share_symbol(code)
        ):
            kept.append(row)
            continue
        quarantined.append({
            "stock_code": code,
            "stock_name": str(row.get("stock_name") or row.get("name") or ""),
            "archive_date": str(row.get("archive_date") or ""),
            "reason": "A_SHARE_CODE_INVALID",
            "rule_version": FILTER_RULE_VERSION,
        })
    return kept, quarantined


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
