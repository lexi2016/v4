"""domains.research_day_product: selection_assembly (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _build_selection_research_product_body(_v4_scope, /, source_date, target_trade_date, *, source_cards, source_envelope, source_ref, generated_at, cutoff_at, run_id, origin, route_status, snapshots, intraday_observations, outcomes, formal_authority, formal_candidate_ids, manager_decision, manager_decision_ref):
    """Build a deterministic ledger from explicitly supplied research cards."""

    source_date, target_trade_date, supply_envelope, source_cards = (
        _prepare_selection_source_cards_phase(
            _v4_scope, source_date, target_trade_date, source_cards, source_envelope,
            source_ref, cutoff_at, run_id, snapshots, manager_decision,
            manager_decision_ref,
        )
    )
    route, candidates, candidate_ids, source_refs = _build_selection_candidates_phase(
        _v4_scope, source_date, cutoff_at, source_cards, supply_envelope,
        route_status, manager_decision, manager_decision_ref,
    )
    snapshots = _project_selection_manager_decision_phase(
        _v4_scope, candidates, candidate_ids, supply_envelope, cutoff_at,
        manager_decision, manager_decision_ref, snapshots,
    )
    (
        snapshot_map, observations, outcome_rows, formal, formal_ids,
        cannot_confirm, status, acceptance, first_failed,
    ) = _project_selection_snapshot_state_phase(
        _v4_scope, target_trade_date, candidates, candidate_ids, supply_envelope,
        snapshots, intraday_observations, outcomes, formal_authority,
        formal_candidate_ids,
    )
    return _assemble_selection_product_phase(
        _v4_scope, source_date, target_trade_date, cutoff_at, generated_at,
        run_id, origin, route, candidates, formal_ids, snapshot_map, observations,
        outcome_rows, status, acceptance, formal, source_refs, first_failed,
        cannot_confirm, manager_decision_ref,
    )


def _prepare_selection_source_cards_phase(_v4_scope, /, source_date, target_trade_date, source_cards, source_envelope, source_ref, cutoff_at, run_id, snapshots, manager_decision, manager_decision_ref):
    source_date = _v4_global(_v4_scope, '_date')(source_date)
    target_trade_date = _v4_global(_v4_scope, '_date')(target_trade_date)
    supply_envelope = (
        source_envelope
        if _v4_global(_v4_scope, 'isinstance')(source_envelope, _v4_global(_v4_scope, 'Mapping'))
        and source_envelope.get("type") == _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE')
        else None
    )
    if _v4_global(_v4_scope, 'isinstance')(source_envelope, _v4_global(_v4_scope, 'Mapping')) and source_envelope.get("type") not in {
        None,
        _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE'),
    }:
        raise _v4_global(_v4_scope, 'ValueError')("selection source envelope type is unsupported")
    if supply_envelope is not None:
        _v4_global(_v4_scope, 'validate_research_supply_envelope')(
            supply_envelope,
            expected_source_date=source_date,
            expected_target_trade_date=target_trade_date,
        )
        supply_run_id = _v4_global(_v4_scope, 'str')(supply_envelope.get("run_id") or "")
        supplied_snapshots = snapshots if _v4_global(_v4_scope, 'isinstance')(snapshots, _v4_global(_v4_scope, 'Mapping')) else {}
        ready_later = [
            phase
            for phase in ("0830", "0935", "1620")
            if _v4_global(_v4_scope, 'isinstance')(supplied_snapshots.get(phase), _v4_global(_v4_scope, 'Mapping'))
            and supplied_snapshots[phase].get("status") == "READY"
        ]
        expected_run_id = (
            _v4_global(_v4_scope, 'str')(supplied_snapshots[ready_later[-1]].get("run_id") or "")
            if ready_later
            else supply_run_id
        )
        if run_id != expected_run_id:
            raise _v4_global(_v4_scope, 'ValueError')("research supply product run must bind to source or latest phase")
        if manager_decision is None and _v4_global(_v4_scope, 'str')(cutoff_at) != _v4_global(_v4_scope, 'str')(supply_envelope["cutoff_at"]):
            raise _v4_global(_v4_scope, 'ValueError')("research supply source-only cutoff must bind to supply envelope")
        if manager_decision is None and manager_decision_ref is not None:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision reference requires a decision document")
    elif manager_decision is not None or manager_decision_ref is not None:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision requires a research supply envelope")
    if not source_cards and _v4_global(_v4_scope, 'isinstance')(source_envelope, _v4_global(_v4_scope, 'Mapping')):
        frozen = source_envelope.get("frozen_payload")
        cards = frozen.get("event_cards") if _v4_global(_v4_scope, 'isinstance')(frozen, _v4_global(_v4_scope, 'Mapping')) else None
        if _v4_global(_v4_scope, 'isinstance')(cards, _v4_global(_v4_scope, 'list')):
            if not _v4_global(_v4_scope, 'isinstance')(source_ref, _v4_global(_v4_scope, 'Mapping')):
                if _v4_global(_v4_scope, 'len')(cards) != 1:
                    raise _v4_global(_v4_scope, 'ValueError')(
                        "selection source envelope requires one explicit card reference"
                    )
                source_cards = [{"card": cards[0], "source_ref": source_ref}]
            else:
                pointer = source_ref.get("json_pointer")
                prefix = "/frozen_payload/event_cards/"
                index_text = (
                    pointer[_v4_global(_v4_scope, 'len')(prefix) :]
                    if _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'str')) and pointer.startswith(prefix)
                    else ""
                )
                if not index_text.isdigit() or _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'int')(index_text)) != index_text:
                    raise _v4_global(_v4_scope, 'ValueError')(
                        "selection source envelope reference must target one event card"
                    )
                index = _v4_global(_v4_scope, 'int')(index_text)
                if index >= _v4_global(_v4_scope, 'len')(cards) or not _v4_global(_v4_scope, 'isinstance')(cards[index], _v4_global(_v4_scope, 'Mapping')):
                    raise _v4_global(_v4_scope, 'ValueError')("selection source envelope card reference is missing")
                source_cards = [{"card": cards[index], "source_ref": source_ref}]
    source_cards = _v4_global(_v4_scope, 'list')(source_cards or [])
    return source_date, target_trade_date, supply_envelope, source_cards


def _build_selection_candidates_phase(_v4_scope, /, source_date, cutoff_at, source_cards, supply_envelope, route_status, manager_decision, manager_decision_ref):
    if supply_envelope is not None:
        envelope_route = supply_envelope["frozen_payload"]["route_status"]
        route = {
            "R1": _v4_global(_v4_scope, 'str')(envelope_route["R1"]),
            "R2": _v4_global(_v4_scope, 'str')(envelope_route["R2"]),
            "R6": _v4_global(_v4_scope, 'str')(envelope_route["R6"]),
            "GEMINI": "UNVERIFIED",
        }
        if route_status:
            supplied_route = {_v4_global(_v4_scope, 'str')(key): _v4_global(_v4_scope, 'str')(value) for key, value in route_status.items()}
            for key in ("R1", "R2", "R6"):
                if key in supplied_route and supplied_route[key] != route[key]:
                    raise _v4_global(_v4_scope, 'ValueError')("research supply route status does not reconcile")
            if "GEMINI" in supplied_route and supplied_route["GEMINI"] not in {
                "UNVERIFIED",
                "NOT_MATERIALIZED",
            }:
                raise _v4_global(_v4_scope, 'ValueError')("research supply Gemini route is unverified only")
    else:
        route = _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, '_SELECTION_DEFAULT_ROUTE_STATUS'))
        if route_status:
            route.update({_v4_global(_v4_scope, 'str')(key): _v4_global(_v4_scope, 'str')(value) for key, value in route_status.items()})
    if _v4_global(_v4_scope, 'set')(route) != _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, '_SELECTION_DEFAULT_ROUTE_STATUS')):
        raise _v4_global(_v4_scope, 'ValueError')("selection route status fields are incomplete")
    if _v4_global(_v4_scope, 'any')("GEMINI" in _v4_global(_v4_scope, 'str')(value).upper() for value in route.values() if value):
        # Gemini is represented only by the independent GEMINI field.
        route["GEMINI"] = "UNVERIFIED"
    candidates = _v4_global(_v4_scope, 'sorted')(
        [
            _v4_global(_v4_scope, '_selection_candidate')(
                entry,
                source_date=source_date,
                cutoff_at=cutoff_at,
                route_status=route,
            )
            for entry in source_cards
        ],
        key=lambda row: row["candidate_id"],
    )
    candidate_ids = [row["candidate_id"] for row in candidates]
    if _v4_global(_v4_scope, 'len')(candidate_ids) != _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'set')(candidate_ids)):
        raise _v4_global(_v4_scope, 'ValueError')("selection candidate identity collision")
    if candidates and route["GEMINI"] == "NOT_MATERIALIZED":
        route["GEMINI"] = "UNVERIFIED"
    for candidate in candidates:
        # Keep per-card route evidence; do not promote a global route from a
        # non-empty ledger.  Gemini remains its own unverified channel.
        candidate["gemini_status"] = candidate.get("gemini_status") or route["GEMINI"]
    source_refs = [ref for candidate in candidates for ref in candidate["source_refs"]]
    if manager_decision is not None and manager_decision_ref is None:
        raise _v4_global(_v4_scope, 'ValueError')("manager decision reference is required")
    if manager_decision_ref is not None:
        if supply_envelope is None or manager_decision is None:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision reference requires a supply decision")
        if (
            not _v4_global(_v4_scope, 'isinstance')(manager_decision_ref, _v4_global(_v4_scope, 'Mapping'))
            or _v4_global(_v4_scope, 'set')(manager_decision_ref) != {"path", "raw_sha256"}
            or not _v4_global(_v4_scope, 'isinstance')(manager_decision_ref.get("path"), _v4_global(_v4_scope, 'str'))
            or not manager_decision_ref["path"]
            or _v4_global(_v4_scope, '_selection_hash_text')(manager_decision_ref.get("raw_sha256")) is None
        ):
            raise _v4_global(_v4_scope, 'ValueError')("manager decision reference is invalid")
    return route, candidates, candidate_ids, source_refs


def _project_selection_manager_decision_phase(_v4_scope, /, candidates, candidate_ids, supply_envelope, cutoff_at, manager_decision, manager_decision_ref, snapshots):
    if manager_decision is not None:
        if supply_envelope is None:
            raise _v4_global(_v4_scope, 'ValueError')("manager decision requires a research supply envelope")
        _v4_global(_v4_scope, 'validate_manager_research_decision')(
            manager_decision,
            candidate_ids=candidate_ids,
            supply_envelope=supply_envelope,
        )
        if _v4_global(_v4_scope, 'str')(cutoff_at) != _v4_global(_v4_scope, 'str')(manager_decision["cutoff_at"]):
            raise _v4_global(_v4_scope, 'ValueError')("research supply product cutoff must bind to manager decision")
        decision_ids = _v4_global(_v4_scope, 'sorted')(
            [
                row["candidate_id"]
                for row in [
                    *manager_decision["core"],
                    *manager_decision["conditional"],
                ]
            ]
        )
        decision_snapshot = {
            "phase": "2200",
            "status": "READY",
            "run_id": manager_decision["run_id"],
            "event_at": manager_decision["generated_at"],
            "artifact_sha256": manager_decision_ref["raw_sha256"],
            "candidate_ids": decision_ids,
            "changes": [],
            "freeze_run_id": None,
            "freeze_snapshot_sha256": None,
            "snapshot_sha256": None,
        }
        supplied_2200 = (snapshots or {}).get("2200") if snapshots else None
        if _v4_global(_v4_scope, 'isinstance')(supplied_2200, _v4_global(_v4_scope, 'Mapping')) and supplied_2200.get("status") == "READY":
            if (
                supplied_2200.get("run_id") != decision_snapshot["run_id"]
                or _v4_global(_v4_scope, 'sorted')(supplied_2200.get("candidate_ids") or []) != decision_ids
            ):
                raise _v4_global(_v4_scope, 'ValueError')("manager decision does not reconcile with 2200 snapshot")
        decision_projection: dict[str, dict[str, Any]] = {}
        for role, field in (("CORE", "core"), ("CONDITIONAL", "conditional")):
            for order, row in _v4_global(_v4_scope, 'enumerate')(manager_decision[field], 1):
                decision_projection[row["candidate_id"]] = {
                    "schema_version": manager_decision["schema_version"],
                    "phase": manager_decision["phase"],
                    "decision_state": manager_decision["decision_state"],
                    "source_date": manager_decision["source_date"],
                    "target_trade_date": manager_decision["target_trade_date"],
                    "run_id": manager_decision["run_id"],
                    "generated_at": manager_decision["generated_at"],
                    "cutoff_at": manager_decision["cutoff_at"],
                    "role": role,
                    "order": order,
                    "reason": row["reason"],
                }
        for candidate in candidates:
            metadata = candidate.get("source_metadata")
            if not _v4_global(_v4_scope, 'isinstance')(metadata, _v4_global(_v4_scope, 'Mapping')) or not _v4_global(_v4_scope, 'isinstance')(metadata.get("supply_card"), _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'ValueError')("manager decision projection requires a supply card")
            projection = decision_projection.get(candidate["candidate_id"])
            if projection is not None:
                # Keep the frozen supply card byte-for-byte equivalent to its
                # source envelope.  The typed manager role is a derived
                # candidate projection, never part of source_metadata.
                candidate["manager_decision"] = projection
        snapshots = {**_v4_global(_v4_scope, 'dict')(snapshots or {}), "2200": decision_snapshot}
    return snapshots


def _project_selection_snapshot_state_phase(_v4_scope, /, target_trade_date, candidates, candidate_ids, supply_envelope, snapshots, intraday_observations, outcomes, formal_authority, formal_candidate_ids):
    snapshot_map = {
        phase: _v4_global(_v4_scope, '_selection_snapshot')(
            phase,
            (snapshots or {}).get(phase),
            candidate_ids=candidate_ids,
        )
        for phase in _v4_global(_v4_scope, 'SELECTION_PHASES')
    }
    observations = [_v4_global(_v4_scope, 'dict')(item) for item in (intraday_observations or [])]
    outcome_rows = [_v4_global(_v4_scope, 'dict')(item) for item in (outcomes or [])]
    formal = _v4_global(_v4_scope, '_selection_formal_authority')(
        formal_authority,
        target_trade_date=target_trade_date,
    )
    requested_formal = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(formal_candidate_ids or []))
    formal_ids = (
        requested_formal
        if formal["status"] == "READY"
        and _v4_global(_v4_scope, '_selection_formal_refs_bind_candidates')(formal, requested_formal)
        and _v4_global(_v4_scope, 'all')(candidate_id in candidate_ids for candidate_id in requested_formal)
        and _v4_global(_v4_scope, 'all')(
            candidate["pit_status"] == "READY"
            and candidate["eligibility"] == "ELIGIBLE"
            for candidate in candidates
            if candidate["candidate_id"] in requested_formal
        )
        else []
    )
    cannot_confirm: list[str] = []
    for phase, snapshot in snapshot_map.items():
        if snapshot["status"] != "READY":
            cannot_confirm.append(
                "SUPPLY_2200_DECISION_NOT_MATERIALIZED"
                if supply_envelope is not None and phase == "2200"
                else f"SNAPSHOT_{phase}_NOT_MATERIALIZED"
            )
    if formal["status"] != "READY" or not formal_ids:
        cannot_confirm.append("FORMAL_AUTHORITY_NOT_MATERIALIZED")
    if _v4_global(_v4_scope, 'any')(candidate["pit_status"] != "READY" for candidate in candidates):
        cannot_confirm.append("CANDIDATE_PIT_NOT_CONFIRMED")
    cannot_confirm = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(cannot_confirm))
    status = "NOT_MATERIALIZED" if not candidates else (
        _v4_global(_v4_scope, 'RESEARCH_SUPPLY_STATUS')
        if supply_envelope is not None
        and _v4_global(_v4_scope, 'all')(snapshot_map[phase]["status"] != "READY" for phase in _v4_global(_v4_scope, 'SELECTION_PHASES'))
        else (
            "EARLY_DRAFT_IMPORTED"
            if _v4_global(_v4_scope, 'all')(snapshot_map[phase]["status"] != "READY" for phase in _v4_global(_v4_scope, 'SELECTION_PHASES'))
            else ("READY" if not cannot_confirm else "READY_WITH_DECLARED_GAPS")
        )
    )
    acceptance = (
        _v4_global(_v4_scope, 'RESEARCH_SUPPLY_ACCEPTANCE')
        if supply_envelope is not None and candidates
        else ("EARLY_DRAFT_FROZEN_ONLY" if candidates else "NOT_MATERIALIZED")
    )
    first_failed = cannot_confirm[0] if cannot_confirm else None
    return snapshot_map, observations, outcome_rows, formal, formal_ids, cannot_confirm, status, acceptance, first_failed


def _assemble_selection_product_phase(_v4_scope, /, source_date, target_trade_date, cutoff_at, generated_at, run_id, origin, route, candidates, formal_ids, snapshot_map, observations, outcome_rows, status, acceptance, formal, source_refs, first_failed, cannot_confirm, manager_decision_ref):
    product = {
        "schema_version": _v4_global(_v4_scope, 'SELECTION_SCHEMA_VERSION'),
        "contract_id": _v4_global(_v4_scope, 'SELECTION_CONTRACT_ID'),
        "workflow_name": _v4_global(_v4_scope, 'SELECTION_WORKFLOW_NAME'),
        "pass_signal": _v4_global(_v4_scope, 'SELECTION_PASS_SIGNAL'),
        "source_date": source_date,
        "target_trade_date": target_trade_date,
        "timezone": _v4_global(_v4_scope, 'TIMEZONE'),
        "cutoff_at": cutoff_at,
        "generated_at": generated_at,
        "run_id": run_id,
        "origin": origin,
        "status": status,
        "acceptance": acceptance,
        "research_candidates": candidates,
        "formal_shortlist": formal_ids,
        "snapshots": snapshot_map,
        "intraday_observations": observations,
        "outcomes": outcome_rows,
        "counts": {
            "research_candidates": _v4_global(_v4_scope, 'len')(candidates),
            "formal_shortlist": _v4_global(_v4_scope, 'len')(formal_ids),
            "snapshots": _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'SELECTION_PHASES')),
            "intraday_observations": _v4_global(_v4_scope, 'len')(observations),
            "outcomes": _v4_global(_v4_scope, 'len')(outcome_rows),
        },
        "route_status": route,
        "gemini_status": route["GEMINI"],
        "formal_authority": formal,
        "source_refs": source_refs,
        "first_failed_layer": first_failed,
        "cannot_confirm": cannot_confirm,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    if manager_decision_ref is not None:
        product["manager_decision_ref"] = _v4_global(_v4_scope, 'dict')(manager_decision_ref)
    _v4_global(_v4_scope, 'validate_selection_research_product')(product)
    return product

