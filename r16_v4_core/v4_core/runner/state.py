"""Durable publication primitives for the isolated V4 slot writer."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import traceback
from typing import Any, Iterator
import uuid


_UNSET = object()


class WriterBusy(RuntimeError):
    """Another local V4 slot owns the writer lock."""


class ConcurrentHistoryChange(AssertionError):
    """The history checkpoint changed during a locked write."""


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()


def file_identity(path: Path) -> dict[str, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return {key: getattr(stat, f"st_{key}") for key in ("dev", "ino", "size", "mtime_ns", "ctime_ns")}


@dataclass(frozen=True)
class WriterLease:
    lock_path: Path
    failure_dir: Path
    owner: dict[str, Any]


@contextmanager
def writer_lease(data_dir: Path, logs_dir: Path, workload: str) -> Iterator[WriterLease]:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / ".r16-writer.lock"
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WriterBusy(f"V4 writer lock busy at {path}") from exc
        owner = {
            "pid": os.getpid(), "ppid": os.getppid(), "workload": workload,
            "acquired_at": datetime.now(timezone.utc).isoformat(), "token": uuid.uuid4().hex,
        }
        handle.seek(0)
        handle.truncate()
        handle.write(json_bytes(owner))
        handle.flush()
        os.fsync(handle.fileno())
        yield WriterLease(path, logs_dir / "writer_assertions", owner)


def _sync_directory(parent: Path) -> None:
    fd = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def discard_published_file(path: Path, expected: dict[str, int]) -> None:
    """Remove the still-owned pointer from a failed first publication."""
    if file_identity(path) == expected:
        path.unlink()
        _sync_directory(path.parent)


def publish_bytes(
    path: Path, data: bytes, *, lease: WriterLease | None = None,
    expected: dict[str, int] | object | None = _UNSET,
) -> str:
    """Flush a sibling temp file, check the original and replace it atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    before = file_identity(path) if lease and expected is _UNSET else expected
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if lease:
            after = file_identity(path)
            if before != after:
                try:
                    raise ConcurrentHistoryChange(f"History checkpoint changed before replace: {path}")
                except ConcurrentHistoryChange:
                    publish_json(lease.failure_dir / f"{uuid.uuid4().hex}.json", {
                        "error": "HISTORY_CHECKPOINT_IDENTITY_CHANGED", "path": str(path),
                        "before": before, "after": after, "pid": os.getpid(), "ppid": os.getppid(),
                        "stack": "".join(traceback.format_stack()) + traceback.format_exc(),
                        "lock_path": str(lease.lock_path),
                        "lock_owner": lease.owner, "recorded_at": datetime.now(timezone.utc).isoformat(),
                    })
                    raise
        os.replace(temp, path)
        _sync_directory(path.parent)
    finally:
        Path(temp).unlink(missing_ok=True)
    return sha256(data).hexdigest()


def publish_json(
    path: Path, value: object, *, lease: WriterLease | None = None,
    expected: dict[str, int] | object | None = _UNSET,
) -> str:
    return publish_bytes(path, json_bytes(value), lease=lease, expected=expected)


SLOT_LEASE_TTL_SECONDS = 600


def last_window_record(receipt) -> tuple[dict | None, int | None]:
    """Return the last complete event and a trailing torn-record offset, if recognizable."""
    receipt.seek(0)
    previous = None
    while True:
        offset = receipt.tell()
        line = receipt.readline()
        if not line:
            return previous, None
        if not line.endswith(b"\n"):
            if previous is not None and previous["schedule_status"] == "RUNNING" and line.lstrip().startswith(b"{"):
                return previous, offset
            raise ValueError("INVALID_SLOT_JOURNAL")
        value = json.loads(line)
        if not isinstance(value, dict) or not isinstance(value.get("schedule_status"), str):
            raise ValueError("INVALID_SLOT_JOURNAL")
        previous = value


def archive_torn_window(receipt, offset: int, directory: Path, journal_name: str, lease: WriterLease) -> dict:
    """Retain the original bytes before dropping an uncommitted tail under both locks."""
    receipt.seek(0)
    original = receipt.read()
    digest = sha256(original).hexdigest()
    path = directory / f"{journal_name}.{digest}.original"
    if not path.exists():
        publish_bytes(path, original, lease=lease, expected=None)
    elif path.read_bytes() != original:
        raise ValueError("STALE_SLOT_JOURNAL_ARCHIVE_CONFLICT")
    receipt.truncate(offset)
    receipt.flush()
    os.fsync(receipt.fileno())
    return {"archived_journal": str(path), "archive_sha256": digest, "torn_tail_bytes": len(original) - offset}


def stale_running_reason(record: dict, heartbeat: Path, now: datetime) -> str | None:
    """Call only after acquiring the slot's exclusive file lock."""
    pid = record.get("pid")
    if type(pid) is int and pid > 0:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return "PID_EXITED"
        except PermissionError:
            pass
    try:
        current = json.loads(heartbeat.read_bytes())
    except (OSError, ValueError):
        current = {}
    if (not isinstance(current, dict) or current.get("lease_token") != record.get("lease_token")
            or current.get("attempt_id") != record.get("attempt_id")):
        current = {}
    expiry = current.get("lease_expires_at", record.get("lease_expires_at"))
    try:
        if expiry is None:
            expiry = datetime.fromisoformat(record["observed_at"]) + timedelta(seconds=SLOT_LEASE_TTL_SECONDS)
        else:
            expiry = datetime.fromisoformat(expiry)
        if now >= expiry:
            return "LEASE_EXPIRED"
    except (KeyError, TypeError, ValueError):
        # Unknown legacy ownership cannot bypass the safety fence.
        return None
    return None


def heartbeat_record(when: datetime) -> dict[str, str]:
    return {
        "heartbeat_at": when.isoformat(),
        "lease_expires_at": (when + timedelta(seconds=SLOT_LEASE_TTL_SECONDS)).isoformat(),
    }
