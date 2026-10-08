#!/usr/bin/env python3
"""Replay and reverse both source patches only in disposable directories."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CASES = (
    (
        "historical_source_date_upper_bound",
        "infrastructure/preselection_pool_store.py",
        "historical_validation/before/infrastructure/preselection_pool_store.py",
        "historical_validation/after/infrastructure/preselection_pool_store.py",
        "historical_validation/historical_date_upper_bound.patch",
    ),
    (
        "close_source_pit_warning",
        "ops/build_close_review.py",
        "close_pit/before/canonical/ops/build_close_review.py",
        "close_pit/after/canonical/ops/build_close_review.py",
        "close_pit/close_pit.patch",
    ),
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = []
    for name, owner_path, before_path, after_path, patch_path in CASES:
        before = (ROOT / before_path).read_bytes()
        after = (ROOT / after_path).read_bytes()
        patch = ROOT / patch_path
        with tempfile.TemporaryDirectory(prefix="issue28-p2-patch-") as temp:
            root = Path(temp)
            target = root / owner_path
            target.parent.mkdir(parents=True)
            target.write_bytes(before)
            commands = []
            for reverse, expected in ((False, after), (True, before)):
                command = ["patch", "-t", "-F", "0", "-p1", "-i", str(patch)]
                if reverse:
                    command.append("-R")
                result = subprocess.run(command, cwd=root, text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                commands.append({
                    "direction": "reverse" if reverse else "forward",
                    "command": command,
                    "exit_code": result.returncode,
                    "output": result.stdout,
                    "exact_expected_bytes": target.read_bytes() == expected,
                })
                if result.returncode or target.read_bytes() != expected:
                    break
            records.append({
                "name": name, "owner_relative_path": owner_path,
                "before_sha256": digest(before), "after_sha256": digest(after),
                "patch_sha256": digest(patch.read_bytes()), "runs": commands,
                "passed": len(commands) == 2 and all(
                    item["exit_code"] == 0 and item["exact_expected_bytes"] for item in commands
                ),
            })
    report = {
        "scope": "TEMPORARY_SOURCE_PATCH_REPLAY_ONLY",
        "python": sys.version, "platform": platform.platform(),
        "records": records, "passed": all(item["passed"] for item in records),
        "Mac_or_business_data_access": False,
    }
    content = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
