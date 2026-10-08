"""domains.preselection: optional_pool_merge (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __merge_optional_pools_body(_v4_scope, /, payload, trade_date, overlay, overlay_error):
    """Add graph-defined research lanes without changing selector-owned input."""
    base_pools = [_v4_global(_v4_scope, 'dict')(pool) for pool in payload.get("pools", [])]
    by_id = {
        _v4_global(_v4_scope, 'str')(pool.get("pool_id") or ""): pool
        for pool in base_pools
        if _v4_global(_v4_scope, 'str')(pool.get("pool_id") or "")
    }
    optional = _v4_global(_v4_scope, 'list')(overlay["pools"]) if overlay is not None else _v4_global(_v4_scope, '_optional_placeholders')(trade_date)
    for pool in optional:
        pool_id = _v4_global(_v4_scope, 'str')(pool["pool_id"])
        if pool_id in by_id:
            if overlay is not None:
                raise _v4_global(_v4_scope, 'ValueError')(f"duplicate optional pool identity: {pool_id}")
            continue
        by_id[pool_id] = _v4_global(_v4_scope, 'dict')(pool)

    base_ids = [_v4_global(_v4_scope, 'str')(pool.get("pool_id") or "") for pool in base_pools if _v4_global(_v4_scope, 'str')(pool.get("pool_id") or "")]
    if _v4_global(_v4_scope, 'any')(pool_id in _v4_global(_v4_scope, '_POOL_ORDER') for pool_id in base_ids):
        ordered_ids = [pool_id for pool_id in _v4_global(_v4_scope, '_POOL_ORDER') if pool_id in by_id]
        ordered_ids.extend(pool_id for pool_id in base_ids if pool_id not in ordered_ids)
    else:
        ordered_ids = _v4_global(_v4_scope, 'list')(base_ids)
        ordered_ids.extend(pool_id for pool_id in _v4_global(_v4_scope, '_POOL_ORDER') if pool_id in by_id and pool_id not in ordered_ids)
    pools = [by_id[pool_id] for pool_id in ordered_ids]
    rows = [row for pool in pools for row in pool.get("rows", [])]
    grouped = {_v4_global(_v4_scope, 'str')(pool.get("pool_id") or ""): _v4_global(_v4_scope, 'list')(pool.get("rows", [])) for pool in pools}
    main_rows = grouped.get("a_d1_premarket_pool") or _v4_global(_v4_scope, 'list')(payload.get("unified_rows", []))
    if grouped.get("a_d1_premarket_pool"):
        all_a_rows = _v4_global(_v4_scope, '_dedupe_by_symbol')(row for row in rows if _v4_global(_v4_scope, '_market')(row) == "A")
    else:
        optional_ids = {"a_share_baimao_research_map", "wechat_public_account_v3_preselect"}
        all_a_rows = _v4_global(_v4_scope, '_dedupe_by_symbol')([
            *_v4_global(_v4_scope, 'list')(payload.get("a_all_pool_rows", [])),
            *(row for pool in pools if pool.get("pool_id") in optional_ids for row in pool.get("rows", []) if _v4_global(_v4_scope, '_market')(row) == "A"),
        ])
    main_symbols = {_v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") for row in main_rows}
    source_only_rows = [
        row for row in all_a_rows
        if _v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    hk_rows = _v4_global(_v4_scope, '_dedupe_by_symbol')(row for row in rows if _v4_global(_v4_scope, '_market')(row) == "HK")
    cannot_confirm = _v4_global(_v4_scope, 'list')(payload.get("cannot_confirm", []))
    if overlay is not None:
        cannot_confirm.extend(overlay.get("cannot_confirm", []))
        optional_status = "MATERIALIZED_RESEARCH_ONLY"
    else:
        cannot_confirm.extend([
            overlay_error or "WECHAT_OPTIONAL_POOL_NOT_MATERIALIZED",
            "BAIMAO_RESEARCH_MAP_NOT_FOUND",
        ])
        optional_status = "CANNOT_CONFIRM"
    restored = _v4_global(_v4_scope, 'dict')(payload)
    restored.update({
        "pools": pools,
        "rows": rows,
        "unified_rows": main_rows,
        "a_source_only_rows": source_only_rows,
        "a_all_pool_rows": all_a_rows,
        "market_totals": {"A": _v4_global(_v4_scope, 'len')(all_a_rows), "HK": _v4_global(_v4_scope, 'len')(hk_rows)},
        "cannot_confirm": cannot_confirm,
        "optional_pool_status": optional_status,
    })
    return restored


def __optional_placeholders_body(_v4_scope, /, trade_date):
    return [
        {
            "pool_id": "a_share_baimao_research_map",
            "market": "A",
            "display_name": "白毛卡点研究池",
            "status": "CANNOT_CONFIRM",
            "recommendation_status": "RESEARCH_ONLY",
            "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
            "stage_selection_eligible": False,
            "write_policy": "RESEARCH_ONLY",
            "production_allowed": False,
            "opens_buy_gate": False,
            "pool_size": 0,
            "returned_rows": 0,
            "trade_date": trade_date,
            "rows": [],
            "cannot_confirm": ["BAIMAO_RESEARCH_MAP_NOT_FOUND"],
            "evidence_paths": {"research_map": ""},
        },
        {
            "pool_id": "wechat_public_account_v3_preselect",
            "market": "WECHAT",
            "display_name": "公众号股票池",
            "status": "CANNOT_CONFIRM",
            "recommendation_status": "RESEARCH_ONLY",
            "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
            "stage_selection_eligible": False,
            "formal_pool_write": False,
            "production_allowed": False,
            "date_match_status": "CANNOT_CONFIRM_EXACT_DATE",
            "source_signal_date": "",
            "target_date": trade_date,
            "pool_size": 0,
            "returned_rows": 0,
            "rows": [],
            "cannot_confirm": ["WECHAT_OPTIONAL_POOL_NOT_MATERIALIZED"],
            "evidence_paths": {},
        },
    ]
