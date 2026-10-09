"""Independent, synthetic-only review commands. Writes only below this directory."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
APP = HERE.parent / "app"
PYTHON = "/workspace/scratch/a154a3323e32/test_env/bin/python"
RUNTIME = [
    "apps/api/v35_api/manager_research_router.py",
    "apps/web/src/api/managerWorkspace.ts",
    "ops/run_manager_daily_announcement.py",
    "upstreams/v3_shared_data/shared_data/hk_security_master.py",
    "v4/manager_research/plan_owner_dispatch.py",
    "v4/manager_research/workspace_announcements.py",
    "v4/manager_research/workspace_plan.py",
]
TESTS = [
    "tests/test_manager_announcement_handoff_20261009.py",
    "tests/test_manager_announcement_parity_20261008.py",
    "tests/test_manager_us_mapping_three_channel_20261009.py",
    "tests/test_manager_three_channel_hk_reader.py",
    "tests/test_security_master_store_error.py",
    "tests/test_manager_screen_summary_contract.py",
    "tests/test_manager_input_contracts_20261008.py",
    "tests/test_manager_us_daily_automation_20261008.py",
    "tests/test_manager_daily_automation_20261008.py",
    "tests/test_manager_daily_dispatch_20261008.py",
    "tests/test_manager_workspace_exact_page_binding_20261008.py",
    "tests/test_manager_us_mapping_isolation_20261008.py",
    "tests/test_manager_us_mapping_research.py::test_TEST_FIXTURE_synthetic_owner_sessions_produce_date_distinct_mappings_and_api_readbacks",
]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def runtime_identity():
    return {name: {"sha256": digest((APP / name).read_bytes()),
                   "bytes": (APP / name).stat().st_size} for name in RUNTIME}


def test_source_identity():
    paths = {APP / name.split("::")[0] for name in TESTS}
    paths.update({APP / "tests/r3_scoped_loader.py", HERE / "test_review_boundaries.py",
                  APP / "tests/manager_three_channel_ui_fixture.py",
                  APP / "apps/web/src/api/managerWorkspace.threeChannel.spec.ts"})
    return {str(path): {"sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}
            for path in sorted(paths)}


def run(kind, suffix=""):
    label = kind + suffix
    before = runtime_identity()
    test_before = test_source_identity()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
               PYTHONPATH=str(APP), V4_TEST_PYTHON=PYTHON, V4_TEST_SOURCE_ROOT=str(APP))
    if kind in {"python", "boundary"}:
        selected = TESTS if kind == "python" else [str(HERE / "test_review_boundaries.py")]
        arguments = ["-q", "--tb=short", "-p", "no:cacheprovider",
                     "--basetemp=" + str(HERE / ("synthetic_" + label)),
                     "--junitxml=" + str(HERE / (label + "_results.xml")), *selected]
        bootstrap = (
            "import sys; sys.path.insert(0, 'tests'); "
            "import r3_scoped_loader; r3_scoped_loader.install(); "
            "setattr(sys.modules['v4'], 'manager_research', sys.modules['v4.manager_research']); "
            "setattr(sys.modules['infrastructure'], 'scheduling', sys.modules['infrastructure.scheduling']); "
            "import pytest; raise SystemExit(pytest.main(" + repr(arguments) + "))"
        )
        argv, cwd = [PYTHON, "-c", bootstrap], APP
    elif kind == "web":
        argv = ["/opt/codex/runtimes/codex-primary-runtime/dependencies/node/bin/node",
                "/workspace/scratch/a154a3323e32/candidate/apps/web/node_modules/vitest/vitest.mjs",
                "run", "--config", str(HERE.parent / "web/vitest.config.mjs"),
                "src/api/managerWorkspace.threeChannel.spec.ts"]
        cwd = APP / "apps/web"
    else:
        raise ValueError(kind)
    started = time.monotonic()
    result = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=90)
    log = HERE / (label + "_checks.log")
    log.write_text(result.stdout)
    after = runtime_identity()
    test_after = test_source_identity()
    receipt = {"classification": "INDEPENDENT_SYNTHETIC_REVIEW", "argv": argv,
        "cwd": str(cwd), "environment_overrides": {k: env[k] for k in (
            "PYTHONDONTWRITEBYTECODE", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONPATH",
            "V4_TEST_PYTHON", "V4_TEST_SOURCE_ROOT")},
        "exit_code": result.returncode, "elapsed_seconds": round(time.monotonic() - started, 3),
        "log": log.name, "log_sha256": digest(log.read_bytes()),
        "runtime_before": before, "runtime_after": after, "runtime_unchanged": before == after,
        "test_source_before": test_before, "test_source_after": test_after,
        "test_source_unchanged": test_before == test_after}
    (HERE / (label + "_checks_receipt.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"kind": kind, "exit_code": result.returncode,
                      "elapsed_seconds": receipt["elapsed_seconds"], "runtime_unchanged": before == after}))
    print(result.stdout)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
