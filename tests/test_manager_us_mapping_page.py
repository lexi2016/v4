from datetime import datetime
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.manager_research_router import create_manager_research_router
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.us_mapping_research import read_workspace_mapping
from v4.manager_research.workspace import get_workspace
from v4.manager_research.workspace_projection import HK


def test_mapping_overlay_is_returned_by_workspace_get_but_not_saved_into_plan(tmp_path):
    date = "20260930"
    now = datetime(2026, 9, 30, 9, 27, 30, tzinfo=HK)
    service = ManagerResearchJobService(ManagerResearchStore(tmp_path / "manager"), None, None)
    try:
        prepared = get_workspace(service, date, include_saved=False, now=now)
        assert "us_mapping_research" not in prepared

        refreshed = service.refresh_workspace_plan(date, now=now)
        assert "us_mapping_research" not in refreshed
        saved = service.get_workspace_plan(date)
        assert saved is not None
        assert "us_mapping_research" not in saved["workspace"]
        persisted = json.loads((service.store.root / "workspace_plans" / date / "latest.json").read_text())
        assert "us_mapping_research" not in persisted["workspace"]
        assert persisted["input_identity"] == saved["input_identity"]

        app = FastAPI()
        app.include_router(create_manager_research_router(service))
        with TestClient(app) as client:
            response = client.get(f"/api/v4/manager/research/workspace?date={date}&view=dynamic")
        assert response.status_code == 200
        body = response.json()
        mapping = body["us_mapping_research"]
        assert mapping["target_trade_date"] == date
        assert mapping["daily_run"]["status"] == "NOT_RUN"
        coverage = mapping["daily_run"]["coverage"]
        assert coverage["available_us_universe_count"] is None
        assert mapping["reviewed_research"]["status"] == "REVIEWED_RETROSPECTIVE_RESEARCH"
        assert len(mapping["reviewed_research"]["cards"]) == 5

        missing_mapping = read_workspace_mapping(service, "20261001")["daily_run"]
        assert missing_mapping["status"] == "NOT_RUN"
        assert missing_mapping["coverage"]["available_us_universe_count"] is None
    finally:
        service.close()
