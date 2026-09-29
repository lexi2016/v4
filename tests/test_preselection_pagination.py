from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import POOL_ORDER, PreselectionPoolStore

DATE = "20260907"


def _artifact(date: str, pool_id: str, rows: list[dict], market: str) -> dict:
    normalized = [
        {
            **row,
            "pool_id": pool_id,
            "pool_rank": rank,
            "recommendation_status": "WATCH_ONLY",
            "signal_date": date,
            "target_date": date,
        }
        for rank, row in enumerate(rows, start=1)
    ]
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": date,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": market,
        "status": "READY" if normalized else "CANNOT_CONFIRM",
        "producer_id": "B01_pagination_fixture",
        "source_role": "RAW_SOURCE" if normalized else "EXPECTED_MISSING",
        "source_path": f"fixture/{date}/{pool_id}.json" if normalized else "",
        "source_sha256": hashlib.sha256(f"{date}:{pool_id}".encode()).hexdigest(),
        "rows": normalized,
        "cannot_confirm": [] if normalized else [f"EXPECTED_MISSING:{pool_id}"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _materialize_fixture(store: NativeDataStore, date: str) -> None:
    main = [{"symbol": f"A.{index:06d}", "market": "A"} for index in range(415)]
    research = [
        {"symbol": f"A.{index:06d}", "market": "A"}
        for index in [*range(238), *range(415, 452)]
    ]
    pools = {
        "a_d1_premarket_pool": (main, "A"),
        "a_share_research_recommendation_pool": (research, "A"),
        "hkconnect_d1_top100": (
            [{"symbol": f"HK.{index:05d}", "market": "HK"} for index in range(100)],
            "HK",
        ),
        "a_d1_fupan_watchlist_pool": ([], "A"),
        "a_d1_stage7_fenshi_review_pool": ([], "A"),
        "a_share_baimao_research_map": ([], "A"),
        "wechat_public_account_v3_preselect": ([], "WECHAT"),
    }
    pool_store = PreselectionPoolStore(store.root)
    for pool_id in POOL_ORDER:
        rows, market = pools[pool_id]
        pool_store.materialize(_artifact(date, pool_id, rows, market))


def _client(tmp_path: Path) -> TestClient:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": DATE,
            "stage_dates": [DATE],
            "future_target_dates": [],
            "materialized_rows": {DATE: 452},
        }
    )
    _materialize_fixture(store, DATE)
    return TestClient(create_app(data_root=store.root))


def test_b01_pages_reach_452_415_275_without_duplicate_rows(tmp_path: Path) -> None:
    client = _client(tmp_path)
    all_pages: list[dict] = []
    all_codes: list[str] = []
    unified_codes: list[str] = []
    research_codes: list[str] = []
    expected_page_lengths = [(200, 200, 200), (200, 200, 75), (52, 15, 0)]

    for offset, expected in zip((0, 200, 400), expected_page_lengths):
        response = client.get(
            "/api/v3/preselection-pools",
            params={"date": DATE, "limit": 200, "offset": offset},
        )
        assert response.status_code == 200
        body = response.json()
        all_pages.append(body)
        pools = {pool["pool_id"]: pool for pool in body["pools"]}

        assert body["trade_date"] == DATE
        assert body["a_all_pool_row_count"] == 452
        assert body["unified_row_count"] == 415
        assert body["pagination"]["offset"] == offset
        assert len(body["a_all_pool_rows"]) == expected[0]
        assert len(body["unified_rows"]) == expected[1]
        assert len(pools["a_share_research_recommendation_pool"]["rows"]) == expected[2]
        assert pools["a_share_research_recommendation_pool"]["pool_size"] == 275
        assert pools["a_share_research_recommendation_pool"]["returned_rows"] == expected[2]
        assert pools["a_d1_premarket_pool"]["pool_size"] == 415
        assert pools["a_d1_premarket_pool"]["returned_rows"] == expected[1]
        assert pools["a_d1_premarket_pool"]["complete"] is (offset == 400)
        assert body["a_all_pool_complete"] is (offset == 400)

        all_codes.extend(row["symbol"] for row in body["a_all_pool_rows"])
        unified_codes.extend(row["symbol"] for row in body["unified_rows"])
        research_codes.extend(
            row["symbol"]
            for row in pools["a_share_research_recommendation_pool"]["rows"]
        )

    assert len(all_codes) == 452
    assert len(set(all_codes)) == 452
    assert len(unified_codes) == 415
    assert len(set(unified_codes)) == 415
    assert len(research_codes) == 275
    assert len(set(research_codes)) == 275
    assert all_pages[0]["pagination"]["next_offset"] == 200
    assert all_pages[1]["pagination"]["next_offset"] == 400
    assert all_pages[2]["pagination"]["next_offset"] is None
    assert all_pages[2]["pagination"]["has_more"] is False

    page_two = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 200, "page": 2},
    ).json()
    assert [row["symbol"] for row in page_two["a_all_pool_rows"]] == [
        row["symbol"] for row in all_pages[1]["a_all_pool_rows"]
    ]


def test_b01_empty_cannot_confirm_pool_is_not_complete_and_date_is_bound(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = client.get(
        "/api/v3/preselection-pools",
        params={"date": DATE, "limit": 200},
    ).json()
    pools = {pool["pool_id"]: pool for pool in body["pools"]}

    missing = pools["a_share_baimao_research_map"]
    assert missing["status"] == "CANNOT_CONFIRM"
    assert missing["rows"] == []
    assert missing["pool_size"] == 0
    assert missing["returned_rows"] == 0
    assert missing["complete"] is False
    assert missing["has_more"] is False
    assert missing["cannot_confirm"]

    for pool in pools.values():
        for row in pool["rows"]:
            assert row["signal_date"] == DATE
            assert row["target_date"] == DATE
    assert body["trade_date"] == DATE
    assert body["selected_date"] == DATE
    assert body["requested_date"] == DATE
