#!/usr/bin/env python3
"""Run one exact historical plan-owner HTTP canary; dry-run is the default.

The execute mode calls only the immutable candidate API in-process through
ASGI, against the existing formal manager state root. It never opens a socket,
loads a scheduler binding, captures announcements, or changes a LaunchAgent.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import plistlib
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only")
API_RELEASE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r2-api")
API_ROOT = API_RELEASE_ROOT / "app"
FORMAL_MANAGER_STATE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research")
TARGET = "20260925"
PLIST_PATH = TASK_ROOT / "staged_config/com.lexi.v35.api-only.c1-final-d1-r2.plist"
BINDING_PATH = TASK_ROOT / "staged_config/manager-plan-binding-c1.disabled.final-d1-r2.json"
OUTPUT_ROOT = TASK_ROOT / "plan_canary_runs" / TARGET / "execution-01"
BASE_URL = "http://127.0.0.1:8873"
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
EXECUTION_MODE = "HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK"
PROTECTED_DATES = ("20261007", "20261008")
SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8"))


def _write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def _tree_hashes(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_dir():
        raise ValueError("D1_PROTECTED_STATE_PATH_NOT_EXACT:" + str(path))
    result: dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise ValueError("D1_PROTECTED_STATE_SYMLINK:" + str(item))
        if item.is_file():
            result[item.relative_to(path).as_posix()] = _sha(item.read_bytes())
        elif not item.is_dir():
            raise ValueError("D1_PROTECTED_STATE_ENTRY_INVALID:" + str(item))
    return result


def _protected_state_hashes() -> dict[str, dict[str, str] | None]:
    return {
        f"{folder}/{day}": _tree_hashes(FORMAL_MANAGER_STATE / folder / day)
        for folder in ("workspace_plan_runs", "workspace_plans")
        for day in PROTECTED_DATES
    }


def dry_run() -> dict[str, Any]:
    # Default invocation remains strictly read-only, but now proves it is
    # pointed at the exact prepared immutable package, disabled owner binding,
    # and staged API plist before reporting the formal-state write boundary.
    identity, _environment = _load_release_and_runtime()
    return {
        "status": "DRY_RUN_NO_HTTP_NO_WRITE",
        "execution_mode": EXECUTION_MODE,
        "target_trade_date": TARGET,
        "api_app_root": str(API_ROOT),
        "release_manifest_path": str(identity["manifest_path"]),
        "release_manifest_sha256": identity["manifest_sha256"],
        "application_inventory_sha256": identity["inventory_sha256"],
        "manager_source_inventory_sha256": identity["source_inventory_sha256"],
        "manager_state_root": str(FORMAL_MANAGER_STATE),
        "output_root": str(OUTPUT_ROOT),
        "http_calls": [],
        "durable_owner_write_paths": [
            str(FORMAL_MANAGER_STATE / "workspace_plan_runs" / TARGET / "latest.json"),
            str(FORMAL_MANAGER_STATE / "workspace_plan_runs" / TARGET / "<owner-run-id>.json"),
            str(FORMAL_MANAGER_STATE / "workspace_plans" / TARGET / "latest.json"),
            str(FORMAL_MANAGER_STATE / "workspace_plans" / TARGET / "<owner-run-id>.json"),
        ],
        "transient_lock_path": str(FORMAL_MANAGER_STATE / ".locks" / f"{TARGET}-workspace-plan-refresh.mutex"),
        "other_formal_state_written": False,
        "launchctl_called": False,
        "safety": SAFETY,
    }


def _exact_directory(path: Path, code: str) -> None:
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        raise ValueError(code)


def _resolve_api_runtime_roots(program_arguments: list[Any], environment: dict[str, str],
                               working_directory: str) -> dict[str, Any]:
    """Resolve the roots exactly as the pinned ``apps.api.v35_api.run`` does.

    The LaunchAgent wraps the Python command in ``/usr/bin/env``; its
    ``ProgramArguments`` therefore contain both environment assignments and
    the Python/module arguments.  ``extract_environment`` has already parsed
    the assignments.  This function mirrors run.py's argparse declarations
    and CLI-over-environment precedence without requiring optional settings
    such as ``V35_DISPATCH_LEDGER_ROOT`` to exist.
    """
    module_positions = [index for index, value in enumerate(program_arguments[:-1])
                        if value == "-m" and program_arguments[index + 1] == "apps.api.v35_api.run"]
    if len(module_positions) != 1:
        raise ValueError("D1_API_PLIST_RUN_MODULE_INVALID")
    argv = program_arguments[module_positions[0] + 2:]
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8873, type=int)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--preselection-source-root", type=Path)
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument("--ledger-root", type=Path)
    parser.add_argument("--stage-selection-root", type=Path)
    parser.add_argument("--stage-mode", choices=("shared", "local"),
                        default=environment.get("V35_STAGE_MODE", "shared"))
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as exc:
        raise ValueError("D1_API_PLIST_RUN_ARGUMENTS_INVALID") from exc

    # These expressions mirror run.py's ``argument or environment`` behavior.
    def configured(argument: Path | None, environment_key: str) -> Path | None:
        value = argument or (Path(environment[environment_key])
                             if environment.get(environment_key) else None)
        return value

    data_root = configured(arguments.data_root, "V35_DATA_ROOT")
    # create_app defaults NativeDataStore to Path.cwd() / .runtime / data.
    # A LaunchAgent's cwd is the plist WorkingDirectory, so resolve that
    # effective default explicitly for this in-process invocation.
    if data_root is None:
        data_root = Path(working_directory) / ".runtime" / "data"
    shared_data_root = configured(arguments.shared_data_root, "V35_SHARED_DATA_ROOT")
    ledger_root = configured(arguments.ledger_root, "V35_DISPATCH_LEDGER_ROOT")
    stage_root = arguments.stage_selection_root or (
        Path(environment["V35_STAGE_CENTER_SELECTION_ROOT"])
        if environment.get("V35_STAGE_CENTER_SELECTION_ROOT") else None
    )
    if arguments.stage_mode == "shared" and stage_root is None:
        raise ValueError("D1_API_SHARED_STAGE_ROOT_MISSING")
    if arguments.stage_mode == "local" and stage_root is not None:
        raise ValueError("D1_API_LOCAL_STAGE_ROOT_CONFLICT")

    # create_app receives the parsed preselection argument directly and may
    # fall back to V35_PRESELECTION_SOURCE_ROOT from its inherited env.
    effective_preselection_root = arguments.preselection_source_root or (
        Path(environment["V35_PRESELECTION_SOURCE_ROOT"])
        if environment.get("V35_PRESELECTION_SOURCE_ROOT") else None
    )
    roots = {
        "data_root": data_root,
        "preselection_source_root_argument": arguments.preselection_source_root,
        "preselection_source_root": effective_preselection_root,
        "shared_data_root": shared_data_root,
        "ledger_root": ledger_root,
        "stage_selection_root": stage_root,
        "stage_mode": arguments.stage_mode,
        "host": arguments.host,
        "port": arguments.port,
        "working_directory": Path(working_directory),
    }
    for key, code in (
        ("data_root", "D1_API_DATA_ROOT_NOT_EXACT"),
        ("preselection_source_root", "D1_API_PRESELECTION_ROOT_NOT_EXACT"),
        ("shared_data_root", "D1_API_SHARED_ROOT_NOT_EXACT"),
        ("ledger_root", "D1_API_LEDGER_ROOT_NOT_EXACT"),
        ("stage_selection_root", "D1_API_STAGE_ROOT_NOT_EXACT"),
    ):
        path = roots[key]
        if path is not None:
            _exact_directory(path, code)
    return roots


def _create_candidate_api_app(identity: dict[str, Any], create_app_factory=None):
    """Build the exact candidate app with the roots resolved from its plist."""
    environment = identity["environment"]
    roots = identity["api_runtime_roots"]
    _configure_runtime_environment(environment)
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    if create_app_factory is None:
        from apps.api.v35_api.app import create_app
        create_app_factory = create_app
    return create_app_factory(
        data_root=roots["data_root"],
        preselection_source_root=roots["preselection_source_root_argument"],
        shared_data_root=roots["shared_data_root"],
        ledger_root=roots["ledger_root"],
        stage_center_selection_root=roots["stage_selection_root"],
        manager_research_state_root=FORMAL_MANAGER_STATE,
    )


def _validate_disabled_binding(binding: dict[str, Any], environment: dict[str, str],
                               program_arguments: list[Any]) -> None:
    if (binding.get("enabled") is not False
            or binding.get("plan_material_refresh_only") is not False
            or binding.get("announcement_collection_enabled") is not False
            or binding.get("app_root") != str(API_ROOT)
            or binding.get("manager_state_root") != str(FORMAL_MANAGER_STATE)):
        raise ValueError("D1_CANARY_REQUIRES_EXACT_DISABLED_BINDING")
    if (environment.get("V35_APP_ROOT") != str(API_ROOT)
            or environment.get("V4_MANAGER_RESEARCH_STATE_ROOT") != str(FORMAL_MANAGER_STATE)
            or environment.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(BINDING_PATH)):
        raise ValueError("D1_STAGED_API_RUNTIME_IDENTITY_MISMATCH")
    python_pins = [Path(item) for item in program_arguments
                   if isinstance(item, str) and item.startswith("/") and item.endswith("/bin/python")]
    if python_pins != [Path(str(binding.get("python", "")))]:
        raise ValueError("D1_API_PYTHON_BINDING_MISMATCH")
    if not isinstance(binding.get("files"), dict):
        raise ValueError("D1_BINDING_SOURCE_INVENTORY_MISSING")
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
    validate_binding(binding, API_ROOT)


def _load_release_and_runtime() -> tuple[dict[str, Any], dict[str, str]]:
    _exact_directory(API_ROOT, "D1_API_RELEASE_ROOT_NOT_EXACT")
    _exact_directory(FORMAL_MANAGER_STATE, "D1_FORMAL_MANAGER_STATE_NOT_EXACT")
    if FORMAL_MANAGER_STATE == API_ROOT or API_ROOT in FORMAL_MANAGER_STATE.parents:
        raise ValueError("D1_FORMAL_STATE_OVERLAPS_RELEASE")
    if OUTPUT_ROOT.exists() or OUTPUT_ROOT.is_symlink():
        raise FileExistsError(OUTPUT_ROOT)

    manifest_path = API_RELEASE_ROOT / "release-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.resolve(strict=True) != manifest_path:
        raise ValueError("D1_API_RELEASE_MANIFEST_NOT_EXACT")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != "v4.release_candidate.v1"
            or manifest.get("activation_status") != "NOT_ACTIVATED"
            or manifest.get("candidate", {}).get("release_id") != "manager-daily-chain-20261008-r2-api"
            or manifest.get("candidate", {}).get("app_root") != str(API_ROOT)):
        raise ValueError("D1_API_RELEASE_MANIFEST_IDENTITY_MISMATCH")
    entries = manifest.get("application_inventory", {}).get("entries")
    if not isinstance(entries, list) or manifest.get("application_inventory", {}).get("entry_count") != len(entries):
        raise ValueError("D1_API_RELEASE_INVENTORY_INVALID")
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    from ops.build_release_candidate import inventory_digest, inventory_tree
    actual_entries = inventory_tree(API_ROOT)
    inventory_sha = inventory_digest(actual_entries)
    if (entries != actual_entries
            or inventory_sha != manifest.get("application_inventory", {}).get("aggregate_sha256")):
        raise ValueError("D1_API_RELEASE_INVENTORY_DRIFT")

    if PLIST_PATH.is_symlink() or not PLIST_PATH.is_file():
        raise ValueError("D1_STAGED_API_PLIST_MISSING")
    plist = plistlib.loads(PLIST_PATH.read_bytes())
    from ops.prepare_api_only_cutover import extract_environment
    environment = extract_environment(plist)
    if BINDING_PATH.is_symlink() or not BINDING_PATH.is_file():
        raise ValueError("D1_DISABLED_BINDING_MISSING")
    binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    program_arguments = plist.get("ProgramArguments")
    if not isinstance(program_arguments, list):
        raise ValueError("D1_API_PLIST_SOURCE_CONTRACT_INVALID")
    working_directory = plist.get("WorkingDirectory")
    if working_directory != str(API_ROOT):
        raise ValueError("D1_API_PLIST_WORKING_DIRECTORY_MISMATCH")
    _validate_disabled_binding(binding, environment, program_arguments)
    runtime_roots = _resolve_api_runtime_roots(program_arguments, environment, working_directory)
    return {
        "manifest_path": manifest_path,
        "manifest_sha256": _sha(manifest_path.read_bytes()),
        "manifest": manifest,
        "inventory_sha256": inventory_sha,
        "source_inventory_sha256": _canonical_sha(binding["files"]),
        "binding": binding,
        "api_runtime_roots": runtime_roots,
        "environment": environment,
    }, environment


def _check_target_preimage() -> dict[str, dict[str, str] | None]:
    target_paths = (
        FORMAL_MANAGER_STATE / "workspace_plan_runs" / TARGET,
        FORMAL_MANAGER_STATE / "workspace_plans" / TARGET,
        FORMAL_MANAGER_STATE / ".locks" / f"{TARGET}-workspace-plan-refresh.mutex",
    )
    for path in target_paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError("D1_TARGET_STATE_PREEXISTS:" + str(path))
    return _protected_state_hashes()


def _configure_runtime_environment(environment: dict[str, str]) -> None:
    for key in tuple(os.environ):
        if key.startswith(("V35_", "V4_MANAGER_")) or key in {
            "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT", "RESEARCH_ONLY",
        }:
            os.environ.pop(key, None)
    os.environ.update(environment)
    os.environ.update(PRODUCTION_ALLOWED="false", BUY_GATE_UPDATED="false",
                      ORDERS_SENT="false", RESEARCH_ONLY="true")


def _validate_execution_python(identity: dict[str, Any]) -> None:
    """Require this process to be the interpreter pinned by the staged API plist.

    The API LaunchAgent carries its Python in ProgramArguments; unlike the
    scheduler plist, it does not export V4_MANAGER_ANNOUNCEMENT_PYTHON.
    _validate_disabled_binding has already checked that ProgramArguments and
    the binding name the same interpreter.  Compare that exact path with this
    process before creating a canary output directory or touching formal state.
    """
    binding = identity.get("binding")
    expected = binding.get("python") if isinstance(binding, dict) else None
    if not isinstance(expected, str) or not Path(expected).is_absolute() or sys.executable != expected:
        raise ValueError("D1_CANARY_PYTHON_IDENTITY_MISMATCH")


def _make_http_record(*, response: Any, method: str, url: str,
                      name: str, output_root: Path) -> dict[str, Any]:
    body = bytes(response.content)
    body_path = output_root / f"{name}.response.bin"
    _write_exclusive(body_path, body)
    try:
        readback = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("D1_CANARY_RESPONSE_JSON_INVALID:" + name) from exc
    if not isinstance(readback, dict):
        raise ValueError("D1_CANARY_RESPONSE_ENVELOPE_INVALID:" + name)
    record = {
        "schema_version": "manager_daily_chain.plan_owner_http_evidence.v1",
        "http_status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "request": {"method": method, "url": url},
        "response": {"path": str(body_path), "sha256": _sha(body), "bytes": len(body)},
        "readback": readback,
    }
    evidence_path = output_root / f"{name}.http-evidence.json"
    raw = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _write_exclusive(evidence_path, raw)
    return {"path": str(evidence_path), "sha256": _sha(raw)}


def _validate_owner_pair(refresh: dict[str, Any], readback: dict[str, Any]) -> tuple[str, str, str, str]:
    target = TARGET
    product = refresh.get("plan_product")
    get_product = readback.get("plan_product")
    persisted = refresh.get("persisted_store")
    attempt = refresh.get("workspace_plan_attempt")
    safety = refresh.get("safety")
    if (refresh.get("target_trade_date") != target or readback.get("target_trade_date") != target
            or refresh.get("formal_recommendation_count") != 0
            or refresh.get("store_latest_matches_http_plan_product") is not True
            or not isinstance(product, dict) or not isinstance(get_product, dict)
            or product.get("status") != "CURRENT" or get_product.get("status") != "CURRENT"
            or product.get("consumed") is not True or get_product.get("consumed") is not True
            or product.get("run_id") != get_product.get("run_id")
            or product.get("sha256") != get_product.get("sha256")
            or product.get("original_owner") != OWNER or get_product.get("original_owner") != OWNER
            or not isinstance(persisted, dict) or persisted.get("target_trade_date") != target
            or persisted.get("run_id") != product.get("run_id")
            or persisted.get("product_sha256") != product.get("sha256")
            or persisted.get("execution_kind") != "MANUAL_REFRESH" or persisted.get("owner") != OWNER
            or not isinstance(attempt, dict) or attempt.get("execution_kind") != "MANUAL_REFRESH"
            or attempt.get("state") not in {"SUCCEEDED", "PARTIAL"}
            or refresh.get("input_identity") != readback.get("input_identity")
            or not isinstance(refresh.get("input_identity"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", refresh["input_identity"])
            or not isinstance(safety, dict) or safety != SAFETY
            or any(persisted.get(key) != value for key, value in SAFETY.items())):
        raise ValueError("D1_CANARY_OWNER_READBACK_MISMATCH")
    run_id = str(product.get("run_id") or "")
    product_sha = str(product.get("sha256") or "")
    input_identity = str(refresh.get("input_identity") or "")
    if (not re.fullmatch(r"[0-9a-f]{32}", run_id)
            or not re.fullmatch(r"[0-9a-f]{64}", product_sha)):
        raise ValueError("D1_CANARY_PRODUCT_IDENTITY_INVALID")
    state = str(attempt["state"])
    return run_id, product_sha, input_identity, state


async def _execute_owner_canary(identity: dict[str, Any], environment: dict[str, str],
                                protected_before: dict[str, dict[str, str] | None]) -> dict[str, Any]:
    _validate_execution_python(identity)
    import httpx
    roots = identity["api_runtime_roots"]
    if roots["stage_mode"] != "shared":
        raise ValueError("D1_CANARY_API_STAGE_MODE_NOT_SHARED")
    app = _create_candidate_api_app(identity)
    url_refresh = BASE_URL + f"/api/v4/manager/research/workspace/refresh?date={TARGET}"
    url_readback = BASE_URL + f"/api/v4/manager/research/workspace?date={TARGET}"
    output = OUTPUT_ROOT
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
            response = await client.post(
                f"/api/v4/manager/research/workspace/refresh?date={TARGET}",
                headers={"Origin": BASE_URL},
            )
            refresh_ref = _make_http_record(response=response, method="POST", url=url_refresh,
                                            name="refresh", output_root=output)
            if response.status_code != 200 or refresh_ref.get("sha256") is None:
                raise ValueError("D1_CANARY_REFRESH_HTTP_FAILED")
            refresh_body = response.json()
            if not isinstance(refresh_body, dict):
                raise ValueError("D1_CANARY_REFRESH_ENVELOPE_INVALID")

            response = await client.get(f"/api/v4/manager/research/workspace?date={TARGET}")
            readback_ref = _make_http_record(response=response, method="GET", url=url_readback,
                                             name="readback", output_root=output)
            if response.status_code != 200 or readback_ref.get("sha256") is None:
                raise ValueError("D1_CANARY_READBACK_HTTP_FAILED")
            readback_body = response.json()
            if not isinstance(readback_body, dict):
                raise ValueError("D1_CANARY_READBACK_ENVELOPE_INVALID")
            run_id, product_sha, input_identity, attempt_state = _validate_owner_pair(refresh_body, readback_body)

        if _protected_state_hashes() != protected_before:
            raise ValueError("D1_CANARY_PROTECTED_STATE_CHANGED")
        run_root = FORMAL_MANAGER_STATE / "workspace_plan_runs" / TARGET
        plan_root = FORMAL_MANAGER_STATE / "workspace_plans" / TARGET
        expected_run = f"{run_id}.json"
        expected_run_files = {"latest.json", expected_run}
        run_files = {item.name for item in run_root.iterdir() if item.is_file() and not item.is_symlink()} if run_root.is_dir() else set()
        plan_files = {item.name for item in plan_root.iterdir() if item.is_file() and not item.is_symlink()} if plan_root.is_dir() else set()
        if (not (run_root / "latest.json").is_file() or not (run_root / expected_run).is_file()
                or not (plan_root / "latest.json").is_file() or not (plan_root / expected_run).is_file()
                or run_files != expected_run_files or plan_files != expected_run_files
                or (FORMAL_MANAGER_STATE / ".locks" / f"{TARGET}-workspace-plan-refresh.mutex").exists()):
            raise ValueError("D1_CANARY_DURABLE_OWNER_WRITE_SET_INVALID")
        run_latest = json.loads((run_root / "latest.json").read_text(encoding="utf-8"))
        plan_latest = json.loads((plan_root / "latest.json").read_text(encoding="utf-8"))
        plan_run = json.loads((plan_root / expected_run).read_text(encoding="utf-8"))
        if (run_latest.get("run_id") != run_id or run_latest.get("state") != attempt_state
                or plan_latest.get("run_id") != run_id or plan_latest.get("sha256") != product_sha
                or plan_run != plan_latest or plan_latest.get("execution_kind") != "MANUAL_REFRESH"
                or plan_latest.get("owner") != OWNER):
            raise ValueError("D1_CANARY_LOCAL_STORE_READBACK_MISMATCH")

        manifest = identity["manifest"]
        canary = {
            "schema_version": "manager_daily_chain.plan_refresh_owner_evidence.v2",
            "status": "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING",
            "app_root": str(API_ROOT),
            "manager_state_root": str(FORMAL_MANAGER_STATE),
            "policy_status": "PROPOSAL_ONLY",
            "scope": "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK",
            "plan_material_refresh_only": True,
            "candidate_binding_app_root": str(API_ROOT),
            "owner_execution_app_root": str(API_ROOT),
            "execution_mode": EXECUTION_MODE,
            "hook_executed": False,
            "announcement_collection_enabled": False,
            "announcement_network_requests": 0,
            **SAFETY,
            "research_only": True,
            "target_trade_date": TARGET,
            "run_id": run_id,
            "product_sha256": product_sha,
            "input_identity": input_identity,
            "execution_kind": "MANUAL_REFRESH",
            "owner": OWNER,
            "owner_attempt_state": attempt_state,
            "formal_recommendation_count": 0,
            "candidate_release_id": manifest["candidate"]["release_id"],
            "candidate_release_manifest_path": str(identity["manifest_path"]),
            "candidate_release_manifest_sha256": identity["manifest_sha256"],
            "candidate_application_inventory_sha256": identity["inventory_sha256"],
            "candidate_manager_source_inventory_sha256": identity["source_inventory_sha256"],
            "owner_evidence": {"refresh": refresh_ref, "readback": readback_ref},
            "state_preimage": {
                "protected_dates_sha256": protected_before,
                "target_preexisted": False,
                "expected_durable_paths": [
                    str(run_root / "latest.json"), str(run_root / expected_run),
                    str(plan_root / "latest.json"), str(plan_root / expected_run),
                ],
            },
            "safety": SAFETY,
        }
        from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
        binding = identity["binding"]
        binding.update(
            enabled=True,
            plan_material_refresh_only=True,
            plan_activation_receipt={"path": str(output / ".plan-canary-validation.json"), "sha256": "0" * 64},
        )
        binding["plan_material_refresh"] = {
            "enabled": True, "start_local": "16:00", "end_local": "23:00",
            "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600,
            "status": "PROPOSAL_ONLY",
        }
        # Validate the complete evidence contract before publishing the final
        # receipt path. A failed validation is retained under a rejected name.
        canary_raw = (json.dumps(canary, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        pending_canary_path = output / ".plan-canary-validation.json"
        canary_path = output / "plan-canary.json"
        _write_exclusive(pending_canary_path, canary_raw)
        binding["plan_activation_receipt"]["sha256"] = _sha(canary_raw)
        validate_binding(binding, API_ROOT)
        pending_canary_path.rename(canary_path)
        receipt = {
            "schema_version": "manager_daily_chain.plan_canary_operation.v1",
            "status": "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING",
            "canary_path": str(canary_path), "canary_sha256": _sha(canary_raw),
            "api_app_root": str(API_ROOT), "manager_state_root": str(FORMAL_MANAGER_STATE),
            "target_trade_date": TARGET, "run_id": run_id, "product_sha256": product_sha,
            "input_identity": input_identity, "owner_attempt_state": attempt_state,
            "candidate_release_manifest_sha256": identity["manifest_sha256"],
            "application_inventory_sha256": identity["inventory_sha256"],
            "manager_source_inventory_sha256": identity["source_inventory_sha256"],
            "activation_status": "NOT_ACTIVATED", "launchctl_called": False,
            "safety": SAFETY,
        }
        _write_exclusive(output / "operation-receipt.json",
                         (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        return receipt
    finally:
        service = getattr(app.state, "manager_research_service", None)
        close = getattr(service, "close", None)
        if callable(close):
            close()


def execute() -> dict[str, Any]:
    if TARGET >= datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y%m%d"):
        raise ValueError("D1_CANARY_TARGET_MUST_BE_PAST")
    identity, environment = _load_release_and_runtime()
    # Refuse a Python mismatch before creating a failure-output directory. The
    # binding and ProgramArguments were validated together during load.
    _validate_execution_python(identity)
    protected = _check_target_preimage()
    output = OUTPUT_ROOT
    output.mkdir(parents=True, exist_ok=False)
    preimage = {
        "schema_version": "manager_daily_chain.plan_canary_preimage.v1",
        "target_trade_date": TARGET, "manager_state_root": str(FORMAL_MANAGER_STATE),
        "target_preexisted": False, "protected_dates_sha256": protected,
        "api_app_root": str(API_ROOT), "release_manifest_sha256": identity["manifest_sha256"],
        "application_inventory_sha256": identity["inventory_sha256"],
        "manager_source_inventory_sha256": identity["source_inventory_sha256"],
        "http_calls_expected": ["POST " + BASE_URL + f"/api/v4/manager/research/workspace/refresh?date={TARGET}",
                                "GET " + BASE_URL + f"/api/v4/manager/research/workspace?date={TARGET}"],
        "safety": SAFETY,
    }
    _write_exclusive(output / "state-preimage.json",
                     (json.dumps(preimage, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    try:
        return asyncio.run(_execute_owner_canary(identity, environment, protected))
    except Exception as exc:
        pending_canary = output / ".plan-canary-validation.json"
        if pending_canary.is_file() and not pending_canary.is_symlink():
            pending_canary.rename(output / "rejected-plan-canary.json")
        error = {"schema_version": "manager_daily_chain.plan_canary_failure.v1",
                 "status": "FAIL_CANNOT_BIND_PLAN_ACTIVATION", "error_code": str(exc),
                 "target_trade_date": TARGET, "manager_state_root": str(FORMAL_MANAGER_STATE),
                 "activation_status": "NOT_ACTIVATED", "launchctl_called": False,
                 "safety": SAFETY}
        failure_path = output / "failure-receipt.json"
        if not failure_path.exists():
            _write_exclusive(failure_path,
                             (json.dumps(error, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="perform the one exact historical owner POST/GET against the formal manager state")
    args = parser.parse_args(argv)
    result = execute() if args.execute else dry_run()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
