"""infrastructure.stage_acquisition_universe_commit: current_verification (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageAcquisitionUniverseCommit__verify_run_body(_v4_scope, /, self, secure, date, run, identity):
    paths = _v4_global(_v4_scope, '_paths')(date, run)
    try:
        artifact_result = secure.read_regular_bytes(paths["artifact"])
        manifest_result = secure.read_regular_bytes(paths["manifest"])
        receipt_result = secure.read_regular_bytes(paths["receipt"])
        marker_result = secure.read_regular_bytes(paths["commit"])
    except (_v4_global(_v4_scope, 'SecureEvidenceUnavailable'), _v4_global(_v4_scope, 'SecureEvidenceConflict')) as error:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict committed run evidence or marker is unavailable") from error
    artifact = _v4_global(_v4_scope, '_decode')(artifact_result, "strict artifact")
    manifest = _v4_global(_v4_scope, '_decode')(manifest_result, "strict manifest")
    receipt = _v4_global(_v4_scope, '_decode')(receipt_result, "strict receipt")
    marker = _v4_global(_v4_scope, '_decode')(marker_result, "strict commit marker")
    _v4_global(_v4_scope, '_validate_artifact')(artifact, date, identity)
    hashes = {
        "artifact_bytes_sha256": artifact_result.sha256,
        "artifact_canonical_sha256": _v4_global(_v4_scope, '_canonical_sha')(artifact),
        "manifest_bytes_sha256": manifest_result.sha256,
        "manifest_canonical_sha256": _v4_global(_v4_scope, '_canonical_sha')(manifest),
        "receipt_bytes_sha256": receipt_result.sha256,
        "receipt_canonical_sha256": _v4_global(_v4_scope, '_canonical_sha')(receipt),
    }
    if manifest != _v4_global(_v4_scope, '_manifest')(artifact, identity, date, run, artifact_result.sha256, hashes["artifact_canonical_sha256"], artifact_result.size):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict manifest binding mismatch")
    if receipt != _v4_global(_v4_scope, '_receipt')(artifact, manifest, identity, date, run, artifact_result.sha256, hashes["artifact_canonical_sha256"], manifest_result.sha256, hashes["manifest_canonical_sha256"], manifest_result.size):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict receipt binding mismatch")
    marker_predecessor = marker.get("predecessor")
    marker_supersession = marker.get("supersession")
    if marker_predecessor is not None:
        _v4_global(_v4_scope, '_validate_lineage_predecessor')(marker_predecessor, date, identity)
    if marker_supersession is not None:
        _v4_global(_v4_scope, '_validate_marker_supersession')(marker_supersession, date, identity)
    expected_marker_preimage = _v4_global(_v4_scope, '_commit_preimage')(
        artifact,
        manifest,
        receipt,
        identity,
        date,
        run,
        hashes,
        predecessor=marker_predecessor,
        supersession=marker_supersession,
    )
    expected_marker = {**expected_marker_preimage, "commit_id": _v4_global(_v4_scope, '_canonical_sha')(expected_marker_preimage)}
    if marker != expected_marker:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict commit marker binding mismatch")
    result = {
        "trade_date": date,
        "run_id": run,
        "artifact": artifact,
        "manifest": manifest,
        "receipt": receipt,
        "commit": marker,
        "artifact_path": self.root / paths["artifact"],
        "manifest_path": self.root / paths["manifest"],
        "receipt_path": self.root / paths["receipt"],
        "commit_marker_path": self.root / paths["commit"],
        "artifact_bytes_sha256": artifact_result.sha256,
        "artifact_canonical_sha256": hashes["artifact_canonical_sha256"],
        "manifest_bytes_sha256": manifest_result.sha256,
        "manifest_canonical_sha256": hashes["manifest_canonical_sha256"],
        "receipt_bytes_sha256": receipt_result.sha256,
        "receipt_canonical_sha256": hashes["receipt_canonical_sha256"],
        "commit_id": marker["commit_id"],
        "commit_marker_bytes_sha256": marker_result.sha256,
        "commit_marker_canonical_sha256": _v4_global(_v4_scope, '_canonical_sha')(marker),
        "commit_marker_size_bytes": marker_result.size,
    }
    return result


def _StageAcquisitionUniverseCommit__verify_current_body(_v4_scope, /, self, secure, date, identity, expected):
    paths = _v4_global(_v4_scope, '_paths')(date, "placeholder")
    current_relative = paths["current"]
    try:
        current_result = secure.read_regular_bytes(current_relative)
    except _v4_global(_v4_scope, 'SecureEvidenceUnavailable') as error:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict current is missing or unavailable") from error
    if expected is not None and current_result.sha256 != expected:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict current raw SHA mismatch")
    current = _v4_global(_v4_scope, '_decode')(current_result, "strict current")
    if current.get("schema_version") != _v4_global(_v4_scope, 'STRICT_CURRENT_SCHEMA') or current.get("role") != _v4_global(_v4_scope, 'STRICT_ROLE') or current.get("trade_date") != date or current.get("status") not in {"READY", "READY_EMPTY"}:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict current identity/status mismatch")
    _v4_global(_v4_scope, '_check_identity')(current, identity, "strict current")
    _v4_global(_v4_scope, '_false_flags')(current, "strict current")
    if current.get("digest_mode") != _v4_global(_v4_scope, 'DIGEST_MODE'):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict current digest mode is invalid")
    current_predecessor = current.get("predecessor")
    previous_commit_id = current.get("previous_commit_id")
    previous_current_sha = current.get("previous_current_bytes_sha256")
    if (current_predecessor is None) != (
        previous_commit_id is None and previous_current_sha is None
    ):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict current predecessor fields are incomplete")
    run = _v4_global(_v4_scope, '_safe_run')(current.get("run_id"))
    chain = self._verify_run(secure, date, run, identity)
    marker_predecessor = chain["commit"].get("predecessor")
    if marker_predecessor is not None:
        _v4_global(_v4_scope, '_validate_lineage_predecessor')(marker_predecessor, date, identity)
    expected_current = _v4_global(_v4_scope, '_current')(chain["artifact"], identity, date, run, {
        "artifact_bytes_sha256": chain["artifact_bytes_sha256"],
        "artifact_canonical_sha256": chain["artifact_canonical_sha256"],
        "manifest_bytes_sha256": chain["manifest_bytes_sha256"],
        "manifest_canonical_sha256": chain["manifest_canonical_sha256"],
        "receipt_bytes_sha256": chain["receipt_bytes_sha256"],
        "receipt_canonical_sha256": chain["receipt_canonical_sha256"],
    }, chain["commit_id"], chain["commit_marker_bytes_sha256"], chain["commit_marker_canonical_sha256"], chain["commit_marker_size_bytes"], predecessor=marker_predecessor)
    if current != expected_current:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict current binding mismatch")
    marker_supersession = chain["commit"].get("supersession")
    if marker_predecessor is None:
        if marker_supersession is not None:
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict initial current has supersession lineage")
    else:
        self._verify_supersession_for_current(
            secure,
            date,
            identity,
            chain,
            current,
            current_result.sha256,
            marker_predecessor,
            marker_supersession,
        )
    return {**chain, "current": current, "current_path": self.root / current_relative, "current_bytes_sha256": current_result.sha256, "current_size_bytes": current_result.size}
