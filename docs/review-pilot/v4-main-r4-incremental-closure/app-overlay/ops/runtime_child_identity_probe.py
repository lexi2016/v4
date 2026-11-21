"""Read-only Mac child identity probe used only by the isolated R4 fixture."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
from datetime import datetime
from zoneinfo import ZoneInfo


SOURCE_ONLY_PYCACHE_PREFIX = "/dev/null/v4-main-r4-source-only-pycache"
QFQ_ENV_NAMES = (
    "V4_A_QFQ_COMPUTE_BACKEND", "V4_A_QFQ_SOURCE_REPAIR_DATE",
    "V4_A_QFQ_SOURCE_REPAIR_INPUT", "V4_A_QFQ_SOURCE_REPAIR_INPUT_SHA256",
    "V4_QFQ_CONVENTION_ACCEPTANCE_PATH", "V4_QFQ_CONVENTION_ACCEPTANCE_SHA256",
    "RESEARCH_PANEL_QFQ_REFRESH_FACTORS",
)
CHAIN_FILES = (
    "ops/runtime_child_identity_probe.py",
    "ops/run_v4_macos_scheduler_daemon.py",
    "ops/run_v4_macos_scheduler.py",
    "infrastructure/scheduling/executor_registry.py",
    "infrastructure/scheduling/executor_registry_review.py",
    "ops/macos_research_panel_daily.py",
    "ops/macos_research_panel_daily_authority.py",
    "ops/research_panel_qfq.py",
    "ops/research_storage_governance.py",
    "ops/research_qfq_dependency_identity.py",
    "ops/qfq_directory_contract.py",
)


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_regular_sha(path: Path) -> dict:
    before = path.lstat()
    if path.is_symlink() or not path.is_file():
        return {"status": "CANNOT_CONFIRM_NOT_REGULAR", "path": str(path), "sha256": None}
    value = _sha_file(path)
    after = path.lstat()
    stable = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    return {"status": "READ_ONLY_STABLE" if stable else "CANNOT_CONFIRM_CHANGED_DURING_READ",
            "path": str(path), "sha256": value if stable else None, "size": before.st_size}


def _environment_digest(environment: dict[str, str]) -> str:
    raw = "".join(f"{key}={environment[key]}\n" for key in sorted(environment)).encode("utf-8")
    return _sha_bytes(raw)


def _manifest_and_keys(dates: list[int]) -> dict:
    from ops.research_qfq_dependency_identity import computation_dependencies
    from ops.research_storage_governance import qfq_invocation_key
    from ops.research_storage_retention import canonical

    module = importlib.import_module("ops.research_panel_qfq")
    app_root = Path(__file__).resolve().parents[1]
    environment = os.environ
    required = {
        "V4_RESEARCH_PANEL_A_TDX_ROOT": environment.get("V4_RESEARCH_PANEL_A_TDX_ROOT"),
        "V4_RESEARCH_PANEL_A_DATA_ROOT": environment.get("V4_RESEARCH_PANEL_A_DATA_ROOT"),
        "V4_RESEARCH_PANEL_A_SELECTOR_POINTER": environment.get("V4_RESEARCH_PANEL_A_SELECTOR_POINTER"),
        "V4_RESEARCH_PANEL_A_BACKTEST_POINTER": environment.get("V4_RESEARCH_PANEL_A_BACKTEST_POINTER"),
        "V4_RESEARCH_PANEL_A_CONTRACT_CSV": environment.get("V4_RESEARCH_PANEL_A_CONTRACT_CSV"),
        "V4_RESEARCH_PANEL_A_CANONICAL_FORMULA": environment.get("V4_RESEARCH_PANEL_A_CANONICAL_FORMULA"),
        "V4_RESEARCH_PANEL_A_RETURN_ROOT": environment.get("V4_RESEARCH_PANEL_A_RETURN_ROOT"),
    }
    missing = [name for name, value in required.items() if not isinstance(value, str) or not value.strip()]
    if missing:
        raise RuntimeError("QFQ_REQUIRED_BINDING_MISSING:" + ",".join(missing))

    data_root = Path(required["V4_RESEARCH_PANEL_A_DATA_ROOT"]).resolve()
    driver_path = (app_root / "ops/vendor/data_layer_daily_formula_increment_update_v1.py").resolve()
    formula_path = Path(required["V4_RESEARCH_PANEL_A_CANONICAL_FORMULA"]).resolve()
    # Match macos_research_panel_daily_authority.run_windows_a_sync_authority.
    kwargs = {
        "driver_path": driver_path,
        "formula_path": formula_path,
        "tdx_root": Path(required["V4_RESEARCH_PANEL_A_TDX_ROOT"]).resolve(),
        "data_root": data_root,
        "pointers": {
            "selector": Path(required["V4_RESEARCH_PANEL_A_SELECTOR_POINTER"]).absolute(),
            "backtest": Path(required["V4_RESEARCH_PANEL_A_BACKTEST_POINTER"]).absolute(),
        },
        "contract_csv": Path(required["V4_RESEARCH_PANEL_A_CONTRACT_CSV"]).resolve(),
        "return_root": Path(required["V4_RESEARCH_PANEL_A_RETURN_ROOT"]).resolve(),
        "target": dates[-1],
        "publish": True,
        "workers": None,
        "refresh_inputs": True,
        "storage_layout": "arrow_blocks_v1",
    }
    runtime_root = module.input_path(data_root).parent
    dependencies = computation_dependencies(module, kwargs, runtime_root=runtime_root)
    manifest_sha = canonical(dependencies)
    keys = {}
    for target in dates:
        target_kwargs = dict(kwargs, target=target)
        keys[str(target)] = qfq_invocation_key(module, data_root, target, target_kwargs)

    chain = {}
    for relative in CHAIN_FILES:
        path = app_root / relative
        chain[relative] = {"path": str(path), "sha256": _sha_file(path) if path.is_file() else None}

    manifest_path_text = environment.get("V4_RELEASE_MANIFEST_PATH")
    manifest_sha_expected = environment.get("V4_RELEASE_MANIFEST_SHA256")
    if not manifest_path_text or not manifest_sha_expected:
        raise RuntimeError("CANDIDATE_RELEASE_MANIFEST_BINDING_MISSING")
    manifest_path = Path(manifest_path_text)
    manifest_record = _stable_regular_sha(manifest_path)
    if (manifest_record.get("status") != "READ_ONLY_STABLE"
            or manifest_record.get("sha256") != manifest_sha_expected):
        raise RuntimeError("CANDIDATE_RELEASE_MANIFEST_SHA_MISMATCH")
    release_manifest = json.loads(manifest_path.read_bytes())
    release_id = environment.get("V4_RELEASE_ID")
    if (release_manifest.get("release_id") != release_id
            or release_manifest.get("app_root") != str(app_root)
            or Path(sys.executable).resolve() != Path(environment.get("V4_RUNTIME_ROOT", "")) / "venvs/v4-mac/bin/python"):
        raise RuntimeError("CANDIDATE_RELEASE_ID_ROOT_OR_INTERPRETER_MISMATCH")

    policy_path = Path(environment["V4_RESEARCH_RETENTION_POLICY"])
    policy_record = _stable_regular_sha(policy_path)
    if (policy_record.get("status") != "READ_ONLY_STABLE"
            or policy_record.get("sha256") != environment.get("V4_RESEARCH_RETENTION_POLICY_SHA256")):
        raise RuntimeError("CANDIDATE_POLICY_SHA_MISMATCH")
    policy = json.loads(policy_path.read_bytes())
    if (Path(policy.get("data_root", "")).resolve() != data_root
            or Path(policy.get("run_root", "")).resolve() != kwargs["return_root"]):
        raise RuntimeError("QFQ_DATA_OR_RETURN_ROOT_POLICY_MISMATCH")
    governance = policy.get("governance") or {}
    registry_root_text = governance.get("registry_root")
    registry_root = Path(registry_root_text) if isinstance(registry_root_text, str) and registry_root_text else None
    registry_path = registry_root / "registry.json" if registry_root is not None else None
    registry_record = (_stable_regular_sha(registry_path) if registry_path is not None
                       else {"status": "CANNOT_CONFIRM_REGISTRY_ROOT_MISSING", "path": None, "sha256": None})

    flags = {name: getattr(sys.flags, name) for name in (
        "debug", "inspect", "optimize", "dont_write_bytecode", "no_user_site", "no_site",
        "ignore_environment", "isolated", "safe_path", "utf8_mode")}
    stdlib = Path(sysconfig.get_path("stdlib")).resolve()
    runtime_root = Path(environment["V4_RUNTIME_ROOT"]).resolve()
    expected_prefix = runtime_root / "python/cpython-3.14.6"
    pycache_prefix = str(sys.pycache_prefix) if sys.pycache_prefix is not None else None
    if (sys.flags.no_site != 0 or sys.flags.no_user_site != 1
            or sys.dont_write_bytecode is not True
            or pycache_prefix != SOURCE_ONLY_PYCACHE_PREFIX
            or Path(sys.base_prefix).resolve() != expected_prefix
            or Path(sys.executable).resolve() != runtime_root / "venvs/v4-mac/bin/python"
            or os.environ.get("PYTHONNOUSERSITE") != "1"):
        raise RuntimeError("QFQ_CHILD_INTERPRETER_FLAGS_OR_PREFIX_MISMATCH")

    return {
        "status": "PASS_READ_ONLY_QFQ_CHILD_IDENTITY",
        "release_id": release_id,
        "release_root": str(Path(environment["V4_APP_ROOT"]).resolve().parent),
        "app_root": str(app_root),
        "runtime_root": str(runtime_root),
        "release_manifest": {**manifest_record, "expected_sha256": manifest_sha_expected,
                              "application_inventory_sha256": release_manifest.get("application_inventory", {}).get("aggregate_sha256")},
        "helper": {"path": str(Path(__file__).resolve()), "sha256": _sha_file(Path(__file__).resolve())},
        "executable": str(Path(sys.executable).resolve()),
        "executable_sha256": _sha_file(Path(sys.executable).resolve()),
        "python": sys.version,
        "cache_tag": sys.implementation.cache_tag,
        "flags": flags,
        "no_site": sys.flags.no_site,
        "no_user_site": sys.flags.no_user_site,
        "base_prefix": str(Path(sys.base_prefix).resolve()),
        "stdlib_root": str(stdlib),
        "pycache_prefix": pycache_prefix,
        "effective_sys_path": list(sys.path),
        "environment_sha256": _environment_digest(dict(os.environ)),
        "environment_key_names": sorted(os.environ),
        "qfq_environment_values": {name: os.environ.get(name) for name in QFQ_ENV_NAMES},
        "computation_manifest_sha256": manifest_sha,
        "computation_source_roles": len(dependencies.get("dependencies", [])),
        "computation_manifest": dependencies,
        "qfq_operation_keys": keys,
        "source_chain": chain,
        "data_root": str(data_root),
        "return_root": str(kwargs["return_root"]),
        "registry_root": str(registry_root) if registry_root else None,
        "registry_path": str(registry_path) if registry_path else None,
        "registry_sha256": registry_record.get("sha256"),
        "registry_read_status": registry_record.get("status"),
        "claim_begin_called": False,
        "admission_called": False,
        "production_owner_called": False,
        "registry_mutated": False,
        "current_pointer_mutated": False,
    }


def _run_identity_probe(dates: list[int]) -> dict:
    if len(dates) != 2 or dates != [20261120, 20261123]:
        raise RuntimeError("R4_TARGET_DATE_SET_MISMATCH")
    return _manifest_and_keys(dates)


def _run_executor_fixture(business_date: str, slot: str, ledger_root: Path) -> dict:
    """Call the actual A executor method and _run, redirecting only the child module."""
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from infrastructure.scheduling.executor_registry_review import _NATURAL_DISPATCH_CONTEXT_ENV

    app_root = Path(__file__).resolve().parents[1]
    run_id = "f" * 32
    now = "2026-11-23T15:40:00+08:00"
    dispatch = {"schema_version": "v3_5.dispatch_claim.v1", "business_date": business_date,
                "target_date": business_date, "slot": slot, "mode": "LIVE", "run_id": run_id,
                "pid": os.getpid(), "created_at": now}
    workload = {**dispatch, "schema_version": "v3_5.workload_claim.v1",
                "workload_id": "research_panel_daily_a"}
    dispatch_path = ledger_root / "claims/live" / business_date / slot / "dispatch.claim.json"
    workload_path = ledger_root / "workloads/live" / business_date / slot / "research_panel_daily_a.workload-claim.json"
    dispatch_path.parent.mkdir(parents=True, exist_ok=True)
    workload_path.parent.mkdir(parents=True, exist_ok=True)
    dispatch_path.write_text(json.dumps(dispatch, sort_keys=True, separators=(",", ":")) + "\n")
    workload_path.write_text(json.dumps(workload, sort_keys=True, separators=(",", ":")) + "\n")

    captured: dict = {}

    def runner(command, *, cwd, timeout_seconds, env=None):
        if command[0] != sys.executable or command[1:3] != ["-m", "ops.macos_research_panel_daily"]:
            raise RuntimeError("A_EXECUTOR_RUN_COMMAND_SHAPE_MISMATCH")
        child_env = dict(os.environ) if env is None else dict(env)
        probe_command = command[:2] + ["ops.runtime_child_identity_probe", "--mode", "qfq-owner",
                                       "--dates", "20261120", "20261123"]
        result = subprocess.run(probe_command, cwd=cwd, env=child_env,
            shell=False, timeout=timeout_seconds, capture_output=True, text=True,
            encoding="utf-8", check=False)
        if result.returncode != 0:
            raise RuntimeError("QFQ_CHILD_READ_ONLY_IDENTITY_PROBE_FAILED:" + result.stderr[-2000:])
        qfq_identity = json.loads(result.stdout)
        captured.update({
            "module": "ops.macos_research_panel_daily",
            "arguments": command[3:],
            "command": command,
            "command_sha256": _sha_bytes(json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode()),
            "cwd": str(cwd),
            "timeout_seconds": timeout_seconds,
            "environment_sha256": _environment_digest(child_env),
            "environment_key_names": sorted(child_env),
            "environment_py_no_user_site": child_env.get("PYTHONNOUSERSITE"),
            "identity_probe_module_substitution": {
                "original": "ops.macos_research_panel_daily",
                "substitute": "ops.runtime_child_identity_probe",
                "owner_or_provider_invoked": False,
            },
            "qfq_identity_probe": qfq_identity,
        })
        # Return a bounded, structurally valid failure payload so the actual
        # executor review method exits before any receipt or provider fallback.
        return {"returncode": 0, "stdout": "", "stderr": "",
                "authoritative_payload": {
                    "status": "CANNOT_CONFIRM", "lane": "A",
                    "lanes": {"A": {"status": "CANNOT_CONFIRM",
                                      "reason": "READ_ONLY_IDENTITY_FIXTURE"}},
                    "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
                }}

    os.environ["V4_DISPATCH_LEDGER_ROOT"] = str(ledger_root)
    registry = FixedExecutorRegistry(
        data_root=os.environ["V4_DATA_ROOT"], repo_root=app_root,
        runner=runner, hk_0_2_python_executable=Path(sys.executable),
        a_daily_timeout_seconds=14400,
    )
    registry._active_workload_id = "research_panel_daily_a"
    request = DispatchRequest(scheduled_date=business_date, business_date=business_date,
                              target_date=business_date, slot=slot, mode=DispatchMode.LIVE)
    expected_error = None
    expected_error_detail = None
    try:
        registry._research_panel_daily(request, lane="A")
    except Exception as error:
        expected_error = type(error).__name__
        expected_error_detail = f"{type(error).__name__}:{str(error)[:1000]}"
    if not captured:
        raise RuntimeError("A_EXECUTOR_RUN_WAS_NOT_CAPTURED:" + str(expected_error_detail))
    if expected_error != "WorkloadExecutionError":
        raise RuntimeError("A_EXECUTOR_FIXTURE_DID_NOT_STOP_AT_READ_ONLY_NEGATIVE:" + str(expected_error))
    return {"status": "PASS_ACTUAL_A_EXECUTOR_RUN_CAPTURE",
            "dispatch_context_fixture": {"run_id": run_id, "business_date": business_date,
                                          "slot": slot,
                                          "dispatch_claim_sha256": _sha_file(dispatch_path),
                                          "workload_claim_sha256": _sha_file(workload_path),
                                          "files_in_temporary_fixture_root": True},
            "task_key": None, "attempt_id": None,
            "expected_terminal_error": expected_error,
            "expected_terminal_error_detail": expected_error_detail,
            "claim_begin_called": False, "provider_invoked": False,
            "production_registry_mutated": False,
            "captured_executor_run": captured}


def _run_daemon_parent_fixture(business_date: str, slot: str, ledger_root: Path) -> dict:
    """Use the actual slot controller/Popen builder with a fake child factory."""
    from ops.runtime_bytecode_policy import SOURCE_ONLY_PYCACHE_PREFIX, require_source_only_cache_policy
    from ops.run_v4_macos_scheduler_daemon import SlotProcessLanes

    cache_policy = require_source_only_cache_policy()
    if cache_policy is None or sys.flags.no_site != 1:
        raise RuntimeError("DAEMON_PARENT_NO_SITE_CACHE_POLICY_REQUIRED")
    expected_app = Path(os.environ["V4_APP_ROOT"]).resolve()
    release_root = expected_app.parent
    if Path.cwd() != expected_app:
        raise RuntimeError("DAEMON_PARENT_CWD_MISMATCH")

    scheduler_argv = [
        "--data-root", os.environ["V4_DATA_ROOT"],
        "--ledger-root", str(ledger_root),
        "--preselection-input-root", os.environ["V4_PRESELECTION_INPUT_ROOT"],
        "--stage-selection-root", os.environ["V4_STAGE_CENTER_SELECTION_ROOT"],
        "--hk-0-2-python", os.environ.get("V4_HK_0_2_PYTHON") or str(Path(sys.executable)),
        "--a-daily-timeout-seconds", "14400",
    ]
    for env_name, option in (
        ("V4_SHARED_DATA_ROOT", "--shared-data-root"),
        ("V4_HK_UNIVERSE_ROOT", "--hk-universe-root"),
        ("V4_SHARED_PACKAGE_ROOT", "--shared-package-root"),
        ("V4_SELECTOR_DATA_ROOT", "--selector-data-root"),
    ):
        if os.environ.get(env_name):
            scheduler_argv.extend((option, os.environ[env_name]))

    captured: dict = {}
    os.environ["V4_DISPATCH_LEDGER_ROOT"] = str(ledger_root)

    class FakeChild:
        pid = 917263

        def poll(self):
            return None

        def wait(self, timeout=None):
            return None

    def capture_popen(command, *, cwd, env, **kwargs):
        captured.update({"argv": list(command),
                         "argv_sha256": _sha_bytes(json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode()),
                         "cwd": str(cwd),
                         "environment_sha256": _environment_digest(dict(env)),
                         "environment_keys": sorted(env),
                         "environment_allowlist": {key: env.get(key) for key in (
                             "PYTHONNOUSERSITE", "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE",
                             "V4_SOURCE_ONLY_PYCACHE_REQUIRED", "V4_RELEASE_ID", "V4_APP_ROOT",
                             "V4_RUNTIME_ROOT", "V4_RELEASE_MANIFEST_PATH", "V4_RELEASE_MANIFEST_SHA256",
                             "V4_RESEARCH_RETENTION_POLICY", "V4_RESEARCH_RETENTION_POLICY_SHA256",
                             "V4_DISPATCH_LEDGER_ROOT", "V4_SCHEDULER_LANE_FD",
                             "V4_SCHEDULER_LANE_NAME", "V4_SCHEDULER_RESOLVED_DATE",
                             "V4_SCHEDULER_RESOLVED_SLOT", "V4_QFQ_CONVENTION_ACCEPTANCE_PATH",
                             "V4_QFQ_CONVENTION_ACCEPTANCE_SHA256",
                             "V4_RESEARCH_PANEL_A_SYNC_SCRIPT",
                             "V4_RESEARCH_PANEL_A_DATA_ROOT", "V4_RESEARCH_PANEL_A_RETURN_ROOT")},
                         "popen_kwargs": {"start_new_session": kwargs.get("start_new_session"),
                                          "close_fds": kwargs.get("close_fds"),
                                          "pass_fds_count": len(kwargs.get("pass_fds", ()))},
                         "popen_factory_is_fake": True,
                         "_captured_environment": dict(env)})
        return FakeChild()

    controller = SlotProcessLanes(scheduler_argv, release_id=os.environ["V4_RELEASE_ID"],
                                  popen_factory=capture_popen,
                                  clock=lambda: datetime(2026, 11, 23, 15, 40, tzinfo=ZoneInfo("Asia/Shanghai")))
    moment = datetime(2026, 11, 23, 15, 40, tzinfo=ZoneInfo("Asia/Shanghai"))
    controller.enqueue(business_date, slot, moment)
    controller.pulse(moment, dispatch=True)
    if not captured:
        raise RuntimeError("ACTUAL_DAEMON_POPEN_BUILDER_NOT_CALLED")
    for job in controller.active.values():
        for stream_name in ("stdout", "stderr"):
            try:
                job[stream_name].close()
            except Exception:
                pass
    if captured.get("environment_allowlist", {}).get("PYTHONNOUSERSITE") != "1":
        raise RuntimeError("PYTHONNOUSERSITE_NOT_BOUND_BEFORE_POPEN")

    command = captured["argv"]
    module_index = command.index("-m") + 1
    if command[module_index] != "ops.run_v4_macos_scheduler":
        raise RuntimeError("DAEMON_SCHEDULER_MODULE_BINDING_MISMATCH")
    probe_command = command[:module_index] + ["ops.runtime_child_identity_probe", "--mode", "daemon-child",
        "--date", business_date, "--slot", slot, "--ledger-root", str(ledger_root)]
    # The Popen factory above captured, but did not execute, the true
    # scheduler child. This exact interpreter/flags/env process substitutes
    # only the scheduler module with the bounded read-only fixture.
    captured_env = captured.pop("_captured_environment")
    child = subprocess.run(probe_command, cwd=captured["cwd"], env=captured_env,
                           shell=False, capture_output=True, text=True, encoding="utf-8",
                           timeout=300, check=False)
    if child.returncode != 0:
        raise RuntimeError("DAEMON_CHILD_READ_ONLY_FIXTURE_FAILED:" + child.stderr[-2000:])
    a_fixture = json.loads(child.stdout)
    qfq = a_fixture["captured_executor_run"]["qfq_identity_probe"]
    if (a_fixture.get("status") != "PASS_ACTUAL_A_EXECUTOR_RUN_CAPTURE"
            or qfq.get("status") != "PASS_READ_ONLY_QFQ_CHILD_IDENTITY"):
        raise RuntimeError("DAEMON_TO_A_TO_QFQ_CHAIN_DID_NOT_CLOSE")
    parent_env_sha = _environment_digest(dict(os.environ))
    return {
        "status": "PASS_READ_ONLY_REAL_DAEMON_AND_EXECUTOR_SEAMS",
        "release_id": os.environ["V4_RELEASE_ID"],
        "release_root": str(release_root), "app_root": str(expected_app),
        "runtime_root": os.environ["V4_RUNTIME_ROOT"],
        "parent": {"executable": str(Path(sys.executable).resolve()),
                   "executable_sha256": _sha_file(Path(sys.executable).resolve()),
                   "python": sys.version, "flags": {name: getattr(sys.flags, name) for name in (
                       "no_site", "no_user_site", "dont_write_bytecode", "ignore_environment", "isolated")},
                   "base_prefix": str(Path(sys.base_prefix).resolve()),
                   "stdlib_root": str(Path(sysconfig.get_path("stdlib")).resolve()),
                   "pycache_prefix": sys.pycache_prefix,
                   "environment_sha256": parent_env_sha,
                   "source_only_cache_policy": cache_policy},
        "daemon_popen": captured,
        "scheduler_module_substitution": {"original": "ops.run_v4_macos_scheduler",
                                           "substitute": "ops.runtime_child_identity_probe",
                                           "real_scheduler_started": False},
        "a_executor_fixture": a_fixture,
        "qfq_child_identity": qfq,
        "ledger_root": str(ledger_root),
        "fixture_ledger_only": True,
        "claim_begin_called": False, "admission_called": False,
        "production_owner_called": False, "production_registry_mutated": False,
        "production_current_pointer_mutated": False,
        "old_reservations_changed": False,
        "natural_dispatch_task_key": None,
        "natural_dispatch_attempt_id": None,
        "natural_dispatch_run_id": None,
        "natural_dispatch_generation": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("qfq-owner", "daemon-child", "daemon-parent"), required=True)
    parser.add_argument("--dates", nargs="+", type=int, default=[20261120, 20261123])
    parser.add_argument("--date")
    parser.add_argument("--slot", default="1540")
    parser.add_argument("--ledger-root", type=Path)
    args = parser.parse_args()
    if args.mode == "qfq-owner":
        value = _run_identity_probe(args.dates)
    elif args.mode == "daemon-child":
        if not args.date or args.ledger_root is None:
            raise RuntimeError("DAEMON_CHILD_FIXTURE_ARGUMENTS_REQUIRED")
        value = _run_executor_fixture(args.date, args.slot, args.ledger_root)
    else:
        if not args.date or args.ledger_root is None:
            raise RuntimeError("DAEMON_PARENT_FIXTURE_ARGUMENTS_REQUIRED")
        value = _run_daemon_parent_fixture(args.date, args.slot, args.ledger_root)
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
