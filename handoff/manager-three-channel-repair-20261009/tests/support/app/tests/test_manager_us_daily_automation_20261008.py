from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from threading import Event
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
from v4.manager_research.workspace_projection import FLAGS, HK
from v4.manager_research import us_mapping_research


def _service(tmp_path: Path) -> ManagerResearchJobService:
    master = tmp_path / "security-master"
    master.mkdir(exist_ok=True)
    return ManagerResearchJobService(
        ManagerResearchStore(tmp_path / "manager-state"), None, None,
        existing_research_source=None,
        workspace_security_master_root=master,
        workspace_us_market_reader=object(),
    )


def test_original_us_owner_seals_execution_context_and_reads_exact_run_back(tmp_path, monkeypatch):
    now = datetime(2026, 10, 8, 6, 30, tzinfo=HK)
    trigger_id = "a" * 64

    def pure_build(_service, target, *, now):
        return {
            "schema_version": us_mapping_research.DAILY_SCHEMA,
            "status": "VALID_EMPTY",
            "target_trade_date": target,
            "run_id": "b" * 32,
            "generated_at": now.isoformat(),
            "us_session_date": "20261007",
            "research_cutoff": now.isoformat(),
            "input_identity": "c" * 64,
            "coverage": {"matched_us_symbol_count": 0, "matched_hk_relation_count": 0,
                         "full_market_coverage": False},
            "matches": [],
            **FLAGS,
        }

    monkeypatch.setattr(us_mapping_research, "build_daily_run", pure_build)
    service = _service(tmp_path)
    try:
        result = service.refresh_us_mapping_research(
            "20261008", now=now, timeout_seconds=1.0,
            execution_context={
                "trigger_kind": "SCHEDULED",
                "timing": "ON_TIME",
                "scheduled_for": now.isoformat(),
                "trigger_id": trigger_id,
                "natural_run_verified": False,
            },
        )
        saved = us_mapping_research.read_workspace_mapping(service, "20261008")["daily_run"]
    finally:
        service.close()

    assert result["run_id"] == saved["run_id"] == "b" * 32
    assert result["artifact_sha256"] == saved["artifact_sha256"]
    context = saved["execution_context"]
    assert context["trigger_kind"] == "SCHEDULED"
    assert context["timing"] == "ON_TIME"
    assert context["scheduled_for"] == now.isoformat()
    assert context["started_at"] <= context["finished_at"]
    assert context["trigger_id"] == trigger_id
    assert context["natural_run_verified"] is False


def test_original_us_owner_timed_out_pure_build_cannot_publish_late(tmp_path, monkeypatch):
    """The abandoned build worker is pure: only the waiting owner can persist."""
    started, release, finished = Event(), Event(), Event()

    def blocked_pure_build(_service, target, *, now):
        started.set()
        try:
            assert release.wait(2)
            return {
                "schema_version": us_mapping_research.DAILY_SCHEMA,
                "status": "VALID_EMPTY",
                "target_trade_date": target,
                "run_id": "d" * 32,
                "generated_at": now.isoformat(),
                "us_session_date": "20261007",
                "research_cutoff": now.isoformat(),
                "input_identity": "e" * 64,
                "coverage": {"matched_us_symbol_count": 0, "matched_hk_relation_count": 0,
                             "full_market_coverage": False},
                "matches": [],
                **FLAGS,
            }
        finally:
            finished.set()

    monkeypatch.setattr(us_mapping_research, "build_daily_run", blocked_pure_build)
    service = _service(tmp_path)
    unrelated = service.store.root / "unrelated-product.json"
    unrelated.write_bytes(b"preserve-me")
    now = datetime(2026, 10, 8, 6, 31, tzinfo=HK)
    try:
        began = time.monotonic()
        result = service.refresh_us_mapping_research(
            "20261008", now=now, timeout_seconds=0.05,
            execution_context={"trigger_kind": "SCHEDULED", "timing": "ON_TIME",
                               "scheduled_for": now.isoformat(), "natural_run_verified": False},
        )
        elapsed = time.monotonic() - began
        assert started.is_set()
        assert elapsed < 0.5
        assert result["status"] == "FAILED"
        assert "US_MAPPING_OWNER_READ_TIMEOUT" in result["gaps"]
        assert (service.store.root / "us_mapping_research" / "20261008" / "latest.json").exists() is False
        release.set()
        assert finished.wait(1)
        assert (service.store.root / "us_mapping_research" / "20261008" / "latest.json").exists() is False
        assert unrelated.read_bytes() == b"preserve-me"
    finally:
        release.set()
        service.close()


