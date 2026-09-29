"""infrastructure.runtime_graph.store: snapshot_publish (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _AtomicSnapshotStore__publish_handle_posix_body(_v4_scope, /, self, handle, temp, identity, expected, parent_handle):
    metadata = _v4_global(_v4_scope, 'os').fstat(handle.fileno())
    if (
        _v4_global(_v4_scope, '_reparse')(metadata)
        or not _v4_global(_v4_scope, 'stat').S_ISREG(metadata.st_mode)
        or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(metadata, "st_nlink", 1)) != 1
        or _v4_global(_v4_scope, '_file_identity')(metadata) != identity
    ):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
    self._verify_handle(handle, expected)
    _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
    if _v4_global(_v4_scope, '_absolute')(temp.parent) != _v4_global(_v4_scope, '_absolute')(self.path.parent):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
    try:
        existing = _v4_global(_v4_scope, 'os').lstat(self.path)
    except _v4_global(_v4_scope, 'FileNotFoundError'):
        existing = None
    if existing is not None and (
        _v4_global(_v4_scope, '_reparse')(existing)
        or not _v4_global(_v4_scope, 'stat').S_ISREG(existing.st_mode)
        or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(existing, "st_nlink", 1)) != 1
    ):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
    _v4_global(_v4_scope, 'os').replace(temp.name, self.path.name, src_dir_fd=parent_handle, dst_dir_fd=parent_handle)
    _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
    target = _v4_global(_v4_scope, 'os').lstat(self.path)
    if (
        _v4_global(_v4_scope, '_reparse')(target)
        or not _v4_global(_v4_scope, 'stat').S_ISREG(target.st_mode)
        or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(target, "st_nlink", 1)) != 1
        or _v4_global(_v4_scope, '_file_identity')(target) != identity
    ):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")


def _AtomicSnapshotStore__publish_handle_no_replace_posix_body(_v4_scope, /, self, handle, temp, identity, expected, parent_handle):
    metadata = _v4_global(_v4_scope, 'os').fstat(handle.fileno())
    if (
        _v4_global(_v4_scope, '_reparse')(metadata)
        or not _v4_global(_v4_scope, 'stat').S_ISREG(metadata.st_mode)
        or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(metadata, "st_nlink", 1)) != 1
        or _v4_global(_v4_scope, '_file_identity')(metadata) != identity
    ):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
    self._verify_handle(handle, expected)
    _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
    if _v4_global(_v4_scope, '_absolute')(temp.parent) != _v4_global(_v4_scope, '_absolute')(self.path.parent):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
    _v4_global(_v4_scope, 'os').link(
        temp.name,
        self.path.name,
        src_dir_fd=parent_handle,
        dst_dir_fd=parent_handle,
        follow_symlinks=False,
    )
    _v4_global(_v4_scope, 'os').unlink(temp.name, dir_fd=parent_handle)
    _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
    target = _v4_global(_v4_scope, 'os').lstat(self.path)
    if (
        _v4_global(_v4_scope, '_reparse')(target)
        or not _v4_global(_v4_scope, 'stat').S_ISREG(target.st_mode)
        or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(target, "st_nlink", 1)) != 1
        or _v4_global(_v4_scope, '_file_identity')(target) != identity
    ):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")


def _AtomicSnapshotStore__publish_handle_body(_v4_scope, /, self, handle, temp, identity, expected, parent_handle):
    if not self._is_windows():
        self._publish_handle_posix(handle, temp, identity, expected, parent_handle)
        return
    if _v4_global(_v4_scope, '_file_identity')(_v4_global(_v4_scope, 'os').fstat(handle.fileno())) != identity:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
    self._verify_handle(handle, expected)
    _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
    if not self._is_windows():
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PLATFORM_UNSUPPORTED")
    if _v4_global(_v4_scope, '_absolute')(temp.parent) != _v4_global(_v4_scope, '_absolute')(self.path.parent):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
    self._validate_directory_handle(parent_handle, _v4_global(_v4_scope, '_absolute')(self.path.parent))
    self._rename_open_file_on_windows(handle, self.path)


def _AtomicSnapshotStore__publish_handle_no_replace_body(_v4_scope, /, self, handle, temp, identity, expected, parent_handle):
    if not self._is_windows():
        self._publish_handle_no_replace_posix(handle, temp, identity, expected, parent_handle)
        return
    if _v4_global(_v4_scope, '_file_identity')(_v4_global(_v4_scope, 'os').fstat(handle.fileno())) != identity:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")
    self._verify_handle(handle, expected)
    _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
    if not self._is_windows() or _v4_global(_v4_scope, '_absolute')(temp.parent) != _v4_global(_v4_scope, '_absolute')(self.path.parent):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
    self._validate_directory_handle(parent_handle, _v4_global(_v4_scope, '_absolute')(self.path.parent))
    self._rename_open_file_on_windows(handle, self.path, replace_if_exists=False)
    _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
    metadata = _v4_global(_v4_scope, 'os').lstat(self.path)
    if (
        _v4_global(_v4_scope, '_reparse')(metadata)
        or not _v4_global(_v4_scope, 'stat').S_ISREG(metadata.st_mode)
        or _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'getattr')(metadata, "st_nlink", 1)) != 1
        or _v4_global(_v4_scope, '_file_identity')(metadata) != identity
    ):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_IDENTITY_INVALID")


def _AtomicSnapshotStore__write_body(_v4_scope, /, self, payload, *, require_absent):
    _v4_global(_v4_scope, '_assert_safe_path')(self.path, self.allowed_root)
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')) or payload.get("schema_version") != self.expected_schema:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_SCHEMA_INVALID")
    try:
        serialized = _v4_global(_v4_scope, 'json').dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        roundtrip = _v4_global(_v4_scope, 'json').loads(serialized)
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError')) as exc:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_SERIALIZE_FAILED") from exc
    if not _v4_global(_v4_scope, 'isinstance')(roundtrip, _v4_global(_v4_scope, 'Mapping')) or roundtrip.get("schema_version") != self.expected_schema:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_SCHEMA_INVALID")
    if not self._is_windows():
        self._write_posix(serialized, require_absent=require_absent)
        return
    temp = self._new_temp_path()
    _v4_global(_v4_scope, '_assert_safe_path')(temp, self.allowed_root)
    temp_owned = False
    handle = None
    identity: tuple[int, int] | None = None
    published = False
    ancestry: list[int] = []
    try:
        ancestry = self._lock_publication_ancestry(temp)
        handle = self._open_temp(temp)
        temp_owned = True
        identity = _v4_global(_v4_scope, '_file_identity')(_v4_global(_v4_scope, 'os').fstat(handle.fileno()))
        payload_bytes = serialized.encode("utf-8")
        handle.write(payload_bytes)
        handle.flush()
        _v4_global(_v4_scope, 'os').fsync(handle.fileno())
        self._verify_handle(handle, payload_bytes)
        self._verify_temp(temp)
        _v4_global(_v4_scope, '_assert_safe_path')(temp, self.allowed_root)
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
        for native in _v4_global(_v4_scope, 'reversed')(ancestry):
            with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'OSError')):
                self._close_native_handle(native)


def _AtomicSnapshotStore__write_posix_body(_v4_scope, /, self, serialized, *, require_absent):
    temp = self._new_temp_path()
    _v4_global(_v4_scope, '_assert_safe_path')(temp, self.allowed_root)
    temp_owned = False
    handle = None
    published = False
    ancestry: list[int] = []
    try:
        ancestry = self._lock_publication_ancestry(temp)
        handle = self._open_temp_posix(temp, ancestry[-1])
        temp_owned = True
        identity = _v4_global(_v4_scope, '_file_identity')(_v4_global(_v4_scope, 'os').fstat(handle.fileno()))
        payload_bytes = serialized.encode("utf-8")
        handle.write(payload_bytes)
        handle.flush()
        _v4_global(_v4_scope, 'os').fsync(handle.fileno())
        self._verify_handle(handle, payload_bytes)
        self._verify_temp(temp)
        _v4_global(_v4_scope, '_assert_safe_path')(temp, self.allowed_root)
        if require_absent:
            self._publish_handle_no_replace(handle, temp, identity, payload_bytes, ancestry[-1])
        else:
            self._publish_handle(handle, temp, identity, payload_bytes, ancestry[-1])
        temp_owned = False
        published = True
        _v4_global(_v4_scope, 'os').fsync(ancestry[-1])
    finally:
        if handle is not None:
            if temp_owned and not published:
                with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'OSError')):
                    _v4_global(_v4_scope, 'os').unlink(temp.name, dir_fd=ancestry[-1])
            self._close_handle(handle)
        _v4_global(_v4_scope, '_posix_close_directory_ancestry')(ancestry)
