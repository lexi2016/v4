"""domains.preselection: pagination_metadata (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __metadata_values_body(_v4_scope, /, value):
    if _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'), _v4_global(_v4_scope, 'set'))):
        values: list[str] = []
        for item in value:
            values.extend(_v4_global(_v4_scope, '_metadata_values')(item))
        return values
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'dict')):
        return _v4_global(_v4_scope, '_metadata_values')(_v4_global(_v4_scope, 'list')(value))
    text = _v4_global(_v4_scope, 'str')(value or "").strip()
    if not text:
        return []
    text = _v4_global(_v4_scope, 're').sub(r"\s+(?:/|\|)\s+", "\n", text)
    return [item.strip() for item in text.splitlines() if item.strip()]


def __input_fingerprint_body(_v4_scope, /, pools, trade_date):
    """Hash the read-only pool inputs so paged reads cannot mix snapshots.

    The fingerprint reuses each artifact's source digest and includes the
    returned rows as a defensive check for an in-place materialization whose
    source metadata was not updated.  It is a read contract only; it never
    creates or binds a new producer artifact.
    """
    entries = []
    for pool in pools if _v4_global(_v4_scope, 'isinstance')(pools, _v4_global(_v4_scope, 'list')) else []:
        if not _v4_global(_v4_scope, 'isinstance')(pool, _v4_global(_v4_scope, 'Mapping')):
            continue
        entries.append({
            "pool_id": _v4_global(_v4_scope, 'str')(pool.get("pool_id") or ""),
            "trade_date": _v4_global(_v4_scope, 'str')(pool.get("trade_date") or trade_date),
            "source_sha256": _v4_global(_v4_scope, 'str')(pool.get("source_sha256") or ""),
            "source_artifact_sha256": _v4_global(_v4_scope, 'str')(pool.get("source_artifact_sha256") or ""),
            "rows": pool.get("rows", []),
        })
    canonical = _v4_global(_v4_scope, 'json').dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _v4_global(_v4_scope, 'hashlib').sha256(canonical.encode("utf-8")).hexdigest()


def __page_metadata_body(_v4_scope, /, rows, *, limit, offset, status):
    buckets = _v4_global(_v4_scope, '_market_buckets')(rows)
    returned_rows = _v4_global(_v4_scope, 'sum')(
        _v4_global(_v4_scope, 'len')(bucket[offset:offset + limit])
        for bucket in buckets.values()
    )
    has_more = _v4_global(_v4_scope, 'any')(offset + limit < _v4_global(_v4_scope, 'len')(bucket) for bucket in buckets.values())
    incomplete_statuses = {"CANNOT_CONFIRM", "MISSING", "NOT_MATERIALIZED", "DATA_BLOCKED_EMPTY"}
    return {
        "total_rows": _v4_global(_v4_scope, 'len')(rows),
        "offset": offset,
        "limit": limit,
        "returned_rows": returned_rows,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "complete": not has_more and status.upper() not in incomplete_statuses,
    }


def __market_buckets_body(_v4_scope, /, rows):
    buckets = {"A": [], "HK": [], "OTHER": []}
    for row in rows:
        market = _v4_global(_v4_scope, 'str')(row.get("market") or "").upper()
        symbol = _v4_global(_v4_scope, 'str')(row.get("symbol") or "")
        if market == "A" or symbol.startswith("A."):
            buckets["A"].append(row)
        elif market == "HK" or symbol.startswith("HK."):
            buckets["HK"].append(row)
        else:
            buckets["OTHER"].append(row)
    return buckets
