"""Read-only, scoped observer for V3.5 execution-ledger drain evidence.

The current ledger records PIDs but has no trusted admission-barrier, lease,
or parent/child birth-identity contract.  This module can block on a live PID
and report bounded evidence, but intentionally cannot promote legacy claims
to DRAINED.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from infrastructure.scheduling.execution_ledger import ExecutionLedger


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_RECORD_BYTES = 4 * 1024 * 1024
_IDENTITY_FIELDS = (
    "run_id",
    "scheduled_date",
    "business_date",
    "target_date",
    "slot",
    "mode",
)


@dataclass(frozen=True)
class ProcessIdentity:
    """Read-only process identity returned by a provider for a live PID."""

    pid: int
    start_identity: str
    parent_pid: int | None


ProcessIdentityProvider = Callable[[int], ProcessIdentity | None]


def system_process_identity(pid: int) -> ProcessIdentity | None:
    """Read PID, parent PID, and process start text through ``ps`` only.

    No signal is sent.  An absent process and a failed lookup both remain
    unknown to the observer; neither is evidence that a workload is drained.
    """

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart=", "-o", "ppid="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.strip().splitlines()
    if result.returncode != 0 or len(lines) != 1:
        return None
    parts = lines[0].strip().rsplit(maxsplit=1)
    if len(parts) != 2 or not parts[0].strip():
        return None
    try:
        parent_pid = int(parts[1])
    except ValueError:
        return None
    return ProcessIdentity(pid=pid, start_identity=parts[0].strip(), parent_pid=parent_pid)


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "ledger_sha256"}
    raw = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _read_record(path: Path) -> tuple[dict[str, Any] | None, str, str | None]:
    """Read one regular JSON file without following a final symlink."""

    try:
        before = path.lstat()
    except FileNotFoundError:
        return None, "MISSING", None
    except OSError:
        return None, "UNREADABLE", None
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        return None, "INVALID_FILE_TYPE", None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None, "MISSING", None
    except OSError:
        return None, "UNREADABLE", None
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            return None, "IDENTITY_CHANGED", None
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(fd, 65536)
            if not block:
                break
            total += len(block)
            if total > _MAX_RECORD_BYTES:
                return None, "TOO_LARGE", None
            chunks.append(block)
        raw = b"".join(chunks)
    except OSError:
        return None, "UNREADABLE", None
    finally:
        os.close(fd)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, "CORRUPT", digest
    if not isinstance(value, dict):
        return None, "CORRUPT", digest
    return value, "VALID", digest


def _path_for(ledger: ExecutionLedger, relative: str) -> Path:
    # The ledger exposes no exact claim reader; reuse its owned-path resolver
    # and read only the one relative path selected by the explicit scope.
    return ledger._path(relative)


def _scope_valid(
    row: Mapping[str, Any], *, mode: str, business_date: str, slot: str
) -> bool:
    return (
        str(row.get("business_date") or "") == business_date
        and str(row.get("slot") or "") == slot
        and str(row.get("mode") or "").upper() == mode
    )


def _identity_fields_match(*rows: Mapping[str, Any]) -> bool:
    if not rows:
        return False
    for field in _IDENTITY_FIELDS:
        values = [str(row.get(field) or "") for row in rows]
        if not values[0] or any(value != values[0] for value in values[1:]):
            return False
    return True


def _valid_pid(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    pid = value
    return pid if pid > 0 else None


def observe_workload_drain(
    ledger: ExecutionLedger,
    *,
    workload_id: str,
    business_date: str,
    slot: str,
    mode: str = "LIVE",
    process_identity_provider: ProcessIdentityProvider = system_process_identity,
) -> dict[str, Any]:
    """Return a conservative read-only snapshot for one workload/date/slot.

    A live matching PID blocks.  Missing or mismatched process birth identity,
    incomplete parent/child lineage, an invalid receipt, or absent trusted
    admission-barrier/lease evidence leaves the result CANNOT_CONFIRM.  The
    current ledger has no accepted schema for the latter evidence, so this
    observer never returns DRAINED.
    """

    if not isinstance(ledger, ExecutionLedger):
        raise TypeError("ledger must be an ExecutionLedger")
    if not isinstance(mode, str) or mode.upper() not in {"LIVE", "DRY_RUN"}:
        raise ValueError("mode must be LIVE or DRY_RUN")
    mode = mode.upper()
    if (
        not isinstance(business_date, str)
        or len(business_date) != 8
        or not business_date.isdigit()
    ):
        raise ValueError("business_date must be YYYYMMDD")
    try:
        datetime.strptime(business_date, "%Y%m%d")
    except ValueError as error:
        raise ValueError("business_date must be a valid YYYYMMDD") from error
    for value, label in ((slot, "slot"), (workload_id, "workload_id")):
        if not isinstance(value, str) or _SAFE_SEGMENT.fullmatch(value) is None:
            raise ValueError(f"invalid {label}")
    if not callable(process_identity_provider):
        raise TypeError("process_identity_provider must be callable")

    mode_dir = mode.lower()
    dispatch_relative = (
        f"claims/{mode_dir}/{business_date}/{slot}/dispatch.claim.json"
    )
    workload_relative = (
        f"workloads/{mode_dir}/{business_date}/{slot}/"
        f"{workload_id}.workload-claim.json"
    )
    blockers: list[str] = []
    dispatch_path = _path_for(ledger, dispatch_relative)
    workload_path = _path_for(ledger, workload_relative)
    dispatch, dispatch_status, dispatch_sha = _read_record(dispatch_path)
    workload, workload_status, workload_sha = _read_record(workload_path)
    if dispatch is None:
        blockers.append("DISPATCH_CLAIM_" + dispatch_status)
    if workload is None:
        blockers.append("WORKLOAD_CLAIM_" + workload_status)

    dispatch_view = {
        "path": dispatch_relative,
        "status": dispatch_status,
        "raw_sha256": dispatch_sha,
        "record": dispatch,
    }
    workload_view = {
        "path": workload_relative,
        "status": workload_status,
        "raw_sha256": workload_sha,
        "record": workload,
    }
    receipt_view: dict[str, Any] = {
        "path": None,
        "status": "NOT_READ",
        "raw_sha256": None,
        "record": None,
    }

    receipt: dict[str, Any] | None = None
    receipt_status = "NOT_READ"
    receipt_sha: str | None = None
    run_id: str | None = None
    if dispatch is not None:
        raw_run_id = dispatch.get("run_id")
        if isinstance(raw_run_id, str) and _SAFE_SEGMENT.fullmatch(raw_run_id):
            run_id = raw_run_id
            receipt_relative = (
                f"receipts/{mode_dir}/{business_date}/{slot}/"
                f"{run_id}.dispatch-receipt.json"
            )
            receipt_path = _path_for(ledger, receipt_relative)
            receipt, receipt_status, receipt_sha = _read_record(receipt_path)
            receipt_view = {
                "path": receipt_relative,
                "status": receipt_status,
                "raw_sha256": receipt_sha,
                "record": receipt,
            }
            if receipt is None:
                blockers.append("RECEIPT_" + receipt_status)
        else:
            receipt_status = "NOT_READ_INVALID_RUN_ID"
            receipt_view["status"] = receipt_status
            blockers.append("DISPATCH_RUN_ID_INVALID")
    else:
        blockers.append("RECEIPT_CANNOT_BE_BOUND_WITHOUT_DISPATCH_CLAIM")

    claims_valid = dispatch is not None and workload is not None
    if claims_valid:
        assert dispatch is not None and workload is not None
        if dispatch.get("schema_version") != "v3_5.dispatch_claim.v1":
            blockers.append("DISPATCH_CLAIM_SCHEMA_INVALID")
            claims_valid = False
        if workload.get("schema_version") != "v3_5.workload_claim.v1":
            blockers.append("WORKLOAD_CLAIM_SCHEMA_INVALID")
            claims_valid = False
        if not _scope_valid(dispatch, mode=mode, business_date=business_date, slot=slot):
            blockers.append("DISPATCH_CLAIM_OUT_OF_SCOPE")
            claims_valid = False
        if not _scope_valid(workload, mode=mode, business_date=business_date, slot=slot):
            blockers.append("WORKLOAD_CLAIM_OUT_OF_SCOPE")
            claims_valid = False
        if str(workload.get("workload_id") or "") != workload_id:
            blockers.append("WORKLOAD_CLAIM_IDENTITY_MISMATCH")
            claims_valid = False
        if not _identity_fields_match(dispatch, workload):
            blockers.append("CLAIM_IDENTITY_MISMATCH_OR_INCOMPLETE")
            claims_valid = False
        if str(dispatch.get("run_id") or "") != str(workload.get("run_id") or ""):
            blockers.append("CLAIM_RUN_ID_MISMATCH")
            claims_valid = False

    receipt_valid = receipt is not None
    if receipt is not None:
        if receipt.get("ledger_sha256") != _canonical_digest(receipt):
            blockers.append("RECEIPT_HASH_INVALID")
            receipt_valid = False
        if not _scope_valid(receipt, mode=mode, business_date=business_date, slot=slot):
            blockers.append("RECEIPT_OUT_OF_SCOPE")
            receipt_valid = False
        if dispatch is not None and workload is not None:
            if not _identity_fields_match(dispatch, workload, receipt):
                blockers.append("RECEIPT_IDENTITY_MISMATCH_OR_INCOMPLETE")
                receipt_valid = False
            if receipt.get("run_id") != dispatch.get("run_id"):
                blockers.append("RECEIPT_RUN_ID_MISMATCH")
                receipt_valid = False
        if receipt.get("run_id") != run_id:
            blockers.append("RECEIPT_PATH_RUN_ID_MISMATCH")
            receipt_valid = False
        if any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
            blockers.append("RECEIPT_SAFETY_FLAGS_INVALID")
            receipt_valid = False
        results = receipt.get("workload_results")
        selected = receipt.get("selected_workload_ids")
        started = receipt.get("started_workload_ids")
        matching_results = [
            item for item in results
            if isinstance(item, Mapping) and item.get("workload_id") == workload_id
        ] if isinstance(results, list) else []
        if (
            not isinstance(results, list)
            or not isinstance(selected, list)
            or not isinstance(started, list)
            or selected.count(workload_id) != 1
            or started.count(workload_id) != 1
            or len(matching_results) != 1
        ):
            blockers.append("RECEIPT_WORKLOAD_RESULT_MISSING_OR_AMBIGUOUS")
            receipt_valid = False

    process_views: list[dict[str, Any]] = []
    live_pid_seen = False
    process_identity_unknown = False
    if claims_valid:
        assert dispatch is not None and workload is not None
        seen_pids: dict[int, ProcessIdentity | None] = {}
        for role, claim in (("dispatch_parent", dispatch), ("workload_owner", workload)):
            pid = _valid_pid(claim.get("pid"))
            if pid is None:
                process_views.append({"role": role, "status": "CANNOT_CONFIRM", "reason": "PID_MISSING_OR_INVALID"})
                process_identity_unknown = True
                blockers.append(role.upper() + "_PID_INVALID")
                continue
            if pid not in seen_pids:
                try:
                    seen_pids[pid] = process_identity_provider(pid)
                except Exception:
                    seen_pids[pid] = None
            observed = seen_pids[pid]
            recorded_start = claim.get("process_start_identity")
            if not isinstance(recorded_start, str) or not recorded_start:
                blockers.append(role.upper() + "_START_IDENTITY_NOT_RECORDED")
                process_identity_unknown = True
            if observed is None:
                process_views.append({"role": role, "pid": pid, "status": "UNKNOWN", "reason": "PROCESS_NOT_OBSERVED_OR_LOOKUP_FAILED"})
                process_identity_unknown = True
                blockers.append(role.upper() + "_PROCESS_IDENTITY_UNKNOWN")
            elif (
                not isinstance(observed, ProcessIdentity)
                or observed.pid != pid
                or not isinstance(observed.start_identity, str)
                or not observed.start_identity
            ):
                process_views.append({"role": role, "pid": pid, "status": "UNKNOWN", "reason": "PROCESS_IDENTITY_PROVIDER_INVALID"})
                process_identity_unknown = True
                blockers.append(role.upper() + "_PROCESS_IDENTITY_INVALID")
            elif (
                isinstance(recorded_start, str)
                and recorded_start
                and recorded_start != observed.start_identity
            ):
                process_views.append({
                    "role": role,
                    "pid": pid,
                    "status": "UNKNOWN",
                    "recorded_start_identity": recorded_start,
                    "observed_start_identity": observed.start_identity,
                    "reason": "PID_REUSE_OR_START_IDENTITY_MISMATCH",
                })
                process_identity_unknown = True
                blockers.append(role.upper() + "_START_IDENTITY_MISMATCH")
            else:
                process_views.append({
                    "role": role,
                    "pid": pid,
                    "status": "LIVE_BLOCKER",
                    "recorded_start_identity": recorded_start,
                    "observed_start_identity": observed.start_identity,
                    "parent_pid": observed.parent_pid,
                    "reason": "LIVE_PID_BLOCKS_DRAIN",
                })
                live_pid_seen = True

    # Existing claims contain no child start identities, admission barrier,
    # or lease identity.  Missing these is a hard CANNOT_CONFIRM boundary.
    child_identity_field_present = bool(
        isinstance(workload, Mapping)
        and isinstance(workload.get("child_process_identities"), list)
        and workload.get("child_process_identities")
    )
    if not child_identity_field_present:
        blockers.append("CHILD_PROCESS_IDENTITIES_NOT_RECORDED")
    else:
        blockers.append("CHILD_PROCESS_IDENTITIES_NOT_VALIDATED_BY_LEDGER_CONTRACT")
    blockers.extend(("ADMISSION_BARRIER_IDENTITY_NOT_REPRESENTED", "LEASE_IDENTITY_NOT_REPRESENTED"))

    if live_pid_seen and not process_identity_unknown:
        status = "BLOCKED"
    else:
        status = "CANNOT_CONFIRM"
    if not claims_valid or not receipt_valid or process_identity_unknown:
        status = "CANNOT_CONFIRM" if not live_pid_seen else "BLOCKED"

    return {
        "schema_version": "v4.migration.drain_observer.v1",
        "status": status,
        "drained": False,
        "scope": {
            "mode": mode,
            "business_date": business_date,
            "slot": slot,
            "workload_id": workload_id,
        },
        "dispatch_claim": dispatch_view,
        "workload_claim": workload_view,
        "receipt": receipt_view,
        "processes": process_views,
        "lineage": {
            "child_process_identity_field_present": child_identity_field_present,
            "status": "CANNOT_CONFIRM",
        },
        "admission_barrier": {"status": "CANNOT_CONFIRM", "identity_recorded": False},
        "lease": {"status": "CANNOT_CONFIRM", "identity_recorded": False},
        "blockers": sorted(set(blockers)),
        "snapshot_consistency": "BOUNDED_READS_NOT_AN_ATOMIC_LEASE",
        "read_only": True,
        "ledger_written": False,
        "claims_unlinked": False,
        "processes_signalled": False,
        "launchctl_called": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
