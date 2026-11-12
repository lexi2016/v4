"""Research decision-desk (v3 research lane) adapter tests."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from apps.api.v4_api.research_lane_router import create_research_lane_router
from domains.research import build_research_archive
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.research_store import ResearchArchiveStore


def _write_lane_snapshot(root: Path, date: str, *, morning_status: str = "GENERATED_SNAPSHOT") -> Path:
    # Freeze the old producer-shaped input in the test only, then exercise the
    # same public normalization/publication path used by V4.  The router
    # must consume the owned archive, not the removed V3 module-root adapter.
    base_time = f"{date[:4]}-{date[4:6]}-{date[6:]}T08:30:00+08:00"
    timeline = [
        {
            "stock_code": "600970",
            "stock_name": "中材国际",
            "event_time": base_time,
            "source_published_at": base_time,
            "first_seen_at": base_time,
            "last_checked_at": base_time,
            "source_type": "research",
            "source_name": "research_feed",
            "source_title": "中材国际研究更新",
            "source_path": f"research/{date}/e1.json",
            "url": f"https://example.invalid/{date}/e1",
            "theme": "基建",
            "catalyst": "订单",
            "evidence_sentence": "研究证据一",
            "evidence_level": "L2_MEDIUM",
            "confidence": "MEDIUM",
            "dedup_key": f"{date}-e1",
        },
        {
            "stock_code": "600970",
            "stock_name": "中材国际",
            "event_time": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:31:00+08:00",
            "source_published_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:31:00+08:00",
            "first_seen_at": base_time,
            "last_checked_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:31:00+08:00",
            "source_type": "research",
            "source_name": "research_feed",
            "source_title": "中材国际研究更新二",
            "source_path": f"research/{date}/e2.json",
            "url": f"https://example.invalid/{date}/e2",
            "theme": "基建",
            "catalyst": "订单",
            "evidence_sentence": "研究证据二",
            "evidence_level": "L3_STRONG",
            "confidence": "HIGH",
            "dedup_key": f"{date}-e2",
        },
        {
            "stock_code": "000037",
            "stock_name": "深南电A",
            "event_time": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:32:00+08:00",
            "source_published_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:32:00+08:00",
            "first_seen_at": base_time,
            "last_checked_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T08:32:00+08:00",
            "source_type": "research",
            "source_name": "research_feed",
            "source_title": "深南电A研究更新",
            "source_path": f"research/{date}/e3.json",
            "url": f"https://example.invalid/{date}/e3",
            "theme": "电力",
            "catalyst": "供需",
            "evidence_sentence": "研究证据三",
            "evidence_level": "L2_MEDIUM",
            "confidence": "MEDIUM",
            "dedup_key": f"{date}-e3",
        },
    ]
    legacy = {
        "schema_version": "v3_research_lane.v2",
        "trade_date": date,
        "source_manifest": {"generated_at": base_time},
        "stock_research_daily": [
            {
                "stock_code": "600970",
                "stock_name": "中材国际",
                "first_seen_time": base_time,
                "last_seen_time": base_time,
                "research_score": 100,
                "research_status": "RESEARCH_ONLY",
                "evidence_count": 2,
                "source_count": 1,
                "strong_evidence_count": 1,
                "medium_evidence_count": 1,
                "weak_evidence_count": 0,
                "source_types": ["research"],
                "themes": ["基建"],
                "top_catalysts": ["订单"],
            },
            {
                "stock_code": "000037",
                "stock_name": "深南电A",
                "first_seen_time": base_time,
                "last_seen_time": base_time,
                "research_score": 90,
                "research_status": "RESEARCH_ONLY",
                "evidence_count": 1,
                "source_count": 1,
                "strong_evidence_count": 0,
                "medium_evidence_count": 1,
                "weak_evidence_count": 0,
                "source_types": ["research"],
                "themes": ["电力"],
                "top_catalysts": ["供需"],
            },
        ],
        "stock_research_timeline": timeline,
        "research_pool_bridge": [
            {"stock_code": "600970", "formal_overlap": True, "stage_overlap": True},
            {"stock_code": "000037", "formal_overlap": False, "stage_overlap": True},
        ],
        "cannot_confirm": [],
    }
    # Keep the parameter because callers use it to vary the fixture's producer
    # status; the owned archive deliberately carries only validated fields.
    assert morning_status
    archive = build_research_archive(legacy, source_input_sha256="a" * 64)
    published = ResearchArchiveStore(root).publish(archive, mode="LIVE")
    return root / published["payload_path"]


def _make_client(data_root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_research_lane_router(data_root))
    return TestClient(app)


def test_lane_reader_reads_owned_archive(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    source = ResearchLaneSource(data_root=tmp_path)
    payload, hourly_slot, hourly_count = source.read_exact_lane("20260804")
    assert payload is not None
    assert hourly_slot == ""
    assert hourly_count == 0
    assert payload["schema_version"] == "v3_5.research_archive.v1"
    assert payload["write_policy"] == "read_only"
    assert len(payload["stock_pool"]) == 2
    assert payload["article_count"] == 3


def test_lane_reader_rejects_unsafe_snapshot(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    target = tmp_path / "research" / "archives" / "20260804.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["write_policy"] = "read_write"
    target.write_text(json.dumps(payload), encoding="utf-8")
    source = ResearchLaneSource(data_root=tmp_path)
    with pytest.raises(ValueError, match="manifest or receipt mismatch"):
        source.read_exact_archive("20260804")


def test_lane_reader_rejects_traversal(tmp_path: Path) -> None:
    source = ResearchLaneSource(data_root=tmp_path)
    with pytest.raises(ValueError):
        source._resolve("../outside.json")


def test_lane_router_exact_date(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    client = _make_client(tmp_path)
    response = client.get("/api/v4/research/lane?research_date=20260804")
    assert response.status_code == 200
    body = response.json()
    assert body["research_date"] == "20260804"
    assert body["schema_version"] == "v3_5.research_lane.v1"
    assert body["endpoint_mode"] == "EXACT"
    assert len(body["stock_research_daily"]) == 2
    assert body["production_allowed"] is False


def test_lane_router_missing_date(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    client = _make_client(tmp_path)
    response = client.get("/api/v4/research/lane?research_date=20260901")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NOT_MATERIALIZED"
    assert body["reason"] == "RESEARCH_LANE_SNAPSHOT_NOT_FOUND"


def test_lane_router_invalid_date(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    response = client.get("/api/v4/research/lane?research_date=20261399")
    assert response.status_code == 422


def test_lane_router_latest_uses_newest(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260803")
    _write_lane_snapshot(tmp_path, "20260804")
    client = _make_client(tmp_path)
    response = client.get("/api/v4/research/lane")
    assert response.status_code == 200
    assert response.json()["research_date"] == "20260804"


def test_lane_dates_endpoint(tmp_path: Path) -> None:
    _write_lane_snapshot(tmp_path, "20260804")
    client = _make_client(tmp_path)
    response = client.get("/api/v4/research/dates")
    assert response.status_code == 200
    assert response.json()["research_dates"] == ["20260804"]


def _write_latest_event(root: Path) -> Path:
    target = root / "research_module" / "runtime_outputs" / "events"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "latest_research_event.json"
    path.write_text(json.dumps({
        "ok": True,
        "schema_version": "v3_5.research_event.v1",
        "module_id": "research_intelligence",
        "trade_date": "20260804",
        "event_id": "research:20260804:20260804230027-4961953b",
        "front_end_action": "reload_page_once",
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }), encoding="utf-8")
    return path


def test_latest_event_endpoint(tmp_path: Path) -> None:
    _write_latest_event(tmp_path)
    client = _make_client(tmp_path)
    response = client.get("/api/v4/research/latest-event")
    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == "research:20260804:20260804230027-4961953b"
    assert body["trade_date"] == "20260804"
    assert body["write_policy"] == "read_only"
    assert body["production_allowed"] is False


def test_latest_event_missing(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    response = client.get("/api/v4/research/latest-event")
    assert response.status_code == 200
    assert response.json()["status"] == "NO_RESEARCH_EVENT"


def test_events_stream_starts_and_emits_generation_event(tmp_path: Path) -> None:
    _write_latest_event(tmp_path)
    app = FastAPI()
    app.include_router(create_research_lane_router(tmp_path))

    collected = asyncio.run(_collect_sse(app))

    text = collected.decode("utf-8", errors="replace")
    assert ": connected" in text
    assert "id: research:20260804:20260804230027-4961953b" in text
    assert "event: research_generation_completed" in text
    assert '"production_allowed": false' in text or '"production_allowed":false' in text


async def _collect_sse(app: FastAPI) -> bytes:
    """Drive the SSE endpoint directly through ASGI.

    TestClient/httpx transports in current starlette wait for the infinite
    event-stream generator to finish, so they hang on this endpoint. Calling the
    app's ASGI interface directly lets us stop once the first generation event
    is observed.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "GET",
        "path": "/api/v4/research/events",
        "query_string": b"since=",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
        "scheme": "http",
    }
    body = bytearray()

    async def receive() -> dict:
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    try:
        await asyncio.wait_for(app(scope, receive, send), timeout=15)
    except asyncio.TimeoutError:
        pass
    return bytes(body)
