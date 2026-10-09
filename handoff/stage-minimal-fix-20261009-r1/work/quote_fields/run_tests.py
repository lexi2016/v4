"""Run the portable source-slice suite, preserving raw results and source pins."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), default="after")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, STAGE_QUOTE_PHASE=args.phase)
    command = [sys.executable, "-m", "pytest", "--junitxml=" + str(output / "junit.xml")]
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    (output / "stdout.log").write_text(process.stdout)
    (output / "stderr.log").write_text(process.stderr)
    fingerprints = []
    for directory in (root / args.phase, root / "support", root / "before"):
        for path in sorted(directory.rglob("*.py")):
            data = path.read_bytes()
            entry = {"path": str(path.relative_to(root)), "bytes": len(data),
                     "sha256": hashlib.sha256(data).hexdigest()}
            if entry not in fingerprints:
                fingerprints.append(entry)
    metadata = {"phase": args.phase, "command": command, "cwd": str(root),
                "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
                "exit_code": process.returncode, "python": sys.version, "platform": platform.platform(),
                "scope": "ACTUAL_SELECTOR_SLICES_WITH_HISTORICAL_SUPPORT_AND_TEST_NAMESPACE_SEAMS",
                "full_actual_owner_import": "NOT_RUN", "mac": "NOT_RUN", "api_ui": "NOT_RUN",
                "natural": "NOT_RUN", "source_files": fingerprints}
    (output / "execution.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, end="", file=sys.stderr)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
