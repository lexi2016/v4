"""Descriptor-relative filesystem operations with no-follow path traversal."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath

_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
_WRITE_NEW_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _path_parts(path: str | Path) -> tuple[str, ...]:
    raw = os.fspath(path)
    if any(part == os.pardir for part in raw.split(os.sep)):
        raise ValueError("PATH_TRAVERSAL_REJECTED")
    absolute = os.path.abspath(raw)
    if not os.path.isabs(absolute):
        raise ValueError("ABSOLUTE_PATH_REQUIRED")
    return tuple(part for part in absolute.split(os.sep) if part)


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise OSError("SHORT_WRITE")
        offset += written


def _relative_parts(relative: str) -> tuple[str, ...]:
    if not isinstance(relative, str) or not relative or relative.startswith("/") or "\\" in relative or "\x00" in relative:
        raise ValueError("RELATIVE_PATH_INVALID")
    parsed = PurePosixPath(relative)
    parts = parsed.parts
    if not parts or any(part in {"", ".", ".."} for part in parts) or parsed.is_absolute():
        raise ValueError("RELATIVE_PATH_INVALID")
    return parts


def _open_child_dir(parent_fd: int, name: str, *, create: bool, mode: int) -> int:
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(name, mode=mode, dir_fd=parent_fd)
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("PATH_COMPONENT_NOT_DIRECTORY")
    return fd


def open_absolute_dir(path: str | Path, *, create: bool = False, mode: int = 0o700) -> int:
    """Open every absolute path component through O_NOFOLLOW dir descriptors."""
    fd = os.open(os.sep, _DIR_FLAGS)
    try:
        for part in _path_parts(path):
            next_fd = _open_child_dir(fd, part, create=create, mode=mode)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_relative_dir(root_fd: int, relative: str, *, create: bool = False, mode: int = 0o700) -> int:
    parts = _relative_parts(relative)
    fd = os.dup(root_fd)
    try:
        for part in parts:
            next_fd = _open_child_dir(fd, part, create=create, mode=mode)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_relative_parent(root_fd: int, relative: str, *, create: bool = False, mode: int = 0o700) -> tuple[int, str]:
    parts = _relative_parts(relative)
    if len(parts) == 1:
        return os.dup(root_fd), parts[0]
    parent = "/".join(parts[:-1])
    return open_relative_dir(root_fd, parent, create=create, mode=mode), parts[-1]


def _read_fd(fd: int) -> bytes:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("REGULAR_FILE_REQUIRED")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    after = os.fstat(fd)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if identity_before != identity_after or total != before.st_size:
        raise ValueError("FILE_CHANGED_DURING_READ")
    return b"".join(chunks)


def read_relative_file(root: str | Path, relative: str) -> bytes:
    root_fd = open_absolute_dir(root)
    try:
        parent_fd, leaf = open_relative_parent(root_fd, relative)
        try:
            fd = os.open(leaf, _READ_FLAGS, dir_fd=parent_fd)
            try:
                return _read_fd(fd)
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)
    finally:
        os.close(root_fd)


def read_relative_file_at(root_fd: int, relative: str) -> bytes:
    parent_fd, leaf = open_relative_parent(root_fd, relative)
    try:
        fd = os.open(leaf, _READ_FLAGS, dir_fd=parent_fd)
        try:
            return _read_fd(fd)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def read_absolute_file(path: str | Path) -> bytes:
    absolute = Path(os.path.abspath(os.fspath(path)))
    parent_fd = open_absolute_dir(absolute.parent)
    try:
        fd = os.open(absolute.name, _READ_FLAGS, dir_fd=parent_fd)
        try:
            return _read_fd(fd)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def write_new_absolute_file(path: str | Path, data: bytes, *, mode: int = 0o600) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    parent_fd = open_absolute_dir(absolute.parent, create=True)
    try:
        fd = os.open(absolute.name, _WRITE_NEW_FLAGS, mode=mode, dir_fd=parent_fd)
        try:
            _write_all(fd, data)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                os.unlink(absolute.name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def write_new_relative_file(root_fd: int, relative: str, data: bytes, *, mode: int = 0o600) -> None:
    parent_fd, leaf = open_relative_parent(root_fd, relative, create=True)
    try:
        fd = os.open(leaf, _WRITE_NEW_FLAGS, mode=mode, dir_fd=parent_fd)
        try:
            _write_all(fd, data)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                os.unlink(leaf, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _hash_fd(fd: int) -> tuple[str, int]:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("REGULAR_FILE_REQUIRED")
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    after = os.fstat(fd)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if identity_before != identity_after or total != before.st_size:
        raise ValueError("FILE_CHANGED_DURING_READ")
    return digest.hexdigest(), total


def copy_verified_file(
    source_root: str | Path,
    relative: str,
    destination_root: str | Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
) -> dict[str, object]:
    """Copy one manifest-bound regular file without following any path component."""
    parts = _relative_parts(relative)
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha256):
        raise ValueError("EXPECTED_SHA256_INVALID")
    if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0:
        raise ValueError("EXPECTED_BYTES_INVALID")
    source_path = os.path.abspath(os.fspath(source_root))
    destination_path = os.path.abspath(os.fspath(destination_root))
    if os.path.commonpath((source_path, destination_path)) in (source_path, destination_path):
        raise ValueError("SOURCE_DESTINATION_ROOTS_OVERLAP")

    source_fd = open_absolute_dir(source_path)
    destination_fd = -1
    source_parent = -1
    destination_parent = -1
    source_file = -1
    destination_file = -1
    destination_created = False
    leaf = parts[-1]
    try:
        destination_fd = open_absolute_dir(destination_path, create=True)
        source_parent, _ = open_relative_parent(source_fd, relative)
        destination_parent, _ = open_relative_parent(destination_fd, relative, create=True)
        source_file = os.open(leaf, _READ_FLAGS, dir_fd=source_parent)
        source_before = os.fstat(source_file)
        if not stat.S_ISREG(source_before.st_mode):
            raise ValueError("SOURCE_REGULAR_FILE_REQUIRED")
        destination_file = os.open(leaf, _WRITE_NEW_FLAGS, mode=0o600, dir_fd=destination_parent)
        destination_created = True
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(source_file, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            _write_all(destination_file, chunk)
        source_after = os.fstat(source_file)
        source_identity_before = (source_before.st_dev, source_before.st_ino, source_before.st_size, source_before.st_mtime_ns, source_before.st_ctime_ns)
        source_identity_after = (source_after.st_dev, source_after.st_ino, source_after.st_size, source_after.st_mtime_ns, source_after.st_ctime_ns)
        observed_sha = digest.hexdigest()
        if source_identity_before != source_identity_after or total != expected_bytes or observed_sha != expected_sha256:
            raise ValueError("SOURCE_IDENTITY_MISMATCH")
        os.fsync(destination_file)
        os.close(destination_file)
        destination_file = -1
        verify_fd = os.open(leaf, _READ_FLAGS, dir_fd=destination_parent)
        try:
            copied_sha, copied_bytes = _hash_fd(verify_fd)
        finally:
            os.close(verify_fd)
        if copied_sha != expected_sha256 or copied_bytes != expected_bytes:
            raise ValueError("DESTINATION_IDENTITY_MISMATCH")
        os.fsync(destination_parent)
        return {"sha256": copied_sha, "bytes": copied_bytes}
    except BaseException:
        if destination_file >= 0:
            os.close(destination_file)
            destination_file = -1
        if destination_created and destination_parent >= 0:
            try:
                os.unlink(leaf, dir_fd=destination_parent)
                os.fsync(destination_parent)
            except FileNotFoundError:
                pass
        raise
    finally:
        for fd in (source_file, source_parent, destination_parent, destination_fd, source_fd):
            if fd >= 0:
                os.close(fd)
