"""Run Issue 28 synthetic checks with the selected Mac interpreter."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
WRITER = HERE.parent
CANDIDATE_ROOT = WRITER / "isolated_candidate"
CANONICAL_ROOT = Path("/Users/lexi/Desktop/学习/v4_app").resolve()
RECEIPT_ROOT = WRITER / "receipt"
DATE_TEST = HERE / "test_date_upper_bound.py"
COMPAT_TEST = HERE / "test_compatibility.py"
CLOSE_TEST = HERE / "test_close_source_pit_warning.py"
READ_TEST = HERE / "test_existing_future_artifact_read.py"
CANONICAL_REGRESSION_TEST = CANONICAL_ROOT / "tests/test_issue28_historical_p2_20261008.py"


def _source_identity(target: str) -> tuple[Path, str, str]:
    if target == "candidate":
        root = CANDIDATE_ROOT / "source"
    elif target == "integrated":
        root = CANONICAL_ROOT
    else:
        raise ValueError(target)
    pool = root / "infrastructure/preselection_pool_store.py"
    close = root / "ops/build_close_review.py"
    import hashlib

    return root, hashlib.sha256(pool.read_bytes()).hexdigest(), hashlib.sha256(close.read_bytes()).hexdigest()


def run(target: str, phase: str) -> dict:
    root, pool_sha, close_sha = _source_identity(target)
    output_dir = RECEIPT_ROOT / f"{target}_{phase}"
    output_dir.mkdir(parents=True, exist_ok=True)
    junit = output_dir / "results.xml"
    log = output_dir / "pytest.log"
    tests = [DATE_TEST, COMPAT_TEST, CLOSE_TEST, READ_TEST, CANONICAL_REGRESSION_TEST]
    args = [
        "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
    ]
    if target == "candidate":
        args.extend(["-p", "candidate_loader"])
    if phase == "canary":
        args.extend([
            str(DATE_TEST) + "::test_future_source_date_is_rejected_before_materialization[split-eligibility_source_date-20261008]",
            str(CLOSE_TEST) + "::test_missing_source_pair_retains_pit_uncertainty_in_stored_review",
            str(READ_TEST) + "::test_existing_future_artifact_read_rejects_without_changing_trio",
        ])
        expected_tests = 9
    elif phase == "focused":
        args.extend(str(path) for path in tests)
        expected_tests = 38
    else:
        raise ValueError(phase)
    args.extend([f"--basetemp={output_dir / 'tmp'}", f"--junitxml={junit}"])
    env = dict(os.environ)
    extra_paths = [CANONICAL_ROOT, HERE]
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in extra_paths)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["V4_CANONICAL_ROOT"] = str(CANONICAL_ROOT)
    env["ISSUE28_CANDIDATE_ROOT"] = str(CANDIDATE_ROOT)
    env["ISSUE28_CANDIDATE_SOURCE_ROOT"] = str(CANDIDATE_ROOT / "source")
    env["ISSUE28_EXPECTED_POOL_SHA"] = pool_sha
    env["ISSUE28_EXPECTED_CLOSE_SHA"] = close_sha
    env["ISSUE28_EXPECTED_AFTER_POOL_PATH"] = str(root / "infrastructure/preselection_pool_store.py")
    command = [sys.executable, *args]
    result = subprocess.run(
        command,
        cwd=CANONICAL_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log.write_text(result.stdout, encoding="utf-8")
    cases = ET.parse(junit).getroot().findall(".//testcase") if junit.exists() else []
    failures = [case.attrib.get("name", "") for case in cases if case.find("failure") is not None]
    errors = [case.attrib.get("name", "") for case in cases if case.find("error") is not None]
    skipped = [case.attrib.get("name", "") for case in cases if case.find("skipped") is not None]
    expected = result.returncode == 0 and len(cases) == expected_tests and not failures and not errors and not skipped
    record = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "phase": phase,
        "command": command,
        "cwd": str(CANONICAL_ROOT),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "selected_source_root": str(root),
        "selected_pool_sha256": pool_sha,
        "selected_close_sha256": close_sha,
        "pytest_returncode": result.returncode,
        "tests_collected": len(cases),
        "passed": len(cases) - len(failures) - len(errors) - len(skipped),
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "expected_result_observed": expected,
        "log": str(log),
        "junit_xml": str(junit),
        "data_scope": "SYNTHETIC_TMP_PATH_ONLY",
        "stage_consumer": "REAL_CANONICAL_MODULE_AVAILABLE; stage_selection_root=None IN THESE FIXTURES",
        "deployment_api_ui_natural_slot": "NOT_RUN",
    }
    (output_dir / "RESULT.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))
    print(result.stdout, end="")
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("candidate", "integrated"), required=True)
    parser.add_argument("--phase", choices=("canary", "focused"), required=True)
    args = parser.parse_args()
    result = run(args.target, args.phase)
    return 0 if result["expected_result_observed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
