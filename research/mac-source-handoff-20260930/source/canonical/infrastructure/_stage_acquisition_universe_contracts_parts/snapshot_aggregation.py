"""infrastructure.stage_acquisition_universe_contracts: snapshot_aggregation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _aggregate_verified_pool_snapshots_body(_v4_scope, /, snapshots, trade_date, *, pool_diagnostics):
    """Aggregate the known A lanes, accepting any verified non-empty subset.

    Every known lane still has a fixed provenance slot.  Missing, empty, or
    rejected lanes are recorded under their pool ID; they are not allowed to
    erase rows contributed by another valid lane.  The aggregate only becomes
    blocked when no valid A rows remain.
    """

    try:
        date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(trade_date))
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')("required A pool trade date is invalid") from error
    items = _v4_global(_v4_scope, 'tuple')(snapshots)
    by_pool: dict[str, VerifiedPoolSnapshot] = {}
    for item in items:
        if not _v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'VerifiedPoolSnapshot')):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                "required A pool set contains an invalid physical snapshot"
            )
        if item.pool_id not in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS'):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"unknown A pool snapshot: {item.pool_id}"
            )
        if item.pool_id in by_pool:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"duplicate A pool snapshot: {item.pool_id}"
            )
        by_pool[item.pool_id] = item

    diagnostics: dict[str, list[str]] = {
        pool_id: [] for pool_id in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS')
    }
    if pool_diagnostics is not None:
        if not _v4_global(_v4_scope, 'isinstance')(pool_diagnostics, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')("A pool diagnostics must be an object")
        for pool_id, reasons in pool_diagnostics.items():
            if pool_id not in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS'):
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"unknown A pool diagnostic: {pool_id}"
                )
            for reason in reasons:
                _v4_global(_v4_scope, '_append_diagnostic')(diagnostics, pool_id, _v4_global(_v4_scope, 'str')(reason))
    all_rows: list[dict[str, Any]] = []
    codes: list[str] = []
    code_sources: dict[str, list[str]] = {}
    notes: list[str] = []
    physical_snapshots: list[VerifiedPoolSnapshot] = []
    contribution_counts: dict[str, int] = {}
    for pool_id in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS'):
        snapshot = by_pool.get(pool_id)
        if snapshot is None:
            _v4_global(_v4_scope, '_append_diagnostic')(diagnostics, pool_id, "POOL_NOT_AVAILABLE")
            continue
        try:
            rows, pool_blocking, pool_notes = _v4_global(_v4_scope, 'validate_verified_pool_snapshot')(
                snapshot,
                date,
                pool_id,
                allow_diagnostics=True,
            )
        except _v4_global(_v4_scope, 'StageAcquisitionContractError') as error:
            physical_snapshots.append(snapshot)
            contribution_counts[pool_id] = 0
            _v4_global(_v4_scope, '_append_diagnostic')(diagnostics, pool_id, f"SOURCE_REJECTED:{error}")
            raw_rows = snapshot.artifact.get("rows", ())
            if _v4_global(_v4_scope, 'isinstance')(raw_rows, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))) and raw_rows:
                _v4_global(_v4_scope, '_append_diagnostic')(diagnostics, pool_id, "NON_CONTRIBUTING_ROWS")
            continue
        physical_snapshots.append(snapshot)
        contribution_counts[pool_id] = _v4_global(_v4_scope, 'len')(rows)
        for reason in pool_blocking:
            _v4_global(_v4_scope, '_append_diagnostic')(diagnostics, pool_id, f"SOURCE_REJECTED:{reason}")
        for reason in pool_notes:
            if reason not in notes:
                notes.append(reason)
        if not rows:
            raw_rows = snapshot.artifact.get("rows", ())
            _v4_global(_v4_scope, '_append_diagnostic')(
                diagnostics,
                pool_id,
                "POOL_EMPTY"
                if not _v4_global(_v4_scope, 'isinstance')(raw_rows, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))) or not raw_rows
                else "NON_CONTRIBUTING_ROWS",
            )
        for row in rows:
            code = row["symbol"]
            sources = code_sources.setdefault(code, [])
            if pool_id not in sources:
                sources.append(pool_id)
            if code not in codes:
                codes.append(code)
                all_rows.append(row)
    normalized_diagnostics = {
        pool_id: _v4_global(_v4_scope, 'tuple')(reasons)
        for pool_id, reasons in diagnostics.items()
        if reasons
    }
    diagnostic_reasons = _v4_global(_v4_scope, 'tuple')(
        f"{pool_id}:{reason}"
        for pool_id in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS')
        for reason in diagnostics[pool_id]
    )
    ready = _v4_global(_v4_scope, 'bool')(codes)
    return _v4_global(_v4_scope, 'StrictAPreselectionSnapshot')(
        trade_date=date,
        pools=_v4_global(_v4_scope, 'tuple')(physical_snapshots),
        codes=_v4_global(_v4_scope, 'tuple')(codes),
        code_sources={code: _v4_global(_v4_scope, 'tuple')(source_ids) for code, source_ids in code_sources.items()},
        a_all_pool_rows=_v4_global(_v4_scope, 'tuple')(all_rows),
        blocking_reasons=() if ready else ("A_POOL_AGGREGATE_NO_VALID_ROWS",),
        policy_notes=_v4_global(_v4_scope, 'tuple')(notes),
        stage_selection_eligible=ready,
        status="READY" if ready else "CANNOT_CONFIRM",
        pool_diagnostics=normalized_diagnostics,
        pool_contribution_counts=contribution_counts,
        diagnostic_reasons=diagnostic_reasons,
    )
