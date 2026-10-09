#!/usr/bin/env python3
"""Create or verify the portable offline handoff ZIP using only the standard library."""
from __future__ import annotations
import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PACKAGE = ROOT / "package"
ZIP_PATH = ROOT / "ZIP" / "V4_MANAGER_FOUR_FUNCTION_GAPS_20261009.zip"
FILE_MANIFEST = PACKAGE / "PACKAGE_FILE_MANIFEST.json"
SOURCE_MANIFEST = PACKAGE / "SOURCE_SNAPSHOT_MANIFEST.json"
FORBIDDEN_SUFFIXES = {".csv", ".parquet", ".db", ".sqlite", ".png", ".jpg", ".jpeg", ".pyc"}

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def package_entries():
    rows = []
    for path in sorted(PACKAGE.rglob("*")):
        if not path.is_file() or path == FILE_MANIFEST:
            continue
        rel = path.relative_to(PACKAGE).as_posix()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise SystemExit(f"FORBIDDEN_PACKAGE_FILE:{rel}")
        rows.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256(path.read_bytes())})
    return rows

def verify_source_copies() -> None:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    for row in manifest["files"]:
        path = PACKAGE / row["bundle_path"]
        if not path.is_file():
            raise SystemExit(f"SOURCE_COPY_MISSING:{row['bundle_path']}")
        actual = sha256(path.read_bytes())
        if actual != row["bundle_sha256"] or actual != row["source_sha256"]:
            raise SystemExit(f"SOURCE_COPY_SHA_MISMATCH:{row['bundle_path']}")
    print(f"SOURCE_SNAPSHOTS=PASS ({len(manifest['files'])} files)")

def write_file_manifest() -> None:
    data = {"schema_version": "offline_handoff.package_files.v1", "files": package_entries()}
    FILE_MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def write_zip() -> None:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(PACKAGE.rglob("*")):
            if not path.is_file():
                continue
            rel = "package/" + path.relative_to(PACKAGE).as_posix()
            info = zipfile.ZipInfo(rel, date_time=(2026, 10, 9, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

def verify_zip() -> None:
    expected = {row["path"]: row for row in json.loads(FILE_MANIFEST.read_text(encoding="utf-8"))["files"]}
    expected["PACKAGE_FILE_MANIFEST.json"] = {
        "bytes": FILE_MANIFEST.stat().st_size,
        "sha256": sha256(FILE_MANIFEST.read_bytes()),
    }
    with zipfile.ZipFile(ZIP_PATH) as archive:
        names = archive.namelist()
        actual_names = {name.removeprefix("package/") for name in names}
        if actual_names != set(expected):
            raise SystemExit(f"ZIP_MEMBER_SET_MISMATCH:missing={sorted(set(expected)-actual_names)} extra={sorted(actual_names-set(expected))}")
        for name in names:
            rel = name.removeprefix("package/")
            payload = archive.read(name)
            row = expected[rel]
            if len(payload) != row["bytes"] or sha256(payload) != row["sha256"]:
                raise SystemExit(f"ZIP_MEMBER_SHA_MISMATCH:{rel}")
    print("DIRECTORY_ZIP_CONSISTENCY=PASS")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="rewrite package file manifest and deterministic ZIP")
    args = parser.parse_args()
    verify_source_copies()
    if args.build:
        write_file_manifest()
        write_zip()
    if not FILE_MANIFEST.is_file() or not ZIP_PATH.is_file():
        raise SystemExit("PACKAGE_MANIFEST_OR_ZIP_MISSING")
    current = package_entries()
    recorded = json.loads(FILE_MANIFEST.read_text(encoding="utf-8"))["files"]
    if current != recorded:
        raise SystemExit("PACKAGE_FILE_MANIFEST_MISMATCH:run --build")
    verify_zip()
    print(f"PACKAGE_FILE_COUNT={len(recorded)+1}")
    print(f"ZIP_SHA256={sha256(ZIP_PATH.read_bytes())}")
    print(f"ZIP_BYTES={ZIP_PATH.stat().st_size}")

if __name__ == "__main__":
    main()
