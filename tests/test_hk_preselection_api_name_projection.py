from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api import preselection_service
from apps.api.v35_api.preselection_router import create_preselection_router
from apps.api.v35_api.preselection_service import PreselectionPoolService


OLD_NAME = "帝王国际投资"


@pytest.mark.parametrize(
    ("trade_date", "expected_name", "expected_status"),
    [
        ("20261012", "云迹", "EFFECTIVE_DATE_OVERRIDE"),
        ("20261030", OLD_NAME, "SOURCE_NAME_AFTER_EFFECTIVE_WINDOW"),
    ],
)
def test_preselection_http_service_projects_only_dated_hk_display_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    trade_date: str,
    expected_name: str,
    expected_status: str,
) -> None:
    hk_row = {
        "symbol": "HK.02915",
        "code": "HK.02915",
        "market": "HK",
        "pool_id": "hkconnect_d1_top100",
        "pool_rank": 1,
        "rank": "1",
        "name": OLD_NAME,
        "stock_name": OLD_NAME,
        "trade_date": trade_date,
        "target_date": trade_date,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    a_row = {
        "symbol": "A.002915",
        "code": "002915",
        "market": "A",
        "pool_id": "a_d1_premarket_pool",
        "pool_rank": 1,
        "name": OLD_NAME,
        "stock_name": OLD_NAME,
        "trade_date": trade_date,
        "target_date": trade_date,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    source_response = {
        "ok": True,
        "data_status": "PARTIAL_WITH_ROWS",
        "trade_date": trade_date,
        "pools": [
            {"pool_id": "hkconnect_d1_top100", "market": "HK", "rows": [deepcopy(hk_row)]},
            {"pool_id": "a_d1_premarket_pool", "market": "A", "rows": [deepcopy(a_row)]},
        ],
        "rows": [deepcopy(hk_row), deepcopy(a_row)],
        "unified_rows": [deepcopy(hk_row), deepcopy(a_row)],
        "a_source_only_rows": [deepcopy(a_row)],
        "a_all_pool_rows": [deepcopy(a_row)],
        "input_fingerprint": "frozen-input-fingerprint",
        "source_digests": {"hkconnect_d1_top100": "frozen-source-sha"},
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }

    def read_materialized_pools(*_args, **_kwargs):
        return deepcopy(source_response)

    monkeypatch.setattr(preselection_service, "preselection", read_materialized_pools)
    service = PreselectionPoolService(
        SimpleNamespace(root=tmp_path),
        configured_pool_source=False,
        resolved_pool_source=tmp_path,
    )
    app = FastAPI()
    app.include_router(
        create_preselection_router(
            service,
            get_catalog=lambda: {"default_date": trade_date, "system_date": trade_date},
            validate_date=lambda value: value,
        )
    )

    response = TestClient(app).get(
        "/api/v3/preselection-pools",
        params={"date": trade_date, "limit": 200, "offset": 0},
    )

    assert response.status_code == 200
    body = response.json()
    hk_pool_row = body["pools"][0]["rows"][0]
    for row in (hk_pool_row, body["rows"][0], body["unified_rows"][0]):
        assert row["name"] == row["stock_name"] == expected_name
        assert row["raw_name"] == OLD_NAME
        assert row["name_resolution"]["status"] == expected_status
        assert (row["symbol"], row["pool_rank"]) == ("HK.02915", 1)

    # A-share projections must not receive an HK counter-name overlay.
    assert body["a_source_only_rows"][0]["name"] == OLD_NAME
    assert body["a_all_pool_rows"][0]["stock_name"] == OLD_NAME
    assert body["pools"][1]["rows"][0]["name"] == OLD_NAME
    assert body["input_fingerprint"] == "frozen-input-fingerprint"
    assert body["source_digests"] == {"hkconnect_d1_top100": "frozen-source-sha"}
    assert source_response["pools"][0]["rows"][0]["name"] == OLD_NAME
