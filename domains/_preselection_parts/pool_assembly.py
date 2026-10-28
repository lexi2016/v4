"""domains.preselection: pool_assembly (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _preselection_body(_v4_scope, /, store, date, limit, *, offset, allow_legacy_flat):
    if limit < 1:
        raise _v4_global(_v4_scope, 'ValueError')("preselection page limit must be positive")
    if offset < 0:
        raise _v4_global(_v4_scope, 'ValueError')("preselection page offset cannot be negative")
    independent_store = _v4_global(_v4_scope, 'PreselectionPoolStore')(store.root)
    try:
        independent_pools = independent_store.read_all(date)
    except _v4_global(_v4_scope, 'FileNotFoundError'):
        independent_pools = []
    except _v4_global(_v4_scope, 'ValueError') as error:
        return _v4_global(_v4_scope, '_blocked')(date, f"V3.5 independent pool receipt cannot be confirmed: {error}")
    if independent_pools:
        independent_pools = _v4_global(_v4_scope, '_replace_review_core_fupan_pool')(independent_pools, date)
        independent_pools = _v4_global(_v4_scope, '_replace_review_core_stage7_pool')(independent_pools, date)
        independent_pools = _v4_global(_v4_scope, '_complete_independent_pool_set')(independent_pools, date)
        payload = _v4_global(_v4_scope, '_project_independent_pools')(independent_pools, date)
    else:
        if not allow_legacy_flat:
            return _v4_global(_v4_scope, '_blocked')(
                date,
                "V3.5 independent preselection producers have not materialized this date.",
            )
        try:
            payload = store.read_payload(date)
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            return _v4_global(_v4_scope, '_blocked')(date, "V3.5 independent preselection producers have not materialized this date.")
        except _v4_global(_v4_scope, 'ValueError') as error:
            return _v4_global(_v4_scope, '_blocked')(date, f"V3.5 pool receipt cannot be confirmed: {error}")
        payload = _v4_global(_v4_scope, '_replace_payload_review_core_fupan_pool')(payload, date)
        payload = _v4_global(_v4_scope, '_replace_payload_review_core_stage7_pool')(payload, date)
        if _v4_global(_v4_scope, 'any')(pool.get("pool_id") == "legacy_partial_migration" for pool in payload.get("pools", [])):
            return _v4_global(_v4_scope, '_blocked')(date, "LEGACY_PARTIAL_MIGRATION_REJECTED: final-output imports are oracle-only.")
    rows = payload["rows"]
    status = "READY_WITH_ROWS" if payload.get("producer_status") == "CANONICAL_COMPLETE" else "PARTIAL_WITH_ROWS"
    if not rows:
        return _v4_global(_v4_scope, '_blocked')(date, "Empty output is not promoted to VALID_EMPTY without complete producer evidence.")
    response = {key: payload.get(key, [] if key.endswith("rows") or key == "pools" or key == "cannot_confirm" else {}) for key in ("pools", "unified_rows", "a_source_only_rows", "a_all_pool_rows", "startup_ensure", "strict_0_2_status", "evidence_paths", "cannot_confirm")}
    response.update({"ok": True, "data_status": status, "blocking_reasons": _v4_global(_v4_scope, 'list')(payload.get("blocking_reasons", [])), "schema_version": "v3_preselection_pools.v1", "trade_date": date, "module_id": "unified_preselection_pools", "write_policy": "read_only", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "recommendation_status": "WATCH_ONLY_BACKTEST_GATED", "pool_count": _v4_global(_v4_scope, 'len')(payload.get("pools", [])), "row_count": _v4_global(_v4_scope, 'len')(rows), "unified_row_count": _v4_global(_v4_scope, 'len')(payload.get("unified_rows", rows)), "a_source_only_row_count": _v4_global(_v4_scope, 'len')(payload.get("a_source_only_rows", [])), "a_all_pool_row_count": _v4_global(_v4_scope, 'len')(payload.get("a_all_pool_rows", rows)), "rows": [], "daily_readiness_status": payload.get("daily_readiness_status", status), "mandatory_pool_ids": _v4_global(_v4_scope, 'list')(payload.get("mandatory_pool_ids", ())), "optional_pool_ids": _v4_global(_v4_scope, 'list')(payload.get("optional_pool_ids", _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')))})
    response["market_totals"] = payload.get("market_totals", _v4_global(_v4_scope, '_market_totals')(rows))
    response["hk_pool_version"] = payload.get("hk_pool_version")
    response["hk_pool_role"] = payload.get("hk_pool_role")
    response["input_fingerprint"] = _v4_global(_v4_scope, '_input_fingerprint')(payload.get("pools", []), date)
    response["source_digests"] = {
        _v4_global(_v4_scope, 'str')(pool.get("pool_id") or ""): _v4_global(_v4_scope, 'str')(pool.get("source_sha256") or "")
        for pool in payload.get("pools", [])
        if _v4_global(_v4_scope, 'str')(pool.get("pool_id") or "")
    }
    full_arrays = {
        "unified_rows": _v4_global(_v4_scope, 'list')(response["unified_rows"]),
        "a_source_only_rows": _v4_global(_v4_scope, 'list')(response["a_source_only_rows"]),
        "a_all_pool_rows": _v4_global(_v4_scope, 'list')(response["a_all_pool_rows"]),
    }
    array_pagination = {
        name: _v4_global(_v4_scope, '_page_metadata')(rows_for_array, limit=limit, offset=offset)
        for name, rows_for_array in full_arrays.items()
    }
    response["unified_rows"] = _v4_global(_v4_scope, '_page_per_market')(full_arrays["unified_rows"], limit, offset)
    response["a_source_only_rows"] = _v4_global(_v4_scope, '_page_per_market')(full_arrays["a_source_only_rows"], limit, offset)
    response["a_all_pool_rows"] = _v4_global(_v4_scope, '_page_per_market')(full_arrays["a_all_pool_rows"], limit, offset)

    paged_pools: list[dict[str, Any]] = []
    pool_pagination: dict[str, dict[str, Any]] = {}
    for pool in response["pools"]:
        full_pool_rows = _v4_global(_v4_scope, 'list')(pool.get("rows", []))
        metadata = _v4_global(_v4_scope, '_page_metadata')(
            full_pool_rows,
            limit=limit,
            offset=offset,
            status=_v4_global(_v4_scope, 'str')(pool.get("status") or ""),
        )
        pool_pagination[_v4_global(_v4_scope, 'str')(pool.get("pool_id") or "")] = metadata
        paged_pools.append({
            **pool,
            "pool_size": _v4_global(_v4_scope, 'len')(full_pool_rows),
            "returned_rows": metadata["returned_rows"],
            "rows": _v4_global(_v4_scope, '_page_per_market')(full_pool_rows, limit, offset),
            "page_offset": offset,
            "page_limit": limit,
            "has_more": metadata["has_more"],
            "complete": metadata["complete"],
        })
    response["pools"] = paged_pools
    response["rows"] = [row for pool in paged_pools for row in pool.get("rows", [])]
    has_more = _v4_global(_v4_scope, 'any')(
        metadata["has_more"]
        for metadata in (*array_pagination.values(), *pool_pagination.values())
    )
    response["pagination"] = {
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if has_more else None,
        "has_more": has_more,
        "complete": not has_more and status == "READY_WITH_ROWS"
        and _v4_global(_v4_scope, 'all')(
            metadata["complete"]
            for pool_id, metadata in pool_pagination.items()
            if pool_id not in _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')
        ),
        "arrays": array_pagination,
        "pools": pool_pagination,
    }
    response["a_all_pool_complete"] = array_pagination["a_all_pool_rows"]["complete"]
    response["unified_rows_complete"] = array_pagination["unified_rows"]["complete"]
    response["a_source_only_rows_complete"] = array_pagination["a_source_only_rows"]["complete"]
    response["optional_pool_status"] = payload.get("optional_pool_status", "CANNOT_CONFIRM")
    response["daily_readiness_status"] = payload.get(
        "daily_readiness_status",
        "READY_WITH_ROWS" if status == "READY_WITH_ROWS" else status,
    )
    response["mandatory_pool_ids"] = _v4_global(_v4_scope, 'list')(payload.get("mandatory_pool_ids", ()))
    response["optional_pool_ids"] = _v4_global(_v4_scope, 'list')(payload.get("optional_pool_ids", _v4_global(_v4_scope, 'OPTIONAL_DAILY_POOL_IDS')))
    return response


def __dedupe_by_symbol_body(_v4_scope, /, rows):
    selected: list[dict[str, Any]] = []
    selected_by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        canonical = _v4_global(_v4_scope, '_canonical_a_symbol')(row)
        raw_symbol = _v4_global(_v4_scope, 'str')(row.get("symbol") or row.get("code") or "").strip()
        symbol = canonical or (raw_symbol if raw_symbol.upper().startswith("HK.") else "")
        if not symbol:
            continue
        source_row = _v4_global(_v4_scope, 'dict')(row)
        if canonical:
            source_row["symbol"] = canonical
        current = selected_by_symbol.get(symbol)
        if current is None:
            current = source_row
            _v4_global(_v4_scope, '_ensure_source_contract')(current)
            selected_by_symbol[symbol] = current
            selected.append(current)
            continue
        _v4_global(_v4_scope, '_merge_source_contract')(current, source_row)
    return selected
