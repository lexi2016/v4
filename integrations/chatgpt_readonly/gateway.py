"""Explicit REST contract; no generic proxy, file, SQL or command endpoint."""
from __future__ import annotations

import asyncio
import hmac
import json
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Callable, Literal, Protocol

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response

from . import VERSION
from .saved_reader import PHASES, POOLS, SAFETY, ReadFailure

Pool = Literal[
    "a_d1_premarket_pool", "a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool",
    "a_share_research_recommendation_pool", "a_share_baimao_research_map", "hkconnect_d1_top100",
    "wechat_public_account_v3_preselect",
]
Phase = Literal["PREOPEN", "INTRADAY", "NEXT_DAY", "RETROSPECTIVE", "MANUAL"]
TradeDate = Annotated[str, Query(pattern=r"^[0-9]{8}$", description="Exact saved trading date YYYYMMDD; no latest fallback.")]
Limit = Annotated[int, Query(ge=1, le=50)]
Offset = Annotated[int, Query(ge=0, le=100000)]


class Reader(Protocol):
    def read(self, kind: str, params: dict) -> dict: ...


@dataclass(frozen=True)
class Limits:
    response_bytes: int = 64_000
    concurrency: int = 1
    requests_per_minute: int = 60
    read_seconds: float = 10

    def __post_init__(self):
        if (not 2048 <= self.response_bytes <= 90_000 or not 1 <= self.concurrency <= 2
                or not 1 <= self.requests_per_minute <= 600 or not 0 < self.read_seconds <= 15):
            raise ValueError("GATEWAY_LIMITS_INVALID")


