#!/usr/bin/env python3
"""Build a deterministic ZIP from package_manifest.json and write its SHA sidecar."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.package_root.resolve()
    output = args.output.resolve()
    if output == root or root in output.parents:
        print("FAIL: output ZIP must be outside package-root", file=sys.stderr)
        return 2
    manifest_path = root / "package_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot read package manifest: {exc}", file=sys.stderr)
        return 2
    records = manifest.get("files")
    if not isinstance(records, list):
        print("FAIL: manifest files must be a list", file=sys.stderr)
        return 2
    names: list[str] = []
    for record in records:
        name = str(record.get("path", ""))
        rel = Path(name)
        if not name or rel.is_absolute() or ".." in rel.parts or name == "package_manifest.json":
            print(f"FAIL: invalid manifest path {name!r}", file=sys.stderr)
            return 2
        path = root / rel
        try:
            actual = sha256(path.read_bytes())
        except OSError as exc:
            print(f"FAIL: missing package file {name}: {exc}", file=sys.stderr)
            return 2
        if actual != record.get("sha256"):
            print(f"FAIL: package SHA mismatch: {name}", file=sys.stderr)
            return 2
        names.append(name)
    actual_files = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p != manifest_path
    }
    if set(names) != actual_files or len(names) != len(set(names)):
        print("FAIL: manifest package closure differs from files on disk", file=sys.stderr)
        return 2
    names.sort()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in [*names, "package_manifest.json"]:
            data = (root / name).read_bytes()
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 9, 6, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    digest = sha256(output.read_bytes())
    sidecar = output.with_suffix(output.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"PASS: built {output} ({len(names) + 1} files, sha256={digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
