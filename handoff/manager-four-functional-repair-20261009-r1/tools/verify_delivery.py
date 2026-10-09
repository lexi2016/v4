#!/usr/bin/env python3
"""Verify package inventory and the four before/after + 16 unchanged R2 files.

This tool reads bytes only. CHECKSUMS.json is an inventory, not a signature;
its own identity must be obtained from the separately delivered ZIP/commit.
Files under LOCAL/ are local execution outputs and are outside that inventory.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys

SCHEMA = "v4.manager_four_function_repair.source_manifest.v1"
RUNTIME_COUNT = 4
UNCHANGED_COUNT = 16
JSON_LIMIT = 16 * 1024 * 1024


class VerificationError(ValueError):
    """An expected, reportable identity or package format failure."""


def relative_path(value: object) -> str:
    if (not isinstance(value, str) or not value or "\\" in value
            or any(ord(char) < 32 for char in value)):
        raise VerificationError("UNSAFE_RELATIVE_PATH:" + repr(value))
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value or value == ".":
        raise VerificationError("UNSAFE_RELATIVE_PATH:" + value)
    return value


def exact_file(root: Path, relative: str) -> Path:
    current = root
    for part in PurePosixPath(relative_path(relative)).parts:
        current = current / part
        if current.is_symlink():
            raise VerificationError("SYMLINK_REJECTED:" + str(current))
    try:
        mode = current.stat().st_mode
    except FileNotFoundError as exc:
        raise VerificationError("FILE_MISSING:" + str(current)) from exc
    if not stat.S_ISREG(mode):
        raise VerificationError("NOT_REGULAR_FILE:" + str(current))
    return current


def file_identity(path: Path) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "bytes": size}


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError("DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def read_json(root: Path, relative: str) -> dict:
    path = exact_file(root, relative)
    with path.open("rb") as stream:
        raw = stream.read(JSON_LIMIT + 1)
    if len(raw) > JSON_LIMIT:
        raise VerificationError("JSON_SIZE_LIMIT:" + relative)
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise VerificationError("JSON_OBJECT_REQUIRED:" + relative)
    return value


def _expected(row: dict, prefix: str = "") -> dict:
    digest, size = row.get(prefix + "sha256"), row.get(prefix + "bytes")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise VerificationError("INVALID_SHA256:" + str(row.get("path")))
    if type(size) is not int or size < 0:
        raise VerificationError("INVALID_BYTE_COUNT:" + str(row.get("path")))
    return {"sha256": digest, "bytes": size}


def _rows(value: object, count: int | None, label: str) -> list[dict]:
    if not isinstance(value, list) or (count is not None and len(value) != count):
        raise VerificationError(label + "_COUNT_INVALID")
    seen = set()
    for row in value:
        if not isinstance(row, dict):
            raise VerificationError(label + "_ROW_INVALID")
        path = relative_path(row.get("path"))
        if path in seen:
            raise VerificationError(label + "_DUPLICATE_PATH:" + path)
        seen.add(path)
    return value


def _check(root: Path, path: str, expected: dict, label: str) -> dict:
    actual = file_identity(exact_file(root, path))
    if actual != expected:
        raise VerificationError(label + ":" + path + ":expected="
                                + json.dumps(expected, sort_keys=True) + ":actual="
                                + json.dumps(actual, sort_keys=True))
    return {"path": path, **actual}


def _inventory_paths(root: Path) -> set[str]:
    result = set()

    def walk(folder: Path) -> None:
        for path in sorted(folder.iterdir()):
            relative = path.relative_to(root).as_posix()
            if relative == "LOCAL":
                # Local receipts are deliberately outside the released inventory.
                continue
            if path.is_symlink():
                raise VerificationError("PACKAGE_SYMLINK_REJECTED:" + relative)
            if path.is_dir():
                walk(path)
            elif path.is_file():
                if relative != "CHECKSUMS.json":
                    result.add(relative_path(relative))
            else:
                raise VerificationError("PACKAGE_NONREGULAR_ENTRY:" + relative)

    walk(root)
    return result


def verify(package: Path, *, source_root: Path | None = None,
           side: str = "after") -> dict:
    package = package.expanduser().resolve(strict=True)
    if not package.is_dir():
        raise VerificationError("PACKAGE_ROOT_NOT_DIRECTORY")
    if side not in {"before", "after"}:
        raise VerificationError("SIDE_INVALID")
    checksums = read_json(package, "CHECKSUMS.json")
    inventory = _rows(checksums.get("files"), None, "INVENTORY")
    listed = {row["path"] for row in inventory}
    if "CHECKSUMS.json" in listed or any(path == "LOCAL" or path.startswith("LOCAL/") for path in listed):
        raise VerificationError("INVENTORY_INCLUDES_EXCLUDED_OUTPUT")
    actual_paths = _inventory_paths(package)
    if listed != actual_paths:
        raise VerificationError("PACKAGE_INVENTORY_SET_MISMATCH:missing="
                                + json.dumps(sorted(listed - actual_paths)) + ":unlisted="
                                + json.dumps(sorted(actual_paths - listed)))
    for required in ("source_manifest.json", "UNCHANGED_R2_TARGETS.json",
                     "tools/verify_delivery.py", "tools/run_regression.py"):
        if required not in listed:
            raise VerificationError("INVENTORY_REQUIRED_FILE_MISSING:" + required)
    for row in inventory:
        _check(package, row["path"], _expected(row), "PACKAGE_CHECKSUM_MISMATCH")

    manifest = read_json(package, "source_manifest.json")
    if manifest.get("schema_version") != SCHEMA:
        raise VerificationError("SOURCE_MANIFEST_SCHEMA_INVALID")
    if not isinstance(manifest.get("input_commit"), str) or re.fullmatch(
            r"[0-9a-f]{40}", manifest["input_commit"]) is None:
        raise VerificationError("INPUT_COMMIT_INVALID")
    for field in ("target_date", "publication_date"):
        value = manifest.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{8}", value) is None:
            raise VerificationError("MANIFEST_DATE_INVALID:" + field)
        datetime.strptime(value, "%Y%m%d")
    runtime = _rows(manifest.get("runtime_files"), RUNTIME_COUNT, "RUNTIME")
    unchanged = _rows(read_json(package, "UNCHANGED_R2_TARGETS.json").get("files"),
                      UNCHANGED_COUNT, "UNCHANGED_R2")
    overlap = {row["path"] for row in runtime} & {row["path"] for row in unchanged}
    if overlap:
        raise VerificationError("RUNTIME_UNCHANGED_OVERLAP:" + json.dumps(sorted(overlap)))

    payloads = []
    for row in runtime:
        relative_path(row.get("input_snapshot_path"))
        for payload_side in ("before", "after"):
            path = payload_side + "/" + row["path"]
            if path not in listed:
                raise VerificationError("PAYLOAD_NOT_IN_INVENTORY:" + path)
            payloads.append(_check(package, path, _expected(row, payload_side + "_"),
                                   "BUNDLED_PAYLOAD_MISMATCH"))
    for row in unchanged:
        relative_path(row.get("input_snapshot_path"))
        _expected(row)
    expected_payload_paths = {row["path"] for row in payloads}
    actual_payload_paths = {path for path in listed if path.startswith(("before/", "after/"))}
    if actual_payload_paths != expected_payload_paths:
        raise VerificationError("BEFORE_AFTER_PAYLOAD_SET_MISMATCH")

    source_checks, unchanged_checks = [], []
    if source_root is not None:
        source_root = source_root.expanduser().resolve(strict=True)
        if not source_root.is_dir():
            raise VerificationError("SOURCE_ROOT_NOT_DIRECTORY")
        for row in runtime:
            source_checks.append(_check(source_root, row["path"], _expected(row, side + "_"),
                                         "SOURCE_" + side.upper() + "_MISMATCH"))
        for row in unchanged:
            unchanged_checks.append(_check(source_root, row["path"], _expected(row),
                                            "UNCHANGED_R2_SOURCE_MISMATCH"))
    return {
        "schema_version": "v4.manager_four_function_repair.verification.v1",
        "status": "PASS", "package_root": str(package),
        "input_commit": manifest["input_commit"],
        "target_date": manifest["target_date"], "publication_date": manifest["publication_date"],
        "source_manifest": file_identity(package / "source_manifest.json"),
        "checksums_inventory": file_identity(package / "CHECKSUMS.json"),
        "inventory_file_count": len(inventory), "bundled_payload_count": len(payloads),
        "source_root": str(source_root) if source_root is not None else None,
        "side": side if source_root is not None else None,
        "runtime_checked": source_checks, "unchanged_r2_checked": unchanged_checks,
        "source_writes": 0, "business_io": False, "deployment_claimed": False,
        "identity_scope": "Four runtime files and sixteen preserved R2 targets; not a complete Mac release identity.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-root", type=Path,
                        help="Optional isolated source checkout; check all four selected-side files and 16 unchanged targets.")
    parser.add_argument("--side", choices=("before", "after"), default="after")
    args = parser.parse_args(argv)
    try:
        result = verify(args.package, source_root=args.source_root, side=args.side)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc), "source_writes": 0}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