def test_retrospective_owner_keeps_real_execution_time_and_target_bound_us_session(tmp_path, monkeypatch):
    """A 10/9 recovery for 10/8 may consume US 10/7, never US 10/8."""
    from test_manager_us_mapping_research import _synthetic_us_payload

    reviewed = {"schema_version": "TEST_FIXTURE", "artifact_sha256": "f" * 64, "cards": []}
    monkeypatch.setattr(us_mapping_research, "_read_reviewed", lambda: reviewed)
    monkeypatch.setattr(us_mapping_research, "_relation_available_at",
        lambda _reviewed: (datetime(2026, 10, 1, 0, 0, tzinfo=HK), None))
    payloads = {
        "20261007": _synthetic_us_payload("20261007", {}),
        "20261008": _synthetic_us_payload("20261008", {}),
    }

    class SyntheticExactReader:
        def read_exact_session(self, session_date):
            return payloads.get(session_date), {
                "status": "VERIFIED", "payload_sha256": "1" * 64,
                "receipt_sha256": "2" * 64, "manifest_sha256": "3" * 64,
            }

    master = tmp_path / "master"
    master.mkdir()
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path / "manager-state"), None, None,
        existing_research_source=None,
        workspace_security_master_root=master,
        workspace_us_market_reader=SyntheticExactReader(),
    )
    actual_execution = datetime(2026, 10, 9, 10, 0, tzinfo=HK)
    try:
        result = service.refresh_us_mapping_research(
            "20261008", now=actual_execution, timeout_seconds=2.0,
            execution_context={"trigger_kind": "MANUAL", "timing": "UNCLASSIFIED",
                               "natural_run_verified": False},
        )
    finally:
        service.close()

    assert result["status"] == "VALID_EMPTY"
    assert result["us_session_date"] == "20261007"
    assert result["research_cutoff"] == "2026-10-08T23:59:59.999999+08:00"
    generated_at = datetime.fromisoformat(result["generated_at"].replace("Z", "+00:00"))
    assert generated_at >= actual_execution.astimezone(generated_at.tzinfo)
    assert result["execution_context"]["timing"] == "RETROSPECTIVE"
    assert result["execution_context"]["started_at"] >= actual_execution.isoformat(timespec="microseconds")
    assert result["execution_context"]["research_cutoff_policy"] == "TARGET_DATE_END_OF_DAY_RETROSPECTIVE"


def test_duplicate_trigger_after_service_restart_reuses_immutable_run(tmp_path, monkeypatch):
    calls = []

    def pure_build(_service, target, *, now):
        calls.append(1)
        return {
            "schema_version": us_mapping_research.DAILY_SCHEMA,
            "status": "VALID_EMPTY", "target_trade_date": target,
            "run_id": "9" * 32, "generated_at": now.isoformat(),
            "us_session_date": "20261007", "research_cutoff": now.isoformat(),
            "input_identity": "8" * 64,
            "coverage": {"matched_us_symbol_count": 0, "matched_hk_relation_count": 0,
                         "full_market_coverage": False},
            "matches": [], **FLAGS,
        }

    monkeypatch.setattr(us_mapping_research, "build_daily_run", pure_build)
    now = datetime(2026, 10, 8, 6, 30, tzinfo=HK)
    context = {"trigger_kind": "SCHEDULED", "timing": "ON_TIME",
               "scheduled_for": now.isoformat(), "trigger_id": "7" * 64,
               "natural_run_verified": False}
    first_service = _service(tmp_path)
    try:
        first = first_service.refresh_us_mapping_research(
            "20261008", now=now, timeout_seconds=1, execution_context=context)
        first_bytes = (first_service.store.root / "us_mapping_research" / "20261008" /
                       "runs" / f"{first['run_id']}.json").read_bytes()
    finally:
        first_service.close()

    def forbidden_rebuild(*_args, **_kwargs):
        raise AssertionError("same stable trigger must not rebuild after restart")

    monkeypatch.setattr(us_mapping_research, "build_daily_run", forbidden_rebuild)
    second_service = _service(tmp_path)
    try:
        second = second_service.refresh_us_mapping_research(
            "20261008", now=now, timeout_seconds=1, execution_context=context)
        second_bytes = (second_service.store.root / "us_mapping_research" / "20261008" /
                        "runs" / f"{second['run_id']}.json").read_bytes()
    finally:
        second_service.close()

    assert calls == [1]
    assert second["run_id"] == first["run_id"]
    assert second["artifact_sha256"] == first["artifact_sha256"]
    assert second_bytes == first_bytes


