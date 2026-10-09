#!/usr/bin/env python3
"""Read-only source checks; replay the two-file patch only in temporary storage."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ALLOWED = {
    "v4/manager_research/connect_selection.py",
    "v4/manager_research/workspace.py",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside_file(root: Path, relative: str) -> Path:
    path = root / relative
    if (Path(relative).is_absolute() or ".." in Path(relative).parts
            or not path.resolve().is_relative_to(root) or not path.is_file()):
        raise SystemExit("PATH_INVALID: " + relative)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--expect", choices=("before", "after"), default="before")
    parser.add_argument("--check-r2-context", action="store_true")
    args = parser.parse_args()
    if args.check_r2_context and args.source_root is None:
        parser.error("--check-r2-context requires --source-root")
    package = Path(__file__).resolve().parents[1]
    manifest = json.loads((package / "MANIFEST.json").read_text())
    seen = set()
    for entry in manifest["files"]:
        relative = entry["path"]
        if relative in seen:
            raise SystemExit("DUPLICATE_PACKAGE_PATH: " + relative)
        seen.add(relative)
        path = inside_file(package, relative)
        if path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            raise SystemExit("PACKAGE_FILE_MISMATCH: " + relative)
    changes = manifest["production_changes"]
    if len(changes) != len(ALLOWED) or {e["path"] for e in changes} != ALLOWED:
        raise SystemExit("PRODUCTION_ALLOWLIST_MISMATCH")
    by_path = {e["path"]: e for e in changes}
    for relative, entry in by_path.items():
        for side in ("before", "after"):
            if digest(inside_file(package, side + "/" + relative)) != entry[side + "_sha256"]:
                raise SystemExit("PRODUCTION_PREIMAGE_MISMATCH: " + relative)
    checked_context = 0
    if args.source_root is not None:
        source = args.source_root.resolve(strict=True)
        expected = {rel: entry[args.expect + "_sha256"] for rel, entry in by_path.items()}
        if args.check_r2_context:
            for entry in manifest["r2_context_files"]:
                if entry["path"] not in expected:
                    expected[entry["path"]] = entry["sha256"]
            checked_context = len(manifest["r2_context_files"])
        for relative, wanted in expected.items():
            if digest(inside_file(source, relative)) != wanted:
                raise SystemExit("TARGET_SHA_MISMATCH: " + relative)
    patch = str(package / "runtime.patch")
    with tempfile.TemporaryDirectory(prefix="v4-manager-owner-patch-") as temporary:
        replay = Path(temporary)
        for relative in sorted(ALLOWED):
            path = replay / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package / "before" / relative, path)
        stats = subprocess.run(["git", "apply", "--numstat", patch], cwd=replay,
                               check=True, capture_output=True, text=True).stdout
        touched = {line.split("\t", 2)[2] for line in stats.splitlines()}
        if touched != ALLOWED:
            raise SystemExit("PATCH_PATH_ALLOWLIST_MISMATCH")
        for flags in [("--check",), ()]:
            subprocess.run(["git", "apply", *flags, patch], cwd=replay, check=True)
        for relative in sorted(ALLOWED):
            if (replay / relative).read_bytes() != (package / "after" / relative).read_bytes():
                raise SystemExit("PATCH_AFTER_MISMATCH: " + relative)
        for flags in [("--reverse", "--check"), ("--reverse",)]:
            subprocess.run(["git", "apply", *flags, patch], cwd=replay, check=True)
        for relative in sorted(ALLOWED):
            if (replay / relative).read_bytes() != (package / "before" / relative).read_bytes():
                raise SystemExit("PATCH_ROLLBACK_MISMATCH: " + relative)
    print(json.dumps({"status": "PASS", "manifest_payloads": len(seen),
        "production_paths": sorted(ALLOWED), "patch_apply": "PASS", "patch_rollback": "PASS",
        "target_check": args.expect if args.source_root else "NOT_REQUESTED",
        "r2_context_files_checked": checked_context, "target_writes": False}))


if __name__ == "__main__":
    main()
