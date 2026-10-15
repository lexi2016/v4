"""Focused, in-process API checks against the prepared candidate app only."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_workbench.api import (
    US_MAPPING_CATALOG_PATH,
    US_MAPPING_REVIEW_OVERLAY_PATH,
    create_router,
)


CANDIDATE_APP = Path(os.environ.get(
    "V4_MAPPING700_CANDIDATE_APP_ROOT",
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-mapping700-20261016-r1/app",
))
CONFIG = Path(os.environ.get(
    "V4_MAPPING700_CONFIG_PATH",
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/config/us-hk-mapping700-20261016-r1.json",
))
SOURCE_PACKAGE_SHA256 = "2894b3bca475965aa3553977a654b10fa4c6750bbcb80f70f1bea17bdde649b0"


def main() -> None:
    assert Path.cwd().resolve() == CANDIDATE_APP.resolve()
    assert Path(__file__).resolve().parents[3] == Path("/Users/lexi/Desktop/学习/v4_app")
    assert Path(os.environ["V4_MANAGER_WORKBENCH_CONFIG_PATH"]).resolve() == CONFIG.resolve()
    assert str(US_MAPPING_CATALOG_PATH).startswith(str(CANDIDATE_APP / "v4/manager_workbench/"))
    assert str(US_MAPPING_REVIEW_OVERLAY_PATH).startswith(str(CANDIDATE_APP / "v4/manager_workbench/"))
    app = FastAPI()
    app.include_router(create_router(None))
    client = TestClient(app)
    listing = client.get("/api/v4/manager-workbench/mapping-catalog")
    assert listing.status_code == 200
    assert len(listing.content) < 1_000_000
    data = listing.json()["data"]
    assert data["coverage"]["membership_count"] == 667
    assert data["coverage"]["relation_row_count"] == 1003
    assert data["review_progress"]["source_reviewed_relations"] == 700
    assert data["review_progress"]["unprocessed_relations"] == 303
    assert data["review_progress"]["independently_verified_relations"] == 0
    assert data["review_source"]["source_package_sha256"] == SOURCE_PACKAGE_SHA256
    assert data["safety"] == {
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False,
        "orders_sent": False, "prediction_validation": "UNTESTED", "historical_PIT": "NOT_VALIDATED",
    }

    reviewed = client.get("/api/v4/manager-workbench/mapping-catalog?q=R001")
    assert reviewed.status_code == 200
    relation = reviewed.json()["data"]["items"][0]["relations"][0]
    assert relation["relation_id"] == "R001"
    assert relation["source_review_status"] == "SOURCE_REVIEWED"
    assert relation["review_detail_level"] == "FULL"
    evidence = relation["review_revision"]["evidence"]
    assert evidence
    assert "declared_unresolved_navigation_reference_json" in evidence[0]
    assert "evidence_wording_clarifications_json" in evidence[0]

    unprocessed = client.get("/api/v4/manager-workbench/mapping-catalog?q=R700")
    assert unprocessed.status_code == 200
    relation = unprocessed.json()["data"]["items"][0]["relations"][0]
    assert relation["relation_id"] == "R700"
    assert (relation["source_review_status"], relation["review_detail_level"], relation["review_revision"]) == (
        "NOT_PROCESSED", "SUMMARY", None)
    print(json.dumps({
        "status": "PASS",
        "default_response_bytes": len(listing.content),
        "membership_count": data["coverage"]["membership_count"],
        "relation_count": data["coverage"]["relation_row_count"],
        "source_reviewed_relations": data["review_progress"]["source_reviewed_relations"],
        "unprocessed_relations": data["review_progress"]["unprocessed_relations"],
        "independently_verified_relations": data["review_progress"]["independently_verified_relations"],
        "exact_reviewed_rid": "R001/FULL",
        "exact_unprocessed_rid": "R700/NOT_PROCESSED/SUMMARY/null",
        "api_module_catalog_path": str(US_MAPPING_CATALOG_PATH),
        "api_module_overlay_path": str(US_MAPPING_REVIEW_OVERLAY_PATH),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
