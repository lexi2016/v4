"""Date-list compatibility on an isolated r19 store."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4_core.api.routes_review import build_review_router
from v4_core.storage.db import V4Store


URL = "/api/v1/runs/date-list"
UNBOUND_LISTS = (
    "hk_observation_only_dates", "materialized", "partial", "blocked",
    "materialized_stage_dates", "partial_stage_dates", "blocked_stage_dates",
)


@pytest.fixture
def catalog(tmp_path):
    store = V4Store(tmp_path / "catalog.sqlite3")
    app = FastAPI()
    app.include_router(build_review_router(store))
    with TestClient(app) as client:
        yield client, store


def test_empty_catalog_supplies_required_lists_without_claiming_availability(catalog):
    client, _ = catalog
    shanghai = ZoneInfo("Asia/Shanghai")
    before = datetime.now(shanghai).strftime("%Y%m%d")
    body = client.get(URL).json()
    after = datetime.now(shanghai).strftime("%Y%m%d")

    for key in ("dates", "stage_navigation_dates", "stage_dates", "future_target_dates",
                "review_dates", "research_dates", *UNBOUND_LISTS):
        assert body[key] == [], key
    assert body["ok"] is True
    assert body["count"] == 0 and body["latest_date"] is None and body["default_date"] == ""
    assert body["status"] == "EMPTY"
    assert body["navigation_timezone"] == "Asia/Shanghai"
    assert body["navigation_policy"] == "SHANGHAI_CIVIL_DATE_NOT_EXCHANGE_CALENDAR"
    assert body["system_date"] in {before, after}
    assert body["navigation_date"] == body["system_date"] == body["selected_date"]
    assert body["requested_date"] is None
    assert body["runtime_identity"]["status"] == "CANNOT_CONFIRM"
    assert body["research_source"]["status"] == "EMPTY"


def test_exact_evidence_dates_and_legacy_research_navigation(catalog):
    client, store = catalog
    for day in ("2026-02-05", "20260205"):
        store.upsert_stage_selections([{"trade_date": day, "stage": "STAGE_0925", "symbol": "000001"}])
    store.upsert_stage_selections([{"trade_date": "2026-02-06", "stage": "STAGE_0925", "symbol": "000002", "status": "CANNOT_CONFIRM"}])
    store.save_review_record("2026-02-06", "GENERATED", {})
    store.upsert_research_materials([{"trade_date": "2026-02-07", "record_id": "weekend", "source_type": "article"}])
    store.log_task_run("attempt", "2026-02-08", "slot", "FAILED", {})
    store.log_task_run("invalid", "2026-02-30", "slot", "FAILED", {})
    store.upsert_preselection_pools([
        {"trade_date": "2099-03-02", "pool_name": "test", "symbol": "000001"},
        {"trade_date": "2099-03-03", "pool_name": "test", "symbol": "000001", "status": "CANNOT_CONFIRM"},
    ])

    body = client.get(URL, params={"date": "20260203"}).json()

    assert body["dates"] == ["20990303", "20990302", "20260208", "20260207", "20260206", "20260205"]
    assert body["stage_navigation_dates"] == ["20990302", "20260206", "20260205"]
    assert body["count"] == len(body["dates"])
    assert body["stage_dates"] == ["20260205"]
    assert body["future_target_dates"] == ["20990302"]
    assert body["review_dates"] == ["20260206"]
    assert body["research_dates"] == ["20260207"]
    assert body["default_date"] == "20260207"
    assert body["requested_date"] == body["selected_date"] == "20260203"
    for key in UNBOUND_LISTS:
        assert body[key] == [], key


def test_research_only_weekend_remains_available_to_legacy_command(catalog):
    client, store = catalog
    store.upsert_research_materials([{"trade_date": "2026-02-07", "record_id": "weekend", "source_type": "article"}])

    body = client.get(URL).json()

    assert body["dates"] == body["research_dates"] == ["20260207"]
    assert body["default_date"] == body["latest_date"] == "20260207"
    assert body["stage_navigation_dates"] == body["stage_dates"] == []


@pytest.mark.parametrize("requested", ["2026-02-05", "20260230", "", "2026025", "2026-W05-1"])
def test_invalid_explicit_date_returns_422(catalog, requested):
    client, _ = catalog
    assert client.get(URL, params={"date": requested}).status_code == 422
