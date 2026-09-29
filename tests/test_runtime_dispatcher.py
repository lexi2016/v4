from __future__ import annotations

import json
import hashlib
import inspect
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling import dispatcher as dispatcher_module
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling import execution_ledger as execution_ledger_module


ROOT = Path(__file__).resolve().parents[1]


def _write_release_binding(app_root: Path, manifest_path: Path, release_id: str) -> dict[str, str]:
    entries = []
    for relative in dispatcher_module._RUNTIME_IDENTITY_FILES:
        content = (app_root / relative).read_bytes()
        entries.append({
            "path": relative,
            "kind": "file",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        })
    inventory = {
        "entries": entries,
        "entry_count": len(entries),
        "aggregate_sha256": hashlib.sha256(json.dumps(
            entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
    }
    raw = json.dumps({
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"app_root": str(app_root), "release_id": release_id},
        "application_inventory": inventory,
    }, sort_keys=True).encode()
    manifest_path.write_bytes(raw)
    return {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": release_id,
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(raw).hexdigest(),
    }


def _copy_runtime_candidate(tmp_path: Path) -> Path:
    app_root = tmp_path / "candidate" / "v4_app"
    for relative in dispatcher_module._RUNTIME_IDENTITY_FILES:
        destination = app_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    return app_root


def _load_trade_day_dispatch_test_catalog(tmp_path: Path):
    """Build the declared trade-day scenario without rewriting NATURAL_DAY source semantics."""
    source = ROOT / "contracts" / "runtime_workloads.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    workload = next(row for row in payload["workloads"] if row["workload_id"] == "hourly_research")
    # The frozen source catalog currently declares hourly_research as NATURAL_DAY.
    # These dispatch tests exercise the trade-day policy branch, so express that
    # policy explicitly in a temporary catalog that still passes the strict loader.
    workload["run_policy"] = "A_OR_HK_CONNECT_TRADE_DAY"
    path = tmp_path / "trade-day-dispatch-test-catalog.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return load_workload_catalog(path)


def _assert_slot_release_identity(result, *, expected_release_id: str, expected_app_root: str) -> None:
    assert result["release_id"] == expected_release_id, "slot release_id mismatch"
    assert result["app_root"] == expected_app_root, "slot app_root mismatch"


@pytest.fixture(autouse=True)
def approved_release_binding(tmp_path, monkeypatch):
    """Pin real running-source bytes, not a mock identity verifier."""
    env = _write_release_binding(ROOT, tmp_path / "release-manifest.json", "fixture-reviewed-release")
    for key, value in env.items(): monkeypatch.setenv(key, value)
    return env


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
        _load_trade_day_dispatch_test_catalog(tmp_path),
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
        _load_trade_day_dispatch_test_catalog(tmp_path),
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
        _load_trade_day_dispatch_test_catalog(tmp_path),
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


def test_canonical_hourly_research_keeps_natural_day_contract(tmp_path) -> None:
    catalog = load_workload_catalog()
    hourly = next(row for row in catalog.workloads if row.workload_id == "hourly_research")
    assert hourly.run_policy.value == "NATURAL_DAY"
    assert hourly.market_scope.value == "CROSS_MARKET"
    assert hourly.session_requirement.value == "DAY_ELIGIBILITY_ONLY"

    executor = FakeExecutor()
    receipt = dispatch_due(
        DispatchRequest("20260725", "20260725", "20260725", "1200", DispatchMode.LIVE),
        catalog,
        executor,
        ledger=ExecutionLedger(tmp_path),
    )

    assert receipt.status == "SUCCEEDED"
    assert receipt.selected_workload_ids == ("hourly_research",)
    assert receipt.started_workload_ids == ("hourly_research",)
    assert receipt.eligible_markets == ()
    assert executor.calls == [("hourly_research", "20260725", ())]


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
    launcher = (ROOT / "ops" / "launch_v35_dispatcher.ps1").read_text(
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

    monkeypatch.setattr(execution_ledger_module.os, "write", delayed_write)
    monkeypatch.setattr(execution_ledger_module.time, "sleep", release_during_retry)
    first: dict[str, object] = {}

    def acquire_first() -> None:
        first["claim"] = ledger.try_claim_dispatch(request)

    worker = threading.Thread(target=acquire_first)
    worker.start()
    assert write_entered.wait(timeout=5)
    second = ledger.try_claim_dispatch(request)
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert first["claim"].acquired is True
    assert second.acquired is False
    assert second.run_id == first["claim"].run_id


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


@pytest.mark.parametrize("field", ["V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256"])
def test_release_identity_missing_rejects_before_claim(tmp_path, monkeypatch, field):
    monkeypatch.delenv(field)
    executor = FakeExecutor(); ledger = ExecutionLedger(tmp_path / "ledger")
    receipt = dispatch_due(DispatchRequest("20260914", "20260914", "20260914", "1200", DispatchMode.LIVE),
                           load_workload_catalog(), executor, ledger=ledger)
    assert receipt.status == "FAILED" and receipt.failure_class == "RELEASE_IDENTITY"
    assert executor.calls == [] and not list((tmp_path / "ledger").rglob("*.json"))

@pytest.mark.parametrize("field,value", [("V35_APP_ROOT", "/not/current/release"), ("V35_RELEASE_ID", "wrong-release"),
                                        ("V35_RELEASE_MANIFEST_SHA256", "0"*64)])
def test_release_identity_mismatch_rejects_before_executor(tmp_path, monkeypatch, field, value):
    monkeypatch.setenv(field, value); executor = FakeExecutor()
    receipt = dispatch_due(DispatchRequest("20260914", "20260914", "20260914", "1200", DispatchMode.LIVE),
                           load_workload_catalog(), executor, ledger=ExecutionLedger(tmp_path / "ledger"))
    assert receipt.status == "FAILED" and receipt.failure_class == "RELEASE_IDENTITY"
    assert not executor.calls


def test_release_renderer_dispatcher_and_slot_bind_same_identity(tmp_path, approved_release_binding, monkeypatch):
    from ops.install_v35_macos_launchagents import build_scheduler_plist
    from ops.run_scheduled_slot import run_scheduled_slot
    app_root = _copy_runtime_candidate(tmp_path)
    candidate_binding = _write_release_binding(
        app_root, tmp_path / "candidate-release-manifest.json", approved_release_binding["V35_RELEASE_ID"]
    )
    monkeypatch.setattr(
        dispatcher_module, "__file__", str(app_root / "infrastructure/scheduling/dispatcher.py")
    )
    for key, value in candidate_binding.items(): monkeypatch.setenv(key, value)
    kwargs = {name: str(tmp_path / name) for name, item in inspect.signature(build_scheduler_plist).parameters.items()
              if item.default is inspect.Parameter.empty}
    kwargs.update(app_root=str(app_root), release_id=candidate_binding["V35_RELEASE_ID"],
                  upstream_fingerprint="fixture-upstream", release_manifest_path=candidate_binding["V35_RELEASE_MANIFEST_PATH"],
                  release_manifest_sha256=candidate_binding["V35_RELEASE_MANIFEST_SHA256"])
    rejected_kwargs = dict(kwargs, app_root="/Users/lexi/Desktop/学习/v4_app")
    with pytest.raises(ValueError, match="read-only Desktop/学习 root"):
        build_scheduler_plist(**rejected_kwargs)
    plist = build_scheduler_plist(**kwargs)
    for key, value in plist["EnvironmentVariables"].items(): monkeypatch.setenv(key, value)
    receipt = dispatch_due(DispatchRequest("20260914", "20260914", "20260914", "0700", DispatchMode.LIVE),
                           load_workload_catalog(), FakeExecutor(), ledger=ExecutionLedger(tmp_path / "ledger"), dry_run=True)
    assert receipt.release_id == candidate_binding["V35_RELEASE_ID"]
    assert receipt.release_manifest_sha256 == candidate_binding["V35_RELEASE_MANIFEST_SHA256"]
    saved = json.loads((tmp_path / "ledger" / "dry-run" / receipt.receipt_path).read_text())
    assert saved["release_manifest_sha256"] == receipt.release_manifest_sha256
    result = run_scheduled_slot(data_root=tmp_path / "data", ledger_root=tmp_path / "slot-ledger", slot="0700",
                               business_date="20260914", scheduled_date="20260914", target_date="20260914", dry_run=True)
    _assert_slot_release_identity(
        result,
        expected_release_id=candidate_binding["V35_RELEASE_ID"],
        expected_app_root=str(app_root),
    )
    assert result["release_manifest_path"] == receipt.release_manifest_path
    assert result["release_manifest_sha256"] == receipt.release_manifest_sha256


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    (("release_id", "wrong-release"), ("app_root", "/wrong/candidate/root")),
)
def test_slot_identity_readback_assertions_reject_mutated_identity(field: str, wrong_value: str) -> None:
    """A mutation of either returned identity field must make the positive oracle go red."""

    mutated = {
        "release_id": "fixture-reviewed-release",
        "app_root": "/fixture/candidate/root",
    }
    mutated[field] = wrong_value

    with pytest.raises(AssertionError, match=field):
        _assert_slot_release_identity(
            mutated,
            expected_release_id="fixture-reviewed-release",
            expected_app_root="/fixture/candidate/root",
        )


def test_scheduled_slot_rejects_mismatched_release_identity_before_readback(
    tmp_path, approved_release_binding, monkeypatch
):
    from ops.run_scheduled_slot import run_scheduled_slot

    monkeypatch.setenv("V35_RELEASE_ID", "self-asserted-wrong-release")
    result = run_scheduled_slot(
        data_root=tmp_path / "data",
        ledger_root=tmp_path / "slot-ledger",
        slot="0700",
        business_date="20260914",
        scheduled_date="20260914",
        target_date="20260914",
        dry_run=True,
    )

    assert result["status"] == "FAILED"
    assert result["failure_class"] == "RELEASE_IDENTITY"
    assert result["release_id"] is None
    assert result["app_root"] is None
    assert result["release_manifest_path"] is None
    assert result["release_manifest_sha256"] is None
    assert not list((tmp_path / "slot-ledger").rglob("*.workload-claim.json"))


def test_manifest_inventory_bad_runtime_hash_rejected(tmp_path, approved_release_binding, monkeypatch):
    path = Path(approved_release_binding["V35_RELEASE_MANIFEST_PATH"])
    obj = json.loads(path.read_bytes()); entries = obj["application_inventory"]["entries"]
    entries[0]["sha256"] = "1" * 64
    obj["application_inventory"]["aggregate_sha256"] = hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    raw = json.dumps(obj).encode(); path.write_bytes(raw); monkeypatch.setenv("V35_RELEASE_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())
    executor = FakeExecutor()
    receipt = dispatch_due(DispatchRequest("20260914", "20260914", "20260914", "0700", DispatchMode.LIVE), load_workload_catalog(), executor)
    assert receipt.failure_class == "RELEASE_IDENTITY" and not executor.calls


@pytest.mark.parametrize("missing", dispatcher_module._RUNTIME_IDENTITY_FILES)
def test_release_identity_missing_runtime_inventory_entry_rejected(tmp_path, approved_release_binding, monkeypatch, missing):
    manifest = Path(approved_release_binding["V35_RELEASE_MANIFEST_PATH"])
    payload = json.loads(manifest.read_bytes())
    entries = [entry for entry in payload["application_inventory"]["entries"] if entry["path"] != missing]
    payload["application_inventory"]["entries"] = entries
    payload["application_inventory"]["entry_count"] = len(entries)
    payload["application_inventory"]["aggregate_sha256"] = hashlib.sha256(json.dumps(
        entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    raw = json.dumps(payload, sort_keys=True).encode()
    manifest.write_bytes(raw)
    monkeypatch.setenv("V35_RELEASE_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())

    executor = FakeExecutor()
    ledger = ExecutionLedger(tmp_path / "ledger")
    receipt = dispatch_due(
        DispatchRequest("20260914", "20260914", "20260914", "1200", DispatchMode.LIVE),
        load_workload_catalog(),
        executor,
        ledger=ledger,
    )
    assert receipt.status == "FAILED" and receipt.failure_class == "RELEASE_IDENTITY"
    assert executor.calls == []
    assert not list((tmp_path / "ledger").rglob("*.json"))


@pytest.mark.parametrize("mutated", dispatcher_module._RUNTIME_IDENTITY_FILES)
def test_release_identity_rejects_mutated_runtime_inventory_file_before_executor(tmp_path, monkeypatch, mutated):
    """A reviewed manifest must bind every byte in the dispatcher runtime identity."""

    app = tmp_path / "candidate" / "v4_app"
    entries = []
    for relative in dispatcher_module._RUNTIME_IDENTITY_FILES:
        source = ROOT / relative
        destination = app / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        destination.write_bytes(content)
        entries.append({
            "path": relative,
            "kind": "file",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        })
    inventory = {
        "entries": entries,
        "entry_count": len(entries),
        "aggregate_sha256": hashlib.sha256(
            json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    manifest = tmp_path / "release-manifest.json"
    raw = json.dumps({
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"app_root": str(app), "release_id": "fixture-intraday-identity"},
        "application_inventory": inventory,
    }, ensure_ascii=False, sort_keys=True).encode()
    manifest.write_bytes(raw)
    manifest_sha = hashlib.sha256(raw).hexdigest()
    mutated_path = app / mutated
    mutated_path.write_bytes(mutated_path.read_bytes() + b"\n# isolated identity mutation\n")

    monkeypatch.setattr(dispatcher_module, "__file__", str(app / "infrastructure/scheduling/dispatcher.py"))
    monkeypatch.setenv("V35_APP_ROOT", str(app))
    monkeypatch.setenv("V35_RELEASE_ID", "fixture-intraday-identity")
    monkeypatch.setenv("V35_RELEASE_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("V35_RELEASE_MANIFEST_SHA256", manifest_sha)

    executor = FakeExecutor()
    ledger = ExecutionLedger(tmp_path / "ledger")
    receipt = dispatch_due(
        DispatchRequest("20260914", "20260914", "20260914", "1200", DispatchMode.LIVE),
        load_workload_catalog(),
        executor,
        ledger=ledger,
    )
    assert receipt.status == "FAILED" and receipt.failure_class == "RELEASE_IDENTITY"
    assert executor.calls == []
    assert not list((tmp_path / "ledger").rglob("*.json"))


def test_real_catalog_dispatches_single_intraday_cli_and_binds_release(tmp_path, monkeypatch, approved_release_binding):
    """1130 has only the replacement task; no stub success for other workloads."""
    from test_v4_intraday_research import fixture_config
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from ops.run_intraday_research import main
    from domains.intraday_research import read_intraday_day
    import contextlib, io
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path, "11:30")
    for key, val in {"V4_INTRADAY_CONFIG_PATH": str(path), "V4_INTRADAY_CONFIG_SHA256": pin,
                     "V4_INTRADAY_SOURCE_MANIFEST_SHA256": code}.items(): monkeypatch.setenv(key, val)
    commands = []
    def runner(command, **kwargs):
        commands.append(command)
        assert command[1:3] == ["-m", "ops.run_intraday_research"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = main(command[3:], transport=transport, clock=lambda: stamp)
        return subprocess.CompletedProcess(command, rc, output.getvalue(), "")
    registry = FixedExecutorRegistry(tmp_path / "data", runner=runner)
    receipt = dispatch_due(DispatchRequest("20260914", "20260914", "20260914", "1130", DispatchMode.LIVE),
                           load_workload_catalog(), registry, ledger=ExecutionLedger(tmp_path / "ledger"))
    assert receipt.status == "SUCCEEDED"
    assert receipt.started_workload_ids == ("v4_intraday_research",)
    assert receipt.release_manifest_sha256 == approved_release_binding["V35_RELEASE_MANIFEST_SHA256"]
    assert commands == [[sys.executable, "-m", "ops.run_intraday_research",
                         "--date", "20260914", "--slot", "1130",
                         "--config", str(path), "--config-sha256", pin,
                         "--source-manifest-sha256", code]]
    execution = receipt.workload_results[0]
    assert execution["modules"] == ["ops.run_intraday_research"]
    assert execution["exit_code"] == 0 and execution["stderr"] == ""
    cli_payload = json.loads(execution["stdout"])
    assert cli_payload["status"] == "SUCCEEDED"
    assert cli_payload["quote_day_observed"] == "2026-09-14"
    assert cli_payload["production_allowed"] is False
    assert cli_payload["buy_gate_updated"] is False
    assert cli_payload["orders_sent"] is False
    assert execution["intraday_evidence"]["slot"] == "11:30"
    view = read_intraday_day("20260914", intraday_root=tmp_path / "state/intraday")
    assert view["slots"][0]["slot"] == "11:30"
    assert sum(transport.calls.values()) == 6 and len(commands) == 1
