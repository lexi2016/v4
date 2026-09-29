from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from .errors import RuntimeV1Error
from .hashio import assert_sha, canonical_json_bytes, is_sha256, load_json, require_absolute, require_regular_file, sha256_file

RUNTIME_SCHEMA = "factor_factory.runtime_capsule.v1"
_ALLOWED_STATUSES = {"CANDIDATE", "FROZEN"}


def runtime_manifest_review_digest(doc: Mapping[str, Any]) -> str:
    """Digest the reviewed runtime payload, excluding its self-referential evidence pointer."""
    payload = {key: value for key, value in doc.items() if key != "release_review_evidence"}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _verify_release_review(
    doc: Mapping[str, Any],
    verified: Mapping[str, Any],
    research_policy: Mapping[str, str],
) -> dict[str, Any]:
    evidence = doc.get("release_review_evidence")
    if not isinstance(evidence, Mapping):
        raise RuntimeV1Error("RUNTIME_RELEASE_REVIEW_REQUIRED")
    review_path = Path(str(evidence.get("path", "")))
    require_absolute(review_path, "RUNTIME_RELEASE_REVIEW_PATH_NOT_ABSOLUTE")
    expected_sha = evidence.get("sha256")
    if not is_sha256(expected_sha):
        raise RuntimeV1Error("RUNTIME_RELEASE_REVIEW_SHA_INVALID")
    assert_sha(review_path, str(expected_sha), "RUNTIME_RELEASE_REVIEW_SHA_MISMATCH")
    review = load_json(review_path, "RUNTIME_RELEASE_REVIEW_INVALID")
    if review.get("schema_version") != "factor_factory.runtime_v1_release_review.v1":
        raise RuntimeV1Error("RUNTIME_RELEASE_REVIEW_SCHEMA_INVALID")
    if (
        review.get("review_status") != "PASS"
        or type(review.get("p0")) is not int
        or type(review.get("p1")) is not int
        or review.get("p0") != 0
        or review.get("p1") != 0
    ):
        raise RuntimeV1Error("RUNTIME_RELEASE_REVIEW_NOT_ACCEPTED")
    reviewer = review.get("reviewer_identity")
    writer = review.get("writer_identity")
    if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(writer, str) or not writer.strip() or reviewer == writer:
        raise RuntimeV1Error("RUNTIME_RELEASE_REVIEW_INDEPENDENCE_UNCONFIRMED")
    if review.get("runtime_id") != doc.get("runtime_id") or review.get("reviewed_runtime_status") != "FROZEN":
        raise RuntimeV1Error("RUNTIME_RELEASE_REVIEW_IDENTITY_MISMATCH")
    if review.get("runtime_manifest_payload_sha256") != runtime_manifest_review_digest(doc):
        raise RuntimeV1Error("RUNTIME_RELEASE_REVIEW_MANIFEST_MISMATCH")
    if review.get("component_identities") != dict(verified):
        raise RuntimeV1Error("RUNTIME_RELEASE_REVIEW_COMPONENTS_MISMATCH")
    if review.get("research_lane_policy") != dict(research_policy):
        raise RuntimeV1Error("RUNTIME_RELEASE_REVIEW_POLICY_MISMATCH")
    return {
        "path": str(review_path),
        "sha256": str(expected_sha),
        "runtime_manifest_payload_sha256": runtime_manifest_review_digest(doc),
        "component_identities": dict(verified),
        "research_lane_policy": dict(research_policy),
        "trust_boundary": "LOCAL_REVIEW_RECEIPT_IDENTITY; NOT_A_CRYPTOGRAPHIC_OR_EXTERNAL_AUTHORITY",
    }


