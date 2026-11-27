"""Stage shell timeline compatibility and exact-date evidence boundaries."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4_core.api.routes_stage import build_stage_router
from v4_core.storage.db import V4Store


def test_stage_timeline_projects_keyed_date_bound_summaries(tmp_path):
    store = V4Store(tmp_path / "stage.sqlite3")
    opening = "STAGE_0930_0935"
    auction = "STAGE_0925"
    requested = [opening, auction]
    store.upsert_stage_selections([
        {"trade_date": "2026-11-25", "stage": opening, "market": "A", "symbol": "SZ.000001"},
        {"trade_date": "2026-11-26", "stage": opening, "market": "HK", "symbol": "HK.00001"},
    ])
    app = FastAPI()
    app.include_router(build_stage_router(store))

    with TestClient(app) as client:
        for day, market, other in (("20261125", "A", "HK"), ("20261126", "HK", "A")):
            response = client.get("/api/v4/workbench/stage-batch", params={"date": day, "stages": ",".join(requested)})
            assert response.status_code == 200
            body = response.json()
            assert body["schema_version"] == "v4.stage_timeline_batch.v1"
            assert body["trade_date"] == day
            assert body["stage_ids"] == requested
            assert [i["stage"] for i in body["items"]] == requested
            assert body["RESEARCH_ONLY"] is True
            for flag in ("production_allowed", "buy_gate_updated", "orders_sent", "write_performed"):
                assert body[flag] is False
            assert set(body["stages"]) == set(requested)
            selected = body["stages"][opening]
            assert selected["trade_date"] == day
            assert selected["stage"]["stage_id"] == opening
            assert selected["markets"][market]["display_mode"] == "OBSERVATION_UNVERIFIED"
            assert selected["markets"][market]["observation_count"] == 1
            assert selected["markets"][other]["display_mode"] == "CANNOT_CONFIRM"
            assert selected["selected_a_rows"] == int(market == "A")
            assert selected["selected_hk_rows"] == int(market == "HK")
            assert "execution_evidence" not in selected
            missing = body["stages"][auction]
            assert missing["stage"]["status"] == "CANNOT_CONFIRM"
            assert all(item["display_mode"] == "CANNOT_CONFIRM" for item in missing["markets"].values())
