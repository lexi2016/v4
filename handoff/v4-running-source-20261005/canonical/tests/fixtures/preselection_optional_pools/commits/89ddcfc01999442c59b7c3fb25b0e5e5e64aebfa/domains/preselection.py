from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_overlay_store import PreselectionOverlayStore


def date_catalog(store: NativeDataStore) -> dict[str, Any]:
    catalog = store.read_catalog(); system_date = catalog["system_date"]
    materialized = catalog.get("materialized_rows", {})
    stage = sorted({date for date in catalog["stage_dates"] + [date for date, rows in materialized.items() if rows > 0] if date <= system_date and _is_trading_date(date)})
    future = sorted({date for date in catalog["future_target_dates"] if date > system_date and _is_trading_date(date)})
    positive = sorted(date for date, rows in materialized.items() if date <= system_date and rows > 0 and _is_trading_date(date))
    if not stage and _is_trading_date(system_date):
        stage = [system_date]
    default = positive[-1] if positive else (stage[-1] if stage else "")
    return {"ok": True, "default_date": default, "dates": sorted(set(stage + future), reverse=True), "stage_dates": stage, "future_target_dates": future, "system_date": system_date}


def preselection(store: NativeDataStore, date: str, limit: int) -> dict[str, Any]:
    try:
        payload = store.read_payload(date)
    except FileNotFoundError:
        return _blocked(date, "V3.5-owned canonical main pool has not been imported for this date.")
    except ValueError as error:
        return _blocked(date, f"V3.5-owned pool receipt cannot be confirmed: {error}")
    payload = _restore_flat_migration_contract(payload)
    overlay_error = ""
    try:
        overlay = PreselectionOverlayStore(store.root).read_overlay(date)
    except ValueError as error:
        overlay = None
        overlay_error = f"OPTIONAL_POOL_OVERLAY_CANNOT_CONFIRM: {error}"
    payload = _merge_optional_pools(payload, date, overlay, overlay_error)
    rows = payload["rows"]
    status = "READY_WITH_ROWS" if payload.get("producer_status") == "CANONICAL_COMPLETE" else "PARTIAL_WITH_ROWS"
    if not rows:
        return _blocked(date, "Empty output is not promoted to VALID_EMPTY without complete producer evidence.")
    response = {key: payload.get(key, [] if key.endswith("rows") or key == "pools" or key == "cannot_confirm" else {}) for key in ("pools", "unified_rows", "a_source_only_rows", "a_all_pool_rows", "startup_ensure", "strict_0_2_status", "evidence_paths", "cannot_confirm")}
    response.update({"ok": True, "data_status": status, "blocking_reasons": [], "schema_version": "v3_preselection_pools.v1", "trade_date": date, "module_id": "unified_preselection_pools", "write_policy": "read_only", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "recommendation_status": "WATCH_ONLY_BACKTEST_GATED", "pool_count": len(payload.get("pools", [])), "row_count": len(rows), "unified_row_count": len(payload.get("unified_rows", rows)), "a_source_only_row_count": len(payload.get("a_source_only_rows", [])), "a_all_pool_row_count": len(payload.get("a_all_pool_rows", rows)), "rows": []})
    response["market_totals"] = payload.get("market_totals", _market_totals(rows))
    response["hk_pool_version"] = payload.get("hk_pool_version")
    response["hk_pool_role"] = payload.get("hk_pool_role")
    response["unified_rows"] = _limit_per_market(response["unified_rows"], limit); response["a_source_only_rows"] = response["a_source_only_rows"][:limit]; response["a_all_pool_rows"] = response["a_all_pool_rows"][:limit]
    response["pools"] = [{**pool, "rows": _limit_per_market(pool.get("rows", []), limit)} for pool in response["pools"]]
    response["rows"] = [row for pool in response["pools"] for row in pool.get("rows", [])]
    response["optional_pool_status"] = payload.get("optional_pool_status", "CANNOT_CONFIRM")
    return response


