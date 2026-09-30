"""infrastructure.stage_acquisition_universe_commit: supersession_verification (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageAcquisitionUniverseCommit__verify_supersession_for_current_body(_v4_scope, /, self, secure, date, identity, chain, current, current_sha256, predecessor, marker_supersession):
    """Verify the immutable receipt that explains a successor current."""

    if marker_supersession is None:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor current has no supersession receipt")
    _v4_global(_v4_scope, '_validate_marker_supersession')(marker_supersession, date, identity)
    relative = marker_supersession["relative"]
    try:
        result = secure.read_regular_bytes(relative)
    except (_v4_global(_v4_scope, 'SecureEvidenceUnavailable'), _v4_global(_v4_scope, 'SecureEvidenceConflict')) as error:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor supersession receipt is unavailable") from error
    receipt = _v4_global(_v4_scope, '_decode')(result, "strict supersession receipt")
    if marker_supersession.get("expected_current_bytes_sha256") != receipt.get(
        "expected_current_bytes_sha256"
    ):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession marker CAS mismatch")
    if marker_supersession.get("successor_run_id") != chain["run_id"]:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession marker run mismatch")
    if marker_supersession.get("successor_artifact_canonical_sha256") != chain[
        "artifact_canonical_sha256"
    ]:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession marker artifact mismatch")
    if relative != self._supersession_relative(
        date,
        marker_supersession["expected_current_bytes_sha256"],
        chain["artifact_canonical_sha256"],
    ):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession marker path mismatch")

    # Re-verify the predecessor run and rebuild its current pointer.  The
    # receipt's previous_current object is therefore committed by the
    # predecessor chain, rather than accepted merely because its own SHA
    # field happens to be self-consistent.
    predecessor_run = _v4_global(_v4_scope, '_safe_run')(predecessor.get("run_id"))
    predecessor_chain = self._verify_run(secure, date, predecessor_run, identity)
    previous_current = self._current_from_chain(
        predecessor_chain, identity, date
    )
    if _v4_global(_v4_scope, '_raw_sha')(_v4_global(_v4_scope, '_canonical_bytes')(previous_current)) != predecessor[
        "current_bytes_sha256"
    ]:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession previous current bytes mismatch")
    expected_predecessor = self._predecessor_summary(
        {**predecessor_chain, "current": previous_current},
        predecessor["current_bytes_sha256"],
    )
    if _v4_global(_v4_scope, 'dict')(predecessor) != expected_predecessor:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession predecessor lineage mismatch")

    expected_receipt = self._build_supersession_receipt(
        date=date,
        identity=identity,
        reason=marker_supersession["reason"],
        expected_current_sha256=marker_supersession[
            "expected_current_bytes_sha256"
        ],
        predecessor=predecessor,
        previous_current=previous_current,
        successor_chain=chain,
        successor_current=current,
        target_current_relative=marker_supersession["target_current_relative"],
    )
    if receipt != expected_receipt:
        raise _v4_global(_v4_scope, 'StrictCommitError')(
            "strict supersession receipt canonical binding mismatch "
            "(successor current or request)"
        )
    if _v4_global(_v4_scope, '_raw_sha')(_v4_global(_v4_scope, '_canonical_bytes')(current)) != current_sha256:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession successor current bytes mismatch")


def _StageAcquisitionUniverseCommit__verify_supersession_for_predecessor_body(_v4_scope, /, self, secure, date, identity, receipt, receipt_relative, predecessor_chain, expected_current_sha256, reason, requested_artifact_canonical_sha256):
    """Verify a receipt left before CAS so a safe retry can resume it."""

    if receipt.get("schema_version") != _v4_global(_v4_scope, 'STRICT_SUPERSESSION_SCHEMA'):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession receipt schema mismatch")
    if receipt.get("role") != _v4_global(_v4_scope, 'STRICT_ROLE') or receipt.get("trade_date") != date:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession receipt identity mismatch")
    if receipt.get("status") != "SUPERSEDED" or receipt.get("reason") != reason:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession receipt request conflict")
    _v4_global(_v4_scope, '_check_identity')(receipt, identity, "strict supersession receipt")
    _v4_global(_v4_scope, '_false_flags')(receipt, "strict supersession receipt")
    predecessor_sha = predecessor_chain["current_bytes_sha256"]
    if receipt.get("expected_current_bytes_sha256") != expected_current_sha256 or receipt.get("previous_current_bytes_sha256") != predecessor_sha:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession predecessor current SHA mismatch")
    predecessor = self._predecessor_summary(predecessor_chain, predecessor_sha)
    if receipt.get("previous_commit_id") != predecessor["commit_id"] or receipt.get("predecessor") != predecessor:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession predecessor lineage mismatch")
    previous_current = predecessor_chain["current"]
    if _v4_global(_v4_scope, '_raw_sha')(_v4_global(_v4_scope, '_canonical_bytes')(previous_current)) != predecessor_sha:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession previous current bytes mismatch")
    target_current = _v4_global(_v4_scope, '_paths')(date, "placeholder")["current"]
    if (
        receipt.get("target_current_relative") != target_current
        or receipt.get("successor_current_relative") != target_current
        or receipt_relative != self._supersession_relative(
            date, expected_current_sha256, requested_artifact_canonical_sha256
        )
    ):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession receipt path mismatch")
    successor_run = _v4_global(_v4_scope, '_safe_run')(receipt.get("successor_run_id"))
    try:
        successor_chain = self._verify_run(secure, date, successor_run, identity)
    except _v4_global(_v4_scope, 'StrictCommitError') as error:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession successor chain is unavailable") from error
    if successor_chain["artifact_canonical_sha256"] != requested_artifact_canonical_sha256:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession successor artifact conflict")
    marker_supersession = successor_chain["commit"].get("supersession")
    if marker_supersession is None:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession successor marker is missing")
    _v4_global(_v4_scope, '_validate_marker_supersession')(marker_supersession, date, identity)
    if (
        marker_supersession.get("relative") != receipt_relative
        or marker_supersession.get("reason") != reason
        or marker_supersession.get("expected_current_bytes_sha256")
        != expected_current_sha256
        or marker_supersession.get("successor_artifact_canonical_sha256")
        != requested_artifact_canonical_sha256
        or marker_supersession.get("successor_run_id") != successor_run
    ):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession marker request conflict")
    successor_current = self._current_from_chain(
        successor_chain,
        identity,
        date,
        predecessor=predecessor,
    )
    expected_receipt = self._build_supersession_receipt(
        date=date,
        identity=identity,
        reason=reason,
        expected_current_sha256=expected_current_sha256,
        predecessor=predecessor,
        previous_current=previous_current,
        successor_chain=successor_chain,
        successor_current=successor_current,
        target_current_relative=target_current,
    )
    if receipt != expected_receipt:
        raise _v4_global(_v4_scope, 'StrictCommitError')(
            "strict supersession receipt canonical binding mismatch "
            "(successor current or request)"
        )
    return successor_chain, successor_current
