#!/usr/bin/env python3
"""Verify the generated V4 review snapshot transport and content hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_CHUNK_BYTES = 400_000


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def main() -> int:
    manifest = json.loads((ROOT / "metadata/manifest.json").read_text(encoding="utf-8"))
    transport = json.loads((ROOT / "metadata/transport_index.json").read_text(encoding="utf-8"))
    source_state = json.loads((ROOT / "metadata/source_state.json").read_text(encoding="utf-8"))
    secret_scan = json.loads((ROOT / "metadata/secret_scan.json").read_text(encoding="utf-8"))
    exclusions = json.loads((ROOT / "metadata/exclusions.json").read_text(encoding="utf-8"))

    if source_state.get("source_content_consistent_at_capture") is not True:
        return fail("source files changed during capture")
    if source_state.get("active_deploy_equivalence") != "CANNOT_CONFIRM":
        return fail("active deployment status is not explicit")
    if source_state.get("all_tests_claimed") is not False or source_state.get("tests_run") is not False:
        return fail("test status overclaims this snapshot task")
    if secret_scan.get("result") != "NO_PATTERN_MATCHES" or secret_scan.get("finding_paths"):
        return fail("secret scan has unresolved path findings")
    if secret_scan.get("values_emitted") is not False:
        return fail("secret scan metadata does not confirm values were suppressed")

    expected_files = {entry["published_path"]: entry for entry in manifest["files"]}
    expected_files.update({entry["path"]: entry for entry in manifest["snapshot_artifacts"]})
    manifest_target = manifest["manifest_published_path"]
    manifest_bytes = (ROOT / "metadata/manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != transport["manifest_sha256"]:
        return fail("manifest SHA-256 differs from transport index")
    if git_blob_sha(manifest_bytes) != transport["manifest_git_blob_sha"]:
        return fail("manifest Git blob SHA differs from transport index")
    expected_files[manifest_target] = {
        "path": manifest_target,
        "mode": "100644",
        "size_bytes": len(manifest_bytes),
        "sha256": transport["manifest_sha256"],
        "git_blob_sha": transport["manifest_git_blob_sha"],
    }

    assembled: dict[str, list[tuple[int, int, str]]] = {}
    total_rows = 0
    max_chunk = 0
    chunks = transport["chunks"]
    for chunk in chunks:
        path = ROOT / chunk["path"]
        data = path.read_bytes()
        max_chunk = max(max_chunk, len(data))
        if len(data) > MAX_CHUNK_BYTES:
            return fail(f"upload chunk exceeds size cap: {chunk['path']}")
        if len(data) != chunk["size_bytes"] or hashlib.sha256(data).hexdigest() != chunk["sha256"]:
            return fail(f"upload chunk hash or size mismatch: {chunk['path']}")
        doc = json.loads(data.decode("utf-8"))
        if doc.get("schema") != "v4-github-tree-entries.v1":
            return fail(f"unexpected upload chunk schema: {chunk['path']}")
        rows = doc.get("entries")
        if not isinstance(rows, list) or len(rows) != chunk["entry_rows"]:
            return fail(f"upload row count mismatch: {chunk['path']}")
        total_rows += len(rows)
        for row in rows:
            if not all(k in row for k in ("path", "mode", "type", "content", "part", "parts")):
                return fail(f"upload row is missing required fields: {chunk['path']}")
            if row["path"] not in expected_files:
                return fail(f"upload row path absent from manifest: {chunk['path']}")
            if not isinstance(row["content"], str) or row["type"] != "blob":
                return fail(f"upload row has an invalid content or blob type: {chunk['path']}")
            if row["mode"] != expected_files[row["path"]].get("mode", "100644"):
                return fail(f"upload row mode differs from manifest: {chunk['path']}")
            assembled.setdefault(row["path"], []).append((row["part"], row["parts"], row["content"]))

    if set(assembled) != set(expected_files):
        return fail("upload transport and file manifest path sets differ")
    for path, parts in assembled.items():
        parts.sort(key=lambda item: item[0])
        expected_part_count = parts[0][1]
        if expected_part_count != len(parts) or [p[0] for p in parts] != list(range(1, len(parts) + 1)):
            return fail(f"upload content pieces are incomplete: {path}")
        if any(part_count != expected_part_count for _, part_count, _ in parts):
            return fail(f"upload content part counts disagree: {path}")
        data = "".join(piece for _, _, piece in parts).encode("utf-8")
        record = expected_files[path]
        if len(data) != record["size_bytes"]:
            return fail(f"reassembled file byte count mismatch: {path}")
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            return fail(f"reassembled file SHA-256 mismatch: {path}")
        if git_blob_sha(data) != record["git_blob_sha"]:
            return fail(f"reassembled file Git blob SHA mismatch: {path}")

    if manifest["source_file_count"] != len(manifest["files"]):
        return fail("source manifest file count mismatch")
    if exclusions["excluded_path_count"] != len(exclusions["excluded_paths"]):
        return fail("exclusion path count mismatch")
    if exclusions["market_capture_fixture_count"] != len(exclusions["market_capture_fixtures"]):
        return fail("market-capture fixture path count mismatch")
    if transport["tree_file_count"] != len(expected_files):
        return fail("transport tree path count mismatch")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if (
        "CANNOT_CONFIRM" not in readme
        or "No claim is made that all tests pass" not in readme
        or "unified review entry point" not in readme
        or "docs/source_snapshot_20260929/metadata/manifest.json" not in readme
    ):
        return fail("README lacks required review limitations")

    print(
        "PASS: "
        f"{len(expected_files)} tree files reassembled from {len(chunks)} chunks "
        f"({total_rows} rows); max chunk {max_chunk} bytes; "
        f"{exclusions['excluded_path_count']} exclusions, "
        f"{exclusions['market_capture_fixture_count']} market-capture fixture paths; secret scan clean."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
