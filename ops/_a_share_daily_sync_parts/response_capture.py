"""ops.a_share_daily_sync: response_capture (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __write_raw_response_snapshot_body(_v4_scope, /, *, target_date, target, request, host, host_ordinal, attempt_ordinal, response_rows, response_error, run_id, rule_id, rule_version, observed_at):
    """Persist one immutable provider-response object under the sync run root."""
    snapshot = {
        "schema_version": "v3_5.a_share.tdx_raw_response_snapshot.v1",
        "target_date": _v4_global(_v4_scope, 'str')(target_date),
        "symbol": _v4_global(_v4_scope, 'str')(target.code),
        "request": _v4_global(_v4_scope, 'dict')(request),
        "host": host,
        "host_ordinal": _v4_global(_v4_scope, 'int')(host_ordinal),
        "attempt_ordinal": _v4_global(_v4_scope, 'int')(attempt_ordinal),
        "run_id": run_id,
        "rule_id": rule_id,
        "rule_version": rule_version,
        "observed_at": observed_at or _v4_global(_v4_scope, '_observed_at')(),
        "response_rows": _v4_global(_v4_scope, '_snapshot_json_value')(response_rows),
        "response_error": response_error,
    }
    encoded = _v4_global(_v4_scope, 'json').dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = _v4_global(_v4_scope, 'hashlib').sha256(encoded).hexdigest()
    symbol_path = _v4_global(_v4_scope, 'str')(target.code).replace("/", "_").replace("\\", "_")
    root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'RUN_DIR')) / "raw_responses" / _v4_global(_v4_scope, 'str')(target_date) / symbol_path
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{digest}.json"
    flags = _v4_global(_v4_scope, 'os').O_WRONLY | _v4_global(_v4_scope, 'os').O_CREAT | _v4_global(_v4_scope, 'os').O_EXCL
    if _v4_global(_v4_scope, 'hasattr')(_v4_global(_v4_scope, 'os'), "O_CLOEXEC"):
        flags |= _v4_global(_v4_scope, 'os').O_CLOEXEC
    try:
        fd = _v4_global(_v4_scope, 'os').open(_v4_global(_v4_scope, 'str')(path), flags, 0o600)
    except _v4_global(_v4_scope, 'FileExistsError'):
        try:
            before = _v4_global(_v4_scope, 'os').lstat(path)
        except _v4_global(_v4_scope, 'OSError') as error:
            raise _v4_global(_v4_scope, 'RuntimeError')(f"raw response snapshot identity unavailable: {path}") from error
        if (
            not _v4_global(_v4_scope, 'stat').S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or _v4_global(_v4_scope, 'stat').S_IMODE(before.st_mode) != 0o600
        ):
            raise _v4_global(_v4_scope, 'RuntimeError')(f"raw response snapshot identity is unsafe: {path}")
        read_flags = _v4_global(_v4_scope, 'os').O_RDONLY
        if _v4_global(_v4_scope, 'hasattr')(_v4_global(_v4_scope, 'os'), "O_CLOEXEC"):
            read_flags |= _v4_global(_v4_scope, 'os').O_CLOEXEC
        if _v4_global(_v4_scope, 'hasattr')(_v4_global(_v4_scope, 'os'), "O_NOFOLLOW"):
            read_flags |= _v4_global(_v4_scope, 'os').O_NOFOLLOW
        read_fd: int | None = None
        try:
            try:
                read_fd = _v4_global(_v4_scope, 'os').open(_v4_global(_v4_scope, 'str')(path), read_flags)
            except _v4_global(_v4_scope, 'OSError') as error:
                raise _v4_global(_v4_scope, 'RuntimeError')(f"raw response snapshot cannot be opened safely: {path}") from error
            opened = _v4_global(_v4_scope, 'os').fstat(read_fd)
            if (
                not _v4_global(_v4_scope, 'stat').S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or _v4_global(_v4_scope, 'stat').S_IMODE(opened.st_mode) != 0o600
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise _v4_global(_v4_scope, 'RuntimeError')(f"raw response snapshot identity changed: {path}")
            with _v4_global(_v4_scope, 'os').fdopen(read_fd, "rb") as stream:
                read_fd = None
                existing = stream.read()
        finally:
            if read_fd is not None:
                try:
                    _v4_global(_v4_scope, 'os').close(read_fd)
                except _v4_global(_v4_scope, 'OSError'):
                    pass
        if existing != encoded:
            raise _v4_global(_v4_scope, 'RuntimeError')(f"raw response snapshot content conflict: {path}")
    else:
        open_fd: int | None = fd
        try:
            with _v4_global(_v4_scope, 'os').fdopen(fd, "wb") as stream:
                open_fd = None
                stream.write(encoded)
                stream.flush()
                _v4_global(_v4_scope, 'os').fsync(stream.fileno())
        except _v4_global(_v4_scope, 'Exception'):
            if open_fd is not None:
                try:
                    _v4_global(_v4_scope, 'os').close(open_fd)
                except _v4_global(_v4_scope, 'OSError'):
                    pass
            try:
                path.unlink()
            except _v4_global(_v4_scope, 'FileNotFoundError'):
                pass
            raise
    return {
        "capture_id": digest,
        "path": _v4_global(_v4_scope, 'str')(path),
        "sha256": digest,
        "host": host,
        "host_ordinal": _v4_global(_v4_scope, 'int')(host_ordinal),
        "attempt_ordinal": _v4_global(_v4_scope, 'int')(attempt_ordinal),
    }
