#!/usr/bin/env python3
"""Guarded API-only switch for the reviewed manager-workbench R1 release.

This is adapted from the independently reviewed R3 API-only switch helper at
V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/candidate/analysis-readback-compat/helpers/switch_api_only_announcement.py.
The adaptation adds an on-disk and loopback readback of the manager-selection
frontend bundle. It can write only the API LaunchAgent plist and its own
operation receipts/backups. The scheduler, plan binding, and manager state are
read-only. The default `plan` command performs no runtime reads or writes.
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
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

sys.dont_write_bytecode = True

TASK_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = TASK_ROOT / "phase2/drafts/api_only_cutover_plan.json"
STAGED_API_PLIST_PATH = TASK_ROOT / "phase2/drafts/com.lexi.v35.api-only.plist"
STAGED_API_PLIST_DIFF_PATH = TASK_ROOT / "phase2/drafts/staged_api_plist_diff.json"
RELEASE_STAGE_RECEIPT_PATH = TASK_ROOT / "phase2/receipts/api_release_stage_receipt.json"
PRODUCT_BASELINE_PATH = TASK_ROOT / "control/pre_switch_product_baseline.json"
PRODUCT_BASELINE_SHA256 = "c511e4c0241e7f98820aeba0e763a967223da1af454d14c6bac89c6fe8d49c31"
EXPECTED_RELEASE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-api"
)
EXPECTED_API_ROOT = EXPECTED_RELEASE_ROOT / "app"
EXPECTED_API_INVENTORY_SHA256 = "0f2e6752b55430dd556d212739a9de4b2176acc92f95fc15b45ec342cb2b3771"
EXPECTED_DIST_TREE_SHA256 = "38f0d0195385ed9cf5ce8943e15a81a9b1ef4813c7a1cd5e4359386e76917234"
INVENTORY_BACKEND_PATH = TASK_ROOT / "candidate/api/app/ops/build_release_candidate.py"
P2_REVIEW_PATH = TASK_ROOT / "review/p2_delta_independent_review.json"
P2_REVIEW_SHA256 = "0cf607eecc19a73d21eafef653b69ff9f9716c286198de05c272f47aa5d58084"
P2_DELTA_RECEIPT_PATH = TASK_ROOT / "receipts/p2_delta_receipt.json"
P2_DELTA_RECEIPT_SHA256 = "04535f6bc8c7b97cf585661c96b9327d3928876ffed314725dd2c8ea5f76b547"
API_INVENTORY_RECEIPT_PATH = TASK_ROOT / "receipts/api_candidate_p2_delta.json"
API_INVENTORY_RECEIPT_SHA256 = "164411c9abeab5fb8726776c09274254d01f2199e483b182770d18def0eda58c"
ACTIVE_API_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
ACTIVE_SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
STAGE_CENTER_SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist")
DISABLED_BINDING_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/staged_config/manager-plan-binding-c1.disabled.final-d1-r2.json"
)
SCREEN_AUTHORITY_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/"
    "v3_shared_data/.runtime/data"
)
FORMAL_MANAGER_STATE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research"
)
PINNED_PYTHON = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
)
LAUNCHCTL = Path("/bin/launchctl")
LABEL = "com.lexi.v35.api-only"
BASE_URL = "http://127.0.0.1:8873"
OPENAPI_URL = BASE_URL + "/openapi.json"
MANAGER_WORKSPACE_ROUTE = "/api/v4/manager/research/workspace"
MANAGER_SELECTION_HTML = "/manager-selection/"
CONFIRM_SWITCH = "SWITCH_API_ONLY_TO_MANAGER_WORKBENCH_R1_20261008"
CONFIRM_ROLLBACK = "ROLLBACK_API_ONLY_TO_RECORDED_PREIMAGE"
PLAN_SCHEMA = "v4.manager_workbench_r1_mac.api_only_cutover_plan.v1"
RECEIPT_SCHEMA = "v4.manager_workbench_r1_mac.api_only_cutover.v1"
CONSUMPTION_VALIDATION_SCHEMA = "v4.manager_research.announcement_analysis_consumption.v1"
CONSUMPTION_VALIDATION_CANONICAL_SHA256 = {
    "current_analysis": "796e437a76c1a40acf7ade7c1bac64be53c7aaa4cd21e387d3ca7e3e2c72aee9",
    "legacy_analysis": "25ed3622660ce7602bb782257cf3b85d7346c1c7838e8fc1488b9dbf245ab726",
}
CONSUMPTION_VALIDATION_KEYS = frozenset({
    "schema_version", "target_trade_date", "publication_date", "status", "validation_status",
    "consumed", "product_sha256", "source_manifest_sha256", "catalog_product_sha256",
    "source_run_id", "evidence_run_id", "handoff_manifest_sha256",
    "agent_judgment_receipt_sha256", "owner_import_receipt_sha256",
    "owner_handoff_binding_status", "decision_status", "selection_status", "stock_count",
    "selected_stock_count", "conditional_watch_count", "not_selected_stock_count",
    "not_assessed_stock_count", "reviewed_at", "owner_available_at", "latest_source_or_review_at",
    "plan_cutoff", "cutoff_status", "failure_stage", "gaps", "research_references",
    "RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent",
})
SAFETY_EXPECTED = {
    "RESEARCH_ONLY": "1",
    "production_allowed": "false",
    "PRODUCTION_ALLOWED": "false",
    "buy_gate_updated": "false",
    "BUY_GATE_UPDATED": "false",
    "orders_sent": "false",
    "ORDERS_SENT": "false",
}
ALLOWED_ENV_CHANGES = {
    "V35_APP_ROOT",
    "V35_RELEASE_ID",
    "V35_RELEASE_MANIFEST_PATH",
    "V35_RELEASE_MANIFEST_SHA256",
    "PYTHONPATH",
}
REQUIRED_ENV_CHANGES = set(ALLOWED_ENV_CHANGES)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha(path.read_bytes())


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8"))


def _consumption_validation_sha(value: Mapping[str, Any]) -> str:
    """Hash the projection using the API's source-order compact JSON bytes.

    The frozen R3-compatible pins were derived by the original readback probe
    without sorting object keys. Keep this serializer separate from the
    sorted canonical format used for internal plans and operation receipts.
    """
    return _sha(json.dumps(value, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8"))


def _regular_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(label + "_NOT_EXACT_REGULAR_FILE")
    return path.read_bytes()


def _exact_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        raise ValueError(label + "_NOT_EXACT_DIRECTORY")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(_regular_file(path, label).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(label + "_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError(label + "_JSON_OBJECT_REQUIRED")
    return value


def _load_plan(path: Path = PLAN_PATH) -> dict[str, Any]:
    value = _read_json(path, "API_ONLY_PLAN")
    if value.get("schema_version") != PLAN_SCHEMA:
        raise ValueError("API_ONLY_PLAN_SCHEMA_MISMATCH")
    if value.get("task_root") != str(TASK_ROOT):
        raise ValueError("API_ONLY_PLAN_TASK_ROOT_MISMATCH")
    target = value.get("target")
    if not isinstance(target, dict):
        raise ValueError("API_ONLY_PLAN_TARGET_MISSING")
    if (target.get("release_root") != str(EXPECTED_RELEASE_ROOT)
            or target.get("app_root") != str(EXPECTED_API_ROOT)):
        raise ValueError("API_ONLY_PLAN_TARGET_ROOT_MISMATCH")
    if target.get("release_id") != EXPECTED_RELEASE_ROOT.name:
        raise ValueError("API_ONLY_PLAN_RELEASE_ID_MISMATCH")
    if target.get("application_inventory_sha256") != EXPECTED_API_INVENTORY_SHA256:
        raise ValueError("API_ONLY_PLAN_INVENTORY_PIN_MISMATCH")
    before = value.get("before")
    guards = value.get("guards")
    source = value.get("source")
    if not all(isinstance(item, dict) for item in (before, guards, source)):
        raise ValueError("API_ONLY_PLAN_GUARD_OR_SOURCE_MISSING")
    fixed_paths = {
        "target.staged_api_plist_path": target.get("staged_api_plist_path"),
        "target.staged_api_plist_diff_path": target.get("staged_api_plist_diff_path"),
        "before.active_api_plist_path": before.get("active_api_plist_path"),
        "before.scheduler_plist_path": before.get("scheduler_plist_path"),
        "before.stage_center_scheduler_plist_path": before.get("stage_center_scheduler_plist_path"),
        "guards.disabled_binding_path": guards.get("disabled_binding_path"),
        "guards.formal_manager_state_root": guards.get("formal_manager_state_root"),
        "guards.scheduler_plist_path": guards.get("scheduler_plist_path"),
        "guards.stage_center_scheduler_plist_path": guards.get("stage_center_scheduler_plist_path"),
        "source.source_candidate_app_root": source.get("source_candidate_app_root"),
        "source.inventory_backend_path": source.get("inventory_backend_path"),
        "source.p2_independent_review_receipt": source.get("p2_independent_review_receipt"),
        "source.p2_delta_receipt": source.get("p2_delta_receipt"),
        "source.candidate_inventory_receipt": source.get("candidate_inventory_receipt"),
        "source.release_stage_receipt": source.get("release_stage_receipt"),
        "source.pre_switch_product_baseline": source.get("pre_switch_product_baseline"),
    }
    expected_paths = {
        "target.staged_api_plist_path": str(STAGED_API_PLIST_PATH),
        "target.staged_api_plist_diff_path": str(STAGED_API_PLIST_DIFF_PATH),
        "before.active_api_plist_path": str(ACTIVE_API_PLIST),
        "before.scheduler_plist_path": str(ACTIVE_SCHEDULER_PLIST),
        "before.stage_center_scheduler_plist_path": str(STAGE_CENTER_SCHEDULER_PLIST),
        "guards.disabled_binding_path": str(DISABLED_BINDING_PATH),
        "guards.formal_manager_state_root": str(FORMAL_MANAGER_STATE),
        "guards.scheduler_plist_path": str(ACTIVE_SCHEDULER_PLIST),
        "guards.stage_center_scheduler_plist_path": str(STAGE_CENTER_SCHEDULER_PLIST),
        "source.source_candidate_app_root": str(TASK_ROOT / "candidate/api/app"),
        "source.inventory_backend_path": str(INVENTORY_BACKEND_PATH),
        "source.p2_independent_review_receipt": "review/p2_delta_independent_review.json",
        "source.p2_delta_receipt": "receipts/p2_delta_receipt.json",
        "source.candidate_inventory_receipt": "receipts/api_candidate_p2_delta.json",
        "source.release_stage_receipt": "phase2/receipts/api_release_stage_receipt.json",
        "source.pre_switch_product_baseline": "control/pre_switch_product_baseline.json",
    }
    for key, observed in fixed_paths.items():
        if observed != expected_paths[key]:
            raise ValueError("API_ONLY_PLAN_PATH_PIN_MISMATCH:" + key)
    if (source.get("p2_independent_review_sha256") != P2_REVIEW_SHA256
            or source.get("p2_delta_receipt_sha256") != P2_DELTA_RECEIPT_SHA256
            or source.get("candidate_inventory_receipt_sha256") != API_INVENTORY_RECEIPT_SHA256):
        raise ValueError("API_ONLY_PLAN_SOURCE_RECEIPT_SHA_PIN_MISMATCH")
    if source.get("pre_switch_product_baseline_sha256") != PRODUCT_BASELINE_SHA256:
        raise ValueError("API_ONLY_PLAN_PRODUCT_BASELINE_SHA_PIN_MISMATCH")
    release_stage_sha = source.get("release_stage_receipt_sha256")
    if not isinstance(release_stage_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", release_stage_sha):
        raise ValueError("API_ONLY_PLAN_RELEASE_STAGE_RECEIPT_SHA_NOT_FROZEN")
    if not isinstance(target.get("release_manifest_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", target["release_manifest_sha256"]):
        raise ValueError("API_ONLY_PLAN_RELEASE_MANIFEST_SHA_NOT_FROZEN")
    for key in ("staged_api_plist_sha256", "staged_api_plist_diff_sha256"):
        artifact_sha = target.get(key)
        if artifact_sha is not None and (not isinstance(artifact_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha)):
            raise ValueError("API_ONLY_PLAN_STAGED_ARTIFACT_SHA_INVALID:" + key)
    allowed = [str(ACTIVE_API_PLIST), str(TASK_ROOT / "phase2/receipts/api_only_switch_runs"),
               str(EXPECTED_RELEASE_ROOT), str(STAGED_API_PLIST_PATH),
               str(STAGED_API_PLIST_DIFF_PATH), str(PLAN_PATH), str(RELEASE_STAGE_RECEIPT_PATH)]
    if value.get("allowed_paths") != allowed:
        raise ValueError("API_ONLY_PLAN_ALLOWED_PATHS_MISMATCH")
    return value


def _split_env_arguments(plist_value: Mapping[str, Any]) -> tuple[list[str], dict[str, str], list[Any]]:
    arguments = plist_value.get("ProgramArguments")
    if not isinstance(arguments, list) or not arguments or arguments[0] != "/usr/bin/env":
        raise ValueError("API_ONLY_PLIST_ENV_WRAPPER_INVALID")
    prefix: list[str] = []
    environment: dict[str, str] = {}
    command: list[Any] = []
    passed_assignments = False
    for item in arguments[1:]:
        if not passed_assignments and isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            if key and not any(char.isspace() for char in key):
                if key in environment:
                    raise ValueError("API_ONLY_PLIST_DUPLICATE_ENV_KEY:" + key)
                prefix.append(key)
                environment[key] = value
                continue
        passed_assignments = True
        command.append(item)
    if not command or command[0] != str(PINNED_PYTHON):
        raise ValueError("API_ONLY_PYTHON_ENTRYPOINT_MISMATCH")
    return prefix, environment, command


def _identity_from_plist(raw: bytes) -> dict[str, str]:
    value = plistlib.loads(raw)
    _prefix, environment, _command = _split_env_arguments(value)
    keys = ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")
    identity = {key: environment.get(key, "") for key in keys}
    if any(not item for item in identity.values()):
        raise ValueError("API_ONLY_PLIST_RUNTIME_IDENTITY_UNAVAILABLE")
    return identity


def _candidate_plist_bytes(active_raw: bytes, plan: Mapping[str, Any],
                           candidate: Mapping[str, Any]) -> bytes:
    current = plistlib.loads(active_raw)
    if (current.get("Label") != LABEL or current.get("KeepAlive") is not True
            or current.get("RunAtLoad") is not False):
        raise ValueError("API_ONLY_LAUNCH_AGENT_POLICY_MISMATCH")
    prefix, old_env, command = _split_env_arguments(current)
    if old_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(DISABLED_BINDING_PATH):
        raise ValueError("API_ONLY_ORIGINAL_DISABLED_BINDING_PATH_MISMATCH")
    if old_env.get("V4_MANAGER_SCREEN_AUTHORITY_ROOT") != str(SCREEN_AUTHORITY_ROOT):
        raise ValueError("API_ONLY_ORIGINAL_SCREEN_AUTHORITY_ROOT_MISMATCH")
    expected_before = plan.get("before", {}).get("loaded_identity", {})
    if any(old_env.get(key) != expected_before.get(key) for key in (
            "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")):
        raise ValueError("API_ONLY_ORIGINAL_RELEASE_IDENTITY_MISMATCH")
    if current.get("WorkingDirectory") != old_env.get("V35_APP_ROOT"):
        raise ValueError("API_ONLY_ORIGINAL_WORKING_DIRECTORY_MISMATCH")
    candidate_root = Path(str(plan["target"]["app_root"]))
    manifest_path = Path(str(candidate["manifest_path"]))
    new_env = {
        **old_env,
        "V35_APP_ROOT": str(candidate_root),
        "V35_RELEASE_ID": str(plan["target"]["release_id"]),
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": str(candidate["manifest_sha256"]),
        "PYTHONPATH": f"{candidate_root / 'upstreams'}:{candidate_root}",
    }
    missing = sorted(set(ALLOWED_ENV_CHANGES) - set(old_env))
    if missing:
        raise ValueError("API_ONLY_REQUIRED_ENV_KEYS_MISSING:" + ",".join(missing))
    for key, expected in SAFETY_EXPECTED.items():
        if new_env.get(key) != expected:
            raise ValueError("API_ONLY_SAFETY_FLAG_MISMATCH:" + key)
    if {k: v for k, v in old_env.items() if k not in ALLOWED_ENV_CHANGES} != {
            k: v for k, v in new_env.items() if k not in ALLOWED_ENV_CHANGES}:
        raise ValueError("API_ONLY_PRESERVED_ENVIRONMENT_CHANGED")
    current["ProgramArguments"] = ["/usr/bin/env", *[f"{key}={new_env[key]}" for key in prefix], *command]
    current["WorkingDirectory"] = str(candidate_root)
    return plistlib.dumps(current, fmt=plistlib.FMT_XML, sort_keys=True)


def _staged_plist_diff(active_raw: bytes, staged_raw: bytes,
                       candidate: Mapping[str, Any]) -> dict[str, Any]:
    active = plistlib.loads(active_raw)
    staged = plistlib.loads(staged_raw)
    old_prefix, old_env, old_command = _split_env_arguments(active)
    new_prefix, new_env, new_command = _split_env_arguments(staged)
    if old_prefix != new_prefix or old_command != new_command:
        raise ValueError("API_ONLY_STAGED_PLIST_CHANGED_LAUNCH_ARGUMENT_SHAPE")
    changed_keys = sorted(key for key in set(old_env) | set(new_env)
                          if old_env.get(key) != new_env.get(key))
    if set(changed_keys) != REQUIRED_ENV_CHANGES:
        raise ValueError("API_ONLY_STAGED_PLIST_ENVIRONMENT_DELTA_MISMATCH:" + ",".join(changed_keys))
    if old_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(DISABLED_BINDING_PATH) \
            or new_env.get("V4_MANAGER_PLAN_OWNER_BINDING_PATH") != str(DISABLED_BINDING_PATH):
        raise ValueError("API_ONLY_STAGED_PLIST_DISABLED_BINDING_CHANGED")
    if (old_env.get("V4_MANAGER_SCREEN_AUTHORITY_ROOT") != str(SCREEN_AUTHORITY_ROOT)
            or new_env.get("V4_MANAGER_SCREEN_AUTHORITY_ROOT") != str(SCREEN_AUTHORITY_ROOT)):
        raise ValueError("API_ONLY_STAGED_PLIST_SCREEN_AUTHORITY_CHANGED")
    before_top = {key: value for key, value in active.items()
                  if key not in {"ProgramArguments", "WorkingDirectory"}}
    after_top = {key: value for key, value in staged.items()
                 if key not in {"ProgramArguments", "WorkingDirectory"}}
    if before_top != after_top:
        raise ValueError("API_ONLY_STAGED_PLIST_OTHER_KEY_CHANGED")
    if active.get("WorkingDirectory") != old_env.get("V35_APP_ROOT"):
        raise ValueError("API_ONLY_STAGED_PLIST_PREIMAGE_WORKDIR_MISMATCH")
    expected_new = str(candidate["app_root"])
    if staged.get("WorkingDirectory") != expected_new:
        raise ValueError("API_ONLY_STAGED_PLIST_WORKDIR_MISMATCH")
    changes = [{"key": key, "before": old_env[key], "after": new_env[key]}
               for key in changed_keys]
    preserved_keys = ("V4_MANAGER_PLAN_OWNER_BINDING_PATH",
                      "V4_MANAGER_SCREEN_AUTHORITY_ROOT",
                      "V4_MANAGER_RESEARCH_STATE_ROOT")
    return {
        "schema_version": "v4.manager_workbench_r1_mac.staged_api_plist_diff.v1",
        "changed_top_level_fields": ["ProgramArguments", "WorkingDirectory"],
        "changed_environment": changes,
        "changed_plist_keys": [{"key": "WorkingDirectory",
                                 "before": active.get("WorkingDirectory"),
                                 "after": staged.get("WorkingDirectory")}],
        "preserved_runtime_bindings": {
            key: {"before": old_env.get(key), "after": new_env.get(key), "unchanged": old_env.get(key) == new_env.get(key)}
            for key in preserved_keys if key in old_env or key in new_env
        },
        "disabled_binding": {"path": str(DISABLED_BINDING_PATH),
                             "sha256": _sha_file(DISABLED_BINDING_PATH),
                             "enabled": False, "announcement_collection_enabled": False},
        "release_identity": {"release_id": candidate["release_id"],
                             "release_manifest_sha256": candidate["manifest_sha256"]},
        "staged_api_plist_sha256": _sha(staged_raw),
    }


def _load_inventory_backend(plan: Mapping[str, Any]) -> Any:
    path = Path(str(plan["source"]["inventory_backend_path"]))
    if path != INVENTORY_BACKEND_PATH:
        raise ValueError("INVENTORY_BACKEND_PATH_MISMATCH")
    raw = _regular_file(path, "INVENTORY_BACKEND")
    if _sha(raw) != plan["source"].get("inventory_backend_sha256"):
        raise ValueError("INVENTORY_BACKEND_SHA_MISMATCH")
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("_r1_api_release_inventory", path)
    if spec is None or spec.loader is None:
        raise ValueError("INVENTORY_BACKEND_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "inventory_tree", None)) or not callable(getattr(module, "inventory_digest", None)):
        raise ValueError("INVENTORY_BACKEND_INTERFACE_INVALID")
    return module


class _AssetReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key in {"src", "href"} and value and value.startswith("/"):
                path = urlsplit(value).path
                if path.startswith("/assets/"):
                    self.references.add(path)


def _validate_frontend_dist(app_root: Path, inventory_entries: list[dict[str, Any]]) -> dict[str, Any]:
    dist = app_root / "apps/web/dist"
    _exact_directory(dist, "API_FRONTEND_DIST")
    html_path = dist / "manager-selection/index.html"
    html_raw = _regular_file(html_path, "MANAGER_SELECTION_INDEX")
    parser = _AssetReferences()
    parser.feed(html_raw.decode("utf-8"))
    refs = sorted(parser.references)
    if not refs:
        raise ValueError("MANAGER_SELECTION_ASSETS_MISSING")
    inventory_paths = {str(row.get("path")) for row in inventory_entries}
    verified: list[dict[str, str]] = []
    for ref in refs:
        relative = ref.lstrip("/")
        file_path = dist / relative
        raw = _regular_file(file_path, "MANAGER_SELECTION_ASSET")
        inventory_rel = "apps/web/dist/" + relative
        if inventory_rel not in inventory_paths:
            raise ValueError("MANAGER_SELECTION_ASSET_NOT_IN_RELEASE_INVENTORY:" + relative)
        verified.append({"url_path": ref, "sha256": _sha(raw)})
    if "apps/web/dist/manager-selection/index.html" not in inventory_paths:
        raise ValueError("MANAGER_SELECTION_INDEX_NOT_IN_RELEASE_INVENTORY")
    return {"index_sha256": _sha(html_raw), "index_path": str(html_path),
            "assets": verified, "asset_reference_count": len(verified)}


def _load_candidate_release(plan: Mapping[str, Any]) -> dict[str, Any]:
    target = plan["target"]
    release_root = Path(str(target["release_root"]))
    app_root = Path(str(target["app_root"]))
    manifest_path = release_root / "release-manifest.json"
    manifest_expected = target.get("release_manifest_sha256")
    if not isinstance(manifest_expected, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_expected):
        raise ValueError("R1_API_RELEASE_MANIFEST_SHA_NOT_FROZEN")
    _exact_directory(release_root, "R1_API_RELEASE_ROOT")
    _exact_directory(app_root, "R1_API_APP_ROOT")
    manifest_raw = _regular_file(manifest_path, "R1_API_RELEASE_MANIFEST")
    manifest_sha = _sha(manifest_raw)
    if manifest_sha != manifest_expected:
        raise ValueError("R1_API_RELEASE_MANIFEST_SHA_MISMATCH")
    manifest = json.loads(manifest_raw.decode("utf-8"))
    if (manifest.get("schema_version") != "v4.release_candidate.v1"
            or manifest.get("activation_status") != "NOT_ACTIVATED"
            or manifest.get("candidate", {}).get("release_id") != target.get("release_id")
            or manifest.get("candidate", {}).get("app_root") != str(app_root)):
        raise ValueError("R1_API_RELEASE_MANIFEST_IDENTITY_MISMATCH")
    inventory = manifest.get("application_inventory")
    if not isinstance(inventory, dict):
        raise ValueError("R1_API_RELEASE_INVENTORY_MISSING")
    expected_inventory_sha = target.get("application_inventory_sha256")
    if expected_inventory_sha != EXPECTED_API_INVENTORY_SHA256 or inventory.get("aggregate_sha256") != expected_inventory_sha:
        raise ValueError("R1_API_RELEASE_INVENTORY_PIN_MISMATCH")
    backend = _load_inventory_backend(plan)
    entries = backend.inventory_tree(app_root)
    inventory_sha = backend.inventory_digest(entries)
    if (inventory_sha != expected_inventory_sha or entries != inventory.get("entries")
            or inventory.get("entry_count") != len(entries)):
        raise ValueError("R1_API_APPLICATION_INVENTORY_DRIFT")
    source_root = Path(str(plan["source"]["source_candidate_app_root"]))
    if source_root != TASK_ROOT / "candidate/api/app":
        raise ValueError("R1_API_SOURCE_CANDIDATE_ROOT_MISMATCH")
    source_entries = backend.inventory_tree(source_root)
    source_inventory_sha = backend.inventory_digest(source_entries)
    if source_inventory_sha != expected_inventory_sha or source_entries != entries:
        raise ValueError("R1_API_SOURCE_CANDIDATE_DRIFT")
    api_receipt_path = TASK_ROOT / "receipts/api_candidate_p2_delta.json"
    if _sha_file(api_receipt_path) != API_INVENTORY_RECEIPT_SHA256:
        raise ValueError("R1_API_SOURCE_INVENTORY_RECEIPT_SHA_MISMATCH")
    api_receipt = _read_json(api_receipt_path, "R1_API_SOURCE_INVENTORY_RECEIPT")
    if api_receipt.get("aggregate_sha256") != expected_inventory_sha:
        raise ValueError("R1_API_SOURCE_INVENTORY_RECEIPT_PIN_MISMATCH")
    p2_receipt_path = TASK_ROOT / "receipts/p2_delta_receipt.json"
    if _sha_file(p2_receipt_path) != P2_DELTA_RECEIPT_SHA256:
        raise ValueError("R1_API_P2_DELTA_RECEIPT_SHA_MISMATCH")
    p2_receipt = _read_json(p2_receipt_path, "R1_API_P2_DELTA_RECEIPT")
    dist_sync = p2_receipt.get("dist_sync")
    if (not isinstance(dist_sync, dict) or dist_sync.get("same_paths_and_bytes") is not True
            or dist_sync.get("source_tree_sha256") != EXPECTED_DIST_TREE_SHA256
            or dist_sync.get("target_tree_sha256") != EXPECTED_DIST_TREE_SHA256):
        raise ValueError("R1_API_FRONTEND_DIST_SOURCE_SYNC_NOT_VERIFIED")
    frontend = _validate_frontend_dist(app_root, entries)
    stage_receipt_raw = _regular_file(RELEASE_STAGE_RECEIPT_PATH, "API_RELEASE_STAGE_RECEIPT")
    stage_receipt_sha = _sha(stage_receipt_raw)
    if stage_receipt_sha != plan["source"].get("release_stage_receipt_sha256"):
        raise ValueError("API_RELEASE_STAGE_RECEIPT_SHA_MISMATCH")
    stage_receipt = _read_json(RELEASE_STAGE_RECEIPT_PATH, "API_RELEASE_STAGE_RECEIPT")
    stage_unsigned = {key: value for key, value in stage_receipt.items() if key != "receipt_sha256"}
    if (stage_receipt.get("receipt_sha256") != _canonical_sha(stage_unsigned)
            or stage_receipt.get("status") != "STAGED_AND_VERIFIED_NOT_DEPLOYED"
            or stage_receipt.get("release_root") != str(release_root)
            or stage_receipt.get("release_manifest_sha256") != manifest_sha
            or stage_receipt.get("application_inventory_sha256") != inventory_sha
            or stage_receipt.get("application_inventory_entries") != len(entries)):
        raise ValueError("API_RELEASE_STAGE_RECEIPT_CONTENT_MISMATCH")
    return {"release_id": target["release_id"], "release_root": str(release_root),
            "app_root": str(app_root), "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_sha, "inventory_sha256": inventory_sha,
            "entry_count": len(entries), "frontend": frontend,
            "stage_receipt_path": str(RELEASE_STAGE_RECEIPT_PATH),
            "stage_receipt_sha256": stage_receipt_sha}


def _validate_p2_review(plan: Mapping[str, Any]) -> dict[str, Any]:
    if (plan["source"].get("p2_independent_review_sha256") != P2_REVIEW_SHA256
            or _sha_file(P2_REVIEW_PATH) != P2_REVIEW_SHA256):
        raise ValueError("P2_INDEPENDENT_REVIEW_SHA_MISMATCH")
    receipt = _read_json(P2_REVIEW_PATH, "P2_INDEPENDENT_REVIEW")
    status = receipt.get("status")
    if (not isinstance(status, dict) or status.get("REVIEWED") != "PASS"
            or not str(status.get("BEHAVIOR_VERIFIED", "")).startswith("PASS")):
        raise ValueError("P2_INDEPENDENT_REVIEW_NOT_PASS")
    return {"path": str(P2_REVIEW_PATH), "sha256": P2_REVIEW_SHA256,
            "reviewed": "PASS", "behavior_verified": "PASS"}


def _load_disabled_binding(plan: Mapping[str, Any]) -> dict[str, Any]:
    if str(DISABLED_BINDING_PATH) != plan["guards"].get("disabled_binding_path"):
        raise ValueError("DISABLED_BINDING_PATH_MISMATCH")
    raw = _regular_file(DISABLED_BINDING_PATH, "DISABLED_PLAN_BINDING")
    expected = plan["guards"].get("disabled_binding_sha256")
    if not isinstance(expected, str) or _sha(raw) != expected:
        raise ValueError("DISABLED_PLAN_BINDING_SHA_MISMATCH")
    binding = json.loads(raw.decode("utf-8"))
    if (binding.get("enabled") is not False
            or binding.get("announcement_collection_enabled") is not False
            or binding.get("plan_material_refresh_only") is not False
            or binding.get("manager_state_root") != str(FORMAL_MANAGER_STATE)):
        raise ValueError("API_ONLY_PLAN_BINDING_MUST_REMAIN_DISABLED")
    return {"path": str(DISABLED_BINDING_PATH), "sha256": expected,
            "enabled": False, "announcement_collection_enabled": False,
            "plan_material_refresh_only": False}


def _loaded_identity(output: str) -> dict[str, str]:
    state = re.search(r"(?m)^\s*state\s*=\s*(\S+)", output)
    pid = re.search(r"(?m)^\s*pid\s*=\s*(\d+)", output)
    if not state or state.group(1) != "running":
        raise ValueError("API_ONLY_LAUNCH_AGENT_NOT_RUNNING")
    identity: dict[str, str] = {"state": state.group(1)}
    if pid:
        identity["pid"] = pid.group(1)
    for key in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256"):
        match = re.search(rf"(?m)^\s*{re.escape(key)}=([^\r\n]+)", output)
        if match:
            identity[key] = match.group(1)
    if any(key not in identity for key in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")):
        raise ValueError("API_ONLY_LAUNCH_AGENT_RUNTIME_IDENTITY_UNAVAILABLE")
    return identity


def _launchctl_print() -> str:
    if not LAUNCHCTL.is_file():
        raise ValueError("LAUNCHCTL_NOT_AVAILABLE")
    result = subprocess.run([str(LAUNCHCTL), "print", f"gui/{os.getuid()}/{LABEL}"],
                            capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        detail = result.stderr.strip()[:240] or result.stdout.strip()[:240]
        lowered = detail.lower()
        if "could not find service" in lowered or "service not found" in lowered:
            raise ValueError("API_ONLY_LAUNCH_AGENT_NOT_LOADED:" + detail)
        raise ValueError("API_ONLY_LAUNCH_AGENT_PRINT_FAILED:" +
                         (detail or str(result.returncode)))
    return result.stdout


def _observe_loaded() -> dict[str, Any]:
    try:
        return {"state": "LOADED", "identity": _loaded_identity(_launchctl_print())}
    except ValueError as exc:
        message = str(exc)
        if message.startswith("API_ONLY_LAUNCH_AGENT_NOT_LOADED:"):
            return {"state": "NOT_LOADED", "identity": None}
        if message == "API_ONLY_LAUNCH_AGENT_NOT_RUNNING":
            return {"state": "LOADED_UNVERIFIED", "identity": None, "error": message}
        return {"state": "UNKNOWN", "identity": None, "error": message[:300]}


def _launchctl_action(action: str) -> None:
    if action not in {"bootout", "bootstrap"}:
        raise ValueError("LAUNCHCTL_ACTION_NOT_ALLOWED")
    result = subprocess.run([str(LAUNCHCTL), action, f"gui/{os.getuid()}", str(ACTIVE_API_PLIST)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ValueError("LAUNCHCTL_ACTION_FAILED:" + action + ":" +
                         (result.stderr.strip()[:300] or str(result.returncode)))


def _verify_readonly_guards(plan: Mapping[str, Any]) -> dict[str, str]:
    scheduler_sha = _sha_file(ACTIVE_SCHEDULER_PLIST)
    stage_center_sha = _sha_file(STAGE_CENTER_SCHEDULER_PLIST)
    expected_scheduler = plan["before"].get("scheduler_plist_sha256")
    expected_stage_center = plan["before"].get("stage_center_scheduler_plist_sha256")
    if scheduler_sha != expected_scheduler:
        raise ValueError("SCHEDULER_PLIST_PREIMAGE_SHA_MISMATCH")
    if stage_center_sha != expected_stage_center:
        raise ValueError("STAGE_CENTER_SCHEDULER_PLIST_PREIMAGE_SHA_MISMATCH")
    binding = _load_disabled_binding(plan)
    return {"scheduler_plist_sha256": scheduler_sha,
            "stage_center_scheduler_plist_sha256": stage_center_sha,
            "disabled_binding_sha256": binding["sha256"]}


def _preflight(plan: Mapping[str, Any]) -> dict[str, Any]:
    target = plan["target"]
    before = plan["before"]
    p2_review = _validate_p2_review(plan)
    candidate = _load_candidate_release(plan)
    binding = _load_disabled_binding(plan)
    active_raw = _regular_file(ACTIVE_API_PLIST, "ACTIVE_API_PLIST")
    active_sha = _sha(active_raw)
    if active_sha != before.get("active_api_plist_sha256"):
        raise ValueError("ACTIVE_API_PLIST_PREIMAGE_SHA_MISMATCH")
    active_stat = ACTIVE_API_PLIST.stat(follow_symlinks=False)
    if active_stat.st_uid != os.getuid() or active_stat.st_gid != os.getgid():
        raise ValueError("ACTIVE_API_PLIST_OWNER_MISMATCH")
    if getattr(active_stat, "st_flags", 0) != 0:
        raise ValueError("ACTIVE_API_PLIST_FILE_FLAGS_UNSUPPORTED")
    active_metadata = _file_metadata(ACTIVE_API_PLIST)
    guards = _verify_readonly_guards(plan)
    current_plist_identity = _identity_from_plist(active_raw)
    expected_before = before.get("loaded_identity")
    loaded = _loaded_identity(_launchctl_print())
    if not isinstance(expected_before, dict):
        raise ValueError("API_ONLY_BEFORE_IDENTITY_MISSING")
    if any(current_plist_identity.get(key) != expected_before.get(key)
           for key in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")):
        raise ValueError("ACTIVE_API_PLIST_IDENTITY_DOES_NOT_MATCH_PLAN")
    if not _identity_matches(loaded, expected_before):
        raise ValueError("ACTIVE_API_LAUNCH_AGENT_RUNTIME_DOES_NOT_MATCH_PLAN")
    staged_raw = _candidate_plist_bytes(active_raw, plan, candidate)
    staged_sha = _sha(staged_raw)
    expected_staged_sha = target.get("staged_api_plist_sha256")
    expected_diff_sha = target.get("staged_api_plist_diff_sha256")
    if not isinstance(expected_staged_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_staged_sha):
        raise ValueError("API_ONLY_STAGED_PLIST_SHA_NOT_FROZEN")
    if not isinstance(expected_diff_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_diff_sha):
        raise ValueError("API_ONLY_STAGED_PLIST_DIFF_SHA_NOT_FROZEN")
    staged_file_raw = _regular_file(STAGED_API_PLIST_PATH, "STAGED_API_PLIST")
    if _sha(staged_file_raw) != expected_staged_sha or staged_file_raw != staged_raw:
        raise ValueError("API_ONLY_STAGED_PLIST_MISMATCH")
    diff = _staged_plist_diff(active_raw, staged_raw, candidate)
    diff_raw = _regular_file(STAGED_API_PLIST_DIFF_PATH, "STAGED_API_PLIST_DIFF")
    if _sha(diff_raw) != expected_diff_sha or json.loads(diff_raw.decode("utf-8")) != diff:
        raise ValueError("API_ONLY_STAGED_PLIST_DIFF_MISMATCH")
    historical_products = _verify_historical_product_readback()
    return {
        "status": "READY_API_ONLY_R1_CUTOVER",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "before": {"active_api_plist_path": str(ACTIVE_API_PLIST),
                   "active_api_plist_sha256": active_sha,
                   "active_api_plist_metadata": active_metadata,
                   "loaded_identity": loaded},
        "after": {"release_id": target["release_id"], "app_root": target["app_root"],
                  "release_manifest_sha256": candidate["manifest_sha256"],
                  "application_inventory_sha256": candidate["inventory_sha256"],
                  "staged_api_plist_path": str(STAGED_API_PLIST_PATH),
                  "staged_api_plist_sha256": staged_sha,
                  "loaded_pid": "ASSIGNED_BY_LAUNCHD"},
        "candidate_release": candidate,
        "p2_independent_review": p2_review,
        "disabled_binding": binding,
        "staged_plist_diff": diff,
        "historical_product_readback": historical_products,
        "readonly_guards": guards,
        "allowed_live_write": str(ACTIVE_API_PLIST),
        "scheduler_action": "UNCHANGED",
        "formal_manager_state_action": "READ_ONLY",
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                   "buy_gate_updated": False, "orders_sent": False},
    }


def _atomic_write_json(path: Path, value: Mapping[str, Any], expected_current_sha: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("API_ONLY_PLAN_NOT_EXACT_REGULAR_FILE")
    info = path.stat(follow_symlinks=False)
    if _sha_file(path) != expected_current_sha:
        raise ValueError("API_ONLY_PLAN_COMPARE_AND_SWAP_MISMATCH")
    mode = stat.S_IMODE(info.st_mode)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        _write_exclusive(temp, raw, mode=mode)
        current = path.stat(follow_symlinks=False)
        if ((current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)
                or _sha_file(path) != expected_current_sha):
            raise ValueError("API_ONLY_PLAN_COMPARE_AND_SWAP_MISMATCH")
        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()


def _stage_api_plist(plan: Mapping[str, Any]) -> dict[str, Any]:
    plan_raw = _regular_file(PLAN_PATH, "API_ONLY_PLAN")
    if json.loads(plan_raw.decode("utf-8")) != dict(plan):
        raise ValueError("API_ONLY_PLAN_CHANGED_BEFORE_STAGING")
    _validate_p2_review(plan)
    candidate = _load_candidate_release(plan)
    binding = _load_disabled_binding(plan)
    active_raw = _regular_file(ACTIVE_API_PLIST, "ACTIVE_API_PLIST")
    before = plan["before"]
    if _sha(active_raw) != before.get("active_api_plist_sha256"):
        raise ValueError("ACTIVE_API_PLIST_PREIMAGE_SHA_MISMATCH")
    active_stat = ACTIVE_API_PLIST.stat(follow_symlinks=False)
    if active_stat.st_uid != os.getuid() or active_stat.st_gid != os.getgid():
        raise ValueError("ACTIVE_API_PLIST_OWNER_MISMATCH")
    if getattr(active_stat, "st_flags", 0) != 0:
        raise ValueError("ACTIVE_API_PLIST_FILE_FLAGS_UNSUPPORTED")
    guards = _verify_readonly_guards(plan)
    current_identity = _identity_from_plist(active_raw)
    expected_before = before.get("loaded_identity")
    if not isinstance(expected_before, dict) or any(
            current_identity.get(key) != expected_before.get(key)
            for key in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")):
        raise ValueError("ACTIVE_API_PLIST_IDENTITY_DOES_NOT_MATCH_PLAN")
    loaded = _loaded_identity(_launchctl_print())
    if not _identity_matches(loaded, expected_before):
        raise ValueError("ACTIVE_API_LAUNCH_AGENT_RUNTIME_DOES_NOT_MATCH_PLAN")

    staged_raw = _candidate_plist_bytes(active_raw, plan, candidate)
    diff = _staged_plist_diff(active_raw, staged_raw, candidate)
    diff_raw = (json.dumps(diff, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    for path, expected_raw, label in (
        (STAGED_API_PLIST_PATH, staged_raw, "STAGED_API_PLIST"),
        (STAGED_API_PLIST_DIFF_PATH, diff_raw, "STAGED_API_PLIST_DIFF"),
    ):
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file() or _regular_file(path, label) != expected_raw:
                raise ValueError(label + "_EXISTS_WITH_DIFFERENT_BYTES")
        else:
            _write_exclusive(path, expected_raw)
    staged_sha = _sha(staged_raw)
    diff_sha = _sha(diff_raw)
    target = plan["target"]
    if target.get("staged_api_plist_sha256") not in (None, staged_sha):
        raise ValueError("API_ONLY_PLAN_STAGED_PLIST_SHA_CONFLICT")
    if target.get("staged_api_plist_diff_sha256") not in (None, diff_sha):
        raise ValueError("API_ONLY_PLAN_STAGED_PLIST_DIFF_SHA_CONFLICT")
    updated_plan = dict(plan)
    updated_before = dict(plan.get("before", {}))
    updated_before["loaded_identity"] = loaded
    updated_before["observed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    updated_plan["before"] = updated_before
    updated_target = dict(target)
    updated_target["staged_api_plist_sha256"] = staged_sha
    updated_target["staged_api_plist_diff_sha256"] = diff_sha
    updated_plan["target"] = updated_target
    boundary = dict(plan.get("execution_boundary", {}))
    boundary["staged_api_plist_written"] = True
    boundary["active_api_plist_written"] = False
    boundary["launchctl_mutation_called"] = False
    boundary["launchctl_readonly_prints"] = True
    updated_plan["execution_boundary"] = boundary
    _atomic_write_json(PLAN_PATH, updated_plan, _sha(plan_raw))
    return {"status": "STAGED_API_PLIST_READY_NOT_DEPLOYED",
            "staged_api_plist_path": str(STAGED_API_PLIST_PATH),
            "staged_api_plist_sha256": staged_sha,
            "staged_api_plist_diff_path": str(STAGED_API_PLIST_DIFF_PATH),
            "staged_api_plist_diff_sha256": diff_sha,
            "changed_environment": diff["changed_environment"],
            "changed_plist_keys": diff["changed_plist_keys"],
            "preserved_runtime_bindings": diff["preserved_runtime_bindings"],
            "disabled_binding": binding,
            "readonly_guards": guards,
            "launchctl_mutation_called": False,
            "launchctl_readonly_prints": True,
            "active_api_plist_written": False}


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
        if name:
            value = subprocess.run([str(xattr), "-px", name, str(path)],
                                   capture_output=True, text=True, timeout=10)
            if value.returncode != 0:
                raise ValueError("API_ONLY_PLIST_XATTR_READ_FAILED:" + name)
            result[name] = "".join(value.stdout.split())
    return result


def _copy_xattrs(source: Path, destination: Path) -> None:
    if hasattr(os, "listxattr"):
        for name in os.listxattr(source, follow_symlinks=False):
            os.setxattr(destination, name, os.getxattr(source, name, follow_symlinks=False),
                        follow_symlinks=False)
        return
    xattr = Path("/usr/bin/xattr")
    for name, encoded in _xattr_snapshot(source).items():
        result = subprocess.run([str(xattr), "-wx", name, encoded, str(destination)],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise ValueError("API_ONLY_PLIST_XATTR_WRITE_FAILED:" + name)


def _file_metadata(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("API_ONLY_PLIST_METADATA_SOURCE_INVALID")
    info = path.stat(follow_symlinks=False)
    return {"uid": info.st_uid, "gid": info.st_gid,
            "mode": stat.S_IMODE(info.st_mode), "flags": getattr(info, "st_flags", 0),
            "mtime_ns": info.st_mtime_ns,
            "xattr_sha256": {name: _sha(os.getxattr(path, name, follow_symlinks=False))
                             for name in os.listxattr(path, follow_symlinks=False)}
                             if hasattr(os, "listxattr") else {}}


def _apply_file_metadata(source: Path, destination: Path) -> None:
    source_info = source.stat(follow_symlinks=False)
    destination_info = destination.stat(follow_symlinks=False)
    if ((source_info.st_uid, source_info.st_gid) != (destination_info.st_uid, destination_info.st_gid)):
        raise ValueError("API_ONLY_TEMP_PLIST_OWNER_MISMATCH")
    os.chmod(destination, stat.S_IMODE(source_info.st_mode), follow_symlinks=False)
    _copy_xattrs(source, destination)
    os.utime(destination, ns=(source_info.st_atime_ns, source_info.st_mtime_ns), follow_symlinks=False)
    observed = _file_metadata(destination)
    expected = _file_metadata(source)
    if any(observed[key] != expected[key] for key in ("uid", "gid", "mode", "xattr_sha256", "mtime_ns")):
        raise ValueError("API_ONLY_TEMP_PLIST_METADATA_MISMATCH")


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.EBADF}:
                raise
    finally:
        os.close(fd)


def _atomic_replace_bytes(path: Path, raw: bytes, metadata_source: Path,
                          expected_current_sha: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("API_ONLY_TARGET_PLIST_NO_LONGER_REGULAR")
    if _sha_file(path) != expected_current_sha:
        raise ValueError("API_ONLY_TARGET_PLIST_CAS_MISMATCH")
    info = path.stat(follow_symlinks=False)
    metadata = _file_metadata(metadata_source)
    if metadata["uid"] != info.st_uid or metadata["gid"] != info.st_gid:
        raise ValueError("API_ONLY_METADATA_SOURCE_OWNER_MISMATCH")
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _apply_file_metadata(metadata_source, temp)
        current_info = path.stat(follow_symlinks=False)
        if ((current_info.st_dev, current_info.st_ino) != (info.st_dev, info.st_ino)
                or _sha_file(path) != expected_current_sha):
            raise ValueError("API_ONLY_TARGET_PLIST_CAS_MISMATCH")
        os.replace(temp, path)
        _fsync_directory(path.parent)
        if _sha_file(path) != _sha(raw):
            raise ValueError("API_ONLY_TARGET_PLIST_POST_REPLACE_SHA_MISMATCH")
        installed_metadata = _file_metadata(path)
        if any(installed_metadata[key] != metadata[key]
               for key in ("uid", "gid", "mode", "xattr_sha256", "mtime_ns")):
            raise ValueError("API_ONLY_TARGET_PLIST_POST_REPLACE_METADATA_MISMATCH")
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()


def _write_exclusive(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _create_preimage_exclusive(path: Path, raw: bytes, metadata_source: Path) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError("API_ONLY_PREIMAGE_RESTORE_PATH_NO_LONGER_ABSENT")
    metadata = _file_metadata(metadata_source)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.restore")
    try:
        _write_exclusive(temp, raw, mode=metadata["mode"])
        _apply_file_metadata(metadata_source, temp)
        if path.exists() or path.is_symlink():
            raise ValueError("API_ONLY_PREIMAGE_RESTORE_PATH_NO_LONGER_ABSENT")
        os.link(temp, path, follow_symlinks=False)
        temp.unlink()
        _fsync_directory(path.parent)
        if _sha_file(path) != _sha(raw):
            raise ValueError("API_ONLY_PREIMAGE_RESTORE_SHA_MISMATCH")
        restored_metadata = _file_metadata(path)
        if any(restored_metadata[key] != metadata[key]
               for key in ("uid", "gid", "mode", "xattr_sha256", "mtime_ns")):
            raise ValueError("API_ONLY_PREIMAGE_RESTORE_METADATA_MISMATCH")
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()


def _receipt_bytes(value: Mapping[str, Any]) -> bytes:
    unsigned = dict(value)
    unsigned.pop("receipt_sha256", None)
    signed = {**unsigned, "receipt_sha256": _canonical_sha(unsigned)}
    return (json.dumps(signed, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write_receipt(path: Path, value: Mapping[str, Any], *, create: bool = False) -> None:
    raw = _receipt_bytes(value)
    if create or not path.exists():
        _write_exclusive(path, raw)
        return
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        _write_exclusive(temp, raw)
        os.replace(temp, path)
        _fsync_directory(path.parent)
    finally:
        if temp.exists() or temp.is_symlink():
            temp.unlink()


def _http_get(path: str) -> tuple[int, bytes]:
    request = urllib.request.Request(BASE_URL + path, headers={"Accept": "*/*", "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read(8 * 1024 * 1024)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError("API_ONLY_HTTP_READBACK_FAILED:" + path + ":" + type(exc).__name__) from exc


def _verify_openapi(*, require_manager_route: bool) -> dict[str, Any]:
    status, raw = _http_get("/openapi.json")
    if status != 200:
        raise ValueError("API_OPENAPI_HTTP_STATUS:" + str(status))
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("API_OPENAPI_JSON_INVALID") from exc
    method = value.get("paths", {}).get(MANAGER_WORKSPACE_ROUTE, {}).get("get")
    if require_manager_route and not isinstance(method, dict):
        raise ValueError("MANAGER_WORKSPACE_GET_ROUTE_NOT_AVAILABLE")
    return {"http_status": status, "manager_workspace_get": "AVAILABLE" if isinstance(method, dict) else "NOT_PRESENT",
            "openapi_sha256": _sha(raw)}


def _load_product_baseline() -> dict[str, Any]:
    raw = _regular_file(PRODUCT_BASELINE_PATH, "PRE_SWITCH_PRODUCT_BASELINE")
    if _sha(raw) != PRODUCT_BASELINE_SHA256:
        raise ValueError("PRE_SWITCH_PRODUCT_BASELINE_SHA_MISMATCH")
    try:
        baseline = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("PRE_SWITCH_PRODUCT_BASELINE_JSON_INVALID") from exc
    if not isinstance(baseline, dict) or baseline.get("scope") != "ROOT_READ_ONLY_PRE_SWITCH_PRODUCT_BASELINE":
        raise ValueError("PRE_SWITCH_PRODUCT_BASELINE_SCOPE_MISMATCH")
    rows = baseline.get("results")
    if not isinstance(rows, list):
        raise ValueError("PRE_SWITCH_PRODUCT_BASELINE_RESULTS_MISSING")
    by_name = {row.get("name"): row for row in rows if isinstance(row, dict)}
    expected_paths = {
        "current_analysis": "/api/v4/manager/research/announcements/analysis?date=20261008&publication_date=2026-10-07",
        "legacy_analysis": "/api/v4/manager/research/announcements/analysis?date=20261007&publication_date=2026-10-06",
        "current_workspace": "/api/v4/manager/research/workspace?date=20261008&selection_date=20261007&announcement_date=20261007&view=dynamic",
    }
    if len(rows) != len(expected_paths) or set(by_name) != set(expected_paths):
        raise ValueError("PRE_SWITCH_PRODUCT_BASELINE_RESULT_SET_MISMATCH")
    for name, path in expected_paths.items():
        row = by_name[name]
        if row.get("path") != path or row.get("http_status") != 200:
            raise ValueError("PRE_SWITCH_PRODUCT_BASELINE_ENDPOINT_MISMATCH:" + name)
    return {"path": str(PRODUCT_BASELINE_PATH), "sha256": PRODUCT_BASELINE_SHA256,
            "rows": by_name}


def _strip_top_level_json_member(raw: bytes, member_name: str) -> tuple[bytes, int]:
    """Remove one top-level object member while preserving all other response bytes.

    This lets the post-switch oracle compare the complete pinned R3 response
    byte-for-byte after excluding only the approved additive R1 projection.
    """
    text = raw.decode("utf-8")
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text) or text[pos] != "{":
        raise ValueError("HISTORICAL_ANALYSIS_OBJECT_REQUIRED")
    pos += 1
    prior_comma: int | None = None
    target: tuple[int, int, int | None, int | None] | None = None
    target_count = 0
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos < len(text) and text[pos] == "}":
            break
        key_start = pos
        try:
            key, key_end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError as exc:
            raise ValueError("HISTORICAL_ANALYSIS_JSON_INVALID") from exc
        if not isinstance(key, str):
            raise ValueError("HISTORICAL_ANALYSIS_JSON_OBJECT_KEY_INVALID")
        pos = key_end
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text) or text[pos] != ":":
            raise ValueError("HISTORICAL_ANALYSIS_JSON_INVALID")
        pos += 1
        while pos < len(text) and text[pos].isspace():
            pos += 1
        try:
            _value, value_end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError as exc:
            raise ValueError("HISTORICAL_ANALYSIS_JSON_INVALID") from exc
        pos = value_end
        while pos < len(text) and text[pos].isspace():
            pos += 1
        following_comma: int | None = None
        if pos < len(text) and text[pos] == ",":
            following_comma = pos
            pos += 1
        elif pos >= len(text) or text[pos] != "}":
            raise ValueError("HISTORICAL_ANALYSIS_JSON_INVALID")
        if key == member_name:
            target_count += 1
            target = (key_start, value_end, prior_comma, following_comma)
        if following_comma is None:
            break
        prior_comma = following_comma
    if target_count > 1:
        raise ValueError("HISTORICAL_ANALYSIS_DUPLICATE_CONSUMPTION_VALIDATION")
    if target is None:
        return raw, 0
    key_start, value_end, preceding_comma, following_comma = target
    if following_comma is not None:
        stripped = text[:key_start] + text[following_comma + 1:]
    elif preceding_comma is not None:
        stripped = text[:preceding_comma] + text[value_end:]
    else:
        stripped = text[:key_start] + text[value_end:]
    return stripped.encode("utf-8"), 1


def _validate_consumption_validation(name: str, value: Any, expected: Mapping[str, Any],
                                     product_sha: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != CONSUMPTION_VALIDATION_KEYS:
        raise ValueError("HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_SCHEMA_MISMATCH:" + name)
    query = parse_qs(urlsplit(expected["path"]).query, keep_blank_values=True)
    target_dates = query.get("date", [])
    publication_dates = query.get("publication_date", [])
    if len(target_dates) != 1 or len(publication_dates) != 1:
        raise ValueError("HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_PATH_INVALID:" + name)
    legacy = name == "legacy_analysis"
    expected_values = {
        "schema_version": CONSUMPTION_VALIDATION_SCHEMA,
        "target_trade_date": target_dates[0],
        "publication_date": publication_dates[0],
        "status": "NOT_CONSUMED_INVALID" if legacy else "VERIFIED",
        "validation_status": "CANNOT_CONFIRM" if legacy else "VERIFIED",
        "consumed": False,
        "product_sha256": product_sha,
        "failure_stage": "JUDGMENT_RECEIPT" if legacy else None,
        "gaps": (["ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID"] if legacy else []),
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected_values.items()):
        raise ValueError("HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_MISMATCH:" + name)
    if _consumption_validation_sha(value) != CONSUMPTION_VALIDATION_CANONICAL_SHA256.get(name):
        raise ValueError("HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_SHA_MISMATCH:" + name)
    return {"schema_version": value["schema_version"], "target_trade_date": value["target_trade_date"],
            "publication_date": value["publication_date"], "status": value["status"],
            "validation_status": value["validation_status"], "consumed": value["consumed"],
            "product_sha256": value["product_sha256"], "failure_stage": value["failure_stage"],
            "gaps": value["gaps"], "safety_flags_match": True}


def _verify_historical_product_readback(*, allow_r1_consumption_validation: bool = False) -> dict[str, Any]:
    baseline = _load_product_baseline()
    observed: dict[str, Any] = {}
    for name in ("current_analysis", "legacy_analysis"):
        expected = baseline["rows"][name]
        status, raw = _http_get(expected["path"])
        if status != 200:
            raise ValueError("HISTORICAL_ANALYSIS_HTTP_STATUS:" + name + ":" + str(status))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("HISTORICAL_ANALYSIS_JSON_INVALID:" + name) from exc
        if not isinstance(payload, dict):
            raise ValueError("HISTORICAL_ANALYSIS_OBJECT_REQUIRED:" + name)
        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else payload
        selection = analysis.get("stock_selection")
        expected_analysis = expected.get("analysis", {})
        expected_selection = expected.get("stock_selection", {})
        expected_owner_receipt = expected.get("owner_import_receipt")
        observed_owner_receipt = payload.get("owner_import_receipt")
        expected_response_sha = expected.get("response_sha256")
        product_sha = expected_analysis.get("product_sha256")
        stripped_raw, extension_count = _strip_top_level_json_member(raw, "consumption_validation")
        if allow_r1_consumption_validation and extension_count != 1:
            raise ValueError("HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_REQUIRED:" + name)
        consumption_summary = None
        if allow_r1_consumption_validation:
            consumption_summary = _validate_consumption_validation(
                name, payload.get("consumption_validation"), expected, product_sha)
        baseline_compare_raw = stripped_raw if allow_r1_consumption_validation else raw
        if not isinstance(expected_response_sha, str) or _sha(baseline_compare_raw) != expected_response_sha:
            raise ValueError("HISTORICAL_ANALYSIS_RESPONSE_SHA_MISMATCH:" + name)
        if isinstance(expected_owner_receipt, dict):
            owner_receipt_matches = (isinstance(observed_owner_receipt, dict)
                and all(observed_owner_receipt.get(key) == value
                        for key, value in expected_owner_receipt.items()))
        else:
            owner_receipt_matches = observed_owner_receipt is expected_owner_receipt
        if (not isinstance(selection, dict)
                or analysis.get("status") != expected_analysis.get("status")
                or analysis.get("product_sha256") != product_sha
                or analysis.get("gaps") != expected_analysis.get("gaps")
                or selection.get("status") != expected_selection.get("status")
                or selection.get("product_sha256") != product_sha
                or selection.get("gaps") != expected_selection.get("gaps")
                or "owner_import_receipt" not in payload
                or not owner_receipt_matches):
            raise ValueError("HISTORICAL_ANALYSIS_PRODUCT_READBACK_MISMATCH:" + name)
        lengths = expected.get("stock_selection_list_lengths", {})
        stock_list = selection.get("stocks", [])
        decision_list = selection.get("article_decisions", [])
        gap_list = selection.get("gaps", [])
        if (len(stock_list) != lengths.get("stocks")
                or len(decision_list) != lengths.get("article_decisions")
                or len(gap_list) != lengths.get("gaps")):
            raise ValueError("HISTORICAL_ANALYSIS_PRODUCT_LENGTH_MISMATCH:" + name)
        observed[name] = {"http_status": status, "response_sha256": _sha(raw),
                          "response_sha256_matches_baseline": _sha(raw) == expected_response_sha,
                          "baseline_comparison_sha256": _sha(baseline_compare_raw),
                          "baseline_comparison_sha256_matches": True,
                          "baseline_comparison_method": (
                              "R1_ADDITIVE_CONSUMPTION_VALIDATION_STRIPPED"
                              if allow_r1_consumption_validation else "STRICT_RAW_RESPONSE_BYTES"),
                          "status": analysis.get("status"), "product_sha256": product_sha,
                          "stock_selection_product_sha256": selection.get("product_sha256"),
                          "owner_import_receipt": {
                              "baseline_status": "VERIFIED" if expected_owner_receipt else "ABSENT_LEGACY_R3_COMPATIBLE",
                              "after_readback": "VERIFIED" if observed_owner_receipt else "ABSENT_LEGACY_R3_COMPATIBLE",
                              "matched_pinned_baseline": True},
                          "stock_selection_list_lengths": {"stocks": len(stock_list),
                              "article_decisions": len(decision_list), "gaps": len(gap_list)}}
        if consumption_summary is not None:
            observed[name]["consumption_validation"] = consumption_summary
    expected_workspace = baseline["rows"]["current_workspace"]
    status, raw = _http_get(expected_workspace["path"])
    try:
        workspace_payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        workspace_payload = None
    workspace = workspace_payload.get("announcement_reviewed_analysis", {}) if isinstance(workspace_payload, dict) else {}
    expected_workspace_analysis = expected_workspace.get("workspace_analysis", {})
    expected_gap = "ANNOUNCEMENT_ANALYSIS_NOT_CONSUMED:ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID"
    gaps = workspace.get("gaps") if isinstance(workspace, dict) else None
    read_context = workspace_payload.get("read_context", {}) if isinstance(workspace_payload, dict) else {}
    announcement_review = workspace_payload.get("announcement_review", {}) if isinstance(workspace_payload, dict) else {}
    plan_product = workspace_payload.get("plan_product", {}) if isinstance(workspace_payload, dict) else {}
    workspace_status = workspace.get("status") if isinstance(workspace, dict) else None
    read_context_status = read_context.get("status") if isinstance(read_context, dict) else None
    gap_codes = [gap for gap in gaps if isinstance(gap, str) and gap.startswith("ANNOUNCEMENT_ANALYSIS_NOT_CONSUMED:")] if isinstance(gaps, list) else []
    observed_workspace_sha = _sha(raw)
    baseline_workspace_sha = expected_workspace.get("response_sha256")
    workspace_sha_matches = (isinstance(baseline_workspace_sha, str)
                             and observed_workspace_sha == baseline_workspace_sha)
    known_invalid_judgment_gap = expected_gap in gap_codes
    workspace_readback = {
        "http_status": status,
        "status": "CANNOT_CONFIRM",
        "baseline_response_sha256": baseline_workspace_sha or "CANNOT_CONFIRM",
        "observed_response_sha256": observed_workspace_sha,
        "response_sha_matches_baseline": workspace_sha_matches,
        "baseline_status": expected_workspace_analysis.get("status", "CANNOT_CONFIRM"),
        "observed_status": workspace_status or "CANNOT_CONFIRM",
        "read_context_status": read_context_status or "CANNOT_CONFIRM",
        "announcement_review_status": announcement_review.get("status") if isinstance(announcement_review, dict) else "CANNOT_CONFIRM",
        "plan_product_status": plan_product.get("status") if isinstance(plan_product, dict) else "CANNOT_CONFIRM",
        "judgment_receipt": "CANNOT_CONFIRM",
        "known_invalid_judgment_gap_present": known_invalid_judgment_gap,
        "observed_gap_codes": gap_codes,
        "data_loss_conclusion": "CANNOT_CONFIRM",
    }
    observed["current_workspace"] = workspace_readback
    return {"status": "HISTORICAL_ANALYSIS_PRODUCTS_VERIFIED_WORKSPACE_CANNOT_CONFIRM",
            "baseline_path": baseline["path"], "baseline_sha256": baseline["sha256"],
            "workspace_status": "CANNOT_CONFIRM",
            "results": observed}


def _verify_frontend_http(app_root: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    status, html_raw = _http_get(MANAGER_SELECTION_HTML)
    if status != 200:
        raise ValueError("MANAGER_SELECTION_HTTP_STATUS:" + str(status))
    if _sha(html_raw) != expected["frontend"]["index_sha256"]:
        raise ValueError("MANAGER_SELECTION_HTTP_INDEX_SHA_MISMATCH")
    parser = _AssetReferences()
    parser.feed(html_raw.decode("utf-8"))
    observed: list[dict[str, str]] = []
    expected_by_url = {row["url_path"]: row["sha256"] for row in expected["frontend"]["assets"]}
    for url_path in sorted(parser.references):
        if url_path not in expected_by_url:
            raise ValueError("MANAGER_SELECTION_HTTP_ASSET_NOT_PINNED:" + url_path)
        status, asset_raw = _http_get(url_path)
        if status != 200 or _sha(asset_raw) != expected_by_url[url_path]:
            raise ValueError("MANAGER_SELECTION_HTTP_ASSET_READBACK_MISMATCH:" + url_path)
        observed.append({"url_path": url_path, "sha256": _sha(asset_raw)})
    if set(expected_by_url) != set(parser.references):
        raise ValueError("MANAGER_SELECTION_HTTP_ASSET_SET_MISMATCH")
    return {"http_status": 200, "index_sha256": _sha(html_raw), "assets": observed,
            "static_bundle_status": "BYTE_IDENTICAL_TO_RELEASE"}


def _wait_for_candidate(expected: Mapping[str, Any], app_root: Path, *, timeout_s: int = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            loaded = _loaded_identity(_launchctl_print())
            expected_runtime = {"V35_APP_ROOT": expected["app_root"],
                                "V35_RELEASE_ID": expected["release_id"],
                                "V35_RELEASE_MANIFEST_SHA256": expected["release_manifest_sha256"]}
            if any(loaded.get(key) != value for key, value in expected_runtime.items()):
                raise ValueError("API_ONLY_CANDIDATE_RUNTIME_IDENTITY_MISMATCH")
            if not loaded.get("pid"):
                raise ValueError("API_ONLY_CANDIDATE_PID_UNAVAILABLE")
            http = _verify_openapi(require_manager_route=True)
            ui = _verify_frontend_http(app_root, expected["candidate_release"])
            historical_products = _verify_historical_product_readback(
                allow_r1_consumption_validation=True)
            return {"runtime": loaded, "http": http, "ui_static_readback": ui,
                    "historical_product_readback": historical_products}
        except (ValueError, OSError) as exc:
            last_error = str(exc)
            time.sleep(1)
    raise ValueError("API_ONLY_RUNTIME_VERIFICATION_TIMEOUT:" + str(last_error))


def _observe_scheduler(plan: Mapping[str, Any]) -> dict[str, Any]:
    # Scheduler state is only a read-only compare-and-swap guard.
    return _verify_readonly_guards(plan)


def _operation_root() -> Path:
    root = TASK_ROOT / "phase2/receipts/api_only_switch_runs"
    if root.is_symlink():
        raise ValueError("API_ONLY_OPERATION_ROOT_SYMLINK")
    root.mkdir(parents=True, exist_ok=True)
    if root.resolve(strict=True) != root:
        raise ValueError("API_ONLY_OPERATION_ROOT_NOT_EXACT")
    return root


def _new_operation_dir(suffix: str = "") -> Path:
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + suffix + "-" + uuid.uuid4().hex[:8]
    path = _operation_root() / name
    path.mkdir(mode=0o700, exist_ok=False)
    return path


def _record(path: Path, status: str, details: Mapping[str, Any]) -> dict[str, Any]:
    receipt = {"schema_version": RECEIPT_SCHEMA, "status": status,
               "recorded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "active_api_plist": str(ACTIVE_API_PLIST), "active_label": LABEL,
               "scheduler_action": "UNCHANGED", "formal_manager_state_action": "READ_ONLY",
               "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
               **dict(details)}
    _write_receipt(path, receipt)
    return _read_json(path, "API_ONLY_OPERATION_RECEIPT")


def _identity_matches(identity: Mapping[str, Any] | None,
                      expected: Mapping[str, Any]) -> bool:
    if not isinstance(identity, Mapping) or identity.get("state") != "running":
        return False
    return all(identity.get(key) == expected.get(key) for key in (
        "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256"))


def _restore_after_failure(plan: Mapping[str, Any], backup_path: Path, original_raw: bytes,
                           candidate_plist_sha: str, operation_dir: Path,
                           original_error: str,
                           backup_metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    receipt_path = operation_dir / "operation_receipt.json"
    try:
        if _sha(original_raw) != plan["before"]["active_api_plist_sha256"]:
            raise ValueError("API_ONLY_ROLLBACK_PREIMAGE_CONTENT_MISMATCH")
        if _sha_file(backup_path) != plan["before"]["active_api_plist_sha256"]:
            raise ValueError("API_ONLY_ROLLBACK_BACKUP_SHA_MISMATCH")
        actual_backup_metadata = _file_metadata(backup_path)
        if backup_metadata is not None and any(
                actual_backup_metadata.get(key) != backup_metadata.get(key)
                for key in ("uid", "gid", "mode", "flags", "mtime_ns", "xattr_sha256")):
            raise ValueError("API_ONLY_ROLLBACK_BACKUP_METADATA_MISMATCH")
        old_identity = plan["before"]["loaded_identity"]
        observed = _observe_loaded()
        if ACTIVE_API_PLIST.is_symlink() or (ACTIVE_API_PLIST.exists() and not ACTIVE_API_PLIST.is_file()):
            raise ValueError("API_ONLY_ROLLBACK_ACTIVE_PLIST_PATH_UNAVAILABLE")
        current_sha = _sha_file(ACTIVE_API_PLIST) if ACTIVE_API_PLIST.is_file() else None
        if observed.get("state") == "LOADED" and _identity_matches(observed.get("identity"), old_identity) \
                and current_sha == plan["before"]["active_api_plist_sha256"]:
            result = {"status": "ROLLED_BACK_TO_PREIMAGE", "recovery_action": "OLD_API_REMAINS_LOADED",
                      "runtime_verification": {"runtime": observed["identity"],
                                                "http": _verify_openapi(require_manager_route=False)},
                      "historical_product_readback": "CANNOT_CONFIRM_NOT_RECHECKED_DURING_RECOVERY"}
            _record(receipt_path, result["status"], {"original_error": original_error,
                "backup_path": str(backup_path), "backup_sha256": _sha_file(backup_path),
                "backup_metadata": actual_backup_metadata, **result})
            return result
        if observed.get("state") == "LOADED":
            identity = observed.get("identity") or {}
            candidate_identity = {"state": "running",
                "V35_RELEASE_ID": plan["target"]["release_id"],
                "V35_APP_ROOT": plan["target"]["app_root"],
                "V35_RELEASE_MANIFEST_SHA256": plan["target"]["release_manifest_sha256"]}
            if not _identity_matches(identity, candidate_identity):
                raise ValueError("API_ONLY_ROLLBACK_REFUSES_UNKNOWN_LOADED_IDENTITY")
            try:
                _launchctl_action("bootout")
            except Exception:
                pass
            observed = _observe_loaded()
        if observed.get("state") != "NOT_LOADED":
            raise ValueError("API_ONLY_ROLLBACK_COULD_NOT_CONFIRM_JOB_UNLOADED:" + str(observed))
        if current_sha not in {None, plan["before"]["active_api_plist_sha256"], candidate_plist_sha}:
            raise ValueError("API_ONLY_ROLLBACK_ACTIVE_PLIST_UNEXPECTED_SHA")
        if current_sha == candidate_plist_sha:
            _atomic_replace_bytes(ACTIVE_API_PLIST, original_raw, backup_path,
                                  expected_current_sha=candidate_plist_sha)
        elif current_sha is None:
            _create_preimage_exclusive(ACTIVE_API_PLIST, original_raw, backup_path)
        if _sha_file(ACTIVE_API_PLIST) != plan["before"]["active_api_plist_sha256"]:
            raise ValueError("API_ONLY_ROLLBACK_PREIMAGE_RESTORE_FAILED")
        bootstrap_error = None
        try:
            _launchctl_action("bootstrap")
        except Exception as exc:
            bootstrap_error = str(exc)
            observed = _observe_loaded()
            if observed.get("state") != "LOADED" or not _identity_matches(observed.get("identity"), old_identity):
                raise ValueError("API_ONLY_ROLLBACK_BOOTSTRAP_STATE_UNRESOLVED") from exc
        deadline = time.monotonic() + 30
        verified = None
        while time.monotonic() < deadline:
            observed = _observe_loaded()
            if observed.get("state") == "LOADED" and _identity_matches(observed.get("identity"), old_identity):
                verified = {"runtime": observed["identity"],
                            "http": _verify_openapi(require_manager_route=False)}
                break
            time.sleep(1)
        if verified is None:
            raise ValueError("API_ONLY_ROLLBACK_OLD_API_READBACK_FAILED")
        try:
            historical_products: Any = _verify_historical_product_readback()
        except Exception as exc:
            historical_products = {"status": "CANNOT_CONFIRM", "reason": str(exc)}
        _record(receipt_path, "ROLLED_BACK_TO_PREIMAGE", {
            "original_error": original_error, "backup_path": str(backup_path),
            "backup_sha256": _sha_file(backup_path), "backup_metadata": actual_backup_metadata,
            "recovery_action": "PREIMAGE_RESTORED_AND_BOOTSTRAPPED",
            "runtime_verification": verified, "bootstrap_error": bootstrap_error,
            "historical_product_readback": historical_products,
            "scheduler_post_sha256": _sha_file(ACTIVE_SCHEDULER_PLIST),
            "stage_center_scheduler_post_sha256": _sha_file(STAGE_CENTER_SCHEDULER_PLIST),
            "scheduler_action": "UNCHANGED"})
        return {"status": "ROLLED_BACK_TO_PREIMAGE", "runtime_verification": verified}
    except Exception as recovery_error:
        result = {"status": "ROLLBACK_INCOMPLETE", "reason": str(recovery_error),
                  "original_error": original_error, "backup_path": str(backup_path),
                  "backup_sha256": _sha_file(backup_path) if backup_path.is_file() else "CANNOT_CONFIRM",
                  "active_api_plist_sha256": _sha_file(ACTIVE_API_PLIST) if ACTIVE_API_PLIST.is_file() and not ACTIVE_API_PLIST.is_symlink() else None,
                  "scheduler_post_sha256": _sha_file(ACTIVE_SCHEDULER_PLIST) if ACTIVE_SCHEDULER_PLIST.is_file() else "CANNOT_CONFIRM",
                  "stage_center_scheduler_post_sha256": _sha_file(STAGE_CENTER_SCHEDULER_PLIST) if STAGE_CENTER_SCHEDULER_PLIST.is_file() else "CANNOT_CONFIRM"}
        _record(receipt_path, "ROLLBACK_INCOMPLETE", result)
        return result


def _run_switch(plan: Mapping[str, Any], *, confirmation: str,
                expected_current_sha: str, expected_staged_sha: str) -> dict[str, Any]:
    if confirmation != CONFIRM_SWITCH:
        raise ValueError("EXPLICIT_API_ONLY_SWITCH_CONFIRMATION_REQUIRED")
    preflight = _preflight(plan)
    before_sha = plan["before"]["active_api_plist_sha256"]
    staged_sha = preflight["after"]["staged_api_plist_sha256"]
    if expected_current_sha != before_sha or expected_staged_sha != staged_sha:
        raise ValueError("API_ONLY_SWITCH_EXPECTED_SHA_ARGUMENT_MISMATCH")
    source_raw = _regular_file(ACTIVE_API_PLIST, "ACTIVE_API_PLIST")
    staged_raw = _regular_file(STAGED_API_PLIST_PATH, "STAGED_API_PLIST")
    if _sha(staged_raw) != staged_sha:
        raise ValueError("API_ONLY_SWITCH_STAGED_PLIST_SHA_MISMATCH")
    source_metadata = _file_metadata(ACTIVE_API_PLIST)
    if source_metadata != preflight["before"]["active_api_plist_metadata"]:
        raise ValueError("API_ONLY_SWITCH_PREIMAGE_METADATA_CHANGED")
    operation_dir = _new_operation_dir()
    receipt_path = operation_dir / "operation_receipt.json"
    backup_path = operation_dir / "active_api_only.preimage.plist"
    _write_exclusive(backup_path, source_raw, mode=source_metadata["mode"])
    _apply_file_metadata(ACTIVE_API_PLIST, backup_path)
    backup_metadata = _file_metadata(backup_path)
    if _sha_file(backup_path) != before_sha or backup_metadata != source_metadata:
        raise ValueError("API_ONLY_BACKUP_SHA_MISMATCH")
    _write_exclusive(operation_dir / "preflight.json",
                     (json.dumps(preflight, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    _record(receipt_path, "PREPARED", {
        "before": preflight["before"], "after": preflight["after"],
        "candidate_release": preflight["candidate_release"],
        "backup_path": str(backup_path), "backup_sha256": before_sha,
        "backup_metadata": backup_metadata,
        "scheduler_preimage_sha256": preflight["readonly_guards"]["scheduler_plist_sha256"],
        "stage_center_scheduler_preimage_sha256": preflight["readonly_guards"]["stage_center_scheduler_plist_sha256"],
        "disabled_binding_sha256": preflight["disabled_binding"]["sha256"],
    })
    bootout_started = False
    try:
        # Revalidate the loaded API PID, plist CAS, immutable package, binding,
        # and both read-only scheduler guards immediately before bootout.
        second = _preflight(plan)
        if (second["before"] != preflight["before"]
                or second["after"]["staged_api_plist_sha256"] != staged_sha):
            raise ValueError("API_ONLY_SWITCH_IDENTITY_CHANGED_AFTER_BACKUP")
        bootout_started = True
        _launchctl_action("bootout")
        unloaded = _observe_loaded()
        if unloaded.get("state") != "NOT_LOADED":
            raise ValueError("API_ONLY_SWITCH_BOOTOUT_NOT_CONFIRMED:" + str(unloaded))
        if _sha_file(ACTIVE_API_PLIST) != before_sha:
            raise ValueError("API_ONLY_SWITCH_ACTIVE_PLIST_CHANGED_AFTER_BOOTOUT")
        _observe_scheduler(plan)
        _load_candidate_release(plan)
        _load_disabled_binding(plan)
        _atomic_replace_bytes(ACTIVE_API_PLIST, staged_raw, ACTIVE_API_PLIST,
                              expected_current_sha=before_sha)
        if _sha_file(ACTIVE_API_PLIST) != staged_sha:
            raise ValueError("API_ONLY_INSTALLED_PLIST_SHA_MISMATCH")
        _launchctl_action("bootstrap")
        verification = _wait_for_candidate({**preflight["after"],
                                            "candidate_release": preflight["candidate_release"]},
                                            Path(plan["target"]["app_root"]), timeout_s=60)
        readonly = _observe_scheduler(plan)
        final = _record(receipt_path, "API_ONLY_R1_SWITCHED_AND_READBACK_VERIFIED", {
            "before": preflight["before"], "after": {**preflight["after"],
                "loaded_identity": verification["runtime"]},
            "candidate_release": preflight["candidate_release"],
            "backup_path": str(backup_path), "backup_sha256": before_sha,
            "backup_metadata": backup_metadata,
            "scheduler_post_sha256": readonly["scheduler_plist_sha256"],
            "stage_center_scheduler_post_sha256": readonly["stage_center_scheduler_plist_sha256"],
            "disabled_binding_sha256": readonly["disabled_binding_sha256"],
            "runtime_verification": verification,
            "ui_status": "STATIC_HTTP_BUNDLE_READBACK_VERIFIED; BROWSER_RELOAD_CANNOT_CONFIRM",
            "owner_import_or_plan_refresh": "NOT_RUN",
        })
        return {"status": final["status"], "receipt_path": str(receipt_path),
                "receipt_sha256": final["receipt_sha256"], "runtime_verification": verification}
    except Exception as exc:
        if not bootout_started:
            _record(receipt_path, "ABORTED_BEFORE_BOOTOUT", {
                "reason": str(exc), "before": preflight["before"],
                "backup_path": str(backup_path), "backup_sha256": before_sha})
            raise
        recovery = _restore_after_failure(plan, backup_path, source_raw, staged_sha,
                                          operation_dir, str(exc), backup_metadata)
        if recovery.get("status") != "ROLLED_BACK_TO_PREIMAGE":
            raise ValueError("API_ONLY_SWITCH_FAILED_ROLLBACK_INCOMPLETE:" + str(recovery.get("reason"))) from exc
        raise ValueError("API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK:" + str(exc)) from exc


def _run_rollback(plan: Mapping[str, Any], *, receipt_path: Path,
                  confirmation: str, expected_current_sha: str) -> dict[str, Any]:
    if confirmation != CONFIRM_ROLLBACK:
        raise ValueError("EXPLICIT_API_ONLY_ROLLBACK_CONFIRMATION_REQUIRED")
    task_root = TASK_ROOT.resolve(strict=True)
    operation_root = _operation_root().resolve(strict=True)
    if (receipt_path.is_symlink() or not receipt_path.is_file()
            or task_root not in receipt_path.resolve(strict=True).parents
            or operation_root not in receipt_path.resolve(strict=True).parents):
        raise ValueError("API_ONLY_ROLLBACK_RECEIPT_OUTSIDE_TASK_ROOT")
    receipt = _read_json(receipt_path, "API_ONLY_SWITCH_RECEIPT")
    claimed = receipt.pop("receipt_sha256", None)
    if claimed != _canonical_sha(receipt):
        raise ValueError("API_ONLY_ROLLBACK_RECEIPT_SHA_MISMATCH")
    if receipt.get("schema_version") != RECEIPT_SCHEMA or receipt.get("status") != "API_ONLY_R1_SWITCHED_AND_READBACK_VERIFIED":
        raise ValueError("API_ONLY_ROLLBACK_RECEIPT_IDENTITY_INVALID")
    target = _load_candidate_release(plan)
    expected_after = {"release_id": plan["target"]["release_id"],
                      "app_root": plan["target"]["app_root"],
                      "release_manifest_sha256": target["manifest_sha256"]}
    if (receipt.get("before", {}).get("active_api_plist_sha256")
            != plan["before"]["active_api_plist_sha256"]
            or any(receipt.get("after", {}).get(key) != value for key, value in expected_after.items())):
        raise ValueError("API_ONLY_ROLLBACK_RECEIPT_RELEASE_IDENTITY_MISMATCH")
    backup_path = Path(str(receipt.get("backup_path", "")))
    candidate_raw = _candidate_plist_bytes(_regular_file(backup_path, "API_ONLY_BACKUP"), plan, target)
    candidate_sha = _sha(candidate_raw)
    if (candidate_sha != plan["target"].get("staged_api_plist_sha256")
            or expected_current_sha != candidate_sha or ACTIVE_API_PLIST.is_symlink()
            or _sha_file(ACTIVE_API_PLIST) != candidate_sha):
        raise ValueError("API_ONLY_ROLLBACK_CURRENT_PLIST_PREIMAGE_MISMATCH")
    guards = _verify_readonly_guards(plan)
    expected_runtime = {"V35_APP_ROOT": str(plan["target"]["app_root"]),
                        "V35_RELEASE_ID": str(plan["target"]["release_id"]),
                        "V35_RELEASE_MANIFEST_SHA256": target["manifest_sha256"]}
    loaded = _loaded_identity(_launchctl_print())
    if any(loaded.get(key) != value for key, value in expected_runtime.items()):
        raise ValueError("API_ONLY_ROLLBACK_LOADED_RUNTIME_NOT_CANDIDATE")
    if backup_path.is_symlink() or not backup_path.is_file() or backup_path.resolve(strict=True).parent != receipt_path.resolve(strict=True).parent:
        raise ValueError("API_ONLY_ROLLBACK_BACKUP_INVALID")
    original_raw = _regular_file(backup_path, "API_ONLY_BACKUP")
    if _sha(original_raw) != plan["before"]["active_api_plist_sha256"]:
        raise ValueError("API_ONLY_ROLLBACK_BACKUP_SHA_MISMATCH")
    operation_dir = _new_operation_dir("-rollback")
    recovery = _restore_after_failure(plan, backup_path, original_raw, candidate_sha,
                                      operation_dir, "OPERATOR_REQUESTED_ROLLBACK",
                                      receipt.get("backup_metadata"))
    recovery["readonly_guards"] = guards
    return recovery


def _plan_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    target = plan["target"]
    return {"status": "PLANNED_NOT_DEPLOYED", "task_root": str(TASK_ROOT),
            "before": plan["before"], "target": target,
            "allowed_live_write": str(ACTIVE_API_PLIST),
            "operation_receipts_and_preimage_backups": str(TASK_ROOT / "phase2/receipts/api_only_switch_runs"),
            "staged_api_plist_path": str(STAGED_API_PLIST_PATH),
            "staged_api_plist_sha256": target.get("staged_api_plist_sha256") or "CANNOT_CONFIRM",
            "scheduler_action": "UNCHANGED", "disabled_binding_action": "READ_ONLY",
            "formal_manager_state_action": "READ_ONLY", "services_operated": False,
            "launchctl_mutation_called": False, "candidate_manifest_sha": target.get("release_manifest_sha256") or "CANNOT_CONFIRM",
            "canary_plan": plan.get("historical_canary_plan"), "safety": plan.get("safety")}


@contextmanager
def _switch_lock():
    lock = _operation_root() / ".api_only_cutover.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("API_ONLY_SWITCH_LOCK_IDENTITY_INVALID")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with os.fdopen(fd, "r+b", closefd=False) as stream:
            yield
    finally:
        os.close(fd)


@contextmanager
def _locked():
    with _switch_lock():
        yield


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="show the frozen target plan without runtime reads or writes")
    sub.add_parser("stage-plist", help="write the pinned staged API plist under phase2 only")
    sub.add_parser("preflight", help="read-only identity, package, binding, and scheduler-guard checks")
    execute = sub.add_parser("execute", help="switch only the API LaunchAgent and verify API plus static UI readback")
    execute.add_argument("--confirm", required=True)
    execute.add_argument("--expected-current-plist-sha256", required=True)
    execute.add_argument("--expected-staged-plist-sha256", required=True)
    rollback = sub.add_parser("rollback", help="restore the exact API plist preimage from a successful receipt")
    rollback.add_argument("--receipt", required=True, type=Path)
    rollback.add_argument("--confirm", required=True)
    rollback.add_argument("--expected-current-plist-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        plan = _load_plan()
        if args.command == "plan":
            result = _plan_summary(plan)
        elif args.command == "stage-plist":
            result = _stage_api_plist(plan)
        elif args.command == "preflight":
            result = _preflight(plan)
        elif args.command == "execute":
            with _locked():
                result = _run_switch(plan, confirmation=args.confirm,
                    expected_current_sha=args.expected_current_plist_sha256,
                    expected_staged_sha=args.expected_staged_plist_sha256)
        else:
            with _locked():
                result = _run_rollback(plan, receipt_path=args.receipt,
                    confirmation=args.confirm,
                    expected_current_sha=args.expected_current_plist_sha256)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        mutating = args.command in {"execute", "rollback"}
        print(json.dumps({"status": "FAILED_CLOSED", "reason": str(exc),
                          "live_state_after_error": "CANNOT_CONFIRM" if mutating else "UNCHANGED",
                          "live_api_or_scheduler_changed": "CANNOT_CONFIRM" if mutating else False},
                         ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
