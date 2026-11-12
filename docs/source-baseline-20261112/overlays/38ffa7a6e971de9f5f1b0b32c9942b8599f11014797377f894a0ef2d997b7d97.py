from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from ops import run_scheduled_slot, run_v4_macos_scheduler, run_v4_macos_scheduler_daemon


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "contracts" / "runtime_workloads.json"
EXPECTED_SHA = "a" * 64


def _hourly_workload():
    return next(
        item
        for item in load_workload_catalog(CATALOG).workloads
        if item.workload_id == "hourly_research"
    )


def _request(*, date: str = "20260907", slot: str = "0900") -> DispatchRequest:
    return DispatchRequest(
        scheduled_date=date,
        business_date=date,
        target_date=date,
        slot=slot,
        mode=DispatchMode.LIVE,
    )


def _write_valid_recovery_source(data_root: Path, *, slot: str = "0900") -> tuple[Path, str]:
    incoming = data_root / "research" / "incoming" / "20260907"
    incoming.mkdir(parents=True, exist_ok=True)
    canonical = incoming / f"{slot}.json"
    canonical.write_bytes(b'{"canonical":true}')
    old_source_sha = hashlib.sha256(canonical.read_bytes()).hexdigest()
    cutoff = f"2026-09-07T{slot[:2]}:{slot[2:]}:59+08:00"
    receipts = [f"research_module/hourly/20260907/{slot}.json"]
    authorization = {
        "kind": "EXPLICIT_EXPECTED_OLD_INPUT_SHA256",
        "expected_old_input_sha256": old_source_sha,
        "canonical_path": canonical.resolve().as_posix(),
    }
    recovery_payload = {
        "recovery": True,
        "trade_date": "20260907",
        "slot": slot,
        "source_path": canonical.resolve().as_posix(),
        "original_source_path": canonical.resolve().as_posix(),
        "original_source_sha256": old_source_sha,
        "supersedes": old_source_sha,
        "retry_of_sha256": old_source_sha,
        "pit_cutoff": cutoff,
        "capture_origin": "LATE_RECOVERY",
        "original_time_capture": False,
        "natural_execution_verified": False,
        "source_receipts": receipts,
        "cannot_confirm": [],
        "source_manifest": {
            "trade_date": "20260907",
            "hourly_slot": slot,
            "pit_cutoff": cutoff,
            "capture_origin": "LATE_RECOVERY",
            "original_time_capture": False,
            "natural_execution_verified": False,
            "source_receipts": receipts,
        },
        "recovery_metadata": {
            "trade_date": "20260907",
            "slot": slot,
            "pit_cutoff": cutoff,
            "capture_origin": "LATE_RECOVERY",
            "original_time_capture": False,
            "natural_execution_verified": False,
            "source_path": canonical.resolve().as_posix(),
            "original_source_path": canonical.resolve().as_posix(),
            "original_source_sha256": old_source_sha,
            "supersedes": old_source_sha,
            "retry_of_sha256": old_source_sha,
            "source_receipts": receipts,
            "repair_authorization": authorization,
        },
        "repair_authorization": authorization,
    }
    encoded = json.dumps(
        recovery_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    recovery_sha = hashlib.sha256(encoded).hexdigest()
    recovery = incoming / f"{slot}.recovery-{recovery_sha[:16]}.json"
    recovery.write_bytes(encoded)
    return recovery, old_source_sha


def test_repair_auth_forwards_only_collector_and_recovery_source_to_runner(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []
    recovery_path, expected_old_sha = _write_valid_recovery_source(
        tmp_path / "data"
    )

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(list(command))
        module = command[2]
        if module == "ops.run_zsxq_hourly_delta":
            payload = {"status": "READY"}
        elif module == "ops.materialize_research_peripherals":
            payload = {"status": "SUCCEEDED", "outputs": []}
        elif module == "ops.collect_hourly_research_input":
            payload = {
                "status": "READY_WITH_RESEARCH_POOL",
                "row_count": 10,
                "recovery": True,
                "source_path": recovery_path.relative_to(tmp_path / "data").as_posix(),
                "source_sha256": hashlib.sha256(recovery_path.read_bytes()).hexdigest(),
            }
        else:
            payload = {"status": "SUCCEEDED", "row_count": 10}
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        runner=runner,
        repair_date="20260907",
        repair_slot="0900",
        repair_expected_old_input_sha256=expected_old_sha,
    )
    result = registry(_hourly_workload(), _request(), None)

    assert result["status"] == "SUCCEEDED"
    collector = next(c for c in calls if c[2] == "ops.collect_hourly_research_input")
    assert collector[-2:] == ["--repair-expected-old-input-sha256", expected_old_sha]
    for command in calls:
        if command[2] != "ops.collect_hourly_research_input":
            assert "--repair-expected-old-input-sha256" not in command
    runner_call = next(c for c in calls if c[2] == "ops.run_hourly_research")
    source_index = runner_call.index("--source")
    assert runner_call[source_index + 1] == str(
        recovery_path
    )


@pytest.mark.parametrize("slot", ["0700", "0800"])
def test_explicit_repair_rejects_unsupported_early_slots_before_noop(
    tmp_path: Path, slot: str
) -> None:
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        calls.append(list(command))
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"status": "READY"}), stderr=""
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        runner=runner,
        repair_date="20260907",
        repair_slot=slot,
        repair_expected_old_input_sha256=EXPECTED_SHA,
    )
    with pytest.raises(ValueError, match="REPAIR_SLOT_UNSUPPORTED"):
        registry(_hourly_workload(), _request(slot=slot), None)
    assert calls == []


