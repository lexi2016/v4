"""stage_center.raw_store: filesystem_io (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __atomic_write_bytes_body(_v4_scope, /, path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(
        prefix=f".{path.name}.{_v4_global(_v4_scope, 'uuid4')().hex}.", suffix=".tmp", dir=path.parent
    )
    try:
        with _v4_global(_v4_scope, 'os').fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            _v4_global(_v4_scope, 'os').fsync(stream.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)


def __atomic_write_json_body(_v4_scope, /, path, payload):
    _v4_global(_v4_scope, '_atomic_write_bytes')(
        path,
        (
            _v4_global(_v4_scope, 'json').dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8"),
    )


def __atomic_write_csv_body(_v4_scope, /, path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(
        prefix=f".{path.name}.{_v4_global(_v4_scope, 'uuid4')().hex}.", suffix=".tmp", dir=path.parent
    )
    try:
        with _v4_global(_v4_scope, 'os').fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = _v4_global(_v4_scope, 'csv').DictWriter(
                stream,
                fieldnames=_v4_global(_v4_scope, 'ARTIFACT_FIELDS'),
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            _v4_global(_v4_scope, 'os').fsync(stream.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)


def __safe_relative_body(_v4_scope, /, root, relative):
    if (
        not _v4_global(_v4_scope, 'isinstance')(relative, _v4_global(_v4_scope, 'str'))
        or not relative
        or "\\" in relative
        or relative.startswith("/")
        or (_v4_global(_v4_scope, 'len')(relative) > 1 and relative[1] == ":")
    ):
        raise _v4_global(_v4_scope, 'RawStoreError')("path must be normalized and relative")
    parsed = _v4_global(_v4_scope, 'PurePosixPath')(relative)
    if parsed.as_posix() != relative or _v4_global(_v4_scope, 'any')(part in {"", ".", ".."} for part in parsed.parts):
        raise _v4_global(_v4_scope, 'RawStoreError')("path must be normalized and relative")
    current = root
    for part in _v4_global(_v4_scope, 'Path')(relative).parts:
        current = current / part
        if current.is_symlink():
            raise _v4_global(_v4_scope, 'RawStoreError')("symlink component is forbidden")
    resolved_root = root.resolve()
    resolved_candidate = current.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'RawStoreError')("path escapes store root") from error
    return current
