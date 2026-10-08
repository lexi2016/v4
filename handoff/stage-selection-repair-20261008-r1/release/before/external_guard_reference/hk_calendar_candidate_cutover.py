#!/usr/bin/env python3
"""Gated, per-service cutover wrapper for the frozen HK calendar candidates.

`preflight` is read-only. `apply` and `rollback` are deliberately separate
operations for the API and scheduler labels and require a matching independent
review receipt, frozen active identity, and a service-specific confirmation
string. This wrapper has not been executed against launchd.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


EVIDENCE_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_HK_CLOSE_DAILY_20261007/hk_market_calendar")
IDENTITY_PATH = EVIDENCE_ROOT / "candidate_identity_20261007.json"
EXPECTED_IDENTITY_SHA256 = "e6a770f02539b4eaddab510ca425fc8b8231a0670e2d1758c4f017ce4f328de8"
READBACK_PATH = EVIDENCE_ROOT / "candidate_hk_calendar_readback_20261007.json"
REVIEW_RECEIPT = EVIDENCE_ROOT / "candidate_hk_calendar_independent_review_20261007.json"
DRIFT_PREFIX = "cutover-drift-"
BASELINE_INVENTORY_SHA256 = {
    "api": "331b961ff69c057f5c2cd1b3d64058421a2a463330cb63c1e6fed2edc3b43104",
    "scheduler": "a9b4cfcefaf64da63ec27c420ba41f45343dd0514d0f9b2a81004814a779cdda",
}

CONFIRMATIONS = {
    "api": "ACTIVATE_HK_CLOSE_HK_CALENDAR_R2_API",
    "scheduler": "ACTIVATE_HK_CLOSE_HK_CALENDAR_R2_SCHEDULER",
}
ROLLBACK_CONFIRMATIONS = {
    "api": "ROLLBACK_HK_CLOSE_HK_CALENDAR_R2_API",
    "scheduler": "ROLLBACK_HK_CLOSE_HK_CALENDAR_R2_SCHEDULER",
}
PROCESS_READY_TIMEOUT_SECONDS = 30.0
PROCESS_READY_POLL_INTERVAL_SECONDS = 0.25


class GateError(RuntimeError):
    pass


class RuntimeIdentityDrift(GateError):
    """The loaded process cannot be proven to match the reviewed candidate."""


class LaunchdLabelAbsent(GateError):
    """The requested exact launchd service label is confirmed absent."""


def _monotonic_now() -> float:
    return time.monotonic()


def _sleep_for_poll(seconds: float) -> None:
    time.sleep(seconds)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GateError(f"expected a JSON object: {path}")
    return value


def frozen_identity() -> dict[str, Any]:
    observed = sha256_file(IDENTITY_PATH)
    if observed != EXPECTED_IDENTITY_SHA256:
        raise GateError("candidate identity file changed; re-freeze and re-review before cutover")
    identity = json_read(IDENTITY_PATH)
    if identity.get("production_allowed") is not False or identity.get("buy_gate_updated") is not False or identity.get("orders_sent") is not False:
        raise GateError("candidate identity violates the frozen research-only safety flags")
    return identity


def service_identity(service: str) -> dict[str, Any]:
    if service not in ("api", "scheduler"):
        raise GateError(f"unknown service: {service}")
    identity = frozen_identity()
    item = identity.get(service)
    if not isinstance(item, dict):
        raise GateError(f"candidate identity has no {service} entry")
    return item


def inventory(root: Path) -> list[dict[str, Any]]:
    import stat as stat_module

    rows: list[dict[str, Any]] = []
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directories.sort()
        filenames.sort()
        kept: list[str] = []
        for name in directories:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                rows.append({"path": relative, "kind": "symlink", "target": os.readlink(path), "target_exists": path.exists()})
            else:
                kept.append(name)
        directories[:] = kept
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat_module.S_ISLNK(info.st_mode):
                rows.append({"path": relative, "kind": "symlink", "target": os.readlink(path), "target_exists": path.exists()})
            elif stat_module.S_ISREG(info.st_mode):
                rows.append({
                    "path": relative,
                    "kind": "file",
                    "sha256": sha256_file(path),
                    "mode": f"{stat_module.S_IMODE(info.st_mode):04o}",
                    "size": info.st_size,
                })
            else:
                raise GateError(f"unsupported file type in release inventory: {path}")
    return sorted(rows, key=lambda row: row["path"])


def inventory_sha256(entries: list[dict[str, Any]]) -> str:
    raw = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(raw.encode("utf-8"))


def plist_environment(plist: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in plist.get("ProgramArguments", []):
        if isinstance(value, str) and "=" in value:
            key, item = value.split("=", 1)
            if key and not any(char.isspace() for char in key):
                result[key] = item
    for key, value in (plist.get("EnvironmentVariables") or {}).items():
        if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
            result[key] = str(value)
    return result


def drift(*, service: str, phase: str, path: Path, expected: str, observed: str | None, details: dict[str, Any] | None = None) -> Path:
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "v4.hk_calendar_cutover_drift.v1",
        "service": service,
        "phase": phase,
        "path": str(path),
        "expected_sha256": expected,
        "observed_sha256": observed,
        "details": details,
        "recorded_at_epoch_ns": time.time_ns(),
        "service_action_performed_by_recording": False,
    }
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    for suffix in range(100):
        target = EVIDENCE_ROOT / f"{DRIFT_PREFIX}{service}-{time.time_ns()}-{suffix:02d}.json"
        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        return target
    raise GateError("could not write a unique drift receipt")


def require_sha(path: Path, expected: str, *, service: str, phase: str) -> str:
    try:
        actual = sha256_file(path)
    except FileNotFoundError:
        drift(service=service, phase=phase, path=path, expected=expected, observed=None)
        raise GateError(f"{phase}: required file is missing: {path}")
    if actual != expected:
        drift(service=service, phase=phase, path=path, expected=expected, observed=actual)
        raise GateError(f"{phase}: frozen file SHA changed: {path}")
    return actual


def is_runtime_bytecode(row: dict[str, Any]) -> bool:
    path = Path(str(row.get("path", "")))
    return path.suffix == ".pyc" and "__pycache__" in path.parts


def split_runtime_cache(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = [row for row in entries if not is_runtime_bytecode(row)]
    runtime = [row for row in entries if is_runtime_bytecode(row)]
    return source, runtime


def verify_candidate(service: str, *, allow_runtime_bytecode_delta: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    item = service_identity(service)
    root = Path(item["candidate_root"])
    app = Path(item["candidate_app_root"])
    manifest_path = Path(item["candidate_manifest_path"])
    staged_plist = Path(item["candidate_plist_path"])
    manifest_sha = item["candidate_manifest_sha256"]
    inventory_sha = item["candidate_app_inventory_sha256"]
    if not root.is_dir() or not app.is_dir():
        raise GateError(f"{service} candidate release is missing: {root}")
    require_sha(manifest_path, manifest_sha, service=service, phase="VERIFY_CANDIDATE_MANIFEST")
    manifest = json_read(manifest_path)
    candidate = manifest.get("candidate") or {}
    # The R9 scheduler manifest is an overlay contract: candidate.root and
    # candidate.release_id identify its frozen R9 source, while target_root
    # and top-level release_id identify this prepared release. Keep that native
    # schema and validate its explicit target fields instead of rewriting it.
    manifest_root = candidate.get("target_root") if service == "scheduler" else candidate.get("root")
    manifest_release_id = manifest.get("release_id") if service == "scheduler" else candidate.get("release_id")
    if manifest_root != str(root) or candidate.get("app_root") != str(app) or manifest_release_id != item["candidate_release_id"]:
        raise GateError(f"{service} candidate manifest identity mismatch")
    if manifest.get("activation_status") != "NOT_ACTIVATED":
        raise GateError(f"{service} candidate is not marked inactive")
    info = manifest.get("application_inventory") or {}
    actual_entries = inventory(app)
    actual_sha = inventory_sha256(actual_entries)
    expected_entries = info.get("entries")
    if not isinstance(expected_entries, list):
        raise GateError(f"{service} candidate manifest has no application inventory entries")
    expected_source, expected_cache = split_runtime_cache(expected_entries)
    actual_source, actual_cache = split_runtime_cache(actual_entries)
    if (
        actual_source != expected_source
        or inventory_sha256(expected_entries) != inventory_sha
        or inventory_sha256(expected_entries) != info.get("aggregate_sha256")
        or len(expected_entries) != item["candidate_app_inventory_entry_count"]
        or len(expected_entries) != info.get("entry_count")
    ):
        raise GateError(f"{service} candidate source inventory differs from its frozen manifest")
    if not allow_runtime_bytecode_delta and (actual_sha != inventory_sha or actual_entries != expected_entries):
        raise GateError(f"{service} pre-start candidate inventory differs from the frozen manifest")
    if allow_runtime_bytecode_delta:
        # Only interpreter-owned __pycache__ bytecode may be regenerated after
        # launch. All source, assets, metadata, modes and symlinks stay exact.
        if any(not is_runtime_bytecode(row) for row in actual_cache + expected_cache):
            raise GateError(f"{service} runtime cache inventory contains a non-bytecode file")
    require_sha(staged_plist, item["candidate_plist_sha256"], service=service, phase="VERIFY_CANDIDATE_STAGED_PLIST")
    plist = plistlib.loads(staged_plist.read_bytes())
    env = plist_environment(plist)
    if plist.get("Label") != item["base_active_label"]:
        raise GateError(f"{service} candidate plist label mismatch")
    if plist.get("WorkingDirectory") != str(app) or env.get("V35_APP_ROOT") != str(app):
        raise GateError(f"{service} candidate plist app root mismatch")
    if env.get("V35_RELEASE_ID") != item["candidate_release_id"] or env.get("V35_RELEASE_MANIFEST_SHA256") != manifest_sha:
        raise GateError(f"{service} candidate plist release identity mismatch")
    for key in ("production_allowed", "PRODUCTION_ALLOWED", "buy_gate_updated", "BUY_GATE_UPDATED", "orders_sent", "ORDERS_SENT"):
        if env.get(key, "false").lower() != "false":
            raise GateError(f"{service} candidate safety flag is not false: {key}")
    if manifest.get("production_allowed") is not False or manifest.get("buy_gate_updated") is not False or manifest.get("orders_sent") is not False:
        raise GateError(f"{service} release manifest safety flags are not false")
    manifest["_runtime_cache_observed"] = {
        "pre_start_expected_sha256": inventory_sha256(expected_cache),
        "observed_sha256": inventory_sha256(actual_cache),
        "pre_start_entry_count": len(expected_cache),
        "observed_entry_count": len(actual_cache),
        "changed": expected_cache != actual_cache,
        "runtime_cache_paths": [row["path"] for row in actual_cache],
        "runtime_cache_inventory_sha256": inventory_sha256(actual_cache),
        "source_inventory_sha256": inventory_sha256(actual_source),
        "source_inventory_entry_count": len(actual_source),
        "full_pre_start_inventory_sha256": inventory_sha,
        "full_pre_start_inventory_entry_count": len(expected_entries),
        "observed_full_inventory_sha256": actual_sha,
        "observed_full_inventory_entry_count": len(actual_entries),
    }
    return manifest, plist


def verify_reviewer_receipt(service: str) -> dict[str, Any]:
    if not REVIEW_RECEIPT.is_file():
        raise GateError(f"independent HK calendar package review receipt is missing: {REVIEW_RECEIPT}")
    receipt = json_read(REVIEW_RECEIPT)
    identity = frozen_identity()
    expected = {
        "candidate_identity_sha256": EXPECTED_IDENTITY_SHA256,
        "verdict": "PASS",
        "behavior_verified": "PASS",
        "actual_diff_inspected": True,
        "independent_reviewer": "/root/hk_close_daily_review",
        "api_manifest_sha256": identity["api"]["candidate_manifest_sha256"],
        "api_inventory_sha256": identity["api"]["candidate_app_inventory_sha256"],
        "scheduler_manifest_sha256": identity["scheduler"]["candidate_manifest_sha256"],
        "scheduler_inventory_sha256": identity["scheduler"]["candidate_app_inventory_sha256"],
        "api_readback_sha256": sha256_file(READBACK_PATH),
    }
    mismatches = [key for key, value in expected.items() if receipt.get(key) != value]
    reviewed_services = receipt.get("reviewed_services")
    if not isinstance(reviewed_services, list) or service not in reviewed_services:
        mismatches.append("reviewed_services")
    if mismatches:
        raise GateError("independent review receipt does not match the frozen candidate: " + ", ".join(mismatches))
    return receipt


def launchctl_status(service: str) -> tuple[str, int]:
    label = service_identity(service)["base_active_label"]
    target = f"gui/{os.getuid()}/{label}"
    result = subprocess.run(
        ["/bin/launchctl", "print", target],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        diagnostic = "\n".join((result.stdout or "", result.stderr or "")).strip()
        absence_reported = re.search(r"(?i)(could not find service|service not found|no such service)", diagnostic)
        if absence_reported and label in diagnostic:
            raise LaunchdLabelAbsent(f"launchd label is absent: {label}: {diagnostic}")
        raise GateError(f"launchd label is not readable: {label}: {diagnostic}")
    match = re.search(r"\bpid\s*=\s*(\d+)\b", result.stdout)
    if not match:
        raise GateError(f"launchd output has no PID for {label}")
    return result.stdout, int(match.group(1))


def launchd_state(output: str) -> str | None:
    match = re.search(r"(?im)^\s*state\s*=\s*([^\r\n]+?)\s*$", output)
    return match.group(1).strip().lower() if match else None


def launchd_is_waiting_for_pid(output: str, pid: int) -> bool:
    # launchctl print addresses one exact frozen label. A loaded job in
    # `waiting` with pid=0 is the only state treated as transient here;
    # positive-PID identity mismatches and all other states fail immediately.
    return pid == 0 and launchd_state(output) == "waiting"


def verify_frozen_active(service: str) -> tuple[dict[str, Any], int]:
    item = service_identity(service)
    active_plist_path = Path(item["base_active_plist_path"])
    require_sha(active_plist_path, item["base_active_plist_sha256"], service=service, phase="VERIFY_ACTIVE_PLIST")
    plist = plistlib.loads(active_plist_path.read_bytes())
    env = plist_environment(plist)
    if plist.get("Label") != item["base_active_label"]:
        raise GateError(f"{service} active plist label changed")
    if env.get("V35_APP_ROOT") != str(Path(item["base_release_root"]) / "app"):
        raise GateError(f"{service} active app root changed")
    if env.get("V35_RELEASE_MANIFEST_SHA256") != item["base_release_manifest_sha256"]:
        raise GateError(f"{service} active release manifest pin changed")
    manifest_path = Path(item["base_release_root"]) / "release-manifest.json"
    require_sha(manifest_path, item["base_release_manifest_sha256"], service=service, phase="VERIFY_ACTIVE_MANIFEST")
    manifest = json_read(manifest_path)
    candidate = manifest.get("candidate") or {}
    if candidate.get("root") != item["base_release_root"] or candidate.get("app_root") != str(Path(item["base_release_root"]) / "app"):
        raise GateError(f"{service} active release manifest identity changed")
    active_app = Path(item["base_release_root"]) / "app"
    active_entries = inventory(active_app)
    active_source, active_cache = split_runtime_cache(active_entries)
    baseline_inventory_path = EVIDENCE_ROOT / ("api_baseline_application_inventory_20261007.json" if service == "api" else "scheduler_baseline_application_inventory_20261007.json")
    require_sha(baseline_inventory_path, BASELINE_INVENTORY_SHA256[service], service=service, phase="VERIFY_FROZEN_BASELINE_INVENTORY_RECEIPT")
    baseline_inventory = json_read(baseline_inventory_path)
    manifest_source_entries = (manifest.get("application_inventory") or {}).get("entries")
    if not isinstance(manifest_source_entries, list):
        raise GateError(f"{service} active manifest has no source inventory")
    expected_source, _manifest_cache = split_runtime_cache(manifest_source_entries)
    expected_source_sha = inventory_sha256(expected_source)
    expected_manifest_aggregate = (manifest.get("application_inventory") or {}).get("aggregate_sha256")
    if active_source != expected_source or expected_source_sha != expected_manifest_aggregate:
        observed_sha = inventory_sha256(active_source)
        drift(service=service, phase="VERIFY_ACTIVE_SOURCE_INVENTORY", path=active_app, expected=expected_source_sha, observed=observed_sha)
        raise GateError(f"{service} active source inventory differs from the frozen release manifest")
    expected_base_sha = item["base_app_inventory_sha256"]
    actual_snapshot_entries = baseline_inventory.get("runtime_generated_unmanifested_entries")
    if not isinstance(actual_snapshot_entries, list) or baseline_inventory.get("actual_app_aggregate_sha256") != expected_base_sha:
        raise GateError(f"{service} frozen baseline inventory receipt is internally inconsistent")
    expected_snapshot_cache = sorted(actual_snapshot_entries, key=lambda row: row.get("path", ""))
    if any(not is_runtime_bytecode(row) for row in expected_snapshot_cache):
        raise GateError(f"{service} frozen baseline cache list contains a non-bytecode entry")
    observed_cache_sha = inventory_sha256(active_cache)
    baseline_cache_sha = inventory_sha256(expected_snapshot_cache)
    output, pid = launchctl_status(service)
    if pid != item["base_active_pid"]:
        raise GateError(f"{service} active PID changed from frozen {item['base_active_pid']} to {pid}")
    if str(active_app) not in output:
        raise GateError(f"{service} launchd process does not identify the frozen active app root")
    plist["_runtime_cache_observed"] = {
        "frozen_actual_inventory_sha256": expected_base_sha,
        "frozen_actual_inventory_entry_count": baseline_inventory.get("actual_app_entry_count"),
        "frozen_unmanifested_runtime_cache_sha256": baseline_cache_sha,
        "frozen_unmanifested_runtime_cache_entry_count": len(expected_snapshot_cache),
        "frozen_inventory_receipt_sha256": BASELINE_INVENTORY_SHA256[service],
        "current_runtime_cache_sha256": observed_cache_sha,
        "current_runtime_cache_entry_count": len(active_cache),
        "current_runtime_cache_matches_frozen_snapshot": active_cache == expected_snapshot_cache,
        "runtime_cache_delta_is_bytecode_only": True,
        "current_actual_full_inventory_sha256": inventory_sha256(active_entries),
        "current_actual_full_inventory_entry_count": len(active_entries),
        "runtime_cache_paths": [row["path"] for row in active_cache],
    }
    return plist, pid


def run_launchctl(service: str, action: str) -> None:
    item = service_identity(service)
    domain = f"gui/{os.getuid()}"
    service_target = f"{domain}/{item['base_active_label']}"
    if action == "bootstrap":
        command = ["/bin/launchctl", "bootstrap", domain, item["base_active_plist_path"]]
    elif action == "bootout":
        command = ["/bin/launchctl", "bootout", service_target]
    else:
        raise GateError(f"unsupported launchctl action: {action}")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise GateError(f"launchctl {action} failed for {service}: {result.stderr.strip()}")


def wait_for_service_down(service: str, timeout_seconds: int = 15) -> None:
    item = service_identity(service)
    target = f"gui/{os.getuid()}/{item['base_active_label']}"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(["/bin/launchctl", "print", target], capture_output=True, text=True, check=False)
        if result.returncode != 0 or not re.search(r"\bpid\s*=\s*\d+\b", result.stdout):
            return
        time.sleep(0.25)
    raise GateError(f"exact launchd label did not stop: {item['base_active_label']}")


def record_drift(service: str, phase: str, path: Path, expected: str, observed: str | None, details: dict[str, Any] | None = None) -> None:
    drift(service=service, phase=phase, path=path, expected=expected, observed=observed, details=details)


def atomic_write_no_clobber(service: str, target: Path, candidate_bytes: bytes, *, expected_current_sha256: str, phase: str) -> Path:
    """Claim exact old bytes, then install with link(2); never overwrite drift."""
    if sha256_bytes(candidate_bytes) == expected_current_sha256:
        raise GateError("candidate and current plist bytes must differ")
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp_path = Path(temp_name)
    claim_dir: Path | None = None
    claim_path: Path | None = None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(candidate_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IMODE(target.stat().st_mode))
        for _ in range(100):
            path = target.parent / f".{target.name}.claim-{uuid.uuid4().hex}"
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                continue
            claim_dir = path
            claim_path = path / "before.plist"
            break
        if claim_path is None:
            raise GateError("could not reserve unique plist claim directory")
        try:
            os.rename(target, claim_path)
        except FileNotFoundError:
            record_drift(service, f"{phase}_CLAIM_MISSING", target, expected_current_sha256, None)
            raise GateError(f"{phase}: active plist disappeared before claim")
        actual = sha256_file(claim_path)
        if actual != expected_current_sha256:
            record_drift(service, f"{phase}_CLAIM_MISMATCH", target, expected_current_sha256, actual, {"claim_path": str(claim_path)})
            try:
                os.link(claim_path, target)
            except FileExistsError:
                observed = sha256_file(target) if target.exists() else None
                record_drift(service, f"{phase}_RESTORE_CONFLICT", target, expected_current_sha256, observed, {"claim_path": str(claim_path)})
                raise GateError(f"{phase}: drifted claim retained and parallel target preserved")
            raise GateError(f"{phase}: drifted target restored without overwrite; claim retained at {claim_path}")
        try:
            os.link(temp_path, target)
        except FileExistsError:
            observed = sha256_file(target) if target.exists() else None
            record_drift(service, f"{phase}_NO_CLOBBER_CONFLICT", target, expected_current_sha256, observed, {"claim_path": str(claim_path)})
            raise GateError(f"{phase}: parallel target preserved; original claim retained at {claim_path}")
        except OSError as exc:
            try:
                os.link(claim_path, target)
            except FileExistsError:
                observed = sha256_file(target) if target.exists() else None
                record_drift(service, f"{phase}_INSTALL_FAILURE_RESTORE_CONFLICT", target, expected_current_sha256, observed, {"claim_path": str(claim_path)})
                raise GateError(f"{phase}: install failed and a parallel target exists; original claim retained") from exc
            record_drift(service, f"{phase}_INSTALL_FAILURE_RESTORED", target, expected_current_sha256, expected_current_sha256, {"claim_path": str(claim_path), "error_type": type(exc).__name__})
            raise GateError(f"{phase}: install failed; exact original bytes were restored without overwrite") from exc
        return claim_path
    finally:
        if temp_path.exists():
            temp_path.unlink()


def wait_for_loaded_candidate(
    service: str,
    *,
    timeout_seconds: float = PROCESS_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = PROCESS_READY_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    item = service_identity(service)
    active_plist_path = Path(item["base_active_plist_path"])
    candidate_plist_path = Path(item["candidate_plist_path"])
    candidate_plist_bytes = candidate_plist_path.read_bytes()
    if sha256_bytes(candidate_plist_bytes) != item["candidate_plist_sha256"]:
        raise GateError(f"{service} staged candidate plist changed before loaded-identity verification")
    candidate_plist = plistlib.loads(candidate_plist_bytes)
    app_root = item["candidate_app_root"]
    required_tokens = (app_root, item["candidate_release_id"], item["candidate_manifest_sha256"])
    deadline = _monotonic_now() + timeout_seconds
    last_output = ""
    last_pid = 0
    while True:
        observed_plist_sha = sha256_file(active_plist_path) if active_plist_path.is_file() else None
        if observed_plist_sha != item["candidate_plist_sha256"]:
            record_drift(service, "VERIFY_LOADED_CANDIDATE_PLIST", active_plist_path, item["candidate_plist_sha256"], observed_plist_sha)
            raise RuntimeIdentityDrift(f"{service} active plist no longer belongs to the candidate")
        try:
            active_plist = plistlib.loads(active_plist_path.read_bytes())
        except (OSError, plistlib.InvalidFileException) as exc:
            record_drift(service, "VERIFY_LOADED_CANDIDATE_PLIST_PARSE", active_plist_path, item["candidate_plist_sha256"], observed_plist_sha, {"error_type": type(exc).__name__})
            raise RuntimeIdentityDrift(f"{service} active candidate plist cannot be parsed") from exc
        if active_plist != candidate_plist:
            record_drift(service, "VERIFY_LOADED_CANDIDATE_PLIST_CONTENT", active_plist_path, item["candidate_plist_sha256"], observed_plist_sha)
            raise RuntimeIdentityDrift(f"{service} active plist differs from staged candidate bytes")

        output, pid = launchctl_status(service)
        last_output, last_pid = output, pid
        if pid > 0:
            missing_tokens = [token for token in required_tokens if token not in output]
            if missing_tokens:
                record_drift(service, "VERIFY_LOADED_PROCESS_IDENTITY", active_plist_path, item["candidate_plist_sha256"], sha256_bytes(output.encode()), {"pid": pid, "missing_tokens": missing_tokens})
                raise RuntimeIdentityDrift(f"{service} launchd PID/output cannot prove candidate root, release ID, and manifest SHA")
            return {"pid": pid, "launchd_output_sha256": sha256_bytes(output.encode()), "app_root": app_root, "release_id": item["candidate_release_id"], "manifest_sha256": item["candidate_manifest_sha256"]}
        if not launchd_is_waiting_for_pid(output, pid):
            record_drift(service, "VERIFY_LOADED_PROCESS_IDENTITY", active_plist_path, item["candidate_plist_sha256"], sha256_bytes(output.encode()), {"pid": pid, "state": launchd_state(output)})
            raise RuntimeIdentityDrift(f"{service} launchd state cannot prove a pending candidate startup")
        remaining = deadline - _monotonic_now()
        if remaining <= 0:
            break
        _sleep_for_poll(min(poll_interval_seconds, remaining))
    record_drift(service, "VERIFY_LOADED_PROCESS_TIMEOUT", active_plist_path, item["candidate_plist_sha256"], sha256_bytes(last_output.encode()), {"pid": last_pid, "state": launchd_state(last_output), "timeout_seconds": timeout_seconds})
    raise GateError(f"{service} candidate remained in launchd waiting/pid=0 beyond {timeout_seconds:g}s")


def verify_api_semantics(timeout_seconds: int = 30) -> dict[str, Any]:
    expected = {
        "20260911": ("MODEL_REVIEW_READY", 20, 691, 100, 70),
        "20260930": ("MODEL_0_2_SOURCE_MISSING", 20, 696, 0, 0),
        "20261001": ("NON_TRADING_DAY", 0, None, None, None),
        "20261002": ("CANNOT_CONFIRM", 0, None, None, None),
        "20260929": ("CANNOT_CONFIRM", 0, None, None, None),
        "20270102": ("CANNOT_CONFIRM", 0, None, None, None),
    }
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            results: dict[str, Any] = {}
            for trade_date, (status, close_count, universe, model, stages) in expected.items():
                url = "http://127.0.0.1:8873/api/v3/review?" + urllib.parse.urlencode({"date": trade_date})
                with urllib.request.urlopen(url, timeout=3) as response:
                    if response.status != 200:
                        raise GateError(f"API HTTP {response.status} for {trade_date}")
                    payload = json.load(response)
                hk = payload["market_reviews"]["HK"]
                review = hk["model_selection_review"]
                actual_status = review.get("status")
                rows = review.get("close_top20") or []
                counts = review.get("row_counts") or {}
                safety = [hk.get(key) for key in ("production_allowed", "buy_gate_updated", "orders_sent")]
                if safety != [False, False, False] or actual_status != status or hk.get("status") != status or len(rows) != close_count:
                    raise GateError(f"API semantic mismatch for {trade_date}: status={actual_status}, rows={len(rows)}")
                if trade_date == "20261001":
                    calendar = review.get("calendar") or {}
                    if calendar.get("market") != "HK_SECURITIES" or calendar.get("state") != "NON_TRADING_DAY" or counts or review.get("models") or review.get("stages"):
                        raise GateError("HK securities holiday response must be empty and explicitly calendar-gated")
                elif trade_date in ("20261002", "20260929"):
                    calendar = review.get("calendar") or {}
                    if review.get("cannot_confirm") != ["CLOSE_REVIEW_ARTIFACT_MISSING"] or calendar.get("state") != "FULL_TRADING_DAY" or counts:
                        raise GateError(f"missing valid-day artifact must remain CANNOT_CONFIRM for {trade_date}")
                elif trade_date == "20270102":
                    calendar = review.get("calendar") or {}
                    if review.get("cannot_confirm") != ["HK_SECURITIES_CALENDAR_UNKNOWN"] or calendar.get("state") != "UNKNOWN" or counts:
                        raise GateError("unknown HK securities calendar date must remain CANNOT_CONFIRM")
                elif trade_date == "20260911":
                    if counts != {"hkconnect_universe": universe, "close_top20": close_count, "model_0_2": model, "stage_rows": stages}:
                        raise GateError("9/11 successful chain row counts changed")
                    if review["models"]["0.2_prob_active"]["hit_count"] != 15 or review["stage_union"]["hit_count"] != 10:
                        raise GateError("9/11 successful chain hit counts changed")
                elif trade_date == "20260930":
                    if counts != {"hkconnect_universe": universe, "close_top20": close_count, "model_0_2": model, "stage_rows": stages} or len(review.get("missing_stages") or []) != 7:
                        raise GateError("9/30 source-missing evidence was not preserved")
                results[trade_date] = {"status": actual_status, "close_top20_count": len(rows), "row_counts": counts, "safety": safety}
            return results
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise GateError(f"date-bound API verification timed out: {last_error}")


def wait_for_active_baseline(
    service: str,
    *,
    timeout_seconds: float = PROCESS_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = PROCESS_READY_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    item = service_identity(service)
    expected_root = str(Path(item["base_release_root"]) / "app")
    active_plist_path = Path(item["base_active_plist_path"])
    require_sha(active_plist_path, item["base_active_plist_sha256"], service=service, phase="VERIFY_LOADED_BASELINE_PLIST")
    base_plist = plistlib.loads(active_plist_path.read_bytes())
    if base_plist.get("Label") != item["base_active_label"]:
        raise GateError(f"rollback plist label does not match the frozen {service} baseline")
    base_env = plist_environment(base_plist)
    expected_tokens = (expected_root, base_env.get("V35_RELEASE_ID", ""), item["base_release_manifest_sha256"])
    deadline = _monotonic_now() + timeout_seconds
    last_output = ""
    last_pid = 0
    while True:
        observed_plist_sha = sha256_file(active_plist_path) if active_plist_path.is_file() else None
        if observed_plist_sha != item["base_active_plist_sha256"]:
            record_drift(service, "VERIFY_LOADED_BASELINE_PLIST", active_plist_path, item["base_active_plist_sha256"], observed_plist_sha)
            raise GateError(f"rollback plist does not match the frozen {service} baseline")
        output, pid = launchctl_status(service)
        last_output, last_pid = output, pid
        if pid > 0:
            missing_tokens = [token for token in expected_tokens if not token or token not in output]
            if missing_tokens:
                record_drift(service, "VERIFY_LOADED_BASELINE_IDENTITY", active_plist_path, item["base_active_plist_sha256"], sha256_bytes(output.encode()), {"pid": pid, "missing_tokens": missing_tokens})
                raise GateError(f"rollback process does not identify the frozen {service} base root/release/manifest")
            return {"pid": pid, "launchd_output_sha256": sha256_bytes(output.encode()), "app_root": expected_root}
        if not launchd_is_waiting_for_pid(output, pid):
            record_drift(service, "VERIFY_LOADED_BASELINE_IDENTITY", active_plist_path, item["base_active_plist_sha256"], sha256_bytes(output.encode()), {"pid": pid, "state": launchd_state(output)})
            raise GateError(f"rollback launchd state cannot prove a pending {service} baseline startup")
        remaining = deadline - _monotonic_now()
        if remaining <= 0:
            break
        _sleep_for_poll(min(poll_interval_seconds, remaining))
    record_drift(service, "VERIFY_LOADED_BASELINE_TIMEOUT", active_plist_path, item["base_active_plist_sha256"], sha256_bytes(last_output.encode()), {"pid": last_pid, "state": launchd_state(last_output), "timeout_seconds": timeout_seconds})
    raise GateError(f"{service} baseline remained in launchd waiting/pid=0 beyond {timeout_seconds:g}s")


def write_backup(service: str, active_bytes: bytes) -> Path:
    item = service_identity(service)
    path = EVIDENCE_ROOT / f"{service}_before_hk_calendar_cutover.plist"
    expected = item["base_active_plist_sha256"]
    if sha256_bytes(active_bytes) != expected:
        raise GateError(f"{service} original plist bytes differ from frozen baseline")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if sha256_file(path) != expected:
            raise GateError(f"{service} existing backup differs from frozen baseline")
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(active_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    require_sha(path, expected, service=service, phase="VERIFY_PREAPPLY_BACKUP")
    return path


def operation_path(service: str, action: str) -> Path:
    return EVIDENCE_ROOT / f"{service}_hk_calendar_{action.lower()}_operation.json"


def write_operation_receipt(service: str, action: str, reviewer: dict[str, Any] | None, pid_before: int, result: dict[str, Any]) -> None:
    item = service_identity(service)
    path = operation_path(service, action)
    if path.exists():
        raise GateError(f"operation receipt already exists; refusing to overwrite: {path}")
    if action == "APPLIED":
        manifest, _plist = verify_candidate(service, allow_runtime_bytecode_delta=True)
        loaded = wait_for_loaded_candidate(service)
        api_results = verify_api_semantics() if service == "api" else None
        # Recheck loaded identity after the HTTP calls so a different local
        # process cannot answer the date-bound probe and then be recorded.
        if service == "api":
            loaded = wait_for_loaded_candidate(service)
        result = {**result, "api_semantic_results": api_results, "loaded_identity": loaded, "candidate_runtime_cache": manifest["_runtime_cache_observed"]}
    payload = {
        "schema_version": "v4.hk_calendar_cutover_operation.v1",
        "service": service,
        "action": action,
        "candidate_root": item["candidate_root"],
        "candidate_manifest_sha256": item["candidate_manifest_sha256"],
        "candidate_app_inventory_sha256": item["candidate_app_inventory_sha256"],
        "candidate_plist_sha256": item["candidate_plist_sha256"],
        "review_receipt_sha256": sha256_file(REVIEW_RECEIPT) if REVIEW_RECEIPT.is_file() else None,
        "review_verdict": reviewer.get("verdict") if reviewer else None,
        "pid_before": pid_before,
        "result": result,
        "other_service_touched": False,
        "data_root_touched": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "created_at_epoch": int(time.time()),
    }
    if action == "APPLIED":
        payload["pid_after"] = result["loaded_identity"]["pid"]
    elif action in ("ROLLED_BACK", "AUTO_ROLLED_BACK"):
        payload["pid_after"] = result["loaded_identity"]["pid"]
    else:
        payload["pid_after"] = None
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def rollback(service: str, *, reviewer: dict[str, Any] | None, pid_before: int, automatic: bool = False) -> None:
    item = service_identity(service)
    active = Path(item["base_active_plist_path"])
    backup = EVIDENCE_ROOT / f"{service}_before_hk_calendar_cutover.plist"
    require_sha(backup, item["base_active_plist_sha256"], service=service, phase="VERIFY_ROLLBACK_BACKUP")
    expected_candidate = item["candidate_plist_sha256"]
    expected_base = item["base_active_plist_sha256"]
    if automatic and sha256_file(active) == expected_base:
        # A failed no-clobber installation may already have restored the exact
        # baseline plist. Restart that known baseline only if the exact label
        # is down; preserve an unexpected running identity and fail closed.
        expected_root = str(Path(item["base_release_root"]) / "app")
        try:
            output, _pid = launchctl_status(service)
        except LaunchdLabelAbsent:
            output = ""
        except GateError:
            raise
        if output and expected_root not in output:
            raise GateError(f"automatic recovery found an unexpected running {service} identity")
        if not output:
            run_launchctl(service, "bootstrap")
            loaded = wait_for_active_baseline(service)
        else:
            loaded = wait_for_active_baseline(service)
        write_operation_receipt(service, "AUTO_ROLLED_BACK", reviewer, pid_before, {"loaded_identity": loaded, "baseline_plist_was_already_restored": True})
        return
    phase = "AUTO_ROLLBACK_PREBOOTOUT" if automatic else "MANUAL_ROLLBACK_PREBOOTOUT"
    require_sha(active, expected_candidate, service=service, phase=phase)
    if not automatic:
        output, _ = launchctl_status(service)
        if item["candidate_app_root"] not in output:
            raise GateError(f"running {service} process is not bound to the candidate")
    candidate_label_was_absent = False
    try:
        run_launchctl(service, "bootout")
    except GateError as bootout_error:
        if not automatic:
            raise
        try:
            output, _pid = launchctl_status(service)
        except LaunchdLabelAbsent:
            output = ""
            candidate_label_was_absent = True
        except GateError as status_error:
            raise GateError(f"automatic rollback cannot prove candidate label absence: {status_error}") from bootout_error
        if output:
            raise GateError(f"automatic rollback could not boot out candidate {service}")
    wait_for_service_down(service)
    require_sha(active, expected_candidate, service=service, phase="AUTO_ROLLBACK_POSTBOOTOUT" if automatic else "MANUAL_ROLLBACK_POSTBOOTOUT")
    atomic_write_no_clobber(service, active, backup.read_bytes(), expected_current_sha256=expected_candidate, phase="AUTO_ROLLBACK_RESTORE" if automatic else "MANUAL_ROLLBACK_RESTORE")
    run_launchctl(service, "bootstrap")
    loaded = wait_for_active_baseline(service)
    write_operation_receipt(
        service,
        "AUTO_ROLLED_BACK" if automatic else "ROLLED_BACK",
        reviewer,
        pid_before,
        {"loaded_identity": loaded, "candidate_label_was_absent_before_restore": candidate_label_was_absent},
    )


def cmd_preflight(args: argparse.Namespace) -> int:
    service = args.service
    verify_candidate(service)
    reviewer = verify_reviewer_receipt(service)
    active, pid = verify_frozen_active(service)
    item = service_identity(service)
    print(json.dumps({
        "status": "PREFLIGHT_PASS",
        "service": service,
        "label": item["base_active_label"],
        "active_pid": pid,
        "active_runtime_cache": active.get("_runtime_cache_observed"),
        "candidate_root": item["candidate_root"],
        "candidate_manifest_sha256": item["candidate_manifest_sha256"],
        "reviewer": reviewer["independent_reviewer"],
        "service_changed": False,
        "other_service_changed": False,
        "data_root_touched": False,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    service = args.service
    if args.confirm != CONFIRMATIONS[service]:
        raise GateError("service-specific explicit activation confirmation is required")
    verify_candidate(service)
    reviewer = verify_reviewer_receipt(service)
    active, old_pid = verify_frozen_active(service)
    receipt = operation_path(service, "applied")
    rollback_receipt = operation_path(service, "rolled_back")
    auto_receipt = operation_path(service, "auto_rolled_back")
    if any(path.exists() for path in (receipt, rollback_receipt, auto_receipt)):
        raise GateError("an apply/rollback receipt exists; refusing a repeated operation")
    active_path = Path(service_identity(service)["base_active_plist_path"])
    backup = write_backup(service, active_path.read_bytes())
    active_mode = stat.S_IMODE(active_path.stat().st_mode)
    service_touched = False
    try:
        verify_candidate(service)
        reviewer = verify_reviewer_receipt(service)
        staged_path = Path(service_identity(service)["candidate_plist_path"])
        staged_bytes = staged_path.read_bytes()
        require_sha(staged_path, service_identity(service)["candidate_plist_sha256"], service=service, phase="APPLY_STAGED_PLIST")
        _fresh, current_pid = verify_frozen_active(service)
        if current_pid != old_pid:
            raise GateError("active PID changed while preparing the exact backup")
        require_sha(active_path, service_identity(service)["base_active_plist_sha256"], service=service, phase="APPLY_PREBOOTOUT")
        run_launchctl(service, "bootout")
        service_touched = True
        wait_for_service_down(service)
        require_sha(active_path, service_identity(service)["base_active_plist_sha256"], service=service, phase="APPLY_POSTBOOTOUT")
        atomic_write_no_clobber(service, active_path, staged_bytes, expected_current_sha256=service_identity(service)["base_active_plist_sha256"], phase="APPLY_INSTALL")
        verify_candidate(service)
        require_sha(active_path, service_identity(service)["candidate_plist_sha256"], service=service, phase="APPLY_PREBOOTSTRAP")
        run_launchctl(service, "bootstrap")
        write_operation_receipt(service, "APPLIED", reviewer, old_pid, {})
    except Exception as apply_error:
        if not service_touched:
            raise
        if isinstance(apply_error, RuntimeIdentityDrift):
            raise GateError(f"{service} runtime identity drifted; stopping without automatic rollback: {apply_error}") from apply_error
        try:
            rollback(service, reviewer=reviewer, pid_before=old_pid, automatic=True)
        except Exception as rollback_error:
            raise GateError(f"{service} candidate failed and guarded automatic rollback also failed: {rollback_error}") from apply_error
        raise GateError(f"{service} candidate failed; exact frozen baseline bytes were restored: {apply_error}") from apply_error
    print(json.dumps({"status": f"{service.upper()}_CANDIDATE_APPLIED", "other_service_touched": False}, ensure_ascii=False, indent=2))
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    service = args.service
    if args.confirm != ROLLBACK_CONFIRMATIONS[service]:
        raise GateError("service-specific explicit rollback confirmation is required")
    item = service_identity(service)
    rollback_receipt = operation_path(service, "ROLLED_BACK")
    if rollback_receipt.exists():
        raise GateError("a rollback receipt already exists; refusing to overwrite prior evidence")
    backup = EVIDENCE_ROOT / f"{service}_before_hk_calendar_cutover.plist"
    require_sha(backup, item["base_active_plist_sha256"], service=service, phase="VERIFY_ROLLBACK_BACKUP")
    require_sha(Path(item["base_active_plist_path"]), item["candidate_plist_sha256"], service=service, phase="MANUAL_ROLLBACK_PRECHECK")
    _output, pid = launchctl_status(service)
    if item["candidate_app_root"] not in _output:
        raise GateError(f"running {service} process is not bound to the candidate")
    rollback(service, reviewer=None, pid_before=pid, automatic=False)
    print(json.dumps({"status": f"{service.upper()}_ROLLED_BACK", "other_service_touched": False}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("preflight", "apply", "rollback"):
        command = sub.add_parser(action)
        command.add_argument("--service", choices=("api", "scheduler"), required=True)
        if action in ("apply", "rollback"):
            command.add_argument("--confirm", default="")
        command.set_defaults(function={"preflight": cmd_preflight, "apply": cmd_apply, "rollback": cmd_rollback}[action])
    args = parser.parse_args()
    try:
        return args.function(args)
    except (GateError, OSError, ValueError, KeyError, plistlib.InvalidFileException, json.JSONDecodeError) as exc:
        print(f"HK calendar candidate cutover blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
