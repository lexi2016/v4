from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import POOL_ORDER, PreselectionPoolStore
from infrastructure.review_core_fupan_pool_source import load_review_core_fupan_pool
from infrastructure.review_core_stage7_pool_source import load_review_core_stage7_pool


def date_catalog(
    store: NativeDataStore,
    *,
    current_date: str | None = None,
) -> dict[str, Any]:
    catalog = store.read_catalog()
    persisted_system_date = str(catalog["system_date"])
    materialized = catalog.get("materialized_rows", {})
    independent_dates = _verified_independent_pool_dates(store)
    wall_date = current_date or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    # The natural-day clock is a runtime fact, not a persisted producer state.
    # A stale catalog must not make an explicit/current date disappear from the
    # date family merely because today's pools are incomplete.
    system_date = wall_date
    candidate_dates = (
        list(catalog["stage_dates"])
        + [date for date, rows in materialized.items() if rows > 0]
        + list(independent_dates)
    )
    evidence_stage = sorted(
        {
            date
            for date in candidate_dates
            if date <= system_date
            and date not in independent_dates
            and _is_trading_date(date)
        }
    )
    stage = list(evidence_stage)
    future = sorted(
        {
            date
            for date in list(catalog["future_target_dates"])
            + list(independent_dates)
            if _is_trading_date(date)
        }
    )
    positive = sorted(
        date
        for date, rows in materialized.items()
        if date <= system_date and rows > 0 and _is_trading_date(date)
    )
    # ``stage_dates`` and ``default_date`` are evidence projections only.  The
    # persisted catalog date is not proof that a same-date artifact exists and
    # must never be promoted merely because the producer catalog is stale.
    default = positive[-1] if positive else (evidence_stage[-1] if evidence_stage else "")
    navigation_dates = set(stage + future)
    if _is_trading_date(system_date):
        # The wall-clock trading date is navigable so the UI can show an
        # explicit DATA_BLOCKED_EMPTY/CANNOT_CONFIRM page, but it is not added
        # to stage_dates or default_date without exact evidence.
        navigation_dates.add(system_date)
    return {
        "ok": True,
        "default_date": default,
        "dates": sorted(navigation_dates, reverse=True),
        "stage_dates": stage,
        "future_target_dates": future,
        "system_date": system_date,
    }


def _verified_independent_pool_dates(store: NativeDataStore) -> tuple[str, ...]:
    """Discover dates with at least one SHA-verified independent pool.

    Pool families are independently published.  Requiring ``read_all`` here
    made one missing optional pool hide a target date whose other artifact
    trio was already complete.
    """
    root = Path(store.root) / "preselection_pools"
    if not root.is_dir():
        return ()
    pool_store = PreselectionPoolStore(store.root)
    dates: list[str] = []
    try:
        children = tuple(root.iterdir())
    except OSError:
        return ()
    for child in children:
        date = child.name
        if not child.is_dir() or len(date) != 8 or not date.isdigit():
            continue
        for pool_id in POOL_ORDER:
            try:
                pool_store.read_pool(date, pool_id)
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                continue
            dates.append(date)
            break
    return tuple(sorted(set(dates)))


def preselection(
    store: NativeDataStore,
    date: str,
    limit: int,
    *,
    allow_legacy_flat: bool = False,
) -> dict[str, Any]:
    independent_store = PreselectionPoolStore(store.root)
    try:
        independent_pools = independent_store.read_all(date)
    except FileNotFoundError:
        independent_pools = []
    except ValueError as error:
        return _blocked(date, f"V3.5 independent pool receipt cannot be confirmed: {error}")
    if independent_pools:
        independent_pools = _replace_review_core_fupan_pool(independent_pools, date)
        independent_pools = _replace_review_core_stage7_pool(independent_pools, date)
        independent_pools = _complete_independent_pool_set(independent_pools, date)
        payload = _project_independent_pools(independent_pools, date)
    else:
        if not allow_legacy_flat:
            return _blocked(
                date,
                "V3.5 independent preselection producers have not materialized this date.",
            )
        try:
            payload = store.read_payload(date)
        except FileNotFoundError:
            return _blocked(date, "V3.5 independent preselection producers have not materialized this date.")
        except ValueError as error:
            return _blocked(date, f"V3.5 pool receipt cannot be confirmed: {error}")
        payload = _replace_payload_review_core_fupan_pool(payload, date)
        payload = _replace_payload_review_core_stage7_pool(payload, date)
        if any(pool.get("pool_id") == "legacy_partial_migration" for pool in payload.get("pools", [])):
            return _blocked(date, "LEGACY_PARTIAL_MIGRATION_REJECTED: final-output imports are oracle-only.")
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


