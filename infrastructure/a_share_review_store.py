"""Exact-date, V3.5-owned persistence for canonical A-share reviews."""
from __future__ import annotations

import os
import tempfile
import time
from infrastructure.interprocess_lock import owned_interprocess_lock
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from domains.a_share_review import validate_a_share_review
from infrastructure.data_store import _canonical_bytes, _date, _sha256
from infrastructure.owned_path import resolve_owned_path
from infrastructure.owned_io import SafeRoot


class AShareReviewStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._io = SafeRoot(self.root)

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    def _read(self, relative: str) -> Any:
        import json

        return json.loads(self._io.read_bytes(relative).decode("utf-8"))

    def _write(self, relative: str, value: Mapping[str, Any]) -> None:
        # Payload contracts stay at each public materialization boundary.
        self._io.write_bytes(relative, _canonical_bytes(value))

    @contextmanager
    def _lock(self):
        with owned_interprocess_lock(self._path("a_share_reviews/.import.lock"), timeout_seconds=10, timeout_message='A-share review import lock timeout'):
            yield

    def _paths(self, trade_date: str) -> tuple[str, str, str]:
        payload = f"a_share_reviews/{trade_date}.json"
        receipt = f"a_share_reviews/receipts/{trade_date}.json"
        manifest = "a_share_reviews/manifest.json"
        for relative in (payload, receipt, manifest, "a_share_reviews/.import.lock"):
            self._path(relative)
        return payload, receipt, manifest

    def import_review(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date = validate_a_share_review(payload)
        payload_path, receipt_path, manifest_path = self._paths(trade_date)
        manifest_file = self._path(manifest_path)
        if manifest_file.exists() and not manifest_file.is_file():
            raise ValueError("A-share review manifest path is not a regular file")
        digest = _sha256(payload)
        receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": payload_path,
            "payload_sha256": digest,
            "source_sha256": payload["source_sha256"],
            "trade_date": trade_date,
        }
        with self._lock():
            manifest = self._read(manifest_path) if manifest_file.is_file() else {}
            if not isinstance(manifest, dict):
                raise ValueError("A-share review manifest is invalid")
            existing = manifest.get(payload_path)
            payload_file = self._path(payload_path)
            receipt_file = self._path(receipt_path)
            if existing is not None:
                if (
                    existing != digest
                    or not payload_file.is_file()
                    or _sha256(self._read(payload_path)) != digest
                    or not receipt_file.is_file()
                    or self._read(receipt_path) != receipt
                ):
                    raise ValueError("A-share review idempotent import SHA mismatch")
                return {"sha256": digest, "payload_path": payload_path, "receipt_path": receipt_path}
            if payload_file.exists():
                if (
                    not payload_file.is_file()
                    or _sha256(self._read(payload_path)) != digest
                    or (receipt_file.exists() and (
                        not receipt_file.is_file() or self._read(receipt_path) != receipt
                    ))
                ):
                    raise ValueError("A-share review interrupted import SHA mismatch")
                if not receipt_file.exists():
                    self._write(receipt_path, receipt)
                manifest[payload_path] = digest
                self._write(manifest_path, manifest)
                return {"sha256": digest, "payload_path": payload_path, "receipt_path": receipt_path}
            if receipt_file.exists():
                raise ValueError("A-share review interrupted import conflicts with manifest")
            self._write(payload_path, payload)
            self._write(receipt_path, receipt)
            manifest[payload_path] = digest
            self._write(manifest_path, manifest)
        return {"sha256": digest, "payload_path": payload_path, "receipt_path": receipt_path}

    def replace_review(
        self,
        payload: Mapping[str, Any],
        *,
        expected_sha256: str,
        reason: str,
    ) -> dict[str, str]:
        """Replace a proven-invalid legacy review, preserving the audit chain."""
        trade_date = validate_a_share_review(payload)
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            raise ValueError("invalid expected SHA-256")
        reason = str(reason).strip()
        if not reason:
            raise ValueError("review replacement reason is required")
        payload_path, receipt_path, manifest_path = self._paths(trade_date)
        replacement_sha = _sha256(payload)
        supersession_path = (
            f"a_share_reviews/supersessions/{trade_date}/{expected_sha256}.json"
        )
        replacement_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": payload_path,
            "payload_sha256": replacement_sha,
            "source_sha256": payload["source_sha256"],
            "trade_date": trade_date,
        }
        supersession = {
            "schema_version": "v3_5.review_supersession.v1",
            "trade_date": trade_date,
            "payload_path": payload_path,
            "previous_sha256": expected_sha256,
            "replacement_sha256": replacement_sha,
            "reason": reason,
        }
        with self._lock():
            manifest_file = self._path(manifest_path)
            manifest = self._read(manifest_path) if manifest_file.is_file() else {}
            if not isinstance(manifest, dict):
                raise ValueError("A-share review manifest is invalid")
            current_sha = manifest.get(payload_path)
            payload_file = self._path(payload_path)
            receipt_file = self._path(receipt_path)
            supersession_file = self._path(supersession_path)
            if current_sha == replacement_sha:
                if (
                    not payload_file.is_file()
                    or _sha256(self._read(payload_path)) != replacement_sha
                    or not receipt_file.is_file()
                    or self._read(receipt_path) != replacement_receipt
                    or not supersession_file.is_file()
                    or self._read(supersession_path) != supersession
                ):
                    raise ValueError("idempotent review replacement integrity mismatch")
                return {
                    "sha256": replacement_sha,
                    "previous_sha256": expected_sha256,
                    "receipt_path": receipt_path,
                    "supersession_receipt_path": supersession_path,
                    "payload_path": payload_path,
                }
            if current_sha != expected_sha256:
                raise ValueError("A-share review does not match expected SHA")
            self._write(payload_path, payload)
            self._write(receipt_path, replacement_receipt)
            self._write(supersession_path, supersession)
            manifest[payload_path] = replacement_sha
            self._write(manifest_path, manifest)
        return {
            "sha256": replacement_sha,
            "previous_sha256": expected_sha256,
            "receipt_path": receipt_path,
            "supersession_receipt_path": supersession_path,
            "payload_path": payload_path,
        }

    def read_review(self, trade_date: str) -> dict[str, Any] | None:
        trade_date = _date(trade_date)
        payload_path, receipt_path, manifest_path = self._paths(trade_date)
        payload_file = self._path(payload_path)
        receipt_file = self._path(receipt_path)
        manifest_file = self._path(manifest_path)
        present = (payload_file.exists(), receipt_file.exists(), manifest_file.exists())
        if any(path.exists() and not path.is_file() for path in (payload_file, receipt_file, manifest_file)):
            raise ValueError("A-share review evidence path is not a regular file")
        if not present[0] and not present[1]:
            if not present[2]:
                return None
            try:
                manifest = self._read(manifest_path)
            except (OSError, ValueError) as error:
                raise ValueError("A-share review manifest cannot be read") from error
            if not isinstance(manifest, dict):
                raise ValueError("A-share review manifest is invalid")
            if payload_path not in manifest:
                return None
            raise ValueError("A-share review evidence is partially materialized")
        if not all(present):
            raise ValueError("A-share review evidence is partially materialized")
        try:
            payload = self._read(payload_path)
            receipt = self._read(receipt_path)
            manifest = self._read(manifest_path)
        except (OSError, ValueError) as error:
            raise ValueError("A-share review evidence cannot be read") from error
        digest = _sha256(payload)
        expected_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": payload_path,
            "payload_sha256": digest,
            "source_sha256": payload["source_sha256"],
            "trade_date": trade_date,
        }
        if not isinstance(manifest, dict) or manifest.get(payload_path) != digest or receipt != expected_receipt:
            raise ValueError("A-share review manifest or receipt SHA mismatch")
        if validate_a_share_review(payload) != trade_date:
            raise ValueError("A-share review payload identity mismatch")
        return payload
