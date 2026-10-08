#!/usr/bin/env python3
"""Stage (never activate) the exact C1+D1 plan-only config after a fresh canary.

Default invocation is read-only. ``--stage-enabled`` writes an enabled binding
and matching API/scheduler plist copies only below this task's staged_config.
It does not change LaunchAgents, manager state, a running process, or launchd.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import plistlib
import re
import sys
from pathlib import Path
from typing import Any

TASK_ROOT = Path(__file__).resolve().parent
APP_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
API_RELEASE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r2-api")
SCHEDULER_RELEASE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/manager-daily-chain-20261008-r2-scheduler")
API_ROOT = API_RELEASE_ROOT / "app"
SCHEDULER_ROOT = SCHEDULER_RELEASE_ROOT / "app"
FORMAL_MANAGER_STATE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research")
API_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
ACTIVE_API_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-research-calendar-all-r1-20261007-api/app")
ACTIVE_SCHEDULER_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/hk-research-calendar-all-r1-20261007-scheduler/app")
RUNTIME_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime")
EXACT_PYTHON = RUNTIME_ROOT / "venvs/v3.5-mac/bin/python"
CONFIG_ROOT = TASK_ROOT / "staged_config"
PREIMAGE_ROOT = TASK_ROOT / "preimage/runtime_plists"
RELEASE_STAGE_RECEIPT = CONFIG_ROOT / "manager_daily_chain_c1_release_receipt.final-d1-r2.json"
DISABLED_BINDING = CONFIG_ROOT / "manager-plan-binding-c1.disabled.final-d1-r2.json"
DISABLED_API_PLIST = CONFIG_ROOT / "com.lexi.v35.api-only.c1-final-d1-r2.plist"
DISABLED_SCHEDULER_PLIST = CONFIG_ROOT / "com.lexi.v35.scheduler.c1-final-d1-r2.plist"
CANARY_ROOT = TASK_ROOT / "plan_canary_runs/20260925/execution-01"
CANARY_PATH = CANARY_ROOT / "plan-canary.json"
CANARY_OPERATION_RECEIPT = CANARY_ROOT / "operation-receipt.json"
PROTECTED_DATES = ("20261007", "20261008")

EXPECTED_API_MANIFEST_SHA256 = "ab8cc247bced7cfceae7fdad35ba20535a4af1778d4d2fb36705a78485ee160d"
EXPECTED_API_INVENTORY_SHA256 = "69cf711f81f390954f3806f7e50d63f248988867738371650342e58657dca78c"
EXPECTED_SCHEDULER_MANIFEST_SHA256 = "503a28a5bb2befe49997e30998bab1765a5302dfc59adda71deb214355780247"
EXPECTED_SCHEDULER_INVENTORY_SHA256 = "58e51a7472e012f0c749cc909bdd85c634f5c31ae48f97fe8094af1e404eaf01"
EXPECTED_STAGE_RECEIPT_SHA256 = "6418d8143b671f54c8fd527c7fef6195cf73481e4ef7b67acda35ab05ee6565f"
EXPECTED_DISABLED_BINDING_SHA256 = "f3b7cbfa1709b2b27816d294e599cb1ae82ff918ba41ec148644f1a1751f5fd6"
EXPECTED_DISABLED_API_PLIST_SHA256 = "b2eb9828645538863571ea9cdb0d830ac76afcafba551faf127a16752db2eee3"
EXPECTED_DISABLED_SCHEDULER_PLIST_SHA256 = "bd2df5b6138bb28f31c208b2643c519bf035e2e86057bdcb680f4d2d614e7960"
EXPECTED_ACTIVE_API_PLIST_SHA256 = "36b80da4e7cd2d002c0338c7b3788ed01572d89bdaf928f668305af7abdb3ab2"
EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256 = "c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2"
EXPECTED_SAFE_CUTOVER_BACKEND_SHA256 = "4747df35c3d7922bd1122256565e1136d5740d942ebb03d925ef870d056df22e"

SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}
PLAN_REFRESH = {
    "enabled": True, "start_local": "16:00", "end_local": "23:00",
    "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600,
    "status": "PROPOSAL_ONLY",
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8"))


def _exact_file(path: Path, code: str) -> bytes:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(code)
    return path.read_bytes()


def _exact_directory(path: Path, code: str) -> None:
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        raise ValueError(code)


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(_exact_file(path, code))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(code) from exc
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _tree_hashes(root: Path) -> dict[str, str] | None:
    if not root.exists():
        return None
    _exact_directory(root, "POSTCANARY_PROTECTED_STATE_PATH_INVALID")
    result: dict[str, str] = {}
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError("POSTCANARY_PROTECTED_STATE_SYMLINK")
        if item.is_file():
            result[item.relative_to(root).as_posix()] = _sha(item.read_bytes())
        elif not item.is_dir():
            raise ValueError("POSTCANARY_PROTECTED_STATE_ENTRY_INVALID")
    return result


def _protected_hashes(state_root: Path) -> dict[str, dict[str, str] | None]:
    return {
        f"{folder}/{day}": _tree_hashes(state_root / folder / day)
        for folder in ("workspace_plan_runs", "workspace_plans")
        for day in PROTECTED_DATES
    }


def _assignments(plist: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in plist.get("ProgramArguments", []):
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                result[key] = value
    env = plist.get("EnvironmentVariables")
    if isinstance(env, dict):
        result.update({str(k): str(v) for k, v in env.items()})
    return result


def _replace_env_args(arguments: list[Any], updates: dict[str, str]) -> list[Any]:
    if not arguments or arguments[0] != "/usr/bin/env":
        raise ValueError("POSTCANARY_API_PLIST_ENV_WRAPPER_INVALID")
    out: list[Any] = []
    seen: set[str] = set()
    for item in arguments:
        if isinstance(item, str) and "=" in item:
            key, _ = item.split("=", 1)
            if key in updates:
                if key in seen:
                    raise ValueError("POSTCANARY_API_PLIST_DUPLICATE_ENV:" + key)
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(item)
    missing = set(updates) - seen
    if missing:
        insert_at = next((i for i, value in enumerate(out[1:], 1)
                          if not (isinstance(value, str) and "=" in value)), len(out))
        out[insert_at:insert_at] = [f"{key}={updates[key]}" for key in sorted(missing)]
    return out


def _binding_inventory(api_root: Path) -> dict[str, str]:
    if str(API_ROOT / "upstreams") not in sys.path:
        sys.path.insert(0, str(API_ROOT / "upstreams"))
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    module_name = "infrastructure.scheduling.manager_announcement_supervisor"
    module = sys.modules.get(module_name)
    expected_module = API_ROOT / "infrastructure/scheduling/manager_announcement_supervisor.py"
    if module is None:
        module = importlib.import_module(module_name)
    if Path(module.__file__).resolve(strict=True) != expected_module.resolve(strict=True):
        raise ValueError("POSTCANARY_VALIDATOR_NOT_FROM_PINNED_R2_API_ROOT")
    return module.binding_inventory(api_root)


def _validate_binding(binding: dict[str, Any]) -> None:
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    if str(API_ROOT / "upstreams") not in sys.path:
        sys.path.insert(0, str(API_ROOT / "upstreams"))
    module_name = "infrastructure.scheduling.manager_announcement_supervisor"
    module = sys.modules.get(module_name)
    expected_module = API_ROOT / "infrastructure/scheduling/manager_announcement_supervisor.py"
    if module is None:
        module = importlib.import_module(module_name)
    if Path(module.__file__).resolve(strict=True) != expected_module.resolve(strict=True):
        raise ValueError("POSTCANARY_VALIDATOR_NOT_FROM_PINNED_R2_API_ROOT")
    module.validate_binding(binding, API_ROOT)


def _legacy_api_rewrite(api_plist: dict[str, Any]) -> dict[str, Any]:
    """Use the reviewed API-only backend to render the API half of the pair.

    The high-level render_cutover() API is intentionally not called: it
    requires a distinct candidate manager-state root. This plan-only release
    keeps the existing formal owner root and uses only its lower-level,
    non-activating plist renderer.
    """
    backend_path = API_ROOT / "ops/prepare_api_only_cutover.py"
    backend_raw = _exact_file(backend_path, "POSTCANARY_SAFE_CUTOVER_BACKEND_MISSING")
    if _sha(backend_raw) != EXPECTED_SAFE_CUTOVER_BACKEND_SHA256:
        raise ValueError("POSTCANARY_SAFE_CUTOVER_BACKEND_SHA_MISMATCH")
    spec = importlib.util.spec_from_file_location("d1_r2_prepare_api_only_cutover", backend_path)
    if spec is None or spec.loader is None:
        raise ValueError("POSTCANARY_SAFE_CUTOVER_BACKEND_IMPORT_INVALID")
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    return backend.rewrite_api_only_plist(
        api_plist,
        candidate_app_root=API_ROOT,
        release_id="manager-daily-chain-20261008-r2-api",
        manifest_path=API_RELEASE_ROOT / "release-manifest.json",
        manifest_sha256=EXPECTED_API_MANIFEST_SHA256,
        candidate_manager_state_root=FORMAL_MANAGER_STATE,
    )


def _validate_stager_python(binding: dict[str, Any]) -> str:
    """Bind staging execution to the API interpreter already pinned in its plist."""
    expected = binding.get("python")
    if (not isinstance(expected, str) or expected != str(EXACT_PYTHON)
            or sys.executable != expected):
        raise ValueError("POSTCANARY_API_BINDING_PYTHON_IDENTITY_MISMATCH")
    return expected


def _check_release_and_disabled_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    _exact_directory(API_RELEASE_ROOT, "POSTCANARY_API_RELEASE_ROOT_INVALID")
    _exact_directory(SCHEDULER_RELEASE_ROOT, "POSTCANARY_SCHEDULER_RELEASE_ROOT_INVALID")
    _exact_directory(API_ROOT, "POSTCANARY_API_APP_ROOT_INVALID")
    _exact_directory(SCHEDULER_ROOT, "POSTCANARY_SCHEDULER_APP_ROOT_INVALID")
    api_manifest_path = API_RELEASE_ROOT / "release-manifest.json"
    scheduler_manifest_path = SCHEDULER_RELEASE_ROOT / "release-manifest.json"
    api_raw = _exact_file(api_manifest_path, "POSTCANARY_API_MANIFEST_MISSING")
    scheduler_raw = _exact_file(scheduler_manifest_path, "POSTCANARY_SCHEDULER_MANIFEST_MISSING")
    if _sha(api_raw) != EXPECTED_API_MANIFEST_SHA256:
        raise ValueError("POSTCANARY_API_MANIFEST_SHA_MISMATCH")
    if _sha(scheduler_raw) != EXPECTED_SCHEDULER_MANIFEST_SHA256:
        raise ValueError("POSTCANARY_SCHEDULER_MANIFEST_SHA_MISMATCH")
    api_manifest, scheduler_manifest = json.loads(api_raw), json.loads(scheduler_raw)
    if (api_manifest.get("candidate", {}).get("release_id") != "manager-daily-chain-20261008-r2-api"
            or api_manifest.get("candidate", {}).get("app_root") != str(API_ROOT)
            or api_manifest.get("application_inventory", {}).get("aggregate_sha256") != EXPECTED_API_INVENTORY_SHA256
            or scheduler_manifest.get("candidate", {}).get("release_id") != "manager-daily-chain-20261008-r2-scheduler"
            or scheduler_manifest.get("candidate", {}).get("app_root") != str(SCHEDULER_ROOT)
            or scheduler_manifest.get("application_inventory", {}).get("aggregate_sha256") != EXPECTED_SCHEDULER_INVENTORY_SHA256):
        raise ValueError("POSTCANARY_RELEASE_IDENTITY_MISMATCH")

    stage_raw = _exact_file(RELEASE_STAGE_RECEIPT, "POSTCANARY_RELEASE_STAGE_RECEIPT_MISSING")
    if _sha(stage_raw) != EXPECTED_STAGE_RECEIPT_SHA256:
        raise ValueError("POSTCANARY_RELEASE_STAGE_RECEIPT_SHA_MISMATCH")
    stage = json.loads(stage_raw)
    if (stage.get("status") != "CANDIDATE_STAGED_NOT_ACTIVATED"
            or stage.get("activation_status") != "NOT_ACTIVATED"
            or stage.get("launchctl_called") is not False):
        raise ValueError("POSTCANARY_RELEASE_STAGE_RECEIPT_INVALID")

    binding_raw = _exact_file(DISABLED_BINDING, "POSTCANARY_DISABLED_BINDING_MISSING")
    api_plist_raw = _exact_file(DISABLED_API_PLIST, "POSTCANARY_DISABLED_API_PLIST_MISSING")
    scheduler_plist_raw = _exact_file(DISABLED_SCHEDULER_PLIST, "POSTCANARY_DISABLED_SCHEDULER_PLIST_MISSING")
    if (_sha(binding_raw) != EXPECTED_DISABLED_BINDING_SHA256
            or _sha(api_plist_raw) != EXPECTED_DISABLED_API_PLIST_SHA256
            or _sha(scheduler_plist_raw) != EXPECTED_DISABLED_SCHEDULER_PLIST_SHA256):
        raise ValueError("POSTCANARY_DISABLED_STAGE_INPUT_SHA_MISMATCH")
    binding = json.loads(binding_raw)
    _validate_stager_python(binding)
    api_plist = plistlib.loads(api_plist_raw)
    scheduler_plist = plistlib.loads(scheduler_plist_raw)
    if (binding.get("enabled") is not False
            or binding.get("plan_material_refresh_only") is not False
            or binding.get("announcement_collection_enabled") is not False
            or binding.get("app_root") != str(API_ROOT)
            or binding.get("manager_state_root") != str(FORMAL_MANAGER_STATE)
            or binding.get("research_only") is not True
            or binding.get("production_allowed") is not False
            or binding.get("buy_gate_updated") is not False
            or binding.get("orders_sent") is not False
            or _binding_inventory(API_ROOT) != binding.get("files")):
        raise ValueError("POSTCANARY_DISABLED_BINDING_CONTRACT_INVALID")
    if (stage.get("shared_binding", {}).get("path") != str(DISABLED_BINDING)
            or stage.get("shared_binding", {}).get("sha256") != EXPECTED_DISABLED_BINDING_SHA256
            or stage.get("candidate_api", {}).get("manifest_sha256") != EXPECTED_API_MANIFEST_SHA256
            or stage.get("candidate_scheduler", {}).get("manifest_sha256") != EXPECTED_SCHEDULER_MANIFEST_SHA256):
        raise ValueError("POSTCANARY_STAGE_RECEIPT_REFERENCE_MISMATCH")
    return stage, binding, {"api": api_plist, "scheduler": scheduler_plist}


def _check_live_preimages(stage: dict[str, Any]) -> dict[str, Any]:
    _exact_directory(FORMAL_MANAGER_STATE, "POSTCANARY_FORMAL_STATE_ROOT_INVALID")
    if FORMAL_MANAGER_STATE.resolve(strict=True) != FORMAL_MANAGER_STATE:
        raise ValueError("POSTCANARY_FORMAL_STATE_ROOT_NOT_EXACT")
    preimages = {
        "api": (API_PLIST, PREIMAGE_ROOT / "active-api-only.plist", EXPECTED_ACTIVE_API_PLIST_SHA256,
                ACTIVE_API_ROOT),
        "scheduler": (SCHEDULER_PLIST, PREIMAGE_ROOT / "active-scheduler.plist", EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256,
                      ACTIVE_SCHEDULER_ROOT),
    }
    result: dict[str, Any] = {}
    for name, (live_path, preimage_path, expected_sha, active_root) in preimages.items():
        live_raw = _exact_file(live_path, "POSTCANARY_LIVE_PLIST_MISSING:" + name)
        preimage_raw = _exact_file(preimage_path, "POSTCANARY_SAVED_PREIMAGE_MISSING:" + name)
        if _sha(live_raw) != expected_sha or live_raw != preimage_raw:
            raise ValueError("POSTCANARY_LIVE_PLIST_PREIMAGE_MISMATCH:" + name)
        source_ref = stage.get("source_api_plist" if name == "api" else "source_scheduler_plist", {})
        if source_ref.get("path") != str(live_path) or source_ref.get("sha256") != expected_sha:
            raise ValueError("POSTCANARY_RELEASE_RECEIPT_LIVE_PREIMAGE_MISMATCH:" + name)
        payload = plistlib.loads(live_raw)
        env = _assignments(payload)
        if (env.get("V35_APP_ROOT") != str(active_root)
                or env.get("V4_MANAGER_RESEARCH_STATE_ROOT") != str(FORMAL_MANAGER_STATE)):
            raise ValueError("POSTCANARY_LIVE_PLIST_IDENTITY_MISMATCH:" + name)
        manifest_path = Path(env.get("V35_RELEASE_MANIFEST_PATH", ""))
        if not manifest_path.is_absolute() or manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("POSTCANARY_LIVE_RELEASE_MANIFEST_MISSING:" + name)
        if _sha(manifest_path.read_bytes()) != env.get("V35_RELEASE_MANIFEST_SHA256"):
            raise ValueError("POSTCANARY_LIVE_RELEASE_MANIFEST_SHA_MISMATCH:" + name)
        result[name] = {"path": str(live_path), "sha256": expected_sha,
                        "preimage_path": str(preimage_path), "preimage_sha256": _sha(preimage_raw),
                        "active_app_root": str(active_root), "release_manifest_path": str(manifest_path),
                        "release_manifest_sha256": env.get("V35_RELEASE_MANIFEST_SHA256")}
    if (result["api"]["sha256"] != stage["source_api_plist"]["sha256"]
            or result["scheduler"]["sha256"] != stage["source_scheduler_plist"]["sha256"]):
        raise ValueError("POSTCANARY_LIVE_PREIMAGE_RECEIPT_MISMATCH")
    return result


def _load_fresh_canary(expected_sha256: str | None, disabled_binding: dict[str, Any]) -> tuple[dict[str, Any], bytes, str]:
    operation = _read_json(CANARY_OPERATION_RECEIPT, "POSTCANARY_FRESH_CANARY_RECEIPT_MISSING")
    raw = _exact_file(CANARY_PATH, "POSTCANARY_FRESH_CANARY_MISSING")
    actual_sha = _sha(raw)
    if expected_sha256 is not None and actual_sha != expected_sha256:
        raise ValueError("POSTCANARY_EXPECTED_CANARY_SHA_MISMATCH")
    if (operation.get("status") != "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING"
            or operation.get("activation_status") != "NOT_ACTIVATED"
            or operation.get("launchctl_called") is not False
            or operation.get("canary_path") != str(CANARY_PATH)
            or operation.get("canary_sha256") != actual_sha
            or operation.get("api_app_root") != str(API_ROOT)
            or operation.get("manager_state_root") != str(FORMAL_MANAGER_STATE)
            or operation.get("candidate_release_manifest_sha256") != EXPECTED_API_MANIFEST_SHA256
            or operation.get("application_inventory_sha256") != EXPECTED_API_INVENTORY_SHA256):
        raise ValueError("POSTCANARY_OPERATION_RECEIPT_IDENTITY_MISMATCH")
    canary = json.loads(raw)
    source_inventory_sha = _canonical_sha(disabled_binding["files"])
    if (canary.get("status") != "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING"
            or canary.get("scope") != "HISTORICAL_MANUAL_REFRESH_WITH_HTTP_READBACK"
            or canary.get("app_root") != str(API_ROOT)
            or canary.get("candidate_binding_app_root") != str(API_ROOT)
            or canary.get("owner_execution_app_root") != str(API_ROOT)
            or canary.get("manager_state_root") != str(FORMAL_MANAGER_STATE)
            or canary.get("candidate_release_id") != "manager-daily-chain-20261008-r2-api"
            or canary.get("candidate_release_manifest_path") != str(API_RELEASE_ROOT / "release-manifest.json")
            or canary.get("candidate_release_manifest_sha256") != EXPECTED_API_MANIFEST_SHA256
            or canary.get("candidate_application_inventory_sha256") != EXPECTED_API_INVENTORY_SHA256
            or canary.get("candidate_manager_source_inventory_sha256") != source_inventory_sha
            or canary.get("candidate_release_manifest_sha256") != operation.get("candidate_release_manifest_sha256")
            or canary.get("candidate_application_inventory_sha256") != operation.get("application_inventory_sha256")
            or canary.get("plan_material_refresh_only") is not True
            or canary.get("announcement_collection_enabled") is not False
            or canary.get("announcement_network_requests") != 0
            or canary.get("hook_executed") is not False
            or canary.get("research_only") is not True
            or canary.get("formal_recommendation_count") != 0
            or canary.get("execution_kind") != "MANUAL_REFRESH"
            or canary.get("owner") != "ManagerResearchJobService.refresh_workspace_plan"
            or canary.get("owner_attempt_state") not in {"SUCCEEDED", "PARTIAL"}
            or any(canary.get(k) != v for k, v in SAFETY.items())
            or not re.fullmatch(r"[0-9a-f]{32}", str(canary.get("run_id", "")))):
        raise ValueError("POSTCANARY_CANARY_RELEASE_OR_POLICY_MISMATCH")
    if (canary.get("target_trade_date") != "20260925"
            or operation.get("target_trade_date") != canary.get("target_trade_date")
            or operation.get("run_id") != canary.get("run_id")
            or operation.get("product_sha256") != canary.get("product_sha256")
            or operation.get("input_identity") != canary.get("input_identity")
            or operation.get("owner_attempt_state") != canary.get("owner_attempt_state")
            or operation.get("manager_source_inventory_sha256") != source_inventory_sha):
        raise ValueError("POSTCANARY_CANARY_OPERATION_PAIR_MISMATCH")
    state_preimage = canary.get("state_preimage")
    if (not isinstance(state_preimage, dict)
            or state_preimage.get("target_preexisted") is not False
            or state_preimage.get("protected_dates_sha256") != _protected_hashes(FORMAL_MANAGER_STATE)):
        raise ValueError("POSTCANARY_PROTECTED_STATE_PREIMAGE_MISMATCH")
    _verify_owner_store(canary)
    return operation, raw, actual_sha


def _verify_owner_store(canary: dict[str, Any]) -> None:
    """Recheck the canary's exact durable owner write set and latest readback."""
    target = canary["target_trade_date"]
    run_id = canary["run_id"]
    product_sha = canary["product_sha256"]
    run_root = FORMAL_MANAGER_STATE / "workspace_plan_runs" / target
    plan_root = FORMAL_MANAGER_STATE / "workspace_plans" / target
    expected = {"latest.json", f"{run_id}.json"}
    for root in (run_root, plan_root):
        _exact_directory(root, "POSTCANARY_OWNER_STORE_ROOT_INVALID")
        actual = set()
        for item in root.iterdir():
            if item.is_symlink():
                raise ValueError("POSTCANARY_OWNER_STORE_SYMLINK")
            if item.is_file():
                actual.add(item.name)
            elif not item.is_dir():
                raise ValueError("POSTCANARY_OWNER_STORE_ENTRY_INVALID")
        if actual != expected:
            raise ValueError("POSTCANARY_OWNER_STORE_WRITE_SET_CHANGED")
    run_latest = _read_json(run_root / "latest.json", "POSTCANARY_OWNER_RUN_READBACK_INVALID")
    plan_latest = _read_json(plan_root / "latest.json", "POSTCANARY_OWNER_PLAN_READBACK_INVALID")
    plan_run = _read_json(plan_root / f"{run_id}.json", "POSTCANARY_OWNER_PLAN_RUN_INVALID")
    owner = "ManagerResearchJobService.refresh_workspace_plan"
    if (run_latest.get("run_id") != run_id or run_latest.get("state") != canary.get("owner_attempt_state")
            or plan_latest.get("run_id") != run_id or plan_latest.get("sha256") != product_sha
            or plan_latest.get("execution_kind") != "MANUAL_REFRESH" or plan_latest.get("owner") != owner
            or plan_run != plan_latest):
        raise ValueError("POSTCANARY_OWNER_STORE_READBACK_MISMATCH")
    lock_path = FORMAL_MANAGER_STATE / ".locks" / f"{target}-workspace-plan-refresh.mutex"
    if lock_path.exists() or lock_path.is_symlink():
        raise ValueError("POSTCANARY_OWNER_STORE_LOCK_REMAINS")


