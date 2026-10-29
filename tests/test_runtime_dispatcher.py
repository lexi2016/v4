from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling import execution_ledger as execution_ledger_module


ROOT = Path(__file__).resolve().parents[1]


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def __call__(self, workload, request, decision) -> dict[str, str]:
        self.calls.append(
            (workload.workload_id, request.business_date, decision.eligible_markets)
        )
        return {"status": "SUCCEEDED"}


def test_weekend_dispatch_starts_no_trade_day_runner(tmp_path) -> None:
    executor = FakeExecutor()
    receipt = dispatch_due(
        DispatchRequest("20260725", "20260725", "20260725", "1200", DispatchMode.LIVE),
        load_workload_catalog(),
        executor,
        ledger=ExecutionLedger(tmp_path),
    )

    assert receipt.status == "NON_TRADING_DAY"
    assert receipt.started_workload_ids == ()
    assert receipt.selected_workload_ids == ()
    assert executor.calls == []
    assert not list(tmp_path.rglob("workloads"))


def test_trading_day_dry_run_selects_due_workload_without_execution(tmp_path) -> None:
    executor = FakeExecutor()
    receipt = dispatch_due(
        DispatchRequest("20260730", "20260730", "20260730", "1200", DispatchMode.LIVE),
        load_workload_catalog(),
        executor,
        ledger=ExecutionLedger(tmp_path),
        dry_run=True,
    )

    assert receipt.status == "DRY_RUN_SELECTED"
    assert receipt.selected_workload_ids == ("hourly_research",)
    assert receipt.started_workload_ids == ()
    assert executor.calls == []
    assert receipt.eligible_markets == ("a_share", "hk_connect")


def test_injected_executor_runs_only_after_workload_claim(tmp_path) -> None:
    executor = FakeExecutor()
    receipt = dispatch_due(
        DispatchRequest("20260730", "20260730", "20260730", "1200", DispatchMode.LIVE),
        load_workload_catalog(),
        executor,
        ledger=ExecutionLedger(tmp_path),
        dry_run=False,
    )

    assert receipt.status == "SUCCEEDED"
    assert receipt.started_workload_ids == ("hourly_research",)
    assert executor.calls == [
        ("hourly_research", "20260730", ("a_share", "hk_connect"))
    ]
    workload_claims = list(tmp_path.rglob("*.workload-claim.json"))
    assert len(workload_claims) == 1
    workload_claim = json.loads(workload_claims[0].read_text(encoding="utf-8"))
    assert {
        field: workload_claim[field]
        for field in ("scheduled_date", "business_date", "target_date", "slot", "mode")
    } == {
        "scheduled_date": "20260730",
        "business_date": "20260730",
        "target_date": "20260730",
        "slot": "1200",
        "mode": "LIVE",
    }


def test_live_mode_rejects_cross_date_request() -> None:
    with pytest.raises(ValueError, match="LIVE"):
        DispatchRequest("20260731", "20260730", "20260730", "1200", DispatchMode.LIVE)


@pytest.mark.parametrize("relative", ["../outside.json", "C:/outside.json"])
def test_execution_ledger_rejects_path_escape(tmp_path, relative: str) -> None:
    with pytest.raises(ValueError, match="execution ledger path escaped root"):
        ExecutionLedger(tmp_path)._path(relative)


def test_backfill_uses_isolated_namespace_and_never_live_pointer(tmp_path) -> None:
    receipt = dispatch_due(
        DispatchRequest("20260731", "20260730", "20260730", "1200", DispatchMode.BACKFILL),
        load_workload_catalog(),
        FakeExecutor(),
        ledger=ExecutionLedger(tmp_path),
        dry_run=True,
    )

    assert receipt.status == "DRY_RUN_SELECTED"
    assert receipt.mode is DispatchMode.BACKFILL
    assert "/backfill/" in receipt.receipt_path.replace("\\", "/")
    assert not list(tmp_path.rglob("latest.json"))
    assert not list(tmp_path.rglob("live"))


def test_two_dispatcher_processes_produce_one_selection_and_one_skip(tmp_path) -> None:
    command = [
        sys.executable,
        "-m",
        "ops.run_dispatcher",
        "--mode",
        "live",
        "--scheduled-date",
        "20260730",
        "--business-date",
        "20260730",
        "--target-date",
        "20260730",
        "--slot",
        "1200",
        "--data-root",
        str(tmp_path),
        "--dry-run",
    ]
    processes = [
        subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        for _ in range(2)
    ]
    outputs = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        outputs.append(json.loads(stdout.strip().splitlines()[-1]))

    assert sorted(output["status"] for output in outputs) == [
        "CONCURRENCY_SKIPPED",
        "DRY_RUN_SELECTED",
    ]
    assert sum(output["selected_workload_ids"] == ["hourly_research"] for output in outputs) == 1
    assert not list(tmp_path.rglob("*.workload-claim.json"))
    assert len(list(tmp_path.rglob("*.dispatch-receipt.json"))) == 1


def test_cli_accepts_contract_uppercase_mode(tmp_path) -> None:
    command = [
        sys.executable,
        "-m",
        "ops.run_dispatcher",
        "--mode",
        "LIVE",
        "--scheduled-date",
        "20260730",
        "--business-date",
        "20260730",
        "--target-date",
        "20260730",
        "--slot",
        "1200",
        "--data-root",
        str(tmp_path),
        "--dry-run",
    ]

    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip().splitlines()[-1])["mode"] == "LIVE"


