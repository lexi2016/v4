from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from infrastructure.research_peripheral_store import ResearchPeripheralStore
from infrastructure.research_peripheral_store import CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP, _CANONICAL_SYMBOLS
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader
from v4.manager_research.us_mapping_research import (
    build_daily_run,
    persist_daily_run,
    read_workspace_mapping,
)
from v4.manager_research.workspace_projection import HK


REPORT_SHA = "0c538bc30b48af0d47185b67eb8dcc58dd412b5b92c5fbe050fa08940f97313d"
RAW_SOURCE_PAYLOAD = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/"
    "research/peripherals/20260929/external_finance.json"
)


def test_reviewed_research_is_exact_date_and_keeps_original_failure(tmp_path):
    service = SimpleNamespace(store=ManagerResearchStore(tmp_path / "manager-state"))
    reviewed = read_workspace_mapping(service, "20260930")
    artifact = reviewed["reviewed_research"]
    assert artifact["status"] == "REVIEWED_RETROSPECTIVE_RESEARCH"
    assert artifact["report"]["sha256"] == REPORT_SHA
    assert len(artifact["cards"]) == 5
    assert artifact["source_scope"]["original_workspace_plan_status"] == "SOURCE_FAILED"
    assert artifact["source_scope"]["original_us_owner_lineage_status"] == "CANNOT_CONFIRM"
    assert artifact["source_scope"]["original_plan_consumed_these_relations"] is False
    assert all(row["target_date_eligibility"] == "CANNOT_CONFIRM" for row in artifact["cards"])
    later = read_workspace_mapping(service, "20261001")
    assert later["reviewed_research"] is None
    assert later["daily_run"]["status"] == "NOT_RUN"
    assert later["daily_run"]["coverage"]["matched_hk_relation_count"] is None


def _isolated_service(tmp_path):
    if not RAW_SOURCE_PAYLOAD.is_file():
        pytest.skip("current research-peripheral payload unavailable; isolated source-owner contract cannot be exercised")
    payload = json.loads(RAW_SOURCE_PAYLOAD.read_bytes())
    data_root = tmp_path / "existing-us-owner"
    # Republish only inside tmp_path so the existing producer emits a complete
    # receipt; the historical live receipt and payload are never changed.
    ResearchPeripheralStore(data_root).publish(payload)
    reader = ResearchPeripheralUsMarketReader(data_root)
    store = ManagerResearchStore(tmp_path / "manager-owner")
    master = tmp_path / "security-master"
    master.mkdir()
    return ManagerResearchJobService(
        store, None, None,
        existing_research_source=object(),
        workspace_security_master_root=master,
        workspace_us_market_reader=reader,
    )


def test_relation_review_is_not_backdated_before_system_publication(tmp_path):
    service = _isolated_service(tmp_path)
    now = datetime(2026, 9, 30, 9, 27, 30, tzinfo=HK)
    first = persist_daily_run(service, "20260930", now=now)
    assert first["status"] == "PARTIAL"
    assert first["source_status"] == "READY"
    assert first["us_session_date"] == "20260929"
    assert first["source_identity"]["status"] == "VERIFIED"
    assert first["matches"] == []
    assert first["relation_artifact_sha256"] is None
    assert "US_HK_RELATION_NOT_AVAILABLE_AT_RESEARCH_CUTOFF" in first["gaps"]
    assert first["coverage"]["configured_us_universe_count"] == 33
    assert first["coverage"]["full_market_coverage"] is False
    assert first["coverage"]["matched_us_symbol_count"] is None
    assert first["coverage"]["matched_hk_relation_count"] is None
    saved = read_workspace_mapping(service, "20260930")["daily_run"]
    assert saved["run_id"] == first["run_id"]
    assert saved["artifact_sha256"] == first["artifact_sha256"]
    assert saved["matches"] == first["matches"]
    assert saved["target_date_eligibility"] == "CANNOT_CONFIRM"


def test_unverified_owner_input_does_not_turn_unknown_counts_into_zero(tmp_path):
    class MissingReader:
        def read_exact_session(self, session_date):
            return None, {"status": "NOT_MATERIALIZED", "session_date": session_date}

    service = SimpleNamespace(
        store=ManagerResearchStore(tmp_path / "manager-state"),
        _workspace_us_market_reader=MissingReader(),
    )
    now = datetime(2026, 9, 30, 9, 27, 30, tzinfo=HK)
    result = persist_daily_run(service, "20260930", now=now)
    assert result["status"] == "INPUT_MISSING"
    assert result["matches"] == []
    assert result["coverage"]["matched_us_symbol_count"] is None
    assert result["coverage"]["matched_hk_relation_count"] is None


