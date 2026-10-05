"""infrastructure.stage_acquisition_universe_commit: supersession_receipts (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageAcquisitionUniverseCommit__predecessor_summary_body(_v4_scope, /, chain, current_sha256):
    current = chain["current"]
    return {
        "schema_version": _v4_global(_v4_scope, 'STRICT_CURRENT_SCHEMA'),
        "role": _v4_global(_v4_scope, 'STRICT_ROLE'),
        "trade_date": chain["trade_date"],
        "run_id": chain["run_id"],
        "status": current["status"],
        "row_count": current["row_count"],
        "codes_sha256": current["codes_sha256"],
        "source_projection_sha256": chain["artifact"]["source_projection_sha256"],
        "artifact_bytes_sha256": chain["artifact_bytes_sha256"],
        "artifact_canonical_sha256": chain["artifact_canonical_sha256"],
        "manifest_bytes_sha256": chain["manifest_bytes_sha256"],
        "manifest_canonical_sha256": chain["manifest_canonical_sha256"],
        "receipt_bytes_sha256": chain["receipt_bytes_sha256"],
        "receipt_canonical_sha256": chain["receipt_canonical_sha256"],
        "commit_id": chain["commit_id"],
        "commit_marker_bytes_sha256": chain["commit_marker_bytes_sha256"],
        "commit_marker_canonical_sha256": chain["commit_marker_canonical_sha256"],
        "current_bytes_sha256": current_sha256,
        **_v4_global(_v4_scope, '_identity_fields')(
            _v4_global(_v4_scope, 'EvidenceIdentity')(
                owner_id=current["owner_id"],
                producer_id=current["producer_id"],
                release_id=current["release_id"],
                lane_id=current["lane_id"],
            )
        ),
        **{name: False for name in _v4_global(_v4_scope, '_FLAGS')},
    }


def _StageAcquisitionUniverseCommit__successor_lineage_body(_v4_scope, /, chain):
    artifact = chain["artifact"]
    return {
        "run_id": chain["run_id"],
        "row_count": artifact["row_count"],
        "codes_sha256": artifact["codes_sha256"],
        "source_projection_sha256": artifact["source_projection_sha256"],
        "artifact_bytes_sha256": chain["artifact_bytes_sha256"],
        "artifact_canonical_sha256": chain["artifact_canonical_sha256"],
        "manifest_bytes_sha256": chain["manifest_bytes_sha256"],
        "manifest_canonical_sha256": chain["manifest_canonical_sha256"],
        "receipt_bytes_sha256": chain["receipt_bytes_sha256"],
        "receipt_canonical_sha256": chain["receipt_canonical_sha256"],
        "commit_id": chain["commit_id"],
        "commit_marker_bytes_sha256": chain["commit_marker_bytes_sha256"],
        "commit_marker_canonical_sha256": chain["commit_marker_canonical_sha256"],
    }


def _StageAcquisitionUniverseCommit__current_from_chain_body(_v4_scope, /, chain, identity, date, *, predecessor):
    """Rebuild a current pointer solely from its committed run chain."""

    marker_predecessor = chain["commit"].get("predecessor")
    if predecessor is None:
        predecessor = marker_predecessor
    elif marker_predecessor != _v4_global(_v4_scope, 'dict')(predecessor):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict chain predecessor pointer mismatch")
    return _v4_global(_v4_scope, '_current')(
        chain["artifact"],
        identity,
        date,
        chain["run_id"],
        _v4_global(_v4_scope, 'StageAcquisitionUniverseCommit')._chain_hashes(chain),
        chain["commit_id"],
        chain["commit_marker_bytes_sha256"],
        chain["commit_marker_canonical_sha256"],
        chain["commit_marker_size_bytes"],
        predecessor=predecessor,
    )


def _StageAcquisitionUniverseCommit__build_supersession_receipt_body(_v4_scope, /, self, *, date, identity, reason, expected_current_sha256, predecessor, previous_current, successor_chain, successor_current, target_current_relative):
    """Build the complete canonical receipt from the verified chain.

        Every field is derived from the predecessor/successor chain or the
        explicit request.  Readers use this same function, so a receipt field
        cannot be changed in place without failing canonical reconstruction.
        """

    expected = _v4_global(_v4_scope, '_require_sha')(
        expected_current_sha256,
        "strict supersession expected current SHA",
    )
    reason_text = _v4_global(_v4_scope, '_require_nonempty_text')(reason, "strict supersession reason")
    target = _v4_global(_v4_scope, '_require_nonempty_text')(
        target_current_relative, "strict supersession target path"
    )
    predecessor_sha = _v4_global(_v4_scope, '_require_sha')(
        predecessor.get("current_bytes_sha256"),
        "strict supersession predecessor current SHA",
    )
    if expected != predecessor_sha:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession predecessor current SHA mismatch")
    successor_current_bytes = _v4_global(_v4_scope, '_canonical_bytes')(successor_current)
    return {
        "schema_version": _v4_global(_v4_scope, 'STRICT_SUPERSESSION_SCHEMA'),
        "role": _v4_global(_v4_scope, 'STRICT_ROLE'),
        "trade_date": date,
        "status": "SUPERSEDED",
        "evolution": _v4_global(_v4_scope, 'STRICT_SUCCESSOR_EVOLUTION'),
        "reason": reason_text,
        "expected_current_bytes_sha256": expected,
        "previous_current_bytes_sha256": predecessor_sha,
        "previous_commit_id": predecessor["commit_id"],
        "predecessor": _v4_global(_v4_scope, 'dict')(predecessor),
        "previous_current": _v4_global(_v4_scope, 'dict')(previous_current),
        "successor_run_id": successor_chain["run_id"],
        "successor": self._successor_lineage(successor_chain),
        "successor_current": _v4_global(_v4_scope, 'dict')(successor_current),
        "successor_current_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(successor_current_bytes),
        "target_current_relative": target,
        "successor_current_relative": target,
        **_v4_global(_v4_scope, '_identity_fields')(identity),
        **{name: False for name in _v4_global(_v4_scope, '_FLAGS')},
    }
