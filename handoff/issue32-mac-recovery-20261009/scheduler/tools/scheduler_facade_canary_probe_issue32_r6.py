from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def main() -> None:
    if len(sys.argv) != 10:
        raise SystemExit("EXPECTED_PROBE_ARGUMENTS")
    app_root = Path(sys.argv[1])
    data_root = Path(sys.argv[2])
    input_root = Path(sys.argv[3])
    shared_data_root = Path(sys.argv[4])
    shared_package_root = Path(sys.argv[5])
    universe_root = Path(sys.argv[6])
    tdx_root = Path(sys.argv[7])
    materializer_stdout = Path(sys.argv[8]).read_text(encoding="utf-8")
    materializer_stderr = Path(sys.argv[9]).read_text(encoding="utf-8")
    materializer_result = json.loads(
        (app_root.parent / "materializer_result.json").read_text(encoding="utf-8")
    )
    materializer_returncode = int(materializer_result["returncode"])

    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.scheduling import executor_registry as facade

    bound_method = facade.FixedExecutorRegistry._preselection_pools
    candidate_handler_path = (app_root / "infrastructure/scheduling/executor_registry_preselection.py").resolve()
    bound_code_path = Path(bound_method.__code__.co_filename).resolve()
    loader_check = {
        "facade_path": str(Path(facade.__file__).resolve()),
        "candidate_handler_path": str(candidate_handler_path),
        "bound_method_code_filename": bound_method.__code__.co_filename,
        "bound_method_code_resolves_to_candidate_handler": bound_code_path == candidate_handler_path,
        "bound_method_globals_are_facade_globals": bound_method.__globals__ is vars(facade),
        "timeout_global_value": bound_method.__globals__.get("_V192_PRESELECTION_TIMEOUT_SECONDS"),
        "bound_method_module": bound_method.__module__,
    }
    if not all((loader_check["bound_method_code_resolves_to_candidate_handler"],
                loader_check["bound_method_globals_are_facade_globals"],
                loader_check["timeout_global_value"] == 1800)):
        raise SystemExit("ACTUAL_FACADE_LOADER_DID_NOT_BIND_CANDIDATE_HANDLER")

    calls: list[dict[str, Any]] = []
    forbidden_calls: list[str] = []
    unknown_calls: list[str] = []

    def runner(command, *, cwd=None, timeout_seconds=None, env=None):
        module = str(command[2]) if len(command) > 2 else ""
        args = [str(item) for item in command[3:]]
        calls.append({
            "module": module,
            "arguments": args,
            "cwd": str(cwd or ""),
            "timeout_seconds": timeout_seconds,
            "isolated_root_bindings": {
                key: (env or {}).get(key)
                for key in (
                    "V3_SHARED_DATA_STORE_ROOT", "V35_SHARED_PACKAGE_ROOT",
                    "V3_SHARED_SELECTOR_READY_PANEL", "V3_SHARED_HK_TDX_ROOT",
                )
            },
        })
        if module == "ops.materialize_scheduled_preselection":
            return subprocess.CompletedProcess(
                command, materializer_returncode, materializer_stdout, materializer_stderr
            )
        if module == "ops.ensure_hk_security_master":
            payload = {
                "schema_version": "v3_5.hk_security_master_preparation.v1",
                "status": "FAILED",
                "failure_class": "HK_SECURITY_MASTER_NEEDS_VERIFIED_SOURCE",
                "trade_date": "20261008",
                "reason": "exact-date authoritative security master input unavailable",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
            return subprocess.CompletedProcess(
                command, 1, json.dumps(payload, ensure_ascii=False),
                "HK_SECURITY_MASTER_NEEDS_VERIFIED_SOURCE: trade_date=20261008",
            )
        if module == "scripts.materialize_hk_0_2":
            forbidden_calls.append(module)
            return subprocess.CompletedProcess(command, 1, "", "MUST_NOT_SCORE_HK")
        if module == "scripts.capture_public_fupan":
            return subprocess.CompletedProcess(command, 1, "", "EXACT_INPUT_MISSING:20261008")
        if module in {"ops.materialize_shared_v192_preselection", "scripts.update_hk_0_2_panel"}:
            return subprocess.CompletedProcess(
                command, 0,
                json.dumps({"status": "SUCCEEDED", "production_allowed": False,
                            "buy_gate_updated": False, "orders_sent": False}),
                "",
            )
        unknown_calls.append(module)
        return subprocess.CompletedProcess(command, 1, "", f"UNEXPECTED_EXTERNAL_MODULE:{module}")

    # This is a process-local harness for the external-runner seam; avoid inheriting
    # an explicit machine HK runtime that would make an unrelated runtime gate win.
    os.environ.pop("V35_HK_0_2_PYTHON", None)
    registry = facade.FixedExecutorRegistry(
        data_root=data_root,
        shared_data_root=shared_data_root,
        hk_universe_root=universe_root,
        shared_package_root=shared_package_root,
        shared_futu_python_executable=sys.executable,
        selector_data_root=None,
        preselection_input_root=input_root,
        repo_root=app_root,
        runner=runner,
        hk_0_2_tdx_root=tdx_root,
    )
    request = DispatchRequest(
        scheduled_date="20261009",
        business_date="20261008",
        target_date="20261009",
        slot="0930",
        mode=DispatchMode.REPLAY,
    )
    result = registry._preselection_pools(request)
    print(json.dumps({
        "loader_check": loader_check,
        "candidate_executor_result": {
            key: result.get(key) for key in (
                "status", "exit_code", "failure_class", "first_gate",
                "a_selector_status", "hk_lane_status", "hk_local_pool_gate_status",
                "materializer_status", "formal_pool_gate", "producer_called",
                "write_performed", "modules",
            )
        },
        "candidate_child_calls": calls,
        "forbidden_hk_scoring_calls": forbidden_calls,
        "unknown_child_calls": unknown_calls,
        "handler_materializer_arguments": next(
            (call["arguments"] for call in calls if call["module"] == "ops.materialize_scheduled_preselection"),
            None,
        ),
        "safe_external_runner_stubbed": True,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