def test_latest_us_failure_is_visible_without_replacing_saved_success(tmp_path, monkeypatch):
    builds = ["VALID_EMPTY", "FAILED"]

    def pure_build(_service, target, *, now):
        status = builds.pop(0)
        return {
            "schema_version": us_mapping_research.DAILY_SCHEMA,
            "status": status, "target_trade_date": target,
            "run_id": "5" * 32 if status == "VALID_EMPTY" else "6" * 32,
            "generated_at": now.isoformat(), "us_session_date": "20261007",
            "research_cutoff": now.isoformat(),
            "input_identity": "1" * 64 if status == "VALID_EMPTY" else "2" * 64,
            "coverage": {"matched_us_symbol_count": 0 if status == "VALID_EMPTY" else None,
                         "matched_hk_relation_count": 0 if status == "VALID_EMPTY" else None,
                         "full_market_coverage": False},
            "matches": [], "gaps": [] if status == "VALID_EMPTY" else ["SYNTHETIC_SOURCE_FAILURE"],
            **FLAGS,
        }

    monkeypatch.setattr(us_mapping_research, "build_daily_run", pure_build)
    service = _service(tmp_path)
    now = datetime(2026, 10, 8, 6, 30, tzinfo=HK)
    try:
        saved = service.refresh_us_mapping_research(
            "20261008", now=now, timeout_seconds=1,
            execution_context={"trigger_kind": "SCHEDULED", "timing": "ON_TIME",
                               "trigger_id": "a" * 64, "natural_run_verified": False})
        failed = service.refresh_us_mapping_research(
            "20261008", now=now.replace(minute=35), timeout_seconds=1,
            execution_context={"trigger_kind": "SCHEDULED", "timing": "LATE_CATCHUP",
                               "trigger_id": "b" * 64, "natural_run_verified": False})
        projected = us_mapping_research.read_workspace_mapping(service, "20261008")["daily_run"]
    finally:
        service.close()

    assert failed["status"] == "FAILED"
    assert failed["coverage"]["matched_hk_relation_count"] is None
    assert projected["run_id"] == saved["run_id"]
    assert projected["status"] == "VALID_EMPTY"
    assert projected["latest_attempt"]["status"] == "FAILED"
    assert projected["latest_attempt"]["run_id"] == failed["run_id"]


def test_manual_us_recovery_endpoint_uses_server_execution_context(tmp_path, monkeypatch):
    service = _service(tmp_path)
    target = datetime.now(HK).strftime("%Y%m%d")

    def pure_build(_service, date, *, now):
        return {
            "schema_version": us_mapping_research.DAILY_SCHEMA,
            "status": "VALID_EMPTY", "target_trade_date": date,
            "run_id": "3" * 32, "generated_at": now.isoformat(),
            "us_session_date": "20261007", "research_cutoff": now.isoformat(),
            "input_identity": "4" * 64,
            "coverage": {"matched_us_symbol_count": 0, "matched_hk_relation_count": 0,
                         "full_market_coverage": False},
            "matches": [], **FLAGS,
        }

    monkeypatch.setattr(us_mapping_research, "build_daily_run", pure_build)
    from apps.api.v35_api.manager_research_router import create_manager_research_router

    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    try:
        with TestClient(app) as client:
            response = client.post(f"/api/v4/manager/research/workspace/us-mapping/refresh?date={target}",
                                   content=b"")
    finally:
        service.close()

    assert response.status_code == 200
    run = response.json()
    assert run["target_trade_date"] == target
    assert run["execution_context"]["trigger_kind"] == "MANUAL"
    assert run["execution_context"]["trigger_id"]
    assert run["execution_context"]["natural_run_verified"] is False


