#!/usr/bin/env python3
"""Create exact isolated R1 API/web source snapshots with preimage receipts.

This tool is intentionally one-shot: it refuses existing candidate roots and
copies only the two confirmed source roots. It does not apply delivery patches.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

E = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_AUTOMATION_R2_MAC_20261009")
API_SOURCE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-workbench-r1-mac-20261008-api-r2/app")
WEB_SOURCE = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_R1_MAC_20261008/candidate/web")
R1_MANIFEST = E / "incoming/r1/source_manifest.json"
R2_MANIFEST = E / "incoming/r2/source_manifest.json"
RECEIPT = E / "evidence/receipts/r2_candidate_baseline_inventory.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        directory = Path(dirpath)
        kept_dirs: list[str] = []
        for name in sorted(dirnames):
            path = directory / name
            rel = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                rows.append({"path": rel, "kind": "symlink", "target": os.readlink(path)})
            else:
                kept_dirs.append(name)
        dirnames[:] = kept_dirs
        for name in sorted(filenames):
            path = directory / name
            rel = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                rows.append({"path": rel, "kind": "symlink", "target": os.readlink(path)})
            elif stat.S_ISREG(info.st_mode):
                rows.append({"path": rel, "kind": "file", "bytes": info.st_size, "sha256": sha(path)})
            else:
                rows.append({"path": rel, "kind": "other", "mode": stat.S_IFMT(info.st_mode)})
    return sorted(rows, key=lambda row: str(row["path"]))


def main() -> None:
    for path in (API_SOURCE, WEB_SOURCE, R1_MANIFEST, R2_MANIFEST):
        if not path.exists():
            raise SystemExit(f"required source missing: {path}")
    api_dest, web_dest = E / "candidate/api", E / "candidate/web"
    if api_dest.exists() or web_dest.exists():
        raise SystemExit("candidate API or web root already exists; refusing overwrite")

    r1 = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    r2 = json.loads(R2_MANIFEST.read_text(encoding="utf-8"))
    checked = []
    for row in r1["files"]:
        profile = row.get("profile")
        if profile not in ("api", "web"):
            continue
        source_root = API_SOURCE if profile == "api" else WEB_SOURCE
        source_file = source_root / row["path"]
        actual = sha(source_file) if source_file.is_file() else None
        expected = row["before_sha256"]
        if actual != expected:
            raise SystemExit(
                f"R1 preimage mismatch profile={profile} path={row['path']} "
                f"expected={expected!r} actual={actual!r}"
            )
        checked.append({
            "profile": profile,
            "path": row["path"],
            "expected_before_sha256": expected,
            "actual_before_sha256": actual,
            "status": "MATCH_BEFORE",
        })

    shutil.copytree(API_SOURCE, api_dest, symlinks=True, copy_function=shutil.copy2)
    shutil.copytree(WEB_SOURCE, web_dest, symlinks=True, copy_function=shutil.copy2)

    api_source_inventory = inventory(API_SOURCE)
    api_candidate_inventory = inventory(api_dest)
    web_source_inventory = inventory(WEB_SOURCE)
    web_candidate_inventory = inventory(web_dest)
    if api_source_inventory != api_candidate_inventory or web_source_inventory != web_candidate_inventory:
        raise SystemExit("copied tree inventory differs from confirmed source root")

    receipt = {
        "schema_version": "v4.manager_r2_candidate_baseline_inventory.v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "ISOLATED_SOURCE_SNAPSHOTS_ONLY; NO LIVE ROOT WRITES",
        "r1_source_manifest_sha256": sha(R1_MANIFEST),
        "r2_source_manifest_sha256": sha(R2_MANIFEST),
        "r1_delivery_commit": "008649895054cb24f1d1c3df37e215d307615db3",
        "r2_delivery_commit": "6a2fa48faf1da0a7d0d1715b3a4a40f55249b64c",
        "sources": {
            "api": {"root": str(API_SOURCE), "candidate_root": str(api_dest)},
            "web": {"root": str(WEB_SOURCE), "candidate_root": str(web_dest)},
        },
        "r1_declared_api_web_preimages": checked,
        "candidate_inventories": {
            "api": {
                "file_count": sum(row["kind"] == "file" for row in api_candidate_inventory),
                "symlink_count": sum(row["kind"] == "symlink" for row in api_candidate_inventory),
                "regular_file_bytes": sum(int(row.get("bytes", 0)) for row in api_candidate_inventory),
                "files": api_candidate_inventory,
            },
            "web": {
                "file_count": sum(row["kind"] == "file" for row in web_candidate_inventory),
                "symlink_count": sum(row["kind"] == "symlink" for row in web_candidate_inventory),
                "regular_file_bytes": sum(int(row.get("bytes", 0)) for row in web_candidate_inventory),
                "files": web_candidate_inventory,
            },
        },
        "copy_equality": {
            "api": "PASS_ALL_FILES_AND_SYMLINK_TARGETS_MATCH",
            "web": "PASS_ALL_FILES_AND_SYMLINK_TARGETS_MATCH",
        },
        "test_assembly": "NOT_STARTED",
        "declared_hk_profiles": "NOT_COPIED_OR_APPLIED",
    }
    if RECEIPT.exists():
        raise SystemExit(f"receipt already exists; refusing overwrite: {RECEIPT}")
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "receipt": str(RECEIPT),
        "r1_manifest_sha256": receipt["r1_source_manifest_sha256"],
        "r2_manifest_sha256": receipt["r2_source_manifest_sha256"],
        "api_files": receipt["candidate_inventories"]["api"]["file_count"],
        "web_files": receipt["candidate_inventories"]["web"]["file_count"],
        "r1_api_web_preimages": len(checked),
        "copy_equality": receipt["copy_equality"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
