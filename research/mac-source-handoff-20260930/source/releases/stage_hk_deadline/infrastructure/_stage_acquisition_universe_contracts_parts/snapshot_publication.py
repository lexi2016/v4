"""infrastructure.stage_acquisition_universe_contracts: snapshot_publication (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _read_strict_a_preselection_snapshot_body(
    _v4_scope, /, store, trade_date, _limit, lock_lease=None
):
    """Read the known physical pool trios once and return one frozen snapshot.

    A lane read failure is scoped to that lane.  The aggregate remains
    eligible when another verified lane contributes rows; no source is
    replaced with ``latest`` or a display projection.
    """

    try:
        date = _v4_global(_v4_scope, '_date')(_v4_global(_v4_scope, 'str')(trade_date))
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')("required A pool trade date is invalid") from error
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    # ``Path`` itself has a ``root`` property (``/`` on POSIX); inspect paths
    # before looking for the NativeDataStore root attribute.
    root = _v4_global(_v4_scope, 'Path')(store) if _v4_global(_v4_scope, 'isinstance')(store, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'Path'))) else _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'getattr')(store, "root", store))
    pool_store = store if _v4_global(_v4_scope, 'isinstance')(store, PreselectionPoolStore) else PreselectionPoolStore(root)
    snapshots: list[VerifiedPoolSnapshot] = []
    diagnostics: dict[str, list[str]] = {}
    for pool_id in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS'):
        try:
            if lock_lease is None:
                result = pool_store.read_pool_snapshot(date, pool_id)
            else:
                if not _v4_global(_v4_scope, 'isinstance')(
                    pool_store, PreselectionPoolStore
                ):
                    raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                        "owned lock lease requires the native preselection store"
                    )
                result = pool_store.read_pool_snapshot(
                    date, pool_id, lock_lease=lock_lease
                )
            snapshots.append(_v4_global(_v4_scope, '_snapshot_from_store_result')(result, date, pool_id))
        except _v4_global(_v4_scope, 'Exception') as error:
            _v4_global(_v4_scope, '_append_diagnostic')(
                diagnostics,
                pool_id,
                f"SOURCE_UNAVAILABLE:{_v4_global(_v4_scope, 'type')(error).__name__}:{error}",
            )
    return _v4_global(_v4_scope, 'aggregate_verified_pool_snapshots')(
        snapshots,
        date,
        pool_diagnostics=diagnostics,
    )


def _build_strict_stage_acquisition_universe_body(_v4_scope, /, snapshot):
    """Build the stage artifact from the frozen physical snapshot."""

    if not _v4_global(_v4_scope, 'isinstance')(snapshot, _v4_global(_v4_scope, 'StrictAPreselectionSnapshot')):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition builder requires StrictAPreselectionSnapshot"
        )
    if not snapshot.ready:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "strict stage-acquisition snapshot is not READY"
        )
    provenance = _v4_global(_v4_scope, '_snapshot_pool_provenance')(snapshot)
    projection_digest = _v4_global(_v4_scope, '_snapshot_projection_sha256')(snapshot)
    artifact = {
        "schema_version": "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2",
        "artifact_role": "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2",
        "artifact_version": "V2",
        "authority": _v4_global(_v4_scope, 'STRICT_POOL_SNAPSHOT_AUTHORITY'),
        "status": "READY",
        "trade_date": snapshot.trade_date,
        "codes": _v4_global(_v4_scope, 'list')(snapshot.codes),
        "row_count": _v4_global(_v4_scope, 'len')(snapshot.codes),
        "codes_sha256": _v4_global(_v4_scope, '_semantic_sha')(_v4_global(_v4_scope, 'list')(snapshot.codes)),
        "source_projection_sha256": projection_digest,
        "source_projection_row_count": _v4_global(_v4_scope, 'len')(snapshot.codes),
        "source_projection_status": "READY_WITH_ROWS",
        "source_pool_provenance": provenance,
        "source_pool_provenance_sha256": _v4_global(_v4_scope, '_semantic_sha')(provenance),
        "code_sources": {
            code: _v4_global(_v4_scope, 'list')(pool_ids) for code, pool_ids in snapshot.code_sources.items()
        },
        "source_merge_role": "STAGE_ACQUISITION_INPUT",
        "stage_selection_eligible": True,
        "policy_notes": _v4_global(_v4_scope, 'list')(snapshot.policy_notes),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "cannot_confirm": _v4_global(_v4_scope, 'list')(snapshot.diagnostic_reasons),
        "blocking_reasons": [],
        "pool_diagnostics": {
            pool_id: _v4_global(_v4_scope, 'list')(reasons)
            for pool_id, reasons in snapshot.pool_diagnostics.items()
        },
        "pool_contribution_counts": _v4_global(_v4_scope, 'dict')(snapshot.pool_contribution_counts),
        "known_pool_ids": _v4_global(_v4_scope, 'list')(snapshot.known_pool_ids),
        "available_pool_ids": _v4_global(_v4_scope, 'list')(snapshot.pool_ids),
    }
    return artifact
