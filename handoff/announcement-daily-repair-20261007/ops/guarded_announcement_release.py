#!/usr/bin/env python3
"""Read-only release gate for the reviewed announcement overlay.

Release activation stays with the parent-controlled local release manager.
This helper inventories the running baseline or verifies a separately staged
release; it never copies files, switches a release, or touches a process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from guarded_announcement_import import (
    DEFAULT_ACTIVE_RELEASE, EXPECTED_AGGREGATE, SOURCE_RECORDS, TASK_ROOT,
    candidate_source_check, launchd_owner_identity, legacy_readback,
    process_identity, release_source_hashes,
)

DEFAULT_WEB_DIST = TASK_ROOT / "candidate_live_build/apps/web/dist"
EXPECTED_DIST_AGGREGATE = "efbc2fa26319219afcd465e90733dfd426f5ee96e052a6dd1e8d4060743d0b47"
FRONTEND_SOURCE_RECORDS = {
    "apps/web/src/api/managerAnnouncementAnalysis.ts": "f30ec19c2c5b21f79ecfe3a3a23b1cf9d59bc5f5f48d117c7db4bcce39f3e5b5",
    "apps/web/src/manager-selection/announcementAnalysis.ts": "7365a33cd65c024131844ea7a451bc3d89220f6391a17863f31a3781e0b6e327",
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_manifest(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise ValueError("STAGED_RELEASE_DIRECTORY_MISSING")
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest(path.read_bytes())})
    aggregate = digest(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return {"root": str(root.resolve()), "file_count": len(rows), "bytes_total": sum(x["bytes"] for x in rows),
            "aggregate_sha256": aggregate, "files": rows}


def candidate_frontend_source_hashes() -> dict[str, str]:
    receipt = json.loads((TASK_ROOT / "CANDIDATE_SOURCE_RECEIPT_R2_P2.json").read_text(encoding="utf-8"))
    declared = {Path(item["path"]).relative_to("candidate_frontend").as_posix(): item["sha256"]
                for item in receipt.get("frontend_source_files", [])}
    if declared != FRONTEND_SOURCE_RECORDS:
        raise ValueError("FROZEN_FRONTEND_SOURCE_RECEIPT_MISMATCH")
    observed = {}
    for relative, expected in FRONTEND_SOURCE_RECORDS.items():
        path = TASK_ROOT / "candidate_frontend" / relative
        if not path.is_file():
            raise ValueError("FROZEN_FRONTEND_SOURCE_MISSING:" + relative)
        observed[relative] = digest(path.read_bytes())
        if observed[relative] != expected:
            raise ValueError("FROZEN_FRONTEND_SOURCE_HASH_MISMATCH:" + relative)
    return observed


def inventory_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for directory, directories, filenames in os.walk(root, followlinks=False):
        directories.sort(); filenames.sort()
        keep: list[str] = []
        for name in directories:
            path = Path(directory) / name
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                entries.append({"path": relative, "kind": "symlink", "target": os.readlink(path),
                                "target_exists": path.exists()})
            else:
                keep.append(name)
        directories[:] = keep
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries.append({"path": relative, "kind": "symlink", "target": os.readlink(path),
                                "target_exists": path.exists()})
            elif path.is_file():
                entries.append({"path": relative, "kind": "file", "sha256": digest(path.read_bytes()),
                                "mode": f"{stat.S_IMODE(path.stat().st_mode):04o}", "size": path.stat().st_size})
            else:
                raise ValueError("RELEASE_INVENTORY_UNSUPPORTED_FILE_TYPE:" + relative)
    return sorted(entries, key=lambda item: item["path"])


def inventory_digest(entries: list[dict[str, Any]]) -> str:
    return digest(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def plan(active_root: Path, pid: int | None = None) -> dict[str, Any]:
    owner = launchd_owner_identity(active_root, pid)
    pid = owner["pid"]
    source = candidate_source_check()
    frontend = candidate_frontend_source_hashes()
    identity = owner["process"]
    live = release_source_hashes(active_root)
    live_frontend = {relative: digest((active_root / relative).read_bytes())
                     for relative in FRONTEND_SOURCE_RECORDS}
    legacy = legacy_readback()
    return {
        "schema": "v4.manager_research.announcement_release_plan.v1",
        "status": "READ_ONLY_PLAN",
        "reviewed_candidate_aggregate_sha256": EXPECTED_AGGREGATE,
        "candidate_backend_sources": source["source_sha256"],
        "candidate_frontend_sources": frontend,
        "active_process": identity,
        "active_launchd_owner": {key: owner[key] for key in ("label", "plist_path", "plist_sha256", "service_target")},
        "active_release_root": str(active_root.resolve()),
        "active_backend_source_sha256": live,
        "candidate_overlay_needed": [rel for rel, sha in SOURCE_RECORDS.items() if live.get(rel) != sha],
        "active_frontend_source_sha256": live_frontend,
        "frontend_source_overlay_needed": [rel for rel, sha in FRONTEND_SOURCE_RECORDS.items() if live_frontend.get(rel) != sha],
        "legacy_20260929_contract": legacy,
        "frontend_dist": {"root": str(DEFAULT_WEB_DIST), "expected_file_count": 11,
                           "expected_bytes": 798364, "expected_aggregate_sha256": EXPECTED_DIST_AGGREGATE},
        "activation_performed": False,
    }


def assert_disjoint_release_paths(active_root: Path, staged_root: Path) -> tuple[Path, Path]:
    """Require separate immutable release trees after resolving both paths."""
    if active_root.is_symlink() or staged_root.is_symlink():
        raise ValueError("RELEASE_ROOT_SYMLINK_FORBIDDEN")
    active = active_root.expanduser().resolve()
    staged = staged_root.expanduser().resolve()
    if active == staged or active in staged.parents or staged in active.parents:
        raise ValueError("STAGED_RELEASE_PATH_MUST_BE_DISJOINT_FROM_ACTIVE_RELEASE")
    return active, staged


def verify_staged(active_root: Path, staged_root: Path, pid: int | None = None) -> dict[str, Any]:
    active_root, staged_root = assert_disjoint_release_paths(active_root, staged_root)
    owner = launchd_owner_identity(active_root, pid)
    identity = owner["process"]
    if Path(identity["cwd"]).resolve() != active_root.resolve():
        raise ValueError("ACTIVE_RELEASE_IDENTITY_DRIFT")
    source = candidate_source_check()
    staged_sources = release_source_hashes(staged_root)
    if staged_sources != SOURCE_RECORDS:
        raise ValueError("STAGED_BACKEND_SOURCE_HASH_MISMATCH")
    candidate_frontend_source_hashes()
    staged_frontend = {relative: digest((staged_root / relative).read_bytes())
                       for relative in FRONTEND_SOURCE_RECORDS}
    if staged_frontend != FRONTEND_SOURCE_RECORDS:
        raise ValueError("STAGED_FRONTEND_SOURCE_HASH_MISMATCH")
    dist = tree_manifest(staged_root / "apps/web/dist")
    if (dist["file_count"] != 11 or dist["bytes_total"] != 798364
            or dist["aggregate_sha256"] != EXPECTED_DIST_AGGREGATE):
        raise ValueError("STAGED_WEB_DIST_HASH_MISMATCH")
    manifest_path = staged_root.parent / "release-manifest.json"
    try:
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("STAGED_RELEASE_MANIFEST_UNAVAILABLE") from exc
    inventory = manifest.get("application_inventory") or {}
    entries = inventory_entries(staged_root)
    manifest_dist = manifest.get("frontend_dist") or {}
    dist_entries = inventory_entries(staged_root / "apps/web/dist")
    if (manifest.get("schema_version") != "v4.release_candidate.v1"
            or manifest.get("candidate", {}).get("app_root") != str(staged_root.resolve())
            or manifest.get("candidate", {}).get("release_id") != staged_root.parent.name
            or inventory.get("entry_count") != len(entries)
            or inventory.get("aggregate_sha256") != inventory_digest(entries)
            or inventory.get("entries") != entries
            or manifest_dist.get("entry_count") != len(dist_entries)
            or manifest_dist.get("aggregate_sha256") != inventory_digest(dist_entries)
            or manifest_dist.get("entries") != dist_entries
            or manifest_dist.get("source_relative_root") != "apps/web/dist"
            or manifest.get("research_only") is not True
            or manifest.get("production_allowed") is not False
            or manifest.get("buy_gate_updated") is not False
            or manifest.get("orders_sent") is not False):
        raise ValueError("STAGED_RELEASE_MANIFEST_CONTENT_MISMATCH")
    legacy = legacy_readback()
    return {
        "schema": "v4.manager_research.announcement_staged_release_receipt.v1",
        "status": "STAGED_RELEASE_VERIFIED_NOT_ACTIVATED",
        "reviewed_candidate_aggregate_sha256": source["aggregate_sha256"],
        "prior_active_release_root": str(active_root.resolve()),
        "staged_release_root": str(staged_root.resolve()),
        "running_pid": pid,
        "backend_source_sha256": staged_sources,
        "frontend_source_sha256": staged_frontend,
        "web_dist": dist,
        "release_manifest_sha256": digest(manifest_raw),
        "legacy_20260929_contract": legacy,
        "process_switch_or_restart_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("plan")
    inv.add_argument("--active-release-root", type=Path, default=DEFAULT_ACTIVE_RELEASE)
    inv.add_argument("--pid", type=int)
    stage = sub.add_parser("verify-staged")
    stage.add_argument("--active-release-root", type=Path, default=DEFAULT_ACTIVE_RELEASE)
    stage.add_argument("--staged-release-root", type=Path, required=True)
    stage.add_argument("--pid", type=int)
    args = parser.parse_args()
    try:
        result = plan(args.active_release_root, args.pid) if args.command == "plan" else verify_staged(
            args.active_release_root, args.staged_release_root, args.pid)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
