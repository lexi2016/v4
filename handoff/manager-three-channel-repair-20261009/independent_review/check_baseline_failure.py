"""Recheck the preserved failure against independently verified baseline bytes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASELINE = ROOT / "announcement/baseline_app"
PYTHON = "/workspace/scratch/a154a3323e32/test_env/bin/python"
assembly = json.loads((ROOT / "evidence/assembly.json").read_text())
for row in assembly["files"]:
    raw = (BASELINE / row["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row["sha256"], row["path"]
args = ["-q", "--tb=short", "-p", "no:cacheprovider",
        "--basetemp=" + str(HERE / "synthetic_baseline"),
        "tests/test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection"]
code = ("import sys; sys.path.insert(0, 'tests'); import r3_scoped_loader; r3_scoped_loader.install(); "
        "setattr(sys.modules['v4'], 'manager_research', sys.modules['v4.manager_research']); "
        "setattr(sys.modules['infrastructure'], 'scheduling', sys.modules['infrastructure.scheduling']); "
        "import pytest; raise SystemExit(pytest.main(" + repr(args) + "))")
argv = [PYTHON, "-c", code]
env = dict(os.environ, PYTHONPATH=str(BASELINE), PYTHONDONTWRITEBYTECODE="1",
           PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
started = time.monotonic()
result = subprocess.run(argv, cwd=BASELINE, env=env, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, timeout=30)
log = HERE / "baseline_failure.log"
log.write_text(result.stdout)
receipt = {"classification": "INDEPENDENT_UNCHANGED_BASELINE_FAILURE_REPRODUCTION",
    "argv": argv, "cwd": str(BASELINE), "exit_code": result.returncode,
    "elapsed_seconds": round(time.monotonic() - started, 3),
    "baseline_files_sha256_verified": len(assembly["files"]),
    "baseline_identity": "7ca0190a721a7fd0fc0c88b79a872889867d111f",
    "environment_overrides": {key: env[key] for key in
        ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTEST_DISABLE_PLUGIN_AUTOLOAD")},
    "log": log.name, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
(HERE / "baseline_failure_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({k: v for k, v in receipt.items() if k != "argv"}, indent=2))
print(result.stdout)
raise SystemExit(result.returncode)
