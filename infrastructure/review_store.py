"""Verified V3.5-owned storage for read-only close-review references."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.stage_store import _assert_safe_tree


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_close_review_reference(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping) or payload.get("schema_version") not in {
        "v3_5.close_review_reference.v1",
        "v3_5.close_review.v1",
    }:
        raise ValueError("invalid close review reference schema")
    trade_date = _date(str(payload.get("trade_date") or ""))
    fixed = {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "write_policy": "review_only_read_only",
    }
    if any(payload.get(key) != expected for key, expected in fixed.items()):
        raise ValueError("unsafe close review reference boundary")
    if payload.get("schema_version") == "v3_5.close_review_reference.v1":
        if payload.get("reference_snapshot") is not True:
            raise ValueError("invalid imported close review provenance")
    elif (
        payload.get("reference_snapshot") is not False
        or payload.get("evidence_mode") != "V3_5_NATIVE_PRODUCTION"
        or not isinstance(payload.get("close_source_sha256"), str)
        or not _SHA256.fullmatch(payload["close_source_sha256"])
    ):
        raise ValueError("invalid native close review provenance")
    for key in ("models", "stages", "stage_union", "kpi", "row_counts"):
        if not isinstance(payload.get(key), Mapping):
            raise ValueError(f"invalid close review {key}")
    for key in ("close_top20", "model_rows", "stage_rows", "top20_attribution", "missing_stages", "cannot_confirm"):
        if not isinstance(payload.get(key), list):
            raise ValueError(f"invalid close review {key}")
    _assert_safe_tree(payload)
    return trade_date


class ReviewStore(NativeDataStore):
    def import_reference(self, payload: Mapping[str, Any]) -> dict[str, str]:
        trade_date = validate_close_review_reference(payload)
        relative = f"close_reviews/{trade_date}.json"
        receipt = f"receipts/close_reviews/{trade_date}.json"
        with self._lock():
            result = self._import(relative, payload, receipt)
        return {**result, "payload_path": relative}

    def read_reference(self, trade_date: str) -> dict[str, Any] | None:
        trade_date = _date(trade_date)
        relative = f"close_reviews/{trade_date}.json"
        receipt_path = f"receipts/close_reviews/{trade_date}.json"
        if not self._path(relative).is_file():
            return None
        try:
            payload = self._read(relative)
            digest = _sha256(payload)
            manifest = self._manifest()
            receipt = self._read(receipt_path)
        except (OSError, ValueError) as error:
            raise ValueError("close review reference evidence cannot be read") from error
        expected_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": relative,
            "source_sha256": digest,
            "trade_date": trade_date,
        }
        if manifest.get(relative) != digest or receipt != expected_receipt:
            raise ValueError("close review reference manifest or receipt mismatch")
        if validate_close_review_reference(payload) != trade_date:
            raise ValueError("close review reference identity mismatch")
        return payload

    def publish_native(self, payload: Mapping[str, Any], *, expected_sha256: str | None = None) -> dict[str, str]:
        trade_date = validate_close_review_reference(payload)
        if payload.get("schema_version") != "v3_5.close_review.v1":
            raise ValueError("native publisher requires native close review schema")
        if expected_sha256 is not None and not _SHA256.fullmatch(expected_sha256):
            raise ValueError("invalid expected close review SHA")
        relative = f"close_reviews/{trade_date}.json"
        receipt_path = f"receipts/close_reviews/{trade_date}.json"
        replacement_sha = _sha256(payload)
        replacement_receipt = {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": relative,
            "source_sha256": replacement_sha,
            "trade_date": trade_date,
        }
        with self._lock():
            manifest = self._manifest()
            current_sha = manifest.get(relative)
            if current_sha is None:
                if expected_sha256 is not None:
                    raise ValueError("expected close review does not exist")
                result = self._import(relative, payload, receipt_path)
                return {**result, "payload_path": relative, "previous_sha256": ""}
            if current_sha == replacement_sha:
                if (
                    not self._path(relative).is_file()
                    or _sha256(self._read(relative)) != replacement_sha
                    or not self._path(receipt_path).is_file()
                    or self._read(receipt_path) != replacement_receipt
                ):
                    raise ValueError("idempotent native review integrity mismatch")
                return {
                    "sha256": replacement_sha,
                    "payload_path": relative,
                    "receipt_path": receipt_path,
                    "previous_sha256": expected_sha256 or current_sha,
                    "supersession_receipt_path": "",
                }
            if expected_sha256 is None or current_sha != expected_sha256:
                raise ValueError("close review does not match expected SHA")
            supersession_path = (
                f"receipts/close_review_supersessions/{trade_date}/{expected_sha256}.json"
            )
            supersession = {
                "schema_version": "v3_5.close_review_supersession.v1",
                "trade_date": trade_date,
                "payload_path": relative,
                "previous_sha256": expected_sha256,
                "replacement_sha256": replacement_sha,
                "reason": "V3_5_NATIVE_CLOSE_PRODUCTION_REPLACES_BLOCKED_REFERENCE",
            }
            self._write(supersession_path, supersession)
            self._write(relative, payload)
            self._write(receipt_path, replacement_receipt)
            manifest[relative] = replacement_sha
            self._write_manifest(manifest)
        return {
            "sha256": replacement_sha,
            "payload_path": relative,
            "receipt_path": receipt_path,
            "previous_sha256": expected_sha256,
            "supersession_receipt_path": supersession_path,
        }

    def list_dates(self) -> list[str]:
        dates: list[str] = []
        for relative in self._manifest():
            path = Path(relative)
            if len(path.parts) != 2 or path.parts[0] != "close_reviews" or path.suffix != ".json":
                continue
            trade_date = path.stem
            try:
                if self.read_reference(trade_date) is not None:
                    dates.append(trade_date)
            except ValueError:
                continue
        return sorted(set(dates), reverse=True)
