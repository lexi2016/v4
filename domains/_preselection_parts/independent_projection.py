"""domains.preselection: independent_projection (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __complete_independent_pool_set_body(_v4_scope, /, pools, trade_date):
    """Project missing independent lanes as explicit CANNOT_CONFIRM pools.

    The source artifacts remain immutable and are never synthesized here.  The
    projection only preserves the graph-defined seven-pool surface so one
    verified lane cannot hide the other lanes or force a cross-date fallback.
    """
    by_id = {
        _v4_global(_v4_scope, 'str')(pool.get("pool_id") or ""): _v4_global(_v4_scope, 'dict')(pool)
        for pool in pools
        if _v4_global(_v4_scope, 'str')(pool.get("pool_id") or "")
    }
    completed: list[dict[str, Any]] = []
    for pool_id in _v4_global(_v4_scope, 'POOL_ORDER'):
        if pool_id in by_id:
            existing = by_id[pool_id]
            existing["optional"] = pool_id in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')
            existing["required_for_daily_readiness"] = pool_id not in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')
            existing["readiness_role"] = (
                "OPTIONAL_RESEARCH" if pool_id in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS') else "MANDATORY_DAILY"
            )
            completed.append(existing)
            continue
        market = "HK" if pool_id == "hkconnect_d1_top100" else (
            "WECHAT" if pool_id == "wechat_public_account_v3_preselect" else "A"
        )
        completed.append({
            "pool_id": pool_id,
            "display_name": _v4_global(_v4_scope, '_POOL_NAMES').get(pool_id, pool_id),
            "market": market,
            "status": "CANNOT_CONFIRM",
            "producer_id": "V3_5_INDEPENDENT_POOL_PROJECTION",
            "source_role": "EXPECTED_MISSING",
            "source_path": "",
            "source_sha256": "",
            "trade_date": trade_date,
            "signal_date": "",
            "target_date": trade_date,
            "rows": [],
            "pool_size": 0,
            "returned_rows": 0,
            "cannot_confirm": [f"POOL_ARTIFACT_MISSING:{pool_id}"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "optional": pool_id in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS'),
            "required_for_daily_readiness": pool_id not in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS'),
            "readiness_role": (
                "OPTIONAL_RESEARCH" if pool_id in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS') else "MANDATORY_DAILY"
            ),
        })
    return completed


def __project_independent_pools_body(_v4_scope, /, pools, trade_date):
    projected_pools: list[dict[str, Any]] = []
    for pool in pools:
        rows = _v4_global(_v4_scope, 'list')(pool["rows"])
        status = _v4_global(_v4_scope, 'str')(pool.get("status") or "").upper()
        ready_status = _v4_global(_v4_scope, 'bool')(rows) and (
            status in {"READY", "MATERIALIZED", "AVAILABLE"}
            or status.endswith("_READY")
        )
        projected = _v4_global(_v4_scope, 'dict')(pool)
        if not ready_status and pool.get("pool_id") not in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS'):
            reasons = _v4_global(_v4_scope, 'list')(projected.get("cannot_confirm") or ())
            reason = f"POOL_NOT_READY:{pool.get('pool_id')}:{status or 'UNKNOWN'}"
            if reason not in reasons:
                reasons.append(reason)
            projected["cannot_confirm"] = reasons
        projected_pools.append({
            **projected,
            "pool_size": _v4_global(_v4_scope, 'len')(rows),
            "returned_rows": _v4_global(_v4_scope, 'len')(rows),
        })
    grouped = {pool["pool_id"]: _v4_global(_v4_scope, 'list')(pool["rows"]) for pool in projected_pools}
    all_rows = [row for pool in projected_pools for row in pool["rows"]]
    main_rows = grouped["a_d1_premarket_pool"]
    all_a_rows = _v4_global(_v4_scope, '_dedupe_by_symbol')(row for row in all_rows if _v4_global(_v4_scope, '_market')(row) == "A")
    main_symbols = {_v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") for row in main_rows}
    source_only = [
        row for row in all_a_rows
        if _v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    hk_rows = _v4_global(_v4_scope, '_dedupe_by_symbol')(row for row in all_rows if _v4_global(_v4_scope, '_market')(row) == "HK")
    incomplete = [
        pool["pool_id"] for pool in projected_pools
        if not (
            _v4_global(_v4_scope, 'bool')(pool.get("rows"))
            and (
                _v4_global(_v4_scope, 'str')(pool.get("status") or "").upper() in {"READY", "MATERIALIZED", "AVAILABLE"}
                or _v4_global(_v4_scope, 'str')(pool.get("status") or "").upper().endswith("_READY")
            )
        )
    ]
    mandatory_incomplete = [
        pool_id for pool_id in incomplete if pool_id not in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')
    ]
    optional_incomplete = [
        pool_id for pool_id in incomplete if pool_id in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')
    ]
    daily_readiness_status = "PARTIAL_WITH_ROWS" if mandatory_incomplete else "READY_WITH_ROWS"
    return {
        "producer_status": "PARTIAL" if mandatory_incomplete else "CANONICAL_COMPLETE",
        "pools": projected_pools,
        "rows": all_rows,
        "unified_rows": main_rows,
        "a_source_only_rows": source_only,
        "a_all_pool_rows": all_a_rows,
        "market_totals": {"A": _v4_global(_v4_scope, 'len')(all_a_rows), "HK": _v4_global(_v4_scope, 'len')(hk_rows)},
        "hk_pool_version": "0.2",
        "hk_pool_role": "D_MINUS_1_MODEL_TOP100",
        "startup_ensure": {},
        "strict_0_2_status": _v4_global(_v4_scope, 'next')(pool["status"] for pool in projected_pools if pool["pool_id"] == "hkconnect_d1_top100"),
        "evidence_paths": [
            _v4_global(_v4_scope, 'str')(pool.get("source_path") or "")
            for pool in projected_pools
            if pool.get("source_path")
        ],
        "cannot_confirm": [reason for pool in projected_pools for reason in pool.get("cannot_confirm", [])],
        "optional_pool_status": "CANNOT_CONFIRM" if optional_incomplete else "MATERIALIZED_RESEARCH_ONLY",
        "daily_readiness_status": daily_readiness_status,
        "mandatory_incomplete_pool_ids": mandatory_incomplete,
        "optional_incomplete_pool_ids": optional_incomplete,
        "mandatory_pool_ids": [pool_id for pool_id in _v4_global(_v4_scope, '_POOL_ORDER') if pool_id not in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')],
        "optional_pool_ids": [pool_id for pool_id in _v4_global(_v4_scope, '_POOL_ORDER') if pool_id in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')],
        "blocking_reasons": [
            reason
            for pool in projected_pools
            if pool.get("pool_id") not in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')
            for reason in pool.get("cannot_confirm", [])
        ],
        "trade_date": trade_date,
    }
