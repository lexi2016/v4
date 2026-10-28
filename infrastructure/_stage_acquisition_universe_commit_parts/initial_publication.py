"""infrastructure.stage_acquisition_universe_commit: initial_publication (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageAcquisitionUniverseCommit_publish_body(_v4_scope, /, self, payload, *, run_id, identity):
    if not _v4_global(_v4_scope, 'isinstance')(identity, _v4_global(_v4_scope, 'EvidenceIdentity')):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict publication requires evidence identity")
    identity.validate()
    _v4_global(_v4_scope, '_reject_unsafe_strict_fields')(payload)
    date = _v4_global(_v4_scope, '_safe_date')(payload.get("trade_date") if _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')) else None)
    try:
        # This read is deliberately inside the strict writer, immediately
        # before any artifact bytes are computed or written.  A caller's
        # in-memory projection is therefore only a proposal; the six
        # physical pool trios remain the authority at publication time.
        snapshot = _v4_global(_v4_scope, 'read_strict_a_preselection_snapshot')(self.preselection_source_root, date)
        _v4_global(_v4_scope, '_validate_physical_input')(payload, snapshot)
        artifact = _v4_global(_v4_scope, '_normalize_strict_artifact')(payload, snapshot, identity)
    except (_v4_global(_v4_scope, 'StageAcquisitionContractError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'StrictCommitError')(
            f"required A pool strict physical snapshot cannot be confirmed: {error}"
        ) from error
    self._bind_source_root(artifact)
    _v4_global(_v4_scope, '_validate_artifact')(artifact, date, identity)
    artifact_bytes = _v4_global(_v4_scope, '_canonical_bytes')(artifact)
    artifact_canonical = _v4_global(_v4_scope, '_canonical_sha')(artifact)
    selected_run = _v4_global(_v4_scope, '_safe_run')(run_id or f"{date}-{_v4_global(_v4_scope, 'STRICT_ROLE').lower()}-{artifact_canonical[:12]}")
    paths = _v4_global(_v4_scope, '_paths')(date, selected_run)
    manifest = _v4_global(_v4_scope, '_manifest')(artifact, identity, date, selected_run, _v4_global(_v4_scope, '_raw_sha')(artifact_bytes), artifact_canonical, _v4_global(_v4_scope, 'len')(artifact_bytes))
    manifest_bytes = _v4_global(_v4_scope, '_canonical_bytes')(manifest)
    manifest_canonical = _v4_global(_v4_scope, '_canonical_sha')(manifest)
    receipt = _v4_global(_v4_scope, '_receipt')(artifact, manifest, identity, date, selected_run, _v4_global(_v4_scope, '_raw_sha')(artifact_bytes), artifact_canonical, _v4_global(_v4_scope, '_raw_sha')(manifest_bytes), manifest_canonical, _v4_global(_v4_scope, 'len')(manifest_bytes))
    receipt_bytes = _v4_global(_v4_scope, '_canonical_bytes')(receipt)
    lock = self._publication_locks()
    try:
        with lock as lock_lease, self._secure() as secure:
            _v4_global(_v4_scope, '_revalidate_physical_snapshot')(
                self.preselection_source_root, date, snapshot, lock_lease=lock_lease
            )
            try:
                current = self._verify_current(secure, date, identity)
            except _v4_global(_v4_scope, 'StrictCommitError') as error:
                if "missing or unavailable" not in _v4_global(_v4_scope, 'str')(error):
                    raise
                current = None
            if current is not None:
                if current["artifact_canonical_sha256"] == artifact_canonical and current["artifact"]["trade_date"] == date:
                    return self._result(current, idempotent=True)
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict exact-date current conflict")
            committed, _selected_partial = self._scan_orphans(secure, date, identity, selected_run)
            if _v4_global(_v4_scope, 'len')(committed) > 1:
                raise _v4_global(_v4_scope, 'StrictCommitError')("multiple strict committed orphans are ambiguous")
            if committed:
                orphan = committed[0]
                if orphan["artifact_canonical_sha256"] != artifact_canonical:
                    raise _v4_global(_v4_scope, 'StrictCommitError')("strict committed orphan conflicts with payload")
                hashes = {name: orphan[name] for name in ("artifact_bytes_sha256", "artifact_canonical_sha256", "manifest_bytes_sha256", "manifest_canonical_sha256", "receipt_bytes_sha256", "receipt_canonical_sha256")}
                pointer = _v4_global(_v4_scope, '_current')(orphan["artifact"], identity, date, orphan["run_id"], hashes, orphan["commit_id"], orphan["commit_marker_bytes_sha256"], orphan["commit_marker_canonical_sha256"], orphan["commit_marker_size_bytes"])
                secure.replace_current_cas(_v4_global(_v4_scope, '_paths')(date, orphan["run_id"])["current"], expected_current_bytes_sha256=None, new_bytes=_v4_global(_v4_scope, '_canonical_bytes')(pointer))
                verified = self._verify_current(secure, date, identity)
                return self._result(verified, idempotent=True)

            self._write(secure, paths["artifact"], artifact)
            self._write(secure, paths["manifest"], manifest)
            self._write(secure, paths["receipt"], receipt)
            hashes = {
                "artifact_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(artifact_bytes),
                "artifact_canonical_sha256": artifact_canonical,
                "manifest_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(manifest_bytes),
                "manifest_canonical_sha256": manifest_canonical,
                "receipt_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(receipt_bytes),
                "receipt_canonical_sha256": _v4_global(_v4_scope, '_canonical_sha')(receipt),
            }
            marker_preimage = _v4_global(_v4_scope, '_commit_preimage')(artifact, manifest, receipt, identity, date, selected_run, hashes)
            marker = {**marker_preimage, "commit_id": _v4_global(_v4_scope, '_canonical_sha')(marker_preimage)}
            self._write(secure, paths["commit"], marker)
            self._fsync_run_dir(secure, date, selected_run)
            committed_chain = self._verify_run(secure, date, selected_run, identity)
            pointer = _v4_global(_v4_scope, '_current')(artifact, identity, date, selected_run, hashes, committed_chain["commit_id"], committed_chain["commit_marker_bytes_sha256"], committed_chain["commit_marker_canonical_sha256"], committed_chain["commit_marker_size_bytes"])
            secure.replace_current_cas(paths["current"], expected_current_bytes_sha256=None, new_bytes=_v4_global(_v4_scope, '_canonical_bytes')(pointer))
            verified = self._verify_current(secure, date, identity)
            return self._result(verified, idempotent=False)
    except (_v4_global(_v4_scope, 'SecureEvidenceUnavailable'), _v4_global(_v4_scope, 'SecureEvidenceConflict')) as error:
        raise _v4_global(_v4_scope, 'StrictCommitError')(_v4_global(_v4_scope, 'str')(error)) from error
