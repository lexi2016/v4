"""Minimal entrypoint; run from existing repo environment (PYTHONPATH=.)."""
from v4.manager_workbench.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

