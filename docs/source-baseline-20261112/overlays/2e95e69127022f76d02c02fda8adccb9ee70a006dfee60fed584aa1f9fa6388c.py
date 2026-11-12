"""Fail-closed, data-only repair control for the V4 runtime graph.

The repair surface accepts only the frozen action names and writes fixed
artifacts below the V4 runtime-graph root.  It never constructs or invokes
shell commands, schedulers, process launches, or user-provided paths.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import ctypes
from ctypes import wintypes
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator, model_validator

from .store import AtomicSnapshotStore, _assert_safe_path, _file_identity, _reparse

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows path
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX path
    msvcrt = None


REPAIR_REQUEST_SCHEMA = "v3_runtime_graph_repair_request.v1"
REPAIR_RECEIPT_SCHEMA = "v3_runtime_graph_repair_receipt.v1"
REPAIR_LEDGER_SCHEMA = "v3_runtime_graph_repair_ledger.v1"
REPAIR_JOURNAL_SCHEMA = "v3_runtime_graph_repair_journal.v1"
ALLOWED_ACTIONS = frozenset(
    {
        "REBUILD_GRAPH_SNAPSHOT",
        "RELOAD_ACCEPTED_ARTIFACT_CACHE",
        "RETRY_IDEMPOTENT_NODE",
        "REPAIR_VERIFIED_DATE_POINTER",
    }
)
DENIED_ACTIONS = frozenset(
    {
        "OVERWRITE_FORMAL_POOL",
        "CHANGE_SCORE_RULE",
        "DELETE_ARTIFACT",
        "DISABLE_CANONICAL_TASK",
        "SWITCH_SCHEDULER",
        "STOP_RESEARCH_PROCESS",
    }
)
MAX_ATTEMPTS = 2
MAX_REQUEST_BYTES = 16 * 1024
MAX_CONTEXT_KEYS = 16
MAX_CONTEXT_DEPTH = 4
MAX_CONTEXT_BYTES = 8 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
MAX_LEDGER_BYTES = 256 * 1024
MAX_JOURNAL_BYTES = 64 * 1024
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_MARKER_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath(
            (os.path.normcase(str(path)), os.path.normcase(str(root)))
        ) == os.path.normcase(str(root))
    except ValueError:
        return False


def _assert_no_reparse_ancestors(path: Path) -> None:
    absolute = Path(os.path.abspath(str(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError("REPAIR_STATE_UNSAFE") from error
        if _reparse(metadata):
            raise ValueError("REPAIR_STATE_UNSAFE")


def _ensure_directory(path: Path, *, allowed_root: Path) -> Path:
    destination = Path(os.path.abspath(str(path)))
    root = Path(os.path.abspath(str(allowed_root)))
    if not _within(destination, root):
        raise ValueError("REPAIR_STATE_UNSAFE")
    # Check containment and the complete parent chain before mkdir.
    _assert_no_reparse_ancestors(root)
    _assert_no_reparse_ancestors(destination)
    try:
        metadata = os.lstat(destination)
    except FileNotFoundError:
        metadata = None
    except OSError as error:
        raise ValueError("REPAIR_STATE_UNSAFE") from error
    if metadata is not None and (_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode)):
        raise ValueError("REPAIR_STATE_UNSAFE")
    if metadata is None:
        destination.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_ancestors(destination)
    return destination


def _validate_posix_lock_identity(handle: int, path: Path) -> None:
    try:
        opened = os.fstat(handle)
        current = os.lstat(path)
    except OSError as error:
        raise ValueError('REPAIR_STATE_UNSAFE') from error
    for metadata in (opened, current):
        if (
            _reparse(metadata)
            or not stat.S_ISREG(metadata.st_mode)
            or int(getattr(metadata, 'st_nlink', 1)) != 1
        ):
            raise ValueError('REPAIR_STATE_UNSAFE')
    if _file_identity(opened) != _file_identity(current):
        raise ValueError('REPAIR_STATE_UNSAFE')


class _InterProcessFileLock:
    """Crash-released exclusive lock for the repair ledger critical section."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle: int | None = None
        self._native_handle: int | None = None

    def acquire(self, *, blocking: bool) -> bool:
        if fcntl is None and msvcrt is None:
            raise ValueError("REPAIR_LOCK_UNSUPPORTED")
        _assert_safe_path(self.path, self.path.parent.parent)
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_file = kernel32.CreateFileW
            create_file.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.LPVOID,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
            ]
            create_file.restype = wintypes.HANDLE
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            handle = create_file(
                str(self.path),
                0xC0000000,
                0,
                None,
                4,
                0x80,
                None,
            )
            invalid = wintypes.HANDLE(-1).value
            if handle == invalid:
                error_code = ctypes.get_last_error()
                if error_code in {32, 33}:
                    return False
                raise OSError(error_code, "CreateFileW")
            try:
                metadata = os.lstat(self.path)
                if (
                    _reparse(metadata)
                    or not stat.S_ISREG(metadata.st_mode)
                    or int(getattr(metadata, "st_nlink", 1)) != 1
                ):
                    raise ValueError("REPAIR_STATE_UNSAFE")
            except Exception:
                close_handle(handle)
                raise
            self._native_handle = handle
            return True
        handle: int | None = None
        try:
            handle = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
            _validate_posix_lock_identity(handle, self.path)
            if os.fstat(handle).st_size < 1:
                os.ftruncate(handle, 1)
            os.lseek(handle, 0, os.SEEK_SET)
            if fcntl is not None:
                flags = fcntl.LOCK_EX
                if not blocking:
                    flags |= fcntl.LOCK_NB
                try:
                    fcntl.flock(handle, flags)
                except OSError:
                    return False
            else:
                mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                try:
                    msvcrt.locking(handle, mode, 1)
                except OSError:
                    return False
            _validate_posix_lock_identity(handle, self.path)
            self._handle = handle
            handle = None
            return True
        except FileNotFoundError as error:
            raise ValueError("REPAIR_STATE_UNSAFE") from error
        finally:
            if handle is not None:
                os.close(handle)

    def release(self) -> None:
        native_handle, self._native_handle = self._native_handle, None
        if native_handle is not None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle(wintypes.HANDLE(native_handle))
            return
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
            elif msvcrt is not None:
                os.lseek(handle, 0, os.SEEK_SET)
                msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(handle)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _validate_json_value(value: Any, *, depth: int) -> None:
    if depth > MAX_CONTEXT_DEPTH:
        raise ValueError("REPAIR_CONTEXT_TOO_DEEP")
    if value is None or type(value) in {str, int, bool}:
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise ValueError("REPAIR_CONTEXT_NONFINITE")
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_CONTEXT_KEYS:
            raise ValueError("REPAIR_CONTEXT_TOO_LARGE")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise ValueError("REPAIR_CONTEXT_KEY_INVALID")
            _validate_json_value(item, depth=depth + 1)
        return
    raise ValueError("REPAIR_CONTEXT_NON_JSON")


