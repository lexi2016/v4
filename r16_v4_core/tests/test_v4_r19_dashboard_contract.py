"""Compatibility for the unmodified static Dashboard entry."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4_core.api.routes_top200 import build_top200_router
from v4_core.api.routes_workbench import build_workbench_router
from v4_core.storage.db import V4Store


BASE = "/api/v4/research/workbench"


def test_dashboard_empty_history_and_missing_day_are_distinct(tmp_path):
    store = V4Store(tmp_path / "workbench.sqlite3")
    app = FastAPI()
    app.include_router(build_workbench_router(store))
    with TestClient(app) as client:
        history = client.get(f"{BASE}/history").json()
        schedule = client.get(f"{BASE}/workflow-contract").json()
        missing = client.get(f"{BASE}/days/2026-11-24")

    assert history == {"dates": [], "rows": [], "count": 0, "days": []}
    assert schedule["slot_count"] == 6
    assert schedule["visual_stages"] == []
    assert schedule["time_contract"] == {"nodes": [], "status": "CANNOT_CONFIRM"}
    assert all(row["execution_ref"] is None for row in schedule["rows"])
    assert missing.status_code == 404


def test_dashboard_catalog_resolves_two_exact_days_without_inferring_formula_groups(tmp_path):
    store = V4Store(tmp_path / "workbench.sqlite3")
    days = {"2026-11-24": "000001.SZ", "2026-11-25": "000002.SZ"}
    for day, symbol in days.items():
        store.save_workbench_scores(day, [{
            "trade_date": day, "symbol": symbol, "selection_group": "192",
            "rule_version": "a_share_kb_hold_score_v1", "score": 50,
            "action": "WATCH", "status": "READY", "detail_json": "{}",
        }])
    app = FastAPI()
    app.include_router(build_workbench_router(store))
    with TestClient(app) as client:
        history = client.get(f"{BASE}/history").json()
        assert history["dates"] == ["2026-11-25", "2026-11-24"]
        assert history["rows"] == [{"source_date": day} for day in history["dates"]]
        assert [entry["observation_date"] for entry in history["days"]] == ["2026-11-26", "2026-11-25"]

        for entry in history["days"]:
            day = entry["source_date"]
            result = client.get(f"{BASE}/days/{day}", params={"revision": entry["revision"]}).json()
            assert result["source_date"] == day
            assert result["observation_date"] == entry["observation_date"]
            assert result["revision"] == entry["revision"]
            assert result["schema"] == "RESEARCH_SYSTEM_DAY_V1"
            assert result["scope_count"] == result["count"] == 1
            assert result["rows"][0]["symbol"] == days[day]
            assert result["formula_groups"]["192"] == 1
            assert result["formula_groups"]["group_counts"] == {"b23_entry": None, "pb2_confirm": None}
            assert result["formula_groups"]["status"] == "CANNOT_CONFIRM_NOT_MATERIALIZED"
            assert result["formula_review"] == "PENDING"
            assert result["chart_review"] == "UNKNOWN_NOT_REVIEWED"
            assert result["materials"] == result["reference_links"] == []
            assert all(slot["status"] == "NOT_MATERIALIZED" for slot in result["workflow"])


def test_dashboard_top200_flags_and_rows_are_bound_to_exact_source_dates(tmp_path):
    store = V4Store(tmp_path / "top200.sqlite3")
    supplied = {"2026-11-25": "000001.SZ", "2026-11-26": "000002.SZ"}
    for day, symbol in supplied.items():
        store.save_top200(day, [{
            "trade_date": day, "rank": 1, "symbol": symbol, "name": symbol,
            "close": 8.5, "pct_chg": 3.25, "amount": 1_248.50,
            "daily_gain_rank_eligibility": "eligible", "historical_pit": 0,
        }])
    app = FastAPI()
    app.include_router(build_top200_router(store))
    with TestClient(app) as client:
        for day, symbol in supplied.items():
            response = client.get(f"{BASE}/days/{day}/top200")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "PARTIAL_DESCRIPTIVE"
            assert body["source_date"] == day
            assert body["data_date"] == day.replace("-", "")
            assert body["top200_count"] == 1
            assert body["top200"] == [{
                "source_date": day, "rank": 1, "symbol": symbol, "name": symbol,
                "close": 8.5, "change_pct": 3.25, "amount_cny": 1_248.50,
                "daily_gain_rank_eligibility": True,
            }]
            assert body["RESEARCH_ONLY"] is True
            for flag in ("production_allowed", "buy_gate_updated", "orders_sent", "historical_PIT"):
                assert body[flag] is False
            assert body["coverage_counts_status"] == "CANNOT_CONFIRM"
            for key in ("directory_count", "valid_quote_count", "missing_quote_count"):
                assert body[key] == "待确认"
        assert client.get(f"{BASE}/days/2026-11-24/top200").status_code == 404
