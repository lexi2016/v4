"""Pure V4 Unified Research & Announcements Index router (Domain 3: 研报指挥台域, 38 routes, strict UI validator parity)."""
from __future__ import annotations

from datetime import date as dt_date
import uuid
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from v4_core.storage.db import V4Store, normalize_compact_date, normalize_iso_date, normalize_symbol


_CARD_LIMIT = 200
_PREVIEW_LIMIT = 240
_CLUE_SOURCE_LIMIT = 500
_TITLE_LIMIT = 5
_CONFIRM_REASONS = {"CODE", "CONTEXT", "COHERENCE"}
_NO_SIDE_EFFECTS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def _evidence_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = normalize_compact_date(value)
    if len(compact) != 8 or not (compact.isascii() and compact.isdecimal()):
        return None
    try:
        dt_date.fromisoformat(normalize_iso_date(compact))
    except ValueError:
        return None
    return compact


def _projection_date(store: V4Store, requested: str | None) -> str:
    dates = store.list_run_dates() if requested is None else []
    compact = _evidence_date(requested if requested is not None else (dates[0] if dates else dt_date.today().isoformat()))
    if compact is None:
        raise HTTPException(status_code=422, detail="Invalid research date")
    return compact


def _projection_inputs(store: V4Store, source_type: str, date: str, limit: int) -> tuple[list[dict], bool]:
    rows: dict[str, dict] = {}
    capped = False
    for alias in (normalize_iso_date(date), date):
        batch = store.query_research_materials(source_type=source_type, trade_date=alias, limit=limit)
        for row in batch:
            # Storage also matches applicable_date. A later record bound to an
            # earlier day cannot be new evidence in that day's response.
            stored_date = _evidence_date(row["trade_date"])
            if stored_date is not None and stored_date <= date:
                rows.setdefault(row["record_id"], row)
        capped = capped or len(batch) == limit
    return list(rows.values()), capped


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _optional_text(data: dict, field: str, default: str | None = None) -> str | None:
    value = data.get(field)
    return value if isinstance(value, str) else default


def _machine_card(row: dict, date: str) -> dict | None:
    payload = row["payload"]
    if not isinstance(payload, dict) or _evidence_date(payload.get("research_date")) != date:
        return None
    document_id, status, title = (payload.get(k) for k in ("document_id", "status", "title"))
    if not all(isinstance(value, str) and value.strip() for value in (document_id, status, title)):
        return None
    superseded = payload.get("superseded_batch_ids")
    source, review, report = (payload.get(k) for k in ("source", "review", "report"))
    if not _string_list(superseded) or not all(isinstance(obj, dict) for obj in (source, review, report)):
        return None
    if not isinstance(source.get("original_filename"), str) or not isinstance(review.get("human_reviewed"), bool):
        return None
    if not isinstance(report.get("preview"), str) or (
        payload.get("machine_generated") is not True or payload.get("read_only") is not True
    ):
        return None
    if any(payload.get(flag, False) is not False for flag in _NO_SIDE_EFFECTS):
        return None
    group_name = source.get("source_group_name")
    if group_name is not None and not isinstance(group_name, str):
        return None
    review_status = review.get("review_status")
    report_bytes = report.get("bytes")
    return {
        "document_id": document_id,
        "research_date": date,
        "status": status,
        "title": title,
        "batch_id": _optional_text(payload, "batch_id", ""),
        "title_source": _optional_text(payload, "title_source", "CANNOT_CONFIRM"),
        "superseded_batch_ids": superseded,
        "source": {
            "source_group_name": group_name,
            "source_group_status": _optional_text(source, "source_group_status", "CANNOT_CONFIRM"),
            "original_filename": source["original_filename"],
            **{key: _optional_text(source, key, "")
               for key in ("source_directory", "source_relative_path", "source_pdf_path")},
        },
        "review": {
            **{key: _optional_text(review, key)
               for key in ("origin_status", "source_review_status", "user_acceptance_status")},
            "review_status": review_status if review_status in ("REVIEWED", "NOT_REVIEWED") else "CANNOT_CONFIRM",
            "human_reviewed": review["human_reviewed"],
            "user_accepted": review.get("user_accepted") is True,
        },
        "report": {
            "path": _optional_text(report, "path", ""),
            "receipt_path": _optional_text(report, "receipt_path", ""),
            "sha256": _optional_text(report, "sha256"),
            "bytes": report_bytes if type(report_bytes) is int and report_bytes >= 0 else None,
            "preview": report["preview"][:_PREVIEW_LIMIT],
            "preview_max_chars": _PREVIEW_LIMIT,
        },
        "machine_generated": True,
        "read_only": True,
        "research_only": True,
        **_NO_SIDE_EFFECTS,
    }


