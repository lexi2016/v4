"""Thin FastAPI routes for the V4 manager research job.

The router only validates date/origin and delegates to the injected V4
service.  It does not accept symbols, source URLs, commands or document text
from the browser.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, HTTPException, Query, Request


_DATE_RE = re.compile(r"^\d{8}$")


def _date(value: str | None) -> str:
    if value is None:
        raise HTTPException(status_code=422, detail="date is required")
    if _DATE_RE.fullmatch(value) is None:
        raise HTTPException(status_code=422, detail="target_trade_date must use YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="target_trade_date must be a real calendar date") from exc


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    expected = str(request.base_url).rstrip("/")
    if origin.rstrip("/") != expected:
        raise HTTPException(status_code=403, detail="cross-origin manager research request rejected")


async def _reject_client_body(request: Request) -> None:
    body = await request.body()
    if body.strip():
        raise HTTPException(status_code=422, detail="manager research symbols and source URLs are server-owned")


def _job_envelope(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v4.manager_research.product.v1",
        "kind": "MANAGER_RESEARCH",
        "target_trade_date": job.get("target_trade_date"),
        "stage_id": job.get("stage_id"),
        "market": job.get("market"),
        "cutoff_at": job.get("cutoff_at"),
        "input_identity": job.get("input_identity"),
        "input_source_sha256": job.get("input_source_sha256"),
        "input_row_count": job.get("input_row_count"),
        "status": job.get("status"),
        "product": None,
        "job": job,
        "can_ensure": job.get("status") in {"FAILED", "CANNOT_CONFIRM", "PARTIAL_WITH_ROWS"},
        "can_retry": bool(job.get("can_retry")),
        "cannot_confirm": [job["error"]] if job.get("error") else [],
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "safety": {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }


def create_manager_research_router(service: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v4/manager/research", tags=["manager-research"])

    @router.get("")
    def read_research(
        date: str = Query(
            ...,
            description="Exact manager-research material date in YYYYMMDD format.",
        ),
    ) -> dict[str, Any]:
        return service.get(_date(date))

    @router.get("/status")
    def read_research_status(
        date: str = Query(
            ...,
            description="Exact manager-research material date in YYYYMMDD format.",
        ),
    ) -> dict[str, Any]:
        return service.get(_date(date))

    @router.post("/ensure")
    async def ensure_research(request: Request, date: str | None = None) -> dict[str, Any]:
        _same_origin(request)
        await _reject_client_body(request)
        return await run_in_threadpool(service.ensure, _date(date))

    @router.post("/retry")
    async def retry_research(request: Request, date: str | None = None) -> dict[str, Any]:
        _same_origin(request)
        await _reject_client_body(request)
        return await run_in_threadpool(service.retry, _date(date))

    @router.post("/events")
    async def refresh_research_events(request: Request, date: str | None = None) -> dict[str, Any]:
        """Refresh bounded catalyst evidence while retaining financial facts."""

        _same_origin(request)
        await _reject_client_body(request)
        ensure_events = getattr(service, "ensure_events", None)
        if not callable(ensure_events):
            raise HTTPException(status_code=503, detail="manager research catalyst refresh is unavailable")
        return await run_in_threadpool(ensure_events, _date(date), force=True)

    @router.get("/jobs/{job_id}")
    def read_job(job_id: str, date: str | None = None) -> dict[str, Any]:
        target = _date(date) if date is not None else None
        job = service.job(job_id, target)
        if job is None:
            raise HTTPException(status_code=404, detail="manager research job not found")
        envelope = _job_envelope(job)
        # A terminal job is still read through the exact date/input keyed
        # product path.  This lets the poller render the final rows without a
        # second unscoped lookup.
        exact = service.get(str(job.get("target_trade_date")))
        if exact.get("input_identity") == job.get("input_identity"):
            envelope["product"] = exact.get("product")
            envelope["status"] = exact.get("status", envelope["status"])
        return envelope

    @router.post("/jobs/{job_id}/cancel")
    async def cancel_job(request: Request, job_id: str, date: str | None = None) -> dict[str, Any]:
        _same_origin(request)
        await _reject_client_body(request)
        target = _date(date) if date is not None else None
        job = await run_in_threadpool(service.cancel, job_id, target)
        if job is None:
            raise HTTPException(status_code=404, detail="manager research job not found")
        return _job_envelope(job)

    @router.get("/{target_trade_date}")
    def read_research_by_path(target_trade_date: str) -> dict[str, Any]:
        return service.get(_date(target_trade_date))

    return router
