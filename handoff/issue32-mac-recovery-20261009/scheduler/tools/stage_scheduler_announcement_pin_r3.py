from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


BASE = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009")
R2_PLIST = BASE / "candidate/issue32_scheduler_shared_pair_r1/staged_pair_r2/scheduler/config/com.lexi.v35.scheduler.plist"
R3_PLIST = BASE / "candidate/issue32_scheduler_shared_pair_r1/staged_pair_r3/scheduler/config/com.lexi.v35.scheduler.plist"
ACTIVE_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
STAGE_RECEIPT = BASE / "writer/scheduler_shared_pair_staging_r2.json"
PAIR_DELTA = BASE / "writer/scheduler_shared_pair_candidate_r1.json"
FORMAL_RELEASES = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases")
EXPECTED_ACTIVE_PLIST_SHA = "c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2"
EXPECTED_R2_PLIST_SHA = "9c395256d7d67a1dd58ba063ada56a13442d19b64fdd3d36aee8344737fa3875"
EXPECTED_BINDING_SHA = "c0fbff52449eb5dbf5c1655f17cf08915bea1214f9499cc8a4df1176d9625951"
ANNOUNCEMENT_PINS = (
    "V4_MANAGER_ANNOUNCEMENT_APP_ROOT",
    "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256",
    "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256",
)
DAEMON_MODULE_RELATIVE = Path("ops/run_v35_macos_scheduler_daemon.py")
CYCLE_RELATIVE = "ops/run_manager_announcement_cycle.py"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(data, encoding="utf-8")


