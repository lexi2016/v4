#!/usr/bin/env python3
"""Cold-process, synthetic-data checks against complete SHA-matched canaries.

The normal Mac invocation does not install the archive-only raw signature
adapter. The explicit reference option exists solely to reproduce the Linux
archive test record; it cannot be called a complete current-source acceptance.
"""
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

from stage_patch import inspect

PACKAGE = Path(__file__).resolve().parents[1]


def code_inventory(roots):
    """Record every candidate code file so a test cannot silently replace support."""
    records = {}
    omitted = {"node_modules", ".git", "__pycache__", ".pytest_cache", ".venv", "venv", "dist"}
    for role, root in roots.items():
        for directory, children, names in os.walk(root, followlinks=False):
            children[:] = sorted(name for name in children if name not in omitted)
            for name in sorted(names):
                path = Path(directory) / name
                if path.suffix not in {".py", ".vue", ".ts", ".js", ".mjs", ".cjs"}:
                    continue
                data = path.read_bytes()
                records[role + "/" + path.relative_to(root).as_posix()] = {
                    "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--stage-role", choices=("actual_stage", "canonical_stage"), default="actual_stage")
    parser.add_argument("--api-root", type=Path, required=True)
    parser.add_argument("--ui-runtime", type=Path, required=True, help="directory whose node_modules contains the existing Vue/compiler/server-renderer")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--allow-archived-signature-test-support", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((PACKAGE / "SOURCE_MAP.json").read_text())
    identities = [inspect(args.stage_root.resolve(strict=True), manifest["roles"][args.stage_role], final=True),
                  inspect(args.api_root.resolve(strict=True), manifest["roles"]["actual_api"], final=True)]
    if any(item["status"] != "MATCH" for item in identities):
        print(json.dumps({"status": "SOURCE_MISMATCH", "identities": identities}, ensure_ascii=False, indent=2))
        return 2
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    roots = {args.stage_role: args.stage_root.resolve(), "actual_api": args.api_root.resolve()}
    before_inventory = code_inventory(roots)
    (output / "CANDIDATE_CODE_BEFORE.json").write_text(json.dumps(before_inventory, indent=2) + "\n")
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
        V4_HK_TEST_RUNTIME=str(args.stage_root.resolve()),
        V4_RECEIPT_TEST_RUNTIME=str(args.stage_root.resolve()),
        V4_TEST_RUNTIME_ROOT=str(args.stage_root.resolve()),
        V4_API_TEST_RUNTIME=str(args.stage_root.resolve()),
        V4_COLLECTORS_PHASE="after", V4_COLLECTORS_VARIANT="canonical" if args.stage_role=="canonical_stage" else "actual_stage",
        STAGE_UI_RUNTIME=str(args.ui_runtime.resolve()),
        V4_RAW_SIGNATURE_SUPPORT="strict_false" if args.allow_archived_signature_test_support else "disabled")
    if args.node:
        environment["PATH"] = str(args.node.absolute().parent) + os.pathsep + environment.get("PATH", "")
    suites = {
        "hk_runner": PACKAGE / "components/hk/tests/test_hk_current_day_research.py",
        "collectors": PACKAGE / "components/collectors/tests",
        "source_and_owner": PACKAGE / "components/receipt/tests/test_runtime_source_identity.py",
        "api_vue": PACKAGE / "components/api_ui/tests",
        "canary_tools": PACKAGE / "tests",
    }
    runs = []
    for name, tests in suites.items():
        target = output / name
        target.mkdir()
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tests),
                   "--junitxml=" + str(target / "junit.xml")]
        start = datetime.now(timezone.utc).isoformat()
        process = subprocess.run(command, env=environment, capture_output=True, text=True, cwd=PACKAGE)
        (target / "stdout.log").write_text(process.stdout)
        (target / "stderr.log").write_text(process.stderr)
        counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
        if (target / "junit.xml").is_file():
            for suite in ET.parse(target / "junit.xml").getroot().iter("testsuite"):
                for key in counts:
                    counts[key] += int(suite.attrib.get(key, 0))
        run = {"suite": name, "command": command, "started_at": start,
               "finished_at": datetime.now(timezone.utc).isoformat(), "exit_code": process.returncode, **counts}
        runs.append(run)
        print(json.dumps(run), flush=True)
    after_inventory = code_inventory(roots)
    (output / "CANDIDATE_CODE_AFTER.json").write_text(json.dumps(after_inventory, indent=2) + "\n")
    changed_code = sorted(key for key in set(before_inventory) | set(after_inventory)
                          if before_inventory.get(key) != after_inventory.get(key))
    final_identities = [inspect(args.stage_root.resolve(strict=True), manifest["roles"][args.stage_role], final=True),
                        inspect(args.api_root.resolve(strict=True), manifest["roles"]["actual_api"], final=True)]
    report = {
        "schema_version": "v4.stage.r2.independent_rerun.v1",
        "status": "PASS" if all(x["exit_code"]==0 for x in runs) and not changed_code
                  and all(x["status"]=="MATCH" for x in final_identities) else "FAIL",
        "runs": runs, "source_identities": identities, "stage_role": args.stage_role,
        "final_source_identities": final_identities,
        "candidate_code_unchanged_during_tests": not changed_code,
        "changed_code_files": changed_code,
        "candidate_code_file_count": len(before_inventory),
        "source_map_sha256": hashlib.sha256((PACKAGE / "SOURCE_MAP.json").read_bytes()).hexdigest(),
        "python": sys.version, "platform": platform.platform(),
        "synthetic_provider_data": True, "real_provider_network_calls": 0,
        "actual_hk_snapshot_read": False,
        "archived_raw_signature_test_adapter": args.allow_archived_signature_test_support,
        "full_mac_service_acceptance": False, "natural_verified": False,
    }
    (output / "TEST_RECEIPT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
