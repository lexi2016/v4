from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pytest


SHANGHAI = timezone(timedelta(hours=8))
TRADE_DATE = "20260907"


def _route_endpoint(app: Any, path: str) -> Any:
    return next(route.endpoint for route in app.routes if getattr(route, "path", None) == path)


def _catalog_store(root: Path):
    from infrastructure.data_store import NativeDataStore

    store = NativeDataStore(root / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": TRADE_DATE,
            "stage_dates": [],
            "future_target_dates": [],
            "materialized_rows": {},
        }
    )
    return store


def _historical_hk_selection() -> dict[str, Any]:
    from stage_center.contracts import SELECTION_ALGORITHM_ID
    from stage_center.selection import ALGORITHM_SHA256

    return {
        "schema_version": "stage_center.selection.v2",
        "trade_date": TRADE_DATE,
        "stage_id": "STAGE_0935_0940",
        "market": "HK_CONNECT",
        "algorithm_id": SELECTION_ALGORITHM_ID,
        "algorithm_sha256": ALGORITHM_SHA256,
        "raw_artifact_sha256": "a" * 64,
        "source_status": "READY",
        "selection_status": "PARTIAL_WITH_ROWS",
        "requested_rows": 10,
        "source_rows": 1,
        "selected_rows": 1,
        "coverage_ratio": 0.1,
        "missing_symbols": [],
        "rows": [{"code": "HK.00001", "rank": 1, "name": "Example"}],
        "source_evidence": ["recovery_mode=HISTORICAL_BACKFILL"],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_stage_projection_keeps_hk_cannot_confirm_reason_when_a_has_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app

    payload = {
        "schema_version": "stage_center.selection_consumer.v1",
        "trade_date": TRADE_DATE,
        "stage_id": "STAGE_0935_0940",
        "status": "PARTIAL_WITH_ROWS",
        "cannot_confirm": [],
        "markets": {
            "A_SHARE": {
                "market": "A_SHARE",
                "status": "READY",
                "selection_status": "READY",
                "selected_rows": 1,
                "rows": [{"code": "A.000001", "rank": 1}],
                "cannot_confirm": [],
            },
            "HK_CONNECT": {
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "selection_status": "CANNOT_CONFIRM",
                "selected_rows": 0,
                "rows": [],
                "cannot_confirm": ["HK_NATIVE_RECEIPT_MISSING"],
            },
        },
    }

    class FakeConsumer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def get(self, _date: str, _stage: str, **_kwargs: Any) -> dict[str, Any]:
            return payload

    monkeypatch.setattr(app_module, "StageSelectionConsumer", FakeConsumer)
    store = _catalog_store(tmp_path)
    app = create_app(data_root=store.root, stage_center_selection_root=tmp_path / "stage")
    endpoint = _route_endpoint(app, "/api/v3/stage-center/selection")

    projected = endpoint(date=TRADE_DATE, stage="STAGE_0935_0940", limit=50)

    assert projected["status"] == "PARTIAL_WITH_ROWS"
    assert projected["markets"]["A"]["candidate_count"] == 1
    assert projected["markets"]["HK"]["status"] == "CANNOT_CONFIRM"
    assert "HK:HK_NATIVE_RECEIPT_MISSING" in projected["cannot_confirm"]
    assert projected["selected_total_rows"] == 1


def test_stage_projection_propagates_partial_market_reason_without_status_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app

    payload = {
        "schema_version": "stage_center.selection_consumer.v1",
        "trade_date": TRADE_DATE,
        "stage_id": "STAGE_0935_0940",
        "status": "PARTIAL_WITH_ROWS",
        "cannot_confirm": [],
        "markets": {
            "A_SHARE": {
                "market": "A_SHARE",
                "status": "PARTIAL_WITH_ROWS",
                "selection_status": "PARTIAL_WITH_ROWS",
                "selected_rows": 1,
                "rows": [{"code": "A.000001", "rank": 1}],
                "cannot_confirm": ["A_SOURCE_PARTIAL"],
            },
            "HK_CONNECT": {
                "market": "HK_CONNECT",
                "status": "READY",
                "selection_status": "READY",
                "selected_rows": 0,
                "rows": [],
                "cannot_confirm": [],
            },
        },
    }

    class FakeConsumer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def get(self, _date: str, _stage: str, **_kwargs: Any) -> dict[str, Any]:
            return payload

    monkeypatch.setattr(app_module, "StageSelectionConsumer", FakeConsumer)
    store = _catalog_store(tmp_path)
    app = create_app(data_root=store.root, stage_center_selection_root=tmp_path / "stage")
    endpoint = _route_endpoint(app, "/api/v3/stage-center/selection")

    projected = endpoint(date=TRADE_DATE, stage="STAGE_0935_0940", limit=50)

    assert projected["status"] == "PARTIAL_WITH_ROWS"
    assert projected["stage"]["status"] == "PARTIAL_WITH_ROWS"
    expected_gaps = [
        "A:A_SOURCE_PARTIAL",
        "HK:SELECTION_ARTIFACT_MISSING_OR_INVALID",
    ]
    assert projected["stage"]["cannot_confirm"] == expected_gaps
    assert projected["cannot_confirm"] == expected_gaps
    assert projected["markets"]["A"]["cannot_confirm"] == ["A_SOURCE_PARTIAL"]
    # The fixture has no valid HK artifact, so the combined row total is unknown.
    assert projected["selected_total_rows"] is None


def test_backfill_is_opt_in_only_for_stage_workbench_not_manager_or_ensure(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from apps.api.v35_api.app import create_app
    from stage_center.consumer import StageSelectionConsumer
    from stage_center.selection import SelectionStore

    selection_root = tmp_path / "stage-selection"
    SelectionStore(selection_root / "backfill" / "recovery-r1").publish(
        _historical_hk_selection(), market="HK_CONNECT"
    )
    ordinary_consumer = StageSelectionConsumer(selection_root)
    ordinary = ordinary_consumer.get(
        TRADE_DATE, "STAGE_0935_0940", markets=("HK_CONNECT",)
    )["markets"]["HK_CONNECT"]
    ensured = ordinary_consumer.ensure(
        TRADE_DATE, "STAGE_0935_0940", markets=("HK_CONNECT",)
    )["markets"]["HK_CONNECT"]
    assert ordinary["status"] == ensured["status"] == "CANNOT_CONFIRM"
    assert ordinary["rows"] == ensured["rows"] == []

    catalog = _catalog_store(tmp_path)
    client = TestClient(
        create_app(
            data_root=catalog.root,
            stage_center_selection_root=selection_root,
            current_date=TRADE_DATE,
        )
    )
    stage = client.get(
        "/api/v3/workbench/stage",
        params={"date": TRADE_DATE, "stage": "STAGE_0935_0940", "limit": 50},
    ).json()
    assert stage["markets"]["HK"]["selection_mode"] == "BACKFILL"
    assert stage["markets"]["HK"]["rows"][0]["code"] == "HK.00001"
    backfill_provenance_keys = {
        "selection_mode",
        "backfill_run_id",
        "backfill_run_ids",
        "selection_manifest_sha256",
        "selection_receipt_sha256",
        "selection_artifact_sha256",
        "selection_manifest_receipt_verified",
        "runner_receipt_verified",
        "runner_receipt_status",
        "runner_receipt_sha256",
        "recovery_provenance",
    }
    assert backfill_provenance_keys.issubset(stage["markets"]["HK"])

    manager = client.get(
        "/api/v3/manager/stage-selection",
        params={
            "date": TRADE_DATE,
            "stage": "STAGE_0935_0940",
            "market": "HK_CONNECT",
        },
    ).json()
    assert manager["status"] == "CANNOT_CONFIRM"
    assert manager["markets"]["HK"]["rows"] == []
    assert not backfill_provenance_keys.intersection(manager["markets"]["HK"])

    ensure = client.post(
        "/api/v3/workbench/stage/ensure",
        params={"date": TRADE_DATE, "stage": "STAGE_0935_0940"},
    ).json()
    assert ensure["status"] == "CANNOT_CONFIRM"
    assert ensure["markets"]["HK"]["rows"] == []
    assert not backfill_provenance_keys.intersection(ensure["markets"]["HK"])


def _workload(*, policy: Any, slot: str = "1700") -> Any:
    from contracts.runtime_tasks import SafetyBoundary, WorkloadDefinition
    from contracts.trading_calendar import MarketScope, SessionRequirement

    return WorkloadDefinition(
        workload_id="stage_projection_test",
        owner_id="test",
        run_policy=policy,
        market_scope=MarketScope.A_SHARE,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
        slots=(slot,),
        command=("test",),
        aliases=(),
        enabled=True,
        scheduled_date_role="BUSINESS_DATE",
        signal_date_role="BUSINESS_DATE",
        target_date_role="BUSINESS_DATE",
        safety=SafetyBoundary(False, False, False),
    )


def test_task_projection_moves_past_slot_to_next_eligible_date_without_changing_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contracts.trading_calendar import RunPolicy
    from domains import task_status

    workload = _workload(policy=RunPolicy.A_SHARE_TRADE_DAY)
    now = datetime(2026, 9, 7, 18, 0, tzinfo=SHANGHAI)
    receipt = {
        "status": "FAILED",
        "finished_at": "2026-09-07T17:01:00+08:00",
        "duration_ms": 42,
    }

    row = task_status._logical_row(workload, receipt, TRADE_DATE, now)

    assert row["status"] == "FAILED"
    assert row["result_code"] == "FAILED"
    assert row["next_due"] == "20260908 17:00"
    assert row["next_due_date"] == "20260908"
    assert row["next_due_reason"] == "NEXT_ELIGIBLE_SLOT"


def _selection_envelope(trade_date: str, stage_id: str, market: str) -> dict[str, Any]:
    from stage_center.contracts import SELECTION_ALGORITHM_ID
    from stage_center.selection import ALGORITHM_SHA256

    return {
        "schema_version": "stage_center.selection.v2",
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": market,
        "algorithm_id": SELECTION_ALGORITHM_ID,
        "algorithm_sha256": ALGORITHM_SHA256,
        "raw_artifact_sha256": "a" * 64,
        "source_status": "READY",
        "selection_status": "READY_EMPTY",
        "requested_rows": 0,
        "source_rows": 0,
        "selected_rows": 0,
        "coverage_ratio": 1.0,
        "missing_symbols": [],
        "rows": [],
        "source_evidence": ["fixture=stage_projection_regression"],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_date_catalog_reports_verified_and_invalid_stage_entries_from_shared_root(
    tmp_path: Path,
) -> None:
    from domains.preselection import date_catalog
    from stage_center.selection import SelectionStore

    store = _catalog_store(tmp_path)
    selection_root = tmp_path / "stage-selection"
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    # Keep an independent pool on the same date to prove the two authoritative
    # roots are deduplicated instead of one hiding the stage artifact date.
    PreselectionPoolStore(store.root).materialize(
        _pool_payload(TRADE_DATE, "a_d1_premarket_pool", "A")
    )
    SelectionStore(selection_root).publish(
        _selection_envelope(TRADE_DATE, "STAGE_0935_0940", "A_SHARE"),
        market="A_SHARE",
    )
    latest_path = selection_root / "selection_latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["entries"][f"{TRADE_DATE}/STAGE_0935_0940/HK_CONNECT"] = {
        "owner": "stage_center",
        "trade_date": TRADE_DATE,
        "stage_id": "STAGE_0935_0940",
        "market": "HK_CONNECT",
        "role": "HK_CONNECT_SELECTION_STAGE_0935_0940",
        "run_id": "missing-run",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    latest_path.write_text(json.dumps(latest), encoding="utf-8")

    catalog = date_catalog(store, current_date=TRADE_DATE, stage_selection_root=selection_root)
    artifact = catalog["stage_artifacts"][TRADE_DATE]

    assert artifact["status"] == "PARTIAL"
    assert artifact["verified_entries"] == 1
    assert artifact["blocked_entries"] == 1
    assert TRADE_DATE in catalog["stage_dates"]
    assert TRADE_DATE in catalog["dates"]
    assert catalog["partial_stage_dates"] == [TRADE_DATE]


def test_date_catalog_requires_every_scheduled_market_for_materialized_stage(
    tmp_path: Path,
) -> None:
    from domains.preselection import date_catalog
    from stage_center.selection import SelectionStore

    store = _catalog_store(tmp_path)
    selection_root = tmp_path / "stage-selection"
    SelectionStore(selection_root).publish(
        _selection_envelope(TRADE_DATE, "STAGE_0935_0940", "A_SHARE"),
        market="A_SHARE",
    )

    catalog = date_catalog(store, current_date=TRADE_DATE, stage_selection_root=selection_root)
    artifact = catalog["stage_artifacts"][TRADE_DATE]

    assert artifact["status"] == "PARTIAL"
    assert artifact["verified_markets"] == ["A_SHARE"]
    assert artifact["expected_markets"]["STAGE_0935_0940"] == ["A_SHARE", "HK_CONNECT"]
    assert artifact["missing_markets"] == ["STAGE_0935_0940:HK_CONNECT"]
    assert "STAGE_MARKET_MISSING:STAGE_0935_0940:HK_CONNECT" in artifact["cannot_confirm"]


def test_date_catalog_default_follows_newest_verified_evidence_across_lanes(
    tmp_path: Path,
) -> None:
    from domains.preselection import date_catalog
    from infrastructure.data_store import NativeDataStore
    from stage_center.selection import SelectionStore

    store = NativeDataStore(tmp_path / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": "20260901",
            "stage_dates": ["20260901"],
            "future_target_dates": [],
            "materialized_rows": {"20260901": 2},
        }
    )
    selection_root = tmp_path / "stage-selection"
    SelectionStore(selection_root).publish(
        _selection_envelope(TRADE_DATE, "STAGE_0935_0940", "A_SHARE"),
        market="A_SHARE",
    )

    catalog = date_catalog(store, current_date=TRADE_DATE, stage_selection_root=selection_root)

    # The legacy pool-import lane froze on 20260901; the verified stage-center
    # artifact for TRADE_DATE is newer evidence.  The default must follow the
    # newest verified evidence instead of pinning the app to the stale date.
    assert catalog["default_date"] == TRADE_DATE
    assert catalog["dates"] == [TRADE_DATE, "20260901"]


def test_runtime_graph_projection_is_bounded_and_preserves_snapshot_identity(tmp_path: Path) -> None:
    from infrastructure.runtime_graph.contracts import EvidenceLayer, EvidenceResult, GraphStatus
    from infrastructure.runtime_graph.service import MAX_SNAPSHOT_BYTES, RuntimeGraphService
    from infrastructure.runtime_graph.snapshot import build_snapshot

    now = datetime(2026, 9, 7, 10, 0, tzinfo=SHANGHAI)
    service = RuntimeGraphService(tmp_path / "data", now_provider=lambda: now)
    # Keep the raw envelope above the strict 1 MiB semantic cap while staying
    # inside the separate bounded projection read cap.
    huge = "x" * 40_000
    topology = json.loads(json.dumps(service.topology))
    topology["generated_at"] = now.isoformat(timespec="seconds")
    evidence = {
        str(node["node_id"]): (
            EvidenceResult(EvidenceLayer.CALENDAR, GraphStatus.NOT_DUE, "NOT_DUE", {"bulk": huge}),
        )
        for node in topology["nodes"]
    }
    payload = build_snapshot(
        topology=topology,
        evidence_by_node=evidence,
        business_date=TRADE_DATE,
        generated_at=now,
        topology_freshness_seconds=service.contract["freshness_seconds"]["topology"],
    )
    snapshot_path = service.runtime_root / "snapshots" / "current.json"
    snapshot_path.parent.mkdir(parents=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(raw) > MAX_SNAPSHOT_BYTES
    snapshot_path.write_bytes(raw)

    projected = service.snapshot()
    status = service.status()

    assert projected["snapshot_projection"]["bounded"] is True
    assert projected["snapshot_projection"]["source_bytes"] == len(raw)
    assert projected["snapshot_projection"]["semantic_status"] == "CANNOT_CONFIRM_FULL_DETAILS"
    assert projected["status"] == "NOT_DUE"
    assert all(flag is False for flag in (projected["production_allowed"], projected["buy_gate_updated"], projected["orders_sent"]))
    assert projected["snapshot_identity"]["snapshot_sha256"] == hashlib.sha256(raw).hexdigest()
    assert len(json.dumps(projected, ensure_ascii=False).encode("utf-8")) < MAX_SNAPSHOT_BYTES
    assert status["snapshot_sha256"] == hashlib.sha256(raw).hexdigest()
    assert status["status"] == "NOT_DUE"
    assert status["ok"] is True


def test_runtime_graph_bounded_projection_rejects_invalid_pass_and_safety_flags(
    tmp_path: Path,
) -> None:
    from infrastructure.runtime_graph.service import MAX_SNAPSHOT_BYTES, RuntimeGraphService

    now = datetime(2026, 9, 7, 10, 0, tzinfo=SHANGHAI)
    service = RuntimeGraphService(tmp_path / "data", now_provider=lambda: now)
    payload = {
        "schema_version": "v3_runtime_snapshot.v1",
        "business_date": TRADE_DATE,
        "generated_at": now.isoformat(timespec="seconds"),
        "topology_schema_version": service.topology["schema_version"],
        "topology_authority_root": service.topology["authority_root"],
        "topology_version_sha": service.topology_version_sha,
        "nodes": [],
        "edges": [],
        "status": "PASS",
        "reason": "GRAPH_READY",
        "production_allowed": True,
        "buy_gate_updated": True,
        "orders_sent": True,
        "padding": "x" * (MAX_SNAPSHOT_BYTES + 10_000),
    }
    snapshot_path = service.runtime_root / "snapshots" / "current.json"
    snapshot_path.parent.mkdir(parents=True)
    snapshot_path.write_bytes(json.dumps(payload, separators=(",", ":")).encode())

    projected = service.snapshot()
    status = service.status()

    assert projected["ok"] is False
    assert projected["status"] == "EVIDENCE_GAP"
    assert "SNAPSHOT_SEMANTICS_INVALID" in projected["reason"]
    assert status["ok"] is False
    assert status["status"] == "EVIDENCE_GAP"


def test_runtime_graph_events_keep_invalid_event_as_cannot_confirm(tmp_path: Path) -> None:
    from infrastructure.runtime_graph.service import RuntimeGraphService
    from infrastructure.runtime_graph.store import RuntimeEventStore

    now = datetime(2026, 9, 7, 10, 0, tzinfo=SHANGHAI)
    service = RuntimeGraphService(tmp_path / "data", now_provider=lambda: now)
    service.runtime_root.mkdir(parents=True)
    state_root = service.runtime_root / "state"
    state_root.mkdir()
    node_id = str(service.topology["nodes"][0]["node_id"])
    RuntimeEventStore(
        state_root / "graph_state.db",
        allowed_root=service.runtime_root,
        observed_at=lambda: now,
    ).record_transitions(
        {
            "schema_version": "v3_runtime_snapshot.v1",
            "business_date": TRADE_DATE,
            "topology_version_sha": service.topology_version_sha,
            "nodes": [{"node_id": node_id, "status": "EVIDENCE_GAP", "reason": "INVALID_RECEIPT"}],
        }
    )

    result = service.events(node_id, 10)

    assert result["ok"] is True
    assert result["status"] == "EVIDENCE_GAP"
    assert result["reason"] == "EVENTS_READ_WITH_CANNOT_CONFIRM"
    assert result["cannot_confirm"]
    assert "INVALID_RECEIPT" in result["cannot_confirm"][0]
    assert result["topology_version_sha"] == service.topology_version_sha


def _pool_payload(date: str, pool_id: str, market: str) -> dict[str, Any]:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": date,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": market,
        "status": "READY",
        "producer_id": "B03_OPTIONALITY_FIXTURE",
        "source_role": "RAW_SOURCE",
        "source_path": f"fixture/{date}/{pool_id}.json",
        "source_sha256": hashlib.sha256(f"{date}:{pool_id}".encode()).hexdigest(),
        "rows": [{"symbol": f"{market}.{pool_id[:3].upper()}", "market": market}],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "signal_date": date,
        "target_date": date,
    }


def test_optional_research_pool_absence_does_not_block_mandatory_daily_readiness(
    tmp_path: Path,
) -> None:
    from domains.preselection import preselection
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    store = _catalog_store(tmp_path)
    pool_store = PreselectionPoolStore(store.root)
    mandatory = (
        ("a_d1_premarket_pool", "A"),
        ("a_d1_fupan_watchlist_pool", "A"),
        ("a_d1_stage7_fenshi_review_pool", "A"),
        ("a_share_research_recommendation_pool", "A"),
        ("hkconnect_d1_top100", "HK"),
    )
    for pool_id, market in mandatory:
        pool_store.materialize(_pool_payload(TRADE_DATE, pool_id, market))

    payload = preselection(store, TRADE_DATE, limit=50)
    pools = {pool["pool_id"]: pool for pool in payload["pools"]}

    assert payload["data_status"] == "READY_WITH_ROWS"
    assert payload["daily_readiness_status"] == "READY_WITH_ROWS"
    assert payload["optional_pool_status"] == "CANNOT_CONFIRM"
    assert payload["optional_pool_ids"] == [
        "a_share_baimao_research_map",
        "wechat_public_account_v3_preselect",
    ]
    for pool_id in payload["optional_pool_ids"]:
        assert pools[pool_id]["optional"] is True
        assert pools[pool_id]["required_for_daily_readiness"] is False
        assert pools[pool_id]["status"] == "CANNOT_CONFIRM"
    assert payload["blocking_reasons"] == []


def test_mandatory_partial_pool_stays_incomplete_when_optional_pools_are_absent(
    tmp_path: Path,
) -> None:
    from domains.preselection import (
        _complete_independent_pool_set,
        _project_independent_pools,
        preselection,
    )
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    store = _catalog_store(tmp_path)
    pool_store = PreselectionPoolStore(store.root)
    mandatory = (
        ("a_d1_premarket_pool", "A"),
        ("a_d1_fupan_watchlist_pool", "A"),
        ("a_d1_stage7_fenshi_review_pool", "A"),
        ("a_share_research_recommendation_pool", "A"),
        ("hkconnect_d1_top100", "HK"),
    )
    for pool_id, market in mandatory:
        payload = _pool_payload(TRADE_DATE, pool_id, market)
        if pool_id == "a_d1_premarket_pool":
            payload["status"] = "PARTIAL_WITH_ROWS"
            payload["cannot_confirm"] = ["SOURCE_PARTIAL"]
        pool_store.materialize(payload)

    projected = _project_independent_pools(
        _complete_independent_pool_set(pool_store.read_all(TRADE_DATE), TRADE_DATE),
        TRADE_DATE,
    )
    response = preselection(store, TRADE_DATE, limit=50)

    assert projected["producer_status"] == "PARTIAL"
    assert projected["daily_readiness_status"] == "PARTIAL_WITH_ROWS"
    assert projected["optional_pool_status"] == "CANNOT_CONFIRM"
    assert projected["mandatory_incomplete_pool_ids"] == ["a_d1_premarket_pool"]
    assert "SOURCE_PARTIAL" in projected["blocking_reasons"]
    assert projected["optional_incomplete_pool_ids"] == [
        "a_share_baimao_research_map",
        "wechat_public_account_v3_preselect",
    ]
    assert response["data_status"] == "PARTIAL_WITH_ROWS"
    assert response["daily_readiness_status"] == "PARTIAL_WITH_ROWS"
