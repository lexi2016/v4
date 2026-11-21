"""Run the isolated, no-claim daemon -> A executor -> QFQ identity fixture."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile


TASK = Path(__file__).resolve().parents[1]
RELEASE = TASK / "v4-main-r4-incremental-closure-20261122"
APP = RELEASE / "app"
RUNTIME = RELEASE / "runtime"
PYCACHE = "/dev/null/v4-main-r4-source-only-pycache"


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def main() -> None:
    if RELEASE.name != "v4-main-r4-incremental-closure-20261122":
        raise RuntimeError("RUNTIME_RELEASE_ROOT_ID_MISMATCH")
    freeze_path = TASK / "FINAL_CANDIDATE_FREEZE_RECEIPT.json"
    freeze = json.loads(freeze_path.read_bytes())
    if (freeze.get("status") != "PASS_ISOLATED_FINAL_CANDIDATE_FROZEN"
            or freeze.get("release_root") != str(RELEASE)
            or freeze.get("app_root") != str(APP)
            or freeze.get("runtime_root") != str(RUNTIME)):
        raise RuntimeError("FINAL_FROZEN_CANDIDATE_REQUIRED")

    with (RELEASE / "launchd.plist").open("rb") as stream:
        plist = plistlib.load(stream)
    plist_env = plist.get("EnvironmentVariables")
    if not isinstance(plist_env, dict):
        raise RuntimeError("CANDIDATE_LAUNCHD_ENVIRONMENT_MISSING")
    if (plist.get("WorkingDirectory") != str(APP)
            or plist_env.get("V4_APP_ROOT") != str(APP)
            or plist_env.get("V4_RUNTIME_ROOT") != str(RUNTIME)
            or plist_env.get("V4_RELEASE_ID") != RELEASE.name):
        raise RuntimeError("CANDIDATE_LAUNCHD_ROOT_BINDING_MISMATCH")

    python = RUNTIME / "venvs/v4-mac/bin/python"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeError("CANDIDATE_MAC_PYTHON_MISSING")
    main_site = RUNTIME / "venvs/v4-mac/lib/python3.14/site-packages"
    if not main_site.is_dir():
        raise RuntimeError("CANDIDATE_MAIN_SITE_PACKAGES_MISSING")

    verification_root = TASK / "verification"
    verification_root.mkdir(parents=True, exist_ok=True)
    fixture_root = Path(tempfile.mkdtemp(prefix="daemon-child-identity-", dir=verification_root))
    temp_ledger = fixture_root / "dispatch-ledger"
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": os.environ.get("HOME", "/Users/lexi"),
        "LANG": "en_US.UTF-8",
        "TZ": "Asia/Shanghai",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    env.update({str(key): str(value) for key, value in plist_env.items()})
    inherited_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(item for item in (str(APP), str(main_site), inherited_path) if item)
    env.update({
        "V3_SHARED_HK_TDX_ROOT": env.get("V4_RESEARCH_PANEL_HK_TDX_ROOT", ""),
        "V4_SOURCE_ONLY_PYCACHE_REQUIRED": "1",
        "PYTHONPYCACHEPREFIX": PYCACHE,
        "PYTHONDONTWRITEBYTECODE": "1",
        # The fixture's real SlotProcessLanes and A-executor seams are bound
        # only to this task-owned temporary ledger; production ledger values
        # from the plist are never passed to a child.
        "V4_DISPATCH_LEDGER_ROOT": str(temp_ledger),
    })
    env.pop("PYTHONNOUSERSITE", None)
    command = [str(python), "-X", f"pycache_prefix={PYCACHE}", "-B", "-S", "-m",
               "ops.runtime_child_identity_probe", "--mode", "daemon-parent",
               "--date", "20261123", "--slot", "1540", "--ledger-root", str(temp_ledger)]
    command_json = json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    result = subprocess.run(command, cwd=APP, env=env, shell=False, capture_output=True,
                            text=True, encoding="utf-8", timeout=600, check=False)
    if result.returncode:
        failure = {
            "schema": "v4.r4_daemon_child_identity_fixture_run.v1",
            "status": "FAIL_READ_ONLY_IDENTITY_FIXTURE",
            "return_code": result.returncode,
            "stderr_tail": result.stderr[-5000:],
            "stdout_tail": result.stdout[-2000:],
            "command_sha256": sha_bytes(command_json),
            "candidate_python_sha256": sha(python),
            "candidate_release_manifest_sha256": sha(RELEASE / "release-manifest.json"),
            "fixture_root": str(fixture_root),
            "temporary_fixture_retained_for_diagnosis": True,
            "production_write": False,
        }
        write_json(verification_root / "CHILD_IDENTITY_FIXTURE_FAILURE.json", failure)
        raise RuntimeError("DAEMON_A_QFQ_FIXTURE_FAILED:" + result.stderr[-2000:])

    observed = json.loads(result.stdout)
    a_fixture = observed.get("a_executor_fixture", {})
    qfq = observed.get("qfq_child_identity", {})
    expected_dates = {"20261120", "20261123"}
    if (observed.get("status") != "PASS_READ_ONLY_REAL_DAEMON_AND_EXECUTOR_SEAMS"
            or a_fixture.get("status") != "PASS_ACTUAL_A_EXECUTOR_RUN_CAPTURE"
            or qfq.get("status") != "PASS_READ_ONLY_QFQ_CHILD_IDENTITY"
            or set(qfq.get("qfq_operation_keys", {})) != expected_dates
            or qfq.get("no_user_site") != 1 or qfq.get("no_site") != 0
            or qfq.get("claim_begin_called") is not False
            or qfq.get("registry_mutated") is not False
            or observed.get("natural_dispatch_task_key") is not None
            or observed.get("natural_dispatch_attempt_id") is not None
            or observed.get("natural_dispatch_run_id") is not None
            or observed.get("natural_dispatch_generation") is not None):
        raise RuntimeError("DAEMON_A_QFQ_FIXTURE_ASSERTION_FAILED")

    key_manifest = {
        "schema": "v4.r4_child_qfq_key_manifest.v2",
        "status": "PASS_READ_ONLY_DAEMON_A_QFQ_IDENTITY",
        "release_id": qfq["release_id"],
        "release_root": qfq["release_root"],
        "app_root": qfq["app_root"],
        "runtime_root": qfq["runtime_root"],
        "release_manifest_sha256": qfq["release_manifest"]["sha256"],
        "application_inventory_sha256": qfq["release_manifest"]["application_inventory_sha256"],
        "helper": qfq["helper"],
        "no_user_site": qfq["no_user_site"],
        "no_site": qfq["no_site"],
        "stdlib_root": qfq["stdlib_root"],
        "flags": qfq["flags"],
        "pycache_prefix": qfq["pycache_prefix"],
        "executable": qfq["executable"],
        "executable_sha256": qfq["executable_sha256"],
        "source_chain": qfq["source_chain"],
        "data_root": qfq["data_root"],
        "return_root": qfq["return_root"],
        "registry_root": qfq["registry_root"],
        "registry_path": qfq["registry_path"],
        "registry_sha256": qfq["registry_sha256"],
        "registry_read_status": qfq["registry_read_status"],
        "computation_manifest_sha256": qfq["computation_manifest_sha256"],
        "computation_manifest": qfq["computation_manifest"],
        "computation_source_roles": qfq["computation_source_roles"],
        "keys": qfq["qfq_operation_keys"],
        "daemon_dispatch": {
            "status": "NATURAL_DISPATCH_NOT_RUN",
            "task_key": None,
            "attempt_id": None,
            "run_id": None,
            "generation": None,
        },
        "claim_begin_called": False,
        "admission_called": False,
        "provider_invoked": False,
        "production_owner_called": False,
        "production_registry_mutated": False,
        "production_current_pointer_mutated": False,
        "old_reservations_changed": False,
    }
    key_path = verification_root / "CHILD_QFQ_KEY_MANIFEST.json"
    write_json(key_path, key_manifest)

    identity_receipt = {
        "schema": "v4.r4_daemon_a_qfq_identity_probe.v1",
        "status": "PASS_READ_ONLY_DAEMON_A_QFQ_IDENTITY",
        "release_id": observed["release_id"],
        "release_root": observed["release_root"],
        "app_root": observed["app_root"],
        "runtime_root": observed["runtime_root"],
        "parent": observed["parent"],
        "daemon_popen": observed["daemon_popen"],
        "scheduler_module_substitution": observed["scheduler_module_substitution"],
        "a_executor_fixture": a_fixture,
        "qfq_child_identity": qfq,
        "daemon_dispatch": key_manifest["daemon_dispatch"],
        "registry_root": qfq["registry_root"],
        "registry_path": qfq["registry_path"],
        "registry_sha256": qfq["registry_sha256"],
        "data_root": qfq["data_root"],
        "return_root": qfq["return_root"],
        "qfq_operation_keys": qfq["qfq_operation_keys"],
        "computation_manifest_sha256": qfq["computation_manifest_sha256"],
        "computation_manifest": qfq["computation_manifest"],
        "release_manifest_sha256": qfq["release_manifest"]["sha256"],
        "no_user_site": qfq["no_user_site"],
        "no_site": qfq["no_site"],
        "stdlib_root": qfq["stdlib_root"],
        "source_chain": qfq["source_chain"],
        "claim_begin_called": False,
        "admission_called": False,
        "provider_invoked": False,
        "production_registry_mutated": False,
        "production_current_pointer_mutated": False,
        "old_reservations_changed": False,
        "natural_dispatch_status": "NOT_RUN",
        "fixture_ledger_root": str(temp_ledger),
    }
    identity_path = verification_root / "CHILD_IDENTITY_RECEIPT.json"
    write_json(identity_path, identity_receipt)
    run_receipt = {
        "schema": "v4.r4_daemon_child_identity_fixture_run.v1",
        "status": "PASS_READ_ONLY_DAEMON_A_QFQ_IDENTITY",
        "command_sha256": sha_bytes(command_json),
        "command": command,
        "parent_environment_sha256": observed["parent"]["environment_sha256"],
        "parent_python_flags": observed["parent"]["flags"],
        "daemon_popen_argv_sha256": observed["daemon_popen"]["argv_sha256"],
        "daemon_popen_environment_sha256": observed["daemon_popen"]["environment_sha256"],
        "executor_run_command_sha256": a_fixture["captured_executor_run"]["command_sha256"],
        "executor_run_environment_sha256": a_fixture["captured_executor_run"]["environment_sha256"],
        "qfq_environment_sha256": qfq["environment_sha256"],
        "candidate_python_sha256": sha(python),
        "candidate_release_manifest_sha256": sha(RELEASE / "release-manifest.json"),
        "candidate_freeze_receipt_sha256": sha(freeze_path),
        "identity_receipt": {"path": str(identity_path), "sha256": sha(identity_path),
                             "size": identity_path.stat().st_size},
        "key_manifest": {"path": str(key_path), "sha256": sha(key_path), "size": key_path.stat().st_size,
                         "computation_manifest_embedded": True},
        "fixture_ledger_only": True,
        "temporary_fixture_removed": False,
        "production_write": False,
        "claim_begin_called": False,
        "natural_dispatch": "NOT_RUN",
    }
    run_path = verification_root / "CHILD_IDENTITY_FIXTURE_RUN_RECEIPT.json"
    write_json(run_path, run_receipt)
    shutil.rmtree(fixture_root)
    run_receipt["temporary_fixture_removed"] = True
    run_receipt["fixture_ledger_root"] = str(temp_ledger)
    write_json(run_path, run_receipt)
    # Recompute hashes after the cleanup-state field is finalized.
    run_receipt["identity_receipt"]["sha256"] = sha(identity_path)
    run_receipt["key_manifest"]["sha256"] = sha(key_path)
    run_receipt["key_manifest"]["size"] = key_path.stat().st_size
    write_json(run_path, run_receipt)


if __name__ == "__main__":
    main()