def test_timed_out_us_reader_keeps_single_global_preparation_lane(tmp_path, monkeypatch):
    started, release, finished = Event(), Event(), Event()
    calls = []

    def blocked_build(_service, target, *, now):
        calls.append(target)
        started.set()
        try:
            assert release.wait(2)
            return {
                "schema_version": us_mapping_research.DAILY_SCHEMA,
                "status": "VALID_EMPTY", "target_trade_date": target,
                "run_id": "2" * 32, "generated_at": now.isoformat(),
                "us_session_date": "20261007", "research_cutoff": now.isoformat(),
                "input_identity": "3" * 64,
                "coverage": {"matched_us_symbol_count": 0, "matched_hk_relation_count": 0,
                             "full_market_coverage": False},
                "matches": [], **FLAGS,
            }
        finally:
            finished.set()

    monkeypatch.setattr(us_mapping_research, "build_daily_run", blocked_build)
    service = _service(tmp_path)
    now = datetime(2026, 10, 8, 6, 30, tzinfo=HK)
    try:
        first = service.refresh_us_mapping_research(
            "20261008", now=now, timeout_seconds=0.05,
            execution_context={"trigger_kind": "SCHEDULED", "timing": "ON_TIME",
                               "trigger_id": "1" * 64, "natural_run_verified": False})
        assert started.is_set()
        second = service.refresh_us_mapping_research(
            "20261008", now=now.replace(minute=31), timeout_seconds=0.05,
            execution_context={"trigger_kind": "SCHEDULED", "timing": "LATE_CATCHUP",
                               "trigger_id": "4" * 64, "natural_run_verified": False})
        assert first["execution_status"] == "US_MAPPING_OWNER_READ_TIMEOUT"
        assert second["execution_status"] == "US_MAPPING_OWNER_READ_BUSY"
        assert calls == ["20261008"]
    finally:
        release.set()
        assert finished.wait(1)
        service.close()


def test_same_input_identity_reuses_run_across_moving_cutoff(tmp_path, monkeypatch):
    calls = []

    def same_input(_service, target, *, now):
        calls.append(now)
        return {
            "schema_version": us_mapping_research.DAILY_SCHEMA,
            "status": "VALID_EMPTY", "target_trade_date": target,
            "run_id": ("a" if len(calls) == 1 else "b") * 32,
            "generated_at": now.isoformat(), "us_session_date": "20261007",
            "research_cutoff": now.isoformat(), "input_identity": "c" * 64,
            "source_identity": {"payload_sha256": "d" * 64},
            "relation_artifact_sha256": "e" * 64,
            "coverage": {"matched_us_symbol_count": 0, "matched_hk_relation_count": 0,
                         "full_market_coverage": False},
            "matches": [], **FLAGS,
        }

    monkeypatch.setattr(us_mapping_research, "build_daily_run", same_input)
    service = _service(tmp_path)
    now = datetime(2026, 10, 8, 6, 30, tzinfo=HK)
    try:
        first = service.refresh_us_mapping_research(
            "20261008", now=now, timeout_seconds=1,
            execution_context={"trigger_kind": "SCHEDULED", "timing": "ON_TIME",
                               "trigger_id": "1" * 64, "natural_run_verified": False})
        second = service.refresh_us_mapping_research(
            "20261008", now=now.replace(minute=45), timeout_seconds=1,
            execution_context={"trigger_kind": "SCHEDULED", "timing": "LATE_CATCHUP",
                               "trigger_id": "2" * 64, "natural_run_verified": False})
        runs = service.store._io.files("us_mapping_research/20261008/runs")
        latest_attempt = us_mapping_research.read_workspace_mapping(
            service, "20261008")["daily_run"]["latest_attempt"]
    finally:
        service.close()

    assert len(calls) == 2
    assert first["run_id"] == second["run_id"]
    assert len(runs) == 1
    assert latest_attempt["trigger_id"] == "2" * 64
    assert latest_attempt["execution_context"]["trigger_id"] == "2" * 64


