"""infrastructure.research_store: selection_publish (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _ResearchSelectionStore_publish_body(_v4_scope, /, self, payload, *, manager_overlay_source_successor_ref):
    """Publish one immutable run and advance only the selection current pointer.

        The optional successor proof is a writer-side authorization for a
        later MANUAL_RECOVERY evidence overlay.  It is intentionally not part
        of the persisted product schema or receipt.
        """

    target_trade_date = _v4_global(_v4_scope, 'validate_selection_research_product')(payload)
    run_id = _v4_global(_v4_scope, 'str')(payload["run_id"])
    if not self._RUN_ID.fullmatch(run_id):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection run_id")
    self._verify_product_sources(payload)
    artifact_relative = self._artifact_relative(target_trade_date, run_id)
    receipt_relative = self._receipt_relative(target_trade_date, run_id)
    run_manifest_relative = self._run_manifest_relative(target_trade_date, run_id)
    artifact_sha = self._canonical_sha(payload)
    receipt = self._receipt(payload, artifact_relative, artifact_sha)
    receipt_sha = self._canonical_sha(receipt)
    run_manifest = {
        "schema_version": "v3_5.selection_manifest.v1",
        "namespace": self._SELECTION_ROOT,
        "entries": {
            artifact_relative: artifact_sha,
            receipt_relative: receipt_sha,
        },
    }
    run_manifest_sha = self._canonical_sha(run_manifest)
    with self._lock():
        old_current = self._read_date_current(target_trade_date)
        old_payload = None
        if old_current is not None:
            old_payload = self._read_current_run(target_trade_date, old_current)
            old_snapshots = old_payload.get("snapshots", {})
            new_snapshots = payload.get("snapshots", {})
            overlay_2200_changed = (
                old_snapshots.get("2200", {}).get("status") == "READY"
                and old_snapshots.get("2200") != new_snapshots.get("2200")
            )
            if overlay_2200_changed:
                if manager_overlay_source_successor_ref is None:
                    raise self._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_REQUIRED",
                        "selection 2200 snapshot is immutable without an explicit successor proof",
                    )
                self._verify_manager_overlay_successor(
                    old_payload,
                    payload,
                    manager_overlay_source_successor_ref,
                )
            if _v4_global(_v4_scope, 'str')(old_current["generated_at"]) > _v4_global(_v4_scope, 'str')(payload["generated_at"]):
                raise _v4_global(_v4_scope, 'ValueError')("selection current cannot move backwards")
            for phase in ("0830", "0935", "1620"):
                if (
                    old_snapshots.get(phase, {}).get("status") == "READY"
                    and old_snapshots.get(phase) != new_snapshots.get(phase)
                ):
                    raise _v4_global(_v4_scope, 'ValueError')(f"selection {phase} snapshot is immutable")
        manifest = self._manifest()
        entries = _v4_global(_v4_scope, 'dict')(manifest["entries"])
        existing = entries.get(artifact_relative)
        artifact_path = self._path(artifact_relative)
        receipt_path = self._path(receipt_relative)
        run_manifest_path = self._path(run_manifest_relative)
        if existing and existing != artifact_sha:
            raise _v4_global(_v4_scope, 'ValueError')("conflicting selection run")
        if existing:
            if (
                entries.get(artifact_relative) != artifact_sha
                or entries.get(receipt_relative) != receipt_sha
                or entries.get(run_manifest_relative) != run_manifest_sha
                or not artifact_path.is_file()
                or self._raw_sha(artifact_path) != artifact_sha
                or not receipt_path.is_file()
                or self._raw_sha(receipt_path) != receipt_sha
                or self._read(receipt_relative) != receipt
                or not run_manifest_path.is_file()
                or self._raw_sha(run_manifest_path) != run_manifest_sha
                or self._read(run_manifest_relative) != run_manifest
            ):
                raise _v4_global(_v4_scope, 'ValueError')("selection existing artifact integrity mismatch")
        else:
            if artifact_path.exists() or receipt_path.exists() or run_manifest_path.exists():
                raise _v4_global(_v4_scope, 'ValueError')("orphan selection artifact or receipt")
            self._write(artifact_relative, payload)
            self._write(receipt_relative, receipt)
            self._write(run_manifest_relative, run_manifest)
            entries[artifact_relative] = artifact_sha
            entries[receipt_relative] = receipt_sha
            entries[run_manifest_relative] = run_manifest_sha
            manifest = {**manifest, "entries": entries}
            self._write_manifest(manifest)
        if existing and entries.get(run_manifest_relative) != run_manifest_sha:
            raise _v4_global(_v4_scope, 'ValueError')("selection run manifest index mismatch")
        manifest_sha = self._raw_sha(run_manifest_path)
        date_current_relative = self._date_current_relative(target_trade_date)
        date_current = self._current_pointer(
            payload,
            artifact_relative=artifact_relative,
            artifact_sha=artifact_sha,
            receipt_relative=receipt_relative,
            receipt_sha=receipt_sha,
            manifest_relative=run_manifest_relative,
            manifest_sha=manifest_sha,
        )
        current_updated = old_current != date_current
        if current_updated:
            self._write(date_current_relative, date_current)
        global_relative = self._CURRENT_RELATIVE
        global_path = self._path(global_relative)
        global_updated = False
        global_pointer = self._global_current_pointer(date_current)
        if global_path.is_file():
            old_global = self._read(global_relative)
            self._validate_global_current(old_global)
            if _v4_global(_v4_scope, 'str')(old_global["target_trade_date"]) > target_trade_date:
                global_pointer = old_global
            elif _v4_global(_v4_scope, 'str')(old_global["target_trade_date"]) == target_trade_date and old_global == global_pointer:
                global_pointer = old_global
            else:
                global_updated = old_global != global_pointer
        elif global_path.exists():
            raise _v4_global(_v4_scope, 'ValueError')("selection global current pointer is not a file")
        else:
            global_updated = True
        if global_updated:
            self._write(global_relative, global_pointer)
    return {
        "target_trade_date": target_trade_date,
        "run_id": run_id,
        "artifact_path": artifact_relative,
        "artifact_sha256": artifact_sha,
        "receipt_path": receipt_relative,
        "receipt_sha256": receipt_sha,
        "manifest_path": run_manifest_relative,
        "manifest_sha256": run_manifest_sha,
        "current_path": date_current_relative,
        "current_sha256": self._raw_sha(self._path(date_current_relative)),
        "global_current_path": global_relative,
        "global_current_sha256": self._raw_sha(self._path(global_relative)),
        "current_updated": current_updated,
        "global_current_updated": global_updated,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _ResearchSelectionStore_append_phase_body(_v4_scope, /, self, target_trade_date, phase, *, run_id, event_at, artifact_sha256, changes, observation, outcome):
    base = self.read_exact(target_trade_date)
    if base is None:
        raise _v4_global(_v4_scope, 'ValueError')("selection base ledger is not materialized")
    next_product = _v4_global(_v4_scope, 'append_selection_phase')(
        base,
        phase,
        run_id=run_id,
        event_at=event_at,
        artifact_sha256=artifact_sha256,
        changes=changes,
        observation=observation,
        outcome=outcome,
    )
    return self.publish(next_product)
