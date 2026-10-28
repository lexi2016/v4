from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from contracts.trading_calendar import (
    TradingDayState as CalendarTradingDayState,
    load_market_calendar,
    resolve_market_states as resolve_contract_market_states,
)
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import (
    POOL_ORDER,
    PreselectionPoolIntegrityError,
    PreselectionPoolStore,
    PreselectionSourceResolver,
)
from infrastructure.review_core_fupan_pool_source import load_review_core_fupan_pool
from infrastructure.review_core_stage7_pool_source import load_review_core_stage7_pool
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
    preselection_source_root: Path | str | None = None,
) -> dict[str, Any]:
    from domains._preselection_parts.date_catalog import _date_catalog_body as _v4_impl
    return _v4_impl(
        globals(),
        store,
        current_date=current_date,
        stage_selection_root=stage_selection_root,
        preselection_source_root=preselection_source_root,
    )


def _verified_stage_artifact_catalog(
    stage_selection_root: Path | str | None,
) -> dict[str, dict[str, Any]]:
    """Project exact-date stage artifacts from the existing selection root.

    This is deliberately a read-only view of the stage-center latest pointer.
    A date is ``MATERIALIZED`` only when at least one pointer entry verifies
    its immutable run trio; invalid entries remain visible as ``BLOCKED``.
    No date or stage artifact is copied into the data store.
    """
    from domains._preselection_parts.date_catalog import __verified_stage_artifact_catalog_body as _v4_impl
    return _v4_impl(globals(), stage_selection_root)


def _verified_independent_pool_dates(
    store: NativeDataStore,
    *,
    preselection_source_root: Path | str | None = None,
    include_evidence: bool = False,
) -> tuple[str, ...] | tuple[tuple[str, ...], dict[str, Any]]:
    """Discover dates with at least one SHA-verified independent pool.

    Pool families are independently published.  Requiring ``read_all`` here
    made one missing optional pool hide a target date whose other artifact
    trio was already complete.
    """
    from domains._preselection_parts.date_catalog import __verified_independent_pool_dates_body as _v4_impl
    return _v4_impl(
        globals(),
        store,
        preselection_source_root=preselection_source_root,
        include_evidence=include_evidence,
    )


