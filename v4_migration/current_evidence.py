"""Read-only verifier for the frozen current Batch3 evidence envelope."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .safe_io import read_absolute_file, read_relative_file

BINDINGS_SHA256 = "d6a49c39681119f827f8ccdcf46fab9e9fc8bb98cb45883c940449296e9a3f21"
BINDING_REVIEW_SHA256 = "c0486a2d2d2bbcba96328eff49de6ed781ee02b711ef802d46554252426aaebc"
INDEPENDENT_REVIEW_SHA256 = "2e3f6fc631576f2f3e5583a1d5768dd5747222756a9fe740fedd3f3c554f41b2"
ACCEPTED_PREFLIGHT_SHA256 = "6c0706f2825b6550936db9eff201264572d763648df8a11399fda1514dda9b9e"
ACCEPTED_REVIEW_SHA256 = "7d5634ba2d0e513fdd621e2c0c1ed474134fbb9ba0b7a379532538e9a28404f4"
EXPECTED_BLOCKER_CODES = (
    "DUPLICATE_CODE_OWNER_DECISION_MISSING",
    "CONFLICT_RESOLUTION_INCOMPLETE",
    "CUTOVER_OWNER_ADAPTERS_UNBOUND",
    "METADATA_SIDECAR_CONFLICTS_UNRESOLVED",
)
SAFETY_FALSE_FIELDS = (
    "authority_cutover_authorized",
    "production_switch_executed",
    "writer_fenced",
    "writer_drained",
    "canonical_root_changed",
    "scheduler_changed",
    "old_system_retired",
    "production_allowed",
    "buy_gate_updated",
    "orders_sent",
)
def _read_json(root: Path, relative: str, expected_sha256: str | None = None) -> tuple[dict[str, Any], str]:
    raw = read_relative_file(root, relative)
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("CURRENT_EVIDENCE_HASH_MISMATCH")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("CURRENT_EVIDENCE_OBJECT_REQUIRED")
    return value, digest


def _role(index: dict[str, Any], role_name: str) -> dict[str, Any]:
    rows = index.get("files")
    if not isinstance(rows, list):
        raise ValueError("CURRENT_BINDING_ROWS_INVALID")
    matches = [row for row in rows if isinstance(row, dict) and row.get("role") == role_name]
    if len(matches) != 1:
        raise ValueError("CURRENT_BINDING_ROLE_INVALID")
    row = matches[0]
    if row.get("transformed") is not False or not isinstance(row.get("sha256"), str) or not isinstance(row.get("bytes"), int):
        raise ValueError("CURRENT_BINDING_ROW_UNVERIFIED")
    return row


def _verify_binding_pairs(root: Path, rows: list[Any]) -> str:
    """Reopen every pinned source/copy pair under the frozen path convention."""
    roles: set[str] = set()
    originals: set[str] = set()
    copies: set[str] = set()
    identities: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("CURRENT_BINDING_ROW_UNVERIFIED")
        role = row.get("role")
        expected_sha256 = row.get("sha256")
        expected_bytes = row.get("bytes")
        original_path = row.get("original_path")
        copy_path = row.get("copy_path")
        if (
            not isinstance(role, str) or not role or role in roles
            or isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0
            or not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_sha256)
            or not isinstance(original_path, str) or not Path(original_path).is_absolute()
            or not isinstance(copy_path, str)
        ):
            raise ValueError("CURRENT_BINDING_ROW_UNVERIFIED")
        copy = Path(copy_path)
        if (
            not copy.is_absolute() or not copy.name
            or copy.parent.name != "evidence_current_raw"
            or copy.parent.parent != root
        ):
            raise ValueError("CURRENT_BINDING_COPY_PATH_INVALID")
        relative_copy = f"evidence_current_raw/{copy.name}"
        if original_path in originals or relative_copy in copies:
            raise ValueError("CURRENT_BINDING_PATH_DUPLICATE")
        originals.add(original_path)
        copies.add(relative_copy)
        original_bytes = read_absolute_file(original_path)
        copied_bytes = read_relative_file(root, relative_copy)
        original_sha256 = hashlib.sha256(original_bytes).hexdigest()
        copied_sha256 = hashlib.sha256(copied_bytes).hexdigest()
        if (
            len(original_bytes) != expected_bytes or original_sha256 != expected_sha256
            or len(copied_bytes) != expected_bytes or copied_sha256 != expected_sha256
        ):
            raise ValueError("CURRENT_BINDING_PAIR_MISMATCH")
        roles.add(role)
        identities.append({"role": role, "sha256": expected_sha256, "bytes": expected_bytes})
    if len(rows) != 14 or len(roles) != 14:
        raise ValueError("CURRENT_BINDING_ROLE_COUNT_MISMATCH")
    canonical = json.dumps(sorted(identities, key=lambda item: item["role"]), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_current_evidence(evidence_root: str | Path) -> dict[str, Any]:
    root = Path(evidence_root)
    if not root.is_absolute():
        if ".." in root.parts:
            raise ValueError("CURRENT_EVIDENCE_ROOT_PATH_INVALID")
        root = Path.cwd() / root
    bindings, bindings_sha = _read_json(root, "CURRENT_EVIDENCE_BINDINGS.json", BINDINGS_SHA256)
    binding_review, binding_review_sha = _read_json(
        root, "control_review/CURRENT_EVIDENCE_BINDINGS_REVIEW.json", BINDING_REVIEW_SHA256
    )
    independent, independent_sha = _read_json(root, "control_review/INDEPENDENT_REVIEW.json", INDEPENDENT_REVIEW_SHA256)
    current, preflight_sha = _read_json(
        root, "evidence_current_raw/accepted_batch3_preflight.json", ACCEPTED_PREFLIGHT_SHA256
    )
    accepted_review, accepted_review_sha = _read_json(
        root, "evidence_current_raw/accepted_batch3_review.json", ACCEPTED_REVIEW_SHA256
    )

    if bindings_sha != binding_review.get("index_sha256") or bindings.get("authority_or_cutover_authorized") is not False:
        raise ValueError("CURRENT_BINDING_ATTESTATION_MISMATCH")
    if bindings.get("new_owner_decisions") not in ([], 0, None, False):
        raise ValueError("UNEXPECTED_OWNER_DECISION_IN_CURRENT_BINDINGS")
    rows = bindings.get("files")
    if not isinstance(rows, list) or len(rows) != 14:
        raise ValueError("CURRENT_BINDING_ROLE_COUNT_MISMATCH")
    for row in rows:
        if not isinstance(row, dict) or row.get("transformed") is not False or isinstance(row.get("bytes"), bool) or not isinstance(row.get("bytes"), int) or not isinstance(row.get("sha256"), str):
            raise ValueError("CURRENT_BINDING_ROW_UNVERIFIED")
    pair_sha256 = _verify_binding_pairs(root, rows)

    preflight_row = _role(bindings, "accepted_batch3_preflight")
    review_row = _role(bindings, "accepted_batch3_review")
    if preflight_row.get("sha256") != preflight_sha or preflight_row.get("bytes") != len(read_relative_file(root, "evidence_current_raw/accepted_batch3_preflight.json")):
        raise ValueError("CURRENT_PREFLIGHT_BINDING_MISMATCH")
    if review_row.get("sha256") != accepted_review_sha or review_row.get("bytes") != len(read_relative_file(root, "evidence_current_raw/accepted_batch3_review.json")):
        raise ValueError("CURRENT_ACCEPTED_REVIEW_BINDING_MISMATCH")

    expected_codes = list(EXPECTED_BLOCKER_CODES)
    if (
        binding_review.get("index_sha256") != BINDINGS_SHA256
        or binding_review.get("actual_current_accepted_preflight_sha256") != ACCEPTED_PREFLIGHT_SHA256
        or binding_review.get("actual_current_accepted_status") != "BLOCKED"
        or binding_review.get("actual_current_blockers") != expected_codes
        or binding_review.get("all_pairs_byte_sha_verified") is not True
        or binding_review.get("original_and_copy_pairs_checked") != 28
        or binding_review.get("role_count") != 14
        or binding_review.get("errors") != []
        or binding_review.get("control_plane_source_refs_to_index_or_current_accepted_receipts") != []
    ):
        raise ValueError("CURRENT_BINDING_REVIEW_INVALID")

    accepted = independent.get("acceptance_evidence")
    if not isinstance(accepted, dict) or accepted.get("authority_or_cutover_authorized") is not False:
        raise ValueError("CURRENT_INDEPENDENT_REVIEW_INVALID")
    if accepted.get("binding_index_sha256") != BINDINGS_SHA256 or accepted.get("raw_binding_review_sha256") != BINDING_REVIEW_SHA256:
        raise ValueError("CURRENT_INDEPENDENT_REVIEW_BINDING_MISMATCH")
    if accepted.get("current_batch3_status") != "BLOCKED" or accepted.get("current_blockers") is None:
        raise ValueError("CURRENT_INDEPENDENT_GATE_NOT_BLOCKED")
    if [str(value).split(" ")[0] for value in accepted["current_blockers"]] != expected_codes:
        raise ValueError("CURRENT_INDEPENDENT_BLOCKERS_MISMATCH")

    if accepted_review.get("acceptance", {}).get("current_gate_status") != "BLOCKED":
        raise ValueError("CURRENT_ACCEPTED_REVIEW_NOT_BLOCKED")
    if accepted_review.get("acceptance", {}).get("current_blocker_codes") != expected_codes:
        raise ValueError("CURRENT_ACCEPTED_REVIEW_BLOCKERS_MISMATCH")
    if current.get("status") != "BLOCKED":
        raise ValueError("CURRENT_PREFLIGHT_NOT_BLOCKED")
    blockers = current.get("blockers")
    if not isinstance(blockers, list) or [row.get("code") for row in blockers if isinstance(row, dict)] != expected_codes:
        raise ValueError("CURRENT_PREFLIGHT_BLOCKERS_MISMATCH")
    for field in SAFETY_FALSE_FIELDS:
        if current.get(field) is not False:
            raise ValueError("CURRENT_PREFLIGHT_SAFETY_FIELD_INVALID")
    sidecar = blockers[3].get("detail")
    expected_sidecar = {
        "aggregate_manifests_verified": 6,
        "business_key_decisions_verified": 0,
        "business_keys_supported": 23,
        "file_evidence_verified": 29,
        "manual_sidecar_owner_decisions_required": 0,
        "resolved": 0,
        "total": 29,
        "unresolved": 29,
    }
    if sidecar != expected_sidecar:
        raise ValueError("CURRENT_SIDECAR_COUNTS_MISMATCH")

    proof = {
        "bindings_sha256": bindings_sha,
        "binding_review_sha256": binding_review_sha,
        "independent_review_sha256": independent_sha,
        "accepted_preflight_sha256": preflight_sha,
        "accepted_review_sha256": accepted_review_sha,
        "binding_pairs_sha256": pair_sha256,
    }
    return {"preflight": current, "proof": proof}


def build_current_preflight(evidence_root: str | Path) -> dict[str, Any]:
    try:
        verified = load_current_evidence(evidence_root)
    except Exception as exc:
        return {
            "schema": "v4_migration.pre_cutover.v2",
            "status": "BLOCKED",
            "verification_status": "CURRENT_EVIDENCE_UNBOUND",
            "blockers": [{"code": "CURRENT_EVIDENCE_UNBOUND", "detail": type(exc).__name__}],
            "authority_cutover_authorized": False,
            "production_switch_executed": False,
            "writer_fenced": False,
            "writer_drained": False,
            "canonical_root_changed": False,
            "scheduler_changed": False,
            "old_system_retired": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    return {
        "schema": "v4_migration.pre_cutover.v2",
        "status": "BLOCKED",
        "verification_status": "HASH_BOUND_CURRENT_RECEIPTS_VERIFIED",
        "blockers": verified["preflight"]["blockers"],
        "evidence_proof": verified["proof"],
        "authority_cutover_authorized": False,
        "production_switch_executed": False,
        "writer_fenced": False,
        "writer_drained": False,
        "canonical_root_changed": False,
        "scheduler_changed": False,
        "old_system_retired": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def build_preflight(evidence: Any) -> dict[str, Any]:
    """Accept only a current-evidence root and re-open its pinned envelope."""
    if isinstance(evidence, (str, Path)):
        return build_current_preflight(evidence)
    return {
        "schema": "v4_migration.pre_cutover.v2",
        "status": "BLOCKED",
        "verification_status": "UNVERIFIED_INPUT_REJECTED",
        "blockers": [{"code": "HASH_BOUND_EVIDENCE_REQUIRED", "detail": None}],
        "authority_cutover_authorized": False,
        "production_switch_executed": False,
        "writer_fenced": False,
        "writer_drained": False,
        "canonical_root_changed": False,
        "scheduler_changed": False,
        "old_system_retired": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
