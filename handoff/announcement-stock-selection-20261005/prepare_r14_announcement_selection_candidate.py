#!/usr/bin/env python3
"""Prepare a task-isolated R14 app with only the frozen four-file overlay.

No flags: verify inputs and print a read-only plan. --prepare copies the full
verified R14 app under this task directory, overlays four announcement runtime
files, and rebuilds that isolated app's web dist. It never writes releases,
owner state, or canonical source files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_SELECTION_20261005")
RELEASES_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases")
BASE_RELEASE_ID = "manager-announcement-r14-20261005-page-results-r1"
BASE_RELEASE_ROOT = RELEASES_ROOT / BASE_RELEASE_ID
BASE_APP = BASE_RELEASE_ROOT / "app"
BASE_MANIFEST = BASE_RELEASE_ROOT / "release-manifest.json"
BASE_MANIFEST_SHA256 = "220406155fc7b556cca64e8ec376abbbf88bc2f499a174905d1503ebbd783fc1"
BASE_APP_INVENTORY_SHA256 = "a969ea48481ba490ffc8b591c3ccbbe4207bab8c420e1e2a8e76cdef2ec2a8cf"
SOURCE_MANIFEST = TASK_ROOT / "source_delta_sha_manifest.json"
SOURCE_MANIFEST_SHA256 = "5becb1eade90fc0856ab15edfd6b5c51a7c80a4d952037a4b111571ce7dc16f7"
CANONICAL_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
FINAL_ROOT = TASK_ROOT / "isolated_r14_announcement_selection_candidate"
STAGING_ROOT = TASK_ROOT / ".isolated_r14_announcement_selection_candidate.staging"
CANONICAL_WEB_DEPS = CANONICAL_ROOT / "apps/web/node_modules"

OVERLAY_PATHS = (
    "v4/manager_research/announcement_analysis.py",
    "v4/manager_research/announcement_selection.py",
    "apps/web/src/api/managerAnnouncementAnalysis.ts",
    "apps/web/src/manager-selection/announcementAnalysis.ts",
)
WEB_PACKAGE_EXPECTED = {
    "apps/web/package.json": "c19353356c407e397c4eeda0bf052c0229e6fb814c55de43eb60a43263306d2b",
    "apps/web/package-lock.json": "3f0b8425f35a7fdeb13cc0e5422b7814b386a6c7559d0e5c6b2f8340bc01be47",
}


class CandidateError(RuntimeError):
    pass


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_sha(value: Any) -> str:
    return sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CandidateError(f"expected regular file: {path}")
    return sha_bytes(path.read_bytes())


def inventory(app_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(app_root.rglob("*"), key=lambda item: item.relative_to(app_root).as_posix()):
        relative = path.relative_to(app_root).as_posix()
        if path.is_symlink():
            rows.append({
                "path": relative,
                "kind": "symlink",
                "target": os.readlink(path),
                "mode": format(stat.S_IMODE(path.lstat().st_mode), "04o"),
            })
        elif path.is_file():
            rows.append({
                "path": relative,
                "kind": "file",
                "sha256": file_sha(path),
                "mode": format(stat.S_IMODE(path.stat().st_mode), "04o"),
                "size": path.stat().st_size,
            })
    return rows


def inventory_sha(rows: list[dict[str, Any]]) -> str:
    return canonical_sha(rows)


def read_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    if sha_bytes(BASE_MANIFEST.read_bytes()) != BASE_MANIFEST_SHA256:
        raise CandidateError("R14 release manifest SHA changed")
    manifest = json.loads(BASE_MANIFEST.read_bytes())
    if (manifest.get("candidate_status") != "REVIEWED_PASS"
            or manifest.get("candidate", {}).get("release_id") != BASE_RELEASE_ID
            or manifest.get("candidate", {}).get("app_root") != str(BASE_APP)):
        raise CandidateError("R14 release manifest identity/status mismatch")
    expected_inventory = manifest.get("application_inventory", {}).get("entries")
    if not isinstance(expected_inventory, list) or len(expected_inventory) != 996:
        raise CandidateError("R14 inventory row count mismatch")
    if inventory_sha(expected_inventory) != BASE_APP_INVENTORY_SHA256:
        raise CandidateError("R14 inventory manifest aggregate mismatch")
    actual_inventory = inventory(BASE_APP)
    if actual_inventory != expected_inventory:
        raise CandidateError("R14 app contents do not match release inventory")
    if inventory_sha(actual_inventory) != BASE_APP_INVENTORY_SHA256:
        raise CandidateError("R14 app inventory aggregate SHA mismatch")

    source_manifest_bytes = SOURCE_MANIFEST.read_bytes()
    if sha_bytes(source_manifest_bytes) != SOURCE_MANIFEST_SHA256:
        raise CandidateError("frozen canonical source manifest SHA changed")
    source_manifest = json.loads(source_manifest_bytes)
    source_rows = {row["path"]: row for row in source_manifest.get("canonical_files", [])}
    source_shas: dict[str, str] = {}
    for relative in OVERLAY_PATHS:
        row = source_rows.get(relative)
        if not isinstance(row, dict) or row.get("state") not in {"CHANGED", "NEW"}:
            raise CandidateError(f"overlay is absent from frozen source delta: {relative}")
        expected = row.get("current_sha256")
        source_path = CANONICAL_ROOT / relative
        if not isinstance(expected, str) or file_sha(source_path) != expected:
            raise CandidateError(f"canonical overlay SHA changed: {relative}")
        source_shas[relative] = expected

    for relative, expected in WEB_PACKAGE_EXPECTED.items():
        if file_sha(BASE_APP / relative) != expected:
            raise CandidateError(f"R14 web package input changed: {relative}")
        if file_sha(CANONICAL_ROOT / relative) != expected:
            raise CandidateError(f"canonical web package input differs: {relative}")
    return manifest, source_manifest, source_shas


def dry_run_plan() -> dict[str, Any]:
    manifest, source_manifest, source_shas = read_inputs()
    return {
        "schema_version": "v4.announcement_selection_isolated_candidate_plan.v1",
        "status": "DRY_RUN_READY",
        "base_release_id": BASE_RELEASE_ID,
        "base_release_manifest_sha256": BASE_MANIFEST_SHA256,
        "base_app_inventory_sha256": BASE_APP_INVENTORY_SHA256,
        "base_app_file_count": len(manifest["application_inventory"]["entries"]),
        "source_delta_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "overlay_files": source_shas,
        "web_package_sha256": WEB_PACKAGE_EXPECTED,
        "candidate_root": str(FINAL_ROOT),
        "candidate_app_root": str(FINAL_ROOT / "app"),
        "web_build_cwd": str(FINAL_ROOT / "app/apps/web"),
        "web_build_command": "npm run build -- --outDir dist --emptyOutDir",
        "canonical_web_node_modules_reused_for_build": str(CANONICAL_WEB_DEPS),
        "release_or_state_write": False,
    }


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json(path: Path, data: dict[str, Any]) -> bytes:
    payload = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return payload


def _assert_only_scoped_changes(base_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> None:
    base = {row["path"]: row for row in base_rows}
    current = {row["path"]: row for row in candidate_rows}
    scoped = set(OVERLAY_PATHS)
    dist_prefix = "apps/web/dist/"
    removed = set(base) - set(current)
    added = set(current) - set(base)
    changed = {path for path in set(base) & set(current) if base[path] != current[path]}
    if any(not path.startswith(dist_prefix) for path in removed):
        raise CandidateError(f"unexpected removed base paths: {sorted(p for p in removed if not p.startswith(dist_prefix))[:8]}")
    allowed_added = scoped - set(base)
    if any(path not in allowed_added and not path.startswith(dist_prefix) for path in added):
        raise CandidateError(f"unexpected added paths: {sorted(p for p in added if p not in allowed_added and not p.startswith(dist_prefix))[:8]}")
    if any(path not in scoped and not path.startswith(dist_prefix) for path in changed):
        raise CandidateError(f"unexpected modified paths: {sorted(p for p in changed if p not in scoped and not p.startswith(dist_prefix))[:8]}")


def prepare_candidate() -> dict[str, Any]:
    if FINAL_ROOT.exists() or FINAL_ROOT.is_symlink():
        raise CandidateError(f"candidate root already exists; refusing overwrite: {FINAL_ROOT}")
    if STAGING_ROOT.exists() or STAGING_ROOT.is_symlink():
        raise CandidateError(f"staging root already exists; inspect before retry: {STAGING_ROOT}")
    TASK_ROOT.mkdir(parents=True, exist_ok=True)
    base_manifest, source_manifest, source_shas = read_inputs()
    STAGING_ROOT.mkdir()
    app_root = STAGING_ROOT / "app"
    shutil.copytree(BASE_APP, app_root, symlinks=True, copy_function=shutil.copy2)

    overlay_receipt: list[dict[str, Any]] = []
    for relative in OVERLAY_PATHS:
        source = CANONICAL_ROOT / relative
        destination = app_root / relative
        old_sha = file_sha(destination) if destination.exists() else None
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        new_sha = file_sha(destination)
        if new_sha != source_shas[relative]:
            raise CandidateError(f"overlay copy SHA mismatch: {relative}")
        overlay_receipt.append({
            "path": relative,
            "base_r14_sha256": old_sha,
            "canonical_overlay_sha256": source_shas[relative],
            "candidate_sha256": new_sha,
        })

    web_root = app_root / "apps/web"
    candidate_modules = web_root / "node_modules"
    if candidate_modules.exists() or candidate_modules.is_symlink():
        raise CandidateError("base R14 app unexpectedly contains node_modules")
    if not CANONICAL_WEB_DEPS.is_dir() or CANONICAL_WEB_DEPS.is_symlink():
        raise CandidateError("canonical web node_modules is unavailable or symlinked")
    # The isolated R14 app has byte-identical package.json/lockfile. Reuse that
    # exact installed dependency tree only during build; remove the link before
    # candidate inventory/finalization so the release app remains self-contained.
    os.symlink(CANONICAL_WEB_DEPS, candidate_modules, target_is_directory=True)
    stdout_path = STAGING_ROOT / "web_build.stdout.log"
    stderr_path = STAGING_ROOT / "web_build.stderr.log"
    command = ["npm", "run", "build", "--", "--outDir", "dist", "--emptyOutDir"]
    try:
        result = subprocess.run(command, cwd=web_root, check=False, capture_output=True, text=True)
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")
        if result.returncode != 0:
            raise CandidateError(f"isolated R14 web build failed rc={result.returncode}; see {stdout_path} and {stderr_path}")
    finally:
        candidate_modules.unlink(missing_ok=True)
    _fsync_dir(web_root)

    # Recheck source after copy/build to guard against a concurrent writer.
    _, _, final_source_shas = read_inputs()
    if final_source_shas != source_shas:
        raise CandidateError("canonical source changed while candidate was being prepared")

    base_rows = base_manifest["application_inventory"]["entries"]
    candidate_rows = inventory(app_root)
    _assert_only_scoped_changes(base_rows, candidate_rows)
    candidate_inventory_sha = inventory_sha(candidate_rows)
    dist_rows = [row for row in candidate_rows if row["path"].startswith("apps/web/dist/")]
    dist_inventory_sha = inventory_sha(dist_rows)
    if not dist_rows:
        raise CandidateError("isolated web build emitted no apps/web/dist files")

    planned_final_app = FINAL_ROOT / "app"
    manifest: dict[str, Any] = {
        "schema_version": "v4.announcement_selection_isolated_release_candidate.v1",
        "candidate_status": "PREPARED_IN_TASK_NOT_ACTIVATABLE",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "NOT_ATTEMPTED",
        "release_id_hint": "manager-announcement-r14-plus-announcement-selection-candidate",
        "base": {
            "release_id": BASE_RELEASE_ID,
            "release_root": str(BASE_RELEASE_ROOT),
            "app_root": str(BASE_APP),
            "release_manifest_sha256": BASE_MANIFEST_SHA256,
            "application_inventory_entry_count": len(base_rows),
            "application_inventory_aggregate_sha256": BASE_APP_INVENTORY_SHA256,
        },
        "source_delta": {
            "manifest_path": str(SOURCE_MANIFEST),
            "manifest_sha256": SOURCE_MANIFEST_SHA256,
            "manifest_scope_sha256": source_manifest.get("scope_file_sha256"),
            "overlay_files": overlay_receipt,
        },
        "web_build": {
            "cwd": str(planned_final_app / "apps/web"),
            "command": "npm run build -- --outDir dist --emptyOutDir",
            "node_modules_source": str(CANONICAL_WEB_DEPS),
            "node_modules_link_ephemeral_and_removed": True,
            "package_json_sha256": WEB_PACKAGE_EXPECTED["apps/web/package.json"],
            "package_lock_sha256": WEB_PACKAGE_EXPECTED["apps/web/package-lock.json"],
            "stdout_log_sha256": file_sha(stdout_path),
            "stderr_log_sha256": file_sha(stderr_path),
            "dist_file_count": len(dist_rows),
            "dist_inventory_aggregate_sha256": dist_inventory_sha,
        },
        "candidate": {
            "task_only_root": str(FINAL_ROOT),
            "app_root": str(planned_final_app),
            "application_inventory_entry_count": len(candidate_rows),
            "application_inventory_aggregate_sha256": candidate_inventory_sha,
            "application_inventory": candidate_rows,
        },
        "state_and_release_boundary": {
            "owner_state_write": False,
            "release_directory_write": False,
            "service_stop_or_start": False,
            "candidate_is_under_task_evidence_only": True,
            "runtime_switch_spec_prepared": False,
        },
        "command_to_reproduce": {
            "cwd": str(TASK_ROOT),
            "command": "python3 prepare_r14_announcement_selection_candidate.py --prepare",
        },
    }
    manifest["manifest_sha256"] = canonical_sha(manifest)
    _write_json(STAGING_ROOT / "prepared_candidate_manifest.json", manifest)
    _fsync_dir(STAGING_ROOT)
    os.replace(STAGING_ROOT, FINAL_ROOT)
    _fsync_dir(TASK_ROOT)
    return {
        "status": manifest["candidate_status"],
        "candidate_root": str(FINAL_ROOT),
        "candidate_app_root": str(FINAL_ROOT / "app"),
        "manifest_path": str(FINAL_ROOT / "prepared_candidate_manifest.json"),
        "manifest_sha256": manifest["manifest_sha256"],
        "candidate_app_inventory_sha256": candidate_inventory_sha,
        "web_dist_inventory_sha256": dist_inventory_sha,
        "web_dist_file_count": len(dist_rows),
        "owner_state_write": False,
        "release_directory_write": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="create task-isolated R14 overlay and rebuild its web app")
    args = parser.parse_args(argv)
    try:
        result = prepare_candidate() if args.prepare else dry_run_plan()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (CandidateError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "REFUSED_OR_FAILED", "error": f"{type(error).__name__}: {error}"},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
