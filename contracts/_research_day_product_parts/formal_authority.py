"""contracts.research_day_product: formal_authority (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_selection_formal_authority_body(_v4_scope, /, value, *, target_trade_date):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(value) != _v4_global(_v4_scope, '_SELECTION_FORMAL_AUTHORITY_FIELDS'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection formal authority fields")
    if value.get("status") not in {"READY", "NOT_MATERIALIZED", "STALE", "CANNOT_CONFIRM"}:
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection formal authority status")
    if value.get("target_trade_date") != target_trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("selection formal authority target date mismatch")
    for field in ("pit_status", "selector_status"):
        if not _v4_global(_v4_scope, 'isinstance')(value.get(field), _v4_global(_v4_scope, 'str')):
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection formal authority {field}")
    if _v4_global(_v4_scope, 'type')(value.get("research_evidence")) is not _v4_global(_v4_scope, 'bool') or _v4_global(_v4_scope, 'type')(value.get("manager_decision")) is not _v4_global(_v4_scope, 'bool'):
        raise _v4_global(_v4_scope, 'ValueError')("selection formal authority gates must be boolean")
    evidence_refs = value.get("evidence_refs")
    if not _v4_global(_v4_scope, 'isinstance')(evidence_refs, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) for ref in evidence_refs):
        raise _v4_global(_v4_scope, 'ValueError')("selection formal evidence refs are invalid")
    decision_ref = value.get("manager_decision_ref")
    if decision_ref is not None and not _v4_global(_v4_scope, 'isinstance')(decision_ref, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("selection manager decision ref is invalid")
    if value.get("status") == "READY":
        if value.get("pit_status") != "READY" or value.get("selector_status") != "READY" or not value["research_evidence"] or not value["manager_decision"]:
            raise _v4_global(_v4_scope, 'ValueError')("selection formal authority READY gate is incomplete")
        if not evidence_refs or decision_ref is None:
            raise _v4_global(_v4_scope, 'ValueError')("selection formal authority references are incomplete")
        for ref in evidence_refs:
            if not _v4_global(_v4_scope, 'isinstance')(ref.get("path"), _v4_global(_v4_scope, 'str')) or not ref["path"]:
                raise _v4_global(_v4_scope, 'ValueError')("selection formal evidence ref path is missing")
            _v4_global(_v4_scope, '_selection_sha')(ref.get("sha256"), "formal evidence SHA")
        if not _v4_global(_v4_scope, 'isinstance')(decision_ref.get("path"), _v4_global(_v4_scope, 'str')) or not decision_ref["path"]:
            raise _v4_global(_v4_scope, 'ValueError')("selection manager decision ref path is missing")
        _v4_global(_v4_scope, '_selection_sha')(decision_ref.get("sha256"), "manager decision SHA")
        _v4_global(_v4_scope, '_selection_sha')(value.get("source_sha256"), "formal authority source_sha256")
    elif value.get("source_sha256") is not None:
        _v4_global(_v4_scope, '_selection_sha')(value.get("source_sha256"), "formal authority source_sha256")


def __validate_selection_formal_refs_body(_v4_scope, /, authority, *, source_date, target_trade_date, candidate_ids):
    """Validate the immutable, typed references behind a formal shortlist."""

    if not candidate_ids:
        return
    expected_source_sha = authority.get("source_sha256")
    evidence_refs = authority.get("evidence_refs")
    decision_ref = authority.get("manager_decision_ref")
    authority_run_ids: set[str] = _v4_global(_v4_scope, 'set')()
    for ref in evidence_refs:
        required = {
            "schema_version",
            "type",
            "path",
            "sha256",
            "source_sha256",
            "source_date",
            "target_trade_date",
            "run_id",
            "candidate_ids",
            "candidate_bindings",
            "status",
            "pit_status",
        }
        if not required.issubset(ref):
            raise _v4_global(_v4_scope, 'ValueError')("selection formal evidence reference schema is incomplete")
        if ref.get("schema_version") != "v3_5.selection_formal_evidence.v1" or ref.get("type") != "EXACT_DATE_PIT":
            raise _v4_global(_v4_scope, 'ValueError')("selection formal evidence reference type is invalid")
        if ref.get("source_sha256") != expected_source_sha:
            raise _v4_global(_v4_scope, 'ValueError')("selection formal evidence source binding mismatch")
        if (
            ref.get("source_date") != source_date
            or ref.get("target_trade_date") != target_trade_date
            or not _v4_global(_v4_scope, 'isinstance')(ref.get("run_id"), _v4_global(_v4_scope, 'str'))
            or not _v4_global(_v4_scope, '_SELECTION_RUN_ID').fullmatch(ref["run_id"])
        ):
            raise _v4_global(_v4_scope, 'ValueError')("selection formal evidence date/run binding mismatch")
        authority_run_ids.add(ref["run_id"])
        if ref.get("candidate_ids") != candidate_ids or ref.get("status") != "READY" or ref.get("pit_status") != "READY":
            raise _v4_global(_v4_scope, 'ValueError')("selection formal evidence candidate binding mismatch")
        _v4_global(_v4_scope, '_validate_selection_proof_bindings')(
            ref,
            candidate_ids=candidate_ids,
            source_date=source_date,
            label="selection formal evidence",
        )
    required_decision = {
        "schema_version",
        "type",
        "path",
        "sha256",
        "source_sha256",
        "source_date",
        "target_trade_date",
        "run_id",
        "candidate_ids",
        "candidate_bindings",
        "decision",
    }
    if not _v4_global(_v4_scope, 'isinstance')(decision_ref, _v4_global(_v4_scope, 'Mapping')) or not required_decision.issubset(decision_ref):
        raise _v4_global(_v4_scope, 'ValueError')("selection manager decision reference schema is incomplete")
    if decision_ref.get("schema_version") != "v3_5.selection_manager_decision.v1" or decision_ref.get("type") != "MANAGER_DECISION":
        raise _v4_global(_v4_scope, 'ValueError')("selection manager decision reference type is invalid")
    if decision_ref.get("source_sha256") != expected_source_sha:
        raise _v4_global(_v4_scope, 'ValueError')("selection manager decision source binding mismatch")
    if (
        decision_ref.get("source_date") != source_date
        or decision_ref.get("target_trade_date") != target_trade_date
        or not _v4_global(_v4_scope, 'isinstance')(decision_ref.get("run_id"), _v4_global(_v4_scope, 'str'))
        or not _v4_global(_v4_scope, '_SELECTION_RUN_ID').fullmatch(decision_ref["run_id"])
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection manager decision date/run binding mismatch")
    authority_run_ids.add(decision_ref["run_id"])
    if decision_ref.get("candidate_ids") != candidate_ids or decision_ref.get("decision") is not True:
        raise _v4_global(_v4_scope, 'ValueError')("selection manager decision candidate binding mismatch")
    _v4_global(_v4_scope, '_validate_selection_proof_bindings')(
        decision_ref,
        candidate_ids=candidate_ids,
        source_date=source_date,
        label="selection manager decision",
    )
    if _v4_global(_v4_scope, 'len')(authority_run_ids) != 1:
        raise _v4_global(_v4_scope, 'ValueError')("selection formal references use conflicting authority runs")


def __validate_selection_proof_bindings_body(_v4_scope, /, value, *, candidate_ids, source_date, label):
    bindings = value.get("candidate_bindings")
    if not _v4_global(_v4_scope, 'isinstance')(bindings, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(bindings) != _v4_global(_v4_scope, 'len')(candidate_ids):
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding is incomplete")
    seen: list[str] = []
    for binding in bindings:
        if not _v4_global(_v4_scope, 'isinstance')(binding, _v4_global(_v4_scope, 'Mapping')) or not {
            "candidate_id",
            "eligibility",
            "pit_status",
            "source_refs",
        }.issubset(binding):
            raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding is invalid")
        candidate_id = binding.get("candidate_id")
        if candidate_id not in candidate_ids or candidate_id in seen:
            raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding identity is invalid")
        if binding.get("eligibility") != "ELIGIBLE" or binding.get("pit_status") != "READY":
            raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source proof status is incomplete")
        refs = binding.get("source_refs")
        if not _v4_global(_v4_scope, 'isinstance')(refs, _v4_global(_v4_scope, 'list')) or not refs:
            raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding refs are missing")
        for ref in refs:
            _v4_global(_v4_scope, '_validate_selection_source_ref')(ref, source_date=source_date)
        seen.append(candidate_id)
    if seen != candidate_ids:
        raise _v4_global(_v4_scope, 'ValueError')(f"{label} candidate source binding order mismatch")
