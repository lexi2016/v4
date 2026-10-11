#!/usr/bin/env python3
"""Prepare final-root binding and LaunchAgent plist copies; never activate.

Default mode is read-only and reports the exact inputs and staged delta. The
explicit ``--stage-enabled`` mode requires a validated next-session canary and
writes only immutable files below this task's ``staged_config`` directory.
"""
from __future__ import annotations

import argparse
import copy
import json
import plistlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import daily_chain_activation_common as common


MAX_CANARY_AGE = timedelta(minutes=60)
HONG_KONG_TZ = ZoneInfo("Asia/Hong_Kong")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def _pythonpath_for_final(current: str, active_root: Path, final_root: Path) -> str:
    parts = current.split(":")
    if not parts or str(active_root) not in parts:
        raise ValueError("API_PYTHONPATH_ACTIVE_ROOT_MISSING")
    if str(active_root / "upstreams") not in parts:
        raise ValueError("API_PYTHONPATH_ACTIVE_UPSTREAMS_MISSING")
    if active_root == final_root:
        if (parts.count(str(final_root)) != 1
                or parts.count(str(final_root / "upstreams")) != 1):
            raise ValueError("API_PYTHONPATH_FINAL_ROOT_INVALID")
        return current
    rewritten = [str(final_root / "upstreams") if item == str(active_root / "upstreams")
                 else str(final_root) if item == str(active_root) else item for item in parts]
    if (rewritten.count(str(final_root)) != 1
            or rewritten.count(str(final_root / "upstreams")) != 1
            or str(active_root) in rewritten or str(active_root / "upstreams") in rewritten):
        raise ValueError("API_PYTHONPATH_FINAL_ROOT_INVALID")
    return ":".join(rewritten)


def _stage_plists(identity: dict[str, Any], output_dir: Path,
                  canary_path: Path, canary_sha: str) -> dict[str, Any]:
    release = identity["release"]
    app_root = release["app_root"]
    live = identity["live"]
    api = copy.deepcopy(live["api"])
    scheduler = copy.deepcopy(live["scheduler"])
    api_env = live["api_env"]
    scheduler_env = live["scheduler_env"]
    if identity["state_root"] != Path(api_env.get("V4_MANAGER_RESEARCH_STATE_ROOT", "")):
        raise ValueError("API_MANAGER_STATE_ROOT_CHANGED")
    if identity["state_root"] != Path(scheduler_env.get("V4_MANAGER_RESEARCH_STATE_ROOT", "")):
        raise ValueError("SCHEDULER_MANAGER_STATE_ROOT_CHANGED")
    if (identity["api_binding"].get("manager_state_root") != str(identity["state_root"])
            or identity["scheduler_binding"].get("manager_state_root") != str(identity["state_root"])):
        raise ValueError("API_SCHEDULER_MANAGER_STATE_ROOT_MISMATCH")

    release_id = str(release["manifest"]["candidate"]["release_id"])
    api_binding_path = output_dir / "manager-plan-binding.json"
    api_updates = {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": release_id,
        "V35_RELEASE_MANIFEST_PATH": str(release["manifest_path"]),
        "V35_RELEASE_MANIFEST_SHA256": release["manifest_sha256"],
        "PYTHONPATH": _pythonpath_for_final(api_env.get("PYTHONPATH", ""),
                                            identity["active_api_app_root"], app_root),
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(api_binding_path),
    }
    for key, value in api_updates.items():
        common.replace_environment(api, key, value)
    api["WorkingDirectory"] = str(app_root)

    cycle_path = app_root / "ops/run_manager_announcement_cycle.py"
    cycle_sha = common.sha256_bytes(common.exact_file(cycle_path, "FINAL_CYCLE_SCRIPT_MISSING"))
    scheduler_updates = {
        "V4_MANAGER_ANNOUNCEMENT_APP_ROOT": str(app_root),
        "V4_MANAGER_ANNOUNCEMENT_BINDING": str(api_binding_path),
        "V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256": cycle_sha,
        "V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256": canary_sha,
    }
    for key, value in scheduler_updates.items():
        common.replace_environment(scheduler, key, value)

    api_env_after = common.env_from_plist(api)
    scheduler_env_after = common.env_from_plist(scheduler)
    api_changed_keys = sorted(key for key in set(api_env) | set(api_env_after)
                              if api_env.get(key) != api_env_after.get(key))
    scheduler_changed_keys = sorted(key for key in set(scheduler_env) | set(scheduler_env_after)
                                    if scheduler_env.get(key) != scheduler_env_after.get(key))
    api_expected_changed_keys = sorted(
        key for key, value in api_updates.items() if api_env.get(key) != value)
    scheduler_expected_changed_keys = sorted(
        key for key, value in scheduler_updates.items() if scheduler_env.get(key) != value)
    if api_changed_keys != api_expected_changed_keys:
        raise ValueError("STAGED_API_ENV_DELTA_OUT_OF_SCOPE")
    if scheduler_changed_keys != scheduler_expected_changed_keys:
        raise ValueError("STAGED_SCHEDULER_ENV_DELTA_OUT_OF_SCOPE")
    if (scheduler.get("WorkingDirectory") != live["scheduler"].get("WorkingDirectory")
            or scheduler.get("ProgramArguments") != live["scheduler"].get("ProgramArguments")
            or scheduler_env_after.get("V35_APP_ROOT") != scheduler_env.get("V35_APP_ROOT")):
        raise ValueError("STAGED_SCHEDULER_HK_ROOT_OR_TASK_CHANGED")
    if (api_env_after.get("V35_APP_ROOT") != str(app_root)
            or api.get("WorkingDirectory") != str(app_root)
            or api_env_after.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(api_binding_path)
            or scheduler_env_after.get("V4_MANAGER_ANNOUNCEMENT_BINDING") != str(api_binding_path)
            or scheduler_env_after.get("V4_MANAGER_ANNOUNCEMENT_APP_ROOT") != str(app_root)
            or api_env_after.get("V4_MANAGER_RESEARCH_STATE_ROOT")
            != scheduler_env_after.get("V4_MANAGER_RESEARCH_STATE_ROOT")):
        raise ValueError("STAGED_API_SCHEDULER_IDENTITY_MISMATCH")
    return {
        "api_plist": api,
        "scheduler_plist": scheduler,
        "api_updates": api_updates,
        "scheduler_updates": scheduler_updates,
        "api_changed_environment_keys": api_changed_keys,
        "api_expected_changed_environment_keys": api_expected_changed_keys,
        "scheduler_changed_environment_keys": scheduler_changed_keys,
        "scheduler_expected_changed_environment_keys": scheduler_expected_changed_keys,
        "scheduler_hk_root_and_task_preserved": True,
        "cycle_sha256": cycle_sha,
        "binding_path": api_binding_path,
        "canary_path": canary_path,
        "canary_sha256": canary_sha,
    }


