"""Owned cross-process lock files with dead-owner recovery."""
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
    handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(handle, raw)
        os.fsync(handle)
    finally:
        os.close(handle)


def _unlink_if_same(path: Path, expected: bytes) -> bool:
    try:
        if path.read_bytes() != expected:
            return False
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def _try_reclaim(path: Path, observed: bytes, claim_raw: bytes) -> bool:
    reclaim_path = path.with_name(f"{path.name}.reclaim")
    try:
        _write_exclusive(reclaim_path, claim_raw)
    except FileExistsError:
        return False
    try:
        try:
            current = path.read_bytes()
        except FileNotFoundError:
            return True
        owner = _decode_owner(current)
        return current == observed and owner is not None and not _pid_is_alive(owner[0]) and _unlink_if_same(path, current)
    finally:
        _unlink_if_same(reclaim_path, claim_raw)


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
            try:
                observed = path.read_bytes()
            except FileNotFoundError:
                continue
            owner = _decode_owner(observed)
            if owner is not None and not _pid_is_alive(owner[0]) and _try_reclaim(path, observed, owner_raw):
                continue
            if time.monotonic() >= deadline:
                raise ValueError(timeout_message)
            time.sleep(poll_seconds)
    try:
        yield
    finally:
        _unlink_if_same(path, owner_raw)
