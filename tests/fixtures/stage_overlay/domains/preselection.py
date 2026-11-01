from __future__ import annotations

import hashlib
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
from stage_center.commit_store import (
    STRICT_PUBLICATION_MODE,
    StageCommitStore,
    publication_mode,
    runtime_config,
)
from stage_center.selection import SelectionError, SelectionStore
from stage_center.contracts import STAGE_BY_ID


OPTIONAL_DAILY_POOL_IDS = frozenset(
    {
        "a_share_baimao_research_map",
        "wechat_public_account_v3_preselect",
    }
)


def date_catalog(
    store: NativeDataStore,
    *,
    current_date: str | None = None,
    stage_selection_root: Path | str | None = None,
) -> dict[str, Any]:
    catalog = store.read_catalog()
    persisted_system_date = str(catalog["system_date"])
    materialized = catalog.get("materialized_rows", {})
    independent_dates = _verified_independent_pool_dates(store)
    stage_artifacts = _verified_stage_artifact_catalog(stage_selection_root)
    stage_artifact_dates = tuple(stage_artifacts)
    wall_date = current_date or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    # The natural-day clock is a runtime fact, not a persisted producer state.
    # A stale catalog must not make an explicit/current date disappear from the
    # date family merely because today's pools are incomplete.
    system_date = wall_date
    candidate_dates = (
        list(catalog["stage_dates"])
        + [date for date, rows in materialized.items() if rows > 0]
        + list(independent_dates)
        + list(stage_artifact_dates)
    )
    # Independent pool materialization and stage-center artifacts are separate
    # evidence lanes. A shared date must remain visible when either lane is
    # present; do not let an independent pool date hide an exact stage date.
    evidence_stage = sorted(
        {
            date
            for date in (
                list(catalog["stage_dates"])
                + [date for date, rows in materialized.items() if rows > 0]
                + list(stage_artifact_dates)
            )
            if date <= system_date and _is_trading_date(date)
        }
    )
    stage = list(evidence_stage)
    future = sorted(
        {
            date
            for date in list(catalog["future_target_dates"])
            + list(independent_dates)
            # Producer target dates are relative to the persisted catalog
            # clock.  The wall date still controls current-date navigation;
            # retaining this distinction keeps a verified target visible when
            # the catalog itself is stale by one or more days.
            if date > persisted_system_date
            if _is_trading_date(date)
        }
    )
    # ``stage_dates`` and ``default_date`` are evidence projections only.  The
    # persisted catalog date is not proof that a same-date artifact exists and
    # must never be promoted merely because the producer catalog is stale.
    # The legacy pool-import lane can freeze while the verified stage-center
    # lane keeps producing, so the default is the newest date with materialized
    # pool rows or a verified stage artifact -- never the newest date of the
    # legacy lane alone, and never a stage-list date without rows or artifacts.
    default_candidates = sorted(
        {
            date
            for date, rows in materialized.items()
            if rows > 0 and date <= system_date and _is_trading_date(date)
        }
        | {
            date
            for date, item in stage_artifacts.items()
            if str(item.get("status")) in ("MATERIALIZED", "PARTIAL")
            if date <= system_date and _is_trading_date(date)
        }
    )
    default = (
        default_candidates[-1]
        if default_candidates
        else (evidence_stage[-1] if evidence_stage else "")
    )
    navigation_dates = set(stage + future + list(stage_artifact_dates))
    if _is_trading_date(system_date):
        # The wall-clock trading date is navigable so the UI can show an
        # explicit DATA_BLOCKED_EMPTY/CANNOT_CONFIRM page, but it is not added
        # to stage_dates or default_date without exact evidence.
        navigation_dates.add(system_date)
    materialized_stage_dates = sorted(
        date for date, item in stage_artifacts.items()
        if item.get("status") == "MATERIALIZED"
    )
    partial_stage_dates = sorted(
        date for date, item in stage_artifacts.items()
        if item.get("status") == "PARTIAL"
    )
    blocked_stage_dates = sorted(
        date for date, item in stage_artifacts.items()
        if item.get("status") == "BLOCKED"
    )
    return {
        "ok": True,
        "default_date": default,
        # Navigation is not artifact evidence. Keep the original default_date
        # contract while allowing the current Shanghai trading day to be empty.
        "navigation_date": system_date if _is_trading_date(system_date) else default,
        "navigation_timezone": "Asia/Shanghai",
        "navigation_policy": "SHANGHAI_TRADING_DAY_ELSE_EVIDENCE_DEFAULT",
        "dates": sorted(navigation_dates, reverse=True),
        "stage_dates": stage,
        "future_target_dates": future,
        "system_date": system_date,
        "stage_artifacts": stage_artifacts,
        "materialized": materialized_stage_dates,
        "partial": partial_stage_dates,
        "blocked": blocked_stage_dates,
        "materialized_stage_dates": materialized_stage_dates,
        "partial_stage_dates": partial_stage_dates,
        "blocked_stage_dates": blocked_stage_dates,
    }


