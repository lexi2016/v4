from __future__ import annotations

from copy import deepcopy
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


def test_current_relation_overlay_preserves_actual_owner_payload_sha(tmp_path):
    from v4.manager_research.us_mapping_research import (
        CURRENT_RELATION_EVIDENCE_PATH,
        attach_current_relation_evidence,
    )
    from v4.manager_research.us_market_bridge import project_us_market

    service = _isolated_service(tmp_path)
    cutoff = "2026-09-30T09:27:30+08:00"
    bridge = project_us_market(
        service._workspace_us_market_reader, "20260930", {"research_cutoff": cutoff}
    )
    bridge_identity = bridge["source_identity"]
    assert bridge_identity["owner"] == "ResearchPeripheralStore"
    assert bridge_identity["status"] == "VERIFIED"
    bridge_sha = bridge_identity["payload_sha256"]

    artifact = json.loads(CURRENT_RELATION_EVIDENCE_PATH.read_bytes())
    body_shas = {
        source["source_body_sha256"]
        for card in artifact["relations"]
        for source in card["sources"]
    }
    assert body_shas
    assert bridge_sha not in body_shas

    result = attach_current_relation_evidence(bridge)
    overlay = result["relation_evidence"]
    assert overlay["current_bridge_source_payload_sha256"] == bridge_sha
    later_cutoff = "2026-09-30T09:27:31+08:00"
    later = attach_current_relation_evidence({**bridge, "research_cutoff": later_cutoff})
    assert later["research_cutoff"] == later_cutoff
    assert overlay["assessment_identity"] == later["relation_evidence"]["assessment_identity"]
    assert overlay["post_cutoff_relation_count"] == later["relation_evidence"]["post_cutoff_relation_count"]
    assert overlay["current_bridge_source_payload_sha256"] == later["relation_evidence"]["current_bridge_source_payload_sha256"]
    assert overlay["artifact_sha256"] is None
    assert all(source["relation_source"] != "CURRENT_REVIEWED_RELATION_EVIDENCE"
               for source in overlay["relation_source_artifacts"])


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
        "status": "READY", "target_trade_date": "20260930", "expected_us_session": "20260929", "research_cutoff": "2026-09-30T09:27:30+08:00",
        "coverage": {"requested_symbol_count": 33, "available_symbol_count": 33},
        "source_identity": {"status": "VERIFIED", "payload_sha256": "a" * 64,
            "receipt_sha256": "b" * 64, "manifest_sha256": "c" * 64},
        "raw_individual_up": [], "symbol_assessments": [], "gaps": [],
    }
    monkeypatch.setattr(us_market_bridge, "project_us_market", lambda *_args, **_kwargs: bridge)
    from v4.manager_research import us_mapping_research
    monkeypatch.setattr(us_mapping_research, "attach_current_relation_evidence",
        lambda value: {**value, "relation_evidence": {"status": "VERIFIED", "artifact_sha256": "d" * 64,
            "assessment_identity": "f" * 64, "reviewed_seed_relation_count": 1,
            "mapped_us_symbol_count": 0, "eligible_relation_count": 1, "gaps": []}})
    service = SimpleNamespace(store=ManagerResearchStore(tmp_path / "state"), _workspace_us_market_reader=object())
    result = build_daily_run(service, "20260930", now=datetime(2026, 9, 30, 9, 27, 30, tzinfo=HK))
    assert result["status"] == "VALID_EMPTY"
    assert result["matches"] == []
    assert result["coverage"]["matched_us_symbol_count"] == 0
    assert result["coverage"]["matched_hk_relation_count"] == 0


def test_partial_coverage_keeps_valid_same_session_daily_mapping_rows(tmp_path, monkeypatch):
    from v4.manager_research import us_market_bridge, us_mapping_research

    bridge = {
        "status": "PARTIAL", "target_trade_date": "20260930", "mapping_eligible": True,
        "expected_us_session": "20260929", "research_cutoff": "2026-09-30T09:27:30+08:00",
        "coverage": {"requested_symbol_count": 33, "available_symbol_count": 1,
            "assessed_symbol_count": 1, "unassessed_symbol_count": 32, "status": "PARTIAL",
            "gaps": ["US_CONFIGURED_SYMBOL_QUOTE_COVERAGE_INCOMPLETE"]},
        "source_identity": {"status": "VERIFIED", "payload_sha256": "a" * 64,
            "receipt_sha256": "b" * 64, "manifest_sha256": "c" * 64},
        "raw_individual_up": [{"symbol": "NVDA", "change_pct": 2.1, "session_date": "20260929"}],
        "symbol_assessments": [{"symbol": "NVDA", "instrument_classification": "EQUITY_PROXY",
            "relation_assessment_status": "NOT_EVALUATED", "relation_count": None,
            "relations": [], "relation_gaps": []}],
        "gaps": ["US_CONFIGURED_SYMBOL_QUOTE_COVERAGE_INCOMPLETE"],
    }
    relation = {"us_symbol": "NVDA", "hk_symbol": "HK.01234", "hk_name": "测试公司",
        "research_priority": "PRIORITY", "relationship_type": "DIRECT_NAMED_COMPONENT_SUPPLY",
        "reason": "TEST_FIXTURE", "maturity": "TEST_FIXTURE", "limitations": ["synthetic fixture"],
        "official_sources": []}
    reviewed = {"schema_version": "TEST_FIXTURE", "artifact_sha256": "d" * 64,
        "cards": [{**relation, "daily_match_symbols": ["NVDA"]}]}
    monkeypatch.setattr(us_market_bridge, "project_us_market", lambda *_args, **_kwargs: bridge)
    seed_availability = {"registry_file_sha256": "e" * 64, "registry_artifact_sha256": "f" * 64,
        "registry_schema_version": "TEST_FIXTURE", "availability_basis": "TEST_FIXTURE",
        "availability_scope": "TEST_FIXTURE", "release_id": "TEST_FIXTURE",
        "release_manifest_sha256": "1" * 64, "deployment_receipt_sha256": "2" * 64,
        "available_at": "2026-09-29T09:00:00+08:00", "seed_file_sha256": "3" * 64,
        "source_report_sha256": "4" * 64}
    monkeypatch.setattr(us_mapping_research, "_read_reviewed", lambda: reviewed)
    monkeypatch.setattr(us_mapping_research, "_relation_availability_details",
        lambda _reviewed: (datetime(2026, 9, 29, 9, 0, tzinfo=HK), None, seed_availability))
    service = SimpleNamespace(store=ManagerResearchStore(tmp_path / "state"), _workspace_us_market_reader=object())

    result = build_daily_run(service, "20260930", now=datetime(2026, 9, 30, 9, 27, 30, tzinfo=HK))

    assert result["status"] == "PARTIAL"
    assert result["source_status"] == "PARTIAL"
    assert result["coverage"]["configured_us_universe_count"] == 33
    assert result["coverage"]["available_us_universe_count"] == 1
    assert result["coverage"]["matched_us_symbol_count"] == 1
    assert result["coverage"]["matched_hk_relation_count"] == 1
    assert [(row["us_symbol"], row["hk_symbol"], row["session_date"]) for row in result["matches"]] == [
        ("NVDA", "HK.01234", "20260929")]
    assert "US_CONFIGURED_SYMBOL_QUOTE_COVERAGE_INCOMPLETE" in result["gaps"]


