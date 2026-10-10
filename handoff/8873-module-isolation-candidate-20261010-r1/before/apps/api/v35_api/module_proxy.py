"""Fixed-role API routing and backend proxy for the V4 module split.

The gateway owns the public same-origin URL space. Its upstream addresses are
loaded from the checked-in module contract and are never accepted from a
request. Stage and Manager processes retain only their declared routes.
"""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import httpx
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send


CONTRACT_PATH = Path(__file__).resolve().parents[3] / "deployment" / "api_module_contracts.json"
VALID_ROLES = frozenset({"combined", "gateway", "stage", "manager"})
_SHARED_BACKEND_ROUTES = frozenset({"/healthz", "/readyz"})
_HOP_BY_HOP_HEADERS = frozenset({
    b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization",
    b"te", b"trailer", b"transfer-encoding", b"upgrade",
})


def load_module_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("API_MODULE_CONTRACT_UNREADABLE") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "v4.api_module_contracts.v1":
        raise RuntimeError("API_MODULE_CONTRACT_SCHEMA_INVALID")
    roles = value.get("roles")
    if not isinstance(roles, dict) or not {"gateway", "stage", "manager"} <= roles.keys():
        raise RuntimeError("API_MODULE_CONTRACT_ROLES_INVALID")
    for role in ("stage", "manager"):
        target = roles[role].get("upstream")
        if not isinstance(target, dict):
            raise RuntimeError("API_MODULE_CONTRACT_UPSTREAM_INVALID")
        host = target.get("host")
        try:
            address = ipaddress.ip_address(host)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("API_MODULE_UPSTREAM_MUST_BE_LOOPBACK") from exc
        if not address.is_loopback or target.get("port") != roles[role].get("port"):
            raise RuntimeError("API_MODULE_UPSTREAM_BINDING_INVALID")
    if value.get("proxy_policy", {}).get("retry_post") is not False:
        raise RuntimeError("API_MODULE_POST_RETRY_MUST_BE_DISABLED")
    return value


def _route_pattern(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[a-zA-Z_][a-zA-Z0-9_]*\})", path)
    source = "".join(r"[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
                     for part in parts)
    return re.compile("^" + source + "$")


def _owned_routes(contract: Mapping[str, Any], role: str) -> list[dict[str, str]]:
    names = ("stage_routes",) if role == "stage" else ("manager_research_routes", "manager_other_routes")
    routes: list[dict[str, str]] = []
    for name in names:
        value = contract.get(name)
        if not isinstance(value, list):
            raise RuntimeError("API_MODULE_ROUTE_LIST_INVALID:" + name)
        for route in value:
            if not isinstance(route, dict) or not isinstance(route.get("method"), str) or not isinstance(route.get("path"), str):
                raise RuntimeError("API_MODULE_ROUTE_INVALID:" + name)
            routes.append({"method": route["method"].upper(), "path": route["path"]})
    return routes


def _module_prefix(path: str) -> bool:
    prefixes = (
        "/api/v3/meta/stages",
        "/api/v3/preselection-pools",
        "/api/v3/workbench/stage",
        "/api/v3/stage-center/selection",
        "/api/v4/manager/research",
        "/api/v4/manager/workbench-research",
        "/api/v3/manager/stage-selection",
    )
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)


def _match_route(routes: Iterable[Mapping[str, str]], path: str) -> tuple[dict[str, str] | None, set[str]]:
    allowed: set[str] = set()
    match: dict[str, str] | None = None
    for route in routes:
        if _route_pattern(route["path"]).fullmatch(path):
            allowed.add(route["method"])
            match = dict(route)
    return match, allowed


async def _read_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            continue
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


