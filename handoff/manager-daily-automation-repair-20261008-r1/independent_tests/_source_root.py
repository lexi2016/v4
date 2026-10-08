"""Resolve the checkout used by independent reviewer probes.

Set ``MANAGER_TEST_SOURCE_ROOT`` to the absolute source checkout path when
running these tests outside the original workspace. In the original problem
bundle, the worktree sibling is discovered automatically.
"""
from __future__ import annotations

import os
from pathlib import Path


def source_root(test_file: str) -> Path:
    configured = os.environ.get("MANAGER_TEST_SOURCE_ROOT")
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if not (candidate / "v4" / "manager_research").is_dir():
            raise RuntimeError(
                "MANAGER_TEST_SOURCE_ROOT must point to the manager_automation source root"
            )
        return candidate

    file_path = Path(test_file).resolve()
    candidates = [
        file_path.parents[3] / "worktrees" / "manager_automation",
        Path.cwd(),
    ]
    for candidate in candidates:
        candidate = candidate.resolve()
        if (candidate / "v4" / "manager_research").is_dir():
            return candidate
    raise RuntimeError(
        "could not discover the manager_automation checkout; set "
        "MANAGER_TEST_SOURCE_ROOT=/absolute/path/to/source"
    )
