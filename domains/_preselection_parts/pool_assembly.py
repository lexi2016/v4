"""domains.preselection: pool_assembly (review candidate, not deployment)."""
from __future__ import annotations
from typing import Any, Mapping

from contracts.a_share_entity_filter import (
    FILTER_RULE_VERSION,
    filter_pool_rows,
    summarize_pool_quarantine,
)
from domains.preselection import OPTIONAL_DAILY_POOL_IDS, _blocked, _canonical_a_symbol, _complete_independent_pool_set, _ensure_source_contract, _input_fingerprint, _market_totals, _merge_source_contract, _page_metadata, _page_per_market, _project_independent_pools, _replace_payload_review_core_fupan_pool, _replace_payload_review_core_stage7_pool, _replace_review_core_fupan_pool, _replace_review_core_stage7_pool


def _preselection_body(store, date, limit, *, offset, allow_legacy_flat, pool_store_class):
    if limit < 1:
        raise ValueError("preselection page limit must be positive")
    if offset < 0:
        raise ValueError("preselection page offset cannot be negative")
    independent_store = pool_store_class(store.root)
    try:
        independent_pools = independent_store.read_all(date)
    except FileNotFoundError:
        independent_pools = []
    except ValueError as error:
        return _blocked(date, f"V4 independent pool receipt cannot be confirmed: {error}")
    if independent_pools:
        independent_pools = _replace_review_core_fupan_pool(independent_pools, date)
        independent_pools = _replace_review_core_stage7_pool(independent_pools, date)
        independent_pools = _complete_independent_pool_set(independent_pools, date)
        payload = _project_independent_pools(independent_pools, date)
    else:
        if not allow_legacy_flat:
            return _blocked(
                date,
                "V4 independent preselection producers have not materialized this date.",
            )
        try:
            payload = store.read_payload(date)
        except FileNotFoundError:
            return _blocked(date, "V4 independent preselection producers have not materialized this date.")
        except ValueError as error:
            return _blocked(date, f"V4 pool receipt cannot be confirmed: {error}")
        payload = _replace_payload_review_core_fupan_pool(payload, date)
        payload = _replace_payload_review_core_stage7_pool(payload, date)
        if any(pool.get("pool_id") == "legacy_partial_migration" for pool in payload.get("pools", [])):
            return _blocked(date, "LEGACY_PARTIAL_MIGRATION_REJECTED: final-output imports are oracle-only.")
    # Storage is write-once and its digest was verified when the pools were
    # read; this quarantine only decides which rows a consumer may treat as
    # A-share entities. Stored rows, ranks and counts are never rewritten.
    quarantine: list = []
    if isinstance(payload, Mapping) and isinstance(payload.get("pools"), list):
        filtered_pools, quarantine = filter_pool_rows(payload["pools"])
        if quarantine:
            payload = {**payload, **_project_independent_pools(filtered_pools, date)}
    rows = payload["rows"]
    status = "READY_WITH_ROWS" if payload.get("producer_status") == "CANONICAL_COMPLETE" else "PARTIAL_WITH_ROWS"
    if not rows:
        if quarantine:
            return _all_rows_quarantined(date, quarantine)
        return _blocked(date, "Empty output is not promoted to VALID_EMPTY without complete producer evidence.")
    response = {key: payload.get(key, [] if key.endswith("rows") or key == "pools" or key == "cannot_confirm" else {}) for key in ("pools", "unified_rows", "a_source_only_rows", "a_all_pool_rows", "startup_ensure", "strict_0_2_status", "evidence_paths", "cannot_confirm")}
    response.update({"ok": True, "data_status": status, "blocking_reasons": list(payload.get("blocking_reasons", [])), "schema_version": "v3_preselection_pools.v1", "trade_date": date, "module_id": "unified_preselection_pools", "write_policy": "read_only", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "recommendation_status": "WATCH_ONLY_BACKTEST_GATED", "pool_count": len(payload.get("pools", [])), "row_count": len(rows), "unified_row_count": len(payload.get("unified_rows", rows)), "a_source_only_row_count": len(payload.get("a_source_only_rows", [])), "a_all_pool_row_count": len(payload.get("a_all_pool_rows", rows)), "rows": [], "daily_readiness_status": payload.get("daily_readiness_status", status), "mandatory_pool_ids": list(payload.get("mandatory_pool_ids", ())), "optional_pool_ids": list(payload.get("optional_pool_ids", OPTIONAL_DAILY_POOL_IDS))})
    response["market_totals"] = payload.get("market_totals", _market_totals(rows))
    response["hk_pool_version"] = payload.get("hk_pool_version")
    response["hk_pool_role"] = payload.get("hk_pool_role")
    response["input_fingerprint"] = _input_fingerprint(payload.get("pools", []), date)
    response["source_digests"] = {
        str(pool.get("pool_id") or ""): str(pool.get("source_sha256") or "")
        for pool in payload.get("pools", [])
        if str(pool.get("pool_id") or "")
    }
    from .source_validation import project_a_display_names
    resolver = getattr(independent_store, "_resolver", None)
    name_root = resolver.root_for_date(date) if resolver is not None else store.root
    response = project_a_display_names(response, date, name_root)
    full_arrays = {
        "unified_rows": list(response["unified_rows"]),
        "a_source_only_rows": list(response["a_source_only_rows"]),
        "a_all_pool_rows": list(response["a_all_pool_rows"]),
    }
    array_pagination = {
        name: _page_metadata(rows_for_array, limit=limit, offset=offset)
        for name, rows_for_array in full_arrays.items()
    }
    response["unified_rows"] = _page_per_market(full_arrays["unified_rows"], limit, offset)
    response["a_source_only_rows"] = _page_per_market(full_arrays["a_source_only_rows"], limit, offset)
    response["a_all_pool_rows"] = _page_per_market(full_arrays["a_all_pool_rows"], limit, offset)

    paged_pools: list[dict[str, Any]] = []
    pool_pagination: dict[str, dict[str, Any]] = {}
    for pool in response["pools"]:
        full_pool_rows = list(pool.get("rows", []))
        metadata = _page_metadata(
            full_pool_rows,
            limit=limit,
            offset=offset,
            status=str(pool.get("status") or ""),
        )
        pool_pagination[str(pool.get("pool_id") or "")] = metadata
        paged_pools.append({
            **pool,
            "pool_size": len(full_pool_rows),
            "returned_rows": metadata["returned_rows"],
            "rows": _page_per_market(full_pool_rows, limit, offset),
            "page_offset": offset,
            "page_limit": limit,
            "has_more": metadata["has_more"],
            "complete": metadata["complete"],
        })
    response["pools"] = paged_pools
    response["rows"] = [row for pool in paged_pools for row in pool.get("rows", [])]
    has_more = any(
        metadata["has_more"]
        for metadata in (*array_pagination.values(), *pool_pagination.values())
    )
    response["pagination"] = {
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if has_more else None,
        "has_more": has_more,
        "complete": not has_more and status == "READY_WITH_ROWS"
        and all(
            metadata["complete"]
            for pool_id, metadata in pool_pagination.items()
            if pool_id not in OPTIONAL_DAILY_POOL_IDS
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
    response["mandatory_pool_ids"] = list(payload.get("mandatory_pool_ids", ()))
    response["optional_pool_ids"] = list(payload.get("optional_pool_ids", OPTIONAL_DAILY_POOL_IDS))
    return summarize_pool_quarantine(response)


def _all_rows_quarantined(date, quarantine) -> dict[str, Any]:
    """Report a pool set whose every published row was an invalid A-share entity.

    This is not an empty product: the producer published rows, the read side
    withheld all of them, and the caller must be able to tell the two apart.
    """
    return {
        "ok": True,
        "status": "ALL_ROWS_QUARANTINED",
        "data_status": "ALL_ROWS_QUARANTINED",
        "schema_version": "v3_preselection_pools.v1",
        "trade_date": date,
        "module_id": "unified_preselection_pools",
        "write_policy": "read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "pool_count": 0,
        "row_count": 0,
        "original_row_count": len(quarantine),
        "effective_row_count": 0,
        "quarantined_row_count": len(quarantine),
        "quarantined": list(quarantine),
        "filter_rule_version": FILTER_RULE_VERSION,
        "blocking_reasons": ["ALL_ROWS_QUARANTINED_AS_INVALID_A_SHARE"],
        "cannot_confirm": ["ALL_ROWS_QUARANTINED_AS_INVALID_A_SHARE"],
        "rows": [],
        "pools": [],
        "unified_rows": [],
        "a_source_only_rows": [],
        "a_all_pool_rows": [],
    }


def __dedupe_by_symbol_body(rows):
    selected: list[dict[str, Any]] = []
    selected_by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        canonical = _canonical_a_symbol(row)
        raw_symbol = str(row.get("symbol") or row.get("code") or "").strip()
        symbol = canonical or (raw_symbol if raw_symbol.upper().startswith("HK.") else "")
        if not symbol:
            continue
        source_row = dict(row)
        if canonical:
            source_row["symbol"] = canonical
        current = selected_by_symbol.get(symbol)
        if current is None:
            current = source_row
            _ensure_source_contract(current)
            selected_by_symbol[symbol] = current
            selected.append(current)
            continue
        _merge_source_contract(current, source_row)
    return selected
