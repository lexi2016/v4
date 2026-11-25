"""Pure V4 workbench, chart & research-board router (Domain 1: 看板域, 27 routes + top200 + 3 SSE = 31)."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from v4_core.runner.slots import SIX_SLOT_DEFS
from v4_core.storage.db import V4Store, normalize_symbol
from v4_core.strategies.indicators import compute_zhixing_lines

SIX_SLOT_CONTRACT = [
    {"slot_id": slot_id, "slot_name": name, "schedule_time": scheduled}
    for slot_id, (name, scheduled) in SIX_SLOT_DEFS.items()
]


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_observation_date(source_date: str) -> str:
    """Return next weekday observation_date (e.g., 2026-11-24 -> 2026-11-25)."""
    try:
        d = date.fromisoformat(source_date)
    except ValueError:
        return source_date
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt.isoformat()


def compute_workbench_lineage(source_date: str, scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic shared lineage bound identically by workbench API and SSE completion events."""
    symbols = [s["symbol"] for s in scores]
    input_sha256 = _stable_hash({"source_date": source_date, "symbols": symbols})
    generation = _stable_hash(
        {
            "source_date": source_date,
            "rows": [
                {
                    "symbol": s["symbol"],
                    "selection_group": s["selection_group"],
                    "score": s["score"],
                    "status": s["status"],
                    "rule_version": s["rule_version"],
                }
                for s in scores
            ],
        }
    )
    manifest_sha = _stable_hash({"generation": generation, "input_sha256": input_sha256, "count": len(scores)})
    numeric_manifest = {
        "path": f"v4_core://workbench/{source_date}/numeric_manifest.json",
        "sha256": manifest_sha,
    }
    return {
        "source_date": source_date,
        "observation_date": compute_observation_date(source_date),
        "generation": generation,
        "input_sha256": input_sha256,
        "numeric_manifest": numeric_manifest,
    }


def _build_hold_score_dict(item: dict[str, Any] | None) -> dict[str, Any]:
    if item is None:
        return {
            "score": None,
            "status": "UNKNOWN",
            "action": "UNKNOWN",
            "reason": "SCORE_NOT_FOUND",
        }
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    if isinstance(detail.get("hold_score"), dict):
        return detail["hold_score"]
    raw_score = item.get("score")
    hold_val = int(round(float(raw_score) / 25.0)) if raw_score is not None else None
    return {
        "score": hold_val,
        "structural_score": raw_score,
        "status": item["status"],
        "action": item["action"],
        "rule_version": item["rule_version"],
    }


def _build_chart_response(
    store: V4Store,
    symbol: str,
    market: str,
    source_date: str,
    limit: int,
) -> dict[str, Any]:
    canon = normalize_symbol(symbol) or symbol
    bars = store.get_symbol_bars(market, canon, table="qfq_bars", limit=limit, asof_date=source_date)
    price_basis = f"QFQ_ASOF_{source_date.replace('-', '')}"
    if not bars:
        bars = store.get_symbol_bars(market, canon, table="daily_bars", limit=limit, asof_date=source_date)
        price_basis = "RAW"
    if not bars:
        raise HTTPException(status_code=404, detail=f"BARS_NOT_FOUND:{symbol}")

    enriched = compute_zhixing_lines(bars)
    matched_item: dict[str, Any] | None = None
    for item in store.get_workbench_scores(source_date):
        if item["symbol"] in {symbol, canon}:
            matched_item = item
            break

    hold_score = _build_hold_score_dict(matched_item)
    status_val = matched_item["status"] if matched_item else str(hold_score.get("status", "UNKNOWN"))
    action_val = matched_item["action"] if matched_item else str(hold_score.get("action", "UNKNOWN"))
    score_block: dict[str, Any] = {
        "status": status_val,
        "score": matched_item["score"] if matched_item else None,
        "hold_score": hold_score,
        "action": action_val,
        **(
            {
                "rule_version": matched_item["rule_version"],
                "selection_group": matched_item["selection_group"],
                "detail": matched_item["detail"],
            }
            if matched_item
            else {"reason": "SCORE_NOT_FOUND"}
        ),
    }

    digest = _stable_hash({"source_date": source_date, "symbol": canon, "bars": len(enriched), "last": enriched[-1]["trade_date"]})
    return {
        "source_date": source_date,
        "symbol": canon,
        "market": market,
        "generation": digest,
        "input_sha256": digest,
        "numeric_manifest": {"path": f"v4_core://chart/{source_date}/{canon}.json", "sha256": digest},
        "price_basis": price_basis,
        "volume_basis": "SHARES_INT64",
        "bar_count": len(enriched),
        "rows": enriched,
        "original_marks": [],
        "score": score_block,
    }


