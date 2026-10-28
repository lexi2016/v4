"""infrastructure.stage_acquisition_universe_contracts: snapshot_verification (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __snapshot_from_store_result_body(_v4_scope, /, result, trade_date, pool_id):
    artifact = result.get("artifact", result.get("payload"))
    manifest = result.get("manifest")
    receipt = result.get("receipt")
    if not _v4_global(_v4_scope, 'all')(_v4_global(_v4_scope, 'isinstance')(item, _v4_global(_v4_scope, 'Mapping')) for item in (artifact, manifest, receipt)):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} physical snapshot is incomplete"
        )
    fields = {
        "artifact_relative_path": result.get("artifact_relative_path", result.get("artifact_relative")),
        "manifest_relative_path": result.get("manifest_relative_path", result.get("manifest_relative")),
        "receipt_relative_path": result.get("receipt_relative_path", result.get("receipt_relative")),
        "artifact_raw_sha256": result.get("artifact_raw_sha256"),
        "manifest_raw_sha256": result.get("manifest_raw_sha256"),
        "receipt_raw_sha256": result.get("receipt_raw_sha256"),
        "pool_sha256": result.get("pool_sha256", result.get("semantic_sha256")),
    }
    if _v4_global(_v4_scope, 'any')(not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value for value in fields.values()):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} physical snapshot identity is incomplete"
        )
    for name in (
        "artifact_raw_sha256",
        "manifest_raw_sha256",
        "receipt_raw_sha256",
        "pool_sha256",
    ):
        if _v4_global(_v4_scope, '_SHA256').fullmatch(fields[name]) is None:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"required A pool {pool_id} {name} is invalid"
            )
    expected_artifact = f"preselection_pools/{trade_date}/{pool_id}.json"
    expected_manifest = f"preselection_pools/{trade_date}/manifest.json"
    expected_receipt = f"preselection_pools/{trade_date}/receipts/{pool_id}.json"
    if (
        fields["artifact_relative_path"] != expected_artifact
        or fields["manifest_relative_path"] != expected_manifest
        or fields["receipt_relative_path"] != expected_receipt
    ):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} relative path is not bound"
        )
    return _v4_global(_v4_scope, 'VerifiedPoolSnapshot')(
        pool_id=pool_id,
        trade_date=trade_date,
        artifact=artifact,
        manifest=manifest,
        receipt=receipt,
        **fields,
    )


def _validate_verified_pool_snapshot_body(_v4_scope, /, snapshot, trade_date, pool_id, *, allow_diagnostics):
    """Validate one verified snapshot and return rows plus reason classes."""

    if not _v4_global(_v4_scope, 'isinstance')(snapshot, _v4_global(_v4_scope, 'VerifiedPoolSnapshot')):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} snapshot type is invalid"
        )
    if snapshot.pool_id != pool_id or snapshot.trade_date != trade_date:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} physical identity mismatch"
        )
    # Snapshot payloads are recursively frozen; validation works on a local
    # mutable JSON-shaped view so the existing list/object contract remains
    # exact without exposing mutability through the dataclass.
    payload = _v4_global(_v4_scope, '_thaw')(snapshot.artifact)
    payload, blocking, notes = _v4_global(_v4_scope, 'validate_pool_source_metadata')(
        payload, trade_date, pool_id
    )
    if snapshot.pool_sha256 != _v4_global(_v4_scope, '_semantic_sha')(payload):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} semantic SHA mismatch"
        )
    for name in ("artifact_raw_sha256", "manifest_raw_sha256", "receipt_raw_sha256"):
        if _v4_global(_v4_scope, '_SHA256').fullmatch(_v4_global(_v4_scope, 'getattr')(snapshot, name)) is None:
            raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                f"required A pool {pool_id} {name} is invalid"
            )
    expected_artifact = f"preselection_pools/{trade_date}/{pool_id}.json"
    expected_manifest = f"preselection_pools/{trade_date}/manifest.json"
    expected_receipt = f"preselection_pools/{trade_date}/receipts/{pool_id}.json"
    if (
        snapshot.artifact_relative_path != expected_artifact
        or snapshot.manifest_relative_path != expected_manifest
        or snapshot.receipt_relative_path != expected_receipt
    ):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} relative path is not bound"
        )
    if (
        snapshot.artifact_raw_sha256 != _v4_global(_v4_scope, '_semantic_sha')(payload)
        or snapshot.manifest_raw_sha256 != _v4_global(_v4_scope, '_semantic_sha')(snapshot.manifest)
        or snapshot.receipt_raw_sha256 != _v4_global(_v4_scope, '_semantic_sha')(snapshot.receipt)
    ):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} physical SHA mismatch"
        )
    if snapshot.manifest.get(pool_id) != snapshot.pool_sha256:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} manifest binding mismatch"
        )
    expected_receipt_payload = {
        "schema_version": "v3_5.preselection_pool_receipt.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "artifact_path": expected_artifact,
        "artifact_sha256": snapshot.pool_sha256,
        "source_sha256": payload.get("source_sha256"),
        "source_role": payload.get("source_role"),
    }
    for key in ("source_row_count", "source_run_id"):
        if key in payload:
            expected_receipt_payload[key] = payload[key]
    if _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, '_thaw')(snapshot.receipt)) != expected_receipt_payload:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} receipt binding mismatch"
        )
    if blocking and not allow_diagnostics:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} cannot be confirmed: {', '.join(blocking)}"
        )
    expected_status = _v4_global(_v4_scope, 'a_pool_contract')(pool_id)[0]
    if payload.get("status") != expected_status:
        if allow_diagnostics:
            return [], blocking, notes
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} status is not a contributing result"
        )
    try:
        rows = _v4_global(_v4_scope, 'validate_pool_rows')(
            payload,
            pool_id,
            trade_date,
            allow_empty=allow_diagnostics,
        )
    except _v4_global(_v4_scope, 'StageAcquisitionContractError'):
        if not allow_diagnostics:
            raise
        raise
    return rows, blocking, notes