def preselection(
    store: NativeDataStore,
    date: str,
    limit: int,
    *,
    offset: int = 0,
    allow_legacy_flat: bool = False,
    preselection_source_root: Path | str | None = None,
) -> dict[str, Any]:
    from domains._preselection_parts.pool_assembly import _preselection_body as _v4_impl
    from infrastructure import preselection_pool_sources as pool_source_reader
    import infrastructure.preselection_pool_store as pool_store_api

    scope = globals()
    pool_read_evidence: dict[str, Any] = {}

    class _ResolvedPoolStore:
        """Keep the assembler's read_all port over verified locked snapshots."""

        def __init__(self, root: Path | str) -> None:
            self._resolver = PreselectionSourceResolver(
                root,
                source_root=preselection_source_root,
            )

        def read_all(self, trade_date: str) -> list[dict[str, Any]]:
            date = pool_store_api._date(trade_date)
            snapshots, integrity_errors = pool_source_reader.read_all_with_quarantine(
                self._resolver,
                date,
                _api=pool_store_api,
            )
            owner = self._resolver.root_for_date(date)
            pool_by_id: dict[str, dict[str, Any]] = {}
            legacy_pool_source_bindings: dict[str, dict[str, Any]] = {}
            projection_source_pools: dict[str, dict[str, Any]] = {}
            legacy_snapshot_fields = (
                "physical_source_root",
                "artifact_relative",
                "manifest_relative",
                "receipt_relative",
                "artifact_raw_sha256",
                "manifest_raw_sha256",
                "receipt_raw_sha256",
            )
            for snapshot in snapshots:
                artifact = snapshot.get("artifact")
                pool_id = artifact.get("pool_id") if isinstance(artifact, Mapping) else None
                if pool_id not in POOL_ORDER or pool_id in pool_by_id:
                    raise ValueError("configured preselection snapshot pool identity is invalid")
                if any(field not in snapshot for field in legacy_snapshot_fields):
                    raise ValueError("configured preselection snapshot binding is incomplete")
                cannot_confirm: list[str] = []
                if pool_id == "hkconnect_d1_top100":
                    canonical_pool = (
                        artifact.get("schema_version") == "v3_5.preselection_pool.v1"
                    )
                    if "target_date" in artifact and artifact.get("target_date") != date:
                        cannot_confirm.append(
                            "HK_D1_EXPLICIT_target_date_MISSING_OR_MISMATCH"
                        )
                    elif "target_date" not in artifact and not canonical_pool:
                        cannot_confirm.append(
                            "HK_D1_EXPLICIT_target_date_MISSING_OR_MISMATCH"
                        )
                    if (
                        "stage_selection_eligible" in artifact
                        and artifact.get("stage_selection_eligible") is not True
                    ):
                        cannot_confirm.append(
                            "HK_D1_EXPLICIT_stage_selection_eligible_NOT_TRUE"
                        )
                    elif "stage_selection_eligible" not in artifact and not canonical_pool:
                        cannot_confirm.append(
                            "HK_D1_EXPLICIT_stage_selection_eligible_NOT_TRUE"
                        )
                legacy_binding = {
                    field: snapshot[field] for field in legacy_snapshot_fields
                }
                legacy_binding.update(
                    {
                        "trade_date": date,
                        "target_date": artifact.get("target_date"),
                        "source_sha256": artifact["source_sha256"],
                        "source_role": artifact["source_role"],
                        "source_run_id": artifact.get("source_run_id"),
                        "stage_selection_eligible": artifact.get(
                            "stage_selection_eligible"
                        ),
                        "physical_status": "TRIO_VERIFIED",
                        "cannot_confirm": cannot_confirm,
                        "stage_reuse_status": (
                            "CANNOT_CONFIRM"
                            if cannot_confirm
                            else "REQUIRES_STAGE_CONTRACT_VALIDATION"
                        ),
                    }
                )
                legacy_pool_source_bindings[str(pool_id)] = legacy_binding
                projection_source_pools[str(pool_id)] = dict(artifact)
                pool_by_id[pool_id] = {
                    "pool_id": pool_id,
                    "market_lane": "HK_CONNECT" if pool_id == "hkconnect_d1_top100" else "A_SHARE",
                    "market": artifact.get("market"),
                    "status": "VERIFIED",
                    "source_role": artifact.get("source_role"),
                    "source_sha256": artifact.get("source_sha256"),
                    "pool_sha256": snapshot.get("pool_sha256"),
                    "physical_source_root": snapshot.get("physical_source_root", str(owner)),
                    "diagnostics": [],
                }
            for error in integrity_errors:
                if not isinstance(error, PreselectionPoolIntegrityError):
                    raise ValueError("configured preselection quarantine outcome is untyped")
                if error.pool_id not in POOL_ORDER or error.pool_id in pool_by_id:
                    raise ValueError("configured preselection quarantine pool identity is invalid")
                pool_by_id[error.pool_id] = {
                    "pool_id": error.pool_id,
                    "market_lane": "HK_CONNECT" if error.pool_id == "hkconnect_d1_top100" else "A_SHARE",
                    "market": "HK" if error.pool_id == "hkconnect_d1_top100" else "A",
                    "status": "CANNOT_CONFIRM",
                    "source_role": None,
                    "source_sha256": None,
                    "pool_sha256": None,
                    "physical_source_root": str(owner),
                    "diagnostics": [f"PRESELECTION_POOL_INTEGRITY:{error.pool_id}:{error.reason}"],
                }
            for pool_id in POOL_ORDER:
                if pool_id not in pool_by_id:
                    pool_by_id[pool_id] = {
                        "pool_id": pool_id,
                        "market_lane": "HK_CONNECT" if pool_id == "hkconnect_d1_top100" else "A_SHARE",
                        "market": "HK" if pool_id == "hkconnect_d1_top100" else "A",
                        "status": "MISSING",
                        "source_role": None,
                        "source_sha256": None,
                        "pool_sha256": None,
                        "physical_source_root": str(owner),
                        "diagnostics": [f"POOL_NOT_AVAILABLE:{pool_id}"],
                    }
            pool_read_evidence[date] = {
                "trade_date": date,
                "physical_source_root": str(owner),
                "pools": pool_by_id,
            }
            if preselection_source_root is not None:
                pool_read_evidence[date]["_legacy_pool_source_bindings"] = (
                    legacy_pool_source_bindings
                )
                pool_read_evidence[date]["_projection_source_pools"] = (
                    projection_source_pools
                )

            pools = [snapshot["artifact"] for snapshot in snapshots]
            pools.extend(
                _unconfirmed_pool_source(error.pool_id, date, error.reason)
                for error in integrity_errors
            )
            if not pools:
                raise FileNotFoundError(date)
            return pools

    scope = {**scope, "PreselectionPoolStore": _ResolvedPoolStore}
    response = _v4_impl(
        scope,
        store,
        date,
        limit,
        offset=offset,
        allow_legacy_flat=allow_legacy_flat,
    )
    evidence = pool_read_evidence.get(str(date))
    if evidence is not None:
        legacy_bindings = evidence.pop("_legacy_pool_source_bindings", None)
        projection_source_pools = evidence.pop("_projection_source_pools", {})
        response["pool_source_evidence"] = evidence
        if response.get("ok") is True and isinstance(legacy_bindings, dict) and legacy_bindings:
            projected_pools = {
                str(pool.get("pool_id")): pool
                for pool in response.get("pools", [])
                if isinstance(pool, Mapping) and pool.get("pool_id")
            }
            for pool_id, binding in legacy_bindings.items():
                projected = projected_pools.get(pool_id)
                if projected is None:
                    projected = projection_source_pools.get(pool_id)
                if not isinstance(projected, Mapping):
                    binding["projection_source_matches"] = False
                    binding["cannot_confirm"].append("PROJECTION_SOURCE_NOT_RETURNED")
                    binding["stage_reuse_status"] = "CANNOT_CONFIRM"
                    continue
                binding["projection_source_matches"] = (
                    projected.get("source_sha256") == binding["source_sha256"]
                    and projected.get("source_run_id") == binding["source_run_id"]
                    and projected.get("source_role") == binding["source_role"]
                )
                if not binding["projection_source_matches"]:
                    binding["cannot_confirm"].append(
                        "PROJECTION_USES_SEPARATE_REVIEW_CORE_AUTHORITY"
                    )
                    binding["stage_reuse_status"] = "CANNOT_CONFIRM"
            response["pool_source_bindings"] = legacy_bindings
    return response