def _complete_independent_pool_set(
    pools: list[dict[str, Any]], trade_date: str
) -> list[dict[str, Any]]:
    """Project missing independent lanes as explicit CANNOT_CONFIRM pools.

    The source artifacts remain immutable and are never synthesized here.  The
    projection only preserves the graph-defined seven-pool surface so one
    verified lane cannot hide the other lanes or force a cross-date fallback.
    """
    by_id = {
        str(pool.get("pool_id") or ""): dict(pool)
        for pool in pools
        if str(pool.get("pool_id") or "")
    }
    completed: list[dict[str, Any]] = []
    for pool_id in POOL_ORDER:
        if pool_id in by_id:
            completed.append(by_id[pool_id])
            continue
        market = "HK" if pool_id == "hkconnect_d1_top100" else (
            "WECHAT" if pool_id == "wechat_public_account_v3_preselect" else "A"
        )
        completed.append({
            "pool_id": pool_id,
            "display_name": _POOL_NAMES.get(pool_id, pool_id),
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
        })
    return completed


def _replace_review_core_fupan_pool(
    pools: list[dict[str, Any]], trade_date: str
) -> list[dict[str, Any]]:
    """Replace the V3.5-local fupan artifact with the exact Review Core DTO."""

    if not any(pool.get("pool_id") == "a_d1_fupan_watchlist_pool" for pool in pools):
        return pools
    review_core_pool = load_review_core_fupan_pool(trade_date)
    # Review Core is an optional oracle for this lane.  A typed unavailable or
    # zero-row response must not erase an already verified native observation
    # pool.  Only an exact-date, safety-clean READY/PARTIAL response with rows
    # may supersede the local artifact.
    if not _usable_review_core_fupan_pool(review_core_pool, trade_date):
        return pools
    return [
        review_core_pool if pool.get("pool_id") == "a_d1_fupan_watchlist_pool" else pool
        for pool in pools
    ]


