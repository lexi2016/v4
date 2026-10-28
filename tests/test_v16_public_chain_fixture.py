"""Actual entries/updaters, temporary SDK fixtures; positive FULL E2E is NOT asserted.

All .day bytes here are synthetic test data under tmp_path, never real marketdata.
External formula seeds/frozen HK assets are deliberately absent: failures must
remain failures through both exact receipt and dispatch receipt publication.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from ops.a_share_daily_sync import pack_hq_bar, read_hq_day_bars
from verification.scheduler_candidate.fixture_support import (
    transport_environment, bar, read_lines, file_fact, record_evidence,
)

REPO = Path(__file__).resolve().parents[1]
DATE = "20260911"
A_KEYS = ("a-tdx-root", "a-sync-script", "a-formula-script", "a-seed-panel", "a-data-root",
          "a-selector-pointer", "a-backtest-pointer", "a-selector-seed", "a-backtest-seed",
          "a-contract-csv", "a-canonical-formula", "a-return-root")


def a_setup(tmp_path, *, count=1):
    paths = {name: tmp_path / name for name in A_KEYS}
    paths["a-sync-script"] = REPO / "ops/a_share_daily_sync.py"
    paths["receipt-root"] = tmp_path / "receipts"
    root = paths["a-tdx-root"] / "vipdoc/sh/lday"
    root.mkdir(parents=True)
    before = pack_hq_bar(bar(20260909, 10))
    names = [f"{prefix}{n:03d}" for prefix in ("600", "601", "603", "605", "688") for n in range(1000)]
    for index, code in enumerate(names[:count]):
        (root / f"sh{code}.day").write_bytes(before if index == 0 else pack_hq_bar(bar(20260911, 11)))
    environment = transport_environment(tmp_path / "sdk-fixture", REPO)
    environment["V4_FIXTURE_BARS"] = json.dumps([bar(20260909, 10), bar(20260910, 10.5), bar(20260911, 11)])
    environment["V35_A_SYNC_HOST"] = "fixture.invalid:7710"
    environment["V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS"] = "30"
    return paths, environment, root / "sh600000.day", before


def a_command(paths):
    return [sys.executable, "-m", "ops.macos_research_panel_daily", "--date", DATE, "--lane", "A"] + [
        part for name, value in paths.items() for part in ("--" + name, str(value))]


def test_real_public_a_entry_runs_real_sync_and_fails_closed_before_missing_formula(tmp_path):
    paths, environment, day, prefix = a_setup(tmp_path)
    command = a_command(paths)
    first = subprocess.run(command, cwd=REPO, env=environment, capture_output=True, text=True, timeout=20)
    assert first.returncode == 1, first.stderr
    stdout = json.loads(first.stdout)
    assert len(first.stdout.encode()) < 2048
    assert stdout["lanes"]["A"]["status"] == "FAILED"
    receipt_root = paths["receipt-root"]
    summary = json.loads((receipt_root / "a_sync_authority/summary.json").read_text())
    assert summary["status"] == "PASS"
    assert summary["budgets"]["run_budget_seconds"] == 30.0
    assert summary["by_symbol"]["600000"]["records_written"] == 2
    assert day.read_bytes().startswith(prefix)
    assert [b["day"] for b in read_hq_day_bars(day)] == [9, 10, 11]
    assert (receipt_root / "a_sync_authority/file_results.csv").is_file()
    lane_file = receipt_root / f"a-{DATE}.json"
    assert hashlib.sha256(lane_file.read_bytes()).hexdigest() == stdout["lanes"]["A"]["receipt_sha256"]
    calls_before = read_lines(Path(environment["V4_FIXTURE_CALLS"]))
    assert sum(row["event"] == "bars" for row in calls_before) == 1
    artifacts_before = [file_fact(p, tmp_path) for p in sorted(receipt_root.rglob("*")) if p.is_file()]
    second = subprocess.run(command, cwd=REPO, env=environment, capture_output=True, text=True, timeout=20)
    assert second.returncode == 1
    assert read_lines(Path(environment["V4_FIXTURE_CALLS"])) == calls_before
    assert json.loads((receipt_root / "a_sync_authority/summary.json").read_text())["updated_count"] == 0
    record_evidence("public-a-real-sync", {
        "classification": "REAL_PUBLIC_ENTRY_REAL_SYNC_FIXTURE_TRANSPORT_NEGATIVE_E2E",
        "full_authority_manifest_e2e": "CANNOT_CONFIRM", "formula_status": "NOT_INCLUDED_INPUTS_STOP_BEFORE_AUTHORITY",
        "child_exit_codes": [first.returncode, second.returncode], "envelope": stdout,
        "actual_sync_source": file_fact(REPO / "ops/a_share_daily_sync.py", REPO),
        "artifact_facts_first_run": artifacts_before, "day_fact": file_fact(day, tmp_path),
        "initial_history_bytes_preserved": True, "records_appended": 2, "replay_sdk_calls": 0,
        "calls": calls_before, "executed_modules": read_lines(Path(environment["V4_FIXTURE_MODULES"])),
        "stdout_bytes": len(first.stdout.encode()), "diagnostic_stderr_bytes": len(first.stderr.encode()),
        "manifest": "file_results.csv_IS_NOT_FORMULA_PANEL_MANIFEST", "fixture_only": True,
    })


@pytest.mark.parametrize("mode", ["future", "malformed", "budget"])
def test_real_public_entry_preserves_history_on_sync_rejection(tmp_path, mode):
    paths, environment, day, prefix = a_setup(tmp_path)
    if mode == "future":
        environment["V4_FIXTURE_BARS"] = json.dumps([bar(20260910, 10.5), bar(20260911, 11), bar(20260912, 11.2)])
    elif mode == "malformed":
        environment["V4_FIXTURE_BARS"] = json.dumps([{"year": 2026, "month": 9, "day": 11}])
    else:
        environment["V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS"] = "0.005"
        environment["V4_FIXTURE_DELAY"] = "0.02"
    child = subprocess.run(a_command(paths), cwd=REPO, env=environment, capture_output=True, text=True, timeout=20)
    assert child.returncode == 1
    assert day.read_bytes() == prefix
    assert not (paths["receipt-root"] / "a_sync_authority.json").exists()
    envelope = json.loads(child.stdout)
    assert envelope["lanes"]["A"]["status"] == "FAILED"
    summary = json.loads((paths["receipt-root"] / "a_sync_authority/summary.json").read_text())
    assert summary["status"] in {"FAILED", "TIMEOUT"}
    record_evidence("public-a-" + mode, {"fixture_only": True, "entry_exit": child.returncode,
                    "summary_status": summary["status"], "summary_exit": summary["exit_code"],
                    "history_unchanged": True, "ready_authority_receipt": False, "envelope": envelope})


def test_real_hk_public_entry_requires_reusable_master_before_tdx_or_updater(tmp_path):
    env = transport_environment(tmp_path / "sdk-fixture", REPO)
    env["V35_RESEARCH_PANEL_A_SYNC_RUN_BUDGET_SECONDS"] = "invalid-but-unrelated-A-setting"
    tdx, receipt, assets = tmp_path / "hk-fixture", tmp_path / "receipts", tmp_path / "NOT_INCLUDED_FROZEN_ASSETS"
    updater = REPO / "upstreams/v3_shared_data/scripts/update_hk_0_2_panel.py"
    command = [sys.executable, "-m", "ops.macos_research_panel_daily", "--date", DATE,
               "--lane", "HK", "--receipt-root", str(receipt), "--hk-tdx-root", str(tdx),
               "--hk-python-executable", env["V4_FIXTURE_PYTHON"], "--hk-updater-script", str(updater),
               "--hk-asset-root", str(assets)]
    child = subprocess.run(command, cwd=REPO, env=env, capture_output=True, text=True, timeout=20)
    assert child.returncode == 1
    envelope = json.loads(child.stdout)
    assert envelope["lanes"]["HK"]["status"] == "FAILED"
    assert not tdx.exists()
    assert not assets.exists()
    assert not (receipt / "hk_tdx_daily").exists()
    assert not (receipt / "hk_capture").exists()
    modules = read_lines(Path(env["V4_FIXTURE_MODULES"]))
    assert all("futu" not in item["modules"] and "pytdx.hq" not in item["modules"]
               for item in modules)
    calls = read_lines(Path(env["V4_FIXTURE_CALLS"]))
    assert calls == []
    assert not (receipt / f"a-{DATE}.json").exists()
    record_evidence("public-hk-tdx-preflight", {"fixture_only": True,
        "classification": "REAL_PUBLIC_ENTRY_FAILS_CLOSED_BEFORE_TDX_OR_UPDATER",
        "child_exit": child.returncode, "envelope": envelope, "tdx_files_written": 0,
        "artifact_manifest_status": "NOT_PRODUCED_EXACT_DATE_SECURITY_MASTER_UNAVAILABLE",
        "full_positive_e2e": "CANNOT_CONFIRM", "python31312_verified": False,
        "executed_modules": modules, "calls": calls, "updater_source": file_fact(updater, REPO),
        "hk_lane_receipt": file_fact(receipt / f"hk-{DATE}.json", tmp_path)})


def test_bounded_persistent_daemon_real_due_registry_public_sync_and_dispatch_receipt(tmp_path, monkeypatch, capsys):
    from ops import run_v35_macos_scheduler as scheduler
    from ops import run_v35_macos_scheduler_daemon as daemon
    from contracts.runtime_tasks import DispatchRequest, DispatchMode
    from infrastructure.scheduling.catalog import load_workload_catalog
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    paths, environment, day, prefix = a_setup(tmp_path, count=5000)
    # Only raw SDK transport and the clock are fixtures; no updater/registry/main mocks.
    for key in tuple(os.environ):
        if key.startswith("V35_RESEARCH_PANEL_") or key in {"V35_HK_0_2_PYTHON", "V35_UPSTREAM_FINGERPRINT"}:
            monkeypatch.delenv(key)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    for name, path in paths.items():
        monkeypatch.setenv("V35_RESEARCH_PANEL_" + name.upper().replace("-", "_"), str(path))
    monkeypatch.setenv("V35_RELEASE_ID", "OFFLINE_FIXTURE_CANDIDATE")
    ledger_root = tmp_path / "dispatch-fixture"
    request = DispatchRequest(scheduled_date=DATE, business_date=DATE, target_date=DATE, slot="1700", mode=DispatchMode.LIVE)
    hourly = next(w for w in load_workload_catalog().workloads if w.workload_id == "hourly_research")
    claim = ExecutionLedger(ledger_root).try_claim_workload(request, hourly, run_id="fixture-sibling-owner")
    assert claim.acquired  # Isolates unrelated hourly network work without modifying the catalog.
    frozen = datetime(2026, 9, 11, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz is None else frozen.astimezone(tz)
    monkeypatch.setattr(scheduler, "datetime", Clock)
    class BoundedStop(threading.Event):
        waits = 0
        def wait(self, timeout=None):
            self.waits += 1
            if self.waits >= 3:
                self.set()
            return self.is_set()
    stop = BoundedStop()
    rc = daemon.run_daemon(["--data-root", str(tmp_path / "data-fixture"), "--ledger-root", str(ledger_root),
                           "--release-id", "OFFLINE_FIXTURE_CANDIDATE"], clock=lambda: frozen,
                          stop_event=stop, install_signals=False, poll_interval_seconds=.001)
    assert rc == 0  # daemon lifecycle only; cycle/producer must remain FAILED.
    emitted = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    cycles = [row for row in emitted if row.get("status") == "DAEMON_CYCLE"]
    assert len(cycles) == 1 and cycles[0]["return_code"] == 1 and cycles[0]["result_status"] == "FAILED"
    receipts = list(ledger_root.rglob("*.dispatch-receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    result = next(row for row in receipt["workload_results"] if row["workload_id"] == "research_panel_daily_a")
    assert result["status"] == "FAILED" and result["receipt_verified"] is True
    summary = json.loads((paths["receipt-root"] / "a_sync_authority/summary.json").read_text())
    assert summary["status"] == "PASS" and summary["updated_count"] == 1
    assert len(summary["by_symbol"]) == 5000 and day.read_bytes().startswith(prefix)
    calls = read_lines(Path(environment["V4_FIXTURE_CALLS"]))
    assert sum(row["event"] == "bars" for row in calls) == 1
    record_evidence("persistent-real-chain", {"fixture_only": True,
        "classification": "REAL_DAEMON_RUNNER_DUE_REGISTRY_SUBPROCESS_ENTRY_SYNC_DISPATCH_NEGATIVE_E2E",
        "daemon_lifecycle_exit": rc, "cycles": cycles, "cycle_count": 1,
        "same_minute_waits": stop.waits, "dispatch_status": receipt["status"],
        "panel_status": result["lane_status"], "receipt_verified": result["receipt_verified"],
        "dispatch_receipt": file_fact(receipts[0], tmp_path), "sync_summary": {"status": summary["status"],
        "symbols": len(summary["by_symbol"]), "updated_count": summary["updated_count"], "budgets": summary["budgets"]},
        "calls": calls, "full_positive_artifact_manifest_e2e": "CANNOT_CONFIRM",
        "isolated_sibling": "hourly_research preclaimed via real ledger in temporary fixture root",
        "clock": "2026-09-11T17:00:00+08:00", "service_started": False, "natural_slot": False})