def main() -> int:
    if not R2_PLIST.is_file() or not ACTIVE_PLIST.is_file():
        raise RuntimeError("EXPECTED_PLIST_INPUT_MISSING")
    if R3_PLIST.exists():
        raise RuntimeError(f"R3_PLIST_ALREADY_EXISTS:{R3_PLIST}")

    active_bytes = ACTIVE_PLIST.read_bytes()
    r2_bytes = R2_PLIST.read_bytes()
    active_sha = sha_bytes(active_bytes)
    r2_sha = sha_bytes(r2_bytes)
    if active_sha != EXPECTED_ACTIVE_PLIST_SHA:
        raise RuntimeError(f"ACTIVE_PLIST_SHA_DRIFT:{active_sha}")
    if r2_sha != EXPECTED_R2_PLIST_SHA:
        raise RuntimeError(f"R2_PLIST_SHA_DRIFT:{r2_sha}")

    active = plistlib.loads(active_bytes)
    r2 = plistlib.loads(r2_bytes)
    active_env = active.get("EnvironmentVariables", {})
    r2_env = r2.get("EnvironmentVariables", {})
    if active.get("Label") != "com.lexi.v35.scheduler" or r2.get("Label") != "com.lexi.v35.scheduler":
        raise RuntimeError("SCHEDULER_LABEL_MISMATCH")
    old_pin_values = {key: active_env.get(key) for key in ANNOUNCEMENT_PINS}
    r2_pin_values = {key: r2_env.get(key) for key in ANNOUNCEMENT_PINS}
    if old_pin_values != r2_pin_values:
        raise RuntimeError("OLD_AND_R2_ANNOUNCEMENT_PINS_DIFFER")

    binding_path = Path(r2_env["V4_MANAGER_ANNOUNCEMENT_BINDING"])
    binding_bytes = binding_path.read_bytes()
    binding_sha = sha_bytes(binding_bytes)
    if binding_sha != EXPECTED_BINDING_SHA:
        raise RuntimeError(f"ANNOUNCEMENT_BINDING_SHA_DRIFT:{binding_sha}")
    binding = json.loads(binding_bytes)
    owner_root = Path(binding["app_root"])
    if not owner_root.is_dir() or owner_root.resolve(strict=True) != owner_root:
        raise RuntimeError("ANNOUNCEMENT_OWNER_ROOT_INVALID")
    cycle_sha = binding.get("files", {}).get(CYCLE_RELATIVE)
    cycle_path = owner_root / CYCLE_RELATIVE
    if not isinstance(cycle_sha, str) or sha_file(cycle_path) != cycle_sha:
        raise RuntimeError("BOUND_ANNOUNCEMENT_CYCLE_SHA_MISMATCH")

    plan_ref = binding.get("plan_activation_receipt")
    if not isinstance(plan_ref, dict) or not isinstance(plan_ref.get("path"), str):
        raise RuntimeError("BOUND_PLAN_CANARY_REFERENCE_MISSING")
    canary_path = Path(plan_ref["path"])
    canary_bytes = canary_path.read_bytes()
    canary_sha = sha_bytes(canary_bytes)
    if canary_sha != plan_ref.get("sha256"):
        raise RuntimeError("BOUND_PLAN_CANARY_SHA_MISMATCH")
    canary = json.loads(canary_bytes)
    if canary.get("app_root") != str(owner_root) or canary.get("candidate_binding_app_root") != str(owner_root):
        raise RuntimeError("BOUND_PLAN_CANARY_OWNER_MISMATCH")

    python_path = Path(r2_env["V4_MANAGER_ANNOUNCEMENT_PYTHON"])
    python_resolved = python_path.resolve(strict=True)
    python_sha = sha_file(python_resolved)
    if python_sha != r2_env["V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256"]:
        raise RuntimeError("ANNOUNCEMENT_PYTHON_SHA_MISMATCH")
    if binding.get("python") != r2_env["V4_MANAGER_ANNOUNCEMENT_PYTHON"]:
        raise RuntimeError("BINDING_PYTHON_PATH_MISMATCH")
    if binding.get("python_sha256") != python_sha or binding.get("python_resolved") != str(python_resolved):
        raise RuntimeError("BINDING_PYTHON_IDENTITY_MISMATCH")

    stage_receipt = json.loads(STAGE_RECEIPT.read_text(encoding="utf-8"))
    scheduler_release_id = stage_receipt["scheduler_release_id"]
    scheduler_root = FORMAL_RELEASES / scheduler_release_id / "app"
    manifest_path = Path(r2_env["V35_RELEASE_MANIFEST_PATH"])
    if not scheduler_root.is_dir() or not manifest_path.is_file():
        raise RuntimeError("FROZEN_FORMAL_R1_RELEASE_MISSING")
    manifest_sha = sha_file(manifest_path)
    if manifest_sha != r2_env["V35_RELEASE_MANIFEST_SHA256"]:
        raise RuntimeError("FROZEN_FORMAL_R1_MANIFEST_SHA_MISMATCH")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release_id") != scheduler_release_id:
        raise RuntimeError("FROZEN_FORMAL_R1_RELEASE_ID_MISMATCH")

    pair_delta = json.loads(PAIR_DELTA.read_text(encoding="utf-8"))
    verified_business_files: list[dict[str, str]] = []
    shared_root = Path(r2_env["V35_SHARED_PACKAGE_ROOT"])
    for item in pair_delta["files"]:
        root = scheduler_root if item["owner"] == "actual_pool_scheduler" else shared_root
        product_path = root / item["product_path"]
        digest = sha_file(product_path)
        if digest != item["candidate_after_sha256"]:
            raise RuntimeError(f"FROZEN_PRODUCT_SHA_MISMATCH:{item['product_path']}:{digest}")
        verified_business_files.append({"path": item["product_path"], "sha256": digest, "owner": item["owner"]})

    new_values = {
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": str(owner_root),
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": cycle_sha,
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": canary_sha,
    }
    new_plist = copy.deepcopy(r2)
    new_env = new_plist["EnvironmentVariables"]
    new_env.update(new_values)
    changed_env_keys = sorted(key for key in r2_env if r2_env.get(key) != new_env.get(key))
    if changed_env_keys != sorted(ANNOUNCEMENT_PINS):
        raise RuntimeError(f"UNEXPECTED_ENVIRONMENT_CHANGES:{changed_env_keys}")
    if {key: value for key, value in r2.items() if key != "EnvironmentVariables"} != {
        key: value for key, value in new_plist.items() if key != "EnvironmentVariables"
    }:
        raise RuntimeError("UNEXPECTED_PLIST_TOP_LEVEL_CHANGE")

    R3_PLIST.parent.mkdir(parents=True, exist_ok=True)
    output = plistlib.dumps(new_plist, fmt=plistlib.FMT_XML, sort_keys=False)
    mode = stat.S_IMODE(R2_PLIST.stat().st_mode)
    fd, temp_name = tempfile.mkstemp(prefix=".scheduler-plist-r3-", dir=R3_PLIST.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, R3_PLIST)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    plutil = shutil.which("plutil")
    if not plutil:
        raise RuntimeError("PLUTIL_UNAVAILABLE")
    lint = subprocess.run([plutil, "-lint", str(R3_PLIST)], capture_output=True, text=True, check=False)
    if lint.returncode != 0:
        raise RuntimeError(f"PLUTIL_LINT_FAILED:{lint.stderr.strip()}")

    source_app = R2_PLIST.parents[1] / "app"
    daemon_source = source_app / DAEMON_MODULE_RELATIVE
    daemon_target = scheduler_root / DAEMON_MODULE_RELATIVE
    if sha_file(daemon_source) != sha_file(daemon_target):
        raise RuntimeError("DAEMON_MODULE_SHA_DIFFERS_FROM_FROZEN_R2_STAGE")
    daemon_module_sha = sha_file(daemon_target)

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(scheduler_root))
    daemon = importlib.import_module("ops.run_v35_macos_scheduler_daemon")
    imported_daemon = Path(daemon.__file__).resolve(strict=True)
    if imported_daemon != daemon_target.resolve(strict=True) or sha_file(imported_daemon) != daemon_module_sha:
        raise RuntimeError("IMPORTED_DAEMON_MODULE_IDENTITY_MISMATCH")

    prior_environment = dict(os.environ)
    os.environ.update({key: str(value) for key, value in new_env.items()})
    popen_calls: list[str] = []

    def forbidden_popen(*args: Any, **kwargs: Any) -> Any:
        popen_calls.append("called")
        raise RuntimeError("UNEXPECTED_ANNOUNCEMENT_CHILD_PROCESS")

    try:
        hook = daemon.AnnouncementCycleHook.from_environment(start=False, popen_factory=forbidden_popen)
    finally:
        os.environ.clear()
        os.environ.update(prior_environment)
    if hook is None:
        raise RuntimeError("ANNOUNCEMENT_HOOK_NOT_CONSTRUCTED")
    if hook.thread.is_alive() or hook.thread.ident is not None:
        raise RuntimeError("ANNOUNCEMENT_THREAD_STARTED_DESPITE_START_FALSE")
    if popen_calls:
        raise RuntimeError("ANNOUNCEMENT_CHILD_PROCESS_WAS_STARTED")
    identity = hook.identity
    if identity["binding_sha256"] != binding_sha or identity["app_root"] != owner_root:
        raise RuntimeError("CONSTRUCTED_HOOK_IDENTITY_MISMATCH")
    if identity["cycle_path"] != cycle_path or identity["cycle_sha256"] != cycle_sha:
        raise RuntimeError("CONSTRUCTED_HOOK_CYCLE_IDENTITY_MISMATCH")

    receipt = {
        "schema_version": "v4.issue32.scheduler_announcement_pin_canary.v1",
        "status": "PASS_ANNOUNCEMENT_OWNER_PIN_AND_CONSTRUCTOR_START_FALSE",
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        "old_active_plist_sha256": active_sha,
        "r2_staged_plist_sha256": r2_sha,
        "old_and_r2_announcement_pins_identical": True,
        "preexisting_pin_mismatch": {
            "binding_app_root": binding["app_root"],
            "old_configured_app_root": old_pin_values["V4_MANAGER_ANNOUNCEMENT_APP_ROOT"],
            "old_configured_cycle_sha256": old_pin_values["V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256"],
            "binding_cycle_sha256": cycle_sha,
            "old_configured_plan_canary_sha256": old_pin_values["V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256"],
            "binding_plan_canary_sha256": canary_sha,
            "classification": "same old pin set in restored active plist and r2 candidate; this is inherited configuration mismatch, not established as introduced by issue32",
        },
        "r3_plist_path": str(R3_PLIST),
        "r3_plist_sha256": sha_file(R3_PLIST),
        "r3_plist_mode": oct(stat.S_IMODE(R3_PLIST.stat().st_mode)),
        "r3_changed_environment_keys": changed_env_keys,
        "r3_announcement_pins": new_values,
        "binding_path": str(binding_path),
        "binding_sha256": binding_sha,
        "binding_owner_root": str(owner_root),
        "binding_cycle_file_sha256": cycle_sha,
        "binding_plan_receipt_path": str(canary_path),
        "binding_plan_receipt_sha256": canary_sha,
        "announcement_python_resolved": str(python_resolved),
        "announcement_python_sha256": python_sha,
        "frozen_scheduler_release_id": scheduler_release_id,
        "frozen_scheduler_manifest_sha256": manifest_sha,
        "daemon_module_path": str(imported_daemon),
        "daemon_module_sha256": daemon_module_sha,
        "constructor": "AnnouncementCycleHook.from_environment(start=False)",
        "constructor_returned_hook": True,
        "hook_thread_started": False,
        "announcement_child_process_count": len(popen_calls),
        "verified_frozen_product_files": verified_business_files,
        "plutil_lint_stdout": lint.stdout.strip(),
        "launchctl_called": False,
        "live_service_touched": False,
        "formal_release_roots_modified": False,
        "natural_slot_verified": False,
        "stage_result_verified": False,
    }
    receipt_path = BASE / "evidence/scheduler_announcement_pin_canary_issue32_r3.json"
    write_json(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    receipt["receipt_sha256"] = sha_file(receipt_path)

    plan = {
        "schema_version": "v4.issue32.scheduler_shared_pair_cutover_plan.v3",
        "status": "R3_ANNOUNCEMENT_PINS_VALIDATED_READY_FOR_REVIEW_NO_SWITCH",
        "scope": "E-local LaunchAgent plist correction only. Reuses the frozen formal r1 scheduler/shared-owner release roots; no product source or live service changes.",
        "rollback_observation": {
            "publish_receipt": str(BASE / "evidence/scheduler_pair_publish_receipt.json"),
            "rollback_receipt": str(BASE / "evidence/scheduler_pair_rollback_announcement_pin.json"),
            "restored_old_plist_sha256": EXPECTED_ACTIVE_PLIST_SHA,
            "old_scheduler_pid_reported_by_controller": 82246,
            "api_changed": False,
        },
        "root_cause_classification": "The restored active plist and r2 staged plist carry the same stale announcement pin values. The current external binding names the manager-us-mapping-daily-20261006-r2 owner root and its own cycle/plan receipt SHAs. The prior startup error is therefore not established as introduced by Issue32.",
        "announcement_pin_source": {
            "binding_path": str(binding_path),
            "binding_sha256": binding_sha,
            "owner_root": str(owner_root),
            "cycle_path": str(cycle_path),
            "cycle_sha256": cycle_sha,
            "plan_receipt_path": str(canary_path),
            "plan_receipt_sha256": canary_sha,
            "python_path": str(python_path),
            "python_sha256": python_sha,
        },
        "frozen_formal_release": {
            "scheduler_release_id": scheduler_release_id,
            "scheduler_app_root": str(scheduler_root),
            "scheduler_manifest_sha256": manifest_sha,
            "shared_package_root": str(shared_root),
            "business_source_sha_checks": verified_business_files,
            "roots_rebuilt_or_modified": False,
        },
        "candidate_plist": {
            "source_r2_path": str(R2_PLIST),
            "source_r2_sha256": r2_sha,
            "new_r3_path": str(R3_PLIST),
            "new_r3_sha256": receipt["r3_plist_sha256"],
            "changed_environment_keys": changed_env_keys,
            "only_announcement_configuration_changed": True,
        },
        "behavior_verification": {
            "receipt_path": str(receipt_path),
            "receipt_sha256": receipt["receipt_sha256"],
            "status": receipt["status"],
            "loaded_module_path": str(imported_daemon),
            "loaded_module_sha256": daemon_module_sha,
            "constructor": "AnnouncementCycleHook.from_environment(start=False)",
            "thread_started": False,
            "child_process_count": 0,
        },
        "not_performed": ["plist replacement", "launchctl", "service restart", "real Stage run", "natural-slot verification"],
        "remaining_cannot_confirm": ["genuine exact-date HK security master for 20261008", "selector-ready panel for isolated 20261009 candidate", "natural Stage behavior after controller-owned future switch"],
        "safety": {"research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    plan_path = BASE / "plan/scheduler_shared_pair_issue32_r3.json"
    if plan_path.exists():
        raise RuntimeError(f"R3_PLAN_ALREADY_EXISTS:{plan_path}")
    write_json(plan_path, plan)
    print(json.dumps({"status": receipt["status"], "r3_plist": str(R3_PLIST), "r3_plist_sha256": receipt["r3_plist_sha256"], "receipt": str(receipt_path), "receipt_sha256": receipt["receipt_sha256"], "plan": str(plan_path), "binding_sha256": binding_sha, "owner_root": str(owner_root), "cycle_sha256": cycle_sha, "plan_canary_sha256": canary_sha, "daemon_module_sha256": daemon_module_sha, "verified_product_file_count": len(verified_business_files)}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