_POOL_ORDER = (
    "a_d1_premarket_pool",
    "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool",
    "a_share_research_recommendation_pool",
    "a_share_baimao_research_map",
    "hkconnect_d1_top100",
    "wechat_public_account_v3_preselect",
)
_POOL_NAMES = {
    "a_d1_premarket_pool": "A股 D-1 主预选池",
    "a_d1_fupan_watchlist_pool": "A股 D-1 复盘继续观察池",
    "a_d1_stage7_fenshi_review_pool": "A股 D-1 Stage7/分时复盘池",
    "a_share_research_recommendation_pool": "A股研报推荐股票池",
    "a_share_baimao_research_map": "白毛卡点研究池",
    "hkconnect_d1_top100": "港股通 0.2 D-1 Top100",
    "wechat_public_account_v3_preselect": "公众号股票池",
}


def _restore_flat_migration_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Project the one-time flat import back into the old V3 pool contract.

    This is a read-only compatibility projection.  It does not claim that a
    partial migration is canonical and it never fabricates candidate rows.
    """
    pools = payload.get("pools") or []
    if len(pools) != 1 or pools[0].get("pool_id") != "legacy_partial_migration":
        return payload

    rows = list(payload.get("rows") or pools[0].get("rows") or [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pool_id = str(row.get("pool_id") or "")
        if pool_id:
            grouped.setdefault(pool_id, []).append(row)

    restored_pools = []
    pool_ids = [pool_id for pool_id in _POOL_ORDER if grouped.get(pool_id)]
    pool_ids.extend(sorted(set(grouped) - set(pool_ids)))
    for pool_id in pool_ids:
        pool_rows = grouped[pool_id]
        markets = {_market(row) for row in pool_rows}
        restored_pools.append({
            "pool_id": pool_id,
            "display_name": _POOL_NAMES.get(pool_id, pool_id),
            "market": markets.pop() if len(markets) == 1 else "MIXED",
            "pool_size": len(pool_rows),
            "returned_rows": len(pool_rows),
            "rows": pool_rows,
        })

    main_rows = grouped.get("a_d1_premarket_pool", [])
    all_a_rows = _dedupe_by_symbol(
        row for pool_id in pool_ids if pool_id != "hkconnect_d1_top100"
        for row in grouped.get(pool_id, [])
        if _market(row) == "A"
    )
    main_symbols = {str(row.get("symbol") or row.get("code") or "") for row in main_rows}
    source_only_rows = [
        row for row in all_a_rows
        if str(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    hk_rows = _dedupe_by_symbol(row for row in rows if _market(row) == "HK")

    restored = dict(payload)
    restored.update({
        "pools": restored_pools,
        "unified_rows": list(main_rows),
        "a_source_only_rows": source_only_rows,
        "a_all_pool_rows": all_a_rows,
        "market_totals": {"A": len(all_a_rows), "HK": len(hk_rows)},
        "hk_pool_version": "0.2" if grouped.get("hkconnect_d1_top100") else None,
        "hk_pool_role": "D_MINUS_1_MODEL_TOP100" if grouped.get("hkconnect_d1_top100") else None,
    })
    return restored


def _merge_optional_pools(
    payload: dict[str, Any],
    trade_date: str,
    overlay: dict[str, Any] | None,
    overlay_error: str,
) -> dict[str, Any]:
    """Add graph-defined research lanes without changing selector-owned input."""
    base_pools = [dict(pool) for pool in payload.get("pools", [])]
    by_id = {
        str(pool.get("pool_id") or ""): pool
        for pool in base_pools
        if str(pool.get("pool_id") or "")
    }
    optional = list(overlay["pools"]) if overlay is not None else _optional_placeholders(trade_date)
    for pool in optional:
        pool_id = str(pool["pool_id"])
        if pool_id in by_id:
            if overlay is not None:
                raise ValueError(f"duplicate optional pool identity: {pool_id}")
            continue
        by_id[pool_id] = dict(pool)

    base_ids = [str(pool.get("pool_id") or "") for pool in base_pools if str(pool.get("pool_id") or "")]
    if any(pool_id in _POOL_ORDER for pool_id in base_ids):
        ordered_ids = [pool_id for pool_id in _POOL_ORDER if pool_id in by_id]
        ordered_ids.extend(pool_id for pool_id in base_ids if pool_id not in ordered_ids)
    else:
        ordered_ids = list(base_ids)
        ordered_ids.extend(pool_id for pool_id in _POOL_ORDER if pool_id in by_id and pool_id not in ordered_ids)
    pools = [by_id[pool_id] for pool_id in ordered_ids]
    rows = [row for pool in pools for row in pool.get("rows", [])]
    grouped = {str(pool.get("pool_id") or ""): list(pool.get("rows", [])) for pool in pools}
    main_rows = grouped.get("a_d1_premarket_pool") or list(payload.get("unified_rows", []))
    if grouped.get("a_d1_premarket_pool"):
        all_a_rows = _dedupe_by_symbol(row for row in rows if _market(row) == "A")
    else:
        optional_ids = {"a_share_baimao_research_map", "wechat_public_account_v3_preselect"}
        all_a_rows = _dedupe_by_symbol([
            *list(payload.get("a_all_pool_rows", [])),
            *(row for pool in pools if pool.get("pool_id") in optional_ids for row in pool.get("rows", []) if _market(row) == "A"),
        ])
    main_symbols = {str(row.get("symbol") or row.get("code") or "") for row in main_rows}
    source_only_rows = [
        row for row in all_a_rows
        if str(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    hk_rows = _dedupe_by_symbol(row for row in rows if _market(row) == "HK")
    cannot_confirm = list(payload.get("cannot_confirm", []))
    if overlay is not None:
        cannot_confirm.extend(overlay.get("cannot_confirm", []))
        optional_status = "MATERIALIZED_RESEARCH_ONLY"
    else:
        cannot_confirm.extend([
            overlay_error or "WECHAT_OPTIONAL_POOL_NOT_MATERIALIZED",
            "BAIMAO_RESEARCH_MAP_NOT_FOUND",
        ])
        optional_status = "CANNOT_CONFIRM"
    restored = dict(payload)
    restored.update({
        "pools": pools,
        "rows": rows,
        "unified_rows": main_rows,
        "a_source_only_rows": source_only_rows,
        "a_all_pool_rows": all_a_rows,
        "market_totals": {"A": len(all_a_rows), "HK": len(hk_rows)},
        "cannot_confirm": cannot_confirm,
        "optional_pool_status": optional_status,
    })
    return restored


def _optional_placeholders(trade_date: str) -> list[dict[str, Any]]:
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


def _market(row: dict[str, Any]) -> str:
    explicit = str(row.get("market") or "").upper()
    if explicit in {"A", "HK"}:
        return explicit
    symbol = str(row.get("symbol") or row.get("code") or "").upper()
    return "HK" if symbol.startswith("HK.") else "A" if symbol.startswith("A.") else ""


def _dedupe_by_symbol(rows: Any) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        symbol = str(row.get("symbol") or row.get("code") or "")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        selected.append(row)
    return selected


def _market_totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        market: len(_dedupe_by_symbol(row for row in rows if _market(row) == market))
        for market in ("A", "HK")
    }


def _blocked(date: str, reason: str) -> dict[str, Any]:
    return {"ok": False, "data_status": "DATA_BLOCKED_EMPTY", "blocking_reasons": [reason], "schema_version": "v3_preselection_pools.v1", "trade_date": date, "module_id": "unified_preselection_pools", "write_policy": "read_only", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "recommendation_status": "WATCH_ONLY_BACKTEST_GATED", "pool_count": 0, "row_count": 0, "unified_row_count": 0, "a_source_only_row_count": 0, "a_all_pool_row_count": 0, "pools": [], "unified_rows": [], "a_source_only_rows": [], "a_all_pool_rows": [], "rows": [], "startup_ensure": {}, "strict_0_2_status": "CANNOT_CONFIRM", "evidence_paths": [], "cannot_confirm": [reason]}


def _is_trading_date(value: str) -> bool:
    contract = Path(__file__).resolve().parents[1] / "contracts" / "trading_calendar_2026.json"
    excluded = set(json.loads(contract.read_text(encoding="utf-8"))["known_non_trading_dates"])
    return datetime.strptime(value, "%Y%m%d").weekday() < 5 and value not in excluded


def _limit_per_market(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for market in ("A", "HK"):
        selected.extend([
            row
            for row in rows
            if str(row.get("market") or "").upper() == market
            or str(row.get("symbol") or "").startswith(f"{market}.")
        ][:limit])
    other = [
        row
        for row in rows
        if str(row.get("market") or "").upper() not in {"A", "HK"}
        and not str(row.get("symbol") or "").startswith(("A.", "HK."))
    ]
    selected.extend(other[:limit])
    return selected
