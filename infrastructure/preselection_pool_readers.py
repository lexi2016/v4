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

def _read_pool_unlocked(self, trade_date: str, pool_id: str, *, _api: PoolAPI) -> dict[str, Any]:
    trade_date = _api._date(trade_date)
    if pool_id not in _api.POOL_ORDER:
        raise ValueError("unknown preselection pool")
    artifact_path, receipt_path = self._relative(trade_date, pool_id)
    manifest_path = f"preselection_pools/{trade_date}/manifest.json"
    if not self._path(artifact_path).is_file():
        raise FileNotFoundError(pool_id)
    payload = self._read(artifact_path)
    digest = _api._sha256(payload)
    manifest = self._read(manifest_path)
    receipt = self._read(receipt_path)
    expected = self._receipt(
        trade_date=trade_date,
        pool_id=pool_id,
        artifact_path=artifact_path,
        artifact_sha256=digest,
        payload=payload,
    )
    if (
        not isinstance(manifest, dict)
        or manifest.get(pool_id) != digest
        or receipt != expected
    ):
        raise ValueError("preselection-pool manifest or receipt SHA mismatch")
    if _api.validate_pool_artifact(payload) != trade_date or payload["pool_id"] != pool_id:
        raise ValueError("preselection-pool identity mismatch")
    return payload


def _read_pool_snapshot_unlocked(self, trade_date: str, pool_id: str, *, _api: PoolAPI) -> dict[str, Any]:
    """Read one pool trio with canonical physical-byte identity.

        ``read_pool`` intentionally keeps its historical semantic-object
        behavior.  Strict stage acquisition needs the physical artifact,
        manifest, and receipt bytes to be canonical and bound to one another.
        This reader therefore returns both semantic and raw-byte digests while
        preserving the existing store paths and validation rules.
        """

    trade_date = _api._date(trade_date)
    if pool_id not in _api.POOL_ORDER:
        raise ValueError("unknown preselection pool")
    artifact_relative, receipt_relative = self._relative(trade_date, pool_id)
    manifest_relative = f"preselection_pools/{trade_date}/manifest.json"
    # Read and classify each path separately. Only the exact pool artifact's
    # absence is a normal missing-lane gap; a shared manifest or safe-root
    # failure must remain fail-closed.
    try:
        artifact_bytes = self._io.read_bytes(artifact_relative)
    except FileNotFoundError as error:
        raise _api.PreselectionPoolArtifactMissing(pool_id) from error
    try:
        manifest_bytes = self._io.read_bytes(manifest_relative)
    except FileNotFoundError as error:
        raise RuntimeError("preselection-pool shared manifest is missing") from error
    try:
        receipt_bytes = self._io.read_bytes(receipt_relative)
    except FileNotFoundError as error:
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool receipt is missing"
        ) from error

    try:
        artifact = json.loads(artifact_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool artifact physical JSON cannot be parsed"
        ) from error
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("preselection-pool shared manifest JSON cannot be parsed") from error
    try:
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool receipt physical JSON cannot be parsed"
        ) from error
    if not isinstance(artifact, Mapping):
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool artifact physical snapshot must contain an object"
        )
    if not isinstance(manifest, Mapping):
        raise RuntimeError("preselection-pool shared manifest must contain an object")
    if not isinstance(receipt, Mapping):
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool receipt must contain an object"
        )
    if artifact_bytes != _api._canonical_bytes(artifact):
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool artifact bytes are not canonical"
        )
    if manifest_bytes != _api._canonical_bytes(manifest):
        raise RuntimeError("preselection-pool shared manifest bytes are not canonical")
    if receipt_bytes != _api._canonical_bytes(receipt):
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool receipt bytes are not canonical"
        )

    digest = _api._sha256(artifact)
    expected_receipt = self._receipt(
        trade_date=trade_date,
        pool_id=pool_id,
        artifact_path=artifact_relative,
        artifact_sha256=digest,
        payload=artifact,
    )
    if manifest.get(pool_id) != digest:
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool manifest SHA mismatch"
        )
    if receipt != expected_receipt:
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool receipt SHA mismatch"
        )
    try:
        artifact_trade_date = _api.validate_pool_artifact(artifact)
    except _api.OwnedIOError:
        raise
    except (TypeError, ValueError) as error:
        raise _api.PreselectionPoolIntegrityError(
            pool_id, f"pool artifact contract validation failed: {error}"
        ) from error
    if artifact_trade_date != trade_date or artifact.get("pool_id") != pool_id:
        raise _api.PreselectionPoolIntegrityError(
            pool_id, "pool trade-date or identity mismatch"
        )
    return {
        "artifact": dict(artifact),
        "payload": dict(artifact),
        "manifest": dict(manifest),
        "receipt": dict(receipt),
        "artifact_relative": artifact_relative,
        "manifest_relative": manifest_relative,
        "receipt_relative": receipt_relative,
        "artifact_relative_path": artifact_relative,
        "manifest_relative_path": manifest_relative,
        "receipt_relative_path": receipt_relative,
        "pool_sha256": digest,
        "semantic_sha256": digest,
        "artifact_sha256": digest,
        "artifact_raw_sha256": _api._sha256_bytes(artifact_bytes),
        "manifest_raw_sha256": _api._sha256_bytes(manifest_bytes),
        "receipt_raw_sha256": _api._sha256_bytes(receipt_bytes),
    }


