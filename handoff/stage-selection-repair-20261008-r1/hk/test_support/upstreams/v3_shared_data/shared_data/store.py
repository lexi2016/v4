"""Safe-root raw store: immutable run dirs + artifact/manifest/receipt/latest.

Every file lands in an immutable run directory ``runs/{trade_date}/{role}/{run_id}/``
via temp-file + flush + fsync + os.replace under a single-owner lock. The
``latest.json`` pointer is only updated after the full trio re-verifies
(artifact sha, manifest sha, row_count, status semantics, safety flags).
"""
from __future__ import annotations

import csv
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .allowlist import AllowlistRegistry
from .collectors import get_collector
from .constants import (
    CANNOT_CONFIRM,
    EXPLICIT_STATUSES,
    FAILED,
    LATEST_SCHEMA_VERSION,
    OWNER_REGISTRY,
    OWNERS_SCHEMA_VERSION,
    READY,
    READY_EMPTY,
    RECEIPT_SCHEMA_VERSION,
    SAFETY_FLAG_KEYS,
    STORE_LOCK_NAME,
    STORE_LOCK_STALE_SECONDS,
    STORE_LOCK_TIMEOUT_SECONDS,
)
from .hashing import canonical_bytes, sha256_file, sha256_json
from .paths import resolve_under, validate_date, validate_role


class StoreError(Exception):
    """Fail-closed store error (validation, conflict, lock, corruption)."""


class LockTimeoutError(StoreError):
    pass


class ConflictError(StoreError):
    pass


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _count_rows(path: Path) -> int:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for row in reader if row and any(str(cell).strip() for cell in row))