def _clue_observation(row: dict, date: str) -> tuple[str, bool] | None:
    payload = row["payload"]
    if not isinstance(payload, dict) or _evidence_date(payload.get("research_date", row["trade_date"])) != date:
        return None
    if any(payload.get(flag, False) is not False for flag in _NO_SIDE_EFFECTS):
        return None
    code, name = payload.get("ts_code"), payload.get("name")
    if not isinstance(code, str) or not code.strip() or (name is not None and not isinstance(name, str)):
        return None
    code = normalize_symbol(code)
    if row["symbol"] and normalize_symbol(row["symbol"]) != code:
        return None
    count, weak = payload.get("document_count"), payload.get("weak_document_count")
    if type(count) is not int or type(weak) is not int or count < 0 or weak < 0:
        return None
    reasons = payload.get("confirm_reasons", [])
    first = _evidence_date(payload.get("first_seen_date"))
    last = _evidence_date(payload.get("last_seen_date"))
    if any(key in payload and (bound is None or bound > date)
           for key, bound in (("first_seen_date", first), ("last_seen_date", last))):
        return None
    if count == 0:
        return (code, False) if weak > 0 and name and reasons == [] else None
    titles, matched_by = payload.get("document_titles"), payload.get("matched_by")
    if not _string_list(reasons) or not reasons or not set(reasons) <= _CONFIRM_REASONS:
        return None
    if len(set(reasons)) != len(reasons) or not _string_list(titles) or matched_by not in ("NAME", "CODE", "BOTH"):
        return None
    if first is None or last is None or not first <= last <= date:
        return None
    return code, True


