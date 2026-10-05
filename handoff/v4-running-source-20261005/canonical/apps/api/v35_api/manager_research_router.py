"""Thin FastAPI routes for the V4 manager research job.

The router delegates to the injected V4 service. It does not accept source
URLs, commands, or document text; bounded issuer subsets are verified again
against the owner's native master.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from threading import Event
import re
from typing import Any, Literal

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, HTTPException, Query, Request
from v4.manager_research.store import StoreError
from v4.manager_research.workspace_read_control import WorkspaceReadError


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

    @router.get("/catalyst-observations")
    def read_catalyst_observations(date: str | None = None) -> dict[str, Any]:
        target = _date(date)
        try:
            return service.get_catalyst_observations(target)
        except (ValueError, OSError, KeyError, TypeError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="CATALYST_SOURCE_INTEGRITY_FAILED") from exc

    @router.post("/catalyst-observations/refresh")
    async def refresh_catalyst_observations(request: Request, date: str | None = None) -> dict[str, Any]:
        _same_origin(request)
        await _reject_client_body(request)
        target = _date(date)
        try:
            return await run_in_threadpool(service.refresh_catalyst_observations, target)
        except (ValueError, OSError, KeyError, TypeError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="CATALYST_SOURCE_INTEGRITY_FAILED") from exc

    @router.get("/workspace")
    async def read_manager_workspace(request: Request, date: str | None = None,
            view: Literal["auto", "historical", "dynamic"] = "auto") -> dict[str, Any]:
        # Use the existing ASGI worker pool. A disconnect only withdraws this
        # subscriber; the owner cooperatively stops when no subscriber remains.
        # Native blocking calls cannot be preempted and retain their bounded slot.
        target = _date(date)
        cancelled = Event()
        task = asyncio.create_task(run_in_threadpool(
            service.get_workspace, target, view=view, cancel_event=cancelled))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.1)
                if not task.done() and await request.is_disconnected():
                    raise HTTPException(status_code=499, detail="WORKSPACE_READ_CANCELLED")
            return await task
        except WorkspaceReadError as exc:
            status = {"WORKSPACE_READ_TIMEOUT": 504, "WORKSPACE_READ_BUSY": 503,
                      "WORKSPACE_READ_CANCELLED": 499}.get(exc.code, 409)
            raise HTTPException(status_code=status, detail=exc.code) from exc
        except (ValueError, OSError, KeyError, TypeError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="WORKSPACE_SOURCE_INTEGRITY_FAILED") from exc
        finally:
            cancelled.set()
            if not task.done():
                # Cancel this awaiting ASGI task, not the Python thread. The
                # read coordinator still accounts for work until it exits.
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    @router.post("/workspace/refresh")
    async def refresh_manager_workspace(request: Request, date: str | None = None) -> dict[str, Any]:
        _same_origin(request)
        await _reject_client_body(request)
        target = _date(date)
        try:
            # Existing owner projects existing inputs; no catalyst refresh,
            # quote collection, Stage job or browser-supplied stock list.
            return await run_in_threadpool(service.refresh_workspace_plan, target)
        except (ValueError, OSError, KeyError, TypeError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="WORKSPACE_PLAN_REFRESH_FAILED") from exc

    @router.get("/announcements")
    def read_announcements(date: str | None = None, scope_id: str | None = None) -> dict[str, Any]:
        if scope_id is not None and re.fullmatch(r"[0-9a-f]{64}", scope_id) is None:
            raise HTTPException(status_code=422, detail="announcement scope id is invalid")
        target = _date(date)
        return service.get_announcements(target) if scope_id is None else service.get_announcements(target, scope_id=scope_id)

    @router.post("/announcements/refresh")
    async def refresh_announcements(request: Request, date: str | None = None,
                                    resume: bool = False, source_scope: str | None = None,
                                    issuer_code: str | None = None,
                                    issuer_codes: list[str] | None = Query(default=None)) -> dict[str, Any]:
        _same_origin(request)
        await _reject_client_body(request)
        target = _date(date)
        if source_scope not in {None, "EASTMONEY_HK"} or (issuer_code is not None and source_scope != "EASTMONEY_HK"):
            raise HTTPException(status_code=422, detail="announcement source scope is invalid")
        if issuer_codes is not None:
            if (source_scope is not None or issuer_code is not None
                    or not 1 <= len(issuer_codes) <= 24
                    or len(set(issuer_codes)) != len(issuer_codes)
                    or any(re.fullmatch(r"HK\.\d{5}", code or "") is None or int(code[3:]) == 0
                           for code in issuer_codes)):
                raise HTTPException(status_code=422, detail="announcement issuer subset is invalid")
        if source_scope == "EASTMONEY_HK" and resume:
            raise HTTPException(status_code=422, detail="Eastmoney HK scope cannot resume an HKEX scan")
        try:
            scope_args: dict[str, Any] = {"resume": resume}
            if source_scope is not None:
                scope_args["source_scope"] = source_scope
            if issuer_code is not None:
                scope_args["issuer_code"] = issuer_code
            if issuer_codes is not None:
                scope_args["issuer_codes"] = issuer_codes
            return await run_in_threadpool(service.refresh_announcements, target, **scope_args)
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
            # The original owner's latest attempt preserves the safe exact reason.
            raise HTTPException(status_code=409, detail="ANNOUNCEMENT_OWNER_REFRESH_FAILED") from exc

    @router.get("/{target_trade_date}")
    def read_research_by_path(target_trade_date: str) -> dict[str, Any]:
        return service.get(_date(target_trade_date))

    return router
