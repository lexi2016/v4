"""In-process API assertions for the isolated prepared release candidate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


def require(condition: bool, label: str) -> None:
    if not condition:
        raise RuntimeError("CANDIDATE_API_ASSERTION_FAILED:" + label)


def main() -> None:
    candidate_app = Path(os.environ["V4_MAPPING_RECOVERY_CANDIDATE_APP_ROOT"]).resolve()
    config_path = Path(os.environ["V4_MAPPING_RECOVERY_CONFIG_PATH"]).resolve()
    try:
        candidate_app.relative_to(Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-hk-recovery-v2r1-20261016-r1"))
    except ValueError as exc:
        raise RuntimeError("CANDIDATE_APP_ROOT_NOT_PINNED") from exc
    require(config_path.is_file(), "candidate config exists")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    require(config.get("relation_root") == str(candidate_app), "config relation root")

    from v4.manager_workbench import api as workbench_api
    from v4.manager_workbench.us_mapping_catalog import CatalogStore

    for module in (workbench_api, sys.modules["v4.manager_workbench.us_mapping_catalog"]):
        try:
            Path(module.__file__).resolve().relative_to(candidate_app)
        except ValueError as exc:
            raise RuntimeError("API_IMPORTED_OUTSIDE_CANDIDATE:" + str(module.__file__)) from exc

    app = FastAPI()
    app.include_router(workbench_api.create_router(None))
    client = TestClient(app)
    listing_response = client.get("/api/v4/manager-workbench/mapping-catalog")
    require(listing_response.status_code == 200, "default route status")
    listing_raw = listing_response.content
    require(len(listing_raw) < 1_000_000, "default response stays under 1 MB")
    envelope = listing_response.json()
    require(envelope.get("state") == "STRUCTURE_VALID", "default route state")
    data = envelope["data"]
    require(data.get("total") == 667, "snapshot stock count")
    recovery = data.get("recovery_v2r1")
    require(isinstance(recovery, dict), "recovery summary exists")
    counts = recovery["counts"]
    require((counts.get("snapshot_stocks"), counts.get("original_relations"),
             counts.get("processed_relations")) == (667, 1003, 1003), "667/1003 accounting")
    require(counts.get("closure_status_counts") == {
        "CLOSED_RESEARCH_SCOPE": 757, "CLOSED_EXCLUDED_SCOPE": 25, "OPEN": 221,
    }, "closure count accounting")
    require(counts.get("stocks_with_relations") == 649
            and counts.get("stocks_without_relations") == 18, "stock edge accounting")
    require(counts.get("company_independent_acceptance") == 0, "independent acceptance remains zero")
    limits = recovery["evidence_limits"]
    require(limits.get("available_at") == "ABSENT", "available_at gap")
    require(limits.get("A_url_occurrences_unattempted") == 62, "unattempted source URL gap")
    require(recovery.get("prior_700_history", {}).get("record_count") == 700, "old 700 history count")
    require(recovery.get("prior_700_history", {}).get("status_crosswalk") == "NOT_ESTABLISHED",
            "no status crosswalk")
    safety = recovery["research_safety"]
    require(safety.get("semantic_mapping_validity") == "CANNOT_CONFIRM"
            and safety.get("historical_PIT") == "NOT_VALIDATED"
            and safety.get("prediction_validation") == "UNTESTED"
            and safety.get("event_and_data_tests") == "NOT_RUN", "research safety limits")
    require(data["safety"] == {
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False,
        "orders_sent": False, "prediction_validation": "UNTESTED", "historical_PIT": "NOT_VALIDATED",
    }, "production/trading safety flags")

    overlay_path = candidate_app / "v4/manager_workbench/research_data/us_hk_667_recovery_overlay_20261016.json"
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    records = {row["relation_id"]: row for row in overlay["records"]}
    require(len(records) == 1003, "overlay relation count")
    queried: dict[str, dict[str, object]] = {}

    def exact(relation_id: str) -> dict[str, object]:
        response = client.get("/api/v4/manager-workbench/mapping-catalog",
                              params={"q": relation_id, "limit": 200})
        require(response.status_code == 200, "exact query status " + relation_id)
        body = response.json()["data"]
        matches = [row for item in body["items"] for row in item["relations"]
                   if row.get("relation_id") == relation_id]
        require(len(matches) == 1, "one exact relation " + relation_id)
        queried[relation_id] = body
        return matches[0]

    for relation_id, expected_status in (
        ("R006", "CLOSED_RESEARCH_SCOPE"), ("R003", "CLOSED_EXCLUDED_SCOPE"), ("R001", "OPEN"),
    ):
        row = exact(relation_id)
        current = row["recovery_v2r1"]
        require(current.get("closure_status") == expected_status, "closure status " + relation_id)
        require(current.get("detail_level") == "FULL", "exact query is full " + relation_id)
        require(current.get("full_record") == records[relation_id], "exact record matches overlay " + relation_id)
        require(len(current["full_record"].get("six_layers", [])) == 6, "six layer details " + relation_id)
        require(len(current["full_record"].get("field_assessments", [])) == 7,
                "seven field details " + relation_id)

    reviewed = queried["R001"]["items"]
    reviewed_row = next(row for item in reviewed for row in item["relations"])
    evidence = reviewed_row.get("review_revision", {}).get("evidence")
    require(reviewed_row.get("source_review_status") == "SOURCE_REVIEWED"
            and reviewed_row.get("review_detail_level") == "FULL"
            and isinstance(evidence, list) and bool(evidence), "old reviewed R001 history is retained")

    unprocessed = exact("R700")
    require((unprocessed.get("source_review_status"), unprocessed.get("review_detail_level"),
             unprocessed.get("review_revision")) == ("NOT_PROCESSED", "FULL", None),
            "R700 legacy state and exact full query")
    require(unprocessed.get("recovery_v2r1", {}).get("closure_status")
            == records["R700"]["effective_summary"]["closure_status"]
            and unprocessed.get("recovery_v2r1", {}).get("full_record") == records["R700"],
            "R700 current record remains separately available")

    default_rows = [row for item in data.get("items", []) for row in item.get("relations", [])]
    require(default_rows and all(row["recovery_v2r1"]["detail_level"] == "SUMMARY"
                                 and "full_record" not in row["recovery_v2r1"]
                                 for row in default_rows), "default payload uses summaries")
    no_edge = client.get("/api/v4/manager-workbench/mapping-catalog",
                         params={"q": "01528", "limit": 200}).json()["data"]
    no_edge_items = [item for item in no_edge["items"] if item["hk_code"] == "01528"]
    require(len(no_edge_items) == 1 and no_edge_items[0]["relation_count"] == 0
            and no_edge_items[0]["relations"] == [], "no-edge stock remains visible")

    old_overlay_sha = hashlib.sha256(
        (candidate_app / "v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json").read_bytes()
    ).hexdigest()
    require(recovery["prior_700_history"]["sha256"] == old_overlay_sha, "prior history hash binds old overlay")
    print(json.dumps({
        "status": "PASS",
        "default_response_bytes": len(listing_raw),
        "counts": counts,
        "closure_status_counts": counts["closure_status_counts"],
        "research_safety": safety,
        "exact_rids": ["R006", "R003", "R001", "R700"],
        "prior_700_history_sha256": old_overlay_sha,
        "runtime_safety": data["safety"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
