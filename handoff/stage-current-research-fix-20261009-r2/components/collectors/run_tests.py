"""Capture one portable, offline collector regression run with code identities."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after"), default="after")
    parser.add_argument("--variant", choices=("actual_stage", "canonical"), default="actual_stage")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    component_source_root = root / "canonical" if args.variant == "canonical" else root
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, V4_COLLECTORS_PHASE=args.phase, V4_COLLECTORS_VARIANT=args.variant)
    if args.runtime_root is not None:
        runtime = args.runtime_root.resolve()
        for source in (component_source_root / args.phase).rglob("*.py"):
            target = runtime / source.relative_to(component_source_root / args.phase)
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                raise SystemExit(f"canary source mismatch: {target}; apply the reviewed patch first")
        if not (runtime / "stage_center/hk_current_day_research.py").is_file():
            raise SystemExit("canary missing stage_center/hk_current_day_research.py")
        environment["V4_TEST_RUNTIME_ROOT"] = str(runtime)
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests", "--junitxml=" + str(output / "junit.xml")]
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
    (output / "stdout.log").write_text(process.stdout)
    (output / "stderr.log").write_text(process.stderr)
    suites = ET.parse(output / "junit.xml").getroot().iter("testsuite") if (output / "junit.xml").is_file() else ()
    counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.attrib.get(key, 0))
    files = []
    for folder in (component_source_root / args.phase, root / "tests", root / "support"):
        for path in sorted(folder.rglob("*.py")):
            files.append({"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    receipt = {"command": command, "cwd": str(root), "phase": args.phase, "variant": args.variant,
        "runtime_root": environment.get("V4_TEST_RUNTIME_ROOT", "PINNED_RUNTIME_BEFORE_WITH_COMPONENT_OVERLAYS"),
        "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": process.returncode, "python": sys.version, "platform": platform.platform(),
        **counts, "source_files": files,
        "scope": "SYNTHETIC_PROVIDER_RESPONSES_NATIVE_NORMALIZATION_SOURCE_BUILDER_SELECTORS_STORES_AND_REAL_WITNESS_VALIDATOR",
        "mac": "NOT_RUN", "provider_network_calls": 0, "real_user_snapshot_read": False,
        "api_ui": "NOT_RUN", "natural_execution": "NOT_RUN"}
    (output / "execution.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, end="", file=sys.stderr)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
