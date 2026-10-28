from __future__ import annotations

from typing import Any

from .contracts import canonical_sha256, valid_sha


def _validate_map(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{label}_NOT_MAP")
    for key, digest in value.items():
        if not isinstance(key, str) or not key or not valid_sha(digest):
            raise ValueError(f"{label}_IDENTITY_INVALID:{key}")
    return value


def verify_final_delta(
    source_before: dict[str, str],
    source_after: dict[str, str],
    target: dict[str, str],
    decisions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    _validate_map(source_before, "SOURCE_BEFORE")
    _validate_map(source_after, "SOURCE_AFTER")
    _validate_map(target, "TARGET")
    if source_before != source_after:
        raise ValueError("SOURCE_CHANGED_AFTER_FENCE")
    if not isinstance(decisions, dict):
        raise ValueError("DECISIONS_NOT_MAP")
    missing_decisions = sorted(set(source_before) - set(decisions))
    if missing_decisions:
        raise ValueError("DECISION_MISSING:" + ",".join(missing_decisions))
    excluded: list[str] = []
    promoted: list[str] = []
    for key, source_sha in source_before.items():
        decision = decisions[key]
        if not isinstance(decision, dict):
            raise ValueError(f"DECISION_INVALID:{key}")
        action = decision.get("action")
        if decision.get("sha256") != source_sha:
            raise ValueError(f"DECISION_SHA_MISMATCH:{key}")
        if action == "PROMOTE_SOURCE":
            if target.get(key) != source_sha:
                raise ValueError(f"TARGET_PROMOTION_MISMATCH:{key}")
            promoted.append(key)
        elif action == "QUARANTINE_EXCLUDE":
            if key in target:
                raise ValueError(f"QUARANTINED_KEY_PRESENT_IN_TARGET:{key}")
            excluded.append(key)
        else:
            raise ValueError(f"DECISION_ACTION_INVALID:{key}")
    extras = sorted(set(target) - set(source_before))
    if extras:
        raise ValueError("UNPLANNED_TARGET_KEYS:" + ",".join(extras))
    proof = {
        "source_before_sha256": canonical_sha256(source_before),
        "source_after_sha256": canonical_sha256(source_after),
        "target_sha256": canonical_sha256(target),
        "decisions_sha256": canonical_sha256(decisions),
        "promoted_keys": sorted(promoted),
        "excluded_keys": sorted(excluded),
        "loss_count": 0,
        "extra_count": 0,
    }
    proof_sha = canonical_sha256(proof)
    return {
        "schema": "v4_migration.final_delta_receipt.v2",
        "status": "PASS",
        "source_stable_after_fence": True,
        **proof,
        "proof_sha256": proof_sha,
    }


def build_rollback_capture(old_authority: dict[str, str], new_authority: dict[str, str]) -> dict[str, Any]:
    _validate_map(old_authority, "OLD_AUTHORITY")
    _validate_map(new_authority, "NEW_AUTHORITY")
    preserve = {key: value for key, value in new_authority.items() if old_authority.get(key) != value}
    proof = {
        "old_authority_sha256": canonical_sha256(old_authority),
        "new_authority_sha256": canonical_sha256(new_authority),
        "preserve_before_rollback": preserve,
        "preserve_count": len(preserve),
    }
    return {
        "schema": "v4_migration.rollback_capture.v2",
        **proof,
        "proof_sha256": canonical_sha256(proof),
        "destructive_merge_performed": False,
    }
