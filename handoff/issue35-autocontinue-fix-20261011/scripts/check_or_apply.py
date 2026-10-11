#!/usr/bin/env python3
"""Verify Issue #35 frozen patch identity; optionally apply in a disposable worktree.

Default is strictly read-only.  This NEVER deploys, restarts a service, edits
a binding, changes a trading gate, or asserts that market owners have run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def die(message: str) -> None:
    raise SystemExit(message)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def no_symlink_path(path: Path) -> None:
    for node in (path, *path.parents):
        if node.is_symlink():
            die(f"REFUSE_SYMLINK_PATH: {node}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True, help="isolated candidate source root, not the live API directory")
    p.add_argument("--mode", required=True, choices=("canonical_r2", "runtime_r1", "runtime_after_r2"))
    p.add_argument("--apply", action="store_true", help="explicitly modify isolated root after exact checks")
    args = p.parse_args()

    root = Path(args.root)
    if not root.is_absolute() or ".." in root.parts:
        die("ROOT_MUST_BE_ABSOLUTE_WITHOUT_DOTDOT")
    no_symlink_path(root)
    if not root.is_dir():
        die("CANDIDATE_ROOT_MISSING")
    own_root = Path(__file__).absolute().parent.parent
    no_symlink_path(own_root)
    manifest = json.loads((own_root / "PATCH_SHA_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "v4.issue35.patch_identity.v1":
        die("MANIFEST_CONTRACT_INVALID")
    patch_order = manifest["mode_patch_order"][args.mode]
    rows = [f for f in manifest["files"] if f["mode"] in (args.mode, "shared")]
    if not rows or len({f["path"] for f in rows}) != len(rows):
        die("MANIFEST_TARGET_AMBIGUOUS")

    verified = []
    for f in rows:
        rel = Path(f["path"])
        if rel.is_absolute() or ".." in rel.parts or rel.suffix != ".py":
            die("TARGET_PATH_NOT_ADMITTED")
        target = root / rel
        no_symlink_path(target)
        if not target.is_file():
            die(f"TARGET_MISSING: {rel}")
        actual = sha256_bytes(target.read_bytes())
        if actual != f["before_sha256"]:
            die(f"BEFORE_SHA256_MISMATCH: {rel}; actual={actual}; expected={f['before_sha256']}")
        verified.append((f, target))

    patches = []
    for rel in patch_order:
        patch_path = own_root / rel
        no_symlink_path(patch_path)
        if not patch_path.is_file() or not str(rel).startswith("patches/"):
            die(f"PATCH_UNAVAILABLE: {rel}")
        patches.append(patch_path.read_bytes())
    diff = b"".join(patches)
    if not diff:
        die("PATCH_EMPTY")

    check = subprocess.run(
        ["git", "apply", "--check", "-"], cwd=root, input=diff,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if check.returncode:
        die("GIT_APPLY_CHECK_FAILED: " + check.stderr.decode("utf-8", "replace")[:2000].strip())

    if args.apply:
        # Git verifies all hunks before this operation; non-matching source
        # identities have already been rejected. The user supplied --apply.
        done = subprocess.run(
            ["git", "apply", "-"], cwd=root, input=diff,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if done.returncode:
            die("GIT_APPLY_FAILED: " + done.stderr.decode("utf-8", "replace")[:2000].strip())
        for f, target in verified:
            got = sha256_bytes(target.read_bytes())
            if got != f["after_sha256"]:
                die(f"AFTER_SHA256_MISMATCH: {f['path']}; actual={got}; expected={f['after_sha256']}")

    print(json.dumps({
        "status": "PATCH_APPLIED_SHA256_VERIFIED" if args.apply else "PATCH_APPLICABLE_READ_ONLY_CHECK",
        "mode": args.mode,
        "source_root": str(root),
        "target_files": [dict(path=f["path"], before_sha256=f["before_sha256"],
                              after_sha256=f["after_sha256"]) for f, _ in verified],
        "patches": patch_order,
        "changed_live_service": False,
        "tests_run": False,
        "api_ui_natural_verified": False,
    }, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, TypeError, ValueError) as exc:
        die(type(exc).__name__ + ": " + str(exc)[:1000])
