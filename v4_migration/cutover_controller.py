from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import validate_authorization
from .current_evidence import build_current_preflight as _build_current_preflight

ACTIONS = ("fence", "drain", "final_delta", "switch", "readback", "rollback")
SAFETY = {
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


def _blocked(blockers: list[dict[str, Any]], verification_status: str) -> dict[str, Any]:
    return {
        "schema": "v4_migration.pre_cutover.v2",
        "status": "BLOCKED",
        "verification_status": verification_status,
        "blockers": blockers,
        **SAFETY,
    }


def build_preflight(evidence: Any) -> dict[str, Any]:
    """Accept only a current-evidence root and re-open all bound files."""
    if not isinstance(evidence, (str, Path)):
        return _blocked(
            [
                {"code": "HASH_BOUND_EVIDENCE_REQUIRED", "detail": None},
                {"code": "EXTERNAL_OWNER_PENDING", "detail": "No owner trust root is configured."},
            ],
            "UNVERIFIED_INPUT_REJECTED",
        )
    return build_current_preflight(str(evidence))


def build_current_preflight(evidence_root: str) -> dict[str, Any]:
    result = _build_current_preflight(evidence_root)
    return _blocked(
        list(result.get("blockers", []))
        + [
            {"code": "AUTHORIZATION_TRUST_ROOT_UNCONFIGURED", "detail": None},
            {"code": "EXTERNAL_OWNER_PENDING", "detail": None},
        ],
        str(result.get("verification_status", "CURRENT_EVIDENCE_UNBOUND")),
    )



def execute_authorized_cutover(
    *,
    cutover_id: str,
    candidate_sha: str,
    preflight_sha: str,
    binding_sha: str,
    authorization: dict[str, Any],
    adapters: dict[str, Any],
    payload: dict[str, Any],
    journal: Any | None = None,
) -> dict[str, Any]:
    validate_authorization(
        authorization,
        candidate_sha=candidate_sha,
        preflight_sha=preflight_sha,
        binding_sha=binding_sha,
        required_actions=ACTIONS,
    )
    raise PermissionError("CUTOVER_REMAINS_BLOCKED_AUTHORITY_UNBOUND")


def execute_dry_run(*, cutover_id: str, adapters: dict[str, Any] | None = None, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a pure simulation plan; the adapter argument is deliberately ignored."""
    if not isinstance(cutover_id, str) or not cutover_id.strip():
        raise ValueError("CUTOVER_ID_REQUIRED")
    proposed = [name for name in ACTIONS if name != "rollback"]
    return {
        "schema": "v4_migration.cutover_simulation.v1",
        "status": "SIMULATED",
        "cutover_id": cutover_id,
        "actions": proposed,
        "adapter_invocations": 0,
        "side_effects": False,
        "production_switch_executed": False,
        "authority_cutover_authorized": False,
        "simulation_only": True,
    }
