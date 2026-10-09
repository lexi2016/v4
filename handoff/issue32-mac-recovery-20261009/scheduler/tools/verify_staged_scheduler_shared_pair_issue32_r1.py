from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
import sys
from pathlib import Path
from typing import Any


E = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009")
PAIR = E / "candidate/issue32_scheduler_shared_pair_r1"
STAGE = PAIR / "staged_pair_r2"
SCHEDULER_APP = STAGE / "scheduler/app"
SHARED_PACKAGE = STAGE / "shared_owner/app/upstreams/v3_shared_data"
SCHEDULER_MANIFEST = STAGE / "scheduler/release-manifest.json"
SHARED_MANIFEST = STAGE / "shared_owner/release-manifest.json"
PAIR_MANIFEST = STAGE / "release-pair-manifest.json"
STAGED_PLIST = STAGE / "scheduler/config/com.lexi.v35.scheduler.plist"
STAGING_RECEIPT = E / "writer/scheduler_shared_pair_staging_r2.json"
PAIR_RECEIPT = E / "writer/scheduler_shared_pair_candidate_r1.json"
CANARY_APP = PAIR / "canary_r5/scheduler_app"
CURRENT_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
ACTIVE_SCHEDULER_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "hk-research-calendar-all-r1-20261007-scheduler/app"
)
ACTIVE_SHARED_PACKAGE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data"
)
INTEGRATION_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_ISSUE30_MAC_20261008/integration/ops/api_release_integration.py"
)
OUTPUT = E / "evidence/scheduler_shared_pair_stage_verification_r2.json"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_module():
    spec = importlib.util.spec_from_file_location("issue32_stage_verify_api", INTEGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("API_RELEASE_INTEGRATION_HELPER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit("REFUSE_EXISTING_VERIFICATION_RECEIPT")
    api = load_module()
    staged = json.loads(STAGING_RECEIPT.read_text(encoding="utf-8"))
    pair = json.loads(PAIR_RECEIPT.read_text(encoding="utf-8"))
    scheduler_manifest_raw = SCHEDULER_MANIFEST.read_bytes()
    scheduler_manifest = json.loads(scheduler_manifest_raw)
    shared_manifest_raw = SHARED_MANIFEST.read_bytes()
    shared_manifest = json.loads(shared_manifest_raw)
    pair_manifest_raw = PAIR_MANIFEST.read_bytes()
    pair_manifest = json.loads(pair_manifest_raw)
    plist_raw = STAGED_PLIST.read_bytes()
    staged_plist = plistlib.loads(plist_raw)
    env = staged_plist.get("EnvironmentVariables")
    if not isinstance(env, dict):
        raise SystemExit("STAGED_PLIST_ENV_INVALID")

    scheduler_inventory = api.inventory_tree(SCHEDULER_APP)
    shared_inventory = api.inventory_tree(SHARED_PACKAGE)
    if scheduler_inventory != scheduler_manifest["application_inventory"]["entries"]:
        raise SystemExit("STAGED_SCHEDULER_MANIFEST_INVENTORY_MISMATCH")
    if shared_inventory != shared_manifest["application_inventory"]["entries"]:
        raise SystemExit("STAGED_SHARED_MANIFEST_INVENTORY_MISMATCH")
    if api.inventory_digest(scheduler_inventory) != scheduler_manifest["application_inventory"]["aggregate_sha256"]:
        raise SystemExit("STAGED_SCHEDULER_MANIFEST_AGGREGATE_MISMATCH")
    if api.inventory_digest(shared_inventory) != shared_manifest["application_inventory"]["aggregate_sha256"]:
        raise SystemExit("STAGED_SHARED_MANIFEST_AGGREGATE_MISMATCH")
    if scheduler_inventory != api.inventory_tree(CANARY_APP):
        raise SystemExit("STAGED_SCHEDULER_TREE_DIFFERS_FROM_CANARY_TREE")

    active_scheduler_inventory = api.inventory_tree(ACTIVE_SCHEDULER_APP)
    active_scheduler_by_path = {entry["path"]: entry for entry in active_scheduler_inventory}
    staged_scheduler_by_path = {entry["path"]: entry for entry in scheduler_inventory}
    scheduler_delta = sorted(
        path for path in set(active_scheduler_by_path) | set(staged_scheduler_by_path)
        if active_scheduler_by_path.get(path) != staged_scheduler_by_path.get(path)
    )
    expected_scheduler_delta = sorted(
        "upstreams/v3_shared_data/" + item["product_path"]
        if item.get("owner") == "actual_shared_owner"
        else item["product_path"]
        for item in pair["files"]
    )
    if scheduler_delta != expected_scheduler_delta:
        raise SystemExit("STAGED_SCHEDULER_DELTA_NOT_EXACT")

    active_shared_inventory = api.inventory_tree(ACTIVE_SHARED_PACKAGE)
    active_shared_by_path = {entry["path"]: entry for entry in active_shared_inventory}
    staged_shared_by_path = {entry["path"]: entry for entry in shared_inventory}
    shared_delta = sorted(
        path for path in set(active_shared_by_path) | set(staged_shared_by_path)
        if active_shared_by_path.get(path) != staged_shared_by_path.get(path)
    )
    if shared_delta != ["shared_data/hk_security_master.py"]:
        raise SystemExit("STAGED_SHARED_DELTA_NOT_EXACT")

    current_plist_sha = sha(CURRENT_PLIST.read_bytes())
    if current_plist_sha != staged["scheduler_plist_preimage_sha256"]:
        raise SystemExit("CURRENT_SCHEDULER_PLIST_PREIMAGE_DRIFT")
    scheduler_release = staged["scheduler_release_id"]
    scheduler_manifest_sha = sha(scheduler_manifest_raw)
    target_scheduler_manifest = staged["scheduler_manifest_path_runtime"]
    target_scheduler_app = str(Path(target_scheduler_manifest).parent / "app")
    shared_release = staged["shared_release_id"]
    if (
        scheduler_manifest.get("release_id") != scheduler_release
        or scheduler_manifest.get("candidate", {}).get("release_id") != scheduler_release
        or scheduler_manifest.get("candidate", {}).get("app_root") != target_scheduler_app
        or scheduler_manifest.get("candidate", {}).get("manifest_path") != target_scheduler_manifest
        or shared_manifest.get("release_id") != shared_release
        or shared_manifest.get("candidate", {}).get("release_id") != shared_release
        or pair_manifest.get("scheduler_release", {}).get("release_id") != scheduler_release
        or pair_manifest.get("scheduler_release", {}).get("manifest_sha256") != scheduler_manifest_sha
        or pair_manifest.get("shared_owner_release", {}).get("release_id") != shared_release
        or pair_manifest.get("shared_owner_release", {}).get("manifest_sha256") != sha(shared_manifest_raw)
    ):
        raise SystemExit("STAGED_RELEASE_MANIFEST_IDENTITY_FIELDS_MISMATCH")
    target_shared_package = staged["shared_manifest_path_runtime"].replace(
        "/release-manifest.json", "/app/upstreams/v3_shared_data"
    )
    expected_pythonpath = str(Path(target_scheduler_app) / "upstreams") + ":" + target_scheduler_app
    required_bindings = {
        "V35_APP_ROOT": target_scheduler_app,
        "V35_RELEASE_ID": scheduler_release,
        "V35_RELEASE_MANIFEST_PATH": target_scheduler_manifest,
        "V35_RELEASE_MANIFEST_SHA256": scheduler_manifest_sha,
        "V35_SHARED_PACKAGE_ROOT": target_shared_package,
        "PYTHONPATH": expected_pythonpath,
    }
    for key, expected in required_bindings.items():
        if env.get(key) != expected:
            raise SystemExit(f"STAGED_PLIST_IDENTITY_MISMATCH:{key}")
    if staged_plist.get("ProgramArguments") != ["/bin/bash", str(Path(target_scheduler_app) / "ops/launch_v35_macos_scheduler.sh")]:
        raise SystemExit("STAGED_PLIST_PROGRAM_ARGUMENTS_MISMATCH")
    if staged_plist.get("WorkingDirectory") != target_scheduler_app:
        raise SystemExit("STAGED_PLIST_WORKING_DIRECTORY_MISMATCH")
    if any(old in env["PYTHONPATH"] for old in ("20260929-manager-1555-pytdx-r1", "20260908-full-repair-a-content-isolation")):
        raise SystemExit("STAGED_PLIST_HAS_OLD_PYTHONPATH_FALLBACK")
    old_plist = plistlib.loads(CURRENT_PLIST.read_bytes())
    old_env = old_plist.get("EnvironmentVariables", {})
    preserved_keys = sorted(set(old_env) - set(required_bindings))
    changed_preserved = [key for key in preserved_keys if env.get(key) != old_env.get(key)]
    # The established renderer normalizes safety flags to false; they were
    # already false in the verified active plist. Anything else must persist.
    if changed_preserved:
        raise SystemExit("STAGED_PLIST_UNRELATED_ENVIRONMENT_CHANGED:" + ",".join(changed_preserved))

    target_scheduler_release = Path(target_scheduler_manifest).parent
    target_shared_release = Path(staged["shared_manifest_path_runtime"]).parent
    formal_target_state = {
        "scheduler_release_exists": target_scheduler_release.exists(),
        "shared_release_exists": target_shared_release.exists(),
    }
    if any(formal_target_state.values()):
        raise SystemExit("FORMAL_RELEASE_PATH_ALREADY_EXISTS_STOP")

    result = {
        "schema_version": "v4.issue32.scheduler_shared_stage_verification.v1",
        "status": "PASS_FULL_PAIR_STAGE_IDENTITIES_AND_SCHEDULER_PLIST_BINDINGS",
        "stage_receipt_sha256": sha(STAGING_RECEIPT.read_bytes()),
        "pair_manifest_sha256": sha(pair_manifest_raw),
        "scheduler_release_manifest_sha256": scheduler_manifest_sha,
        "shared_owner_release_manifest_sha256": sha(shared_manifest_raw),
        "scheduler_app_inventory_sha256": api.inventory_digest(scheduler_inventory),
        "scheduler_app_inventory_entry_count": len(scheduler_inventory),
        "scheduler_delta": scheduler_delta,
        "shared_package_inventory_sha256": api.inventory_digest(shared_inventory),
        "shared_package_inventory_entry_count": len(shared_inventory),
        "shared_delta": shared_delta,
        "scheduler_plist_preimage_sha256": current_plist_sha,
        "staged_scheduler_plist_sha256": sha(plist_raw),
        "staged_runtime_bindings": required_bindings,
        "staged_program_arguments": staged_plist.get("ProgramArguments"),
        "staged_working_directory": staged_plist.get("WorkingDirectory"),
        "unmodified_environment_key_count": len(preserved_keys),
        "unmodified_environment_keys_changed": changed_preserved,
        "formal_target_state": formal_target_state,
        "actual_launchd_state_checked": False,
        "launchctl_called": False,
        "formal_release_written": False,
        "service_mutated": False,
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(OUTPUT, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    print(json.dumps({"path": str(OUTPUT), "sha256": sha(raw), **result}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
