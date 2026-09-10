from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger


def test_task_status_separates_identity_groups_and_exposes_evidence_gap(tmp_path) -> None:
    body = TestClient(create_app(data_root=tmp_path / "data")).get(
        "/api/v3/tasks/status?date=20260730"
    ).json()

    assert set(body["groups"]) == {
        "logical",
        "active_owners",
        "aliases",
        "retired",
        "registrations",
    }
    assert body["logical_workload_count"] == len(body["groups"]["logical"]) == 5
    assert body["active_owner_count"] == len(body["groups"]["active_owners"]) == 1
    assert body["alias_count"] == len(body["groups"]["aliases"]) == 4
    assert body["retired_owner_count"] == len(body["groups"]["retired"]) == 6
    assert body["task_registration_count"] == len(
        body["groups"]["registrations"]
    ) == 34
    assert body["cannot_confirm"] == [
        "EXECUTION_RECEIPT_MISSING:hourly_research",
        "GRAPH_TASK_REGISTRATIONS_CANNOT_CONFIRM:34",
    ]
    assert all(
        row["enabled"] is False and row["execution_allowed"] is False
        for row in body["groups"]["registrations"]
    )
    assert all(
        row["status"] == "CANNOT_CONFIRM"
        for row in body["groups"]["registrations"]
    )
    assert all(
        "command" not in row and "owner_id" not in row and "slots" not in row
        for row in body["groups"]["registrations"]
    )
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


def test_task_status_uses_same_date_receipt_without_counting_alias_as_execution(tmp_path) -> None:
    data_root = tmp_path / "data"
    ledger = ExecutionLedger(data_root / "dispatcher")
    dispatch_due(
        DispatchRequest("20260730", "20260730", "20260730", "1200", DispatchMode.LIVE),
        load_workload_catalog(),
        lambda *_args: {"status": "SUCCEEDED"},
        ledger=ledger,
        dry_run=True,
    )

    response = TestClient(create_app(data_root=data_root)).get(
        "/api/v3/tasks/status?date=20260730"
    )

    assert response.status_code == 200
    body = response.json()
    hourly = next(row for row in body["groups"]["logical"] if row["workload_id"] == "hourly_research")
    assert hourly["status"] == "DRY_RUN_SELECTED"
    assert hourly["last_run"].endswith("Z")
    assert hourly["receipt_path"].endswith(".dispatch-receipt.json")
    assert body["cannot_confirm"] == [
        "GRAPH_TASK_REGISTRATIONS_CANNOT_CONFIRM:34"
    ]


def test_task_status_projects_the_first_research_panel_breakpoint(tmp_path) -> None:
    data_root = tmp_path / "data"
    receipt_path = tmp_path / "dispatcher" / "receipts" / "live" / "20260730" / "1700" / "panel.dispatch-receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        "{" 
        "\"business_date\": \"20260730\", "
        "\"finished_at\": \"2026-07-30T09:01:00Z\", "
        "\"mode\": \"LIVE\", "
        "\"selected_workload_ids\": [\"research_panel_daily_a\"], "
        "\"status\": \"FAILED\", "
        "\"workload_results\": [{\"workload_id\": \"research_panel_daily_a\", "
        "\"reason\": \"RESEARCH_PANEL_DAILY_LANE_NOT_READY\"}]"
        "}",
        encoding="utf-8",
    )

    body = TestClient(create_app(data_root=data_root)).get(
        "/api/v3/tasks/status?date=20260730"
    ).json()

    panel_a = next(
        row for row in body["groups"]["logical"]
        if row["workload_id"] == "research_panel_daily_a"
    )
    assert panel_a["status"] == "FAILED"
    assert panel_a["breakpoint"] == "RESEARCH_PANEL_DAILY_LANE_NOT_READY"


def test_task_status_rejects_invalid_date(tmp_path) -> None:
    response = TestClient(create_app(data_root=tmp_path / "data")).get(
        "/api/v3/tasks/status?date=2026-07-30"
    )

    assert response.status_code == 422
