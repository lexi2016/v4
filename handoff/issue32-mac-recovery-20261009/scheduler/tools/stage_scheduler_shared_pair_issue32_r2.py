from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


E = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009")
PAIR = E / "candidate/issue32_scheduler_shared_pair_r1"
STAGE = PAIR / "staged_pair_r2"
STAGING_RECEIPT = E / "writer/scheduler_shared_pair_staging_r2.json"
SCHEDULER_STAGE = STAGE / "scheduler"
SCHEDULER_APP = SCHEDULER_STAGE / "app"
SHARED_STAGE = STAGE / "shared_owner"
SHARED_APP = SHARED_STAGE / "app"
SHARED_PACKAGE = SHARED_APP / "upstreams/v3_shared_data"
CONFIG = SCHEDULER_STAGE / "config/com.lexi.v35.scheduler.plist"
PAIR_RECEIPT = E / "writer/scheduler_shared_pair_candidate_r1.json"
CANARY_APP = PAIR / "canary_r5/scheduler_app"
SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
ACTIVE_SCHEDULER_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "hk-research-calendar-all-r1-20261007-scheduler/app"
)
ACTIVE_SCHEDULER_RELEASE = ACTIVE_SCHEDULER_APP.parent
ACTIVE_SHARED_PACKAGE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data"
)
FORMAL_RELEASE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases")
SCHEDULER_RELEASE_ID = "issue32-preselection-scheduler-mac-20261009-r1"
SHARED_RELEASE_ID = "issue32-hk-security-master-owner-mac-20261009-r1"
TARGET_SCHEDULER_RELEASE = FORMAL_RELEASE_ROOT / SCHEDULER_RELEASE_ID
TARGET_SCHEDULER_APP = TARGET_SCHEDULER_RELEASE / "app"
TARGET_SCHEDULER_MANIFEST = TARGET_SCHEDULER_RELEASE / "release-manifest.json"
TARGET_SHARED_RELEASE = FORMAL_RELEASE_ROOT / SHARED_RELEASE_ID
TARGET_SHARED_APP = TARGET_SHARED_RELEASE / "app"
TARGET_SHARED_PACKAGE = TARGET_SHARED_APP / "upstreams/v3_shared_data"
TARGET_SHARED_MANIFEST = TARGET_SHARED_RELEASE / "release-manifest.json"
INTEGRATION_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_ISSUE30_MAC_20261008/integration/ops/api_release_integration.py"
)
BUILDER_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_ISSUE30_MAC_20261008/integration/ops/build_release_candidate.py"
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_sha(value: object) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_UNAVAILABLE:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_exclusive(path: Path, raw: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def copy_tree(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise SystemExit(f"REFUSE_PREEXISTING_STAGE_TREE:{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=True, copy_function=shutil.copy2)


def main() -> None:
    if STAGE.exists() or not PAIR_RECEIPT.is_file() or not CANARY_APP.is_dir():
        raise SystemExit("REFUSE_EXISTING_STAGE_OR_MISSING_FROZEN_PAIR")
    if STAGING_RECEIPT.exists():
        raise SystemExit("REFUSE_EXISTING_STAGING_RECEIPT")
    sys.path.insert(0, str(BUILDER_PATH.parent))
    api = module_from_path("issue32_api_release_integration", INTEGRATION_PATH)
    builder = module_from_path("issue32_build_release_candidate", BUILDER_PATH)
    pair_receipt = json.loads(PAIR_RECEIPT.read_text(encoding="utf-8"))
    if pair_receipt.get("paired_file_count") != 4 or pair_receipt.get("candidate_after_identities_match") is not True:
        raise SystemExit("FROZEN_FOUR_FILE_PAIR_NOT_READY")

    # Build full inactive copies in E only. Preserve symlinks; they are
    # inventoried and must resolve to the same dependency targets as baseline.
    copy_tree(ACTIVE_SCHEDULER_APP, SCHEDULER_APP)
    copy_tree(ACTIVE_SHARED_PACKAGE, SHARED_PACKAGE)
    scheduler_overlays = []
    shared_overlay = None
    for item in pair_receipt["files"]:
        source = Path(item["candidate_path"])
        raw = source.read_bytes()
        if sha(raw) != item["candidate_after_sha256"] or format(stat.S_IMODE(source.stat().st_mode), "04o") != item["candidate_after_mode"]:
            raise SystemExit(f"FROZEN_AFTER_SHA_CHANGED:{source}")
        if item["owner"] == "actual_pool_scheduler":
            destination = SCHEDULER_APP / item["product_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            scheduler_overlays.append(item)
        elif item["owner"] == "actual_shared_owner":
            destination = SHARED_PACKAGE / item["product_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            shared_overlay = item
            # Keep the scheduler release's packaged copy aligned with the
            # actual shared owner artifact used by the facade canary.
            scheduler_copy = SCHEDULER_APP / "upstreams/v3_shared_data" / item["product_path"]
            scheduler_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, scheduler_copy)
        else:
            raise SystemExit(f"UNKNOWN_FROZEN_OWNER:{item['owner']}")
    if len(scheduler_overlays) != 3 or shared_overlay is None:
        raise SystemExit("EXPECTED_THREE_SCHEDULER_FILES_AND_ONE_SHARED_OWNER_FILE")

    active_scheduler_inventory = api.inventory_tree(ACTIVE_SCHEDULER_APP)
    staged_scheduler_inventory = api.inventory_tree(SCHEDULER_APP)
    canary_inventory = api.inventory_tree(CANARY_APP)
    if staged_scheduler_inventory != canary_inventory:
        raise SystemExit("STAGED_SCHEDULER_APP_DIFFERS_FROM_FULL_FACADE_CANARY")
    active_scheduler_by_path = {row["path"]: row for row in active_scheduler_inventory}
    staged_scheduler_by_path = {row["path"]: row for row in staged_scheduler_inventory}
    scheduler_delta = sorted(
        path for path in set(active_scheduler_by_path) | set(staged_scheduler_by_path)
        if active_scheduler_by_path.get(path) != staged_scheduler_by_path.get(path)
    )
    expected_scheduler_delta = sorted(
        "upstreams/v3_shared_data/" + item["product_path"]
        if item.get("owner") == "actual_shared_owner"
        else item["product_path"]
        for item in pair_receipt["files"]
    )
    if scheduler_delta != expected_scheduler_delta:
        raise SystemExit(f"SCHEDULER_STAGE_DELTA_NOT_EXACT:{scheduler_delta}")

    active_shared_inventory = api.inventory_tree(ACTIVE_SHARED_PACKAGE)
    staged_shared_inventory = api.inventory_tree(SHARED_PACKAGE)
    active_shared_by_path = {row["path"]: row for row in active_shared_inventory}
    staged_shared_by_path = {row["path"]: row for row in staged_shared_inventory}
    shared_delta = sorted(
        path for path in set(active_shared_by_path) | set(staged_shared_by_path)
        if active_shared_by_path.get(path) != staged_shared_by_path.get(path)
    )
    if shared_delta != [shared_overlay["product_path"]]:
        raise SystemExit(f"SHARED_STAGE_DELTA_NOT_EXACT:{shared_delta}")
    if sha((SHARED_PACKAGE / shared_overlay["product_path"]).read_bytes()) != shared_overlay["candidate_after_sha256"]:
        raise SystemExit("SHARED_OWNER_AFTER_SHA_MISMATCH")
    if sha((SCHEDULER_APP / "upstreams/v3_shared_data" / shared_overlay["product_path"]).read_bytes()) != shared_overlay["candidate_after_sha256"]:
        raise SystemExit("SCHEDULER_PACKAGED_SHARED_OWNER_AFTER_SHA_MISMATCH")

    scheduler_inventory_digest = api.inventory_digest(staged_scheduler_inventory)
    shared_inventory_digest = api.inventory_digest(staged_shared_inventory)
    source_release_manifest = json.loads((ACTIVE_SCHEDULER_RELEASE / "release-manifest.json").read_text(encoding="utf-8"))
    source_release_manifest_sha = sha((ACTIVE_SCHEDULER_RELEASE / "release-manifest.json").read_bytes())
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    scheduler_manifest = {
        "schema_version": "v4.release_candidate.v1",
        "generated_at_utc": now,
        "release_id": SCHEDULER_RELEASE_ID,
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "STAGED_IN_E_ONLY_NOT_DEPLOYED",
        "candidate_status": "READY_FOR_INDEPENDENT_REVIEW",
        "source": {
            "base_release_id": source_release_manifest.get("release_id"),
            "base_manifest_path": str(ACTIVE_SCHEDULER_RELEASE / "release-manifest.json"),
            "base_manifest_sha256": source_release_manifest_sha,
            "base_app_root": str(ACTIVE_SCHEDULER_APP),
            "full_tree_source_copied": True,
            "paired_source_candidate_manifest_sha256": pair_receipt["candidate_manifest_sha256"],
            "paired_delta_count": 4,
            "active_service_mutated": False,
        },
        "candidate": {
            "formal_release_root": str(FORMAL_RELEASE_ROOT),
            "target_root": str(TARGET_SCHEDULER_RELEASE),
            "app_root": str(TARGET_SCHEDULER_APP),
            "release_id": SCHEDULER_RELEASE_ID,
            "manifest_path": str(TARGET_SCHEDULER_MANIFEST),
            "staging_app_root": str(SCHEDULER_APP),
            "target_write_performed": False,
            "data_copy_performed": False,
        },
        "application_inventory": {
            "entry_count": len(staged_scheduler_inventory),
            "aggregate_sha256": scheduler_inventory_digest,
            "entries": staged_scheduler_inventory,
        },
        "paired_shared_owner": {
            "release_id": SHARED_RELEASE_ID,
            "target_root": str(TARGET_SHARED_RELEASE),
            "app_root": str(TARGET_SHARED_APP),
            "package_root": str(TARGET_SHARED_PACKAGE),
            "manifest_path": str(TARGET_SHARED_MANIFEST),
            "inventory_entry_count": len(staged_shared_inventory),
            "inventory_sha256": shared_inventory_digest,
            "owner_file_sha256": shared_overlay["candidate_after_sha256"],
        },
        "overlay": {
            "scheduler_app_changed_paths": scheduler_delta,
            "shared_owner_changed_paths": shared_delta,
            "paired_file_count": 4,
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "verification": {
            "candidate_full_app_matches_facade_canary": True,
            "scheduler_full_tree_delta_exact": True,
            "shared_full_tree_delta_exact": True,
            "symlink_inventory_preserved": True,
            "paired_owner_artifact_sha_equal_in_both_trees": True,
            "formal_release_copied": False,
            "launchctl_called": False,
        },
    }
    scheduler_manifest_raw = (json.dumps(scheduler_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    scheduler_manifest_sha = sha(scheduler_manifest_raw)
    write_exclusive(SCHEDULER_STAGE / "release-manifest.json", scheduler_manifest_raw)

    shared_manifest = {
        "schema_version": "v4.issue32.shared_owner_release.v1",
        "generated_at_utc": now,
        "release_id": SHARED_RELEASE_ID,
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "STAGED_IN_E_ONLY_NOT_DEPLOYED",
        "candidate_status": "READY_FOR_INDEPENDENT_REVIEW",
        "source": {
            "base_owner_root": str(ACTIVE_SHARED_PACKAGE),
            "paired_source_candidate_manifest_sha256": pair_receipt["candidate_manifest_sha256"],
            "shared_owner_delta_count": 1,
            "active_owner_mutated": False,
        },
        "candidate": {
            "formal_release_root": str(FORMAL_RELEASE_ROOT),
            "target_root": str(TARGET_SHARED_RELEASE),
            "app_root": str(TARGET_SHARED_APP),
            "package_root": str(TARGET_SHARED_PACKAGE),
            "release_id": SHARED_RELEASE_ID,
            "manifest_path": str(TARGET_SHARED_MANIFEST),
            "target_write_performed": False,
        },
        "application_inventory": {
            "entry_count": len(staged_shared_inventory),
            "aggregate_sha256": shared_inventory_digest,
            "entries": staged_shared_inventory,
        },
        "paired_scheduler_release": {
            "release_id": SCHEDULER_RELEASE_ID,
            "manifest_path": str(TARGET_SCHEDULER_MANIFEST),
            "manifest_sha256": scheduler_manifest_sha,
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    shared_manifest_raw = (json.dumps(shared_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    shared_manifest_sha = sha(shared_manifest_raw)
    write_exclusive(SHARED_STAGE / "release-manifest.json", shared_manifest_raw)

    # Use the established scheduler identity renderer, then bind its local
    # staged paths to the formal target paths that the controller may publish.
    helper_receipt = builder._stage_scheduler_identity(
        source_plist=SCHEDULER_PLIST,
        candidate_root=SCHEDULER_STAGE,
        release_id=SCHEDULER_RELEASE_ID,
        manifest_path=TARGET_SCHEDULER_MANIFEST,
        manifest_sha256=scheduler_manifest_sha,
    )
    staged_plist = plistlib.loads(CONFIG.read_bytes())
    env = staged_plist.get("EnvironmentVariables")
    if not isinstance(env, dict):
        raise SystemExit("STAGED_SCHEDULER_PLIST_ENV_INVALID")
    env["V35_APP_ROOT"] = str(TARGET_SCHEDULER_APP)
    env["V35_RELEASE_ID"] = SCHEDULER_RELEASE_ID
    env["V35_RELEASE_MANIFEST_PATH"] = str(TARGET_SCHEDULER_MANIFEST)
    env["V35_RELEASE_MANIFEST_SHA256"] = scheduler_manifest_sha
    env["V35_SHARED_PACKAGE_ROOT"] = str(TARGET_SHARED_PACKAGE)
    env["PYTHONPATH"] = str(TARGET_SCHEDULER_APP / "upstreams") + ":" + str(TARGET_SCHEDULER_APP)
    staged_plist["ProgramArguments"] = ["/bin/bash", str(TARGET_SCHEDULER_APP / "ops/launch_v35_macos_scheduler.sh")]
    staged_plist["WorkingDirectory"] = str(TARGET_SCHEDULER_APP)
    final_plist_raw = plistlib.dumps(staged_plist, fmt=plistlib.FMT_XML, sort_keys=True)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_bytes(final_plist_raw)
    final_plist = plistlib.loads(CONFIG.read_bytes())
    final_env = final_plist["EnvironmentVariables"]
    if any(old in str(final_env.get("PYTHONPATH", "")) for old in (
        "20260929-manager-1555-pytdx-r1", "20260908-full-repair-a-content-isolation"
    )):
        raise SystemExit("STAGED_PYTHONPATH_RETAINS_OLD_ROOT")
    if final_env.get("V35_RELEASE_ID") != SCHEDULER_RELEASE_ID or final_env.get("V35_RELEASE_MANIFEST_SHA256") != scheduler_manifest_sha:
        raise SystemExit("STAGED_RELEASE_IDENTITY_MISMATCH")
    if final_env.get("V35_SHARED_PACKAGE_ROOT") != str(TARGET_SHARED_PACKAGE):
        raise SystemExit("STAGED_SHARED_ROOT_MISMATCH")

    pair_manifest = {
        "schema_version": "v4.issue32.scheduler_shared_staged_pair.v1",
        "status": "STAGED_IN_E_ONLY_READY_FOR_INDEPENDENT_REVIEW",
        "candidate_id": STAGE.name,
        "target_date": "20261009",
        "signal_date": "20261008",
        "scheduler_release": {
            "release_id": SCHEDULER_RELEASE_ID,
            "staging_root": str(SCHEDULER_STAGE),
            "target_root": str(TARGET_SCHEDULER_RELEASE),
            "app_root": str(TARGET_SCHEDULER_APP),
            "manifest_path": str(TARGET_SCHEDULER_MANIFEST),
            "manifest_sha256": scheduler_manifest_sha,
            "application_inventory_sha256": scheduler_inventory_digest,
            "application_inventory_entry_count": len(staged_scheduler_inventory),
        },
        "shared_owner_release": {
            "release_id": SHARED_RELEASE_ID,
            "staging_root": str(SHARED_STAGE),
            "target_root": str(TARGET_SHARED_RELEASE),
            "package_root": str(TARGET_SHARED_PACKAGE),
            "manifest_path": str(TARGET_SHARED_MANIFEST),
            "manifest_sha256": shared_manifest_sha,
            "application_inventory_sha256": shared_inventory_digest,
            "application_inventory_entry_count": len(staged_shared_inventory),
        },
        "staged_scheduler_plist": {
            "path": str(CONFIG),
            "sha256": sha(final_plist_raw),
            "activation_status": "NOT_ACTIVATED",
            "launchctl_called": False,
            "render_helper": str(BUILDER_PATH),
            "render_helper_function": "_stage_scheduler_identity",
            "render_helper_result": helper_receipt,
            "bindings": {
                "Label": final_plist.get("Label"),
                "V35_APP_ROOT": final_env.get("V35_APP_ROOT"),
                "V35_RELEASE_ID": final_env.get("V35_RELEASE_ID"),
                "V35_RELEASE_MANIFEST_PATH": final_env.get("V35_RELEASE_MANIFEST_PATH"),
                "V35_RELEASE_MANIFEST_SHA256": final_env.get("V35_RELEASE_MANIFEST_SHA256"),
                "V35_SHARED_PACKAGE_ROOT": final_env.get("V35_SHARED_PACKAGE_ROOT"),
                "PYTHONPATH": final_env.get("PYTHONPATH"),
                "ProgramArguments": final_plist.get("ProgramArguments"),
                "WorkingDirectory": final_plist.get("WorkingDirectory"),
            },
            "old_pythonpath_roots_removed": True,
        },
        "scheduler_app_changed_paths": scheduler_delta,
        "shared_owner_changed_paths": shared_delta,
        "four_file_product_delta": pair_receipt["files"],
        "source_scheduler_plist_sha256": sha(SCHEDULER_PLIST.read_bytes()),
        "source_scheduler_release_manifest_sha256": source_release_manifest_sha,
        "launchctl_called": False,
        "formal_release_written": False,
        "service_mutated": False,
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }
    pair_manifest_raw = (json.dumps(pair_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    write_exclusive(STAGE / "release-pair-manifest.json", pair_manifest_raw)
    receipt = {
        "status": "FULL_PAIRED_RELEASE_STAGED_IN_E_ONLY",
        "stage_root": str(STAGE),
        "release_pair_manifest_path": str(STAGE / "release-pair-manifest.json"),
        "release_pair_manifest_sha256": sha(pair_manifest_raw),
        "scheduler_release_id": SCHEDULER_RELEASE_ID,
        "scheduler_manifest_path_staged": str(SCHEDULER_STAGE / "release-manifest.json"),
        "scheduler_manifest_path_runtime": str(TARGET_SCHEDULER_MANIFEST),
        "scheduler_manifest_sha256": scheduler_manifest_sha,
        "scheduler_app_inventory_sha256": scheduler_inventory_digest,
        "scheduler_app_inventory_entry_count": len(staged_scheduler_inventory),
        "shared_release_id": SHARED_RELEASE_ID,
        "shared_manifest_path_staged": str(SHARED_STAGE / "release-manifest.json"),
        "shared_manifest_path_runtime": str(TARGET_SHARED_MANIFEST),
        "shared_manifest_sha256": shared_manifest_sha,
        "shared_package_inventory_sha256": shared_inventory_digest,
        "shared_package_inventory_entry_count": len(staged_shared_inventory),
        "scheduler_plist_stage_path": str(CONFIG),
        "scheduler_plist_sha256": sha(final_plist_raw),
        "scheduler_plist_preimage_sha256": sha(SCHEDULER_PLIST.read_bytes()),
        "scheduler_app_changed_paths": scheduler_delta,
        "shared_owner_changed_paths": shared_delta,
        "canary_app_inventory_sha256": api.inventory_digest(canary_inventory),
        "scheduler_stage_matches_canary": True,
        "shared_owner_active_delta_exact": True,
        "old_pythonpath_roots_removed": True,
        "activation_status": "NOT_ACTIVATED",
        "formal_release_written": False,
        "launchctl_called": False,
        "service_mutated": False,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    receipt_raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    write_exclusive(STAGING_RECEIPT, receipt_raw)
    print(json.dumps({"receipt_path": str(STAGING_RECEIPT), "receipt_sha256": sha(receipt_raw), **receipt}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