def _validate_canary(path: Path, release: dict[str, Any], state_root: Path,
                     target: str, *, now: datetime | None = None
                     ) -> tuple[dict[str, Any], str, dict[str, Any]]:
    raw = common.exact_file(path, "FRESH_CANARY_MISSING")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("FRESH_CANARY_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError("FRESH_CANARY_INVALID")
    app_root = release["app_root"]
    expected = {
        "schema_version": common.CANARY_SCHEMA,
        "status": common.CANARY_STATUS,
        "app_root": str(app_root),
        "manager_state_root": str(state_root),
        "scope": common.CANARY_NEXT_SCOPE,
        "target_trade_date": target,
        "plan_material_refresh_only": True,
        "candidate_binding_app_root": str(app_root),
        "owner_execution_app_root": str(app_root),
        "owner_source_inventory_sha256": release["owner_inventory_sha256"],
        "candidate_release_manifest_sha256": release["manifest_sha256"],
        "candidate_application_inventory_sha256": release["application_inventory_sha256"],
        "candidate_manager_source_inventory_sha256": common.canonical_sha(release["binding_files"]),
        "execution_mode": common.EXECUTION_MODE,
        "hook_executed": False,
        "announcement_collection_enabled": False,
        "announcement_network_requests": 0,
        "research_only": True,
        **common.SAFETY,
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise ValueError("FRESH_CANARY_IDENTITY_MISMATCH:" + key)
    if value.get("readback_view") != "auto (route default)":
        raise ValueError("FRESH_CANARY_READBACK_VIEW_INVALID")
    clock_text = value.get("current_clock_local")
    if not isinstance(clock_text, str):
        raise ValueError("FRESH_CANARY_CLOCK_MISSING")
    try:
        clock = datetime.fromisoformat(clock_text)
    except ValueError as exc:
        raise ValueError("FRESH_CANARY_CLOCK_INVALID") from exc
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("FRESH_CANARY_CLOCK_NOT_LOCALIZED")
    current = now or datetime.now(HONG_KONG_TZ)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("CURRENT_CLOCK_NOT_LOCALIZED")
    clock_hk = clock.astimezone(HONG_KONG_TZ)
    current_hk = current.astimezone(HONG_KONG_TZ)
    age_seconds = (current_hk - clock_hk).total_seconds()
    if age_seconds < 0:
        raise ValueError("FRESH_CANARY_CLOCK_IN_FUTURE")
    if age_seconds > MAX_CANARY_AGE.total_seconds():
        raise ValueError("FRESH_CANARY_STALE_MAX_AGE_60_MINUTES")
    try:
        canary_next_session = common.next_hk_session(app_root, clock_hk)
        current_next_session = common.next_hk_session(app_root, current_hk)
    except (OSError, ValueError) as exc:
        raise ValueError("FRESH_CANARY_NEXT_HK_SESSION_UNAVAILABLE") from exc
    if target != canary_next_session:
        raise ValueError("FRESH_CANARY_TARGET_NOT_NEXT_HK_SESSION_AT_CANARY_CLOCK")
    if target != current_next_session:
        raise ValueError("FRESH_CANARY_TARGET_NOT_NEXT_HK_SESSION_AT_CURRENT_CLOCK")
    freshness = {
        "max_age_minutes": 60,
        "age_seconds": age_seconds,
        "canary_clock_local": clock_hk.isoformat(),
        "validated_at_local": current_hk.isoformat(),
        "next_hk_session_at_canary_clock": canary_next_session,
        "next_hk_session_at_validation": current_next_session,
        "target_trade_date": target,
    }
    return value, common.sha256_bytes(raw), freshness


def _default_output(release: dict[str, Any]) -> Path:
    return (common.TASK_ROOT / "staged_config" / "manager-us-mapping-daily-chain"
            / release["manifest_sha256"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True,
                        help="exact app directory in the prepared integrated release")
    parser.add_argument("--target-date", default=common.TARGET_DEFAULT)
    parser.add_argument("--api-plist", type=Path, default=common.LIVE_API_PLIST)
    parser.add_argument("--scheduler-plist", type=Path, default=common.LIVE_SCHEDULER_PLIST)
    parser.add_argument("--canary-path", type=Path,
                        help="fresh plan-canary.json produced by run_daily_chain_canary.py")
    parser.add_argument("--output-dir", type=Path,
                        help="new staging directory below task staged_config")
    parser.add_argument("--stage-enabled", action="store_true",
                        help="write an enabled binding and paired plist copies; never activate them")
    args = parser.parse_args(argv)
    release = common.load_release(args.app_root)
    live = common.current_plists(args.api_plist, args.scheduler_plist)
    identity = common.current_identity(args.app_root, release, live=live)
    output_dir = args.output_dir or _default_output(release)
    stage_root = common.TASK_ROOT / "staged_config"
    if not output_dir.is_absolute() or output_dir.resolve() != output_dir:
        raise ValueError("STAGING_OUTPUT_PATH_NOT_EXACT")
    if output_dir != stage_root and stage_root not in output_dir.parents:
        raise ValueError("STAGING_OUTPUT_OUTSIDE_TASK_SCOPE")
    canary_path = args.canary_path or (
        common.TASK_ROOT / "receipts" / "plan_canary_runs" / args.target_date
        / "execution-01" / "plan-canary.json")
    if not canary_path.is_absolute() or canary_path.resolve() != canary_path:
        raise ValueError("CANARY_PATH_NOT_EXACT")
    receipts_root = common.TASK_ROOT / "receipts"
    if receipts_root not in canary_path.parents:
        raise ValueError("CANARY_PATH_OUTSIDE_TASK_RECEIPTS")

    canary_exists = canary_path.is_file() and not canary_path.is_symlink()
    if args.stage_enabled and not canary_exists:
        raise ValueError("FRESH_CANARY_REQUIRED_FOR_STAGING")
    if canary_exists:
        _canary, canary_sha, canary_freshness = _validate_canary(
            canary_path, release, identity["state_root"], args.target_date)
    else:
        canary_sha = "0" * 64
        canary_freshness = None
    staged = _stage_plists(identity, output_dir, canary_path, canary_sha)
    binding = common.build_binding(identity, enabled=True,
                                   canary_path=canary_path, canary_sha256=canary_sha)
    if canary_exists:
        release["contract"].validate_binding(binding, args.app_root,
                                            expected_owner_app=args.app_root)

    receipt = {
        "schema_version": "v4.us_daily_chain.activation_stage.v1",
        "status": "PREPARED_NOT_ACTIVATED" if args.stage_enabled else
                  "DRY_RUN_READY" if canary_exists else "DRY_RUN_AWAITING_FRESH_CANARY",
        "target_trade_date": args.target_date,
        "candidate_app_root": str(args.app_root),
        "release_id": release["manifest"]["candidate"]["release_id"],
        "release_manifest_path": str(release["manifest_path"]),
        "release_manifest_sha256": release["manifest_sha256"],
        "application_inventory_sha256": release["application_inventory_sha256"],
        "binding_inventory_sha256": common.canonical_sha(release["binding_files"]),
        "owner_source_inventory_sha256": release["owner_inventory_sha256"],
        "active_api_app_root": str(identity["active_api_app_root"]),
        "active_api_release_id": identity["active_api_release_id"],
        "manager_state_root": str(identity["state_root"]),
        "security_master_root": str(identity["master_root"]),
        "current_api_plist_sha256": live["api_sha256"],
        "current_scheduler_plist_sha256": live["scheduler_sha256"],
        "current_api_binding_path": str(identity["active_api_binding_path"]),
        "current_api_binding_sha256": identity["active_api_binding_sha256"],
        "current_scheduler_binding_path": str(identity["active_scheduler_binding_path"]),
        "current_scheduler_binding_sha256": identity["active_scheduler_binding_sha256"],
        "canary_path": str(canary_path),
        "canary_sha256": canary_sha,
        "canary_freshness_policy": {
            "max_age_minutes": 60,
            "current_clock_source": "datetime.now(Asia/Hong_Kong)",
            "checks": [
                "canary clock is not in the future",
                "canary age is at most 60 minutes",
                "target is next HK session at canary clock",
                "target is next HK session at validation clock",
            ],
            "rechecked_immediately_before_enabled_staging": bool(args.stage_enabled),
        },
        "canary_freshness": canary_freshness,
        "staging_output_dir": str(output_dir),
        "staged_binding_path": str(staged["binding_path"]),
        "staged_api_plist_path": str(output_dir / "com.lexi.v35.api-only.plist"),
        "staged_scheduler_plist_path": str(output_dir / "com.lexi.v35.scheduler.plist"),
        "api_environment_updates": staged["api_updates"],
        "api_changed_environment_keys": staged["api_changed_environment_keys"],
        "api_expected_changed_environment_keys": staged["api_expected_changed_environment_keys"],
        "scheduler_manager_hook_updates": staged["scheduler_updates"],
        "scheduler_changed_environment_keys": staged["scheduler_changed_environment_keys"],
        "scheduler_expected_changed_environment_keys": staged["scheduler_expected_changed_environment_keys"],
        "preserved_api_working_data_roots": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in common.resolve_api_runtime_roots(live["api"], live["api_env"]).items()
        },
        "scheduler_working_directory_preserved": live["scheduler"].get("WorkingDirectory"),
        "scheduler_app_root_preserved": live["scheduler_env"].get("V35_APP_ROOT"),
        "scheduler_hk_root_and_task_preserved": staged["scheduler_hk_root_and_task_preserved"],
        "plan_material_refresh": common.PLAN_MATERIAL_REFRESH,
        "daily_automation": common.DAILY_AUTOMATION,
        "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False,
        "live_plists_modified": False,
        "manager_state_modified_by_stager": False,
        "safety": common.SAFETY,
    }
    if not args.stage_enabled:
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2))
        return 0

    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("STAGING_OUTPUT_ALREADY_EXISTS:" + str(output_dir))
    # Do not stage against stale LaunchAgent bytes if the active app changed
    # while the helper was validating the release and canary.
    current_again = common.current_plists(args.api_plist, args.scheduler_plist)
    if (current_again["api_sha256"] != live["api_sha256"]
            or current_again["scheduler_sha256"] != live["scheduler_sha256"]):
        raise ValueError("LIVE_PLIST_INPUTS_CHANGED_DURING_STAGING")
    # Recheck against the real local clock immediately before creating enabled
    # staging outputs; there is deliberately no CLI clock override.
    _canary_again, canary_sha_again, canary_freshness = _validate_canary(
        canary_path, release, identity["state_root"], args.target_date,
        now=datetime.now(HONG_KONG_TZ))
    if canary_sha_again != canary_sha:
        raise ValueError("FRESH_CANARY_CHANGED_DURING_STAGING")
    receipt["canary_freshness"] = canary_freshness
    receipt["canary_sha256"] = canary_sha_again
    stage_root.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=False, exist_ok=False)
    binding_raw = _json_bytes(binding)
    api_raw = plistlib.dumps(staged["api_plist"], fmt=plistlib.FMT_XML, sort_keys=False)
    scheduler_raw = plistlib.dumps(staged["scheduler_plist"], fmt=plistlib.FMT_XML, sort_keys=False)
    receipt.update({
        "staged_binding_sha256": common.sha256_bytes(binding_raw),
        "staged_api_plist_sha256": common.sha256_bytes(api_raw),
        "staged_scheduler_plist_sha256": common.sha256_bytes(scheduler_raw),
    })
    # The plist paths must be calculated before serialization and match these
    # actual output names; all creates are exclusive to prevent replacement.
    _write_exclusive(output_dir / "manager-plan-binding.json", binding_raw)
    _write_exclusive(output_dir / "com.lexi.v35.api-only.plist", api_raw)
    _write_exclusive(output_dir / "com.lexi.v35.scheduler.plist", scheduler_raw)
    receipt_raw = _json_bytes(receipt)
    _write_exclusive(output_dir / "activation-stage-receipt.json", receipt_raw)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
