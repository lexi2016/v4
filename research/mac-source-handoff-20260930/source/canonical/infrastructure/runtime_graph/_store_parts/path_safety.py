"""infrastructure.runtime_graph.store: path_safety (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __assert_safe_path_body(_v4_scope, /, path, root):
    destination, allowed = _v4_global(_v4_scope, '_absolute')(path), _v4_global(_v4_scope, '_absolute')(root)
    if not _v4_global(_v4_scope, '_within')(destination, allowed):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
    try:
        relative = destination.relative_to(allowed)
    except _v4_global(_v4_scope, 'ValueError') as exc:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
    current = allowed
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        try:
            metadata = _v4_global(_v4_scope, 'os').lstat(current)
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            continue
        except _v4_global(_v4_scope, 'OSError') as exc:
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
        if _v4_global(_v4_scope, '_reparse')(metadata):
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")


def __posix_open_directory_ancestry_body(_v4_scope, /, root, parent, error):
    """Open every directory in an allowlisted ancestry without following links."""
    root, parent = _v4_global(_v4_scope, '_absolute')(root), _v4_global(_v4_scope, '_absolute')(parent)
    if not _v4_global(_v4_scope, '_within')(parent, root):
        raise _v4_global(_v4_scope, 'ValueError')(error)
    try:
        relative = parent.relative_to(root)
    except _v4_global(_v4_scope, 'ValueError') as exc:
        raise _v4_global(_v4_scope, 'ValueError')(error) from exc

    flags = _v4_global(_v4_scope, 'os').O_RDONLY | _v4_global(_v4_scope, 'getattr')(_v4_global(_v4_scope, 'os'), "O_DIRECTORY", 0) | _v4_global(_v4_scope, 'getattr')(_v4_global(_v4_scope, 'os'), "O_NOFOLLOW", 0)
    handles: list[int] = []
    paths = [root]
    current = root
    for part in relative.parts:
        current = current / part
        paths.append(current)
    current_fd: int | None = None
    try:
        for index, path in _v4_global(_v4_scope, 'enumerate')(paths):
            metadata = _v4_global(_v4_scope, 'os').lstat(path)
            if _v4_global(_v4_scope, '_reparse')(metadata) or not _v4_global(_v4_scope, 'stat').S_ISDIR(metadata.st_mode):
                raise _v4_global(_v4_scope, 'ValueError')(error)
            if index == 0:
                descriptor = _v4_global(_v4_scope, 'os').open(_v4_global(_v4_scope, 'str')(path), flags)
            else:
                descriptor = _v4_global(_v4_scope, 'os').open(path.name, flags, dir_fd=current_fd)
            opened = _v4_global(_v4_scope, 'os').fstat(descriptor)
            if (
                _v4_global(_v4_scope, '_reparse')(opened)
                or not _v4_global(_v4_scope, 'stat').S_ISDIR(opened.st_mode)
                or _v4_global(_v4_scope, '_file_identity')(metadata) != _v4_global(_v4_scope, '_file_identity')(opened)
            ):
                _v4_global(_v4_scope, 'os').close(descriptor)
                raise _v4_global(_v4_scope, 'ValueError')(error)
            handles.append(descriptor)
            current_fd = descriptor
        return handles
    except _v4_global(_v4_scope, 'Exception'):
        for descriptor in _v4_global(_v4_scope, 'reversed')(handles):
            with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'OSError')):
                _v4_global(_v4_scope, 'os').close(descriptor)
        raise


def _AtomicSnapshotStore__open_directory_handle_body(_v4_scope, /, path):
    import ctypes
    from ctypes import wintypes

    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    native = create_file(
        _v4_global(_v4_scope, 'str')(path), 0x00000020 | 0x00000080 | 0x00100000,
        0x00000001, None, 3, 0x02000000, None,
    )
    if native == wintypes.HANDLE(-1).value:
        raise _v4_global(_v4_scope, 'OSError')(ctypes.get_last_error(), "CreateFileW directory failed", _v4_global(_v4_scope, 'str')(path))
    return native


def _AtomicSnapshotStore__directory_final_path_body(_v4_scope, /, native):
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_final = kernel32.GetFinalPathNameByHandleW
    get_final.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    get_final.restype = wintypes.DWORD
    size = get_final(native, None, 0, 0)
    if not size:
        raise _v4_global(_v4_scope, 'OSError')(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
    buffer = ctypes.create_unicode_buffer(size + 1)
    result = get_final(native, buffer, _v4_global(_v4_scope, 'len')(buffer), 0)
    if not result or result >= _v4_global(_v4_scope, 'len')(buffer):
        raise _v4_global(_v4_scope, 'OSError')(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return _v4_global(_v4_scope, 'os').path.normcase(_v4_global(_v4_scope, 'os').path.normpath(value))


def _AtomicSnapshotStore__lock_publication_ancestry_body(_v4_scope, /, self, temp):
    if not self._is_windows():
        return _v4_global(_v4_scope, '_posix_open_directory_ancestry')(
            self.allowed_root,
            temp.parent,
            "RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE",
        )
    root, parent = _v4_global(_v4_scope, '_absolute')(self.allowed_root), _v4_global(_v4_scope, '_absolute')(temp.parent)
    if not _v4_global(_v4_scope, '_within')(parent, root):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
    try:
        relative = parent.relative_to(root)
    except _v4_global(_v4_scope, 'ValueError') as exc:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
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
            except _v4_global(_v4_scope, 'Exception'):
                with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'OSError')):
                    self._close_native_handle(native)
                raise
            handles.append(native)
        return handles
    except _v4_global(_v4_scope, 'Exception'):
        for native in _v4_global(_v4_scope, 'reversed')(handles):
            with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'OSError')):
                self._close_native_handle(native)
        raise


def _RuntimeEventStore__lock_allowed_ancestry_body(_v4_scope, /, self):
    """Bind the database parent to held platform directory handles."""
    assert self.allowed_root is not None
    if _v4_global(_v4_scope, 'os').name != "nt":
        return _v4_global(_v4_scope, '_posix_open_directory_ancestry')(
            self.allowed_root,
            self.path.parent,
            "RUNTIME_GRAPH_EVENT_PATH_UNSAFE",
        )
    root, parent = _v4_global(_v4_scope, '_absolute')(self.allowed_root), _v4_global(_v4_scope, '_absolute')(self.path.parent)
    if not _v4_global(_v4_scope, '_within')(parent, root):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE")
    try:
        relative = parent.relative_to(root)
    except _v4_global(_v4_scope, 'ValueError') as exc:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_SNAPSHOT_PATH_UNSAFE") from exc
    paths, current = [root], root
    for part in relative.parts:
        current /= part
        paths.append(current)
    handles: list[int] = []
    try:
        for path in paths:
            native = _v4_global(_v4_scope, 'AtomicSnapshotStore')._open_directory_handle(path)
            try:
                _v4_global(_v4_scope, 'AtomicSnapshotStore')._validate_directory_handle(native, path)
            except _v4_global(_v4_scope, 'Exception'):
                with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'OSError')):
                    _v4_global(_v4_scope, 'AtomicSnapshotStore')._close_native_handle(native)
                raise
            handles.append(native)
        return handles
    except _v4_global(_v4_scope, 'Exception'):
        for native in _v4_global(_v4_scope, 'reversed')(handles):
            with _v4_global(_v4_scope, 'suppress')(_v4_global(_v4_scope, 'OSError')):
                _v4_global(_v4_scope, 'AtomicSnapshotStore')._close_native_handle(native)
        raise
