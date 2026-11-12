"""Atomic, V4-owned storage for self-hashed parity receipts."""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
import time
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from contracts.parity import (
    ParityReceiptError,
    validate_parity_receipt,
    validate_parity_receipt_against_graph,
)
from infrastructure.owned_path import resolve_owned_path


class ParityReceiptStore:
    AUTHORITY_SCHEMA = "v3_5.parity_receipt_authority.v1"

    def __init__(
        self,
        root: Path,
        *,
        graph_baseline: Mapping[str, Any],
        inventory_v2: Mapping[str, Any],
    ) -> None:
        self.root = Path(root)
        self.graph_baseline = deepcopy(graph_baseline)
        self.inventory_v2 = deepcopy(inventory_v2)

    @staticmethod
    def _relative(business_date: str, feature_id: str, view_id: str) -> str:
        return f"parity/{business_date}/{feature_id}/{view_id}/receipt.json"

    @staticmethod
    def _authority_relative(business_date: str, feature_id: str) -> str:
        return f"parity/{business_date}/{feature_id}/authority.json"

    @contextmanager
    def _exclusive_identity(self, destination: Path) -> Iterator[None]:
        lock = destination.with_name(f".{destination.name}.write.lock")
        deadline = time.monotonic() + 5.0
        handle: int | None = None
        while handle is None:
            try:
                handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as error:
                if time.monotonic() >= deadline:
                    raise ParityReceiptError(
                        "parity receipt identity is busy"
                    ) from error
                time.sleep(0.01)
        try:
            os.write(handle, str(os.getpid()).encode("ascii"))
            os.fsync(handle)
            os.close(handle)
            handle = None
            yield
        finally:
            if handle is not None:
                os.close(handle)
            try:
                lock.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _canonical_json(payload: Mapping[str, Any]) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _semantic_hash(payload: Mapping[str, Any]) -> str:
        return hashlib.sha256(ParityReceiptStore._canonical_json(payload)).hexdigest()

    def _atomic_write(self, destination: Path, payload: Mapping[str, Any]) -> None:
        handle, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(self._canonical_json(payload))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def write(self, receipt: Mapping[str, Any]) -> dict[str, str]:
        validate_parity_receipt_against_graph(
            receipt, self.graph_baseline, self.inventory_v2
        )
        relative = self._relative(
            str(receipt["business_date"]),
            str(receipt["feature_id"]),
            str(receipt["view_id"]),
        )
        destination = resolve_owned_path(self.root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._exclusive_identity(destination):
            if destination.exists():
                existing = self._read_file(destination)
                if existing != receipt:
                    raise ParityReceiptError("conflicting parity receipt identity")
            else:
                self._atomic_write(destination, receipt)
        return {
            "receipt_path": relative,
            "receipt_semantic_hash": str(receipt["receipt_semantic_hash"]),
        }

    def _read_file(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ParityReceiptError("invalid parity receipt schema") from error
        validate_parity_receipt(payload)
        validate_parity_receipt_against_graph(
            payload, self.graph_baseline, self.inventory_v2
        )
        return deepcopy(payload)

    def read(self, business_date: str, feature_id: str, view_id: str) -> dict[str, Any]:
        relative = self._relative(business_date, feature_id, view_id)
        destination = resolve_owned_path(self.root, relative)
        if not destination.is_file():
            raise FileNotFoundError(relative)
        return self._read_file(destination)

    def set_authority(
        self,
        business_date: str,
        feature_id: str,
        *,
        active_view_id: str,
        superseded_view_ids: Sequence[str],
    ) -> dict[str, Any]:
        active = self.read(business_date, feature_id, active_view_id)
        superseded = [
            self._read_historical_receipt(business_date, feature_id, view_id)
            for view_id in sorted(set(superseded_view_ids))
        ]
        if any(
            item["receipt_semantic_hash"] == active["receipt_semantic_hash"]
            for item in superseded
        ):
            raise ParityReceiptError("active receipt cannot supersede itself")

        def receipt_ref(item: Mapping[str, Any]) -> dict[str, str]:
            return {
                "path": self._relative(
                    str(item["business_date"]),
                    str(item["feature_id"]),
                    str(item["view_id"]),
                ),
                "receipt_semantic_hash": str(item["receipt_semantic_hash"]),
            }

        body: dict[str, Any] = {
            "schema_version": self.AUTHORITY_SCHEMA,
            "business_date": business_date,
            "feature_id": feature_id,
            "graph_baseline_semantic_hash": self.graph_baseline["semantic_hash"],
            "active_receipt": receipt_ref(active),
            "superseded_receipts": sorted(
                (receipt_ref(item) for item in superseded),
                key=lambda item: (item["path"], item["receipt_semantic_hash"]),
            ),
            "safety": {
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        }
        authority = {
            **body,
            "authority_semantic_hash": self._semantic_hash(body),
        }
        relative = self._authority_relative(business_date, feature_id)
        destination = resolve_owned_path(self.root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._exclusive_identity(destination):
            if destination.exists():
                existing = self._read_authority_file(destination)
                if existing != authority:
                    old_active = existing["active_receipt"]["receipt_semantic_hash"]
                    new_superseded = {
                        item["receipt_semantic_hash"]
                        for item in authority["superseded_receipts"]
                    }
                    old_superseded = {
                        item["receipt_semantic_hash"]
                        for item in existing["superseded_receipts"]
                    }
                    if old_active not in new_superseded or not old_superseded.issubset(
                        new_superseded
                    ):
                        raise ParityReceiptError(
                            "conflicting parity authority transition"
                        )
                    self._atomic_write(destination, authority)
            else:
                self._atomic_write(destination, authority)
        return deepcopy(authority)

    def _read_historical_receipt(
        self, business_date: str, feature_id: str, view_id: str
    ) -> dict[str, Any]:
        """Read an immutable old receipt by envelope hash, even if policy evolved."""

        relative = self._relative(business_date, feature_id, view_id)
        destination = resolve_owned_path(self.root, relative)
        if not destination.is_file():
            raise FileNotFoundError(relative)
        try:
            payload = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ParityReceiptError("invalid historical parity receipt") from error
        semantic_hash = payload.get("receipt_semantic_hash")
        body = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key != "receipt_semantic_hash"
        }
        if (
            not isinstance(semantic_hash, str)
            or len(semantic_hash) != 64
            or any(character not in "0123456789abcdef" for character in semantic_hash)
            or self._semantic_hash(body) != semantic_hash
            or payload.get("business_date") != business_date
            or payload.get("feature_id") != feature_id
            or payload.get("view_id") != view_id
        ):
            raise ParityReceiptError("invalid historical parity receipt")
        return deepcopy(payload)

    def _read_authority_file(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ParityReceiptError("invalid parity authority schema") from error
        semantic_hash = payload.get("authority_semantic_hash")
        body = {
            key: deepcopy(value)
            for key, value in payload.items()
            if key != "authority_semantic_hash"
        }
        expected_fields = {
            "schema_version",
            "business_date",
            "feature_id",
            "graph_baseline_semantic_hash",
            "active_receipt",
            "superseded_receipts",
            "safety",
            "authority_semantic_hash",
        }
        if (
            set(payload) != expected_fields
            or payload.get("schema_version") != self.AUTHORITY_SCHEMA
            or not isinstance(semantic_hash, str)
            or len(semantic_hash) != 64
            or any(character not in "0123456789abcdef" for character in semantic_hash)
            or self._semantic_hash(body) != semantic_hash
            or payload.get("graph_baseline_semantic_hash")
            != self.graph_baseline["semantic_hash"]
            or payload.get("safety")
            != {
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        ):
            raise ParityReceiptError("invalid parity authority schema")
        active_ref = payload.get("active_receipt")
        superseded_refs = payload.get("superseded_receipts")
        if not isinstance(active_ref, Mapping) or not isinstance(
            superseded_refs, list
        ):
            raise ParityReceiptError("invalid parity authority schema")
        if set(active_ref) != {"path", "receipt_semantic_hash"}:
            raise ParityReceiptError("invalid parity authority schema")
        business_date = str(payload.get("business_date"))
        feature_id = str(payload.get("feature_id"))
        active_path = str(active_ref.get("path"))
        active_view_id = Path(active_path).parent.name
        if active_path != self._relative(business_date, feature_id, active_view_id):
            raise ParityReceiptError("invalid parity authority active path")
        expected_active = self.read(
            business_date,
            feature_id,
            active_view_id,
        )
        if expected_active.get("receipt_semantic_hash") != active_ref.get(
            "receipt_semantic_hash"
        ):
            raise ParityReceiptError("parity authority active hash mismatch")
        normalized_superseded: list[tuple[str, str]] = []
        for item in superseded_refs:
            if not isinstance(item, Mapping) or set(item) != {
                "path",
                "receipt_semantic_hash",
            }:
                raise ParityReceiptError("invalid parity authority schema")
            receipt_path = str(item.get("path"))
            view_id = Path(receipt_path).parent.name
            if receipt_path != self._relative(business_date, feature_id, view_id):
                raise ParityReceiptError("invalid parity authority superseded path")
            receipt = self._read_historical_receipt(
                business_date,
                feature_id,
                view_id,
            )
            if receipt.get("receipt_semantic_hash") != item.get(
                "receipt_semantic_hash"
            ):
                raise ParityReceiptError("parity authority superseded hash mismatch")
            normalized_superseded.append(
                (receipt_path, str(item.get("receipt_semantic_hash")))
            )
        if normalized_superseded != sorted(set(normalized_superseded)):
            raise ParityReceiptError("invalid parity authority superseded order")
        if str(active_ref.get("receipt_semantic_hash")) in {
            digest for _, digest in normalized_superseded
        }:
            raise ParityReceiptError("active receipt cannot supersede itself")
        return deepcopy(payload)

    def read_authority(self, business_date: str, feature_id: str) -> dict[str, Any]:
        relative = self._authority_relative(business_date, feature_id)
        destination = resolve_owned_path(self.root, relative)
        if not destination.is_file():
            raise FileNotFoundError(relative)
        return self._read_authority_file(destination)


__all__ = ["ParityReceiptStore"]
