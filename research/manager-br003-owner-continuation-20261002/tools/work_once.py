#!/usr/bin/env python3
"""Apply the BR003 incremental patch to an existing BI01/BI02 isolated candidate and run 39+2 tests.

This tool never installs packages, starts services, runs a scheduler, captures market data,
or writes into a configured release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT.parent / "manager-bi-contract-fix-20261001"
PATCH = ROOT / "br003.incremental.patch"
PINS = json.loads((ROOT / "SOURCE_PINS.json").read_text())["files"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected(before: bool) -> dict[str, str]:
    result = {}
    for row in PINS:
        if row["path"] == "apps/web/src/api/managerWorkspace.ts":
            result[row["path"]] = row["before_sha256"] if before else row["after_sha256"]
        else:
            result[row["path"]] = row["required_sha256"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True, help="Existing disposable BI01/BI02 application_candidate")
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory outside app")
    args = parser.parse_args()
    app = args.app.resolve()
    out = args.output.resolve()

    if not app.is_dir() or "releases" in app.parts or out == app or out.is_relative_to(app):
        parser.error("use the existing isolated candidate and a new external evidence directory")
    if not (UPSTREAM / "tests" / "test_cross_boundary.py").is_file():
        parser.error("upstream 39-case delivery is missing")
    if out.exists():
        parser.error("output directory must not already exist")

    before = expected(True)
    after = expected(False)
    observed = {
        rel: sha(app / rel) if (app / rel).is_file() else None
        for rel in before
    }
    if observed not in (before, after):
        print(json.dumps({
            "status": "SOURCE_DRIFT",
            "files": [
                {
                    "path": rel,
                    "actual": observed[rel],
                    "required_before": before[rel],
                    "required_after": after[rel],
                }
                for rel in before
            ],
        }, ensure_ascii=False, indent=2))
        return 2

    out.mkdir(parents=True)
    receipt = {
        "status": "NOT_RUN",
        "app": str(app),
        "python": sys.version,
        "source_before": observed,
        "patch_applied": False,
        "expected_case_count": 41,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "DEPLOYED": "NOT_RUN",
        "API_VERIFIED": "NOT_RUN",
        "UI_VERIFIED": "NOT_RUN",
    }

    try:
        if observed == before:
            for check in (True, False):
                cmd = ["git", "apply", *(["--check"] if check else []), str(PATCH)]
                run = subprocess.run(cmd, cwd=app, text=True, capture_output=True)
                (out / ("patch_check.log" if check else "patch_apply.log")).write_text(
                    run.stdout + run.stderr
                )
                if run.returncode:
                    raise RuntimeError("BR003_PATCH_APPLY_FAILED")
            receipt["patch_applied"] = True

        actual_after = {rel: sha(app / rel) for rel in after}
        if actual_after != after:
            raise RuntimeError("BR003_AFTER_SHA_MISMATCH")

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join([
            str(app),
            str(UPSTREAM / "tests"),
            str(ROOT / "tests"),
        ])
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["BI_APP"] = str(app)
        env["BI_OUTPUT"] = str(out / "cases")

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(UPSTREAM / "pytest.ini"),
            str(UPSTREAM / "tests" / "test_cross_boundary.py"),
            str(ROOT / "tests" / "test_br003_target_date.py"),
            "-q",
            "--tb=short",
            "--junitxml=" + str(out / "junit.xml"),
        ]
        run = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True)
        (out / "pytest.log").write_text(run.stdout + run.stderr)
        print(run.stdout + run.stderr)

        receipt.update(
            status="ISOLATED_41_CASES_PASS" if run.returncode == 0 else "TEST_FAILED",
            command=cmd,
            exit_code=run.returncode,
            source_after=actual_after,
        )
        if {rel: sha(app / rel) for rel in after} != after:
            raise RuntimeError("SOURCE_CHANGED_DURING_TEST")
        return run.returncode
    except (OSError, ValueError, RuntimeError, AssertionError) as exc:
        receipt.update(
            status="FAILED",
            error=type(exc).__name__,
            reason=str(exc),
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 2
    finally:
        (out / "WORK_RECEIPT.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
        )


if __name__ == "__main__":
    raise SystemExit(main())
