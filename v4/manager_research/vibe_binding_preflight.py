"""Read-only preflight for the existing Vibe aggregated-review binding.

The existing contract is A-share review context.  This module deliberately does
not call Vibe, create HK candidates, or infer a state root/SHA.  It only tells
an operator whether the already-owned binding inputs are present and verifiable.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


def required_inputs(dates: Sequence[str]) -> list[str]:
    return ["binding_json", "implementation_manifest_sha256", *[f"input_sha256_by_date:{date}" for date in dates]]


def preflight_vibe_binding(config: Mapping[str, Any] | None, dates: Sequence[str]) -> dict[str, Any]:
    dates = [str(date) for date in dates]
    base = {
        "schema_version": "v4.manager_research.vibe_binding_preflight.v1",
        "source_contract": "A_SHARE_AGGREGATED_REVIEW_CONTEXT_ONLY",
        "hk_candidate_coverage": "NOT_PROVIDED_BY_VIBE_A_SHARE_REVIEW_CONTRACT",
        "network_requests": 0,
        "writes": 0,
        "required_inputs": required_inputs(dates),
        "verified_dates": [],
        "gaps": [],
    }
    if config is None:
        return {**base, "status": "NOT_CONFIGURED", "gaps": ["VIBE_OWNER_INPUT_BINDING_NOT_CONFIGURED"]}
    if config.get("schema_version") != "v4.manager_existing_vibe_binding.v1":
        return {**base, "status": "SOURCE_FAILED", "gaps": ["VIBE_EXPLICIT_BINDING_SCHEMA_INVALID"]}
    implementation = config.get("implementation_manifest_sha256")
    if not re.fullmatch(r"[0-9a-f]{64}", str(implementation or "")):
        return {**base, "status": "SOURCE_FAILED", "gaps": ["VIBE_IMPLEMENTATION_MANIFEST_SHA_NOT_BOUND"]}
    sha_by_date = config.get("input_sha256_by_date")
    if not isinstance(sha_by_date, Mapping):
        return {**base, "status": "SOURCE_FAILED", "gaps": ["VIBE_INPUT_SHA_MAP_INVALID"]}
    missing = [date for date in dates if not re.fullmatch(r"[0-9a-f]{64}", str(sha_by_date.get(date) or ""))]
    if missing:
        return {**base, "status": "INPUT_MISSING", "gaps": [f"VIBE_EXACT_INPUT_SHA_NOT_BOUND:{date}" for date in missing]}
    return {**base, "status": "CONFIGURED_REQUIRES_OWNER_READ_VALIDATION", "verified_dates": dates}


def finalize_vibe_preflight(preflight: Mapping[str, Any], *, verified_dates: Sequence[str], failed_dates: Sequence[str]) -> dict[str, Any]:
    result=dict(preflight)
    result["verified_dates"]=sorted(set(str(v) for v in verified_dates))
    failed=sorted(set(str(v) for v in failed_dates))
    if failed:
        result["status"]="PARTIAL_A_SHARE_CONTEXT_ONLY" if result["verified_dates"] else "SOURCE_FAILED"
        result["gaps"]=sorted(set(list(result.get("gaps") or [])+[f"VIBE_OWNER_READ_FAILED:{date}" for date in failed]))
    elif result["verified_dates"]:
        result["status"]="READY_A_SHARE_CONTEXT_ONLY"
    return result


__all__ = ["preflight_vibe_binding", "finalize_vibe_preflight", "required_inputs"]
