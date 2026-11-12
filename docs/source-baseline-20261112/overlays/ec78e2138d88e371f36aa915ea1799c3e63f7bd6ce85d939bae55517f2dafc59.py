"""File-only scheduler entry; importing it never registers a task or service."""

from __future__ import annotations

from .scheduler import main, run_once

__all__ = ["main", "run_once"]


if __name__ == "__main__":
    raise SystemExit(main())