def _build_enabled_binding(disabled: dict[str, Any], *, canary_path: Path,
                           canary_sha256: str) -> dict[str, Any]:
    binding = copy.deepcopy(disabled)
    binding.update({
        "enabled": True,
        "plan_material_refresh_only": True,
        "announcement_collection_enabled": False,
        "plan_material_refresh": copy.deepcopy(PLAN_REFRESH),
        "plan_activation_receipt": {"path": str(canary_path), "sha256": canary_sha256},
        "activation_status": "CANARY_VALIDATED_STAGED_NOT_ACTIVATED",
    })
    if binding.get("activation_receipt") is not None:
        raise ValueError("POSTCANARY_ANNOUNCEMENT_ACTIVATION_RECEIPT_FORBIDDEN")
    if any(binding.get(k) != v for k, v in SAFETY.items()):
        raise ValueError("POSTCANARY_SAFETY_FLAGS_INVALID")
    return binding


def _build_plists(disabled_plists: dict[str, Any], *, binding_path: Path,
                  canary_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    api = _legacy_api_rewrite(copy.deepcopy(disabled_plists["api"]))
    scheduler = copy.deepcopy(disabled_plists["scheduler"])
    api_env = _assignments(api)
    if (api_env.get("V35_APP_ROOT") != str(API_ROOT)
            or api_env.get("V4_MANAGER_RESEARCH_STATE_ROOT") != str(FORMAL_MANAGER_STATE)
            or api_env.get("V35_RELEASE_MANIFEST_SHA256") != EXPECTED_API_MANIFEST_SHA256
            or api_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(DISABLED_BINDING)):
        raise ValueError("POSTCANARY_DISABLED_API_PLIST_IDENTITY_MISMATCH")
    api["ProgramArguments"] = _replace_env_args(api["ProgramArguments"], {
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(binding_path),
    })
    sched_env = scheduler.get("EnvironmentVariables")
    if not isinstance(sched_env, dict):
        raise ValueError("POSTCANARY_SCHEDULER_ENVIRONMENT_INVALID")
    if (sched_env.get("V35_APP_ROOT") != str(SCHEDULER_ROOT)
            or sched_env.get("V4_MANAGER_RESEARCH_STATE_ROOT") != str(FORMAL_MANAGER_STATE)
            or sched_env.get("V35_RELEASE_MANIFEST_SHA256") != EXPECTED_SCHEDULER_MANIFEST_SHA256
            or sched_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(DISABLED_BINDING)):
        raise ValueError("POSTCANARY_DISABLED_SCHEDULER_PLIST_IDENTITY_MISMATCH")
    sched_env.update({
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(binding_path),
        "V4_MANAGER_ANNOUNCEMENT_BINDING": str(binding_path),
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": canary_sha256,
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": str(API_ROOT),
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": _sha((API_ROOT / "ops/run_manager_announcement_cycle.py").read_bytes()),
    })
    if (sched_env.get("V35_RELEASE_MANIFEST_SHA256") != EXPECTED_SCHEDULER_MANIFEST_SHA256
            or sched_env.get("V35_RELEASE_ID") != "manager-daily-chain-20261008-r2-scheduler"
            or sched_env.get("V4_MANAGER_ANNOUNCEMENT_PYTHON") != str(EXACT_PYTHON)
            or sched_env.get("V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256") != _sha(EXACT_PYTHON.resolve(strict=True).read_bytes())
            or sched_env.get("production_allowed", "false").lower() != "false"
            or sched_env.get("buy_gate_updated", "false").lower() != "false"
            or sched_env.get("orders_sent", "false").lower() != "false"):
        raise ValueError("POSTCANARY_SCHEDULER_PIN_OR_SAFETY_MISMATCH")
    if _assignments(api).get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(binding_path):
        raise ValueError("POSTCANARY_API_OWNER_BINDING_PIN_MISMATCH")
    return api, scheduler


def _write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def _prepare(expected_canary_sha256: str | None) -> dict[str, Any]:
    stage, disabled, disabled_plists = _check_release_and_disabled_inputs()
    live_preimages = _check_live_preimages(stage)
    operation, canary_raw, canary_sha = _load_fresh_canary(expected_canary_sha256, disabled)
    binding_path = TASK_ROOT / "staged_config/postcanary" / canary_sha / "manager-plan-binding-c1.enabled.json"
    binding = _build_enabled_binding(disabled, canary_path=CANARY_PATH, canary_sha256=canary_sha)
    _validate_binding(binding)
    api_plist, scheduler_plist = _build_plists(disabled_plists, binding_path=binding_path,
                                               canary_sha256=canary_sha)
    api_env, scheduler_env = _assignments(api_plist), _assignments(scheduler_plist)
    if (api_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(binding_path)
            or scheduler_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(binding_path)
            or scheduler_env.get("V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256") != canary_sha):
        raise ValueError("POSTCANARY_CANDIDATE_PLIST_BINDING_MISMATCH")
    output_root = binding_path.parent
    receipt = {
        "schema_version": "manager_daily_chain.postcanary_config_stage.v1",
        "status": "POSTCANARY_ENABLED_CONFIG_READY_FOR_INDEPENDENT_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False,
        "live_files_written": False,
        "manager_state_written_by_this_helper": False,
        "output_root": str(output_root),
        "canary": {"path": str(CANARY_PATH), "sha256": canary_sha,
                   "operation_receipt_path": str(CANARY_OPERATION_RECEIPT),
                   "operation_receipt_sha256": _sha(_exact_file(CANARY_OPERATION_RECEIPT, "POSTCANARY_RECEIPT_MISSING"))},
        "api_release": {"root": str(API_ROOT), "release_id": "manager-daily-chain-20261008-r2-api",
                        "manifest_sha256": EXPECTED_API_MANIFEST_SHA256,
                        "inventory_sha256": EXPECTED_API_INVENTORY_SHA256},
        "scheduler_release": {"root": str(SCHEDULER_ROOT), "release_id": "manager-daily-chain-20261008-r2-scheduler",
                              "manifest_sha256": EXPECTED_SCHEDULER_MANIFEST_SHA256,
                              "inventory_sha256": EXPECTED_SCHEDULER_INVENTORY_SHA256},
        "manager_state_root": str(FORMAL_MANAGER_STATE),
        "enabled_binding": {"path": str(binding_path), "enabled": True,
                            "plan_material_refresh_only": True,
                            "announcement_collection_enabled": False,
                            "sha256": _sha((json.dumps(binding, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())},
        "staged_api_plist": {"path": str(output_root / "com.lexi.v35.api-only.plist"),
                             "owner_binding_path": api_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH")},
        "staged_scheduler_plist": {"path": str(output_root / "com.lexi.v35.scheduler.plist"),
                                   "owner_binding_path": scheduler_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH"),
                                   "plan_canary_sha256": scheduler_env.get("V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256")},
        "live_preimages": live_preimages,
        "rollback": {
            "status": "IDENTITY_ONLY_NO_LIVE_CHANGE",
            "api_plist_preimage": {"path": live_preimages["api"]["preimage_path"], "sha256": live_preimages["api"]["preimage_sha256"]},
            "scheduler_plist_preimage": {"path": live_preimages["scheduler"]["preimage_path"], "sha256": live_preimages["scheduler"]["preimage_sha256"]},
            "guard": "Both live LaunchAgent plist bytes were compared with their preserved preimages; no live path was changed.",
        },
        "next_gate": "Independent review of the fresh canary, exact enabled binding, staged API/scheduler plists, and live preimages. This helper does not activate them.",
        "cutover_backend": {
            "existing_api_only_prepare": "ops.prepare_api_only_cutover.render_cutover requires an isolated manager state root and is not called; its SHA-pinned rewrite_api_only_plist renderer is reused for the API plist only.",
            "safe_cutover_backend_path": str(API_ROOT / "ops/prepare_api_only_cutover.py"),
            "safe_cutover_backend_sha256": EXPECTED_SAFE_CUTOVER_BACKEND_SHA256,
            "execution_python": binding.get("python"),
            "stager_python": sys.executable,
            "existing_launchagent_builder": "ops.install_v35_macos_launchagents renders plist files; it does not install them or call launchctl.",
            "same_root_cutover_executor": "NOT_FOUND_IN_REVIEWED_HELPERS",
        },
        "safety": SAFETY,
    }
    return {"binding": binding, "api_plist": api_plist, "scheduler_plist": scheduler_plist,
            "receipt": receipt, "output_root": output_root, "canary_raw": canary_raw,
            "operation": operation}


def dry_run(expected_canary_sha256: str | None = None) -> dict[str, Any]:
    # Validate the real frozen R2 roots, disabled staged binding, staged
    # plists, and unchanged live plist preimages even when the fresh canary is
    # not available yet. This makes the default dry-run useful without relying
    # on fixture-only paths.
    stage, disabled, disabled_plists = _check_release_and_disabled_inputs()
    live_preimages = _check_live_preimages(stage)
    pending_binding = TASK_ROOT / "staged_config/postcanary/PENDING/manager-plan-binding-c1.enabled.json"
    preview_api, preview_scheduler = _build_plists(
        disabled_plists, binding_path=pending_binding, canary_sha256="0" * 64)
    preview_api_env = _assignments(preview_api)
    preview_scheduler_env = _assignments(preview_scheduler)
    actual_inputs = {
        "api_release_manifest_sha256": EXPECTED_API_MANIFEST_SHA256,
        "api_inventory_sha256": EXPECTED_API_INVENTORY_SHA256,
        "scheduler_release_manifest_sha256": EXPECTED_SCHEDULER_MANIFEST_SHA256,
        "scheduler_inventory_sha256": EXPECTED_SCHEDULER_INVENTORY_SHA256,
        "disabled_binding_path": str(DISABLED_BINDING),
        "disabled_binding_sha256": EXPECTED_DISABLED_BINDING_SHA256,
        "staged_api_plist_path": str(DISABLED_API_PLIST),
        "staged_api_plist_sha256": EXPECTED_DISABLED_API_PLIST_SHA256,
        "staged_scheduler_plist_path": str(DISABLED_SCHEDULER_PLIST),
        "staged_scheduler_plist_sha256": EXPECTED_DISABLED_SCHEDULER_PLIST_SHA256,
        "api_execution_python": disabled["python"],
        "stager_python": sys.executable,
        "same_root_api_renderer": {
            "path": str(API_ROOT / "ops/prepare_api_only_cutover.py"),
            "sha256": EXPECTED_SAFE_CUTOVER_BACKEND_SHA256,
            "api_binding_path_preview": preview_api_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH"),
            "scheduler_binding_path_preview": preview_scheduler_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH"),
        },
        "live_plist_preimages": live_preimages,
    }
    if not CANARY_PATH.exists() or not CANARY_OPERATION_RECEIPT.exists():
        return {
            "status": "BLOCKED_FRESH_CANARY_REQUIRED",
            "activation_status": "NOT_ACTIVATED",
            "launchctl_called": False,
            "live_files_written": False,
            "canary_path": str(CANARY_PATH),
            "manager_state_root": str(FORMAL_MANAGER_STATE),
            "expected_release_id": "manager-daily-chain-20261008-r2-api",
            "validated_inputs": actual_inputs,
            "action": "Run only after an independently acceptable fresh exact-root plan owner canary exists.",
            "safety": SAFETY,
        }
    result = _prepare(expected_canary_sha256)
    receipt = result["receipt"]
    receipt["status"] = "DRY_RUN_READY_TO_STAGE_NOT_ACTIVATED"
    receipt["live_files_written"] = False
    receipt["output_root_exists"] = result["output_root"].exists()
    receipt["validated_inputs"] = actual_inputs
    return receipt


def stage_enabled(expected_canary_sha256: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_canary_sha256):
        raise ValueError("POSTCANARY_EXPECTED_CANARY_SHA_INVALID")
    result = _prepare(expected_canary_sha256)
    output_root: Path = result["output_root"]
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError("POSTCANARY_OUTPUT_ALREADY_EXISTS:" + str(output_root))
    output_root.mkdir(parents=True, exist_ok=False)
    binding_raw = (json.dumps(result["binding"], ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    api_raw = plistlib.dumps(result["api_plist"], fmt=plistlib.FMT_XML, sort_keys=True)
    scheduler_raw = plistlib.dumps(result["scheduler_plist"], fmt=plistlib.FMT_XML, sort_keys=True)
    binding_path = output_root / "manager-plan-binding-c1.enabled.json"
    api_path = output_root / "com.lexi.v35.api-only.plist"
    scheduler_path = output_root / "com.lexi.v35.scheduler.plist"
    receipt_path = output_root / "postcanary-stage-receipt.json"
    result["receipt"]["enabled_binding"]["sha256"] = _sha(binding_raw)
    result["receipt"]["staged_api_plist"]["sha256"] = _sha(api_raw)
    result["receipt"]["staged_scheduler_plist"]["sha256"] = _sha(scheduler_raw)
    result["receipt"]["status"] = "POSTCANARY_ENABLED_CONFIG_STAGED_NOT_ACTIVATED"
    _write_exclusive(binding_path, binding_raw)
    _write_exclusive(api_path, api_raw)
    _write_exclusive(scheduler_path, scheduler_raw)
    _write_exclusive(receipt_path, (json.dumps(result["receipt"], ensure_ascii=False,
                                                sort_keys=True, indent=2) + "\n").encode())
    return result["receipt"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-enabled", action="store_true",
                        help="write only candidate enabled binding/plist copies after all guards pass")
    parser.add_argument("--expected-canary-sha256",
                        help="exact SHA-256 printed in the successful canary operation receipt")
    args = parser.parse_args(argv)
    if args.stage_enabled and not args.expected_canary_sha256:
        parser.error("--stage-enabled requires --expected-canary-sha256")
    try:
        result = stage_enabled(args.expected_canary_sha256) if args.stage_enabled else dry_run(args.expected_canary_sha256)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc),
                          "activation_status": "NOT_ACTIVATED", "launchctl_called": False,
                          "safety": SAFETY}, ensure_ascii=False, sort_keys=True, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("status") != "BLOCKED_FRESH_CANARY_REQUIRED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
