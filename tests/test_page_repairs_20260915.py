"""Read-only r3 page regressions; real API/store/ledger, no provider/graph fake."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from domains.preselection import date_catalog
from infrastructure.data_store import NativeDataStore
from infrastructure.research_lane_source import ResearchLaneSource
from infrastructure.scheduling.execution_ledger import ExecutionLedger

FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def data_root(tmp_path: Path) -> Path:
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({"schema_version": "v3_trade_calendar.v1", "system_date": "20260914",
                          "stage_dates": ["20260914"], "future_target_dates": [],
                          "materialized_rows": {"20260914": 2}})
    return store.root


def clock(monkeypatch, iso: str) -> None:
    import infrastructure.research_lane_source as module
    fixed = datetime.fromisoformat(iso).astimezone(ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(module, "shanghai_now", lambda: fixed)


def receipt(root: Path, *, date="20260915", slot="0900", status="FAILED", run_id="fixture-run") -> Path:
    ledger = ExecutionLedger(root)
    relative = f"receipts/live/{date}/{slot}/{run_id}.dispatch-receipt.json"
    ledger.write_receipt(relative, {"schema_version": "v3_5.dispatch.v1", "business_date": date,
        "scheduled_date": date, "target_date": date, "slot": slot, "mode": "LIVE", "run_id": run_id,
        "finished_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T09:02:00+08:00", "status": status,
        "selected_workload_ids": ["hourly_research"],
        "workload_results": [{"workload_id": "hourly_research", "status": status,
                              "stderr": "SECRET_TEST_TOKEN_DO_NOT_DISPLAY"}], **FLAGS})
    return root / relative


def test_shanghai_navigation_keeps_evidence_default(tmp_path):
    value = date_catalog(NativeDataStore(data_root(tmp_path)), current_date="20260915")
    assert value["default_date"] == "20260914"
    assert value["navigation_date"] == "20260915"
    assert value["navigation_timezone"] == "Asia/Shanghai"
    assert "20260915" not in value["stage_dates"]


def test_closed_day_navigation_does_not_manufacture_trading_day(tmp_path):
    value = date_catalog(NativeDataStore(data_root(tmp_path)), current_date="20260919")
    assert value["navigation_date"] == value["default_date"] == "20260914"
    assert "20260919" not in value["dates"]


def test_public_date_list_navigation_and_explicit_date(tmp_path):
    client = TestClient(create_app(data_root=data_root(tmp_path), current_date="20260915"))
    actual = client.get("/api/v1/runs/date-list").json()
    assert actual["selected_date"] == "20260915"
    assert actual["default_date"] == "20260914"
    assert client.get("/api/v1/runs/date-list?date=20260911").json()["selected_date"] == "20260911"


def test_identity_unbound_is_not_an_old_release_label(tmp_path, monkeypatch):
    for key in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256"):
        monkeypatch.delenv(key, raising=False)
    value = TestClient(create_app(data_root=data_root(tmp_path))).get("/api/v1/runs/date-list").json()
    identity = value["runtime_identity"]
    assert identity["status"] == "CANNOT_CONFIRM"
    assert identity["release_id"] == ""
    assert identity["process_status"] == "CANNOT_CONFIRM"


def test_real_identity_validator_used_for_release_label(tmp_path, monkeypatch):
    from infrastructure.scheduling import dispatcher
    app = Path(dispatcher.__file__).resolve().parents[2]
    entries = []
    for rel in dispatcher._RUNTIME_IDENTITY_FILES:
        raw = (app / rel).read_bytes()
        entries.append({"path": rel, "kind": "file", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    aggregate = hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps({"schema_version": "v4.release_candidate.v1",
        "candidate": {"app_root": str(app), "release_id": "r3-fixture-only"},
        "application_inventory": {"entries": entries, "entry_count": len(entries), "aggregate_sha256": aggregate}}))
    for k, v in {"V35_APP_ROOT": str(app), "V35_RELEASE_ID": "r3-fixture-only", "V35_RELEASE_MANIFEST_PATH": str(manifest),
                 "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(manifest.read_bytes()).hexdigest()}.items():
        monkeypatch.setenv(k, v)
    client = TestClient(create_app(data_root=data_root(tmp_path)))
    identity = client.get("/api/v1/runs/date-list").json()["runtime_identity"]
    assert identity["status"] == "MANIFEST_EXECUTION_FILES_VERIFIED"
    assert identity["release_id"] == "r3-fixture-only"
    manifest.write_text("{}")
    assert client.get("/api/v1/runs/date-list").json()["runtime_identity"]["status"] == "CANNOT_CONFIRM"


@pytest.mark.parametrize("stamp,state", [("2026-09-15T00:20:00+08:00", "NOT_DUE"),
    ("2026-09-15T09:20:00+08:00", "EXECUTION_UNCONFIRMED")])
def test_exact_missing_lane_clock_is_not_a_failed_run(tmp_path, monkeypatch, stamp, state):
    clock(monkeypatch, stamp)
    client = TestClient(create_app(data_root=data_root(tmp_path), ledger_root=tmp_path/"actual-ledger"))
    value = client.get("/api/v3/research/lane?research_date=20260915").json()
    assert value["research_date"] == "20260915"
    assert value["endpoint_mode"] == "EXACT"
    assert value["update_diagnostic"]["state"] == state
    assert value["update_diagnostic"]["artifact_verified"] is False
    assert all(value[k] is False for k in FLAGS)


def test_actual_app_uses_explicit_ledger_root_not_sibling(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-09-15T09:20:00+08:00")
    root = data_root(tmp_path)
    actual = tmp_path / "actual-ledger"
    receipt(actual)
    receipt(root.parent / "dispatcher", status="SUCCEEDED", run_id="wrong-root")
    client = TestClient(create_app(data_root=root, ledger_root=actual))
    value = client.get("/api/v3/research/lane?date=20260915").json()
    diag = value["update_diagnostic"]
    assert diag["state"] == "FAILED_RECEIPT"
    assert diag["receipt_run_id"] == "fixture-run"
    assert diag["receipt_verification"] == "LEDGER_CHAIN_VERIFIED"
    assert "SECRET_TEST_TOKEN" not in json.dumps(diag)
    timeline = value["research_intelligence_timeline"]["slots"]
    assert next(row for row in timeline if row["slot"] == "0900")["run_id"] == "fixture-run"


def test_success_receipt_is_not_materialized_artifact(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-09-15T09:20:00+08:00")
    root = data_root(tmp_path); ledger = tmp_path / "actual-ledger"
    receipt(ledger, status="SUCCEEDED")
    value = TestClient(create_app(data_root=root, ledger_root=ledger)).get("/api/v3/research/lane?date=20260915").json()
    assert value["update_diagnostic"]["state"] == "MATERIALIZATION_MISSING_AFTER_RECEIPT"
    assert value["update_diagnostic"]["artifact_verified"] is False


def test_copied_other_date_and_tampered_receipt_not_verified(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-09-15T09:20:00+08:00")
    root = data_root(tmp_path); ledger = tmp_path / "ledger"
    old = receipt(ledger, date="20260914")
    target = ledger / "receipts/live/20260915/0900/copied.dispatch-receipt.json"
    target.parent.mkdir(parents=True); target.write_bytes(old.read_bytes())
    client = TestClient(create_app(data_root=root, ledger_root=ledger))
    value = client.get("/api/v3/research/lane?date=20260915").json()
    assert value["update_diagnostic"]["state"] == "EXECUTION_UNCONFIRMED"
    target.unlink()
    path = receipt(ledger)
    payload = json.loads(path.read_text()); payload["status"] = "SUCCEEDED"
    path.write_text(json.dumps(payload))
    value = client.get("/api/v3/research/lane?date=20260915").json()
    assert value["update_diagnostic"]["state"] == "RECEIPT_INVALID"
    assert value["update_diagnostic"]["receipt_verification"] != "LEDGER_CHAIN_VERIFIED"


def test_future_lane_is_not_due_not_failed(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-09-15T22:20:00+08:00")
    value = TestClient(create_app(data_root=data_root(tmp_path))).get("/api/v3/research/lane?date=20260916").json()
    assert value["update_diagnostic"]["state"] == "NOT_DUE"
    slots = value.get("research_intelligence_timeline", {}).get("slots", [])
    assert all(row["status"] == "NOT_DUE" for row in slots)


def test_us_missing_history_is_separate_from_clock_and_not_zero_demand(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-09-15T00:20:00+08:00")
    value = TestClient(create_app(data_root=data_root(tmp_path))).get("/api/v3/research/dates").json()
    diag = value["us_close_availability"]
    assert value["market_snapshot_dates"] == []
    assert diag["state"] == "NO_VERIFIED_COMPLETED_SESSION"
    assert diag["latest_verified_source_date"] == ""
    assert diag["exchange_calendar_status"] == "CANNOT_CONFIRM"
    assert diag["new_york_time"].startswith("2026-09-14T12:20")
    assert diag["clock_phase"] == "BEFORE_REGULAR_CLOSE"
    assert diag["configured_proxy_count"] > 0


@pytest.mark.parametrize("exists", [False, True])
def test_tasks_distinguish_configured_owner_receipt_and_process(tmp_path, exists):
    root = data_root(tmp_path); ledger = tmp_path / "actual-ledger"
    if exists:
        receipt(ledger)
    client = TestClient(create_app(data_root=root, ledger_root=ledger))
    value = client.get("/api/v3/tasks/status?date=20260915").json()
    obs = value["scheduler_observation"]
    assert obs["process_status"] == "CANNOT_CONFIRM"
    assert obs["status"] == ("RECEIPT_CHAIN_VERIFIED" if exists else "NO_SAME_DATE_RECEIPT")
    assert obs["receipt_count"] == int(exists)
    assert all(not r["enabled"] and not r["execution_allowed"] for r in value["groups"]["registrations"])
    assert all(value[k] is False for k in FLAGS)


def test_tasks_tamper_not_upgraded(tmp_path):
    root = data_root(tmp_path); ledger = tmp_path / "actual-ledger"
    path = receipt(ledger); payload = json.loads(path.read_text()); payload["status"] = "SUCCEEDED"
    path.write_text(json.dumps(payload))
    value = TestClient(create_app(data_root=root, ledger_root=ledger)).get("/api/v3/tasks/status?date=20260915").json()
    assert value["scheduler_observation"]["status"] == "RECEIPT_INVALID"


def test_tasks_rejects_mismatched_scheduled_and_target_dates(tmp_path):
    root = data_root(tmp_path)
    ledger = ExecutionLedger(root / "dispatcher")
    ledger.write_receipt(
        "receipts/live/20260915/0900/misbound.dispatch-receipt.json",
        {"schema_version": "v3_5.dispatch.v1", "business_date": "20260915",
         "scheduled_date": "20260914", "target_date": "20260914", "slot": "0900",
         "mode": "LIVE", "run_id": "misbound", "finished_at": "2026-09-15T09:02:00+08:00",
         "status": "SUCCEEDED", "selected_workload_ids": ["hourly_research"],
         "workload_results": [{"workload_id": "hourly_research", "status": "SUCCEEDED"}], **FLAGS},
    )
    value = TestClient(create_app(data_root=root, ledger_root=ledger.root)).get("/api/v3/tasks/status?date=20260915").json()
    hourly = next(row for row in value["groups"]["logical"] if row["workload_id"] == "hourly_research")
    assert hourly["status"] == "CANNOT_CONFIRM"
    assert hourly["result_code"] == "EXECUTION_RECEIPT_DATE_MISMATCH"
    assert hourly["freshness"] == "NOT_OBSERVED"
    assert value["scheduler_observation"]["status"] == "RECEIPT_DATE_MISMATCH"
    assert value["scheduler_observation"]["logical_row_evidence"] == "DATE_BOUND_RECEIPT_REJECTED"


def test_timeline_cannot_confirm_receipt_is_not_current(tmp_path):
    root = data_root(tmp_path)
    ledger = ExecutionLedger(root / "dispatcher")
    ledger.write_receipt(
        "receipts/live/20260915/1605/invalid-fupan.dispatch-receipt.json",
        {"schema_version": "v3_5.dispatch.v1", "business_date": "20260915",
         "scheduled_date": "20260915", "target_date": "20260915", "slot": "1605",
         "mode": "LIVE", "run_id": "invalid-fupan", "finished_at": "not-a-timestamp",
         "status": "SUCCEEDED", "selected_workload_ids": ["a_share_close_review"],
         "workload_results": [{"workload_id": "a_share_close_review", "status": "SUCCEEDED"}], **FLAGS},
    )
    value = TestClient(create_app(data_root=root, ledger_root=ledger.root)).get("/api/v3/tasks/status?date=20260915").json()
    node = next(row for row in value["timeline_nodes"] if row["node_id"] == "FUPAN_A_SHARE_STRUCTURE")
    assert node["status"] == "CANNOT_CONFIRM"
    assert node["freshness"] == "NOT_OBSERVED"


def test_tasks_keep_workload_specific_cross_day_target_contract(tmp_path):
    root = data_root(tmp_path)
    ledger = ExecutionLedger(root / "dispatcher")
    ledger.write_receipt(
        "receipts/live/20260915/1730/preselection.dispatch-receipt.json",
        {"schema_version": "v3_5.dispatch.v1", "business_date": "20260915",
         "scheduled_date": "20260915", "target_date": "20260916", "slot": "1730",
         "mode": "LIVE", "run_id": "preselection-cross-day", "finished_at": "2026-09-15T17:32:00+08:00",
         "status": "SUCCEEDED", "selected_workload_ids": ["preselection_pools"],
         "workload_results": [{"workload_id": "preselection_pools", "status": "SUCCEEDED"}], **FLAGS},
    )
    value = TestClient(create_app(data_root=root, ledger_root=ledger.root)).get("/api/v3/tasks/status?date=20260915").json()
    preselection = next(row for row in value["groups"]["logical"] if row["workload_id"] == "preselection_pools")
    assert preselection["status"] == "SUCCEEDED"


def test_empty_closed_day_does_not_choose_unverified_weekend(tmp_path):
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({"schema_version":"v3_trade_calendar.v1", "system_date":"20260918",
        "stage_dates":[], "future_target_dates":[], "materialized_rows":{}})
    client = TestClient(create_app(data_root=store.root, current_date="20260919"))
    value = client.get("/api/v1/runs/date-list").json()
    assert value["system_date"] == "20260919"
    assert value["selected_date"] == ""


def _frozen_hourly_input(date: str) -> dict:
    # Reuse the repository's existing synthetic input fixture; not a fabricated
    # successful graph, provider or store. Public main and transformer run below.
    import importlib.util
    spec = importlib.util.spec_from_file_location("_existing_hourly_fixture", Path(__file__).with_name("test_hourly_research_runner.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._source(date)


def test_real_hourly_cli_to_verified_artifact_api_with_synthetic_frozen_input(tmp_path, monkeypatch, capsys):
    import sys
    from ops.run_hourly_research import main
    root = data_root(tmp_path)
    source = root / "research/incoming/20260914/1200.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(_frozen_hourly_input("20260914"), ensure_ascii=False))
    original_source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(sys, "argv", ["ops.run_hourly_research", "--data-root", str(root),
        "--date", "20260914", "--target-date", "20260914", "--slot", "1200", "--mode", "LIVE"])
    assert main() == 0
    result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert result["status"] == "SUCCEEDED"
    assert result["payload_sha256"] == hashlib.sha256((root / result["payload_path"]).read_bytes()).hexdigest()
    assert main() == 0
    repeated = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert repeated["payload_sha256"] == result["payload_sha256"]
    assert repeated["latest_updated"] is False
    client = TestClient(create_app(data_root=root))
    before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    exact = client.get("/api/v3/research/lane?date=20260914").json()
    missing = client.get("/api/v3/research/lane?date=20260915").json()
    latest = client.get("/api/v3/research/lane").json()
    assert exact["research_date"] == latest["research_date"] == "20260914"
    assert exact["endpoint_mode"] == "EXACT" and latest["endpoint_mode"] == "LATEST"
    assert exact["update_diagnostic"]["artifact_verified"] is True
    assert missing["research_date"] == "20260915"
    assert missing["update_diagnostic"]["artifact_verified"] is False
    assert len(exact["stock_research_daily"]) == 1
    after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
    assert before == after
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_source_sha
    (tmp_path / "public_chain_evidence.json").write_text(json.dumps({"fixture_kind":"SYNTHETIC_FROZEN_INPUT_NOT_MARKET_VERIFICATION",
        "main_exit_codes":[0,0], "publication":result, "repeat":repeated,
        "api_exact":exact, "api_next_date":missing, "api_latest":latest, "read_only_hashes":after},ensure_ascii=False,indent=2))


def test_real_hourly_cli_rejects_missing_input_not_synthesize_latest(tmp_path, monkeypatch, capsys):
    import sys
    from ops.run_hourly_research import main
    root = data_root(tmp_path)
    monkeypatch.setattr(sys, "argv", ["ops.run_hourly_research", "--data-root", str(root),
        "--date", "20260915", "--target-date", "20260915", "--slot", "0700", "--mode", "LIVE"])
    assert main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "NOT_MATERIALIZED"
    assert result["business_date"] == "20260915"
    assert not (root / "research/hourly").exists()


def test_hourly_status_projects_latest_verified_receipt_not_filename_first(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-09-15T09:20:00+08:00")
    root = data_root(tmp_path); ledger = tmp_path / "ledger"
    receipt(ledger, status="FAILED", run_id="a-old")
    receipt(ledger, status="SUCCEEDED", run_id="z-new")
    source = ResearchLaneSource(root, ledger_root=ledger)
    row = next(item for item in source.read_status_lane("20260915")["slots"] if item["slot"] == "0900")
    assert row["run_id"] == "z-new"
    assert row["status"] == "SUCCEEDED"


def test_invalid_receipt_does_not_become_a_successful_hour_row(tmp_path, monkeypatch):
    clock(monkeypatch, "2026-09-15T09:20:00+08:00")
    root = data_root(tmp_path); ledger = tmp_path / "ledger"
    path = receipt(ledger)
    body = json.loads(path.read_text()); body["status"] = "SUCCEEDED"; body["workload_results"][0]["status"] = "SUCCEEDED"
    path.write_text(json.dumps(body))
    value = TestClient(create_app(data_root=root, ledger_root=ledger)).get("/api/v3/research/lane?date=20260915").json()
    assert value["update_diagnostic"]["state"] == "RECEIPT_INVALID"
    row = next(item for item in value["research_intelligence_timeline"]["slots"] if item["slot"] == "0900")
    assert row["status"] not in {"READY", "SUCCEEDED"}
