from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import POOL_ORDER, PreselectionPoolStore


def _pool(trade_date: str, pool_id: str, rows: list[dict[str, object]]) -> dict[str, object]:
    market = "HK" if pool_id == "hkconnect_d1_top100" else "A"
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": market,
        "status": "available" if rows else "CANNOT_CONFIRM",
        "producer_id": "DATE_API_CONTRACT_TEST",
        "source_role": "RAW_SOURCE" if rows else "EXPECTED_MISSING",
        "source_path": f"fixtures/{pool_id}.json" if rows else "",
        "source_sha256": hashlib.sha256(pool_id.encode()).hexdigest(),
        "rows": rows,
        "cannot_confirm": [] if rows else ["EXPECTED_MISSING"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _store(tmp_path: Path) -> NativeDataStore:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": "20260818",
            "stage_dates": ["20260818"],
            "future_target_dates": [],
            "materialized_rows": {"20260818": 2},
        }
    )
    PreselectionPoolStore(store.root).materialize(
        _pool(
            "20260820",
            "a_d1_premarket_pool",
            [{"symbol": "A.000001", "market": "A", "recommendation_status": "WATCH_ONLY"}],
        )
    )
    return store


def test_explicit_target_date_stays_selected_and_partial_pools_remain_independent(tmp_path: Path) -> None:
    client = TestClient(create_app(data_root=_store(tmp_path).root, current_date="20260820"))

    date_response = client.get("/api/v1/runs/date-list", params={"date": "20260820"})
    assert date_response.status_code == 200
    date_payload = date_response.json()
    assert date_payload["system_date"] == "20260820"
    assert date_payload["default_date"] == "20260818"
    assert date_payload["requested_date"] == "20260820"
    assert date_payload["selected_date"] == "20260820"
    assert "20260820" in date_payload["future_target_dates"]

    pool_response = client.get(
        "/api/v3/preselection-pools",
        params={"date": "20260820", "limit": 200},
    )
    assert pool_response.status_code == 200
    payload = pool_response.json()
    assert payload["trade_date"] == "20260820"
    assert payload["selected_date"] == "20260820"
    assert payload["data_status"] == "PARTIAL_WITH_ROWS"
    assert payload["row_count"] == 1
    assert [pool["pool_id"] for pool in payload["pools"]] == list(POOL_ORDER)
    assert {row["symbol"] for row in payload["a_all_pool_rows"]} == {"A.000001"}
    missing = [pool for pool in payload["pools"] if pool["pool_id"] != "a_d1_premarket_pool"]
    assert len(missing) == 6
    assert all(pool["status"] == "CANNOT_CONFIRM" for pool in missing)
    assert payload["market_totals"] == {"A": 1, "HK": 0}
    assert all(
        pool[flag] is False
        for pool in payload["pools"]
        for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
    )
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False

def test_explicit_missing_target_date_does_not_fall_back_to_previous_date(tmp_path: Path) -> None:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": "20260818",
            "stage_dates": ["20260818"],
            "future_target_dates": [],
            "materialized_rows": {"20260818": 2},
        }
    )
    client = TestClient(create_app(data_root=store.root, current_date="20260820"))

    response = client.get("/api/v3/preselection-pools", params={"date": "20260820"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["trade_date"] == "20260820"
    assert payload["data_status"] == "DATA_BLOCKED_EMPTY"
    assert payload["pools"] == []
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