class RepairRequest(BaseModel):
    """Strict request envelope; it is never an execution specification."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["v3_runtime_graph_repair_request.v1"]
    request_id: str = Field(min_length=16, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    action: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    node_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    business_date: str = Field(min_length=8, max_length=8, pattern=r"^\d{8}$")
    topology_version_sha: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    input_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=1024)
    production_allowed: StrictBool
    buy_gate_updated: StrictBool
    orders_sent: StrictBool
    context: dict[str, Any]

    @field_validator("business_date")
    @classmethod
    def _real_date(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError as error:
            raise ValueError("REPAIR_DATE_INVALID") from error
        return value

    @field_validator("production_allowed", "buy_gate_updated", "orders_sent")
    @classmethod
    def _safety_flags_false(cls, value: bool) -> bool:
        if type(value) is not bool or value is not False:
            raise ValueError("REPAIR_SAFETY_FLAGS_REQUIRED_FALSE")
        return value

    @field_validator("context")
    @classmethod
    def _bounded_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > MAX_CONTEXT_KEYS:
            raise ValueError("REPAIR_CONTEXT_TOO_LARGE")
        _validate_json_value(value, depth=0)
        if len(_json_bytes(value)) > MAX_CONTEXT_BYTES:
            raise ValueError("REPAIR_CONTEXT_TOO_LARGE")
        return value

    @model_validator(mode="after")
    def _validate_tokens(self) -> "RepairRequest":
        if not _REQUEST_ID_RE.fullmatch(self.request_id) or not _NODE_ID_RE.fullmatch(self.node_id):
            raise ValueError("REPAIR_REQUEST_TOKEN_INVALID")
        if not all(_SHA_RE.fullmatch(value) for value in (self.topology_version_sha, self.snapshot_sha256, self.input_sha256)):
            raise ValueError("REPAIR_SHA_INVALID")
        if not self.reason.strip():
            raise ValueError("REPAIR_REASON_INVALID")
        return self


def parse_repair_request_bytes(raw: bytes) -> RepairRequest:
    """Parse strict JSON and reject duplicate keys and non-finite numbers."""
    def reject_constant(value: str) -> None:
        raise ValueError(f"REPAIR_REQUEST_NONFINITE:{value}")

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("REPAIR_REQUEST_DUPLICATE_FIELD")
            payload[key] = value
        return payload

    try:
        if not isinstance(raw, bytes) or not raw or len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("REPAIR_REQUEST_SIZE_INVALID")
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
        if not isinstance(parsed, dict):
            raise ValueError("REPAIR_REQUEST_OBJECT_REQUIRED")
        return RepairRequest.model_validate(parsed, strict=True)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
        raise ValueError("REPAIR_REQUEST_INVALID") from error


@dataclass(frozen=True)
class SnapshotState:
    raw: bytes
    payload: Mapping[str, Any]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


@dataclass(frozen=True)
class RepairResult:
    status: str
    request_id: str
    identity: str = ""
    attempt_number: int = 0
    receipt_path: str = ""
    replayed: bool = False
    executed: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "REPAIR_PASS"

    @classmethod
    def passive(cls, status: str, request: RepairRequest, *, identity: str = "") -> "RepairResult":
        return cls(status=status, request_id=request.request_id, identity=identity)

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "request_id": self.request_id,
            "identity": self.identity,
            "attempt_number": self.attempt_number,
            "receipt_path": self.receipt_path,
            "replayed": self.replayed,
            "executed": self.executed,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }


def _safe_file(path: Path, root: Path, *, maximum: int) -> tuple[bytes, os.stat_result]:
    _assert_safe_path(path, root)
    try:
        before = os.lstat(path)
    except FileNotFoundError as error:
        raise ValueError("REPAIR_STATE_MISSING") from error
    except OSError as error:
        raise ValueError("REPAIR_STATE_UNSAFE") from error
    if _reparse(before) or not stat.S_ISREG(before.st_mode) or int(getattr(before, "st_nlink", 1)) != 1 or before.st_size > maximum:
        raise ValueError("REPAIR_STATE_UNSAFE")
    identity = _file_identity(before)
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            raw = handle.read(maximum + 1)
            closed = os.fstat(handle.fileno())
        after = os.lstat(path)
    except OSError as error:
        raise ValueError("REPAIR_STATE_UNSAFE") from error
    if len(raw) > maximum or _reparse(after) or not stat.S_ISREG(after.st_mode) or int(getattr(after, "st_nlink", 1)) != 1 or any(_file_identity(item) != identity for item in (opened, closed, after)):
        raise ValueError("REPAIR_STATE_UNSAFE")
    return raw, after


def load_current_snapshot(runtime_root: Path) -> SnapshotState:
    root = Path(os.path.abspath(str(runtime_root)))
    path = root / "snapshots" / "current.json"
    raw, _ = _safe_file(path, root, maximum=1024 * 1024)

    def reject_constant(value: str) -> None:
        raise ValueError(value)

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("REPAIR_SNAPSHOT_DUPLICATE_FIELD")
            payload[key] = value
        return payload

    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_pairs, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("REPAIR_SNAPSHOT_UNSAFE") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != "v3_runtime_snapshot.v1":
        raise ValueError("REPAIR_SNAPSHOT_UNSAFE")
    return SnapshotState(raw=raw, payload=payload)


class RepairController:
    """Apply only fixed, idempotent V4-owned data repairs."""

    def __init__(
        self,
        *,
        runtime_root: Path,
        snapshot_provider: Callable[[], SnapshotState],
        rebuild_snapshot: Callable[[str], SnapshotState],
        allowed_node_ids: set[str] | frozenset[str],
    ) -> None:
        self.runtime_root = Path(os.path.abspath(str(runtime_root)))
        _assert_no_reparse_ancestors(self.runtime_root)
        self.snapshot_provider = snapshot_provider
        self.rebuild_snapshot = rebuild_snapshot
        self.allowed_node_ids = frozenset(allowed_node_ids)

    @property
    def state_root(self) -> Path:
        return self.runtime_root / "state"

    @property
    def repair_root(self) -> Path:
        return self.runtime_root / "repairs"

    @staticmethod
    def _identity(request: RepairRequest) -> str:
        return "|".join((request.action, request.node_id, request.business_date, request.topology_version_sha, request.snapshot_sha256, request.input_sha256))

    @staticmethod
    def _request_digest(request: RepairRequest) -> str:
        return hashlib.sha256(_json_bytes(request.model_dump(mode="json"))).hexdigest()

    def _ledger_path(self) -> Path:
        return self.state_root / "repair_ledger.json"

    def _lock_path(self) -> Path:
        return self.state_root / "repair.lock"

    def _publication_lock_path(self) -> Path:
        return self.state_root / "publication.lock"

    def _journal_path(self, request: RepairRequest) -> Path:
        return self.repair_root / request.request_id / "journal.json"

    def _load_journal(self, request: RepairRequest, digest: str, identity: str) -> dict[str, Any] | None:
        path = self._journal_path(request)
        if not path.exists():
            return None
        raw, _ = _safe_file(path, self.runtime_root, maximum=MAX_JOURNAL_BYTES)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("REPAIR_STATE_UNSAFE") from error
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != REPAIR_JOURNAL_SCHEMA
            or payload.get("request_id") != request.request_id
            or payload.get("request_sha256") != digest
            or payload.get("identity") != identity
            or payload.get("phase") not in {"IN_PROGRESS", "COMMITTED"}
            or any(payload.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        ):
            raise ValueError("REPAIR_STATE_UNSAFE")
        return payload

    def _journal(
        self,
        request: RepairRequest,
        *,
        digest: str,
        identity: str,
        attempt: int,
        receipt_path: Path,
        phase: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": REPAIR_JOURNAL_SCHEMA,
            "request_id": request.request_id,
            "request_sha256": digest,
            "identity": identity,
            "action": request.action,
            "node_id": request.node_id,
            "business_date": request.business_date,
            "attempt_number": attempt,
            "receipt_path": str(receipt_path),
            "phase": phase,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _load_ledger(self) -> dict[str, Any]:
        path = self._ledger_path()
        if not path.exists():
            return {"schema_version": REPAIR_LEDGER_SCHEMA, "attempts": {}, "requests": {}}
        raw, _ = _safe_file(path, self.runtime_root, maximum=MAX_LEDGER_BYTES)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("REPAIR_STATE_UNSAFE") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != REPAIR_LEDGER_SCHEMA or not isinstance(payload.get("attempts"), dict) or not isinstance(payload.get("requests"), dict):
            raise ValueError("REPAIR_STATE_UNSAFE")
        if len(payload["attempts"]) > 128 or len(payload["requests"]) > 128:
            raise ValueError("REPAIR_STATE_UNSAFE")
        return payload

    def _write_json(self, path: Path, payload: Mapping[str, Any], schema: str) -> None:
        _ensure_directory(path.parent, allowed_root=self.runtime_root)
        _assert_safe_path(path.parent, self.runtime_root)
        AtomicSnapshotStore(path, allowed_root=self.runtime_root, expected_schema=schema).write(payload)

    def _write_marker(self, request: RepairRequest, attempt: int) -> str:
        if request.action == "RELOAD_ACCEPTED_ARTIFACT_CACHE":
            path = self.state_root / "accepted_artifact_cache.reload.json"
            postcondition = "ACCEPTED_ARTIFACT_CACHE_RELOAD_MARKED"
        elif request.action == "RETRY_IDEMPOTENT_NODE":
            if request.node_id not in self.allowed_node_ids:
                raise ValueError("REPAIR_NODE_UNKNOWN")
            path = self.state_root / "retry_requests" / f"{request.node_id}.json"
            postcondition = "IDEMPOTENT_NODE_RETRY_MARKED"
        elif request.action == "REPAIR_VERIFIED_DATE_POINTER":
            if request.context.get("verified_date") != request.business_date:
                raise ValueError("REPAIR_VERIFIED_DATE_MISMATCH")
            path = self.state_root / "verified_date_pointer.json"
            postcondition = "VERIFIED_DATE_POINTER_REPAIRED"
        else:
            raise ValueError("REPAIR_ACTION_NOT_MARKER")
        if not _MARKER_NAME_RE.fullmatch(request.node_id):
            raise ValueError("REPAIR_NODE_UNKNOWN")
        payload = {
            "schema_version": "v3_runtime_graph_repair_marker.v1",
            "action": request.action,
            "node_id": request.node_id,
            "business_date": request.business_date,
            "request_id": request.request_id,
            "attempt_number": attempt,
            "reason": request.reason,
        }
        self._write_json(path, payload, "v3_runtime_graph_repair_marker.v1")
        return postcondition

    def _receipt(self, request: RepairRequest, identity: str, attempt: int, before: SnapshotState, after: SnapshotState, status: str, postcondition: str, started_at: str, finished_at: str, receipt_path: Path) -> dict[str, Any]:
        return {
            "schema_version": REPAIR_RECEIPT_SCHEMA,
            "request_id": request.request_id,
            "request_sha256": self._request_digest(request),
            "identity": identity,
            "action": request.action,
            "node_id": request.node_id,
            "business_date": request.business_date,
            "reason": request.reason,
            "topology_version_sha": request.topology_version_sha,
            "snapshot_sha256": request.snapshot_sha256,
            "input_sha256": request.input_sha256,
            "attempt_number": attempt,
            "status": status,
            "policy_id": f"v3.5:{request.action}",
            "started_at": started_at,
            "finished_at": finished_at,
            "before_sha256": before.sha256,
            "after_sha256": after.sha256,
            "rollback_reference": "NO_STATE_CHANGE",
            "rollback_artifact_sha256": hashlib.sha256(b"NO_STATE_CHANGE").hexdigest(),
            "rollback_artifact_identity": {"kind": "NO_STATE_CHANGE"},
            "postcondition": postcondition,
            "execution": {"returncode": 0 if status == "REPAIR_PASS" else None, "timed_out": False, "stdout": "", "stderr": ""},
            "circuit_state": "CLOSED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "receipt_path": str(receipt_path),
        }

    def handle(self, request: RepairRequest, *, authorization_verified: bool = False) -> RepairResult:
        if not isinstance(request, RepairRequest):
            return RepairResult(status="REPAIR_DENIED_REQUEST_INVALID", request_id="")
        identity = self._identity(request)
        if not authorization_verified:
            return RepairResult.passive("REPAIR_DENIED_AUTHORIZATION", request, identity=identity)
        if request.action in DENIED_ACTIONS or request.action not in ALLOWED_ACTIONS:
            return RepairResult.passive("REPAIR_DENIED_ACTION", request, identity=identity)
        if request.node_id not in self.allowed_node_ids:
            return RepairResult.passive("REPAIR_DENIED_NODE", request, identity=identity)
        if hashlib.sha256(_json_bytes(request.context)).hexdigest() != request.input_sha256:
            return RepairResult.passive("REPAIR_DENIED_INPUT_MISMATCH", request, identity=identity)
        try:
            _ensure_directory(self.state_root, allowed_root=self.runtime_root)
            lock = _InterProcessFileLock(self._lock_path())
            acquired = lock.acquire(blocking=False)
        except (OSError, ValueError, TypeError):
            return RepairResult.passive("REPAIR_DENIED_STATE_UNSAFE", request, identity=identity)
        if not acquired:
            return RepairResult.passive("REPAIR_BUSY", request, identity=identity)
        publication_lock: _InterProcessFileLock | None = None
        try:
            publication_lock = _InterProcessFileLock(self._publication_lock_path())
            if not publication_lock.acquire(blocking=False):
                return RepairResult.passive("REPAIR_BUSY", request, identity=identity)
            _ensure_directory(self.state_root, allowed_root=self.runtime_root)
            _ensure_directory(self.repair_root, allowed_root=self.runtime_root)
            _assert_safe_path(self.state_root, self.runtime_root)
            _assert_safe_path(self.repair_root, self.runtime_root)
            try:
                before = self.snapshot_provider()
            except (OSError, ValueError, TypeError):
                return RepairResult.passive("REPAIR_DENIED_SNAPSHOT_UNAVAILABLE", request, identity=identity)
            if before.sha256 != request.snapshot_sha256 or str(before.payload.get("topology_version_sha")) != request.topology_version_sha:
                return RepairResult.passive("REPAIR_DENIED_INPUT_MISMATCH", request, identity=identity)
            ledger = self._load_ledger()
            digest = self._request_digest(request)
            prior = ledger["requests"].get(request.request_id)
            if prior is not None:
                if not isinstance(prior, dict) or prior.get("request_sha256") != digest:
                    return RepairResult.passive("REPAIR_DENIED_REQUEST_ID_CONFLICT", request, identity=identity)
                result = prior.get("result")
                if isinstance(result, dict):
                    return RepairResult(
                        status=str(result.get("status") or "REPAIR_DENIED_STATE_UNSAFE"),
                        request_id=request.request_id,
                        identity=identity,
                        attempt_number=int(result.get("attempt_number") or 0),
                        receipt_path=str(result.get("receipt_path") or ""),
                        replayed=True,
                        executed=bool(result.get("executed")),
                    )
                return RepairResult.passive("REPAIR_DENIED_STATE_UNSAFE", request, identity=identity)
            attempts = ledger["attempts"].get(identity, 0)
            if type(attempts) is not int or attempts < 0 or attempts >= MAX_ATTEMPTS:
                return RepairResult.passive("REPAIR_CIRCUIT_OPEN", request, identity=identity)
            attempt = attempts + 1
            receipt_path = self.repair_root / request.request_id / f"attempt-{attempt}.json"
            journal = self._load_journal(request, digest, identity)
            if journal is not None:
                return RepairResult(
                    status="REPAIR_RECOVERY_REQUIRED",
                    request_id=request.request_id,
                    identity=identity,
                    attempt_number=int(journal.get("attempt_number") or attempt),
                    receipt_path=str(journal.get("receipt_path") or receipt_path),
                    executed=False,
                )
            try:
                self._write_json(
                    self._journal_path(request),
                    self._journal(
                        request,
                        digest=digest,
                        identity=identity,
                        attempt=attempt,
                        receipt_path=receipt_path,
                        phase="IN_PROGRESS",
                    ),
                    REPAIR_JOURNAL_SCHEMA,
                )
            except (OSError, ValueError, TypeError):
                return RepairResult(
                    status="REPAIR_FAILED_JOURNAL",
                    request_id=request.request_id,
                    identity=identity,
                    attempt_number=attempt,
                    receipt_path=str(receipt_path),
                    executed=False,
                )
            started_at = datetime.now().astimezone().isoformat(timespec="seconds")
            postcondition = ""
            status = "REPAIR_PASS"
            after = before
            try:
                if request.action == "REBUILD_GRAPH_SNAPSHOT":
                    after = self.rebuild_snapshot(request.business_date)
                    postcondition = "GRAPH_SNAPSHOT_REBUILT"
                else:
                    postcondition = self._write_marker(request, attempt)
                    after = self.snapshot_provider()
            except (OSError, ValueError, TypeError) as error:
                status = "REPAIR_FAILED_POSTCONDITION"
                postcondition = type(error).__name__
                after = before
            finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
            result = RepairResult(
                status=status,
                request_id=request.request_id,
                identity=identity,
                attempt_number=attempt,
                receipt_path=str(receipt_path),
                executed=status == "REPAIR_PASS",
            )
            try:
                receipt = self._receipt(request, identity, attempt, before, after, status, postcondition, started_at, finished_at, receipt_path)
                self._write_json(receipt_path, receipt, REPAIR_RECEIPT_SCHEMA)
                ledger["attempts"][identity] = attempt
                ledger["requests"][request.request_id] = {
                    "request_sha256": digest,
                    "identity": identity,
                    "attempt_number": attempt,
                    "result": result.to_payload(),
                }
                self._write_json(self._ledger_path(), ledger, REPAIR_LEDGER_SCHEMA)
                self._write_json(
                    self._journal_path(request),
                    self._journal(
                        request,
                        digest=digest,
                        identity=identity,
                        attempt=attempt,
                        receipt_path=receipt_path,
                        phase="COMMITTED",
                    ),
                    REPAIR_JOURNAL_SCHEMA,
                )
            except (OSError, ValueError, TypeError):
                return RepairResult(
                    status="REPAIR_FAILED_RECEIPT",
                    request_id=request.request_id,
                    identity=identity,
                    attempt_number=attempt,
                    receipt_path=str(receipt_path),
                    executed=status == "REPAIR_PASS",
                )
            return result
        except (OSError, ValueError, TypeError):
            return RepairResult.passive("REPAIR_DENIED_STATE_UNSAFE", request, identity=identity)
        finally:
            if publication_lock is not None:
                publication_lock.release()
            lock.release()