def _verified_stage_artifact_catalog(
    stage_selection_root: Path | str | None,
) -> dict[str, dict[str, Any]]:
    """Project exact-date stage artifacts from the existing selection root.

    This is deliberately a read-only view of the stage-center latest pointer.
    A date is ``MATERIALIZED`` only when at least one pointer entry verifies
    its immutable run trio; invalid entries remain visible as ``BLOCKED``.
    No date or stage artifact is copied into the data store.
    """
    if stage_selection_root is None:
        return {}
    policy = runtime_config()
    mode = publication_mode(policy)
    if mode == STRICT_PUBLICATION_MODE:
        try:
            configured_root = Path(str(policy.get("selection_root") or "")).expanduser().resolve()
            observed_root = Path(stage_selection_root).expanduser().resolve()
            receipt_root = Path(str(policy.get("receipt_root") or "")).expanduser()
            if configured_root != observed_root or not receipt_root.is_absolute():
                return {}
            return StageCommitStore(receipt_root).catalog()
        except (OSError, TypeError, ValueError):
            return {}
    if mode != "legacy":
        # An unreadable or unknown packaged policy cannot silently reopen the
        # legacy selection_latest catalog.
        return {}
    root = Path(stage_selection_root).expanduser()
    try:
        latest = SelectionStore(root)._latest()
    except (OSError, SelectionError, ValueError, TypeError):
        return {}
    entries = latest.get("entries")
    if not isinstance(entries, Mapping):
        return {}
    by_date: dict[str, dict[str, Any]] = {}
    store = SelectionStore(root)
    for key, entry in entries.items():
        if not isinstance(key, str) or not isinstance(entry, Mapping):
            continue
        parts = key.split("/")
        if len(parts) != 3 or not re.fullmatch(r"\d{8}", parts[0]):
            continue
        trade_date, stage_id, market = parts
        item = by_date.setdefault(
            trade_date,
            {
                "status": "BLOCKED",
                "trade_date": trade_date,
                "stage_ids": [],
                "markets": [],
                "verified_markets": [],
                "expected_markets": {},
                "missing_markets": [],
                "verified_entries": 0,
                "blocked_entries": 0,
                "receipt_paths": [],
                "artifact_ids": [],
                "cannot_confirm": [],
            },
        )
        if stage_id not in item["stage_ids"]:
            item["stage_ids"].append(stage_id)
        if market not in item["markets"]:
            item["markets"].append(market)
        try:
            envelope = store.read_verified(trade_date, stage_id, market)
        except (OSError, SelectionError, ValueError, TypeError) as error:
            item["blocked_entries"] += 1
            item["cannot_confirm"].append(f"STAGE_ARTIFACT_INVALID:{stage_id}:{market}:{type(error).__name__}")
            continue
        item["verified_entries"] += 1
        item["verified_markets"].append(market)
        item["receipt_paths"].append(
            f"selection_runs/{trade_date}/{market}_SELECTION_{stage_id}/{entry.get('run_id', '')}/receipt.json"
        )
        artifact_id = envelope.get("artifact_id")
        if artifact_id:
            item["artifact_ids"].append(str(artifact_id))
        selection_status = str(envelope.get("selection_status") or "CANNOT_CONFIRM")
        if selection_status in {"CANNOT_CONFIRM", "PARTIAL_WITH_ROWS"}:
            item["cannot_confirm"].extend(str(reason) for reason in envelope.get("cannot_confirm") or [])
    for item in by_date.values():
        verified_by_stage: dict[str, set[str]] = {}
        for key, entry in entries.items():
            if not isinstance(key, str) or not isinstance(entry, Mapping):
                continue
            parts = key.split("/")
            if len(parts) != 3 or parts[0] != item["trade_date"]:
                continue
            stage_id, market = parts[1], parts[2]
            if stage_id not in STAGE_BY_ID:
                continue
            try:
                store.read_verified(item["trade_date"], stage_id, market)
            except (OSError, SelectionError, ValueError, TypeError):
                continue
            verified_by_stage.setdefault(stage_id, set()).add(market)
        for stage_id in item["stage_ids"]:
            expected = tuple(STAGE_BY_ID[stage_id].markets) if stage_id in STAGE_BY_ID else ()
            item["expected_markets"][stage_id] = list(expected)
            missing = sorted(set(expected) - verified_by_stage.get(stage_id, set()))
            for market in missing:
                item["missing_markets"].append(f"{stage_id}:{market}")
                item["cannot_confirm"].append(f"STAGE_MARKET_MISSING:{stage_id}:{market}")
        if item["verified_entries"] == 0:
            item["status"] = "BLOCKED"
        elif item["blocked_entries"] or item["cannot_confirm"]:
            item["status"] = "PARTIAL"
        else:
            item["status"] = "MATERIALIZED"
        item["stage_ids"] = sorted(set(item["stage_ids"]))
        item["markets"] = sorted(set(item["markets"]))
        item["verified_markets"] = sorted(set(item["verified_markets"]))
        item["expected_markets"] = {
            stage_id: sorted(set(markets))
            for stage_id, markets in item["expected_markets"].items()
        }
        item["missing_markets"] = sorted(set(item["missing_markets"]))
        item["receipt_paths"] = sorted(set(item["receipt_paths"]))
        item["artifact_ids"] = sorted(set(item["artifact_ids"]))
        item["cannot_confirm"] = sorted(set(item["cannot_confirm"]))
    return dict(sorted(by_date.items()))


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
    offset: int = 0,
    allow_legacy_flat: bool = False,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("preselection page limit must be positive")
    if offset < 0:
        raise ValueError("preselection page offset cannot be negative")
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
            existing = by_id[pool_id]
            existing["optional"] = pool_id in OPTIONAL_DAILY_POOL_IDS
            existing["required_for_daily_readiness"] = pool_id not in OPTIONAL_DAILY_POOL_IDS
            existing["readiness_role"] = (
                "OPTIONAL_RESEARCH" if pool_id in OPTIONAL_DAILY_POOL_IDS else "MANDATORY_DAILY"
            )
            completed.append(existing)
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
            "optional": pool_id in OPTIONAL_DAILY_POOL_IDS,
            "required_for_daily_readiness": pool_id not in OPTIONAL_DAILY_POOL_IDS,
            "readiness_role": (
                "OPTIONAL_RESEARCH" if pool_id in OPTIONAL_DAILY_POOL_IDS else "MANDATORY_DAILY"
            ),
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
        status = str(pool.get("status") or "").upper()
        ready_status = bool(rows) and (
            status in {"READY", "MATERIALIZED", "AVAILABLE"}
            or status.endswith("_READY")
        )
        projected = dict(pool)
        if not ready_status and pool.get("pool_id") not in OPTIONAL_DAILY_POOL_IDS:
            reasons = list(projected.get("cannot_confirm") or ())
            reason = f"POOL_NOT_READY:{pool.get('pool_id')}:{status or 'UNKNOWN'}"
            if reason not in reasons:
                reasons.append(reason)
            projected["cannot_confirm"] = reasons
        projected_pools.append({
            **projected,
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
        if not (
            bool(pool.get("rows"))
            and (
                str(pool.get("status") or "").upper() in {"READY", "MATERIALIZED", "AVAILABLE"}
                or str(pool.get("status") or "").upper().endswith("_READY")
            )
        )
    ]
    mandatory_incomplete = [
        pool_id for pool_id in incomplete if pool_id not in OPTIONAL_DAILY_POOL_IDS
    ]
    optional_incomplete = [
        pool_id for pool_id in incomplete if pool_id in OPTIONAL_DAILY_POOL_IDS
    ]
    daily_readiness_status = "PARTIAL_WITH_ROWS" if mandatory_incomplete else "READY_WITH_ROWS"
    return {
        "producer_status": "PARTIAL" if mandatory_incomplete else "CANONICAL_COMPLETE",
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
        "optional_pool_status": "CANNOT_CONFIRM" if optional_incomplete else "MATERIALIZED_RESEARCH_ONLY",
        "daily_readiness_status": daily_readiness_status,
        "mandatory_incomplete_pool_ids": mandatory_incomplete,
        "optional_incomplete_pool_ids": optional_incomplete,
        "mandatory_pool_ids": [pool_id for pool_id in _POOL_ORDER if pool_id not in OPTIONAL_DAILY_POOL_IDS],
        "optional_pool_ids": [pool_id for pool_id in _POOL_ORDER if pool_id in OPTIONAL_DAILY_POOL_IDS],
        "blocking_reasons": [
            reason
            for pool in projected_pools
            if pool.get("pool_id") not in OPTIONAL_DAILY_POOL_IDS
            for reason in pool.get("cannot_confirm", [])
        ],
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


def _input_fingerprint(pools: Any, trade_date: str) -> str:
    """Hash the read-only pool inputs so paged reads cannot mix snapshots.

    The fingerprint reuses each artifact's source digest and includes the
    returned rows as a defensive check for an in-place materialization whose
    source metadata was not updated.  It is a read contract only; it never
    creates or binds a new producer artifact.
    """
    entries = []
    for pool in pools if isinstance(pools, list) else []:
        if not isinstance(pool, Mapping):
            continue
        entries.append({
            "pool_id": str(pool.get("pool_id") or ""),
            "trade_date": str(pool.get("trade_date") or trade_date),
            "source_sha256": str(pool.get("source_sha256") or ""),
            "source_artifact_sha256": str(pool.get("source_artifact_sha256") or ""),
            "rows": pool.get("rows", []),
        })
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _blocked(date: str, reason: str) -> dict[str, Any]:
    return {"ok": False, "data_status": "DATA_BLOCKED_EMPTY", "blocking_reasons": [reason], "schema_version": "v3_preselection_pools.v1", "trade_date": date, "module_id": "unified_preselection_pools", "write_policy": "read_only", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "recommendation_status": "WATCH_ONLY_BACKTEST_GATED", "pool_count": 0, "row_count": 0, "unified_row_count": 0, "a_source_only_row_count": 0, "a_all_pool_row_count": 0, "pools": [], "unified_rows": [], "a_source_only_rows": [], "a_all_pool_rows": [], "rows": [], "startup_ensure": {}, "strict_0_2_status": "CANNOT_CONFIRM", "evidence_paths": [], "cannot_confirm": [reason], "input_fingerprint": None, "source_digests": {}}


def _is_trading_date(value: str) -> bool:
    contract = Path(__file__).resolve().parents[1] / "contracts" / "trading_calendar_2026.json"
    excluded = set(json.loads(contract.read_text(encoding="utf-8"))["known_non_trading_dates"])
    return datetime.strptime(value, "%Y%m%d").weekday() < 5 and value not in excluded


def _page_metadata(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    offset: int,
    status: str = "",
) -> dict[str, Any]:
    buckets = _market_buckets(rows)
    returned_rows = sum(
        len(bucket[offset:offset + limit])
        for bucket in buckets.values()
    )
    has_more = any(offset + limit < len(bucket) for bucket in buckets.values())
    incomplete_statuses = {"CANNOT_CONFIRM", "MISSING", "NOT_MATERIALIZED", "DATA_BLOCKED_EMPTY"}
    return {
        "total_rows": len(rows),
        "offset": offset,
        "limit": limit,
        "returned_rows": returned_rows,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "complete": not has_more and status.upper() not in incomplete_statuses,
    }


def _market_buckets(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets = {"A": [], "HK": [], "OTHER": []}
    for row in rows:
        market = str(row.get("market") or "").upper()
        symbol = str(row.get("symbol") or "")
        if market == "A" or symbol.startswith("A."):
            buckets["A"].append(row)
        elif market == "HK" or symbol.startswith("HK."):
            buckets["HK"].append(row)
        else:
            buckets["OTHER"].append(row)
    return buckets


def _page_per_market(rows: list[dict[str, Any]], limit: int, offset: int = 0) -> list[dict[str, Any]]:
    buckets = _market_buckets(rows)
    selected: list[dict[str, Any]] = []
    for bucket in ("A", "HK", "OTHER"):
        selected.extend(buckets[bucket][offset:offset + limit])
    return selected


def _limit_per_market(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return _page_per_market(rows, limit, 0)
