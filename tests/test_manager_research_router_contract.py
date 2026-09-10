"""Frozen OpenAPI/runtime parity checks for the V4 manager research reader."""
from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from apps.api.v35_api.manager_research_router import create_manager_research_router


class _Service:
    def __init__(self) -> None:
        self.dates: list[str] = []

    def get(self, date: str) -> dict[str, object]:
        self.dates.append(date)
        return {"target_trade_date": date}

    def ensure_events(self, date: str, *, force: bool = False) -> dict[str, object]:
        self.dates.append(f"events:{date}:{force}")
        return {"target_trade_date": date, "status": "QUEUED"}


class _FailedEventService(_Service):
    def ensure_events(self, date: str, *, force: bool = False) -> dict[str, object]:
        self.dates.append(f"events:{date}:{force}")
        return {
            "schema_version": "v4.manager_research.product.v1",
            "kind": "MANAGER_RESEARCH",
            "target_trade_date": date,
            "stage_id": "STAGE_0935_0940",
            "market": "HK_CONNECT",
            "status": "CANNOT_CONFIRM",
            "product": {
                "status": "CANNOT_CONFIRM",
                "catalyst_coverage": {"event_count": 0, "all_sources_failed": True},
            },
            "job": {"status": "CANNOT_CONFIRM", "progress": {"event_rows": 0}},
            "cannot_confirm": ["ALL_EVENT_SOURCES_FAILED"],
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }


def _app() -> tuple[FastAPI, _Service]:
    service = _Service()
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    return app, service


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def _post(app: FastAPI, path: str, body: bytes = b"") -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, content=body)


def test_manager_research_date_is_required_in_openapi_and_runtime() -> None:
    app, service = _app()
    schema = app.openapi()
    for path in ("/api/v4/manager/research", "/api/v4/manager/research/status"):
        parameters = schema["paths"][path]["get"]["parameters"]
        date_parameter = next(item for item in parameters if item["name"] == "date")
        assert date_parameter["required"] is True

    omitted = asyncio.run(_get(app, "/api/v4/manager/research"))
    omitted_status = asyncio.run(_get(app, "/api/v4/manager/research/status"))
    assert omitted.status_code == 422
    assert omitted_status.status_code == 422
    assert service.dates == []


def test_manager_research_routes_keep_exact_date_semantics() -> None:
    app, service = _app()
    for path in (
        "/api/v4/manager/research?date=20260907",
        "/api/v4/manager/research/status?date=20260907",
    ):
        response = asyncio.run(_get(app, path))
        assert response.status_code == 200
        assert response.json() == {"target_trade_date": "20260907"}
    assert service.dates == ["20260907", "20260907"]


def test_manager_research_routes_reject_invalid_and_impossible_dates() -> None:
    app, service = _app()
    for value in ("2026-09-07", "20261301", "20260230"):
        response = asyncio.run(_get(app, f"/api/v4/manager/research?date={value}"))
        assert response.status_code == 422
    assert service.dates == []


def test_manager_research_event_refresh_is_exact_and_bodyless() -> None:
    app, service = _app()
    response = asyncio.run(_post(app, "/api/v4/manager/research/events?date=20260908"))
    assert response.status_code == 200
    assert response.json() == {"target_trade_date": "20260908", "status": "QUEUED"}
    assert service.dates == ["events:20260908:True"]

    rejected = asyncio.run(_post(app, "/api/v4/manager/research/events?date=20260908", b"{\"symbols\":[]}"))
    assert rejected.status_code == 422
    assert service.dates == ["events:20260908:True"]


def test_manager_research_event_refresh_preserves_source_outage_status() -> None:
    service = _FailedEventService()
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    response = asyncio.run(_post(app, "/api/v4/manager/research/events?date=20260908"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CANNOT_CONFIRM"
    assert body["product"]["catalyst_coverage"]["event_count"] == 0
    assert body["cannot_confirm"] == ["ALL_EVENT_SOURCES_FAILED"]
    assert service.dates == ["events:20260908:True"]