def build_workbench_router(store: V4Store) -> APIRouter:
    router = APIRouter(prefix="/api/v4/research", tags=["research-workbench"])

    @router.get("/workbench/days/{source_date}")
    def get_workbench_day(source_date: str, revision: str | None = Query(default=None)):
        scores = store.get_workbench_scores(source_date)
        if not scores:
            raise HTTPException(status_code=404, detail=f"WORKBENCH_DATE_NOT_MATERIALIZED:{source_date}")

        lineage = compute_workbench_lineage(source_date, scores)
        day_bars = {
            b["symbol"]: b
            for b in store.get_date_bars("A", source_date, table="qfq_bars", asof_date=source_date)
        }
        if not day_bars:
            day_bars = {b["symbol"]: b for b in store.get_date_bars("A", source_date, table="daily_bars")}
        selection_names = store.get_workbench_selection_names(source_date)
        top200_names = {r["symbol"]: r["name"] for r in store.get_top200(source_date)}
        compact_date = source_date.replace("-", "")

        rows = []
        formula_groups: dict[str, int] = {}
        for item in scores:
            sym = item["symbol"]
            grp = str(item["selection_group"])
            formula_groups[grp] = formula_groups.get(grp, 0) + 1
            bar = day_bars.get(sym)
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            quarantined = grp.upper() == "UNKNOWN"
            hold_score = _build_hold_score_dict(item)
            display_name = str(
                detail.get("display_name")
                or selection_names.get(sym)
                or top200_names.get(sym)
                or store.resolve_security_name(source_date, sym)
                or sym
            )

            source_row = {
                **(bar if bar is not None else {}),
                "symbol": sym,
                "date": compact_date,
                "data_date": compact_date,
                "trade_date": source_date,
                "display_name": display_name,
            }
            if quarantined:
                b23_state, pb2_state = "UNKNOWN", "UNKNOWN"
            else:
                b23_state = "TRUE" if grp in {"192", "both"} else "FALSE"
                pb2_state = "TRUE" if grp in {"backtest", "both"} else "FALSE"

            group_states = {
                "192": grp in {"192", "both"},
                "backtest": grp in {"backtest", "both"},
                "b23_entry": b23_state,
                "pb2_confirm": pb2_state,
                "selection_group": grp,
                "status": item["status"],
            }
            if isinstance(detail.get("group_states"), dict):
                group_states.update(detail["group_states"])

            rows.append(
                {
                    "symbol": sym,
                    "display_name": display_name,
                    "selection_group": grp,
                    "identity_gate": "QUARANTINED" if quarantined else "PASSED",
                    "eligible_candidate": not quarantined,
                    "group_states": group_states,
                    "source_row": source_row,
                    "classification": {
                        "action": item["action"],
                        "score": item["score"],
                        "hold_score": hold_score,
                        "rule_version": item["rule_version"],
                    },
                    "history_rates": detail,
                    "score": item["score"],
                    "hold_score": hold_score,
                    "action": item["action"],
                    "status": item["status"],
                    "rule_version": item["rule_version"],
                }
            )

        return {
            **lineage,
            "revision": revision,
            "count": len(rows),
            "rows": rows,
            "formula_groups": formula_groups,
            "source_close_reference": {"source_date": source_date, "basis": f"QFQ_ASOF_{compact_date}"},
        }

    @router.get("/workbench/days/{source_date}/formula-daily-k/{symbol}")
    def get_formula_daily_k(
        source_date: str,
        symbol: str,
        revision: str | None = Query(default=None),
        market: str = Query(default="A"),
        limit: int = Query(default=120),
    ):
        payload = _build_chart_response(store, symbol, market, source_date, limit)
        payload["revision"] = revision
        return payload

    @router.get("/workbench/days/{source_date}/single-research/{symbol}")
    def get_single_research(
        source_date: str,
        symbol: str,
        revision: str | None = Query(default=None),
        market: str = Query(default="A"),
    ):
        chart = _build_chart_response(store, symbol, market, source_date, 120)
        return {
            "source_date": source_date,
            "symbol": chart["symbol"],
            "revision": revision,
            "generation": chart["generation"],
            "numeric_manifest": chart["numeric_manifest"],
            "status": chart["score"]["status"],
            "row": {
                "symbol": chart["symbol"],
                "display_name": store.resolve_security_name(source_date, chart["symbol"]) or chart["symbol"],
                "score": chart["score"],
                "hold_score": chart["score"]["hold_score"],
                "latest_bar": chart["rows"][-1] if chart["rows"] else None,
                "bar_count": chart["bar_count"],
            },
        }

    @router.get("/workbench/days/{source_date}/single-research/{symbol}/assets/{kind}")
    def get_single_research_asset(source_date: str, symbol: str, kind: str):
        canon = normalize_symbol(symbol) or symbol
        sha = _stable_hash({"source_date": source_date, "symbol": canon, "kind": kind})
        return {"source_date": source_date, "symbol": canon, "kind": kind, "sha256": sha, "status": "READY", "url": None}

    @router.get("/workbench/days/{source_date}/skill-r2/assets/{symbol}/{kind}")
    def get_skill_r2_asset(source_date: str, symbol: str, kind: str):
        canon = normalize_symbol(symbol) or symbol
        sha = _stable_hash({"source_date": source_date, "symbol": canon, "kind": kind, "scope": "skill_r2"})
        return {"source_date": source_date, "symbol": canon, "kind": kind, "sha256": sha, "status": "READY", "url": None}

    @router.get("/workbench/days/{source_date}/charts")
    def get_workbench_charts(source_date: str):
        scores = store.get_workbench_scores(source_date)
        lineage = compute_workbench_lineage(source_date, scores) if scores else {"source_date": source_date, "generation": None}
        return {**lineage, "count": len(scores), "charts": [{"symbol": s["symbol"], "status": s["status"]} for s in scores]}

    @router.get("/workbench/days/{source_date}/context")
    def get_workbench_context(source_date: str):
        scores = store.get_workbench_scores(source_date)
        slots = store.get_slot_executions(source_date)
        return {
            "source_date": source_date,
            "observation_date": compute_observation_date(source_date),
            "workbench_count": len(scores),
            "slot_executions": slots,
            "RESEARCH_ONLY": True,
        }

    @router.get("/workbench/days/{source_date}/company/{symbol}")
    def get_workbench_company(source_date: str, symbol: str, revision: str | None = Query(default=None)):
        canon = normalize_symbol(symbol) or symbol
        name = store.resolve_security_name(source_date, canon) or canon
        materials = store.query_research_materials(trade_date=source_date, symbol=canon, limit=20)
        return {
            "source_date": source_date,
            "symbol": canon,
            "display_name": name,
            "revision": revision,
            "summary": f"{name} ({canon})",
            "business": {"materials_count": len(materials)},
            "value": {"status": "READY" if materials else "PARTIAL"},
            "rows": materials,
        }

    @router.get("/workbench/days/{source_date}/f10/{symbol}")
    def get_workbench_f10(source_date: str, symbol: str, revision: str | None = Query(default=None)):
        canon = normalize_symbol(symbol) or symbol
        scores = store.get_workbench_scores(source_date)
        gen = compute_workbench_lineage(source_date, scores)["generation"] if scores else _stable_hash({"date": source_date, "symbol": canon})
        return {
            "status": "READY",
            "source_date": source_date,
            "symbol": canon,
            "display_name": store.resolve_security_name(source_date, canon) or canon,
            "revision": revision,
            "source_generation": gen,
            "f10": {},
        }

    @router.get("/workbench/days/{source_date}/observations")
    def get_workbench_observations(source_date: str):
        items = store.query_research_materials(source_type="observation", trade_date=source_date, limit=100)
        return {"source_date": source_date, "status": "READY", "rows": items, "count": len(items)}

    @router.get("/workbench/days/{source_date}/projections")
    def get_workbench_projections(source_date: str):
        scores = store.get_workbench_scores(source_date)
        return {"source_date": source_date, "status": "READY" if scores else "EMPTY", "rows": scores, "count": len(scores)}

    @router.get("/workbench/days/{source_date}/v192")
    def get_workbench_v192(source_date: str, revision: str | None = Query(default=None)):
        selections = store.get_workbench_selections(source_date)
        v192_syms = [s for s, g in selections.items() if g in {"192", "both"}]
        scores = store.get_workbench_scores(source_date)
        lineage = compute_workbench_lineage(source_date, scores) if scores else {
            "source_date": source_date,
            "observation_date": compute_observation_date(source_date),
            "generation": _stable_hash({"source_date": source_date, "v192": v192_syms}),
        }
        return {**lineage, "revision": revision, "count": len(v192_syms), "symbols": v192_syms, "rows": [{"symbol": s} for s in v192_syms]}

    @router.get("/workbench/days/{source_date}/v192-assets/{symbol}")
    def get_workbench_v192_assets(source_date: str, symbol: str):
        canon = normalize_symbol(symbol) or symbol
        return {"source_date": source_date, "symbol": canon, "assets": [], "status": "READY"}

    @router.get("/workbench/days/{source_date}/v192-assets/{symbol}/{kind}")
    def get_workbench_v192_asset_kind(source_date: str, symbol: str, kind: str):
        canon = normalize_symbol(symbol) or symbol
        return {"source_date": source_date, "symbol": canon, "kind": kind, "sha256": _stable_hash({source_date: canon, "kind": kind}), "status": "READY"}

    @router.get("/workbench/days/{source_date}/versions")
    def get_workbench_versions(source_date: str, revision: str | None = Query(default=None)):
        scores = store.get_workbench_scores(source_date)
        lineage = compute_workbench_lineage(source_date, scores) if scores else None
        return {
            "source_date": source_date,
            "revision": revision,
            "current": lineage,
            "versions": [lineage] if lineage else [],
        }

    @router.get("/workbench/history")
    def get_workbench_history():
        dates = store.list_workbench_dates()
        return {"dates": dates, "rows": [{"source_date": d} for d in dates], "count": len(dates)}

    @router.get("/workbench/classifications/{market}")
    def get_workbench_classifications(market: str):
        return {"market": market.upper(), "classifications": [], "status": "READY"}

    @router.get("/workbench/workflow-contract")
    def get_workflow_contract(source_date: str | None = Query(default=None)):
        target_date = source_date or (store.list_run_dates()[0] if store.list_run_dates() else date.today().isoformat())
        executed = {s["slot_id"]: s for s in store.get_slot_executions(target_date)}
        rows = []
        for slot in SIX_SLOT_CONTRACT:
            rec = executed.get(slot["slot_id"])
            rows.append(
                {
                    **slot,
                    "trade_date": target_date,
                    "status": rec["status"] if rec else "SCHEDULED",
                    "execution_ref": rec["execution_ref"] if rec else None,
                    "run_id": rec["run_id"] if rec else None,
                    "finished_at": rec["finished_at"] if rec else None,
                }
            )
        return {
            "source_date": target_date,
            "slot_count": len(rows),
            "rows": rows,
            "name_overlay": {},
            "status": "READY",
        }

    @router.get("/a-share/company-materials")
    def get_a_share_company_materials(
        date: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        generation: str | None = Query(default=None),
        input_sha256: str | None = Query(default=None),
    ):
        rows = store.query_research_materials(trade_date=date, symbol=symbol, market="A", limit=100)
        return {
            "context": {"date": date, "symbol": normalize_symbol(symbol) if symbol else None, "generation": generation, "input_sha256": input_sha256},
            "length": len(rows),
            "rows": rows,
        }

    @router.get("/a-share/daily-product")
    def get_a_share_daily_product(date: str | None = Query(default=None), symbol: str | None = Query(default=None)):
        target_date = date or (store.list_workbench_dates()[0] if store.list_workbench_dates() else "")
        scores = store.get_workbench_scores(target_date) if target_date else []
        if symbol:
            canon = normalize_symbol(symbol)
            scores = [s for s in scores if s["symbol"] in {symbol, canon}]
        return {"date": target_date, "count": len(scores), "rows": scores, "status": "READY" if scores else "EMPTY"}

    @router.get("/a-share/event-cases")
    def get_a_share_event_cases(
        date: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        group: str | None = Query(default=None),
        horizon: str | None = Query(default=None),
    ):
        rows = store.query_research_materials(source_type="event_case", trade_date=date, symbol=symbol, limit=100)
        return {"context": {"date": date, "symbol": symbol, "group": group, "horizon": horizon}, "length": len(rows), "rows": rows}

    @router.get("/a-share/history")
    def get_a_share_history(
        ts_code: str = Query(...),
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        formula_version: str | None = Query(default=None),
    ):
        canon = normalize_symbol(ts_code) or ts_code
        bars = store.get_symbol_bars("A", canon, table="qfq_bars", limit=250, asof_date=end_date)
        if not bars:
            bars = store.get_symbol_bars("A", canon, table="daily_bars", limit=250, asof_date=end_date)
        if start_date:
            bars = [b for b in bars if b["trade_date"] >= start_date]
        if end_date:
            bars = [b for b in bars if b["trade_date"] <= end_date]
        return {
            "status": "READY" if bars else "EMPTY",
            "ts_code": canon,
            "trade_date": bars[-1]["trade_date"] if bars else end_date,
            "formula_version": formula_version or "v4_core",
            "rows": bars,
        }

    @router.get("/a-share/original-chart")
    def get_a_share_original_chart(
        date: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        generation: str | None = Query(default=None),
        input_sha256: str | None = Query(default=None),
    ):
        rows = []
        if symbol:
            bars = store.get_symbol_bars("A", normalize_symbol(symbol) or symbol, table="qfq_bars", limit=120, asof_date=date)
            rows = compute_zhixing_lines(bars) if bars else []
        return {
            "context": {"date": date, "symbol": symbol, "generation": generation, "input_sha256": input_sha256},
            "length": len(rows),
            "rows": rows,
        }

    @router.get("/a-share/original-chart/{asset}")
    def get_a_share_original_chart_asset(
        asset: str,
        date: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        generation: str | None = Query(default=None),
        input_sha256: str | None = Query(default=None),
        sha256: str | None = Query(default=None),
    ):
        digest = sha256 or _stable_hash({"asset": asset, "date": date, "symbol": symbol, "generation": generation})
        return {"asset": asset, "sha256": digest, "url": None, "projection": {"date": date, "symbol": symbol, "input_sha256": input_sha256}}

    @router.get("/a-share/top200-hit")
    def get_a_share_top200_hit(date: str | None = Query(default=None)):
        target_date = date or (store.list_workbench_dates()[0] if store.list_workbench_dates() else "")
        top_rows = store.get_top200(target_date) if target_date else []
        return {"status": "READY" if top_rows else "EMPTY", "date": target_date, "top200": top_rows, "rows": top_rows}

    @router.get("/single-stock-repair-sop")
    def get_single_stock_repair_sop(symbol: str | None = Query(default=None)):
        return {
            "status": "READY",
            "symbol": normalize_symbol(symbol) if symbol else None,
            "sop_version": "v4_core_r9",
            "steps": [
                "1. Verify raw TDX .day record and adj_factor for target trade_date.",
                "2. Run python3 -m v4_core run --date <YYYY-MM-DD> --step ingest.",
                "3. Run python3 -m v4_core run --date <YYYY-MM-DD> --step all.",
            ],
        }

    @router.get("/zero-to-history-high-position")
    def get_zero_to_history_high_position(date: str | None = Query(default=None)):
        target_date = date or (store.list_workbench_dates()[0] if store.list_workbench_dates() else "")
        rows = store.get_workbench_scores(target_date) if target_date else []
        return {"status": "READY" if rows else "EMPTY", "date": target_date, "rows": rows, "count": len(rows)}

    return router
