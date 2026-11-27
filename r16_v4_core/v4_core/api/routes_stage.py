"""Pure V4 Stage Selection & Preselection Pools router (Domain 2: 阶段选股域, 11 routes, strict UI validator parity)."""
from __future__ import annotations

from datetime import date as dt_date
from typing import Any

from fastapi import APIRouter, Query

from v4_core.runner.cache_lanes import STAGE7_ID, read_stage7
from v4_core.runner.evidence import EvidenceError
from v4_core.storage.db import V4Store, normalize_compact_date, normalize_symbol

STAGE_META = [
    {"stage": "09:25", "stage_id": "STAGE_0925", "label": "竞价留档", "role": "PREOPEN_AUCTION"},
    {"stage": "09:30-09:35", "stage_id": "STAGE_0930_0935", "label": "开盘观察与二筛", "role": "OPENING_RESCREEN"},
    {"stage": "14:45-15:00", "stage_id": "STAGE_1445_1500", "label": "Stage7 尾盘归集", "role": "A_SHARE_1MIN_STAGE_1445_1500"},
]


def _page_entry(total_rows: int, offset: int, limit: int, returned_rows: int) -> dict[str, Any]:
    has_more = (offset + returned_rows) < total_rows
    return {
        "total_rows": total_rows,
        "offset": offset,
        "limit": limit,
        "returned_rows": returned_rows,
        "has_more": has_more,
        "next_offset": (offset + limit) if has_more else None,
        "complete": not has_more,
    }


_STAGE_READBACK_CLAIMS = frozenset({
    "status", "source_status", "selection_status", "owner_selection_status", "display_status", "display_mode",
    "data_level", "recommendation_status", "selection_manifest_receipt", "selection_manifest_receipt_verified",
    "receipt_verified", "execution_evidence", "execution_verified", "natural_verified", "readback_provenance",
    "research_only", "write_performed", "production_allowed", "buy_gate_updated", "orders_sent",
})


def _stage_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stage_metadata(item) for key, item in value.items() if key.casefold() not in _STAGE_READBACK_CLAIMS}
    if isinstance(value, list):
        return [_stage_metadata(item) for item in value]
    return value


def _stage_lane(row: dict[str, Any]) -> str:
    return "HK" if row.get("market") in {"HK", "HK_CONNECT"} else "A"


def _stage_readback_status(row: dict[str, Any]) -> tuple[str, str]:
    payload = row.get("payload")
    source_status = payload.get("source_status", "") if isinstance(payload, dict) else ""
    stored_status = str(row["status"]).strip().upper()
    source_partial = "PARTIAL" in str(source_status).upper()
    if "PARTIAL" in stored_status or source_partial:
        status = "PARTIAL"
    elif stored_status in {"CANNOT_CONFIRM", "UNKNOWN", "WATCH_ONLY"}:
        status = stored_status
    else:
        status = "OBSERVATION_UNVERIFIED"
    return status, "PARTIAL" if source_partial else "CANNOT_CONFIRM"


def _stage_aggregate_status(row_count: int, has_partial: bool) -> str:
    if has_partial:
        return "PARTIAL"
    return "OBSERVATION_UNVERIFIED" if row_count else "CANNOT_CONFIRM"


def _enrich_stage_row(store: V4Store, trade_date: str, stage_id: str, row: dict[str, Any]) -> dict[str, Any]:
    raw_sym = str(row["symbol"])
    canon = normalize_symbol(raw_sym) or raw_sym
    resolved_name = (
        row.get("display_name")
        or store.resolve_security_name(trade_date, canon)
        or store.resolve_security_name(trade_date, raw_sym)
    )
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    readback_status, source_status = _stage_readback_status(row)
    out = {
        **_stage_metadata(payload),
        "trade_date": trade_date,
        "stage": row["stage"],
        "stage_id": stage_id,
        "market": _stage_lane(row),
        "symbol": raw_sym,
        "canonical_symbol": canon,
        "name": resolved_name,
        "display_name": resolved_name,
        "rank": row["rank"],
        "signal_date": row["signal_date"] or trade_date,
        "status": readback_status,
        "selection_status": readback_status,
        "source_status": source_status,
        "owner_selection_status": "WATCH_ONLY" if payload.get("owner_selection_status") == "WATCH_ONLY" else "CANNOT_CONFIRM",
        "display_mode": "OBSERVATION_UNVERIFIED",
        "display_status": readback_status,
        "execution_ref": row["execution_ref"],
        "data_level": "OBSERVATION_UNVERIFIED",
        "selection_manifest_receipt_verified": False,
        "execution_verified": False,
        "natural_verified": False,
        "recommendation_status": "WATCH_ONLY",
        "execution_evidence": {
            "status": "CANNOT_CONFIRM",
            "execution_verified": False,
            "natural_verified": False,
        },
        "RESEARCH_ONLY": True,
        "write_performed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "readback_provenance": {
            "store": "SQLITE_STAGE_SELECTIONS",
            "stored_trade_date": row["trade_date"],
            "stored_stage": row["stage"],
            "stored_status": row["status"],
            "stored_execution_ref": row["execution_ref"],
            "receipt_verified": False,
        },
    }
    if resolved_name and not out.get("stock_name"):
        out["stock_name"] = resolved_name
    return out


