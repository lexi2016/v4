"""infrastructure.stage_acquisition_universe_contracts: snapshot_provenance (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __snapshot_pool_provenance_body(_v4_scope, /, snapshot):
    """Derive the exact stage provenance representation from one snapshot."""

    by_pool = {pool.pool_id: pool for pool in snapshot.pools}
    provenance: list[dict[str, Any]] = []
    for pool_id in _v4_global(_v4_scope, 'KNOWN_A_STAGE_POOL_IDS'):
        pool = by_pool.get(pool_id)
        diagnostics = _v4_global(_v4_scope, 'list')(snapshot.pool_diagnostics.get(pool_id, ()))
        expected_paths = {
            "artifact_relative_path": f"preselection_pools/{snapshot.trade_date}/{pool_id}.json",
            "manifest_relative_path": f"preselection_pools/{snapshot.trade_date}/manifest.json",
            "receipt_relative_path": f"preselection_pools/{snapshot.trade_date}/receipts/{pool_id}.json",
        }
        if pool is None:
            if not diagnostics:
                diagnostics = ["POOL_NOT_AVAILABLE"]
            provenance.append(
                {
                    "pool_id": pool_id,
                    "status": "UNAVAILABLE",
                    "producer_id": "",
                    "source_role": "",
                    "row_count": 0,
                    "valid_empty": False,
                    "available": False,
                    "diagnostics": diagnostics,
                    "pool_sha256": None,
                    "artifact_raw_sha256": None,
                    "manifest_raw_sha256": None,
                    "receipt_raw_sha256": None,
                    **expected_paths,
                }
            )
            continue
        rows = pool.artifact.get("rows", ())
        raw_row_count = _v4_global(_v4_scope, 'len')(rows) if _v4_global(_v4_scope, 'isinstance')(rows, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))) else 0
        contribution_count = snapshot.pool_contribution_counts.get(
            pool_id, raw_row_count
        )
        if (
            _v4_global(_v4_scope, 'isinstance')(contribution_count, _v4_global(_v4_scope, 'bool'))
            or not _v4_global(_v4_scope, 'isinstance')(contribution_count, _v4_global(_v4_scope, 'int'))
            or contribution_count < 0
            or contribution_count > raw_row_count
        ):
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"strict stage-acquisition source pool {pool_id} contribution count is invalid"
            )
        source_status = _v4_global(_v4_scope, 'str')(pool.artifact.get("status") or "")
        provenance_status = source_status
        if (
            contribution_count == 0
            and source_status.casefold() == "available"
            and any(reason.startswith("SOURCE_REJECTED:") for reason in diagnostics)
        ):
            # A physical upstream artifact with the legacy ``available``
            # status is not an accepted lane status.  Keep the verified
            # physical identity, but describe its zero-row contribution as
            # diagnostic-only so the strict aggregate can publish other
            # valid lanes without admitting these rejected rows.
            provenance_status = "CANNOT_CONFIRM"
            rejected_status = f"SOURCE_STATUS_REJECTED:{source_status}"
            if rejected_status not in diagnostics:
                diagnostics.append(rejected_status)
        provenance.append(
            {
                "pool_id": pool_id,
                "status": provenance_status,
                "producer_id": _v4_global(_v4_scope, 'str')(pool.artifact.get("producer_id") or ""),
                "source_role": _v4_global(_v4_scope, 'str')(pool.artifact.get("source_role") or ""),
                # This is the count of rows that passed contribution
                # validation, not the count declared by a rejected raw lane.
                "row_count": contribution_count,
                "valid_empty": contribution_count == 0,
                "available": True,
                "diagnostics": diagnostics,
                "pool_sha256": pool.pool_sha256,
                "artifact_raw_sha256": pool.artifact_raw_sha256,
                "manifest_raw_sha256": pool.manifest_raw_sha256,
                "receipt_raw_sha256": pool.receipt_raw_sha256,
                **expected_paths,
            }
        )
    return provenance


def _validate_artifact_against_snapshot_body(_v4_scope, /, artifact, snapshot):
    """Require every strict artifact binding to match a fresh physical read."""

    if not _v4_global(_v4_scope, 'isinstance')(snapshot, _v4_global(_v4_scope, 'StrictAPreselectionSnapshot')) or not snapshot.ready:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "required A pool strict snapshot is not READY"
        )
    _v4_global(_v4_scope, 'validate_strict_stage_acquisition_artifact')(artifact)
    if artifact.get("trade_date") != snapshot.trade_date:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact trade_date does not match physical snapshot"
        )
    expected_codes = _v4_global(_v4_scope, 'list')(snapshot.codes)
    if artifact.get("codes") != expected_codes:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact codes do not match physical snapshot"
        )
    if artifact.get("row_count") != _v4_global(_v4_scope, 'len')(expected_codes):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact rows do not match physical snapshot"
        )
    if artifact.get("codes_sha256") != _v4_global(_v4_scope, '_semantic_sha')(expected_codes):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact codes SHA does not match physical snapshot"
        )
    if artifact.get("source_projection_row_count") != _v4_global(_v4_scope, 'len')(expected_codes):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact projection rows do not match physical snapshot"
        )
    if artifact.get("source_projection_sha256") != _v4_global(_v4_scope, '_snapshot_projection_sha256')(snapshot):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact projection SHA does not match physical snapshot"
        )
    expected_provenance = _v4_global(_v4_scope, '_snapshot_pool_provenance')(snapshot)
    if artifact.get("source_pool_provenance") != expected_provenance:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact pool provenance does not match physical snapshot"
        )
    if artifact.get("source_pool_provenance_sha256") != _v4_global(_v4_scope, '_semantic_sha')(
        expected_provenance
    ):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact provenance SHA does not match physical snapshot"
        )
    expected_sources = {
        code: _v4_global(_v4_scope, 'list')(pool_ids) for code, pool_ids in snapshot.code_sources.items()
    }
    if artifact.get("code_sources") != expected_sources:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact code sources do not match physical snapshot"
        )
    if artifact.get("policy_notes") != _v4_global(_v4_scope, 'list')(snapshot.policy_notes):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact policy notes do not match physical snapshot"
        )
    expected_diagnostics = {
        pool_id: _v4_global(_v4_scope, 'list')(reasons)
        for pool_id, reasons in snapshot.pool_diagnostics.items()
    }
    if artifact.get("pool_diagnostics", {}) != expected_diagnostics:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact pool diagnostics do not match physical snapshot"
        )
    if artifact.get("cannot_confirm", []) != _v4_global(_v4_scope, 'list')(snapshot.diagnostic_reasons):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition artifact diagnostics do not match physical snapshot"
        )
    expected_contribution_counts = _v4_global(_v4_scope, 'dict')(snapshot.pool_contribution_counts)
    if artifact.get("pool_contribution_counts", expected_contribution_counts) != expected_contribution_counts:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            "stage-acquisition contribution counts do not match physical snapshot"
        )
