"""Small POSIX dir-fd I/O boundary shared by research stores.

Every ancestry component is opened with O_NOFOLLOW; publication uses the same
parent descriptor for creation, rename and directory fsync. No resolve/check-
then-open path is used. Unsupported platforms fail closed rather than silently
falling back to weaker path checks. Intended for a private local state root.
"""
from __future__ import annotations
from contextlib import contextmanager, suppress
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import time
from typing import Iterator
from uuid import uuid4


class OwnedIOError(ValueError):
    pass


class LockAcquireTimeout(TimeoutError):
    """Only raised while acquiring the persistent kernel lock."""


class SafeRoot:
    def __init__(self, root: Path | str):
        self.root = Path(os.path.abspath(Path(root).expanduser()))
        self._identity: tuple[int, int] | None = None

    @staticmethod
    def _open_visible(pathname, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        """os.open with a bounded retry for macOS dir-entry visibility lag.

        On macOS a freshly created directory entry can transiently report
        ENOENT to an adjacent openat despite a live parent descriptor.  Only
        FileNotFoundError is retried (a few milliseconds); every other
        failure propagates unchanged.
        """

        attempts = 25
        for attempt in range(attempts):
            try:
                return os.open(pathname, flags, mode, dir_fd=dir_fd)
            except FileNotFoundError:
                if attempt + 1 >= attempts:
                    raise
                time.sleep(0.004)
        raise AssertionError("unreachable")

    @staticmethod
    def _parts(relative: str) -> tuple[str, ...]:
        if not isinstance(relative, str) or not relative or '\\' in relative or '\x00' in relative:
            raise OwnedIOError('OWNED_PATH_UNSAFE')
        p = PurePosixPath(relative)
        windows = PureWindowsPath(relative)
        if p.is_absolute() or windows.drive or windows.root or '..' in p.parts or not p.parts:
            raise OwnedIOError('OWNED_PATH_UNSAFE')
        return p.parts

    @contextmanager
    def directory(self, relative: str | None = None, *, create: bool = False) -> Iterator[int]:
        if os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW'):
            raise OwnedIOError('OWNED_IO_PLATFORM_UNSUPPORTED')
        parts = list(self.root.parts[1:])
        root_depth = len(parts)
        if relative is not None:
            parts.extend(self._parts(relative))
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for i, part in enumerate(parts, 1):
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                    child = self._open_visible(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                else:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
                if i == root_depth:
                    meta = os.fstat(fd)
                    identity = (meta.st_dev, meta.st_ino)
                    if self._identity is not None and identity != self._identity:
                        raise OwnedIOError('OWNED_ROOT_REPLACED')
                    self._identity = identity
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def parent(self, relative: str, *, create: bool = False) -> Iterator[tuple[int, str]]:
        parts = self._parts(relative)
        with self.directory('/'.join(parts[:-1]) if len(parts) > 1 else None, create=create) as fd:
            yield fd, parts[-1]

    def ensure_directory(self, relative: str | None = None) -> None:
        with self.directory(relative, create=True):
            pass

    def read_bytes(self, relative: str, *, max_bytes: int = 64 * 1024 * 1024) -> bytes:
        with self.parent(relative) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                meta = os.fstat(fd)
                if not stat.S_ISREG(meta.st_mode):
                    raise OwnedIOError('OWNED_FILE_NOT_REGULAR')
                if meta.st_size > max_bytes:
                    raise OwnedIOError('OWNED_FILE_TOO_LARGE')
                with os.fdopen(fd, 'rb', closefd=False) as handle:
                    raw = handle.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise OwnedIOError('OWNED_FILE_TOO_LARGE')
                return raw
            finally:
                os.close(fd)

    def write_bytes(self, relative: str, raw: bytes, *, require_absent: bool = False) -> None:
        with self.parent(relative, create=True) as (parent, name):
            try:
                meta = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                meta = None
            if meta is not None and not stat.S_ISREG(meta.st_mode):
                raise OwnedIOError('OWNED_DESTINATION_UNSAFE')
            temp = f'.{name}.{uuid4().hex}.tmp'
            fd = self._open_visible(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                if require_absent:
                    # Atomic no-replace publication, with no empty-owner window.
                    # ENOENT here is the same macOS visibility lag: retry briefly.
                    for attempt in range(25):
                        try:
                            os.link(temp, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                            break
                        except FileNotFoundError:
                            if attempt + 1 >= 25:
                                raise
                            time.sleep(0.004)
                    os.unlink(temp, dir_fd=parent)
                else:
                    os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temp, dir_fd=parent)

    def unlink_if_same(self, relative: str, expected: bytes) -> bool:
        # Callers serialize mutations with kernel_lock; never a standalone CAS.
        with self.parent(relative) as (parent, name):
            try:
                if self.read_bytes(relative) != expected:
                    return False
                os.unlink(name, dir_fd=parent)
                os.fsync(parent)
                return True
            except FileNotFoundError:
                return False

    def files(self, relative: str | None = None, *, suffix: str = '.json') -> list[str]:
        try:
            with self.directory(relative) as fd:
                result = []
                for name in os.listdir(fd):
                    if not name.endswith(suffix):
                        continue
                    meta = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if not stat.S_ISREG(meta.st_mode):
                        raise OwnedIOError('OWNED_FILE_NOT_REGULAR')
                    result.append(name)
                return sorted(result)
        except FileNotFoundError:
            return []

    @contextmanager
    def kernel_lock(self, relative: str, *, timeout: float = 10.0, poll: float = 0.02) -> Iterator[int]:
        if not math.isfinite(timeout) or timeout < 0 or not math.isfinite(poll) or poll <= 0:
            raise OwnedIOError('INVALID_LOCK_BUDGET')
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise OwnedIOError("OWNED_IO_PLATFORM_UNSUPPORTED")
        import fcntl
        with self.parent(relative, create=True) as (parent, name):
            fd = self._open_visible(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise OwnedIOError('LOCK_FILE_NOT_REGULAR')
                deadline = time.monotonic() + timeout
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise LockAcquireTimeout('OWNED_LOCK_TIMEOUT')
                        time.sleep(min(poll, remaining))
                try:
                    # Existing callers may ignore this; leased owners bind the
                    # descriptor actually holding flock, not a guessed inode.
                    yield fd
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                # Keep the inode: unlinking a kernel lock would split contenders.
                os.close(fd)
