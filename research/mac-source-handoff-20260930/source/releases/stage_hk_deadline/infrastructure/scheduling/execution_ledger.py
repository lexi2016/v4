"""Atomic, V3.5-owned dispatch claims and aggregate receipts."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from contracts.runtime_tasks import DispatchRequest, WorkloadDefinition
from infrastructure.interprocess_lock import _pid_is_alive as _owned_pid_is_alive
from infrastructure.owned_path import resolve_owned_path


SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
CLAIM_IDENTITY_FIELDS = (
    "workload_id",
    "scheduled_date",
    "business_date",
    "target_date",
    "slot",
    "mode",
)
CLAIM_READ_ATTEMPTS = 50
CLAIM_READ_DELAY_SECONDS = 0.01


@dataclass(frozen=True)
class ClaimResult:
    acquired: bool
    run_id: str
    relative_path: str


def _segment(value: str) -> str:
    if not SAFE_SEGMENT.fullmatch(value):
        raise ValueError("unsafe execution identity segment")
    return value


def _ledger_digest(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "ledger_sha256"}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _receipt_finished_at(payload: Mapping[str, Any]) -> datetime:
    value = payload.get("finished_at")
    if not isinstance(value, str) or not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return datetime.min.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_existing_claim(destination: Path) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(CLAIM_READ_ATTEMPTS):
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                return existing
            last_error = ValueError("execution claim payload is not an object")
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            last_error = error
        if attempt + 1 < CLAIM_READ_ATTEMPTS:
            time.sleep(CLAIM_READ_DELAY_SECONDS)
    raise ValueError("execution claim is unreadable") from last_error


def _pid_is_alive(pid: Any) -> bool:
    if isinstance(pid, bool):
        return False
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    return _owned_pid_is_alive(value)


class ExecutionLedger:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, relative: str) -> Path:
        try:
            return resolve_owned_path(self.root, relative)
        except ValueError as error:
            raise ValueError("execution ledger path escaped root") from error

    def dry_run_namespace(self) -> "ExecutionLedger":
        if self.root.name.casefold() == "dry-run":
            return self
        return ExecutionLedger(self.root / "dry-run")

    def _has_completed_receipt(self, claim: Mapping[str, Any]) -> bool:
        run_id = str(claim.get("run_id") or "")
        mode = str(claim.get("mode") or "").lower()
        business_date = str(claim.get("business_date") or "")
        slot = str(claim.get("slot") or "")
        if not all((run_id, mode, business_date, slot)):
            return False
        receipt_path = self._path(
            f"receipts/{mode}/{business_date}/{slot}/"
            f"{run_id}.dispatch-receipt.json"
        )
        if not receipt_path.is_file():
            return False
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return True
        if not isinstance(receipt, Mapping):
            return True
        if str(receipt.get("ledger_sha256") or "") != _ledger_digest(receipt):
            return True
        if any(
            str(receipt.get(field) or "") != str(claim.get(field) or "")
            for field in ("run_id", "scheduled_date", "business_date", "target_date", "slot", "mode")
        ):
            return True
        if any(
            receipt.get(field) is not False
            for field in ("production_allowed", "buy_gate_updated", "orders_sent")
        ):
            return True
        status = str(receipt.get("status") or "")
        workload_id = str(claim.get("workload_id") or "")
        if workload_id:
            results = receipt.get("workload_results")
            selected = receipt.get("selected_workload_ids")
            started = receipt.get("started_workload_ids")
            if (
                not isinstance(results, list)
                or not isinstance(selected, list)
                or not isinstance(started, list)
                or workload_id not in selected
                or workload_id not in started
            ):
                return False
            matching = [
                item
                for item in results
                if isinstance(item, Mapping)
                and str(item.get("workload_id") or "") == workload_id
            ]
            if len(matching) != 1:
                return False
            return str(matching[0].get("status") or "") in {"SUCCEEDED", "ALREADY_EXISTS"}
        return status != "FAILED"

    def _replace_dead_claim(
        self,
        destination: Path,
        *,
        observed: Mapping[str, Any],
        encoded: bytes,
    ) -> bool:
        recovery_lock = destination.with_name(f".{destination.name}.reclaim.lock")
        try:
            lock_handle = os.open(
                recovery_lock,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            return False
        try:
            os.close(lock_handle)
            current = _read_existing_claim(destination)
            if current != dict(observed):
                return False
            if self._has_completed_receipt(current) or _pid_is_alive(current.get("pid")):
                return False
            handle, temporary = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
            )
            try:
                with os.fdopen(handle, "wb") as output:
                    output.write(encoded)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return True
        finally:
            try:
                recovery_lock.unlink()
            except FileNotFoundError:
                pass

    def _claim(self, relative: str, payload: Mapping[str, Any]) -> ClaimResult:
        destination = self._path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        run_id = str(payload["run_id"])
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        try:
            handle = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = _read_existing_claim(destination)
            run_id = str(existing.get("run_id") or "")
            if any(
                existing.get(field) != payload.get(field)
                for field in CLAIM_IDENTITY_FIELDS
                if field in payload or field in existing
            ):
                raise ValueError("execution claim identity conflict")
            if self._replace_dead_claim(
                destination,
                observed=existing,
                encoded=encoded,
            ):
                return ClaimResult(True, str(payload["run_id"]), relative)
            return ClaimResult(False, run_id, relative)
        try:
            os.write(handle, encoded)
            os.fsync(handle)
        finally:
            os.close(handle)
        return ClaimResult(True, run_id, relative)

    def try_claim_dispatch(self, request: DispatchRequest) -> ClaimResult:
        run_id = uuid4().hex
        relative = (
            f"claims/{request.mode.value.lower()}/{request.business_date}/"
            f"{request.slot}/dispatch.claim.json"
        )
        return self._claim(
            relative,
            {
                "schema_version": "v3_5.dispatch_claim.v1",
                "run_id": run_id,
                "pid": os.getpid(),
                "created_at": _now(),
                "scheduled_date": request.scheduled_date,
                "business_date": request.business_date,
                "target_date": request.target_date,
                "slot": request.slot,
                "mode": request.mode.value,
            },
        )

    def try_claim_workload(
        self,
        request: DispatchRequest,
        workload: WorkloadDefinition,
        *,
        run_id: str,
    ) -> ClaimResult:
        workload_id = _segment(workload.workload_id)
        relative = (
            f"workloads/{request.mode.value.lower()}/{request.business_date}/"
            f"{request.slot}/{workload_id}.workload-claim.json"
        )
        return self._claim(
            relative,
            {
                "schema_version": "v3_5.workload_claim.v1",
                "run_id": run_id,
                "workload_id": workload.workload_id,
                "scheduled_date": request.scheduled_date,
                "business_date": request.business_date,
                "target_date": request.target_date,
                "slot": request.slot,
                "mode": request.mode.value,
                "pid": os.getpid(),
                "created_at": _now(),
            },
        )

    def _claim_identity_mismatch(
        self,
        relative: str,
        *,
        expected_run_id: str,
        identity: Mapping[str, str],
    ) -> str | None:
        """Return the mismatch reason for one claim, or None when it is safe.

        An already-absent claim matches (removing it again is a no-op so a
        retry after a partial failure stays safe).  An unreadable or
        identity-mismatched claim returns a reason so the caller can abort the
        whole release before any unlink happens.
        """
        destination = self._path(relative)
        if not destination.exists():
            return None
        try:
            existing = _read_existing_claim(destination)
        except ValueError:
            return "execution claim is unreadable"
        if str(existing.get("run_id") or "") != expected_run_id:
            return "execution claim release identity mismatch"
        if any(
            str(existing.get(field) or "") != str(identity.get(field) or "")
            for field in CLAIM_IDENTITY_FIELDS
        ):
            return "execution claim release identity mismatch"
        return None

    def _unlink_claim(self, relative: str) -> None:
        destination = self._path(relative)
        try:
            destination.unlink()
        except FileNotFoundError:
            pass

    def release_failed_request(
        self,
        request: DispatchRequest,
        *,
        run_id: str,
        workload_ids: tuple[str, ...],
    ) -> None:
        """Release this request's dispatch and workload claims after a failure.

        Only called by the dispatcher after it has written a FAILED aggregate
        receipt.  A successfully completed workload keeps its claim so the run
        stays idempotent; only the failed workloads and the dispatch claim are
        released so the same request can be retried.

        Every claim is validated first and only then removed, so a single
        identity mismatch aborts the whole release without deleting any file.
        """
        _segment(run_id)
        identity = {
            "scheduled_date": request.scheduled_date,
            "business_date": request.business_date,
            "target_date": request.target_date,
            "slot": request.slot,
            "mode": request.mode.value,
        }
        dispatch_relative = (
            f"claims/{request.mode.value.lower()}/{request.business_date}/"
            f"{request.slot}/dispatch.claim.json"
        )
        workload_relatives: list[str] = []
        for workload_id in workload_ids:
            workload_relatives.append(
                f"workloads/{request.mode.value.lower()}/{request.business_date}/"
                f"{request.slot}/{_segment(workload_id)}.workload-claim.json"
            )
        for relative, workload_id in zip(
            workload_relatives, workload_ids, strict=True
        ):
            reason = self._claim_identity_mismatch(
                relative,
                expected_run_id=run_id,
                identity={**identity, "workload_id": workload_id},
            )
            if reason is not None:
                raise ValueError(reason)
        reason = self._claim_identity_mismatch(
            dispatch_relative,
            expected_run_id=run_id,
            identity=identity,
        )
        if reason is not None:
            raise ValueError(reason)
        for relative in workload_relatives:
            self._unlink_claim(relative)
        self._unlink_claim(dispatch_relative)

    def receipt_relative(self, request: DispatchRequest, *, run_id: str) -> str:
        _segment(run_id)
        return (
            f"receipts/{request.mode.value.lower()}/{request.business_date}/"
            f"{request.slot}/{run_id}.dispatch-receipt.json"
        )

    def write_receipt(self, relative: str, payload: Mapping[str, Any]) -> None:
        destination = self._path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        body = dict(payload)
        # Link every receipt to the previous one in the same (mode, date, slot)
        # chain so the ledger becomes an unbroken, tamper-evident fact chain.
        prev_sha = self._previous_receipt_sha(relative)
        body["prev_ledger_sha256"] = prev_sha
        body["ledger_sha256"] = _ledger_digest(body)
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        handle, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _previous_receipt_sha(self, relative: str) -> str:
        """Return the hash of the most recently written sibling receipt.

        Receipt run ids are random, so filename order is meaningless.  The
        predecessor is the sibling written most recently (by file mtime, with
        the filename as a deterministic same-nanosecond tie-break).  If that
        newest sibling is unreadable or fails its self-hash, we fail closed
        instead of chaining to an older receipt, which would silently fork the
        chain.  Empty is returned only when no sibling exists (a fresh chain
        head).
        """
        destination = self._path(relative)
        root = destination.parent
        if not root.is_dir():
            return ""
        siblings = sorted(
            (
                path
                for path in root.glob("*.dispatch-receipt.json")
                if path.is_file() and path.resolve() != destination.resolve()
            ),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        if not siblings:
            return ""
        newest = siblings[-1]
        try:
            payload = json.loads(newest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("previous receipt is invalid") from error
        if not isinstance(payload, dict):
            raise ValueError("previous receipt is invalid")
        if str(payload.get("ledger_sha256") or "") != _ledger_digest(payload):
            raise ValueError("previous receipt is invalid")
        return str(payload["ledger_sha256"])

    def list_receipts(
        self,
        business_date: str,
        *,
        mode: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        receipts: list[dict[str, Any]] = []
        root = self._path("receipts")
        if not root.is_dir():
            return ()
        for path in root.glob(f"*/{business_date}/*/*.dispatch-receipt.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(payload, dict)
                and payload.get("business_date") == business_date
                and (
                    mode is None
                    or str(payload.get("mode") or "").upper() == mode.upper()
                )
            ):
                receipts.append(payload)
        receipts.sort(
            key=lambda row: (
                _receipt_finished_at(row),
                str(row.get("slot") or ""),
                str(row.get("run_id") or ""),
            )
        )
        return tuple(receipts)

    def verify_receipt_chain(
        self,
        business_date: str,
        *,
        mode: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Prove each (mode, slot) receipt chain is a single linear chain.

        Receipt run ids are random, so filename order is meaningless.  Each
        receipt records the ``prev_ledger_sha256`` of the receipt written before
        it; verification walks those links instead of assuming an order.  For
        every (mode, slot) chain it proves: every self-hash is correct and
        unique, every prev resolves inside the same chain, there is exactly one
        head (no prev), no receipt is referenced by more than one successor (no
        fork), and exactly one tail whose prev-walk is acyclic and covers every
        receipt.
        """
        receipts = self.list_receipts(business_date)
        if mode is not None:
            receipts = tuple(
                row
                for row in receipts
                if str(row.get("mode") or "").upper() == str(mode).upper()
            )
        problems: list[str] = []
        by_sha: dict[str, dict[str, Any]] = {}
        for receipt in receipts:
            run_id = str(receipt.get("run_id") or "?")
            sha = str(receipt.get("ledger_sha256") or "")
            if sha != _ledger_digest(receipt):
                problems.append(f"{run_id}: self hash mismatch")
                continue
            if sha in by_sha:
                problems.append(f"{sha[:12]}: duplicate ledger sha256")
                continue
            by_sha[sha] = receipt
        chains: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for receipt in receipts:
            chain_key = (
                str(receipt.get("mode") or "").lower(),
                str(receipt.get("slot") or ""),
            )
            chains.setdefault(chain_key, []).append(receipt)
        for chain_key, chain in chains.items():
            label = f"{chain_key[0]}/{chain_key[1]}"
            chain_by_sha: dict[str, dict[str, Any]] = {}
            for receipt in chain:
                sha = str(receipt.get("ledger_sha256") or "")
                if sha:
                    chain_by_sha[sha] = receipt
            for receipt in chain:
                run_id = str(receipt.get("run_id") or "?")
                prev = str(receipt.get("prev_ledger_sha256") or "")
                if prev and prev not in chain_by_sha:
                    problems.append(
                        f"{run_id}: prev hash does not resolve to same chain"
                    )
            heads = [
                receipt
                for receipt in chain
                if not str(receipt.get("prev_ledger_sha256") or "")
            ]
            if len(heads) != 1:
                problems.append(
                    f"{label}: expected one chain head, found {len(heads)}"
                )
            successors: dict[str, list[str]] = {}
            for receipt in chain:
                prev = str(receipt.get("prev_ledger_sha256") or "")
                if prev:
                    successors.setdefault(prev, []).append(
                        str(receipt.get("run_id") or "?")
                    )
            for sha, run_ids in successors.items():
                if len(run_ids) > 1:
                    problems.append(
                        f"{sha[:12]}: forked chain "
                        f"(successors: {', '.join(sorted(run_ids))})"
                    )
            tails = [
                receipt
                for receipt in chain
                if str(receipt.get("ledger_sha256") or "") not in successors
            ]
            if len(tails) != 1:
                problems.append(
                    f"{label}: expected one chain tail, found {len(tails)}"
                )
            else:
                seen: set[str] = set()
                current = tails[0]
                cyclic = False
                while True:
                    sha = str(current.get("ledger_sha256") or "")
                    run_id = str(current.get("run_id") or "?")
                    if sha in seen:
                        problems.append(
                            f"{label}: cycle detected at {run_id}"
                        )
                        cyclic = True
                        break
                    seen.add(sha)
                    prev = str(current.get("prev_ledger_sha256") or "")
                    if not prev:
                        break
                    if prev not in chain_by_sha:
                        # Already reported as an unresolvable prev.
                        break
                    current = chain_by_sha[prev]
                if not cyclic and len(seen) != len(chain):
                    problems.append(
                        f"{label}: chain does not cover all receipts"
                    )
        return (not problems, problems)
