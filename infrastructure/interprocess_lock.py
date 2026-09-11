"""Owned cross-process lock files with dead-owner recovery.

Locks are created atomically carrying an owner record (pid + token), so a
crash can never leave an ownerless empty lock behind.  An unknown or
unreadable owner record is never guessed dead: recovery is fail-closed and
the timeout error names which lock blocks and in what state.  Locks are
released with an unlink-if-same guard so one holder can never delete a
successor's lock.
"""
from __future__ import annotations

import errno
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


_SCHEMA = "v3_5_interprocess_lock.v1"


def _owner_bytes(pid: int, token: str) -> bytes:
    return json.dumps(
        {"schema_version": _SCHEMA, "pid": pid, "token": token},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _decode_owner(raw: bytes) -> tuple[int, str] | None:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        try:
            pid_text, token = raw.decode("ascii").split(":", 1)
            pid = int(pid_text)
        except (UnicodeDecodeError, ValueError):
            return None
        return (pid, token) if pid > 0 and token else None
    if not isinstance(value, dict):
        return None
    pid = value.get("pid")
    token = value.get("token")
    if value.get("schema_version") != _SCHEMA or not isinstance(pid, int) or pid <= 0:
        return None
    if not isinstance(token, str) or not token:
        return None
    return pid, token


def _pid_is_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        if error.errno == errno.ESRCH:
            return False
        if error.errno == errno.EPERM:
            return True
        return False
    return True


def _write_exclusive(path: Path, raw: bytes) -> None:
    """Create ``path`` carrying ``raw`` in one atomic step.

    The owner record is staged in a temporary sibling and linked into place,
    so other processes can never observe an empty or half-written lock file.
    Filesystems without hardlink support fall back to the classic
    O_EXCL-then-write sequence.
    """
    staged = path.with_name(f".{path.name}.{uuid4().hex}.staged")
    handle = os.open(staged, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(handle, raw)
        os.fsync(handle)
    finally:
        os.close(handle)
    try:
        try:
            os.link(staged, path)
            return
        except FileExistsError:
            raise
        except OSError:
            pass
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(handle, raw)
            os.fsync(handle)
        finally:
            os.close(handle)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def _unlink_if_same(path: Path, expected: bytes) -> bool:
    try:
        if path.read_bytes() != expected:
            return False
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _lock_state(path: Path) -> tuple[str, tuple[int, str] | None, bytes]:
    """Classify a lock file as missing / empty / corrupt / live / dead."""

    try:
        observed = path.read_bytes()
    except FileNotFoundError:
        return "missing", None, b""
    if not observed:
        return "empty", None, observed
    owner = _decode_owner(observed)
    if owner is None:
        return "corrupt", None, observed
    return ("live" if _pid_is_alive(owner[0]) else "dead"), owner, observed


def recover_owner_lock_residue(path: Path) -> bool:
    """Remove an empty or dead-owner side lock; never a live owner's.

    Returns True when a residue was removed, so callers can retry the
    atomic acquisition immediately.
    """

    try:
        observed = path.read_bytes()
    except FileNotFoundError:
        return False
    if not observed:
        return _unlink_if_same(path, observed)
    owner = _decode_owner(observed)
    if owner is not None and not _pid_is_alive(owner[0]):
        return _unlink_if_same(path, observed)
    return False


def _drop_reclaim_residue(reclaim_path: Path) -> None:
    """Remove an empty or dead-owner reclaim file; never a live reclaimer's."""

    recover_owner_lock_residue(reclaim_path)


def _try_reclaim(path: Path, observed: bytes, claim_raw: bytes) -> bool:
    reclaim_path = path.with_name(f"{path.name}.reclaim")
    _drop_reclaim_residue(reclaim_path)
    try:
        _write_exclusive(reclaim_path, claim_raw)
    except FileExistsError:
        return False
    try:
        try:
            current = path.read_bytes()
        except FileNotFoundError:
            return True
        if current != observed:
            return False
        if current:
            owner = _decode_owner(current)
            if owner is None or _pid_is_alive(owner[0]):
                return False
        return _unlink_if_same(path, current)
    finally:
        _unlink_if_same(reclaim_path, claim_raw)


def _blocked_detail(name: str, state: str, owner: tuple[int, str] | None) -> str:
    if state == "live" and owner is not None:
        return f"{name} held by live pid {owner[0]}"
    if state == "corrupt":
        return f"{name} owner record unreadable; manual recovery required"
    if state == "empty":
        return f"{name} empty owner residue"
    return f"{name} blocked in state {state}"


@contextmanager
def owned_interprocess_lock(
    path: Path,
    *,
    timeout_seconds: float,
    timeout_message: str,
    poll_seconds: float = 0.02,
) -> Iterator[None]:
    """Acquire ``path`` without stealing a lock from a live owner."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    owner_raw = _owner_bytes(os.getpid(), uuid4().hex)
    while True:
        try:
            _write_exclusive(path, owner_raw)
            break
        except FileExistsError:
            state, owner, observed = _lock_state(path)
            if state == "missing":
                continue
            if state in ("empty", "dead") and _try_reclaim(path, observed, owner_raw):
                continue
            if time.monotonic() >= deadline:
                raise ValueError(f"{timeout_message} [{_blocked_detail(path.name, state, owner)}]")
            time.sleep(poll_seconds)
    try:
        yield
    finally:
        _unlink_if_same(path, owner_raw)