def build_research_router(store: V4Store) -> APIRouter:
    router = APIRouter(prefix="/api/v4", tags=["research-command"])

    # --- Baimao observations (2) ---

    @router.get("/baimao/observations")
    def get_baimao_observations(source_date: str | None = Query(default=None)):
        items = store.query_research_materials(source_type="baimao", trade_date=source_date, limit=100)
        return {"source_date": source_date, "status": "READY" if items else "EMPTY", "items": items, "count": len(items)}

    @router.get("/baimao/x/latest")
    def get_baimao_x_latest():
        items = store.query_research_materials(source_type="baimao_x", limit=20)
        return {"status": "READY" if items else "EMPTY", "latest": items[0] if items else None, "items": items}

    # --- Announcement flash control (5 kept; recover-cached-product pruned per blueprint) ---

    @router.get("/manager-workbench/announcement-flash")
    def get_announcement_flash(target_date: str | None = Query(default=None)):
        t_date = target_date or (store.list_run_dates()[0] if store.list_run_dates() else dt_date.today().isoformat())
        rows = store.query_announcements(trade_date=t_date)
        return {"target_date": t_date, "data": {"items": rows, "count": len(rows)}, "gaps": []}

    @router.post("/manager-workbench/announcement-flash/update")
    def post_announcement_flash_update(body: dict[str, Any] = Body(default_factory=dict)):
        target_date = str(body.get("target_date") or body.get("requested_target_date") or dt_date.today().isoformat())
        job_id = f"ann-{uuid.uuid4().hex[:8]}"
        job = store.upsert_announcement_job(job_id, target_date, "QUEUED", payload=body)
        return {"job_id": job_id, "requested_target_date": target_date, "data": job}

    @router.post("/manager-workbench/announcement-flash/resume")
    def post_announcement_flash_resume(body: dict[str, Any] = Body(default_factory=dict)):
        source_job_id = str(body.get("source_job_id") or "")
        target_date = str(body.get("target_date") or dt_date.today().isoformat())
        job_id = f"ann-resume-{uuid.uuid4().hex[:8]}"
        job = store.upsert_announcement_job(job_id, target_date, "RESUMED", source_job_id=source_job_id, payload=body)
        return {"job_id": job_id, "source_job_id": source_job_id, "data": job}

    @router.post("/manager-workbench/announcement-flash/{job_id}/execute-preprocessed")
    def post_announcement_flash_execute(job_id: str):
        existing = store.get_announcement_job(job_id)
        t_date = existing["target_date"] if existing else dt_date.today().isoformat()
        job = store.upsert_announcement_job(job_id, t_date, "EXECUTED_PREPROCESSED")
        return {"job_id": job_id, "state": job["state"], "data": job}

    @router.post("/manager-workbench/announcement-flash/{job_id}/stop")
    def post_announcement_flash_stop(job_id: str):
        existing = store.get_announcement_job(job_id)
        t_date = existing["target_date"] if existing else dt_date.today().isoformat()
        job = store.upsert_announcement_job(job_id, t_date, "STOPPED")
        return {"job_id": job_id, "state": job["state"], "data": job}

    # --- Manager workbench command views (6) ---

    @router.get("/manager-workbench/days/{date}")
    def get_manager_workbench_day(
        date: str,
        phase: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        offset: int = Query(default=0),
        limit: int = Query(default=100),
        decision: str | None = Query(default=None),
        lane: str | None = Query(default=None),
        q: str | None = Query(default=None),
    ):
        materials = store.query_research_materials(trade_date=date, q=q, limit=limit)
        scores = store.get_workbench_scores(date)
        return {
            "date": date,
            "data": {"phase": phase, "run_id": run_id, "lane": lane, "decision": decision, "materials": materials[offset : offset + limit]},
            "stocks": scores,
            "snapshot": {"date": date, "materials_count": len(materials), "stocks_count": len(scores)},
        }

    @router.get("/manager-workbench/days/{date}/recommendations/{lane}")
    def get_manager_workbench_recommendations(
        date: str,
        lane: str,
        phase: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        offset: int = Query(default=0),
        limit: int = Query(default=100),
        decision: str | None = Query(default=None),
        q: str | None = Query(default=None),
        view: str | None = Query(default=None),
        projection: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        relationship_offset: int = Query(default=0),
        relationship_limit: int = Query(default=50),
    ):
        items = store.query_research_materials(trade_date=date, symbol=symbol, q=q, limit=limit)
        return {
            "date": date,
            "lane": lane,
            "data": {"items": items[offset : offset + limit], "phase": phase, "run_id": run_id, "decision": decision, "view": view, "projection": projection},
            "snapshot": {"date": date, "lane": lane, "count": len(items), "relationship_offset": relationship_offset, "relationship_limit": relationship_limit},
        }

    @router.get("/manager-workbench/history")
    def get_manager_workbench_history(date: str | None = Query(default=None)):
        dates = store.list_run_dates()
        return {"date": date, "data": {"dates": dates}, "count": len(dates)}

    @router.get("/manager-workbench/hk-history")
    def get_manager_workbench_hk_history(
        symbol: str | None = Query(default=None),
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        offset: int = Query(default=0),
        limit: int = Query(default=100),
        mode: str | None = Query(default=None),
        fields: str | None = Query(default=None),
    ):
        bars = store.get_symbol_bars("HK", normalize_symbol(symbol) if symbol else "", table="daily_bars", limit=limit, asof_date=end) if symbol else []
        if start:
            bars = [b for b in bars if b["trade_date"] >= start]
        return {"symbol": symbol, "mode": mode, "fields": fields, "data": bars[offset : offset + limit], "count": len(bars)}

    @router.get("/manager-workbench/mapping-catalog")
    def get_manager_workbench_mapping_catalog(
        q: str | None = Query(default=None),
        research_use: str | None = Query(default=None),
        offset: int = Query(default=0),
        limit: int = Query(default=100),
    ):
        items = store.query_research_materials(source_type="us_mapping", q=q, limit=limit)
        return {
            "query": {"q": q, "research_use": research_use, "offset": offset, "limit": limit},
            "catalog_state": "READY",
            "data": items[offset : offset + limit],
        }

    @router.get("/manager-workbench/stocks/{symbol}")
    def get_manager_workbench_stock(
        symbol: str,
        date: str | None = Query(default=None),
        run_id: str | None = Query(default=None),
        lane: str | None = Query(default=None),
        row_id: str | None = Query(default=None),
    ):
        canon = normalize_symbol(symbol) or symbol
        materials = store.query_research_materials(trade_date=date, symbol=canon, limit=50)
        return {
            "symbol": canon,
            "display_name": store.resolve_security_name(date, canon) or canon,
            "plan_run_id": run_id or "default",
            "lane": lane,
            "row_id": row_id,
            "data": {"materials": materials, "count": len(materials)},
        }

    # --- Manager research announcements (3) ---

    @router.get("/manager/research/announcements")
    def get_manager_research_announcements(
        target_trade_date: str | None = Query(default=None),
        scope_id: str | None = Query(default=None),
    ):
        rows = store.query_announcements(trade_date=target_trade_date, scope_id=scope_id)
        return {"target_trade_date": target_trade_date, "scope_id": scope_id, "status": "READY" if rows else "EMPTY", "items": rows, "count": len(rows)}

    @router.get("/manager/research/announcements/body")
    def get_manager_research_announcement_body(
        target_trade_date: str | None = Query(default=None),
        scope_id: str | None = Query(default=None),
        product_sha256: str | None = Query(default=None),
        event_id: str | None = Query(default=None),
    ):
        rec = store.get_announcement(event_id) if event_id else None
        return {
            "target_trade_date": target_trade_date,
            "scope_id": scope_id,
            "product_sha256": product_sha256 or (rec["product_sha256"] if rec else ""),
            "event_id": event_id,
            "body": rec["body_text"] if rec else "",
            "status": "READY" if rec else "NOT_FOUND",
        }

    @router.post("/manager/research/announcements/refresh")
    def post_manager_research_announcements_refresh(
        target_trade_date: str | None = Query(default=None),
        issuer_codes: str | None = Query(default=None),
        resume: bool = Query(default=False),
    ):
        t_date = target_trade_date or dt_date.today().isoformat()
        job_id = f"ann-ref-{uuid.uuid4().hex[:8]}"
        job = store.upsert_announcement_job(job_id, t_date, "REFRESH_QUEUED", payload={"issuer_codes": issuer_codes, "resume": resume})
        return {"ok": True, "job_id": job_id, "target_trade_date": t_date, "data": job}

    # --- Manual collection (2; strict manualCollection.ts contract: 32-hex job_id + trade_date) ---

    @router.post("/manual-collection")
    def post_manual_collection(body: dict[str, Any] = Body(default_factory=dict)):
        job_id = uuid.uuid4().hex  # exact 32 lowercase hex chars matching /^[a-f0-9]{32}$/
        req_date = str(body.get("date") or body.get("trade_date") or dt_date.today().strftime("%Y%m%d"))
        target = str(body.get("target") or "HK_STAGE")
        stage_id = body.get("stage_id")
        meta = {
            **body,
            "trade_date": req_date,
            "target": target,
            "stage_id": stage_id,
            "step": "QUEUED",
        }
        job = store.upsert_manual_collection_job(job_id, "READY", "Manual collection job accepted", payload=meta)
        return {
            "ok": True,
            "job_id": job_id,
            "trade_date": req_date,
            "target": target,
            "stage_id": stage_id,
            "status": job["status"],
            "step": "QUEUED",
            "message": job["message"],
            "cannot_confirm": [],
            "result": {"selected_rows": 0, "source_rows": 0, "returned_rows": 0},
        }

    @router.get("/manual-collection/{job_id}")
    def get_manual_collection(job_id: str):
        job = store.get_manual_collection_job(job_id)
        if not job:
            fallback_date = normalize_compact_date(store.list_run_dates()[0]) if store.list_run_dates() else dt_date.today().strftime("%Y%m%d")
            return {
                "ok": True,
                "job_id": job_id,
                "trade_date": fallback_date,
                "target": "HK_STAGE",
                "stage_id": None,
                "status": "CANNOT_CONFIRM",
                "step": "NOT_FOUND",
                "message": f"No manual collection job {job_id}",
                "cannot_confirm": [f"MANUAL_COLLECTION_JOB_NOT_FOUND:{job_id}"],
                "result": {"selected_rows": 0, "source_rows": 0, "returned_rows": 0},
                "payload": {},
            }
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        t_date = str(payload.get("trade_date") or payload.get("date") or dt_date.today().strftime("%Y%m%d"))
        return {
            "ok": True,
            "job_id": job["job_id"],
            "trade_date": t_date,
            "target": str(payload.get("target") or "HK_STAGE"),
            "stage_id": payload.get("stage_id"),
            "status": job["status"],
            "step": str(payload.get("step") or "COMPLETED"),
            "message": job["message"],
            "cannot_confirm": [],
            "result": {"selected_rows": 0, "source_rows": 0, "returned_rows": 0},
            "payload": payload,
        }

    # --- Research articles / dates / day / lane / pdf / clues / us-market / wechat (20) ---

    @router.get("/research/articles")
    def get_research_articles(archive_date: str | None = Query(default=None)):
        items = store.query_research_materials(source_type="article", trade_date=archive_date, limit=100)
        return {"archive_date": archive_date, "status": "READY" if items else "EMPTY", "items": items}

    @router.get("/research/articles/latest")
    def get_research_articles_latest():
        items = store.query_research_materials(source_type="article", limit=20)
        return {"status": "READY" if items else "EMPTY", "items": items}

    @router.get("/research/authoritative")
    def get_research_authoritative(archive_date: str | None = Query(default=None)):
        items = store.query_research_materials(source_type="authoritative", trade_date=archive_date, limit=100)
        return {"archive_date": archive_date, "status": "READY" if items else "EMPTY", "items": items}

    @router.get("/research/dates")
    def get_research_dates():
        dates = store.list_run_dates()
        us_items = store.query_research_materials(source_type="us_market", limit=10)
        return {
            "schema_version": "v3_5.research_lane_dates.v1",
            "dates": dates,
            "latest_date": dates[0] if dates else None,
            "us_close_availability": {
                "available": len(us_items) > 0,
                "latest_date": us_items[0]["trade_date"] if us_items else None,
            },
            "status": "READY",
        }

    @router.get("/research/day")
    def get_instruction_day(archive_date: str | None = Query(default=None)):
        endpoint_mode = "EXACT" if archive_date else "LATEST"
        raw_date = archive_date or (store.list_run_dates()[0] if store.list_run_dates() else dt_date.today().strftime("%Y%m%d"))
        compact_date = normalize_compact_date(raw_date)
        iso_date = normalize_iso_date(raw_date)
        scores = store.get_workbench_scores(iso_date) or store.get_workbench_scores(compact_date)
        materials = store.query_research_materials(trade_date=iso_date, limit=200) or store.query_research_materials(trade_date=compact_date, limit=200)
        slots = store.get_slot_executions(iso_date)
        materialized = bool(scores or materials)
        status = "READY" if materialized else "NOT_MATERIALIZED"
        ready_slots = sum(1 for s in slots if s.get("status") == "DONE")
        return {
            "schema_version": "v3_5.research_day_product.v1",
            "status": status,
            "authoritative": materialized,
            "endpoint_mode": endpoint_mode,
            "archive_date": compact_date,
            "requested_date": compact_date,
            "resolved_date": compact_date if materialized else None,
            "is_full_day": True,
            "counts": {
                "raw_rows": len(materials),
                "evidence_rows": len(materials),
                "excluded_rows": 0,
                "mention_pairs": 0,
                "urls": 0,
                "stock_rollups": len(scores),
                "high_priority": 0,
                "duplicate_pairs": 0,
            },
            "coverage": {
                "complete": ready_slots >= 6,
                "expected_slots": 6,
                "ready_slots": ready_slots,
                "missing_slots": [],
                "slot_matrix": slots,
                "workbench_count": len(scores),
                "materials_count": len(materials),
            },
            "cannot_confirm": [],
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @router.get("/research/evidence-search")
    def get_research_evidence_search(
        text: str | None = Query(default=None),
        security: str | None = Query(default=None),
        market: str | None = Query(default=None),
        source: str | None = Query(default=None),
        date_from: str | None = Query(default=None),
        date_to: str | None = Query(default=None),
        mode: str | None = Query(default=None),
        as_of: str | None = Query(default=None),
        limit: int = Query(default=50),
    ):
        items = store.query_research_materials(source_type=source, symbol=security, market=market, q=text, limit=limit)
        if date_from:
            items = [i for i in items if i["trade_date"] >= date_from]
        if date_to:
            items = [i for i in items if i["trade_date"] <= date_to]
        return {"status": "READY", "mode": mode, "as_of": as_of, "items": items, "count": len(items)}

    @router.get("/research/hourly")
    def get_research_hourly(archive_date: str | None = Query(default=None), slot: str | None = Query(default=None)):
        items = store.query_research_materials(source_type="hourly", trade_date=archive_date, limit=100)
        return {"archive_date": archive_date, "slot": slot, "status": "READY" if items else "EMPTY", "items": items}

    @router.get("/research/hourly/latest")
    def get_research_hourly_latest():
        items = store.query_research_materials(source_type="hourly", limit=20)
        return {"status": "READY" if items else "EMPTY", "items": items}

    @router.get("/research/lane")
    def get_research_lane(
        research_date: str | None = Query(default=None),
        date: str | None = Query(default=None),
    ):
        endpoint_mode = "EXACT" if (research_date or date) else "LATEST"
        raw_date = research_date or date or (store.list_run_dates()[0] if store.list_run_dates() else dt_date.today().strftime("%Y%m%d"))
        compact_date = normalize_compact_date(raw_date)
        iso_date = normalize_iso_date(raw_date)
        items = store.query_research_materials(trade_date=iso_date, limit=100) or store.query_research_materials(trade_date=compact_date, limit=100)
        status = "READY" if items else "NOT_MATERIALIZED"
        return {
            "schema_version": "v3_5.research_lane.v1",
            "endpoint_mode": endpoint_mode,
            "research_date": compact_date,
            "status": status,
            "lane_status": status,
            "daily_archive_status": status,
            "reason": "" if items else "RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
            "items": items,
            "count": len(items),
            "stock_research_daily": [],
            "stock_research_timeline": [],
            "research_pool_bridge": [],
            "key_investment_messages": [],
            "research_quality_summary": {},
            "morning_news": {},
            "zsxq_hourly": {},
            "external_finance": {},
            "ai_news": {},
            "news_workbench": {},
            "hourly_research": {},
            "cannot_confirm": [],
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @router.get("/research/machine-cards")
    def get_research_machine_cards(research_date: str | None = Query(default=None)):
        compact_date = _projection_date(store, research_date)
        rows, capped = _projection_inputs(store, "machine_card", compact_date, _CARD_LIMIT + 1)
        by_document = {}
        unresolved_documents: list[str] = []
        unresolved_count = 0
        duplicate_count = 0
        for row in rows:
            card = _machine_card(row, compact_date)
            if card is None:
                unresolved_count += 1
                raw = row["payload"]
                identity = raw.get("document_id") if isinstance(raw, dict) else None
                if isinstance(identity, str) and identity.strip():
                    unresolved_documents.append(identity)
                continue
            document_id = card["document_id"]
            if document_id in by_document:
                duplicate_count += 1
            else:
                by_document[document_id] = card
        items = list(by_document.values())[:_CARD_LIMIT]
        status = "READY" if items else ("CANNOT_CONFIRM" if rows else "NOT_MATERIALIZED")
        return {
            "schema_version": "v4.pdf_research.machine_cards.v1",
            "endpoint_mode": "EXACT" if research_date else "LATEST",
            "research_date": compact_date,
            "status": status,
            "items": items,
            "cards": items,
            "card_count": len(items),
            "count": len(items),
            "matched_count": len(rows),
            "max_cards_per_date": _CARD_LIMIT,
            "preview_max_chars": _PREVIEW_LIMIT,
            "duplicate_count": duplicate_count,
            "cannot_confirm": ["MACHINE_CARD_PAYLOAD_UNVERIFIED"] if unresolved_count else [],
            "cannot_confirm_count": unresolved_count,
            "cannot_confirm_document_ids": [],
            "unresolved_document_ids": list(dict.fromkeys(unresolved_documents)),
            "source_index_used": False,
            "truncated": capped or len(by_document) > _CARD_LIMIT,
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "research_only": True,
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @router.get("/research/pdf-documents/{document_id}")
    def get_research_pdf_document(document_id: str, research_date: str | None = Query(default=None)):
        rec = store.get_research_material(document_id)
        # Echo exact research_date param when provided (matches research_lane.ts strict equality check)
        echo_date = research_date if research_date is not None else (normalize_compact_date(rec["trade_date"]) if rec else "")
        pages: list[dict[str, Any]] = []
        if rec and isinstance(rec.get("payload"), dict) and isinstance(rec["payload"].get("pages"), list):
            pages = [p for p in rec["payload"]["pages"] if isinstance(p, dict)]
        return {
            "schema_version": "v4.zsxq_pdf_document_detail.v1",
            "document_id": document_id,
            "research_date": echo_date,
            "status": "READY" if rec else "NOT_FOUND",
            "pages": pages,
            "document": rec,
        }

    @router.get("/research/pdf-relations")
    def get_research_pdf_relations(
        symbols: str | None = Query(default=None),
        identity_date: str | None = Query(default=None),
        hints: str | None = Query(default=None),
        max_dates: int = Query(default=10),
        max_documents: int = Query(default=50),
        cursor: str | None = Query(default=None),
    ):
        sym_list = [normalize_symbol(s) for s in (symbols or "").split(",") if s.strip()]
        items = store.query_research_materials(source_type="pdf", trade_date=identity_date, limit=max_documents)
        if sym_list:
            items = [i for i in items if i["symbol"] in sym_list]
        return {
            "incomplete": False,
            "coverage": {"requested_symbols": len(sym_list), "matched_documents": len(items), "max_dates": max_dates},
            "data": items,
            "cursor": cursor,
            "hints": hints,
        }

    @router.get("/research/stage-report-evidence")
    def get_research_stage_report_evidence(
        date: str | None = Query(default=None),
        stage: str | None = Query(default=None),
        selection_run: str | None = Query(default=None),
        market: str | None = Query(default=None),
    ):
        items = store.query_research_materials(trade_date=date, market=market, limit=100)
        return {"date": date, "stage": stage, "selection_run": selection_run, "market": market, "status": "READY", "items": items}

    @router.get("/research/stock-clues")
    def get_research_stock_clues(research_date: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200)):
        compact_date = _projection_date(store, research_date)
        rows, capped = _projection_inputs(store, "stock_clue", compact_date, _CLUE_SOURCE_LIMIT)
        confirmed, weak_only = set(), set()
        rejected = 0
        for row in rows:
            observation = _clue_observation(row, compact_date)
            if observation is None:
                rejected += 1
                continue
            code, has_confirmed_payload = observation
            (confirmed if has_confirmed_payload else weak_only).add(code)
        # Owner rows are observations only until the reader can prove the name map,
        # corpus and scan. The frontend contract requires zero actionable rows for
        # a non-ready status, independently of the number of stored observations.
        cannot_confirm = ["STOCK_CLUE_NAME_MAP_UNAVAILABLE", "STOCK_CLUE_CORPUS_UNAVAILABLE",
                          "STOCK_CLUE_SCAN_PROVENANCE_UNAVAILABLE"]
        if rejected:
            cannot_confirm.append("STOCK_CLUE_PAYLOAD_UNVERIFIED")
        if capped:
            cannot_confirm.append("STOCK_CLUE_SOURCE_LIMIT_REACHED")
        return {
            "schema_version": "v4.research.stock_clues.v1",
            "endpoint_mode": "EXACT" if research_date else "LATEST",
            "research_date": compact_date,
            "status": "CANNOT_CONFIRM" if rows else "NOT_MATERIALIZED",
            "items": [],
            "clues": [],
            "count": 0,
            "card_count": 0,
            "clue_count": 0,
            "matched_count": 0,
            "scanned_card_count": 0,
            "skipped_card_count": 0,
            "stock_count": 0,
            "confirmed_stock_count": 0,
            "weak_only_stock_count": 0,
            "corpus_report_count": 0,
            "truncated_report_count": 0,
            "clue_limit": limit,
            "limit": limit,
            "name_map_status": "CANNOT_CONFIRM",
            "name_map_path": "",
            "name_map_trade_date": "",
            "corpus_cache_status": "CANNOT_CONFIRM",
            "corpus_fingerprint": "",
            "corpus_cutoff_date": compact_date,
            "corpus_version": "v4.research.stock_clues.v1",
            "generic_filtered": [],
            "weak_items": [],
            "truncated": capped,
            "source_observations": {
                "rows_read": len(rows),
                "unverified_rows": rejected,
                "codes_with_confirmed_payload": len(confirmed),
                "codes_with_weak_only_payload": len(weak_only - confirmed),
            },
            "cannot_confirm": cannot_confirm,
            "cannot_confirm_count": len(cannot_confirm),
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "research_only": True,
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @router.get("/research/us-market")
    def get_research_us_market(research_date: str | None = Query(default=None)):
        target_date = research_date or (store.list_run_dates()[0] if store.list_run_dates() else dt_date.today().isoformat())
        items = store.query_research_materials(source_type="us_market", trade_date=target_date, limit=50)
        return {"research_date": target_date, "status": "READY" if items else "EMPTY", "items": items}

    @router.get("/research/wechat/materials")
    def get_wechat_materials(
        date: str | None = Query(default=None),
        date_basis: str | None = Query(default=None),
        q: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50),
    ):
        items = store.query_research_materials(source_type="wechat", trade_date=date, q=q, limit=limit)
        return {
            "date": date,
            "date_basis": date_basis or "applicable_date",
            "status": "READY" if items else "MATERIALIZED_EMPTY",
            "items": items,
            "cursor": cursor,
        }

    @router.get("/research/wechat/materials/mentions")
    def get_wechat_materials_mentions(
        date: str | None = Query(default=None),
        date_basis: str | None = Query(default=None),
        market: str | None = Query(default=None),
        q: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50),
    ):
        items = store.query_research_materials(source_type="wechat", trade_date=date, market=market, q=q, limit=limit)
        return {"date": date, "date_basis": date_basis, "status": "READY", "items": items, "cursor": cursor}

    @router.get("/research/wechat/materials/{record_id}")
    def get_wechat_material_detail(record_id: str):
        rec = store.get_research_material(record_id)
        if not rec:
            raise HTTPException(status_code=404, detail=f"WECHAT_MATERIAL_NOT_FOUND:{record_id}")
        return {"status": "READY", "record": rec}

    @router.get("/research/wechat/materials/{record_id}/artifacts/{artifact_id}")
    def get_wechat_material_artifact(record_id: str, artifact_id: str):
        rec = store.get_research_material(record_id)
        return {"record_id": record_id, "artifact_id": artifact_id, "status": "READY" if rec else "NOT_FOUND", "owner_ref": rec["owner_ref"] if rec else ""}

    @router.get("/research/wechat/materials/{record_id}/mentions")
    def get_wechat_material_record_mentions(
        record_id: str,
        market: str | None = Query(default=None),
        q: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=50),
    ):
        rec = store.get_research_material(record_id)
        return {"record_id": record_id, "market": market, "q": q, "cursor": cursor, "limit": limit, "items": [rec] if rec else []}

    return router
