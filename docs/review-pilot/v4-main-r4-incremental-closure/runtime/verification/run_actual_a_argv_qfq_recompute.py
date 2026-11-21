"""Run the exact-argv key recomputation in the final Mac child environment."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile


TASK = Path(__file__).resolve().parents[1]
RELEASE = TASK / "v4-main-r4-incremental-closure-20261122"
APP = RELEASE / "app"
RUNTIME = RELEASE / "runtime"
PYTHON = RUNTIME / "venvs/v4-mac/bin/python"
SITE = RUNTIME / "venvs/v4-mac/lib/python3.14/site-packages"
PYCACHE = "/dev/null/v4-main-r4-source-only-pycache"
VERIFY_SCRIPT = TASK / "verification/verify_qfq_key_from_actual_a_argv.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    with (RELEASE / "launchd.plist").open("rb") as stream:
        plist = plistlib.load(stream)
    plist_env = plist.get("EnvironmentVariables") or {}
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": os.environ.get("HOME", "/Users/lexi"),
        "LANG": "en_US.UTF-8",
        "TZ": "Asia/Shanghai",
        "TMPDIR": os.environ.get("TMPDIR", tempfile.gettempdir()),
    }
    env.update({str(key): str(value) for key, value in plist_env.items()})
    env.update({
        "PYTHONPATH": os.pathsep.join(
            item for item in (str(APP), str(SITE), plist_env.get("PYTHONPATH", "")) if item),
        "PYTHONPYCACHEPREFIX": PYCACHE,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "V4_SOURCE_ONLY_PYCACHE_REQUIRED": "1",
    })
    import_command = (
        "import importlib.util,sys;"
        "p=sys.argv[1];s=importlib.util.spec_from_file_location('verify_qfq_key_from_actual_a_argv',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.main()"
    )
    command = [str(PYTHON), "-X", f"pycache_prefix={PYCACHE}", "-B", "-c",
               import_command, str(VERIFY_SCRIPT)]
    result = subprocess.run(command, cwd=APP, env=env, shell=False, capture_output=True,
                            text=True, encoding="utf-8", timeout=300, check=False)
    if result.returncode:
        failure = {
            "schema": "v4.r4_actual_a_argv_qfq_recompute_run.v1",
            "status": "FAIL_ACTUAL_A_ARGV_QFQ_KEY_RECOMPUTE",
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr[-5000:],
            "command_sha256": hashlib.sha256(
                json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
            "candidate_python_sha256": sha(PYTHON),
            "production_write": False,
            "claim_begin_called": False,
        }
        (TASK / "verification/ACTUAL_A_ARGV_QFQ_RECOMPUTE_FAILURE_ATTEMPT_02.json").write_text(
            json.dumps(failure, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        raise RuntimeError("ACTUAL_A_ARGV_QFQ_RECOMPUTE_FAILED:" + result.stderr[-2000:])
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    if observed.get("status") != "PASS_ACTUAL_A_ARGV_BINDS_QFQ_KEYS":
        raise RuntimeError("ACTUAL_A_ARGV_QFQ_RECOMPUTE_STATUS_INVALID")
    receipt_path = TASK / "verification/ACTUAL_A_ARGV_QFQ_KEY_RECOMPUTE_RECEIPT.json"
    run_receipt = {
        "schema": "v4.r4_actual_a_argv_qfq_recompute_run.v1",
        "status": "PASS_ACTUAL_A_ARGV_BINDS_QFQ_KEYS",
        "command": command,
        "command_sha256": hashlib.sha256(
            json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
        "candidate_python_sha256": sha(PYTHON),
        "release_manifest_sha256": sha(RELEASE / "release-manifest.json"),
        "verification_receipt": {
            "path": str(receipt_path),
            "sha256": sha(receipt_path),
            "size": receipt_path.stat().st_size,
        },
        "stdout": result.stdout,
        "stderr": result.stderr,
        "no_site": False,
        "no_user_site": True,
        "production_write": False,
        "claim_begin_called": False,
        "admission_called": False,
        "provider_invoked": False,
        "natural_dispatch": "NOT_RUN",
    }
    (TASK / "verification/ACTUAL_A_ARGV_QFQ_RECOMPUTE_RUN_RECEIPT.json").write_text(
        json.dumps(run_receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps(observed, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