def _usable_review_core_fupan_pool(pool: Mapping[str, Any], trade_date: str) -> bool:
    if not isinstance(pool, Mapping):
        return False
    if pool.get("pool_id") != "a_d1_fupan_watchlist_pool":
        return False
    if pool.get("market") != "A" or pool.get("target_date") not in (None, trade_date):
        return False
    if pool.get("status") not in {"READY", "PARTIAL"}:
        return False
    rows = pool.get("rows")
    if not isinstance(rows, list) or not rows or pool.get("row_count") != len(rows):
        return False
    if pool.get("source_merge_role") != "SOURCE_ONLY" or pool.get("stage_selection_eligible") is not False:
        return False
    if any(pool.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    flags = pool.get("safety_flags")
    if not isinstance(flags, Mapping) or any(flags.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping) or ("rank" in row and row.get("rank") != index):
            return False
        if row.get("source_merge_role") != "SOURCE_ONLY" or row.get("stage_selection_eligible") is not False:
            return False
        if any(name in row and row.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")):
            return False
        row_flags = row.get("safety_flags")
        if row_flags is not None and (
            not isinstance(row_flags, Mapping)
            or any(row_flags.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent"))
        ):
            return False
    return True


def _replace_payload_review_core_fupan_pool(
    payload: dict[str, Any], trade_date: str
) -> dict[str, Any]:
    """Apply the same exact-date replacement to a legacy payload projection."""

    pools = payload.get("pools")
    if not isinstance(pools, list) or not any(
        isinstance(pool, dict) and pool.get("pool_id") == "a_d1_fupan_watchlist_pool"
        for pool in pools
    ):
        return payload
    replaced = _replace_review_core_fupan_pool([dict(pool) for pool in pools], trade_date)
    if [pool.get("pool_id") for pool in replaced] == list(POOL_ORDER):
        projected = _project_independent_pools(replaced, trade_date)
        restored = dict(payload)
        restored.update(projected)
        return restored
    restored = dict(payload)
    restored["pools"] = replaced
    restored["rows"] = [row for pool in replaced for row in pool.get("rows", [])]
    restored["a_all_pool_rows"] = _dedupe_by_symbol(
        row for row in restored["rows"] if _market(row) == "A"
    )
    main = next(
        (pool for pool in replaced if pool.get("pool_id") == "a_d1_premarket_pool"),
        None,
    )
    restored["unified_rows"] = list(main.get("rows", [])) if main else []
    main_symbols = {str(row.get("symbol") or row.get("code") or "") for row in restored["unified_rows"]}
    restored["a_source_only_rows"] = [
        row for row in restored["a_all_pool_rows"]
        if str(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    restored["market_totals"] = _market_totals(restored["rows"])
    return restored


def _replace_review_core_stage7_pool(
    pools: list[dict[str, Any]], trade_date: str
) -> list[dict[str, Any]]:
    """Replace the native Stage7 artifact only with a verified external DTO."""

    if not any(pool.get("pool_id") == "a_d1_stage7_fenshi_review_pool" for pool in pools):
        return pools
    review_core_pool = load_review_core_stage7_pool(trade_date)
    if not _usable_review_core_stage7_pool(review_core_pool, trade_date):
        return pools
    return [
        review_core_pool if pool.get("pool_id") == "a_d1_stage7_fenshi_review_pool" else pool
        for pool in pools
    ]


def _usable_review_core_stage7_pool(pool: Mapping[str, Any], trade_date: str) -> bool:
    """Accept only an exact, safety-clean, non-empty Review Core Stage7 DTO."""

    if not isinstance(pool, Mapping):
        return False
    if pool.get("pool_id") != "a_d1_stage7_fenshi_review_pool":
        return False
    if pool.get("market") != "A" or pool.get("target_date") != trade_date:
        return False
    if pool.get("status") not in {"READY", "PARTIAL"}:
        return False
    rows = pool.get("rows")
    if not isinstance(rows, list) or not rows or pool.get("row_count") != len(rows):
        return False
    if pool.get("source_merge_role") != "SOURCE_ONLY" or pool.get("stage_selection_eligible") is not False:
        return False
    if any(pool.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    flags = pool.get("safety_flags")
    if not isinstance(flags, Mapping) or any(
        flags.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")
    ):
        return False
    for row in rows:
        if not isinstance(row, Mapping):
            return False
        if row.get("source_merge_role") != "SOURCE_ONLY" or row.get("stage_selection_eligible") is not False:
            return False
        if any(row.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")):
            return False
        row_flags = row.get("safety_flags")
        if row_flags is not None and (
            not isinstance(row_flags, Mapping)
            or any(
                row_flags.get(name) is not False
                for name in ("production_allowed", "buy_gate_updated", "orders_sent")
            )
        ):
            return False
    return True


def _replace_payload_review_core_stage7_pool(
    payload: dict[str, Any], trade_date: str
) -> dict[str, Any]:
    """Apply the same exact-date Stage7 replacement to a legacy payload."""

    pools = payload.get("pools")
    if not isinstance(pools, list) or not any(
        isinstance(pool, dict) and pool.get("pool_id") == "a_d1_stage7_fenshi_review_pool"
        for pool in pools
    ):
        return payload
    replaced = _replace_review_core_stage7_pool([dict(pool) for pool in pools], trade_date)
    if [pool.get("pool_id") for pool in replaced] == list(POOL_ORDER):
        projected = _project_independent_pools(replaced, trade_date)
        restored = dict(payload)
        restored.update(projected)
        return restored
    restored = dict(payload)
    restored["pools"] = replaced
    restored["rows"] = [row for pool in replaced for row in pool.get("rows", [])]
    restored["a_all_pool_rows"] = _dedupe_by_symbol(
        row for row in restored["rows"] if _market(row) == "A"
    )
    main = next(
        (pool for pool in replaced if pool.get("pool_id") == "a_d1_premarket_pool"),
        None,
    )
    restored["unified_rows"] = list(main.get("rows", [])) if main else []
    main_symbols = {str(row.get("symbol") or row.get("code") or "") for row in restored["unified_rows"]}
    restored["a_source_only_rows"] = [
        row for row in restored["a_all_pool_rows"]
        if str(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    restored["market_totals"] = _market_totals(restored["rows"])
    return restored


def _project_independent_pools(pools: list[dict[str, Any]], trade_date: str) -> dict[str, Any]:
    projected_pools: list[dict[str, Any]] = []
    for pool in pools:
        rows = list(pool["rows"])
        projected_pools.append({
            **pool,
            "pool_size": len(rows),
            "returned_rows": len(rows),
        })
    grouped = {pool["pool_id"]: list(pool["rows"]) for pool in projected_pools}
    all_rows = [row for pool in projected_pools for row in pool["rows"]]
    main_rows = grouped["a_d1_premarket_pool"]
    all_a_rows = _dedupe_by_symbol(row for row in all_rows if _market(row) == "A")
    main_symbols = {str(row.get("symbol") or row.get("code") or "") for row in main_rows}
    source_only = [
        row for row in all_a_rows
        if str(row.get("symbol") or row.get("code") or "") not in main_symbols
    ]
    hk_rows = _dedupe_by_symbol(row for row in all_rows if _market(row) == "HK")
    incomplete = [
        pool["pool_id"] for pool in projected_pools
        if pool.get("status") in {"CANNOT_CONFIRM", "MISSING"}
    ]
    return {
        "producer_status": "PARTIAL" if incomplete else "CANONICAL_COMPLETE",
        "pools": projected_pools,
        "rows": all_rows,
        "unified_rows": main_rows,
        "a_source_only_rows": source_only,
        "a_all_pool_rows": all_a_rows,
        "market_totals": {"A": len(all_a_rows), "HK": len(hk_rows)},
        "hk_pool_version": "0.2",
        "hk_pool_role": "D_MINUS_1_MODEL_TOP100",
        "startup_ensure": {},
        "strict_0_2_status": next(pool["status"] for pool in projected_pools if pool["pool_id"] == "hkconnect_d1_top100"),
        "evidence_paths": [
            str(pool.get("source_path") or "")
            for pool in projected_pools
            if pool.get("source_path")
        ],
        "cannot_confirm": [reason for pool in projected_pools for reason in pool.get("cannot_confirm", [])],
        "optional_pool_status": "CANNOT_CONFIRM" if incomplete else "MATERIALIZED_RESEARCH_ONLY",
        "trade_date": trade_date,
    }


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

_POOL_SOURCE_CONTRACT = {
    "a_d1_premarket_pool": ("V192_SELECTOR", "（选）", "selector_lane"),
    "a_d1_fupan_watchlist_pool": ("D1_FUPAN", "（复）", "fupan_lane"),
    "a_d1_stage7_fenshi_review_pool": ("D1_STAGE7", "（分）", "stage7_lane"),
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


def _canonical_a_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("A."):
        text = text[2:]
    elif text.startswith("HK."):
        return ""
    if text.endswith((".SH", ".SZ", ".BJ")):
        text = text[:-3]
    return f"A.{text}" if re.fullmatch(r"\d{6}", text) else ""


def _canonical_a_symbol(row: dict[str, Any]) -> str:
    market = str(row.get("market") or "").strip().upper()
    if market in {"HK", "HK_CONNECT", "HKCONNECT", "港股", "港股通"}:
        return ""
    candidates = {
        canonical
        for key in ("symbol", "normalized_code", "code", "stock_code", "ts_code")
        if (canonical := _canonical_a_code(row.get(key)))
    }
    return candidates.pop() if len(candidates) == 1 else ""


def _market(row: dict[str, Any]) -> str:
    explicit = str(row.get("market") or "").upper()
    if explicit in {"A", "HK"}:
        return explicit
    symbol = str(row.get("symbol") or row.get("code") or "").upper()
    if symbol.startswith("HK."):
        return "HK"
    return "A" if _canonical_a_symbol(row) else ""


def _dedupe_by_symbol(rows: Any) -> list[dict[str, Any]]:
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


def _ensure_source_contract(row: dict[str, Any]) -> None:
    """Fill the evidenced old-V3 source fields without changing row values."""

    source_tag, source_suffix, source_lane = _pool_source_metadata(row)
    if not row.get("display_name") and source_suffix:
        stock_name = str(row.get("stock_name") or row.get("name") or row.get("symbol") or "")
        row["display_name"] = f"{stock_name}{source_suffix}"
    if not _metadata_values(row.get("source_tag")) and source_tag:
        row["source_tag"] = source_tag
    if not _metadata_values(row.get("source_tags")) and source_suffix:
        row["source_tags"] = source_suffix
    if not _metadata_values(row.get("source_lanes")) and source_lane:
        row["source_lanes"] = source_lane


def _merge_source_contract(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge provenance while keeping the first row's rank, score, and name."""

    _ensure_source_contract(target)
    incoming_row = dict(incoming)
    _ensure_source_contract(incoming_row)
    for field in ("source_tags", "source_lanes", "source_trace"):
        values = _ordered_metadata_values(
            [*_metadata_values(target.get(field)), *_metadata_values(incoming_row.get(field))]
        )
        if values:
            target[field] = " / ".join(values)


def _pool_source_metadata(row: dict[str, Any]) -> tuple[str, str, str]:
    metadata = _POOL_SOURCE_CONTRACT.get(str(row.get("pool_id") or ""))
    return metadata if metadata is not None else ("", "", "")


def _metadata_values(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            values.extend(_metadata_values(item))
        return values
    if isinstance(value, dict):
        return _metadata_values(list(value))
    text = str(value or "").strip()
    if not text:
        return []
    text = re.sub(r"\s+(?:/|\|)\s+", "\n", text)
    return [item.strip() for item in text.splitlines() if item.strip()]


def _ordered_metadata_values(values: Any) -> list[str]:
    ordered: list[str] = []
    for value in values if isinstance(values, (list, tuple, set)) else [values]:
        for item in _metadata_values(value):
            if item not in ordered:
                ordered.append(item)
    return ordered


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
