"""Independent, exact-date storage for V3.5 preselection pools."""
from __future__ import annotations

import sys
from infrastructure import preselection_pool_transactions as _pool_transactions
from infrastructure import preselection_pool_readers as _pool_readers
from infrastructure import preselection_pool_sources as _pool_sources

import hashlib
import errno
import fcntl
import json
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping

from infrastructure.data_store import _canonical_bytes, _date, _sha256
from infrastructure.interprocess_lock import (
    assert_owned_interprocess_lock,
    owned_interprocess_lock,
)
from infrastructure.owned_path import resolve_owned_path
from infrastructure.owned_io import SafeRoot
from infrastructure.trading_safety import assert_safe_tree
from infrastructure.scope_gate import (
    GateConfigurationError,
    StoreGateContext,
    _load_permit_at,
    _open_control_directory,
    assert_write_allowed,
    update_gate_state,
)


POOL_ORDER = (
    "a_d1_premarket_pool",
    "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool",
    "a_share_research_recommendation_pool",
    "a_share_baimao_research_map",
    "hkconnect_d1_top100",
    "wechat_public_account_v3_preselect",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

# The original pool contract used three coarse roles.  Formal 20260824/25
# artifacts already carry these producer-specific roles, so readers must
# accept them without weakening the legacy final-output rejection.
FORMAL_SOURCE_ROLES = frozenset(
    {
        "SHARED_VERIFIED_V192",
        "VERIFIED_D1_FUPAN_REVIEW",
        "VERIFIED_D1_STAGE7_REPLAY",
        "VERIFIED_HOURLY_RESEARCH",
        "SHARED_VERIFIED_HK_0_2",
        "VERIFIED_WECHAT_RESEARCH",
        "VERIFIED_BAIMAO_RESEARCH",
    }
)

# These are the lineage additions present on the accepted formal artifacts.
# They remain optional so the generic v1 artifacts and their receipts keep
# their exact historical wire shape.
POOL_ARTIFACT_OPTIONAL_FIELDS = frozenset(
    {
        "artifact_role",
        "artifact_version",
        "signal_date",
        "target_date",
        "source_artifact_sha256",
        "source_merge_role",
        "source_row_count",
        "source_run_id",
        "stage_selection_eligible",
        "source_manifest_sha256",
        "source_receipt_sha256",
        "source_archive",
        "historical_provenance",
        "coverage_evidence",
    }
)
RECEIPT_EXTENSION_FIELDS = frozenset({"source_row_count", "source_run_id"})

# Recovery is deliberately narrower than the historical V3.5 refresh surface.
# Only optional source pools may replace their exact fail-closed placeholder,
# and only with the producer-specific verified role already accepted by the
# artifact contract.  Formal A/HK pools remain immutable.
_RECOVERABLE_EXPECTED_MISSING_ROLES = {
    "a_d1_fupan_watchlist_pool": "VERIFIED_D1_FUPAN_REVIEW",
    "a_d1_stage7_fenshi_review_pool": "VERIFIED_D1_STAGE7_REPLAY",
    "a_share_research_recommendation_pool": "VERIFIED_HOURLY_RESEARCH",
}
_EMPTY_SOURCE_SHA256 = hashlib.sha256(b"").hexdigest()


def _is_exact_expected_missing_placeholder(
    payload: Mapping[str, Any], *, trade_date: str, pool_id: str
) -> bool:
    rows = payload.get("rows")
    return (
        payload.get("trade_date") == trade_date
        and payload.get("pool_id") == pool_id
        and payload.get("status") == "CANNOT_CONFIRM"
        and payload.get("producer_id") == "graph_expected_missing_v1"
        and payload.get("source_role") == "EXPECTED_MISSING"
        and payload.get("source_path") == ""
        and payload.get("source_sha256") == _EMPTY_SOURCE_SHA256
        and isinstance(rows, list)
        and not rows
        and isinstance(payload.get("cannot_confirm"), list)
        and bool(payload.get("cannot_confirm"))
        and payload.get("production_allowed") is False
        and payload.get("buy_gate_updated") is False
        and payload.get("orders_sent") is False
    )


class PreselectionPoolStore:
    """Store each graph-defined pool as its own immutable artifact."""

    def __init__(
        self,
        root: Path,
        *,
        write_gate_context: StoreGateContext | None = None,
        require_write_gate_context: bool = False,
    ) -> None:
        if not isinstance(require_write_gate_context, bool):
            raise TypeError("require_write_gate_context must be a bool")
        self.root = Path(root)
        self._write_gate_context = write_gate_context
        self._require_write_gate_context = require_write_gate_context
        self._io = SafeRoot(self.root)
        # Capture an already-existing root before any caller can swap its
        # directory entry.  A missing root remains constructible for the
        # first materialization, where SafeRoot binds it on the first write.
        try:
            with self._io.directory():
                pass
        except FileNotFoundError:
            pass

    def _assert_write_allowed(self, trade_date: str, pool_id: str) -> None:
        if self._require_write_gate_context and not isinstance(
            self._write_gate_context, StoreGateContext
        ):
            raise GateConfigurationError(
                "required write-gate context is missing or invalid"
            )
        assert_write_allowed(
            self._write_gate_context,
            store_root=self.root,
            trade_date=trade_date,
            pool_id=pool_id,
            pool_ids=POOL_ORDER,
        )

    def _preflight_required_write_context(self, trade_date: str, pool_id: str) -> None:
        """Reject strict-mode writes before acquiring a lock that may create files."""

        if self._require_write_gate_context:
            self._assert_write_allowed(trade_date, pool_id)

    def _preflight_pending_read_recovery(
        self, trade_date: str, pool_ids: Iterable[str]
    ) -> None:
        """Validate strict write authority before locking when repair may run."""

        if not self._require_write_gate_context:
            return
        for pool_id in pool_ids:
            pending_relative = self._pending_relative(
                trade_date=trade_date,
                pool_id=pool_id,
            )
            try:
                self._io.read_bytes(pending_relative)
            except FileNotFoundError:
                continue
            self._assert_write_allowed(trade_date, pool_id)

    def set_write_gate(self, *, expected_revision: int, state: str) -> dict[str, Any]:
        """Install or release a durable gate while holding the import lock."""

        self._preflight_gate_state_change_context()
        with owned_interprocess_lock(
            self.root / ".import.lock",
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        ):
            return self._set_write_gate_locked(expected_revision=expected_revision, state=state)

    def _preflight_gate_state_change_context(self) -> None:
        """Read-validate strict setter context before the shared lock can create files.

        This checks the same permit/root bindings used by ``update_gate_state``
        without inspecting the current gate state, so a valid FENCED gate can
        still be opened.  The locked setter repeats its authoritative checks.
        """

        if not self._require_write_gate_context:
            return
        context = self._write_gate_context
        if not isinstance(context, StoreGateContext):
            raise GateConfigurationError(
                "required write-gate context is missing or invalid"
            )
        directory_fd = _open_control_directory(context.control_dir)
        try:
            _load_permit_at(directory_fd, context, self.root, POOL_ORDER)
        finally:
            os.close(directory_fd)

    def _set_write_gate_locked(self, *, expected_revision: int, state: str) -> dict[str, Any]:
        if self._write_gate_context is None:
            raise GateConfigurationError("write-gate context is required to change gate state")
        return update_gate_state(
            self._write_gate_context,
            store_root=self.root,
            pool_ids=POOL_ORDER,
            expected_revision=expected_revision,
            state=state,
        )

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    def _read(self, relative: str) -> Any:
        import json

        return json.loads(self._io.read_bytes(relative).decode("utf-8"))

    def _write(self, relative: str, value: Mapping[str, Any]) -> None:
        # Payload contracts stay at each public materialization boundary.
        self._io.write_bytes(relative, _canonical_bytes(value))

    @staticmethod
    def _relative(trade_date: str, pool_id: str) -> tuple[str, str]:
        return (
            f"preselection_pools/{trade_date}/{pool_id}.json",
            f"preselection_pools/{trade_date}/receipts/{pool_id}.json",
        )

    @staticmethod
    def _receipt(
        *,
        trade_date: str,
        pool_id: str,
        artifact_path: str,
        artifact_sha256: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": "v3_5.preselection_pool_receipt.v1",
            "trade_date": trade_date,
            "pool_id": pool_id,
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha256,
            "source_sha256": payload["source_sha256"],
            "source_role": payload["source_role"],
        }
        for key in RECEIPT_EXTENSION_FIELDS:
            if key in payload:
                receipt[key] = payload[key]
        return receipt

    def materialize(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date = validate_pool_artifact(payload)
        pool_id = str(payload["pool_id"])
        self._preflight_required_write_context(trade_date, pool_id)
        # Physical pool writers and strict stage publication share this root
        # lock.  This closes the snapshot-to-commit window for every writer
        # using the store API without creating a second lock protocol.
        with owned_interprocess_lock(
            self.root / ".import.lock",
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        ):
            self._assert_write_allowed(trade_date, pool_id)
            self._reconcile_pending_commit_unlocked(trade_date, pool_id)
            return self._materialize_unlocked(payload)

    def _materialize_unlocked(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date = validate_pool_artifact(payload)
        pool_id = str(payload["pool_id"])
        artifact_path, receipt_path = self._relative(trade_date, pool_id)
        manifest_path = f"preselection_pools/{trade_date}/manifest.json"
        digest = _sha256(payload)
        receipt = self._receipt(
            trade_date=trade_date,
            pool_id=pool_id,
            artifact_path=artifact_path,
            artifact_sha256=digest,
            payload=payload,
        )
        manifest_file = self._path(manifest_path)
        manifest = self._read(manifest_path) if manifest_file.is_file() else {}
        if not isinstance(manifest, dict):
            raise ValueError("invalid preselection-pool manifest")
        existing = manifest.get(pool_id)
        artifact_file = self._path(artifact_path)
        receipt_file = self._path(receipt_path)
        if existing is not None:
            if (
                existing != digest
                or not artifact_file.is_file()
                or _sha256(self._read(artifact_path)) != digest
                or not receipt_file.is_file()
                or self._read(receipt_path) != receipt
            ):
                raise ValueError("conflicting preselection-pool materialization")
            return {"artifact_path": artifact_path, "receipt_path": receipt_path, "sha256": digest}
        if artifact_file.exists() or receipt_file.exists():
            raise ValueError("partial preselection-pool materialization")
        self._write(artifact_path, payload)
        self._write(receipt_path, receipt)
        manifest[pool_id] = digest
        self._write(manifest_path, manifest)
        return {"artifact_path": artifact_path, "receipt_path": receipt_path, "sha256": digest}

    def recover_expected_missing(
        self,
        payload: Mapping[str, Any],
        *,
        expected_old_sha256: str,
    ) -> dict[str, Any]:
        """CAS-replace one exact EXPECTED_MISSING optional source artifact.

        This is intentionally not a general overwrite API.  The current
        artifact must be the exact graph placeholder, its semantic SHA must
        match the caller-supplied preimage, and the replacement must carry the
        one verified source role assigned to that pool.  Both revisions and a
        recovery record are persisted so the operation can be rolled back
        without deleting evidence.
        """

        trade_date = validate_pool_artifact(payload)
        pool_id = str(payload["pool_id"])
        expected_role = _RECOVERABLE_EXPECTED_MISSING_ROLES.get(pool_id)
        if expected_role is None or payload.get("source_role") != expected_role:
            raise ValueError("preselection pool is not eligible for expected-missing recovery")
        expected_old = str(expected_old_sha256 or "").lower()
        if _SHA256.fullmatch(expected_old) is None:
            raise ValueError("invalid preselection recovery expected old SHA")
        self._preflight_required_write_context(trade_date, pool_id)
        with owned_interprocess_lock(
            self.root / ".import.lock",
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        ):
            self._assert_write_allowed(trade_date, pool_id)
            self._reconcile_pending_commit_unlocked(trade_date, pool_id)
            return self._recover_expected_missing_unlocked(
                payload,
                trade_date=trade_date,
                pool_id=pool_id,
                expected_old_sha256=expected_old,
            )

    def _recover_expected_missing_unlocked(
        self,
        payload: Mapping[str, Any],
        *,
        trade_date: str,
        pool_id: str,
        expected_old_sha256: str,
    ) -> dict[str, Any]:
        return _pool_transactions._recover_expected_missing_unlocked(self, payload, trade_date=trade_date, pool_id=pool_id, expected_old_sha256=expected_old_sha256, _api=sys.modules[__name__])

    def _archive_recovery_revision(
        self,
        trade_date: str,
        pool_id: str,
        digest: str,
        payload: Mapping[str, Any],
        main_receipt: Mapping[str, Any],
    ) -> None:
        return _pool_transactions._archive_recovery_revision(self, trade_date, pool_id, digest, payload, main_receipt, _api=sys.modules[__name__])

    def _commit_main_snapshot(
        self,
        snapshot: Mapping[str, Any],
        *,
        payload: Mapping[str, Any],
        receipt: Mapping[str, Any],
        manifest: Mapping[str, Any],
    ) -> None:
        """Publish one trio with a durable journal for process interruption.

        The existing root lock keeps readers out while the three files are
        replaced.  The pending journal is written before the first live file
        and lets a new process choose a complete old or new trio after a hard
        exit.  Normal exceptions still restore the old snapshot immediately.
        """
        return _pool_transactions._commit_main_snapshot(self, snapshot, payload=payload, receipt=receipt, manifest=manifest, _api=sys.modules[__name__])

    @staticmethod
    def _pending_relative(*, pool_id: str, trade_date: str) -> str:
        """Return the private journal path for one recovery commit."""
        return _pool_transactions._pending_relative(pool_id=pool_id, trade_date=trade_date, _api=sys.modules[__name__])

    @staticmethod
    def _revision_relative(
        trade_date: str, pool_id: str, digest: str
    ) -> tuple[str, str]:
        return _pool_transactions._revision_relative(trade_date, pool_id, digest, _api=sys.modules[__name__])

    def _pending_commit(
        self,
        snapshot: Mapping[str, Any],
        *,
        payload: Mapping[str, Any],
        receipt: Mapping[str, Any],
        manifest: Mapping[str, Any],
    ) -> dict[str, Any]:
        return _pool_transactions._pending_commit(self, snapshot, payload=payload, receipt=receipt, manifest=manifest, _api=sys.modules[__name__])

    def _remove_pending_commit_unlocked(self, relative: str) -> None:
        return _pool_transactions._remove_pending_commit_unlocked(self, relative, _api=sys.modules[__name__])

    def _read_pending_side_unlocked(
        self, pending: Mapping[str, Any], side_name: str
    ) -> dict[str, Any]:
        return _pool_transactions._read_pending_side_unlocked(self, pending, side_name, _api=sys.modules[__name__])

    def _main_state_matches_unlocked(self, side: Mapping[str, Any]) -> bool:
        return _pool_transactions._main_state_matches_unlocked(self, side, _api=sys.modules[__name__])

    def _reconcile_pending_commit_unlocked(self, trade_date: str, pool_id: str) -> None:
        """Finish or undo a commit left behind by a terminated process."""
        return _pool_transactions._reconcile_pending_commit_unlocked(self, trade_date, pool_id, _api=sys.modules[__name__])

    def _reconcile_pending_commit_read_unlocked(self, trade_date: str, pool_id: str) -> None:
        """Keep read-path recovery writes behind the same exact-scope fence."""
        return _pool_transactions._reconcile_pending_commit_read_unlocked(self, trade_date, pool_id, _api=sys.modules[__name__])

    def rollback_recovery(
        self,
        trade_date: str,
        pool_id: str,
        *,
        expected_current_sha256: str,
    ) -> dict[str, Any]:
        """Roll back the current pool only to the preimage of its recovery record."""

        trade_date = _date(trade_date)
        if pool_id not in _RECOVERABLE_EXPECTED_MISSING_ROLES:
            raise ValueError("preselection pool has no recovery rollback contract")
        current_expected = str(expected_current_sha256 or "").lower()
        if _SHA256.fullmatch(current_expected) is None:
            raise ValueError("invalid preselection rollback expected current SHA")
        self._preflight_required_write_context(trade_date, pool_id)
        with owned_interprocess_lock(
            self.root / ".import.lock",
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        ):
            self._assert_write_allowed(trade_date, pool_id)
            self._reconcile_pending_commit_unlocked(trade_date, pool_id)
            snapshot = self._read_pool_snapshot_unlocked(trade_date, pool_id)
            current_sha = str(snapshot["artifact_sha256"])
            if current_sha != current_expected:
                raise ValueError("preselection rollback expected current SHA mismatch")
            recovery_relative = (
                f"preselection_recoveries/{trade_date}/{pool_id}/{current_sha}.json"
            )
            recovery = self._read(recovery_relative)
            if (
                not isinstance(recovery, Mapping)
                or recovery.get("schema_version")
                != "v4.preselection_expected_missing_recovery.v1"
                or recovery.get("trade_date") != trade_date
                or recovery.get("pool_id") != pool_id
                or recovery.get("replacement_sha256") != current_sha
            ):
                raise ValueError("preselection rollback recovery record mismatch")
            previous_sha = str(recovery.get("previous_sha256") or "")
            previous_artifact_relative = (
                f"preselection_revisions/{trade_date}/{pool_id}/{previous_sha}.json"
            )
            previous_receipt_relative = (
                f"preselection_revisions/{trade_date}/{pool_id}/{previous_sha}.receipt.json"
            )
            previous_payload = self._read(previous_artifact_relative)
            revision_receipt = self._read(previous_receipt_relative)
            if (
                _sha256(previous_payload) != previous_sha
                or not isinstance(revision_receipt, Mapping)
                or revision_receipt.get("artifact_sha256") != previous_sha
                or revision_receipt.get("trade_date") != trade_date
                or revision_receipt.get("pool_id") != pool_id
                or revision_receipt.get("main_receipt")
                != self._receipt(
                    trade_date=trade_date,
                    pool_id=pool_id,
                    artifact_path=snapshot["artifact_relative"],
                    artifact_sha256=previous_sha,
                    payload=previous_payload,
                )
            ):
                raise ValueError("preselection rollback revision integrity mismatch")
            if not _is_exact_expected_missing_placeholder(
                previous_payload, trade_date=trade_date, pool_id=pool_id
            ):
                raise ValueError("preselection rollback target is not exact EXPECTED_MISSING")
            manifest = dict(snapshot["manifest"])
            manifest[pool_id] = previous_sha
            self._commit_main_snapshot(
                snapshot,
                payload=previous_payload,
                receipt=revision_receipt["main_receipt"],
                manifest=manifest,
            )
            return {
                "artifact_path": snapshot["artifact_relative"],
                "receipt_path": snapshot["receipt_relative"],
                "sha256": previous_sha,
                "rolled_back_from_sha256": current_sha,
                "recovery": False,
            }

    def read_pool(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        self._preflight_pending_read_recovery(trade_date, (pool_id,))
        with owned_interprocess_lock(
            self.root / ".import.lock",
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        ):
            self._reconcile_pending_commit_read_unlocked(trade_date, pool_id)
            return self._read_pool_unlocked(trade_date, pool_id)

    def _read_pool_unlocked(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        return _pool_readers._read_pool_unlocked(self, trade_date, pool_id, _api=sys.modules[__name__])

    def read_pool_snapshot(
        self,
        trade_date: str,
        pool_id: str,
        *,
        lock_lease: object | None = None,
    ) -> dict[str, Any]:
        lock_path = self.root / ".import.lock"
        if lock_lease is None:
            self._preflight_pending_read_recovery(trade_date, (pool_id,))
            with owned_interprocess_lock(
                lock_path,
                timeout_seconds=10,
                timeout_message="data-root import lock timeout",
            ) as acquired_lease:
                return self._read_pool_snapshot_under_lease(
                    trade_date, pool_id, acquired_lease
                )

        # A caller may reuse the root lock only with the exact live lease from
        # its context.  Validate before preflight, then again immediately
        # before recovery or physical reads.
        assert_owned_interprocess_lock(lock_lease, lock_path)
        self._preflight_pending_read_recovery(trade_date, (pool_id,))
        return self._read_pool_snapshot_under_lease(trade_date, pool_id, lock_lease)

    def _read_pool_snapshot_under_lease(
        self, trade_date: str, pool_id: str, lock_lease: object
    ) -> dict[str, Any]:
        assert_owned_interprocess_lock(
            lock_lease, self.root / ".import.lock"
        )
        self._reconcile_pending_commit_read_unlocked(trade_date, pool_id)
        return self._read_pool_snapshot_unlocked(trade_date, pool_id)

    def _read_pool_snapshot_unlocked(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        """Read one pool trio with canonical physical-byte identity.

        ``read_pool`` intentionally keeps its historical semantic-object
        behavior.  Strict stage acquisition needs the physical artifact,
        manifest, and receipt bytes to be canonical and bound to one another.
        This reader therefore returns both semantic and raw-byte digests while
        preserving the existing store paths and validation rules.
        """
        return _pool_readers._read_pool_snapshot_unlocked(self, trade_date, pool_id, _api=sys.modules[__name__])

    read_pool_raw_snapshot = read_pool_snapshot
    read_raw_snapshot = read_pool_snapshot

    def read_all(self, trade_date: str) -> list[dict[str, Any]]:
        trade_date = _date(trade_date)
        self._preflight_pending_read_recovery(trade_date, POOL_ORDER)
        with owned_interprocess_lock(
            self.root / ".import.lock",
            timeout_seconds=10,
            timeout_message="data-root import lock timeout",
        ):
            pools: list[dict[str, Any]] = []
            for pool_id in POOL_ORDER:
                self._reconcile_pending_commit_read_unlocked(trade_date, pool_id)
                try:
                    pools.append(self._read_pool_unlocked(trade_date, pool_id))
                except FileNotFoundError:
                    continue
            if not pools:
                raise FileNotFoundError(trade_date)
            return pools


class PreselectionSourceResolver:
    """Read-only exact-date owner routing for the deployed Stage contract.

    A primary date directory, even an incomplete one, owns that date.  A
    secondary source root is considered only when the primary date directory
    is absent.  This is whole-date routing, never per-pool merging or a latest
    fallback.
    """

    def __init__(self, root: Path | str, *, source_root: Path | str | None = None) -> None:
        self.root = Path(os.path.abspath(Path(root).expanduser()))
        self.source_root = (
            Path(os.path.abspath(Path(source_root).expanduser()))
            if source_root is not None else None
        )
        self._stores = {self.root: PreselectionPoolStore(self.root)}
        if self.source_root is not None and self.source_root != self.root:
            self._stores[self.source_root] = PreselectionPoolStore(self.source_root)

    def root_for_date(self, trade_date: str) -> Path:
        return _pool_sources.root_for_date(self, trade_date, _api=sys.modules[__name__])

    @contextmanager
    def source_read_lease(self, trade_date: str, *, timeout_seconds: float = 10):
        """Use the deployed V3.5 shared lock inode read-only when secondary."""
        with _pool_sources.source_read_lease(self, trade_date, timeout_seconds=timeout_seconds, _api=sys.modules[__name__]):
            yield

    def read_pool_snapshot(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        return _pool_sources.read_pool_snapshot(self, trade_date, pool_id, _api=sys.modules[__name__])

    def read_pool(self, trade_date: str, pool_id: str) -> dict[str, Any]:
        return _pool_sources.read_pool(self, trade_date, pool_id, _api=sys.modules[__name__])

    def read_all(self, trade_date: str) -> list[dict[str, Any]]:
        return _pool_sources.read_all(self, trade_date, _api=sys.modules[__name__])

    def verified_dates(self) -> tuple[str, ...]:
        return _pool_sources.verified_dates(self, _api=sys.modules[__name__])


def validate_pool_artifact(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("invalid preselection-pool artifact")
    required = {
        "schema_version", "trade_date", "pool_id", "display_name", "market",
        "status", "producer_id", "source_role", "source_path", "source_sha256",
        "rows", "cannot_confirm", "production_allowed", "buy_gate_updated", "orders_sent",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError("missing required preselection-pool fields")
    unknown = set(payload) - required - POOL_ARTIFACT_OPTIONAL_FIELDS
    if unknown:
        raise ValueError("invalid preselection-pool fields")
    if payload.get("schema_version") != "v3_5.preselection_pool.v1":
        raise ValueError("invalid preselection-pool schema")
    trade_date = _date(str(payload.get("trade_date") or ""))
    pool_id = str(payload.get("pool_id") or "")
    if pool_id not in POOL_ORDER or pool_id == "legacy_partial_migration":
        raise ValueError("unknown or legacy preselection pool")
    if payload.get("source_role") == "LEGACY_FINAL_API":
        raise ValueError("legacy final API is oracle-only")
    if payload.get("source_role") not in {
        "RAW_SOURCE",
        "UPSTREAM_PRODUCER_ARTIFACT",
        "EXPECTED_MISSING",
        *FORMAL_SOURCE_ROLES,
    }:
        raise ValueError("invalid preselection source role")
    if not _SHA256.fullmatch(str(payload.get("source_sha256") or "")):
        raise ValueError("invalid preselection source SHA")
    if "source_artifact_sha256" in payload and not _SHA256.fullmatch(
        str(payload.get("source_artifact_sha256") or "")
    ):
        raise ValueError("invalid preselection source artifact SHA")
    if "source_row_count" in payload:
        value = payload["source_row_count"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("invalid preselection source row count")
    if "source_run_id" in payload and not str(payload.get("source_run_id") or "").strip():
        raise ValueError("invalid preselection source run id")
    for field in ("signal_date", "target_date"):
        if field in payload:
            value = str(payload.get(field) or "")
            if _date(value) != value:
                raise ValueError(f"invalid preselection {field}")
    if "target_date" in payload and payload["target_date"] != payload["trade_date"]:
        raise ValueError("preselection target date mismatch")
    if "stage_selection_eligible" in payload and not isinstance(
        payload["stage_selection_eligible"], bool
    ):
        raise ValueError("invalid preselection stage selection flag")
    if any(payload.get(field) is not False for field in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise ValueError("unsafe preselection-pool artifact")
    rows = payload.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("invalid preselection-pool rows")
    if not isinstance(payload.get("cannot_confirm"), list):
        raise ValueError("invalid preselection-pool cannot_confirm")
    if not rows and payload.get("status") not in {"CANNOT_CONFIRM", "MISSING", "VALID_EMPTY"}:
        raise ValueError("empty pool requires an explicit status")
    _assert_safe(payload)
    return trade_date


def _legacy_research_flag_view(value: Any, *, depth: int = 0) -> Any:
    """Declared legacy shape: the HK 0.2 lane serialized ``research_only``
    as the string ``"True"`` in its pool rows.  Normalize exactly that
    truthy spelling for the guard view only; every other value still fails
    closed in the shared guard, and the persisted artifact is never
    rewritten."""

    if depth > 128:
        raise ValueError("preselection-pool payload nesting")
    if isinstance(value, Mapping):
        view: dict[Any, Any] = {}
        for key, nested in value.items():
            if (
                isinstance(key, str)
                and key.casefold() == "research_only"
                and isinstance(nested, str)
                and nested.strip().lower() == "true"
            ):
                view[key] = True
            else:
                view[key] = _legacy_research_flag_view(nested, depth=depth + 1)
        return view
    if isinstance(value, list):
        return [_legacy_research_flag_view(item, depth=depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(_legacy_research_flag_view(item, depth=depth + 1) for item in value)
    return value


def _assert_safe(value: Any) -> None:
    assert_safe_tree(_legacy_research_flag_view(value), label="preselection-pool")
