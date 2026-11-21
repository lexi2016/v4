"""Recompute read-only QFQ keys from the captured A executor argv."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import sys


TASK = Path(__file__).resolve().parents[1]
RELEASE = TASK / "v4-main-r4-incremental-closure-20261122"
APP = RELEASE / "app"
PYCACHE = "/dev/null/v4-main-r4-source-only-pycache"
IDENTITY_PATH = TASK / "verification/CHILD_IDENTITY_RECEIPT.json"


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_options(arguments: list[str]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    index = 0
    while index < len(arguments):
        option = arguments[index]
        if not option.startswith("--") or index + 1 >= len(arguments):
            raise RuntimeError("ACTUAL_A_EXECUTOR_ARGV_MALFORMED")
        values.setdefault(option, []).append(arguments[index + 1])
        index += 2
    return values


def single_option(options: dict[str, list[str]], name: str) -> str:
    values = options.get(name)
    if not isinstance(values, list) or not values or len(set(values)) != 1:
        raise RuntimeError("ACTUAL_A_EXECUTOR_ARGV_OPTION_CONFLICT:" + name)
    return values[0]


def main() -> None:
    if sys.flags.no_site != 0 or sys.flags.no_user_site != 1 or os.environ.get("PYTHONNOUSERSITE") != "1":
        raise RuntimeError("ACTUAL_QFQ_CHILD_FLAGS_MISMATCH")
    if (sys.dont_write_bytecode is not True or sys.pycache_prefix != PYCACHE
            or os.environ.get("PYTHONPYCACHEPREFIX") != PYCACHE
            or os.environ.get("V4_SOURCE_ONLY_PYCACHE_REQUIRED") != "1"):
        raise RuntimeError("ACTUAL_QFQ_CHILD_CACHE_POLICY_MISMATCH")

    identity = json.loads(IDENTITY_PATH.read_bytes())
    qfq_identity = identity["qfq_child_identity"]
    a_capture = identity["a_executor_fixture"]["captured_executor_run"]
    command = a_capture["command"]
    if (command[:3] != [str(Path(sys.executable).resolve()), "-m", "ops.macos_research_panel_daily"]
            or Path(a_capture["cwd"]).resolve() != APP.resolve()):
        raise RuntimeError("CAPTURED_A_EXECUTOR_COMMAND_IDENTITY_MISMATCH")
    if a_capture["environment_sha256"] != qfq_identity["environment_sha256"]:
        raise RuntimeError("QFQ_PROBE_ENVIRONMENT_NOT_THE_ACTUAL_A_RUN_ENV")

    options = parse_options(command[3:])
    with (RELEASE / "launchd.plist").open("rb") as stream:
        launchd = plistlib.load(stream)
    launch_env = launchd.get("EnvironmentVariables") or {}
    option_env = {
        "--a-tdx-root": "V4_RESEARCH_PANEL_A_TDX_ROOT",
        "--a-data-root": "V4_RESEARCH_PANEL_A_DATA_ROOT",
        "--a-selector-pointer": "V4_RESEARCH_PANEL_A_SELECTOR_POINTER",
        "--a-backtest-pointer": "V4_RESEARCH_PANEL_A_BACKTEST_POINTER",
        "--a-sync-script": "V4_RESEARCH_PANEL_A_SYNC_SCRIPT",
        "--a-formula-script": "V4_RESEARCH_PANEL_A_FORMULA_SCRIPT",
        "--a-selector-seed": "V4_RESEARCH_PANEL_A_SELECTOR_SEED",
        "--a-backtest-seed": "V4_RESEARCH_PANEL_A_BACKTEST_SEED",
        "--a-contract-csv": "V4_RESEARCH_PANEL_A_CONTRACT_CSV",
        "--a-canonical-formula": "V4_RESEARCH_PANEL_A_CANONICAL_FORMULA",
        "--a-return-root": "V4_RESEARCH_PANEL_A_RETURN_ROOT",
    }
    argument_binding = {}
    for option, env_name in option_env.items():
        actual_values = options.get(option)
        expected_value = launch_env.get(env_name)
        if (not isinstance(actual_values, list) or not actual_values or not isinstance(expected_value, str)
                or any(value != expected_value for value in actual_values)):
            raise RuntimeError("A_EXECUTOR_ARGV_TO_PLIST_ENV_MISMATCH:" + option)
        argument_binding[option] = {
            "environment_name": env_name,
            "captured_argv_values": actual_values,
            "plist_environment_value": expected_value,
            "match": True,
        }
    if single_option(options, "--date") != "20261123" or single_option(options, "--lane") != "A":
        raise RuntimeError("A_EXECUTOR_DATE_OR_LANE_IDENTITY_MISMATCH")

    from ops import research_panel_qfq as qfq
    from ops.research_qfq_dependency_identity import computation_dependencies
    from ops.research_storage_governance import canonical, qfq_invocation_key

    data_root = Path(single_option(options, "--a-data-root")).resolve()
    driver_path = (APP / "ops/vendor/data_layer_daily_formula_increment_update_v1.py").resolve()
    formula_path = Path(single_option(options, "--a-canonical-formula")).resolve()
    contract_csv = Path(single_option(options, "--a-contract-csv")).resolve()
    tdx_root = Path(single_option(options, "--a-tdx-root")).resolve()
    selector_pointer = Path(single_option(options, "--a-selector-pointer")).absolute()
    backtest_pointer = Path(single_option(options, "--a-backtest-pointer")).absolute()
    return_root = Path(single_option(options, "--a-return-root")).resolve()
    kwargs = {
        "driver_path": driver_path,
        "formula_path": formula_path,
        "tdx_root": tdx_root,
        "data_root": data_root,
        "pointers": {"selector": selector_pointer, "backtest": backtest_pointer},
        "contract_csv": contract_csv,
        "return_root": return_root,
        "target": 20261123,
        "publish": True,
        "workers": None,
        "refresh_inputs": True,
        "storage_layout": "arrow_blocks_v1",
    }
    manifest = computation_dependencies(qfq, kwargs, runtime_root=qfq.input_path(data_root).parent)
    manifest_sha = canonical(manifest)
    keys = {}
    for target in (20261120, 20261123):
        target_kwargs = dict(kwargs, target=target)
        keys[str(target)] = qfq_invocation_key(qfq, data_root, target, target_kwargs)

    expected_dependencies = {
        "driver_path": str(driver_path),
        "formula_path": str(formula_path),
        "contract_csv": str(contract_csv),
    }
    dependency_roles = {}
    for role, path in expected_dependencies.items():
        matches = [row for row in manifest.get("dependencies", []) if role in row.get("used_by", [])]
        recorded_path = matches[0].get("path") if len(matches) == 1 else None
        resolved_recorded_path = (
            str((APP / recorded_path).resolve())
            if isinstance(recorded_path, str) and not Path(recorded_path).is_absolute()
            else recorded_path
        )
        if len(matches) != 1 or resolved_recorded_path != path:
            raise RuntimeError("QFQ_ACTUAL_ARG_DEPENDENCY_ROLE_MISMATCH:" + role)
        dependency_roles[role] = {
            "argv_or_runtime_path": path,
            "dependency_path": recorded_path,
            "resolved_dependency_path": resolved_recorded_path,
            "sha256": matches[0]["sha256"],
            "match": True,
        }
    if keys != qfq_identity["qfq_operation_keys"]:
        raise RuntimeError("QFQ_ACTUAL_ARG_RECOMPUTED_KEY_MISMATCH")
    if manifest_sha != qfq_identity["computation_manifest_sha256"]:
        raise RuntimeError("QFQ_ACTUAL_ARG_COMPUTATION_MANIFEST_SHA_MISMATCH")

    receipt = {
        "schema": "v4.r4_actual_a_argv_to_qfq_key_recompute.v1",
        "status": "PASS_ACTUAL_A_ARGV_BINDS_QFQ_KEYS",
        "release_id": identity["release_id"],
        "release_manifest_sha256": identity["release_manifest_sha256"],
        "application_inventory_sha256": qfq_identity["release_manifest"]["application_inventory_sha256"],
        "identity_receipt": {
            "path": str(IDENTITY_PATH),
            "sha256": sha_file(IDENTITY_PATH),
            "size": IDENTITY_PATH.stat().st_size,
        },
        "captured_a_executor_argv_sha256": a_capture["command_sha256"],
        "captured_a_executor_environment_sha256": a_capture["environment_sha256"],
        "qfq_child_environment_sha256": qfq_identity["environment_sha256"],
        "effective_sys_path": qfq_identity["effective_sys_path"],
        "sys_flags": qfq_identity["flags"],
        "pythonno_usersite": os.environ.get("PYTHONNOUSERSITE"),
        "no_site": sys.flags.no_site,
        "argument_binding": argument_binding,
        "dependency_roles": dependency_roles,
        "computation_manifest_sha256": manifest_sha,
        "computation_environment_sha256": canonical(manifest["environment"]),
        "effective_sys_path": qfq_identity["effective_sys_path"],
        "qfq_operation_keys": keys,
        "claim_begin_called": False,
        "admission_called": False,
        "provider_invoked": False,
        "production_registry_mutated": False,
        "production_current_pointer_mutated": False,
        "old_reservations_changed": False,
        "natural_dispatch": "NOT_RUN",
    }
    path = TASK / "verification/ACTUAL_A_ARGV_QFQ_KEY_RECOMPUTE_RECEIPT.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "keys": keys, "manifest_sha256": manifest_sha,
                      "argument_count": len(argument_binding)}, sort_keys=True))


if __name__ == "__main__":
    main()
