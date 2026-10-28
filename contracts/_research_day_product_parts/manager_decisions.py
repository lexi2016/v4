"""contracts.research_day_product: manager_decisions (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _validate_manager_research_decision_body(_v4_scope, /, value, *, candidate_ids, supply_envelope):
    """Validate the typed 22:00 manager delta used for a supply snapshot."""

    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(value) != _v4_global(_v4_scope, '_MANAGER_DECISION_FIELDS'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager research decision fields")
    if value.get("schema_version") != _v4_global(_v4_scope, 'MANAGER_DECISION_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager research decision schema")
    if value.get("phase") != _v4_global(_v4_scope, 'MANAGER_DECISION_PHASE'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager research decision phase")
    if value.get("decision_state") != _v4_global(_v4_scope, 'MANAGER_DECISION_STATE'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager research decision state")
    source_date = _v4_global(_v4_scope, '_selection_date')(value.get("source_date"), "decision source_date")
    target_date = _v4_global(_v4_scope, '_selection_date')(value.get("target_trade_date"), "decision target_trade_date")
    run_id = value.get("run_id")
    if not _v4_global(_v4_scope, 'isinstance')(run_id, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SELECTION_RUN_ID').fullmatch(run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager research decision run_id")
    generated = _v4_global(_v4_scope, '_selection_parsed_timestamp')(value.get("generated_at"), "decision generated_at")
    cutoff = _v4_global(_v4_scope, '_selection_parsed_timestamp')(value.get("cutoff_at"), "decision cutoff_at")
    if cutoff > generated:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision cutoff exceeds generated_at")
    source_start_hkt = _v4_global(_v4_scope, 'datetime').strptime(source_date, "%Y%m%d").replace(tzinfo=_v4_global(_v4_scope, '_SHANGHAI'))
    target_start_hkt = _v4_global(_v4_scope, 'datetime').strptime(target_date, "%Y%m%d").replace(tzinfo=_v4_global(_v4_scope, '_SHANGHAI'))
    generated_hkt = generated.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))
    if not source_start_hkt <= generated_hkt < target_start_hkt:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision generated_at source date mismatch")
    if cutoff.astimezone(_v4_global(_v4_scope, '_SHANGHAI')).strftime("%Y%m%d") != source_date:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision cutoff source date mismatch")
    if supply_envelope is not None:
        _v4_global(_v4_scope, 'validate_research_supply_envelope')(
            supply_envelope,
            expected_source_date=source_date,
            expected_target_trade_date=target_date,
            expected_run_id=run_id,
        )
        supply_generated = _v4_global(_v4_scope, '_selection_parsed_timestamp')(
            supply_envelope["generated_at"], "supply generated_at"
        )
        if generated < supply_generated:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision generated_at predates supply envelope")
        if cutoff < _v4_global(_v4_scope, '_selection_parsed_timestamp')(
            supply_envelope["cutoff_at"], "supply cutoff_at"
        ):
            raise _v4_global(_v4_scope, 'ValueError')("manager decision cutoff predates supply coverage")
    supply_ref = value.get("supply_ref")
    if not _v4_global(_v4_scope, 'isinstance')(supply_ref, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(supply_ref) != {
        "path",
        "raw_sha256",
        "frozen_payload_sha256",
        "run_id",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision supply reference is incomplete")
    if not _v4_global(_v4_scope, 'isinstance')(supply_ref.get("path"), _v4_global(_v4_scope, 'str')) or not supply_ref["path"]:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision supply path is missing")
    _v4_global(_v4_scope, '_selection_sha')(supply_ref.get("raw_sha256"), "manager decision supply raw SHA")
    _v4_global(_v4_scope, '_selection_sha')(
        supply_ref.get("frozen_payload_sha256"), "manager decision supply frozen SHA"
    )
    if supply_ref.get("run_id") != run_id:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision supply run binding mismatch")
    if supply_envelope is not None and supply_ref.get("frozen_payload_sha256") != supply_envelope.get("frozen_payload_sha256"):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision supply frozen SHA binding mismatch")
    baseline = value.get("baseline_ref")
    if baseline is not None:
        if not _v4_global(_v4_scope, 'isinstance')(baseline, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(baseline) != {"path", "raw_sha256"}:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline reference is invalid")
        if not _v4_global(_v4_scope, 'isinstance')(baseline.get("path"), _v4_global(_v4_scope, 'str')) or not baseline["path"]:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline path is missing")
        _v4_global(_v4_scope, '_selection_sha')(baseline.get("raw_sha256"), "manager decision baseline SHA")
    known = _v4_global(_v4_scope, 'set')(candidate_ids or [])
    core_ids = _v4_global(_v4_scope, '_validate_supply_action_rows')(
        value.get("core"), "core", candidate_ids=known or None, maximum=5
    )
    conditional_ids = _v4_global(_v4_scope, '_validate_supply_action_rows')(
        value.get("conditional"), "conditional", candidate_ids=known or None, maximum=5
    )
    if _v4_global(_v4_scope, 'set')(core_ids) & _v4_global(_v4_scope, 'set')(conditional_ids):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision core and conditional candidates overlap")
    decision_ids = _v4_global(_v4_scope, 'set')(core_ids) | _v4_global(_v4_scope, 'set')(conditional_ids)
    action_ids: set[str] = _v4_global(_v4_scope, 'set')()
    for field in ("KEEP", "ADD", "REMOVE"):
        selected = _v4_global(_v4_scope, '_validate_supply_action_rows')(
            value.get(field), field, candidate_ids=known or None
        )
        if action_ids.intersection(selected):
            raise _v4_global(_v4_scope, 'ValueError')("manager decision action candidate is duplicated")
        action_ids.update(selected)
    if baseline is None:
        if value["KEEP"] or value["REMOVE"]:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision baseline is required for KEEP/REMOVE")
        if _v4_global(_v4_scope, 'set')(row["candidate_id"] for row in value["ADD"]) != decision_ids:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision initial ADD set does not reconcile")
    qualification_refs = value.get("qualification_refs")
    if not _v4_global(_v4_scope, 'isinstance')(qualification_refs, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision qualification refs are invalid")
    qualified: set[str] = _v4_global(_v4_scope, 'set')()
    for ref in qualification_refs:
        if not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(ref) != {
            "candidate_id",
            "status",
            "path",
            "raw_sha256",
        }:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision qualification ref is invalid")
        candidate_id = ref.get("candidate_id")
        if not _v4_global(_v4_scope, 'isinstance')(candidate_id, _v4_global(_v4_scope, 'str')) or (known and candidate_id not in known):
            raise _v4_global(_v4_scope, 'ValueError')("manager decision qualification candidate is unknown")
        if candidate_id in qualified:
            raise _v4_global(_v4_scope, 'ValueError')("duplicate manager decision qualification candidate")
        qualified.add(candidate_id)
        if not _v4_global(_v4_scope, 'isinstance')(ref.get("status"), _v4_global(_v4_scope, 'str')) or not ref["status"].strip():
            raise _v4_global(_v4_scope, 'ValueError')("manager decision qualification status is invalid")
        if ref["status"] == "ELIGIBILITY_CANNOT_CONFIRM":
            if ref.get("path") is not None or ref.get("raw_sha256") is not None:
                raise _v4_global(_v4_scope, 'ValueError')("unconfirmed qualification cannot carry evidence")
        else:
            if not _v4_global(_v4_scope, 'isinstance')(ref.get("path"), _v4_global(_v4_scope, 'str')) or not ref["path"]:
                raise _v4_global(_v4_scope, 'ValueError')("confirmed qualification path is missing")
            _v4_global(_v4_scope, '_selection_sha')(ref.get("raw_sha256"), "manager qualification SHA")
    _v4_global(_v4_scope, '_validate_supply_safety')(value.get("safety"), "manager decision")
    return target_date


def __validate_manager_decision_projection_body(_v4_scope, /, value, *, source_date, target_trade_date, cutoff_at, expected_run_id, expected_generated_at):
    """Validate one candidate's typed manager projection without source mutation."""

    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(value) != _v4_global(_v4_scope, '_MANAGER_DECISION_PROJECTION_FIELDS'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager decision projection fields")
    if value.get("schema_version") != _v4_global(_v4_scope, 'MANAGER_DECISION_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager decision projection schema")
    if value.get("phase") != _v4_global(_v4_scope, 'MANAGER_DECISION_PHASE'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager decision projection phase")
    if value.get("decision_state") != _v4_global(_v4_scope, 'MANAGER_DECISION_STATE'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager decision projection state")
    if value.get("source_date") != source_date:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision projection source date mismatch")
    if value.get("target_trade_date") != target_trade_date:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision projection target date mismatch")
    run_id = value.get("run_id")
    if not _v4_global(_v4_scope, 'isinstance')(run_id, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SELECTION_RUN_ID').fullmatch(run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid manager decision projection run_id")
    if expected_run_id is not None and run_id != expected_run_id:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision projection run binding mismatch")
    generated_at = _v4_global(_v4_scope, '_selection_timestamp')(value.get("generated_at"), "manager decision projection generated_at")
    generated_value = _v4_global(_v4_scope, '_selection_parsed_timestamp')(
        generated_at,
        "manager decision projection generated_at",
    )
    cutoff_value = _v4_global(_v4_scope, '_selection_parsed_timestamp')(value.get("cutoff_at"), "manager decision projection cutoff_at")
    if cutoff_value > generated_value:
        raise _v4_global(_v4_scope, 'ValueError')(
            "manager decision projection cutoff must not be later than generated_at"
        )
    if cutoff_value != _v4_global(_v4_scope, '_selection_parsed_timestamp')(cutoff_at, "cutoff_at"):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision projection cutoff mismatch")
    if expected_generated_at is not None and generated_at != expected_generated_at:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision projection generated_at mismatch")
    if value.get("role") not in _v4_global(_v4_scope, '_MANAGER_DECISION_PROJECTION_ROLES'):
        raise _v4_global(_v4_scope, 'ValueError')("manager decision projection role is invalid")
    if _v4_global(_v4_scope, 'type')(value.get("order")) is not _v4_global(_v4_scope, 'int') or value["order"] < 1 or value["order"] > 5:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision projection order is invalid")
    if not _v4_global(_v4_scope, 'isinstance')(value.get("reason"), _v4_global(_v4_scope, 'str')) or not value["reason"].strip():
        raise _v4_global(_v4_scope, 'ValueError')("manager decision projection reason is invalid")


def _validate_manager_decision_projection_body(_v4_scope, /, value, *, source_date, target_trade_date, cutoff_at, expected_run_id, expected_generated_at):
    """Public validation entry point for Store/API candidate projections."""

    _v4_global(_v4_scope, '_validate_manager_decision_projection')(
        value,
        source_date=source_date,
        target_trade_date=target_trade_date,
        cutoff_at=cutoff_at,
        expected_run_id=expected_run_id,
        expected_generated_at=expected_generated_at,
    )
