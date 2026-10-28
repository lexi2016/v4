from __future__ import annotations

from typing import Any


def evaluate_runtime(evidence: dict[str, Any]) -> dict[str, Any]:
    """Cache reuse has no trusted shared-runtime attestation in this scope."""
    decision = evidence.get("decision") if isinstance(evidence, dict) else None
    if decision == "KEEP_ISOLATED":
        reviewed = evidence.get("independent_review") == "PASS"
        return {
            "operational_status": "KEEP_ISOLATED_ACCEPTED" if reviewed else "KEEP_ISOLATED_NEEDS_REVIEW",
            "merge_authorized": False,
            "shared_cache_allowed": False,
            "cache_policy_status": "CANNOT_CONFIRM_KEEP_ISOLATED",
        }
    required = ("unified_abi", "unified_rebuild", "unified_launch", "unified_behavior")
    if decision == "MERGE_ELIGIBLE_FOR_INDEPENDENT_REVIEW" and evidence.get("independent_review") == "PASS" and all(evidence.get(key) == "PASS" for key in required):
        return {
            "operational_status": "MERGE_REQUIRES_SEPARATE_AUTHORIZATION",
            "merge_authorized": False,
            "shared_cache_allowed": False,
            "cache_policy_status": "CANNOT_CONFIRM_TRUSTED_SHARED_CACHE_CONTRACT",
        }
    return {
        "operational_status": "CANNOT_CONFIRM",
        "merge_authorized": False,
        "shared_cache_allowed": False,
        "cache_policy_status": "CANNOT_CONFIRM_TRUSTED_SHARED_CACHE_CONTRACT",
    }
