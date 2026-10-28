"""Private pool operations extracted from the exact d8b1 store baseline.

The public facade retains locks, gate checks and compatibility methods. This
module has no producer, scheduler or authority. Dependencies arrive explicitly
from that facade; it never imports the facade or binds mutable global services.
"""
from __future__ import annotations
import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Mapping, TYPE_CHECKING
if TYPE_CHECKING:
    from infrastructure.preselection_pool_ports import PoolAPI

def _recover_expected_missing_unlocked(self, payload: Mapping[str, Any], *, trade_date: str, pool_id: str, expected_old_sha256: str, _api: PoolAPI) -> dict[str, Any]:
    snapshot = self._read_pool_snapshot_unlocked(trade_date, pool_id)
    old_payload = snapshot["artifact"]
    old_sha = str(snapshot["artifact_sha256"])
    if old_sha != expected_old_sha256:
        raise ValueError("preselection recovery expected old SHA mismatch")
    if not _api._is_exact_expected_missing_placeholder(
        old_payload, trade_date=trade_date, pool_id=pool_id
    ):
        raise ValueError("preselection recovery preimage is not exact EXPECTED_MISSING")

    replacement_sha = _api._sha256(payload)
    if replacement_sha == old_sha:
        raise ValueError("preselection recovery replacement must differ from placeholder")
    replacement_receipt = self._receipt(
        trade_date=trade_date,
        pool_id=pool_id,
        artifact_path=snapshot["artifact_relative"],
        artifact_sha256=replacement_sha,
        payload=payload,
    )
    old_receipt = snapshot["receipt"]
    self._archive_recovery_revision(
        trade_date, pool_id, old_sha, old_payload, old_receipt
    )
    self._archive_recovery_revision(
        trade_date, pool_id, replacement_sha, payload, replacement_receipt
    )

    recovery_relative = (
        f"preselection_recoveries/{trade_date}/{pool_id}/{replacement_sha}.json"
    )
    recovery = {
        "schema_version": "v4.preselection_expected_missing_recovery.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "previous_sha256": old_sha,
        "replacement_sha256": replacement_sha,
        "previous_source_role": old_payload.get("source_role"),
        "replacement_source_role": payload.get("source_role"),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    recovery_file = self._path(recovery_relative)
    if recovery_file.exists():
        if not recovery_file.is_file() or self._read(recovery_relative) != recovery:
            raise ValueError("preselection recovery record conflict")
    else:
        self._write(recovery_relative, recovery)

    manifest = dict(snapshot["manifest"])
    manifest[pool_id] = replacement_sha
    self._commit_main_snapshot(
        snapshot,
        payload=payload,
        receipt=replacement_receipt,
        manifest=manifest,
    )
    return {
        "artifact_path": snapshot["artifact_relative"],
        "receipt_path": snapshot["receipt_relative"],
        "sha256": replacement_sha,
        "previous_sha256": old_sha,
        "recovery_record": recovery_relative,
        "recovery": True,
    }


def _archive_recovery_revision(self, trade_date: str, pool_id: str, digest: str, payload: Mapping[str, Any], main_receipt: Mapping[str, Any], *, _api: PoolAPI) -> None:
    artifact_relative = (
        f"preselection_revisions/{trade_date}/{pool_id}/{digest}.json"
    )
    receipt_relative = (
        f"preselection_revisions/{trade_date}/{pool_id}/{digest}.receipt.json"
    )
    receipt = {
        "schema_version": "v4.preselection_recovery_revision_receipt.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "artifact_path": artifact_relative,
        "artifact_sha256": digest,
        "source_sha256": payload.get("source_sha256"),
        "source_role": payload.get("source_role"),
        "main_receipt": dict(main_receipt),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    artifact_file = self._path(artifact_relative)
    receipt_file = self._path(receipt_relative)
    if artifact_file.exists() or receipt_file.exists():
        if (
            not artifact_file.is_file()
            or _api._sha256(self._read(artifact_relative)) != digest
            or not receipt_file.is_file()
            or self._read(receipt_relative) != receipt
        ):
            raise ValueError("preselection recovery revision integrity mismatch")
        return
    self._write(artifact_relative, payload)
    self._write(receipt_relative, receipt)


def _commit_main_snapshot(self, snapshot: Mapping[str, Any], *, payload: Mapping[str, Any], receipt: Mapping[str, Any], manifest: Mapping[str, Any], _api: PoolAPI) -> None:
    """Publish one trio with a durable journal for process interruption.

        The existing root lock keeps readers out while the three files are
        replaced.  The pending journal is written before the first live file
        and lets a new process choose a complete old or new trio after a hard
        exit.  Normal exceptions still restore the old snapshot immediately.
        """

    pending_relative = self._pending_relative(
        pool_id=str(snapshot["artifact"].get("pool_id") or ""),
        trade_date=str(snapshot["artifact"].get("trade_date") or ""),
    )
    pending = self._pending_commit(
        snapshot,
        payload=payload,
        receipt=receipt,
        manifest=manifest,
    )
    self._write(pending_relative, pending)
    try:
        self._write(snapshot["artifact_relative"], payload)
        self._write(snapshot["receipt_relative"], receipt)
        self._write(snapshot["manifest_relative"], manifest)
    except Exception as error:
        try:
            # Restore the commit pointer first, then its two pointed-to
            # objects. A reader that observes the intermediate state still
            # fails closed, while the final state is the old trio.
            self._write(snapshot["manifest_relative"], snapshot["manifest"])
            self._write(snapshot["receipt_relative"], snapshot["receipt"])
            self._write(snapshot["artifact_relative"], snapshot["artifact"])
        except Exception as restore_error:
            raise RuntimeError(
                "preselection recovery commit failed and rollback failed"
            ) from restore_error
        self._remove_pending_commit_unlocked(pending_relative)
        raise
    self._remove_pending_commit_unlocked(pending_relative)


def _pending_relative(*, pool_id: str, trade_date: str, _api: PoolAPI) -> str:
    """Return the private journal path for one recovery commit."""

    return f"preselection_pending_commits/{trade_date}/{pool_id}.json"


def _revision_relative(trade_date: str, pool_id: str, digest: str, *, _api: PoolAPI) -> tuple[str, str]:
    return (
        f"preselection_revisions/{trade_date}/{pool_id}/{digest}.json",
        f"preselection_revisions/{trade_date}/{pool_id}/{digest}.receipt.json",
    )


def _pending_commit(self, snapshot: Mapping[str, Any], *, payload: Mapping[str, Any], receipt: Mapping[str, Any], manifest: Mapping[str, Any], _api: PoolAPI) -> dict[str, Any]:
    trade_date = str(snapshot["artifact"].get("trade_date") or "")
    pool_id = str(snapshot["artifact"].get("pool_id") or "")
    old_sha = str(snapshot["artifact_sha256"])
    new_sha = _api._sha256(payload)
    old_revision, old_revision_receipt = self._revision_relative(
        trade_date, pool_id, old_sha
    )
    new_revision, new_revision_receipt = self._revision_relative(
        trade_date, pool_id, new_sha
    )
    return {
        "schema_version": "v4.preselection_pending_commit.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "old": {
            "artifact_path": snapshot["artifact_relative"],
            "artifact_sha256": old_sha,
            "revision_path": old_revision,
            "revision_receipt_path": old_revision_receipt,
            "receipt_path": snapshot["receipt_relative"],
            "manifest_path": snapshot["manifest_relative"],
            "manifest": dict(snapshot["manifest"]),
        },
        "new": {
            "artifact_path": snapshot["artifact_relative"],
            "artifact_sha256": new_sha,
            "revision_path": new_revision,
            "revision_receipt_path": new_revision_receipt,
            "receipt_path": snapshot["receipt_relative"],
            "manifest_path": snapshot["manifest_relative"],
            "manifest": dict(manifest),
            "receipt": dict(receipt),
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _remove_pending_commit_unlocked(self, relative: str, *, _api: PoolAPI) -> None:
    path = self._path(relative)
    if not path.is_file():
        return
    try:
        raw = self._io.read_bytes(relative)
        self._io.unlink_if_same(relative, raw)
    except FileNotFoundError:
        return


def _read_pending_side_unlocked(self, pending: Mapping[str, Any], side_name: str, *, _api: PoolAPI) -> dict[str, Any]:
    side = pending.get(side_name)
    if not isinstance(side, Mapping):
        raise ValueError("preselection pending commit side is invalid")
    trade_date = str(pending.get("trade_date") or "")
    pool_id = str(pending.get("pool_id") or "")
    digest = str(side.get("artifact_sha256") or "")
    expected_revision, expected_revision_receipt = self._revision_relative(
        trade_date, pool_id, digest
    )
    if (
        side.get("artifact_path")
        != f"preselection_pools/{trade_date}/{pool_id}.json"
        or side.get("receipt_path")
        != f"preselection_pools/{trade_date}/receipts/{pool_id}.json"
        or side.get("manifest_path")
        != f"preselection_pools/{trade_date}/manifest.json"
        or side.get("revision_path") != expected_revision
        or side.get("revision_receipt_path") != expected_revision_receipt
        or not _api._SHA256.fullmatch(digest)
        or not isinstance(side.get("manifest"), Mapping)
    ):
        raise ValueError("preselection pending commit paths are invalid")
    artifact = self._read(str(side["revision_path"]))
    revision_receipt = self._read(str(side["revision_receipt_path"]))
    if not isinstance(revision_receipt, Mapping):
        raise ValueError("preselection pending commit revision receipt is invalid")
    main_receipt = revision_receipt.get("main_receipt")
    if (
        not isinstance(artifact, Mapping)
        or _api._sha256(artifact) != digest
        or revision_receipt.get("artifact_sha256") != digest
        or revision_receipt.get("trade_date") != trade_date
        or revision_receipt.get("pool_id") != pool_id
        or not isinstance(main_receipt, Mapping)
    ):
        raise ValueError("preselection pending commit revision is invalid")
    expected_receipt = self._receipt(
        trade_date=trade_date,
        pool_id=pool_id,
        artifact_path=str(side["artifact_path"]),
        artifact_sha256=digest,
        payload=artifact,
    )
    if dict(main_receipt) != expected_receipt:
        raise ValueError("preselection pending commit receipt is invalid")
    if side_name == "new":
        inline_receipt = side.get("receipt")
        if not isinstance(inline_receipt, Mapping) or dict(inline_receipt) != expected_receipt:
            raise ValueError("preselection pending commit new receipt is invalid")
    return {
        "artifact": dict(artifact),
        "artifact_sha256": digest,
        "receipt": expected_receipt,
        "manifest": dict(side["manifest"]),
        "artifact_path": str(side["artifact_path"]),
        "receipt_path": str(side["receipt_path"]),
        "manifest_path": str(side["manifest_path"]),
    }


def _main_state_matches_unlocked(self, side: Mapping[str, Any], *, _api: PoolAPI) -> bool:
    try:
        artifact_bytes = self._io.read_bytes(str(side["artifact_path"]))
        receipt_bytes = self._io.read_bytes(str(side["receipt_path"]))
        manifest_bytes = self._io.read_bytes(str(side["manifest_path"]))
        artifact = json.loads(artifact_bytes.decode("utf-8"))
        receipt = json.loads(receipt_bytes.decode("utf-8"))
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return False
    return (
        artifact_bytes == _api._canonical_bytes(artifact)
        and receipt_bytes == _api._canonical_bytes(receipt)
        and manifest_bytes == _api._canonical_bytes(manifest)
        and _api._sha256(artifact) == side["artifact_sha256"]
        and receipt == side["receipt"]
        and manifest == side["manifest"]
    )


def _reconcile_pending_commit_unlocked(self, trade_date: str, pool_id: str, *, _api: PoolAPI) -> None:
    """Finish or undo a commit left behind by a terminated process."""

    trade_date = _api._date(trade_date)
    if pool_id not in _api.POOL_ORDER:
        raise ValueError("unknown preselection pool")
    pending_relative = self._pending_relative(
        trade_date=trade_date,
        pool_id=pool_id,
    )
    journal_file = self._path(pending_relative)
    if not journal_file.exists():
        return
    if not journal_file.is_file():
        raise ValueError("preselection pending commit journal is not a file")
    raw = self._io.read_bytes(pending_relative)
    try:
        pending = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("preselection pending commit cannot be parsed") from error
    if not isinstance(pending, Mapping) or raw != _api._canonical_bytes(pending):
        raise ValueError("preselection pending commit is not canonical")
    if (
        pending.get("schema_version") != "v4.preselection_pending_commit.v1"
        or pending.get("trade_date") != trade_date
        or pending.get("pool_id") != pool_id
    ):
        raise ValueError("preselection pending commit identity mismatch")
    old = self._read_pending_side_unlocked(pending, "old")
    new = self._read_pending_side_unlocked(pending, "new")
    if self._main_state_matches_unlocked(old) or self._main_state_matches_unlocked(new):
        self._remove_pending_commit_unlocked(pending_relative)
        return
    # The writer order is artifact -> receipt -> manifest.  Any
    # interrupted mixed state therefore conservatively rolls back to
    # the complete old trio before a caller retries or reads.
    self._write(old["manifest_path"], old["manifest"])
    self._write(old["receipt_path"], old["receipt"])
    self._write(old["artifact_path"], old["artifact"])
    if not self._main_state_matches_unlocked(old):
        raise ValueError("preselection pending commit reconciliation failed")
    self._remove_pending_commit_unlocked(pending_relative)


def _reconcile_pending_commit_read_unlocked(self, trade_date: str, pool_id: str, *, _api: PoolAPI) -> None:
    """Keep read-path recovery writes behind the same exact-scope fence."""

    pending_relative = self._pending_relative(trade_date=trade_date, pool_id=pool_id)
    try:
        self._io.read_bytes(pending_relative)
    except FileNotFoundError:
        pass
    else:
        self._assert_write_allowed(trade_date, pool_id)
    self._reconcile_pending_commit_unlocked(trade_date, pool_id)


