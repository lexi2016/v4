"""Shared, fail-closed helpers for the US daily-chain staging package.

This module reads the current API/scheduler plists when invoked. It does not
write live configuration, launch services, or access manager state except when
the canary runner is invoked with its explicit ``--execute`` flag.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import plistlib
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TASK_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_ROOT = TASK_ROOT / "integrated_release" / "issue35-manager-autocontinue-20261012-r4b"
LIVE_API_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
LIVE_SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
DEFAULT_MANAGER_STATE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research")
TARGET_DEFAULT = "20261012"
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
BINDING_SCHEMA = "v4.manager_research.announcement_binding.v1"
PLAN_OWNER_SCHEMA = "v4.manager_research.plan_owner_binding.v1"
CANARY_SCHEMA = "manager_daily_chain.plan_refresh_owner_evidence.v2"
CANARY_STATUS = "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING"
CANARY_NEXT_SCOPE = "NEXT_HK_SESSION_MANUAL_REFRESH_WITH_HTTP_READBACK"
EXECUTION_MODE = "HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK"
DAILY_AUTOMATION = {
    "enabled": True,
    "same_day_catchup_slots_local": ["10:00", "12:30", "15:45", "18:30", "22:30"],
    "us_mapping_budget_seconds": 5,
    "max_attempts_per_target_date": 5,
    "status": "PROPOSAL_ONLY",
}
PLAN_MATERIAL_REFRESH = {
    "enabled": True,
    "start_local": "16:00",
    "end_local": "23:00",
    "max_attempts_per_target_date": 3,
    "retry_backoff_seconds": 600,
    "status": "PROPOSAL_ONLY",
}
SAFETY = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
PROTECTED_DATES = ("20261007", "20261008", "20261009")
API_BASE_URL = "http://127.0.0.1:8873"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_sha(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8"))


def exact_file(path: Path, code: str) -> bytes:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(code)
    return path.read_bytes()


def exact_directory(path: Path, code: str) -> None:
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        raise ValueError(code)


def read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(exact_file(path, code))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def app_module(app_root: Path, module_name: str):
    exact_directory(app_root, "FINAL_APP_ROOT_NOT_EXACT")
    root_text = str(app_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return importlib.import_module(module_name)


def load_release(app_root: Path) -> dict[str, Any]:
    """Verify a prepared final release from its own manifest and inventory."""
    exact_directory(app_root, "FINAL_APP_ROOT_NOT_EXACT")
    if (TASK_ROOT / "integrated_release") not in app_root.parents:
        raise ValueError("FINAL_APP_ROOT_OUTSIDE_INTEGRATED_RELEASE")
    release_root = app_root.parent
    exact_directory(release_root, "FINAL_RELEASE_ROOT_NOT_EXACT")
    manifest_path = release_root / "release-manifest.json"
    manifest_raw = exact_file(manifest_path, "FINAL_RELEASE_MANIFEST_MISSING")
    manifest = json.loads(manifest_raw)
    if (not isinstance(manifest, dict)
            or manifest.get("schema_version") != "v4.release_candidate.v1"
            or manifest.get("activation_status") != "NOT_ACTIVATED"
            or manifest.get("candidate", {}).get("app_root") != str(app_root)
            or manifest.get("candidate", {}).get("root") != str(release_root)):
        raise ValueError("FINAL_RELEASE_MANIFEST_IDENTITY_MISMATCH")
    build = app_module(app_root, "ops.build_release_candidate")
    actual_entries = build.inventory_tree(app_root)
    inventory = manifest.get("application_inventory")
    if (not isinstance(inventory, dict)
            or inventory.get("entry_count") != len(actual_entries)
            or inventory.get("entries") != actual_entries
            or inventory.get("aggregate_sha256") != build.inventory_digest(actual_entries)):
        raise ValueError("FINAL_RELEASE_INVENTORY_MISMATCH")
    contract = app_module(app_root, "infrastructure.scheduling.manager_announcement_supervisor")
    files = contract.binding_inventory(app_root)
    if not isinstance(files, dict) or not files:
        raise ValueError("FINAL_BINDING_INVENTORY_EMPTY")
    return {
        "app_root": app_root,
        "release_root": release_root,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "manifest_sha256": sha256_bytes(manifest_raw),
        "application_inventory_sha256": inventory["aggregate_sha256"],
        "binding_files": files,
        "binding_inventory_sha256": canonical_sha(files),
        "owner_inventory_sha256": contract.owner_inventory_sha256(files),
        "contract": contract,
    }


def env_from_plist(plist: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    args = plist.get("ProgramArguments")
    if not isinstance(args, list):
        raise ValueError("PLIST_PROGRAM_ARGUMENTS_INVALID")
    for item in args:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                if key in result and result[key] != value:
                    raise ValueError("PLIST_DUPLICATE_ENV:" + key)
                result[key] = value
    explicit = plist.get("EnvironmentVariables")
    if explicit is not None:
        if not isinstance(explicit, dict):
            raise ValueError("PLIST_ENVIRONMENT_INVALID")
        for key, value in explicit.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("PLIST_ENVIRONMENT_INVALID")
            if key in result and result[key] != value:
                raise ValueError("PLIST_DUPLICATE_ENV:" + key)
            result[key] = value
    return result


def environment_occurrences(plist: dict[str, Any], key: str) -> int:
    args = plist.get("ProgramArguments") or []
    in_args = sum(1 for item in args if isinstance(item, str) and item.startswith(key + "="))
    env = plist.get("EnvironmentVariables") or {}
    return in_args + (1 if isinstance(env, dict) and key in env else 0)


def replace_environment(plist: dict[str, Any], key: str, value: str,
                        *, require_existing: bool = True) -> None:
    count = environment_occurrences(plist, key)
    if count > 1 or (require_existing and count != 1):
        raise ValueError("PLIST_ENV_KEY_CARDINALITY:" + key)
    args = plist.get("ProgramArguments") or []
    changed = False
    for index, item in enumerate(args):
        if isinstance(item, str) and item.startswith(key + "="):
            args[index] = key + "=" + value
            changed = True
    env = plist.get("EnvironmentVariables")
    if isinstance(env, dict) and key in env:
        env[key] = value
        changed = True
    if count == 0 and not require_existing:
        if not isinstance(env, dict):
            env = {}
            plist["EnvironmentVariables"] = env
        env[key] = value
        changed = True
    if not changed:
        raise ValueError("PLIST_ENV_KEY_NOT_UPDATED:" + key)


def current_plists(api_plist: Path = LIVE_API_PLIST,
                   scheduler_plist: Path = LIVE_SCHEDULER_PLIST) -> dict[str, Any]:
    api_raw = exact_file(api_plist, "LIVE_API_PLIST_MISSING")
    scheduler_raw = exact_file(scheduler_plist, "LIVE_SCHEDULER_PLIST_MISSING")
    try:
        api = plistlib.loads(api_raw)
        scheduler = plistlib.loads(scheduler_raw)
    except Exception as exc:
        raise ValueError("LIVE_LAUNCHAGENT_PLIST_INVALID") from exc
    if not isinstance(api, dict) or not isinstance(scheduler, dict):
        raise ValueError("LIVE_LAUNCHAGENT_PLIST_INVALID")
    return {
        "api": api,
        "scheduler": scheduler,
        "api_raw": api_raw,
        "scheduler_raw": scheduler_raw,
        "api_sha256": sha256_bytes(api_raw),
        "scheduler_sha256": sha256_bytes(scheduler_raw),
        "api_env": env_from_plist(api),
        "scheduler_env": env_from_plist(scheduler),
    }


def load_current_binding(path_text: str, label: str) -> dict[str, Any]:
    path = Path(path_text)
    value = read_json(path, label + "_BINDING_INVALID")
    if value.get("schema_version") != BINDING_SCHEMA:
        raise ValueError(label + "_BINDING_SCHEMA_MISMATCH")
    return value


def current_identity(app_root: Path, release: dict[str, Any] | None = None,
                     *, live: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read active plist inputs as a base for a separately staged final root."""
    release = release or load_release(app_root)
    live = live or current_plists()
    api = live["api"]
    scheduler = live["scheduler"]
    api_env = live["api_env"]
    scheduler_env = live["scheduler_env"]
    active_app_text = api_env.get("V35_APP_ROOT")
    if not isinstance(active_app_text, str):
        raise ValueError("ACTIVE_API_APP_ROOT_MISSING")
    active_app = Path(active_app_text)
    exact_directory(active_app, "ACTIVE_API_APP_ROOT_INVALID")
    if api.get("WorkingDirectory") != str(active_app):
        raise ValueError("ACTIVE_API_WORKING_DIRECTORY_MISMATCH")
    active_manifest_text = api_env.get("V35_RELEASE_MANIFEST_PATH")
    active_manifest_sha = api_env.get("V35_RELEASE_MANIFEST_SHA256")
    active_release_id = api_env.get("V35_RELEASE_ID")
    if not (isinstance(active_manifest_text, str)
            and isinstance(active_manifest_sha, str)
            and re.fullmatch(r"[0-9a-f]{64}", active_manifest_sha)
            and isinstance(active_release_id, str)):
        raise ValueError("ACTIVE_API_RELEASE_PINS_MISSING")
    active_manifest_path = Path(active_manifest_text)
    active_manifest_raw = exact_file(active_manifest_path, "ACTIVE_API_RELEASE_MANIFEST_MISSING")
    if sha256_bytes(active_manifest_raw) != active_manifest_sha:
        raise ValueError("ACTIVE_API_RELEASE_MANIFEST_SHA_MISMATCH")
    try:
        active_manifest = json.loads(active_manifest_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("ACTIVE_API_RELEASE_MANIFEST_INVALID") from exc
    if (not isinstance(active_manifest, dict)
            or active_manifest.get("candidate", {}).get("app_root") != str(active_app)
            or active_manifest.get("candidate", {}).get("release_id") != active_release_id):
        raise ValueError("ACTIVE_API_RELEASE_IDENTITY_MISMATCH")
    state_text = api_env.get("V4_MANAGER_RESEARCH_STATE_ROOT")
    if not state_text:
        raise ValueError("API_MANAGER_STATE_ROOT_MISSING")
    state_root = Path(state_text)
    exact_directory(state_root, "FORMAL_MANAGER_STATE_ROOT_INVALID")
    api_binding_path = api_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH")
    scheduler_binding_path = scheduler_env.get("V4_MANAGER_ANNOUNCEMENT_BINDING")
    if not api_binding_path or not scheduler_binding_path:
        raise ValueError("LIVE_MANAGER_BINDING_PATH_MISSING")
    api_binding_raw = exact_file(Path(api_binding_path), "API_BINDING_FILE_MISSING")
    scheduler_binding_raw = exact_file(Path(scheduler_binding_path), "SCHEDULER_BINDING_FILE_MISSING")
    api_binding = load_current_binding(api_binding_path, "API")
    scheduler_binding = load_current_binding(scheduler_binding_path, "SCHEDULER")
    if (api_binding.get("manager_state_root") != str(state_root)
            or scheduler_binding.get("manager_state_root") != str(state_root)):
        raise ValueError("LIVE_BINDING_MANAGER_STATE_ROOT_MISMATCH")
    stable_keys = ("policy", "policy_status", "priority_codes", "preopen_plan", "morning_plan",
                   "security_master_root", "python", "python_resolved", "python_sha256")
    stable: dict[str, Any] = {}
    for key in stable_keys:
        left_present = key in api_binding
        right_present = key in scheduler_binding
        if left_present and right_present and api_binding[key] != scheduler_binding[key]:
            raise ValueError("LIVE_BINDING_STABLE_FIELD_MISMATCH:" + key)
        if left_present:
            stable[key] = api_binding[key]
        elif right_present:
            stable[key] = scheduler_binding[key]
    if stable.get("policy_status") != "PROPOSAL_ONLY":
        raise ValueError("LIVE_BINDING_POLICY_STATUS_INVALID")
    if stable.get("policy") not in {"BALANCED_V1", "LOW_LOAD_V1"}:
        raise ValueError("LIVE_BINDING_POLICY_INVALID")
    if not isinstance(stable.get("priority_codes"), list):
        raise ValueError("LIVE_BINDING_PRIORITIES_INVALID")
    master_text = stable.get("security_master_root")
    if not isinstance(master_text, str):
        raise ValueError("LIVE_SECURITY_MASTER_ROOT_MISSING")
    master_root = Path(master_text)
    exact_directory(master_root, "LIVE_SECURITY_MASTER_ROOT_INVALID")
    if any(Path(value) != master_root for value in (
            api_binding.get("security_master_root"), scheduler_binding.get("security_master_root"))):
        raise ValueError("LIVE_SECURITY_MASTER_ROOT_MISMATCH")
    scheduler_cwd = scheduler.get("WorkingDirectory")
    if not isinstance(scheduler_cwd, str):
        raise ValueError("LIVE_SCHEDULER_WORKING_DIRECTORY_MISSING")
    scheduler_root = Path(scheduler_cwd)
    exact_directory(scheduler_root, "LIVE_SCHEDULER_ROOT_INVALID")
    hook_root_text = scheduler_env.get("V4_MANAGER_ANNOUNCEMENT_APP_ROOT")
    if not hook_root_text:
        raise ValueError("LIVE_SCHEDULER_HOOK_APP_ROOT_MISSING")
    hook_root = Path(hook_root_text)
    if any((state_root == p or state_root in p.parents or p in state_root.parents)
           for p in (app_root, master_root)):
        raise ValueError("MANAGER_STATE_ROOT_OVERLAPS_BOUND_ROOT")
    python = stable.get("python")
    if not isinstance(python, str) or not Path(python).is_absolute() or not Path(python).is_file():
        raise ValueError("BOUND_PYTHON_INVALID")
    if stable.get("python_resolved") != str(Path(python).resolve()):
        raise ValueError("BOUND_PYTHON_RESOLVED_MISMATCH")
    if stable.get("python_sha256") != sha256_bytes(Path(python).read_bytes()):
        raise ValueError("BOUND_PYTHON_SHA_MISMATCH")
    if scheduler_env.get("V4_MANAGER_ANNOUNCEMENT_PYTHON") != python:
        raise ValueError("API_SCHEDULER_PYTHON_MISMATCH")
    if scheduler_env.get("V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256") != stable["python_sha256"]:
        raise ValueError("SCHEDULER_PYTHON_SHA_MISMATCH")
    _validate_api_invocation(api, api_env, python)
    return {
        "release": release,
        "live": live,
        "active_api_app_root": active_app,
        "active_api_manifest_path": active_manifest_path,
        "active_api_manifest_sha256": active_manifest_sha,
        "active_api_release_id": active_release_id,
        "active_api_binding_path": Path(api_binding_path),
        "active_api_binding_sha256": sha256_bytes(api_binding_raw),
        "active_scheduler_binding_path": Path(scheduler_binding_path),
        "active_scheduler_binding_sha256": sha256_bytes(scheduler_binding_raw),
        "state_root": state_root,
        "master_root": master_root,
        "scheduler_root": scheduler_root,
        "scheduler_hook_root": hook_root,
        "stable_binding_fields": stable,
        "api_binding": api_binding,
        "scheduler_binding": scheduler_binding,
        "python": python,
    }


def _validate_api_invocation(api: dict[str, Any], environment: dict[str, str],
                             expected_python: str) -> None:
    args = api.get("ProgramArguments")
    if not isinstance(args, list) or not args or args[0] != "/usr/bin/env":
        raise ValueError("API_PLIST_ENV_WRAPPER_INVALID")
    modules = [i for i, value in enumerate(args[:-1])
               if value == "-m" and args[i + 1] == "apps.api.v35_api.run"]
    if len(modules) != 1:
        raise ValueError("API_PLIST_RUN_MODULE_INVALID")
    python_entries = [item for item in args if isinstance(item, str)
                      and item.startswith("/") and item.endswith("/bin/python")]
    if len(python_entries) != 1:
        raise ValueError("API_PLIST_PYTHON_INVALID")
    if python_entries != [expected_python] or not Path(expected_python).is_absolute():
        raise ValueError("API_PLIST_PYTHON_BINDING_MISMATCH")


def resolve_api_runtime_roots(api: dict[str, Any], environment: dict[str, str]) -> dict[str, Any]:
    """Mirror the live run.py argument/environment precedence for in-process ASGI."""
    args = api["ProgramArguments"]
    module_index = next(i for i, value in enumerate(args[:-1])
                        if value == "-m" and args[i + 1] == "apps.api.v35_api.run")
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
        parsed = parser.parse_args(args[module_index + 2:])
    except SystemExit as exc:
        raise ValueError("API_PLIST_RUN_ARGUMENTS_INVALID") from exc

    def configured(argument: Path | None, key: str) -> Path | None:
        return argument or (Path(environment[key]) if environment.get(key) else None)

    working = Path(api["WorkingDirectory"])
    data_root = configured(parsed.data_root, "V35_DATA_ROOT") or (working / ".runtime" / "data")
    shared = configured(parsed.shared_data_root, "V35_SHARED_DATA_ROOT")
    ledger = configured(parsed.ledger_root, "V35_DISPATCH_LEDGER_ROOT")
    stage = parsed.stage_selection_root or (Path(environment["V35_STAGE_CENTER_SELECTION_ROOT"])
                                            if environment.get("V35_STAGE_CENTER_SELECTION_ROOT") else None)
    preselection = parsed.preselection_source_root or (Path(environment["V35_PRESELECTION_SOURCE_ROOT"])
                                                       if environment.get("V35_PRESELECTION_SOURCE_ROOT") else None)
    if parsed.stage_mode == "shared" and stage is None:
        raise ValueError("API_SHARED_STAGE_ROOT_MISSING")
    if parsed.stage_mode == "local" and stage is not None:
        raise ValueError("API_LOCAL_STAGE_ROOT_CONFLICT")
    for key, path in (("data", data_root), ("shared", shared), ("ledger", ledger),
                      ("stage", stage), ("preselection", preselection)):
        if path is not None:
            exact_directory(path, "API_RUNTIME_ROOT_INVALID:" + key)
    return {
        "data_root": data_root,
        "preselection_source_root_argument": parsed.preselection_source_root,
        "shared_data_root": shared,
        "ledger_root": ledger,
        "stage_selection_root": stage,
        "stage_mode": parsed.stage_mode,
        "host": parsed.host,
        "port": parsed.port,
        "working_directory": working,
    }


def next_hk_session(app_root: Path, now: datetime | None = None) -> str:
    """Resolve the next HK securities session using the bound release calendar."""
    now = now or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("CURRENT_CLOCK_MUST_BE_TIMEZONE_AWARE")
    calendar_module = app_module(app_root, "contracts.trading_calendar")
    calendar = calendar_module.load_market_calendar(app_root / "contracts/market_calendar_2026.json")
    cursor = now.astimezone(ZoneInfo("Asia/Hong_Kong")).date() + timedelta(days=1)
    while cursor.year == calendar.year:
        date_text = cursor.strftime("%Y%m%d")
        state = calendar_module.resolve_market_states(calendar, date_text).get("hk_securities")
        if state in {calendar_module.TradingDayState.FULL_TRADING_DAY,
                     calendar_module.TradingDayState.HALF_TRADING_DAY_AM}:
            return date_text
        cursor += timedelta(days=1)
    raise ValueError("NEXT_HK_SESSION_OUTSIDE_BOUND_CALENDAR")


def build_binding(identity: dict[str, Any], *, canary_path: Path | None = None,
                  canary_sha256: str | None = None, enabled: bool = True) -> dict[str, Any]:
    release = identity["release"]
    core = identity["stable_binding_fields"]
    binding: dict[str, Any] = {
        "schema_version": BINDING_SCHEMA,
        "enabled": bool(enabled),
        "policy_status": core["policy_status"],
        "policy": core["policy"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "research_only": True,
        "app_root": str(release["app_root"]),
        "manager_state_root": str(identity["state_root"]),
        "security_master_root": str(identity["master_root"]),
        "python": core["python"],
        "python_resolved": core["python_resolved"],
        "python_sha256": core["python_sha256"],
        "priority_codes": list(core["priority_codes"]),
        "files": release["binding_files"],
        "plan_material_refresh_only": bool(enabled),
        "announcement_collection_enabled": False,
        "preopen_plan": core.get("preopen_plan", {"enabled": True, "lead_seconds": 180,
                                                     "status": "PROPOSAL_ONLY"}),
    }
    if "morning_plan" in core:
        binding["morning_plan"] = core["morning_plan"]
    if not enabled:
        binding["plan_material_refresh_only"] = False
        return binding
    if canary_path is None or not isinstance(canary_sha256, str):
        raise ValueError("FRESH_CANARY_REQUIRED_FOR_ENABLED_BINDING")
    owner_files = release["binding_files"]
    binding.update({
        "plan_material_refresh": dict(PLAN_MATERIAL_REFRESH),
        "plan_activation_receipt": {"path": str(canary_path), "sha256": canary_sha256},
        "daily_automation": dict(DAILY_AUTOMATION),
        "plan_owner": {
            "schema_version": PLAN_OWNER_SCHEMA,
            "owner": OWNER,
            "app_root": str(release["app_root"]),
            "files": owner_files,
        },
    })
    return binding


def protected_state_hashes(state_root: Path) -> dict[str, dict[str, str] | None]:
    result: dict[str, dict[str, str] | None] = {}
    for folder in ("workspace_plan_runs", "workspace_plans"):
        for target in PROTECTED_DATES:
            path = state_root / folder / target
            if not path.exists():
                result[f"{folder}/{target}"] = None
                continue
            exact_directory(path, "PROTECTED_STATE_ROOT_INVALID")
            files: dict[str, str] = {}
            for item in sorted(path.rglob("*")):
                if item.is_symlink():
                    raise ValueError("PROTECTED_STATE_SYMLINK")
                if item.is_file():
                    files[item.relative_to(path).as_posix()] = sha256_bytes(item.read_bytes())
                elif not item.is_dir():
                    raise ValueError("PROTECTED_STATE_ENTRY_INVALID")
            result[f"{folder}/{target}"] = files
    return result


def require_next_session(target: str, app_root: Path, now: datetime | None = None) -> None:
    if not re.fullmatch(r"20\d{6}", target):
        raise ValueError("TARGET_TRADE_DATE_INVALID")
    current = now or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    if target != next_hk_session(app_root, current):
        raise ValueError("TARGET_IS_NOT_NEXT_HK_SESSION_AT_CURRENT_CLOCK")

