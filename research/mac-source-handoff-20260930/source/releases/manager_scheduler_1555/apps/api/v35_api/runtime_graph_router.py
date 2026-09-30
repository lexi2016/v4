"""V3-compatible runtime-graph API backed only by V3.5-owned data."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from infrastructure.runtime_graph.repair import MAX_REQUEST_BYTES, parse_repair_request_bytes
from infrastructure.runtime_graph.service import RuntimeGraphService


_NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}
ADMIN_KEY_ENV = "V35_ADMIN_KEY"
ADMIN_HEADER = "X-8872-Admin-Key"


def _repair_http_status(status: str) -> int:
    if status == "REPAIR_PASS" or status.startswith("REPAIR_FAILED_"):
        return 200
    if status == "REPAIR_CIRCUIT_OPEN":
        return 429
    if status == "REPAIR_BUSY":
        return 409
    if status.startswith("REPAIR_DENIED_"):
        return 403
    return 409


async def _read_bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length", "")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                raise ValueError("REPAIR_REQUEST_SIZE_INVALID")
        except (TypeError, ValueError) as error:
            raise ValueError("REPAIR_REQUEST_SIZE_INVALID") from error
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        if not isinstance(chunk, bytes):
            raise ValueError("REPAIR_REQUEST_SIZE_INVALID")
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise ValueError("REPAIR_REQUEST_SIZE_INVALID")
        chunks.append(chunk)
    if not chunks:
        raise ValueError("REPAIR_REQUEST_SIZE_INVALID")
    return b"".join(chunks)


def _request_admin_key(request: Request) -> str:
    direct = request.headers.get(ADMIN_HEADER, "").strip()
    if direct:
        return direct
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _admin_allowed(request: Request) -> tuple[bool, str]:
    configured = os.environ.get(ADMIN_KEY_ENV, "").strip()
    if not configured:
        return False, "ADMIN_AUTH_DISABLED"
    submitted = _request_admin_key(request)
    if not submitted:
        return False, "ADMIN_KEY_REQUIRED"
    if not secrets.compare_digest(submitted, configured):
        return False, "ADMIN_KEY_INVALID"
    return True, "ADMIN_AUTH_OK"


def _admin_denied_response(reason: str) -> JSONResponse:
    status_code = 403 if reason == "ADMIN_AUTH_DISABLED" else 401
    response = JSONResponse(
        {
            "ok": False,
            "status": reason,
            "detail": "runtime graph repair requires the configured admin key",
            "auth_header": ADMIN_HEADER,
        },
        status_code=status_code,
        headers=_NO_CACHE_HEADERS,
    )
    response.headers["WWW-Authenticate"] = "API-Key"
    return response


def create_runtime_graph_router(data_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v3/runtime-graph", tags=["runtime-graph"])
    service = RuntimeGraphService(Path(data_root))

    @router.get("/snapshot", response_model=dict)
    def runtime_graph_snapshot() -> JSONResponse:
        return JSONResponse(service.snapshot(), headers=_NO_CACHE_HEADERS)

    @router.get("/status", response_model=dict)
    def runtime_graph_status() -> JSONResponse:
        payload = service.status()
        return JSONResponse(payload, headers=_NO_CACHE_HEADERS)

    @router.get("/events", response_model=dict)
    def runtime_graph_events(
        node_id: str = Query(..., min_length=1, max_length=256),
        limit: int = Query(100, ge=1, le=500),
    ) -> JSONResponse:
        return JSONResponse(service.events(node_id, limit), headers=_NO_CACHE_HEADERS)

    @router.post("/repair", response_model=dict)
    async def runtime_graph_repair(request: Request) -> JSONResponse:
        authorized, reason = _admin_allowed(request)
        if not authorized:
            return _admin_denied_response(reason)
        try:
            parsed = parse_repair_request_bytes(await _read_bounded_body(request))
        except (ValueError, OverflowError):
            raise HTTPException(status_code=422, detail="REPAIR_REQUEST_INVALID") from None
        result = await run_in_threadpool(
            service.repair_controller.handle,
            parsed,
            authorization_verified=authorized,
        )
        return JSONResponse(
            result.to_payload(),
            status_code=_repair_http_status(result.status),
            headers=_NO_CACHE_HEADERS,
        )

    return router
