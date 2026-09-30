#!/usr/bin/env python3
"""Read-only final verification of the handoff file manifest and security scan."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


HANDOFF = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "HANDOFF_FILE_MANIFEST.json"
SIDECAR_NAME = "HANDOFF_FILE_MANIFEST.sha256"
PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(rb"\bsk-[A-Za-z0-9]{48,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9._-]{24,}"),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def main() -> None:
    manifest_path = HANDOFF / MANIFEST_NAME
    sidecar_path = HANDOFF / SIDECAR_NAME
    errors = []
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise SystemExit("CANNOT_CONFIRM: final handoff manifest or SHA sidecar is missing")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    sidecar = {}
    for line in sidecar_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            key, value = line.split(" ", 1)
            sidecar[key] = value
    if sha256(manifest_bytes) != sidecar.get("sha256"):
        errors.append("manifest SHA-256 does not match sidecar")
    if blob_sha1(manifest_bytes) != sidecar.get("git_blob_sha1"):
        errors.append("manifest Git blob SHA-1 does not match sidecar")

    expected = {row["path"]: row for row in manifest.get("files", [])}
    actual_paths = {
        path.relative_to(HANDOFF).as_posix()
        for path in HANDOFF.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name not in {MANIFEST_NAME, SIDECAR_NAME}
    }
    if actual_paths != set(expected):
        errors.append(f"file set differs: missing={len(set(expected)-actual_paths)} extra={len(actual_paths-set(expected))}")
    for rel, row in expected.items():
        path = HANDOFF / rel
        if not path.is_file() or path.is_symlink():
            errors.append(f"manifest entry missing or non-regular: {rel}")
            continue
        data = path.read_bytes()
        if (len(data), sha256(data), blob_sha1(data)) != (row["bytes"], row["sha256"], row["git_blob_sha1"]):
            errors.append(f"manifest identity mismatch: {rel}")
    if len(expected) != manifest.get("payload_file_count"):
        errors.append("manifest file count does not match payload_file_count")
    if sum(row["bytes"] for row in expected.values()) != manifest.get("payload_bytes"):
        errors.append("manifest byte total does not match payload_bytes")
    if sidecar.get("payload_file_count") != str(len(expected)):
        errors.append("sidecar payload count mismatch")
    if sidecar.get("payload_bytes") != str(sum(row["bytes"] for row in expected.values())):
        errors.append("sidecar payload byte total mismatch")

    json_count = 0
    findings = []
    for path in sorted(HANDOFF.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            errors.append(f"unexpected symlink: {path.relative_to(HANDOFF)}")
            continue
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in PATTERNS):
            findings.append(path.relative_to(HANDOFF).as_posix())
        if path.suffix == ".json":
            try:
                json.loads(data)
                json_count += 1
            except (UnicodeDecodeError, json.JSONDecodeError):
                errors.append(f"invalid JSON: {path.relative_to(HANDOFF)}")
    errors.extend(f"high-confidence secret pattern: {path}" for path in findings)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors[:40]}, ensure_ascii=False))
        raise SystemExit(1)

    print(json.dumps({
        "status": "PASS",
        "manifest_payload_file_count": len(expected),
        "total_files_including_manifest_and_sidecar": len(expected) + 2,
        "payload_bytes": sum(row["bytes"] for row in expected.values()),
        "manifest_sha256": sha256(manifest_bytes),
        "manifest_git_blob_sha1": blob_sha1(manifest_bytes),
        "parsed_json_file_count_including_manifest": json_count,
        "final_secret_scan_file_count": len(actual_paths) + 2,
        "final_secret_findings": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
