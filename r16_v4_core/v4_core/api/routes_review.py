"""Pure V4 Review & Task Status router (Domain 4: 复盘状态域, 11 routes + /healthz in app.py = 12)."""
from __future__ import annotations

from datetime import date as dt_date
import uuid
from typing import Any

from fastapi import APIRouter, Body, Query

from v4_core.api.routes_workbench import SIX_SLOT_CONTRACT
from v4_core.storage.db import V4Store, normalize_iso_date


def build_review_router(store: V4Store) -> APIRouter:
    router = APIRouter(tags=["review-status"])

    @router.get("/readyz")
    def readyz():
        return {"status": "ready", "mode": "v4_core_single_root", "version": "4.0.0"}

    @router.get("/api/v1/runs/date-list")
    def get_v1_runs_date_list():
        dates = store.list_run_dates()
        return {"dates": dates, "latest_date": dates[0] if dates else None, "count": len(dates), "status": "READY"}

    @router.get("/api/v4/runtime-graph/frontend-build")
    def get_frontend_build_identity():
        return {
            "status": "READY",
            "mode": "v4_core_single_root",
            "version": "4.0.0-r10",
            "ui_contract_frozen": True,
            "api_namespace": "/api/v4",
        }

    @router.get("/api/v4/operations/sop")
    def get_operations_sop():
        return {
            "status": "READY",
            "version": "v4_core_r10",
            "slots": SIX_SLOT_CONTRACT,
            "single_directory_mode": True,
        }

    @router.get("/api/v4/review")
    def get_review(date: str | None = Query(default=None)):
        target_date = date or (store.list_run_dates()[0] if store.list_run_dates() else dt_date.today().isoformat())
        rec = store.get_review_record(target_date)
        slots = store.get_slot_executions(target_date)
        return {
            "trade_date": target_date,
            "status": rec["status"] if rec else "NOT_MATERIALIZED",
            "plan_run_id": rec["plan_run_id"] if rec else None,
            "data": rec["payload"] if rec else {},
            "slot_executions": slots,
            "RESEARCH_ONLY": True,
        }

    @router.post("/api/v4/review/generate")
    def post_review_generate(body: dict[str, Any] = Body(default_factory=dict)):
        target_date = str(body.get("date") or body.get("trade_date") or dt_date.today().isoformat())
        iso_date = normalize_iso_date(target_date)
        rec = store.get_review_record(iso_date)
        slot = next((item for item in store.get_slot_executions(iso_date)
                     if item["slot_id"] == "slot_6_review_and_maint" and rec and item["run_id"] == rec["plan_run_id"]), None)
        return {
            "code": "OK" if rec and rec["status"] == "GENERATED" else "CANNOT_CONFIRM",
            "detail": f"Review readback for {target_date}",
            "trade_date": target_date,
            "plan_run_id": rec["plan_run_id"] if rec else None,
            "execution_ref": slot["execution_ref"] if slot else None,
            "data": rec["payload"] if rec else {},
            "write_performed": False,
        }

    @router.get("/api/v4/manager-workbench/reviews/{date}")
    def get_manager_workbench_review(date: str, plan_run_id: str | None = Query(default=None)):
        rec = store.get_review_record(date, plan_run_id=plan_run_id)
        return {
            "target_date": date,
            "plan_run_id": rec["plan_run_id"] if rec else (plan_run_id or "default"),
            "status": rec["status"] if rec else "NOT_MATERIALIZED",
            "data": rec["payload"] if rec else {},
        }

    @router.post("/api/v4/manager-workbench/runs")
    def post_manager_workbench_runs(body: dict[str, Any] = Body(default_factory=dict)):
        target_date = str(body.get("date") or body.get("trade_date") or dt_date.today().isoformat())
        run_id = f"mrun-{uuid.uuid4().hex[:8]}"
        rec = store.upsert_manager_run(run_id, target_date, "QUEUED", payload=body)
        return {"ok": True, "id": run_id, "run_id": run_id, "data": rec}

    @router.get("/api/v4/manager-workbench/runs/{id}")
    def get_manager_workbench_run(id: str):
        rec = store.get_manager_run(id)
        return {"id": id, "status": rec["status"] if rec else "NOT_FOUND", "data": rec}

    @router.post("/api/v4/manager-workbench/runs/{id}/retry")
    def post_manager_workbench_run_retry(id: str):
        existing = store.get_manager_run(id)
        t_date = existing["trade_date"] if existing else dt_date.today().isoformat()
        rec = store.upsert_manager_run(id, t_date, "RETRIED", payload=existing["payload"] if existing else {})
        return {"ok": True, "id": id, "status": rec["status"], "data": rec}

    @router.get("/api/v4/tasks/status")
    def get_tasks_status(date: str | None = Query(default=None)):
        target_date = date or (store.list_run_dates()[0] if store.list_run_dates() else dt_date.today().isoformat())
        iso_date = normalize_iso_date(target_date)
        runs = store.list_task_runs(iso_date)
        slots = {s["slot_id"]: s for s in store.get_slot_executions(target_date)}
        a_bars = store.get_date_bars("A", iso_date, table="daily_bars")
        hk_bars = store.get_date_bars("HK", iso_date, table="daily_bars")

        timeline_nodes = []
        logical_rows = []
        for slot in SIX_SLOT_CONTRACT:
            rec = slots.get(slot["slot_id"])
            exec_ref = rec["execution_ref"] if rec else None
            node = {
                "slot_id": slot["slot_id"],
                "node_id": slot["slot_id"],
                "name": slot["slot_name"],
                "schedule_time": slot["schedule_time"],
                "status": rec["status"] if rec else "SCHEDULED",
                "execution_ref": exec_ref,
                "run_id": rec["run_id"] if rec else None,
                "finished_at": rec["finished_at"] if rec else None,
                "error": rec["detail"].get("error") if (rec and isinstance(rec.get("detail"), dict)) else None,
            }
            timeline_nodes.append(node)
            logical_rows.append(
                {
                    "workload_id": slot["slot_id"],
                    "enabled": True,
                    "status": node["status"],
                    "last_run": node["finished_at"],
                    "next_due": slot["schedule_time"],
                    "result_code": node["status"],
                    "receipt_path": exec_ref,
                }
            )
        return {
            "business_date": target_date,
            "logical_workload_count": len(logical_rows),
            "active_owner_count": 1,
            "alias_count": 0,
            "retired_owner_count": 0,
            "task_registration_count": len(timeline_nodes),
            "timeline_nodes": timeline_nodes,
            "groups": {
                "logical": logical_rows,
                "active_owners": [{"owner_id": "v4_core_single_root", "status": "ACTIVE"}],
                "aliases": [],
                "retired": [],
                "registrations": [],
            },
            "slots": timeline_nodes,
            "task_runs": runs,
            "market_evidence": {
                "A": {"status": "READY" if a_bars else "EMPTY", "bar_count": len(a_bars)},
                "HK": {"status": "READY" if hk_bars else "CANNOT_CONFIRM", "bar_count": len(hk_bars)},
            },
            "scheduler_observation": {
                "status": "READY",
                "mode": "v4_core_single_root_6_slots",
                "receipt_count": len(slots),
                "process_status": "RUNNING",
                "logical_row_evidence": "SQLITE_SLOT_EXECUTIONS",
                "message": f"{len(slots)}/6 slots executed for {target_date}",
                "slot_count": len(timeline_nodes),
                "executed_slots": len(slots),
            },
            "cannot_confirm": [],
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    return router
