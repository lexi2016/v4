from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.v4_api.app import _project_stage_timeline_summary, create_app
from contracts.stages import FROZEN_STAGE_IDS
from infrastructure.data_store import NativeDataStore


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


def _full_payload() -> dict:
    return {
        "schema_version": "stage_center.selection_consumer.v1",
        "trade_date": "20260818",
        "stage_id": "STAGE_0925",
        "status": "PARTIAL_WITH_ROWS",
        "stage": {
            "stage_id": "STAGE_0925",
            "status": "PARTIAL_WITH_ROWS",
            "display_status": "部分完成",
            "cannot_confirm": ["a-large-stage-level-gap-list-the-timeline-never-renders"],
        },
        "markets": {
            "A": {
                "status": "CANNOT_CONFIRM",
                "display_mode": "OBSERVATION_UNVERIFIED",
                "observation_count": 10,
                "source_evidence": ["evidence-that-the-timeline-never-renders"],
                "cannot_confirm": ["gap"],
            },
            "HK": {"status": "PARTIAL_WITH_ROWS", "selected_rows": 10},
        },
        "execution_evidence": {
            "status": "EXECUTION_RECEIPT_MISSING",
            "due_status": "DUE",
            "markets": {"A": {"selection_binding": "unused"}},
        },
        "selected_a_rows": 0,
        "selected_hk_rows": 10,
        "selected_total_rows": 10,
        "selection_mode": "V1_1_CHAMPION_DUAL_MARKET",
        "snapshot_reselection": {
            "status": "SELECTED_WATCH_ONLY",
            "markets": {
                "A_SHARE": {
                    "mode": "AFTERFACT_SNAPSHOT_RESELECTION",
                    "selected_rows": 10,
                    "captured_at": "2026-08-18T09:34:00",
                    "rows": [{"code": "unused"}],
                }
            },
        },
        "snapshot_recovery": {
            "status": "OBSERVATIONS_AVAILABLE",
            "markets": {
                "A_SHARE": {
                    "mode": "SNAPSHOT_RECOVERY_OBSERVATION",
                    "observed_rows": 5,
                    "captured_at": "2026-08-18T09:37:00",
                    "rows": [{"code": "unused"}],
                }
            },
        },
        "unified_rows": [{"code": "A.000001"} for _ in range(1000)],
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "write_performed": False,
    }


def test_projection_keeps_only_timeline_fields() -> None:
    summary = _project_stage_timeline_summary(_full_payload())

    assert "unified_rows" not in summary
    assert "cannot_confirm" not in summary["stage"]
    assert summary["stage"]["stage_id"] == "STAGE_0925"
    assert summary["markets"]["A"]["observation_count"] == 10
    assert "source_evidence" not in summary["markets"]["A"]
    assert "cannot_confirm" not in summary["markets"]["A"]
    assert summary["execution_evidence"] == {
        "status": "EXECUTION_RECEIPT_MISSING",
        "due_status": "DUE",
    }
    reselection = summary["snapshot_reselection"]["markets"]["A_SHARE"]
    assert reselection["selected_rows"] == 10
    assert "rows" not in reselection
    recovery = summary["snapshot_recovery"]["markets"]["A_SHARE"]
    assert recovery["observed_rows"] == 5
    assert "rows" not in recovery
    assert summary["RESEARCH_ONLY"] is True
    assert summary["production_allowed"] is False


def test_batch_returns_every_requested_stage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = TestClient(create_app(data_root=store.root, current_date="20260818"))

    response = client.get(
        "/api/v4/workbench/stage-batch",
        params={"date": "20260818", "stages": "STAGE_0925,STAGE_0930_0935"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "v4.stage_timeline_batch.v1"
    assert payload["trade_date"] == "20260818"
    assert set(payload["stages"]) == {"STAGE_0925", "STAGE_0930_0935"}
    for summary in payload["stages"].values():
        assert "unified_rows" not in summary
        assert summary["stage"]["stage_id"] in {"STAGE_0925", "STAGE_0930_0935"}
    assert payload["RESEARCH_ONLY"] is True
    for key in ("production_allowed", "buy_gate_updated", "orders_sent", "write_performed"):
        assert payload[key] is False


def test_batch_defaults_to_every_frozen_stage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = TestClient(create_app(data_root=store.root, current_date="20260818"))

    payload = client.get(
        "/api/v4/workbench/stage-batch", params={"date": "20260818"}
    ).json()

    assert set(payload["stages"]).issubset(set(FROZEN_STAGE_IDS))
    assert payload["stages"]


def test_batch_rejects_unknown_stage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    client = TestClient(create_app(data_root=store.root, current_date="20260818"))

    response = client.get(
        "/api/v4/workbench/stage-batch",
        params={"date": "20260818", "stages": "STAGE_0925,NOT_A_STAGE"},
    )

    assert response.status_code == 422
