"""Exact-date immutable JSON artifact storage for Review Core."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

MANIFEST_SCHEMA = "review_core.pool_store.manifest.v1"
RECEIPT_SCHEMA = "review_core.pool_store.receipt.v1"
CURRENT_SCHEMA = "review_core.pool_store.current.v1"
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
ROLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
STATUSES = {"READY", "READY_EMPTY", "PARTIAL", "CANNOT_CONFIRM", "FAILED"}

class StoreError(Exception):
    """Exact-slot verification failure."""

class ConflictError(StoreError):
    """Different immutable content attempted for one exact slot."""

def _validate_date(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise StoreError("trade_date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise StoreError("trade_date must be a real calendar date") from error
    return value

def _validate_slug(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ROLE_RE.fullmatch(value):
        raise StoreError(f"{label} must be a strict safe slug")
    return value

def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise StoreError(f"non-canonical JSON artifact: {error}") from error


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError as error:
        raise StoreError(f"store file cannot be read: {path}") from error
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StoreError(f"invalid store JSON: {path}") from error


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _row_count(artifact: Any, explicit: int | None) -> int:
    value: Any = explicit
    if value is None:
        if isinstance(artifact, list):
            value = len(artifact)
        elif isinstance(artifact, Mapping):
            value = next((len(artifact[key]) for key in ("rows", "model_rows", "close_top20", "stage_rows") if isinstance(artifact.get(key), list)), 1)
        else:
            value = 1
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StoreError("row_count must be a non-negative integer")
    return value


def _assert_safety_flags(payload: Mapping[str, Any], name: str) -> None:
    if any(payload.get(key) is not False for key in SAFETY_FLAGS):
        raise StoreError(f"{name} safety flags must all be false")


class PoolStore:
    """Immutable run trio plus one current pointer per exact date and role."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.runs_root = self.root / "runs"
        self.current_root = self.root / "current"
        self.lock_path = self.root / ".pool_store.lock"

    def current_path(self, trade_date: str, role: str) -> Path:
        date = _validate_date(trade_date)
        safe_role = _validate_slug(role, "role")
        return self.current_root / date / safe_role / "current.json"

    def _run_dir(self, date: str, role: str, run_id: str) -> Path:
        return self.runs_root / date / role / run_id

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        token = f"{os.getpid()}:{time.time_ns()}"
        deadline = time.monotonic() + 10.0
        while True:
            try:
                descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                    handle.write(token)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise StoreError("pool store lock timeout")
                time.sleep(0.01)
        try:
            yield
        finally:
            try:
                if self.lock_path.read_text(encoding="ascii") == token:
                    self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def _verify_run(self, date: str, role: str, run_id: str) -> dict[str, Any]:
        directory = self._run_dir(date, role, run_id)
        paths = {
            name: directory / f"{name}.json" for name in ("artifact", "manifest", "receipt")
        }
        if not directory.is_dir() or any(not path.is_file() for path in paths.values()):
            raise StoreError("artifact, manifest, and receipt trio is incomplete")
        manifest = _read_json(paths["manifest"])
        receipt = _read_json(paths["receipt"])
        if not isinstance(manifest, Mapping) or not isinstance(receipt, Mapping):
            raise StoreError("manifest and receipt must be objects")
        for name, payload, schema in (
            ("manifest", manifest, MANIFEST_SCHEMA),
            ("receipt", receipt, RECEIPT_SCHEMA),
        ):
            if (
                payload.get("schema_version") != schema
                or payload.get("trade_date") != date
                or payload.get("role") != role
                or payload.get("run_id") != run_id
            ):
                raise StoreError(f"{name} identity or schema mismatch")
            _assert_safety_flags(payload, name)
        if (
            manifest.get("status") != receipt.get("status")
            or manifest.get("row_count") != receipt.get("row_count")
            or manifest.get("status") not in STATUSES
        ):
            raise StoreError("manifest and receipt row/status mismatch")
        relative = f"runs/{date}/{role}/{run_id}/artifact.json"
        if manifest.get("artifact_relative") != relative:
            raise StoreError("manifest artifact path mismatch")
        artifact_sha = _sha256_file(paths["artifact"])
        manifest_sha = _sha256_file(paths["manifest"])
        receipt_sha = _sha256_file(paths["receipt"])
        if artifact_sha != manifest.get("artifact_sha256") or artifact_sha != receipt.get("artifact_sha256"):
            raise StoreError("artifact SHA mismatch")
        if manifest_sha != receipt.get("manifest_sha256"):
            raise StoreError("manifest SHA mismatch")
        artifact = _read_json(paths["artifact"])
        if _row_count(artifact, None) != manifest.get("row_count"):
            raise StoreError("row_count mismatch")
        return {
            "run_id": run_id,
            "artifact": artifact,
            "manifest": dict(manifest),
            "receipt": dict(receipt),
            "artifact_path": paths["artifact"],
            "manifest_path": paths["manifest"],
            "receipt_path": paths["receipt"],
            "artifact_sha256": artifact_sha,
            "manifest_sha256": manifest_sha,
            "receipt_sha256": receipt_sha,
        }

    def _verify_current(self, date: str, role: str) -> dict[str, Any]:
        pointer_path = self.current_path(date, role)
        if not pointer_path.is_file():
            raise StoreError(f"exact current missing: {date}/{role}")
        pointer = _read_json(pointer_path)
        if not isinstance(pointer, Mapping) or pointer.get("schema_version") != CURRENT_SCHEMA:
            raise StoreError("current schema mismatch")
        run_id = _validate_slug(pointer.get("run_id"), "run_id")
        if pointer.get("trade_date") != date or pointer.get("role") != role:
            raise StoreError("current identity mismatch")
        _assert_safety_flags(pointer, "current")
        verified = self._verify_run(date, role, run_id)
        expected = {
            "status": verified["receipt"]["status"],
            "row_count": verified["receipt"]["row_count"],
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
        }
        if any(pointer.get(key) != value for key, value in expected.items()):
            raise StoreError("current SHA, row, or status mismatch")
        if pointer.get("artifact_relative") != f"runs/{date}/{role}/{run_id}/artifact.json":
            raise StoreError("current artifact path mismatch")
        return {"current": dict(pointer), **verified}

    def publish(
        self,
        trade_date: str,
        role: str,
        artifact: Any,
        *,
        run_id: str | None = None,
        row_count: int | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        date = _validate_date(trade_date)
        safe_role = _validate_slug(role, "role")
        if isinstance(artifact, Mapping) and any(key in artifact for key in SAFETY_FLAGS):
            _assert_safety_flags(artifact, "artifact")
        data = _canonical_json(artifact)
        count = _row_count(artifact, row_count)
        artifact_sha = _sha256_bytes(data)
        selected_run = _validate_slug(
            run_id or f"{date}-{safe_role.lower()}-{artifact_sha[:12]}", "run_id"
        )
        selected_status = status or (
            artifact.get("status") if isinstance(artifact, Mapping) else None
        ) or ("READY" if count else "READY_EMPTY")
        if selected_status not in STATUSES:
            raise StoreError(f"unsupported status: {selected_status!r}")
        directory = self._run_dir(date, safe_role, selected_run)
        relative = f"runs/{date}/{safe_role}/{selected_run}"
        with self._lock():
            pointer_path = self.current_path(date, safe_role)
            if pointer_path.exists():
                existing = self._verify_current(date, safe_role)
                if existing["artifact_sha256"] == artifact_sha:
                    return {
                        "status": existing["receipt"]["status"],
                        "idempotent": True,
                        "trade_date": date,
                        "role": safe_role,
                        "run_id": existing["run_id"],
                        "artifact_sha256": artifact_sha,
                        "manifest_sha256": existing["manifest_sha256"],
                        "receipt_sha256": existing["receipt_sha256"],
                    }
                raise ConflictError(f"exact slot conflict: {date}/{safe_role}")
            if directory.exists():
                raise ConflictError(f"immutable run already exists: {directory}")
            directory.mkdir(parents=True)
            manifest = {
                "schema_version": MANIFEST_SCHEMA,
                "trade_date": date,
                "role": safe_role,
                "run_id": selected_run,
                "status": selected_status,
                "row_count": count,
                "artifact_sha256": artifact_sha,
                "artifact_relative": f"{relative}/artifact.json",
                **{key: False for key in SAFETY_FLAGS},
            }
            _atomic_write(directory / "artifact.json", data)
            _atomic_write(directory / "manifest.json", _canonical_json(manifest))
            manifest_sha = _sha256_file(directory / "manifest.json")
            receipt = {
                "schema_version": RECEIPT_SCHEMA,
                "trade_date": date,
                "role": safe_role,
                "run_id": selected_run,
                "status": selected_status,
                "row_count": count,
                "artifact_sha256": artifact_sha,
                "manifest_sha256": manifest_sha,
                **{key: False for key in SAFETY_FLAGS},
            }
            _atomic_write(directory / "receipt.json", _canonical_json(receipt))
            verified = self._verify_run(date, safe_role, selected_run)
            pointer = {
                "schema_version": CURRENT_SCHEMA,
                "trade_date": date,
                "role": safe_role,
                "run_id": selected_run,
                "status": selected_status,
                "row_count": count,
                "artifact_sha256": artifact_sha,
                "manifest_sha256": manifest_sha,
                "receipt_sha256": verified["receipt_sha256"],
                "artifact_relative": f"{relative}/artifact.json",
                **{key: False for key in SAFETY_FLAGS},
            }
            _atomic_write(pointer_path, _canonical_json(pointer))
            self._verify_current(date, safe_role)
        return {
            "status": selected_status,
            "idempotent": False,
            "trade_date": date,
            "role": safe_role,
            "run_id": selected_run,
            "artifact_sha256": artifact_sha,
            "manifest_sha256": manifest_sha,
            "receipt_sha256": verified["receipt_sha256"],
        }

    def read_verified(self, trade_date: str, role: str) -> dict[str, Any]:
        date = _validate_date(trade_date)
        safe_role = _validate_slug(role, "role")
        return {"trade_date": date, "role": safe_role, **self._verify_current(date, safe_role)}
