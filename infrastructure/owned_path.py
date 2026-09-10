"""Fail-closed resolution for files owned below V3.5's data root."""
from __future__ import annotations

import stat
from pathlib import Path, PureWindowsPath


_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def _is_reparse_point(path: Path) -> bool:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _assert_no_reparse_ancestor(path: Path) -> None:
    current = path
    while True:
        if current.exists() or current.is_symlink():
            if _is_reparse_point(current):
                raise ValueError("owned destination has a reparse-point ancestor")
        parent = current.parent
        if parent == current:
            return
        current = parent


def resolve_owned_path(root: Path, relative: str) -> Path:
    """Resolve a write destination while rejecting traversal and reparse escapes."""
    if not isinstance(relative, str) or not relative:
        raise ValueError("owned destination must be a non-empty relative path")
    native = Path(relative)
    windows = PureWindowsPath(relative)
    if (
        native.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or bool(windows.root)
        or any(part in {"", ".", ".."} for part in native.parts)
        or any(part == ".." for part in windows.parts)
    ):
        raise ValueError("owned destination must not be absolute or traverse parents")
    raw_root = Path(root)
    _assert_no_reparse_ancestor(raw_root)
    canonical_root = raw_root.resolve(strict=False)
    # Build below the one canonical root captured above.  The relative path is
    # already traversal-free and every existing ancestor was checked for a
    # reparse point, so containment follows from construction.  Do not resolve
    # the candidate again: on Windows a concurrent directory creation can make
    # Path.resolve() intermittently add the ``\\?\\`` prefix to only the child,
    # causing a false escape against the otherwise identical canonical root.
    candidate = canonical_root.joinpath(*native.parts)
    _assert_no_reparse_ancestor(candidate)
    return candidate
