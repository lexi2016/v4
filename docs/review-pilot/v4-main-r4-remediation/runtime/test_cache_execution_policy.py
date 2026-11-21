"""Mac CPython 3.14 proof for the R4 source-only pycache launch policy."""
from __future__ import annotations

import hashlib
import importlib.util
import importlib._bootstrap_external as bootstrap_external
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


RELEASE = Path(__file__).resolve().parent / "v4-main-r4-review-remediation-20261121"
APP = RELEASE / "app"
RUNTIME = RELEASE / "runtime"
PYTHON = RUNTIME / "venvs/v4-mac/bin/python"
SITE = RUNTIME / "venvs/v4-mac/lib/python3.14/site-packages"
PREFIX = "/dev/null/v4-main-r4-source-only-pycache"
SOURCE_MODULE = APP / "ops/runtime_bytecode_policy.py"
CACHE_FILE = SOURCE_MODULE.parent / "__pycache__" / (
    f"{SOURCE_MODULE.stem}.{sys.implementation.cache_tag}.pyc"
)
RUNTIME_INVENTORY = Path(__file__).resolve().parents[2] / (
    "v4_main_autorun_r4_release_readiness_20261121/private/bundle/RUNTIME_INVENTORY.json"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=APP, env=env, capture_output=True, text=True, check=False)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    require(sys.platform == "darwin", "MACOS_REQUIRED")
    require(sys.version_info[:2] == (3, 14), "CANDIDATE_MAC_PYTHON_314_REQUIRED")
    require(PYTHON.is_file() and os.access(PYTHON, os.X_OK), "CANDIDATE_INTERPRETER_REQUIRED")
    require(APP.is_dir() and SITE.is_dir(), "CANDIDATE_APP_AND_SITE_REQUIRED")
    runtime_inventory = json.loads(RUNTIME_INVENTORY.read_bytes())
    runtime_inventory_by_path = {row["path"]: row for row in runtime_inventory["entries"]}
    runtime_cache_rows = []
    for path in RUNTIME.rglob("*.pyc"):
        if not path.is_file():
            continue
        relative = path.relative_to(RUNTIME).as_posix()
        inventory_path = relative
        row = runtime_inventory_by_path.get(inventory_path)
        require(row is not None and row["sha256"] == digest(path),
                "RUNTIME_BYTECODE_NOT_HASH_BOUND:" + relative)
        runtime_cache_rows.append(inventory_path)
    sourceless_app_bytecode = [
        path.relative_to(APP).as_posix() for path in APP.rglob("*.pyc")
        if path.is_file() and path.parent.name != "__pycache__"
    ]
    require(not sourceless_app_bytecode, "UNBOUND_APP_SOURCELESS_BYTECODE_PRESENT")
    launcher = APP / "ops/launch_v4_macos_scheduler.sh"
    launcher_text = launcher.read_text()
    require(f'source_only_pycache_prefix="{PREFIX}"' in launcher_text, "LAUNCHER_CACHE_PREFIX_DRIFT")
    require("export V4_SOURCE_ONLY_PYCACHE_REQUIRED=\"1\"" in launcher_text, "LAUNCHER_REQUIRED_MARKER_MISSING")
    require("export PYTHONDONTWRITEBYTECODE=\"1\"" in launcher_text, "LAUNCHER_CACHE_WRITES_ENABLED")
    require(sum('exec "$python_bin" -X "pycache_prefix=$source_only_pycache_prefix" -B -S -m ops.run_v4_macos_scheduler "' in line
                for line in launcher_text.splitlines()) == 1,
            "ONESHOT_LAUNCH_CACHE_FLAGS_DRIFT")
    require(launcher_text.count(f'-X "pycache_prefix=$source_only_pycache_prefix" -B -S -m ops.run_v4_macos_scheduler_daemon') == 1,
            "DAEMON_LAUNCH_CACHE_FLAGS_DRIFT")
    require(CACHE_FILE.name.endswith(".cpython-314.pyc"), "CANDIDATE_CACHE_TAG_REQUIRED")
    require(not CACHE_FILE.exists(), "CONFLICT_CACHE_PATH_ALREADY_EXISTS")

    source_sha_before = digest(SOURCE_MODULE)
    source_stat = SOURCE_MODULE.stat()
    alternate_code = compile(
        "def require_source_only_cache_policy():\n    print('CACHE_CONFLICT_EXECUTED')\n",
        str(SOURCE_MODULE),
        "exec",
    )
    cached_bytes = bootstrap_external._code_to_timestamp_pyc(
        alternate_code, int(source_stat.st_mtime), source_stat.st_size
    )
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_bytes(cached_bytes)
    conflict_sha = digest(CACHE_FILE)
    probe = (
        "import importlib.util,json,sys; "
        "from ops.runtime_bytecode_policy import require_source_only_cache_policy; "
        "proof=require_source_only_cache_policy(); "
        "source=sys.modules['ops.runtime_bytecode_policy']; "
        "print(json.dumps({'proof':proof,'module_file':source.__file__,"
        "'cache_path':importlib.util.cache_from_source(source.__file__),"
        "'cache_prefix':sys.pycache_prefix,'dont_write_bytecode':sys.dont_write_bytecode}))"
    )
    common_env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "PYTEST_"))}
    common_env.update(
        PYTHONPATH=os.pathsep.join((str(APP), str(SITE))),
        V4_SOURCE_ONLY_PYCACHE_REQUIRED="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    try:
        unguarded_env = dict(common_env)
        unguarded_env.pop("V4_SOURCE_ONLY_PYCACHE_REQUIRED")
        unguarded = run([str(PYTHON), "-B", "-S", "-c", probe], unguarded_env)
        require(unguarded.returncode == 0 and "CACHE_CONFLICT_EXECUTED" in unguarded.stdout,
                "VALID_TIMESTAMP_SIZE_CONFLICT_CACHE_CONTROL_DID_NOT_EXECUTE")

        hostile_prefix = str(CACHE_FILE.parent.parent.parent / "hostile-cache-root")
        inherited_hostile_env = dict(common_env, PYTHONPYCACHEPREFIX=hostile_prefix)
        parent_flags = ["-X", f"pycache_prefix={PREFIX}", "-B", "-S"]
        guarded_parent = run([str(PYTHON), *parent_flags, "-c", probe], inherited_hostile_env)
        require(guarded_parent.returncode == 0, "PARENT_GUARDED_CACHE_PROBE_FAILED:" + guarded_parent.stderr)
        parent_result = json.loads(guarded_parent.stdout.strip().splitlines()[-1])
        require(parent_result["proof"]["source_only_prefix"] == PREFIX, "PARENT_SOURCE_POLICY_NOT_ACTIVE")
        require(parent_result["proof"]["environment_prefix"] == hostile_prefix,
                "PARENT_HOSTILE_INHERITED_PREFIX_NOT_EXERCISED")
        require(Path(parent_result["module_file"]).resolve() == SOURCE_MODULE.resolve(),
                "PARENT_MODULE_ORIGIN_MISMATCH")
        require("CACHE_CONFLICT_EXECUTED" not in guarded_parent.stdout, "PARENT_CONFLICT_CACHE_EXECUTED")
        require(not Path(parent_result["cache_path"]).exists(), "PARENT_EFFECTIVE_CACHE_PATH_WAS_READABLE")
        daemon_help = run(
            [str(PYTHON), *parent_flags, "-m", "ops.run_v4_macos_scheduler_daemon", "--help"],
            inherited_hostile_env,
        )
        require(daemon_help.returncode == 0 and "Run the persistent V4 scheduler daemon" in daemon_help.stdout,
                "REAL_PARENT_DAEMON_ENTRY_DID_NOT_REACH_SAFE_HELP")

        builder = (
            "import json,sys; from ops.run_v4_macos_scheduler_daemon import _scheduler_child_invocation; "
            "command,env=_scheduler_child_invocation(['--data-root','/tmp/r4-safe-data',"
            "'--ledger-root','/tmp/r4-safe-ledger','--preselection-input-root','/tmp/r4-safe-preselection',"
            "'--stage-selection-root','/tmp/r4-safe-stage'], '1540', '20261123'); "
            "print(json.dumps({'command':command,'environment':{k:env.get(k) for k in "
            "('PYTHONPYCACHEPREFIX','PYTHONDONTWRITEBYTECODE','V4_SOURCE_ONLY_PYCACHE_REQUIRED')} }))"
        )
        builder_env = dict(inherited_hostile_env)
        builder = run([str(PYTHON), *parent_flags, "-c", builder], builder_env)
        require(builder.returncode == 0, "DAEMON_CHILD_COMMAND_BUILDER_FAILED:" + builder.stderr)
        child_record = json.loads(builder.stdout.strip().splitlines()[-1])
        child_command = child_record["command"]
        child_env = dict(inherited_hostile_env)
        child_env.update(child_record["environment"])
        require(child_command[:5] == [str(PYTHON), "-X", f"pycache_prefix={PREFIX}", "-B", "-m"],
                "CHILD_PRODUCTION_CACHE_ARGUMENTS_DRIFT")
        require(child_record["environment"] == {
            "PYTHONPYCACHEPREFIX": PREFIX,
            "PYTHONDONTWRITEBYTECODE": "1",
            "V4_SOURCE_ONLY_PYCACHE_REQUIRED": "1",
        }, "CHILD_CACHE_POLICY_ENVIRONMENT_DRIFT")

        child_probe = [*child_command[:4], "-c", probe]
        guarded_child = run(child_probe, child_env)
        require(guarded_child.returncode == 0, "CHILD_GUARDED_CACHE_PROBE_FAILED:" + guarded_child.stderr)
        child_result = json.loads(guarded_child.stdout.strip().splitlines()[-1])
        require(child_result["proof"]["source_only_prefix"] == PREFIX, "CHILD_SOURCE_POLICY_NOT_ACTIVE")
        require("CACHE_CONFLICT_EXECUTED" not in guarded_child.stdout, "CHILD_CONFLICT_CACHE_EXECUTED")
        require(not Path(child_result["cache_path"]).exists(), "CHILD_EFFECTIVE_CACHE_PATH_WAS_READABLE")

        help_command = [*child_command, "--help"]
        child_help = run(help_command, child_env)
        require(child_help.returncode == 0 and "Run the due fixed V4 macOS slot" in child_help.stdout,
                "REAL_CHILD_SCHEDULER_ENTRY_DID_NOT_REACH_SAFE_HELP")
        require("SOURCE_ONLY_PYCACHE_POLICY_REJECTED" not in child_help.stdout,
                "REAL_CHILD_SCHEDULER_CACHE_POLICY_REJECTED")

        import ops.research_qfq_dependency_identity as dependency_identity

        qfq_environment = dependency_identity.environment_identity(set())
        require(qfq_environment["pycache_prefix"] == PREFIX, "QFQ_RUNTIME_IDENTITY_OMITS_SOURCE_CACHE_PREFIX")

        from ops import run_v4_macos_scheduler_daemon as daemon

        with tempfile.TemporaryDirectory(prefix="v4-r4-daemon-identity-") as temp:
            manifest_path = Path(temp).resolve() / "release-manifest.json"
            release_id = "v4-main-r4-cache-policy-probe"
            manifest_path.write_text(json.dumps({"app_root": str(APP), "release_id": release_id}))
            previous = {name: os.environ.get(name) for name in (
                "V4_APP_ROOT", "V4_RELEASE_MANIFEST_PATH", "V4_RELEASE_MANIFEST_SHA256")}
            manifest_sha = digest(manifest_path)
            os.environ.update(V4_APP_ROOT=str(APP), V4_RELEASE_MANIFEST_PATH=str(manifest_path),
                              V4_RELEASE_MANIFEST_SHA256=manifest_sha)
            try:
                daemon_identity = daemon._loaded_daemon_identity(release_id)
            finally:
                for name, value in previous.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
        require(daemon_identity["daemon_pid"] == os.getpid(), "DAEMON_PID_PROOF_MISMATCH")
        require(daemon_identity["release_manifest_sha256"] == manifest_sha,
                "DAEMON_RELEASE_MANIFEST_PROOF_MISMATCH")
        require(digest(SOURCE_MODULE) == source_sha_before, "CONFLICT_TEST_CHANGED_FROZEN_SOURCE")

        receipt = {
            "schema": "v4.r4_source_only_cache_probe.v1",
            "status": "PASS_MACOS_CPYTHON314_PARENT_AND_CHILD",
            "python": sys.version,
            "interpreter": str(PYTHON),
            "interpreter_sha256": digest(PYTHON),
            "app_root": str(APP),
            "release_root": str(RELEASE),
            "no_site": True,
            "launcher_sha256": digest(launcher),
            "daemon_sha256": digest(APP / "ops/run_v4_macos_scheduler_daemon.py"),
            "scheduler_sha256": digest(APP / "ops/run_v4_macos_scheduler.py"),
            "policy_source_sha256": source_sha_before,
            "source_sha_unchanged": True,
            "runtime_bytecode_files_hash_bound": len(runtime_cache_rows),
            "app_sourceless_bytecode_files": sourceless_app_bytecode,
            "conflict_cache_sha256": conflict_sha,
            "conflict_cache_bytes": len(cached_bytes),
            "conflict_cache_timestamp_and_size_header_matches_source": True,
            "control_without_source_only_prefix": "CACHE_CONFLICT_EXECUTED",
            "parent": {
                "flags": parent_flags,
                "inherited_pycache_prefix": hostile_prefix,
                "effective_sys_prefix": parent_result["cache_prefix"],
                "effective_module_origin": parent_result["module_file"],
                "proof": parent_result["proof"],
                "conflict_cache_result": "IGNORED_SOURCE_MODULE_EXECUTED",
                "actual_daemon_entry": "--help only, no scheduler loop",
                "daemon_help_return_code": daemon_help.returncode,
            },
            "child": {
                "actual_command_prefix": child_command[:5],
                "child_environment": child_record["environment"],
                "effective_sys_prefix": child_result["cache_prefix"],
                "effective_module_origin": child_result["module_file"],
                "proof": child_result["proof"],
                "conflict_cache_result": "IGNORED_SOURCE_MODULE_EXECUTED",
                "actual_scheduler_entry": "--help only, no scheduler call",
                "scheduler_help_return_code": child_help.returncode,
            },
            "qfq_runtime_identity": {
                "pycache_prefix": qfq_environment["pycache_prefix"],
                "canonical_manifest_sha256": hashlib.sha256(
                    json.dumps(qfq_environment, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            },
            "loaded_daemon_identity_readback": daemon_identity,
            "side_effects": {
                "scheduler_triggered": False,
                "production_paths_opened": False,
                "lane_or_registry_locks_acquired": False,
                "source_cache_removed_after_test": True,
            },
        }
        output = Path(__file__).resolve().parent / "CACHE_POLICY_TEST_RECEIPT.json"
        output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"status": receipt["status"], "parent": receipt["parent"]["conflict_cache_result"],
                          "child": receipt["child"]["conflict_cache_result"],
                          "interpreter_sha256": receipt["interpreter_sha256"]}))
    finally:
        CACHE_FILE.unlink(missing_ok=True)
        if CACHE_FILE.parent.exists() and not any(CACHE_FILE.parent.iterdir()):
            CACHE_FILE.parent.rmdir()


if __name__ == "__main__":
    main()
