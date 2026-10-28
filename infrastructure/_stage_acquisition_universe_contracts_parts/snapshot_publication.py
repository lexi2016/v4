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
    from infrastructure.preselection_pool_store import (
        PreselectionPoolArtifactMissing,
        PreselectionPoolIntegrityError,
        PreselectionPoolStore,
    )

    class _StagePoolReadStore(PreselectionPoolStore):
        """Classify only malformed identity fields from one physical pool."""

        def read_pool_snapshot(self, trade_date, pool_id, *, lock_lease=None):
            try:
                return super().read_pool_snapshot(
                    trade_date, pool_id, lock_lease=lock_lease
                )
            except KeyError as error:
                field = error.args[0] if error.args else None
                if field not in {"source_sha256", "source_role"}:
                    raise
                raise PreselectionPoolIntegrityError(
                    pool_id, f"pool artifact is missing {field}"
                ) from error

    # ``Path`` itself has a ``root`` property (``/`` on POSIX); inspect paths
    # before looking for the NativeDataStore root attribute.
    root = _v4_global(_v4_scope, 'Path')(store) if _v4_global(_v4_scope, 'isinstance')(store, (_v4_global(_v4_scope, 'str'), _v4_global(_v4_scope, 'Path'))) else _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'getattr')(store, "root", store))
    # Use the exact same aggregate API and root lock while translating the
    # store reader's narrow missing-identity KeyError into its typed lane
    # outcome. Directory, lock, manifest and other failures remain untouched.
    pool_store = _StagePoolReadStore(root)
    snapshots: list[VerifiedPoolSnapshot] = []
    diagnostics: dict[str, list[str]] = {}
    integrity_errors: list[PreselectionPoolIntegrityError] = []
    if lock_lease is None:
        # This is the PREP_0915 path: consume the store's single locked
        # exact-date aggregate so pool-local failures stay distinct from root,
        # lock, and shared-manifest failures.
        store_snapshots, integrity_errors = pool_store.read_all_with_quarantine(date)
    else:
        # Strict publication revalidation already owns this exact root lease.
        # Reuse it for each A lane because read_all_with_quarantine acquires
        # its own lease and cannot safely nest inside the publisher's lease.
        if not _v4_global(_v4_scope, 'isinstance')(
            pool_store, PreselectionPoolStore
        ):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                "owned lock lease requires the native preselection store"
            )
        store_snapshots = []
        for pool_id in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS'):
            try:
                store_snapshots.append(
                    pool_store.read_pool_snapshot(
                        date, pool_id, lock_lease=lock_lease
                    )
                )
            except PreselectionPoolArtifactMissing:
                continue
            except PreselectionPoolIntegrityError as error:
                integrity_errors.append(error)

    for result in store_snapshots:
        if not _v4_global(_v4_scope, 'isinstance')(result, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                "locked pool reader returned an invalid snapshot"
            )
        artifact = result.get("artifact")
        if not _v4_global(_v4_scope, 'isinstance')(artifact, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                "locked pool reader returned an invalid artifact"
            )
        pool_id = artifact.get("pool_id")
        if pool_id in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS'):
            snapshots.append(_v4_global(_v4_scope, '_snapshot_from_store_result')(result, date, pool_id))
        elif pool_id != "hkconnect_d1_top100":
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"locked A pool reader returned an unsupported pool: {pool_id}"
            )

    for error in integrity_errors:
        if not _v4_global(_v4_scope, 'isinstance')(error, PreselectionPoolIntegrityError):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                "locked A pool reader returned an untyped quarantine outcome"
            )
        if error.pool_id not in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS'):
            if error.pool_id == "hkconnect_d1_top100":
                continue
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"locked A pool reader returned an unknown quarantine pool: {error.pool_id}"
            )
        _v4_global(_v4_scope, '_append_diagnostic')(
            diagnostics,
            error.pool_id,
            f"POOL_SOURCE_INTEGRITY_UNCONFIRMED:{error.reason}",
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
        "available_pool_ids": [
            item["pool_id"] for item in provenance if item.get("available", True) is True
        ],
    }
    return artifact