def test_dispatch_request_requires_explicit_target_date() -> None:
    with pytest.raises(TypeError):
        DispatchRequest(
            scheduled_date="20260730",
            business_date="20260730",
            slot="1200",
            mode=DispatchMode.LIVE,
        )


def test_explicit_cross_day_target_is_preserved_without_implicit_roll(tmp_path) -> None:
    payload = load_workload_catalog().source_payload
    hourly = next(
        row for row in payload["workloads"] if row["workload_id"] == "hourly_research"
    )
    hourly["target_date_role"] = "TARGET_DATE"
    catalog_path = tmp_path / "target_date_catalog.json"
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")
    request = DispatchRequest(
        scheduled_date="20260730",
        business_date="20260730",
        target_date="20260731",
        slot="1200",
        mode=DispatchMode.LIVE,
    )

    receipt = dispatch_due(
        request,
        load_workload_catalog(catalog_path),
        FakeExecutor(),
        ledger=ExecutionLedger(tmp_path / "ledger"),
        dry_run=True,
    )

    assert receipt.target_date == "20260731"
    assert receipt.to_dict()["target_date"] == "20260731"
    assert receipt.resolved_dates["hourly_research"]["target_date"] == "20260731"


def test_target_date_must_be_a_real_explicit_date() -> None:
    with pytest.raises(ValueError, match="target_date"):
        DispatchRequest(
            scheduled_date="20260730",
            business_date="20260730",
            target_date="20260732",
            slot="1200",
            mode=DispatchMode.LIVE,
        )


def test_powershell_launcher_requires_and_forwards_target_date() -> None:
    launcher = (ROOT / "ops" / "launch_v4_dispatcher.ps1").read_text(
        encoding="utf-8"
    )

    assert "[Parameter(Mandatory = $true)][string]$TargetDate" in launcher
    assert "'--target-date', $TargetDate" in launcher


def test_same_idempotency_key_with_different_target_date_fails_closed(tmp_path) -> None:
    ledger = ExecutionLedger(tmp_path)
    first = DispatchRequest(
        "20260730", "20260730", "20260731", "1200", DispatchMode.LIVE
    )
    second = DispatchRequest(
        "20260730", "20260730", "20260801", "1200", DispatchMode.LIVE
    )

    first_receipt = dispatch_due(
        first,
        load_workload_catalog(),
        FakeExecutor(),
        ledger=ledger,
        dry_run=True,
    )
    dispatch_claim = json.loads(
        next(tmp_path.rglob("dispatch.claim.json")).read_text(encoding="utf-8")
    )

    assert first_receipt.status == "DRY_RUN_SELECTED"
    assert dispatch_claim["target_date"] == "20260731"
    with pytest.raises(ValueError, match="execution claim identity conflict"):
        dispatch_due(
            second,
            load_workload_catalog(),
            FakeExecutor(),
            ledger=ledger,
            dry_run=True,
        )


def test_same_request_retries_a_claim_that_is_created_but_not_written(
    tmp_path, monkeypatch
) -> None:
    ledger = ExecutionLedger(tmp_path)
    request = DispatchRequest(
        "20260730", "20260730", "20260731", "1200", DispatchMode.LIVE
    )
    # Simulate an in-flight legacy writer. New claims publish complete bytes,
    # while readers must still tolerate a legacy final path being filled in.
    destination = tmp_path / "claims/live/20260730/1200/dispatch.claim.json"
    destination.parent.mkdir(parents=True)
    handle = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    payload = json.dumps({
        "schema_version": "v3_5.dispatch_claim.v1",
        "run_id": "legacy-in-flight",
        "pid": os.getpid(),
        "scheduled_date": request.scheduled_date,
        "business_date": request.business_date,
        "target_date": request.target_date,
        "slot": request.slot,
        "mode": request.mode.value,
    }).encode("utf-8")
    write_entered = threading.Event()
    release_write = threading.Event()
    original_write = os.write
    original_sleep = time.sleep

    def delayed_write(handle: int, payload: bytes) -> int:
        write_entered.set()
        assert release_write.wait(timeout=5)
        return original_write(handle, payload)

    def release_during_retry(delay: float) -> None:
        release_write.set()
        original_sleep(delay)

    monkeypatch.setattr(execution_ledger_module.time, "sleep", release_during_retry)
    errors: list[BaseException] = []

    def acquire_first() -> None:
        try:
            delayed_write(handle, payload)
            os.fsync(handle)
        except BaseException as error:
            errors.append(error)
        finally:
            os.close(handle)

    worker = threading.Thread(target=acquire_first)
    worker.start()
    try:
        assert write_entered.wait(timeout=5)
        second = ledger.try_claim_dispatch(request)
    finally:
        release_write.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert not errors
    assert second.acquired is False
    assert second.run_id == "legacy-in-flight"


def test_persistently_corrupt_existing_claim_fails_closed(tmp_path, monkeypatch) -> None:
    ledger = ExecutionLedger(tmp_path)
    request = DispatchRequest(
        "20260730", "20260730", "20260731", "1200", DispatchMode.LIVE
    )
    destination = tmp_path / "claims" / "live" / "20260730" / "1200"
    destination.mkdir(parents=True)
    (destination / "dispatch.claim.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(execution_ledger_module, "CLAIM_READ_ATTEMPTS", 2)
    monkeypatch.setattr(execution_ledger_module, "CLAIM_READ_DELAY_SECONDS", 0)

    with pytest.raises(ValueError, match="execution claim is unreadable"):
        ledger.try_claim_dispatch(request)