def _unconfirmed_pool_source(
    pool_id: str, trade_date: str, reason: str | None = None
) -> dict[str, Any]:
    """Quarantine one unreadable source while preserving other verified pools."""

    market = "HK" if pool_id == "hkconnect_d1_top100" else (
        "WECHAT" if pool_id == "wechat_public_account_v3_preselect" else "A"
    )
    return {
        "pool_id": pool_id,
        "display_name": _POOL_NAMES.get(pool_id, pool_id),
        "market": market,
        "status": "CANNOT_CONFIRM",
        "producer_id": "V3_5_POOL_SOURCE_READ_QUARANTINE",
        "source_role": "RAW_SOURCE",
        "source_path": f"preselection_pools/{trade_date}/{pool_id}.json",
        "source_sha256": "",
        "trade_date": trade_date,
        "signal_date": "",
        "target_date": trade_date,
        "rows": [],
        "cannot_confirm": [
            f"POOL_SOURCE_INTEGRITY_UNCONFIRMED:{pool_id}",
            *(
                [f"PRESELECTION_POOL_INTEGRITY:{pool_id}:{reason}"]
                if reason
                else []
            ),
        ],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _complete_independent_pool_set(
    pools: list[dict[str, Any]], trade_date: str
) -> list[dict[str, Any]]:
    """Project missing independent lanes as explicit CANNOT_CONFIRM pools.

    The source artifacts remain immutable and are never synthesized here.  The
    projection only preserves the graph-defined seven-pool surface so one
    verified lane cannot hide the other lanes or force a cross-date fallback.
    """
    from domains._preselection_parts.independent_projection import __complete_independent_pool_set_body as _v4_impl
    return _v4_impl(globals(), pools, trade_date)


def _replace_review_core_fupan_pool(
    pools: list[dict[str, Any]], trade_date: str
) -> list[dict[str, Any]]:
    """Replace the V4-local fupan artifact with the exact Review Core DTO."""
    from domains._preselection_parts.review_fupan import __replace_review_core_fupan_pool_body as _v4_impl
    return _v4_impl(globals(), pools, trade_date)


def _usable_review_core_fupan_pool(pool: Mapping[str, Any], trade_date: str) -> bool:
    from domains._preselection_parts.review_fupan import __usable_review_core_fupan_pool_body as _v4_impl
    return _v4_impl(globals(), pool, trade_date)


def _replace_payload_review_core_fupan_pool(
    payload: dict[str, Any], trade_date: str
) -> dict[str, Any]:
    """Apply the same exact-date replacement to a legacy payload projection."""
    from domains._preselection_parts.review_fupan import __replace_payload_review_core_fupan_pool_body as _v4_impl
    return _v4_impl(globals(), payload, trade_date)


def _replace_review_core_stage7_pool(
    pools: list[dict[str, Any]], trade_date: str
) -> list[dict[str, Any]]:
    """Replace the native Stage7 artifact only with a verified external DTO."""
    from domains._preselection_parts.review_stage7 import __replace_review_core_stage7_pool_body as _v4_impl
    return _v4_impl(globals(), pools, trade_date)


def _usable_review_core_stage7_pool(pool: Mapping[str, Any], trade_date: str) -> bool:
    """Accept only an exact, safety-clean, non-empty Review Core Stage7 DTO."""
    from domains._preselection_parts.review_stage7 import __usable_review_core_stage7_pool_body as _v4_impl
    return _v4_impl(globals(), pool, trade_date)


def _replace_payload_review_core_stage7_pool(
    payload: dict[str, Any], trade_date: str
) -> dict[str, Any]:
    """Apply the same exact-date Stage7 replacement to a legacy payload."""
    from domains._preselection_parts.review_stage7 import __replace_payload_review_core_stage7_pool_body as _v4_impl
    return _v4_impl(globals(), payload, trade_date)


def _project_independent_pools(pools: list[dict[str, Any]], trade_date: str) -> dict[str, Any]:
    from domains._preselection_parts.independent_projection import __project_independent_pools_body as _v4_impl
    return _v4_impl(globals(), pools, trade_date)


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
    "a_share_research_recommendation_pool": ("RESEARCH_RECOMMENDATION", "（研）", "research_lane"),
}