@pytest.mark.parametrize(("source_status", "expected_status"), [
    ("PARTIAL", "PARTIAL"), ("SOURCE_FAILED", "FAILED"),
])
def test_incomplete_or_failed_source_keeps_daily_match_counts_unknown(tmp_path, monkeypatch, source_status, expected_status):
    from v4.manager_research import us_market_bridge

    bridge = {
        "status": source_status, "expected_us_session": "20260929", "research_cutoff": "2026-09-30T09:27:30+08:00",
        "coverage": {"requested_symbol_count": 33, "available_symbol_count": 33},
        "source_identity": None, "raw_individual_up": [], "gaps": ["UPSTREAM_SOURCE_NOT_COMPLETE"],
    }
    monkeypatch.setattr(us_market_bridge, "project_us_market", lambda *_args, **_kwargs: bridge)
    service = SimpleNamespace(store=ManagerResearchStore(tmp_path / "state"), _workspace_us_market_reader=object())
    result = build_daily_run(service, "20260930", now=datetime(2026, 9, 30, 9, 27, 30, tzinfo=HK))
    assert result["status"] == expected_status
    assert result["matches"] == []
    assert result["coverage"]["matched_us_symbol_count"] is None
    assert result["coverage"]["matched_hk_relation_count"] is None


def test_ready_source_with_zero_positive_reviewed_movers_is_valid_empty(tmp_path, monkeypatch):
    from v4.manager_research import us_market_bridge

    bridge = {
        "status": "READY", "expected_us_session": "20260929", "research_cutoff": "2026-09-30T09:27:30+08:00",
        "coverage": {"requested_symbol_count": 33, "available_symbol_count": 33},
        "source_identity": {"status": "VERIFIED", "payload_sha256": "a" * 64,
            "receipt_sha256": "b" * 64, "manifest_sha256": "c" * 64},
        "raw_individual_up": [], "gaps": [],
    }
    monkeypatch.setattr(us_market_bridge, "project_us_market", lambda *_args, **_kwargs: bridge)
    from v4.manager_research import us_mapping_research
    monkeypatch.setattr(us_mapping_research, "_relation_available_at",
        lambda _reviewed: (datetime(2026, 9, 29, 9, 0, tzinfo=HK), None))
    service = SimpleNamespace(store=ManagerResearchStore(tmp_path / "state"), _workspace_us_market_reader=object())
    result = build_daily_run(service, "20260930", now=datetime(2026, 9, 30, 9, 27, 30, tzinfo=HK))
    assert result["status"] == "VALID_EMPTY"
    assert result["matches"] == []
    assert result["coverage"]["matched_us_symbol_count"] == 0
    assert result["coverage"]["matched_hk_relation_count"] == 0


