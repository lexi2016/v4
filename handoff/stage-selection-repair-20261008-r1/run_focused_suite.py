"""Run only the supplied synthetic source-candidate tests in subprocesses.

Requires Python >=3.14 plus the recorded test dependencies. This is not an app
launcher and does not execute any real collector, Stage slot or host service.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-root", type=Path, required=True)
    args = parser.parse_args()
    if sys.version_info < (3, 14):
        raise SystemExit("Python >=3.14 is required; use the complete Mac candidate for host acceptance")
    root = Path(__file__).resolve().parent
    logs = args.log_root.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    frozen = root / "test_support/frozen_repo"
    baseline = frozen / "handoff/stage-selection-issues-20261008/source"
    commands = [
        ("auction_canonical", [sys.executable, str(root / "auction/reproduce.py"),
            "--repo-root", str(frozen), "--owner", "canonical", "--phase", "after",
            "--log-root", str(logs / "auction_canonical")]),
        ("auction_active_stage", [sys.executable, str(root / "auction/reproduce.py"),
            "--repo-root", str(frozen), "--owner", "active_stage_reference", "--phase", "after",
            "--log-root", str(logs / "auction_active_stage")]),
        ("hk_split_dates", [sys.executable, str(root / "hk/tests/run_focused.py"),
            "--issue-root", str(root), "--baseline-root", str(baseline),
            "--owner-root", str(root / "hk/after/active_producer_reference"),
            "--support-root", str(root / "hk/test_support")]),
        ("release_existing", [sys.executable, str(root / "release/tests/run_existing_suites.py")]),
        ("release_p1", [sys.executable, str(root / "release/tests/test_release_regressions.py")]),
        ("pool_route_storage", [sys.executable, str(root / "pool/isolated/run_route_tests.py")]),
    ]
    records = []
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    # Do not let an invoking shell redirect the release tests onto another tree.
    environment.pop("RELEASE_SOURCE_ROOT", None)
    for name, command in commands:
        result = subprocess.run(command, cwd=root, env=environment, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        path = logs / f"{name}.log"
        path.write_text(result.stdout)
        record = {"name": name, "command": command, "exit_code": result.returncode,
                  "log": str(path), "log_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        records.append(record)
        print(json.dumps({"name": name, "exit_code": result.returncode, "log": str(path)}), flush=True)
    receipt = {"scope": "SYNTHETIC_SOURCE_CANDIDATE_ONLY", "python": sys.version,
               "platform": platform.platform(), "commands": records,
               "full_active_app": "NOT_RUN", "mac": "NOT_RUN", "live_api_ui": "NOT_RUN",
               "natural_slot": "NOT_RUN", "deployment": "NOT_RUN",
               "passed": all(row["exit_code"] == 0 for row in records)}
    (logs / "results.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
