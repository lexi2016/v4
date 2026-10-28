from __future__ import annotations

import hashlib
from typing import Any

from .contracts import canonical_sha256, valid_sha
from .safe_io import copy_verified_file, read_relative_file


def _validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        raise ValueError("EMPTY_ARCHIVE_MANIFEST_INVALID")
    items = manifest.get("items")
    if not isinstance(items, list) or isinstance(manifest.get("item_count"), bool) or manifest.get("item_count") != len(items):
        raise ValueError("EMPTY_ARCHIVE_COUNT_MISMATCH")
    seen_paths: set[str] = set()
    seen_keys: set[str] = set()
    validated: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or item.get("row_count") != 0:
            raise ValueError("EMPTY_ARCHIVE_ROW_COUNT_NONZERO")
        business_key = item.get("business_key")
        identity = item.get("artifact_identity")
        if not isinstance(business_key, str) or not business_key or not isinstance(identity, dict):
            raise ValueError("EMPTY_ARCHIVE_ITEM_INVALID")
        relative = identity.get("relative_path")
        digest = identity.get("sha256")
        size = identity.get("bytes")
        if not isinstance(relative, str) or not valid_sha(digest) or isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("EMPTY_ARCHIVE_IDENTITY_INVALID")
        if relative in seen_paths or business_key in seen_keys:
            raise ValueError("EMPTY_ARCHIVE_DUPLICATE_ITEM")
        seen_paths.add(relative)
        seen_keys.add(business_key)
        validated.append({"business_key": business_key, "relative_path": relative, "sha256": digest, "bytes": size})
    return validated


def verify_empty_archive_sources(manifest: dict[str, Any], source_root: str | Path) -> dict[str, Any]:
    items = _validate_manifest(manifest)
    rows = []
    for item in items:
        raw = read_relative_file(source_root, item["relative_path"])
        if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("EMPTY_ARCHIVE_SOURCE_IDENTITY_MISMATCH")
        rows.append(dict(item))
    return {
        "schema": "v4_migration.empty_archive_preflight.v2",
        "status": "PASS",
        "count": len(rows),
        "manifest_sha256": canonical_sha256(manifest),
        "items": rows,
        "source_deleted": False,
    }


def preserve_empty_archive(
    manifest: dict[str, Any],
    source_root: str | Path,
    archive_root: str | Path,
    *,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    recomputed = verify_empty_archive_sources(manifest, source_root)
    if preflight != recomputed:
        raise ValueError("PREFLIGHT_MANIFEST_MISMATCH")
    copied = []
    for item in recomputed["items"]:
        identity = copy_verified_file(
            source_root,
            item["relative_path"],
            archive_root,
            expected_sha256=item["sha256"],
            expected_bytes=item["bytes"],
        )
        copied.append({"business_key": item["business_key"], "relative_path": item["relative_path"], **identity})
    return {
        "schema": "v4_migration.empty_archive_preservation.v2",
        "status": "PASS",
        "count": len(copied),
        "manifest_sha256": recomputed["manifest_sha256"],
        "items": copied,
        "deletion_performed": False,
        "authority_established": False,
        "staging_authorized": False,
    }
