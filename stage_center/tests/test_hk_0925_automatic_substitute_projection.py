from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from stage_center.consumer import StageSelectionConsumer
from stage_center.selection import select_hk_four_lane, publish_selection


def test_ordinary_0925_automatic_substitute_projects_as_research_backfill(tmp_path):
    row = {
        "code": "HK.00068",
        "name": "Test Co",
        "last_price": 7.85,
        "open_price": 7.79,
        "high_price": 7.86,
        "low_price": 7.71,
        "source_last_bar_time": "2026-09-24 09:35:00",
        "formal_eligible": False,
        "source_mode": "HK_CONNECT_0930_0935_SUBSTITUTE_STAGE_0925",
        "action_level": "NO_BUY",
        "trade_status": "WATCH_ONLY",
        "candidate_lanes": [],
        "stage_id": "STAGE_0925",
    }
    source_evidence = [
        "substitute_kind=HK_0930_0935_FOR_HK_0925",
        "selection_mode=BACKFILL",
        "recovery_mode=HISTORICAL_BACKFILL",
        "d1_membership_status=STRICT_0_2_READY",
    ]
    envelope = select_hk_four_lane(
        [row],
        "20260924",
        "STAGE_0925",
        "b" * 64,
        source_status="PARTIAL_WITH_ROWS",
        requested_rows=100,
        missing_symbols=["HK.02632", "HK.03355"],
        cannot_confirm=["TARGET_STAGE_0925_CUTOFF_NOT_MET_BY_0930_0935_SUBSTITUTE"],
        source_evidence=source_evidence,
    )
    # Preserve the explicit auto-row source mode after selector normalization.
    envelope["rows"][0]["source_mode"] = row["source_mode"]
    envelope["rows"][0]["stage_id"] = "STAGE_0925"
    # The store derives immutable IDs from the final mapped row payload.
    envelope["artifact_id"] = None
    envelope["run_id"] = None
    selection_root = tmp_path / "stage" / "selection"
    store_result = publish_selection(selection_root, envelope, market="HK_CONNECT")
    store = StageSelectionConsumer(selection_root).store
    latest_entry = store._latest()["entries"][store._key("20260924", "STAGE_0925", "HK_CONNECT")]
    verified_run = store._verify_run("20260924", "STAGE_0925", "HK_CONNECT", store_result["run_id"])

    response = StageSelectionConsumer(selection_root).get(
        "20260924", "STAGE_0925", markets=("HK_CONNECT",)
    )
    market = response["markets"]["HK_CONNECT"]
    assert market["selection_mode"] == "BACKFILL"
    assert market["selection_status"] == "PARTIAL_WITH_ROWS"
    assert set(source_evidence).issubset(set(market["source_evidence"]))
    assert market["rows"][0]["source_mode"] == "HK_CONNECT_0930_0935_SUBSTITUTE_STAGE_0925"
    assert market["missing_symbols"] == ["HK.02632", "HK.03355"]
    assert market["selection_run_id"] == store_result["run_id"] == market["run_id"]
    assert market["selection_manifest_receipt_verified"] is True
    assert market["selection_manifest_sha256"] == latest_entry["manifest_sha256"] == verified_run["manifest_sha256"]
    assert market["selection_receipt_sha256"] == latest_entry["receipt_sha256"] == verified_run["receipt_sha256"]
    assert market["selection_artifact_sha256"] == latest_entry["artifact_sha256"] == verified_run["artifact_sha256"]
    assert "runner_receipt_status" not in market

    client = TestClient(create_app(
        data_root=tmp_path / "data",
        stage_center_selection_root=selection_root,
        current_date="20260924",
    ))
    api_response = client.get(
        "/api/v3/workbench/stage?date=20260924&stage=STAGE_0925&limit=50"
    )
    assert api_response.status_code == 200
    api_payload = api_response.json()
    api_market = api_payload["markets"]["HK"]
    assert api_market["selection_run_id"] == store_result["run_id"]
    assert api_market["selection_manifest_receipt_verified"] is True
    assert api_market["selection_manifest_sha256"] == verified_run["manifest_sha256"]
    assert api_market.get("runner_receipt_status") is None
    assert api_payload["execution_evidence"]["execution_verified"] is False
    assert api_payload["execution_evidence"]["status"] == "EXECUTION_RECEIPT_MISSING"
