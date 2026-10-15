#!/usr/bin/env python3
"""Explicitly gated scheduler rollback entrypoint; default behavior is plan-only."""
from scheduler_release_cutover import main


if __name__ == "__main__":
    raise SystemExit(main("rollback"))