def _restore_flat_migration_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Project the one-time flat import back into the old V3 pool contract.

    This is a read-only compatibility projection.  It does not claim that a
    partial migration is canonical and it never fabricates candidate rows.
    """
    from domains._preselection_parts.source_validation import __restore_flat_migration_contract_body as _v4_impl
    return _v4_impl(globals(), payload)


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
    from domains._preselection_parts.pool_assembly import __dedupe_by_symbol_body as _v4_impl
    return _v4_impl(globals(), rows)


def _ensure_source_contract(row: dict[str, Any]) -> None:
    """Fill the evidenced old-V3 source fields without changing row values."""
    from domains._preselection_parts.source_validation import __ensure_source_contract_body as _v4_impl
    return _v4_impl(globals(), row)


def _merge_source_contract(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge provenance while keeping the first row's rank, score, and name."""
    from domains._preselection_parts.source_validation import __merge_source_contract_body as _v4_impl
    return _v4_impl(globals(), target, incoming)


def _pool_source_metadata(row: dict[str, Any]) -> tuple[str, str, str]:
    metadata = _POOL_SOURCE_CONTRACT.get(str(row.get("pool_id") or ""))
    return metadata if metadata is not None else ("", "", "")


def _metadata_values(value: Any) -> list[str]:
    from domains._preselection_parts.pagination_metadata import __metadata_values_body as _v4_impl
    return _v4_impl(globals(), value)


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
    from domains._preselection_parts.pagination_metadata import __input_fingerprint_body as _v4_impl
    return _v4_impl(globals(), pools, trade_date)


