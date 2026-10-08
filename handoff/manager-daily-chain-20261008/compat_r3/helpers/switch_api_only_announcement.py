#!/usr/bin/env python3
"""Guarded API-only switch for the reviewed manager announcement owner route.

This helper changes only the loaded ``com.lexi.v35.api-only`` LaunchAgent and
its plist. The scheduler plist, manager state, and plan activation binding stay
untouched. ``preflight`` is read-only. The service-changing commands require
an explicit confirmation token and the frozen preimage/candidate SHA values.
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

sys.dont_write_bytecode = True


TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/candidate/analysis-readback-compat")
API_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r3-api/app")
API_RELEASE_ROOT = API_ROOT.parent
API_MANIFEST = API_RELEASE_ROOT / "release-manifest.json"
ACTIVE_API_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
ACTIVE_SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
STAGE_CENTER_SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist")
STAGED_API_PLIST = TASK_ROOT / "staged_config/com.lexi.v35.api-only.r3-announcement-compat.plist"
DISABLED_BINDING = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/staged_config/manager-plan-binding-c1.disabled.final-d1-r2.json")
FORMAL_MANAGER_STATE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research")
PINNED_PYTHON = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python")
SAFE_PLIST_BACKEND = API_ROOT / "ops/prepare_api_only_cutover.py"
INVENTORY_BACKEND = API_ROOT / "ops/build_release_candidate.py"
LAUNCHCTL = Path("/bin/launchctl")

LABEL = "com.lexi.v35.api-only"
PORT = 8873
EXPECTED_API_RELEASE_ID = "manager-daily-chain-20261008-r3-api"
EXPECTED_API_MANIFEST_SHA256 = "946c49b9c34bd09fbca04644556de3acba1635eb240fa9293f6391e9d46b40e9"
EXPECTED_API_INVENTORY_SHA256 = "07ff61bc18f66f7e92eb45f57a20aecf3885eaa79c1bdb705b8f805fdbb95bd8"
EXPECTED_ACTIVE_API_PLIST_SHA256 = "b2eb9828645538863571ea9cdb0d830ac76afcafba551faf127a16752db2eee3"
EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256 = "c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2"
EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256 = "9c7199ca1fcfedc09397255c932d25c6edc15779952bbd5b5bec2671e883d3f5"
EXPECTED_STAGED_API_PLIST_SHA256 = "72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5"
EXPECTED_DISABLED_BINDING_SHA256 = "f3b7cbfa1709b2b27816d294e599cb1ae82ff918ba41ec148644f1a1751f5fd6"
EXPECTED_SAFE_PLIST_BACKEND_SHA256 = "4747df35c3d7922bd1122256565e1136d5740d942ebb03d925ef870d056df22e"
EXPECTED_INVENTORY_BACKEND_SHA256 = "b74a4979f3227e42f4585d27f09eb6f2a4322f2b9ce8406af8839a714e7ba033"
EXPECTED_ANNOUNCEMENT_EVIDENCE_RUN_ID = "3f9d37a643060b57992167f3df05d987"
EXPECTED_ANNOUNCEMENT_HANDOFF_MANIFEST_SHA256 = "70ffa628e43d43c451defecb728197cde4bcc437bbfafc3e883ecf0b3327a03e"
EXPECTED_ANNOUNCEMENT_HANDOFF_MANIFEST_FILE_SHA256 = "10b3d551380109ca6dd659e1e2ce1dff13b4dcd9c407f57992b94fc6c4d2dc43"
EXPECTED_ANNOUNCEMENT_PRODUCT_SHA256 = "8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157"
EXPECTED_ANNOUNCEMENT_PRODUCT_FILE_SHA256 = "5c4e9e29206ce56a8366e1dd3d5cad965a70491d37a0804a6637113ab9f27790"
EXPECTED_ANNOUNCEMENT_CAPTURE_SHA256 = "8d6822620a76fa2438ece0b69876c0b6b0d36e5e4e2ff03e3161317c252a9c95"
EXPECTED_ANNOUNCEMENT_BODY_CORPUS_SHA256 = "de9ad88e09392bf51459fa1f4a4ecff645c5b4731984464868870114f1aecbf6"
EXPECTED_ANNOUNCEMENT_BODY_BATCH_SHA256 = "2b0539c4e090bca4af50f49819d69f689e1dadfa2b0527f7ece1242865313599"
EXPECTED_ANNOUNCEMENT_CATALOG_FILE_SHA256 = "1f7fdc0c713fcf06d019cbdb53eea9fce84a830bbc8bfdab057553a36acfb0f2"
EXPECTED_ANNOUNCEMENT_ARTICLE_ROWS = 613
EXPECTED_ANNOUNCEMENT_BODY_COMPLETE_ROWS = 608
EXPECTED_ANNOUNCEMENT_BODY_FAILED_ROWS = 5
CONFIRM_SWITCH = "SWITCH_API_ONLY_TO_R3_ANNOUNCEMENT_COMPAT"
CONFIRM_ROLLBACK = "ROLLBACK_API_ONLY_TO_R2_PREIMAGE"
OPENAPI_URL = f"http://127.0.0.1:{PORT}/openapi.json"
IMPORT_ROUTE = "/api/v4/manager/research/announcements/analysis/import"
ALLOWED_ENV_CHANGES = {
    "V35_APP_ROOT",
    "V35_RELEASE_ID",
    "PYTHONPATH",
    "V35_RELEASE_MANIFEST_PATH",
    "V35_RELEASE_MANIFEST_SHA256",
    "V4_MANAGER_PLAN_OWNER_BINDING_PATH",
}
SAFETY_EXPECTED = {
    "RESEARCH_ONLY": "1",
    "production_allowed": "false",
    "PRODUCTION_ALLOWED": "false",
    "buy_gate_updated": "false",
    "BUY_GATE_UPDATED": "false",
    "orders_sent": "false",
    "ORDERS_SENT": "false",
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha(path.read_bytes())


def active_plist_sha_or_none(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return _sha_file(path)
    except OSError:
        return None


def _regular_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label}_NOT_REGULAR_FILE")
    return path.read_bytes()


def _exact_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        raise ValueError(f"{label}_NOT_EXACT_DIRECTORY")


def _load_inventory_backend() -> Any:
    raw = _regular_file(INVENTORY_BACKEND, "INVENTORY_BACKEND")
    if _sha(raw) != EXPECTED_INVENTORY_BACKEND_SHA256:
        raise ValueError("R2_INVENTORY_BACKEND_SHA_MISMATCH")
    if str(API_ROOT / "ops") not in sys.path:
        sys.path.insert(0, str(API_ROOT / "ops"))
    spec = importlib.util.spec_from_file_location("_manager_daily_release_inventory", INVENTORY_BACKEND)
    if spec is None or spec.loader is None:
        raise ValueError("R2_INVENTORY_BACKEND_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_release_identity() -> dict[str, Any]:
    _exact_directory(API_ROOT, "R2_API_ROOT")
    manifest_raw = _regular_file(API_MANIFEST, "R2_API_MANIFEST")
    if _sha(manifest_raw) != EXPECTED_API_MANIFEST_SHA256:
        raise ValueError("R2_API_MANIFEST_SHA_MISMATCH")
    manifest = json.loads(manifest_raw.decode("utf-8"))
    if (manifest.get("candidate", {}).get("release_id") != EXPECTED_API_RELEASE_ID
            or manifest.get("candidate", {}).get("app_root") != str(API_ROOT)
            or manifest.get("application_inventory", {}).get("aggregate_sha256") != EXPECTED_API_INVENTORY_SHA256):
        raise ValueError("R2_API_MANIFEST_IDENTITY_MISMATCH")
    inventory = _load_inventory_backend()
    entries = inventory.inventory_tree(API_ROOT)
    inventory_sha = inventory.inventory_digest(entries)
    if (inventory_sha != EXPECTED_API_INVENTORY_SHA256
            or entries != manifest.get("application_inventory", {}).get("entries")):
        raise ValueError("R2_API_APPLICATION_INVENTORY_DRIFT")
    return {"release_id": EXPECTED_API_RELEASE_ID, "app_root": str(API_ROOT),
            "manifest_path": str(API_MANIFEST), "manifest_sha256": EXPECTED_API_MANIFEST_SHA256,
            "inventory_sha256": inventory_sha, "entry_count": len(entries)}


def _load_disabled_binding() -> dict[str, Any]:
    raw = _regular_file(DISABLED_BINDING, "DISABLED_PLAN_BINDING")
    if _sha(raw) != EXPECTED_DISABLED_BINDING_SHA256:
        raise ValueError("DISABLED_PLAN_BINDING_SHA_MISMATCH")
    binding = json.loads(raw.decode("utf-8"))
    if (binding.get("enabled") is not False
            or binding.get("announcement_collection_enabled") is not False
            or binding.get("plan_material_refresh_only") is not False
            or binding.get("manager_state_root") != str(FORMAL_MANAGER_STATE)):
        raise ValueError("API_ONLY_PLAN_BINDING_MUST_REMAIN_DISABLED")
    return binding


def _load_registered_announcement_handoff() -> dict[str, Any]:
    """Read and validate the already registered 10/8 handoff by exact identity."""
    _exact_directory(FORMAL_MANAGER_STATE, "FORMAL_MANAGER_STATE")
    evidence = (FORMAL_MANAGER_STATE / "announcement_agent_runs"
                / EXPECTED_ANNOUNCEMENT_EVIDENCE_RUN_ID / "evidence")
    if evidence.is_symlink() or not evidence.is_dir() or evidence.resolve(strict=True).parent.parent.parent != FORMAL_MANAGER_STATE:
        raise ValueError("ANNOUNCEMENT_HANDOFF_EVIDENCE_ROOT_INVALID")
    paths = {
        "handoff_manifest.v1.json": EXPECTED_ANNOUNCEMENT_HANDOFF_MANIFEST_FILE_SHA256,
        "analysis_product.json": EXPECTED_ANNOUNCEMENT_PRODUCT_FILE_SHA256,
        "capture_receipt.json": EXPECTED_ANNOUNCEMENT_CAPTURE_SHA256,
        "body_corpus.json": EXPECTED_ANNOUNCEMENT_BODY_CORPUS_SHA256,
        "body_batch_receipt.json": EXPECTED_ANNOUNCEMENT_BODY_BATCH_SHA256,
        "catalog_read.json": EXPECTED_ANNOUNCEMENT_CATALOG_FILE_SHA256,
    }
    raw_by_name: dict[str, bytes] = {}
    for name, expected_sha in paths.items():
        path = evidence / name
        raw = _regular_file(path, "ANNOUNCEMENT_HANDOFF_" + name.upper().replace(".", "_"))
        if _sha(raw) != expected_sha:
            raise ValueError("ANNOUNCEMENT_HANDOFF_FILE_SHA_MISMATCH:" + name)
        raw_by_name[name] = raw
    try:
        manifest = json.loads(raw_by_name["handoff_manifest.v1.json"].decode("utf-8"))
        product = json.loads(raw_by_name["analysis_product.json"].decode("utf-8"))
        body = json.loads(raw_by_name["body_corpus.json"].decode("utf-8"))
        catalog_read = json.loads(raw_by_name["catalog_read.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ANNOUNCEMENT_HANDOFF_JSON_INVALID") from exc
    if (manifest.get("evidence_run_id") != EXPECTED_ANNOUNCEMENT_EVIDENCE_RUN_ID
            or manifest.get("sha256") != EXPECTED_ANNOUNCEMENT_HANDOFF_MANIFEST_SHA256
            or product.get("sha256") != EXPECTED_ANNOUNCEMENT_PRODUCT_SHA256
            or product.get("target_trade_date") != "20261008"
            or product.get("publication_date") != "2026-10-07"
            or len(product.get("records", [])) != EXPECTED_ANNOUNCEMENT_ARTICLE_ROWS
            or len(body.get("rows", [])) != EXPECTED_ANNOUNCEMENT_ARTICLE_ROWS
            or catalog_read.get("readback_status") != "VERIFIED"):
        raise ValueError("ANNOUNCEMENT_HANDOFF_IDENTITY_MISMATCH")

    # Load the validator only from the frozen R2 release. The default preflight
    # process starts clean, and bytecode writes remain disabled at module scope.
    for import_root in (str(API_ROOT / "upstreams"), str(API_ROOT)):
        if import_root not in sys.path:
            sys.path.insert(0, import_root)
    from v4.manager_research.workspace_announcements import validate_registered_handoff

    verified = validate_registered_handoff(SimpleNamespace(root=FORMAL_MANAGER_STATE),
        EXPECTED_ANNOUNCEMENT_EVIDENCE_RUN_ID,
        EXPECTED_ANNOUNCEMENT_HANDOFF_MANIFEST_SHA256,
        EXPECTED_ANNOUNCEMENT_PRODUCT_SHA256)
    verified_product = verified.get("product")
    if not isinstance(verified_product, Mapping) or verified_product != product:
        raise ValueError("ANNOUNCEMENT_HANDOFF_VALIDATOR_PRODUCT_MISMATCH")
    failed_codes = {row.get("art_code") for row in product["records"]
                    if isinstance(row, Mapping) and row.get("body_status") == "BODY_CAPTURE_FAILED"}
    complete_count = sum(isinstance(row, Mapping) and row.get("body_status") == "COMPLETE_CONTENT_API_BODY"
                         for row in body["rows"])
    failed_count = sum(isinstance(row, Mapping) and row.get("body_status") == "BODY_CAPTURE_FAILED"
                       for row in body["rows"])
    extension = product.get("stock_selection")
    decisions = extension.get("article_decisions") if isinstance(extension, Mapping) else None
    by_code = {row.get("art_code"): row.get("disposition") for row in decisions or []
               if isinstance(row, Mapping)}
    if (len(failed_codes) != EXPECTED_ANNOUNCEMENT_BODY_FAILED_ROWS
            or complete_count != EXPECTED_ANNOUNCEMENT_BODY_COMPLETE_ROWS
            or failed_count != EXPECTED_ANNOUNCEMENT_BODY_FAILED_ROWS
            or len(decisions or []) != EXPECTED_ANNOUNCEMENT_ARTICLE_ROWS
            or len(by_code) != EXPECTED_ANNOUNCEMENT_ARTICLE_ROWS
            or any(by_code.get(code) != "NOT_ASSESSED" for code in failed_codes)
            or any(by_code.get(code) in {"SELECTED", "CONDITIONAL_WATCH"} for code in failed_codes)):
        raise ValueError("ANNOUNCEMENT_HANDOFF_TERMINAL_COUNTS_OR_FAILURE_DISPOSITIONS_INVALID")
    return {
        "status": "REGISTERED_HANDOFF_VERIFIED_READ_ONLY",
        "evidence_run_id": EXPECTED_ANNOUNCEMENT_EVIDENCE_RUN_ID,
        "evidence_root": str(evidence),
        "handoff_manifest_sha256": EXPECTED_ANNOUNCEMENT_HANDOFF_MANIFEST_SHA256,
        "handoff_manifest_file_sha256": EXPECTED_ANNOUNCEMENT_HANDOFF_MANIFEST_FILE_SHA256,
        "product_sha256": EXPECTED_ANNOUNCEMENT_PRODUCT_SHA256,
        "product_file_sha256": EXPECTED_ANNOUNCEMENT_PRODUCT_FILE_SHA256,
        "target_trade_date": "20261008", "publication_date": "2026-10-07",
        "decision_status": "EXPLICIT_DISPOSITIONS",
        "article_rows": EXPECTED_ANNOUNCEMENT_ARTICLE_ROWS,
        "body_complete_rows": complete_count, "body_failed_rows": failed_count,
        "failed_dispositions": "NOT_ASSESSED", "reader_output_sha256": verified["manifest"]["files"]["reader_output.json"],
        "reviewer_output_sha256": verified["manifest"]["files"]["reviewer_output.json"],
        "reviewer_conclusion": "PASS", "owner_import": "NOT_RUN_BY_PREFLIGHT",
        "external_review_authentication": "DECLARED_OUTPUT_BOUND_NOT_PLATFORM_AUTHENTICATED",
    }


def _parse_assignments(plist_value: Mapping[str, Any]) -> tuple[dict[str, str], list[Any]]:
    arguments = plist_value.get("ProgramArguments")
    if not isinstance(arguments, list) or not arguments or arguments[0] != "/usr/bin/env":
        raise ValueError("API_ONLY_PLIST_ENV_WRAPPER_INVALID")
    environment: dict[str, str] = {}
    command: list[Any] = []
    passed_assignments = False
    for item in arguments[1:]:
        if not passed_assignments and isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            if key and not any(char.isspace() for char in key):
                environment[key] = value
                continue
        passed_assignments = True
        command.append(item)
    if not command or command[0] != str(PINNED_PYTHON):
        raise ValueError("API_ONLY_PYTHON_ENTRYPOINT_MISMATCH")
    return environment, command


def _verify_plist_pair(original_raw: bytes, staged_raw: bytes) -> dict[str, Any]:
    original = plistlib.loads(original_raw)
    staged = plistlib.loads(staged_raw)
    old_env, old_command = _parse_assignments(original)
    new_env, new_command = _parse_assignments(staged)
    if old_command != new_command:
        raise ValueError("API_ONLY_COMMAND_ARGUMENTS_CHANGED")
    for key, value in SAFETY_EXPECTED.items():
        if new_env.get(key) != value:
            raise ValueError("API_ONLY_SAFETY_FLAG_MISMATCH:" + key)
    if {key: value for key, value in old_env.items() if key not in ALLOWED_ENV_CHANGES} != {
        key: value for key, value in new_env.items() if key not in ALLOWED_ENV_CHANGES
    }:
        raise ValueError("API_ONLY_PRESERVED_ENVIRONMENT_CHANGED")
    if any(key not in new_env or new_env[key] != old_env.get(key) for key in old_env if key not in ALLOWED_ENV_CHANGES):
        raise ValueError("API_ONLY_PRESERVED_ENVIRONMENT_VALUE_CHANGED")
    expected_environment = {
        "V35_APP_ROOT": str(API_ROOT),
        "V35_RELEASE_ID": EXPECTED_API_RELEASE_ID,
        "PYTHONPATH": f"{API_ROOT / 'upstreams'}:{API_ROOT}",
        "V35_RELEASE_MANIFEST_PATH": str(API_MANIFEST),
        "V35_RELEASE_MANIFEST_SHA256": EXPECTED_API_MANIFEST_SHA256,
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(DISABLED_BINDING),
        "V4_MANAGER_RESEARCH_STATE_ROOT": str(FORMAL_MANAGER_STATE),
    }
    if any(new_env.get(key) != value for key, value in expected_environment.items()):
        raise ValueError("API_ONLY_TARGET_ENVIRONMENT_MISMATCH")
    allowed_plist_keys = {"ProgramArguments", "WorkingDirectory"}
    if {key: value for key, value in original.items() if key not in allowed_plist_keys} != {
        key: value for key, value in staged.items() if key not in allowed_plist_keys
    }:
        raise ValueError("API_ONLY_LAUNCH_AGENT_POLICY_CHANGED")
    if staged.get("Label") != LABEL or staged.get("KeepAlive") is not True or staged.get("RunAtLoad") is not False:
        raise ValueError("API_ONLY_LAUNCH_AGENT_IDENTITY_OR_POLICY_MISMATCH")
    if original.get("WorkingDirectory") == staged.get("WorkingDirectory"):
        raise ValueError("API_ONLY_WORKING_DIRECTORY_NOT_UPDATED")
    if staged.get("WorkingDirectory") != str(API_ROOT):
        raise ValueError("API_ONLY_WORKING_DIRECTORY_MISMATCH")
    return {"label": LABEL, "old_app_root": old_env.get("V35_APP_ROOT"),
            "old_release_id": old_env.get("V35_RELEASE_ID"),
            "new_app_root": new_env["V35_APP_ROOT"], "new_release_id": new_env["V35_RELEASE_ID"],
            "manager_state_root": new_env["V4_MANAGER_RESEARCH_STATE_ROOT"],
            "plan_binding_enabled": False, "plan_canary_required_for_announcement_import": False}


def _launchctl_print() -> str:
    if not LAUNCHCTL.is_file():
        raise ValueError("LAUNCHCTL_NOT_AVAILABLE")
    domain = f"gui/{os.getuid()}/{LABEL}"
    result = subprocess.run([str(LAUNCHCTL), "print", domain], capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise ValueError("API_ONLY_LAUNCH_AGENT_NOT_LOADED:" + (result.stderr.strip()[:240] or str(result.returncode)))
    return result.stdout


def _job_is_loaded() -> bool:
    if not LAUNCHCTL.is_file():
        return False
    result = subprocess.run([str(LAUNCHCTL), "print", f"gui/{os.getuid()}/{LABEL}"],
                            capture_output=True, text=True, timeout=15)
    return result.returncode == 0


def _observe_loaded_api() -> dict[str, Any]:
    """Best-effort bounded observation used only while restoring the old API."""
    try:
        output = _launchctl_print()
    except Exception as exc:
        message = str(exc)
        if message.startswith("API_ONLY_LAUNCH_AGENT_NOT_LOADED:"):
            return {"state": "NOT_LOADED", "identity": None}
        return {"state": "UNKNOWN", "identity": None, "error": message[:300]}
    try:
        identity = _loaded_identity(output)
    except ValueError as exc:
        return {"state": "LOADED_UNVERIFIED", "identity": None, "error": str(exc)}
    return {"state": "LOADED", "identity": identity}


def _loaded_identity(output: str) -> dict[str, str]:
    state_match = re.search(r"(?m)^\s*state\s*=\s*(\S+)", output)
    if not state_match or state_match.group(1) != "running":
        raise ValueError("API_ONLY_LAUNCH_AGENT_NOT_RUNNING")
    values: dict[str, str] = {}
    for key in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256"):
        match = re.search(rf"(?m)^\s*{re.escape(key)}=([^\r\n]+)", output)
        if match:
            values[key] = match.group(1)
    if len(values) != 3:
        raise ValueError("API_ONLY_LAUNCH_AGENT_RUNTIME_IDENTITY_UNAVAILABLE")
    return values


def _identity_from_plist(raw: bytes) -> dict[str, str]:
    value = plistlib.loads(raw)
    environment, _ = _parse_assignments(value)
    fields = ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")
    result = {key: environment.get(key, "") for key in fields}
    if any(not item for item in result.values()):
        raise ValueError("API_ONLY_PLIST_RUNTIME_IDENTITY_UNAVAILABLE")
    return result


def _preflight() -> dict[str, Any]:
    if Path(sys.executable).resolve(strict=True) != PINNED_PYTHON.resolve(strict=True):
        raise ValueError("API_ONLY_SWITCH_REQUIRES_PINNED_V4_PYTHON")
    _exact_directory(FORMAL_MANAGER_STATE, "FORMAL_MANAGER_STATE")
    release = _load_release_identity()
    _load_disabled_binding()
    registered_handoff = _load_registered_announcement_handoff()
    source_raw = _regular_file(ACTIVE_API_PLIST, "ACTIVE_API_PLIST")
    scheduler_raw = _regular_file(ACTIVE_SCHEDULER_PLIST, "ACTIVE_SCHEDULER_PLIST")
    stage_center_scheduler_raw = _regular_file(STAGE_CENTER_SCHEDULER_PLIST, "STAGE_CENTER_SCHEDULER_PLIST")
    staged_raw = _regular_file(STAGED_API_PLIST, "STAGED_API_PLIST")
    if _sha(source_raw) != EXPECTED_ACTIVE_API_PLIST_SHA256:
        raise ValueError("ACTIVE_API_PLIST_PREIMAGE_SHA_MISMATCH")
    if _sha(scheduler_raw) != EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256:
        raise ValueError("SCHEDULER_PLIST_PREIMAGE_SHA_MISMATCH")
    if _sha(stage_center_scheduler_raw) != EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256:
        raise ValueError("STAGE_CENTER_SCHEDULER_PLIST_PREIMAGE_SHA_MISMATCH")
    if _sha(staged_raw) != EXPECTED_STAGED_API_PLIST_SHA256:
        raise ValueError("STAGED_API_PLIST_SHA_MISMATCH")
    active_xattrs = _xattr_snapshot(ACTIVE_API_PLIST)
    staged_xattrs = _xattr_snapshot(STAGED_API_PLIST)
    if active_xattrs != staged_xattrs:
        raise ValueError("API_ONLY_PLIST_XATTR_PREIMAGE_MISMATCH")
    active_stat = ACTIVE_API_PLIST.stat()
    staged_stat = STAGED_API_PLIST.stat()
    if stat.S_IMODE(active_stat.st_mode) != stat.S_IMODE(staged_stat.st_mode):
        raise ValueError("API_ONLY_PLIST_MODE_MISMATCH")
    if active_stat.st_uid != os.getuid() or active_stat.st_gid != os.getgid():
        raise ValueError("API_ONLY_PLIST_OWNER_MISMATCH")
    if getattr(active_stat, "st_flags", 0) != 0 or getattr(staged_stat, "st_flags", 0) != 0:
        raise ValueError("API_ONLY_PLIST_FILE_FLAGS_UNSUPPORTED")
    plist_pair = _verify_plist_pair(source_raw, staged_raw)
    loaded = _loaded_identity(_launchctl_print())
    old_plist = plistlib.loads(source_raw)
    old_env, _ = _parse_assignments(old_plist)
    if loaded != {
        "V35_APP_ROOT": old_env.get("V35_APP_ROOT", ""),
        "V35_RELEASE_ID": old_env.get("V35_RELEASE_ID", ""),
        "V35_RELEASE_MANIFEST_SHA256": old_env.get("V35_RELEASE_MANIFEST_SHA256", ""),
    }:
        raise ValueError("ACTIVE_API_LAUNCH_AGENT_RUNTIME_DOES_NOT_MATCH_PREIMAGE")
    return {"status": "READY_API_ONLY_ANNOUNCEMENT_CUTOVER", "api_release": release,
            "active_api_plist": {"path": str(ACTIVE_API_PLIST), "sha256": EXPECTED_ACTIVE_API_PLIST_SHA256},
            "staged_api_plist": {"path": str(STAGED_API_PLIST), "sha256": EXPECTED_STAGED_API_PLIST_SHA256},
            "scheduler": {"path": str(ACTIVE_SCHEDULER_PLIST), "sha256": EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256,
                          "action": "UNCHANGED"},
            "stage_center_scheduler": {"path": str(STAGE_CENTER_SCHEDULER_PLIST),
                                       "sha256": EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256,
                                       "action": "READ_ONLY_PRE_POST_GUARD"},
            "manager_state_root": str(FORMAL_MANAGER_STATE), "plist_delta": plist_pair,
            "launchd_runtime": loaded, "announcement_import_route": IMPORT_ROUTE,
            "plist_xattrs_sha256": _sha(json.dumps(active_xattrs, sort_keys=True,
                separators=(",", ":")).encode("utf-8")),
            "plan_activation_canary": "NOT_REQUIRED_FOR_ANNOUNCEMENT_IMPORT",
            "registered_announcement_handoff": registered_handoff,
            "formal_owner_import_or_page_refresh": "NOT_RUN", "safety": {"RESEARCH_ONLY": True,
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}}


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _receipt_bytes(value: Mapping[str, Any]) -> bytes:
    unsigned = dict(value)
    unsigned.pop("receipt_sha256", None)
    digest = _sha(json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8"))
    complete = {**unsigned, "receipt_sha256": digest}
    return (json.dumps(complete, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _update_receipt(path: Path, value: Mapping[str, Any]) -> None:
    temp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    raw = _receipt_bytes(value)
    with temp.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _xattr_snapshot(path: Path) -> dict[str, str]:
    if hasattr(os, "listxattr"):
        return {name: os.getxattr(path, name, follow_symlinks=False).hex()
                for name in os.listxattr(path, follow_symlinks=False)}
    xattr = Path("/usr/bin/xattr")
    if not xattr.is_file():
        raise ValueError("API_ONLY_PLIST_XATTR_COPY_UNAVAILABLE")
    names = subprocess.run([str(xattr), str(path)], capture_output=True, text=True, timeout=10)
    if names.returncode != 0:
        raise ValueError("API_ONLY_PLIST_XATTR_READ_FAILED")
    result: dict[str, str] = {}
    for name in names.stdout.splitlines():
        if not name:
            continue
        value = subprocess.run([str(xattr), "-px", name, str(path)],
                               capture_output=True, text=True, timeout=10)
        if value.returncode != 0:
            raise ValueError("API_ONLY_PLIST_XATTR_READ_FAILED:" + name)
        result[name] = "".join(value.stdout.split())
    return result


def _copy_xattrs(source: Path, destination: Path) -> None:
    if hasattr(os, "listxattr"):
        for name in os.listxattr(source, follow_symlinks=False):
            value = os.getxattr(source, name, follow_symlinks=False)
            os.setxattr(destination, name, value, follow_symlinks=False)
        return
    xattr = Path("/usr/bin/xattr")
    for name, encoded in _xattr_snapshot(source).items():
        copied = subprocess.run([str(xattr), "-wx", name, encoded, str(destination)],
                                capture_output=True, text=True, timeout=10)
        if copied.returncode != 0:
            raise ValueError("API_ONLY_PLIST_XATTR_WRITE_FAILED:" + name)


def _atomic_replace_bytes(path: Path, raw: bytes, metadata_source: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("API_ONLY_TARGET_PLIST_NO_LONGER_REGULAR")
    info = path.stat(follow_symlinks=False)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temp_stat = temp.stat()
        if temp_stat.st_uid != info.st_uid or temp_stat.st_gid != info.st_gid:
            raise ValueError("API_ONLY_TEMP_PLIST_OWNER_MISMATCH")
        os.chmod(temp, stat.S_IMODE(info.st_mode), follow_symlinks=False)
        _copy_xattrs(metadata_source, temp)
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            try:
                os.fsync(dir_fd)
            except OSError as exc:
                if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EBADF}:
                    raise
        finally:
            os.close(dir_fd)
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()


def _launchctl(*arguments: str) -> None:
    domain = f"gui/{os.getuid()}"
    result = subprocess.run([str(LAUNCHCTL), *arguments, domain, str(ACTIVE_API_PLIST)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ValueError("LAUNCHCTL_ACTION_FAILED:" + arguments[0] + ":" +
                         (result.stderr.strip()[:300] or str(result.returncode)))


def _openapi_ready(*, require_import_route: bool) -> dict[str, Any]:
    request = urllib.request.Request(OPENAPI_URL, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise ValueError("API_OPENAPI_HTTP_STATUS:" + str(response.status))
            payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValueError("API_OPENAPI_NOT_READY:" + type(exc).__name__) from exc
    method = payload.get("paths", {}).get(IMPORT_ROUTE, {}).get("post")
    if require_import_route and not isinstance(method, dict):
        raise ValueError("ANNOUNCEMENT_IMPORT_ROUTE_NOT_AVAILABLE")
    return {"http_status": 200, "announcement_import_route": "AVAILABLE" if isinstance(method, dict) else "NOT_PRESENT"}


def _verify_loaded(expected: Mapping[str, str], *, require_import_route: bool) -> dict[str, Any]:
    loaded = _loaded_identity(_launchctl_print())
    if (loaded.get("V35_APP_ROOT") != expected.get("V35_APP_ROOT")
            or loaded.get("V35_RELEASE_ID") != expected.get("V35_RELEASE_ID")
            or loaded.get("V35_RELEASE_MANIFEST_SHA256") != expected.get("V35_RELEASE_MANIFEST_SHA256")):
        raise ValueError("API_ONLY_LAUNCH_AGENT_RUNTIME_IDENTITY_MISMATCH")
    return {"runtime": loaded, "http": _openapi_ready(require_import_route=require_import_route)}


def _record_operation(status: str, operation_dir: Path, details: Mapping[str, Any]) -> Path:
    receipt_path = operation_dir / "operation_receipt.json"
    value = {"schema_version": "v4.manager_daily_chain.api_only_switch.v1", "status": status,
             "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "active_api_plist": str(ACTIVE_API_PLIST), "scheduler_action": "UNCHANGED",
             "plan_activation_canary": "NOT_REQUIRED_FOR_ANNOUNCEMENT_IMPORT", **dict(details)}
    if receipt_path.exists():
        _update_receipt(receipt_path, value)
    else:
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with receipt_path.open("xb") as stream:
            stream.write(_receipt_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
    return receipt_path


def _run_switch(*, confirmation: str, expected_current_sha: str,
                expected_staged_sha: str) -> dict[str, Any]:
    if confirmation != CONFIRM_SWITCH:
        raise ValueError("EXPLICIT_API_ONLY_SWITCH_CONFIRMATION_REQUIRED")
    if expected_current_sha != EXPECTED_ACTIVE_API_PLIST_SHA256 or expected_staged_sha != EXPECTED_STAGED_API_PLIST_SHA256:
        raise ValueError("API_ONLY_SWITCH_EXPECTED_SHA_ARGUMENT_MISMATCH")
    preflight = _preflight()
    source_raw = ACTIVE_API_PLIST.read_bytes()
    staged_raw = STAGED_API_PLIST.read_bytes()
    operation_root = TASK_ROOT / "writer/api_only_switch_runs"
    operation_root.mkdir(parents=True, exist_ok=True)
    operation_dir = operation_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    operation_dir.mkdir(mode=0o700)
    backup = operation_dir / "active_api_only.preimage.plist"
    _write_json_exclusive(operation_dir / "preflight.json", preflight)
    shutil.copy2(ACTIVE_API_PLIST, backup, follow_symlinks=False)
    _copy_xattrs(ACTIVE_API_PLIST, backup)
    if _sha_file(backup) != EXPECTED_ACTIVE_API_PLIST_SHA256:
        raise ValueError("API_ONLY_BACKUP_SHA_MISMATCH")
    if _xattr_snapshot(backup) != _xattr_snapshot(ACTIVE_API_PLIST):
        raise ValueError("API_ONLY_BACKUP_XATTR_MISMATCH")
    receipt_details: dict[str, Any] = {
        "original_plist_sha256": EXPECTED_ACTIVE_API_PLIST_SHA256,
        "candidate_plist_sha256": EXPECTED_STAGED_API_PLIST_SHA256,
        "backup_path": str(backup), "backup_sha256": EXPECTED_ACTIVE_API_PLIST_SHA256,
        "candidate_release_id": EXPECTED_API_RELEASE_ID,
        "candidate_release_manifest_sha256": EXPECTED_API_MANIFEST_SHA256,
        "candidate_inventory_sha256": EXPECTED_API_INVENTORY_SHA256,
        "manager_state_root": str(FORMAL_MANAGER_STATE),
        "disabled_binding_sha256": EXPECTED_DISABLED_BINDING_SHA256,
        "scheduler_plist_sha256": EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256,
        "stage_center_scheduler_plist_sha256": EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256,
        "reimport_required_after_switch": False,
    }
    receipt_path = _record_operation("PREPARED", operation_dir, receipt_details)
    if _sha_file(ACTIVE_API_PLIST) != EXPECTED_ACTIVE_API_PLIST_SHA256 or _sha_file(STAGED_API_PLIST) != EXPECTED_STAGED_API_PLIST_SHA256:
        _record_operation("ABORTED_PREIMAGE_DRIFT", operation_dir, receipt_details)
        raise ValueError("API_ONLY_SWITCH_PREIMAGE_CHANGED_AFTER_PREFLIGHT")
    if _sha_file(ACTIVE_SCHEDULER_PLIST) != EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256:
        _record_operation("ABORTED_SCHEDULER_DRIFT", operation_dir, receipt_details)
        raise ValueError("SCHEDULER_PLIST_CHANGED_BEFORE_API_ONLY_SWITCH")
    if _sha_file(STAGE_CENTER_SCHEDULER_PLIST) != EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256:
        _record_operation("ABORTED_STAGE_CENTER_SCHEDULER_DRIFT", operation_dir, receipt_details)
        raise ValueError("STAGE_CENTER_SCHEDULER_PLIST_CHANGED_BEFORE_API_ONLY_SWITCH")
    replaced = False
    try:
        # Everything after bootout is inside this recovery guard. A launchctl
        # error is ambiguous: the service may already be unloaded, so recovery
        # first observes state and either accepts the still-running old API or
        # restores its exact preimage and bootstraps it once.
        if _sha_file(STAGE_CENTER_SCHEDULER_PLIST) != EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256:
            raise ValueError("STAGE_CENTER_SCHEDULER_PLIST_CHANGED_IMMEDIATELY_BEFORE_BOOTOUT")
        _launchctl("bootout")
        post_bootout_observation = _observe_loaded_api()
        if post_bootout_observation.get("state") != "NOT_LOADED":
            raise ValueError("API_ONLY_SWITCH_BOOTOUT_NOT_CONFIRMED:" + str(post_bootout_observation))
        post_bootout_raw = ACTIVE_API_PLIST.read_bytes()
        post_bootout_scheduler_sha = _sha_file(ACTIVE_SCHEDULER_PLIST)
        post_bootout_stage_sha = _sha_file(STAGE_CENTER_SCHEDULER_PLIST)
        post_bootout_xattrs = _xattr_snapshot(ACTIVE_API_PLIST)
        if (_sha(post_bootout_raw) != EXPECTED_ACTIVE_API_PLIST_SHA256
                or post_bootout_scheduler_sha != EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256
                or post_bootout_stage_sha != EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256
                or post_bootout_xattrs != _xattr_snapshot(STAGED_API_PLIST)):
            raise ValueError("API_ONLY_SWITCH_ABORTED_AFTER_BOOTOUT_PREIMAGE_DRIFT")
        _atomic_replace_bytes(ACTIVE_API_PLIST, staged_raw, ACTIVE_API_PLIST)
        replaced = True
        if _sha_file(ACTIVE_API_PLIST) != EXPECTED_STAGED_API_PLIST_SHA256:
            raise ValueError("API_ONLY_INSTALLED_PLIST_SHA_MISMATCH")
        _launchctl("bootstrap")
        expected_loaded = {"V35_APP_ROOT": str(API_ROOT), "V35_RELEASE_ID": EXPECTED_API_RELEASE_ID,
                           "V35_RELEASE_MANIFEST_SHA256": EXPECTED_API_MANIFEST_SHA256}
        verification = _wait_for_loaded(expected_loaded, require_import_route=True, timeout_s=60)
        if _sha_file(ACTIVE_SCHEDULER_PLIST) != EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256:
            raise ValueError("SCHEDULER_PLIST_CHANGED_DURING_API_ONLY_SWITCH")
        if _sha_file(STAGE_CENTER_SCHEDULER_PLIST) != EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256:
            raise ValueError("STAGE_CENTER_SCHEDULER_PLIST_CHANGED_DURING_API_ONLY_SWITCH")
        final_details = {**receipt_details, "installed_plist_sha256": EXPECTED_STAGED_API_PLIST_SHA256,
                         "runtime_verification": verification,
                         "post_bootout_observation": post_bootout_observation,
                         "stage_center_scheduler_post_sha256": EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256,
                         "owner_import_status": "NOT_RUN_BY_SWITCH_HELPER",
                         "ui_status": "NOT_VERIFIED_BY_SWITCH_HELPER"}
        final_receipt = _record_operation("API_ONLY_SWITCHED_ROUTE_VERIFIED", operation_dir, final_details)
        return {"status": "API_ONLY_SWITCHED_ROUTE_VERIFIED", "receipt_path": str(final_receipt), **final_details}
    except Exception as exc:
        rollback_result = _restore_after_failure(backup, source_raw, receipt_details, operation_dir,
                                                 was_replaced=replaced, original_error=str(exc))
        if rollback_result.get("status") != "ROLLED_BACK_TO_PREIMAGE":
            raise ValueError("API_ONLY_SWITCH_FAILED_ROLLBACK_INCOMPLETE:" + str(rollback_result.get("reason"))) from exc
        raise ValueError("API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK:" + str(exc)) from exc


def _wait_for_loaded(expected: Mapping[str, str], *, require_import_route: bool, timeout_s: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            result = _verify_loaded(expected, require_import_route=require_import_route)
            result["verification_attempts_bounded"] = True
            return result
        except (ValueError, OSError) as exc:
            last_error = str(exc)
            time.sleep(1)
    raise ValueError("API_ONLY_RUNTIME_VERIFICATION_TIMEOUT:" + str(last_error))


def _restore_after_failure(backup: Path, original_raw: bytes, details: Mapping[str, Any],
                           operation_dir: Path, *, was_replaced: bool,
                           original_error: str) -> dict[str, Any]:
    try:
        if _sha(original_raw) != EXPECTED_ACTIVE_API_PLIST_SHA256:
            raise ValueError("API_ONLY_ROLLBACK_PREIMAGE_CONTENT_MISMATCH")
        if _sha_file(backup) != EXPECTED_ACTIVE_API_PLIST_SHA256:
            raise ValueError("API_ONLY_ROLLBACK_BACKUP_SHA_MISMATCH")
        old_plist = plistlib.loads(original_raw)
        old_env, _ = _parse_assignments(old_plist)
        expected_old = {"V35_APP_ROOT": old_env["V35_APP_ROOT"],
                        "V35_RELEASE_ID": old_env["V35_RELEASE_ID"],
                        "V35_RELEASE_MANIFEST_SHA256": old_env["V35_RELEASE_MANIFEST_SHA256"]}

        def active_plist_sha() -> str | None:
            try:
                return _sha_file(ACTIVE_API_PLIST)
            except OSError:
                return None

        observed = _observe_loaded_api()
        current_sha = active_plist_sha()
        if (observed.get("state") == "LOADED" and observed.get("identity") == expected_old
                and current_sha == EXPECTED_ACTIVE_API_PLIST_SHA256):
            verification = _wait_for_loaded(expected_old, require_import_route=False, timeout_s=30)
            stage_sha = active_plist_sha_or_none(STAGE_CENTER_SCHEDULER_PLIST)
            result = {"status": "ROLLED_BACK_TO_PREIMAGE", "runtime_verification": verification,
                      "original_error": original_error, "recovery_action": "OLD_API_REMAINS_LOADED",
                      "stage_center_scheduler_post_sha256": stage_sha or "CANNOT_CONFIRM",
                      "stage_center_scheduler_guard": _stage_center_guard_status(stage_sha)}
            _record_operation("ROLLED_BACK_TO_PREIMAGE", operation_dir, {**dict(details), **result})
            return result

        # A nonzero bootout can mean either "still loaded" or "already unloaded".
        # Only write the plist after observing that it is unloaded. If the query
        # itself is unavailable, make one bounded bootout attempt and query once.
        if observed.get("state") != "NOT_LOADED":
            bootout_error: str | None = None
            try:
                if active_plist_sha_or_none(STAGE_CENTER_SCHEDULER_PLIST) != EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256:
                    raise ValueError("STAGE_CENTER_SCHEDULER_PLIST_CHANGED_BEFORE_RECOVERY_BOOTOUT")
                _launchctl("bootout")
            except Exception as exc:
                bootout_error = str(exc)
            observed = _observe_loaded_api()
            if observed.get("state") != "NOT_LOADED":
                current_sha = active_plist_sha()
                if (observed.get("state") == "LOADED" and observed.get("identity") == expected_old
                        and current_sha == EXPECTED_ACTIVE_API_PLIST_SHA256):
                    verification = _wait_for_loaded(expected_old, require_import_route=False, timeout_s=30)
                    result = {"status": "ROLLED_BACK_TO_PREIMAGE", "runtime_verification": verification,
                              "original_error": original_error, "recovery_action": "OLD_API_REMAINS_LOADED",
                              "bootout_error": bootout_error,
                              "stage_center_scheduler_post_sha256": active_plist_sha_or_none(STAGE_CENTER_SCHEDULER_PLIST) or "CANNOT_CONFIRM",
                              "stage_center_scheduler_guard": _stage_center_guard_status(active_plist_sha_or_none(STAGE_CENTER_SCHEDULER_PLIST))}
                    _record_operation("ROLLED_BACK_TO_PREIMAGE", operation_dir, {**dict(details), **result})
                    return result
                raise ValueError("API_ONLY_ROLLBACK_COULD_NOT_CONFIRM_JOB_UNLOADED:" + str(observed))

        current_sha = active_plist_sha()
        if current_sha not in {None, EXPECTED_ACTIVE_API_PLIST_SHA256,
                               EXPECTED_STAGED_API_PLIST_SHA256}:
            raise ValueError("API_ONLY_ROLLBACK_ACTIVE_PLIST_UNEXPECTED_SHA")
        if was_replaced or current_sha != EXPECTED_ACTIVE_API_PLIST_SHA256:
            _atomic_replace_bytes(ACTIVE_API_PLIST, original_raw, backup)
        if _sha_file(ACTIVE_API_PLIST) != EXPECTED_ACTIVE_API_PLIST_SHA256:
            raise ValueError("API_ONLY_ROLLBACK_PREIMAGE_RESTORE_FAILED")
        bootstrap_error: str | None = None
        try:
            _launchctl("bootstrap")
        except Exception as exc:
            bootstrap_error = str(exc)
            observed = _observe_loaded_api()
            if observed.get("state") != "LOADED" or observed.get("identity") != expected_old:
                raise ValueError("API_ONLY_ROLLBACK_BOOTSTRAP_STATE_UNRESOLVED:" + bootstrap_error) from exc
        verification = _wait_for_loaded(expected_old, require_import_route=False, timeout_s=60)
        stage_sha = active_plist_sha_or_none(STAGE_CENTER_SCHEDULER_PLIST)
        result = {"status": "ROLLED_BACK_TO_PREIMAGE", "runtime_verification": verification,
                  "original_error": original_error, "recovery_action": "PREIMAGE_RESTORED_AND_BOOTSTRAPPED",
                  "bootstrap_error": bootstrap_error,
                  "stage_center_scheduler_post_sha256": stage_sha or "CANNOT_CONFIRM",
                  "stage_center_scheduler_guard": _stage_center_guard_status(stage_sha)}
        _record_operation("ROLLED_BACK_TO_PREIMAGE", operation_dir, {**dict(details), **result})
        return result
    except Exception as rollback_exc:
        stage_sha = active_plist_sha_or_none(STAGE_CENTER_SCHEDULER_PLIST)
        result = {"status": "ROLLBACK_INCOMPLETE", "reason": str(rollback_exc),
                  "original_error": original_error,
                  "active_api_plist_sha256": active_plist_sha_or_none(ACTIVE_API_PLIST),
                  "stage_center_scheduler_post_sha256": stage_sha or "CANNOT_CONFIRM",
                  "stage_center_scheduler_guard": _stage_center_guard_status(stage_sha),
                  "backup_path": str(backup), "backup_sha256": active_plist_sha_or_none(backup)}
        _record_operation("ROLLBACK_INCOMPLETE", operation_dir, {**dict(details), **result})
        return result


def _stage_center_guard_status(observed_sha: str | None) -> str:
    if observed_sha is None:
        return "CANNOT_CONFIRM"
    return "UNCHANGED" if observed_sha == EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256 else "DRIFTED_EXTERNAL_STATE"


def _run_rollback(*, receipt_path: Path, confirmation: str, expected_current_sha: str) -> dict[str, Any]:
    if confirmation != CONFIRM_ROLLBACK:
        raise ValueError("EXPLICIT_API_ONLY_ROLLBACK_CONFIRMATION_REQUIRED")
    if expected_current_sha != EXPECTED_STAGED_API_PLIST_SHA256:
        raise ValueError("API_ONLY_ROLLBACK_EXPECTED_SHA_ARGUMENT_MISMATCH")
    resolved_task = TASK_ROOT.resolve(strict=True)
    if receipt_path.is_symlink() or not receipt_path.is_file() or resolved_task not in receipt_path.resolve(strict=True).parents:
        raise ValueError("API_ONLY_ROLLBACK_RECEIPT_OUTSIDE_TASK_ROOT")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    unsigned_receipt = dict(receipt)
    claimed_receipt_sha = unsigned_receipt.pop("receipt_sha256", None)
    actual_receipt_sha = _sha(json.dumps(unsigned_receipt, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8"))
    if claimed_receipt_sha != actual_receipt_sha:
        raise ValueError("API_ONLY_ROLLBACK_RECEIPT_SHA_MISMATCH")
    if (receipt.get("schema_version") != "v4.manager_daily_chain.api_only_switch.v1"
            or receipt.get("status") != "API_ONLY_SWITCHED_ROUTE_VERIFIED"
            or receipt.get("candidate_release_manifest_sha256") != EXPECTED_API_MANIFEST_SHA256
            or receipt.get("candidate_plist_sha256") != EXPECTED_STAGED_API_PLIST_SHA256
            or receipt.get("scheduler_plist_sha256") != EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256
            or receipt.get("stage_center_scheduler_plist_sha256") != EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256):
        raise ValueError("API_ONLY_ROLLBACK_RECEIPT_IDENTITY_INVALID")
    backup = Path(str(receipt.get("backup_path", "")))
    if (backup.is_symlink() or not backup.is_file() or backup.resolve(strict=True).parent != receipt_path.resolve(strict=True).parent
            or _sha_file(backup) != EXPECTED_ACTIVE_API_PLIST_SHA256):
        raise ValueError("API_ONLY_ROLLBACK_BACKUP_INVALID")
    if _sha_file(ACTIVE_API_PLIST) != EXPECTED_STAGED_API_PLIST_SHA256:
        raise ValueError("API_ONLY_ROLLBACK_CURRENT_PLIST_PREIMAGE_MISMATCH")
    if _sha_file(ACTIVE_SCHEDULER_PLIST) != EXPECTED_ACTIVE_SCHEDULER_PLIST_SHA256:
        raise ValueError("API_ONLY_ROLLBACK_SCHEDULER_PREIMAGE_MISMATCH")
    if _sha_file(STAGE_CENTER_SCHEDULER_PLIST) != EXPECTED_STAGE_CENTER_SCHEDULER_PLIST_SHA256:
        raise ValueError("API_ONLY_ROLLBACK_STAGE_CENTER_SCHEDULER_PREIMAGE_MISMATCH")
    expected_candidate = {"V35_APP_ROOT": str(API_ROOT), "V35_RELEASE_ID": EXPECTED_API_RELEASE_ID,
                         "V35_RELEASE_MANIFEST_SHA256": EXPECTED_API_MANIFEST_SHA256}
    if _loaded_identity(_launchctl_print()) != expected_candidate:
        raise ValueError("API_ONLY_ROLLBACK_LOADED_RUNTIME_NOT_CANDIDATE")
    operation_root = TASK_ROOT / "writer/api_only_switch_runs"
    rollback_dir = operation_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-rollback-" + uuid.uuid4().hex[:8])
    rollback_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    _write_json_exclusive(rollback_dir / "rollback_of.json", {"source_receipt": str(receipt_path),
        "source_receipt_sha256": _sha_file(receipt_path), "backup_path": str(backup),
        "expected_current_plist_sha256": EXPECTED_STAGED_API_PLIST_SHA256})
    original_raw = backup.read_bytes()
    if _sha(original_raw) != EXPECTED_ACTIVE_API_PLIST_SHA256:
        raise ValueError("API_ONLY_ROLLBACK_BACKUP_CONTENT_MISMATCH")
    return _restore_after_failure(backup, original_raw, receipt, rollback_dir,
                                  was_replaced=True, original_error="OPERATOR_REQUESTED_ROLLBACK")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="read-only SHA, plist, runtime and loaded-job checks")
    execute = sub.add_parser("execute", help="replace API-only plist, reload only that LaunchAgent, verify import route")
    execute.add_argument("--confirm", required=True)
    execute.add_argument("--expected-current-plist-sha256", required=True)
    execute.add_argument("--expected-staged-plist-sha256", required=True)
    rollback = sub.add_parser("rollback", help="restore the exact API plist backup recorded by a successful switch")
    rollback.add_argument("--receipt", required=True, type=Path)
    rollback.add_argument("--confirm", required=True)
    rollback.add_argument("--expected-current-plist-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            result = _preflight()
        elif args.command == "execute":
            with _switch_lock():
                result = _run_switch(confirmation=args.confirm,
                    expected_current_sha=args.expected_current_plist_sha256,
                    expected_staged_sha=args.expected_staged_plist_sha256)
        else:
            with _switch_lock():
                result = _run_rollback(receipt_path=args.receipt, confirmation=args.confirm,
                    expected_current_sha=args.expected_current_plist_sha256)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        mutable = args.command in {"execute", "rollback"}
        print(json.dumps({"status": "FAILED_CLOSED", "reason": str(exc),
                          "live_state_after_error": "CANNOT_CONFIRM" if mutable else "UNCHANGED",
                          "live_api_or_scheduler_changed": "CANNOT_CONFIRM" if mutable else False},
                         ensure_ascii=False, sort_keys=True))
        return 2


@contextmanager
def _switch_lock():
    lock_path = TASK_ROOT / "writer/.api_only_switch.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("API_ONLY_SWITCH_ALREADY_RUNNING") from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main())
