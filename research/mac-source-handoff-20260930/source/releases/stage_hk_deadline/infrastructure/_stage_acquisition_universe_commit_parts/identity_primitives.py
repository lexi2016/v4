"""infrastructure.stage_acquisition_universe_commit: identity_primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _EvidenceIdentity_validate_body(_v4_scope, /, self):
    for name in ("owner_id", "producer_id", "release_id", "lane_id"):
        value = _v4_global(_v4_scope, 'getattr')(self, name)
        if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value or value != value.strip():
            raise _v4_global(_v4_scope, 'StrictCommitError')(f"evidence identity {name} is missing")
        if _v4_global(_v4_scope, 'any')(token in value for token in ("/", "\\", "\x00")):
            raise _v4_global(_v4_scope, 'StrictCommitError')(f"evidence identity {name} is unsafe")
    if self.owner_id != _v4_global(_v4_scope, '_OWNER'):
        raise _v4_global(_v4_scope, 'StrictCommitError')("evidence identity owner_id mismatch")
    if self.producer_id != _v4_global(_v4_scope, '_PRODUCER'):
        raise _v4_global(_v4_scope, 'StrictCommitError')("evidence identity producer_id mismatch")
    if self.lane_id != _v4_global(_v4_scope, '_LANE'):
        raise _v4_global(_v4_scope, 'StrictCommitError')("evidence identity lane_id mismatch")


def __validate_lineage_predecessor_body(_v4_scope, /, predecessor, trade_date, identity):
    if not _v4_global(_v4_scope, 'isinstance')(predecessor, _v4_global(_v4_scope, 'Mapping')) or predecessor.get("trade_date") != trade_date:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict predecessor lineage/date is invalid")
    _v4_global(_v4_scope, '_safe_run')(predecessor.get("run_id"))
    if predecessor.get("role") != _v4_global(_v4_scope, 'STRICT_ROLE') or predecessor.get("status") not in {"READY", "READY_EMPTY"}:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict predecessor identity/status is invalid")
    for field in (
        "commit_id", "current_bytes_sha256", "artifact_bytes_sha256",
        "artifact_canonical_sha256", "manifest_bytes_sha256",
        "manifest_canonical_sha256", "receipt_bytes_sha256",
        "receipt_canonical_sha256",
    ):
        _v4_global(_v4_scope, '_require_sha')(predecessor.get(field), f"strict predecessor {field}")
    if not _v4_global(_v4_scope, 'isinstance')(predecessor.get("row_count"), _v4_global(_v4_scope, 'int')) or _v4_global(_v4_scope, 'isinstance')(predecessor.get("row_count"), _v4_global(_v4_scope, 'bool')) or predecessor["row_count"] < 0:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict predecessor row_count is invalid")
    _v4_global(_v4_scope, '_check_identity')(predecessor, identity, "strict predecessor")
    _v4_global(_v4_scope, '_false_flags')(predecessor, "strict predecessor")


def __validate_marker_supersession_body(_v4_scope, /, supersession, trade_date, identity):
    if not _v4_global(_v4_scope, 'isinstance')(supersession, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict commit marker supersession is invalid")
    relative = _v4_global(_v4_scope, '_require_nonempty_text')(supersession.get("relative"), "strict supersession path")
    if not relative.startswith(f"supersessions/{trade_date}/{_v4_global(_v4_scope, 'STRICT_ROLE')}/"):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict commit marker supersession path mismatch")
    _v4_global(_v4_scope, '_require_sha')(supersession.get("expected_current_bytes_sha256"), "strict marker current SHA")
    _v4_global(_v4_scope, '_require_sha')(supersession.get("successor_artifact_canonical_sha256"), "strict marker artifact SHA")
    _v4_global(_v4_scope, '_safe_run')(supersession.get("successor_run_id"))
    _v4_global(_v4_scope, '_require_nonempty_text')(supersession.get("reason"), "strict marker supersession reason")
    if supersession.get("evolution") != _v4_global(_v4_scope, 'STRICT_SUCCESSOR_EVOLUTION'):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict marker supersession evolution is invalid")
    target_current = _v4_global(_v4_scope, '_paths')(trade_date, "placeholder")["current"]
    if (
        supersession.get("target_current_relative") != target_current
        or supersession.get("successor_current_relative") != target_current
    ):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict marker supersession target path mismatch")
    if "owner_id" in supersession:
        _v4_global(_v4_scope, '_check_identity')(supersession, identity, "strict marker supersession")


def _StageAcquisitionUniverseCommit__supersession_relative_body(_v4_scope, /, date, expected_current_sha256, successor_artifact_canonical_sha256):
    _v4_global(_v4_scope, '_require_sha')(expected_current_sha256, "strict supersession expected current SHA")
    _v4_global(_v4_scope, '_require_sha')(
        successor_artifact_canonical_sha256,
        "strict supersession successor artifact SHA",
    )
    return (
        f"supersessions/{date}/{_v4_global(_v4_scope, 'STRICT_ROLE')}/"
        f"{expected_current_sha256}-{successor_artifact_canonical_sha256}/receipt.json"
    )


def _StageAcquisitionUniverseCommit__chain_hashes_body(_v4_scope, /, chain):
    return {
        name: chain[name]
        for name in (
            "artifact_bytes_sha256",
            "artifact_canonical_sha256",
            "manifest_bytes_sha256",
            "manifest_canonical_sha256",
            "receipt_bytes_sha256",
            "receipt_canonical_sha256",
        )
    }


def _StageAcquisitionUniverseCommit__result_body(_v4_scope, /, chain, *, idempotent):
    return {
        "status": chain["current"]["status"],
        "idempotent": idempotent,
        "trade_date": chain["trade_date"],
        "role": _v4_global(_v4_scope, 'STRICT_ROLE'),
        "run_id": chain["run_id"],
        "row_count": chain["current"]["row_count"],
        "artifact_bytes_sha256": chain["artifact_bytes_sha256"],
        "artifact_canonical_sha256": chain["artifact_canonical_sha256"],
        "manifest_bytes_sha256": chain["manifest_bytes_sha256"],
        "manifest_canonical_sha256": chain["manifest_canonical_sha256"],
        "receipt_bytes_sha256": chain["receipt_bytes_sha256"],
        "receipt_canonical_sha256": chain["receipt_canonical_sha256"],
        "commit_id": chain["commit_id"],
        "commit_marker_bytes_sha256": chain["commit_marker_bytes_sha256"],
        "commit_marker_canonical_sha256": chain["commit_marker_canonical_sha256"],
        "digest_mode": _v4_global(_v4_scope, 'DIGEST_MODE'),
        "artifact_path": chain["artifact_path"],
        "manifest_path": chain["manifest_path"],
        "receipt_path": chain["receipt_path"],
        "commit_marker_path": chain["commit_marker_path"],
        "current_path": chain["current_path"],
        "current_bytes_sha256": chain["current_bytes_sha256"],
        # Return the verified strict artifact to callers.  The Gate2 V2
        # input is never exposed as if it were the authoritative current.
        "artifact": _v4_global(_v4_scope, 'dict')(chain["artifact"]),
    }


def _StageAcquisitionUniverseCommit__pool_membership_body(_v4_scope, /, artifact):
    membership = {pool_id: _v4_global(_v4_scope, 'set')() for pool_id in _v4_global(_v4_scope, 'REQUIRED_A_STAGE_POOL_IDS')}
    sources = artifact.get("code_sources")
    if not _v4_global(_v4_scope, 'isinstance')(sources, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor code source membership is missing")
    for code, pool_ids in sources.items():
        if not _v4_global(_v4_scope, 'isinstance')(pool_ids, _v4_global(_v4_scope, 'list')):
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor code source membership is invalid")
        for pool_id in pool_ids:
            if pool_id not in membership:
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor code source pool is invalid")
            membership[pool_id].add(_v4_global(_v4_scope, 'str')(code))
    return membership


def _StageAcquisitionUniverseCommit__successor_result_body(_v4_scope, /, chain, receipt, receipt_path, *, idempotent):
    result = _v4_global(_v4_scope, 'StageAcquisitionUniverseCommit')._result(chain, idempotent=idempotent)
    result.update(
        {
            "status": "SUPERSEDED",
            "current_status": chain["current"]["status"],
            "supersession_receipt_path": receipt_path,
            "supersession_receipt": _v4_global(_v4_scope, 'dict')(receipt),
            "predecessor": receipt.get("predecessor"),
        }
    )
    return result


def _StageAcquisitionUniverseCommit_read_current_body(_v4_scope, /, self, trade_date, *, identity):
    date = _v4_global(_v4_scope, '_safe_date')(trade_date)
    try:
        with self._secure() as secure:
            if identity is None:
                try:
                    current_bytes = secure.read_regular_bytes(_v4_global(_v4_scope, '_paths')(date, "placeholder")["current"])
                    current_payload = _v4_global(_v4_scope, '_decode')(current_bytes, "strict current")
                    identity = _v4_global(_v4_scope, 'EvidenceIdentity').from_mapping(current_payload)
                except (_v4_global(_v4_scope, 'SecureEvidenceUnavailable'), _v4_global(_v4_scope, 'SecureEvidenceConflict')) as error:
                    raise _v4_global(_v4_scope, 'StrictCommitError')("strict current is missing or unavailable") from error
            if not _v4_global(_v4_scope, 'isinstance')(identity, _v4_global(_v4_scope, 'EvidenceIdentity')):
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict read requires EvidenceIdentity")
            identity.validate()
            return self._verify_current(secure, date, identity)
    except (_v4_global(_v4_scope, 'SecureEvidenceUnavailable'), _v4_global(_v4_scope, 'SecureEvidenceConflict')) as error:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict current is missing or unavailable") from error
