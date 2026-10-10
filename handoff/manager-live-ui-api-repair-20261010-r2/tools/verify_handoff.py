#!/usr/bin/env python3
"""Read-only byte verification of this handoff and an optional source root.

No apply, capture, import, service, network or business-state operations.
Target source equality is not runtime, deployment, data or PIT acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_file(root: Path, value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(p in {".", ".."} for p in path.parts) or "\\" in value:
        raise ValueError("UNSAFE_RELATIVE_PATH")
    result = root.joinpath(*path.parts)
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("PATH_ESCAPES_SOURCE_ROOT")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, help="Optional local source root to read; never modified")
    parser.add_argument("--target-state", choices=("before", "after"), help="Expected source state; required with --target-root")
    args = parser.parse_args()
    if bool(args.target_root) != bool(args.target_state):
        parser.error("--target-root and --target-state must be supplied together")
    package = Path(__file__).resolve().parents[1]
    manifest = json.loads((package / "PACKAGE_MANIFEST.json").read_text())
    failures = []
    expected_paths = set()
    for entry in manifest["files"]:
        path = relative_file(package, entry["path"])
        expected_paths.add(entry["path"])
        if path.is_symlink() or not path.is_file():
            failures.append({"path": entry["path"], "reason": "FILE_MISSING_OR_SYMLINK"})
        elif path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            failures.append({"path": entry["path"], "reason": "PACKAGE_BYTES_MISMATCH"})
    observed_paths = {
        p.relative_to(package).as_posix()
        for p in package.rglob("*")
        if p.is_file() and p.name != "PACKAGE_MANIFEST.json"
    }
    for path in sorted(observed_paths - expected_paths):
        failures.append({"path": path, "reason": "UNLISTED_FILE"})
    sources = json.loads((package / "SOURCE_MANIFEST.json").read_text())
    for entry in sources["production_files"]:
        for side in ("before", "after"):
            expected = entry[side + "_sha256"]
            path = relative_file(package / side, entry["path"])
            if expected is None:
                if path.exists() or path.is_symlink():
                    failures.append({"path": str(path), "reason": "EXPECTED_ABSENT"})
            elif not path.is_file() or sha256(path) != expected:
                failures.append({"path": str(path), "reason": "SOURCE_BYTES_MISMATCH"})
    if sha256(package / "PATCH.diff") != sources["patch_sha256"]:
        failures.append({"path": "PATCH.diff", "reason": "PATCH_HASH_MISMATCH"})
    target_results = []
    if args.target_root:
        if not args.target_root.is_dir():
            failures.append({"path": str(args.target_root), "reason": "TARGET_ROOT_NOT_DIRECTORY"})
        else:
            for entry in sources["production_files"]:
                path = relative_file(args.target_root, entry["path"])
                expected = entry[args.target_state + "_sha256"]
                actual = sha256(path) if path.is_file() else None
                matches = not (path.exists() or path.is_symlink()) if expected is None else actual == expected
                result = {"path": entry["path"], "expected_sha256": expected, "actual_sha256": actual, "match": matches}
                target_results.append(result)
                if not matches:
                    failures.append({"path": entry["path"], "reason": "TARGET_SOURCE_MISMATCH"})
    print(json.dumps({
        "status": "PASS_BYTE_VERIFICATION" if not failures else "FAIL",
        "package_file_count": len(expected_paths),
        "production_file_count": len(sources["production_files"]),
        "target_root": str(args.target_root) if args.target_root else None,
        "target_state": args.target_state,
        "target_results": target_results,
        "failures": failures,
        "writes": 0,
        "deployment_api_ui_natural_acceptance": "NOT_RUN",
        "note": "Source byte comparison only; the fixed-Git archive preimage still requires Mac owner verification.",
    }, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
