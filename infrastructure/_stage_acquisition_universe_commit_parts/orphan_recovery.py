"""infrastructure.stage_acquisition_universe_commit: orphan_recovery (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _StageAcquisitionUniverseCommit__scan_orphans_body(_v4_scope, /, self, secure, date, identity, selected_run):
    root = self._run_root(date)
    if not root.exists():
        return [], False
    if root.is_symlink() or not root.is_dir():
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict run root is unsafe")
    committed: list[dict[str, Any]] = []
    selected_partial = False
    for entry in _v4_global(_v4_scope, 'sorted')(root.iterdir(), key=lambda item: item.name):
        run = _v4_global(_v4_scope, '_safe_run')(entry.name)
        if entry.is_symlink() or not entry.is_dir():
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict run entry is unsafe")
        paths = _v4_global(_v4_scope, '_paths')(date, run)
        present = [_v4_global(_v4_scope, 'bool')((self.root / paths[name]).exists()) for name in ("artifact", "manifest", "receipt", "commit")]
        if not _v4_global(_v4_scope, 'any')(present):
            raise _v4_global(_v4_scope, 'StrictCommitError')("strict run entry is empty")
        if present[3]:
            try:
                committed.append(self._verify_run(secure, date, run, identity))
            except _v4_global(_v4_scope, 'StrictCommitError') as error:
                raise _v4_global(_v4_scope, 'StrictCommitError')(f"strict orphan {run} is malformed: {error}") from error
        elif run == selected_run:
            selected_partial = True
        else:
            raise _v4_global(_v4_scope, 'StrictCommitError')(f"strict orphan {run} is incomplete")
    return committed, selected_partial


def _StageAcquisitionUniverseCommit__recover_committed_successor_orphan_body(_v4_scope, /, self, secure, date, identity, current, current_sha256, expected_current_sha256, artifact_canonical_sha256, reason, selected_run, supersession_relative):
    """Resume one committed successor that stopped before receipt/CAS.

        The run marker is the durable boundary for a successor.  A retry first
        searches committed runs bound to the same predecessor raw-current
        SHA; it never creates a parallel run when exactly one such orphan is
        recoverable.  Multiple or conflicting matches are fail-closed.
        """

    committed, _selected_partial = self._scan_orphans(
        secure, date, identity, selected_run
    )
    current_successor_orphans: list[dict[str, Any]] = []
    for candidate in committed:
        marker_predecessor = candidate["commit"].get("predecessor")
        if marker_predecessor is None:
            continue
        if marker_predecessor.get("current_bytes_sha256") != current_sha256:
            continue
        if candidate["artifact_canonical_sha256"] != artifact_canonical_sha256:
            raise _v4_global(_v4_scope, 'StrictCommitError')(
                "strict successor committed orphan conflicts with payload"
            )
        current_successor_orphans.append(candidate)

    if _v4_global(_v4_scope, 'len')(current_successor_orphans) > 1:
        raise _v4_global(_v4_scope, 'StrictCommitError')(
            "multiple strict successor committed orphans are ambiguous"
        )
    if not current_successor_orphans:
        return None

    orphan = current_successor_orphans[0]
    predecessor = self._predecessor_summary(current, current_sha256)
    if orphan["commit"].get("predecessor") != predecessor:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor orphan predecessor conflict")
    marker_supersession = orphan["commit"].get("supersession")
    if marker_supersession is None:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor orphan marker is incomplete")
    _v4_global(_v4_scope, '_validate_marker_supersession')(marker_supersession, date, identity)
    if (
        marker_supersession.get("relative") != supersession_relative
        or marker_supersession.get("expected_current_bytes_sha256")
        != expected_current_sha256
        or marker_supersession.get("successor_artifact_canonical_sha256")
        != artifact_canonical_sha256
        or marker_supersession.get("successor_run_id") != orphan["run_id"]
        or marker_supersession.get("reason") != reason
    ):
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict successor orphan request conflict")

    successor_pointer = self._current_from_chain(
        orphan,
        identity,
        date,
        predecessor=predecessor,
    )
    supersession = self._build_supersession_receipt(
        date=date,
        identity=identity,
        reason=reason,
        expected_current_sha256=expected_current_sha256,
        predecessor=predecessor,
        previous_current=current["current"],
        successor_chain=orphan,
        successor_current=successor_pointer,
        target_current_relative=_v4_global(_v4_scope, '_paths')(date, "placeholder")["current"],
    )
    self._write(secure, supersession_relative, supersession)
    receipt_result = secure.read_regular_bytes(supersession_relative)
    receipt_check = _v4_global(_v4_scope, '_decode')(receipt_result, "strict supersession receipt")
    if receipt_check != supersession:
        raise _v4_global(_v4_scope, 'StrictCommitError')("strict supersession receipt verification failed")
    secure.replace_current_cas(
        _v4_global(_v4_scope, '_paths')(date, "placeholder")["current"],
        expected_current_bytes_sha256=current_sha256,
        new_bytes=_v4_global(_v4_scope, '_canonical_bytes')(successor_pointer),
    )
    verified = self._verify_current(secure, date, identity)
    return self._successor_result(
        verified,
        supersession,
        self.root / supersession_relative,
        idempotent=True,
    )
