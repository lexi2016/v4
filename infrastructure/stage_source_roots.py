"""Explicit source/target binding; never selects a fallback or moves pool data."""
from __future__ import annotations

import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator
from infrastructure.interprocess_lock import (
    OwnedInterprocessLockLease, assert_owned_interprocess_lock, owned_interprocess_lock,
)


def _absolute_directory(value: Path | str, *, required: bool) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("explicit nonempty source/target root required")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("source/target root must be absolute without parent traversal")
    path = Path(os.path.abspath(path))
    for parent in (path, *path.parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("source/target root contains symlink or non-directory")
    if required and not path.is_dir():
        raise ValueError("explicit preselection source root is missing")
    return path


def _physically_overlaps(source: Path, target: Path) -> bool:
    """Detect equality or ancestry even when the volume aliases path case.

    Lexical ``Path.parents`` checks alone miss a parent spelled with a different
    case on the default case-insensitive macOS volume. Compare each existing
    ancestor by filesystem identity as well.
    """
    for ancestor in (target, *target.parents):
        try:
            if os.path.samefile(source, ancestor):
                return True
        except (FileNotFoundError, NotADirectoryError):
            continue
    for ancestor in (source, *source.parents):
        try:
            if os.path.samefile(target, ancestor):
                return True
        except (FileNotFoundError, NotADirectoryError):
            continue
    return False


def resolve_source_root(target: Path | str, source: Path | str | None) -> Path:
    # None preserves the historical same-root API. Empty text is NOT None.
    if source is None:
        return Path(target).expanduser().resolve()
    dst = _absolute_directory(target, required=False)
    src = _absolute_directory(source, required=True)
    if dst != src:
        if dst in src.parents or src in dst.parents or _physically_overlaps(src, dst):
            raise ValueError("distinct source/target roots must not overlap")
    return src


@contextmanager
def publication_source_lease(target: Path, source: Path) -> Iterator[OwnedInterprocessLockLease]:
    """Hold both native import locks through target publication; lock same root once.

    No source lock is borrowed from a different root. Sorting absolute paths gives
    a stable order for concurrent opposite-direction operations. Native no-follow
    lock I/O and live capability checks remain the security boundary.
    """
    target = Path(os.path.abspath(Path(target).expanduser()))
    source = Path(os.path.abspath(Path(source).expanduser()))
    roots = sorted(set((source, target)), key=str)
    source_stat = source.stat(follow_symlinks=False)
    with ExitStack() as stack:
        leases = {}
        for root in roots:
            leases[root] = stack.enter_context(owned_interprocess_lock(
                root / ".import.lock", timeout_seconds=10,
                timeout_message="stage source/target import lock timeout",
            ))
        current = source.stat(follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (source_stat.st_dev, source_stat.st_ino):
            raise ValueError("preselection source root identity changed while locking")
        for root, lease in leases.items():
            assert_owned_interprocess_lock(lease, root / ".import.lock")
        yield leases[source]
