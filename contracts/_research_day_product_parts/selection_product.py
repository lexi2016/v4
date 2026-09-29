"""contracts.research_day_product: selection_product (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _validate_selection_research_product_body(_v4_scope, /, payload, *, market_focus):
    """Validate the selection ledger without reading files or runtime state."""

    source_date, target_date, run_id = _validate_selection_product_header_phase(_v4_scope, payload)
    candidates, candidate_ids, supply_product, manager_decision_ref, formal, formal_authority = (
        _validate_selection_product_candidates_phase(
            _v4_scope, payload, market_focus, source_date, target_date
        )
    )
    snapshots = _validate_selection_product_snapshots_phase(
        _v4_scope, payload, candidates, candidate_ids, supply_product,
        manager_decision_ref, source_date, target_date,
    )
    _validate_selection_product_observations_phase(_v4_scope, payload, candidates, formal)
    _validate_selection_product_gaps_phase(
        _v4_scope, payload, snapshots, supply_product, formal, formal_authority, candidates
    )
    _validate_selection_product_routes_phase(
        _v4_scope, payload, formal, formal_authority, candidates, source_date, target_date
    )
    return target_date


def _validate_selection_product_header_phase(_v4_scope, /, payload):
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, '_SELECTION_PRODUCT_FIELDS').issubset(payload):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection research product fields")
    extra_fields = _v4_global(_v4_scope, 'set')(payload) - _v4_global(_v4_scope, '_SELECTION_PRODUCT_FIELDS')
    if not extra_fields.issubset(_v4_global(_v4_scope, '_SELECTION_OPTIONAL_FIELDS')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection research product fields")
    if payload.get("schema_version") != _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection research product schema")
    if payload.get("contract_id") != _v4_global(_v4_scope, 'SELECTION_CONTRACT_ID'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection research product contract")
    if payload.get("workflow_name") != _v4_global(_v4_scope, 'SELECTION_WORKFLOW_NAME'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection research product workflow")
    if payload.get("pass_signal") != _v4_global(_v4_scope, 'SELECTION_PASS_SIGNAL'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection research product pass signal")
    source_date = _v4_global(_v4_scope, '_selection_date')(payload.get("source_date"), "source_date")
    target_date = _v4_global(_v4_scope, '_selection_date')(payload.get("target_trade_date"), "target_trade_date")
    if payload.get("timezone") != _v4_global(_v4_scope, 'TIMEZONE'):
        raise _v4_global(_v4_scope, 'ValueError')("selection timezone must be Asia/Shanghai")
    _v4_global(_v4_scope, '_selection_timestamp')(payload.get("cutoff_at"), "cutoff_at")
    _v4_global(_v4_scope, '_selection_timestamp')(payload.get("generated_at"), "generated_at")
    run_id = payload.get("run_id")
    if not _v4_global(_v4_scope, 'isinstance')(run_id, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SELECTION_RUN_ID').fullmatch(run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection run_id")
    if payload.get("origin") not in _v4_global(_v4_scope, 'SELECTION_ORIGINS'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection origin")
    if payload.get("status") not in _v4_global(_v4_scope, 'SELECTION_STATUSES'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection research status")
    if payload.get("acceptance") not in {
        "EARLY_DRAFT_FROZEN_ONLY",
        _v4_global(_v4_scope, 'RESEARCH_SUPPLY_ACCEPTANCE'),
        "NOT_MATERIALIZED",
    }:
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection acceptance")
    for key, expected in _v4_global(_v4_scope, 'SAFETY_FLAGS').items():
        if payload.get(key) is not expected:
            raise _v4_global(_v4_scope, 'ValueError')(f"unsafe selection safety boundary: {key}")
    return source_date, target_date, run_id


def _validate_selection_product_candidates_phase(_v4_scope, /, payload, market_focus, source_date, target_date):
    candidates = payload.get("research_candidates")
    if not _v4_global(_v4_scope, 'isinstance')(candidates, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection research candidates")
    candidate_ids: list[str] = []
    for candidate in candidates:
        _v4_global(_v4_scope, '_validate_selection_candidate')(
            candidate,
            source_date=source_date,
            cutoff_at=_v4_global(_v4_scope, 'str')(payload.get("cutoff_at")),
        )
        candidate_id = _v4_global(_v4_scope, 'str')(candidate["candidate_id"])
        if candidate_id in candidate_ids:
            raise _v4_global(_v4_scope, 'ValueError')("duplicate selection candidate")
        candidate_ids.append(candidate_id)
    if candidate_ids != _v4_global(_v4_scope, 'sorted')(candidate_ids):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidates must be sorted by candidate_id")
    _v4_global(_v4_scope, 'validate_selection_market_scope')(payload, market_focus=market_focus)
    candidate_source_types = {
        ref.get("type")
        for candidate in candidates
        for ref in candidate.get("source_refs", [])
        if _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping'))
    }
    if _v4_global(_v4_scope, 'len')(candidate_source_types) > 1:
        raise _v4_global(_v4_scope, 'ValueError')("selection product source reference types are mixed")
    supply_product = candidate_source_types == {_v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE')}
    if supply_product and payload.get("acceptance") != _v4_global(_v4_scope, 'RESEARCH_SUPPLY_ACCEPTANCE'):
        raise _v4_global(_v4_scope, 'ValueError')("research supply product acceptance is invalid")
    if not supply_product and payload.get("acceptance") == _v4_global(_v4_scope, 'RESEARCH_SUPPLY_ACCEPTANCE'):
        raise _v4_global(_v4_scope, 'ValueError')("research supply acceptance lacks supply source")
    manager_decision_ref = payload.get("manager_decision_ref")
    if manager_decision_ref is not None:
        if not supply_product:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision reference requires research supply")
        if not _v4_global(_v4_scope, 'isinstance')(manager_decision_ref, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(manager_decision_ref) != {
            "path",
            "raw_sha256",
        }:
            raise _v4_global(_v4_scope, 'ValueError')("invalid manager decision reference")
        if not _v4_global(_v4_scope, 'isinstance')(manager_decision_ref.get("path"), _v4_global(_v4_scope, 'str')) or not manager_decision_ref["path"]:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision reference path is missing")
        _v4_global(_v4_scope, '_selection_sha')(manager_decision_ref.get("raw_sha256"), "manager decision raw SHA")

    formal = payload.get("formal_shortlist")
    if not _v4_global(_v4_scope, 'isinstance')(formal, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'str')) for item in formal):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection formal shortlist")
    if formal != _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(formal)) or _v4_global(_v4_scope, 'any')(item not in candidate_ids for item in formal):
        raise _v4_global(_v4_scope, 'ValueError')("selection formal shortlist identity mismatch")
    formal_authority = payload.get("formal_authority")
    _v4_global(_v4_scope, '_validate_selection_formal_authority')(
        formal_authority,
        target_trade_date=target_date,
    )
    return candidates, candidate_ids, supply_product, manager_decision_ref, formal, formal_authority


def _validate_selection_product_snapshots_phase(_v4_scope, /, payload, candidates, candidate_ids, supply_product, manager_decision_ref, source_date, target_date):
    snapshots = payload.get("snapshots")
    if not _v4_global(_v4_scope, 'isinstance')(snapshots, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(snapshots) != _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'SELECTION_PHASES')):
        raise _v4_global(_v4_scope, 'ValueError')("selection snapshots must cover every phase")
    for phase in _v4_global(_v4_scope, 'SELECTION_PHASES'):
        _v4_global(_v4_scope, '_validate_selection_snapshot')(snapshots[phase], phase=phase, target_trade_date=target_date)
        if _v4_global(_v4_scope, 'any')(candidate_id not in candidate_ids for candidate_id in snapshots[phase]["candidate_ids"]):
            raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} snapshot contains unknown candidate")

    snapshot_2200 = snapshots["2200"]
    snapshot_0830 = snapshots["0830"]
    snapshot_0935 = snapshots["0935"]
    snapshot_1620 = snapshots["1620"]
    candidate_id_set = _v4_global(_v4_scope, 'set')(candidate_ids)
    projected_candidates = [
        candidate
        for candidate in candidates
        if "manager_decision" in candidate
    ]
    if projected_candidates:
        if manager_decision_ref is None:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision projection requires a decision reference")
        if snapshot_2200["status"] != "READY":
            raise _v4_global(_v4_scope, 'ValueError')("manager decision projection requires a READY 2200 snapshot")
        if snapshot_2200["artifact_sha256"] != manager_decision_ref["raw_sha256"]:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision projection reference does not match 2200 snapshot")
        projected_ids = [candidate["candidate_id"] for candidate in projected_candidates]
        if projected_ids != _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(projected_ids)):
            raise _v4_global(_v4_scope, 'ValueError')("manager decision projection candidate ids are duplicated")
        if _v4_global(_v4_scope, 'sorted')(projected_ids) != snapshot_2200["candidate_ids"]:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision projection does not reconcile with 2200 snapshot")
        role_orders: dict[str, list[int]] = {role: [] for role in _v4_global(_v4_scope, '_MANAGER_DECISION_PROJECTION_ROLES')}
        for candidate in projected_candidates:
            projection = candidate["manager_decision"]
            _v4_global(_v4_scope, '_validate_manager_decision_projection')(
                projection,
                source_date=source_date,
                target_trade_date=target_date,
                cutoff_at=_v4_global(_v4_scope, 'str')(payload["cutoff_at"]),
                expected_run_id=_v4_global(_v4_scope, 'str')(snapshot_2200["run_id"]),
                expected_generated_at=_v4_global(_v4_scope, 'str')(snapshot_2200["event_at"]),
            )
            role_orders[projection["role"]].append(projection["order"])
        for role, orders in role_orders.items():
            if _v4_global(_v4_scope, 'sorted')(orders) != _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'range')(1, _v4_global(_v4_scope, 'len')(orders) + 1)):
                raise _v4_global(_v4_scope, 'ValueError')(f"manager decision projection {role} order is not contiguous")
    if supply_product:
        if snapshot_2200["status"] == "READY" and manager_decision_ref is None:
            raise _v4_global(_v4_scope, 'ValueError')("research supply 2200 requires a manager decision reference")
        if snapshot_2200["status"] != "READY" and manager_decision_ref is not None:
            raise _v4_global(_v4_scope, 'ValueError')("research supply manager decision lacks a 2200 snapshot")
    if snapshot_2200["status"] == "READY":
        if snapshot_2200["changes"]:
            raise _v4_global(_v4_scope, 'ValueError')("selection 2200 initial snapshot cannot carry changes")
    for phase, snapshot in (("0830", snapshot_0830), ("0935", snapshot_0935), ("1620", snapshot_1620)):
        if snapshot["status"] != "READY":
            continue
        if phase == "0830":
            if snapshot_2200["status"] != "READY":
                raise _v4_global(_v4_scope, 'ValueError')("selection 0830 requires a READY 2200 dependency")
            expected_ids = _v4_global(_v4_scope, '_selection_apply_changes')(
                snapshot["changes"],
                current_ids=_v4_global(_v4_scope, 'set')(snapshot_2200["candidate_ids"]),
                candidate_ids=candidate_id_set,
                phase=phase,
            )
            if _v4_global(_v4_scope, 'sorted')(expected_ids) != snapshot["candidate_ids"]:
                raise _v4_global(_v4_scope, 'ValueError')("selection 0830 changes do not reconcile with its candidate set")
        else:
            if snapshot_0830["status"] != "READY":
                raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} requires a READY 0830 dependency")
            if (
                snapshot.get("freeze_run_id") != snapshot_0830.get("run_id")
                or snapshot.get("freeze_snapshot_sha256") != snapshot_0830.get("snapshot_sha256")
            ):
                raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} freeze binding is invalid")
            expected_ids = _v4_global(_v4_scope, '_selection_apply_changes')(
                snapshot["changes"],
                current_ids=_v4_global(_v4_scope, 'set')(snapshot_0830["candidate_ids"]),
                candidate_ids=candidate_id_set,
                phase=phase,
            )
            # Intraday/outcome changes are append-only observations.  They
            # must never rewrite the frozen 08:30 membership.
            if _v4_global(_v4_scope, 'any')(
                change["action"] == "REMOVE"
                or (change["action"] == "KEEP" and change["candidate_id"] not in snapshot_0830["candidate_ids"])
                for change in snapshot["changes"]
            ):
                raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} changes rewrite the 0830 freeze")
            if _v4_global(_v4_scope, 'any')(
                change["action"] == "ADD" and change["candidate_id"] in snapshot_0830["candidate_ids"]
                for change in snapshot["changes"]
            ):
                raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} changes rewrite the 0830 freeze")
            if not _v4_global(_v4_scope, 'set')(snapshot["candidate_ids"]) == _v4_global(_v4_scope, 'set')(snapshot_0830["candidate_ids"]):
                raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} changed the 0830 frozen membership")

    if snapshot_0935["status"] == "READY":
        matching_observation = _v4_global(_v4_scope, 'any')(
            _v4_global(_v4_scope, 'isinstance')(observation, _v4_global(_v4_scope, 'Mapping'))
            and observation.get("kind") == "APPEND_ONLY"
            and observation.get("freeze_run_id") == snapshot_0830["run_id"]
            and observation.get("freeze_snapshot_sha256") == snapshot_0830["snapshot_sha256"]
            for observation in payload.get("intraday_observations", [])
        )
        if not matching_observation:
            raise _v4_global(_v4_scope, 'ValueError')("selection 0935 requires an append-only observation bound to 0830")
    if snapshot_1620["status"] == "READY":
        matching_outcome = _v4_global(_v4_scope, 'any')(
            _v4_global(_v4_scope, 'isinstance')(outcome, _v4_global(_v4_scope, 'Mapping'))
            and outcome.get("kind") == "OUTCOME_REFERENCE"
            and outcome.get("freeze_run_id") == snapshot_0830["run_id"]
            and outcome.get("freeze_snapshot_sha256") == snapshot_0830["snapshot_sha256"]
            for outcome in payload.get("outcomes", [])
        )
        if not matching_outcome:
            raise _v4_global(_v4_scope, 'ValueError')("selection 1620 requires an outcome bound to 0830")
    return snapshots


def _validate_selection_product_observations_phase(_v4_scope, /, payload, candidates, formal):
    for field in ("intraday_observations", "outcomes"):
        if not _v4_global(_v4_scope, 'isinstance')(payload.get(field), _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')) for item in payload[field]):
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection {field}")
    for observation in payload["intraday_observations"]:
        if observation.get("kind") != "APPEND_ONLY":
            raise _v4_global(_v4_scope, 'ValueError')("selection intraday observation must be APPEND_ONLY")
        if "observed_at" in observation:
            _v4_global(_v4_scope, '_selection_timestamp')(observation.get("observed_at"), "intraday observed_at")
    for outcome in payload["outcomes"]:
        if outcome.get("kind") != "OUTCOME_REFERENCE":
            raise _v4_global(_v4_scope, 'ValueError')("selection outcome kind is invalid")
        if "observed_at" in outcome:
            _v4_global(_v4_scope, '_selection_timestamp')(outcome.get("observed_at"), "outcome observed_at")
    counts = payload.get("counts")
    if not _v4_global(_v4_scope, 'isinstance')(counts, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(counts) != _v4_global(_v4_scope, '_SELECTION_COUNTS_FIELDS'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection counts")
    for key, value in counts.items():
        if _v4_global(_v4_scope, 'type')(value) is not _v4_global(_v4_scope, 'int') or value < 0:
            raise _v4_global(_v4_scope, 'ValueError')(f"invalid selection count {key}")
    expected_counts = {
        "research_candidates": _v4_global(_v4_scope, 'len')(candidates),
        "formal_shortlist": _v4_global(_v4_scope, 'len')(formal),
        "snapshots": _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'SELECTION_PHASES')),
        "intraday_observations": _v4_global(_v4_scope, 'len')(payload["intraday_observations"]),
        "outcomes": _v4_global(_v4_scope, 'len')(payload["outcomes"]),
    }
    if _v4_global(_v4_scope, 'dict')(counts) != expected_counts:
        raise _v4_global(_v4_scope, 'ValueError')("selection counts do not reconcile")


def _validate_selection_product_gaps_phase(_v4_scope, /, payload, snapshots, supply_product, formal, formal_authority, candidates):
    expected_gaps: set[str] = _v4_global(_v4_scope, 'set')()
    for phase in _v4_global(_v4_scope, 'SELECTION_PHASES'):
        if snapshots[phase]["status"] != "READY":
            if supply_product and phase == "2200":
                expected_gaps.add("SUPPLY_2200_DECISION_NOT_MATERIALIZED")
            else:
                expected_gaps.add(f"SNAPSHOT_{phase}_NOT_MATERIALIZED")
    if not formal or formal_authority.get("status") != "READY":
        expected_gaps.add("FORMAL_AUTHORITY_NOT_MATERIALIZED")
    if _v4_global(_v4_scope, 'any')(candidate["pit_status"] != "READY" for candidate in candidates):
        expected_gaps.add("CANDIDATE_PIT_NOT_CONFIRMED")
    if _v4_global(_v4_scope, 'set')(payload.get("cannot_confirm", [])) != expected_gaps:
        raise _v4_global(_v4_scope, 'ValueError')("selection cannot_confirm gaps do not reconcile")
    expected_status = (
        "NOT_MATERIALIZED"
        if not candidates
        else (
            _v4_global(_v4_scope, 'RESEARCH_SUPPLY_STATUS')
            if supply_product
            and not _v4_global(_v4_scope, 'any')(snapshots[phase]["status"] == "READY" for phase in _v4_global(_v4_scope, 'SELECTION_PHASES'))
            else (
                "EARLY_DRAFT_IMPORTED"
                if not _v4_global(_v4_scope, 'any')(snapshots[phase]["status"] == "READY" for phase in _v4_global(_v4_scope, 'SELECTION_PHASES'))
                else ("READY_WITH_DECLARED_GAPS" if expected_gaps else "READY")
            )
        )
    )
    if payload.get("status") != expected_status:
        raise _v4_global(_v4_scope, 'ValueError')("selection status does not reconcile with materialized phases and gaps")
    expected_first_failed = _v4_global(_v4_scope, 'min')(expected_gaps) if expected_gaps else None
    if payload.get("first_failed_layer") != expected_first_failed:
        raise _v4_global(_v4_scope, 'ValueError')("selection first_failed_layer does not reconcile")


def _validate_selection_product_routes_phase(_v4_scope, /, payload, formal, formal_authority, candidates, source_date, target_date):
    route_status = payload.get("route_status")
    if not _v4_global(_v4_scope, 'isinstance')(route_status, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(route_status) != {"R1", "R2", "R6", "GEMINI"}:
        raise _v4_global(_v4_scope, 'ValueError')("selection route status must separate R1, R2, R6 and Gemini")
    if _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value for value in route_status.values()):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection route status value")
    if route_status.get("R6") == "GEMINI_DISCOVERY_UNVERIFIED":
        raise _v4_global(_v4_scope, 'ValueError')("selection R6 cannot alias Gemini discovery")
    if route_status.get("GEMINI") not in {"UNVERIFIED", "NOT_MATERIALIZED"}:
        raise _v4_global(_v4_scope, 'ValueError')("Gemini route status must remain unverified")
    if payload.get("gemini_status") not in {"UNVERIFIED", "NOT_MATERIALIZED"}:
        raise _v4_global(_v4_scope, 'ValueError')("Gemini must remain UNVERIFIED or NOT_MATERIALIZED")
    if payload.get("gemini_status") != route_status.get("GEMINI"):
        raise _v4_global(_v4_scope, 'ValueError')("Gemini route and product status do not reconcile")
    if formal:
        authority = formal_authority
        if authority.get("status") != "READY":
            raise _v4_global(_v4_scope, 'ValueError')("selection formal shortlist lacks READY authority")
        candidates_by_id = {
            candidate["candidate_id"]: candidate for candidate in candidates
        }
        for candidate_id in formal:
            candidate = candidates_by_id[candidate_id]
            if candidate.get("eligibility") != "ELIGIBLE" or candidate.get("pit_status") != "READY":
                raise _v4_global(_v4_scope, 'ValueError')("selection formal shortlist candidate gate is incomplete")
        _v4_global(_v4_scope, '_validate_selection_formal_refs')(
            authority,
            source_date=source_date,
            target_trade_date=target_date,
            candidate_ids=formal,
        )

    refs = payload.get("source_refs")
    if not _v4_global(_v4_scope, 'isinstance')(refs, _v4_global(_v4_scope, 'list')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection source refs")
    for ref in refs:
        _v4_global(_v4_scope, '_validate_selection_source_ref')(ref, source_date=source_date)
    if refs != [ref for candidate in candidates for ref in candidate["source_refs"]]:
        raise _v4_global(_v4_scope, 'ValueError')("selection source refs do not reconcile with candidates")

    first_failed = payload.get("first_failed_layer")
    if first_failed is not None and (not _v4_global(_v4_scope, 'isinstance')(first_failed, _v4_global(_v4_scope, 'str')) or not first_failed):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection first_failed_layer")
    _v4_global(_v4_scope, '_selection_strings')(payload.get("cannot_confirm"), "cannot_confirm")
    if not candidates and payload.get("status") != "NOT_MATERIALIZED":
        raise _v4_global(_v4_scope, 'ValueError')("empty selection ledger must be NOT_MATERIALIZED")
    if candidates and payload.get("status") == "NOT_MATERIALIZED":
        raise _v4_global(_v4_scope, 'ValueError')("selection ledger with candidates cannot be NOT_MATERIALIZED")

