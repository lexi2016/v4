"""domains.research_day_product: formal_refs (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __selection_formal_authority_body(_v4_scope, /, value, *, target_trade_date):
    default = {
        "status": "NOT_MATERIALIZED",
        "target_trade_date": target_trade_date,
        "pit_status": "CANNOT_CONFIRM",
        "selector_status": "CANNOT_CONFIRM",
        "research_evidence": False,
        "manager_decision": False,
        "source_sha256": None,
        "evidence_refs": [],
        "manager_decision_ref": None,
    }
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        return default
    result = {**default, **_v4_global(_v4_scope, 'dict')(value)}
    if result.get("target_trade_date") != target_trade_date:
        result["status"] = "STALE"
        result["target_trade_date"] = target_trade_date
        result["pit_status"] = "CANNOT_CONFIRM"
        result["selector_status"] = "CANNOT_CONFIRM"
        result["research_evidence"] = False
        result["manager_decision"] = False
        result["source_sha256"] = None
    if result.get("status") == "READY" and not (
        result.get("pit_status") == "READY"
        and result.get("selector_status") == "READY"
        and result.get("research_evidence") is True
        and result.get("manager_decision") is True
        and _v4_global(_v4_scope, '_selection_hash_text')(result.get("source_sha256"))
        and _v4_global(_v4_scope, 'isinstance')(result.get("evidence_refs"), _v4_global(_v4_scope, 'list'))
        and _v4_global(_v4_scope, 'bool')(result.get("evidence_refs"))
        and _v4_global(_v4_scope, 'isinstance')(result.get("manager_decision_ref"), _v4_global(_v4_scope, 'Mapping'))
    ):
        result["status"] = "CANNOT_CONFIRM"
    return result


def __selection_formal_refs_bind_candidates_body(_v4_scope, /, authority, candidate_ids):
    """Check the pure shape of candidate proof before requesting promotion."""

    if not candidate_ids:
        return False
    refs = _v4_global(_v4_scope, 'list')(authority.get("evidence_refs") or [])
    decision = authority.get("manager_decision_ref")
    if not refs or not _v4_global(_v4_scope, 'isinstance')(decision, _v4_global(_v4_scope, 'Mapping')):
        return False
    for ref in [*refs, decision]:
        bindings = ref.get("candidate_bindings")
        if not _v4_global(_v4_scope, 'isinstance')(bindings, _v4_global(_v4_scope, 'list')) or [
            binding.get("candidate_id")
            for binding in bindings
            if _v4_global(_v4_scope, 'isinstance')(binding, _v4_global(_v4_scope, 'Mapping'))
        ] != candidate_ids:
            return False
        for binding in bindings:
            if not _v4_global(_v4_scope, 'isinstance')(binding, _v4_global(_v4_scope, 'Mapping')):
                return False
            if (
                binding.get("eligibility") != "ELIGIBLE"
                or binding.get("pit_status") != "READY"
                or not _v4_global(_v4_scope, 'isinstance')(binding.get("source_refs"), _v4_global(_v4_scope, 'list'))
                or not binding["source_refs"]
            ):
                return False
    return True
