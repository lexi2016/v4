"""Record fresh before/after commands, stdout, exit codes and source identities."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from assemble_support import BUNDLE, assemble


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--owner", choices=("canonical", "active_stage_reference"), required=True)
    parser.add_argument("--output", type=Path, default=BUNDLE / "logs")
    options = parser.parse_args()
    options.output = options.output.resolve()
    options.output.mkdir(parents=True, exist_ok=True)
    stem = f"{options.owner}_{options.phase}"
    with tempfile.TemporaryDirectory(prefix=f"issue28-auction-{stem}-") as temporary:
        runroot = assemble(options.owner, options.phase, Path(temporary) / "runroot")
        (options.output / f"{stem}.sources.json").write_bytes((runroot / "HARNESS_MANIFEST.json").read_bytes())
        environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(runroot), str(BUNDLE))),
                           PYTHONDONTWRITEBYTECODE="1", ISSUE28_OWNER=options.owner,
                           ISSUE28_PHASE=options.phase)
        xml = options.output / f"{stem}.xml"
        command = [sys.executable, "-m", "pytest", "-vv", "-p", "no:cacheprovider",
                   str(BUNDLE / "tests"), "--tb=short", f"--junitxml={xml}"]
        completed = subprocess.run(command, cwd=BUNDLE, env=environment, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        log = options.output / f"{stem}.log"
        log.write_text(completed.stdout)
        counts = {}
        if xml.exists():
            suite = ET.parse(xml).getroot()
            for field in ("tests", "failures", "errors", "skipped"):
                counts[field] = sum(int(item.attrib.get(field, 0)) for item in suite.findall("testsuite"))
        metadata = {
            "phase": options.phase, "owner": options.owner,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "command": command, "cwd": str(BUNDLE), "PYTHONPATH": environment["PYTHONPATH"],
            "python": sys.version, "platform": platform.platform(),
            "exit_code": completed.returncode, "counts": counts,
            "raw_log": log.name, "source_manifest": f"{stem}.sources.json",
            "scope": "FROZEN_SOURCE_IMPORTS_PERSISTENCE_AND_IN_PROCESS_EXACT_ROUTE_HTTP",
            "full_current_owner_app": "NOT_RUN", "original_mac_python_3_14_6": "NOT_RUN",
            "live_api_8873": "NOT_RUN", "ui": "NOT_RUN", "natural_slot": "NOT_RUN",
            "namespace_substitution": "historic API read_global helper used for missing Stage namespace",
        }
        (options.output / f"{stem}.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(completed.stdout, end="")
        print(json.dumps({"exit_code": completed.returncode, "counts": counts, "raw_log": str(log)}))
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
