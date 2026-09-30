"""domains.research_day_product: phase_append (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _append_selection_phase_body(_v4_scope, /, product, phase, *, run_id, event_at, artifact_sha256, changes, observation, outcome):
    """Append one phase while preserving the immutable 08:30 freeze."""

    _v4_global(_v4_scope, 'validate_selection_research_product')(product)
    if phase not in _v4_global(_v4_scope, 'SELECTION_PHASES') or phase == "2200":
        raise _v4_global(_v4_scope, 'ValueError')("selection append phase must be 0830, 0935 or 1620")
    result = _v4_global(_v4_scope, 'deepcopy')(_v4_global(_v4_scope, 'dict')(product))
    snapshots = result["snapshots"]
    candidate_ids = [row["candidate_id"] for row in result["research_candidates"]]
    candidate_set = _v4_global(_v4_scope, 'set')(candidate_ids)

    def validate_changes(
        values: list[Mapping[str, Any]] | None,
        *,
        current_ids: set[str] | None = None,
    ) -> tuple[list[Mapping[str, Any]], set[str]]:
        rows = _v4_global(_v4_scope, 'list')(values or [])
        seen: set[str] = _v4_global(_v4_scope, 'set')()
        working = _v4_global(_v4_scope, 'set')(current_ids if current_ids is not None else candidate_set)
        for change in rows:
            if not _v4_global(_v4_scope, 'isinstance')(change, _v4_global(_v4_scope, 'Mapping')):
                raise _v4_global(_v4_scope, 'ValueError')("selection phase change must be an object")
            action = _v4_global(_v4_scope, '_text')(change.get("action")).upper()
            candidate_id = _v4_global(_v4_scope, '_text')(change.get("candidate_id"))
            if action not in {"KEEP", "ADD", "REMOVE"}:
                raise _v4_global(_v4_scope, 'ValueError')("selection phase change action is invalid")
            if not candidate_id or candidate_id not in candidate_set:
                raise _v4_global(_v4_scope, 'ValueError')("selection phase change candidate is unknown")
            if candidate_id in seen:
                raise _v4_global(_v4_scope, 'ValueError')("selection phase change candidate is duplicated")
            seen.add(candidate_id)
            if action == "KEEP":
                if candidate_id not in working:
                    raise _v4_global(_v4_scope, 'ValueError')("selection KEEP candidate is not in the current set")
            elif action == "ADD":
                if candidate_id in working:
                    raise _v4_global(_v4_scope, 'ValueError')("selection ADD candidate is already in the current set")
                working.add(candidate_id)
            elif candidate_id not in working:
                raise _v4_global(_v4_scope, 'ValueError')("selection REMOVE candidate is not in the current set")
            else:
                working.remove(candidate_id)
        return rows, working

    try:
        previous_generated = _v4_global(_v4_scope, 'datetime').fromisoformat(
            _v4_global(_v4_scope, 'str')(result["generated_at"]).replace("Z", "+00:00")
        )
        next_event = _v4_global(_v4_scope, 'datetime').fromisoformat(event_at.replace("Z", "+00:00"))
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("selection phase timestamp is invalid") from error
    if (
        previous_generated.tzinfo is None
        or previous_generated.utcoffset() is None
        or next_event.tzinfo is None
        or next_event.utcoffset() is None
        or next_event.astimezone(_v4_global(_v4_scope, '_SHANGHAI')) < previous_generated.astimezone(_v4_global(_v4_scope, '_SHANGHAI'))
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection phase event cannot move backwards")
    supply_product = _v4_global(_v4_scope, 'any')(
        _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) and ref.get("type") == _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE')
        for candidate in result.get("research_candidates", [])
        for ref in candidate.get("source_refs", [])
    )
    if supply_product and next_event.astimezone(_v4_global(_v4_scope, '_SHANGHAI')).strftime("%Y%m%d") != result["target_trade_date"]:
        raise _v4_global(_v4_scope, 'ValueError')("research supply phase event target date mismatch")
    if phase == "0830":
        if snapshots["0830"]["status"] == "READY":
            raise _v4_global(_v4_scope, 'ValueError')("selection 0830 snapshot is immutable")
        initial = snapshots["2200"]
        if initial["status"] != "READY":
            raise _v4_global(_v4_scope, 'ValueError')("selection 0830 requires a 2200 initial snapshot")
        initial_ids = _v4_global(_v4_scope, 'set')(initial["candidate_ids"])
        if not initial_ids.issubset(candidate_set):
            raise _v4_global(_v4_scope, 'ValueError')("selection 2200 snapshot contains unknown candidates")
        change_rows, frozen_candidate_ids = validate_changes(
            changes,
            current_ids=initial_ids,
        )
        freeze = {
            "phase": "0830",
            "status": "READY",
            "run_id": run_id,
            "event_at": event_at,
            "artifact_sha256": artifact_sha256,
            "candidate_ids": _v4_global(_v4_scope, 'sorted')(frozen_candidate_ids),
            "changes": change_rows,
            "freeze_run_id": None,
            "freeze_snapshot_sha256": None,
            "snapshot_sha256": None,
        }
        snapshots["0830"] = _v4_global(_v4_scope, '_selection_snapshot')("0830", freeze, candidate_ids=candidate_ids)
    elif phase == "0935":
        freeze = snapshots["0830"]
        if freeze["status"] != "READY":
            raise _v4_global(_v4_scope, 'ValueError')("selection 0935 requires an 0830 freeze")
        if observation is None:
            raise _v4_global(_v4_scope, 'ValueError')("selection 0935 requires an append observation")
        change_rows, _ = validate_changes(
            changes,
            current_ids=_v4_global(_v4_scope, 'set')(freeze["candidate_ids"]),
        )
        observation_row = _v4_global(_v4_scope, 'dict')(observation)
        observation_row.setdefault("kind", "APPEND_ONLY")
        if observation_row.get("kind") != "APPEND_ONLY":
            raise _v4_global(_v4_scope, 'ValueError')("selection 0935 observation must be APPEND_ONLY")
        observation_candidate = observation_row.get("candidate_id")
        if observation_candidate is not None and _v4_global(_v4_scope, '_text')(observation_candidate) not in candidate_set:
            raise _v4_global(_v4_scope, 'ValueError')("selection 0935 observation candidate is unknown")
        observation_row["freeze_run_id"] = freeze["run_id"]
        observation_row["freeze_snapshot_sha256"] = freeze["snapshot_sha256"]
        result["intraday_observations"].append(observation_row)
        snapshots["0935"] = _v4_global(_v4_scope, '_selection_snapshot')(
            "0935",
            {
                "phase": "0935",
                "status": "READY",
                "run_id": run_id,
                "event_at": event_at,
                "artifact_sha256": artifact_sha256,
                "candidate_ids": _v4_global(_v4_scope, 'list')(freeze["candidate_ids"]),
                "changes": change_rows,
                "freeze_run_id": freeze["run_id"],
                "freeze_snapshot_sha256": freeze["snapshot_sha256"],
                "snapshot_sha256": None,
            },
            candidate_ids=_v4_global(_v4_scope, 'list')(freeze["candidate_ids"]),
        )
    else:
        freeze = snapshots["0830"]
        if freeze["status"] != "READY":
            raise _v4_global(_v4_scope, 'ValueError')("selection 1620 requires an 0830 freeze")
        if outcome is None:
            raise _v4_global(_v4_scope, 'ValueError')("selection 1620 requires an outcome reference")
        change_rows, _ = validate_changes(
            changes,
            current_ids=_v4_global(_v4_scope, 'set')(freeze["candidate_ids"]),
        )
        outcome_row = _v4_global(_v4_scope, 'dict')(outcome)
        if outcome_row.get("freeze_run_id") != freeze["run_id"] or outcome_row.get("freeze_snapshot_sha256") != freeze["snapshot_sha256"]:
            raise _v4_global(_v4_scope, 'ValueError')("selection outcome does not reference the frozen run")
        result["outcomes"].append(outcome_row)
        snapshots["1620"] = _v4_global(_v4_scope, '_selection_snapshot')(
            "1620",
            {
                "phase": "1620",
                "status": "READY",
                "run_id": run_id,
                "event_at": event_at,
                "artifact_sha256": artifact_sha256,
                "candidate_ids": _v4_global(_v4_scope, 'list')(freeze["candidate_ids"]),
                "changes": change_rows,
                "freeze_run_id": freeze["run_id"],
                "freeze_snapshot_sha256": freeze["snapshot_sha256"],
                "snapshot_sha256": None,
            },
            candidate_ids=_v4_global(_v4_scope, 'list')(freeze["candidate_ids"]),
        )
    result["run_id"] = run_id
    result["generated_at"] = event_at
    result["counts"] = {
        "research_candidates": _v4_global(_v4_scope, 'len')(result["research_candidates"]),
        "formal_shortlist": _v4_global(_v4_scope, 'len')(result["formal_shortlist"]),
        "snapshots": _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'SELECTION_PHASES')),
        "intraday_observations": _v4_global(_v4_scope, 'len')(result["intraday_observations"]),
        "outcomes": _v4_global(_v4_scope, 'len')(result["outcomes"]),
    }
    refreshed_gaps = [
        gap
        for gap in result["cannot_confirm"]
        if not _v4_global(_v4_scope, 'any')(gap == f"SNAPSHOT_{known_phase}_NOT_MATERIALIZED" for known_phase in _v4_global(_v4_scope, 'SELECTION_PHASES'))
    ]
    for known_phase in _v4_global(_v4_scope, 'SELECTION_PHASES'):
        if snapshots[known_phase]["status"] != "READY":
            refreshed_gaps.append(f"SNAPSHOT_{known_phase}_NOT_MATERIALIZED")
    if result["formal_authority"].get("status") != "READY" or not result["formal_shortlist"]:
        refreshed_gaps.append("FORMAL_AUTHORITY_NOT_MATERIALIZED")
    if _v4_global(_v4_scope, 'any')(candidate["pit_status"] != "READY" for candidate in result["research_candidates"]):
        refreshed_gaps.append("CANDIDATE_PIT_NOT_CONFIRMED")
    result["cannot_confirm"] = _v4_global(_v4_scope, 'sorted')(_v4_global(_v4_scope, 'set')(refreshed_gaps))
    result["first_failed_layer"] = result["cannot_confirm"][0] if result["cannot_confirm"] else None
    result["status"] = "READY_WITH_DECLARED_GAPS" if result["cannot_confirm"] else "READY"
    _v4_global(_v4_scope, 'validate_selection_research_product')(result)
    return result