def test_scheduled_cycle_api_runs_through_injected_reader_and_rejects_wrong_binding(tmp_path, monkeypatch):
    service = _isolated_service(tmp_path)
    app_root = Path(__file__).resolve().parents[1]
    state = Path(service.store.root)
    master = Path(service._workspace_security_master_root)
    binding = {
        "enabled": True,
        "app_root": str(app_root),
        "manager_state_root": str(state),
        "security_master_root": str(master),
        "plan_material_refresh": {
            "enabled": True, "start_local": "16:00", "end_local": "23:00",
            "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600,
            "status": "PROPOSAL_ONLY",
        },
        "preopen_plan": {"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
    }
    binding_path = tmp_path / "manager-plan-binding.json"
    binding_path.write_text(json.dumps(binding, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(binding_path))
    from infrastructure.scheduling import manager_announcement_supervisor
    from v4.manager_research import plan_owner_dispatch
    monkeypatch.setattr(manager_announcement_supervisor, "validate_binding",
        lambda value, expected_app=None: value if Path(value["app_root"]).resolve() == expected_app.resolve() else (_ for _ in ()).throw(ValueError("APP_ROOT_MISMATCH")))
    monkeypatch.setattr(plan_owner_dispatch, "clock_now", lambda: datetime(2026, 9, 30, 9, 27, 30, tzinfo=HK))
    service.refresh_workspace_plan = lambda _date, **_kwargs: {
        "plan_product": {"run_id": "isolated-plan", "generated_at": "2026-09-30T09:27:30+08:00"}
    }

    from apps.api.v35_api.manager_research_router import create_manager_research_router
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    digest = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    with TestClient(app) as client:
        response = client.post(
            f"/api/v4/manager/research/workspace/scheduled-cycle?date=20260930&binding_sha256={digest}",
            content=b"",
        )
        assert response.status_code == 200
        result = response.json()
        assert result["target_trade_date"] == "20260930"
        assert result["us_mapping_research"]["status"] == "PARTIAL"
        assert result["us_mapping_research"]["coverage"]["matched_hk_relation_count"] is None
        assert read_workspace_mapping(service, "20260930")["daily_run"]["matches"] == []
        workspace = client.get("/api/v4/manager/research/workspace?date=20260930&view=historical")
        assert workspace.status_code == 200
        projected = workspace.json()["us_mapping_research"]
        assert projected["daily_run"]["run_id"] == result["us_mapping_research"]["run_id"]
        assert projected["daily_run"]["status"] == "PARTIAL"
        assert projected["daily_run"]["matches"] == []
        assert projected["reviewed_research"]["us_session_date"] == "20260929"
        next_date = client.get("/api/v4/manager/research/workspace?date=20261002&view=historical")
        assert next_date.status_code == 200
        assert next_date.json()["us_mapping_research"]["daily_run"]["status"] == "NOT_RUN"
        assert next_date.json()["us_mapping_research"]["daily_run"]["matches"] == []
        assert next_date.json()["us_mapping_research"]["reviewed_research"] is None
        mismatch = client.post(
            f"/api/v4/manager/research/workspace/scheduled-cycle?date=20261001&binding_sha256={digest}",
            content=b"",
        )
        assert mismatch.status_code == 409
    service.close()


def _synthetic_us_payload(session_date: str, positive_changes: dict[str, float]) -> dict:
    """TEST_FIXTURE only: valid owner envelope with generated synthetic prices."""
    from infrastructure.research_peripheral_store import _MARKET_MAPPING_VERSION, _MARKET_SNAPSHOT_SCHEMA_VERSION, _SCHEMA_VERSION

    us = ZoneInfo("America/New_York")
    day = datetime.strptime(session_date, "%Y%m%d")
    captured = datetime(day.year, day.month, day.day, 16, 15, 3, tzinfo=us)
    captured_text = captured.isoformat()
    symbols = sorted(_CANONICAL_SYMBOLS)
    changes = {symbol: float(positive_changes.get(symbol, 0.0)) for symbol in symbols}
    quotes = []
    for symbol in symbols:
        pct = changes[symbol]
        previous = 100.0
        quotes.append({
            "symbol": symbol, "exchange": "US", "session_date": session_date,
            "session_time": "16:00:00", "last": previous * (1.0 + pct / 100.0),
            "previous_close": previous, "change_pct": pct,
            "provider": "ISOLATED_TEST_FIXTURE",
        })
    rows = []
    for definition in CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP:
        proxies = list(definition["proxy_symbols"])
        pct = sum(changes[symbol] for symbol in proxies) / len(proxies)
        rows.append({
            "label": definition["label"], "group": definition["group"],
            "mapping_type": definition["mapping_type"], "proxy_symbols": proxies,
            "available_symbols": proxies, "missing_symbols": [],
            "requested_symbol_count": len(proxies), "available_symbol_count": len(proxies),
            "coverage": {"available": len(proxies), "requested": len(proxies)},
            "coverage_pct": 100.0, "change_pct": pct, "pct_change": pct,
            "direction": "UP" if pct > 0 else "DOWN" if pct < 0 else "FLAT",
            "status": "READY", "quote_session_dates": [session_date],
            "quote_session_times": ["16:00:00"], "cannot_confirm": [],
        })
    response_sha = hashlib.sha256(json.dumps(
        {"fixture": True, "session_date": session_date, "changes": changes},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    snapshot = {
        "schema_version": _MARKET_SNAPSHOT_SCHEMA_VERSION, "status": "READY",
        "source": "external_finance", "provider": "ISOLATED_TEST_FIXTURE",
        "source_response_sha256": response_sha, "capture_phase": "POST_CLOSE",
        "capture_session_date": session_date, "captured_at": captured_text,
        "generated_at": captured_text, "mapping_version": _MARKET_MAPPING_VERSION,
        "requested_symbol_count": len(symbols), "available_symbol_count": len(symbols),
        "provider_session_dates": [session_date], "provider_session_times": ["16:00:00"],
        "quotes": quotes, "rows": rows, "cannot_confirm": [],
        "recommendation_status": "RESEARCH_ONLY", "RESEARCH_ONLY": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    capture_id = f"synthetic-fixture-{session_date}"
    capture = {
        "us_session_date": session_date, "capture_phase": "POST_CLOSE",
        "session_timezone": "America/New_York",
        "capture_window_start": datetime(day.year, day.month, day.day, 16, 15, tzinfo=us).isoformat(),
        "capture_window_end": datetime(day.year, day.month, day.day, 16, 20, tzinfo=us).isoformat(),
        "capture_id": capture_id, "run_id": capture_id, "captured_at": captured_text,
        # These fields mirror the normal owner contract inside a temporary
        # TEST_FIXTURE only; no synthetic result is represented as live capture.
        "capture_origin": "ORIGINAL_TIME_CAPTURE", "original_time_capture": True,
    }
    return {
        "schema_version": _SCHEMA_VERSION, "trade_date": session_date,
        "source": "external_finance", "status": "READY_EMPTY",
        "source_url": "https://fixture.invalid/synthetic-us-session",
        "fetched_at": (captured + timedelta(seconds=1)).isoformat(),
        "raw_item_count": 0, "item_count": 0, "overview": [], "details": [], "items": [],
        "cannot_confirm": [], "write_policy": "read_only", "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "market_snapshot_status": "READY", "market_snapshot": snapshot,
        "us_session_captures": [capture], "capture_origin": "ORIGINAL_TIME_CAPTURE",
        "original_time_capture": True,
    }


def test_TEST_FIXTURE_synthetic_owner_sessions_produce_date_distinct_mappings_and_api_readbacks(tmp_path, monkeypatch):
    """Synthetic prices and relations prove persistence only; never historical/PIT evidence."""
    from v4.manager_research import us_mapping_research
    from apps.api.v35_api.manager_research_router import create_manager_research_router

    synthetic_cards = [
        {"daily_match_symbols": ["LITE"], "hk_symbol": "HK.06166", "hk_name": "剑桥科技",
         "research_priority": "PRIORITY", "relationship_type": "PRODUCT_PEER", "reason": "TEST_FIXTURE",
         "maturity": "TEST_FIXTURE", "limitations": ["synthetic fixture"], "official_sources": []},
        {"daily_match_symbols": ["AVGO"], "hk_symbol": "HK.06088", "hk_name": "鸿腾精密",
         "research_priority": "PRIORITY", "relationship_type": "DIRECT_NAMED_COMPONENT_SUPPLY", "reason": "TEST_FIXTURE",
         "maturity": "TEST_FIXTURE", "limitations": ["synthetic fixture"], "official_sources": []},
    ]
    reviewed = {"schema_version": "TEST_FIXTURE", "artifact_sha256": "d" * 64, "cards": synthetic_cards}
    monkeypatch.setattr(us_mapping_research, "_read_reviewed", lambda: reviewed)
    monkeypatch.setattr(us_mapping_research, "_relation_available_at",
        lambda _reviewed: (datetime(2026, 10, 1, 0, 0, tzinfo=HK), None))

    data_root = tmp_path / "synthetic-owner-data"
    owner = ResearchPeripheralStore(data_root)
    owner.publish(_synthetic_us_payload("20261002", {"LITE": 5.125}))
    owner.publish(_synthetic_us_payload("20261005", {"AVGO": 2.75}))
    reader = ResearchPeripheralUsMarketReader(data_root)
    master = tmp_path / "security-master"
    master.mkdir()
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path / "manager-owner"), None, None,
        existing_research_source=None, workspace_security_master_root=master,
        workspace_us_market_reader=reader,
    )
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    try:
        with TestClient(app) as client:
            first = service.refresh_us_mapping_research("20261005", now=datetime(2026, 10, 5, 9, 27, tzinfo=HK))
            first_read = client.get("/api/v4/manager/research/workspace?date=20261005&view=historical")
            second = service.refresh_us_mapping_research("20261006", now=datetime(2026, 10, 6, 9, 27, tzinfo=HK))
            second_read = client.get("/api/v4/manager/research/workspace?date=20261006&view=dynamic")
        assert first_read.status_code == second_read.status_code == 200
        first_projection = first_read.json()["us_mapping_research"]["daily_run"]
        second_projection = second_read.json()["us_mapping_research"]["daily_run"]
        assert first["status"] == second["status"] == "COMPLETED"
        assert first["target_trade_date"] == "20261005" and first["us_session_date"] == "20261002"
        assert [(row["us_symbol"], row["hk_symbol"], row["change_pct"]) for row in first["matches"]] == [
            ("LITE", "HK.06166", 5.125)]
        assert second["target_trade_date"] == "20261006" and second["us_session_date"] == "20261005"
        assert [(row["us_symbol"], row["hk_symbol"], row["change_pct"]) for row in second["matches"]] == [
            ("AVGO", "HK.06088", 2.75)]
        assert first_projection["matches"] == first["matches"]
        assert second_projection["matches"] == second["matches"]
        assert first_projection["run_id"] == first["run_id"]
        assert second_projection["run_id"] == second["run_id"]
        assert all(row["target_date_eligibility"] == "CANNOT_CONFIRM" for row in first["matches"] + second["matches"])
    finally:
        service.close()
