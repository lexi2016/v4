"""Generator JSON contracts on the shared infrastructure.SafeRoot boundary.

No second low-level open/rename/locking implementation lives in this package.
The historical ``fd`` argument name is retained for source compatibility; the
handle is now a SafeRoot whose directory identity is checked on each operation.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from typing import Iterator
from infrastructure.owned_io import SafeRoot, OwnedIOError


class BoundaryError(ValueError):
    pass


def _name(name: str) -> str:
    if not isinstance(name, str) or not name or name in {".", ".."} or any(x in name for x in ("/", "\\", "\x00")):
        raise BoundaryError("one directory-relative file name is required")
    return name


@contextmanager
def directory(root: Path | str, *, create: bool = False) -> Iterator[SafeRoot]:
    path = Path(root)
    if not path.is_absolute() or ".." in path.parts:
        raise BoundaryError("root must be absolute, without traversal")
    io = SafeRoot(path)
    try:
        with io.directory(create=create):
            yield io
    except (OSError, OwnedIOError) as exc:
        raise BoundaryError(f"directory boundary refused: {type(exc).__name__}") from exc


def check_destination(fd: SafeRoot, name: str, *, replace: bool) -> None:
    _name(name)
    try:
        fd.read_bytes(name)
    except FileNotFoundError:
        return
    except (OSError, OwnedIOError) as exc:
        raise BoundaryError("destination is not a regular file (symlink refused)") from exc
    if not replace:
        raise BoundaryError("dated review already exists")


def read_bytes(fd: SafeRoot, name: str, *, limit: int = 8 * 1024 * 1024) -> bytes:
    return fd.read_bytes(_name(name), max_bytes=limit)


def reject_nonfinite(value: str):
    raise BoundaryError("non-finite JSON value refused")


def read_json(fd: SafeRoot, name: str, *, limit: int = 8 * 1024 * 1024) -> tuple[object, str, int]:
    raw = read_bytes(fd, name, limit=limit)
    return json.loads(raw, parse_constant=reject_nonfinite), hashlib.sha256(raw).hexdigest(), len(raw)


def write_bytes(fd: SafeRoot, name: str, data: bytes, *, replace: bool) -> None:
    check_destination(fd, name, replace=replace)
    try:
        fd.write_bytes(_name(name), data, require_absent=not replace)
    except FileExistsError as exc:
        raise BoundaryError("dated review already exists") from exc


def records(fd: SafeRoot, *, max_files: int = 2000) -> tuple[list[dict], list[dict], list[str]]:
    """Read exact-date reflection JSON once; bad JSON is visible, never repaired."""
    names = fd.files()
    if len(names) > max_files:
        raise BoundaryError("reflection directory exceeds bounded file count")
    from datetime import date
    values, manifest, warnings = [], [], []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            parsed = date.fromisoformat(name[:-5])
            if parsed.isoformat() != name[:-5]:
                continue
        except ValueError:
            continue
        # Unsafe filesystem entries fail closed, not a missing-history fallback.
        data = read_bytes(fd, name, limit=2 * 1024 * 1024)
        manifest.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        try:
            value = json.loads(data, parse_constant=reject_nonfinite)
        except (ValueError, UnicodeDecodeError):
            warnings.append(f"reflection {name}: invalid JSON, excluded")
            continue
        if not isinstance(value, dict) or value.get("prediction_date") != parsed.isoformat():
            warnings.append(f"reflection {name}: prediction identity mismatch, excluded")
            continue
        values.append(value)
    return values, manifest, warnings
