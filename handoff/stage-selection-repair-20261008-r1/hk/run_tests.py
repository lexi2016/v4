#!/usr/bin/env python3
"""Replay this isolated HK repair; never starts a scheduler or collects data."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


PACKAGE = Path(__file__).resolve().parent
BEFORE_FOCUS = (
    "actual_materializer_to_unchanged or actual_cli_forwards or "
    "legacy_scheduler_call or frozen_baseline_reproduces or legacy_equal_dates"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_files() -> int:
    inventory = json.loads((PACKAGE / "SOURCE_IDENTITIES.json").read_text())
    for entry in inventory["files"]:
        path = PACKAGE / entry["path"]
        if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise RuntimeError(f"packaged source drift: {entry['path']}")
    return len(inventory["files"])


def replay_patch() -> None:
    with tempfile.TemporaryDirectory(prefix="issue28_hk_patch_") as directory:
        root = Path(directory)
        before = PACKAGE / "before/active_producer_reference"
        after = PACKAGE / "after/active_producer_reference"
        shutil.copytree(before, root, dirs_exist_ok=True)
        patch = PACKAGE / "hk_split_date.patch"
        for reverse, expected in ((False, after), (True, before)):
            arguments = ["git", "apply", *(["--reverse"] if reverse else [])]
            subprocess.run([*arguments, "--check", str(patch)], cwd=root, check=True, capture_output=True)
            subprocess.run([*arguments, str(patch)], cwd=root, check=True, capture_output=True)
            for source in expected.rglob("*.py"):
                if (root / source.relative_to(expected)).read_bytes() != source.read_bytes():
                    raise RuntimeError("patch replay did not reproduce exact source bytes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "before", "after"), default="all")
    parser.add_argument("--log-dir", type=Path, default=None)
    args = parser.parse_args()
    output = args.log_dir or Path(tempfile.mkdtemp(prefix="issue28_hk_results_"))
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "scope": "OFFLINE_SYNTHETIC_OWNER_ADAPTER_AND_UNCHANGED_VALIDATOR_BODY",
        "python_executable": sys.executable,
        "python_executable_resolved": str(Path(sys.executable).resolve()),
        "python_version": sys.version,
        "pytest_version": version("pytest"),
        "python_base_prefix": sys.base_prefix,
        "platform": platform.platform(),
        "verified_file_count": verify_files(),
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "runs": [],
    }
    replay_patch()
    report["forward_reverse_patch_replay"] = "PASS"
    env = dict(os.environ)
    env.update(
        HK_BEFORE_OWNER_ROOT=str(PACKAGE / "before/active_producer_reference"),
        HK_SUPPORT_ROOT=str(PACKAGE / "support/canonical"),
        HK_FROZEN_ROOT=str(PACKAGE / "support/frozen"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    modes = ("before", "after") if args.mode == "all" else (args.mode,)
    for mode in modes:
        env["HK_OWNER_ROOT"] = str(PACKAGE / mode / "active_producer_reference")
        command = [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            str(PACKAGE / "tests/test_hk_split_date_binding.py"),
        ]
        if mode == "before":
            command.extend(["-k", BEFORE_FOCUS])
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        log = output / f"{mode}.log"
        log.write_text(
            json.dumps({"command": command, "environment": {key: value for key, value in env.items() if key.startswith("HK_") or key == "PYTHONDONTWRITEBYTECODE"}}, indent=2)
            + "\n" + result.stdout + result.stderr,
            encoding="utf-8",
        )
        summary = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "NO_STDOUT"
        expected = (result.returncode == 1 and "3 failed, 2 passed" in summary) if mode == "before" else result.returncode == 0
        report["runs"].append({
            "mode": mode, "exit_code": result.returncode,
            "expected_result_observed": expected, "summary": summary,
            "log": str(log), "log_sha256": sha256(log),
        })
        print(f"{mode}: {summary}")
    result_path = output / "RESULTS.json"
    result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result_path)
    return 0 if all(run["expected_result_observed"] for run in report["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
