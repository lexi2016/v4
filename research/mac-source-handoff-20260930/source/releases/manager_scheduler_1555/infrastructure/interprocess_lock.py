"""Persistent owner-file flock for the local V3.5 collaborators.

The old v11 O_EXCL worker must be drained before deployment. Mixed old/new
execution is unsupported; the owner inode and its flock are the sole lock.
"""
from __future__ import annotations

import errno, fcntl, json, os, stat, threading
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep
from typing import Iterator
from uuid import uuid4

_SCHEMA = "v3_5_interprocess_lock.v1"
_MAX_OWNER_BYTES = 4096
_RELEASED_PID, _RELEASED_TOKEN = 2_147_483_647, "RELEASED"
_NOFOLLOW, _CLOEXEC, _DIRECTORY = (getattr(os, n, 0) for n in ("O_NOFOLLOW", "O_CLOEXEC", "O_DIRECTORY"))
_DIR_FLAGS = os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _DIRECTORY
_CREATE_FLAGS = os.O_CREAT | os.O_EXCL | os.O_RDWR | _NOFOLLOW | _CLOEXEC
_OPEN_FLAGS = os.O_RDWR | os.O_NONBLOCK | _NOFOLLOW | _CLOEXEC
_THREAD_LOCK = threading.Lock()

class _UnsafeLock(ValueError): pass
class _CleanupFailure(RuntimeError): pass

def _eintr(error: BaseException) -> bool:
    return isinstance(error, InterruptedError) or isinstance(error, OSError) and error.errno == errno.EINTR

def _retry(function, *args, deadline: float | None = None, **kwargs):
    while True:
        try: return function(*args, **kwargs)
        except OSError as error:
            if not _eintr(error): raise
            if deadline is not None and monotonic() >= deadline:
                raise _UnsafeLock("lock operation deadline expired") from error

def _close(fd: int) -> None:
    try: os.close(fd)
    except OSError as error: raise _CleanupFailure("lock descriptor close failed") from error

def _owner_bytes(pid: int, token: str) -> bytes:
    return json.dumps({"schema_version": _SCHEMA, "pid": pid, "token": token}, sort_keys=True, separators=(",", ":")).encode("ascii")

def _decode_owner(raw: bytes) -> tuple[int, str] | None:
    try: value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        try:
            pid_text, token = raw.decode("ascii").split(":", 1); pid = int(pid_text)
        except (UnicodeDecodeError, ValueError): return None
        return (pid, token) if pid > 0 and token and "/" not in token else None
    if not isinstance(value, dict): return None
    pid, token = value.get("pid"), value.get("token")
    valid = value.get("schema_version") == _SCHEMA and not isinstance(pid, bool) and isinstance(pid, int) and pid > 0 and isinstance(token, str) and bool(token) and "/" not in token
    return (pid, token) if valid else None

def _pid_is_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0: return False
    try: os.kill(pid, 0)
    except OSError as error: return error.errno != errno.ESRCH
    return True

def _open_parent(path: Path, deadline: float | None = None) -> tuple[int, str]:
    if not (_NOFOLLOW and _CLOEXEC and _DIRECTORY): raise _UnsafeLock("directory-safe opens unavailable")
    path, name, parent = Path(path), Path(path).name, Path(path).parent
    if not name or name in {".", ".."} or "/" in name: raise _UnsafeLock("unsafe lock name")
    parts = list(parent.parts)
    if parent.is_absolute():
        if not parts or parts[0] != os.sep: raise _UnsafeLock("unsafe lock parent")
        base, parts = os.sep, parts[1:]
    else:
        base = "."
        if any(part in {"", ".", ".."} for part in parts): raise _UnsafeLock("unsafe lock parent traversal")
    fd = _retry(os.open, base, _DIR_FLAGS, deadline=deadline)
    try:
        for part in parts:
            try: child = _retry(os.open, part, _DIR_FLAGS, dir_fd=fd, deadline=deadline)
            except FileNotFoundError:
                try: _retry(os.mkdir, part, 0o700, dir_fd=fd, deadline=deadline)
                except FileExistsError: pass
                child = _retry(os.open, part, _DIR_FLAGS, dir_fd=fd, deadline=deadline)
            old, fd = fd, child; _close(old)
        return fd, name
    except BaseException as error:
        try: _close(fd)
        except BaseException as cleanup: error.add_note(f"parent descriptor cleanup failed: {cleanup!r}")
        if isinstance(error, OSError): raise _UnsafeLock("lock parent is not a safe directory") from error
        raise

def _private_regular(details: os.stat_result, *, linked: bool = True) -> bool:
    return stat.S_ISREG(details.st_mode) and stat.S_IMODE(details.st_mode) == 0o600 and (not linked or details.st_nlink == 1)

