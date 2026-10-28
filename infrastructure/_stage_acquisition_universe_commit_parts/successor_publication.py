"""infrastructure.stage_acquisition_universe_commit: successor_publication (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageAcquisitionUniverseCommit_publish_successor_body(_v4_scope, /, self, payload, *, expected_current_sha256, reason, run_id, identity):
    """Publish a same-day strict successor using only raw current CAS."""

    if not _v4_global(_v4_scope, 'isinstance')(identity, _v4_global(_v4_scope, 'EvidenceIdentity')):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor publication requires evidence identity")
    identity.validate()
    _v4_global(_v4_scope, '_reject_unsafe_strict_fields')(payload)
    expected = _v4_global(_v4_scope, '_require_sha')(
        expected_current_sha256,
        "strict successor expected current raw SHA",
    ).lower()
    reason_text = _v4_global(_v4_scope, '_require_nonempty_text')(reason, "strict successor reason")
    date = _v4_global(_v4_scope, '_safe_date')(payload.get("trade_date") if _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'Mapping')) else None)
    try:
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
    selected_run = _v4_global(_v4_scope, '_safe_run')(
        run_id or f"{date}-{_v4_global(_v4_scope, 'STRICT_ROLE').lower()}-{artifact_canonical[:12]}"
    )
    paths = _v4_global(_v4_scope, '_paths')(date, selected_run)
    manifest = _v4_global(_v4_scope, '_manifest')(
        artifact,
        identity,
        date,
        selected_run,
        _v4_global(_v4_scope, '_raw_sha')(artifact_bytes),
        artifact_canonical,
        _v4_global(_v4_scope, 'len')(artifact_bytes),
    )
    manifest_bytes = _v4_global(_v4_scope, '_canonical_bytes')(manifest)
    manifest_canonical = _v4_global(_v4_scope, '_canonical_sha')(manifest)
    receipt = _v4_global(_v4_scope, '_receipt')(
        artifact,
        manifest,
        identity,
        date,
        selected_run,
        _v4_global(_v4_scope, '_raw_sha')(artifact_bytes),
        artifact_canonical,
        _v4_global(_v4_scope, '_raw_sha')(manifest_bytes),
        manifest_canonical,
        _v4_global(_v4_scope, 'len')(manifest_bytes),
    )
    supersession_relative = self._supersession_relative(
        date, expected, artifact_canonical
    )
    lock = self._publication_locks()
    try:
        with lock as lock_lease, self._secure() as secure:
            _v4_global(_v4_scope, '_revalidate_physical_snapshot')(
                self.preselection_source_root, date, snapshot, lock_lease=lock_lease
            )
            try:
                current = self._verify_current(secure, date, identity)
            except _v4_global(_v4_scope, 'StrictCommitError') as error:
                raise _v4_global(_v4_scope, 'StrictCommitError')(
                    f"strict successor current cannot be confirmed: {error}"
                ) from error
            current_sha = current["current_bytes_sha256"]
            if expected == current["artifact_bytes_sha256"]:
                raise _v4_global(_v4_scope, 'StrictCommitError')(
                    "strict successor artifact SHA is not a current CAS token"
                )

            existing_receipt: dict[str, Any] | None = None
            try:
                existing_result = secure.read_regular_bytes(supersession_relative)
            except _v4_global(_v4_scope, 'SecureEvidenceUnavailable'):
                existing_result = None
            if existing_result is not None:
                existing_receipt = _v4_global(_v4_scope, '_decode')(
                    existing_result, "strict supersession receipt"
                )
                if current["run_id"] == existing_receipt.get("successor_run_id"):
                    # The current verifier has already checked the receipt
                    # against this successor.  Compare the request fields
                    # here so a changed reason or artifact cannot be
                    # mistaken for an idempotent retry.
                    if (
                        existing_receipt.get("reason") != reason_text
                        or existing_receipt.get("expected_current_bytes_sha256") != expected
                        or existing_receipt.get("successor", {}).get("artifact_canonical_sha256") != artifact_canonical
                    ):
                        raise _v4_global(_v4_scope, 'StrictCommitError')(
                            "strict supersession receipt request conflict"
                        )
                    return self._successor_result(
                        current,
                        existing_receipt,
                        self.root / supersession_relative,
                        idempotent=True,
                    )
                if current_sha == expected:
                    _successor_chain, successor_pointer = self._verify_supersession_for_predecessor(
                        secure,
                        date,
                        identity,
                        existing_receipt,
                        supersession_relative,
                        current,
                        expected,
                        reason_text,
                        artifact_canonical,
                    )
                    successor_bytes = _v4_global(_v4_scope, '_canonical_bytes')(successor_pointer)
                    secure.replace_current_cas(
                        paths["current"],
                        expected_current_bytes_sha256=expected,
                        new_bytes=successor_bytes,
                    )
                    verified = self._verify_current(secure, date, identity)
                    return self._successor_result(
                        verified,
                        existing_receipt,
                        self.root / supersession_relative,
                        idempotent=True,
                    )
                raise _v4_global(_v4_scope, 'StrictCommitError')(
                    "strict successor current raw SHA mismatch"
                )
            if expected != current_sha:
                suffix = " (artifact SHA is not a current CAS token)" if expected == current["artifact_bytes_sha256"] else ""
                raise _v4_global(_v4_scope, 'StrictCommitError')(
                    f"strict successor current raw SHA mismatch{suffix}"
                )

            recovered = self._recover_committed_successor_orphan(
                secure,
                date,
                identity,
                current,
                current_sha,
                expected,
                artifact_canonical,
                reason_text,
                selected_run,
                supersession_relative,
            )
            if recovered is not None:
                return recovered

            # A fully equal strict artifact is an ordinary idempotent
            # retry.  It is not a successor and does not create lineage.
            if current["artifact_canonical_sha256"] == artifact_canonical:
                return self._result(current, idempotent=True)
            if selected_run == current["run_id"]:
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor run_id equals current run")

            predecessor = self._predecessor_summary(current, current_sha)
            self._assert_successor_evolution(current, artifact)
            marker_supersession = {
                "relative": supersession_relative,
                "expected_current_bytes_sha256": expected,
                "successor_artifact_canonical_sha256": artifact_canonical,
                "successor_run_id": selected_run,
                "reason": reason_text,
                "evolution": _v4_global(_v4_scope, 'STRICT_SUCCESSOR_EVOLUTION'),
                "target_current_relative": paths["current"],
                "successor_current_relative": paths["current"],
            }
            marker_preimage = _v4_global(_v4_scope, '_commit_preimage')(
                artifact,
                manifest,
                receipt,
                identity,
                date,
                selected_run,
                {
                    "artifact_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(artifact_bytes),
                    "artifact_canonical_sha256": artifact_canonical,
                    "manifest_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(manifest_bytes),
                    "manifest_canonical_sha256": manifest_canonical,
                    "receipt_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(_v4_global(_v4_scope, '_canonical_bytes')(receipt)),
                    "receipt_canonical_sha256": _v4_global(_v4_scope, '_canonical_sha')(receipt),
                },
                predecessor=predecessor,
                supersession=marker_supersession,
            )
            marker = {**marker_preimage, "commit_id": _v4_global(_v4_scope, '_canonical_sha')(marker_preimage)}

            self._write(secure, paths["artifact"], artifact)
            self._write(secure, paths["manifest"], manifest)
            self._write(secure, paths["receipt"], receipt)
            hashes = {
                "artifact_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(artifact_bytes),
                "artifact_canonical_sha256": artifact_canonical,
                "manifest_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(manifest_bytes),
                "manifest_canonical_sha256": manifest_canonical,
                "receipt_bytes_sha256": _v4_global(_v4_scope, '_raw_sha')(_v4_global(_v4_scope, '_canonical_bytes')(receipt)),
                "receipt_canonical_sha256": _v4_global(_v4_scope, '_canonical_sha')(receipt),
            }
            self._write(secure, paths["commit"], marker)
            self._fsync_run_dir(secure, date, selected_run)
            successor_chain = self._verify_run(secure, date, selected_run, identity)
            pointer = _v4_global(_v4_scope, '_current')(
                artifact,
                identity,
                date,
                selected_run,
                hashes,
                successor_chain["commit_id"],
                successor_chain["commit_marker_bytes_sha256"],
                successor_chain["commit_marker_canonical_sha256"],
                successor_chain["commit_marker_size_bytes"],
                predecessor=predecessor,
            )
            pointer_bytes = _v4_global(_v4_scope, '_canonical_bytes')(pointer)
            supersession = self._build_supersession_receipt(
                date=date,
                identity=identity,
                reason=reason_text,
                expected_current_sha256=expected,
                predecessor=predecessor,
                previous_current=current["current"],
                successor_chain=successor_chain,
                successor_current=pointer,
                target_current_relative=paths["current"],
            )
            self._write(secure, supersession_relative, supersession)
            receipt_result = secure.read_regular_bytes(supersession_relative)
            receipt_check = _v4_global(_v4_scope, '_decode')(receipt_result, "strict supersession receipt")
            if receipt_check != supersession:
                raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession receipt verification failed")
            secure.replace_current_cas(
                paths["current"],
                expected_current_bytes_sha256=current_sha,
                new_bytes=pointer_bytes,
            )
            verified = self._verify_current(secure, date, identity)
            return self._successor_result(
                verified, supersession, self.root / supersession_relative, idempotent=False
            )
    except (_v4_global(_v4_scope, 'SecureEvidenceUnavailable'), _v4_global(_v4_scope, 'SecureEvidenceConflict')) as error:
        raise _v4_global(_v4_scope, 'StrictCommitError')(_v4_global(_v4_scope, 'str')(error)) from error


def _StrictStageAcquisitionUniverseFacade_publish_successor_body(_v4_scope, /, self, payload, *, expected_current_sha256, reason, run_id, identity):
    if identity is None:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor publication requires evidence identity")
    return _v4_global(_v4_scope, 'StageAcquisitionUniverseCommit')(self.root).publish_successor(
        payload,
        expected_current_sha256=expected_current_sha256,
        reason=reason,
        run_id=run_id,
        identity=identity,
    )
