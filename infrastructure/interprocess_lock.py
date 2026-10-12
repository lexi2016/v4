"""Owned cross-process lock files with dead-owner recovery."""
from __future__ import annotations

import errno
import json
import os
import stat
import threading
from dataclasses import dataclass
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


@dataclass(frozen=True, eq=False)
class OwnedInterprocessLockLease:
    """Process-local capability for the exact live mutex context.

    Constructing/copying this value does not mint a capability: only the
    original instance in _ACTIVE_LEASES is accepted. It is not serializable
    authority and must never be used after context exit or across a fork.
    """

    path: Path
    pid: int
    thread_id: int
    _owner_raw: bytes
    _mutex_fd: int
    _mutex_identity: tuple[int, int]
    _owner_identity: tuple[int, int]
    _parent_identity: tuple[int, int]


_ACTIVE_LEASES: dict[int, OwnedInterprocessLockLease] = {}
_LEASE_GUARD = threading.Lock()


def _reset_lease_registry_after_fork() -> None:
    # The child owns neither the parent's capabilities nor its thread mutex.
    global _ACTIVE_LEASES, _LEASE_GUARD
    _ACTIVE_LEASES = {}
    _LEASE_GUARD = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_lease_registry_after_fork)


def _inode(meta: os.stat_result) -> tuple[int, int]:
    return meta.st_dev, meta.st_ino


def assert_owned_interprocess_lock(lease: object, path: Path) -> None:
    """Reject absent, forged, expired, moved or foreign lock authority."""
    if (
        type(lease) is not OwnedInterprocessLockLease
        or lease.pid != os.getpid()
        or lease.thread_id != threading.get_ident()
    ):
        raise ValueError("OWNER_LOCK_LEASE_NOT_OWNED")
    with _LEASE_GUARD:
        if _ACTIVE_LEASES.get(id(lease)) is not lease:
            raise ValueError("OWNER_LOCK_LEASE_NOT_ACTIVE")
    supplied = Path(path).expanduser()
    if ".." in supplied.parts:
        raise ValueError("OWNER_LOCK_LEASE_PATH_MISMATCH")
    supplied = Path(os.path.abspath(supplied))
    if supplied != lease.path:
        raise ValueError("OWNER_LOCK_LEASE_PATH_MISMATCH")
    io = SafeRoot(supplied.parent)
    try:
        with io.directory() as parent:
            mutex = os.stat(supplied.name + ".mutex", dir_fd=parent, follow_symlinks=False)
            owner = os.stat(supplied.name, dir_fd=parent, follow_symlinks=False)
            held = os.fstat(lease._mutex_fd)
            if (
                _inode(os.fstat(parent)) != lease._parent_identity
                or not stat.S_ISREG(mutex.st_mode)
                or not stat.S_ISREG(owner.st_mode)
                or not stat.S_ISREG(held.st_mode)
                or _inode(mutex) != lease._mutex_identity
                or _inode(held) != lease._mutex_identity
                or _inode(owner) != lease._owner_identity
                or io.read_bytes(supplied.name, max_bytes=8192) != lease._owner_raw
                or _inode(os.stat(supplied.name, dir_fd=parent, follow_symlinks=False)) != lease._owner_identity
            ):
                raise ValueError("OWNER_LOCK_LEASE_IDENTITY_CHANGED")
    except OSError as exc:
        raise ValueError("OWNER_LOCK_LEASE_IDENTITY_UNAVAILABLE") from exc


@contextmanager
def owned_interprocess_lock(
    path: Path, *, timeout_seconds: float, timeout_message: str, poll_seconds: float = 0.02, timeout_error: type[ValueError] = ValueError,
) -> Iterator[OwnedInterprocessLockLease]:
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
        with io.kernel_lock(path.name + ".mutex", timeout=timeout_seconds, poll=poll_seconds) as mutex_fd:
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
            lease = None
            try:
                with io.directory() as parent:
                    lease = OwnedInterprocessLockLease(
                        path=io.root / path.name, pid=os.getpid(),
                        thread_id=threading.get_ident(), _owner_raw=owner_raw,
                        _mutex_fd=mutex_fd, _mutex_identity=_inode(os.fstat(mutex_fd)),
                        _owner_identity=_inode(os.stat(path.name, dir_fd=parent, follow_symlinks=False)),
                        _parent_identity=_inode(os.fstat(parent)),
                    )
                with _LEASE_GUARD:
                    _ACTIVE_LEASES[id(lease)] = lease
                assert_owned_interprocess_lock(lease, path)
                yield lease
            finally:
                if lease is not None:
                    with _LEASE_GUARD:
                        _ACTIVE_LEASES.pop(id(lease), None)
                io.unlink_if_same(path.name, owner_raw)
    except LockAcquireTimeout as exc:
        raise timeout_error(timeout_message) from exc
