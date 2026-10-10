#!/usr/bin/env python3
"""Verify the self-contained integrity of this issue package."""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "SOURCE_MANIFEST.json"
SUMS = ROOT / "PACKAGE_SHA256SUMS.txt"

def digest(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return len(raw), hashlib.sha256(raw).hexdigest()

def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = {row["path"]: row for row in manifest["package_artifacts"]}
    frontend_src = ROOT / "source/runtime-B-release/apps/web/src"
    forbidden_frontend = []
    for path in frontend_src.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(frontend_src)
        parts = relative.parts
        name = path.name.lower()
        test_dir = any(part in {"__tests__", "tests"} for part in parts[:-1])
        fixture_dir = any(part in {"fixtures", "fixture", "__fixtures__"} for part in parts[:-1])
        test_file = name.endswith((".spec.ts", ".spec.tsx", ".test.ts", ".test.tsx", ".spec.js", ".test.js")) or ".spec." in name or ".test." in name
        if test_dir or fixture_dir or test_file:
            forbidden_frontend.append(relative.as_posix())
    if forbidden_frontend:
        raise SystemExit(f"FORBIDDEN_RUNTIME_B_FRONTEND_TEST_OR_FIXTURE_PRESENT {forbidden_frontend[:10]}")
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and p.name not in {"SOURCE_MANIFEST.json", "PACKAGE_SHA256SUMS.txt"} and p.name != "_source_entries.tmp.json"}
    if actual != set(expected):
        raise SystemExit(f"PACKAGE_FILE_SET_MISMATCH missing={sorted(set(expected)-actual)} extra={sorted(actual-set(expected))}")
    for rel, row in expected.items():
        n, h = digest(ROOT / rel)
        if n != row["bytes"] or h != row["sha256"]:
            raise SystemExit(f"PACKAGE_ARTIFACT_SHA_MISMATCH {rel}")
    for row in manifest["source_snapshots"]:
        n, h = digest(ROOT / row["destination"])
        if n != row["copied_bytes"] or h != row["copied_sha256"]:
            raise SystemExit(f"SOURCE_COPY_SHA_MISMATCH {row['destination']}")
    listed = {}
    for line in SUMS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        h, rel = line.split("  ", 1)
        listed[rel] = h
    checksum_files = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and p.name != "PACKAGE_SHA256SUMS.txt" and p.name != "_source_entries.tmp.json"}
    if set(listed) != checksum_files:
        raise SystemExit("PACKAGE_CHECKSUM_FILE_SET_MISMATCH")
    for rel, expected_sha in listed.items():
        if digest(ROOT / rel)[1] != expected_sha:
            raise SystemExit(f"PACKAGE_CHECKSUM_MISMATCH {rel}")
    for path in ROOT.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    for path in ROOT.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and ("node_modules" in p.parts or "dist" in p.parts)]
    if forbidden:
        raise SystemExit(f"FORBIDDEN_BUILD_ARTIFACTS_PRESENT {forbidden[:5]}")
    print(f"PASS: {len(expected)} package artifacts; {len(manifest['source_snapshots'])} source snapshots; JSON/Python syntax and all checksums verified")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
