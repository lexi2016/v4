from __future__ import annotations

from typing import Any

from .contracts import canonical_sha256, valid_sha
from .safe_io import copy_verified_file


def verify_and_quarantine_duplicate(
    item: dict[str, Any],
    source_root: str,
    quarantine_root: str,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("DUPLICATE_ITEM_INVALID")
    if item.get("projection") not in {"NONE_REQUIRES_OWNER_DECISION", None}:
        raise ValueError("DUPLICATE_PROJECTION_ALREADY_SELECTED")
    identity = item.get("artifact_identity")
    if not isinstance(identity, dict):
        raise ValueError("DUPLICATE_IDENTITY_INVALID")
    relative = identity.get("relative_path")
    digest = identity.get("sha256")
    size = identity.get("bytes")
    business_key = item.get("business_key")
    if not isinstance(relative, str) or not valid_sha(digest) or isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("DUPLICATE_IDENTITY_INVALID")
    if not isinstance(business_key, str) or not business_key:
        raise ValueError("DUPLICATE_BUSINESS_KEY_INVALID")
    copied = copy_verified_file(source_root, relative, quarantine_root, expected_sha256=digest, expected_bytes=size)
    proof = {
        "business_key": business_key,
        "relative_path": relative,
        "sha256": copied["sha256"],
        "bytes": copied["bytes"],
    }
    return {
        "schema": "v4_migration.duplicate_quarantine.v2",
        "status": "PASS",
        **proof,
        "proof_sha256": canonical_sha256(proof),
        "automatic_winner_selected": False,
        "owner_decision_required": True,
        "source_deleted": False,
        "authority_established": False,
    }
