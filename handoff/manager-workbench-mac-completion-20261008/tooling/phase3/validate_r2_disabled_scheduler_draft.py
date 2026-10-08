#!/usr/bin/env python3
"""Read-only validation for the staged API-R2 disabled scheduler draft."""
from __future__ import annotations

import hashlib
import json
import plistlib
import sys
from pathlib import Path
from typing import Any

TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/phase3")
API_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-api-r2/app")
API_RELEASE_ROOT = API_ROOT.parent
SCHEDULER_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-scheduler/app")
SCHEDULER_RELEASE_ROOT = SCHEDULER_ROOT.parent
ACTIVE_SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
EXPECTED_ACTIVE_SCHEDULER_SHA256 = "c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2"
BINDING_PATH = TASK_ROOT / "drafts/plan_canary_preflight_binding.r2.disabled.json"
API_PLIST_PATH = TASK_ROOT / "drafts/com.lexi.v35.api-only.plan-canary.r2.draft.plist"
SCHEDULER_PLIST_PATH = TASK_ROOT / "drafts/com.lexi.v35.scheduler.plan-only.r2.disabled.draft.plist"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _environment(plist: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in plist.get("ProgramArguments", []):
        if isinstance(item, str) and "=" in item:
            name, value = item.split("=", 1)
            result[name] = value
    return result


def main() -> int:
    binding_raw = BINDING_PATH.read_bytes()
    binding = json.loads(binding_raw)
    active_raw = ACTIVE_SCHEDULER_PLIST.read_bytes()
    active = plistlib.loads(active_raw)
    scheduler_raw = SCHEDULER_PLIST_PATH.read_bytes()
    scheduler_plist = plistlib.loads(scheduler_raw)
    api_raw = API_PLIST_PATH.read_bytes()
    api_plist = plistlib.loads(api_raw)

    active_sha = _sha(active_raw)
    if active_sha != EXPECTED_ACTIVE_SCHEDULER_SHA256:
        raise ValueError("D1_ACTIVE_SCHEDULER_PREIMAGE_CHANGED")
    manifest_path = SCHEDULER_RELEASE_ROOT / "release-manifest.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if (manifest.get("schema_version") != "v4.release_candidate.v1"
            or manifest.get("candidate", {}).get("release_id") != "manager-workbench-r1-mac-20261008-scheduler"
            or manifest.get("candidate", {}).get("app_root") != str(SCHEDULER_ROOT)):
        raise ValueError("D1_SCHEDULER_RELEASE_IDENTITY_MISMATCH")

    active_env = active.get("EnvironmentVariables", {})
    draft_env = scheduler_plist.get("EnvironmentVariables", {})
    expected_changed = {
        "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256",
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT", "V4_MANAGER_ANNOUNCEMENT_BINDING",
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256", "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256",
    }
    changed = sorted(key for key in set(active_env) | set(draft_env)
                     if active_env.get(key) != draft_env.get(key))
    if set(changed) != expected_changed:
        raise ValueError("D1_SCHEDULER_ENVIRONMENT_DIFF_UNEXPECTED")
    if (scheduler_plist.get("Label") != active.get("Label")
            or scheduler_plist.get("KeepAlive") != active.get("KeepAlive")
            or scheduler_plist.get("WorkingDirectory") != str(SCHEDULER_ROOT)
            or scheduler_plist.get("ProgramArguments") != [
                "/bin/bash", str(SCHEDULER_ROOT / "ops/launch_v35_macos_scheduler.sh")
            ]):
        raise ValueError("D1_SCHEDULER_LAUNCH_IDENTITY_INVALID")
    if (draft_env.get("V35_DAEMON_MODE") != active_env.get("V35_DAEMON_MODE")
            or draft_env.get("V35_DAEMON_HEARTBEAT_SECONDS") != active_env.get("V35_DAEMON_HEARTBEAT_SECONDS")
            or draft_env.get("V35_DAEMON_MODE") != "persistent-minute"
            or draft_env.get("V35_DAEMON_HEARTBEAT_SECONDS") != "60"):
        raise ValueError("D1_SCHEDULER_HEARTBEAT_OWNER_CHANGED")

    api_env = _environment(api_plist)
    if (api_plist.get("WorkingDirectory") != str(API_ROOT)
            or api_env.get("V35_APP_ROOT") != str(API_ROOT)
            or api_env.get("V35_RELEASE_MANIFEST_PATH") != str(API_RELEASE_ROOT / "release-manifest.json")
            or api_env.get("V35_RELEASE_MANIFEST_SHA256") != _sha((API_RELEASE_ROOT / "release-manifest.json").read_bytes())
            or api_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(BINDING_PATH)):
        raise ValueError("D1_API_R2_DRAFT_IDENTITY_MISMATCH")
    if (binding.get("app_root") != str(API_ROOT) or binding.get("enabled") is not False
            or binding.get("plan_material_refresh_only") is not False
            or binding.get("announcement_collection_enabled") is not False
            or draft_env.get("V4_MANAGER_ANNOUNCEMENT_APP_ROOT") != str(API_ROOT)
            or draft_env.get("V4_MANAGER_ANNOUNCEMENT_BINDING") != str(BINDING_PATH)
            or draft_env.get("V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256") != ""):
        raise ValueError("D1_R2_DISABLED_BINDING_IDENTITY_MISMATCH")

    active_scheduler_entry = Path(active["WorkingDirectory"]) / "ops/run_v35_macos_scheduler.py"
    candidate_scheduler_entry = SCHEDULER_ROOT / "ops/run_v35_macos_scheduler.py"
    entry_sha = _sha(active_scheduler_entry.read_bytes())
    if entry_sha != _sha(candidate_scheduler_entry.read_bytes()):
        raise ValueError("D1_SCHEDULER_SLOT_ENTRYPOINT_CHANGED")

    sys.path.insert(0, str(SCHEDULER_ROOT))
    from ops.run_v35_macos_scheduler_daemon import _load_announcement_binding

    loaded = _load_announcement_binding({
        "V4_MANAGER_ANNOUNCEMENT_BINDING": str(BINDING_PATH),
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": str(API_ROOT),
        "V4_MANAGER_ANNOUNCEMENT_PYTHON": binding["python"],
        "V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256": binding["python_sha256"],
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": binding["files"]["ops/run_manager_announcement_cycle.py"],
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": "",
    })
    if (loaded.get("app_root") != API_ROOT or loaded.get("enabled") is not False
            or loaded.get("plan_material_refresh_only") is not False
            or loaded.get("announcement_collection_enabled") is not False):
        raise ValueError("D1_SCHEDULER_BINDING_VALIDATION_MISMATCH")

    print(json.dumps({
        "status": "PASS_DISABLED_R2_BINDING_AND_SCHEDULER_DRAFT",
        "api_binding_sha256": _sha(binding_raw),
        "api_plist_sha256": _sha(api_raw),
        "active_scheduler_plist_sha256": active_sha,
        "scheduler_plist_sha256": _sha(scheduler_raw),
        "scheduler_release_manifest_sha256": _sha(manifest_raw),
        "scheduler_slot_entrypoint_sha256": entry_sha,
        "changed_environment_keys": changed,
        "preserved_all_other_environment_keys": True,
        "heartbeat_mode": draft_env["V35_DAEMON_MODE"],
        "heartbeat_seconds": draft_env["V35_DAEMON_HEARTBEAT_SECONDS"],
        "scheduler_activation": "NOT_PERFORMED",
        "launchctl_called": False,
        "announcement_collection_enabled": False,
        "plan_material_refresh_only": False,
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                   "buy_gate_updated": False, "orders_sent": False},
    }, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