def _filtered_headers(headers: Iterable[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    values = list(headers)
    connection_tokens: set[bytes] = set()
    for name, value in values:
        if name.lower() == b"connection":
            connection_tokens.update(token.strip().lower() for token in value.split(b","))
    excluded = _HOP_BY_HOP_HEADERS | connection_tokens | {b"host"}
    return [(name.lower(), value) for name, value in values if name.lower() not in excluded]


class ModuleProxyMiddleware:
    """Dispatch only fixed, contracted Stage and Manager routes."""

    def __init__(self, app: ASGIApp, *, contract: Mapping[str, Any] | None = None,
                 client_factory: Any = httpx.AsyncClient) -> None:
        self.app = app
        self.contract = dict(contract or load_module_contract())
        self.client_factory = client_factory
        self.stage_routes = _owned_routes(self.contract, "stage")
        self.manager_routes = _owned_routes(self.contract, "manager")
        self.timeouts = self.contract["proxy_policy"]["timeouts_seconds"]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        match, methods = _match_route(self.stage_routes, path)
        role = "stage"
        if match is None:
            match, methods = _match_route(self.manager_routes, path)
            role = "manager"
        if match is None:
            if _module_prefix(path):
                await self._plain(send, 404, b'{"detail":"Not Found"}')
                return
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        if method not in methods:
            await self._plain(send, 405, b'{"detail":"Method Not Allowed"}',
                              [(b"allow", b", ".join(sorted(item.encode("ascii") for item in methods)))] )
            return
        target = self.contract["roles"][role]["upstream"]
        raw_path = scope.get("raw_path") or path.encode("utf-8")
        query = scope.get("query_string", b"")
        url = f"http://{target['host']}:{target['port']}" + raw_path.decode("ascii", errors="strict")
        if query:
            url += "?" + query.decode("ascii", errors="strict")
        request_headers = _filtered_headers(scope.get("headers", []))
        body = await _read_body(receive)
        timeout = httpx.Timeout(
            connect=float(self.timeouts["connect"]),
            read=float(self.timeouts["read"]),
            write=float(self.timeouts["write"]),
            pool=float(self.timeouts["pool"]),
        )
        try:
            async with self.client_factory(timeout=timeout, trust_env=False) as client:
                response = await client.request(method, url, headers=request_headers, content=body)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
            await self._plain(send, 504, b'{"detail":"Module backend timeout"}')
            return
        except httpx.HTTPError:
            await self._plain(send, 503, b'{"detail":"Module backend unavailable"}')
            return
        response_headers = _filtered_headers(response.headers.raw)
        await send({"type": "http.response.start", "status": response.status_code,
                    "headers": response_headers})
        await send({"type": "http.response.body", "body": response.content, "more_body": False})

    @staticmethod
    async def _plain(send: Send, status: int, body: bytes,
                     extra_headers: list[tuple[bytes, bytes]] | None = None) -> None:
        headers = [(b"content-type", b"application/json; charset=utf-8"),
                   (b"content-length", str(len(body)).encode("ascii"))]
        if extra_headers:
            headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body, "more_body": False})


def configure_module_role(app: FastAPI, role: str) -> FastAPI:
    if role not in VALID_ROLES:
        raise ValueError("V35_API_ROLE_UNSUPPORTED")
    if role == "combined":
        return app
    contract = load_module_contract()
    if role in {"stage", "manager"}:
        allowed = _owned_routes(contract, role)
        allow_by_path: dict[str, set[str]] = {}
        for route in allowed:
            allow_by_path.setdefault(route["path"], set()).add(route["method"])
        retained = []
        for route in app.router.routes:
            route_path = getattr(route, "path", None)
            route_methods = {str(method).upper() for method in (getattr(route, "methods", None) or set())}
            if route_path in _SHARED_BACKEND_ROUTES:
                retained.append(route)
            elif route_path in allow_by_path and route_methods & allow_by_path[route_path]:
                retained.append(route)
        app.router.routes[:] = retained
    if role == "gateway":
        app.add_middleware(ModuleProxyMiddleware, contract=contract)
    app.state.v35_api_role = role
    return app


__all__ = ["CONTRACT_PATH", "ModuleProxyMiddleware", "VALID_ROLES", "configure_module_role", "load_module_contract"]
