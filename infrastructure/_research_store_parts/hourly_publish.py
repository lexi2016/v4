"""Shared, explicit publication helpers for hourly research archives."""
from __future__ import annotations

from collections.abc import Mapping
import re

from contracts.research import validate_research_archive
from infrastructure.data_store import _date, _sha256
from infrastructure.research_hourly_store import _MODES, _SHA256, _slot
from infrastructure._research_store_parts.hourly_sources import (
    _HourlyResearchStore__validate_ready_empty_source_body,
)


def _HourlyResearchStore__transform_validation_relative_body(
    archive_date, slot, mode, source_input_sha256, transformer_identity_sha256
):
    validation_key = _sha256(
        {
            "source_input_sha256": source_input_sha256,
            "transformer_identity_sha256": transformer_identity_sha256,
        }
    )
    return (
        "receipts/research/hourly/transform-validation/"
        f"{mode.lower()}/{archive_date}/{slot}/{validation_key}.json"
    )


def _HourlyResearchStore__receipt_body(payload, digest, *, slot, mode):
    archive_date = str(payload["archive_date"])
    receipt = {
        "schema_version": "v3_5.hourly_research_receipt.v1",
        "archive_date": archive_date,
        "slot": slot,
        "mode": mode,
        "payload_path": f"research/hourly/{mode.lower()}/{archive_date}/{slot}.json",
        "payload_sha256": digest,
        "source_input_sha256": payload["source_input_sha256"],
        "article_count": payload["article_count"],
        "stock_pool_count": payload["stock_pool_count"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    empty_evidence = payload.get("ready_empty_evidence_v1")
    if isinstance(empty_evidence, Mapping):
        receipt["hourly_artifact_status"] = "READY_EMPTY"
        receipt["ready_empty_evidence_v1"] = dict(empty_evidence)
    return receipt


def _HourlyResearchStore__transform_validation_body(
    payload, digest, *, slot, mode, transformer_identity_sha256
):
    archive_date = str(payload["archive_date"])
    source_input_sha256 = str(payload["source_input_sha256"])
    return {
        "schema_version": "v3_5.hourly_research_transform_validation.v1",
        "archive_date": archive_date,
        "slot": slot,
        "mode": mode,
        "payload_path": f"research/hourly/{mode.lower()}/{archive_date}/{slot}.json",
        "payload_sha256": digest,
        "source_input_sha256": source_input_sha256,
        "transformer_identity_sha256": transformer_identity_sha256,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _HourlyResearchStore_publish_body(
    self, payload, *, slot, mode, transformer_identity_sha256
):
    archive_date = validate_research_archive(payload)
    normalized_slot = _slot(slot)
    normalized_mode = str(mode).upper()
    if normalized_mode not in _MODES:
        raise ValueError("hourly research mode must be LIVE, REPLAY, or BACKFILL")
    verified_ready_empty_source = "ready_empty_evidence_v1" in payload
    if verified_ready_empty_source:
        _HourlyResearchStore__validate_ready_empty_source_body(
            self,
            payload,
            archive_date=archive_date,
            slot=normalized_slot,
            mode=normalized_mode,
        )
    normalized_transformer_sha = None
    if transformer_identity_sha256 is not None:
        normalized_transformer_sha = str(transformer_identity_sha256).lower()
        if not _SHA256.fullmatch(normalized_transformer_sha):
            raise ValueError("hourly research transformer identity must be SHA-256")
    relative = self._relative(archive_date, normalized_slot, normalized_mode)
    receipt_relative = self._receipt_relative(
        archive_date, normalized_slot, normalized_mode
    )
    digest = _sha256(payload)
    receipt = self._receipt(
        payload, digest, slot=normalized_slot, mode=normalized_mode
    )
    latest_updated = False
    with self._lock():
        manifest = self._manifest()
        existing = manifest.get(relative)
        if existing and existing != digest:
            raise ValueError("conflicting hourly research materialization")
        payload_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        interrupted_recovery = not existing and payload_path.exists()
        if normalized_mode == "LIVE" and not (
            existing or interrupted_recovery or verified_ready_empty_source
        ):
            self._assert_latest_not_backwards(archive_date, normalized_slot)
        if existing:
            if (
                not payload_path.is_file()
                or _sha256(self._read(relative)) != digest
                or not receipt_path.is_file()
                or self._read(receipt_relative) != receipt
            ):
                raise ValueError("hourly research integrity mismatch")
        elif payload_path.exists():
            if not payload_path.is_file() or _sha256(self._read(relative)) != digest:
                raise ValueError("conflicting interrupted hourly research artifact")
            if receipt_path.exists():
                if not receipt_path.is_file() or self._read(receipt_relative) != receipt:
                    raise ValueError("conflicting interrupted hourly research receipt")
            else:
                self._write(receipt_relative, receipt)
            manifest[relative] = digest
            self._write_manifest(manifest)
        else:
            if receipt_path.exists():
                raise ValueError("orphan hourly research receipt")
            self._write(relative, payload)
            self._write(receipt_relative, receipt)
            manifest[relative] = digest
            self._write_manifest(manifest)
        if normalized_transformer_sha is not None:
            self._publish_transform_validation_locked(
                payload,
                digest,
                slot=normalized_slot,
                mode=normalized_mode,
                transformer_identity_sha256=normalized_transformer_sha,
            )
        if normalized_mode == "LIVE" and not self._latest_is_after(
            archive_date, normalized_slot
        ):
            latest_updated = self._update_latest(
                archive_date, normalized_slot, digest
            )
    return {
        "archive_date": archive_date,
        "slot": normalized_slot,
        "mode": normalized_mode,
        "payload_path": relative,
        "receipt_path": receipt_relative,
        "payload_sha256": digest,
        "latest_updated": latest_updated,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _HourlyResearchStore__publish_transform_validation_locked_body(
    self, payload, digest, *, slot, mode, transformer_identity_sha256
):
    archive_date = str(payload["archive_date"])
    source_input_sha256 = str(payload["source_input_sha256"]).lower()
    validation = self._transform_validation(
        payload,
        digest,
        slot=slot,
        mode=mode,
        transformer_identity_sha256=transformer_identity_sha256,
    )
    validation_relative = self._transform_validation_relative(
        archive_date, slot, mode, source_input_sha256, transformer_identity_sha256
    )
    validation_path = self._path(validation_relative)
    if validation_path.exists():
        if not validation_path.is_file() or self._read(validation_relative) != validation:
            raise ValueError("hourly research transform validation mismatch")
    else:
        self._write(validation_relative, validation)


def _HourlyResearchStore__latest_is_after_body(self, archive_date, slot):
    destination = self._path("research/hourly/latest.json")
    if not destination.exists():
        return False
    if not destination.is_file():
        raise ValueError("invalid hourly research latest pointer")
    existing = self._read("research/hourly/latest.json")
    self._validate_pointer(existing)
    return (str(existing["archive_date"]), str(existing["slot"])) > (
        archive_date, slot
    )


def _HourlyResearchStore__update_latest_body(self, archive_date, slot, digest):
    relative = "research/hourly/latest.json"
    destination = self._path(relative)
    if destination.is_file():
        existing = self._read(relative)
        self._validate_pointer(existing)
        existing_position = (str(existing["archive_date"]), str(existing["slot"]))
        requested_position = (archive_date, slot)
        if existing_position > requested_position:
            raise ValueError("LIVE hourly research publication cannot move latest backwards")
        if (
            existing_position == requested_position
            and existing["payload_sha256"] == digest
        ):
            return False
    body = {
        "schema_version": "v3_5.hourly_research_latest_pointer.v1",
        "archive_date": archive_date,
        "slot": slot,
        "mode": "LIVE",
        "payload_path": self._relative(archive_date, slot, "LIVE"),
        "payload_sha256": digest,
    }
    pointer = {**body, "pointer_semantic_hash": _sha256(body)}
    self._write(relative, pointer)
    return True


def _HourlyResearchStore__validate_pointer_body(pointer):
    fields = {
        "schema_version", "archive_date", "slot", "mode", "payload_path",
        "payload_sha256", "pointer_semantic_hash",
    }
    if not isinstance(pointer, Mapping) or set(pointer) != fields:
        raise ValueError("invalid hourly research latest pointer")
    archive_date = _date(str(pointer.get("archive_date") or ""))
    slot = _slot(str(pointer.get("slot") or ""))
    body = {
        key: value
        for key, value in pointer.items()
        if key != "pointer_semantic_hash"
    }
    if (
        pointer.get("schema_version")
        != "v3_5.hourly_research_latest_pointer.v1"
        or pointer.get("mode") != "LIVE"
        or pointer.get("payload_path")
        != f"research/hourly/live/{archive_date}/{slot}.json"
        or not _SHA256.fullmatch(str(pointer.get("payload_sha256") or ""))
        or pointer.get("pointer_semantic_hash") != _sha256(body)
    ):
        raise ValueError("invalid hourly research latest pointer")


__all__ = [
    "_HourlyResearchStore__latest_is_after_body",
    "_HourlyResearchStore__publish_transform_validation_locked_body",
    "_HourlyResearchStore__receipt_body",
    "_HourlyResearchStore__transform_validation_body",
    "_HourlyResearchStore__transform_validation_relative_body",
    "_HourlyResearchStore__update_latest_body",
    "_HourlyResearchStore__validate_pointer_body",
    "_HourlyResearchStore_publish_body",
]
