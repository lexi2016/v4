"""Safe local persistence for runtime graph snapshots and transition history."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import GraphStatus


_DATE_RE = re.compile(r"^\d{8}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_SCHEMA = "v3_runtime_snapshot.v1"
_EVENT_COLUMNS = (
    "id",
    "business_date",
    "topology_version_sha",
    "node_id",
    "status",
    "reason",
    "observed_at",
)
_SQLITE_SHARED_FIRST = 0x40000002
_MAX_EVENT_SQLITE_LENGTH_BYTES = 2 * 1024 * 1024
_MAX_EVENT_REASON_BYTES = 16 * 1024
_MAX_EVENT_RAW_BYTES = 768 * 1024
_MAX_EVENT_JSON_BYTES = (1024 * 1024) - 1024
_EVENT_TEXT_BYTE_LIMITS = (8, 64, 256, 32, _MAX_EVENT_REASON_BYTES, 64)


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(str(path)))


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((os.path.normcase(str(path)), os.path.normcase(str(root)))) == os.path.normcase(str(root))
    except ValueError:
        return False


def _reparse(metadata: os.stat_result) -> bool:
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400))


def _assert_safe_path(path: Path, root: Path) -> None:
    destination, allowed = _absolute(path), _absolute(root)
    if not _within(destination, allowed):
        raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
    try:
        relative = destination.relative_to(allowed)
    except ValueError as exc:
        raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
    current = allowed
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
        if _reparse(metadata):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")


def _file_identity(metadata: os.stat_result) -> tuple[int, int]:
    return (int(metadata.st_dev), int(metadata.st_ino))


def _path_matches_identity(path: Path, identity: tuple[int, int]) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    try:
        return not _reparse(metadata) and _file_identity(metadata) == identity
    except AttributeError:
        return False


def _posix_open_directory_ancestry(root: Path, parent: Path, error: str) -> list[int]:
    """Open every directory in an allowlisted ancestry without following links."""
    root, parent = _absolute(root), _absolute(parent)
    if not _within(parent, root):
        raise ValueError(error)
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise ValueError(error) from exc

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    handles: list[int] = []
    paths = [root]
    current = root
    for part in relative.parts:
        current = current / part
        paths.append(current)
    current_fd: int | None = None
    try:
        for index, path in enumerate(paths):
            metadata = os.lstat(path)
            if _reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise ValueError(error)
            if index == 0:
                descriptor = os.open(str(path), flags)
            else:
                descriptor = os.open(path.name, flags, dir_fd=current_fd)
            opened = os.fstat(descriptor)
            if (
                _reparse(opened)
                or not stat.S_ISDIR(opened.st_mode)
                or _file_identity(metadata) != _file_identity(opened)
            ):
                os.close(descriptor)
                raise ValueError(error)
            handles.append(descriptor)
            current_fd = descriptor
        return handles
    except Exception:
        for descriptor in reversed(handles):
            with suppress(OSError):
                os.close(descriptor)
        raise


def _posix_close_directory_ancestry(handles: list[int]) -> None:
    for descriptor in reversed(handles):
        with suppress(OSError):
            os.close(descriptor)


class AtomicSnapshotStore:
    _locks: dict[str, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, path: Path, *, allowed_root: Path, expected_schema: str = _SNAPSHOT_SCHEMA) -> None:
        self.path = Path(path)
        self.allowed_root = Path(allowed_root)
        if not isinstance(expected_schema, str) or not expected_schema:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_SCHEMA_INVALID")
        self.expected_schema = expected_schema

    @staticmethod
    def _is_windows() -> bool:
        return os.name == "nt"

    def _new_temp_path(self) -> Path:
        return self.path.parent / f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"

    @staticmethod
    def _close_native_handle(native: int) -> None:
        import ctypes

        if not ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(native):
            raise OSError(ctypes.get_last_error(), "CloseHandle failed")

    @staticmethod
    def _open_directory_handle(path: Path) -> int:
        import ctypes
        from ctypes import wintypes

        create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        native = create_file(
            str(path), 0x00000020 | 0x00000080 | 0x00100000,
            0x00000001, None, 3, 0x02000000, None,
        )
        if native == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "CreateFileW directory failed", str(path))
        return native

    @staticmethod
    def _directory_final_path(native: int) -> str:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_final = kernel32.GetFinalPathNameByHandleW
        get_final.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
        get_final.restype = wintypes.DWORD
        size = get_final(native, None, 0, 0)
        if not size:
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
        buffer = ctypes.create_unicode_buffer(size + 1)
        result = get_final(native, buffer, len(buffer), 0)
        if not result or result >= len(buffer):
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return os.path.normcase(os.path.normpath(value))

    @staticmethod
    def _validate_directory_handle(native: int, expected: Path) -> None:
        import ctypes
        from ctypes import wintypes

        class FileAttributeTagInfo(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD)]

        info = FileAttributeTagInfo()
        get_info = ctypes.WinDLL("kernel32", use_last_error=True).GetFileInformationByHandleEx
        get_info.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD)
        get_info.restype = wintypes.BOOL
        if not get_info(native, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "GetFileInformationByHandleEx failed", str(expected))
        if info.attributes & 0x0400:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        if AtomicSnapshotStore._directory_final_path(native) != os.path.normcase(os.path.normpath(str(_absolute(expected)))):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")

    def _lock_publication_ancestry(self, temp: Path) -> list[int]:
        if not self._is_windows():
            return _posix_open_directory_ancestry(
                self.allowed_root,
                temp.parent,
                "RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE",
            )
        root, parent = _absolute(self.allowed_root), _absolute(temp.parent)
        if not _within(parent, root):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        try:
            relative = parent.relative_to(root)
        except ValueError as exc:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
        paths = [root]
        current = root
        for part in relative.parts:
            current /= part
            paths.append(current)
        handles: list[int] = []
        try:
            for path in paths:
                native = self._open_directory_handle(path)
                try:
                    self._validate_directory_handle(native, path)
                except Exception:
                    with suppress(OSError):
                        self._close_native_handle(native)
                    raise
                handles.append(native)
            return handles
        except Exception:
            for native in reversed(handles):
                with suppress(OSError):
                    self._close_native_handle(native)
            raise

    @staticmethod
    def _open_temp_posix(temp: Path, parent_handle: int) -> Any:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temp.name, flags, 0o600, dir_fd=parent_handle)
        try:
            metadata = os.fstat(descriptor)
            if (
                _reparse(metadata)
                or not stat.S_ISREG(metadata.st_mode)
                or int(getattr(metadata, "st_nlink", 1)) != 1
            ):
                raise ValueError("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
            return os.fdopen(descriptor, "r+b")
        except Exception:
            with suppress(OSError):
                os.unlink(temp.name, dir_fd=parent_handle)
            with suppress(OSError):
                os.close(descriptor)
            raise

    def _publish_handle_posix(
        self,
        handle: Any,
        temp: Path,
        identity: tuple[int, int],
        expected: bytes,
        parent_handle: int,
    ) -> None:
        metadata = os.fstat(handle.fileno())
        if (
            _reparse(metadata)
            or not stat.S_ISREG(metadata.st_mode)
            or int(getattr(metadata, "st_nlink", 1)) != 1
            or _file_identity(metadata) != identity
        ):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
        self._verify_handle(handle, expected)
        _assert_safe_path(self.path, self.allowed_root)
        if _absolute(temp.parent) != _absolute(self.path.parent):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        try:
            existing = os.lstat(self.path)
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            _reparse(existing)
            or not stat.S_ISREG(existing.st_mode)
            or int(getattr(existing, "st_nlink", 1)) != 1
        ):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
        os.replace(temp.name, self.path.name, src_dir_fd=parent_handle, dst_dir_fd=parent_handle)
        _assert_safe_path(self.path, self.allowed_root)
        target = os.lstat(self.path)
        if (
            _reparse(target)
            or not stat.S_ISREG(target.st_mode)
            or int(getattr(target, "st_nlink", 1)) != 1
            or _file_identity(target) != identity
        ):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")

    def _publish_handle_no_replace_posix(
        self,
        handle: Any,
        temp: Path,
        identity: tuple[int, int],
        expected: bytes,
        parent_handle: int,
    ) -> None:
        metadata = os.fstat(handle.fileno())
        if (
            _reparse(metadata)
            or not stat.S_ISREG(metadata.st_mode)
            or int(getattr(metadata, "st_nlink", 1)) != 1
            or _file_identity(metadata) != identity
        ):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
        self._verify_handle(handle, expected)
        _assert_safe_path(self.path, self.allowed_root)
        if _absolute(temp.parent) != _absolute(self.path.parent):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        os.link(
            temp.name,
            self.path.name,
            src_dir_fd=parent_handle,
            dst_dir_fd=parent_handle,
            follow_symlinks=False,
        )
        os.unlink(temp.name, dir_fd=parent_handle)
        _assert_safe_path(self.path, self.allowed_root)
        target = os.lstat(self.path)
        if (
            _reparse(target)
            or not stat.S_ISREG(target.st_mode)
            or int(getattr(target, "st_nlink", 1)) != 1
            or _file_identity(target) != identity
        ):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")

    @staticmethod
    def _open_temp(temp: Path) -> Any:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        class IoStatusBlock(ctypes.Structure):
            _fields_ = [("status", wintypes.LONG), ("information", ctypes.c_size_t)]

        create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        native = create_file(
            str(temp),
            0x80000000 | 0x40000000 | 0x00010000,
            0x00000001 | 0x00000004,
            None,
            1,
            0x00000080,
            None,
        )
        if native == wintypes.HANDLE(-1).value:
            error = ctypes.get_last_error()
            if error == 80:
                raise FileExistsError(error, "CreateFileW failed", str(temp))
            raise OSError(error, "CreateFileW failed", str(temp))
        try:
            descriptor = msvcrt.open_osfhandle(native, os.O_RDWR | getattr(os, "O_BINARY", 0))
        except Exception:
            try:
                AtomicSnapshotStore._mark_native_handle_delete(native)
            finally:
                ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(native)
            raise
        try:
            return os.fdopen(descriptor, "r+b")
        except Exception:
            try:
                AtomicSnapshotStore._mark_native_handle_delete(native)
            finally:
                os.close(descriptor)
            raise

    @staticmethod
    def _mark_native_handle_delete(native: int) -> None:
        import ctypes
        from ctypes import wintypes

        disposition = ctypes.c_ubyte(1)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        set_info = kernel32.SetFileInformationByHandle
        set_info.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD)
        set_info.restype = wintypes.BOOL
        if not set_info(native, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            raise OSError(ctypes.get_last_error(), "SetFileInformationByHandle delete failed")

    @staticmethod
    def _mark_handle_delete(handle: Any) -> None:
        import msvcrt

        AtomicSnapshotStore._mark_native_handle_delete(msvcrt.get_osfhandle(handle.fileno()))

    @staticmethod
    def _close_handle(handle: Any) -> None:
        handle.close()

    def _verify_temp(self, path: Path) -> None:
        """Post-handle-verification hook retained for local fault injection tests."""
        del path

    def _verify_handle(self, handle: Any, expected: bytes) -> None:
        try:
            handle.seek(0)
            actual = handle.read()
            value = json.loads(actual.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_VERIFY_FAILED") from exc
        if actual != expected or not isinstance(value, Mapping) or value.get("schema_version") != self.expected_schema:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_VERIFY_FAILED")

    @staticmethod
    def _rename_open_file_on_windows(handle: Any, target: Path, *, replace_if_exists: bool = True) -> None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        class IoStatusBlock(ctypes.Structure):
            _fields_ = [
                ("status", wintypes.LONG),
                ("information", ctypes.c_size_t),
            ]

        class FileRenameInformation(ctypes.Structure):
            _fields_ = [
                ("replace_if_exists", ctypes.c_ubyte),
                ("root_directory", wintypes.HANDLE),
                ("file_name_length", wintypes.DWORD),
                ("file_name", wintypes.WCHAR * 1),
            ]

        name = target.name
        if not name or name != Path(name).name:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        encoded = name.encode("utf-16-le")
        offset = FileRenameInformation.file_name.offset
        buffer = ctypes.create_string_buffer(offset + len(encoded))
        info = ctypes.cast(buffer, ctypes.POINTER(FileRenameInformation)).contents
        info.replace_if_exists = replace_if_exists
        # A simple name keeps the rename in the source file's already-bound
        # directory; supplying that same directory as RootDirectory makes the
        # kernel reopen it for write and conflicts with our containment share.
        info.root_directory = None
        info.file_name_length = len(encoded)
        ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
        status_block = IoStatusBlock()
        ntdll = ctypes.WinDLL("ntdll")
        rename = ntdll.NtSetInformationFile
        rename.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(IoStatusBlock),
            wintypes.LPVOID,
            wintypes.ULONG,
            wintypes.ULONG,
        )
        rename.restype = wintypes.LONG
        status = rename(
            msvcrt.get_osfhandle(handle.fileno()),
            ctypes.byref(status_block),
            buffer,
            len(buffer),
            10,
        )
        if status:
            to_dos_error = ntdll.RtlNtStatusToDosError
            to_dos_error.argtypes = (wintypes.LONG,)
            to_dos_error.restype = wintypes.ULONG
            error = to_dos_error(status)
            if not replace_if_exists and error in {80, 183}:
                raise FileExistsError(error, "NtSetInformationFile target exists", name)
            raise OSError(error, "NtSetInformationFile failed", name)

    def _publish_handle(
        self,
        handle: Any,
        temp: Path,
        identity: tuple[int, int],
        expected: bytes,
        parent_handle: int,
    ) -> None:
        if not self._is_windows():
            self._publish_handle_posix(handle, temp, identity, expected, parent_handle)
            return
        if _file_identity(os.fstat(handle.fileno())) != identity:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
        self._verify_handle(handle, expected)
        _assert_safe_path(self.path, self.allowed_root)
        if not self._is_windows():
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PLATFORM_UNSUPPORTED")
        if _absolute(temp.parent) != _absolute(self.path.parent):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        self._validate_directory_handle(parent_handle, _absolute(self.path.parent))
        self._rename_open_file_on_windows(handle, self.path)

    def _publish_handle_no_replace(
        self,
        handle: Any,
        temp: Path,
        identity: tuple[int, int],
        expected: bytes,
        parent_handle: int,
    ) -> None:
        if not self._is_windows():
            self._publish_handle_no_replace_posix(handle, temp, identity, expected, parent_handle)
            return
        if _file_identity(os.fstat(handle.fileno())) != identity:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
        self._verify_handle(handle, expected)
        _assert_safe_path(self.path, self.allowed_root)
        if not self._is_windows() or _absolute(temp.parent) != _absolute(self.path.parent):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        self._validate_directory_handle(parent_handle, _absolute(self.path.parent))
        self._rename_open_file_on_windows(handle, self.path, replace_if_exists=False)
        _assert_safe_path(self.path, self.allowed_root)
        metadata = os.lstat(self.path)
        if (
            _reparse(metadata)
            or not stat.S_ISREG(metadata.st_mode)
            or int(getattr(metadata, "st_nlink", 1)) != 1
            or _file_identity(metadata) != identity
        ):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")

    def _lock(self) -> threading.Lock:
        key = os.path.normcase(str(_absolute(self.path)))
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def write(self, payload: Mapping[str, Any], *, require_absent: bool = False) -> None:
        with self._lock():
            self._write(payload, require_absent=require_absent)

    def _write(self, payload: Mapping[str, Any], *, require_absent: bool = False) -> None:
        _assert_safe_path(self.path, self.allowed_root)
        if not isinstance(payload, Mapping) or payload.get("schema_version") != self.expected_schema:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_SCHEMA_INVALID")
        try:
            serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            roundtrip = json.loads(serialized)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_SERIALIZE_FAILED") from exc
        if not isinstance(roundtrip, Mapping) or roundtrip.get("schema_version") != self.expected_schema:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_SCHEMA_INVALID")
        if not self._is_windows():
            self._write_posix(serialized, require_absent=require_absent)
            return
        temp = self._new_temp_path()
        _assert_safe_path(temp, self.allowed_root)
        temp_owned = False
        handle = None
        identity: tuple[int, int] | None = None
        published = False
        ancestry: list[int] = []
        try:
            ancestry = self._lock_publication_ancestry(temp)
            handle = self._open_temp(temp)
            temp_owned = True
            identity = _file_identity(os.fstat(handle.fileno()))
            payload_bytes = serialized.encode("utf-8")
            handle.write(payload_bytes)
            handle.flush()
            os.fsync(handle.fileno())
            self._verify_handle(handle, payload_bytes)
            self._verify_temp(temp)
            _assert_safe_path(temp, self.allowed_root)
            if require_absent:
                self._publish_handle_no_replace(handle, temp, identity, payload_bytes, ancestry[-1])
            else:
                self._publish_handle(handle, temp, identity, payload_bytes, ancestry[-1])
            temp_owned = False
            published = True
            self._fsync_directory()
        finally:
            if handle is not None:
                try:
                    if temp_owned and not published:
                        self._mark_handle_delete(handle)
                finally:
                    self._close_handle(handle)
            for native in reversed(ancestry):
                with suppress(OSError):
                    self._close_native_handle(native)

    def _write_posix(self, serialized: str, *, require_absent: bool) -> None:
        temp = self._new_temp_path()
        _assert_safe_path(temp, self.allowed_root)
        temp_owned = False
        handle = None
        published = False
        ancestry: list[int] = []
        try:
            ancestry = self._lock_publication_ancestry(temp)
            handle = self._open_temp_posix(temp, ancestry[-1])
            temp_owned = True
            identity = _file_identity(os.fstat(handle.fileno()))
            payload_bytes = serialized.encode("utf-8")
            handle.write(payload_bytes)
            handle.flush()
            os.fsync(handle.fileno())
            self._verify_handle(handle, payload_bytes)
            self._verify_temp(temp)
            _assert_safe_path(temp, self.allowed_root)
            if require_absent:
                self._publish_handle_no_replace(handle, temp, identity, payload_bytes, ancestry[-1])
            else:
                self._publish_handle(handle, temp, identity, payload_bytes, ancestry[-1])
            temp_owned = False
            published = True
            os.fsync(ancestry[-1])
        finally:
            if handle is not None:
                if temp_owned and not published:
                    with suppress(OSError):
                        os.unlink(temp.name, dir_fd=ancestry[-1])
                self._close_handle(handle)
            _posix_close_directory_ancestry(ancestry)

    def _fsync_directory(self) -> None:
        with suppress(OSError):
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


class RuntimeEventStore:
    def __init__(self, path: Path, *, observed_at: Callable[[], datetime] | None = None, allowed_root: Path | None = None) -> None:
        self.path = Path(path)
        self.observed_at = observed_at or (lambda: datetime.now(timezone.utc))
        self.allowed_root = Path(allowed_root) if allowed_root is not None else None

    @staticmethod
    def _validate(snapshot: Any) -> list[tuple[str, str, str]]:
        if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != _SNAPSHOT_SCHEMA:
            raise ValueError("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
        date = snapshot.get("business_date")
        version = snapshot.get("topology_version_sha")
        nodes = snapshot.get("nodes")
        if not isinstance(date, str) or not _DATE_RE.fullmatch(date) or not isinstance(version, str) or not _SHA_RE.fullmatch(version) or not isinstance(nodes, list):
            raise ValueError("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
        try:
            datetime.strptime(date, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID") from exc
        rows: list[tuple[str, str, str]] = []
        identifiers: set[str] = set()
        for node in nodes:
            if not isinstance(node, Mapping):
                raise ValueError("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
            node_id, status, reason = node.get("node_id"), node.get("status"), node.get("reason")
            if not isinstance(node_id, str) or not node_id or node_id in identifiers:
                raise ValueError("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
            if not isinstance(status, str) or status not in {item.value for item in GraphStatus} or not isinstance(reason, str):
                raise ValueError("RUNTIME_GRAPH_EVENT_SNAPSHOT_INVALID")
            identifiers.add(node_id)
            rows.append((node_id, status, reason))
        return rows

    @staticmethod
    def _observed_at(value: datetime) -> str:
        if not isinstance(value, datetime):
            raise ValueError("RUNTIME_GRAPH_EVENT_TIME_INVALID")
        if value.tzinfo is None:
            raise ValueError("RUNTIME_GRAPH_EVENT_TIME_INVALID")
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")

    def _lock_allowed_ancestry(self) -> list[int]:
        """Bind the database parent to held platform directory handles."""
        assert self.allowed_root is not None
        if os.name != "nt":
            return _posix_open_directory_ancestry(
                self.allowed_root,
                self.path.parent,
                "RUNTIME_GRAPH_EVENT_PATH_UNSAFE",
            )
        root, parent = _absolute(self.allowed_root), _absolute(self.path.parent)
        if not _within(parent, root):
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
        try:
            relative = parent.relative_to(root)
        except ValueError as exc:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
        paths, current = [root], root
        for part in relative.parts:
            current /= part
            paths.append(current)
        handles: list[int] = []
        try:
            for path in paths:
                native = AtomicSnapshotStore._open_directory_handle(path)
                try:
                    AtomicSnapshotStore._validate_directory_handle(native, path)
                except Exception:
                    with suppress(OSError):
                        AtomicSnapshotStore._close_native_handle(native)
                    raise
                handles.append(native)
            return handles
        except Exception:
            for native in reversed(handles):
                with suppress(OSError):
                    AtomicSnapshotStore._close_native_handle(native)
            raise

    @staticmethod
    def _close_ancestry(handles: list[int]) -> None:
        if os.name != "nt":
            _posix_close_directory_ancestry(handles)
            return
        for native in reversed(handles):
            with suppress(OSError):
                AtomicSnapshotStore._close_native_handle(native)

    def _validate_database_leaves(
        self,
        expected: Mapping[str, tuple[int, int]] | None = None,
        *,
        require_database: bool = False,
    ) -> dict[str, tuple[int, int]]:
        """Reject links and identity replacement for SQLite's database files.

        Directory handles bind the ancestry; SQLite also opens three leaf files
        whose names can otherwise be redirected with a hardlink or a replace.
        Keep their identities stable for the full connect/schema setup window.
        """
        if self.allowed_root is None:
            return {}
        leaves = {
            "database": self.path,
            "wal": self.path.with_name(f"{self.path.name}-wal"),
            "shm": self.path.with_name(f"{self.path.name}-shm"),
        }
        identities: dict[str, tuple[int, int]] = {}
        for name, leaf in leaves.items():
            _assert_safe_path(leaf, self.allowed_root)
            try:
                metadata = os.lstat(leaf)
            except FileNotFoundError:
                if name == "database" and require_database:
                    raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
                continue
            except OSError as exc:
                raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
            if _reparse(metadata) or not stat.S_ISREG(metadata.st_mode) or int(getattr(metadata, "st_nlink", 1)) != 1:
                raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
            identity = _file_identity(metadata)
            if expected is not None and name in expected and expected[name] != identity:
                raise ValueError("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
            identities[name] = identity
        return identities

    def _connect(self) -> tuple[sqlite3.Connection, list[int]]:
        handles: list[int] = []
        if self.allowed_root is not None:
            _assert_safe_path(self.path, self.allowed_root)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.allowed_root is not None:
            _assert_safe_path(self.path, self.allowed_root)
            handles = self._lock_allowed_ancestry()
        try:
            if self.allowed_root is not None:
                self._validate_database_leaves()
            connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        except Exception:
            self._close_ancestry(handles)
            raise
        if self.allowed_root is not None:
            try:
                _assert_safe_path(self.path, self.allowed_root)
                identities = self._validate_database_leaves(require_database=True)
            except Exception:
                try:
                    connection.close()
                finally:
                    self._close_ancestry(handles)
                raise
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            with suppress(sqlite3.DatabaseError):
                connection.execute("PRAGMA journal_mode=WAL")
            if self.allowed_root is not None:
                identities = self._validate_database_leaves(identities, require_database=True)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS runtime_node_state (business_date TEXT NOT NULL, topology_version_sha TEXT NOT NULL, node_id TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY (business_date, topology_version_sha, node_id))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS runtime_node_events (id INTEGER PRIMARY KEY AUTOINCREMENT, business_date TEXT NOT NULL, topology_version_sha TEXT NOT NULL, node_id TEXT NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, observed_at TEXT NOT NULL)"
            )
            if self.allowed_root is not None:
                self._validate_database_leaves(identities, require_database=True)
        except Exception:
            try:
                connection.close()
            finally:
                self._close_ancestry(handles)
            raise
        return connection, handles

    def record_transitions(self, snapshot: Any) -> int:
        rows = self._validate(snapshot)
        observed_at = self._observed_at(self.observed_at())
        date = str(snapshot["business_date"])
        version = str(snapshot["topology_version_sha"])
        connection, handles = self._connect()
        events = 0
        try:
            connection.execute("BEGIN IMMEDIATE")
            for node_id, status, reason in rows:
                current = connection.execute(
                    "SELECT status, reason FROM runtime_node_state WHERE business_date = ? AND topology_version_sha = ? AND node_id = ?",
                    (date, version, node_id),
                ).fetchone()
                if current is None or current["status"] != status or current["reason"] != reason:
                    connection.execute(
                        "INSERT INTO runtime_node_events (business_date, topology_version_sha, node_id, status, reason, observed_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (date, version, node_id, status, reason, observed_at),
                    )
                    events += 1
                connection.execute(
                    "INSERT INTO runtime_node_state (business_date, topology_version_sha, node_id, status, reason) VALUES (?, ?, ?, ?, ?) ON CONFLICT(business_date, topology_version_sha, node_id) DO UPDATE SET status = excluded.status, reason = excluded.reason",
                    (date, version, node_id, status, reason),
                )
            connection.execute("COMMIT")
            return events
        except Exception:
            with suppress(sqlite3.DatabaseError):
                connection.execute("ROLLBACK")
            raise
        finally:
            try:
                connection.close()
            finally:
                self._close_ancestry(handles)

    def list_events(self, node_id: str, limit: int = 100) -> list[dict[str, Any]]:
        if not isinstance(node_id, str) or not node_id or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("RUNTIME_GRAPH_EVENT_LIST_INVALID")
        connection, handles = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, business_date, topology_version_sha, node_id, status, reason, observed_at FROM runtime_node_events WHERE node_id = ? ORDER BY id ASC LIMIT ?",
                (node_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            try:
                connection.close()
            finally:
                self._close_ancestry(handles)


_EventDatabaseState = tuple[tuple[int, int], int, int]


def _event_database_state(
    store: RuntimeEventStore,
    expected: _EventDatabaseState | None = None,
) -> _EventDatabaseState:
    identities = store._validate_database_leaves(require_database=True)
    if set(identities) != {"database"}:
        raise ValueError("RUNTIME_GRAPH_EVENT_SIDECAR_PRESENT")
    try:
        metadata = os.lstat(store.path)
    except OSError as exc:
        raise ValueError("RUNTIME_GRAPH_EVENT_READ_UNAVAILABLE") from exc
    state = (_file_identity(metadata), int(metadata.st_size), int(metadata.st_mtime_ns))
    if expected is not None and state != expected:
        raise ValueError("RUNTIME_GRAPH_EVENT_DATABASE_CHANGED")
    return state


def _acquire_sqlite_read_guard(database: Path) -> Any:
    handle = None
    try:
        handle = database.open("rb")
        handle.seek(_SQLITE_SHARED_FIRST)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK, 1)
        else:  # pragma: no cover - the canonical runtime is Windows
            import fcntl

            fcntl.lockf(
                handle.fileno(),
                fcntl.LOCK_SH | fcntl.LOCK_NB,
                1,
                _SQLITE_SHARED_FIRST,
                os.SEEK_SET,
            )
        return handle
    except (OSError, ValueError) as exc:
        if handle is not None:
            handle.close()
        raise ValueError("RUNTIME_GRAPH_EVENT_DATABASE_BUSY") from exc


def _release_sqlite_read_guard(handle: Any) -> None:
    error: OSError | ValueError | None = None
    try:
        handle.seek(_SQLITE_SHARED_FIRST)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - the canonical runtime is Windows
            import fcntl

            fcntl.lockf(
                handle.fileno(),
                fcntl.LOCK_UN,
                1,
                _SQLITE_SHARED_FIRST,
                os.SEEK_SET,
            )
    except (OSError, ValueError) as exc:
        error = exc
    finally:
        handle.close()
    if error is not None:
        raise ValueError("RUNTIME_GRAPH_EVENT_GUARD_RELEASE_FAILED") from error


def _set_sqlite_read_limits(connection: sqlite3.Connection) -> None:
    category = getattr(sqlite3, "SQLITE_LIMIT_LENGTH", None)
    set_limit = getattr(connection, "setlimit", None)
    get_limit = getattr(connection, "getlimit", None)
    if category is None or not callable(set_limit):
        return
    target = _MAX_EVENT_SQLITE_LENGTH_BYTES
    if callable(get_limit):
        target = min(target, int(get_limit(category)))
    set_limit(category, target)


def _utf8_length(value: Any) -> int:
    if not isinstance(value, str):
        return -1
    return len(value.encode("utf-8"))


def _preflight_event_window(
    connection: sqlite3.Connection,
    node_id: str,
    limit: int,
) -> tuple[int, ...]:
    running_total = 0
    last_event_id: int | None = None

    def bounded_utf8_length(event_id: Any, value: Any, maximum: Any) -> int:
        nonlocal last_event_id, running_total
        if type(event_id) is not int or event_id <= 0 or type(maximum) is not int:
            raise ValueError("RUNTIME_GRAPH_EVENT_TYPE_INVALID")
        if last_event_id != event_id:
            if last_event_id is not None and event_id <= last_event_id:
                raise ValueError("RUNTIME_GRAPH_EVENT_ORDER_INVALID")
            last_event_id = event_id
            running_total += 8
        size = _utf8_length(value)
        if size < 0 or size > maximum:
            raise ValueError("RUNTIME_GRAPH_EVENT_FIELD_TOO_LARGE")
        running_total += size
        if running_total > _MAX_EVENT_RAW_BYTES:
            raise ValueError("RUNTIME_GRAPH_EVENT_WINDOW_TOO_LARGE")
        return size

    connection.create_function("runtime_utf8_len", 3, bounded_utf8_length)
    cursor = connection.execute(
        "SELECT id, typeof(id), typeof(business_date), typeof(topology_version_sha), "
        "typeof(node_id), typeof(status), typeof(reason), typeof(observed_at), "
        "runtime_utf8_len(id, business_date, 8), "
        "runtime_utf8_len(id, topology_version_sha, 64), "
        "runtime_utf8_len(id, node_id, 256), runtime_utf8_len(id, status, 32), "
        f"runtime_utf8_len(id, reason, {_MAX_EVENT_REASON_BYTES}), "
        "runtime_utf8_len(id, observed_at, 64) FROM runtime_node_events "
        "WHERE node_id = ? ORDER BY id ASC LIMIT ?",
        (node_id, limit),
    )
    expected_types = ("integer", "text", "text", "text", "text", "text", "text")
    ids: list[int] = []
    verified_total = 0
    for row in cursor:
        event_id = row[0]
        field_types = tuple(row[1:8])
        sizes = tuple(row[8:14])
        if type(event_id) is not int or event_id <= 0 or field_types != expected_types:
            raise ValueError("RUNTIME_GRAPH_EVENT_TYPE_INVALID")
        if len(sizes) != len(_EVENT_TEXT_BYTE_LIMITS) or any(
            type(size) is not int or size < 0 or size > maximum
            for size, maximum in zip(sizes, _EVENT_TEXT_BYTE_LIMITS)
        ):
            raise ValueError("RUNTIME_GRAPH_EVENT_FIELD_TOO_LARGE")
        verified_total += 8 + sum(sizes)
        if verified_total > _MAX_EVENT_RAW_BYTES:
            raise ValueError("RUNTIME_GRAPH_EVENT_WINDOW_TOO_LARGE")
        if ids and event_id <= ids[-1]:
            raise ValueError("RUNTIME_GRAPH_EVENT_ORDER_INVALID")
        ids.append(event_id)
    return tuple(ids)


def _validated_event(row: sqlite3.Row, node_id: str) -> dict[str, Any]:
    event = dict(row)
    event_id = event.get("id")
    date = event.get("business_date")
    version = event.get("topology_version_sha")
    actual_node = event.get("node_id")
    status = event.get("status")
    reason = event.get("reason")
    observed_at = event.get("observed_at")
    if type(event_id) is not int or event_id <= 0:
        raise ValueError("RUNTIME_GRAPH_EVENT_TYPE_INVALID")
    if not isinstance(date, str) or not _DATE_RE.fullmatch(date):
        raise ValueError("RUNTIME_GRAPH_EVENT_DATE_INVALID")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("RUNTIME_GRAPH_EVENT_DATE_INVALID") from exc
    if not isinstance(version, str) or not _SHA_RE.fullmatch(version):
        raise ValueError("RUNTIME_GRAPH_EVENT_SHA_INVALID")
    if not isinstance(actual_node, str) or actual_node != node_id:
        raise ValueError("RUNTIME_GRAPH_EVENT_NODE_INVALID")
    if not isinstance(status, str) or status not in {item.value for item in GraphStatus}:
        raise ValueError("RUNTIME_GRAPH_EVENT_STATUS_INVALID")
    if not isinstance(reason, str):
        raise ValueError("RUNTIME_GRAPH_EVENT_REASON_INVALID")
    if not isinstance(observed_at, str):
        raise ValueError("RUNTIME_GRAPH_EVENT_TIME_INVALID")
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("RUNTIME_GRAPH_EVENT_TIME_INVALID") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("RUNTIME_GRAPH_EVENT_TIME_INVALID")
    values = (date, version, actual_node, status, reason, observed_at)
    if any(
        len(value.encode("utf-8")) > maximum
        for value, maximum in zip(values, _EVENT_TEXT_BYTE_LIMITS)
    ):
        raise ValueError("RUNTIME_GRAPH_EVENT_FIELD_TOO_LARGE")
    return event


def _query_events_immutable(database: Path, node_id: str, limit: int) -> list[dict[str, Any]]:
    connection = None
    try:
        connection = sqlite3.connect(
            f"{database.as_uri()}?mode=ro&immutable=1",
            uri=True,
            timeout=0.1,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        _set_sqlite_read_limits(connection)
        connection.execute("PRAGMA query_only = ON")
        schema = connection.execute("PRAGMA table_info(runtime_node_events)").fetchall()
        if tuple(str(row["name"]) for row in schema) != _EVENT_COLUMNS:
            raise ValueError("RUNTIME_GRAPH_EVENT_SCHEMA_INVALID")
        expected_ids = _preflight_event_window(connection, node_id, limit)
        rows = connection.execute(
            "SELECT id, business_date, topology_version_sha, node_id, status, reason, observed_at "
            "FROM runtime_node_events WHERE node_id = ? ORDER BY id ASC LIMIT ?",
            (node_id, limit),
        ).fetchall()
        events = [_validated_event(row, node_id) for row in rows]
        if tuple(event["id"] for event in events) != expected_ids:
            raise ValueError("RUNTIME_GRAPH_EVENT_WINDOW_CHANGED")
        encoded = json.dumps(
            events,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_EVENT_JSON_BYTES:
            raise ValueError("RUNTIME_GRAPH_EVENT_JSON_TOO_LARGE")
        return events
    finally:
        if connection is not None:
            connection.close()


def list_events_read_only(
    path: Path,
    *,
    allowed_root: Path,
    node_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Read events without creating SQLite files, sidecars, or schema."""
    if (
        not isinstance(node_id, str)
        or not node_id
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= 500
    ):
        raise ValueError("RUNTIME_GRAPH_EVENT_LIST_INVALID")

    store = RuntimeEventStore(path, allowed_root=allowed_root)
    guard = None
    try:
        before = _event_database_state(store)
        database = _absolute(Path(path))
        guard = _acquire_sqlite_read_guard(database)
        result = _query_events_immutable(database, node_id, limit)
        _event_database_state(store, before)
        return result
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise ValueError("RUNTIME_GRAPH_EVENT_READ_UNAVAILABLE") from exc
    finally:
        if guard is not None:
            _release_sqlite_read_guard(guard)
