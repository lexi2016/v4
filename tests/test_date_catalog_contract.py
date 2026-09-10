from __future__ import annotations

import hashlib
from pathlib import Path

from domains.preselection import date_catalog
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import PreselectionPoolStore


def _pool(trade_date: str, pool_id: str, rows: list[dict[str, object]]) -> dict[str, object]:
    market = "HK" if pool_id == "hkconnect_d1_top100" else "A"
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": market,
        "status": "available" if rows else "CANNOT_CONFIRM",
        "producer_id": "DATE_CONTRACT_TEST",
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
    return store


def test_catalog_uses_wall_date_and_any_verified_target_pool(tmp_path: Path) -> None:
    store = _store(tmp_path)
    PreselectionPoolStore(store.root).materialize(
        _pool(
            "20260820",
            "a_d1_premarket_pool",
            [{"symbol": "A.000001", "market": "A", "recommendation_status": "WATCH_ONLY"}],
        )
    )

    catalog = date_catalog(store, current_date="20260820")

    assert catalog["system_date"] == "20260820"
    assert catalog["default_date"] == "20260818"
    assert "20260820" in catalog["future_target_dates"]
    assert catalog["dates"] == ["20260820", "20260818"]


def test_catalog_keeps_target_date_when_other_pool_families_are_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    pool_store = PreselectionPoolStore(store.root)
    pool_store.materialize(
        _pool(
            "20260820",
            "a_d1_premarket_pool",
            [{"symbol": "A.000001", "market": "A", "recommendation_status": "WATCH_ONLY"}],
        )
    )
    pool_store.materialize(
        _pool(
            "20260820",
            "a_d1_fupan_watchlist_pool",
            [
                {"symbol": "A.000001", "market": "A", "recommendation_status": "WATCH_ONLY"},
                {"symbol": "A.000002", "market": "A", "recommendation_status": "WATCH_ONLY"},
            ],
        )
    )
    pool_store.materialize(
        _pool(
            "20260820",
            "hkconnect_d1_top100",
            [{"symbol": "HK.00001", "market": "HK", "recommendation_status": "WATCH_ONLY"}],
        )
    )

    catalog = date_catalog(store, current_date="20260820")

    assert catalog["system_date"] == "20260820"
    assert catalog["default_date"] == "20260818"
    assert "20260820" in catalog["future_target_dates"]
    assert catalog["dates"] == ["20260820", "20260818"]
