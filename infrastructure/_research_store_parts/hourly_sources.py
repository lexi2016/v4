"""Shared, explicit source and archive validation for hourly research."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

from contracts.research import validate_research_archive
from domains.research_source_validation import (
    collector_source_cutoff,
    strict_source_receipt_time,
)
from infrastructure.data_store import _date, _sha256
from infrastructure.owned_path import resolve_owned_path
from infrastructure.research_source_evidence import read_zsxq_slot_evidence
from infrastructure.research_hourly_store import _MODES, _SHA256, _slot


def _HourlyResearchStore_read_latest_for_date_body(self, archive_date, *, mode):
    """Read the highest verified slot for one exact date only."""
    archive_date = _date(archive_date)
    slots = self.list_slots(archive_date, mode=mode)
    if not slots:
        return None
    slot = slots[-1]
    payload = self.read_exact(archive_date, slot, mode=mode)
    if payload is None:
        raise ValueError("hourly research manifest or receipt mismatch")
    return slot, payload


def _HourlyResearchStore_read_exact_body(self, archive_date, slot, *, mode):
    archive_date = _date(archive_date)
    normalized_slot = _slot(slot)
    normalized_mode = str(mode).upper()
    if normalized_mode not in _MODES:
        raise ValueError("hourly research mode must be LIVE, REPLAY, or BACKFILL")
    relative = self._relative(archive_date, normalized_slot, normalized_mode)
    receipt_relative = self._receipt_relative(
        archive_date, normalized_slot, normalized_mode
    )
    payload_path = self._path(relative)
    receipt_path = self._path(receipt_relative)
    manifest = self._manifest()
    if not payload_path.is_file():
        if payload_path.exists() or receipt_path.exists() or relative in manifest:
            raise ValueError("hourly research manifest or receipt mismatch")
        return None
    payload = self._read(relative)
    digest = _sha256(payload)
    if (
        manifest.get(relative) != digest
        or not receipt_path.is_file()
        or self._read(receipt_relative)
        != self._receipt(payload, digest, slot=normalized_slot, mode=normalized_mode)
        or validate_research_archive(payload) != archive_date
    ):
        raise ValueError("hourly research manifest or receipt mismatch")
    if "ready_empty_evidence_v1" in payload:
        _HourlyResearchStore__validate_ready_empty_source_body(
            self,
            payload,
            archive_date=archive_date,
            slot=normalized_slot,
            mode=normalized_mode,
        )
    return payload


def _HourlyResearchStore__normalize_ready_empty_owned_path_body(
    self, value, expected_relative
):
    """Normalize a run artifact declaration to its exact owned relative path."""
    if not isinstance(value, str) or not value:
        raise ValueError("hourly research ready-empty run path is missing")
    declared = Path(value)
    if declared.is_absolute():
        canonical_root = Path(self.root).resolve(strict=False)
        try:
            relative = declared.relative_to(canonical_root)
        except ValueError as error:
            raise ValueError(
                "hourly research ready-empty run path is outside the owned root"
            ) from error
        if ".." in relative.parts:
            raise ValueError("hourly research ready-empty run path traverses parents")
        relative_value = relative.as_posix()
    else:
        relative_value = value
    try:
        actual_path = resolve_owned_path(self.root, relative_value)
        expected_path = resolve_owned_path(self.root, expected_relative)
    except ValueError as error:
        raise ValueError("hourly research ready-empty run path is invalid") from error
    if actual_path != expected_path:
        raise ValueError("hourly research ready-empty run path identity mismatch")
    return expected_relative


def _HourlyResearchStore__validate_ready_empty_source_body(
    self, payload, *, archive_date, slot, mode
):
    """Revalidate the exact incoming source and authenticated empty receipt."""
    if mode != "LIVE" or slot != "1700":
        raise ValueError("hourly research ready-empty source is outside the recovery slot")
    evidence = payload.get("ready_empty_evidence_v1")
    if not isinstance(evidence, Mapping):
        raise ValueError("hourly research ready-empty source evidence is missing")
    source_relative = f"research/incoming/{archive_date}/{slot}.json"
    try:
        source_bytes = self._path(source_relative).read_bytes()
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        source = json.loads(source_bytes.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("hourly research ready-empty source witness is missing") from error
    if source_sha != payload.get("source_input_sha256") or not isinstance(source, dict):
        raise ValueError("hourly research ready-empty source witness SHA mismatch")
    manifest = source.get("source_manifest")
    hourly = source.get("hourly_research")
    if not isinstance(manifest, dict):
        raise ValueError("hourly research ready-empty source manifest is missing")
    source_proof = manifest.get("ready_empty_source_proof")
    if not isinstance(source_proof, dict) or dict(evidence) != {
        **source_proof,
        "source_input_sha256": source_sha,
    }:
        raise ValueError("hourly research ready-empty source proof mismatch")
    if (
        source.get("trade_date") != archive_date
        or source.get("slot") != slot
        or manifest.get("trade_date") != archive_date
        or manifest.get("hourly_slot") != slot
        or manifest.get("materialization_origin") != "MANUAL_RECOVERY"
        or manifest.get("capture_origin") != "ORIGINAL_SLOT"
        or manifest.get("original_time_capture") is not True
        or manifest.get("natural_execution_verified") is not False
        or manifest.get("source_receipts") != [evidence.get("source_receipt_path")]
        or manifest.get("source_receipt_sha256") != evidence.get("source_receipt_sha256")
        or not isinstance(hourly, dict)
        or hourly.get("trade_date") != archive_date
        or hourly.get("latest_slot") != slot
        or hourly.get("status") != "READY_EMPTY"
        or type(hourly.get("row_count")) is not int
        or hourly.get("row_count") != 0
        or any(
            source.get(name) != []
            for name in (
                "raw_items", "research_items", "stock_research_timeline",
                "stock_research_daily",
            )
        )
    ):
        raise ValueError("hourly research ready-empty source identity mismatch")

    evidence_files = read_zsxq_slot_evidence(self.root, archive_date, slot)
    if evidence_files is None:
        raise ValueError("hourly research ready-empty status receipt identity mismatch")
    status = evidence_files.status
    cutoff = collector_source_cutoff(archive_date, slot)
    fetched = strict_source_receipt_time(status.get("fetched_at"))
    materialized = strict_source_receipt_time(evidence.get("materialized_at"))
    run_id = str(status.get("latest_run_id") or "")
    run_relative = f"external_sources/zsxq_hourly/{run_id}"
    paths = status.get("paths")
    try:
        if re.fullmatch(rf"{archive_date}_{slot}00_[A-Za-z0-9_-]+", run_id) is None:
            raise ValueError("hourly research ready-empty run identity mismatch")
        if not isinstance(paths, Mapping):
            raise ValueError("hourly research ready-empty run identity mismatch")
        _HourlyResearchStore__normalize_ready_empty_owned_path_body(
            self, paths.get("run_dir"), run_relative
        )
        _HourlyResearchStore__normalize_ready_empty_owned_path_body(
            self, paths.get("summary"),
            f"{run_relative}/zsxq_summary.json",
        )
        _HourlyResearchStore__normalize_ready_empty_owned_path_body(
            self, paths.get("fetch_result"),
            f"{run_relative}/zsxq_recent_topics_fetch_result.json",
        )
    except ValueError as error:
        raise ValueError("hourly research ready-empty run identity mismatch") from error
    if (
        status.get("status") != "READY_EMPTY"
        or status.get("status_path") != evidence.get("source_receipt_path")
        or evidence_files.status_sha256 != evidence.get("source_receipt_sha256")
        or evidence_files.summary_sha256 != evidence.get("summary_sha256")
        or evidence_files.fetch_result_sha256 != evidence.get("fetch_result_sha256")
        or status.get("fetch_ok") is not True
        or evidence_files.fetch_result.get("success") is not True
        or type(status.get("page_count")) is not int
        or status.get("page_count") < 1
        or status.get("topic_count") != 0
        or type(status.get("topic_count")) is not int
        or status.get("effective_topic_count") != 0
        or type(status.get("effective_topic_count")) is not int
        or fetched is None
        or fetched.strftime("%Y%m%d") != archive_date
        or fetched > cutoff
        or materialized is None
        or materialized.strftime("%Y%m%d") != archive_date
        or materialized < cutoff
        or evidence.get("source_cutoff") != cutoff.isoformat(timespec="seconds")
        or manifest.get("source_cutoff") != evidence.get("source_cutoff")
        or manifest.get("fetched_at") != evidence.get("fetched_at")
        or manifest.get("materialized_at") != evidence.get("materialized_at")
        or manifest.get("available_at") != evidence.get("available_at")
        or manifest.get("generated_at") != evidence.get("materialized_at")
        or manifest.get("published_at") != evidence.get("materialized_at")
    ):
        raise ValueError("hourly research ready-empty status receipt mismatch")


def _HourlyResearchStore_reuse_matching_source_body(
    self, archive_date, slot, *, mode, source_input_sha256,
    transformer_identity_sha256,
):
    """Republish a finalized exact artifact only when its source is identical."""
    archive_date = _date(archive_date)
    normalized_slot = _slot(slot)
    normalized_mode = str(mode).upper()
    if normalized_mode not in _MODES:
        raise ValueError("hourly research mode must be LIVE, REPLAY, or BACKFILL")
    normalized_source_sha = str(source_input_sha256).lower()
    if not _SHA256.fullmatch(normalized_source_sha):
        raise ValueError("hourly research source SHA must be SHA-256")
    normalized_transformer_sha = str(transformer_identity_sha256).lower()
    if not _SHA256.fullmatch(normalized_transformer_sha):
        raise ValueError("hourly research transformer identity must be SHA-256")
    relative = self._relative(archive_date, normalized_slot, normalized_mode)
    validation_relative = self._transform_validation_relative(
        archive_date,
        normalized_slot,
        normalized_mode,
        normalized_source_sha,
        normalized_transformer_sha,
    )
    latest_updated = False
    with self._lock():
        validation_path = self._path(validation_relative)
        if not validation_path.is_file():
            if validation_path.exists():
                raise ValueError("invalid hourly research transform validation")
            return None
        if relative not in self._manifest():
            raise ValueError("orphan hourly research transform validation")
        payload = self.read_exact(
            archive_date, normalized_slot, mode=normalized_mode
        )
        if payload is None:
            raise ValueError("hourly research manifest or receipt mismatch")
        digest = _sha256(payload)
        expected_validation = self._transform_validation(
            payload,
            digest,
            slot=normalized_slot,
            mode=normalized_mode,
            transformer_identity_sha256=normalized_transformer_sha,
        )
        if (
            payload["source_input_sha256"] != normalized_source_sha
            or self._read(validation_relative) != expected_validation
        ):
            raise ValueError("hourly research transform validation mismatch")
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
        "receipt_path": self._receipt_relative(
            archive_date, normalized_slot, normalized_mode
        ),
        "payload_sha256": digest,
        "latest_updated": latest_updated,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _HourlyResearchStore_read_latest_body(self):
    relative = "research/hourly/latest.json"
    pointer_path = self._path(relative)
    if not pointer_path.is_file():
        if pointer_path.exists():
            raise ValueError("invalid hourly research latest pointer")
        return None
    pointer = self._read(relative)
    self._validate_pointer(pointer)
    payload = self.read_exact(
        str(pointer["archive_date"]), str(pointer["slot"]), mode="LIVE"
    )
    if payload is None or _sha256(payload) != pointer["payload_sha256"]:
        raise ValueError("hourly research latest pointer target mismatch")
    return payload


__all__ = [
    "_HourlyResearchStore__normalize_ready_empty_owned_path_body",
    "_HourlyResearchStore__validate_ready_empty_source_body",
    "_HourlyResearchStore_read_exact_body",
    "_HourlyResearchStore_read_latest_body",
    "_HourlyResearchStore_read_latest_for_date_body",
    "_HourlyResearchStore_reuse_matching_source_body",
]