def _open_owner(parent_fd: int, name: str, deadline: float | None) -> int:
    while True:
        try: details = _retry(os.stat, name, dir_fd=parent_fd, follow_symlinks=False, deadline=deadline)
        except FileNotFoundError: details = None
        if details is not None and not _private_regular(details): raise _UnsafeLock("owner must be a private single-link regular file")
        try: fd = _retry(os.open, name, _CREATE_FLAGS if details is None else _OPEN_FLAGS, 0o600, dir_fd=parent_fd, deadline=deadline)
        except (FileExistsError, FileNotFoundError):
            if deadline is not None and monotonic() >= deadline: raise _UnsafeLock("owner open deadline expired")
            continue
        except OSError as error: raise _UnsafeLock("owner cannot be opened safely") from error
        try:
            if not _private_regular(_retry(os.fstat, fd, deadline=deadline)): raise _UnsafeLock("owner must be a private single-link regular file")
            return fd
        except BaseException as error:
            try: _close(fd)
            except BaseException as cleanup: error.add_note(f"owner descriptor cleanup failed: {cleanup!r}")
            raise

def _flock(fd: int, deadline: float, message: str, poll_seconds: float) -> None:
    while True:
        try:
            _retry(fcntl.flock, fd, fcntl.LOCK_EX | fcntl.LOCK_NB, deadline=deadline); return
        except OSError as error:
            if _eintr(error):
                if monotonic() >= deadline: raise _UnsafeLock(message)
                continue
            if error.errno not in (errno.EACCES, errno.EAGAIN): raise
        remaining = deadline - monotonic()
        if remaining <= 0: raise _UnsafeLock(message)
        try: _retry(sleep, min(max(0.0, poll_seconds), remaining), deadline=deadline)
        except InterruptedError: pass

def _write_all(fd: int, raw: bytes, deadline: float | None) -> None:
    _retry(os.ftruncate, fd, 0, deadline=deadline)
    _retry(os.lseek, fd, 0, os.SEEK_SET, deadline=deadline)
    view, offset = memoryview(raw), 0
    while offset < len(view):
        count = _retry(os.write, fd, view[offset:], deadline=deadline)
        if not isinstance(count, int) or count <= 0 or count > len(view) - offset: raise OSError("lock owner write made invalid progress")
        offset += count
    _retry(os.fsync, fd, deadline=deadline)
    if not _private_regular(_retry(os.fstat, fd, deadline=deadline), linked=False): raise _UnsafeLock("owner evidence is incomplete")

def _unlock_close(fd: int, deadline: float | None) -> BaseException | None:
    failures: list[BaseException] = []
    for function, args in ((fcntl.flock, (fd, fcntl.LOCK_UN)), (_close, (fd,))):
        try: _retry(function, *args, deadline=deadline)
        except BaseException as error: failures.append(error)
    if not failures: return None
    first = failures[0]
    for extra in failures[1:]: first.add_note(f"additional lock cleanup failure: {extra!r}")
    return first

def _acquire(path: Path, raw: bytes, deadline: float, message: str, poll_seconds: float) -> int:
    parent_fd, name = _open_parent(path, deadline); fd = -1
    try: fd = _open_owner(parent_fd, name, deadline)
    finally:
        try: _close(parent_fd)
        except BaseException as error:
            if fd >= 0:
                cleanup = _unlock_close(fd, deadline)
                if cleanup is not None: error.add_note(f"owner descriptor cleanup failed: {cleanup!r}")
            raise
    locked = False
    try:
        _flock(fd, deadline, message, poll_seconds); locked = True; _write_all(fd, raw, deadline); return fd
    except BaseException as error:
        cleanup = _unlock_close(fd, deadline) if locked else None
        if not locked:
            try: _close(fd)
            except BaseException as close_error: cleanup = close_error
        if cleanup is not None: error.add_note(f"lock acquisition cleanup failed: {cleanup!r}")
        raise

def _release(fd: int, deadline: float | None) -> BaseException | None:
    failures: list[BaseException] = []
    try: _write_all(fd, _owner_bytes(_RELEASED_PID, _RELEASED_TOKEN), deadline)
    except BaseException as error: failures.append(error)
    cleanup = _unlock_close(fd, deadline)
    if cleanup is not None: failures.append(cleanup)
    if not failures: return None
    first = failures[0]
    for extra in failures[1:]: first.add_note(f"additional lock release failure: {extra!r}")
    return first

@contextmanager
def owned_interprocess_lock(path: Path, *, timeout_seconds: float, timeout_message: str, poll_seconds: float = 0.02) -> Iterator[None]:
    deadline = monotonic() + max(0.0, float(timeout_seconds))
    if not _THREAD_LOCK.acquire(timeout=max(0.0, deadline - monotonic())): raise ValueError(timeout_message)
    fd = -1
    try:
        try: fd = _acquire(Path(path), _owner_bytes(os.getpid(), uuid4().hex), deadline, timeout_message, max(0.0, float(poll_seconds)))
        except _UnsafeLock as error: raise ValueError(timeout_message) from error
        body_error: BaseException | None = None
        try:
            try: yield
            except BaseException as error: body_error = error
        finally:
            try: release_error = _release(fd, deadline)
            except BaseException as error: release_error = error
            fd = -1
        if body_error is not None:
            if release_error is not None:
                body_error.add_note(f"lock release failed: {release_error!r}"); raise body_error from release_error
            raise body_error
        if release_error is not None:
            if isinstance(release_error, _UnsafeLock): raise ValueError(timeout_message) from release_error
            raise release_error
    finally:
        if fd >= 0:
            cleanup = _unlock_close(fd, deadline)
            if cleanup is not None: raise cleanup
        _THREAD_LOCK.release()
