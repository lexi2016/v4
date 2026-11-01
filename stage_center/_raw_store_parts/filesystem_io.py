"""stage_center.raw_store: filesystem_io (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global
from pathlib import Path
from pathlib import PurePosixPath
from uuid import uuid4
import csv
import json
import os
import tempfile


def __atomic_write_bytes_body(_v4_scope, /, path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.{uuid4().hex}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def __atomic_write_json_body(_v4_scope, /, path, payload):
    _v4_global(_v4_scope, '_atomic_write_bytes')(
        path,
        (
            json.dumps(
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
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.{uuid4().hex}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=_v4_global(_v4_scope, 'ARTIFACT_FIELDS'),
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def __safe_relative_body(_v4_scope, /, root, relative):
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or relative.startswith("/")
        or (len(relative) > 1 and relative[1] == ":")
    ):
        raise _v4_global(_v4_scope, 'RawStoreError')("path must be normalized and relative")
    parsed = PurePosixPath(relative)
    if parsed.as_posix() != relative or any(part in {"", ".", ".."} for part in parsed.parts):
        raise _v4_global(_v4_scope, 'RawStoreError')("path must be normalized and relative")
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise _v4_global(_v4_scope, 'RawStoreError')("symlink component is forbidden")
    resolved_root = root.resolve()
    resolved_candidate = current.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as error:
        raise _v4_global(_v4_scope, 'RawStoreError')("path escapes store root") from error
    return current