def json_response(payload: dict, code: int = 200) -> Response:
    return Response(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(),
                    status_code=code, media_type="application/json",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def error(code: str, http_status: int) -> Response:
    return json_response({"status": "unavailable", "error": code, **SAFETY}, http_status)


def create_app(reader: Reader, token_provider: Callable[[], str | None], *, limits: Limits = Limits()) -> FastAPI:
    app = FastAPI(title="Saved V4 research reader", version=VERSION, docs_url=None,
                  redoc_url=None, openapi_url=None, redirect_slashes=False,
                  servers=[{"url": "https://v4-readonly.example.invalid",
                            "description": "NOT_DEPLOYED: replace only after authorized HTTPS verification."}])
    slots = threading.BoundedSemaphore(limits.concurrency)
    history: deque[float] = deque()
    history_lock = threading.Lock()
    routes = {
        "/health": set(),
        "/v1/pools": {"trade_date", "market", "pool_id", "limit", "offset"},
        "/v1/announcements": {"trade_date", "market", "limit", "offset"},
        "/v1/reviews": {"trade_date", "market", "phase"},
    }

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        path = request.scope.get("path", "")
        raw = request.scope.get("raw_path", b"").split(b"?", 1)[0]
        public = path == "/health" and raw == b"/health" and request.method == "GET"
        if not public:
            try:
                expected = token_provider()
            except Exception:
                return error("AUTHENTICATION_UNAVAILABLE", 401)
            values = request.headers.getlist("authorization")
            candidate = values[0][7:] if len(values) == 1 and values[0].startswith("Bearer ") else None
            if (not isinstance(expected, str) or len(expected) < 32 or len(expected) > 256
                    or not isinstance(candidate, str) or len(candidate) > 256
                    or not hmac.compare_digest(candidate.encode(), expected.encode())):
                return error("UNAUTHORIZED", 401)
        if request.method != "GET":
            return error("METHOD_NOT_ALLOWED", 405)
        if (raw != path.encode("ascii", errors="replace") or b"%" in raw or b"\\" in raw
                or b"//" in raw or any(part in {b".", b".."} for part in raw.split(b"/"))):
            return error("PATH_NOT_ALLOWED", 404)
        allowed = routes.get(path)
        if allowed is None and re.fullmatch(r"/v1/stocks/HK\.[0-9]{5}/research", path):
            allowed = {"trade_date", "market", "phase"}
        if allowed is None:
            return error("ROUTE_NOT_ALLOWED", 404)
        pairs = list(request.query_params.multi_items())
        if len(pairs) != len({key for key, _ in pairs}) or any(key not in allowed for key, _ in pairs):
            return error("PARAMETER_NOT_ALLOWED", 422)
        if len(request.scope.get("query_string", b"")) > 2048:
            return error("QUERY_TOO_LARGE", 422)
        if request.headers.get("content-length", "0") != "0" or "transfer-encoding" in request.headers:
            return error("GET_BODY_NOT_ALLOWED", 400)
        with history_lock:
            now = time.monotonic()
            while history and now - history[0] >= 60:
                history.popleft()
            if len(history) >= limits.requests_per_minute:
                return error("RATE_LIMITED", 429)
            history.append(now)
        try:
            return await call_next(request)
        except Exception:
            return error("INTERNAL_READ_UNAVAILABLE", 503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo attacker-controlled values or auth/query strings.
        return error("INVALID_PARAMETERS", 422)

    async def read(kind, params):
        try:
            day = datetime.strptime(params["trade_date"], "%Y%m%d")
            if day.strftime("%Y%m%d") != params["trade_date"]:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            return error("INVALID_TRADE_DATE", 422)
        if kind == "pools" and params["market"] != ("HK" if params["pool_id"] == "hkconnect_d1_top100" else "A"):
            return error("POOL_MARKET_MISMATCH", 422)
        if not slots.acquire(blocking=False):
            return error("READ_CONCURRENCY_LIMIT", 503)
        def load():
            payload = reader.read(kind, params)
            response = json_response(payload)
            if len(response.body) > limits.response_bytes:
                return error("RESPONSE_TOO_LARGE_REDUCE_LIMIT", 413)
            return response
        future = asyncio.get_running_loop().run_in_executor(None, load)
        def completed(value):
            # A timed-out filesystem worker retains its slot until it really exits.
            # No request can grow an unbounded queue of abandoned reads.
            slots.release()
            if not value.cancelled():
                value.exception()
        future.add_done_callback(completed)
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=limits.read_seconds)
        except TimeoutError:
            return error("READ_TIMEOUT", 504)
        except ReadFailure as exc:
            return error(exc.code, exc.http_status)
        except Exception:
            return error("SAVED_READ_UNAVAILABLE", 503)

    @app.get("/health", operation_id="savedV4Health", summary="Gateway liveness only; does not prove V4 data is available.")
    def health():
        return json_response({"status": "ok", "version": VERSION, **SAFETY})

    @app.get("/v1/pools", operation_id="readSavedV4Pool", summary="Read one exact-date saved pool; follow next_offset for all rows.")
    async def pools(trade_date: TradeDate, market: Literal["A", "HK"], pool_id: Pool, limit: Limit = 20, offset: Offset = 0):
        return await read("pools", dict(trade_date=trade_date, market=market, pool_id=pool_id, limit=limit, offset=offset))

    @app.get("/v1/stocks/{code}/research", operation_id="readSavedV4StockResearch", summary="Read one HK stock from a saved plan for an explicit date and phase.")
    async def research(code: str, trade_date: TradeDate, market: Literal["HK"], phase: Phase):
        return await read("research", dict(trade_date=trade_date, market=market, code=code, phase=phase))

    @app.get("/v1/announcements", operation_id="readSavedV4Announcements", summary="Read saved HK delivery summaries; unknown does not mean verified or actionable.")
    async def announcements(trade_date: TradeDate, market: Literal["HK"], limit: Limit = 20, offset: Offset = 0):
        return await read("announcements", dict(trade_date=trade_date, market=market, limit=limit, offset=offset))

    @app.get("/v1/reviews", operation_id="readSavedV4Review", summary="Read a saved manager-plan review; absent data remains unavailable.")
    async def reviews(trade_date: TradeDate, market: Literal["HK"], phase: Phase):
        return await read("reviews", dict(trade_date=trade_date, market=market, phase=phase))

    return app


def openapi_document(app: FastAPI) -> dict:
    """Offline export only. No schema or documentation route is exposed at runtime."""
    doc = app.openapi()
    doc.setdefault("components", {}).setdefault("securitySchemes", {})["V4ReadOnlyBearer"] = {
        "type": "http", "scheme": "bearer", "description": "Dedicated V4 read-only secret; configured separately after approval."}
    for path, methods in doc["paths"].items():
        for operation in methods.values():
            operation["security"] = [] if path == "/health" else [{"V4ReadOnlyBearer": []}]
            operation["x-openai-isConsequential"] = False
            operation["responses"] = {
                "200": {"description": "Saved-data result; inspect status, as_of, source, missing_reasons and pagination.",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SavedResult"}}}},
                **{str(code): {"description": description} for code, description in
                   [(400, "GET bodies refused"), (401, "Authentication refused"), (404, "No exact saved data or route"),
                    (405, "Method refused"), (413, "Reduce page limit; no silent truncation"),
                    (422, "Invalid parameters"), (429, "Rate limited"),
                    (503, "Source unavailable, invalid or concurrency limit"), (504, "Read deadline exceeded")]},
            }
            if path == "/health":
                operation["responses"]["200"]["content"]["application/json"]["schema"] = {
                    "type": "object", "properties": {
                        "status": {"type": "string", "const": "ok"}, "version": {"type": "string"},
                        **{k: {"type": "boolean", "const": v} for k, v in SAFETY.items()},
                    },
                }
    doc["components"]["schemas"]["SavedResult"] = {
        "type": "object", "properties": {
            "trade_date": {"type": "string", "pattern": "^[0-9]{8}$"},
            "as_of": {"type": ["string", "null"], "format": "date-time", "description": "Source-recorded time only; null with a reason when not recorded."},
            "observed_at": {"type": "string", "format": "date-time"},
            "status": {"type": "string", "enum": ["valid", "stale", "unknown", "unavailable"]},
            "source_status": {"type": ["string", "null"]}, "market": {"type": "string", "enum": ["A", "HK"]},
            "missing_reasons": {"type": "array", "items": {"type": "string"}},
            "source": {"type": "array", "items": {"type": "object"}}, "version": {"type": "object"},
            "rows": {"type": "array", "items": {"type": "object"}}, "coverage": {"type": "object"},
            **{k: {"type": "boolean", "const": v} for k, v in SAFETY.items()},
        },
    }
    return doc
