#!/usr/bin/env python3
"""Read-only verification of this R3 delivery and selected source pre/postimages.

This verifies bytes and patch content only. It does not apply a release, grant
module ownership, inspect running services, or establish business recovery.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def checked_path(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if not relative or rel.is_absolute() or str(rel) != relative or ".." in rel.parts:
        raise ValueError(f"UNSAFE_RELATIVE_PATH:{relative}")
    path = root.absolute().joinpath(*rel.parts)
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError(f"SYMLINK_NOT_ALLOWED:{relative}")
    return path


def read(root: Path, relative: str) -> bytes:
    path = checked_path(root, relative)
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 8 * 1024 * 1024:
        raise ValueError(f"NOT_BOUNDED_REGULAR_FILE:{relative}")
    return path.read_bytes()


def canonical_patch(bundle: Path, entries: list[dict], *, reverse: bool = False) -> bytes:
    chunks = []
    for entry in entries:
        rel = entry["path"]
        before = read(bundle, entry["before_payload"]) if entry["before_payload"] else b""
        after = read(bundle, entry["after_payload"])
        old, new = (after, before) if reverse else (before, after)
        old_name = "a/" + rel if (reverse or entry["before_payload"]) else "/dev/null"
        new_name = "b/" + rel if (not reverse or entry["before_payload"]) else "/dev/null"
        chunks.extend(difflib.unified_diff(old.decode("utf-8").splitlines(keepends=True),
            new.decode("utf-8").splitlines(keepends=True),
            fromfile=old_name, tofile=new_name, n=3))
    return "".join(chunks).encode("utf-8")


def verify_bundle(bundle: Path) -> dict:
    manifest_raw = read(bundle, "PAYLOAD_MANIFEST.json")
    manifest = json.loads(manifest_raw)
    if manifest.get("schema_version") != "v4.manager_r3.delivery_payload.v1":
        raise ValueError("PAYLOAD_SCHEMA_MISMATCH")
    entries = manifest["files"]
    paths = [row["path"] for row in entries]
    if not entries or len(paths) != len(set(paths)) or len(paths) > 1024:
        raise ValueError("PAYLOAD_INVENTORY_INVALID")
    total = 0
    for row in entries:
        raw = read(bundle, row["path"])
        if len(raw) != row["bytes"] or digest(raw) != row["sha256"]:
            raise ValueError(f"PAYLOAD_MISMATCH:{row['path']}")
        total += len(raw)
    if total > 64 * 1024 * 1024:
        raise ValueError("PAYLOAD_BUDGET_EXCEEDED")
    actual = {str(path.relative_to(bundle)) for path in bundle.rglob("*")
              if path.is_file() or path.is_symlink()}
    if actual != set(paths) | {"PAYLOAD_MANIFEST.json"}:
        raise ValueError("PAYLOAD_CLOSED_INVENTORY_MISMATCH")
    source = json.loads(read(bundle, "source_manifest.json"))
    profile_checks = {}
    for name, profile in source["profiles"].items():
        rows = profile["entries"]
        rels = [row["path"] for row in rows]
        if rels != sorted(set(rels)):
            raise ValueError(f"PROFILE_PATHS_INVALID:{name}")
        for row in rows:
            for phase in ("before", "after"):
                payload, expected = row[phase + "_payload"], row[phase + "_sha256"]
                if payload is None:
                    if phase != "before" or expected is not None:
                        raise ValueError(f"PROFILE_ABSENCE_INVALID:{name}:{row['path']}")
                elif digest(read(bundle, payload)) != expected:
                    raise ValueError(f"PROFILE_SHA_MISMATCH:{name}:{row['path']}")
        for reverse, field in ((False, "forward_patch"), (True, "reverse_patch")):
            if read(bundle, profile[field]) != canonical_patch(bundle, rows, reverse=reverse):
                raise ValueError(f"PATCH_CONTENT_MISMATCH:{name}:{field}")
        profile_checks[name] = {"files": len(rows), "forward_and_reverse_patch": "VERIFIED"}
    return {"status": "VERIFIED", "payload_count": len(entries), "payload_bytes": total,
        "payload_manifest_sha256": digest(manifest_raw), "profiles": profile_checks}


def verify_source(bundle: Path, source_root: Path, profile_name: str, phase: str) -> dict:
    source = json.loads(read(bundle, "source_manifest.json"))
    profile = source["profiles"][profile_name]
    rows = [{"path": row["path"], "expected": row[phase + "_sha256"]}
            for row in profile["entries"]]
    if profile_name == "api":
        rows.extend({"path": row["path"], "expected": row["sha256"]}
                    for row in source["protected_issue32"])
    for row in rows:
        path = checked_path(source_root, row["path"])
        if row["expected"] is None:
            if path.exists():
                raise ValueError(f"SOURCE_MUST_BE_ABSENT:{row['path']}")
        elif digest(read(source_root, row["path"])) != row["expected"]:
            raise ValueError(f"SOURCE_SHA_MISMATCH:{row['path']}")
    return {"status": "VERIFIED", "profile": profile_name, "phase": phase,
        "source_root": str(source_root.absolute()), "paths_checked": len(rows),
        "runtime_identity_verified": False, "ownership_granted": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--profile", choices=("api", "worker", "r3_only"))
    parser.add_argument("--phase", choices=("before", "after"))
    args = parser.parse_args(argv)
    if any((args.source_root, args.profile, args.phase)) and not all((args.source_root, args.profile, args.phase)):
        parser.error("--source-root, --profile and --phase must be supplied together")
    try:
        result = verify_bundle(args.bundle)
        if args.source_root:
            result["source_check"] = verify_source(args.bundle, args.source_root, args.profile, args.phase)
        result.update(read_only=True, integrated="NOT_RUN", deployed="NOT_RUN")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error), "read_only": True}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
