"""Reproduce the offline HK test; all target files live under pytest temp roots."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path)
    parser.add_argument("--owner-root", type=Path, required=True)
    parser.add_argument("--support-root", type=Path, required=True)
    parser.add_argument("--baseline-focus", action="store_true")
    args = parser.parse_args()
    env = os.environ.copy()
    env.update(
        HK_ISSUE_ROOT=str(args.issue_root.resolve()),
        HK_BASELINE_ROOT=str((args.baseline_root or args.issue_root / "baseline/source").resolve()),
        HK_OWNER_ROOT=str(args.owner_root.resolve()),
        HK_SUPPORT_ROOT=str(args.support_root.resolve()),
    )
    command = [sys.executable, "-m", "pytest", "-q", str(Path(__file__).with_name("test_hk_split_date_binding.py")), "--tb=short"]
    if args.baseline_focus:
        command += ["-k", "actual_materializer_to or actual_cli_forwards or legacy_equal_dates or frozen_baseline_reproduces"]
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
