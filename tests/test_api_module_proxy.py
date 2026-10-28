from __future__ import annotations

import asyncio

from fastapi import FastAPI
import httpx
import pytest

from apps.api.v35_api.module_proxy import (
    ModuleProxyMiddleware,
    _owned_routes,
    configure_module_role,
    load_module_contract,
)


CONTRACT = load_module_contract()


def test_contract_has_frozen_stage_and_manager_route_ownership() -> None:
    stage = _owned_routes(CONTRACT, "stage")
    manager = _owned_routes(CONTRACT, "manager")
    assert len(stage) == 6
    assert len(manager) == 19
    assert {route["path"] for route in manager if route["path"].startswith("/api/v4/manager/research")} == {
        "/api/v4/manager/research",
        "/api/v4/manager/research/status",
        "/api/v4/manager/research/ensure",
        "/api/v4/manager/research/retry",
        "/api/v4/manager/research/events",
        "/api/v4/manager/research/jobs/{job_id}",
        "/api/v4/manager/research/jobs/{job_id}/cancel",
        "/api/v4/manager/research/catalyst-observations",
        "/api/v4/manager/research/catalyst-observations/refresh",
        "/api/v4/manager/research/workspace",
        "/api/v4/manager/research/workspace/refresh",
        "/api/v4/manager/research/workspace/scheduled-cycle",
        "/api/v4/manager/research/announcements",
        "/api/v4/manager/research/announcements/analysis",
        "/api/v4/manager/research/announcements/analysis/import",
        "/api/v4/manager/research/announcements/refresh",
        "/api/v4/manager/research/{target_trade_date}",
    }


def _role_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v3/meta/stages")
    def stages() -> dict[str, str]:
        return {"owner": "stage"}

    @app.get("/api/v4/manager/research")
    def manager() -> dict[str, str]:
        return {"owner": "manager"}

    @app.get("/api/v3/runtime/workloads")
    def platform() -> dict[str, str]:
        return {"owner": "platform"}

    return app


async def _request(app: FastAPI, method: str, url: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, url)


@pytest.mark.parametrize(
    ("role", "own_path", "foreign_path"),
    [
        ("stage", "/api/v3/meta/stages", "/api/v4/manager/research"),
        ("manager", "/api/v4/manager/research", "/api/v3/meta/stages"),
    ],
)
def test_backend_role_keeps_only_its_routes(role: str, own_path: str, foreign_path: str) -> None:
    app = configure_module_role(_role_app(), role)
    own = asyncio.run(_request(app, "GET", own_path))
    foreign = asyncio.run(_request(app, "GET", foreign_path))
    platform = asyncio.run(_request(app, "GET", "/api/v3/runtime/workloads"))
    health = asyncio.run(_request(app, "GET", "/healthz"))
    assert own.status_code == 200
    assert foreign.status_code == 404
    assert platform.status_code == 404
    assert health.status_code == 200


class _ProxyReply:
    status_code = 207
    content = b"backend-payload"
    headers = httpx.Headers([
        ("content-type", "application/vnd.v4+json"),
        ("x-required", "preserved"),
        ("connection", "x-internal"),
        ("x-internal", "removed"),
    ])


class _ProxyClient:
    calls: list[tuple[str, str, bytes, dict[str, str]]]

    def __init__(self, *, timeout: httpx.Timeout, trust_env: bool) -> None:
        assert trust_env is False
        self.timeout = timeout

    async def __aenter__(self) -> "_ProxyClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def request(self, method: str, url: str, *, headers: object, content: bytes) -> _ProxyReply:
        self.calls.append((method, url, content, dict(headers)))
        return _ProxyReply()


def test_gateway_proxies_contract_request_and_filters_hop_by_hop_headers() -> None:
    _ProxyClient.calls = []
    app = FastAPI()

    @app.get("/api/v3/meta/stages")
    def legacy_handler() -> dict[str, str]:
        return {"owner": "legacy"}

    app.add_middleware(ModuleProxyMiddleware, contract=CONTRACT, client_factory=_ProxyClient)
    response = asyncio.run(_request(app, "GET", "/api/v3/meta/stages?date=20261009"))
    assert response.status_code == 207
    assert response.content == b"backend-payload"
    assert response.headers["content-type"] == "application/vnd.v4+json"
    assert response.headers["x-required"] == "preserved"
    assert "x-internal" not in response.headers
    assert len(_ProxyClient.calls) == 1
    method, url, body, headers = _ProxyClient.calls[0]
    assert method == "GET"
    assert url == "http://127.0.0.1:8874/api/v3/meta/stages?date=20261009"
    assert body == b""
    assert "host" not in headers


class _NoCallClient:
    def __init__(self, **kwargs: object) -> None:
        raise AssertionError("invalid routes must be rejected before proxying")


def test_gateway_rejects_wrong_methods_and_unknown_module_paths_without_fallback() -> None:
    app = FastAPI()

    @app.get("/api/v3/meta/stages")
    def legacy_handler() -> dict[str, str]:
        return {"owner": "legacy"}

    @app.get("/api/v4/manager/research/unlisted/action")
    def legacy_manager_handler() -> dict[str, str]:
        return {"owner": "legacy"}

    app.add_middleware(ModuleProxyMiddleware, contract=CONTRACT, client_factory=_NoCallClient)
    wrong_method = asyncio.run(_request(app, "POST", "/api/v3/meta/stages"))
    unknown = asyncio.run(_request(app, "GET", "/api/v4/manager/research/unlisted/action"))
    assert wrong_method.status_code == 405
    assert wrong_method.headers["allow"] == "GET"
    assert unknown.status_code == 404


@pytest.mark.parametrize(
    ("error", "expected"),
    [(httpx.ConnectError("offline"), 503), (httpx.ConnectTimeout("timeout"), 504)],
)
def test_gateway_maps_unavailable_backend_without_fallback(error: Exception, expected: int) -> None:
    class _FailingClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_FailingClient":
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def request(self, *args: object, **kwargs: object) -> None:
            raise error

    app = FastAPI()

    @app.get("/api/v3/meta/stages")
    def legacy_handler() -> dict[str, str]:
        return {"owner": "legacy"}

    app.add_middleware(ModuleProxyMiddleware, contract=CONTRACT, client_factory=_FailingClient)
    response = asyncio.run(_request(app, "GET", "/api/v3/meta/stages"))
    assert response.status_code == expected
