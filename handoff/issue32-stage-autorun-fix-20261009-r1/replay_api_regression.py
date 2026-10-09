#!/usr/bin/env python3
"""Replay Issue 32 API tests using the immutable Issue 30 offline runner.

Test-only: writes a new output directory, never starts a real service or
changes either source package. Historical fixtures are not runtime inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types


ISSUE30_RUNNER_SHA = "73069ef34a74a5eddb47ccaab59ab142a7e518841511441e3e20016770811409"
ISSUE30_INPUTS_SHA = "7f846c242af93aac814456a9567d10eec1b18915601791b01c326774ecdd8a2e"
PINS = {
    "after/source/actual_api/apps/api/v35_api/preselection_service.py": "cbed3aa4797889051eb7bebe4b8e3240b568d72b4dfb5c20f65e914d39e48044",
    "tests/test_api_same_date.py": "0a3c6b55e0e09aa0fa6642a047c197baed1ceb44e3583b82a9db8357ffd7ec63",
    "tests/api_support/contracts/trading_calendar.py": "eca22a1e45271df45fc0a3b7cec28cec4e448d1af97b80371cc5c3c1953ec0f1",
    "tests/api_support/contracts/market_calendar_2026.json": "9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb",
    "evidence/api/legacy_exact_date_fixture.patch": "7eadb54f472d173971828a4d1763b9f311e467c01d829408f4725d9d66524d48",
    "evidence/api/legacy_exact_date_fixture.json": "71b6741be25d06b0e5eb3ae3c0e297aad1b60f1ec5dc03a2fb6ecc0c48dab4b4",
}
FIXTURE_BEFORE = "d1e605f9f6d4a0a024a4d104f8cd5dddc9fbbe154914ab4eae76107586c5cc75"
FIXTURE_AFTER = "93e43d4515c8874e83f2066e10912d3a7ebb880f3ace2a9b51f9aaeb397afec5"
COMPOSITION = "29 unchanged regression cases + 1 corrected date fixture + 42 new helper cases"


def checked(raw: bytes, digest: str, label: str) -> bytes:
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("INPUT_SHA_MISMATCH:" + label)
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue30-package", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--python", required=True)
    args = parser.parse_args()
    issue32 = Path(__file__).resolve().parent
    issue30 = Path(args.issue30_package)
    runner_path = issue30 / "run_tests.py"
    runner_raw = checked(runner_path.read_bytes(), ISSUE30_RUNNER_SHA, "Issue30/run_tests.py")
    # Execute the verified bytes, avoiding a second loader read of the file.
    runner = types.ModuleType("issue30_verified_offline_runner")
    runner.__file__ = str(runner_path)
    exec(compile(runner_raw, str(runner_path), "exec"), runner.__dict__)
    issue30 = runner.absolute_path(args.issue30_package)
    output = runner.absolute_path(args.output_root)
    python = runner.absolute_path(args.python)
    for package in (issue30, issue32):
        if output == package or package in output.parents or output in package.parents:
            raise ValueError("OUTPUT_MUST_BE_NEW_AND_OUTSIDE_SOURCE_PACKAGES")
    if not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("PYTHON_EXECUTABLE_UNAVAILABLE")
    with runner.directory_fd(issue30) as fd:
        checked(runner.read_exact(fd, "TEST_INPUTS.json"), ISSUE30_INPUTS_SHA, "Issue30/TEST_INPUTS.json")
    _, captured, mapping, raw_manifest, _ = runner.read_inputs(issue30)
    with runner.directory_fd(issue32) as fd:
        local = {name: checked(runner.read_exact(fd, name), sha, name) for name, sha in PINS.items()}
    with runner.directory_fd(output.parent) as fd:
        os.mkdir(output.name, 0o700, dir_fd=fd)
    suite = output / "isolated/preselection"
    prepared = {"isolated/" + destination: captured[source]
                for destination, source in mapping.items() if destination.startswith("preselection/")}
    service_relative = "isolated/preselection/after/apps/api/v35_api/preselection_service.py"
    prepared[service_relative] = local["after/source/actual_api/apps/api/v35_api/preselection_service.py"]
    for relative in ("test_api_same_date.py", "api_support/contracts/trading_calendar.py",
                     "api_support/contracts/market_calendar_2026.json"):
        prepared["isolated/preselection/tests/" + relative] = local["tests/" + relative]
    prepared["isolated/preselection/test_support/contracts/market_calendar_2026.json"] = local[
        "tests/api_support/contracts/market_calendar_2026.json"]
    fixture_relative = "isolated/preselection/tests/test_preselection_source_root_20261008.py"
    checked(prepared[fixture_relative], FIXTURE_BEFORE, "legacy fixture before")
    with runner.directory_fd(output) as fd:
        for relative, raw in prepared.items():
            runner.write_new(fd, relative, raw, mode=0o644)
        runner.write_new(fd, "_runner/_issue30_portable_metrics.py", runner.METRICS_PLUGIN.encode(), mode=0o644)
        patch = subprocess.run(
            ["patch", "-f", "-F", "0", "-p1"],
            input=local["evidence/api/legacy_exact_date_fixture.patch"],
            cwd=suite, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "LC_ALL": "C"},
        )
        runner.write_new(fd, "fixture_patch.log", patch.stdout)
        if patch.returncode:
            raise ValueError("TEST_FIXTURE_PATCH_FAILED")
        prepared[fixture_relative] = checked(runner.read_exact(fd, fixture_relative), FIXTURE_AFTER, "legacy fixture after")
        runner.write_new(fd, "COMMAND.json", runner.json_bytes({
            "argv": [sys.executable, "-B", str(Path(__file__).resolve()), *sys.argv[1:]],
            "scope": "ISOLATED_SYNTHETIC_SOURCE_TEST_ONLY_NOT_CURRENT_RUNTIME",
            "composition": COMPOSITION,
        }))
        runner.write_new(fd, "LAYOUT.json", runner.json_bytes({
            "issue30_runner_sha256": ISSUE30_RUNNER_SHA,
            "issue30_test_inputs_sha256": ISSUE30_INPUTS_SHA,
            "issue32_pins": PINS, "fixture_before_sha256": FIXTURE_BEFORE,
            "fixture_after_sha256": FIXTURE_AFTER, "composition": COMPOSITION,
            "prepared_files": [{"path": name, "sha256": runner.sha256(raw)} for name, raw in sorted(prepared.items())],
        }))
        original_environment = runner.clean_environment

        def environment(executable, suite_root, import_paths, metrics):
            env = original_environment(executable, suite_root, import_paths, metrics)
            env["ISSUE32_API_SERVICE_SOURCE"] = str(output / service_relative)
            return env

        runner.clean_environment = environment
        result = runner.execute_suite("preselection", output, fd, python, expected=72, timeout=120)
        problems = ["TEST_COPY_CHANGED:" + name for name, raw in prepared.items()
                    if runner.read_exact(fd, name) != raw]
        # Reuse the immutable package verification after execution as well.
        runner.read_inputs(issue30)
        with runner.directory_fd(issue32) as source_fd:
            problems.extend("ISSUE32_INPUT_CHANGED:" + name for name, raw in local.items()
                            if runner.read_exact(source_fd, name) != raw)
        summary = {
            "status": "PASS" if result["status"] == "PASS" and not problems else "FAIL",
            "expected_tests": 72, "composition": COMPOSITION, "problems": problems,
            "result": "results/preselection/result.json",
            "known_warning": "The supplied test environment retains its recorded StarletteDeprecationWarning about httpx; see pytest.log.",
            "safety": runner.SAFETY,
        }
        runner.write_new(fd, "SUMMARY.json", runner.json_bytes(summary))
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}), file=sys.stderr)
        raise SystemExit(1)
