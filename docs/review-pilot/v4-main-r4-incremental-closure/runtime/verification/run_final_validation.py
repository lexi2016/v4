"""Run the frozen R4 174, the known calendar fixtures, and the exact candidate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile


TASK = Path(__file__).resolve().parents[1]
RELEASE = TASK / "v4-main-r4-incremental-closure-20261122"
APP = RELEASE / "app"
RUNTIME = RELEASE / "runtime"
PYTHON = RUNTIME / "venvs/v4-mac/bin/python"
SITE = RUNTIME / "venvs/v4-mac/lib/python3.14/site-packages"
PYCACHE = "/dev/null/v4-main-r4-source-only-pycache"
TESTS = [
    "tests/test_qfq_task_continuity.py",
    "tests/test_qfq_registry_summary.py",
    "tests/test_governance_unique_roots.py",
    "tests/test_daily_derivatives_registry_summary.py",
    "tests/test_qfq_dependency_identity.py",
    "tests/test_main_root_binding_candidate.py",
]
KNOWN_CALENDAR_FIXTURES = [
    "tests/test_macos_scheduler_daemon.py::test_daemon_plist_has_single_persistent_launch_schedule",
    "tests/test_macos_scheduler_daemon.py::test_persistent_daemon_plist_binds_external_scheduler_logs",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def run(command: list[str], cwd: Path, env: dict[str, str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, shell=False, capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout, check=False)


def main() -> None:
    freeze_path = TASK / "FINAL_CANDIDATE_FREEZE_RECEIPT.json"
    freeze = json.loads(freeze_path.read_bytes())
    if (freeze.get("status") != "PASS_ISOLATED_FINAL_CANDIDATE_FROZEN"
            or freeze.get("release_root") != str(RELEASE)
            or freeze.get("app_root") != str(APP)
            or freeze.get("runtime_root") != str(RUNTIME)):
        raise RuntimeError("FINAL_CANDIDATE_FREEZE_REQUIRED")
    with (RELEASE / "launchd.plist").open("rb") as stream:
        plist = plistlib.load(stream)
    binding = plist.get("EnvironmentVariables")
    if not isinstance(binding, dict) or plist.get("WorkingDirectory") != str(APP):
        raise RuntimeError("FINAL_CANDIDATE_LAUNCHD_BINDING_INVALID")
    if (binding.get("V4_RELEASE_ID") != RELEASE.name
            or binding.get("V4_RUNTIME_ROOT") != str(RUNTIME)
            or binding.get("V4_APP_ROOT") != str(APP)):
        raise RuntimeError("FINAL_CANDIDATE_LAUNCHD_IDENTITY_MISMATCH")
    if not PYTHON.is_file() or not SITE.is_dir():
        raise RuntimeError("FINAL_CANDIDATE_MAC_PYTHON_314_REQUIRED")

    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("V4_", "V3_", "PYTHON", "PYTEST_", "PANEL_", "RESEARCH_PANEL_"))}
    env.update(binding)
    env.update({
        "PYTHONPATH": os.pathsep.join(item for item in (str(APP), str(SITE), binding.get("PYTHONPATH", "")) if item),
        "PYTHONPYCACHEPREFIX": PYCACHE,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "V4_SOURCE_ONLY_PYCACHE_REQUIRED": "1",
        "V4_A_QFQ_COMPUTE_BACKEND": "process",
    })
    env.pop("PYTHONNOUSERSITE", None)
    command = [str(PYTHON), "-X", f"pycache_prefix={PYCACHE}", "-B", "-S", "-m", "pytest",
               "-q", "-p", "no:cacheprovider", "--tb=short", *TESTS]
    temp_owner = {"owner": "runtime_writer_C", "root": "created_during_final_174",
                  "system_temp_root": tempfile.gettempdir(), "cleanup": "after suite"}
    with tempfile.TemporaryDirectory(prefix="v4-r4-final174-") as directory:
        temp_root = Path(directory).resolve()
        temp_owner["root"] = str(temp_root)
        if not temp_root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise RuntimeError("PYTEST_BASETEMP_OUTSIDE_SYSTEM_TEMP_ROOT")
        temp_owner["pytest_basetemp"] = str(temp_root / "pytest")
        write_json(TASK / "verification/TEST_TEMP_OWNERSHIP.json", temp_owner)
        full_command = [*command, "--basetemp", str(temp_root / "pytest")]
        completed = run(full_command, APP, env)
    (TASK / "verification/pytest-final-attempt-02.stdout.txt").write_text(completed.stdout + completed.stderr)
    print(completed.stdout, completed.stderr, flush=True)
    if completed.returncode or not re.search(r"\b174 passed\b", completed.stdout):
        raise RuntimeError("FINAL_CANDIDATE_174_FAILED:" + str(completed.returncode))
    full_receipt = {
        "schema": "v4.r4_incremental_final_174_test_receipt.v1",
        "status": "PASS_FINAL_174",
        "test_command": full_command,
        "return_code": completed.returncode,
        "passed": 174,
        "failed": 0,
        "skipped": 0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "release_id": RELEASE.name,
        "release_manifest_sha256": digest(RELEASE / "release-manifest.json"),
        "app_inventory_sha256": freeze["application_inventory_sha256"],
        "runtime_inventory_sha256": freeze["runtime_inventory_sha256"],
        "python_sha256": digest(PYTHON),
        "test_file_sha256": {name: digest(APP / name) for name in TESTS},
        "focused_runtime_fixture": "CHILD_IDENTITY_FIXTURE_RUN_RECEIPT.json",
        "production_write": False,
        "scheduler_triggered": False,
        "provider_invoked": False,
        "registry_or_current_mutated": False,
        "old_reservations_changed": False,
    }
    write_json(TASK / "verification/FINAL_174_TEST_RECEIPT.json", full_receipt)

    calendar_command = [str(PYTHON), "-X", f"pycache_prefix={PYCACHE}", "-B", "-S", "-m", "pytest",
                        "-q", "-p", "no:cacheprovider", "--tb=short", *KNOWN_CALENDAR_FIXTURES]
    with tempfile.TemporaryDirectory(prefix="v4-r4-calendar-fixtures-") as directory:
        calendar_root = Path(directory).resolve()
        if not calendar_root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise RuntimeError("CALENDAR_PYTEST_BASETEMP_OUTSIDE_SYSTEM_TEMP_ROOT")
        calendar_command.extend(("--basetemp", str(calendar_root / "pytest")))
        calendar = run(calendar_command, APP, env, timeout=180)
    (TASK / "verification/calendar-fixtures-final.stdout.txt").write_text(calendar.stdout + calendar.stderr)
    failure_messages = re.findall(
        r"ValueError: (review_core_calendar_path must name market_calendar_2026\.json)",
        calendar.stdout + calendar.stderr)
    calendar_receipt = {
        "schema": "v4.r4_incremental_known_calendar_fixture_recheck.v1",
        "status": "KNOWN_BASELINE_FAILURE_RECONFIRMED" if calendar.returncode and len(failure_messages) == 2
                 else "UNEXPECTED_CALENDAR_FIXTURE_RESULT",
        "test_command": calendar_command,
        "return_code": calendar.returncode,
        "expected_preexisting_failure_count": 2,
        "observed_failure_count": len(failure_messages),
        "failures": [{"nodeid": node, "message": failure_messages[index] if index < len(failure_messages) else None}
                     for index, node in enumerate(KNOWN_CALENDAR_FIXTURES)],
        "stdout": calendar.stdout,
        "stderr": calendar.stderr,
        "source_file_sha256": digest(APP / "tests/test_macos_scheduler_daemon.py"),
        "daemon_source_sha256": digest(APP / "ops/run_v4_macos_scheduler_daemon.py"),
        "production_write": False,
        "scheduler_triggered": False,
    }
    write_json(TASK / "verification/CALENDAR_FIXTURE_RECHECK_RECEIPT.json", calendar_receipt)
    if calendar_receipt["status"] != "KNOWN_BASELINE_FAILURE_RECONFIRMED":
        raise RuntimeError("CALENDAR_FIXTURE_BASELINE_CHANGED_OR_FAILED_DIFFERENTLY")

    print(json.dumps({"final_174": full_receipt["status"],
                      "calendar_fixtures": calendar_receipt["status"],
                      "calendar_failures": calendar_receipt["observed_failure_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()