def load_runtime_manifest(path: Path, *, verify_sources: bool = True) -> dict[str, Any]:
    path = require_absolute(Path(path), "RUNTIME_MANIFEST_PATH_NOT_ABSOLUTE")
    path = require_regular_file(path, "RUNTIME_MANIFEST_REQUIRED")
    doc = load_json(path, "RUNTIME_MANIFEST_INVALID")
    if doc.get("schema_version") != RUNTIME_SCHEMA:
        raise RuntimeV1Error("RUNTIME_SCHEMA_INVALID", doc.get("schema_version"))
    runtime_id = doc.get("runtime_id")
    if not isinstance(runtime_id, str) or not runtime_id.strip():
        raise RuntimeV1Error("RUNTIME_ID_INVALID")
    if doc.get("status") not in _ALLOWED_STATUSES:
        raise RuntimeV1Error("RUNTIME_STATUS_INVALID", doc.get("status"))
    py = doc.get("python")
    if not isinstance(py, Mapping):
        raise RuntimeV1Error("RUNTIME_PYTHON_INVALID")
    py_path = Path(str(py.get("path", "")))
    require_absolute(py_path, "RUNTIME_PYTHON_PATH_NOT_ABSOLUTE")
    components = doc.get("components")
    if not isinstance(components, Mapping) or not components:
        raise RuntimeV1Error("RUNTIME_COMPONENTS_MISSING")
    required = {"training_entry", "training_runtime_manifest", "passport_policy", "passport_validator", "execution_guard", "registry_adapter", "resource_monitor"}
    missing = required - set(components)
    if missing:
        raise RuntimeV1Error("RUNTIME_COMPONENTS_INCOMPLETE", sorted(missing))
    verified: dict[str, dict[str, str]] = {}
    for name, raw in sorted(components.items()):
        if not isinstance(raw, Mapping):
            raise RuntimeV1Error("RUNTIME_COMPONENT_INVALID", name)
        component_path = Path(str(raw.get("path", "")))
        expected = raw.get("sha256")
        if not is_sha256(expected):
            raise RuntimeV1Error("RUNTIME_COMPONENT_SHA_INVALID", name)
        require_absolute(component_path, "RUNTIME_COMPONENT_PATH_NOT_ABSOLUTE")
        if verify_sources:
            actual = assert_sha(component_path, str(expected), "RUNTIME_COMPONENT_DRIFT")
            verified[name] = {"path": str(component_path), "sha256": actual}
    policy_pin = doc.get("research_lane_policy")
    if not isinstance(policy_pin, Mapping):
        raise RuntimeV1Error("RUNTIME_POLICY_PIN_REQUIRED")
    raw_policy_path = Path(str(policy_pin.get("path", "")))
    expected_policy_sha = policy_pin.get("sha256")
    if raw_policy_path.is_absolute() or not raw_policy_path.parts or ".." in raw_policy_path.parts or not is_sha256(expected_policy_sha):
        raise RuntimeV1Error("RUNTIME_POLICY_PIN_INVALID")
    policy_path = path.parent / raw_policy_path
    actual_policy_sha = assert_sha(policy_path, str(expected_policy_sha), "RUNTIME_POLICY_DRIFT")
    verified_policy = {"path": str(policy_path.resolve()), "sha256": actual_policy_sha}
    out = dict(doc)
    out["_manifest_path"] = str(path)
    out["_manifest_sha256"] = sha256_file(path)
    out["_verified_components"] = verified
    out["_verified_research_lane_policy"] = verified_policy
    if doc.get("status") == "FROZEN":
        out["_release_review_verified"] = _verify_release_review(doc, verified, verified_policy)
    return out


def component_path(runtime: Mapping[str, Any], name: str) -> Path:
    components = runtime.get("components")
    if not isinstance(components, Mapping) or name not in components:
        raise RuntimeV1Error("RUNTIME_COMPONENT_NOT_FOUND", name)
    raw = components[name]
    if not isinstance(raw, Mapping):
        raise RuntimeV1Error("RUNTIME_COMPONENT_INVALID", name)
    return Path(str(raw["path"]))
