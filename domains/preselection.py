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
from infrastructure.preselection_pool_store import POOL_ORDER, PreselectionPoolStore
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
) -> dict[str, Any]:
    from domains._preselection_parts.date_catalog import _date_catalog_body as _v4_impl
    return _v4_impl(globals(), store, current_date=current_date, stage_selection_root=stage_selection_root)


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


def _verified_independent_pool_dates(store: NativeDataStore) -> tuple[str, ...]:
    """Discover dates with at least one SHA-verified independent pool.

    Pool families are independently published.  Requiring ``read_all`` here
    made one missing optional pool hide a target date whose other artifact
    trio was already complete.
    """
    from domains._preselection_parts.date_catalog import __verified_independent_pool_dates_body as _v4_impl
    return _v4_impl(globals(), store)


def preselection(
    store: NativeDataStore,
    date: str,
    limit: int,
    *,
    offset: int = 0,
    allow_legacy_flat: bool = False,
) -> dict[str, Any]:
    from domains._preselection_parts.pool_assembly import _preselection_body as _v4_impl
    return _v4_impl(globals(), store, date, limit, offset=offset, allow_legacy_flat=allow_legacy_flat)


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
    """Replace the V3.5-local fupan artifact with the exact Review Core DTO."""
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
}


def _restore_flat_migration_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Project the one-time flat import back into the old V3 pool contract.

    This is a read-only compatibility projection.  It does not claim that a
    partial migration is canonical and it never fabricates candidate rows.
    """
    from domains._preselection_parts.source_validation import __restore_flat_migration_contract_body as _v4_impl
    return _v4_impl(globals(), payload)


def _merge_optional_pools(
    payload: dict[str, Any],
    trade_date: str,
    overlay: dict[str, Any] | None,
    overlay_error: str,
) -> dict[str, Any]:
    """Add graph-defined research lanes without changing selector-owned input."""
    from domains._preselection_parts.optional_pool_merge import __merge_optional_pools_body as _v4_impl
    return _v4_impl(globals(), payload, trade_date, overlay, overlay_error)


def _optional_placeholders(trade_date: str) -> list[dict[str, Any]]:
    from domains._preselection_parts.optional_pool_merge import __optional_placeholders_body as _v4_impl
    return _v4_impl(globals(), trade_date)


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
