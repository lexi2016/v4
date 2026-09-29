from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import httpx
from fastapi import FastAPI

# The release test image carries httpx under its normal name while the pinned
# Starlette test client imports the compatibility name.  Keep this test
# portable without changing production dependency resolution.
sys.modules.setdefault("httpx2", httpx)

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from apps.api.v35_api import research_lane_router as research_router_module
from apps.api.v35_api.research_lane_router import create_research_lane_router
from domains.preselection import date_catalog
from infrastructure.data_store import NativeDataStore


def _catalog(store: NativeDataStore, system_date: str = "20260818") -> None:
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": system_date,
            "stage_dates": [],
            "future_target_dates": [],
            "materialized_rows": {},
        }
    )


def _flat_payload(date: str) -> dict[str, object]:
    row = {"symbol": "A.000001", "market": "A", "recommendation_status": "WATCH_ONLY"}
    return {
        "schema_version": "v3_preselection_pools.v1",
        "trade_date": date,
        "producer_status": "CANONICAL_COMPLETE",
        "data_status": "READY_WITH_ROWS",
        "module_id": "unified_preselection_pools",
        "write_policy": "read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
        "canonical_main_pool_confirmed": True,
        "source_lane": "CANONICAL_MAIN",
        "selector_status": "READY",
        "strict_0_2_status": "STRICT_0_2_READY",
        "pools": [{"pool_id": "main", "rows": [row]}],
        "rows": [row],
        "unified_rows": [row],
        "a_source_only_rows": [],
        "a_all_pool_rows": [row],
        "startup_ensure": {},
        "evidence_paths": ["legacy/flat.json"],
        "cannot_confirm": [],
    }


def test_create_app_uses_one_current_date_source_for_runtime_status(tmp_path: Path) -> None:
    store = NativeDataStore(tmp_path / "data")
    _catalog(store)
    client = TestClient(
        create_app(
            data_root=store.root,
            current_date="20260820",
            stage_center_selection_root=tmp_path / "selection",
        )
    )

    dates = client.get("/api/v1/runs/date-list").json()
    status = client.get("/api/v3/tasks/status").json()

    assert dates["system_date"] == "20260820"
    assert dates["selected_date"] == "20260820"
    assert status["business_date"] == "20260820"


def test_current_preselection_api_never_projects_native_flat_payload(tmp_path: Path) -> None:
    store = NativeDataStore(tmp_path / "data")
    _catalog(store)
    store.import_payload(_flat_payload("20260818"))
    client = TestClient(create_app(data_root=store.root, current_date="20260820"))

    response = client.get("/api/v3/preselection-pools", params={"date": "20260818"})

    assert response.status_code == 200
    body = response.json()
    assert body["data_status"] == "DATA_BLOCKED_EMPTY"
    assert body["trade_date"] == "20260818"
    assert body["row_count"] == 0


def _write_research_snapshot(root: Path, date: str) -> None:
    target = root / "runtime_outputs" / "latest" / date
    target.mkdir(parents=True, exist_ok=True)
    target.joinpath("research_lane_snapshot.json").write_text(
        json.dumps(
            {
                "ok": True,
                "schema_version": "v3_research_lane.v2",
                "trade_date": date,
                "module_id": "research_intelligence",
                "write_policy": "read_only",
                "default_status": "RESEARCH_ONLY",
                "buy_gate_effect": "none",
                "live_order_effect": "none",
                "research_quality_summary": {"stock_daily_count": 0},
                "stock_research_daily": [],
                "stock_research_timeline": [],
                "research_pool_bridge": [],
                "morning_news": {"status": "NOT_MATERIALIZED", "articles": [], "articles_count": 0},
                "news_workbench": {"schema_version": "x", "status": "ok", "action_rows": []},
                "hourly_research": {"schema_version": "x", "latest_slot": "0800", "status": "ok"},
                "source_manifest": {"generated_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T00:00:00+08:00"},
                "cannot_confirm": [],
            }
        ),
        encoding="utf-8",
    )


def _research_client(root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    class FixtureResearchSource:
        def __init__(self, source_root: Path, *, ledger_root: Path | None = None) -> None:
            self.root = source_root
            self.ledger_root = ledger_root
            from infrastructure.research_lane_source import ResearchLaneSource
            self._diagnostic_source = ResearchLaneSource(source_root, ledger_root=ledger_root)

        def update_diagnostic(self, research_date: str, *, artifact_verified: bool):
            return self._diagnostic_source.update_diagnostic(
                research_date, artifact_verified=artifact_verified,
            )

        def _read(self, date: str) -> dict[str, object] | None:
            path = self.root / "runtime_outputs" / "latest" / date / "research_lane_snapshot.json"
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

        def read_latest_lane(self):
            return None, None, 0

        def read_exact_lane(self, date: str):
            return self._read(date), None, 0

        def read_status_lane(self, _date: str):
            return None

        def list_dates(self):
            return ["20260804"]

        def today_date(self):
            return "20260820"

    monkeypatch.setattr(research_router_module, "ResearchLaneSource", FixtureResearchSource)
    app = FastAPI()
    app.include_router(create_research_lane_router(root))
    return TestClient(app)


def test_research_date_alias_is_exact_and_conflicts_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _research_client(tmp_path, monkeypatch)

    alias = client.get("/api/v3/research/lane?date=20260804")
    missing = client.get("/api/v3/research/lane?date=20260901")
    conflict = client.get("/api/v3/research/lane?research_date=20260804&date=20260805")

    assert alias.status_code == 200
    assert alias.json()["research_date"] == "20260804"
    assert alias.json()["research_date"] == "20260804"
    assert missing.status_code == 200
    assert missing.json()["status"] == "NOT_MATERIALIZED"
    assert missing.json()["research_date"] == "20260901"
    assert conflict.status_code == 422


def test_date_catalog_navigation_includes_wall_trading_day_without_promoting_evidence(
    tmp_path: Path,
) -> None:
    store = NativeDataStore(tmp_path / "data")
    _catalog(store)

    catalog = date_catalog(store, current_date="20260820")

    assert catalog["system_date"] == "20260820"
    assert catalog["dates"] == ["20260820"]
    assert catalog["stage_dates"] == []
    assert catalog["default_date"] == ""