@pytest.mark.parametrize("slot", ["0700", "0800"])
def test_early_slots_without_repair_remain_expected_noop(
    tmp_path: Path, slot: str
) -> None:
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        calls.append(list(command))
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"status": "READY"}), stderr=""
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        runner=runner,
    )
    result = registry(_hourly_workload(), _request(slot=slot), None)
    assert result["status"] == "SUCCEEDED"
    assert result["no_op"] is True
    assert result["hourly_artifact_status"] == "NOT_SCHEDULED"
    assert calls == []


def test_recovery_flag_canonical_source_fails_before_runner(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    data_root = tmp_path / "data"
    incoming = data_root / "research" / "incoming" / "20260907"
    incoming.mkdir(parents=True)
    canonical = incoming / "0900.json"
    canonical.write_text("{}", encoding="utf-8")
    source_sha = hashlib.sha256(canonical.read_bytes()).hexdigest()

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(list(command))
        module = command[2]
        payload = (
            {"status": "READY"}
            if module == "ops.run_zsxq_hourly_delta"
            else {"status": "SUCCEEDED", "outputs": []}
            if module == "ops.materialize_research_peripherals"
            else {
                "status": "READY_WITH_RESEARCH_POOL",
                "row_count": 10,
                "recovery": True,
                "source_path": "research/incoming/20260907/0900.json",
                "source_sha256": source_sha,
            }
        )
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    registry = FixedExecutorRegistry(
        data_root=data_root,
        repo_root=tmp_path / "repo",
        runner=runner,
        repair_date="20260907",
        repair_slot="0900",
        repair_expected_old_input_sha256=source_sha,
    )
    with pytest.raises(ValueError, match="REPAIR_RECOVERY_PROVENANCE_INVALID"):
        registry(_hourly_workload(), _request(), None)
    assert not any(command[2] == "ops.run_hourly_research" for command in calls)


@pytest.mark.parametrize("malformation", ["sha", "provenance"])
def test_recovery_source_hash_or_provenance_fails_before_runner(
    tmp_path: Path, malformation: str
) -> None:
    calls: list[list[str]] = []
    data_root = tmp_path / "data"
    recovery_path, expected_old_sha = _write_valid_recovery_source(data_root)
    payload = json.loads(recovery_path.read_text(encoding="utf-8"))
    if malformation == "provenance":
        payload["original_time_capture"] = True
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        recovery_sha = hashlib.sha256(encoded).hexdigest()
        recovery_path = recovery_path.with_name(
            f"0900.recovery-{recovery_sha[:16]}.json"
        )
        recovery_path.write_bytes(encoded)
    source_sha = "f" * 64 if malformation == "sha" else hashlib.sha256(
        recovery_path.read_bytes()
    ).hexdigest()

    def runner(command, *, cwd, timeout_seconds, env):
        del cwd, timeout_seconds, env
        calls.append(list(command))
        module = command[2]
        if module == "ops.run_zsxq_hourly_delta":
            payload = {"status": "READY"}
        elif module == "ops.materialize_research_peripherals":
            payload = {"status": "SUCCEEDED", "outputs": []}
        else:
            payload = {
                "status": "READY_WITH_RESEARCH_POOL",
                "row_count": 10,
                "recovery": True,
                "source_path": recovery_path.relative_to(data_root).as_posix(),
                "source_sha256": source_sha,
            }
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    registry = FixedExecutorRegistry(
        data_root=data_root,
        repo_root=tmp_path / "repo",
        runner=runner,
        repair_date="20260907",
        repair_slot="0900",
        repair_expected_old_input_sha256=expected_old_sha,
    )
    with pytest.raises(ValueError, match="REPAIR_RECOVERY_PROVENANCE_INVALID"):
        registry(_hourly_workload(), _request(), None)
    assert not any(command[2] == "ops.run_hourly_research" for command in calls)


def test_repair_date_slot_mismatch_fails_before_any_workload(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        del kwargs
        calls.append(list(command))
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"status": "READY"}), stderr=""
        )

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        runner=runner,
        repair_date="20260907",
        repair_slot="0900",
        repair_expected_old_input_sha256=EXPECTED_SHA,
    )
    with pytest.raises(ValueError, match="REPAIR_AUTH_DATE_SLOT_MISMATCH"):
        registry(_hourly_workload(), _request(date="20260908"), None)
    assert calls == []


def test_one_shot_scheduler_requires_explicit_date_and_slot_for_repair() -> None:
    with pytest.raises(SystemExit):
        run_v4_macos_scheduler.main(
            [
                "--data-root",
                "/tmp/data",
                "--ledger-root",
                "/tmp/ledger",
                "--slot",
                "0900",
                "--repair-expected-old-input-sha256",
                EXPECTED_SHA,
            ]
        )

    with pytest.raises(SystemExit):
        run_scheduled_slot.main(
            [
                "--data-root",
                "/tmp/data",
                "--slot",
                "0900",
                "--repair-expected-old-input-sha256",
                EXPECTED_SHA,
            ]
        )


def test_persistent_daemon_rejects_repair_authorization() -> None:
    calls: list[list[str]] = []

    def scheduler_main(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    result = run_v4_macos_scheduler_daemon.run_daemon(
        [
            "--slot",
            "0900",
            "--date",
            "20260907",
            "--repair-expected-old-input-sha256",
            EXPECTED_SHA,
        ],
        scheduler_main=scheduler_main,
        install_signals=False,
    )
    assert result == 2
    assert calls == []
    assert "REPAIR_AUTH_FORBIDDEN_IN_DAEMON" in (
        run_v4_macos_scheduler_daemon.last_emitted_output()
    )