def _blocked(date: str, reason: str) -> dict[str, Any]:
    return {"ok": False, "data_status": "DATA_BLOCKED_EMPTY", "blocking_reasons": [reason], "schema_version": "v3_preselection_pools.v1", "trade_date": date, "module_id": "unified_preselection_pools", "write_policy": "read_only", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "recommendation_status": "WATCH_ONLY_BACKTEST_GATED", "pool_count": 0, "row_count": 0, "unified_row_count": 0, "a_source_only_row_count": 0, "a_all_pool_row_count": 0, "pools": [], "unified_rows": [], "a_source_only_rows": [], "a_all_pool_rows": [], "rows": [], "startup_ensure": {}, "strict_0_2_status": "CANNOT_CONFIRM", "evidence_paths": [], "cannot_confirm": [reason], "input_fingerprint": None, "source_digests": {}}


def _is_trading_date(value: str) -> bool:
    contract = Path(__file__).resolve().parents[1] / "contracts" / "trading_calendar_2026.json"
    excluded = set(json.loads(contract.read_text(encoding="utf-8"))["known_non_trading_dates"])
    return datetime.strptime(value, "%Y%m%d").weekday() < 5 and value not in excluded


@lru_cache(maxsize=1)
def _market_calendar():
    return load_market_calendar()


def _is_navigation_trading_date(value: str) -> bool:
    """A/HK observation navigation follows either securities market session."""

    calendar = _market_calendar()
    states = resolve_contract_market_states(calendar, value)
    open_states = {
        CalendarTradingDayState.FULL_TRADING_DAY,
        CalendarTradingDayState.HALF_TRADING_DAY_AM,
    }
    return any(states[key] in open_states for key in ("a_share", "hk_securities"))


def _hk_observation_only_dates() -> list[str]:
    """Return exact calendar dates when HK is open and Southbound is closed."""

    calendar = _market_calendar()
    cursor = date(calendar.year, 1, 1)
    end = date(calendar.year, 12, 31)
    dates: list[str] = []
    open_states = {
        CalendarTradingDayState.FULL_TRADING_DAY,
        CalendarTradingDayState.HALF_TRADING_DAY_AM,
    }
    while cursor <= end:
        date8 = cursor.strftime("%Y%m%d")
        states = resolve_contract_market_states(calendar, date8)
        if (
            states["hk_securities"] in open_states
            and states["hk_connect"] is CalendarTradingDayState.NON_TRADING_DAY
        ):
            dates.append(date8)
        cursor += timedelta(days=1)
    return dates


def _page_metadata(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    offset: int,
    status: str = "",
) -> dict[str, Any]:
    from domains._preselection_parts.pagination_metadata import __page_metadata_body as _v4_impl
    return _v4_impl(globals(), rows, limit=limit, offset=offset, status=status)


def _market_buckets(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    from domains._preselection_parts.pagination_metadata import __market_buckets_body as _v4_impl
    return _v4_impl(globals(), rows)


def _page_per_market(rows: list[dict[str, Any]], limit: int, offset: int = 0) -> list[dict[str, Any]]:
    buckets = _market_buckets(rows)
    selected: list[dict[str, Any]] = []
    for bucket in ("A", "HK", "OTHER"):
        selected.extend(buckets[bucket][offset:offset + limit])
    return selected


def _limit_per_market(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return _page_per_market(rows, limit, 0)