class SafeRootStore:
    def __init__(self, root: Path, allowlist: AllowlistRegistry | None = None) -> None:
        self.root = Path(root)
        self.allowlist = allowlist if allowlist is not None else AllowlistRegistry()
        self.runs_root = self.root / "runs"
        self.latest_path = self.root / "latest.json"
        self.owners_path = self.root / "owners.json"
        self.lock_path = self.root / STORE_LOCK_NAME

    # -- low level ----------------------------------------------------------

    def _atomic_write_bytes(self, destination: Path, data: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _atomic_copy_file(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        try:
            with os.fdopen(handle, "wb") as output, open(source, "rb") as input_file:
                shutil.copyfileobj(input_file, output, length=1 << 20)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _read_json(self, path: Path) -> dict[str, Any]:
        import json

        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, Mapping):
            raise StoreError(f"json payload not an object: {path}")
        return dict(value)

    def _write_json(self, destination: Path, value: Mapping[str, Any]) -> None:
        self._atomic_write_bytes(destination, canonical_bytes(value))

    @contextmanager
    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + STORE_LOCK_TIMEOUT_SECONDS
        token = f"{os.getpid()}:{uuid4().hex}"
        while True:
            try:
                handle = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(handle, token.encode("ascii"))
                os.close(handle)
                break
            except FileExistsError:
                try:
                    if time.time() - self.lock_path.stat().st_mtime > STORE_LOCK_STALE_SECONDS:
                        self.lock_path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise LockTimeoutError(f"store lock timeout: {self.lock_path}")
                time.sleep(0.02)
        try:
            yield
        finally:
            try:
                if self.lock_path.read_text(encoding="ascii") == token:
                    self.lock_path.unlink()
            except FileNotFoundError:
                pass

    # -- ownership ----------------------------------------------------------

    def _check_owner(self, owner: str) -> None:
        entry = OWNER_REGISTRY.get(owner)
        if entry is None or not entry.get("can_write"):
            raise StoreError(f"owner {owner!r} is not allowed to write")
        if not self.owners_path.exists():
            with self._lock():
                if not self.owners_path.exists():
                    self._write_json(
                        self.owners_path,
                        {"schema_version": OWNERS_SCHEMA_VERSION, "owners": {k: dict(v) for k, v in OWNER_REGISTRY.items()}},
                    )

    # -- latest -------------------------------------------------------------

    def _load_latest(self) -> dict[str, Any]:
        if not self.latest_path.exists():
            return {"schema_version": LATEST_SCHEMA_VERSION, "entries": {}}
        value = self._read_json(self.latest_path)
        if value.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(value.get("entries"), Mapping):
            raise StoreError("latest.json corrupt")
        return value

    def _entry_key(self, trade_date: str, role: str) -> str:
        return f"{validate_date(trade_date)}/{validate_role(role)}"

    # -- verification -------------------------------------------------------

    def verify_run(self, trade_date: str, role: str, run_id: str, *, expected_owner: str | None = None) -> dict[str, Any]:
        """Re-verify a run trio. Raises StoreError on any mismatch."""
        validate_date(trade_date)
        validate_role(role)
        run_dir = resolve_under(self.runs_root, f"{trade_date}/{role}/{run_id}")
        if not run_dir.is_dir():
            raise StoreError(f"run dir missing: {run_dir}")
        artifact = run_dir / "artifact.csv"
        manifest_path = run_dir / "manifest.json"
        receipt_path = run_dir / "receipt.json"
        for path in (artifact, manifest_path, receipt_path):
            if not path.is_file():
                raise StoreError(f"run trio incomplete: {path}")
        manifest = self._read_json(manifest_path)
        receipt = self._read_json(receipt_path)
        if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
            raise StoreError("receipt schema mismatch")
        if expected_owner is not None and receipt.get("owner") != expected_owner:
            raise StoreError("run belongs to a different owner")
        if receipt.get("run_id") != run_id or run_dir.name != run_id:
            raise StoreError("run_id mismatch")
        if manifest.get("artifact_relative") != f"runs/{trade_date}/{role}/{run_id}/artifact.csv":
            raise StoreError("manifest relative path mismatch")
        if "source_path" in manifest or "source_meta" in manifest:
            raise StoreError("manifest must be path-neutral (no source_path/source_meta)")
        actual_artifact_sha = sha256_file(artifact)
        if actual_artifact_sha != manifest.get("artifact_sha256"):
            raise StoreError("artifact sha mismatch")
        if actual_artifact_sha != receipt.get("artifact_sha256"):
            raise StoreError("receipt artifact sha mismatch")
        if _count_rows(artifact) != manifest.get("row_count"):
            raise StoreError("row_count mismatch")
        if sha256_json(manifest) != receipt.get("manifest_sha256"):
            raise StoreError("manifest sha mismatch")
        status = receipt.get("status")
        if status not in EXPLICIT_STATUSES:
            raise StoreError(f"receipt status not explicit: {status!r}")
        if status == READY and (manifest.get("row_count", 0) <= 0 or manifest.get("temporal_cutoff_safe") is not True):
            raise StoreError("READY without rows / temporal proof")
        if status == READY_EMPTY and manifest.get("row_count", -1) != 0:
            raise StoreError("READY_EMPTY with rows")
        # CANNOT_CONFIRM-with-rows is legal: the explicit status is the
        # fail-closed marker; it never implies temporal proof.
        for key in SAFETY_FLAG_KEYS:
            if receipt.get(key) is not False:
                raise StoreError(f"safety flag {key!r} must be false")
        return {
            "run_id": run_id,
            "status": status,
            "artifact_sha256": actual_artifact_sha,
            "manifest_sha256": receipt.get("manifest_sha256"),
            "receipt_sha256": sha256_file(receipt_path),
            "input_sha256": manifest.get("input_sha256"),
            "row_count": manifest.get("row_count"),
            "manifest_relative": f"runs/{trade_date}/{role}/{run_id}/manifest.json",
            "receipt_relative": f"runs/{trade_date}/{role}/{run_id}/receipt.json",
            "artifact_relative": f"runs/{trade_date}/{role}/{run_id}/artifact.csv",
        }

    def verify_latest(self, trade_date: str, role: str) -> dict[str, Any]:
        latest = self._load_latest()
        entry = latest["entries"].get(self._entry_key(trade_date, role))
        if entry is None:
            raise StoreError(f"no latest run for {trade_date} / {role}")
        result = self.verify_run(trade_date, role, entry["run_id"], expected_owner=entry.get("owner"))
        return {"latest": entry, "verified": result}

    # -- replay -------------------------------------------------------------

    def replay_file(
        self,
        *,
        owner: str,
        trade_date: str,
        role: str,
        source_id: str,
        stage_id: str | None = None,
        dry_run: bool = False,
        historical_backfill: bool = False,
        expected_previous: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the allowlisted file_replay collector into an immutable run dir.

        Idempotent: the same idempotency key (owner/source/date/role/stage/input
        sha) returns the existing verified run. A different key for the same
        (date, role) slot is a conflict and fails closed.
        """
        try:
            validate_date(trade_date)
            validate_role(role)
        except ValueError as error:
            raise StoreError(str(error)) from error
        self._check_owner(owner)
        try:
            spec = self.allowlist.resolve(trade_date, role, source_id)
        except (ValueError, FileNotFoundError) as error:
            raise StoreError(str(error)) from error
        if stage_id is not None and stage_id not in spec.stages:
            raise StoreError(f"stage {stage_id!r} not allowlisted for {trade_date}/{role}")
        selected_stage = stage_id if stage_id is not None else (spec.stages[0] if spec.stages else "")
        if not selected_stage:
            raise StoreError("no stage_id available")

        captured_at = _now_iso()
        try:
            collect = get_collector(spec.collector)(spec, captured_at=captured_at)
        except ValueError as error:
            raise StoreError(str(error)) from error
        scan = collect.scan
        if spec.expected_input_sha256 is not None and scan.input_sha256 != spec.expected_input_sha256:
            raise StoreError(
                f"input sha mismatch: got {scan.input_sha256} expected frozen {spec.expected_input_sha256}"
            )
        # expected_row_count mismatch is demoted to CANNOT_CONFIRM inside scan_csv
        # and written as an explicit receipt, never as READY.
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "status": scan.status,
                "input_sha256": scan.input_sha256,
                "row_count": scan.row_count,
                "temporal_cutoff_safe": scan.temporal_cutoff_safe,
                "source_id": source_id,
                "trade_date": trade_date,
                "role": role,
            }

        if expected_previous is not None:
            if not isinstance(expected_previous, Mapping) or not expected_previous.get("run_id"):
                raise ConflictError("expected_previous must include a run_id")

        idem_key = sha256_json(
            {
                "owner": owner,
                "source_id": source_id,
                "trade_date": trade_date,
                "role": role,
                "stage_id": selected_stage,
                "input_sha256": scan.input_sha256,
            }
        )
        role_slug = role.lower().replace("_", "-")
        run_id = f"{trade_date}-{role_slug}-{idem_key[:12]}"

        with self._lock():
            latest = self._load_latest()
            key = self._entry_key(trade_date, role)
            existing = latest["entries"].get(key)
            previous_identity: dict[str, Any] | None = None
            supersession_relative: str | None = None
            if existing is not None:
                if existing.get("idempotency_key") == idem_key:
                    # Idempotent re-entry: re-verify, then return the same run.
                    verified = self.verify_run(trade_date, role, existing["run_id"], expected_owner=owner)
                    if expected_previous is not None:
                        current_identity = {
                            "run_id": verified["run_id"],
                            "artifact_sha256": verified["artifact_sha256"],
                            "manifest_sha256": verified["manifest_sha256"],
                            "receipt_sha256": verified["receipt_sha256"],
                            "artifact_relative": verified["artifact_relative"],
                            "manifest_relative": verified["manifest_relative"],
                            "receipt_relative": verified["receipt_relative"],
                        }
                        matches_current = not any(
                            current_identity.get(key) != value
                            for key, value in expected_previous.items()
                        )
                        superseded_from = existing.get("superseded_from")
                        matches_superseded = (
                            historical_backfill
                            and isinstance(superseded_from, Mapping)
                            and not any(
                                superseded_from.get(key) != value
                                for key, value in expected_previous.items()
                            )
                        )
                        if not (matches_current or matches_superseded):
                            raise ConflictError("expected_previous does not match current run identity")
                    return {"ok": True, "already_exists": True, **verified}
                if historical_backfill and existing.get("status") == READY:
                    previous_verified = self.verify_run(
                        trade_date, role, existing["run_id"], expected_owner=owner
                    )
                    previous_identity = {
                        "run_id": previous_verified["run_id"],
                        "artifact_sha256": previous_verified["artifact_sha256"],
                        "manifest_sha256": previous_verified["manifest_sha256"],
                        "receipt_sha256": previous_verified["receipt_sha256"],
                        "artifact_relative": previous_verified["artifact_relative"],
                        "manifest_relative": previous_verified["manifest_relative"],
                        "receipt_relative": previous_verified["receipt_relative"],
                    }
                    if expected_previous is not None and any(
                        previous_identity.get(key) != value
                        for key, value in expected_previous.items()
                    ):
                        raise ConflictError("expected_previous identity mismatch")
                elif historical_backfill and existing.get("status") == CANNOT_CONFIRM:
                    previous_verified = self.verify_run(
                        trade_date, role, existing["run_id"], expected_owner=owner
                    )
                    if previous_verified.get("row_count") != 0:
                        raise ConflictError(
                            "historical backfill CANNOT_CONFIRM supersession requires zero rows"
                        )
                    required_identity = {
                        "run_id",
                        "artifact_sha256",
                        "manifest_sha256",
                        "receipt_sha256",
                        "artifact_relative",
                        "manifest_relative",
                        "receipt_relative",
                    }
                    if (
                        expected_previous is None
                        or not required_identity.issubset(expected_previous.keys())
                    ):
                        raise ConflictError(
                            "CANNOT_CONFIRM supersession requires complete expected_previous identity"
                        )
                    previous_identity = {
                        "run_id": previous_verified["run_id"],
                        "artifact_sha256": previous_verified["artifact_sha256"],
                        "manifest_sha256": previous_verified["manifest_sha256"],
                        "receipt_sha256": previous_verified["receipt_sha256"],
                        "artifact_relative": previous_verified["artifact_relative"],
                        "manifest_relative": previous_verified["manifest_relative"],
                        "receipt_relative": previous_verified["receipt_relative"],
                    }
                    if any(
                        previous_identity.get(key) != value
                        for key, value in expected_previous.items()
                    ):
                        raise ConflictError("expected_previous identity mismatch")
                elif historical_backfill:
                    raise ConflictError(
                        f"historical backfill requires an existing READY run for {key}"
                    )
                if previous_identity is None:
                    raise ConflictError(
                        f"(date, role) slot {key} already has a different run "
                        f"{existing.get('run_id')}; fail closed"
                    )

            run_dir = resolve_under(self.runs_root, f"{trade_date}/{role}/{run_id}")
            attempt = 1
            if run_dir.exists():
                # Crash recovery: incomplete run dir from the same key.
                partial_receipt = run_dir / "receipt.json"
                if partial_receipt.exists():
                    previous = self._read_json(partial_receipt)
                    if previous.get("idempotency_key") != idem_key or previous.get("owner") != owner:
                        raise ConflictError(f"run dir exists for a different key: {run_dir}")
                    attempt = int(previous.get("attempt", 1)) + 1
                run_dir.mkdir(parents=True, exist_ok=True)
            else:
                run_dir.mkdir(parents=True, exist_ok=True)
                if resolve_under(self.runs_root, f"{trade_date}/{role}/{run_id}") != run_dir:
                    raise StoreError("run dir escape after creation")

            relative_prefix = f"runs/{trade_date}/{role}/{run_id}"
            artifact_relative = f"{relative_prefix}/artifact.csv"
            manifest_relative = f"{relative_prefix}/manifest.json"
            receipt_relative = f"{relative_prefix}/receipt.json"
            if previous_identity is not None:
                supersession_relative = f"{relative_prefix}/supersession.json"

            started_at = _now_iso()
            try:
                # 1. artifact (byte-identical copy)
                self._atomic_copy_file(spec.source_path, run_dir / "artifact.csv")
                artifact_sha256 = sha256_file(run_dir / "artifact.csv")
                if artifact_sha256 != scan.input_sha256:
                    raise StoreError("artifact copy is not byte-identical to input")

                # 2. manifest
                manifest = dict(collect.manifest_payload)
                manifest.update(
                    {
                        "stage_id": selected_stage,
                        "artifact_sha256": artifact_sha256,
                        "artifact_relative": artifact_relative,
                        "input_sha256": scan.input_sha256,
                    }
                )
                self._write_json(run_dir / "manifest.json", manifest)

                # 3. receipt
                receipt = {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "owner": owner,
                    "run_id": run_id,
                    "idempotency_key": idem_key,
                    "attempt": attempt,
                    "started_at": started_at,
                    "finished_at": _now_iso(),
                    "status": scan.status,
                    "error": scan.reason or "",
                    "manifest_sha256": sha256_json(manifest),
                    "artifact_sha256": artifact_sha256,
                    "trade_date": trade_date,
                    "role": role,
                    "source_id": source_id,
                    "stage_id": selected_stage,
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
                if previous_identity is not None:
                    receipt.update(
                        {
                            "historical_backfill": True,
                            "supersedes": previous_identity,
                            "supersession_relative": supersession_relative,
                        }
                    )
                self._write_json(run_dir / "receipt.json", receipt)

                # 4. re-verify the trio before touching latest
                verified_result = self.verify_run(trade_date, role, run_id, expected_owner=owner)

                if previous_identity is not None and supersession_relative is not None:
                    self._write_json(
                        run_dir / "supersession.json",
                        {
                            "schema_version": "v3_shared_data.supersession.v1",
                            "owner": owner,
                            "reason": "historical_backfill",
                            "trade_date": trade_date,
                            "role": role,
                            "previous": previous_identity,
                            "replacement": {
                                "run_id": verified_result["run_id"],
                                "artifact_sha256": verified_result["artifact_sha256"],
                                "manifest_sha256": verified_result["manifest_sha256"],
                                "receipt_sha256": verified_result["receipt_sha256"],
                                "artifact_relative": verified_result["artifact_relative"],
                                "manifest_relative": verified_result["manifest_relative"],
                                "receipt_relative": verified_result["receipt_relative"],
                            },
                        },
                    )

                # 5. atomic latest pointer (only after full verification)
                entries = dict(latest.get("entries", {}))
                entries[key] = {
                    "run_id": run_id,
                    "status": scan.status,
                    "owner": owner,
                    "idempotency_key": idem_key,
                    "artifact_relative": artifact_relative,
                    "manifest_relative": manifest_relative,
                    "receipt_relative": receipt_relative,
                    "updated_at": _now_iso(),
                }
                entries[key].update(
                    {
                        "artifact_sha256": verified_result["artifact_sha256"],
                        "manifest_sha256": verified_result["manifest_sha256"],
                        "receipt_sha256": verified_result["receipt_sha256"],
                    }
                )
                if previous_identity is not None and supersession_relative is not None:
                    entries[key].update(
                        {
                            "superseded_from": previous_identity,
                            "supersession_relative": supersession_relative,
                        }
                    )
                self._write_json(self.latest_path, {"schema_version": LATEST_SCHEMA_VERSION, "entries": entries})
            except Exception as error:
                try:
                    self._write_json(
                        run_dir / "receipt.json",
                        {
                            "schema_version": RECEIPT_SCHEMA_VERSION,
                            "owner": owner,
                            "run_id": run_id,
                            "idempotency_key": idem_key,
                            "attempt": attempt,
                            "started_at": started_at,
                            "finished_at": _now_iso(),
                            "status": FAILED,
                            "error": str(error),
                            "manifest_sha256": "",
                            "artifact_sha256": "",
                            "trade_date": trade_date,
                            "role": role,
                            "source_id": source_id,
                            "stage_id": selected_stage,
                            "production_allowed": False,
                            "buy_gate_updated": False,
                            "orders_sent": False,
                        },
                    )
                except OSError:
                    pass
                raise StoreError(f"replay failed closed: {error}") from error

        return {"ok": True, "already_exists": False, "attempt": attempt, **verified_result}

    # -- inspection ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        latest = self._load_latest()
        entries = latest.get("entries", {})
        summary: dict[str, Any] = {"schema_version": LATEST_SCHEMA_VERSION, "runs": {}}
        for key, entry in entries.items():
            trade_date, role = key.split("/", 1)
            try:
                verified = self.verify_run(trade_date, role, entry["run_id"], expected_owner=entry.get("owner"))
                summary["runs"][key] = {"verified": True, **verified, "owner": entry.get("owner")}
            except StoreError as error:
                summary["runs"][key] = {"verified": False, "error": str(error), "owner": entry.get("owner")}
        summary["locked"] = self.lock_path.exists()
        return summary
