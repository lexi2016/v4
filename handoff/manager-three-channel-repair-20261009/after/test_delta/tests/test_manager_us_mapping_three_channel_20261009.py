"""Synthetic three-channel regressions through the original US and plan owners.

Only temporary source/store files are written. Prices and reviewed relations
are deliberately synthetic; none of these results reconstruct the 10/9 live
incident, prove a deployment, or authorize a natural-run/trading claim.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from threading import Event
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api import manager_research_router as api
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from infrastructure.scheduling import manager_announcement_supervisor as supervisor
from v4.manager_research import plan_owner_dispatch as dispatch
from v4.manager_research import us_mapping_research as mapping
from v4.manager_research import workspace
from v4.manager_research.contracts import sha256_json
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader
from v4.manager_research.workspace_projection import FLAGS, HK

from test_manager_us_mapping_research import _synthetic_us_payload


TARGET = "20261009"
SESSION = "20261008"


def _bytes(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def owner(tmp_path, monkeypatch):
    clock = {"now": datetime(2026, 10, 9, 7, 0, tzinfo=HK)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            current = clock["now"]
            return cls.fromtimestamp(current.timestamp(), tz) if tz else cls.fromtimestamp(current.timestamp())

    for module in (api, mapping, workspace):
        monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(dispatch, "clock_now", lambda: Clock.now(HK))
    monkeypatch.delenv("V4_MANAGER_VIBE_BINDING", raising=False)

    # The handoff lacks the two runtime relation JSON files. Exercise their
    # actual integrity/availability readers against explicitly synthetic files.
    seed = {
        "schema_version": "v4.manager_research.us_mapping_reviewed.v1",
        "target_trade_date": "20260930", "report": {"sha256": "b" * 64},
        "status": "SYNTHETIC_REGRESSION_ONLY", "cards": [
            {"daily_match_symbols": [symbol], "hk_symbol": f"HK.{index:05d}",
             "hk_name": f"Synthetic relation {index}",
             "relationship_type": "PRODUCT_PEER", "reason": "SYNTHETIC_REGRESSION_ONLY",
             "official_sources": [], "limitations": ["No historical or live evidence"]}
            for index, symbol in enumerate(("LITE", "AVGO", "COHR", "CIEN"), 1)
        ], **FLAGS,
    }
    seed["artifact_sha256"] = sha256_json(seed)
    seed_path = tmp_path / "synthetic-reviewed-relations.json"
    seed_path.write_text(json.dumps(seed, sort_keys=True), encoding="utf-8")
    registry = {
        "schema_version": "v4.manager_research.us_mapping_relation_registry.v1",
        "source_seed_sha256": hashlib.sha256(seed_path.read_bytes()).hexdigest(),
        "source_report_sha256": seed["report"]["sha256"],
        "available_at": "2026-10-01T00:00:00+08:00",
        "availability_basis": "V4_RELEASE_PUBLICATION", "release_id": "SYNTHETIC_REGRESSION_ONLY",
        "release_manifest_sha256": "c" * 64, "deployment_receipt_sha256": "d" * 64,
    }
    registry["artifact_sha256"] = sha256_json(registry)
    registry_path = tmp_path / "synthetic-relation-registry.json"
    registry_path.write_text(json.dumps(registry, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(mapping, "REVIEWED_PATH", seed_path)
    monkeypatch.setattr(mapping, "RELATION_REGISTRY_PATH", registry_path)

    source_root = tmp_path / "synthetic-us-owner"
    source = ResearchPeripheralStore(source_root)
    master = tmp_path / "synthetic-missing-hk-authority"
    master.mkdir()
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path / "isolated-manager-state"), None, None,
        existing_research_source=None, workspace_security_master_root=master,
        workspace_us_market_reader=ResearchPeripheralUsMarketReader(source_root),
    )
    application = FastAPI()
    application.include_router(api.create_manager_research_router(service))
    try:
        with TestClient(application) as client:
            yield service, source, client, clock
    finally:
        service.close()


def test_explicit_plan_action_materializes_valid_empty_daily_and_consumes_exact_run(owner):
    service, source, client, clock = owner
    source.publish(_synthetic_us_payload(SESSION, {}))
    reader = service._workspace_us_market_reader

    class AdvancingReader:
        def read_exact_session(self, session_date):
            result = reader.read_exact_session(session_date)
            clock["now"] += timedelta(seconds=2)
            return result

    service._workspace_us_market_reader = AdvancingReader()
    before_get = _bytes(service.store.root)
    initial = client.get("/api/v4/manager/research/workspace", params={"date": TARGET, "view": "dynamic"})
    assert initial.status_code == 200
    assert initial.json()["us_mapping_research"]["daily_run"]["status"] == "NOT_RUN"
    assert _bytes(service.store.root) == before_get

    response = client.post("/api/v4/manager/research/workspace/refresh", params={
        "date": TARGET, "selection_date": TARGET, "announcement_date": SESSION}, content=b"")
    assert response.status_code == 200, response.text
    value = response.json()
    daily = value["us_mapping_research"]["daily_run"]
    assert daily["status"] == "VALID_EMPTY"
    assert daily["us_session_date"] == SESSION
    assert daily["coverage"] == {
        "reviewed_us_symbol_count": 4, "matched_us_symbol_count": 0,
        "matched_hk_relation_count": 0, "configured_us_universe_count": 33,
        "available_us_universe_count": 33, "full_market_coverage": False}
    reference = value["owner_chain"]["us_mapping_daily_plan_reference"]
    assert reference["status"] == "CONSUMED"
    assert reference["run_id"] == daily["run_id"]
    assert reference["artifact_sha256"] == daily["artifact_sha256"]
    assert datetime.fromisoformat(reference["available_at"]) <= datetime.fromisoformat(reference["plan_cutoff"])
    assert value["plan_product"]["status"] == "CURRENT"
    assert value["plan_product"]["consumed"] is True
    assert value["store_latest_matches_http_plan_product"] is True

    saved_bytes = _bytes(service.store.root)
    readback = client.get("/api/v4/manager/research/workspace", params={
        "date": TARGET, "view": "dynamic", "selection_date": TARGET,
        "announcement_date": SESSION})
    assert readback.status_code == 200, readback.text
    saved = readback.json()
    assert saved["us_mapping_research"]["daily_run"]["run_id"] == daily["run_id"]
    assert saved["plan_product"]["run_id"] == value["plan_product"]["run_id"]
    assert saved["plan_product"]["status"] == "CURRENT"
    assert all(saved[key] is expected for key, expected in FLAGS.items())
    assert saved["plan_product"]["execution_context"]["natural_run_verified"] is False
    assert _bytes(service.store.root) == saved_bytes


def test_missing_us_input_is_recorded_without_blocking_original_plan_action(owner):
    service, _source, client, _clock = owner
    response = client.post("/api/v4/manager/research/workspace/refresh", params={"date": TARGET}, content=b"")
    assert response.status_code == 200, response.text
    value = response.json()
    daily = value["us_mapping_research"]["daily_run"]
    assert daily["status"] == "INPUT_MISSING"
    assert daily["coverage"]["matched_us_symbol_count"] is None
    assert daily["coverage"]["matched_hk_relation_count"] is None
    assert daily["latest_attempt"]["status"] == "INPUT_MISSING"
    assert daily["latest_attempt"]["execution_context"]["trigger_kind"] == "MANUAL"
    assert value["owner_chain"]["us_mapping_daily_plan_reference"]["status"] == "INPUT_MISSING"
    assert value["plan_product"]["status"] == "CURRENT"
    assert value["workspace_plan_attempt"]["state"] == "PARTIAL"
    assert {row["channel"] for row in value["daily_channels"]["channels"]} == {"ANNOUNCEMENT", "HK_CONNECT", "OVERSOLD"}
    assert service.get_workspace_plan(TARGET)["run_id"] == value["plan_product"]["run_id"]


@pytest.mark.parametrize("failure_type", [RuntimeError, ImportError])
def test_us_owner_exception_is_visible_while_independent_plan_materializes(owner, monkeypatch, failure_type):
    service, _source, client, _clock = owner

    def failed_owner(*_args, **_kwargs):
        raise failure_type("SYNTHETIC_OWNER_EXCEPTION_PRIVATE_DETAIL")

    monkeypatch.setattr(service, "refresh_us_mapping_research", failed_owner)
    response = client.post("/api/v4/manager/research/workspace/refresh", params={"date": TARGET}, content=b"")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["plan_product"]["status"] == "CURRENT"
    preparation = value["us_mapping_preparation"]
    assert preparation["status"] == "FAILED"
    assert preparation["execution_status"] == "US_MAPPING_OWNER_CALL_FAILED:" + failure_type.__name__
    assert preparation["run_id"] is None
    assert "SYNTHETIC_OWNER_EXCEPTION_PRIVATE_DETAIL" not in response.text


def test_future_target_plan_keeps_existing_behavior_without_running_us_owner(owner, monkeypatch):
    service, _source, client, _clock = owner
    monkeypatch.setattr(service, "refresh_us_mapping_research",
        lambda *_args, **_kwargs: pytest.fail("Future target must not run the US daily owner"))
    response = client.post("/api/v4/manager/research/workspace/refresh", params={"date": "20261012"}, content=b"")
    assert response.status_code == 200, response.text
    assert response.json()["plan_product"]["status"] == "CURRENT"
    assert response.json()["us_mapping_preparation"]["status"] == "FUTURE_TARGET_NOT_DUE"
    assert response.json()["us_mapping_preparation"]["execution_attempted"] is False
    assert service.store._io.files("us_mapping_dispatch/20261012") == []


@pytest.mark.parametrize("invalid_field", ["execution_status", "artifact_sha256"])
def test_preparation_rejects_unbounded_owner_diagnostic_without_exposing_it(owner, monkeypatch, invalid_field):
    service, _source, client, _clock = owner
    monkeypatch.setattr(service, "refresh_us_mapping_research", lambda *_args, **_kwargs: {
        "schema_version": mapping.DAILY_SCHEMA, "target_trade_date": TARGET,
        "status": "FAILED", "run_id": None,
        "execution_status": "US_MAPPING_OWNER_BUILD_FAILED",
        "gaps": [], **FLAGS,
        invalid_field: "SYNTHETIC private source body must not be copied"})
    response = client.post("/api/v4/manager/research/workspace/refresh", params={"date": TARGET}, content=b"")
    assert response.status_code == 200, response.text
    assert response.json()["us_mapping_preparation"]["execution_status"] == "US_MAPPING_OWNER_CALL_FAILED:ValueError"
    assert "SYNTHETIC private source body" not in response.text
    assert response.json()["plan_product"]["status"] == "CURRENT"


def test_real_timed_out_reader_is_not_reentered_by_plan_and_cannot_publish_late(owner):
    service, _source, client, clock = owner
    started, release, finished = Event(), Event(), Event()
    calls = []

    class BlockedReader:
        def read_exact_session(self, session_date):
            calls.append(session_date)
            started.set()
            try:
                assert release.wait(8)
                return None, {"status": "NOT_MATERIALIZED", "session_date": session_date}
            finally:
                finished.set()

    service._workspace_us_market_reader = BlockedReader()
    began = time.monotonic()
    try:
        response = client.post("/api/v4/manager/research/workspace/refresh", params={"date": TARGET}, content=b"")
        assert response.status_code == 200, response.text
        assert started.is_set()
        assert time.monotonic() - began < 6.5
        value = response.json()
        assert value["us_mapping_preparation"]["execution_status"] == "US_MAPPING_OWNER_READ_TIMEOUT"
        assert value["plan_product"]["status"] == "CURRENT"
        assert value["us_mapping_research"]["daily_run"]["status"] == "FAILED"
        assert value["us_mapping_research"]["daily_run"]["coverage"]["matched_hk_relation_count"] is None
        assert calls == [SESSION]
        clock["now"] += timedelta(seconds=1)
        busy_started = time.monotonic()
        busy = client.post("/api/v4/manager/research/workspace/refresh", params={"date": TARGET}, content=b"")
        assert busy.status_code == 200, busy.text
        assert time.monotonic() - busy_started < 1.5
        assert busy.json()["us_mapping_preparation"]["execution_status"] == "US_MAPPING_OWNER_READ_BUSY"
        assert busy.json()["plan_product"]["status"] == "CURRENT"
        assert calls == [SESSION]
        saved_bytes = _bytes(service.store.root)
    finally:
        release.set()
        assert finished.wait(1)
        assert mapping._ACTIVE_BUILD.done.wait(1)
    assert _bytes(service.store.root) == saved_bytes
    assert not (service.store.root / "us_mapping_research" / TARGET / "latest.json").exists()


@pytest.mark.parametrize("request_options", [
    {"headers": {"Origin": "https://invalid.example"}, "content": b""},
    {"content": b'{"symbols":["HK.00001"]}'},
])
def test_rejected_manual_request_does_not_enter_us_or_plan_owner(owner, monkeypatch, request_options):
    service, _source, client, _clock = owner
    monkeypatch.setattr(service, "refresh_us_mapping_research",
        lambda *_args, **_kwargs: pytest.fail("Rejected request entered US owner"))
    monkeypatch.setattr(service, "refresh_workspace_plan",
        lambda *_args, **_kwargs: pytest.fail("Rejected request entered plan owner"))
    before = _bytes(service.store.root)
    response = client.post("/api/v4/manager/research/workspace/refresh", params={"date": TARGET}, **request_options)
    assert response.status_code in {403, 422}
    assert _bytes(service.store.root) == before


def _binding(service, tmp_path, monkeypatch):
    value = {
        "enabled": True, "manager_state_root": str(service.store.root),
        "security_master_root": str(service._workspace_security_master_root),
        "preopen_plan": {"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
        "morning_plan": {"enabled": True, "interval_seconds": 300, "status": "PROPOSAL_ONLY"},
        "plan_material_refresh": {"enabled": True, "start_local": "16:00", "end_local": "23:00",
            "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600, "status": "PROPOSAL_ONLY"},
        "daily_automation": {"enabled": True,
            "same_day_catchup_slots_local": ["10:00", "12:30", "15:45", "18:30", "22:30"],
            "us_mapping_budget_seconds": 5, "max_attempts_per_target_date": 5, "status": "PROPOSAL_ONLY"},
    }
    path = tmp_path / "synthetic-binding.json"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv("V4_MANAGER_PLAN_OWNER_BINDING_PATH", str(path))
    # Deployment/source attestation is not supplied. Only that external
    # attestation boundary is injected; SHA/root/date/window admission, owners,
    # dispatch journals and persisted product/readback remain actual code.
    monkeypatch.setattr(supervisor, "validate_binding", lambda payload, **_kwargs: payload)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_next_morning_slot_rechecks_later_arriving_input_and_same_slot_remains_idempotent(owner, tmp_path, monkeypatch):
    service, source, _client, clock = owner
    binding_sha = _binding(service, tmp_path, monkeypatch)
    first = dispatch.execute_bound_daily_cycle(service, TARGET, binding_sha)
    assert first["us_mapping_research"]["status"] == "INPUT_MISSING"
    first_us_trigger = first["us_mapping_research"]["execution_context"]["trigger_id"]
    first_bytes = _bytes(service.store.root)

    # Source arrives after the first admitted slot; this is temporary synthetic
    # publication through the same original store, never a second producer.
    source.publish(_synthetic_us_payload(SESSION, {}))
    replay = dispatch.execute_bound_daily_cycle(service, TARGET, binding_sha)
    assert {key: value for key, value in replay.items() if key != "read_metrics"} == {
        key: value for key, value in first.items() if key != "read_metrics"}
    assert _bytes(service.store.root) == first_bytes

    clock["now"] = datetime(2026, 10, 9, 7, 5, tzinfo=HK)
    next_slot = dispatch.execute_bound_daily_cycle(service, TARGET, binding_sha)
    assert next_slot["us_mapping_research"]["status"] == "VALID_EMPTY"
    assert next_slot["us_mapping_research"]["coverage"]["matched_hk_relation_count"] == 0
    assert next_slot["us_mapping_research"]["execution_context"]["trigger_id"] != first_us_trigger
    saved = service.get_workspace_plan(TARGET)
    reference = saved["workspace"]["owner_chain"]["us_mapping_daily_plan_reference"]
    assert reference["status"] == "CONSUMED"
    assert reference["run_id"] == next_slot["us_mapping_research"]["run_id"]
    assert saved["workspace"]["us_mapping_research"]["daily_run"]["coverage"]["full_market_coverage"] is False
    successful_bytes = _bytes(service.store.root)
    repeated = dispatch.execute_bound_daily_cycle(service, TARGET, binding_sha)
    assert {key: value for key, value in repeated.items() if key != "read_metrics"} == {
        key: value for key, value in next_slot.items() if key != "read_metrics"}
    assert _bytes(service.store.root) == successful_bytes