def test_same_trigger_failure_replay_returns_complete_unknown_dto(tmp_path, monkeypatch):
    now = datetime(2026, 10, 8, 6, 30, tzinfo=HK)
    trigger = "f" * 64
    monkeypatch.setattr(us_mapping_research, "_bounded_build",
        lambda *_a, **_k: (None, "US_MAPPING_OWNER_READ_TIMEOUT"))
    service = _service(tmp_path)
    context = {"trigger_kind": "SCHEDULED", "timing": "ON_TIME",
        "scheduled_for": now.isoformat(), "trigger_id": trigger,
        "natural_run_verified": False}
    try:
        first = service.refresh_us_mapping_research("20261008", now=now,
            timeout_seconds=1, execution_context=context)
        replay = service.refresh_us_mapping_research("20261008", now=now,
            timeout_seconds=1, execution_context=context)
    finally:
        service.close()

    assert replay["schema_version"] == us_mapping_research.DAILY_SCHEMA
    assert replay["target_trade_date"] == "20261008"
    assert replay["status"] == first["status"] == "FAILED"
    assert replay["execution_status"] == first["execution_status"] == "US_MAPPING_OWNER_READ_TIMEOUT"
    assert replay["matches"] == []
    assert replay["coverage"]["matched_us_symbol_count"] is None
    assert replay["execution_context"]["trigger_id"] == trigger
    assert all(replay[key] is value for key, value in FLAGS.items())


def test_pointer_write_timeout_does_not_report_owner_completion(tmp_path, monkeypatch):
    now = datetime(2026, 10, 8, 6, 30, tzinfo=HK)

    def pure_build(_service, target, *, now):
        return {
            "schema_version": us_mapping_research.DAILY_SCHEMA,
            "status": "VALID_EMPTY", "target_trade_date": target,
            "run_id": "a" * 32, "generated_at": now.isoformat(),
            "us_session_date": "20261007", "research_cutoff": now.isoformat(),
            "input_identity": "b" * 64, "source_identity": {"payload_sha256": "c" * 64},
            "relation_artifact_sha256": "d" * 64,
            "coverage": {"matched_us_symbol_count": 0, "matched_hk_relation_count": 0,
                         "full_market_coverage": False},
            "matches": [], **FLAGS,
        }

    monkeypatch.setattr(us_mapping_research, "build_daily_run", pure_build)
    service = _service(tmp_path)
    trigger = "e" * 64
    original_write = service.store._io.write_bytes

    def delayed_pointer(relative, data, **kwargs):
        value = original_write(relative, data, **kwargs)
        if relative == "us_mapping_research/20261008/latest.json":
            time.sleep(0.08)
        return value

    monkeypatch.setattr(service.store._io, "write_bytes", delayed_pointer)
    try:
        result = service.refresh_us_mapping_research("20261008", now=now,
            timeout_seconds=0.05,
            execution_context={"trigger_kind": "SCHEDULED", "timing": "ON_TIME",
                "scheduled_for": now.isoformat(), "trigger_id": trigger,
                "natural_run_verified": False})
        projected = us_mapping_research.read_workspace_mapping(service, "20261008")["daily_run"]
    finally:
        service.close()

    assert result["status"] == "FAILED"
    assert projected["status"] == "CANNOT_CONFIRM"
    assert projected["saved_product_status"] == "VALID_EMPTY"
    assert projected["latest_attempt"]["execution_status"] == "US_MAPPING_DISPATCH_RECONCILIATION_REQUIRED"
    assert projected["run_readback"]["status"] == "CANNOT_CONFIRM"


