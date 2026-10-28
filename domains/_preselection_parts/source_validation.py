"""domains.preselection: source_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __restore_flat_migration_contract_body(_v4_scope, /, payload):
    """Project the one-time flat import back into the old V3 pool contract.

    This is a read-only compatibility projection.  It does not claim that a
    partial migration is canonical and it never fabricates candidate rows.
    """
    pools = payload.get("pools") or []
    if _v4_global(_v4_scope, 'len')(pools) != 1 or pools[0].get("pool_id") != "legacy_partial_migration":
        return payload

    rows = _v4_global(_v4_scope, 'list')(payload.get("rows") or pools[0].get("rows") or [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pool_id = _v4_global(_v4_scope, 'str')(row.get("pool_id") or "")
        if pool_id:
            grouped.setdefault(pool_id, []).append(row)

    restored_pools = []
    pool_ids = [pool_id for pool_id in _v4_global(_v4_scope, '_POOL_ORDER') if grouped.get(pool_id)]
    pool_ids.extend(_v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(grouped) - _v4_global(_v4_scope, 'set')(pool_ids)))
    for pool_id in pool_ids:
        pool_rows = grouped[pool_id]
        markets = {_v4_global(_v4_scope, '_market')(row) for row in pool_rows}
        restored_pools.append({
            "pool_id": pool_id,
            "display_name": _v4_global(_v4_scope, '_POOL_NAMES').get(pool_id, pool_id),
            "market": markets.pop() if _v4_global(_v4_scope, 'len')(markets) == 1 else "MIXED",
            "pool_size": _v4_global(_v4_scope, 'len')(pool_rows),
            "returned_rows": _v4_global(_v4_scope, 'len')(pool_rows),
            "rows": pool_rows,
        })

    main_rows = grouped.get("a_d1_premarket_pool", [])
    all_a_rows = _v4_global(_v4_scope, '_dedupe_by_symbol')(
        row for pool_id in pool_ids if pool_id != "hkconnect_d1_top100"
        for row in grouped.get(pool_id, [])
        if _v4_global(_v4_scope, '_market')(row) == "A"
    )
    main_symbols = {_v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") for row in main_rows}
    source_only_rows = [
        row for row in all_a_rows
        if _v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    hk_rows = _v4_global(_v4_scope, '_dedupe_by_symbol')(row for row in rows if _v4_global(_v4_scope, '_market')(row) == "HK")

    restored = _v4_global(_v4_scope, 'dict')(payload)
    restored.update({
        "pools": restored_pools,
        "unified_rows": _v4_global(_v4_scope, 'list')(main_rows),
        "a_source_only_rows": source_only_rows,
        "a_all_pool_rows": all_a_rows,
        "market_totals": {"A": _v4_global(_v4_scope, 'len')(all_a_rows), "HK": _v4_global(_v4_scope, 'len')(hk_rows)},
        "hk_pool_version": "0.2" if grouped.get("hkconnect_d1_top100") else None,
        "hk_pool_role": "D_MINUS_1_MODEL_TOP100" if grouped.get("hkconnect_d1_top100") else None,
    })
    return restored


def __ensure_source_contract_body(_v4_scope, /, row):
    """Fill the evidenced old-V3 source fields without changing row values."""

    source_tag, source_suffix, source_lane = _v4_global(_v4_scope, '_pool_source_metadata')(row)
    if not row.get("display_name") and source_suffix:
        stock_name = _v4_global(_v4_scope, 'str')(row.get("stock_name") or row.get("name") or row.get("symbol") or "")
        row["display_name"] = f"{stock_name}{source_suffix}"
    if not _v4_global(_v4_scope, '_metadata_values')(row.get("source_tag")) and source_tag:
        row["source_tag"] = source_tag
    if not _v4_global(_v4_scope, '_metadata_values')(row.get("source_tags")) and source_suffix:
        row["source_tags"] = source_suffix
    if not _v4_global(_v4_scope, '_metadata_values')(row.get("source_lanes")) and source_lane:
        row["source_lanes"] = source_lane


def __merge_source_contract_body(_v4_scope, /, target, incoming):
    """Merge provenance while keeping the first row's rank, score, and name."""

    _v4_global(_v4_scope, '_ensure_source_contract')(target)
    incoming_row = _v4_global(_v4_scope, 'dict')(incoming)
    _v4_global(_v4_scope, '_ensure_source_contract')(incoming_row)
    for field in ("source_tags", "source_lanes", "source_trace"):
        values = _v4_global(_v4_scope, '_ordered_metadata_values')(
            [*_v4_global(_v4_scope, '_metadata_values')(target.get(field)), *_v4_global(_v4_scope, '_metadata_values')(incoming_row.get(field))]
        )
        if values:
            target[field] = " / ".join(values)
