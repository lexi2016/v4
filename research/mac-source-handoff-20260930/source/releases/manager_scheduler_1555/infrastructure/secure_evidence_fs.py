"""Fail-closed, descriptor-anchored reads for evidence files."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from dataclasses import dataclass
from typing import Any


_READ_CHUNK = 1024 * 1024
_TEMP_ATTEMPTS = 32
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}", re.ASCII)


@dataclass(frozen=True, slots=True)
class ReadBytesResult:
    data: bytes
    sha256: str
    size: int
    device: int
    inode: int


class SecureEvidenceError(ValueError):
    """Base error for the secure-evidence read boundary."""


class SecureEvidenceConflict(SecureEvidenceError):
    """Reserved for a caller-visible evidence conflict."""


class SecureEvidenceUnavailable(SecureEvidenceError):
    """Evidence could not be safely confirmed."""

    status = "CANNOT_CONFIRM"
    status_nf = status


class _MissingPath(Exception):
    """A descriptor-relative parent component does not exist."""


def _close_quietly(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _validate_relative(relative: Any) -> tuple[str, ...]:
    if not isinstance(relative, str) or not relative:
        raise SecureEvidenceError("relative path must be a non-empty string")
    if "\x00" in relative:
        raise SecureEvidenceError("relative path must not contain NUL")
    if "\\" in relative:
        raise SecureEvidenceError("relative path must use forward separators")
    if relative.startswith("/"):
        raise SecureEvidenceError("relative path must not be absolute")
    if len(relative) > 1 and relative[1] == ":":
        raise SecureEvidenceError("relative path must not contain a drive prefix")
    parts = tuple(relative.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise SecureEvidenceError("relative path contains an invalid component")
    return parts


def _require_flags() -> None:
    for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK"):
        value = getattr(os, name, None)
        if isinstance(value, bool) or not isinstance(value, int) or value == 0:
            raise SecureEvidenceUnavailable(f"required open flag {name} is unavailable")


class SecureEvidenceRoot:
    """Read regular files below one directory descriptor.

    No operation resolves or checks a path before opening it.  Every parent
    and the final entry is opened relative to an already-open descriptor.
    """

    def __init__(self, root: os.PathLike[str] | str, *, max_file_bytes: int) -> None:
        if isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int) or max_file_bytes < 0:
            raise SecureEvidenceError("max_file_bytes must be a nonnegative integer")
        try:
            root_name = os.fspath(root)
        except TypeError as error:
            raise SecureEvidenceError("root must be path-like") from error
        if not isinstance(root_name, (str, bytes)) or not root_name:
            raise SecureEvidenceError("root must be a non-empty path")
        _require_flags()

        root_fd: int | None = None
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            root_fd = os.open(root_name, flags)
            metadata = os.fstat(root_fd)
        except (OSError, TypeError) as error:
            _close_quietly(root_fd)
            raise SecureEvidenceUnavailable("evidence root cannot be securely opened") from error
        if not stat.S_ISDIR(metadata.st_mode):
            _close_quietly(root_fd)
            raise SecureEvidenceUnavailable("evidence root is not a directory")
        self.root = root_name
        self.max_file_bytes = max_file_bytes
        self._root_fd: int | None = root_fd

    def __enter__(self) -> "SecureEvidenceRoot":
        self._assert_open()
        return self

    def __exit__(self, _exc_type: Any, _exc_value: Any, _traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        root_fd = self._root_fd
        self._root_fd = None
        _close_quietly(root_fd)

    def _assert_open(self) -> int:
        root_fd = self._root_fd
        if root_fd is None:
            raise SecureEvidenceUnavailable("evidence root is closed")
        return root_fd

    @staticmethod
    def _directory_flags() -> int:
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    @staticmethod
    def _final_flags() -> int:
        return os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC

    @staticmethod
    def _temp_flags() -> int:
        return os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC

    @staticmethod
    def _fsync_directory(fd: int) -> None:
        try:
            os.fsync(fd)
        except (OSError, TypeError) as error:
            raise SecureEvidenceUnavailable("evidence directory cannot be fsynced") from error

    def _open_parent(self, parts: tuple[str, ...], *, create: bool = False) -> int:
        root_fd = self._assert_open()
        current_fd = root_fd
        try:
            for component in parts[:-1]:
                try:
                    child_fd = os.open(component, self._directory_flags(), dir_fd=current_fd)
                except FileNotFoundError as error:
                    if not create:
                        raise _MissingPath from error
                    try:
                        os.mkdir(component, 0o700, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    except (OSError, TypeError) as mkdir_error:
                        raise SecureEvidenceUnavailable("evidence parent cannot be created") from mkdir_error
                    else:
                        self._fsync_directory(current_fd)
                    try:
                        child_fd = os.open(component, self._directory_flags(), dir_fd=current_fd)
                    except (OSError, TypeError) as reopen_error:
                        raise SecureEvidenceUnavailable("evidence parent cannot be securely reopened") from reopen_error
                except (OSError, TypeError) as error:
                    raise SecureEvidenceUnavailable("evidence parent cannot be securely opened") from error
                if current_fd != root_fd:
                    _close_quietly(current_fd)
                current_fd = child_fd
            return current_fd
        except BaseException:
            if current_fd != root_fd:
                _close_quietly(current_fd)
            raise

    @staticmethod
    def _validate_bytes(data: Any, max_file_bytes: int) -> bytes:
        if not isinstance(data, bytes):
            raise SecureEvidenceError("evidence payload must be bytes")
        if len(data) > max_file_bytes:
            raise SecureEvidenceError("evidence payload exceeds max_file_bytes")
        return data

    @staticmethod
    def _validate_expected(expected: Any) -> str | None:
        if expected is None:
            return None
        if not isinstance(expected, str) or _SHA256_RE.fullmatch(expected) is None:
            raise SecureEvidenceError("expected current SHA-256 must be None or 64 hex characters")
        return expected.lower()

    def _read_fd(self, fd: int) -> ReadBytesResult:
        try:
            before = os.fstat(fd)
        except OSError as error:
            raise SecureEvidenceUnavailable("evidence metadata cannot be read") from error
        if not stat.S_ISREG(before.st_mode):
            raise SecureEvidenceUnavailable("evidence target is not a regular file")
        if before.st_nlink != 1:
            raise SecureEvidenceUnavailable("evidence target must have exactly one link")
        if before.st_size < 0 or before.st_size > self.max_file_bytes:
            raise SecureEvidenceUnavailable("evidence target exceeds max_file_bytes")

        data = bytearray()
        while len(data) <= self.max_file_bytes:
            count = min(_READ_CHUNK, self.max_file_bytes + 1 - len(data))
            try:
                chunk = os.read(fd, count)
            except InterruptedError:
                continue
            except OSError as error:
                raise SecureEvidenceUnavailable("evidence bytes cannot be read") from error
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > self.max_file_bytes:
                raise SecureEvidenceUnavailable("evidence target grew beyond max_file_bytes")

        try:
            after = os.fstat(fd)
        except OSError as error:
            raise SecureEvidenceUnavailable("evidence metadata cannot be reread") from error
        if not stat.S_ISREG(after.st_mode) or after.st_nlink != 1:
            raise SecureEvidenceUnavailable("evidence target changed to an unsafe link state")
        if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            raise SecureEvidenceUnavailable("evidence descriptor identity changed")
        if after.st_size != before.st_size or after.st_size != len(data):
            raise SecureEvidenceUnavailable("evidence target size changed during read")
        raw = bytes(data)
        return ReadBytesResult(raw, hashlib.sha256(raw).hexdigest(), len(raw), int(after.st_dev), int(after.st_ino))

    def _open_final(self, parent_fd: int, name: str) -> int | None:
        try:
            return os.open(name, self._final_flags(), dir_fd=parent_fd)
        except FileNotFoundError:
            return None
        except (OSError, TypeError) as error:
            raise SecureEvidenceUnavailable("evidence target cannot be securely opened") from error

    def _read_from_parent(self, parent_fd: int, name: str) -> ReadBytesResult | None:
        final_fd = self._open_final(parent_fd, name)
        if final_fd is None:
            return None
        try:
            return self._read_fd(final_fd)
        finally:
            _close_quietly(final_fd)

    def _read_current(self, parts: tuple[str, ...]) -> tuple[ReadBytesResult | None, bool]:
        try:
            parent_fd = self._open_parent(parts)
        except _MissingPath:
            return None, True
        root_fd = self._assert_open()
        try:
            return self._read_from_parent(parent_fd, parts[-1]), False
        finally:
            if parent_fd != root_fd:
                _close_quietly(parent_fd)

    def read_regular_bytes(self, relative: str) -> ReadBytesResult:
        self._assert_open()
        parts = _validate_relative(relative)
        result, _parent_missing = self._read_current(parts)
        if result is None:
            raise SecureEvidenceUnavailable("evidence target is absent")
        return result

    def _write_temp(self, parent_fd: int, final_name: str, data: bytes) -> tuple[str, tuple[int, int]]:
        temp_name: str | None = None
        temp_fd: int | None = None
        try:
            for _attempt in range(_TEMP_ATTEMPTS):
                candidate = f".{final_name}.{secrets.token_hex(16)}.tmp"
                try:
                    temp_fd = os.open(candidate, self._temp_flags(), 0o600, dir_fd=parent_fd)
                except FileExistsError:
                    continue
                except (OSError, TypeError) as error:
                    raise SecureEvidenceUnavailable("temporary evidence file cannot be created") from error
                temp_name = candidate
                break
            if temp_fd is None or temp_name is None:
                raise SecureEvidenceUnavailable("temporary evidence name collision")

            view = memoryview(data)
            offset = 0
            while offset < len(view):
                try:
                    written = os.write(temp_fd, view[offset:])
                except InterruptedError:
                    continue
                except (OSError, TypeError) as error:
                    raise SecureEvidenceUnavailable("temporary evidence file cannot be written") from error
                if not isinstance(written, int) or written <= 0 or written > len(view) - offset:
                    raise SecureEvidenceUnavailable("temporary evidence file made invalid write progress")
                offset += written
            try:
                os.fsync(temp_fd)
                metadata = os.fstat(temp_fd)
            except (OSError, TypeError) as error:
                raise SecureEvidenceUnavailable("temporary evidence file cannot be fsynced") from error
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size != len(data):
                raise SecureEvidenceUnavailable("temporary evidence file failed attestation")
            _close_quietly(temp_fd)
            temp_fd = None
            return temp_name, (int(metadata.st_dev), int(metadata.st_ino))
        except BaseException:
            _close_quietly(temp_fd)
            if temp_name is not None:
                self._cleanup_temp(parent_fd, temp_name)
            raise

    @staticmethod
    def _cleanup_temp(parent_fd: int, temp_name: str) -> None:
        try:
            os.unlink(temp_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        except (OSError, TypeError):
            pass

    def _unlink_temp(self, parent_fd: int, temp_name: str, *, fsync: bool) -> None:
        try:
            os.unlink(temp_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        except (OSError, TypeError) as error:
            raise SecureEvidenceUnavailable("temporary evidence file cannot be removed") from error
        if fsync:
            self._fsync_directory(parent_fd)

    def create_immutable_bytes(self, relative: str, data: bytes) -> str:
        """Publish one immutable byte payload and return its raw SHA-256.

        If the link publication succeeds but directory durability or secure
        post-publication verification fails, the target may already be
        changed.  This method does not promise rollback; callers must treat
        ``CANNOT_CONFIRM`` as requiring a safe reread or recovery.
        """
        parts = _validate_relative(relative)
        payload = self._validate_bytes(data, self.max_file_bytes)
        self._assert_open()
        parent_fd = self._open_parent(parts, create=True)
        root_fd = self._assert_open()
        temp_name: str | None = None
        try:
            temp_name, temp_identity = self._write_temp(parent_fd, parts[-1], payload)
            try:
                os.link(
                    temp_name,
                    parts[-1],
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                self._unlink_temp(parent_fd, temp_name, fsync=True)
                temp_name = None
                existing = self._read_from_parent(parent_fd, parts[-1])
                if existing is None:
                    raise SecureEvidenceUnavailable("immutable evidence target disappeared")
                if existing.data != payload:
                    raise SecureEvidenceConflict("immutable evidence bytes conflict")
                return existing.sha256
            except (OSError, TypeError) as error:
                raise SecureEvidenceUnavailable("immutable evidence target cannot be linked") from error

            self._unlink_temp(parent_fd, temp_name, fsync=True)
            temp_name = None
            published = self._read_from_parent(parent_fd, parts[-1])
            if published is None or published.data != payload or (published.device, published.inode) != temp_identity:
                raise SecureEvidenceUnavailable("published immutable evidence failed verification")
            return published.sha256
        finally:
            if temp_name is not None:
                self._cleanup_temp(parent_fd, temp_name)
            if parent_fd != root_fd:
                _close_quietly(parent_fd)

    def replace_current_cas(
        self,
        relative: str,
        *,
        expected_current_bytes_sha256: str | None,
        new_bytes: bytes,
    ) -> str:
        """Replace current bytes under a caller-held existing interprocess lock.

        This method does not acquire a lock.  The caller must hold the
        repository's existing interprocess lock for the complete operation.
        If ``os.replace`` succeeds but directory durability or secure
        post-replacement verification fails, the target may already be
        changed.  This method does not promise rollback; callers must treat
        ``CANNOT_CONFIRM`` as requiring a safe reread or recovery.
        """
        parts = _validate_relative(relative)
        expected = self._validate_expected(expected_current_bytes_sha256)
        payload = self._validate_bytes(new_bytes, self.max_file_bytes)
        self._assert_open()

        current, parent_missing = self._read_current(parts)
        if expected is None:
            if current is not None:
                raise SecureEvidenceConflict("expected current evidence to be absent")
        else:
            if current is None:
                raise SecureEvidenceConflict("expected current evidence is absent")
            if current.sha256 != expected:
                raise SecureEvidenceConflict("current evidence SHA-256 is stale")
            if current.data == payload:
                return current.sha256

        if parent_missing:
            parent_fd = self._open_parent(parts, create=True)
        else:
            parent_fd = self._open_parent(parts)
        root_fd = self._assert_open()
        temp_name: str | None = None
        try:
            latest = self._read_from_parent(parent_fd, parts[-1])
            if expected is None:
                if latest is not None:
                    raise SecureEvidenceConflict("current evidence appeared before CAS replace")
            else:
                if latest is None:
                    raise SecureEvidenceConflict("current evidence disappeared before CAS replace")
                if current is None or latest.sha256 != expected or (latest.device, latest.inode) != (current.device, current.inode):
                    raise SecureEvidenceConflict("current evidence changed before CAS replace")
                if latest.data == payload:
                    return latest.sha256

            temp_name, temp_identity = self._write_temp(parent_fd, parts[-1], payload)
            try:
                os.replace(temp_name, parts[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            except (OSError, TypeError) as error:
                raise SecureEvidenceUnavailable("current evidence cannot be replaced securely") from error
            temp_name = None
            self._fsync_directory(parent_fd)
            replaced = self._read_from_parent(parent_fd, parts[-1])
            if replaced is None or replaced.data != payload or (replaced.device, replaced.inode) != temp_identity:
                raise SecureEvidenceUnavailable("replaced evidence failed verification")
            return replaced.sha256
        finally:
            if temp_name is not None:
                self._cleanup_temp(parent_fd, temp_name)
            if parent_fd != root_fd:
                _close_quietly(parent_fd)
