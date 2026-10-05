from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from infrastructure.scheduling.execution_ledger import ExecutionLedger
from v4_migration.drain_observer import ProcessIdentity, observe_workload_drain


BUSINESS_DATE = "20260918"
SCHEDULED_DATE = "20260918"
TARGET_DATE = "20260921"
SLOT = "1730"
WORKLOAD_ID = "preselection_pools"
RUN_ID = "run-001"
PID = 61321


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_case(
    root: Path,
    *,
    run_id: str = RUN_ID,
    business_date: str = BUSINESS_DATE,
    slot: str = SLOT,
    workload_id: str = WORKLOAD_ID,
    pid: int = PID,
    process_start_identity: str | None = "birth-61321",
) -> tuple[ExecutionLedger, dict[str, Path]]:
    ledger = ExecutionLedger(root)
    mode = "LIVE"
    dispatch_relative = f"claims/live/{business_date}/{slot}/dispatch.claim.json"
    workload_relative = (
        f"workloads/live/{business_date}/{slot}/{workload_id}.workload-claim.json"
    )
    receipt_relative = f"receipts/live/{business_date}/{slot}/{run_id}.dispatch-receipt.json"
    dispatch = {
        "schema_version": "v3_5.dispatch_claim.v1",
        "run_id": run_id,
        "pid": pid,
        "created_at": "2026-09-18T09:30:00Z",
        "scheduled_date": SCHEDULED_DATE,
        "business_date": business_date,
        "target_date": TARGET_DATE,
        "slot": slot,
        "mode": mode,
    }
    workload = {
        "schema_version": "v3_5.workload_claim.v1",
        "run_id": run_id,
        "workload_id": workload_id,
        "scheduled_date": SCHEDULED_DATE,
        "business_date": business_date,
        "target_date": TARGET_DATE,
        "slot": slot,
        "mode": mode,
        "pid": pid,
        "created_at": "2026-09-18T09:30:00Z",
    }
    if process_start_identity is not None:
        dispatch["process_start_identity"] = process_start_identity
        workload["process_start_identity"] = process_start_identity
    for relative, record in ((dispatch_relative, dispatch), (workload_relative, workload)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_json_bytes(record))
    ledger.write_receipt(
        receipt_relative,
        {
            "schema_version": "v3_5.dispatch_receipt.v1",
            "run_id": run_id,
            "scheduled_date": SCHEDULED_DATE,
            "business_date": business_date,
            "target_date": TARGET_DATE,
            "slot": slot,
            "mode": mode,
            "status": "SUCCEEDED",
            "selected_workload_ids": [workload_id],
            "started_workload_ids": [workload_id],
            "workload_results": [{"workload_id": workload_id, "status": "SUCCEEDED"}],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )
    return ledger, {
        "dispatch": root / dispatch_relative,
        "workload": root / workload_relative,
        "receipt": root / receipt_relative,
    }


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _live_identity(pid: int) -> ProcessIdentity:
    return ProcessIdentity(pid=pid, start_identity="birth-61321", parent_pid=1)


def test_live_parent_blocks_drain_and_observer_is_read_only(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ledger"
    ledger, _paths = _write_case(root)
    before = _tree_bytes(root)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("observer attempted a forbidden side effect")

    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(os, "unlink", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    snapshot = observe_workload_drain(
        ledger,
        workload_id=WORKLOAD_ID,
        business_date=BUSINESS_DATE,
        slot=SLOT,
        process_identity_provider=_live_identity,
    )

    assert snapshot["status"] == "BLOCKED"
    assert snapshot["drained"] is False
    assert any(row["status"] == "LIVE_BLOCKER" for row in snapshot["processes"])
    assert snapshot["lineage"]["status"] == "CANNOT_CONFIRM"
    assert snapshot["admission_barrier"]["identity_recorded"] is False
    assert snapshot["lease"]["identity_recorded"] is False
    assert _tree_bytes(root) == before


def test_pid_reuse_or_start_identity_mismatch_is_unknown(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    ledger, _paths = _write_case(root, process_start_identity="birth-before-reuse")
    before = _tree_bytes(root)

    def reused(pid: int) -> ProcessIdentity:
        return ProcessIdentity(pid=pid, start_identity="birth-after-reuse", parent_pid=1)

    snapshot = observe_workload_drain(
        ledger,
        workload_id=WORKLOAD_ID,
        business_date=BUSINESS_DATE,
        slot=SLOT,
        process_identity_provider=reused,
    )

    assert snapshot["status"] == "CANNOT_CONFIRM"
    assert snapshot["drained"] is False
    assert any("START_IDENTITY_MISMATCH" in reason for reason in snapshot["blockers"])
    assert all(row["status"] == "UNKNOWN" for row in snapshot["processes"])
    assert _tree_bytes(root) == before


def test_unrecorded_descendant_keeps_legacy_claim_cannot_confirm(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    ledger, _paths = _write_case(root, process_start_identity=None)
    before = _tree_bytes(root)

    snapshot = observe_workload_drain(
        ledger,
        workload_id=WORKLOAD_ID,
        business_date=BUSINESS_DATE,
        slot=SLOT,
        process_identity_provider=lambda _pid: None,
    )

    assert snapshot["status"] == "CANNOT_CONFIRM"
    assert snapshot["drained"] is False
    assert "CHILD_PROCESS_IDENTITIES_NOT_RECORDED" in snapshot["blockers"]
    assert "ADMISSION_BARRIER_IDENTITY_NOT_REPRESENTED" in snapshot["blockers"]
    assert "LEASE_IDENTITY_NOT_REPRESENTED" in snapshot["blockers"]
    assert _tree_bytes(root) == before


@pytest.mark.parametrize(
    ("damaged_record", "damage"),
    [
        ("dispatch", "missing"),
        ("workload", "corrupt"),
        ("receipt", "missing"),
        ("receipt", "corrupt"),
    ],
)
def test_missing_or_corrupt_claim_and_receipt_remain_cannot_confirm(
    tmp_path: Path, damaged_record: str, damage: str
) -> None:
    root = tmp_path / "ledger"
    ledger, paths = _write_case(root)
    target = paths[damaged_record]
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"{")
    before = _tree_bytes(root)

    snapshot = observe_workload_drain(
        ledger,
        workload_id=WORKLOAD_ID,
        business_date=BUSINESS_DATE,
        slot=SLOT,
        process_identity_provider=lambda _pid: None,
    )

    assert snapshot["status"] == "CANNOT_CONFIRM"
    assert snapshot["drained"] is False
    assert snapshot[damaged_record + ("_claim" if damaged_record != "receipt" else "")]["status"] in {
        "MISSING",
        "CORRUPT",
    }
    assert _tree_bytes(root) == before


def test_out_of_scope_claims_do_not_enter_snapshot_or_change_bytes(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    ledger, _paths = _write_case(root)
    _write_case(
        root,
        run_id="run-other-slot",
        business_date=BUSINESS_DATE,
        slot="1800",
        workload_id="other_workload",
        pid=61322,
    )
    before = _tree_bytes(root)

    snapshot = observe_workload_drain(
        ledger,
        workload_id=WORKLOAD_ID,
        business_date=BUSINESS_DATE,
        slot=SLOT,
        process_identity_provider=lambda _pid: None,
    )

    assert snapshot["scope"] == {
        "mode": "LIVE",
        "business_date": BUSINESS_DATE,
        "slot": SLOT,
        "workload_id": WORKLOAD_ID,
    }
    assert snapshot["dispatch_claim"]["record"]["run_id"] == RUN_ID
    assert snapshot["workload_claim"]["record"]["workload_id"] == WORKLOAD_ID
    assert snapshot["receipt"]["record"]["run_id"] == RUN_ID
    assert snapshot["status"] == "CANNOT_CONFIRM"
    assert _tree_bytes(root) == before