def test_run_scan_stops_at_shared_deadline_after_a_bounded_slow_read(tmp_path, monkeypatch):
    store = ManagerResearchStore(tmp_path / "manager-state")
    date = "20261008"
    store._io.ensure_directory(f"us_mapping_research/{date}/runs")
    names = [f"{index:032x}.json" for index in range(1, 32)]
    for name in names:
        store._io.write_bytes(f"us_mapping_research/{date}/runs/{name}", b"{}")

    reads = []

    def slow_read(inner_store, inner_date, run_id, expected_sha=None, *, read_budget=None):
        reads.append(run_id)
        time.sleep(0.03)
        return {"run_id": run_id, "input_identity": "different"}

    monkeypatch.setattr(us_mapping_research, "_read_exact_run", slow_read)
    budget = us_mapping_research._ReadBudget(time.monotonic() + 0.12)
    began = time.monotonic()
    with pytest.raises(TimeoutError, match="US_MAPPING_OWNER_BUDGET_EXHAUSTED"):
        us_mapping_research._equivalent_run(
            store, date, {"input_identity": "wanted"}, read_budget=budget)
    elapsed = time.monotonic() - began
    assert len(reads) <= 5
    assert elapsed < 0.25  # one in-flight SafeRoot read may finish after the deadline


def test_reconciliation_promotes_recovered_run_without_overwriting_newer_latest(tmp_path):
    service = _service(tmp_path)
    store = service.store
    date = "20261008"
    trigger_id = "a" * 64
    old = {
        "schema_version": us_mapping_research.DAILY_SCHEMA,
        "status": "VALID_EMPTY", "target_trade_date": date,
        "run_id": "1" * 32, "generated_at": "2026-10-08T06:00:00Z",
        "input_identity": "2" * 64, "source_identity": {"payload_sha256": "3" * 64},
        "relation_artifact_sha256": "4" * 64, "matches": [], **FLAGS,
    }
    old["artifact_sha256"] = us_mapping_research.sha256_json(old)
    store._io.write_bytes(f"us_mapping_research/{date}/runs/{old['run_id']}.json",
                          json.dumps(old, sort_keys=True, separators=(",", ":")).encode())
    old_pointer = {"schema_version": "v4.manager_research.us_mapping_daily_pointer.v1",
                   "target_trade_date": date, "run_id": old["run_id"],
                   "artifact_sha256": old["artifact_sha256"], **FLAGS}
    store._io.write_bytes(f"us_mapping_research/{date}/latest.json",
                          json.dumps(old_pointer, sort_keys=True, separators=(",", ":")).encode())

    recovered = {**old, "run_id": "e" * 32, "generated_at": "2026-10-08T06:30:00Z",
                 "input_identity": "5" * 64,
                 "execution_context": {"trigger_id": trigger_id}}
    recovered["artifact_sha256"] = us_mapping_research.sha256_json(
        {key: value for key, value in recovered.items() if key != "artifact_sha256"})
    store._io.write_bytes(f"us_mapping_research/{date}/runs/{recovered['run_id']}.json",
                          json.dumps(recovered, sort_keys=True, separators=(",", ":")).encode())
    started = us_mapping_research._seal_dispatch({
        "schema_version": us_mapping_research.DISPATCH_SCHEMA, "state": "RUNNING",
        "target_trade_date": date, "trigger_id": trigger_id,
        "started_at": "2026-10-08T06:29:00+08:00",
        "owner": "ManagerResearchJobService.refresh_us_mapping_research", **FLAGS,
    })
    store._io.write_bytes(f"us_mapping_dispatch/{date}/{trigger_id}.started.json",
                          json.dumps(started, sort_keys=True, separators=(",", ":")).encode())
    now = datetime(2026, 10, 8, 6, 31, tzinfo=HK)
    try:
        result = service.refresh_us_mapping_research(
            date, now=now, timeout_seconds=1.0,
            execution_context={"trigger_kind": "SCHEDULED", "timing": "ON_TIME",
                               "trigger_id": trigger_id, "natural_run_verified": False})
        readback = us_mapping_research.read_workspace_mapping(service, date)["daily_run"]
    finally:
        service.close()
    assert result["run_id"] == recovered["run_id"]
    assert readback["run_id"] == recovered["run_id"]
