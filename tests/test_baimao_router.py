"""Tests for the V3.5 baimao X API."""
from __future__ import annotations

import json
from pathlib import Path

from apps.api.v35_api.baimao_router import create_baimao_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(v3_data_root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_baimao_router(Path("."), v3_data_root=v3_data_root))
    return TestClient(app)


def _write_digest(root: Path) -> Path:
    target = root / "baimao_x"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "latest_baimao_x_digest.json"
    path.write_text(json.dumps({
        "ok": True,
        "status": "READY",
        "headline": "白毛 X 测试头条",
        "focus_tags": ["机器人", "激光器"],
        "items": [{"title": "条目1"}, {"title": "条目2"}],
        "generated_at": "2026-08-04T20:00:00",
    }), encoding="utf-8")
    return path


def test_baimao_x_latest_returns_digest(tmp_path: Path) -> None:
    _write_digest(tmp_path)
    client = _make_client(tmp_path)
    response = client.get("/api/v3/baimao/x/latest")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["headline"] == "白毛 X 测试头条"
    assert len(body["items"]) == 2
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


def test_baimao_x_latest_missing(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    response = client.get("/api/v3/baimao/x/latest")
    assert response.status_code == 200
    assert response.json()["status"] == "NO_BAIMAO_X_DIGEST"


def test_baimao_x_latest_without_source() -> None:
    app = FastAPI()
    app.include_router(create_baimao_router(Path("."), v3_data_root=None))
    client = TestClient(app)
    response = client.get("/api/v3/baimao/x/latest")
    assert response.status_code == 200
    assert response.json()["status"] == "NO_V3_BAIMAO_SOURCE"
