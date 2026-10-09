"""Thin FastAPI routes for the V4 manager research job.

The router delegates to the injected V4 service. It does not accept source
URLs, commands, or document text; bounded issuer subsets are verified again
against the owner's native master.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from threading import Event
import re
from typing import Any, Literal
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, HTTPException, Query, Request
from v4.manager_research.store import StoreError
from v4.manager_research.workspace_read_control import WorkspaceReadError
from v4.manager_research.workspace_projection import HK
from v4.manager_research.plan_owner_dispatch import PlanOwnerAdmissionError


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


def _announcement_date(value: str | None) -> str | None:
    if value is None:
        return None
    if re.fullmatch(r"(?:\d{8}|\d{4}-\d{2}-\d{2})", value) is None:
        raise HTTPException(status_code=422, detail="announcement publication date must use YYYYMMDD or YYYY-MM-DD")
    try:
        return datetime.strptime(value.replace("-", ""), "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="announcement publication date must be a real date") from exc


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


async def _bounded_json_body(request: Request, *, limit: int) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise HTTPException(status_code=413, detail="announcement analysis import body is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="content-length is invalid") from exc
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > limit:
            raise HTTPException(status_code=413, detail="announcement analysis import body is too large")
        payload.extend(chunk)
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="announcement analysis import JSON is invalid") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="announcement analysis import envelope is invalid")
    return value


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
            view: Literal["auto", "historical", "dynamic"] = "auto",
            announcement_date: str | None = None,
            selection_date: str | None = None) -> dict[str, Any]:
        # Use the existing ASGI worker pool. A disconnect only withdraws this
        # subscriber; the owner cooperatively stops when no subscriber remains.
        # Native blocking calls cannot be preempted and retain their bounded slot.
        target = _date(date)
        cancelled = Event()
        workspace_args: dict[str, Any] = {"view": view, "cancel_event": cancelled}
        if announcement_date is not None:
            workspace_args["announcement_date"] = _announcement_date(announcement_date)
        if selection_date is not None:
            workspace_args["selection_date"] = _date(selection_date)
        task = asyncio.create_task(run_in_threadpool(
            service.get_workspace, target, **workspace_args))
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
    async def refresh_manager_workspace(request: Request, date: str | None = None,
            selection_date: str | None = None,
            announcement_date: str | None = None) -> dict[str, Any]:
        _same_origin(request)
        await _reject_client_body(request)
        target = _date(date)
        workspace_date_bindings: dict[str, str] = {}
        if selection_date is not None:
            workspace_date_bindings['selection_date'] = _date(selection_date)
        if announcement_date is not None:
            normalized_announcement = _announcement_date(announcement_date)
            assert normalized_announcement is not None
            workspace_date_bindings['announcement_date'] = normalized_announcement
        actual_now = datetime.now(HK)
        target_day = datetime.strptime(target, "%Y%m%d").date()
        timing = "RETROSPECTIVE" if target_day < actual_now.astimezone(HK).date() else "UNCLASSIFIED"
        trigger_id = hashlib.sha256(uuid4().bytes).hexdigest()
        try:
            # Existing owner projects existing inputs; no catalyst refresh,
            # quote collection, Stage job or browser-supplied stock list.
            result = await run_in_threadpool(service.refresh_workspace_plan, target,
                execution_kind="MANUAL_REFRESH", now=actual_now,
                workspace_date_bindings=workspace_date_bindings or None,
                execution_context={"trigger_kind":"MANUAL","timing":timing,
                    "scheduled_for":None,"trigger_id":trigger_id,
                    "natural_run_verified":False})
            if not isinstance(result, dict) or not isinstance(result.get("plan_product"), dict):
                raise ValueError("WORKSPACE_PLAN_REFRESH_RESULT_INVALID")
            product = result["plan_product"]
            if (result.get("status") == "CANNOT_CONFIRM"
                    and result.get("reason") == "WORKSPACE_PLAN_INPUTS_NOT_READY"
                    and result.get("target_trade_date") == target
                    and product.get("status") == "CANNOT_CONFIRM"
                    and product.get("consumed") is False
                    and product.get("run_id") is None and product.get("sha256") is None
                    and result.get("workspace_plan_attempt") is None
                    and isinstance(result.get("failure_reasons"), list)
                    and all(isinstance(reason, str) for reason in result["failure_reasons"])
                    and result.get("RESEARCH_ONLY") is True
                    and result.get("production_allowed") is False
                    and result.get("buy_gate_updated") is False
                    and result.get("orders_sent") is False):
                return {**result, "store_latest_matches_http_plan_product": False}
            persisted = await run_in_threadpool(service.get_workspace_plan, target)
            if not isinstance(persisted, dict):
                raise ValueError("WORKSPACE_PLAN_PERSISTED_READBACK_MISSING")
            owner = "ManagerResearchJobService.refresh_workspace_plan"
            attempt = result.get("workspace_plan_attempt")
            matches = (
                isinstance(attempt, dict)
                and product.get("status") == "CURRENT"
                and product.get("consumed") is True
                and product.get("run_id") == persisted.get("run_id")
                and product.get("sha256") == persisted.get("sha256")
                and persisted.get("target_trade_date") == target
                and persisted.get("owner") == owner
                and result.get("input_identity") == persisted.get("input_identity")
                and attempt.get("run_id") == persisted.get("run_id")
                and persisted.get("RESEARCH_ONLY") is True
                and persisted.get("production_allowed") is False
                and persisted.get("buy_gate_updated") is False
                and persisted.get("orders_sent") is False
            )
            if not matches:
                raise ValueError("WORKSPACE_PLAN_REFRESH_PERSISTED_READBACK_MISMATCH")
            # This endpoint materializes an exact-date research plan only. The
            # extra fields expose the owner’s independent store readback to
            # operators without changing the stored product or its inputs.
            safety = {key: persisted.get(key) for key in (
                "RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent",
            )}
            return {
                **result,
                "target_trade_date": target,
                "execution_kind": persisted.get("execution_kind", "MANUAL_REFRESH"),
                "formal_recommendation_count": 0,
                "store_latest_matches_http_plan_product": True,
                "persisted_store": {
                    "target_trade_date": persisted.get("target_trade_date"),
                    "run_id": persisted.get("run_id"),
                    "product_sha256": persisted.get("sha256"),
                    "execution_kind": persisted.get("execution_kind", "MANUAL_REFRESH"),
                    "owner": persisted.get("owner"),
                    "RESEARCH_ONLY": persisted.get("RESEARCH_ONLY"),
                    "production_allowed": persisted.get("production_allowed"),
                    "buy_gate_updated": persisted.get("buy_gate_updated"),
                    "orders_sent": persisted.get("orders_sent"),
                },
                "safety": safety,
            }
        except (ValueError, OSError, KeyError, TypeError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="WORKSPACE_PLAN_REFRESH_FAILED") from exc

    @router.post("/workspace/us-mapping/refresh")
    async def refresh_us_mapping(request: Request, date: str | None = None) -> dict[str, Any]:
        """Explicit, bounded recovery through the original US mapping owner."""
        _same_origin(request)
        await _reject_client_body(request)
        target = _date(date)
        actual_now = datetime.now(HK)
        target_day = datetime.strptime(target, "%Y%m%d").date()
        timing = "RETROSPECTIVE" if target_day < actual_now.date() else "UNCLASSIFIED"
        trigger_id = hashlib.sha256(uuid4().bytes).hexdigest()
        try:
            result = await run_in_threadpool(
                service.refresh_us_mapping_research, target, now=actual_now,
                timeout_seconds=5.0,
                execution_context={
                    "trigger_kind": "MANUAL",
                    "timing": timing,
                    "scheduled_for": None,
                    "trigger_id": trigger_id,
                    "natural_run_verified": False,
                },
            )
            if not isinstance(result, dict) or result.get("target_trade_date") != target:
                raise ValueError("US_MAPPING_OWNER_RESULT_INVALID")
            return {**result, "target_trade_date": target}
        except (ValueError, OSError, KeyError, TypeError, RuntimeError, TimeoutError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="US_MAPPING_OWNER_REFRESH_FAILED") from exc

    @router.post("/workspace/scheduled-cycle")
    async def run_bound_workspace_cycle(request: Request, date: str | None = None,
            binding_sha256: str | None = None) -> dict[str, Any]:
        """Execute one configured scheduler tick through this injected API owner."""
        _same_origin(request)
        await _reject_client_body(request)
        target = _date(date)
        if binding_sha256 is None or re.fullmatch(r"[0-9a-f]{64}", binding_sha256) is None:
            raise HTTPException(status_code=422, detail="binding_sha256 must be a lowercase SHA256")
        try:
            from v4.manager_research.plan_owner_dispatch import execute_bound_plan_cycle
            return await run_in_threadpool(execute_bound_plan_cycle, service, target, binding_sha256)
        except PlanOwnerAdmissionError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        except (ValueError, OSError, KeyError, TypeError, RuntimeError, TimeoutError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="SCHEDULED_WORKSPACE_OWNER_FAILED") from exc

    @router.post("/workspace/daily-cycle")
    async def run_bound_daily_workspace_cycle(request: Request, date: str | None = None,
            binding_sha256: str | None = None) -> dict[str, Any]:
        """Run the fixed daily preparation and one original-plan child."""
        _same_origin(request)
        await _reject_client_body(request)
        target = _date(date)
        if binding_sha256 is None or re.fullmatch(r"[0-9a-f]{64}", binding_sha256) is None:
            raise HTTPException(status_code=422, detail="binding_sha256 must be a lowercase SHA256")
        try:
            from v4.manager_research.plan_owner_dispatch import execute_bound_daily_cycle
            return await run_in_threadpool(execute_bound_daily_cycle, service, target, binding_sha256)
        except PlanOwnerAdmissionError as exc:
            raise HTTPException(status_code=409, detail=exc.code) from exc
        except (ValueError, OSError, KeyError, TypeError, RuntimeError, TimeoutError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="SCHEDULED_WORKSPACE_OWNER_FAILED") from exc

    @router.get("/announcements")
    def read_announcements(date: str | None = None, scope_id: str | None = None,
                          source_scope: str | None = None,
                          publication_date: str | None = None) -> dict[str, Any]:
        if source_scope is not None:
            if (source_scope != "EASTMONEY_HK_DATE_CATALOG" or publication_date is None
                    or scope_id is not None):
                raise HTTPException(status_code=422, detail="announcement date catalog scope is invalid")
            return service.get_announcement_date_catalog(_date(date), publication_date)
        if publication_date is not None:
            raise HTTPException(status_code=422, detail="announcement publication date requires a date catalog scope")
        if scope_id is not None and re.fullmatch(r"[0-9a-f]{64}", scope_id) is None:
            raise HTTPException(status_code=422, detail="announcement scope id is invalid")
        target = _date(date)
        return service.get_announcements(target) if scope_id is None else service.get_announcements(target, scope_id=scope_id)

    @router.get("/announcements/analysis")
    def read_announcement_analysis(date: str | None = None,
                                   publication_date: str | None = None) -> dict[str, Any]:
        target = _date(date)
        publication = _announcement_date(publication_date)
        try:
            result = service.get_announcement_analysis(target, publication)
            analysis = result.get("analysis") if isinstance(result, dict) else None
            product_sha = analysis.get("product_sha256") if isinstance(analysis, dict) else None
            if isinstance(product_sha, str):
                from v4.manager_research.announcement_analysis import product_path
                from v4.manager_research.workspace_announcements import validate_owner_analysis_import_receipt
                raw_product = service.store._read(product_path(service.store, target, result.get("publication_date")))
                receipt_path = product_path(service.store, target, result.get("publication_date")).with_name("owner_import_receipt.v1.json")
                receipt = service.store._read(receipt_path)
                if receipt is not None:
                    result["owner_import_receipt"] = validate_owner_analysis_import_receipt(receipt, raw_product)
                else:
                    result["owner_import_receipt"] = None
            # R3 analysis remains readable with its original product bytes.
            # Consumption is a separate, shared complete-chain validation;
            # a legacy product with no judgment is never silently admitted.
            from v4.manager_research.workspace_announcements import read_analysis_consumption
            result["consumption_validation"] = read_analysis_consumption(
                service, target, result.get("publication_date"), analysis_readback=result)
            return result
        except (ValueError, OSError, KeyError, TypeError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="ANNOUNCEMENT_ANALYSIS_READBACK_REJECTED") from exc

    @router.post("/announcements/analysis/import")
    async def import_announcement_analysis(request: Request) -> dict[str, Any]:
        if not request.headers.get("origin"):
            raise HTTPException(status_code=403, detail="same-origin header is required")
        _same_origin(request)
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="announcement analysis import requires application/json")
        envelope = await _bounded_json_body(request, limit=16 * 1024 * 1024)
        if set(envelope) != {"schema_version", "evidence_run_id", "handoff_manifest_sha256", "product_sha256"} or envelope.get("schema_version") != "v4.manager_research.announcement_analysis_import_ref.v1":
            raise HTTPException(status_code=422, detail="announcement analysis import envelope is invalid")
        try:
            from v4.manager_research.workspace_announcements import validate_registered_handoff
            registered = validate_registered_handoff(service.store, envelope.get("evidence_run_id"),
                envelope.get("handoff_manifest_sha256"), envelope.get("product_sha256"))
            product = registered["product"]
            from v4.manager_research.workspace_announcements import validate_agent_judgment_receipt
            agent_receipt = validate_agent_judgment_receipt(product.get("agent_judgment_receipt"), product)
            imported = await run_in_threadpool(service.import_announcement_analysis, product)
            analysis = imported.get("analysis") if isinstance(imported, dict) else None
            if not isinstance(analysis, dict) or analysis.get("status") != "VERIFIED" or analysis.get("product_sha256") != product.get("sha256"):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_IMPORT_READBACK_FAILED")
            from v4.manager_research.announcement_analysis import product_path
            owner_path = product_path(service.store, product["target_trade_date"], product["publication_date"]).with_name("owner_import_receipt.v1.json")
            existing = service.store._read(owner_path)
            if existing is not None:
                from v4.manager_research.workspace_announcements import validate_owner_analysis_import_receipt
                owner_receipt = validate_owner_analysis_import_receipt(existing, product)
                if (owner_receipt.get("parent_task_id") != agent_receipt.get("parent_task_id")
                        or owner_receipt.get("parent_run_id") != agent_receipt.get("parent_run_id")):
                    raise ValueError("ANNOUNCEMENT_ANALYSIS_OWNER_RECEIPT_CONFLICT")
            else:
                owner_receipt = {
                    "schema_version": "v4.manager_research.announcement_analysis_owner_import.v1",
                    "status": "VERIFIED",
                    "target_trade_date": product["target_trade_date"],
                    "publication_date": product["publication_date"],
                    "product_sha256": product["sha256"],
                    "source_manifest_sha256": product["source_manifest_sha256"],
                    "evidence_run_id": agent_receipt["evidence_run_id"],
                    "handoff_manifest_sha256": envelope["handoff_manifest_sha256"],
                    "agent_judgment_receipt_sha256": agent_receipt["sha256"],
                    "parent_task_id": agent_receipt["parent_task_id"],
                    "parent_run_id": agent_receipt["parent_run_id"],
                    "available_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                    "owner": "ManagerResearchJobService.import_announcement_analysis",
                    "RESEARCH_ONLY": True,
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
                from v4.manager_research.workspace_projection import digest
                owner_receipt["sha256"] = digest(owner_receipt)
                with service.store._transaction(product["target_trade_date"], "announcement-owner-import-receipt"):
                    service.store._write_atomic(owner_path, owner_receipt)
            from v4.manager_research.workspace_announcements import validate_owner_analysis_import_receipt
            validate_owner_analysis_import_receipt(owner_receipt, product)
            result = service.get_announcement_analysis(product["target_trade_date"], product["publication_date"])
            result["owner_import_receipt"] = owner_receipt
            if result.get("analysis", {}).get("product_sha256") != product.get("sha256"):
                raise ValueError("ANNOUNCEMENT_ANALYSIS_FINAL_READBACK_FAILED")
            result["import_status"] = imported.get("import_status")
            result["handoff_manifest_sha256"] = envelope.get("handoff_manifest_sha256")
            result["evidence_run_id"] = envelope.get("evidence_run_id")
            from v4.manager_research.workspace_announcements import read_analysis_consumption
            result["consumption_validation"] = read_analysis_consumption(service,
                product["target_trade_date"], product["publication_date"], analysis_readback=result)
            if result["consumption_validation"]["validation_status"] != "VERIFIED":
                raise ValueError("ANNOUNCEMENT_ANALYSIS_FINAL_CONSUMPTION_VALIDATION_FAILED")
            return result
        except HTTPException:
            raise
        except (ValueError, OSError, KeyError, TypeError, StoreError) as exc:
            raise HTTPException(status_code=409, detail="ANNOUNCEMENT_ANALYSIS_IMPORT_REJECTED") from exc

    @router.post("/announcements/refresh")
    async def refresh_announcements(request: Request, date: str | None = None,
                                    resume: bool = False, source_scope: str | None = None,
                                    publication_date: str | None = None,
                                    issuer_code: str | None = None,
                                    issuer_codes: list[str] | None = Query(default=None)) -> dict[str, Any]:
        _same_origin(request)
        await _reject_client_body(request)
        target = _date(date)
        date_catalog_scope = "EASTMONEY_HK_DATE_CATALOG"
        if (source_scope not in {None, "EASTMONEY_HK", date_catalog_scope}
                or (issuer_code is not None and source_scope != "EASTMONEY_HK")
                or (source_scope == date_catalog_scope and (publication_date is None or issuer_code is not None or issuer_codes is not None))
                or (source_scope != date_catalog_scope and publication_date is not None)):
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
            if publication_date is not None:
                scope_args["publication_date"] = publication_date
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
