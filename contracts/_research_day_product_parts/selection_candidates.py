"""contracts.research_day_product: selection_candidates (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_selection_candidate_body(_v4_scope, /, value, *, source_date, cutoff_at):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, '_SELECTION_CANDIDATE_FIELDS').issubset(value):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection candidate fields")
    if not (_v4_global(_v4_scope, 'set')(value) - _v4_global(_v4_scope, '_SELECTION_CANDIDATE_FIELDS')).issubset(
        _v4_global(_v4_scope, '_SELECTION_CANDIDATE_OPTIONAL_FIELDS')
    ):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection candidate fields")
    refs = value.get("source_refs")
    if not _v4_global(_v4_scope, 'isinstance')(refs, _v4_global(_v4_scope, 'list')) or not refs:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source refs are missing")
    source_types = {
        ref.get("type") for ref in refs if _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping'))
    }
    if _v4_global(_v4_scope, 'len')(source_types) != 1:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source reference types are mixed")
    supply_source = source_types == {_v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE')}
    required_text = (
        "candidate_id",
        "event_stock_link_id",
        "market",
        "normalized_code",
        "entity_id",
        "event_id",
        "acceptance",
        "eligibility",
        "pit_status",
        "research_status",
        "recommendation_status",
    )
    if _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(value.get(field), _v4_global(_v4_scope, 'str')) or not value[field] for field in required_text):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate identity or status is missing")
    if value.get("research_status") != "RESEARCH_ONLY" or value.get("recommendation_status") != "RESEARCH_ONLY":
        raise _v4_global(_v4_scope, 'ValueError')("unsafe selection candidate recommendation")
    expected_acceptance = (
        _v4_global(_v4_scope, 'RESEARCH_SUPPLY_ACCEPTANCE') if supply_source else "EARLY_DRAFT_FROZEN_ONLY"
    )
    if value.get("acceptance") != expected_acceptance:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate acceptance is not frozen-draft only")
    entity_id = _v4_global(_v4_scope, 'unicodedata').normalize("NFKC", value["entity_id"].strip())
    if "." not in entity_id:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate entity identity is invalid")
    code, market = entity_id.rsplit(".", 1)
    expected_candidate_id = f"{market.upper()}.{code.upper()}|{entity_id}"
    if value.get("candidate_id") != expected_candidate_id:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate identity does not reconcile")
    if value.get("event_stock_link_id") != f"{value['event_id']}|{expected_candidate_id}":
        raise _v4_global(_v4_scope, 'ValueError')("selection event-stock link does not reconcile")
    if value.get("eligibility") not in {"ELIGIBILITY_CANNOT_CONFIRM", "ELIGIBLE"}:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate eligibility is invalid")
    if value.get("pit_status") not in {"READY", "PIT_FAILED", "CANNOT_CONFIRM"}:
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection candidate PIT status")
    for field in (
        "bucket",
        "catalyst",
        "counterevidence",
        "invalidation",
        "evidence_level",
        "financial_bridge",
        "consensus",
        "overnight_pending",
        "source_status",
        "published_at",
        "source_time",
    ):
        if not _v4_global(_v4_scope, 'isinstance')(value.get(field), _v4_global(_v4_scope, 'str')):
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection candidate {field}")
    if not _v4_global(_v4_scope, 'isinstance')(value.get("source_metadata"), _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate source metadata is missing")
    _v4_global(_v4_scope, '_selection_timestamp')(value.get("source_time"), "candidate source_time")
    published_aware = value.get("published_at_aware")
    if published_aware is not None:
        _v4_global(_v4_scope, '_selection_timestamp')(published_aware, "candidate published_at_aware")
    if value.get("pit_status") == "READY":
        cutoff_value = _v4_global(_v4_scope, '_selection_parsed_timestamp')(cutoff_at, "cutoff_at")
        if published_aware is None:
            raise _v4_global(_v4_scope, 'ValueError')("selection candidate PIT READY lacks published timestamp")
        published_value = _v4_global(_v4_scope, '_selection_parsed_timestamp')(
            published_aware,
            "candidate published_at_aware",
        )
        source_value = _v4_global(_v4_scope, '_selection_parsed_timestamp')(
            value.get("source_time"), "candidate source_time"
        )
        if published_value > cutoff_value or (
            not supply_source and source_value > cutoff_value
        ):
            raise _v4_global(_v4_scope, 'ValueError')("selection candidate PIT READY exceeds cutoff")
    route_status = value.get("route_status")
    if not _v4_global(_v4_scope, 'isinstance')(route_status, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(route_status) != {"R1", "R6"}:
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate route status must separate R1 and R6")
    if route_status.get("R6") == "GEMINI_DISCOVERY_UNVERIFIED":
        raise _v4_global(_v4_scope, 'ValueError')("selection R6 cannot alias Gemini discovery")
    if value.get("gemini_status") not in {"UNVERIFIED", "NOT_MATERIALIZED"}:
        raise _v4_global(_v4_scope, 'ValueError')("Gemini selection status must remain unverified")
    for ref in refs:
        _v4_global(_v4_scope, '_validate_selection_source_ref')(ref, source_date=source_date)


def __validate_selection_snapshot_body(_v4_scope, /, value, *, phase, target_trade_date):
    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(value) != _v4_global(_v4_scope, '_SELECTION_SNAPSHOT_FIELDS'):
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection {phase} snapshot fields")
    if value.get("phase") != phase or value.get("status") not in _v4_global(_v4_scope, 'SELECTION_SNAPSHOT_STATUSES'):
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection {phase} snapshot identity")
    _v4_global(_v4_scope, '_selection_strings')(value.get("candidate_ids"), f"{phase} candidate_ids")
    if not _v4_global(_v4_scope, 'isinstance')(value.get("changes"), _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')) for item in value["changes"]):
        raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection {phase} changes")
    status = value["status"]
    if status == "NOT_MATERIALIZED" or status == "CANNOT_CONFIRM":
        if _v4_global(_v4_scope, 'any')(value.get(field) is not None for field in ("run_id", "event_at", "artifact_sha256", "freeze_run_id", "freeze_snapshot_sha256", "snapshot_sha256")):
            raise _v4_global(_v4_scope, 'ValueError')(f"unmaterialized selection {phase} snapshot has identity")
        if value.get("candidate_ids") or value.get("changes"):
            raise _v4_global(_v4_scope, 'ValueError')(f"unmaterialized selection {phase} snapshot has rows")
        return
    run_id = value.get("run_id")
    if not _v4_global(_v4_scope, 'isinstance')(run_id, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SELECTION_RUN_ID').fullmatch(run_id):
        raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} snapshot run_id is invalid")
    _v4_global(_v4_scope, '_selection_timestamp')(value.get("event_at"), f"{phase} event_at")
    _v4_global(_v4_scope, '_selection_sha')(value.get("artifact_sha256"), f"{phase} artifact_sha256")
    _v4_global(_v4_scope, '_selection_sha')(value.get("snapshot_sha256"), f"{phase} snapshot_sha256")
    snapshot_body = {
        key: item for key, item in value.items() if key != "snapshot_sha256"
    }
    if value.get("snapshot_sha256") != _v4_global(_v4_scope, '_selection_canonical_sha')(snapshot_body):
        raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} snapshot SHA mismatch")
    if phase in {"0935", "1620"}:
        if not _v4_global(_v4_scope, 'isinstance')(value.get("freeze_run_id"), _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SELECTION_RUN_ID').fullmatch(value["freeze_run_id"]):
            raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} must reference an 0830 run")
        _v4_global(_v4_scope, '_selection_sha')(value.get("freeze_snapshot_sha256"), f"{phase} freeze_snapshot_sha256")
    elif value.get("freeze_run_id") is not None or value.get("freeze_snapshot_sha256") is not None:
        raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} cannot carry a freeze reference")


def __selection_apply_changes_body(_v4_scope, /, changes, *, current_ids, candidate_ids, phase):
    """Validate deterministic KEEP/ADD/REMOVE semantics and return the set."""

    if not _v4_global(_v4_scope, 'isinstance')(changes, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} changes are invalid")
    working = _v4_global(_v4_scope, 'set')(current_ids)
    seen: set[str] = _v4_global(_v4_scope, 'set')()
    for change in changes:
        if not _v4_global(_v4_scope, 'isinstance')(change, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(change) != {"action", "candidate_id"}:
            raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} change fields are invalid")
        action = change.get("action")
        candidate_id = change.get("candidate_id")
        if action not in {"KEEP", "ADD", "REMOVE"} or not _v4_global(_v4_scope, 'isinstance')(candidate_id, _v4_global(_v4_scope, 'str')):
            raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} change operation is invalid")
        if candidate_id not in candidate_ids:
            raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} change candidate is unknown")
        if candidate_id in seen:
            raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} change candidate is duplicated")
        seen.add(candidate_id)
        if action == "KEEP" and candidate_id not in working:
            raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} KEEP candidate is not in the current set")
        if action == "ADD":
            if candidate_id in working:
                raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} ADD candidate is already in the current set")
            working.add(candidate_id)
        if action == "REMOVE":
            if candidate_id not in working:
                raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} REMOVE candidate is not in the current set")
            working.remove(candidate_id)
    return working
