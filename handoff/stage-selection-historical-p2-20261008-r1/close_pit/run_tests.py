"""Run the bounded close-PIT regression and retain stdout/exit/environment."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from harness import ROOT, prepare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "logs")
    args = parser.parse_args()
    if args.worker:
        prepare(args.phase)
        import pytest
        raise SystemExit(pytest.main(["-vv", "-p", "no:cacheprovider", "--tb=short",
                                     str(ROOT / "tests"), f"--junitxml={args.output / (args.phase + '.xml')}"]))
    args.output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--phase", args.phase,
               "--output", str(args.output.resolve())]
    result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (args.output / f"{args.phase}.log").write_text(result.stdout)
    (args.output / f"{args.phase}.json").write_text(json.dumps({
        "command": command, "cwd": str(ROOT), "exit_code": result.returncode,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "platform": platform.platform(),
        "scope": "FROZEN_PRODUCER_DOMAIN_REAL_STORES_SYNTHETIC_FIXTURES",
        "stage_consumer": "NOT_RUN; explicit unused-import sentinel",
        "actual_20260825_artifact": "NOT_SUPPLIED", "full_owner_app": "NOT_RUN",
        "Mac_API_UI_natural_slot": "NOT_RUN", "business_data_or_services_changed": False,
    }, indent=2) + "\n")
    print(result.stdout, end="")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