def test_scheduled_cycle_api_runs_through_injected_reader_and_rejects_wrong_binding(tmp_path, monkeypatch):
    service = _isolated_service(tmp_path)
    app_root = Path(__file__).resolve().parents[1]
    state = Path(service.store.root)
    master = Path(service._workspace_security_master_root)
    binding = {
        "enabled": True,
        "policy": "BALANCED_V1",
        "priority_codes": [],
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
    announcement_owner_calls = []
    announcement_schedules = []
    def refresh_announcements(date, *, schedule=None):
        announcement_owner_calls.append(date)
        announcement_schedules.append(schedule)
        return {
            "status": "PARTIAL", "target_trade_date": date,
            "daily_publication_date": date, "count_known": True,
            "gaps": ["OFFICIAL_DIRECTORY_SERVER_PAGINATION_EXHAUSTION_UNVERIFIED"],
            "attempt": {"state": "PARTIAL", "run_id": "d" * 32,
                        "started_at": "2026-09-30T09:27:30+08:00"},
            "coverage": {"publication_date": date, "observed_document_count": 1,
                         "directory_exhaustion": "UNVERIFIED",
                         "all_official_announcements_captured": False},
            "RESEARCH_ONLY": True, "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False,
        }
    service.refresh_announcements = refresh_announcements

    from apps.api.v35_api.manager_research_router import create_manager_research_router
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    digest = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    with TestClient(app) as client:
        response = client.post(
            f"/api/v4/manager/research/workspace/scheduled-cycle?date=20260930&binding_sha256={digest}",
            content=b"",
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["target_trade_date"] == "20260930"
        assert result["hkex_announcement_refresh"]["capture_target_date"] == "20260930"
        assert result["hkex_announcement_refresh"]["plan_target_date"] == "20260930"
        assert result["hkex_announcement_refresh"]["status"] == "PARTIAL"
        assert result["hkex_announcement_refresh"]["network_requests"] is None
        assert announcement_owner_calls == ["20260930"]
        schedule = announcement_schedules[0]
        assert schedule["policy"] == "BALANCED_V1"
        assert schedule["now"] == "2026-09-30T09:27:30+08:00"
        assert schedule["execution_identity"]["source_trade_date"] == "20260930"
        assert schedule["execution_identity"]["plan_target_date"] == "20260930"
        assert result["us_mapping_research"]["status"] == "PARTIAL"
        assert result["us_mapping_research"]["coverage"]["matched_hk_relation_count"] is None
        assert read_workspace_mapping(service, "20260930")["daily_run"]["matches"] == []
        workspace = client.get("/api/v4/manager/research/workspace?date=20260930&view=historical")
        assert workspace.status_code == 200
        assert announcement_owner_calls == ["20260930"]
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
        assert announcement_owner_calls == ["20260930"]
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
    seed_availability = {"registry_file_sha256": "e" * 64, "registry_artifact_sha256": "f" * 64,
        "registry_schema_version": "TEST_FIXTURE", "availability_basis": "TEST_FIXTURE",
        "availability_scope": "TEST_FIXTURE", "release_id": "TEST_FIXTURE",
        "release_manifest_sha256": "1" * 64, "deployment_receipt_sha256": "2" * 64,
        "available_at": "2026-10-01T00:00:00+08:00", "seed_file_sha256": "3" * 64,
        "source_report_sha256": "4" * 64}
    monkeypatch.setattr(us_mapping_research, "_relation_availability_details",
        lambda _reviewed: (datetime(2026, 10, 1, 0, 0, tzinfo=HK), None, seed_availability))

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
        assert second_projection["status"] == "CANNOT_CONFIRM"
        assert second_projection["current_context_compatibility"] == "CANNOT_CONFIRM"
        assert second_projection["status"] == "CANNOT_CONFIRM"
        assert second_projection["matches"] == []
        assert second_projection["saved_product_match_count"] == 1
        assert first_projection["run_id"] == first["run_id"]
        assert second_projection["run_id"] == second["run_id"]
        assert all(row["target_date_eligibility"] == "CANNOT_CONFIRM" for row in first["matches"] + second["matches"])
    finally:
        service.close()


def test_current_bridge_assesses_every_configured_symbol_and_keeps_etfs_separate():
    from v4.manager_research.us_market_bridge import project_us_market

    class Reader:
        def read_exact_session(self, session_date):
            assert session_date == "20261009"
            return _synthetic_us_payload(session_date, {"AMD": 1.25, "NVDA": -0.75}), {
                "status": "VERIFIED", "payload_sha256": "a" * 64,
                "receipt_sha256": "b" * 64, "manifest_sha256": "c" * 64,
            }

    market = project_us_market(Reader(), "20261009", {
        "research_cutoff": "2026-10-11T09:15:00+08:00",
    })
    rows = {row["symbol"]: row for row in market["symbol_assessments"]}
    assert market["status"] == "READY"
    assert len(rows) == 33
    assert market["coverage"]["requested_symbol_count"] == 33
    assert market["coverage"]["assessed_symbol_count"] == 33
    assert rows["AMD"]["quote_status"] == "VERIFIED"
    assert rows["AMD"]["direction"] == "UP"
    assert rows["NVDA"]["direction"] == "DOWN"
    assert rows["SOXX"]["instrument_classification"] == "ETF_PROXY"
    assert rows["SOXX"]["relation_count"] is None
    assert all(row["relation_count"] is None for row in rows.values())
    assert all(row["target_date_eligibility"] == "CANNOT_CONFIRM" for row in rows.values())


def test_TEST_FIXTURE_candidate_primary_relations_share_current_bridge_cutoff_and_remain_retrospective():
    from v4.manager_research.us_market_bridge import project_us_market
    from v4.manager_research.us_mapping_research import (
        CURRENT_RELATION_EVIDENCE_PATH, CURRENT_RELATION_REVIEW_PATH, attach_current_relation_evidence,
    )
    from v4.manager_research.workspace_projection import timestamp

    class Reader:
        def read_exact_session(self, session_date):
            assert session_date == "20261009"
            return _synthetic_us_payload(session_date, {"AMD": 1.25, "NVDA": -0.75}), {
                "status": "VERIFIED", "payload_sha256": "a" * 64,
                "receipt_sha256": "b" * 64, "manifest_sha256": "c" * 64,
            }

    reader = Reader()
    old_cutoff_context = {"research_cutoff": "2026-10-11T01:36:30+08:00"}
    current_artifact = json.loads(CURRENT_RELATION_EVIDENCE_PATH.read_bytes())
    current_review = json.loads(CURRENT_RELATION_REVIEW_PATH.read_bytes())
    latest_capture = max(
        [timestamp(card["available_at"]) for card in current_artifact["relations"]]
        + [timestamp(item["available_at"]) for item in current_artifact.get("symbol_assessments", [])]
    )
    reviewed_at = timestamp(current_review["reviewed_at"])
    fresh_cutoff_context = {"research_cutoff": (max(latest_capture, reviewed_at) + timedelta(seconds=1)).isoformat()}
    old_market = project_us_market(reader, "20261009", old_cutoff_context)
    fresh_market = project_us_market(reader, "20261009", fresh_cutoff_context)
    assert old_market["expected_us_session"] == fresh_market["expected_us_session"] == "20261009"
    assert old_market["source_identity"]["payload_sha256"] == fresh_market["source_identity"]["payload_sha256"]

    old_projection = attach_current_relation_evidence(old_market)
    fresh_projection = attach_current_relation_evidence(fresh_market)
    old_rows = {row["symbol"]: row for row in old_projection["symbol_assessments"]}
    fresh_rows = {row["symbol"]: row for row in fresh_projection["symbol_assessments"]}
    assert old_projection["relation_evidence"]["status"] == "PARTIAL_SOURCE_EVIDENCE_COVERAGE"
    assert old_projection["relation_evidence"]["eligible_relation_count"] == 4
    assert old_projection["relation_evidence"]["post_cutoff_relation_count"] == 10
    assert old_rows["NVDA"]["relation_count"] is None
    assert {
        (row["symbol"], relation["hk_symbol"])
        for row in old_rows.values() for relation in row["relations"]
    } == {
        ("LITE", "HK.06166"), ("COHR", "HK.06166"),
        ("AVGO", "HK.06088"), ("CIEN", "HK.00763"),
    }
    assert fresh_projection["relation_evidence"]["status"] == "PARTIAL_SOURCE_EVIDENCE_COVERAGE"
    assert fresh_projection["relation_evidence"]["eligible_relation_count"] == 14
    assert fresh_projection["relation_evidence"]["reviewed_seed_relation_count"] == 4
    assert fresh_projection["relation_evidence"]["current_reviewed_relation_count"] == 10
    assert fresh_projection["relation_evidence"]["withheld_candidate_count"] == 0
    # Crossing a recorded source/review availability boundary changes the
    # eligible relations and therefore remains a distinct semantic identity.
    assert (
        old_projection["relation_evidence"]["assessment_identity"]
        != fresh_projection["relation_evidence"]["assessment_identity"]
    )
    assert fresh_rows["NVDA"]["relation_count"] == 5
    assert fresh_rows["AMD"]["relation_count"] == 1
    assert {(relation["us_symbol"], relation["hk_symbol"])
        for row in fresh_rows.values() for relation in row["relations"]} == {
            ("LITE", "HK.06166"), ("COHR", "HK.06166"),
            ("AVGO", "HK.06088"), ("CIEN", "HK.00763"),
            ("NVDA", "HK.00992"), ("AMD", "HK.00992"), ("NVDA", "HK.01211"),
        ("NVDA", "HK.09868"), ("NVDA", "HK.02015"), ("NVDA", "HK.01810"),
        ("DLR", "HK.06823"), ("EQIX", "HK.09988"),
        ("STX", "HK.00992"), ("VRT", "HK.00992"),
        }
    assert fresh_rows["SOXX"]["relation_assessment_status"] == "ETF_THEME_PROXY_ONLY"
    assert fresh_rows["SOXX"]["relation_count"] is None
    assert all(row["target_date_eligibility"] == "CANNOT_CONFIRM" for row in fresh_rows.values())
    assert all(relation["evidence_timing"] == "RETROSPECTIVE_AFTER_TARGET_DATE"
        for row in fresh_rows.values() for relation in row["relations"]
        if relation["relation_source"] == "CURRENT_REVIEWED_RELATION_EVIDENCE")
    assert all(relation["evidence_review_status"] == (
        "INDEPENDENT_SEMANTIC_REVIEW_PASS_BODY_REHASH_CANNOT_CONFIRM"
    ) for row in fresh_rows.values() for relation in row["relations"]
        if relation["relation_source"] == "CURRENT_REVIEWED_RELATION_EVIDENCE")


def test_current_actual_owner_projection_merges_available_seed_and_reviewed_relations_by_cutoff():
    """Actual exact-session owner input; relation semantics remain research-only."""
    from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader, project_us_market
    from v4.manager_research.us_mapping_research import (
        CURRENT_RELATION_EVIDENCE_PATH, CURRENT_RELATION_REVIEW_PATH, attach_current_relation_evidence,
    )
    from v4.manager_research.workspace_projection import timestamp

    owner_root = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data")
    if not (owner_root / "research/peripherals/20261009/external_finance.json").is_file():
        pytest.skip("exact current US owner session 20261009 unavailable")
    reader = ResearchPeripheralUsMarketReader(owner_root)
    expected_pairs = {
        ("LITE", "HK.06166"), ("COHR", "HK.06166"), ("AVGO", "HK.06088"), ("CIEN", "HK.00763"),
        ("NVDA", "HK.00992"), ("AMD", "HK.00992"), ("NVDA", "HK.09868"),
        ("NVDA", "HK.01810"), ("NVDA", "HK.01211"), ("NVDA", "HK.02015"),
        ("DLR", "HK.06823"), ("EQIX", "HK.09988"),
        ("STX", "HK.00992"), ("VRT", "HK.00992"),
    }
    relation_artifact = json.loads(CURRENT_RELATION_EVIDENCE_PATH.read_bytes())
    review_receipt = json.loads(CURRENT_RELATION_REVIEW_PATH.read_bytes())
    latest_capture = max(
        [timestamp(card["available_at"]) for card in relation_artifact["relations"]]
        + [timestamp(item["available_at"]) for item in relation_artifact.get("symbol_assessments", [])]
    )
    reviewed_at = timestamp(review_receipt["reviewed_at"])

    def project(cutoff):
        bridge = project_us_market(reader, "20261009", {"research_cutoff": cutoff})
        assert bridge["status"] == "READY"
        assert bridge["expected_us_session"] == "20261009"
        assert bridge["source_identity"]["payload_sha256"] == (
            "928cd4ae8089a792ea1a3cfab490c9217c4249d6c29c11aeaa9cee879f0fb4e3"
        )
        return attach_current_relation_evidence(bridge)

    fresh = project((max(latest_capture, reviewed_at) + timedelta(seconds=1)).isoformat())
    fresh_rows = {row["symbol"]: row for row in fresh["symbol_assessments"]}
    fresh_pairs = {
        (relation["us_symbol"], relation["hk_symbol"])
        for row in fresh_rows.values() for relation in row["relations"]
    }
    assert len(fresh_rows) == 33
    assert fresh["relation_evidence"]["eligible_relation_count"] == 14
    assert fresh["relation_evidence"]["mapped_us_symbol_count"] == 10
    assert fresh["relation_evidence"]["configured_equity_symbol_count"] == 12
    assert fresh["relation_evidence"]["explicitly_assessed_equity_symbol_count"] == 12
    assert fresh["relation_evidence"]["equity_assessment_coverage_complete"] is True
    assert fresh_pairs == expected_pairs
    assert fresh_rows["SOXX"]["instrument_classification"] == "ETF_PROXY"
    assert fresh_rows["SOXX"]["relation_assessment_status"] == "ETF_THEME_PROXY_ONLY"
    assert fresh_rows["SOXX"]["relation_count"] is None
    old_pairs = {
        (relation["us_symbol"], relation["hk_symbol"])
        for row in fresh_rows.values() for relation in row["relations"]
        if relation.get("relation_source") == "RELEASE_PINNED_REVIEWED_SEED"
    }
    new_relations = [relation for row in fresh_rows.values() for relation in row["relations"]
                     if relation.get("relation_source") == "CURRENT_REVIEWED_RELATION_EVIDENCE"]
    assert old_pairs == {
        ("LITE", "HK.06166"), ("COHR", "HK.06166"),
        ("AVGO", "HK.06088"), ("CIEN", "HK.00763"),
    }
    assert len(new_relations) == 10
    assert {relation["us_symbol"] for relation in new_relations
            if relation.get("reviewer_identity_evidence")} == {"AMD", "DLR", "STX", "VRT"}
    for symbol in ("AMD", "DLR", "STX", "VRT"):
        identity = next(relation["reviewer_identity_evidence"] for relation in new_relations
                        if relation["us_symbol"] == symbol)
        assert identity["identity_status"] == "VERIFIED"
        assert identity["source_body_sha256"] is None
        assert identity["source_body_sha256_status"] == "CANNOT_CONFIRM"
    equities = [row for row in fresh_rows.values() if row["instrument_classification"] == "EQUITY_PROXY"]
    etfs = [row for row in fresh_rows.values() if row["instrument_classification"] == "ETF_PROXY"]
    assert len(equities) == 12
    assert len(etfs) == 21
    assert len(equities) + len(etfs) == 33
    assert all(row["instrument_classification"] in {"EQUITY_PROXY", "ETF_PROXY"}
               for row in fresh_rows.values())
    assert all(row["relations"] or row["relation_assessment_status"] == "ASSESSED_WITH_GAPS"
               for row in equities)
    assert fresh_rows["MU"]["relation_assessment_evidence"]["conclusion"] == "CANNOT_CONFIRM"
    assert fresh_rows["WDC"]["relation_assessment_evidence"]["conclusion"] == "CANNOT_CONFIRM"
    assert all(relation["evidence_review_status"] == (
        "INDEPENDENT_SEMANTIC_REVIEW_PASS_BODY_REHASH_CANNOT_CONFIRM"
    ) for relation in new_relations)
    assert all(relation["http_body_rehash_status"] == "CANNOT_CONFIRM" for relation in new_relations)
    assert all(relation["evidence_timing"] == "RETROSPECTIVE_AFTER_TARGET_DATE" for relation in new_relations)
    assert all(relation["target_date_eligibility"] == "CANNOT_CONFIRM"
               for row in fresh_rows.values() for relation in row["relations"])

    before_review = project((reviewed_at - timedelta(seconds=1)).isoformat())
    before_review_rows = {row["symbol"]: row for row in before_review["symbol_assessments"]}
    before_review_pairs = {
        (relation["us_symbol"], relation["hk_symbol"])
        for row in before_review_rows.values() for relation in row["relations"]
    }
    assert before_review["relation_evidence"]["eligible_relation_count"] == 4
    assert before_review["relation_evidence"]["post_cutoff_relation_count"] == 0
    assert before_review["relation_evidence"]["post_cutoff_review_count"] == 10
    assert before_review_pairs == old_pairs

    historical = project("2026-10-11T01:36:30+08:00")
    historical_rows = {row["symbol"]: row for row in historical["symbol_assessments"]}
    historical_pairs = {
        (relation["us_symbol"], relation["hk_symbol"])
        for row in historical_rows.values() for relation in row["relations"]
    }
    assert historical["relation_evidence"]["eligible_relation_count"] == 4
    assert historical["relation_evidence"]["post_cutoff_relation_count"] == 10
    assert historical["relation_evidence"]["mapped_us_symbol_count"] == 4
    assert historical_pairs == old_pairs
    assert all(relation["relation_source"] == "RELEASE_PINNED_REVIEWED_SEED"
               for row in historical_rows.values() for relation in row["relations"])


def test_current_relation_overlay_is_bound_to_current_session_and_post_target_timing(tmp_path, monkeypatch):
    from v4.manager_research.contracts import sha256_json
    from v4.manager_research.us_mapping_research import attach_current_relation_evidence

    retrieved = "2026-10-11T01:00:00Z"
    card = {
        "hk_symbol": "HK.00992", "hk_code": "00992", "hk_name": "Lenovo Group Limited",
        "us_symbol": "AMD", "relationship_type": "TEST_FIXTURE_DOCUMENTED_COMPONENT_OPTION",
        "direction": "TEST_FIXTURE_HK_BUYER_CAN_SELECT_US_COMPONENT_OPTION",
        "reason": "TEST_FIXTURE relation statement for a generic current relation category.",
        "maturity": "TEST_FIXTURE_RESEARCH_ONLY",
        "limitations": ["TEST_FIXTURE; no product or issuer relationship is asserted."],
        "available_at": retrieved,
        "sources": [
            {"role": "RELATION", "title": "TEST_FIXTURE relation source", "url": "https://example.com/relation",
             "published_at": None, "excerpt": "TEST_FIXTURE source has no publication date.",
             "source_body_sha256": "d" * 64, "retrieval_started_at": "2026-10-11T00:59:59Z",
             "retrieved_at": retrieved, "http_status": 200, "source_locator": "TEST_FIXTURE"},
            {"role": "HK_LISTING_IDENTITY", "title": "TEST_FIXTURE listing identity", "url": "https://example.com/listing",
             "published_at": "UNKNOWN", "excerpt": "TEST_FIXTURE listing identity.",
             "source_body_sha256": "e" * 64, "retrieval_started_at": "2026-10-11T00:59:59Z",
             "retrieved_at": retrieved, "http_status": 200, "source_locator": "TEST_FIXTURE"},
        ],
    }
    artifact = {
        "schema_version": "v4.manager_research.us_mapping_relation_evidence.v1",
        "source_hash_algorithm": "SHA256_HTTP_RESPONSE_BODY_BYTES", "relations": [card],
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    artifact["artifact_sha256"] = sha256_json(artifact)
    path = tmp_path / "relation-evidence.json"
    path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
    from v4.manager_research import us_mapping_research
    monkeypatch.setattr(us_mapping_research, "CURRENT_RELATION_EVIDENCE_PATH", path)
    review = {
        "schema_version": "v4.manager_research.us_mapping_relation_evidence_review.v1",
        "status": "PASS",
        "reviewer_identity": "/root/us_mapping_completion_review",
        "reviewed_at": "2026-10-11T09:10:00+08:00",
        "evidence_path": "v4/manager_research/us_mapping_relation_evidence_20261011.json",
        "evidence_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "declared_artifact_sha256": artifact["artifact_sha256"],
        "recomputed_artifact_sha256": artifact["artifact_sha256"],
        "reviewed_pairs": [{
            "us_symbol": card["us_symbol"], "hk_symbol": card["hk_symbol"],
            "relationship_type": card["relationship_type"], "direction": card["direction"],
        } for card in artifact["relations"]],
        "reviewed_scope": "TEST_FIXTURE single relation",
        "limitations": ["TEST_FIXTURE; HTTP body rehash is not confirmed."],
        "CANNOT_CONFIRM": ["HTTP response body byte provenance."],
        "http_body_rehash_status": "CANNOT_CONFIRM",
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                   "buy_gate_updated": False, "orders_sent": False},
        "us_symbol_identity_evidence": {
            "identity_status": "VERIFIED", "us_symbol": "AMD",
            "issuer": "Advanced Micro Devices, Inc.",
            "exchange": "The NASDAQ Global Select Market",
            "url": "https://ir.amd.com/financial-information/sec-filings/content/test",
            "published_at": "2026-02-04", "retrieved_at": "2026-10-11T09:10:00+08:00",
            "source_locator": "Securities registered pursuant to Section 12(b), test fixture.",
            "source_body_sha256": None, "source_body_sha256_status": "CANNOT_CONFIRM",
        },
    }
    review_path = tmp_path / "relation-review.json"
    review_path.write_text(json.dumps(review, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(us_mapping_research, "CURRENT_RELATION_REVIEW_PATH", review_path)
    monkeypatch.setattr(us_mapping_research, "CURRENT_RELATION_REVIEW_RECEIPT_SHA256",
                        hashlib.sha256(review_path.read_bytes()).hexdigest())
    market = {
        "target_trade_date": "20261009", "expected_us_session": "20261009",
        "research_cutoff": "2026-10-11T09:15:00+08:00",
        "source_identity": {"status": "VERIFIED", "payload_sha256": "a" * 64},
        "symbol_assessments": [{"symbol": "AMD", "instrument_classification": "EQUITY_PROXY",
            "quote_status": "VERIFIED", "quote_evidence": {"session_date": "20261009",
                "source_payload_sha256": "a" * 64}, "relation_count": None, "relations": []}],
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    result = attach_current_relation_evidence(market)
    row = result["symbol_assessments"][0]
    assert row["relation_count"] == 1
    assert row["relations"][0]["evidence_timing"] == "RETROSPECTIVE_AFTER_TARGET_DATE"
    assert row["relations"][0]["target_date_eligibility"] == "CANNOT_CONFIRM"
    assert row["relations"][0]["relationship_type"] == "TEST_FIXTURE_DOCUMENTED_COMPONENT_OPTION"
    assert row["relations"][0]["sources"][0]["published_at"] is None
    assert row["relations"][0]["evidence_review_status"] == (
        "INDEPENDENT_SEMANTIC_REVIEW_PASS_BODY_REHASH_CANNOT_CONFIRM"
    )
    assert row["relations"][0]["reviewer_identity_evidence"]["identity_status"] == "VERIFIED"
    assert row["relations"][0]["http_body_rehash_status"] == "CANNOT_CONFIRM"
    assert result["relation_evidence"]["coverage_complete"] is False


def test_v2_symbol_assessments_bind_capture_status_hash_status_and_cutoff(tmp_path, monkeypatch):
    from v4.manager_research.contracts import sha256_json
    from v4.manager_research.us_mapping_research import attach_current_relation_evidence
    from v4.manager_research import us_mapping_research

    captured = "2026-10-11T01:10:00Z"
    relation = {
        "hk_symbol": "HK.06823", "hk_code": "06823", "hk_name": "HKT Trust and HKT Limited",
        "us_symbol": "DLR", "relationship_type": "TEST_FIXTURE_PLATFORM_RELATION",
        "direction": "TEST_FIXTURE_US_PLATFORM_PARTNER_TO_HK_GROUP",
        "reason": "TEST_FIXTURE bounded relationship statement.", "maturity": "TEST_FIXTURE_RESEARCH_ONLY",
        "limitations": ["TEST_FIXTURE; no target-date eligibility claim."], "available_at": captured,
        "sources": [
            {"role": "RELATION", "title": "TEST_FIXTURE relation", "url": "https://example.com/relation",
             "published_at": None, "excerpt": "TEST_FIXTURE relationship.", "source_body_sha256": "a" * 64,
             "retrieval_started_at": "2026-10-11T01:09:59Z", "retrieved_at": captured, "http_status": 200,
             "source_locator": "TEST_FIXTURE"},
            {"role": "HK_LISTING_IDENTITY", "title": "TEST_FIXTURE issuer identity", "url": "https://example.com/listing",
             "published_at": "UNKNOWN", "excerpt": "TEST_FIXTURE listing code.", "source_body_sha256": "b" * 64,
             "retrieval_started_at": "2026-10-11T01:09:59Z", "retrieved_at": captured, "http_status": 200,
             "source_locator": "TEST_FIXTURE"},
        ],
    }
    mu = {
        "us_symbol": "MU", "candidate_hk_code": "00992", "candidate_hk_symbol": "HK.00992",
        "status": "ASSESSED_WITH_GAPS", "conclusion": "CANNOT_CONFIRM",
        "assessment_scope": "TEST_FIXTURE_BOUNDED_SOURCE_CHECK", "reason": "TEST_FIXTURE source body unavailable.",
        "available_at": "2026-10-11T01:10:25Z", "limitations": ["TEST_FIXTURE; no body hash."],
        "sources": [
            {"role": "RELATION", "title": "TEST_FIXTURE web extraction", "url": "https://example.com/web",
             "published_at": None, "excerpt": "TEST_FIXTURE extracted text, not HTTP bytes.",
             "source_locator": "TEST_FIXTURE web extraction", "source_capture_status": "WEB_EXTRACTED_CONTENT_BODY_NOT_CAPTURED",
             "source_body_sha256": None, "source_body_sha256_status": "CANNOT_CONFIRM", "http_status": None,
             "retrieval_started_at": None, "retrieved_at": "2026-10-11T01:08:00Z"},
            {"role": "SOURCE_RETRIEVAL_ATTEMPT", "title": "TEST_FIXTURE failed direct GET", "url": "https://example.com/web",
             "published_at": None, "excerpt": "TEST_FIXTURE direct GET returned 429 without a response body.",
             "source_locator": "TEST_FIXTURE 429", "source_capture_status": "HTTP_429_NO_RESPONSE_BODY",
             "source_body_sha256": None, "source_body_sha256_status": "CANNOT_CONFIRM", "http_status": 429,
             "retrieval_started_at": "2026-10-11T01:10:24Z", "retrieved_at": "2026-10-11T01:10:25Z"},
        ],
    }
    wdc = {
        "us_symbol": "WDC", "candidate_hk_code": "00992", "candidate_hk_symbol": "HK.00992",
        "status": "ASSESSED_WITH_GAPS", "conclusion": "CANNOT_CONFIRM",
        "assessment_scope": "TEST_FIXTURE_BOUNDED_SOURCE_CHECK", "reason": "TEST_FIXTURE current vendor label is unresolved.",
        "available_at": "2026-10-11T01:10:28Z", "limitations": ["TEST_FIXTURE; abbreviation not expanded."],
        "sources": [
            {"role": "RELATION", "title": "TEST_FIXTURE current guide", "url": "https://example.com/current",
             "published_at": "2026-09-16", "excerpt": "TEST_FIXTURE current table says WDC.",
             "source_locator": "TEST_FIXTURE current table", "source_capture_status": "HTTP_RESPONSE_BODY_CAPTURED",
             "source_body_sha256": "c" * 64, "source_body_sha256_status": "VERIFIED_SHA256_HTTP_RESPONSE_BODY_BYTES",
             "http_status": 200, "retrieval_started_at": "2026-10-11T01:10:27Z", "retrieved_at": "2026-10-11T01:10:28Z"},
            {"role": "HISTORICAL_RELATION_CONTEXT", "title": "TEST_FIXTURE withdrawn guide", "url": "https://example.com/withdrawn",
             "published_at": None, "excerpt": "TEST_FIXTURE historical integration only.",
             "source_locator": "TEST_FIXTURE historical page", "source_capture_status": "WEB_EXTRACTED_WITHDRAWN_SOURCE_BODY_NOT_CAPTURED",
             "source_body_sha256": None, "source_body_sha256_status": "CANNOT_CONFIRM", "http_status": None,
             "retrieval_started_at": None, "retrieved_at": "2026-10-11T01:06:00Z"},
        ],
    }
    artifact = {
        "schema_version": "v4.manager_research.us_mapping_relation_evidence.v2",
        "source_hash_algorithm": "SHA256_HTTP_RESPONSE_BODY_BYTES",
        "relations": [relation], "symbol_assessments": [mu, wdc],
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    artifact["artifact_sha256"] = sha256_json(artifact)
    artifact_path = tmp_path / "relation-evidence-v2.json"
    artifact_path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(us_mapping_research, "CURRENT_RELATION_EVIDENCE_PATH", artifact_path)
    review = {
        "schema_version": "v4.manager_research.us_mapping_relation_evidence_review.v2",
        "status": "PASS", "reviewer_identity": "/root/us_mapping_completion_review",
        "reviewed_at": "2026-10-11T10:20:00+08:00",
        "evidence_path": "v4/manager_research/us_mapping_relation_evidence_20261011.json",
        "evidence_file_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "declared_artifact_sha256": artifact["artifact_sha256"],
        "recomputed_artifact_sha256": artifact["artifact_sha256"],
        "reviewed_pairs": [{"us_symbol": relation["us_symbol"], "hk_symbol": relation["hk_symbol"],
            "relationship_type": relation["relationship_type"], "direction": relation["direction"]}],
        "reviewed_symbol_assessments": [{"us_symbol": x["us_symbol"], "candidate_hk_code": x["candidate_hk_code"],
            "status": x["status"], "conclusion": x["conclusion"], "assessment_sha256": sha256_json(x)}
            for x in artifact["symbol_assessments"]],
        "reviewed_scope": "TEST_FIXTURE relation and two assessed gaps",
        "limitations": ["TEST_FIXTURE body rehash not confirmed."],
        "CANNOT_CONFIRM": ["TEST_FIXTURE HTTP body provenance."],
        "http_body_rehash_status": "CANNOT_CONFIRM",
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
            "buy_gate_updated": False, "orders_sent": False},
        "us_symbol_identity_evidence": [{
            "identity_status": "VERIFIED", "us_symbol": "DLR",
            "issuer": "TEST_FIXTURE Digital Realty Trust, Inc.",
            "exchange": "TEST_FIXTURE NYSE",
            "url": "https://example.com/dlr-identity",
            "published_at": None, "retrieved_at": "2026-10-11T01:10:26Z",
            "source_locator": "TEST_FIXTURE exchange and issuer identity.",
            "source_capture_status": "TEST_FIXTURE_WEB_EXTRACTION",
            "source_body_sha256": None, "source_body_sha256_status": "CANNOT_CONFIRM",
        }],
    }
    review_path = tmp_path / "relation-review-v2.json"
    review_path.write_text(json.dumps(review, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(us_mapping_research, "CURRENT_RELATION_REVIEW_PATH", review_path)
    monkeypatch.setattr(us_mapping_research, "CURRENT_RELATION_REVIEW_RECEIPT_SHA256",
                        hashlib.sha256(review_path.read_bytes()).hexdigest())

    def market(cutoff):
        return {"target_trade_date": "20261009", "expected_us_session": "20261009",
            "research_cutoff": cutoff, "source_identity": {"status": "VERIFIED", "payload_sha256": "d" * 64},
            "symbol_assessments": [{"symbol": symbol, "instrument_classification": "EQUITY_PROXY",
                "quote_status": "VERIFIED", "quote_evidence": {"session_date": "20261009",
                    "source_payload_sha256": "d" * 64}, "relation_count": None, "relations": []}
                for symbol in ["DLR", "MU", "WDC"]],
            "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}

    current = attach_current_relation_evidence(market("2026-10-11T11:00:00+08:00"))
    current_rows = {row["symbol"]: row for row in current["symbol_assessments"]}
    assert current_rows["MU"]["relation_assessment_status"] == "ASSESSED_WITH_GAPS"
    assert current_rows["MU"]["relation_assessment_evidence"]["conclusion"] == "CANNOT_CONFIRM"
    mu_sources = current_rows["MU"]["relation_assessment_evidence"]["sources"]
    assert next(s for s in mu_sources if s["http_status"] == 429)["source_body_sha256"] is None
    assert current_rows["WDC"]["relation_assessment_evidence"]["available_at"] == "2026-10-11T10:20:00+08:00"
    assert current_rows["DLR"]["relations"][0]["reviewer_identity_evidence"]["us_symbol"] == "DLR"
    identity_sources = current_rows["DLR"]["relations"][0]["sources"]
    assert identity_sources[-1]["role"] == "US_SYMBOL_IDENTITY"
    assert identity_sources[-1]["source_capture_status"] == "TEST_FIXTURE_WEB_EXTRACTION"
    assert current["relation_evidence"]["configured_equity_symbol_count"] == 3
    assert current["relation_evidence"]["explicitly_assessed_equity_symbol_count"] == 3
    assert current["relation_evidence"]["equity_assessment_coverage_complete"] is True

    historical = attach_current_relation_evidence(market("2026-10-11T01:36:30+08:00"))
    historical_rows = {row["symbol"]: row for row in historical["symbol_assessments"]}
    assert historical["relation_evidence"]["post_cutoff_symbol_assessment_count"] == 2
    assert historical["relation_evidence"]["eligible_symbol_assessment_count"] == 0
    assert historical_rows["MU"]["relation_assessment_status"] == "ASSESSED_WITH_GAPS_NOT_AVAILABLE_BY_CUTOFF"
    assert historical_rows["MU"]["relation_count"] is None

    early_review = deepcopy(review)
    early_review["reviewed_at"] = "2026-10-11T01:10:27Z"
    review_path.write_text(json.dumps(early_review, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(us_mapping_research, "CURRENT_RELATION_REVIEW_RECEIPT_SHA256",
                        hashlib.sha256(review_path.read_bytes()).hexdigest())
    rejected = attach_current_relation_evidence(market("2026-10-11T11:00:00+08:00"))
    assert rejected["relation_evidence"]["current_reviewed_relation_count"] == 0
    assert "US_RELATION_REVIEW_RECEIPT_INVALID" in rejected["relation_evidence"]["gaps"]


def test_current_relation_overlay_keeps_post_cutoff_evidence_unknown(tmp_path, monkeypatch):
    from v4.manager_research.contracts import sha256_json
    from v4.manager_research.us_mapping_research import attach_current_relation_evidence

    retrieved = "2026-10-11T01:20:00Z"
    card = {
        "hk_symbol": "HK.00992", "hk_code": "00992", "hk_name": "Lenovo Group Limited",
        "us_symbol": "AMD", "relationship_type": "NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER",
        "direction": "HK_CUSTOMER_OR_INTEGRATOR_OF_US_TECHNOLOGY_PROVIDER",
        "reason": "Lenovo documents an AMD product integration.",
        "maturity": "PRODUCT_INTEGRATION_DOCUMENTED_AS_OF_PUBLISHED_DATE",
        "limitations": ["Does not establish current model mix or stock-price causality."],
        "available_at": retrieved,
        "sources": [
            {"role": "RELATION", "title": "Lenovo AMD AI PCs", "url": "https://news.lenovo.com/example",
             "published_at": "2025-10-21", "excerpt": "Powered by AMD Ryzen AI processors.",
             "source_body_sha256": "d" * 64, "retrieval_started_at": "2026-10-11T01:19:59Z",
             "retrieved_at": retrieved, "http_status": 200, "source_locator": "Press release"},
            {"role": "HK_LISTING_IDENTITY", "title": "Lenovo annual report", "url": "https://www1.hkexnews.hk/example.pdf",
             "published_at": "2025-05-22", "excerpt": "Stock code 00992.",
             "source_body_sha256": "e" * 64, "retrieval_started_at": "2026-10-11T01:19:59Z",
             "retrieved_at": retrieved, "http_status": 200, "source_locator": "Cover page"},
        ],
    }
    artifact = {"schema_version": "v4.manager_research.us_mapping_relation_evidence.v1",
        "source_hash_algorithm": "SHA256_HTTP_RESPONSE_BODY_BYTES", "relations": [card],
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    artifact["artifact_sha256"] = sha256_json(artifact)
    path = tmp_path / "relation-evidence.json"
    path.write_text(json.dumps(artifact, sort_keys=True), encoding="utf-8")
    from v4.manager_research import us_mapping_research
    monkeypatch.setattr(us_mapping_research, "CURRENT_RELATION_EVIDENCE_PATH", path)
    market = {"target_trade_date": "20261009", "expected_us_session": "20261009",
        "research_cutoff": "2026-10-11T09:15:00+08:00",
        "source_identity": {"status": "VERIFIED", "payload_sha256": "a" * 64},
        "symbol_assessments": [{"symbol": "AMD", "instrument_classification": "EQUITY_PROXY",
            "quote_status": "VERIFIED", "quote_evidence": {"session_date": "20261009",
                "source_payload_sha256": "a" * 64}, "relation_count": None, "relations": []}],
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    result = attach_current_relation_evidence(market)
    row = result["symbol_assessments"][0]
    assert row["relation_count"] is None
    assert row["relations"] == []
    assert result["relation_evidence"]["post_cutoff_relation_count"] == 1
    assert result["relation_evidence"]["status"] == "NOT_EVALUATED"


def test_daily_mapping_matches_only_the_current_bridge_session_and_payload_sha(monkeypatch):
    from v4.manager_research import us_mapping_research, workspace

    original = {"schema_version": "v4.manager_research.us_mapping_research.v1", "target_trade_date": "20261009",
        "daily_run": {"schema_version": "v4.manager_research.us_mapping_daily_run.v1", "status": "COMPLETED",
            "target_trade_date": "20261009", "us_session_date": "20261008", "generated_at": "2026-10-10T09:00:00+08:00",
            "source_identity": {"status": "VERIFIED", "payload_sha256": "a" * 64},
            "artifact_sha256": "b" * 64, "run_id": "run", "matches": [{"us_symbol": "CIEN"}], "gaps": []},
        "reviewed_research": None}
    monkeypatch.setattr(us_mapping_research, "read_workspace_mapping", lambda *_: deepcopy(original))
    context = {"research_cutoff": "2026-10-11T09:15:00+08:00"}
    current = {"expected_us_session": "20261009", "source_identity": {"payload_sha256": "c" * 64}}
    mapping, _, identities = workspace._daily_mapping_plan_reference(SimpleNamespace(), "20261009", context,
        current_us_market=current)
    daily = mapping["daily_run"]
    assert daily["current_context_compatibility"] == "STALE_INPUTS_CHANGED"
    assert daily["status"] == "CANNOT_CONFIRM"
    assert daily["matches"] == []
    assert daily["saved_product_match_count"] == 1
    assert daily["gaps"] == ["STALE_INPUTS_CHANGED"]
    assert identities == []


def test_stale_valid_empty_daily_mapping_keeps_zero_only_as_saved_product(monkeypatch):
    from v4.manager_research import us_mapping_research, workspace

    original = {"schema_version": "v4.manager_research.us_mapping_research.v1", "target_trade_date": "20261009",
        "daily_run": {"schema_version": "v4.manager_research.us_mapping_daily_run.v1", "status": "VALID_EMPTY",
            "target_trade_date": "20261009", "us_session_date": "20261008", "generated_at": "2026-10-10T09:00:00+08:00",
            "source_identity": {"status": "VERIFIED", "payload_sha256": "a" * 64},
            "artifact_sha256": "b" * 64, "run_id": "run-empty", "matches": [], "gaps": [],
            "coverage": {"reviewed_us_symbol_count": 4, "matched_us_symbol_count": 0,
                "matched_hk_relation_count": 0, "configured_us_universe_count": 33,
                "available_us_universe_count": 33, "full_market_coverage": False}},
        "reviewed_research": None}
    monkeypatch.setattr(us_mapping_research, "read_workspace_mapping", lambda *_: deepcopy(original))
    context = {"research_cutoff": "2026-10-11T09:15:00+08:00"}
    current = {"expected_us_session": "20261009", "source_identity": {"payload_sha256": "c" * 64}}

    mapping, _, identities = workspace._daily_mapping_plan_reference(SimpleNamespace(), "20261009", context,
        current_us_market=current)
    daily = mapping["daily_run"]

    assert daily["current_context_compatibility"] == "STALE_INPUTS_CHANGED"
    assert daily["status"] == "CANNOT_CONFIRM"
    assert daily["matches"] == []
    assert daily["saved_product_status"] == "VALID_EMPTY"
    assert daily["saved_product_match_count"] == 0
    assert daily["saved_product_us_session_date"] == "20261008"
    assert daily["saved_product_source_payload_sha256"] == "a" * 64
    assert daily["coverage"]["matched_us_symbol_count"] is None
    assert daily["coverage"]["matched_hk_relation_count"] is None
    assert daily["coverage"]["configured_us_universe_count"] == 33
    assert daily["coverage"]["available_us_universe_count"] == 33
    assert identities == []
