"""Read-only preselection aggregation behind the shared API entry point.

Extracted from the SHA-pinned R2 app with the reviewed source-root and
empty-local-pool repairs. The bounded legacy SHA-error recovery below reuses
the existing verified pool readers; domain/storage authorities remain unchanged.
"""
from __future__ import annotations

import inspect
import json
import hashlib
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


def _project_wechat_input_gap(response, source_root, trade_date):
    """Display the original exact-date consumer receipt; never create inputs."""
    try:
        receipt=Path(source_root)/'receipts/wechat_preselection'/f'{trade_date}.json'
        if receipt.is_symlink() or receipt.resolve()!=receipt:raise ValueError('unsafe receipt')
        raw=receipt.read_bytes()
        if len(raw)>1024*1024:raise ValueError('receipt too large')
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('receipt not object')
        if (value.get('schema_version')!='v3_5.wechat_preselection_sync_receipt.v1'
                or value.get('effective_trade_date')!=trade_date
                or any(value.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent'))):
            raise ValueError('receipt identity/safety mismatch')
        root=Path(value['input_root'])
        if not root.is_absolute() or root.resolve()!=root:raise ValueError('input root unbound')
        missing=[str(root/trade_date/name) for name in ('wechat_manifest.json','wechat_rows.csv') if not (root/trade_date/name).is_file()]
        if not missing:return response
    except (OSError,ValueError,KeyError,TypeError):return response
    result={**response,'pools':[]}
    for pool in response.get('pools',[]):
        if pool.get('pool_id')=='wechat_public_account_v3_preselect' and not pool.get('rows') and not pool.get('pool_size'):
            pool={**pool,'cannot_confirm':[*pool.get('cannot_confirm',[]),
                '精确日期输入缺失：'+'、'.join(missing)+'；原pair owner：exact-URL wechat_pipeline_runner sync -> wechat_publish_v35_preselection.py；sync仅消费，不采集'],
                'input_gap_receipt':{'path':str(receipt),'sha256':hashlib.sha256(raw).hexdigest()},'missing_inputs':missing}
        result['pools'].append(pool)
    return result

from contracts.a_share_entity_filter import FILTER_RULE_VERSION, filter_pool_rows
from contracts.trading_safety import TRADING_SAFETY_FLAGS
from domains import preselection as preselection_domain
from domains.preselection import OPTIONAL_DAILY_POOL_IDS, preselection
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import (
    POOL_ORDER, PreselectionPoolStore, PreselectionSourceResolver,
)
from upstreams.v3_shared_data.shared_data.names import resolve_hk_name_for_date


_LEGACY_POOL_SHA_BLOCK = (
    "V4 independent pool receipt cannot be confirmed: "
    "preselection-pool manifest or receipt SHA mismatch"
)

_V4_SOURCE_LABELS = {
    "v3_5_hourly_research_window_v1": "V4 小时研究",
    "v3_shared_v192_consumer_v1": "V4 1.9.2 候选",
    "v3_fupan_watchlist_contract_v1": "V4 复盘观察",
    "v3_stage7_tail_replay_contract_v1": "V4 Stage7 复盘",
    "v3_shared_hk_0_2_consumer_v1": "V4 港股通 0.2",
    "graph_expected_missing_v1": "V4 预期缺失",
    "shared_data.baimao_observations.v1": "V4 白毛研究",
}
_A_NAME_CACHE: dict[str, tuple[str, dict[str, str]]] = {}


def _a_code(value: Any) -> str:
    text = re.sub(r"^(?:A\.)?", "", str(value or "").strip(), flags=re.IGNORECASE)
    return text.split(".", 1)[0]


def _is_placeholder_a_name(value: Any, code: str) -> bool:
    text = str(value or "").strip()
    return not text or text.upper() == code or text.upper() == f"A.{code}" or bool(
        re.fullmatch(r"(?:A\.)?\d{6}(?:\.(?:SH|SZ|BJ))?", text, re.IGNORECASE)
    )


def _is_placeholder_a_display(value: Any, code: str) -> bool:
    text = str(value or "").strip()
    return not text or bool(
        re.fullmatch(
            r"(?:A\.)?\d{6}(?:\.(?:SH|SZ|BJ))?(（[^）]*）)?",
            text,
            re.IGNORECASE,
        )
    )


def _month_ranges_backwards(trade_date: str):
    try:
        current = datetime.strptime(trade_date, "%Y%m%d").date()
    except (TypeError, ValueError):
        return
    for _ in range(12):
        month_end = current.replace(day=1) - timedelta(days=1)
        month_start = month_end.replace(day=1)
        yield month_start.strftime("%Y%m%d"), month_end.strftime("%Y%m%d")
        current = month_start


def _load_a_name_map(trade_date: str) -> tuple[str, dict[str, str]]:
    from ops.research_storage_pair import request_binding
    root = os.environ.get('V4_A_SHARE_HISTORY_DATA_ROOT')
    if not root:return '', {}
    try:
        with request_binding(root):
            return _load_a_name_map_bound(trade_date)
    except (OSError,ValueError,RuntimeError):
        # Preserve this display-only fallback's established empty-name behavior
        # on unavailable binding; never fall back to a newly resolved pointer.
        return '', {}


def _load_a_name_map_bound(trade_date: str) -> tuple[str, dict[str, str]]:
    """Load a display-only A-share name fallback from the selector history.

    The live A panel's recent ``name`` column can be empty while older exact
    selector dates still carry names.  This reads only a historical name
    column; it never rewrites a pool artifact or claims PIT certification.
    The returned date is the exact latest non-empty selector date in the
    first month that has a usable name population, not a month-end guess.
    """
    root_value = os.environ.get("V4_A_SHARE_HISTORY_DATA_ROOT")
    if not root_value:
        return "", {}
    root = Path(root_value)
    pointer = root / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"
    try:
        from ops.research_storage_pair import current_binding
        pair = current_binding(root)
        selector = pair.paths['selector'] if pair else Path(pointer.read_text(encoding='utf-8').strip())
        if not selector.is_absolute():
            selector = root / selector
        cache_key = f"{selector}|{selector.stat().st_mtime_ns}|{trade_date}"
    except (OSError, ValueError):
        return "", {}
    if cache_key in _A_NAME_CACHE:
        return _A_NAME_CACHE[cache_key]
    try:
        import pyarrow.dataset as dataset_module
    except ImportError:
        return "", {}
    try:
        from ops.research_panel_logical import dataset as panel_dataset
        dataset = panel_dataset(selector, format="parquet")
    except (OSError, ValueError):
        return "", {}
    for month_start, month_end in _month_ranges_backwards(trade_date):
        try:
            from ops.research_panel_logical import parquet as pq
            table = pq.read_table(selector,columns=["trade_date","ts_code","name"],
                filters=[('trade_date','>=',month_start),('trade_date','<=',month_end)])
        except (OSError, ValueError, TypeError):
            continue
        by_date: dict[str, dict[str, str]] = {}
        for row_date, code, name in zip(
            table.column("trade_date").to_pylist(),
            table.column("ts_code").to_pylist(),
            table.column("name").to_pylist(),
        ):
            code_text = _a_code(code)
            date_text = str(row_date or "").strip()
            name_text = str(name or "").strip()
            if not date_text or not name_text or not code_text:
                continue
            if _is_placeholder_a_name(name_text, code_text):
                continue
            by_date.setdefault(date_text, {})[code_text] = name_text
        for exact_date in sorted(by_date, reverse=True):
            names = by_date[exact_date]
            if len(names) >= 100:
                _A_NAME_CACHE[cache_key] = (exact_date, names)
                return exact_date, names
    return "", {}


def _apply_v4_display_projection(
    response: dict[str, Any], trade_date: str, *,
    name_map: dict[str, str] | None = None,
    name_date: str = "",
) -> dict[str, Any]:
    """Add V4 display labels and A-name fallbacks at the API boundary."""
    if name_map is None:
        name_date, name_map = _load_a_name_map(trade_date)
    row_groups: list[Any] = [
        response.get("rows"),
        response.get("unified_rows"),
        response.get("a_source_only_rows"),
        response.get("a_all_pool_rows"),
    ]
    for pool in response.get("pools", []):
        if not isinstance(pool, dict):
            continue
        label = _V4_SOURCE_LABELS.get(str(pool.get("producer_id") or ""))
        if label:
            pool["producer_label"] = label
        pool_rows = pool.get("rows")
        if isinstance(pool_rows, list):
            row_groups.append(pool_rows)
        if label:
            for row in pool_rows or []:
                if (
                    isinstance(row, dict)
                    and not row.get("source_tags")
                    and not row.get("source_label")
                    and not row.get("source_tag")
                ):
                    row["source_label"] = label
    visited: set[int] = set()
    for rows in row_groups:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or id(row) in visited:
                continue
            visited.add(id(row))
            if str(row.get("market") or "").strip().upper() not in {"A", "A_SHARE"}:
                continue
            code = _a_code(row.get("stock_code") or row.get("code") or row.get("symbol"))
            if not code:
                continue
            stock_name_value = row.get("stock_name")
            name_value = row.get("name")
            current_display = str(row.get("display_name") or "")
            stock_name_real = not _is_placeholder_a_name(stock_name_value, code)
            name_real = not _is_placeholder_a_name(name_value, code)
            display_missing = _is_placeholder_a_display(current_display, code)
            if not stock_name_real and not name_real and not display_missing:
                continue
            suffix = ""
            match = re.match(r"^(?:A\.)?\d{6}(（[^）]*）)?$", current_display)
            if match:
                suffix = match.group(1) or ""
            if not suffix:
                tags = row.get("source_tags")
                if isinstance(tags, str):
                    suffix = "".join(re.findall(r"[（(][^）)]*[）)]", tags))
            if stock_name_real and name_real:
                stock_text = str(stock_name_value).strip()
                name_text = str(name_value).strip()
                if re.sub(r"\s+", "", stock_text) != re.sub(r"\s+", "", name_text):
                    row["name_conflict"] = {
                        "stock_name": stock_text,
                        "name": name_text,
                        "resolution": "PRESERVED_EXISTING_FIELDS",
                    }
                    if display_missing:
                        row["display_name"] = name_text + suffix
                    row["name_resolution"] = {
                        "status": "NAME_FIELD_CONFLICT",
                        "source": "EXISTING_A_POOL_FIELDS",
                    }
                    continue
            authority = (
                str(name_value).strip() if name_real
                else str(stock_name_value).strip() if stock_name_real
                else ""
            )
            if authority:
                if stock_name_real and name_real and not display_missing:
                    continue
                if not stock_name_real:
                    row["raw_stock_name"] = str(stock_name_value or "")
                    row["stock_name"] = authority
                if not name_real:
                    row["raw_name"] = str(name_value or "")
                    row["name"] = authority
                if display_missing:
                    row["display_name"] = authority + suffix
                row["name_resolution"] = {
                    "status": (
                        "EXISTING_NAME_DISPLAY_FILL"
                        if stock_name_real and name_real
                        else "EXISTING_NAME_FIELD_FILL"
                    ),
                    "source": "EXISTING_A_POOL_NAME",
                }
                continue
            if not name_map or code not in name_map:
                continue
            historical = name_map[code]
            row["raw_stock_name"] = str(stock_name_value or "")
            row["raw_name"] = str(name_value or "")
            row["stock_name"] = historical
            row["name"] = historical
            if display_missing:
                row["display_name"] = historical + suffix
            row["name_resolution"] = {
                "status": "HISTORICAL_SELECTOR_PANEL_NAME",
                "source_date": name_date,
            }
    return response


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_exact_configured_hk_pool(payload: Mapping[str, Any], target_date: str) -> bool:
    """Accept only a complete, exact-date HK 0.2 pool from the configured root."""
    signal_date = payload.get("signal_date")
    provenance = payload.get("historical_provenance")
    rows = payload.get("rows")
    eligibility_date = (
        provenance.get("eligibility_source_date")
        if isinstance(provenance, Mapping)
        else payload.get("eligibility_source_date")
    )
    if (
        payload.get("schema_version") != "v3_5.preselection_pool.v1"
        or payload.get("pool_id") != "hkconnect_d1_top100"
        or payload.get("market") != "HK"
        or payload.get("status") != "STRICT_0_2_READY"
        or payload.get("producer_id") != "v3_shared_hk_0_2_consumer_v1"
        or payload.get("source_role") != "SHARED_VERIFIED_HK_0_2"
        or payload.get("trade_date") != target_date
        or payload.get("target_date") != target_date
        or not isinstance(signal_date, str)
        or len(signal_date) != 8
        or not signal_date.isdigit()
        or signal_date >= target_date
        or not _is_sha256(payload.get("source_sha256"))
        or not str(payload.get("source_run_id") or "").strip()
        or not _is_sha256(payload.get("source_manifest_sha256"))
        or not _is_sha256(payload.get("source_receipt_sha256"))
        or payload.get("stage_selection_eligible") is not True
        or not isinstance(rows, list)
        or len(rows) != 100
        or any(payload.get(flag) is not False for flag in TRADING_SAFETY_FLAGS)
    ):
        return False
    # Both provenance forms bind the same existing API calendar authority.
    # A well-shaped historical object cannot authorize stale source dates.
    try:
        from contracts.trading_calendar import (
            TradingDayState, load_market_calendar, previous_session,
            resolve_market_states,
        )

        calendar = load_market_calendar()
        states = resolve_market_states(calendar, target_date)
        open_states = {
            TradingDayState.FULL_TRADING_DAY,
            TradingDayState.HALF_TRADING_DAY_AM,
        }
        if (
            states["hk_securities"] not in open_states
            or states["hk_connect"] is TradingDayState.UNKNOWN
            or previous_session(calendar, target_date, market="hk_securities") != signal_date
            or previous_session(calendar, target_date, market="hk_connect") != eligibility_date
        ):
            return False
    except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError):
        return False
    if "historical_provenance" not in payload:
        # Same-date producer inputs need no split-date object. The exception
        # requires explicit dates and the API's existing calendar authority;
        # missing provenance alone never establishes same-date eligibility.
        if (
            payload.get("price_signal_date") != signal_date
            or eligibility_date != signal_date
        ):
            return False
    elif (
        not isinstance(provenance, Mapping)
        or provenance.get("schema_version") != "v4.hk_d1_split_date_provenance.v1"
        or provenance.get("price_signal_date") != signal_date
        or not isinstance(eligibility_date, str)
        or len(eligibility_date) != 8
        or not eligibility_date.isdigit()
        or eligibility_date > signal_date
        or not str(provenance.get("eligibility_source_run_id") or "").strip()
        or not _is_sha256(provenance.get("eligibility_source_artifact_sha256"))
        or not str(provenance.get("eligibility_source_captured_at") or "").strip()
        or provenance.get("d1_source_run_id") != payload.get("source_run_id")
        or provenance.get("d1_source_artifact_sha256") != payload.get("source_sha256")
        or provenance.get("d1_source_manifest_sha256") != payload.get("source_manifest_sha256")
        or provenance.get("d1_source_receipt_sha256") != payload.get("source_receipt_sha256")
    ):
        return False
    if isinstance(provenance, Mapping):
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            captured = datetime.fromisoformat(str(provenance["eligibility_source_captured_at"]))
            if (
                captured.tzinfo is None
                or captured.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d") != eligibility_date
            ):
                return False
        except (ValueError, TypeError, KeyError, OverflowError):
            return False
    if (
        ("price_signal_date" in payload and payload["price_signal_date"] != signal_date)
        or ("eligibility_source_date" in payload and payload["eligibility_source_date"] != eligibility_date)
    ):
        return False
    symbols: set[str] = set()
    ranks: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return False
        symbol = str(row.get("symbol") or row.get("code") or "").strip().upper()
        rank = row.get("pool_rank")
        if (
            len(symbol) != 8
            or not symbol.startswith("HK.")
            or not symbol[3:].isdigit()
            or row.get("pool_id") != "hkconnect_d1_top100"
            or row.get("market") != "HK"
            or row.get("trade_date") != target_date
            or row.get("target_date") != target_date
            or row.get("signal_date") != signal_date
            or ("price_signal_date" in row and row["price_signal_date"] != signal_date)
            or ("eligibility_source_date" in row and row["eligibility_source_date"] != eligibility_date)
            or any(key in row and row[key] != symbol for key in ("code", "symbol"))
            or isinstance(rank, bool)
            or not isinstance(rank, int)
            or rank not in range(1, 101)
            or any(row.get(flag) is not False for flag in TRADING_SAFETY_FLAGS)
            or str(row.get("recommendation_status") or "").upper() not in {"WATCH_ONLY", "WATCH_ONLY_BACKTEST_GATED"}
        ):
            return False
        symbols.add(symbol)
        ranks.add(rank)
    return len(symbols) == 100 and len(ranks) == 100


def _preselection_response_from_pools(
    pools: list[dict[str, Any]], *, trade_date: str, limit: int, offset: int,
    apply_review_sources: bool = True, name_pool_root: Path | None = None,
) -> dict[str, Any]:
    """Render merged exact-date pool reads with the existing API page contract."""
    if apply_review_sources:
        pools = preselection_domain._replace_review_core_fupan_pool(pools, trade_date)
        pools = preselection_domain._replace_review_core_stage7_pool(pools, trade_date)
    pools = preselection_domain._complete_independent_pool_set(pools, trade_date)
    # Storage is write-once and already verified when it was read; the
    # quarantine below only decides what a consumer may treat as an A-share
    # entity. It never rewrites a stored row, rank or count.
    published_row_count = len(preselection_domain._project_independent_pools(pools, trade_date)["rows"])
    pools, quarantined = filter_pool_rows(pools)
    payload = preselection_domain._project_independent_pools(pools, trade_date)
    rows = payload["rows"]
    status = "READY_WITH_ROWS" if payload.get("producer_status") == "CANONICAL_COMPLETE" else "PARTIAL_WITH_ROWS"
    if not rows:
        if published_row_count == 0:
            raise ValueError("exact-date pool projection has no rows")
        # The producer published rows and the read side withheld all of them.
        # That is not an empty product and must stay distinguishable from one.
        return {
            "ok": True, "status": "ALL_ROWS_QUARANTINED", "data_status": "ALL_ROWS_QUARANTINED",
            "blocking_reasons": ["ALL_ROWS_QUARANTINED_AS_INVALID_A_SHARE"],
            "cannot_confirm": ["ALL_ROWS_QUARANTINED_AS_INVALID_A_SHARE"],
            "schema_version": "v3_preselection_pools.v1", "trade_date": trade_date,
            "module_id": "unified_preselection_pools", "write_policy": "read_only",
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
            "pool_count": 0, "row_count": 0,
            "unified_row_count": 0, "a_source_only_row_count": 0, "a_all_pool_row_count": 0,
            "original_row_count": published_row_count,
            "effective_row_count": 0,
            "quarantined_row_count": len(quarantined),
            "quarantined": list(quarantined),
            "filter_rule_version": FILTER_RULE_VERSION,
            "rows": [], "pools": [], "unified_rows": [],
            "a_source_only_rows": [], "a_all_pool_rows": [],
        }
    response = {
        key: payload.get(key, [] if key.endswith("rows") or key == "pools" or key == "cannot_confirm" else {})
        for key in ("pools", "unified_rows", "a_source_only_rows", "a_all_pool_rows", "startup_ensure", "strict_0_2_status", "evidence_paths", "cannot_confirm")
    }
    response.update({
        "ok": True,
        "data_status": status,
        "blocking_reasons": list(payload.get("blocking_reasons", [])),
        "schema_version": "v3_preselection_pools.v1",
        "trade_date": trade_date,
        "module_id": "unified_preselection_pools",
        "write_policy": "read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "pool_count": len(payload.get("pools", [])),
        "row_count": len(rows),
        "original_row_count": published_row_count,
        "effective_row_count": len(rows),
        "quarantined_row_count": len(quarantined),
        "quarantined": list(quarantined),
        "filter_rule_version": FILTER_RULE_VERSION,
        "unified_row_count": len(payload.get("unified_rows", rows)),
        "a_source_only_row_count": len(payload.get("a_source_only_rows", [])),
        "a_all_pool_row_count": len(payload.get("a_all_pool_rows", rows)),
        "rows": [],
        "daily_readiness_status": payload.get("daily_readiness_status", status),
        "mandatory_pool_ids": list(payload.get("mandatory_pool_ids", ())),
        "optional_pool_ids": list(payload.get("optional_pool_ids", OPTIONAL_DAILY_POOL_IDS)),
    })
    response["market_totals"] = payload.get("market_totals", preselection_domain._market_totals(rows))
    response["hk_pool_version"] = payload.get("hk_pool_version")
    response["hk_pool_role"] = payload.get("hk_pool_role")
    response["input_fingerprint"] = preselection_domain._input_fingerprint(payload.get("pools", []), trade_date)
    response["source_digests"] = {
        str(pool.get("pool_id") or ""): str(pool.get("source_sha256") or "")
        for pool in payload.get("pools", [])
        if str(pool.get("pool_id") or "")
    }
    from domains._preselection_parts.source_validation import project_a_display_names
    if name_pool_root is not None:
        response = project_a_display_names(response, trade_date, name_pool_root)
    full_arrays = {
        "unified_rows": list(response["unified_rows"]),
        "a_source_only_rows": list(response["a_source_only_rows"]),
        "a_all_pool_rows": list(response["a_all_pool_rows"]),
    }
    array_pagination = {
        name: preselection_domain._page_metadata(array_rows, limit=limit, offset=offset)
        for name, array_rows in full_arrays.items()
    }
    response["unified_rows"] = preselection_domain._page_per_market(full_arrays["unified_rows"], limit, offset)
    response["a_source_only_rows"] = preselection_domain._page_per_market(full_arrays["a_source_only_rows"], limit, offset)
    response["a_all_pool_rows"] = preselection_domain._page_per_market(full_arrays["a_all_pool_rows"], limit, offset)
    paged_pools: list[dict[str, Any]] = []
    pool_pagination: dict[str, dict[str, Any]] = {}
    for pool in response["pools"]:
        full_pool_rows = list(pool.get("rows", []))
        metadata = preselection_domain._page_metadata(
            full_pool_rows, limit=limit, offset=offset, status=str(pool.get("status") or "")
        )
        pool_id = str(pool.get("pool_id") or "")
        pool_pagination[pool_id] = metadata
        paged_pools.append({
            **pool,
            "pool_size": len(full_pool_rows),
            "returned_rows": metadata["returned_rows"],
            "rows": preselection_domain._page_per_market(full_pool_rows, limit, offset),
            "page_offset": offset,
            "page_limit": limit,
            "has_more": metadata["has_more"],
            "complete": metadata["complete"],
        })
    response["pools"] = paged_pools
    response["rows"] = [row for pool in paged_pools for row in pool.get("rows", [])]
    has_more = any(metadata["has_more"] for metadata in (*array_pagination.values(), *pool_pagination.values()))
    response["pagination"] = {
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if has_more else None,
        "has_more": has_more,
        "complete": not has_more and status == "READY_WITH_ROWS" and all(
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
    response["daily_readiness_status"] = payload.get("daily_readiness_status", status)
    response["mandatory_pool_ids"] = list(payload.get("mandatory_pool_ids", ()))
    response["optional_pool_ids"] = list(payload.get("optional_pool_ids", OPTIONAL_DAILY_POOL_IDS))
    return _apply_v4_display_projection(response, trade_date)


def _project_dated_hk_name_response(
    response: dict[str, Any], trade_date: str,
) -> dict[str, Any]:
    """Apply the dated HK name correction to this read-only API response only.

    The preselection endpoint reads already-materialized pool DTOs.  This
    projection keeps those stored inputs intact while correcting their HK
    display fields at the response boundary.
    """
    row_groups: list[Any] = [
        response.get("rows"),
        response.get("unified_rows"),
        response.get("a_source_only_rows"),
        response.get("a_all_pool_rows"),
    ]
    for pool in response.get("pools", []):
        if isinstance(pool, Mapping):
            row_groups.append(pool.get("rows"))

    visited: set[int] = set()
    for rows in row_groups:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or id(row) in visited:
                continue
            visited.add(id(row))
            if str(row.get("market") or "").strip().upper() != "HK":
                continue
            code = row.get("symbol") or row.get("code_norm") or row.get("code")
            raw_name_value = row.get("raw_name")
            if raw_name_value is None:
                raw_name_value = row.get("name")
            if raw_name_value is None:
                raw_name_value = row.get("stock_name")
            raw_name = str(raw_name_value or "")
            display_name, resolution = resolve_hk_name_for_date(
                code, trade_date=trade_date, source_name=raw_name
            )
            if resolution is None:
                continue
            row["raw_name"] = raw_name
            row["name_resolution"] = resolution
            if resolution.get("status") == "EFFECTIVE_DATE_OVERRIDE":
                row["name"] = display_name
                row["stock_name"] = display_name
    return response


def _quarantined_pool(pool_id: str, trade_date: str, reason: str) -> dict[str, Any]:
    """Reuse the accepted canonical quarantine DTO; never create an artifact."""
    market = "HK" if pool_id == "hkconnect_d1_top100" else (
        "WECHAT" if pool_id == "wechat_public_account_v3_preselect" else "A"
    )
    return {
        "pool_id": pool_id,
        "display_name": preselection_domain._POOL_NAMES.get(pool_id, pool_id),
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
        "cannot_confirm": [f"{reason}:{pool_id}"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _is_consistent_a_row(row: Any, trade_date: str, pool_id: str) -> bool:
    """Require every supplied identity to agree before recovering a legacy block.

    The old normalizer ignores unknown markets and unrecognized code fields.
    A valid fallback code must not erase an explicit conflicting HK/US identity.
    Missing optional aliases may inherit the verified pool's A/date identity.
    """
    if not isinstance(row, Mapping):
        return False
    market = row.get("market")
    if (market is not None and (
            not isinstance(market, str) or market.strip().upper() not in {"", "A"})):
        return False
    if (row.get("trade_date", trade_date) != trade_date
            or row.get("target_date", trade_date) != trade_date
            or row.get("pool_id", pool_id) != pool_id):
        return False
    canonical = preselection_domain._canonical_a_symbol(row)
    if not canonical:
        return False
    for key in ("symbol", "normalized_code", "code", "stock_code", "ts_code"):
        value = row.get(key)
        if value is None or not str(value).strip():
            continue
        if preselection_domain._canonical_a_symbol({key: value}) != canonical:
            return False
    return True


def _recover_legacy_sha_block(
    response: dict[str, Any], store: NativeDataStore, source_root: Path,
    trade_date: str, limit: int, offset: int,
) -> dict[str, Any]:
    """Recover only the declared old-domain SHA failure from verified A inputs.

    The accepted canonical facade already quarantines individual source errors.
    Some historical monolithic domains block the whole date instead. Do not
    reinterpret their other errors, relax their input guards, or read another
    date. A pending pool is never handed to a recovery-capable snapshot reader.
    """
    if (response.get("data_status") != "DATA_BLOCKED_EMPTY"
            or response.get("blocking_reasons") != [_LEGACY_POOL_SHA_BLOCK]):
        return response

    from infrastructure.interprocess_lock import owned_interprocess_lock

    pools: list[dict[str, Any]] = []
    bindings: dict[str, Any] = {}
    quarantined: dict[str, str] = {}
    sha_failure_seen = False
    try:
        resolver = PreselectionSourceResolver(store.root, source_root=source_root)
        owner = resolver.root_for_date(trade_date)
        source_store = PreselectionPoolStore(owner)
        with resolver.source_read_lease(trade_date):
            with owned_interprocess_lock(
                source_store.root / ".import.lock", timeout_seconds=10,
                timeout_message="data-root import lock timeout",
            ) as source_lock:
                for pool_id in POOL_ORDER:
                    pending_relative_for = getattr(source_store, "_pending_relative", None)
                    pending_relative = (
                        pending_relative_for(trade_date=trade_date, pool_id=pool_id)
                        if callable(pending_relative_for)
                        else f"preselection_pending_commits/{trade_date}/{pool_id}.json"
                    )
                    try:
                        source_store._io.read_bytes(pending_relative)
                    except FileNotFoundError:
                        pass
                    else:
                        pools.append(_quarantined_pool(pool_id, trade_date, "POOL_SOURCE_PENDING_COMMIT"))
                        quarantined[pool_id] = "source_pending_commit"
                        continue
                    try:
                        reader = source_store.read_pool_snapshot
                        if "lock_lease" in inspect.signature(reader).parameters:
                            snapshot = reader(trade_date, pool_id, lock_lease=source_lock)
                        else:
                            snapshot = reader(trade_date, pool_id)
                    except FileNotFoundError:
                        continue
                    except ValueError as error:
                        # Only the independently reproduced legacy error is
                        # translated. Unknown validator/owner errors stay blocked.
                        if str(error) != "preselection-pool manifest or receipt SHA mismatch":
                            raise
                        pools.append(_quarantined_pool(pool_id, trade_date, "POOL_SOURCE_INTEGRITY_UNCONFIRMED"))
                        quarantined[pool_id] = str(error)
                        sha_failure_seen = True
                        continue
                    pool = snapshot["artifact"]
                    expected_market = "HK" if pool_id == "hkconnect_d1_top100" else (
                        "WECHAT" if pool_id == "wechat_public_account_v3_preselect" else "A"
                    )
                    if (pool.get("pool_id") != pool_id or pool.get("market") != expected_market
                            or pool.get("trade_date") != trade_date
                            or pool.get("target_date", trade_date) != trade_date):
                        raise ValueError("QUARANTINE_RECOVERY_MARKET_OR_DATE_MISMATCH")
                    if pool_id == "hkconnect_d1_top100" and not _is_exact_configured_hk_pool(pool, trade_date):
                        pools.append(_quarantined_pool(pool_id, trade_date, "POOL_SOURCE_HK_CONTRACT_UNCONFIRMED"))
                        quarantined[pool_id] = "exact_hk_contract_unconfirmed"
                        continue
                    if expected_market == "A" and any(
                        not _is_consistent_a_row(row, trade_date, pool_id)
                        for row in pool.get("rows", [])
                    ):
                        pools.append(_quarantined_pool(pool_id, trade_date, "POOL_SOURCE_ROW_IDENTITY_UNCONFIRMED"))
                        quarantined[pool_id] = "a_row_market_or_date_unconfirmed"
                        continue
                    pools.append(dict(pool))
                    bindings[pool_id] = {
                        "physical_source_root": str(owner),
                        **{key: snapshot[key] for key in (
                            "artifact_relative", "manifest_relative", "receipt_relative",
                            "artifact_raw_sha256", "manifest_raw_sha256", "receipt_raw_sha256",
                        )},
                        "source_sha256": pool["source_sha256"],
                        "source_run_id": pool.get("source_run_id"),
                        "trade_date": trade_date,
                        "physical_status": "TRIO_VERIFIED",
                        "stage_reuse_status": "REQUIRES_STAGE_CONTRACT_VALIDATION",
                    }
                if resolver.root_for_date(trade_date) != owner:
                    raise ValueError("QUARANTINE_RECOVERY_SOURCE_OWNER_CHANGED")
        if not sha_failure_seen or not any(pool.get("market") == "A" and pool.get("rows") for pool in pools):
            return response
        recovered = _preselection_response_from_pools(
            pools, trade_date=trade_date, limit=limit, offset=offset,
            # The old monolith's configured-source branch does not replace
            # source-bound pools with a separate Review Core authority.
            apply_review_sources=owner == resolver.root, name_pool_root=owner,
        )
        if recovered.get("a_all_pool_row_count", 0) < 1 and recovered.get("data_status") != "ALL_ROWS_QUARANTINED":
            return response
    except (OSError, ValueError) as error:
        # Preserve the original blocked result and expose why recovery declined;
        # no unrelated failure is converted into PARTIAL or silently discarded.
        return {**response, "source_quarantine_recovery": {
            "applied": False, "status": "CANNOT_CONFIRM",
            "reason": "verified_source_recovery_declined", "detail": str(error),
            "target_date": trade_date,
        }}
    recovered["pool_source_bindings"] = bindings
    recovered["source_quarantine_recovery"] = {
        "applied": True, "status": "PARTIAL_WITH_ROWS",
        "reason": "legacy_pool_sha_failure_quarantined",
        "target_date": trade_date, "physical_source_root": str(owner),
        "quarantined_pools": quarantined,
        "read_policy": "read_only_exact_date_verified_trios",
    }
    return recovered


class PreselectionPoolService:
    """Hold only the caller's immutable dependency bindings, never pool data."""

    def __init__(
        self,
        store: NativeDataStore,
        *,
        configured_pool_source: bool,
        resolved_pool_source: Path,
    ) -> None:
        self._store = store
        self._configured_pool_source = configured_pool_source
        self._resolved_pool_source = resolved_pool_source

    def read(self, selected: str, limit: int, *, offset: int = 0) -> dict[str, Any]:
        store = self._store
        configured_pool_source = self._configured_pool_source
        resolved_pool_source = self._resolved_pool_source
        page_offset = offset
        response = preselection(
            store,
            selected,
            limit,
            offset=page_offset,
            preselection_source_root=resolved_pool_source,
        )
        response = _recover_legacy_sha_block(
            response, store, resolved_pool_source, selected, limit, page_offset,
        )
        if configured_pool_source:
            configured_root = resolved_pool_source.expanduser().resolve()
            local_root = store.root.expanduser().resolve()
            if configured_root != local_root:
                try:
                    local_pools = PreselectionPoolStore(store.root).read_all(selected)
                except FileNotFoundError:
                    local_pools = []
                except (OSError, ValueError, TypeError, KeyError):
                    local_pools = None
                if local_pools:
                    local_hk_pool = next(
                        (pool for pool in local_pools if pool.get("pool_id") == "hkconnect_d1_top100"),
                        None,
                    )
                    local_hk_missing = local_hk_pool is None or (
                        local_hk_pool.get("status") == "CANNOT_CONFIRM"
                        and not local_hk_pool.get("rows")
                        and local_hk_pool.get("source_role") == "EXPECTED_MISSING"
                        and local_hk_pool.get("source_path") == ""
                    )
                    local_hk_ready = bool(local_hk_pool and local_hk_pool.get("rows")) and (
                        str(local_hk_pool.get("status") or "").upper().endswith("_READY")
                        or str(local_hk_pool.get("status") or "").upper() in {"READY", "MATERIALIZED", "AVAILABLE"}
                    )
                    if local_hk_missing and not local_hk_ready:
                        source_pending = False
                        source_unconfirmed: str | None = None
                        try:
                            from infrastructure.interprocess_lock import owned_interprocess_lock

                            source_store = PreselectionPoolStore(resolved_pool_source)
                            with owned_interprocess_lock(
                                source_store.root / ".import.lock",
                                timeout_seconds=10,
                                timeout_message="data-root import lock timeout",
                            ) as source_lock:
                                pending_relative_for = getattr(
                                    source_store, "_pending_relative", None
                                )
                                pending_relative = (
                                    pending_relative_for(
                                        trade_date=selected,
                                        pool_id="hkconnect_d1_top100",
                                    )
                                    if callable(pending_relative_for)
                                    else (
                                        "preselection_pending_commits/"
                                        f"{selected}/hkconnect_d1_top100.json"
                                    )
                                )
                                try:
                                    source_store._io.read_bytes(pending_relative)
                                except FileNotFoundError:
                                    snapshot_reader = source_store.read_pool_snapshot
                                    if "lock_lease" in inspect.signature(
                                        snapshot_reader
                                    ).parameters:
                                        source_snapshot = snapshot_reader(
                                            selected,
                                            "hkconnect_d1_top100",
                                            lock_lease=source_lock,
                                        )
                                    else:
                                        # R9's descriptor-anchored snapshot reader
                                        # is already read-only and does not accept a
                                        # lease keyword.  The caller still holds the
                                        # same root import lock around pending check
                                        # and trio read.
                                        source_snapshot = snapshot_reader(
                                            selected, "hkconnect_d1_top100"
                                        )
                                else:
                                    source_pending = True
                                    source_snapshot = None
                        except FileNotFoundError:
                            source_snapshot = None
                        except OSError:
                            source_snapshot = None
                            source_unconfirmed = "source_read_unavailable"
                        except (ValueError, TypeError, KeyError):
                            source_snapshot = None
                            source_unconfirmed = "source_integrity_unconfirmed"
                        if source_pending or source_unconfirmed is not None:
                            response["configured_hk_pool_fallback"] = {
                                "applied": False,
                                "status": "CANNOT_CONFIRM",
                                "reason": (
                                    "source_pending_commit"
                                    if source_pending
                                    else source_unconfirmed
                                ),
                                "read_policy": "read_only_exact_date",
                                "target_date": selected,
                                "production_allowed": False,
                                "buy_gate_updated": False,
                                "orders_sent": False,
                            }
                        source_pool = source_snapshot.get("artifact") if isinstance(source_snapshot, Mapping) else None
                        if isinstance(source_pool, Mapping) and _is_exact_configured_hk_pool(source_pool, selected):
                            merged_pools = [
                                pool for pool in local_pools
                                if pool.get("pool_id") != "hkconnect_d1_top100"
                            ]
                            merged_pools.append(dict(source_pool))
                            response = _preselection_response_from_pools(
                                merged_pools,
                                trade_date=selected,
                                limit=limit,
                                offset=page_offset, name_pool_root=resolved_pool_source,
                            )
                            response["configured_hk_pool_fallback"] = {
                                "applied": True,
                                "read_policy": "read_only_exact_date",
                                "target_date": selected,
                                "pool_artifact_sha256": source_snapshot.get("artifact_raw_sha256"),
                                "pool_manifest_sha256": source_snapshot.get("manifest_raw_sha256"),
                                "pool_receipt_sha256": source_snapshot.get("receipt_raw_sha256"),
                                "producer_run_id": source_pool.get("source_run_id"),
                                "producer_artifact_sha256": source_pool.get("source_sha256"),
                                "producer_manifest_sha256": source_pool.get("source_manifest_sha256"),
                                "producer_receipt_sha256": source_pool.get("source_receipt_sha256"),
                            }
        from domains._preselection_parts.source_validation import project_a_display_names
        response = project_a_display_names(response, selected, resolved_pool_source)
        response = _project_wechat_input_gap(response, resolved_pool_source, selected)
        response = _apply_v4_display_projection(response, selected)
        return _project_dated_hk_name_response(response, selected)
