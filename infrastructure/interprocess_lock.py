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
from infrastructure.owned_io import LockAcquireTimeout, SafeRoot


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
    if value.get("schema_version") != _SCHEMA or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
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
        # Unclassified process-inspection failures are not proof of death.
        return True
    return True


@contextmanager
def owned_interprocess_lock(
    path: Path, *, timeout_seconds: float, timeout_message: str, poll_seconds: float = 0.02, timeout_error: type[ValueError] = ValueError,
) -> Iterator[None]:
    """Local POSIX kernel mutex, bridged to legacy PID/token owners.

    All new writers hold a persistent .mutex inode; process death releases it.
    Live or undecodable legacy owners are never removed by age. Stop all old
    writers before cutover; a corrupted legacy owner requires manual recovery.
    """
    path = Path(path)
    io = SafeRoot(path.parent)
    owner_raw = _owner_bytes(os.getpid(), uuid4().hex)
    deadline = time.monotonic() + timeout_seconds
    try:
        with io.kernel_lock(path.name + ".mutex", timeout=timeout_seconds, poll=poll_seconds):
            while True:
                try:
                    io.write_bytes(path.name, owner_raw, require_absent=True)
                    break
                except FileExistsError:
                    try:
                        observed = io.read_bytes(path.name, max_bytes=8192)
                    except FileNotFoundError:
                        continue
                    owner = _decode_owner(observed)
                    if owner is not None and not _pid_is_alive(owner[0]):
                        io.unlink_if_same(path.name, observed)
                        continue
                    if time.monotonic() >= deadline:
                        raise timeout_error(timeout_message)
                    time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
            try:
                yield
            finally:
                io.unlink_if_same(path.name, owner_raw)
    except LockAcquireTimeout as exc:
        raise timeout_error(timeout_message) from exc
