"""Canonical path contract for a claimed QFQ return root and generation run."""
from __future__ import annotations

import re
from pathlib import Path

_GENERATION = re.compile(r"[0-9a-f]{64}\Z")


def _canonical_directory(value: str, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}_PATH_REQUIRED")
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts or str(path) != value):
        raise ValueError(f"{label}_PATH_NOT_CANONICAL")
    try:
        if not path.is_dir() or path.resolve(strict=True) != path:
            raise ValueError(f"{label}_PATH_NOT_CANONICAL")
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError(f"{label}_PATH_SYMLINK")
    except OSError as exc:
        raise ValueError(f"{label}_PATH_UNAVAILABLE") from exc
    return path


def validate_qfq_generation_directory(return_root: str, run_dir: str,
                                      generation_id: str) -> tuple[Path, Path]:
    """Require `run_dir` to be the exact generation child of the claimed root.

    A registry row stores the stable `return_root`; QFQ receipts point to the
    concrete `qfq_<generation-prefix>` child. Both must be real canonical
    directories with no symlink component.
    """
    if not isinstance(generation_id, str) or not _GENERATION.fullmatch(generation_id):
        raise ValueError("QFQ_GENERATION_ID_INVALID")
    root = _canonical_directory(return_root, "QFQ_RETURN_ROOT")
    run = _canonical_directory(run_dir, "QFQ_RUN_DIR")
    expected = root / ("qfq_" + generation_id[:20])
    if run.parent != root or run != expected:
        raise ValueError("QFQ_RUN_DIRECTORY_GENERATION_BINDING")
    return root, run
