"""domains.preselection: review_stage7 (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __replace_review_core_stage7_pool_body(_v4_scope, /, pools, trade_date):
    """Replace the native Stage7 artifact only with a verified external DTO."""

    if not _v4_global(_v4_scope, 'any')(pool.get("pool_id") == "a_d1_stage7_fenshi_review_pool" for pool in pools):
        return pools
    review_core_pool = _v4_global(_v4_scope, 'load_review_core_stage7_pool')(trade_date)
    if not _v4_global(_v4_scope, '_usable_review_core_stage7_pool')(review_core_pool, trade_date):
        return pools
    return [
        review_core_pool if pool.get("pool_id") == "a_d1_stage7_fenshi_review_pool" else pool
        for pool in pools
    ]


def __usable_review_core_stage7_pool_body(_v4_scope, /, pool, trade_date):
    """Accept only an exact, safety-clean, non-empty Review Core Stage7 DTO."""

    if not _v4_global(_v4_scope, 'isinstance')(pool, _v4_global(_v4_scope, 'Mapping')):
        return False
    if pool.get("pool_id") != "a_d1_stage7_fenshi_review_pool":
        return False
    if pool.get("market") != "A" or pool.get("target_date") != trade_date:
        return False
    if pool.get("status") not in {"READY", "PARTIAL"}:
        return False
    rows = pool.get("rows")
    if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list')) or not rows or pool.get("row_count") != _v4_global(_v4_scope, 'len')(rows):
        return False
    if pool.get("source_merge_role") != "SOURCE_ONLY" or pool.get("stage_selection_eligible") is not False:
        return False
    if _v4_global(_v4_scope, 'any')(pool.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    flags = pool.get("safety_flags")
    if not _v4_global(_v4_scope, 'isinstance')(flags, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'any')(
        flags.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")
    ):
        return False
    for row in rows:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')):
            return False
        if row.get("source_merge_role") != "SOURCE_ONLY" or row.get("stage_selection_eligible") is not False:
            return False
        if _v4_global(_v4_scope, 'any')(row.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")):
            return False
        row_flags = row.get("safety_flags")
        if row_flags is not None and (
            not _v4_global(_v4_scope, 'isinstance')(row_flags, _v4_global(_v4_scope, 'Mapping'))
            or _v4_global(_v4_scope, 'any')(
                row_flags.get(name) is not False
                for name in ("production_allowed", "buy_gate_updated", "orders_sent")
            )
        ):
            return False
    return True


def __replace_payload_review_core_stage7_pool_body(_v4_scope, /, payload, trade_date):
    """Apply the same exact-date Stage7 replacement to a legacy payload."""

    pools = payload.get("pools")
    if not _v4_global(_v4_scope, 'isinstance')(pools, _v4_global(_v4_scope, 'list')) or not _v4_global(_v4_scope, 'any')(
        _v4_global(_v4_scope, 'isinstance')(pool, _v4_global(_v4_scope, 'dict')) and pool.get("pool_id") == "a_d1_stage7_fenshi_review_pool"
        for pool in pools
    ):
        return payload
    replaced = _v4_global(_v4_scope, '_replace_review_core_stage7_pool')([_v4_global(_v4_scope, 'dict')(pool) for pool in pools], trade_date)
    if [pool.get("pool_id") for pool in replaced] == _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'POOL_ORDER')):
        projected = _v4_global(_v4_scope, '_project_independent_pools')(replaced, trade_date)
        restored = _v4_global(_v4_scope, 'dict')(payload)
        restored.update(projected)
        return restored
    restored = _v4_global(_v4_scope, 'dict')(payload)
    restored["pools"] = replaced
    restored["rows"] = [row for pool in replaced for row in pool.get("rows", [])]
    restored["a_all_pool_rows"] = _v4_global(_v4_scope, '_dedupe_by_symbol')(
        row for row in restored["rows"] if _v4_global(_v4_scope, '_market')(row) == "A"
    )
    main = _v4_global(_v4_scope, 'next')(
        (pool for pool in replaced if pool.get("pool_id") == "a_d1_premarket_pool"),
        None,
    )
    restored["unified_rows"] = _v4_global(_v4_scope, 'list')(main.get("rows", [])) if main else []
    main_symbols = {_v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") for row in restored["unified_rows"]}
    restored["a_source_only_rows"] = [
        row for row in restored["a_all_pool_rows"]
        if _v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    restored["market_totals"] = _v4_global(_v4_scope, '_market_totals')(restored["rows"])
    return restored
