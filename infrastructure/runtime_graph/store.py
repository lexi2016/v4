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
    from infrastructure.runtime_graph._store_parts.path_safety import __assert_safe_path_body as _v4_impl
    return _v4_impl(globals(), path, root)


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
    from infrastructure.runtime_graph._store_parts.path_safety import __posix_open_directory_ancestry_body as _v4_impl
    return _v4_impl(globals(), root, parent, error)


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
        from infrastructure.runtime_graph._store_parts.path_safety import _AtomicSnapshotStore__open_directory_handle_body as _v4_impl
        return _v4_impl(globals(), path)

    @staticmethod
    def _directory_final_path(native: int) -> str:
        from infrastructure.runtime_graph._store_parts.path_safety import _AtomicSnapshotStore__directory_final_path_body as _v4_impl
        return _v4_impl(globals(), native)

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
        from infrastructure.runtime_graph._store_parts.path_safety import _AtomicSnapshotStore__lock_publication_ancestry_body as _v4_impl
        return _v4_impl(globals(), self, temp)

    @staticmethod
    def _open_temp_posix(temp: Path, parent_handle: int) -> Any:
        from infrastructure.runtime_graph._store_parts.store_state import _AtomicSnapshotStore__open_temp_posix_body as _v4_impl
        return _v4_impl(globals(), temp, parent_handle)

    def _publish_handle_posix(
        self,
        handle: Any,
        temp: Path,
        identity: tuple[int, int],
        expected: bytes,
        parent_handle: int,
    ) -> None:
        from infrastructure.runtime_graph._store_parts.snapshot_publish import _AtomicSnapshotStore__publish_handle_posix_body as _v4_impl
        return _v4_impl(globals(), self, handle, temp, identity, expected, parent_handle)

    def _publish_handle_no_replace_posix(
        self,
        handle: Any,
        temp: Path,
        identity: tuple[int, int],
        expected: bytes,
        parent_handle: int,
    ) -> None:
        from infrastructure.runtime_graph._store_parts.snapshot_publish import _AtomicSnapshotStore__publish_handle_no_replace_posix_body as _v4_impl
        return _v4_impl(globals(), self, handle, temp, identity, expected, parent_handle)

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
        from infrastructure.runtime_graph._store_parts.snapshot_publish import _AtomicSnapshotStore__publish_handle_body as _v4_impl
        return _v4_impl(globals(), self, handle, temp, identity, expected, parent_handle)

    def _publish_handle_no_replace(
        self,
        handle: Any,
        temp: Path,
        identity: tuple[int, int],
        expected: bytes,
        parent_handle: int,
    ) -> None:
        from infrastructure.runtime_graph._store_parts.snapshot_publish import _AtomicSnapshotStore__publish_handle_no_replace_body as _v4_impl
        return _v4_impl(globals(), self, handle, temp, identity, expected, parent_handle)

    def _lock(self) -> threading.Lock:
        key = os.path.normcase(str(_absolute(self.path)))
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def write(self, payload: Mapping[str, Any], *, require_absent: bool = False) -> None:
        with self._lock():
            self._write(payload, require_absent=require_absent)

    def _write(self, payload: Mapping[str, Any], *, require_absent: bool = False) -> None:
        from infrastructure.runtime_graph._store_parts.snapshot_publish import _AtomicSnapshotStore__write_body as _v4_impl
        return _v4_impl(globals(), self, payload, require_absent=require_absent)

    def _write_posix(self, serialized: str, *, require_absent: bool) -> None:
        from infrastructure.runtime_graph._store_parts.snapshot_publish import _AtomicSnapshotStore__write_posix_body as _v4_impl
        return _v4_impl(globals(), self, serialized, require_absent=require_absent)

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
        from infrastructure.runtime_graph._store_parts.store_state import _RuntimeEventStore__validate_body as _v4_impl
        return _v4_impl(globals(), snapshot)

    @staticmethod
    def _observed_at(value: datetime) -> str:
        if not isinstance(value, datetime):
            raise ValueError("RUNTIME_GRAPH_EVENT_TIME_INVALID")
        if value.tzinfo is None:
            raise ValueError("RUNTIME_GRAPH_EVENT_TIME_INVALID")
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")

    def _lock_allowed_ancestry(self) -> list[int]:
        """Bind the database parent to held platform directory handles."""
        from infrastructure.runtime_graph._store_parts.path_safety import _RuntimeEventStore__lock_allowed_ancestry_body as _v4_impl
        return _v4_impl(globals(), self)

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
        from infrastructure.runtime_graph._store_parts.store_state import _RuntimeEventStore__validate_database_leaves_body as _v4_impl
        return _v4_impl(globals(), self, expected, require_database=require_database)

    def _connect(self) -> tuple[sqlite3.Connection, list[int]]:
        from infrastructure.runtime_graph._store_parts.store_state import _RuntimeEventStore__connect_body as _v4_impl
        return _v4_impl(globals(), self)

    def record_transitions(self, snapshot: Any) -> int:
        from infrastructure.runtime_graph._store_parts.store_state import _RuntimeEventStore_record_transitions_body as _v4_impl
        return _v4_impl(globals(), self, snapshot)

    def list_events(self, node_id: str, limit: int = 100) -> list[dict[str, Any]]:
        from infrastructure.runtime_graph._store_parts.event_store import _RuntimeEventStore_list_events_body as _v4_impl
        return _v4_impl(globals(), self, node_id, limit)


_EventDatabaseState = tuple[tuple[int, int], int, int]


def _event_database_state(
    store: RuntimeEventStore,
    expected: _EventDatabaseState | None = None,
) -> _EventDatabaseState:
    from infrastructure.runtime_graph._store_parts.event_store import __event_database_state_body as _v4_impl
    return _v4_impl(globals(), store, expected)


def _acquire_sqlite_read_guard(database: Path) -> Any:
    from infrastructure.runtime_graph._store_parts.event_store import __acquire_sqlite_read_guard_body as _v4_impl
    return _v4_impl(globals(), database)


def _release_sqlite_read_guard(handle: Any) -> None:
    from infrastructure.runtime_graph._store_parts.event_store import __release_sqlite_read_guard_body as _v4_impl
    return _v4_impl(globals(), handle)


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
    from infrastructure.runtime_graph._store_parts.event_store import __validated_event_body as _v4_impl
    return _v4_impl(globals(), row, node_id)


def _query_events_immutable(database: Path, node_id: str, limit: int) -> list[dict[str, Any]]:
    from infrastructure.runtime_graph._store_parts.event_store import __query_events_immutable_body as _v4_impl
    return _v4_impl(globals(), database, node_id, limit)


def list_events_read_only(
    path: Path,
    *,
    allowed_root: Path,
    node_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Read events without creating SQLite files, sidecars, or schema."""
    from infrastructure.runtime_graph._store_parts.event_store import _list_events_read_only_body as _v4_impl
    return _v4_impl(globals(), path, allowed_root=allowed_root, node_id=node_id, limit=limit)
