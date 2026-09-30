"""Store-relative path safety (mirrors V3.5 `_safe_relative`) plus strict slugs."""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

_ROLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def safe_relative(value: Any) -> str:
    """Return a normalized POSIX-relative path or raise.

    Rejects absolute paths, drive letters, backslashes, ``..`` and empty
    components so store paths can never escape the store root.
    """
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("path must be a normalized relative POSIX path")
    if value.startswith("/") or (len(value) > 1 and value[1] == ":"):
        raise ValueError("path must be a normalized relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or path.as_posix() != value:
        raise ValueError("path must be a normalized relative POSIX path")
    return value


def validate_date(value: Any) -> str:
    import datetime as _dt

    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("date must use YYYYMMDD")
    try:
        _dt.datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("date must be a real calendar date") from error
    return value


def validate_role(value: Any) -> str:
    """Strict safe slug: alnum start/end; only [A-Za-z0-9_.-] inside.

    Rejects ``.``, ``..``, path-like values, absolute paths and any
    non-normalized role string.
    """
    if not isinstance(value, str) or not value or not _ROLE_RE.fullmatch(value):
        raise ValueError("role must be a strict safe slug")
    return value


def _get_file_attributes(path: Path) -> int:
    """Windows GetFileAttributesW with proper unsigned restype.

    Returns INVALID_FILE_ATTRIBUTES (0xFFFFFFFF) off-Windows or on query
    failure. ctypes must declare restype=c_uint32: the default signed c_int
    turns 0xFFFFFFFF into -1, which would break INVALID comparisons.
    """
    if os.name != "nt":
        return _INVALID_FILE_ATTRIBUTES
    try:
        import ctypes

        func = ctypes.windll.kernel32.GetFileAttributesW
        func.restype = ctypes.c_uint32
        func.argtypes = [ctypes.c_wchar_p]
        return int(func(str(path)))
    except (AttributeError, OSError, ValueError):
        return _INVALID_FILE_ATTRIBUTES


def _detect_reparse(path: Path) -> bool:
    """True for Windows reparse/junction components that actually exist.

    Nonexistent components (normal for future run dirs) and any
    INVALID_FILE_ATTRIBUTES result are explicitly NOT reparse. Real existing
    junctions / reparse points keep failing closed.
    """
    if not path.exists():
        return False
    attrs = _get_file_attributes(path)
    if attrs == _INVALID_FILE_ATTRIBUTES:
        return False
    return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)


def _is_link(path: Path) -> bool:
    """True for symlinks and Windows reparse points / junctions."""
    return path.is_symlink() or _detect_reparse(path)


def resolve_under(root: Path, relative: str) -> Path:
    """Resolve a store-relative path and refuse symlink/reparse escapes."""
    root = Path(root)
    safe_relative(relative)
    candidate = root / relative
    # Refuse any symlink / junction / reparse component between root and candidate.
    current = root
    for part in Path(relative).parts:
        current = current / part
        if _is_link(current):
            raise ValueError("symlink/reparse component is not allowed inside the store")
    real_root = root.resolve()
    real_candidate = candidate.resolve()
    if real_root != real_candidate and real_root not in real_candidate.parents:
        raise ValueError("resolved path escapes the store root")
    return candidate