def _build_stage_payload(
    store: V4Store,
    trade_date: str,
    stage: str | None,
    market: str | None,
    limit: int | None,
) -> dict[str, Any]:
    stage_id = stage or "STAGE_0930_0935"
    req_market = market.upper() if market else None
    db_market = "HK" if req_market in {"HK", "HK_CONNECT"} else ("A" if req_market in {"A", "A_SHARE"} else None)
    rows = store.get_stage_selections(trade_date, stage=stage_id, market=db_market)
    totals = {"A": 0, "HK": 0}
    partial_lanes = set()
    for row in rows:
        lane = _stage_lane(row)
        totals[lane] += 1
        status, _ = _stage_readback_status(row)
        if status == "PARTIAL":
            partial_lanes.add(lane)
    displayed = rows[:limit] if limit is not None and limit > 0 else rows
    enriched = [_enrich_stage_row(store, trade_date, stage_id, row) for row in displayed]

    a_rows = [r for r in enriched if r["market"] == "A"]
    hk_rows = [r for r in enriched if r["market"] == "HK"]
    exec_refs = sorted({r["execution_ref"] for r in enriched if r.get("execution_ref")})
    markets = {}
    selection_markets = {}
    for lane, alias, lane_rows in (("A", "A_SHARE", a_rows), ("HK", "HK_CONNECT", hk_rows)):
        has_partial = lane in partial_lanes
        lane_total = totals[lane]
        mode = "OBSERVATION_UNVERIFIED" if lane_total else "CANNOT_CONFIRM"
        state = _stage_aggregate_status(lane_total, has_partial)
        summary = {
            "market": alias,
            "status": state,
            "selection_status": state,
            "source_status": "PARTIAL" if has_partial else "CANNOT_CONFIRM",
            "display_mode": mode,
            "data_level": mode,
            "candidate_count": lane_total,
            "source_rows": None,
            "requested_rows": None,
            "selected_rows": lane_total or None,
            "observation_count": lane_total,
            "rows": lane_rows,
            "selection_manifest_receipt_verified": False,
            "execution_verified": False,
            "natural_verified": False,
        }
        markets[lane] = summary
        selection_markets[alias] = {
            **summary,
            "trade_date": trade_date,
            "stage_id": stage_id,
            "coverage_ratio": None,
            "source_evidence": sorted({row["execution_ref"] for row in lane_rows if row["execution_ref"]}),
            "cannot_confirm": ["OWNER_SELECTION_MANIFEST_RECEIPT_UNVERIFIED"],
        }
    overall_status = _stage_aggregate_status(len(rows), bool(partial_lanes))
    return {
        "schema_version": "v4.stage_workbench.v1",
        "trade_date": trade_date,
        "date": trade_date,
        "target_date": trade_date,
        "stage_id": stage_id,
        "status": overall_status,
        "execution_verified": False,
        "natural_verified": False,
        "stage": {
            "stage_id": stage_id,
            "status": overall_status,
            "display_status": overall_status,
        },
        "market": req_market or "ALL",
        "markets": markets,
        "market_summaries": markets,
        "selection_markets": selection_markets,
        "selected_a_rows": totals["A"],
        "selected_hk_rows": totals["HK"],
        "selected_total_rows": len(rows),
        "count": len(enriched),
        "unified_rows": enriched,
        "rows": enriched,
        "items": enriched,
        "execution_evidence": {
            "status": "CANNOT_CONFIRM",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "execution_verified": False,
            "natural_verified": False,
            "write_performed": False,
            "cannot_confirm": ["OWNER_EXECUTION_RECEIPT_UNVERIFIED"],
            "execution_refs": exec_refs,
            "stage7_role": "A_SHARE_1MIN_STAGE_1445_1500",
        },
        "cannot_confirm": ["OWNER_SELECTION_MANIFEST_RECEIPT_UNVERIFIED"],
        "RESEARCH_ONLY": True,
        "write_performed": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def build_stage_router(store: V4Store) -> APIRouter:
    router = APIRouter(prefix="/api/v4", tags=["stage-selection"])

    @router.get("/meta/stages")
    def get_meta_stages():
        return {"stages": STAGE_META, "count": len(STAGE_META), "status": "READY"}

    @router.get("/preselection-pools")
    def get_preselection_pools(
        date: str | None = Query(default=None),
        limit: int = Query(default=200),
        offset: int = Query(default=0),
        page: int = Query(default=1),
    ):
        if date:
            req_date = date
        else:
            dates = store.list_run_dates()
            req_date = normalize_compact_date(dates[0]) if dates else dt_date.today().strftime("%Y%m%d")

        raw_rows = store.get_preselection_pools(req_date)
        grouped: dict[str, list[dict[str, Any]]] = {}
        unified: list[dict[str, Any]] = []
        for r in raw_rows:
            canon = normalize_symbol(r["symbol"]) or r["symbol"]
            resolved_name = r.get("display_name") or store.resolve_security_name(req_date, canon)
            mkt = "HK" if str(r["market"]).upper() in {"HK", "HK_CONNECT"} else "A"
            entry = {
                "pool_name": r["pool_name"],
                "market": mkt,
                "symbol": r["symbol"],
                "canonical_symbol": canon,
                "name": resolved_name,
                "display_name": resolved_name,
                "status": r["status"],
                **(r.get("payload") if isinstance(r.get("payload"), dict) else {}),
            }
            grouped.setdefault(r["pool_name"], []).append(entry)
            unified.append(entry)

        # WeChat pool backed by unified pure-V4 research_materials
        wechat_items = store.query_research_materials(source_type="wechat", trade_date=req_date, limit=limit)
        if wechat_items and "wechat_materials" not in grouped:
            grouped["wechat_materials"] = [
                {
                    "pool_name": "wechat_materials",
                    "market": "HK" if m["market"] == "HK" else "A",
                    "symbol": m["symbol"],
                    "name": store.resolve_security_name(req_date, m["symbol"]) or m["symbol"],
                    "title": m["title"],
                    "status": "READY",
                }
                for m in wechat_items
                if m.get("symbol")
            ]

        eff_offset = offset if offset > 0 else max(0, (page - 1) * limit)
        sliced_unified = unified[eff_offset : eff_offset + limit]
        a_rows = [r for r in unified if r["market"] == "A"]
        hk_rows = [r for r in unified if r["market"] == "HK"]
        sliced_a = a_rows[eff_offset : eff_offset + limit]

        pools_list: list[dict[str, Any]] = []
        pool_pages: dict[str, dict[str, Any]] = {}
        for pool_id, items in sorted(grouped.items()):
            p_slice = items[eff_offset : eff_offset + limit]
            p_mkt = items[0]["market"] if items else "A"
            p_page = _page_entry(len(items), eff_offset, limit, len(p_slice))
            pool_pages[pool_id] = p_page
            pools_list.append(
                {
                    "pool_id": pool_id,
                    "market": p_mkt,
                    "status": "READY" if items else "READY_EMPTY",
                    "pool_size": len(items),
                    "returned_rows": len(p_slice),
                    "page_offset": eff_offset,
                    "page_limit": limit,
                    "complete": p_page["complete"],
                    "has_more": p_page["has_more"],
                    "rows": p_slice,
                }
            )

        data_status = "READY" if (unified or wechat_items) else "MATERIALIZED_EMPTY"
        root_page = _page_entry(len(unified), eff_offset, limit, len(sliced_unified))
        pagination = {
            **root_page,
            "arrays": {
                "unified_rows": root_page,
                "a_all_pool_rows": _page_entry(len(a_rows), eff_offset, limit, len(sliced_a)),
                "a_source_only_rows": _page_entry(len(a_rows), eff_offset, limit, len(sliced_a)),
            },
            "pools": pool_pages,
        }
        return {
            "trade_date": req_date,
            "requested_date": req_date,
            "selected_date": req_date,
            "date": req_date,
            "data_status": data_status,
            "status": data_status,
            "pool_count": len(pools_list),
            "pools": pools_list,
            "row_count": len(unified),
            "rows": sliced_unified,
            "unified_row_count": len(unified),
            "unified_rows": sliced_unified,
            "a_all_pool_row_count": len(a_rows),
            "a_all_pool_rows": sliced_a,
            "a_source_only_row_count": len(a_rows),
            "a_source_only_rows": sliced_a,
            "market_totals": {"A": len(a_rows), "HK": len(hk_rows)},
            "pagination": pagination,
            "page": {"page": page, "limit": limit, "offset": eff_offset, "total": len(unified)},
            "wechat_upstream_mode": "PURE_V4_RESEARCH_MATERIALS",
            "write_policy": "read_only",
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "write_performed": False,
        }

    @router.get("/workbench/stage")
    def get_workbench_stage(
        date: str | None = Query(default=None),
        stage: str | None = Query(default=None),
        limit: int = Query(default=50),
        market: str | None = Query(default=None),
        backfill_run_id: str | None = Query(default=None),
        source_date: str | None = Query(default=None),
    ):
        target_date = date or (normalize_compact_date(store.list_run_dates()[0]) if store.list_run_dates() else dt_date.today().strftime("%Y%m%d"))
        payload = _build_stage_payload(store, target_date, stage, market, limit)
        payload["backfill_run_id"] = backfill_run_id
        if stage == STAGE7_ID and (market is None or market.upper() in {"A", "A_SHARE"}):
            try:
                binding, rows = read_stage7(store.db_path.parent, source_date or target_date,
                                            target_date if source_date else None)
                shown = rows[:limit] if limit > 0 else rows
                payload["source_pool"] = {**binding, "rows": shown, "returned_rows": len(shown)}
            except EvidenceError as exc:
                payload["source_pool"] = {"status": "CANNOT_CONFIRM", "reason": str(exc), "rows": []}
        return payload

    @router.get("/workbench/stage-batch")
    def get_workbench_stage_batch(
        date: str | None = Query(default=None),
        stages: str | None = Query(default=None),
    ):
        target_date = date or (normalize_compact_date(store.list_run_dates()[0]) if store.list_run_dates() else dt_date.today().strftime("%Y%m%d"))
        stage_list = [s.strip() for s in (stages or "").split(",") if s.strip()] or [m["stage_id"] for m in STAGE_META]
        results = [
            {"date": target_date, "trade_date": target_date, "stage": st, "payload": _build_stage_payload(store, target_date, st, None, 50)}
            for st in stage_list
        ]
        summaries = {}
        for result in results:
            payload = result["payload"]
            summaries[result["stage"]] = {
                "trade_date": target_date,
                "stage": payload["stage"],
                "status": payload["status"],
                "selected_a_rows": payload["selected_a_rows"],
                "selected_hk_rows": payload["selected_hk_rows"],
                "markets": {
                    market: {key: value for key, value in summary.items() if key != "rows"}
                    for market, summary in payload["markets"].items()
                },
            }
        states = {summary["status"] for summary in summaries.values()}
        status = "CANNOT_CONFIRM"
        if "PARTIAL" in states:
            status = "PARTIAL"
        elif "OBSERVATION_UNVERIFIED" in states:
            status = "OBSERVATION_UNVERIFIED"
        return {
            "schema_version": "v4.stage_timeline_batch.v1",
            "date": target_date,
            "trade_date": target_date,
            "stage_ids": stage_list,
            "stages": summaries,
            "items": results,
            "status": status,
            "execution_verified": False,
            "natural_verified": False,
            "RESEARCH_ONLY": True,
            "write_performed": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @router.post("/workbench/stage/ensure")
    def post_workbench_stage_ensure(
        date: str | None = Query(default=None),
        stage: str | None = Query(default=None),
        force: bool = Query(default=False),
    ):
        target_date = date or dt_date.today().strftime("%Y%m%d")
        target_stage = stage or "STAGE_0930_0935"
        existing = store.get_stage_selections(target_date, stage=target_stage)
        refs = {row["execution_ref"] for row in existing if row.get("execution_ref")}
        return {
            "ok": True,
            "ensure_status": "MATERIALIZED" if refs else "CANNOT_CONFIRM",
            "trade_date": target_date,
            "date": target_date,
            "stage": target_stage,
            "stage_id": target_stage,
            "force": force,
            "count": len(existing),
            "execution_ref": next(iter(refs)) if len(refs) == 1 else None,
            "message": f"Stage {target_stage} readback for {target_date}",
            "write_performed": False,
        }

    @router.get("/manager/stage-selection")
    def get_manager_stage_selection(
        date: str | None = Query(default=None),
        stage: str | None = Query(default=None),
        market: str | None = Query(default=None),
        limit: int = Query(default=50),
    ):
        target_date = date or (normalize_compact_date(store.list_run_dates()[0]) if store.list_run_dates() else dt_date.today().strftime("%Y%m%d"))
        return _build_stage_payload(store, target_date, stage, market, limit)

    @router.get("/stage-center/selection")
    def get_stage_center_selection(
        date: str | None = Query(default=None),
        stage: str | None = Query(default=None),
        limit: int = Query(default=50),
    ):
        target_date = date or (normalize_compact_date(store.list_run_dates()[0]) if store.list_run_dates() else dt_date.today().strftime("%Y%m%d"))
        return _build_stage_payload(store, target_date, stage, None, limit)

    @router.post("/stage-center/selection/ensure")
    def post_stage_center_selection_ensure(
        date: str | None = Query(default=None),
        stage: str | None = Query(default=None),
        force: bool = Query(default=False),
    ):
        return post_workbench_stage_ensure(date=date, stage=stage, force=force)

    @router.get("/research/opening-observation")
    def get_opening_observation(
        date: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        candidate_source_date: str | None = Query(default=None),
    ):
        target_date = date or (normalize_compact_date(store.list_run_dates()[0]) if store.list_run_dates() else dt_date.today().strftime("%Y%m%d"))
        rows = store.get_stage_selections(target_date, stage="STAGE_0930_0935")
        if symbol:
            canon = normalize_symbol(symbol)
            rows = [r for r in rows if normalize_symbol(r["symbol"]) == canon]
        enriched = [_enrich_stage_row(store, target_date, "STAGE_0930_0935", r) for r in rows]
        return {
            "trade_date": target_date,
            "date": target_date,
            "candidate_source_date": candidate_source_date,
            "symbol": normalize_symbol(symbol) if symbol else None,
            "status": _stage_aggregate_status(len(enriched), any(row["status"] == "PARTIAL" for row in enriched)),
            "natural_verified": False,
            "rows": enriched,
        }

    @router.get("/research/selection")
    def get_research_selection(
        target_trade_date: str = Query(...),
        market_focus: str | None = Query(default=None),
    ):
        selections = store.get_workbench_selections(target_trade_date)
        status = "MATERIALIZED" if selections else "NOT_MATERIALIZED"
        shortlist = [
            {
                "symbol": sym,
                "display_name": store.resolve_security_name(target_trade_date, sym) or sym,
                "selection_group": grp,
            }
            for sym, grp in selections.items()
        ]
        return {
            "status": status,
            "requested_date": target_trade_date,
            "market_focus": market_focus,
            "formal_shortlist": shortlist,
            "counts": {"total": len(shortlist)},
            "lineage": {"engine": "v4_core"},
            "cannot_confirm": [] if shortlist else [f"SELECTION_NOT_MATERIALIZED:{target_trade_date}"],
            "RESEARCH_ONLY": True,
        }

    @router.get("/research/selection/manager-decision")
    def get_manager_decision(target_trade_date: str = Query(...)):
        return {
            "status": "NOT_MATERIALIZED",
            "requested_date": target_trade_date,
            "decision_state": "PENDING",
            "lineage": {"engine": "v4_core"},
            "ADD": [],
            "KEEP": [],
            "REMOVE": [],
            "RESEARCH_ONLY": True,
        }

    return router
