#!/usr/bin/env python3
"""Build immutable, inactive US producer and API release candidates.

This helper only reads active bindings and release trees. It writes new
candidate directories under the existing releases root plus staged plist
templates and receipts under this handoff. It never calls launchctl, changes a
loaded plist, restarts a service, or runs the market-data producer.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.api_release_integration import (  # noqa: E402
    DELTA_RECEIPT_NAME,
    DELTA_SCHEMA_VERSION,
    _base_binding,
    _diff_proof,
    build_integrated_app,
    inventory_digest,
    inventory_tree,
    _plist_environment,
    _release_identity,
    read_active_release,
    verify_api_release_candidate,
)


HANDOFF = Path(__file__).resolve().parent
SUPPORT = Path.home() / "Library" / "Application Support"
RELEASES = SUPPORT / "com.lexi.v4.local" / "releases"
US_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.lexi.v4.us-market-digest.plist"
API_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.lexi.v35.api-only.plist"
US_ID = "futu-board-map-us-20261018-r1"
API_ID = "futu-board-map-api-20261018-r1"
DELTA_PATH = HANDOFF / "API_INTEGRATION_DELTA_RECEIPT.json"
BUILD_RECEIPT_PATH = HANDOFF / "CANDIDATE_BUILD_RECEIPT.json"
US_BINDING_PATH = HANDOFF / "candidate_bindings" / "com.lexi.v4.us-market-digest.plist"
API_BINDING_PATH = HANDOFF / "candidate_bindings" / "com.lexi.v35.api-only.plist"
SOURCE_RELATIVE = "ops/_us_market_digest_parts/futu_boards.py"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_write_once(path: Path, value: object, *, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(mode)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_bound_release(plist_path: Path, *, expected_label: str) -> dict:
    """Verify a producer release binding with the shared strict manifest reader."""
    payload = plistlib.loads(plist_path.read_bytes())
    if not isinstance(payload, dict) or payload.get("Label") != expected_label:
        raise ValueError("producer LaunchAgent identity mismatch")
    values = _plist_environment(payload)
    app_root = Path(values["V35_APP_ROOT"])
    release_root = app_root.parent
    if release_root.name != values["V35_RELEASE_ID"]:
        raise ValueError("producer release id/root mismatch")
    identity = _release_identity(
        release_root=release_root,
        app_root=app_root,
        release_id=values["V35_RELEASE_ID"],
        manifest_path=Path(values["V35_RELEASE_MANIFEST_PATH"]),
        manifest_sha256=values["V35_RELEASE_MANIFEST_SHA256"],
    )
    if identity.get("module_role") != "gateway":
        raise ValueError("producer manifest is not the gateway release")
    identity["producer_plist_path"] = str(plist_path)
    identity["producer_plist_sha256"] = sha256_file(plist_path)
    return identity


def candidate_manifest(*, root: Path, release_id: str, base: dict, integration: dict | None = None) -> dict:
    app = root / "app"
    entries = inventory_tree(app)
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "generated_at": utc_now(),
        "candidate_status": "READY_FOR_INDEPENDENT_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "candidate": {
            "root": str(root),
            "app_root": str(app),
            "release_id": release_id,
            "module_role": "gateway",
            "module_contract_sha256": None,
            "formal_release_root": str(RELEASES),
            "overwrite_policy": "refuse existing candidate root; live plist unchanged",
            "data_copy_performed": False,
            "runtime_venv_copied": False,
            "ignored_runtime_data_copied": False,
        },
        "source": {
            "base_release_id": base["release_id"],
            "base_app_root": base["app_root"],
            "base_manifest_path": base["release_manifest_path"],
            "base_manifest_sha256": base["release_manifest_sha256"],
            "base_inventory_sha256": base["application_inventory_sha256"],
            "source_workspace": str(REPO_ROOT),
            "source_workspace_full_tree_copied": False,
            "active_release_bytes_copied": True,
        },
        "application_inventory": {
            "entry_count": len(entries),
            "aggregate_sha256": inventory_digest(entries),
            "entries": entries,
            "symlink_entries": [entry for entry in entries if entry.get("kind") == "symlink"],
        },
    }
    if integration is not None:
        manifest["api_integration"] = integration
    else:
        base_app = Path(str(base["app_root"]))
        old_path = base_app / SOURCE_RELATIVE
        new_path = REPO_ROOT / SOURCE_RELATIVE
        manifest["futu_board_map_integration"] = {
            "delta_paths": [SOURCE_RELATIVE],
            "before_sha256": sha256_file(old_path),
            "after_sha256": sha256_file(new_path),
            "non_delta_bytes_modes_and_paths_preserved": True,
            "review_scope": "single Futu US board mapping, compatibility validation, and membership pacing",
        }
    return manifest


def write_manifest(root: Path, manifest: dict) -> tuple[Path, str]:
    path = root / "release-manifest.json"
    json_write_once(path, manifest)
    return path, sha256_file(path)


def replace_candidate_file(base_app: Path, candidate_app: Path, source: Path) -> dict:
    relative = SOURCE_RELATIVE
    base_file = base_app / relative
    candidate_file = candidate_app / relative
    if base_file.is_symlink() or candidate_file.is_symlink() or source.is_symlink():
        raise ValueError("candidate source target may not be a symlink")
    before_mode = stat.S_IMODE(base_file.stat().st_mode)
    before_sha = sha256_file(base_file)
    source_sha = sha256_file(source)
    if before_sha == source_sha:
        raise ValueError("candidate map has no change from active release")
    candidate_file.chmod(stat.S_IMODE(candidate_file.stat().st_mode) | stat.S_IWUSR)
    shutil.copy2(source, candidate_file)
    candidate_file.chmod(before_mode)
    if sha256_file(candidate_file) != source_sha or stat.S_IMODE(candidate_file.stat().st_mode) != before_mode:
        raise ValueError("candidate target file verification failed")
    return {
        "path": relative,
        "before_sha256": before_sha,
        "after_sha256": source_sha,
        "preserved_mode": f"{before_mode:04o}",
    }


def preserve_non_delta(base_app: Path, candidate_app: Path) -> dict:
    before = {entry["path"]: entry for entry in inventory_tree(base_app)}
    after = {entry["path"]: entry for entry in inventory_tree(candidate_app)}
    if before.keys() != after.keys():
        raise ValueError("candidate changed app inventory paths")
    changed = [path for path in before if before[path] != after[path]]
    if changed != [SOURCE_RELATIVE]:
        raise ValueError("candidate changed unexpected app files: " + repr(changed))
    preserved = [before[path] for path in sorted(before) if path != SOURCE_RELATIVE]
    if [after[path] for path in sorted(after) if path != SOURCE_RELATIVE] != preserved:
        raise ValueError("candidate changed bytes or modes outside the one-file delta")
    return {
        "non_delta_entry_count": len(preserved),
        "non_delta_inventory_sha256": inventory_digest(preserved),
        "changed_paths": changed,
    }


def staged_binding(source_plist: Path, destination: Path, *, root: Path, release_id: str, manifest_path: Path, manifest_sha: str) -> dict:
    original = plistlib.loads(source_plist.read_bytes())
    candidate = deepcopy(original)
    replacements = {
        "V35_APP_ROOT": str(root / "app"),
        "V35_RELEASE_ID": release_id,
        "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
    }
    env = candidate.get("EnvironmentVariables")
    if not isinstance(env, dict):
        raise ValueError("source plist has no EnvironmentVariables map")
    for key, value in replacements.items():
        if key not in env:
            raise ValueError("source plist identity missing: " + key)
        env[key] = value
    args = candidate.get("ProgramArguments")
    if not isinstance(args, list):
        raise ValueError("source plist has no ProgramArguments list")
    candidate["ProgramArguments"] = [
        next((key + "=" + value for key, value in replacements.items() if item.startswith(key + "=")), item)
        for item in args
    ]
    candidate["WorkingDirectory"] = str(root / "app")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(plistlib.dumps(candidate, fmt=plistlib.FMT_XML, sort_keys=False))
        handle.flush()
        os.fsync(handle.fileno())
    destination.chmod(stat.S_IMODE(source_plist.stat().st_mode))
    reread = plistlib.loads(destination.read_bytes())
    if reread != candidate:
        raise ValueError("staged plist readback differs from intended binding")
    if original["Label"] != candidate["Label"] or original.get("RunAtLoad") != candidate.get("RunAtLoad"):
        raise ValueError("staged plist changed service label or RunAtLoad")
    if original.get("StartCalendarInterval") != candidate.get("StartCalendarInterval"):
        raise ValueError("staged plist changed schedule")
    before_args = [
        next((key + "=<BINDING>" for key in replacements if item.startswith(key + "=")), item)
        for item in original["ProgramArguments"]
    ]
    after_args = [
        next((key + "=<BINDING>" for key in replacements if item.startswith(key + "=")), item)
        for item in candidate["ProgramArguments"]
    ]
    if before_args != after_args:
        raise ValueError("staged plist changed non-release ProgramArguments")
    return {
        "source_path": str(source_plist),
        "source_sha256": sha256_file(source_plist),
        "staged_path": str(destination),
        "staged_sha256": sha256_file(destination),
        "label": candidate["Label"],
        "run_at_load": candidate.get("RunAtLoad"),
        "start_calendar_interval": candidate.get("StartCalendarInterval"),
        "keep_alive": candidate.get("KeepAlive"),
        "program_arguments_non_binding_unchanged": True,
        "environment_keys_changed": sorted(replacements),
        "working_directory_changed": True,
    }


def build_us_candidate(active: dict, source: Path) -> tuple[Path, dict, dict]:
    root = RELEASES / US_ID
    if root.exists() or root.is_symlink():
        raise FileExistsError(root)
    app = root / "app"
    root.mkdir()
    shutil.copytree(active["app_root"], app, symlinks=True, copy_function=shutil.copy2)
    delta = replace_candidate_file(Path(active["app_root"]), app, source)
    preservation = preserve_non_delta(Path(active["app_root"]), app)
    manifest = candidate_manifest(root=root, release_id=US_ID, base=active)
    manifest["futu_board_map_integration"]["delta"] = delta
    manifest["futu_board_map_integration"]["non_delta_preservation"] = preservation
    manifest_path, manifest_sha = write_manifest(root, manifest)
    root.chmod(0o555)
    return root, {"manifest_path": str(manifest_path), "manifest_sha256": manifest_sha}, preservation


def main() -> None:
    source = REPO_ROOT / SOURCE_RELATIVE
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(source)
    for path in (DELTA_PATH, BUILD_RECEIPT_PATH, US_BINDING_PATH, API_BINDING_PATH):
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    us_root, api_root = RELEASES / US_ID, RELEASES / API_ID
    if us_root.exists() or api_root.exists() or us_root.is_symlink() or api_root.is_symlink():
        raise FileExistsError("one or both immutable candidate roots already exist")

    # Exact current baselines: read_active_release verifies plist binding,
    # manifest SHA, full file inventory, modes, and module role before copying.
    us_active = read_bound_release(US_PLIST, expected_label="com.lexi.v4.us-market-digest")
    api_active = read_active_release(API_PLIST, role="gateway")
    before = {"us": _base_binding(us_active), "api": _base_binding(api_active)}
    base_source_sha = sha256_file(Path(us_active["app_root"]) / SOURCE_RELATIVE)
    if sha256_file(Path(api_active["app_root"]) / SOURCE_RELATIVE) != base_source_sha:
        raise ValueError("active US/API Futu board source bytes differ")

    # US producer candidate: exact active release copy with the one reviewed
    # map module changed; all other path/hash/mode entries must remain equal.
    us_root, us_manifest, us_preservation = build_us_candidate(us_active, source)

    # API candidate: SHA-pinned, single-file integration from the fresh active
    # API identity. The lower-level integration helper is used because this
    # task explicitly places inactive candidate roots beneath the releases root.
    target = SOURCE_RELATIVE
    api_before = (Path(api_active["app_root"]) / target).read_bytes()
    api_after = source.read_bytes()
    diff_sha, hunk_count = _diff_proof(api_before, api_after)
    delta = {
        "schema_version": DELTA_SCHEMA_VERSION,
        "base": _base_binding(api_active),
        "entries": [{
            "path": target,
            "before_sha256": sha256_bytes(api_before),
            "after_sha256": sha256_bytes(api_after),
            "unified_diff_sha256": diff_sha,
            "unified_diff_hunk_count": hunk_count,
        }],
    }
    json_write_once(DELTA_PATH, delta)
    api_root.mkdir()
    integration = build_integrated_app(
        active_api_plist_path=API_PLIST,
        source_root=REPO_ROOT,
        candidate_root=api_root,
        delta_receipt_path=DELTA_PATH,
        role="gateway",
        base_role="gateway",
    )
    api_app = api_root / "app"
    api_changed = replace_candidate_file(Path(api_active["app_root"]), api_app, source)
    api_preservation = preserve_non_delta(Path(api_active["app_root"]), api_app)
    if api_changed["after_sha256"] != integration["delta_entries"][0]["after_sha256"]:
        raise ValueError("API integrated delta differs from reviewed source")
    api_manifest = candidate_manifest(root=api_root, release_id=API_ID, base=api_active, integration=integration)
    api_manifest["candidate"]["module_contract_sha256"] = None
    api_manifest_path, api_manifest_sha = write_manifest(api_root, api_manifest)
    (api_root / DELTA_RECEIPT_NAME).chmod(0o444)
    api_root.chmod(0o555)

    # Fresh compare-and-swap checks after package creation; no service binding
    # has been loaded or changed.
    us_after = read_bound_release(US_PLIST, expected_label="com.lexi.v4.us-market-digest")
    if _base_binding(us_after) != before["us"]:
        raise ValueError("US active release changed while candidate was built")
    api_verification = verify_api_release_candidate(
        candidate_root=api_root,
        active_api_plist_path=API_PLIST,
        expected_manifest_sha256=api_manifest_sha,
        active_pointer="base",
        role="gateway",
        base_role="gateway",
    )

    us_binding = staged_binding(
        US_PLIST, US_BINDING_PATH, root=us_root, release_id=US_ID,
        manifest_path=us_root / "release-manifest.json", manifest_sha=us_manifest["manifest_sha256"],
    )
    api_binding = staged_binding(
        API_PLIST, API_BINDING_PATH, root=api_root, release_id=API_ID,
        manifest_path=api_manifest_path, manifest_sha=api_manifest_sha,
    )
    # The candidate plist is data only; reading it through the same strict
    # release resolver proves its root, manifest, and full inventory bind.
    us_candidate_identity = read_bound_release(
        US_BINDING_PATH, expected_label="com.lexi.v4.us-market-digest"
    )
    api_candidate_identity = read_active_release(API_BINDING_PATH, role="gateway")

    receipt = {
        "status": "READY_FOR_INDEPENDENT_REVIEW",
        "created_at": utc_now(),
        "activation_status": "NOT_ACTIVATED",
        "live_plists_changed": False,
        "services_restarted": False,
        "producer_invocations": 0,
        "source": {
            "path": str(source),
            "sha256": sha256_file(source),
            "base_sha256": base_source_sha,
            "changed_paths": [SOURCE_RELATIVE],
        },
        "active_baselines": before,
        "candidates": {
            "us": {
                "release_id": US_ID,
                "root": str(us_root),
                "manifest_path": us_manifest["manifest_path"],
                "manifest_sha256": us_manifest["manifest_sha256"],
                "inventory_sha256": us_candidate_identity["application_inventory_sha256"],
                "entry_count": us_candidate_identity["application_inventory_entry_count"],
                "preservation": us_preservation,
                "staged_binding": us_binding,
            },
            "api": {
                "release_id": API_ID,
                "root": str(api_root),
                "manifest_path": str(api_manifest_path),
                "manifest_sha256": api_manifest_sha,
                "inventory_sha256": api_candidate_identity["application_inventory_sha256"],
                "entry_count": api_candidate_identity["application_inventory_entry_count"],
                "preservation": api_preservation,
                "integration_verification": api_verification,
                "staged_binding": api_binding,
            },
        },
        "membership_rate_limit": {
            "mapped_boards": 13,
            "get_plate_stock_calls_per_collection": 13,
            "documented_limit": "10 requests per 30 seconds",
            "mocked_clock_wait_seconds_for_instantaneous_13_call_case": 30.0,
            "live_added_wait_measured": False,
        },
        "verification_gaps": [
            "independent review and behavior acceptance pending",
            "no live producer capture or API/UI verification was run",
            "actual runtime latency under the provider rate limit remains unmeasured",
        ],
    }
    json_write_once(BUILD_RECEIPT_PATH, receipt)
    print(json.dumps({
        "status": receipt["status"],
        "candidate_ids": [US_ID, API_ID],
        "manifest_sha256": {"us": us_manifest["manifest_sha256"], "api": api_manifest_sha},
        "inventory": {"us": us_candidate_identity["application_inventory_entry_count"], "api": api_candidate_identity["application_inventory_entry_count"]},
        "receipt": str(BUILD_RECEIPT_PATH),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
