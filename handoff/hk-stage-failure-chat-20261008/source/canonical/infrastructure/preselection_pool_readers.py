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
    try:
        # The descriptor-anchored reader both rejects symlink races and
        # rechecks the root identity captured by SafeRoot.__init__.
        artifact_bytes = self._io.read_bytes(artifact_relative)
        manifest_bytes = self._io.read_bytes(manifest_relative)
        receipt_bytes = self._io.read_bytes(receipt_relative)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            "preselection-pool physical snapshot file is missing"
        ) from error
    try:
        artifact = json.loads(artifact_bytes.decode("utf-8"))
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("preselection-pool physical JSON cannot be parsed") from error
    if not isinstance(artifact, Mapping) or not isinstance(manifest, Mapping) or not isinstance(receipt, Mapping):
        raise ValueError("preselection-pool physical snapshot must contain objects")
    if artifact_bytes != _api._canonical_bytes(artifact):
        raise ValueError("preselection-pool artifact bytes are not canonical")
    if manifest_bytes != _api._canonical_bytes(manifest):
        raise ValueError("preselection-pool manifest bytes are not canonical")
    if receipt_bytes != _api._canonical_bytes(receipt):
        raise ValueError("preselection-pool receipt bytes are not canonical")

    digest = _api._sha256(artifact)
    expected_receipt = self._receipt(
        trade_date=trade_date,
        pool_id=pool_id,
        artifact_path=artifact_relative,
        artifact_sha256=digest,
        payload=artifact,
    )
    if manifest.get(pool_id) != digest or receipt != expected_receipt:
        raise ValueError("preselection-pool manifest or receipt SHA mismatch")
    if _api.validate_pool_artifact(artifact) != trade_date or artifact.get("pool_id") != pool_id:
        raise ValueError("preselection-pool identity mismatch")
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


