#!/usr/bin/env python3
"""Prepare and explicitly activate/rollback an isolated V4 announcement release.

This is a task-local operations artifact. The default commands are read-only.
Release preparation copies the dynamically resolved active LaunchAgent release
to a new version directory and overlays four reviewed backend modules, two
reviewed frontend sources, and the reviewed web dist. Activation/rollback
require a separate operations review receipt and explicit confirmation flags.
They replace only the existing API LaunchAgent binding; they do not change
scheduler labels or trading state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import guarded_announcement_import as import_ops
import guarded_announcement_release as release_ops

TASK_ROOT = import_ops.TASK_ROOT
ACTIVE_RELEASE_DEFAULT = release_ops.DEFAULT_ACTIVE_RELEASE
RELEASES_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases")
RUNTIME_PYTHON = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python")
STAGE_SELECTION_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection")
STATE_ROOT = import_ops.STATE_ROOT
API_BASE = import_ops.API_BASE
OPS_APPROVAL_DEFAULT = TASK_ROOT / "RELEASE_OPS_REVIEW_APPROVAL.json"
TRANSACTION_ROOT = TASK_ROOT / "daily_runs/20261007_20261006/active_import/release_transactions"
RECOVERY_RECEIPT_DEFAULT = TASK_ROOT / "ROOT_ACTIVATION_FAILURE_RECOVERY_RECEIPT.json"
RECOVERY_RECEIPT_EXPECTED_SHA256 = "0ae2c2924fa3eed320b770d7c40aa08ec28df75f34dfdba5deea7aa1637a6d8d"
EXPECTED_DIST_AGGREGATE = release_ops.EXPECTED_DIST_AGGREGATE
APPROVAL_SCOPE = "local_announcement_release_stage_activate_and_rollback_only"
LAUNCHD_UNLOAD_TIMEOUT_SECONDS = 20.0
LAUNCHD_UNLOAD_POLL_SECONDS = 0.10
LEGACY_SOURCE_SHA = {
    "v4/manager_research/announcement_catalog.py": "3e653ffd4048c29c38c025049f2db04e87c264d6fbad370e031102f78a3656fd",
    "v4/manager_research/workspace_announcements.py": "2a5f9c1ed375971440007602b8439821b153e1825e73f2fae02ba3c03d682bac",
    "v4/manager_research/announcement_analysis.py": "3efe0d50bc00d0990a9167d3e7abbe48734cf27a4a2bdac00253cab66a7d3c2c",
    "v4/manager_research/service.py": "35eda5e33e0f00f4f64049bf43b9af184c6d6849d8e2c7dec4946f7972a04081",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def approval_check(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if TASK_ROOT.resolve() not in resolved.parents:
        raise ValueError("RELEASE_OPS_APPROVAL_OUTSIDE_TASK_ROOT")
    value = read_json(resolved)
    if (value.get("status") != "REVIEWED_PASS"
            or value.get("candidate_source_test_aggregate_sha256") != import_ops.EXPECTED_AGGREGATE
            or value.get("scope") != APPROVAL_SCOPE
            or not isinstance(value.get("reviewer_identity"), str)
            or not value.get("reviewer_identity")
            or not isinstance(value.get("review_id"), str)
            or not value.get("review_id")):
        raise ValueError("RELEASE_OPS_APPROVAL_RECEIPT_MISSING_OR_INVALID")
    return value


def transaction_dir(staged_root: Path) -> Path:
    label = re.sub(r"[^A-Za-z0-9_.-]+", "_", staged_root.parent.name)
    if not label or label in {".", ".."}:
        raise ValueError("RELEASE_TRANSACTION_NAME_INVALID")
    return TRANSACTION_ROOT / label


def transaction_paths(staged_root: Path) -> dict[str, Path]:
    root = transaction_dir(staged_root)
    return {"root": root, "plan": root / "release_transaction.json",
            "prior_plist": root / "prior_launchagent.plist", "staged_plist": root / "staged_launchagent.plist",
            "attempt": root / "activation_attempt.json", "receipt": root / "activation_receipt.json",
            "rollback_attempt": root / "rollback_attempt.json", "rollback_receipt": root / "rollback_receipt.json"}


def _release_family(name: str) -> str:
    """Group an explicitly versioned retry with its original staged release."""
    return re.sub(r"-r[0-9]+$", "", name)


def _failed_transaction_dirs(staged_root: Path) -> list[Path]:
    family = _release_family(staged_root.parent.name)
    if not TRANSACTION_ROOT.is_dir():
        return []
    result = []
    for child in sorted(TRANSACTION_ROOT.iterdir()):
        if not child.is_dir() or _release_family(child.name) != family:
            continue
        receipt = child / "activation_receipt.json"
        if not receipt.is_file():
            continue
        try:
            value = read_json(receipt)
        except (OSError, json.JSONDecodeError):
            raise ValueError("PRIOR_RELEASE_TRANSACTION_RECEIPT_UNREADABLE:" + child.name)
        if value.get("status") == "ACTIVATION_INDETERMINATE_MANUAL_RECONCILIATION_REQUIRED":
            result.append(child)
    return result


def _reconciled_failure_lineage(staged_root: Path,
                               failed_transaction_root: Path | None,
                               recovery_receipt_path: Path | None) -> dict[str, Any] | None:
    failures = _failed_transaction_dirs(staged_root)
    if not failures:
        if failed_transaction_root is not None or recovery_receipt_path is not None:
            raise ValueError("RECONCILIATION_INPUTS_WITHOUT_PRIOR_FAILED_TRANSACTION")
        return None
    if failed_transaction_root is None or recovery_receipt_path is None:
        raise ValueError("PRIOR_FAILED_TRANSACTION_RECONCILIATION_REQUIRED")
    failed_root = failed_transaction_root.expanduser().resolve()
    matches = [path.resolve() for path in failures]
    if failed_root not in matches or len(failures) != 1:
        raise ValueError("PRIOR_FAILED_TRANSACTION_IDENTITY_MISMATCH_OR_AMBIGUOUS")
    failed_paths = {
        "plan": failed_root / "release_transaction.json",
        "attempt": failed_root / "activation_attempt.json",
        "receipt": failed_root / "activation_receipt.json",
        "prior_plist": failed_root / "prior_launchagent.plist",
    }
    if any(not path.is_file() for path in failed_paths.values()):
        raise ValueError("PRIOR_FAILED_TRANSACTION_EVIDENCE_INCOMPLETE")
    failure_receipt = read_json(failed_paths["receipt"])
    failed_attempt = read_json(failed_paths["attempt"])
    failed_plan = read_json(failed_paths["plan"])
    recovery = recovery_receipt_path.expanduser().resolve()
    canonical_recovery = RECOVERY_RECEIPT_DEFAULT.expanduser().resolve()
    if recovery != canonical_recovery:
        raise ValueError("RECOVERY_RECEIPT_PATH_NOT_CANONICAL")
    if TASK_ROOT.resolve() not in recovery.parents or not recovery.is_file():
        raise ValueError("RECOVERY_RECEIPT_OUTSIDE_TASK_ROOT_OR_MISSING")
    observed_recovery_sha256 = digest(recovery.read_bytes())
    if observed_recovery_sha256 != RECOVERY_RECEIPT_EXPECTED_SHA256:
        raise ValueError("RECOVERY_RECEIPT_SHA256_MISMATCH")
    recovery_value = read_json(recovery)
    prior_sha = digest(failed_paths["prior_plist"].read_bytes())
    failed_plan_payload = {key: value for key, value in failed_plan.items() if key != "sha256"}
    failed_plan_sha = digest(json.dumps(failed_plan_payload, sort_keys=True,
        ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    legacy = recovery_value.get("legacy") or {}
    target = recovery_value.get("target") or {}
    safety = legacy.get("safety") or {}
    if (failure_receipt.get("status") != "ACTIVATION_INDETERMINATE_MANUAL_RECONCILIATION_REQUIRED"
            or failure_receipt.get("attempt") != str(failed_paths["attempt"])
            or failed_attempt.get("one_attempt_only") is not True
            or failed_attempt.get("plan_sha256") != failed_plan_sha
            or failed_plan.get("sha256") != failed_plan_sha
            or failed_plan.get("status") != "STAGED_RELEASE_VERIFIED_NOT_ACTIVATED"
            or failed_plan.get("candidate_source_aggregate_sha256") != import_ops.EXPECTED_AGGREGATE
            or Path(str(failed_plan.get("staged_release_root") or "")).parent.name != failed_root.name
            or failed_attempt.get("staged_release_root") != failed_plan.get("staged_release_root")
            or failed_attempt.get("active_release_root") != failed_plan.get("active_release_root")
            or failed_plan.get("prior_launchagent_plist_sha256") != prior_sha
            or recovery_value.get("status") != "FAILED_CANDIDATE_BOOTSTRAP_PRIOR_OWNER_RESTORED"
            or recovery_value.get("plist_sha256") != prior_sha
            or target.get("expected_preimport_state") is not True
            or target.get("target_trade_date") != import_ops.API_TARGET_DATE
            or target.get("publication_date") != import_ops.API_PUBLICATION_DATE
            or target.get("analysis_status") != "NOT_IMPORTED"
            or target.get("source_status") != "NOT_RUN"
            or target.get("selection_status") != "NOT_ASSESSED"
            or legacy.get("analysis_status") != "VERIFIED"
            or legacy.get("source_status") != "COMPLETE"
            or legacy.get("stock_count") != 140
            or legacy.get("selected_stock_count") != 23
            or safety.get("RESEARCH_ONLY") is not True
            or safety.get("production_allowed") is not False
            or safety.get("buy_gate_updated") is not False
            or safety.get("orders_sent") is not False):
        raise ValueError("PRIOR_FAILED_TRANSACTION_RECOVERY_RECEIPT_INVALID")
    if failure_receipt.get("error", "").find("Bootstrap failed: 5: Input/output error") < 0:
        raise ValueError("PRIOR_FAILED_TRANSACTION_ERROR_NOT_RECONCILED")
    return {
        "superseded_transaction_root": str(failed_root),
        "failed_attempt_sha256": digest(failed_paths["attempt"].read_bytes()),
        "failed_receipt_sha256": digest(failed_paths["receipt"].read_bytes()),
        "failed_plan_sha256": failed_plan_sha,
        "prior_launchagent_sha256": prior_sha,
        "recovery_receipt_path": str(recovery),
        "recovery_receipt_sha256": digest(recovery.read_bytes()),
        "recovery_status": recovery_value["status"],
        "target_preimport_verified": True,
        "legacy_20260929_verified": True,
    }


def safe_runtime_identity(active_root: Path, pid: int | None) -> dict[str, Any]:
    owner = import_ops.launchd_owner_identity(active_root, pid)
    identity = owner["process"]
    if Path(identity["cwd"]).resolve() != active_root.resolve():
        raise ValueError("ACTIVE_RELEASE_CWD_DRIFT")
    if Path(identity["env"].get("V4_MANAGER_RESEARCH_STATE_ROOT") or "").resolve() != STATE_ROOT.resolve():
        raise ValueError("ACTIVE_MANAGER_STATE_ROOT_DRIFT")
    if Path(identity["env"].get("V35_DATA_ROOT") or "").resolve() != Path(
            "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data").resolve():
        raise ValueError("ACTIVE_V35_DATA_ROOT_DRIFT")
    return {"process": identity, "launchd_owner": owner}


def api_preimport_contract() -> dict[str, Any]:
    baseline = import_ops.target_analysis_baseline()
    if not baseline.get("expected_preimport_state"):
        raise ValueError("TARGET_DATE_NOT_IN_EXPECTED_PREIMPORT_STATE")
    return baseline


def active_baseline_contract(active_root: Path, pid: int | None) -> dict[str, Any]:
    owner = safe_runtime_identity(active_root, pid)
    source_hashes = import_ops.release_source_hashes(active_root)
    if source_hashes != LEGACY_SOURCE_SHA:
        raise ValueError("ACTIVE_RELEASE_SOURCE_BASELINE_DRIFT")
    legacy = import_ops.legacy_readback()
    target = api_preimport_contract()
    return {"process": owner["process"], "launchd_owner": owner["launchd_owner"],
            "source_sha256": source_hashes,
            "legacy_20260929": legacy, "target_20261007_preimport": target}


def overlay_paths() -> tuple[Path, dict[str, str]]:
    candidate = import_ops.candidate_source_check()
    frontend = release_ops.candidate_frontend_source_hashes()
    dist = release_ops.tree_manifest(release_ops.DEFAULT_WEB_DIST)
    if (dist["file_count"] != 11 or dist["bytes_total"] != 798364
            or dist["aggregate_sha256"] != EXPECTED_DIST_AGGREGATE):
        raise ValueError("REVIEWED_FRONTEND_DIST_HASH_MISMATCH")
    return release_ops.DEFAULT_WEB_DIST, {**candidate["source_sha256"], **frontend}


def manifest_rows(root: Path) -> dict[str, dict[str, Any]]:
    if not root.is_dir():
        raise ValueError("RELEASE_DIRECTORY_MISSING")
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise ValueError("RELEASE_TREE_CONTAINS_SYMLINK")
        relative = path.relative_to(root).as_posix()
        result[relative] = {"bytes": path.stat().st_size, "sha256": digest(path.read_bytes())}
    return result


def _manifest_entries(root: Path) -> list[dict[str, Any]]:
    return release_ops.inventory_entries(root)


def _update_release_manifest(active_owner: dict[str, Any], staged_root: Path,
                             manifest_path: Path) -> tuple[bytes, str]:
    environment = active_owner["program_environment"]
    source_path = Path(environment.get("V35_RELEASE_MANIFEST_PATH", "")).resolve()
    active_root = Path(active_owner["active_root"]).resolve()
    if (not source_path.is_file() or source_path.parent != active_root.parent
            or digest(source_path.read_bytes()) != environment.get("V35_RELEASE_MANIFEST_SHA256")):
        raise ValueError("ACTIVE_RELEASE_MANIFEST_IDENTITY_MISMATCH")
    source_manifest = json.loads(source_path.read_text(encoding="utf-8"))
    current_entries = _manifest_entries(active_root)
    current_inventory = source_manifest.get("application_inventory") or {}
    if (source_manifest.get("candidate", {}).get("app_root") != str(active_root)
            or source_manifest.get("candidate", {}).get("release_id") != source_path.parent.name
            or current_inventory.get("entry_count") != len(current_entries)
            or current_inventory.get("aggregate_sha256") != release_ops.inventory_digest(current_entries)
            or current_inventory.get("entries") != current_entries):
        raise ValueError("ACTIVE_RELEASE_MANIFEST_CONTENT_DRIFT")
    result = json.loads(json.dumps(source_manifest))
    entries = _manifest_entries(staged_root)
    symlinks = [item for item in entries if item.get("kind") == "symlink"]
    result["candidate"].update(root=str(staged_root.parent.resolve()),
        app_root=str(staged_root.resolve()), release_id=staged_root.parent.name)
    result["candidate_status"] = "READY_FOR_INDEPENDENT_REVIEW"
    result["activation_status"] = "NOT_ACTIVATED"
    result["deployment_status"] = "NOT_DEPLOYED"
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["application_inventory"] = {
        "entry_count": len(entries),
        "aggregate_sha256": release_ops.inventory_digest(entries),
        "entries": entries,
        "symlink_entries": symlinks,
        "missing_symlink_targets": [item["path"] for item in symlinks if not item.get("target_exists")],
    }
    dist_entries = _manifest_entries(staged_root / "apps/web/dist")
    result["frontend_dist"].update(
        entry_count=len(dist_entries),
        aggregate_sha256=release_ops.inventory_digest(dist_entries),
        entries=dist_entries,
        source_relative_root="apps/web/dist",
        build_source="reviewed announcement analysis frontend; " + EXPECTED_DIST_AGGREGATE,
    )
    if (result.get("research_only") is not True or result.get("production_allowed") is not False
            or result.get("buy_gate_updated") is not False or result.get("orders_sent") is not False):
        raise ValueError("ACTIVE_RELEASE_MANIFEST_SAFETY_CONTRACT_INVALID")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    manifest_path.write_bytes(raw)
    return raw, digest(raw)


def _staged_launchagent_bytes(owner: dict[str, Any], staged_root: Path,
                              manifest_path: Path, manifest_sha: str) -> bytes:
    payload = json.loads(json.dumps(owner["plist_payload"]))
    args = payload["ProgramArguments"]
    replacements = {
        "V35_APP_ROOT": str(staged_root.resolve()),
        "V35_RELEASE_ID": staged_root.parent.name,
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path.resolve()),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
        "PYTHONPATH": str(staged_root / "upstreams") + ":" + str(staged_root.resolve()),
    }
    found: set[str] = set()
    for index, item in enumerate(args):
        if isinstance(item, str) and "=" in item:
            key, _ = item.split("=", 1)
            if key in replacements:
                args[index] = key + "=" + replacements[key]
                found.add(key)
    if found != set(replacements):
        raise ValueError("ACTIVE_LAUNCHAGENT_RELEASE_BINDINGS_INCOMPLETE")
    payload["WorkingDirectory"] = str(staged_root.resolve())
    encoded = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)
    decoded = plistlib.loads(encoded)
    if (decoded.get("Label") != import_ops.LAUNCHD_LABEL or decoded.get("KeepAlive") is not True
            or decoded.get("WorkingDirectory") != replacements["V35_APP_ROOT"]):
        raise ValueError("STAGED_LAUNCHAGENT_CONTENT_INVALID")
    return encoded


def _atomic_replace_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.chmod(temp_path, old_mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _launchctl(args: list[str]) -> dict[str, Any]:
    result = subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ValueError("LAUNCHCTL_COMMAND_FAILED:" + " ".join(args) + ":" + result.stderr.strip()[:500])
    return {"argv": ["launchctl", *args], "returncode": result.returncode,
            "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]}


def _launchd_service_probe(service_target: str) -> dict[str, Any]:
    """Return only the exact label's load state; never persist launchd's full environment dump."""
    result = subprocess.run(["launchctl", "print", service_target], capture_output=True, text=True, check=False)
    if result.returncode == 0:
        state_match = re.search(r"(?m)^\s*state\s*=\s*(\S+)", result.stdout)
        pid_match = re.search(r"(?m)^\s*pid\s*=\s*(\d+)", result.stdout)
        return {"loaded": True, "state": state_match.group(1) if state_match else "STATE_UNREPORTED",
                "pid": int(pid_match.group(1)) if pid_match else None}
    diagnostic = (result.stdout + "\n" + result.stderr).strip()
    if "Could not find service" in diagnostic:
        return {"loaded": False, "state": "UNLOADED", "pid": None}
    raise ValueError("LAUNCHD_UNLOAD_PROBE_FAILED:" + str(result.returncode) + ":" + diagnostic[:300])


def wait_for_service_unloaded(service_target: str, *, timeout_seconds: float = LAUNCHD_UNLOAD_TIMEOUT_SECONDS,
                              poll_seconds: float = LAUNCHD_UNLOAD_POLL_SECONDS) -> dict[str, Any]:
    """Wait for launchd to remove the booted-out service before replacing its plist."""
    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("LAUNCHD_UNLOAD_WAIT_BOUNDS_INVALID")
    started = time.monotonic()
    deadline = started + timeout_seconds
    last_probe: dict[str, Any] = {"loaded": True, "state": "NOT_PROBED", "pid": None}
    while time.monotonic() < deadline:
        last_probe = _launchd_service_probe(service_target)
        if not last_probe["loaded"]:
            return {"service_target": service_target, "status": "UNLOADED",
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "poll_seconds": poll_seconds, "last_probe": last_probe}
        time.sleep(poll_seconds)
    raise ValueError("LAUNCHD_SERVICE_UNLOAD_TIMEOUT:" + service_target + ":state="
                     + str(last_probe.get("state")) + ":pid=" + str(last_probe.get("pid")))


def switch_launchagent(owner: dict[str, Any], expected_plist_sha256: str,
                       replacement_plist: bytes) -> dict[str, Any]:
    """Replace the existing API LaunchAgent config through its launchd owner."""
    plist_path = Path(owner["plist_path"])
    if not plist_path.is_file() or digest(plist_path.read_bytes()) != expected_plist_sha256:
        raise ValueError("ACTIVE_LAUNCHAGENT_BYTES_CHANGED_BEFORE_SWITCH")
    bootout = _launchctl(["bootout", owner["service_target"]])
    unloaded = wait_for_service_unloaded(owner["service_target"])
    _atomic_replace_bytes(plist_path, replacement_plist)
    bootstrap = _launchctl(["bootstrap", f"gui/{os.getuid()}", str(plist_path)])
    return {"bootout": bootout, "wait_until_unloaded": unloaded, "bootstrap": bootstrap,
            "replacement_plist_sha256": digest(replacement_plist)}


def assert_only_reviewed_overlay(active_root: Path, staged_root: Path) -> dict[str, Any]:
    before = manifest_rows(active_root)
    after = manifest_rows(staged_root)
    dist_prefix = "apps/web/dist/"
    allowed = set(import_ops.SOURCE_RECORDS) | set(release_ops.FRONTEND_SOURCE_RECORDS)
    changed = []
    removed = []
    added = []
    for path in sorted(set(before) | set(after)):
        if path not in before:
            added.append(path)
        elif path not in after:
            removed.append(path)
        elif before[path] != after[path]:
            changed.append(path)
    unexpected = [path for path in changed + removed + added
        if path not in allowed and not path.startswith(dist_prefix)]
    if unexpected:
        raise ValueError("STAGED_RELEASE_HAS_UNREVIEWED_FILE_CHANGES:" + ",".join(unexpected[:12]))
    if not allowed.issubset(set(changed)):
        raise ValueError("STAGED_RELEASE_REVIEWED_SOURCE_OVERLAY_INCOMPLETE")
    if not any(path.startswith(dist_prefix) for path in changed + removed + added):
        raise ValueError("STAGED_RELEASE_FRONTEND_OVERLAY_MISSING")
    return {"changed_reviewed_source_files": sorted(path for path in changed if path in allowed),
            "changed_backend_files": sorted(path for path in changed if path in import_ops.SOURCE_RECORDS),
            "changed_frontend_typescript_files": sorted(path for path in changed if path in release_ops.FRONTEND_SOURCE_RECORDS),
            "changed_dist_files": sorted(path for path in changed + removed + added if path.startswith(dist_prefix)),
            "added_files_outside_overlay": [], "removed_files_outside_overlay": []}


def prepare_release(active_root: Path, staged_root: Path, pid: int | None = None,
                    approval_path: Path = OPS_APPROVAL_DEFAULT,
                    superseded_failed_transaction_root: Path | None = None,
                    recovery_receipt_path: Path | None = None) -> dict[str, Any]:
    approval = approval_check(approval_path)
    active_root = active_root.resolve()
    staged_root = staged_root.expanduser().resolve()
    releases_root = RELEASES_ROOT.resolve()
    active_root, staged_root = release_ops.assert_disjoint_release_paths(active_root, staged_root)
    if releases_root not in staged_root.parents:
        raise ValueError("STAGED_RELEASE_OUTSIDE_RELEASES_ROOT")
    if staged_root.exists() or staged_root.parent.exists():
        raise ValueError("STAGED_RELEASE_PATH_ALREADY_EXISTS_NO_OVERWRITE")
    failure_lineage = _reconciled_failure_lineage(staged_root,
        superseded_failed_transaction_root, recovery_receipt_path)
    active = active_baseline_contract(active_root, pid)
    candidate_dist, source_hashes = overlay_paths()
    paths = transaction_paths(staged_root)
    if any(path.exists() for path in paths.values()):
        raise ValueError("RELEASE_TRANSACTION_EXISTS_NO_RETRY")
    paths["root"].mkdir(parents=True, exist_ok=False)
    staged_root.parent.mkdir(parents=False, exist_ok=False)
    try:
        shutil.copytree(active_root, staged_root, symlinks=True)
        for relative, expected_sha in source_hashes.items():
            if relative in import_ops.SOURCE_RECORDS:
                source = import_ops.TASK_ROOT / "candidate" / relative
            else:
                source = import_ops.TASK_ROOT / "candidate_frontend" / relative
            destination = staged_root / relative
            if digest(source.read_bytes()) != expected_sha:
                raise ValueError("FROZEN_BACKEND_SOURCE_CHANGED:" + relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        old_dist = staged_root / "apps/web/dist"
        if old_dist.is_symlink() or old_dist.resolve() != (staged_root / "apps/web/dist").resolve():
            raise ValueError("STAGED_WEB_DIST_PATH_UNSAFE")
        if old_dist.exists():
            shutil.rmtree(old_dist)
        shutil.copytree(candidate_dist, old_dist)
        manifest_path = staged_root.parent / "release-manifest.json"
        _, manifest_sha = _update_release_manifest(active["launchd_owner"], staged_root, manifest_path)
        prior_plist_raw = Path(active["launchd_owner"]["plist_path"]).read_bytes()
        staged_plist_raw = _staged_launchagent_bytes(active["launchd_owner"], staged_root,
            manifest_path, manifest_sha)
        paths["prior_plist"].write_bytes(prior_plist_raw)
        paths["staged_plist"].write_bytes(staged_plist_raw)
        delta = assert_only_reviewed_overlay(active_root, staged_root)
        verification = release_ops.verify_staged(active_root, staged_root, pid)
        result = {
            "schema": "v4.manager_research.announcement_release_transaction.v1",
            "status": "STAGED_RELEASE_VERIFIED_NOT_ACTIVATED",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "candidate_source_aggregate_sha256": import_ops.EXPECTED_AGGREGATE,
            "approval": approval,
            "active_release_root": str(active_root),
            "staged_release_root": str(staged_root),
            "prior_active_pid": pid,
            "prior_process_identity": active["process"],
            "prior_launchd_owner": {key: active["launchd_owner"][key]
                for key in ("label", "plist_path", "plist_sha256", "service_target")},
            "prior_launchagent_plist_sha256": digest(prior_plist_raw),
            "staged_launchagent_plist_sha256": digest(staged_plist_raw),
            "superseded_failed_transaction": failure_lineage,
            "staged_release_manifest_sha256": manifest_sha,
            "prior_backend_source_sha256": active["source_sha256"],
            "legacy_contract": active["legacy_20260929"],
            "target_preimport_contract": active["target_20261007_preimport"],
            "overlay_delta": delta,
            "staged_release_verification": verification,
            "activation_performed": False,
            "launchd_mutation_performed": False,
        }
        result["sha256"] = digest(json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        atomic_json(paths["plan"], result)
        return result
    except Exception:
        # The destination is always a new, task-named release directory. If its
        # construction fails, preserve it for inspection rather than deleting
        # files automatically or touching the active release.
        raise


def verify_transaction(active_root: Path, staged_root: Path, pid: int | None) -> dict[str, Any]:
    active_root, staged_root = release_ops.assert_disjoint_release_paths(active_root, staged_root)
    paths = transaction_paths(staged_root)
    plan = read_json(paths["plan"])
    if plan.get("status") != "STAGED_RELEASE_VERIFIED_NOT_ACTIVATED":
        raise ValueError("STAGED_RELEASE_PLAN_STATUS_INVALID")
    if plan.get("candidate_source_aggregate_sha256") != import_ops.EXPECTED_AGGREGATE:
        raise ValueError("STAGED_RELEASE_CANDIDATE_AGGREGATE_MISMATCH")
    if (Path(plan.get("active_release_root", "")).resolve() != active_root.resolve()
            or Path(plan.get("staged_release_root", "")).resolve() != staged_root.resolve()):
        raise ValueError("STAGED_RELEASE_PLAN_PATH_MISMATCH")
    lineage = plan.get("superseded_failed_transaction")
    if lineage is None:
        current_lineage = _reconciled_failure_lineage(staged_root, None, None)
    else:
        current_lineage = _reconciled_failure_lineage(
            staged_root,
            Path(str(lineage.get("superseded_transaction_root") or "")),
            Path(str(lineage.get("recovery_receipt_path") or "")))
    if current_lineage != lineage:
        raise ValueError("STAGED_RELEASE_FAILED_TRANSACTION_RECONCILIATION_DRIFT")
    active = active_baseline_contract(active_root, pid)
    if (active["launchd_owner"]["plist_sha256"] != plan.get("prior_launchagent_plist_sha256")
            or digest(paths["prior_plist"].read_bytes()) != plan.get("prior_launchagent_plist_sha256")
            or digest(paths["staged_plist"].read_bytes()) != plan.get("staged_launchagent_plist_sha256")):
        raise ValueError("LAUNCHAGENT_TRANSACTION_BYTES_DRIFT")
    delta = assert_only_reviewed_overlay(active_root, staged_root)
    staged = release_ops.verify_staged(active_root, staged_root, pid)
    return {"status": "STAGED_RELEASE_VERIFIED_NOT_ACTIVATED", "plan_sha256": plan.get("sha256"),
            "active_identity": active["process"], "overlay_delta": delta,
            "staged_release_verification": staged, "process_switch_or_restart_performed": False}


def wait_for_api(expected_root: Path, expected_pid: int | None = None,
                 require_candidate: bool = True) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    last_error = None
    while time.monotonic() < deadline:
        try:
            owner = import_ops.launchd_owner_identity(expected_root, expected_pid)
            expected_sources = import_ops.SOURCE_RECORDS if require_candidate else LEGACY_SOURCE_SHA
            if import_ops.release_source_hashes(expected_root) != expected_sources:
                raise ValueError("API_RELEASE_SOURCE_HASH_MISMATCH")
            if require_candidate:
                if {relative: digest((expected_root / relative).read_bytes())
                        for relative in release_ops.FRONTEND_SOURCE_RECORDS} != release_ops.FRONTEND_SOURCE_RECORDS:
                    raise ValueError("NEW_API_FRONTEND_SOURCE_HASH_MISMATCH")
                dist = release_ops.tree_manifest(expected_root / "apps/web/dist")
                if dist["aggregate_sha256"] != EXPECTED_DIST_AGGREGATE:
                    raise ValueError("NEW_API_FRONTEND_DIST_HASH_MISMATCH")
            legacy = import_ops.legacy_readback()
            target = api_preimport_contract()
            return {"process": owner["process"], "launchd_owner": {
                        key: owner[key] for key in ("label", "plist_path", "plist_sha256", "service_target")},
                    "legacy_20260929": legacy, "target_20261007_preimport": target}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            last_error = f"{type(exc).__name__}:{exc}"
            time.sleep(0.5)
    raise ValueError("NEW_API_READBACK_TIMEOUT:" + str(last_error))


def activate_release(active_root: Path, staged_root: Path, pid: int | None,
                     approval_path: Path, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("ACTIVATION_CONFIRMATION_FLAG_REQUIRED")
    active_root, staged_root = release_ops.assert_disjoint_release_paths(active_root, staged_root)
    approval = approval_check(approval_path)
    paths = transaction_paths(staged_root)
    if paths["attempt"].exists() or paths["receipt"].exists():
        raise ValueError("PRIOR_ACTIVATION_ATTEMPT_OR_RECEIPT_EXISTS_NO_RETRY")
    stage = verify_transaction(active_root, staged_root, pid)
    old_identity = stage["active_identity"]
    owner = import_ops.launchd_owner_identity(active_root, pid)
    if owner["plist_sha256"] != read_json(paths["plan"]).get("prior_launchagent_plist_sha256"):
        raise ValueError("ACTIVE_LAUNCHAGENT_CHANGED_AFTER_PREPARE")
    prior_raw = paths["prior_plist"].read_bytes()
    staged_raw = paths["staged_plist"].read_bytes()
    if (digest(prior_raw) != owner["plist_sha256"]
            or digest(staged_raw) != read_json(paths["plan"]).get("staged_launchagent_plist_sha256")):
        raise ValueError("LAUNCHAGENT_ACTIVATION_BYTES_MISMATCH")
    pid = owner["pid"]
    attempt = {"schema": "v4.manager_research.announcement_release_activation_attempt.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_source_aggregate_sha256": import_ops.EXPECTED_AGGREGATE,
        "approval": approval, "plan_sha256": stage["plan_sha256"],
        "active_release_root": str(active_root.resolve()),
        "staged_release_root": str(staged_root.resolve()), "old_pid": pid,
        "old_process_identity": old_identity, "one_attempt_only": True}
    atomic_json(paths["attempt"], attempt)
    result: dict[str, Any] = {"status": "ACTIVATION_INDETERMINATE", "attempt": str(paths["attempt"]),
        "activation_performed": False, "launchd_mutation_performed": False}
    try:
        switch = switch_launchagent(owner, digest(prior_raw), staged_raw)
        readback = wait_for_api(staged_root)
        new_pid = readback["process"]["pid"]
        staged_hashes = import_ops.release_source_hashes(staged_root)
        if staged_hashes != import_ops.SOURCE_RECORDS:
            raise ValueError("NEW_API_RELEASE_SOURCE_HASH_MISMATCH")
        result.update(status="PASS_RELEASE_ACTIVE_AND_API_READBACK", new_pid=new_pid,
            readback=readback, staged_backend_source_sha256=staged_hashes,
            staged_frontend_source_sha256={relative: digest((staged_root / relative).read_bytes())
                for relative in release_ops.FRONTEND_SOURCE_RECORDS},
            web_dist=release_ops.tree_manifest(staged_root / "apps/web/dist"),
            launchctl=switch,
            terminal_at_utc=datetime.now(timezone.utc).isoformat(), activation_performed=True,
            launchd_mutation_performed=True)
        atomic_json(paths["receipt"], result)
        return result
    except Exception as exc:
        result.update(status="ACTIVATION_INDETERMINATE_MANUAL_RECONCILIATION_REQUIRED",
            error=f"{type(exc).__name__}:{exc}", terminal_at_utc=datetime.now(timezone.utc).isoformat(),
            launchd_mutation_performed=Path(owner["plist_path"]).read_bytes() != prior_raw)
        atomic_json(paths["receipt"], result)
        raise


def rollback_release(active_root: Path, staged_root: Path, current_pid: int | None,
                     approval_path: Path, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise ValueError("ROLLBACK_CONFIRMATION_FLAG_REQUIRED")
    active_root, staged_root = release_ops.assert_disjoint_release_paths(active_root, staged_root)
    approval = approval_check(approval_path)
    paths = transaction_paths(staged_root)
    if paths["rollback_attempt"].exists() or paths["rollback_receipt"].exists():
        raise ValueError("PRIOR_RELEASE_ROLLBACK_ATTEMPT_OR_RECEIPT_EXISTS_NO_RETRY")
    if not paths["attempt"].is_file() or not paths["receipt"].is_file():
        raise ValueError("SUCCESSFUL_ACTIVATION_RECEIPT_REQUIRED_FOR_RELEASE_ROLLBACK")
    activation = read_json(paths["receipt"])
    if activation.get("status") != "PASS_RELEASE_ACTIVE_AND_API_READBACK" or not activation.get("new_pid"):
        raise ValueError("SUCCESSFUL_ACTIVATION_RECEIPT_INVALID")
    owner = import_ops.launchd_owner_identity(staged_root, current_pid)
    identity = owner["process"]
    current_pid = owner["pid"]
    if current_pid != activation["new_pid"] or owner["plist_sha256"] != read_json(paths["plan"]).get("staged_launchagent_plist_sha256"):
        raise ValueError("CANDIDATE_PID_DRIFT_BLOCKS_RELEASE_ROLLBACK")
    if import_ops.release_source_hashes(staged_root) != import_ops.SOURCE_RECORDS:
        raise ValueError("ACTIVE_CANDIDATE_SOURCE_DRIFT_BLOCKS_RELEASE_ROLLBACK")
    if (digest(Path(owner["plist_path"]).read_bytes()) != owner["plist_sha256"]
            or digest(paths["prior_plist"].read_bytes()) != read_json(paths["plan"]).get("prior_launchagent_plist_sha256")):
        raise ValueError("LAUNCHAGENT_ROLLBACK_BYTES_DRIFT")
    # The target catalog must first be removed by the separate exact owner
    # rollback if it was imported; this release operation never deletes data.
    target = api_preimport_contract()
    legacy = import_ops.legacy_readback()
    attempt = {"schema": "v4.manager_research.announcement_release_rollback_attempt.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "approval": approval,
        "candidate_source_aggregate_sha256": import_ops.EXPECTED_AGGREGATE,
        "activation_receipt_sha256": digest(paths["receipt"].read_bytes()),
        "current_pid": current_pid, "current_process_identity": identity,
        "current_launchd_owner": {key: owner[key] for key in ("label", "plist_path", "plist_sha256", "service_target")},
        "restore_release_root": str(active_root.resolve()), "one_attempt_only": True}
    atomic_json(paths["rollback_attempt"], attempt)
    try:
        prior_raw = paths["prior_plist"].read_bytes()
        switch = switch_launchagent(owner, owner["plist_sha256"], prior_raw)
        restored = wait_for_api(active_root, require_candidate=False)
        restored_pid = restored["process"]["pid"]
        restored_hashes = import_ops.release_source_hashes(active_root)
        if restored_hashes != LEGACY_SOURCE_SHA:
            raise ValueError("RESTORED_RELEASE_SOURCE_HASH_MISMATCH")
        receipt = {"schema": "v4.manager_research.announcement_release_rollback_receipt.v1",
            "status": "PASS_RELEASE_ROLLED_BACK_AND_API_READBACK", "restored_pid": restored_pid,
            "restored_release_root": str(active_root.resolve()), "restored_source_sha256": restored_hashes,
            "legacy_20260929_contract": restored["legacy_20260929"],
            "target_20261007_preimport_contract": restored["target_20261007_preimport"],
            "candidate_process_identity_before_rollback": identity,
            "target_preimport_before_rollback": target, "legacy_before_rollback": legacy,
            "launchctl": switch,
            "activation_receipt_sha256": attempt["activation_receipt_sha256"],
            "terminal_at_utc": datetime.now(timezone.utc).isoformat(),
            "candidate_release_preserved": True, "catalog_data_changed": False}
        atomic_json(paths["rollback_receipt"], receipt)
        return receipt
    except Exception as exc:
        receipt = {"schema": "v4.manager_research.announcement_release_rollback_receipt.v1",
            "status": "ROLLBACK_INDETERMINATE_MANUAL_RECONCILIATION_REQUIRED",
            "error": f"{type(exc).__name__}:{exc}", "terminal_at_utc": datetime.now(timezone.utc).isoformat(),
            "candidate_release_preserved": True, "catalog_data_changed": False,
            "launchd_mutation_performed": Path(owner["plist_path"]).read_bytes() != paths["staged_plist"].read_bytes()}
        atomic_json(paths["rollback_receipt"], receipt)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Copy a new release and overlay the exact reviewed files.")
    prep.add_argument("--active-release-root", type=Path, default=ACTIVE_RELEASE_DEFAULT)
    prep.add_argument("--staged-release-root", type=Path, required=True)
    prep.add_argument("--pid", type=int, help="Optional guard; must match the PID dynamically resolved from launchd.")
    prep.add_argument("--approval", type=Path, default=OPS_APPROVAL_DEFAULT)
    prep.add_argument("--superseded-failed-transaction-root", type=Path,
        help="Required when retrying a release family with a preserved indeterminate activation receipt.")
    prep.add_argument("--recovery-receipt", type=Path,
        help="Task-local receipt proving the prior owner was restored before a new transaction is prepared.")
    check = sub.add_parser("verify", help="Read-only verification of a prepared release.")
    check.add_argument("--active-release-root", type=Path, default=ACTIVE_RELEASE_DEFAULT)
    check.add_argument("--staged-release-root", type=Path, required=True)
    check.add_argument("--pid", type=int, help="Optional guard; must match the PID dynamically resolved from launchd.")
    activate = sub.add_parser("activate", help="Reload the current API through its existing LaunchAgent on the staged release.")
    activate.add_argument("--active-release-root", type=Path, default=ACTIVE_RELEASE_DEFAULT)
    activate.add_argument("--staged-release-root", type=Path, required=True)
    activate.add_argument("--pid", type=int, help="Optional guard; current owner PID is resolved from launchd.")
    activate.add_argument("--approval", type=Path, default=OPS_APPROVAL_DEFAULT)
    activate.add_argument("--confirm-activation", action="store_true")
    rollback = sub.add_parser("rollback", help="Restore the preserved prior release after a successful activation.")
    rollback.add_argument("--active-release-root", type=Path, default=ACTIVE_RELEASE_DEFAULT)
    rollback.add_argument("--staged-release-root", type=Path, required=True)
    rollback.add_argument("--pid", type=int, help="Optional guard; current owner PID is resolved from launchd.")
    rollback.add_argument("--approval", type=Path, default=OPS_APPROVAL_DEFAULT)
    rollback.add_argument("--confirm-rollback", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            value = prepare_release(args.active_release_root, args.staged_release_root, args.pid, args.approval,
                args.superseded_failed_transaction_root, args.recovery_receipt)
        elif args.command == "verify":
            value = verify_transaction(args.active_release_root, args.staged_release_root, args.pid)
        elif args.command == "activate":
            value = activate_release(args.active_release_root, args.staged_release_root, args.pid,
                args.approval, args.confirm_activation)
        else:
            value = rollback_release(args.active_release_root, args.staged_release_root, args.pid,
                args.approval, args.confirm_rollback)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
