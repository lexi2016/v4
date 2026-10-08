"""Run the bounded synthetic auction regression from a frozen repository tree.

This assembles historic support in a temporary directory. It does not import or
run the full API app, real collectors, Stage runner, schedulers or live data.
The explicit namespace substitution in SUPPORT_INDEX.json remains TEST SUPPORT.
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
import tempfile


HERE = Path(__file__).resolve().parent


def checked_bytes(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(f"source SHA mismatch: {path}; expected {expected}; got {actual}")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True,
                        help="Checkout or sparse source cache of frozen commit 00524e9050fe212f87911b56eea1c2db719dd94b")
    parser.add_argument("--owner", choices=("canonical", "active_stage_reference"), required=True)
    parser.add_argument("--phase", choices=("before", "after"), required=True)
    parser.add_argument("--log-root", type=Path, required=True)
    parser.add_argument("--without-namespace-support", action="store_true",
                        help="Reproduce the supplied source closure import failure instead of substituting the test helper")
    options = parser.parse_args()
    repository = options.repo_root.resolve()
    support = json.loads((HERE / "SUPPORT_INDEX.json").read_text())
    changes = json.loads((HERE / "CHANGE_MANIFEST.json").read_text())["changes"]
    options.log_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="issue28-auction-import-test-") as temporary:
        assembly = Path(temporary)
        identities = []
        for item in support["files"]:
            if options.without_namespace_support and "TEST SUPPORT substitution" in item["role"]:
                continue
            data = checked_bytes(repository / item["repository_path"], item["sha256"])
            destination = assembly / item["target"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            identities.append(item)
        for item in changes:
            if item["source_owner"] != options.owner:
                continue
            if options.phase == "before":
                source = repository / "handoff/stage-selection-issues-20261008" / item["before_package_path"]
                data = checked_bytes(source, item["before_sha256"])
            else:
                source = HERE / item["after_path"]
                data = checked_bytes(source, item["after_sha256"])
            destination = assembly / item["relative_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            identities.append({"source": str(source), "target": item["relative_path"],
                               "sha256": hashlib.sha256(data).hexdigest(), "role": options.owner + " " + options.phase})
        api = support["api_reference"]
        api_path = repository / api["repository_path"]
        checked_bytes(api_path, api["sha256"])
        environment = dict(os.environ, PYTHONPATH=str(assembly), PYTHONDONTWRITEBYTECODE="1",
                           ISSUE28_API_REFERENCE=str(api_path))
        if options.without_namespace_support:
            command = [sys.executable, "-c", "from stage_center.live_collectors import production_selection_builders; from stage_center.selection import SelectionStore"]
        else:
            command = [sys.executable, "-m", "pytest", "-vv", str(HERE / "tests"), "--tb=short", "-p", "no:cacheprovider"]
        result = subprocess.run(command, cwd=assembly, env=environment, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        suffix = "_missing_namespace" if options.without_namespace_support else ""
        stem = f"{options.owner}_{options.phase}{suffix}"
        log = options.log_root / f"{stem}.log"
        log.write_text(result.stdout)
        receipt = {
            "scope": "SOURCE_IMPORT_AND_PERSISTENCE_HARNESS; API_PROJECTION_AST_PARTIAL; NOT_FULL_APP_OR_ACTIVE_RUNTIME",
            "frozen_commit": support["frozen_commit"], "owner": options.owner,
            "phase": options.phase, "python": sys.version, "platform": platform.platform(),
            "command": command, "cwd": str(assembly), "PYTHONPATH": str(assembly),
            "api_reference": api, "namespace_substitution_used": not options.without_namespace_support,
            "source_identities": identities,
            "test_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (HERE / "tests").glob("*.py")},
            "exit_code": result.returncode, "raw_log": str(log.resolve()),
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }
        (options.log_root / f"{stem}.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(result.stdout)
        print(json.dumps({"exit_code": result.returncode, "raw_log": str(log.resolve())}))
        raise SystemExit(result.returncode)
