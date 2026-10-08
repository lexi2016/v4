#!/usr/bin/env python3
"""Replay before/after regressions in new temporary source and data directories.

No runtime root, launchd, API, network, package installation, or deployment is
used. The original suite retains its known failures and nonzero exit code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT.parent
RELATIVE = Path("stage_center/_runner_parts/hk_input_validation.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs():
    manifest = json.loads((ROOT / "INPUT_MANIFEST.json").read_text())
    seen = set()
    for entry in manifest["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or entry["path"] in seen:
            raise ValueError("input path is not a unique bundle-relative path")
        seen.add(entry["path"])
        path = (BUNDLE / relative).resolve()
        if not path.is_relative_to(BUNDLE) or not path.is_file():
            raise ValueError("input path is missing or outside this bundle")
        raw = path.read_bytes()
        if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"frozen input SHA/size mismatch: {entry['path']}")
    expected_support = {entry["path"] for entry in manifest["files"]
                        if entry["path"].startswith("harness/support/")}
    actual_support = set()
    for path in (ROOT / "support").rglob("*"):
        if path.is_symlink():
            raise ValueError("supplemental imports cannot use symlinks")
        if path.is_file():
            actual_support.add(str(path.relative_to(BUNDLE)))
    if actual_support != expected_support:
        raise ValueError("supplemental import inventory differs from its allowlist")
    candidates = json.loads((BUNDLE / "candidate_identity.json").read_text())
    if candidates.get("schema_version") != "issue28.hk_stage_candidate_identity.v1":
        raise ValueError("candidate identity schema mismatch")
    identities = {entry["owner"]: entry for entry in candidates["files"]}
    if set(identities) != {"canonical", "actual_stage_owner"} or len(candidates["files"]) != 2:
        raise ValueError("exact two owner candidates required")
    for owner, entry in identities.items():
        before = BUNDLE / "input/source" / owner / RELATIVE
        after = BUNDLE / "after" / RELATIVE
        if (entry["path"] != str(RELATIVE) or sha(before) != entry["before_sha256"]
                or sha(after) != entry["after_sha256"]):
            raise ValueError("candidate before/after identity mismatch")
    return manifest, identities


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", choices=("actual_stage_owner", "canonical", "both"), default="both")
    parser.add_argument("--phase", choices=("before", "after"), default="after")
    parser.add_argument("--suite", choices=("targeted", "original", "all"), default="targeted")
    parser.add_argument("--output-dir", type=Path, help="Parent for a new isolated run; defaults to the system temp directory")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11+ is required by the original Stage StrEnum imports")
    manifest, identities = verify_inputs()
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix=f"issue28-hk-{args.phase}-", dir=args.output_dir)).resolve()
    owners = ["actual_stage_owner", "canonical"] if args.owner == "both" else [args.owner]
    suites = ["targeted", "original"] if args.suite == "all" else [args.suite]
    results = []
    for owner in owners:
        app = run / owner / "app"
        # Only copy the thirteen declared source files. An old initializer left
        # in an unpacked input directory must never become executable support.
        app.mkdir(parents=True)
        prefix = f"input/source/{owner}/"
        owner_entries = [entry for entry in manifest["files"] if entry["path"].startswith(prefix)]
        if len(owner_entries) != 13:
            raise ValueError("exact thirteen-file owner slice required")
        for entry in owner_entries:
            destination = app / entry["path"][len(prefix):]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(BUNDLE / entry["path"], destination)
        if args.phase == "after":
            shutil.copy2(BUNDLE / "after" / RELATIVE, app / RELATIVE)
        expected = {}
        for entry in manifest["files"]:
            prefix = f"input/source/{owner}/"
            if entry["path"].startswith(prefix):
                expected["app/" + entry["path"][len(prefix):]] = entry["sha256"]
            elif entry["path"].startswith("harness/support/"):
                expected[entry["path"].removeprefix("harness/")] = entry["sha256"]
        if args.phase == "after":
            expected["app/" + str(RELATIVE)] = identities[owner]["after_sha256"]
        expected_file = run / owner / "IMPORT_EXPECTATIONS.json"
        expected_file.write_text(json.dumps(expected, indent=2) + "\n")
        for suite in suites:
            log_root = run / owner / suite
            log_root.mkdir()
            tests = (["tests/test_hk_split_date_identity_closure.py", "tests/test_root_identity_probe.py"]
                     if suite == "targeted" else ["tests/test_hk_prior_observation_source_binding.py"])
            xml = log_root / "junit.xml"
            command = [sys.executable, "-B", "-m", "pytest", "-q", "-ra", "-p", "no:cacheprovider",
                       "-c", str(ROOT / "pytest.ini"), f"--confcutdir={ROOT}",
                       f"--basetemp={log_root / 'data'}", f"--junitxml={xml}", *tests]
            env = {**os.environ, "PYTHONPATH": "", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "ISSUE28_TEST_OWNER": owner,
                   "ISSUE28_TEST_PHASE": args.phase, "ISSUE28_TEST_APP": str(app),
                   "ISSUE28_TEST_IMPORT_EXPECTATIONS": str(expected_file),
                   "ISSUE28_TEST_IMPORT_LOG": str(log_root / "imports.json")}
            env.pop("PYTEST_ADDOPTS", None)
            env.pop("PYTEST_PLUGINS", None)
            process = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
            (log_root / "pytest.log").write_text(process.stdout)
            cases = ET.parse(xml).getroot().findall(".//testcase") if xml.exists() else []
            failures = [case.get("name") for case in cases if case.find("failure") is not None]
            errors = [case.get("name") for case in cases if case.find("error") is not None]
            skipped = [case.get("name") for case in cases if case.find("skipped") is not None]
            result = {"owner": owner, "phase": args.phase, "suite": suite,
                      "command": command, "cwd": str(ROOT), "exit_code": process.returncode,
                      "cases": len(cases), "passed": len(cases) - len(failures) - len(errors) - len(skipped),
                      "failures": failures, "errors": errors, "skipped": skipped,
                      "candidate_file_sha256": sha(app / RELATIVE), "log_root": str(log_root)}
            results.append(result)
            print(json.dumps(result), flush=True)
        for relative, expected_sha in expected.items():
            path = (app / relative.removeprefix("app/") if relative.startswith("app/")
                    else ROOT / relative)
            if sha(path) != expected_sha:
                raise ValueError("source changed during test execution")
    verify_inputs()
    report = {"recorded_at": datetime.now(timezone.utc).isoformat(),
              "python": sys.version, "python_executable": sys.executable,
              "platform": platform.platform(), "pytest": importlib.metadata.version("pytest"),
              "results": results, "run_directory": str(run),
              "scope": "ISOLATED_SOURCE_SLICES_WITH_PINNED_SUPPLEMENTS_NOT_FULL_MAC_RUNTIME",
              "runtime_recovery_status": "CANNOT_CONFIRM"}
    (run / "RESULTS.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(run / "RESULTS.json"), "runtime_recovery_status": "CANNOT_CONFIRM"}))
    return max(item["exit_code"] for item in results)


if __name__ == "__main__":
    raise SystemExit(main())
