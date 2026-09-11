"""Exact-date research archives with an explicit LIVE-only latest pointer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from infrastructure.interprocess_lock import owned_interprocess_lock
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

from contracts.research_day_product import (
    MANAGER_DECISION_SCHEMA_VERSION,
    PRODUCT_SCHEMA_VERSION,
    RESEARCH_SUPPLY_TYPE,
    SELECTION_CONTRACT_ID,
    SELECTION_SCHEMA_VERSION,
    SELECTION_SOURCE_SCOPE_INVALIDATION_SCHEMA_VERSION,
    SELECTION_SOURCE_SCOPE_INVALIDATION_TYPE,
    _selection_market_name,
    selection_source_scope_invalidation_id,
    validate_manager_decision_projection,
    validate_selection_research_product,
    validate_selection_source_scope_invalidation,
    validate_manager_research_decision,
    validate_research_supply_envelope,
    validate_research_supply_receipt,
    validate_research_day_product,
)
from domains.research_day_product import (
    _selection_aware_hkt,
    append_selection_phase,
)
from contracts.research import validate_research_archive
from infrastructure.data_store import NativeDataStore, _date, _sha256
from infrastructure.owned_path import resolve_owned_path


_MODES = frozenset({"LIVE", "REPLAY", "BACKFILL"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


_MANAGER_OVERLAY_PROOF_SCHEMA_VERSION = "v3_5.manager_source_successor_proof.v1"
_MANAGER_OVERLAY_PROOF_TYPE = "MANAGER_SOURCE_SUCCESSOR_PROOF"
_MANAGER_OVERLAY_RULE_ID = "V35_MANAGER_SOURCE_SUCCESSOR_V1"
_MANAGER_OVERLAY_RULE_VERSION = "1.0.0"
_MANAGER_OVERLAY_PROOF_FIELDS = frozenset(
    {
        "schema_version",
        "type",
        "rule_id",
        "rule_version",
        "source_date",
        "target_trade_date",
        "base_supply_ref",
        "successor_supply_ref",
        "candidate_ids",
        "candidate_set_sha256",
        "records",
        "envelope_changed_paths",
        "safety",
    }
)
_MANAGER_OVERLAY_SUPPLY_REF_FIELDS = frozenset(
    {
        "path",
        "raw_sha256",
        "frozen_payload_sha256",
        "run_id",
        "source_date",
        "target_trade_date",
    }
)
_MANAGER_OVERLAY_RECORD_FIELDS = frozenset(
    {"candidate_id", "ticker", "before_card_sha", "after_card_sha", "changed_paths"}
)
_MANAGER_OVERLAY_SAFETY_FIELDS = frozenset(
    {"RESEARCH_ONLY", "WATCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent"}
)

# This is deliberately a closed set.  The proof is an authorization for the
# observed V2 -> V4 evidence enrichment only; it cannot grant itself a new
# mutation class by adding a path to the artifact.
MANAGER_OVERLAY_CARD_CHANGED_PATHS = frozenset(
    {
        "candidate_claim_status",
        "catalyst.status",
        "claim_status",
        "confirmation_conditions",
        "content_source_receipts",
        "counterevidence_cn",
        "evidence_level",
        "independent_evidence_dimensions.research.status",
        "invalidation_conditions",
        "investment_thesis_cn",
        "manager_research",
        "official_facts",
        "official_source.identity_status",
        "primary_fact_review",
        "promotion_missing_fields",
        "review_direction",
        "review_priority_bucket",
        "review_status",
        "source.receipt_path",
        "source.receipt_sha256",
        "source.source_class",
        "typed_gaps",
    }
)
MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS = frozenset(
    {
        "frozen_payload.conditional_watch_candidates",
        "frozen_payload.delivery_timing.actual_generated_at",
        "frozen_payload.delivery_timing.origin",
        "frozen_payload.event_cards[*]",
        "frozen_payload.formal_shortlist",
        "frozen_payload.generated_at",
        "frozen_payload.origin",
        "frozen_payload.primary_fact_reviews",
        "frozen_payload.run_id",
        "frozen_payload.source_receipts",
        "frozen_payload_sha256",
        "generated_at",
        "run_id",
    }
)
MANAGER_OVERLAY_PRODUCT_DERIVED_FIELDS = frozenset(
    {"catalyst", "evidence_level", "source_status", "source_time"}
)


def _manager_overlay_changed_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    """Return deterministic leaf/container paths for an evidence diff."""

    changed: list[str] = []
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                changed.append(path)
            else:
                changed.extend(_manager_overlay_changed_paths(before[key], after[key], path))
        return changed
    if isinstance(before, list) and isinstance(after, list):
        if before != after:
            changed.append(prefix)
        return changed
    if before != after:
        changed.append(prefix)
    return changed


def _manager_overlay_envelope_paths(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    paths = _manager_overlay_changed_paths(before, after)
    return sorted(
        "frozen_payload.event_cards[*]" if path == "frozen_payload.event_cards" else path
        for path in paths
    )


def _slot(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}", value):
        raise ValueError("research slot must use HHMM")
    if int(value[:2]) > 23 or int(value[2:]) > 59:
        raise ValueError("research slot must be a real time")
    return value


class ResearchArchiveStore(NativeDataStore):
    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    @staticmethod
    def _relative(archive_date: str) -> str:
        return f"research/archives/{archive_date}.json"

    @staticmethod
    def _receipt_relative(archive_date: str) -> str:
        return f"receipts/research/archives/{archive_date}.json"

    @staticmethod
    def _day_relative(archive_date: str) -> str:
        """Return the physical namespace owned by exact-day products.

        Generic hourly/archive material uses ``research/archives``.  A day
        product is a different contract and must never claim that same date
        key, because a legacy archive may already exist there.
        """

        return f"research/day/archives/{archive_date}.json"

    @staticmethod
    def _day_receipt_relative(archive_date: str) -> str:
        return f"receipts/research/day/archives/{archive_date}.json"

    @staticmethod
    def _day_latest_relative() -> str:
        return "research/day/latest.json"

    @staticmethod
    def _day_current_relative() -> str:
        return "research/day/current.json"

    @staticmethod
    def _receipt(payload: Mapping[str, Any], digest: str) -> dict[str, Any]:
        archive_date = str(payload["archive_date"])
        return {
            "schema_version": "v3_5.research_archive_receipt.v1",
            "archive_date": archive_date,
            "payload_path": ResearchArchiveStore._relative(archive_date),
            "payload_sha256": digest,
            "source_input_sha256": payload["source_input_sha256"],
            "article_count": payload["article_count"],
            "stock_pool_count": payload["stock_pool_count"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @staticmethod
    def _day_receipt(payload: Mapping[str, Any], digest: str) -> dict[str, Any]:
        archive_date = str(payload["archive_date"])
        return {
            "schema_version": "v3_5.research_day_product_receipt.v1",
            "contract_id": PRODUCT_SCHEMA_VERSION,
            "archive_date": archive_date,
            "payload_path": ResearchArchiveStore._day_relative(archive_date),
            "payload_sha256": digest,
            "source_slots": list(payload["expected_slots"]),
            "counts": dict(payload["counts"]),
            "status": payload["status"],
            "authoritative": bool(payload["authoritative"]),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def publish(self, payload: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
        archive_date = validate_research_archive(payload)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError("research publication mode must be LIVE, REPLAY, or BACKFILL")
        relative = self._relative(archive_date)
        receipt_relative = self._receipt_relative(archive_date)
        digest = _sha256(payload)
        receipt = self._receipt(payload, digest)
        latest_updated = False
        with self._lock():
            manifest = self._manifest()
            existing = manifest.get(relative)
            if existing and existing != digest:
                raise ValueError("conflicting research archive re-import")
            if existing:
                if (
                    not self._path(relative).is_file()
                    or _sha256(self._read(relative)) != digest
                    or not self._path(receipt_relative).is_file()
                    or self._read(receipt_relative) != receipt
                ):
                    raise ValueError("research archive integrity mismatch")
            else:
                if self._path(relative).exists() or self._path(receipt_relative).exists():
                    raise ValueError("orphan research archive or receipt")
                self._write(relative, payload)
                self._write(receipt_relative, receipt)
                manifest[relative] = digest
                self._write_manifest(manifest)
            if normalized_mode == "LIVE":
                latest_updated = self._update_latest(archive_date, digest)
        return {
            "archive_date": archive_date,
            "mode": normalized_mode,
            "payload_path": relative,
            "receipt_path": receipt_relative,
            "payload_sha256": digest,
            "latest_updated": latest_updated,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _update_latest(self, archive_date: str, digest: str) -> bool:
        relative = "research/latest.json"
        destination = self._path(relative)
        if destination.is_file():
            existing = self._read(relative)
            self._validate_pointer(existing)
            if str(existing["archive_date"]) > archive_date:
                raise ValueError("LIVE research publication cannot move latest backwards")
            if str(existing["archive_date"]) == archive_date and existing["payload_sha256"] == digest:
                return False
        body = {
            "schema_version": "v3_5.research_latest_pointer.v1",
            "archive_date": archive_date,
            "payload_path": self._relative(archive_date),
            "payload_sha256": digest,
        }
        pointer = {**body, "pointer_semantic_hash": _sha256(body)}
        self._write(relative, pointer)
        return True

    @staticmethod
    def _validate_pointer(pointer: Mapping[str, Any]) -> None:
        if not isinstance(pointer, Mapping) or set(pointer) != {
            "schema_version",
            "archive_date",
            "payload_path",
            "payload_sha256",
            "pointer_semantic_hash",
        }:
            raise ValueError("invalid research latest pointer")
        archive_date = _date(str(pointer.get("archive_date") or ""))
        body = {key: value for key, value in pointer.items() if key != "pointer_semantic_hash"}
        if (
            pointer.get("schema_version") != "v3_5.research_latest_pointer.v1"
            or pointer.get("payload_path") != ResearchArchiveStore._relative(archive_date)
            or not _SHA256.fullmatch(str(pointer.get("payload_sha256") or ""))
            or pointer.get("pointer_semantic_hash") != _sha256(body)
        ):
            raise ValueError("invalid research latest pointer")

    def read_exact(self, archive_date: str) -> dict[str, Any] | None:
        archive_date = _date(archive_date)
        relative = self._relative(archive_date)
        receipt_relative = self._receipt_relative(archive_date)
        payload_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        manifest = self._manifest()
        if not payload_path.is_file():
            if payload_path.exists() or receipt_path.exists() or relative in manifest:
                raise ValueError("research archive manifest or receipt mismatch")
            return None
        payload = self._read(relative)
        if payload.get("schema_version") == PRODUCT_SCHEMA_VERSION:
            raise ValueError("generic research archive path contains a day product")
        digest = _sha256(payload)
        if (
            manifest.get(relative) != digest
            or not receipt_path.is_file()
            or self._read(receipt_relative) != self._receipt(payload, digest)
            or validate_research_archive(payload) != archive_date
        ):
            raise ValueError("research archive manifest or receipt mismatch")
        return payload

    def publish_day_product(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Publish a complete exact-date day product in its own namespace.

        The legacy generic archive and its receipt remain authoritative at
        ``research/archives/{date}.json``.  Day products use a separate
        manifest key and pointer namespace, so publishing a full-day product
        cannot overwrite or reinterpret a same-date generic archive.
        """

        archive_date = validate_research_day_product(payload)
        relative = self._day_relative(archive_date)
        receipt_relative = self._day_receipt_relative(archive_date)
        digest = _sha256(payload)
        receipt = self._day_receipt(payload, digest)
        latest_updated = False
        current_updated = False
        with self._lock():
            manifest = self._manifest()
            existing = manifest.get(relative)
            payload_path = self._path(relative)
            receipt_path = self._path(receipt_relative)
            if existing and existing != digest:
                raise ValueError("conflicting research day product re-import")
            if existing:
                existing_payload = self._read(relative) if payload_path.is_file() else {}
                if existing_payload.get("schema_version") != PRODUCT_SCHEMA_VERSION:
                    raise ValueError("existing generic archive blocks day product")
                if (
                    not payload_path.is_file()
                    or _sha256(existing_payload) != digest
                    or not receipt_path.is_file()
                    or self._read(receipt_relative) != receipt
                ):
                    raise ValueError("research day product manifest or receipt mismatch")
            else:
                if payload_path.exists() or receipt_path.exists():
                    raise ValueError("orphan research archive or receipt")
                self._write(relative, payload)
                self._write(receipt_relative, receipt)
                manifest[relative] = digest
                self._write_manifest(manifest)
            latest_updated = self._update_day_latest(archive_date, digest)
            current_updated = self._update_day_current(archive_date, digest)
        current_relative = self._day_current_relative()
        current = self._read(current_relative)
        return {
            "archive_date": archive_date,
            "payload_path": relative,
            "receipt_path": receipt_relative,
            "payload_sha256": digest,
            "receipt_sha256": _sha256(receipt),
            "manifest_sha256": _sha256(self._manifest()),
            "latest_updated": latest_updated,
            "current_updated": current_updated,
            "current_path": current_relative,
            "current_sha256": _sha256(current),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _update_day_latest(self, archive_date: str, digest: str) -> bool:
        relative = self._day_latest_relative()
        destination = self._path(relative)
        if destination.is_file():
            existing = self._read(relative)
            self._validate_day_latest_pointer(existing)
            existing_position = str(existing["archive_date"])
            if existing_position > archive_date:
                raise ValueError("research day product cannot move latest backwards")
            if (
                existing_position == archive_date
                and existing["payload_sha256"] == digest
            ):
                return False
        elif destination.exists():
            raise ValueError("invalid research latest pointer")
        body = {
            "schema_version": "v3_5.research_day_latest_pointer.v1",
            "archive_date": archive_date,
            "payload_path": self._day_relative(archive_date),
            "payload_sha256": digest,
        }
        self._write(relative, {**body, "pointer_semantic_hash": _sha256(body)})
        return True

    @staticmethod
    def _validate_day_latest_pointer(pointer: Mapping[str, Any]) -> None:
        fields = {
            "schema_version",
            "archive_date",
            "payload_path",
            "payload_sha256",
            "pointer_semantic_hash",
        }
        if not isinstance(pointer, Mapping) or set(pointer) != fields:
            raise ValueError("invalid research day latest pointer")
        archive_date = _date(str(pointer.get("archive_date") or ""))
        body = {
            key: value for key, value in pointer.items() if key != "pointer_semantic_hash"
        }
        if (
            pointer.get("schema_version") != "v3_5.research_day_latest_pointer.v1"
            or pointer.get("payload_path") != ResearchArchiveStore._day_relative(archive_date)
            or not _SHA256.fullmatch(str(pointer.get("payload_sha256") or ""))
            or pointer.get("pointer_semantic_hash") != _sha256(body)
        ):
            raise ValueError("invalid research day latest pointer")

    def _update_day_current(self, archive_date: str, digest: str) -> bool:
        relative = self._day_current_relative()
        destination = self._path(relative)
        if destination.is_file():
            existing = self._read(relative)
            self._validate_current_pointer(existing)
            existing_position = str(existing["archive_date"])
            if existing_position > archive_date:
                raise ValueError("research day product cannot move current backwards")
            if (
                existing_position == archive_date
                and existing["payload_sha256"] == digest
            ):
                return False
        elif destination.exists():
            raise ValueError("invalid research current pointer")
        body = {
            "schema_version": "v3_5.research_day_current_pointer.v1",
            "archive_date": archive_date,
            "payload_path": self._day_relative(archive_date),
            "payload_sha256": digest,
        }
        self._write(relative, {**body, "pointer_semantic_hash": _sha256(body)})
        return True

    @staticmethod
    def _validate_current_pointer(pointer: Mapping[str, Any]) -> None:
        fields = {
            "schema_version",
            "archive_date",
            "payload_path",
            "payload_sha256",
            "pointer_semantic_hash",
        }
        if not isinstance(pointer, Mapping) or set(pointer) != fields:
            raise ValueError("invalid research current pointer")
        archive_date = _date(str(pointer.get("archive_date") or ""))
        body = {
            key: value for key, value in pointer.items() if key != "pointer_semantic_hash"
        }
        if (
            pointer.get("schema_version") != "v3_5.research_day_current_pointer.v1"
            or pointer.get("payload_path") != ResearchArchiveStore._day_relative(archive_date)
            or not _SHA256.fullmatch(str(pointer.get("payload_sha256") or ""))
            or pointer.get("pointer_semantic_hash") != _sha256(body)
        ):
            raise ValueError("invalid research current pointer")

    def read_day_exact(self, archive_date: str) -> dict[str, Any] | None:
        archive_date = _date(archive_date)
        relative = self._day_relative(archive_date)
        receipt_relative = self._day_receipt_relative(archive_date)
        payload_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        manifest = self._manifest()
        if not payload_path.is_file():
            if payload_path.exists() or receipt_path.exists() or relative in manifest:
                raise ValueError("research day product manifest or receipt mismatch")
            return None
        payload = self._read(relative)
        if payload.get("schema_version") != PRODUCT_SCHEMA_VERSION:
            return None
        digest = _sha256(payload)
        receipt = self._day_receipt(payload, digest)
        if (
            manifest.get(relative) != digest
            or not receipt_path.is_file()
            or self._read(receipt_relative) != receipt
            or validate_research_day_product(payload) != archive_date
        ):
            raise ValueError("research day product manifest or receipt mismatch")
        return payload

    def read_day_latest(self) -> dict[str, Any] | None:
        relative = self._day_latest_relative()
        pointer_path = self._path(relative)
        if not pointer_path.is_file():
            if pointer_path.exists():
                raise ValueError("invalid research latest pointer")
            return None
        pointer = self._read(relative)
        self._validate_day_latest_pointer(pointer)
        payload = self.read_day_exact(str(pointer["archive_date"]))
        if payload is None or _sha256(payload) != pointer["payload_sha256"]:
            return None
        return payload

    def read_day_current(self) -> dict[str, Any] | None:
        relative = self._day_current_relative()
        pointer_path = self._path(relative)
        if not pointer_path.is_file():
            if pointer_path.exists():
                raise ValueError("invalid research current pointer")
            return None
        pointer = self._read(relative)
        self._validate_current_pointer(pointer)
        payload = self.read_day_exact(str(pointer["archive_date"]))
        if payload is None or _sha256(payload) != pointer["payload_sha256"]:
            raise ValueError("research current pointer target mismatch")
        return payload

    def read_latest(self) -> dict[str, Any] | None:
        relative = "research/latest.json"
        pointer_path = self._path(relative)
        if not pointer_path.is_file():
            if pointer_path.exists():
                raise ValueError("invalid research latest pointer")
            return None
        pointer = self._read(relative)
        self._validate_pointer(pointer)
        payload = self.read_exact(str(pointer["archive_date"]))
        if payload is None or _sha256(payload) != pointer["payload_sha256"]:
            raise ValueError("research latest pointer target mismatch")
        return payload

    def list_dates(self) -> list[str]:
        dates = []
        for relative in self._manifest():
            match = re.fullmatch(
                r"research/archives/(\d{8})\.json",
                relative,
            )
            if match:
                dates.append(match.group(1))
        return sorted(set(dates), reverse=True)


class ResearchSelectionStore(NativeDataStore):
    """Append-only selection ledger under its own research namespace."""

    _MANIFEST_RELATIVE = "research/selection/manifest.json"
    _CURRENT_RELATIVE = "research/selection/current.json"
    _SELECTION_ROOT = "research/selection"
    _RECEIPT_ROOT = "receipts/research/selection"
    _RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    @classmethod
    def _artifact_relative(cls, target_trade_date: str, run_id: str) -> str:
        return f"{cls._SELECTION_ROOT}/{target_trade_date}/{run_id}.json"

    @classmethod
    def _receipt_relative(cls, target_trade_date: str, run_id: str) -> str:
        return f"{cls._RECEIPT_ROOT}/{target_trade_date}/{run_id}.json"

    @classmethod
    def _run_manifest_relative(cls, target_trade_date: str, run_id: str) -> str:
        return f"{cls._SELECTION_ROOT}/{target_trade_date}/{run_id}.manifest.json"

    @classmethod
    def _date_current_relative(cls, target_trade_date: str) -> str:
        return f"{cls._SELECTION_ROOT}/{target_trade_date}/current.json"

    @classmethod
    def _source_scope_invalidation_relative(
        cls,
        target_trade_date: str,
        invalidation_id: str,
    ) -> str:
        return (
            f"{cls._SELECTION_ROOT}/{target_trade_date}/invalidations/"
            f"{invalidation_id}.json"
        )

    @staticmethod
    def _raw_sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _canonical_sha(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def _empty_manifest(cls) -> dict[str, Any]:
        return {
            "schema_version": "v3_5.selection_manifest.v1",
            "namespace": cls._SELECTION_ROOT,
            "entries": {},
        }

    @classmethod
    def _validate_manifest(cls, value: Mapping[str, Any]) -> None:
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "namespace",
            "entries",
        }:
            raise ValueError("invalid selection manifest")
        if value.get("schema_version") != "v3_5.selection_manifest.v1" or value.get("namespace") != cls._SELECTION_ROOT:
            raise ValueError("invalid selection manifest namespace")
        entries = value.get("entries")
        if not isinstance(entries, Mapping):
            raise ValueError("invalid selection manifest entries")
        for relative, digest in entries.items():
            if not isinstance(relative, str) or not (
                relative.startswith(f"{cls._SELECTION_ROOT}/")
                or relative.startswith(f"{cls._RECEIPT_ROOT}/")
            ):
                raise ValueError("selection manifest path escapes namespace")
            if not _SHA256.fullmatch(str(digest or "")):
                raise ValueError("invalid selection manifest SHA")

    def _manifest(self) -> dict[str, Any]:
        path = self._path(self._MANIFEST_RELATIVE)
        if not path.exists():
            return self._empty_manifest()
        value = self._read(self._MANIFEST_RELATIVE)
        self._validate_manifest(value)
        return value

    def _write_manifest(self, value: Mapping[str, Any]) -> None:
        self._validate_manifest(value)
        self._write(self._MANIFEST_RELATIVE, dict(value))

    @contextmanager
    def _lock(self):
        with owned_interprocess_lock(self._path(f"{self._SELECTION_ROOT}/.import.lock"), timeout_seconds=10, timeout_message='selection import lock timeout'):
            yield

    @classmethod
    def _receipt(cls, payload: Mapping[str, Any], artifact_relative: str, artifact_sha: str) -> dict[str, Any]:
        return {
            "schema_version": "v3_5.selection_receipt.v1",
            "contract_id": SELECTION_CONTRACT_ID,
            "target_trade_date": payload["target_trade_date"],
            "source_date": payload["source_date"],
            "run_id": payload["run_id"],
            "origin": payload["origin"],
            "payload_path": artifact_relative,
            "payload_sha256": artifact_sha,
            "status": payload["status"],
            "counts": dict(payload["counts"]),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @classmethod
    def _current_pointer(
        cls,
        payload: Mapping[str, Any],
        *,
        artifact_relative: str,
        artifact_sha: str,
        receipt_relative: str,
        receipt_sha: str,
        manifest_relative: str,
        manifest_sha: str,
    ) -> dict[str, Any]:
        body = {
            "schema_version": "v3_5.selection_current_pointer.v1",
            "namespace": cls._SELECTION_ROOT,
            "target_trade_date": payload["target_trade_date"],
            "run_id": payload["run_id"],
            "generated_at": payload["generated_at"],
            "artifact_path": artifact_relative,
            "artifact_sha256": artifact_sha,
            "receipt_path": receipt_relative,
            "receipt_sha256": receipt_sha,
            "manifest_path": manifest_relative,
            "manifest_sha256": manifest_sha,
        }
        return {**body, "pointer_semantic_hash": cls._canonical_sha(body)}

    @classmethod
    def _validate_current(
        cls,
        value: Mapping[str, Any],
        *,
        target_trade_date: str | None = None,
    ) -> None:
        fields = {
            "schema_version",
            "namespace",
            "target_trade_date",
            "run_id",
            "generated_at",
            "artifact_path",
            "artifact_sha256",
            "receipt_path",
            "receipt_sha256",
            "manifest_path",
            "manifest_sha256",
            "pointer_semantic_hash",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("invalid selection current pointer")
        selected = _date(str(value.get("target_trade_date") or ""))
        if target_trade_date is not None and selected != target_trade_date:
            raise ValueError("selection current target date mismatch")
        run_id = value.get("run_id")
        if not isinstance(run_id, str) or not cls._RUN_ID.fullmatch(run_id):
            raise ValueError("invalid selection current run_id")
        if value.get("schema_version") != "v3_5.selection_current_pointer.v1" or value.get("namespace") != cls._SELECTION_ROOT:
            raise ValueError("invalid selection current namespace")
        if value.get("artifact_path") != cls._artifact_relative(selected, run_id) or value.get("receipt_path") != cls._receipt_relative(selected, run_id):
            raise ValueError("invalid selection current paths")
        if value.get("manifest_path") != cls._run_manifest_relative(selected, run_id):
            raise ValueError("invalid selection current manifest path")
        for field in ("artifact_sha256", "receipt_sha256", "manifest_sha256"):
            if not _SHA256.fullmatch(str(value.get(field) or "")):
                raise ValueError("invalid selection current SHA")
        body = {key: item for key, item in value.items() if key != "pointer_semantic_hash"}
        if value.get("pointer_semantic_hash") != cls._canonical_sha(body):
            raise ValueError("invalid selection current semantic hash")

    @classmethod
    def _global_current_pointer(cls, date_current: Mapping[str, Any]) -> dict[str, Any]:
        body = {
            "schema_version": "v3_5.selection_global_current.v1",
            "namespace": cls._SELECTION_ROOT,
            "target_trade_date": date_current["target_trade_date"],
            "current_path": f"{cls._SELECTION_ROOT}/{date_current['target_trade_date']}/current.json",
            "run_id": date_current["run_id"],
            "artifact_sha256": date_current["artifact_sha256"],
        }
        return {**body, "pointer_semantic_hash": cls._canonical_sha(body)}

    @classmethod
    def _validate_global_current(cls, value: Mapping[str, Any]) -> None:
        fields = {
            "schema_version",
            "namespace",
            "target_trade_date",
            "current_path",
            "run_id",
            "artifact_sha256",
            "pointer_semantic_hash",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("invalid selection global current pointer")
        target = _date(str(value.get("target_trade_date") or ""))
        run_id = value.get("run_id")
        if not isinstance(run_id, str) or not cls._RUN_ID.fullmatch(run_id):
            raise ValueError("invalid selection global current run_id")
        if value.get("schema_version") != "v3_5.selection_global_current.v1" or value.get("namespace") != cls._SELECTION_ROOT:
            raise ValueError("invalid selection global current namespace")
        if value.get("current_path") != f"{cls._SELECTION_ROOT}/{target}/current.json" or not _SHA256.fullmatch(str(value.get("artifact_sha256") or "")):
            raise ValueError("invalid selection global current target")
        body = {key: item for key, item in value.items() if key != "pointer_semantic_hash"}
        if value.get("pointer_semantic_hash") != cls._canonical_sha(body):
            raise ValueError("invalid selection global current semantic hash")

    @staticmethod
    def _pointer_value(document: Any, pointer: str) -> Any:
        if pointer == "":
            return document
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("invalid selection source JSON pointer")
        current = document
        for raw_part in pointer[1:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError) as error:
                    raise ValueError("selection source JSON pointer missing") from error
            elif isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                raise ValueError("selection source JSON pointer missing")
        return current

    @classmethod
    def _verify_source_ref(
        cls,
        ref: Mapping[str, Any],
        *,
        expected_target_trade_date: str | None = None,
    ) -> dict[str, Any]:
        path_value = ref.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise ValueError("selection source path is missing")
        path = Path(path_value)
        if not path.is_file() or path.is_symlink():
            raise ValueError("selection source file is unavailable")
        raw = path.read_bytes()
        raw_sha = hashlib.sha256(raw).hexdigest()
        if raw_sha != str(ref.get("raw_sha256") or "").lower():
            raise ValueError("selection source raw SHA mismatch")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("selection source JSON is invalid") from error
        if ref.get("type") == RESEARCH_SUPPLY_TYPE:
            validate_research_supply_envelope(
                document,
                expected_target_trade_date=expected_target_trade_date,
            )
            pointer = ref.get("json_pointer")
            if not isinstance(pointer, str) or not re.fullmatch(
                r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
            ):
                raise ValueError("research supply source JSON pointer must target event card")
            selected = cls._pointer_value(document, pointer)
            if not isinstance(selected, Mapping):
                raise ValueError("research supply selected card is invalid")
            if ref.get("source_date") != document.get("source_date"):
                raise ValueError("research supply source date mismatch")
            if (
                expected_target_trade_date is not None
                and document.get("target_trade_date") != expected_target_trade_date
            ):
                raise ValueError("research supply target date mismatch")
            if ref.get("frozen_payload_sha256") != document.get("frozen_payload_sha256"):
                raise ValueError("research supply frozen SHA mismatch")
            source_time = ref.get("source_time")
            if source_time != document.get("generated_at"):
                raise ValueError("research supply source_time does not match envelope")
            receipt_path_value = ref.get("supply_receipt_path")
            if not isinstance(receipt_path_value, str) or not receipt_path_value:
                raise ValueError("research supply receipt path is missing")
            receipt_path = Path(receipt_path_value)
            if not receipt_path.is_file() or receipt_path.is_symlink():
                raise ValueError("research supply receipt is unavailable")
            receipt_raw = receipt_path.read_bytes()
            receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
            if receipt_sha != str(ref.get("supply_receipt_sha256") or "").lower():
                raise ValueError("research supply receipt SHA mismatch")
            try:
                receipt = json.loads(receipt_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("research supply receipt is invalid JSON") from error
            validate_research_supply_receipt(
                receipt,
                envelope=document,
                artifact_path=str(path),
                artifact_sha256=raw_sha,
            )
            return {
                "card": selected,
                "document": document,
                "supply_receipt": receipt,
                "kind": RESEARCH_SUPPLY_TYPE,
            }
        pointer = str(ref.get("json_pointer") or "")
        if not re.fullmatch(
            r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
        ):
            raise ValueError("selection source JSON pointer must target frozen event card")
        selected = cls._pointer_value(document, pointer)
        frozen_payload = cls._pointer_value(document, "/frozen_payload")
        if not isinstance(selected, Mapping) or not selected.get("event_id") or not isinstance(selected.get("entities"), list):
            raise ValueError("selection source selected card is invalid")
        frozen = hashlib.sha256(
            json.dumps(
                frozen_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if frozen != str(ref.get("frozen_payload_sha256") or "").lower():
            raise ValueError("selection source frozen SHA mismatch")
        source_date = str(ref.get("source_date") or "")
        document_source_date = document.get("source_date")
        if document_source_date is None and isinstance(frozen_payload, Mapping):
            document_source_date = frozen_payload.get("source_date")
        if document_source_date is None or str(document_source_date) != source_date:
            raise ValueError("selection source date mismatch")
        document_target_date = document.get("target_trade_date")
        if document_target_date is None and isinstance(frozen_payload, Mapping):
            document_target_date = frozen_payload.get("target_trade_date")
        if document_target_date is None:
            raise ValueError("selection source target date is missing")
        if (
            expected_target_trade_date is not None
            and str(document_target_date) != expected_target_trade_date
        ):
            raise ValueError("selection source target date mismatch")
        document_generated_at = document.get("generated_at")
        if document_generated_at is None:
            raise ValueError("selection source generated_at is missing")
        try:
            expected_time = datetime.fromisoformat(
                str(ref.get("source_time") or "").replace("Z", "+00:00")
            )
            actual_time = datetime.fromisoformat(
                str(document_generated_at).replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError("selection source generated_at is invalid") from error
        if (
            expected_time.tzinfo is None
            or expected_time.utcoffset() is None
            or actual_time.tzinfo is None
            or actual_time.utcoffset() is None
            or expected_time.astimezone(_SHANGHAI)
            != actual_time.astimezone(_SHANGHAI)
        ):
            raise ValueError("selection source_time does not match source envelope")
        return {"card": selected, "document": document}

    @staticmethod
    def _selection_identity_text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _source_ref_identity(cls, ref: Mapping[str, Any]) -> tuple[str, ...]:
        """Return immutable locator fields used by formal proof bindings."""

        return tuple(
            cls._selection_identity_text(ref.get(field))
            for field in (
                "path",
                "raw_sha256",
                "frozen_payload_sha256",
                "json_pointer",
                "source_date",
                "source_time",
            )
        )

    @classmethod
    def _verify_candidate_source_projection(
        cls,
        candidate: Mapping[str, Any],
        ref: Mapping[str, Any],
        verified: Mapping[str, Any],
        *,
        source_date: str,
        target_trade_date: str,
        cutoff_at: str | None = None,
    ) -> None:
        card = verified.get("card")
        if not isinstance(card, Mapping):
            raise ValueError("selection candidate source card is missing")
        document = verified.get("document")
        if not isinstance(document, Mapping):
            raise ValueError("selection candidate source envelope is missing")
        if ref.get("source_date") != source_date:
            raise ValueError("selection candidate source date binding mismatch")
        if ref.get("type") == RESEARCH_SUPPLY_TYPE:
            if document.get("target_trade_date") != target_trade_date:
                raise ValueError("selection candidate target date mismatch")
            frozen_payload = document.get("frozen_payload")
            if not isinstance(frozen_payload, Mapping):
                raise ValueError("research supply frozen payload is missing")
            ticker = cls._selection_identity_text(card.get("ticker"))
            if not re.fullmatch(r"\d{5}\.HK", ticker):
                raise ValueError("research supply card ticker is invalid")
            event_id = cls._selection_identity_text(card.get("event_id"))
            if event_id != candidate.get("event_id"):
                raise ValueError("selection candidate source identity mismatch")
            candidate_entity = cls._selection_identity_text(candidate.get("entity_id"))
            if candidate_entity != ticker:
                raise ValueError("selection candidate source entity mismatch")
            code, market = ticker.rsplit(".", 1)
            expected_candidate_id = f"{market}.{code}|{ticker}"
            if candidate.get("candidate_id") != expected_candidate_id:
                raise ValueError("selection candidate identity mismatch")
            if candidate.get("market") != market or candidate.get("normalized_code") != code:
                raise ValueError("selection candidate normalized identity mismatch")
            if candidate.get("event_stock_link_id") != f"{event_id}|{expected_candidate_id}":
                raise ValueError("selection candidate event link mismatch")

            def supply_text(value: Any) -> str:
                if value is None:
                    return ""
                if isinstance(value, str):
                    return value.strip()
                if isinstance(value, (Mapping, list)):
                    return json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                return str(value).strip()

            for field in (
                "bucket",
                "catalyst",
                "counterevidence",
                "invalidation",
                "evidence_level",
                "financial_bridge",
                "consensus",
                "overnight_pending",
            ):
                if candidate.get(field) != supply_text(card.get(field)):
                    raise ValueError(f"selection candidate source {field} mismatch")
            if candidate.get("source_metadata") != {"supply_card": dict(card)}:
                raise ValueError("selection candidate source metadata mismatch")
            route_status = frozen_payload.get("route_status")
            if not isinstance(route_status, Mapping) or candidate.get("route_status") != {
                "R1": route_status.get("R1"),
                "R6": route_status.get("R6"),
            }:
                raise ValueError("selection candidate route status mismatch")
            official = card.get("official_source")
            if not isinstance(official, Mapping):
                raise ValueError("research supply official source is missing")
            expected_status = cls._selection_identity_text(official.get("identity_status"))
            if not expected_status or expected_status.upper() in {
                "UNKNOWN",
                "UNVERIFIED",
                "CANNOT_CONFIRM",
                "NOT_MATERIALIZED",
            }:
                expected_status = "UNVERIFIED"
            if candidate.get("source_status") != expected_status:
                raise ValueError("selection candidate source status mismatch")
            eligibility = card.get("eligibility_status")
            if isinstance(eligibility, Mapping):
                expected_eligibility = cls._selection_identity_text(eligibility.get("status"))
            elif isinstance(eligibility, str) and eligibility.strip():
                expected_eligibility = eligibility.strip()
            else:
                expected_eligibility = ""
            if expected_eligibility not in {"ELIGIBILITY_CANNOT_CONFIRM", "ELIGIBLE"}:
                expected_eligibility = "ELIGIBILITY_CANNOT_CONFIRM"
            if candidate.get("eligibility") != expected_eligibility:
                raise ValueError("selection candidate source eligibility mismatch")
            published_value = card.get("published_at")
            if published_value is None:
                published_value = official.get("published_at")
            expected_published_at = supply_text(published_value)
            if candidate.get("published_at") != expected_published_at:
                raise ValueError("selection candidate published_at mismatch")
            expected_aware = _selection_aware_hkt(expected_published_at)
            if candidate.get("published_at_aware") != expected_aware:
                raise ValueError("selection candidate published_at projection mismatch")
            if candidate.get("source_time") != ref.get("source_time"):
                raise ValueError("selection candidate source_time mismatch")
            if cutoff_at is None:
                cutoff_at = str(document.get("cutoff_at") or "")
            try:
                cutoff = datetime.fromisoformat(str(cutoff_at).replace("Z", "+00:00"))
                published = (
                    datetime.fromisoformat(expected_aware.replace("Z", "+00:00"))
                    if expected_aware
                    else None
                )
            except ValueError as error:
                raise ValueError("selection candidate cutoff or published timestamp is invalid") from error
            expected_pit = (
                "CANNOT_CONFIRM"
                if cutoff.tzinfo is None or cutoff.utcoffset() is None or published is None
                else "READY"
                if published.astimezone(_SHANGHAI) <= cutoff.astimezone(_SHANGHAI)
                else "PIT_FAILED"
            )
            if candidate.get("pit_status") != expected_pit:
                raise ValueError("selection candidate PIT status mismatch")
            if candidate.get("acceptance") != "RESEARCH_SUPPLY_ONLY":
                raise ValueError("selection candidate supply acceptance mismatch")
            return
        raw_target_date = document.get("target_trade_date")
        frozen_payload = document.get("frozen_payload")
        if raw_target_date is None and isinstance(frozen_payload, Mapping):
            raw_target_date = frozen_payload.get("target_trade_date")
        if str(raw_target_date) != target_trade_date:
            raise ValueError("selection candidate target date mismatch")
        event_id = cls._selection_identity_text(card.get("event_id"))
        if event_id != candidate.get("event_id"):
            raise ValueError("selection candidate source identity mismatch")
        entities = card.get("entities")
        if not isinstance(entities, list) or len(entities) != 1:
            raise ValueError("selection candidate source entities are ambiguous")
        source_entity = cls._selection_identity_text(entities[0])
        candidate_entity = cls._selection_identity_text(candidate.get("entity_id"))
        if source_entity != candidate_entity:
            raise ValueError("selection candidate source entity mismatch")
        if "." not in candidate_entity:
            raise ValueError("selection candidate entity identity is invalid")
        source_code, source_market = candidate_entity.rsplit(".", 1)
        if (
            source_code.strip().upper() != cls._selection_identity_text(candidate.get("normalized_code")).upper()
            or source_market.strip().upper() != cls._selection_identity_text(candidate.get("market")).upper()
        ):
            raise ValueError("selection candidate normalized identity mismatch")
        expected_candidate_id = (
            f"{cls._selection_identity_text(candidate.get('market')).upper()}."
            f"{cls._selection_identity_text(candidate.get('normalized_code')).upper()}|"
            f"{candidate_entity}"
        )
        if candidate.get("candidate_id") != expected_candidate_id:
            raise ValueError("selection candidate identity mismatch")
        if candidate.get("event_stock_link_id") != f"{event_id}|{expected_candidate_id}":
            raise ValueError("selection candidate event link mismatch")

        source = card.get("source") if isinstance(card.get("source"), Mapping) else {}
        for field in (
            "bucket",
            "catalyst",
            "counterevidence",
            "invalidation",
            "evidence_level",
            "financial_bridge",
            "consensus",
            "overnight_pending",
        ):
            expected = cls._selection_identity_text(card.get(field))
            if candidate.get(field) != expected:
                raise ValueError(f"selection candidate source {field} mismatch")
        expected_metadata = dict(source)
        if candidate.get("source_metadata") != expected_metadata:
            raise ValueError("selection candidate source metadata mismatch")
        expected_status = cls._selection_identity_text(source.get("status")) or "UNVERIFIED"
        if candidate.get("source_status") != expected_status:
            raise ValueError("selection candidate source status mismatch")
        raw_eligibility = card.get("eligibility")
        if isinstance(raw_eligibility, Mapping):
            expected_eligibility = (
                cls._selection_identity_text(raw_eligibility.get("status"))
                or "ELIGIBILITY_CANNOT_CONFIRM"
            )
        elif isinstance(raw_eligibility, str) and raw_eligibility.strip():
            expected_eligibility = raw_eligibility.strip()
        else:
            expected_eligibility = "ELIGIBILITY_CANNOT_CONFIRM"
        if candidate.get("eligibility") != expected_eligibility:
            raise ValueError("selection candidate source eligibility mismatch")
        expected_published_at = cls._selection_identity_text(source.get("published_at"))
        if candidate.get("published_at") != expected_published_at:
            raise ValueError("selection candidate published_at mismatch")
        if candidate.get("published_at_aware") != _selection_aware_hkt(expected_published_at):
            raise ValueError("selection candidate published_at projection mismatch")
        if candidate.get("source_time") != ref.get("source_time"):
            raise ValueError("selection candidate source_time mismatch")
        try:
            source_time = datetime.fromisoformat(
                str(ref.get("source_time") or "").replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError("selection candidate source_time is invalid") from error
        if source_time.tzinfo is None or source_time.utcoffset() is None:
            raise ValueError("selection candidate source_time must include timezone")
        for field in ("official_url", "published_at", "source_status"):
            if field in ref:
                expected = {
                    "official_url": source.get("official_url", ""),
                    "published_at": source.get("published_at", ""),
                    "source_status": source.get("status", ""),
                }[field]
                if ref.get(field) != expected:
                    raise ValueError(f"selection source {field} mismatch")

    @staticmethod
    def _manager_overlay_time(value: Any, field: str) -> datetime:
        if not isinstance(value, str) or not value:
            raise ValueError(f"invalid manager overlay {field}")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"invalid manager overlay {field}") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"invalid manager overlay {field} timezone")
        return parsed.astimezone(_SHANGHAI)

    @staticmethod
    def _manager_overlay_error(code: str, detail: str) -> ValueError:
        return ValueError(f"{code}: {detail}")

    @classmethod
    def _read_manager_overlay_json_ref(
        cls,
        ref: Any,
        *,
        label: str,
    ) -> tuple[dict[str, Any], str]:
        if not isinstance(ref, Mapping) or set(ref) != {"path", "raw_sha256"}:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} reference fields are invalid",
            )
        path_value = ref.get("path")
        raw_sha = ref.get("raw_sha256")
        if (
            not isinstance(path_value, str)
            or not path_value
            or not isinstance(raw_sha, str)
            or not _SHA256.fullmatch(raw_sha.lower())
        ):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} reference is invalid",
            )
        path = Path(path_value)
        if not path.is_file() or path.is_symlink():
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} file is unavailable",
            )
        raw = path.read_bytes()
        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha != raw_sha.lower():
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} raw SHA mismatch",
            )
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} JSON is invalid",
            ) from error
        if not isinstance(document, Mapping):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} document is not an object",
            )
        return dict(document), actual_sha

    @classmethod
    def _read_manager_overlay_supply_ref(
        cls,
        ref: Any,
        *,
        source_date: str,
        target_trade_date: str,
        label: str,
    ) -> dict[str, Any]:
        if not isinstance(ref, Mapping) or set(ref) != _MANAGER_OVERLAY_SUPPLY_REF_FIELDS:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} fields are invalid",
            )
        for field in ("path", "run_id", "source_date", "target_trade_date"):
            if not isinstance(ref.get(field), str) or not ref[field]:
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"{label} {field} is invalid",
                )
        for field in ("raw_sha256", "frozen_payload_sha256"):
            if not isinstance(ref.get(field), str) or not _SHA256.fullmatch(ref[field].lower()):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"{label} {field} is invalid",
                )
        path = Path(ref["path"])
        if not path.is_file() or path.is_symlink():
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} file is unavailable",
            )
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref["raw_sha256"].lower():
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} raw SHA mismatch",
            )
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} JSON is invalid",
            ) from error
        if not isinstance(document, Mapping):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} document is not an object",
            )
        try:
            validate_research_supply_envelope(
                document,
                expected_source_date=source_date,
                expected_target_trade_date=target_trade_date,
                expected_run_id=ref["run_id"],
            )
        except ValueError as error:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} envelope is invalid: {error}",
            ) from error
        if (
            document.get("frozen_payload_sha256")
            != ref["frozen_payload_sha256"].lower()
            or document.get("source_date") != ref["source_date"]
            or document.get("target_trade_date") != ref["target_trade_date"]
        ):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} binding mismatch",
            )
        return dict(document)

    @classmethod
    def _read_manager_overlay_decision(
        cls,
        payload: Mapping[str, Any],
        *,
        source_envelope: Mapping[str, Any],
        candidate_ids: list[str],
        label: str,
    ) -> tuple[dict[str, Any], str]:
        ref = payload.get("manager_decision_ref")
        try:
            document, raw_sha = cls._read_manager_overlay_json_ref(ref, label=label)
            validate_manager_research_decision(
                document,
                candidate_ids=candidate_ids,
                supply_envelope=source_envelope,
            )
        except ValueError as error:
            if str(error).startswith("SOURCE_SUCCESSOR_PROOF_INVALID:"):
                raise
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} validation failed: {error}",
            ) from error
        if payload.get("manager_decision_ref", {}).get("raw_sha256") != raw_sha:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} product binding mismatch",
            )
        return document, raw_sha

    @classmethod
    def _product_supply_refs(
        cls,
        payload: Mapping[str, Any],
        *,
        label: str,
    ) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        candidates = payload.get("research_candidates")
        if not isinstance(candidates, list):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"{label} candidates are invalid",
            )
        for candidate in candidates:
            candidate_id = str(candidate.get("candidate_id") or "")
            refs = candidate.get("source_refs")
            if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], Mapping):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"{label} source binding is not one frozen supply ref per card",
                )
            ref = refs[0]
            if ref.get("type") != RESEARCH_SUPPLY_TYPE:
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"{label} source binding type is invalid",
                )
            if candidate_id in result:
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"{label} candidate is duplicated",
                )
            result[candidate_id] = ref
        return result

    @staticmethod
    def _manager_overlay_expected_projections(
        decision: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        expected: dict[str, dict[str, Any]] = {}
        for role, field in (("CORE", "core"), ("CONDITIONAL", "conditional")):
            for order, row in enumerate(decision[field], 1):
                expected[str(row["candidate_id"])] = {
                    "schema_version": decision["schema_version"],
                    "phase": decision["phase"],
                    "decision_state": decision["decision_state"],
                    "source_date": decision["source_date"],
                    "target_trade_date": decision["target_trade_date"],
                    "run_id": decision["run_id"],
                    "generated_at": decision["generated_at"],
                    "cutoff_at": decision["cutoff_at"],
                    "role": role,
                    "order": order,
                    "reason": row["reason"],
                }
        return expected

    @classmethod
    def _validate_manager_overlay_proof_shape(
        cls,
        proof: Mapping[str, Any],
        *,
        source_date: str,
        target_trade_date: str,
    ) -> None:
        if set(proof) != _MANAGER_OVERLAY_PROOF_FIELDS:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "proof fields are not fixed",
            )
        if (
            proof.get("schema_version") != _MANAGER_OVERLAY_PROOF_SCHEMA_VERSION
            or proof.get("type") != _MANAGER_OVERLAY_PROOF_TYPE
            or proof.get("rule_id") != _MANAGER_OVERLAY_RULE_ID
            or proof.get("rule_version") != _MANAGER_OVERLAY_RULE_VERSION
            or proof.get("source_date") != source_date
            or proof.get("target_trade_date") != target_trade_date
        ):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "proof identity or rule binding is invalid",
            )
        candidate_ids = proof.get("candidate_ids")
        if (
            not isinstance(candidate_ids, list)
            or len(candidate_ids) != 124
            or any(not isinstance(item, str) or not item for item in candidate_ids)
            or candidate_ids != sorted(set(candidate_ids))
            or proof.get("candidate_set_sha256")
            != cls._canonical_sha(candidate_ids)
        ):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "proof candidate set is invalid",
            )
        records = proof.get("records")
        if not isinstance(records, list) or len(records) != len(candidate_ids):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "proof records are incomplete",
            )
        if proof.get("envelope_changed_paths") != sorted(
            set(proof.get("envelope_changed_paths") or [])
        ):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "proof envelope paths are not sorted and unique",
            )
        if not set(proof["envelope_changed_paths"]).issubset(
            MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS
        ):
            raise cls._manager_overlay_error(
                "OVERLAY_MUTATION_OUT_OF_SCOPE",
                "proof expands the envelope allowlist",
            )
        safety = proof.get("safety")
        expected_safety = {
            "RESEARCH_ONLY": True,
            "WATCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if set(safety or {}) != _MANAGER_OVERLAY_SAFETY_FIELDS or safety != expected_safety:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "proof safety is invalid",
            )

    @classmethod
    def _verify_manager_overlay_product_diff(
        cls,
        old_payload: Mapping[str, Any],
        new_payload: Mapping[str, Any],
        *,
        proof: Mapping[str, Any],
        old_supply: Mapping[str, Any],
        new_supply: Mapping[str, Any],
        expected_projections: Mapping[str, Mapping[str, Any]],
    ) -> None:
        old_snapshots = old_payload.get("snapshots")
        new_snapshots = new_payload.get("snapshots")
        if not isinstance(old_snapshots, Mapping) or not isinstance(new_snapshots, Mapping):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "product snapshots are invalid",
            )
        for phase in ("0830", "0935", "1620"):
            old_later = old_snapshots.get(phase)
            new_later = new_snapshots.get(phase)
            if not isinstance(old_later, Mapping) or not isinstance(new_later, Mapping):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"later snapshot is invalid: {phase}",
                )
            if old_later != new_later and (
                old_later.get("status") == "READY" or new_later.get("status") == "READY"
            ):
                raise cls._manager_overlay_error(
                    "LATER_PHASE_READY",
                    f"later snapshot is READY: {phase}",
                )

        allowed_top = {"generated_at", "run_id", "manager_decision_ref", "source_refs"}
        for key in set(old_payload) | set(new_payload):
            if key in allowed_top or key in {"research_candidates", "snapshots"}:
                continue
            if old_payload.get(key) != new_payload.get(key):
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"product field changed outside proof: {key}",
                )

        old_candidates = old_payload.get("research_candidates")
        new_candidates = new_payload.get("research_candidates")
        if not isinstance(old_candidates, list) or not isinstance(new_candidates, list):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "product candidate lists are invalid",
            )
        old_ids = [str(row.get("candidate_id") or "") for row in old_candidates]
        new_ids = [str(row.get("candidate_id") or "") for row in new_candidates]
        proof_ids = list(proof["candidate_ids"])
        if old_ids != new_ids or old_ids != proof_ids:
            raise cls._manager_overlay_error(
                "OVERLAY_MUTATION_OUT_OF_SCOPE",
                "product candidate identity/order changed",
            )
        old_by_id = {row["candidate_id"]: row for row in old_candidates}
        new_by_id = {row["candidate_id"]: row for row in new_candidates}
        record_by_id = {record["candidate_id"]: record for record in proof["records"]}
        old_supply_cards = {
            str(card["ticker"]): card
            for card in old_supply["frozen_payload"]["event_cards"]
        }
        new_supply_cards = {
            str(card["ticker"]): card
            for card in new_supply["frozen_payload"]["event_cards"]
        }
        if set(record_by_id) != set(proof_ids):
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "proof record identities do not reconcile",
            )

        for candidate_id in proof_ids:
            before = old_by_id[candidate_id]
            after = new_by_id[candidate_id]
            record = record_by_id[candidate_id]
            for field in (
                "candidate_id",
                "event_stock_link_id",
                "market",
                "normalized_code",
                "entity_id",
                "event_id",
            ):
                if before.get(field) != after.get(field):
                    raise cls._manager_overlay_error(
                        "OVERLAY_MUTATION_OUT_OF_SCOPE",
                        f"candidate identity changed: {candidate_id}.{field}",
                    )
            before_card = before.get("source_metadata", {}).get("supply_card")
            after_card = after.get("source_metadata", {}).get("supply_card")
            if not isinstance(before_card, Mapping) or not isinstance(after_card, Mapping):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"candidate source card missing: {candidate_id}",
                )
            if set(before.get("source_metadata", {})) != {"supply_card"} or set(
                after.get("source_metadata", {})
            ) != {"supply_card"}:
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"candidate source metadata changed: {candidate_id}",
                )
            ticker = str(record["ticker"])
            expected_candidate_id = (
                f"HK.{ticker.split('.', 1)[0]}|{ticker}"
                if "." in ticker
                else ""
            )
            if candidate_id != expected_candidate_id:
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"candidate identity does not reconcile with ticker: {candidate_id}",
                )
            if before_card != old_supply_cards.get(ticker) or after_card != new_supply_cards.get(ticker):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"product source card does not match bound supply: {candidate_id}",
                )
            if (
                cls._canonical_sha(before_card) != record["before_card_sha"]
                or cls._canonical_sha(after_card) != record["after_card_sha"]
            ):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"product source card SHA does not match proof: {candidate_id}",
                )
            if before.get("source_refs") == after.get("source_refs"):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"candidate source successor ref did not change: {candidate_id}",
                )
            for field in MANAGER_OVERLAY_PRODUCT_DERIVED_FIELDS:
                if before.get(field) != after.get(field) and not record["changed_paths"]:
                    raise cls._manager_overlay_error(
                        "OVERLAY_MUTATION_OUT_OF_SCOPE",
                        f"derived candidate field changed without source evidence: {candidate_id}.{field}",
                    )
            for field in set(before) | set(after):
                if field in {"source_refs", "manager_decision", "source_metadata"}:
                    continue
                if field in MANAGER_OVERLAY_PRODUCT_DERIVED_FIELDS:
                    continue
                if before.get(field) != after.get(field):
                    raise cls._manager_overlay_error(
                        "OVERLAY_MUTATION_OUT_OF_SCOPE",
                        f"candidate field changed outside proof: {candidate_id}.{field}",
                    )
            if "manager_decision" in before:
                raise cls._manager_overlay_error(
                    "SECOND_MANAGER_OVERLAY",
                    "old product already carries a manager projection",
                )
            if after.get("manager_decision") != expected_projections.get(candidate_id):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    f"manager projection mismatch: {candidate_id}",
                )

        old_snapshot = old_snapshots["2200"]
        new_snapshot = new_snapshots["2200"]
        if old_snapshot.get("status") != "READY" or new_snapshot.get("status") != "READY":
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "2200 snapshots must both be READY",
            )
        for phase in ("0830", "0935", "1620"):
            if old_snapshots[phase] != new_snapshots[phase]:
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"later snapshot changed: {phase}",
                )
        if old_payload["snapshots"]["2200"] == new_payload["snapshots"]["2200"]:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                "2200 successor snapshot is not different",
            )
        # These are authority and safety fields, not source-review output.
        for field in (
            "formal_shortlist",
            "formal_authority",
            "route_status",
            "gemini_status",
            "RESEARCH_ONLY",
            "production_allowed",
            "buy_gate_updated",
            "orders_sent",
        ):
            if old_payload.get(field) != new_payload.get(field):
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"immutable authority field changed: {field}",
                )

        # The source documents were already read by the product source
        # validator; compare their identity here as an explicit proof check.
        for field in ("source_date", "target_trade_date", "cutoff_at"):
            if old_supply.get(field) != new_supply.get(field):
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    f"supply identity changed: {field}",
                )

    @classmethod
    def _verify_manager_overlay_successor(
        cls,
        old_payload: Mapping[str, Any],
        new_payload: Mapping[str, Any],
        proof_ref: Any,
    ) -> None:
        try:
            proof, _ = cls._read_manager_overlay_json_ref(
                proof_ref,
                label="manager source successor proof",
            )
            source_date = str(old_payload.get("source_date") or "")
            target_trade_date = str(old_payload.get("target_trade_date") or "")
            if (
                new_payload.get("source_date") != source_date
                or new_payload.get("target_trade_date") != target_trade_date
            ):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "successor product source/target mismatch",
                )
            cls._validate_manager_overlay_proof_shape(
                proof,
                source_date=source_date,
                target_trade_date=target_trade_date,
            )
            base_supply = cls._read_manager_overlay_supply_ref(
                proof["base_supply_ref"],
                source_date=source_date,
                target_trade_date=target_trade_date,
                label="base supply",
            )
            successor_supply = cls._read_manager_overlay_supply_ref(
                proof["successor_supply_ref"],
                source_date=source_date,
                target_trade_date=target_trade_date,
                label="successor supply",
            )
            if base_supply["run_id"] == successor_supply["run_id"]:
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "base and successor run_id must differ",
                )
            if old_payload.get("origin") != "MANUAL_RECOVERY" or new_payload.get("origin") != "MANUAL_RECOVERY":
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "product origin must be MANUAL_RECOVERY",
                )
            if (
                base_supply.get("run_id") != old_payload.get("run_id")
                or successor_supply.get("run_id") != new_payload.get("run_id")
            ):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "product/source run binding mismatch",
                )
            old_refs = cls._product_supply_refs(old_payload, label="base product")
            new_refs = cls._product_supply_refs(new_payload, label="successor product")
            if set(old_refs) != set(new_refs) or set(old_refs) != set(proof["candidate_ids"]):
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    "product/source candidate set mismatch",
                )
            for candidate_id, ref in old_refs.items():
                if (
                    ref.get("path") != proof["base_supply_ref"]["path"]
                    or ref.get("raw_sha256") != proof["base_supply_ref"]["raw_sha256"]
                    or ref.get("frozen_payload_sha256")
                    != proof["base_supply_ref"]["frozen_payload_sha256"]
                ):
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        f"base product source ref mismatch: {candidate_id}",
                    )
                successor_ref = new_refs[candidate_id]
                if (
                    successor_ref.get("path") != proof["successor_supply_ref"]["path"]
                    or successor_ref.get("raw_sha256") != proof["successor_supply_ref"]["raw_sha256"]
                    or successor_ref.get("frozen_payload_sha256")
                    != proof["successor_supply_ref"]["frozen_payload_sha256"]
                ):
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        f"successor product source ref mismatch: {candidate_id}",
                    )

            base_cards = {
                str(card["ticker"]): card
                for card in base_supply["frozen_payload"]["event_cards"]
            }
            successor_cards = {
                str(card["ticker"]): card
                for card in successor_supply["frozen_payload"]["event_cards"]
            }
            candidate_ids = list(proof["candidate_ids"])

            def candidate_id_for_ticker(ticker: str) -> str:
                code, market = ticker.rsplit(".", 1)
                return f"{market}.{code}|{ticker}"

            expected_base_ids = sorted(candidate_id_for_ticker(ticker) for ticker in base_cards)
            expected_successor_ids = sorted(
                candidate_id_for_ticker(ticker) for ticker in successor_cards
            )
            if candidate_ids != expected_base_ids or candidate_ids != expected_successor_ids:
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "proof candidate set does not cover every source event card",
                )
            if set(base_cards) != set(successor_cards):
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    "supply ticker set changed",
                )
            record_by_id: dict[str, Mapping[str, Any]] = {}
            for record, candidate_id in zip(proof["records"], candidate_ids):
                if not isinstance(record, Mapping) or set(record) != _MANAGER_OVERLAY_RECORD_FIELDS:
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        "proof record fields are invalid",
                    )
                if record.get("candidate_id") != candidate_id or candidate_id in record_by_id:
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        "proof record order or identity is invalid",
                    )
                ticker = record.get("ticker")
                expected_ticker = candidate_id.split("|", 1)[1] if "|" in candidate_id else ""
                if ticker != expected_ticker or ticker not in base_cards:
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        f"proof ticker binding is invalid: {candidate_id}",
                    )
                before_card = base_cards[ticker]
                after_card = successor_cards[ticker]
                if record.get("before_card_sha") != cls._canonical_sha(before_card):
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        f"proof before card SHA mismatch: {candidate_id}",
                    )
                if record.get("after_card_sha") != cls._canonical_sha(after_card):
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        f"proof after card SHA mismatch: {candidate_id}",
                    )
                changed_paths = record.get("changed_paths")
                if not isinstance(changed_paths, list) or changed_paths != sorted(set(changed_paths)):
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        f"proof card paths are not sorted and unique: {candidate_id}",
                    )
                if not set(changed_paths).issubset(MANAGER_OVERLAY_CARD_CHANGED_PATHS):
                    raise cls._manager_overlay_error(
                        "OVERLAY_MUTATION_OUT_OF_SCOPE",
                        f"proof expands card allowlist: {candidate_id}",
                    )
                actual_paths = _manager_overlay_changed_paths(before_card, after_card)
                if actual_paths != changed_paths:
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        f"proof card paths do not match source: {candidate_id}",
                    )
                for identity_field in ("ticker", "candidate_id", "event_id", "entity", "market"):
                    if before_card.get(identity_field) != after_card.get(identity_field):
                        raise cls._manager_overlay_error(
                            "OVERLAY_MUTATION_OUT_OF_SCOPE",
                            f"source card identity changed: {candidate_id}.{identity_field}",
                        )
                record_by_id[candidate_id] = record
            if len(record_by_id) != len(candidate_ids):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "proof records are not complete",
                )
            actual_envelope_paths = _manager_overlay_envelope_paths(base_supply, successor_supply)
            if actual_envelope_paths != proof["envelope_changed_paths"]:
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "proof envelope paths do not match source",
                )
            if not set(actual_envelope_paths).issubset(MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS):
                raise cls._manager_overlay_error(
                    "OVERLAY_MUTATION_OUT_OF_SCOPE",
                    "source envelope changed outside proof allowlist",
                )

            old_ids = [str(row["candidate_id"]) for row in old_payload["research_candidates"]]
            new_ids = [str(row["candidate_id"]) for row in new_payload["research_candidates"]]
            old_decision, old_decision_sha = cls._read_manager_overlay_decision(
                old_payload,
                source_envelope=base_supply,
                candidate_ids=old_ids,
                label="base manager decision",
            )
            new_decision, new_decision_sha = cls._read_manager_overlay_decision(
                new_payload,
                source_envelope=successor_supply,
                candidate_ids=new_ids,
                label="successor manager decision",
            )
            if old_decision.get("baseline_ref") is not None:
                raise cls._manager_overlay_error(
                    "SECOND_MANAGER_OVERLAY",
                    "base manager decision already has a baseline",
                )
            old_decision_ref = old_payload.get("manager_decision_ref")
            new_decision_ref = new_payload.get("manager_decision_ref")
            if not isinstance(old_decision_ref, Mapping) or not isinstance(new_decision_ref, Mapping):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "manager decision reference is missing",
                )
            if new_decision.get("baseline_ref") != dict(old_decision_ref):
                raise cls._manager_overlay_error(
                    "STALE_BASELINE",
                    "successor baseline does not name the current base decision",
                )
            if old_decision_sha != str(old_decision_ref.get("raw_sha256") or "").lower():
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "base decision SHA binding mismatch",
                )
            if new_decision_sha != str(new_decision_ref.get("raw_sha256") or "").lower():
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "successor decision SHA binding mismatch",
                )
            if old_decision.get("source_date") != new_decision.get("source_date") or old_decision.get(
                "target_trade_date"
            ) != new_decision.get("target_trade_date"):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "manager decision source/target mismatch",
                )
            for decision, supply_ref, label in (
                (old_decision, proof["base_supply_ref"], "base"),
                (new_decision, proof["successor_supply_ref"], "successor"),
            ):
                decision_supply_ref = decision.get("supply_ref")
                if not isinstance(decision_supply_ref, Mapping) or any(
                    decision_supply_ref.get(field) != supply_ref[field]
                    for field in (
                        "path",
                        "raw_sha256",
                        "frozen_payload_sha256",
                        "run_id",
                    )
                ):
                    raise cls._manager_overlay_error(
                        "SOURCE_SUCCESSOR_PROOF_INVALID",
                        f"{label} manager decision supply binding mismatch",
                    )
            old_decision_time = cls._manager_overlay_time(
                old_decision.get("generated_at"), "base decision generated_at"
            )
            new_decision_time = cls._manager_overlay_time(
                new_decision.get("generated_at"), "successor decision generated_at"
            )
            old_product_time = cls._manager_overlay_time(
                old_payload.get("generated_at"), "base product generated_at"
            )
            new_product_time = cls._manager_overlay_time(
                new_payload.get("generated_at"), "successor product generated_at"
            )
            target_start = datetime.strptime(target_trade_date, "%Y%m%d").replace(tzinfo=_SHANGHAI)
            if not (
                old_decision_time <= old_product_time
                and old_product_time < new_decision_time
                and new_decision_time <= new_product_time
                and new_product_time < target_start
            ):
                raise cls._manager_overlay_error(
                    "GENERATED_AT_NOT_INCREASING",
                    "decision/product generated_at chain is not ordered between base and target day",
                )
            if new_decision.get("run_id") != new_payload.get("run_id"):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "successor decision run binding mismatch",
                )
            if new_decision.get("supply_ref", {}).get("path") != proof["successor_supply_ref"]["path"]:
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "successor decision supply path mismatch",
                )
            if new_decision.get("supply_ref", {}).get("raw_sha256") != proof["successor_supply_ref"]["raw_sha256"]:
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "successor decision supply SHA mismatch",
                )
            expected_projections = cls._manager_overlay_expected_projections(new_decision)
            projected_ids = {
                str(candidate["candidate_id"])
                for candidate in new_payload["research_candidates"]
                if "manager_decision" in candidate
            }
            if projected_ids != set(expected_projections):
                raise cls._manager_overlay_error(
                    "SOURCE_SUCCESSOR_PROOF_INVALID",
                    "successor manager projection set is incomplete",
                )
            cls._verify_manager_overlay_product_diff(
                old_payload,
                new_payload,
                proof=proof,
                old_supply=base_supply,
                new_supply=successor_supply,
                expected_projections=expected_projections,
            )
        except ValueError:
            raise
        except (KeyError, TypeError, AttributeError) as error:
            raise cls._manager_overlay_error(
                "SOURCE_SUCCESSOR_PROOF_INVALID",
                f"proof verification failed: {error}",
            ) from error

    @classmethod
    def _verify_product_sources(
        cls,
        payload: Mapping[str, Any],
        *,
        _seen_paths: set[str] | None = None,
    ) -> None:
        refs = payload.get("source_refs")
        if not isinstance(refs, list) or not refs:
            if payload.get("status") == "NOT_MATERIALIZED":
                return
            raise ValueError("selection source refs are required")
        supply_documents: list[Mapping[str, Any]] = []
        supply_refs: list[Mapping[str, Any]] = []
        for candidate in payload.get("research_candidates", []):
            candidate_refs = candidate.get("source_refs")
            if not isinstance(candidate_refs, list) or not candidate_refs:
                raise ValueError("selection candidate source refs are missing")
            for ref in candidate_refs:
                verified = cls._verify_source_ref(
                    ref,
                    expected_target_trade_date=str(payload["target_trade_date"]),
                )
                if ref.get("type") == RESEARCH_SUPPLY_TYPE:
                    document = verified.get("document")
                    if isinstance(document, Mapping):
                        supply_documents.append(document)
                        supply_refs.append(ref)
                cls._verify_candidate_source_projection(
                    candidate,
                    ref,
                    verified,
                    source_date=str(payload["source_date"]),
                    target_trade_date=str(payload["target_trade_date"]),
                    cutoff_at=str(payload.get("cutoff_at") or ""),
                )
        candidate_source_types = {
            ref.get("type")
            for candidate in payload.get("research_candidates", [])
            for ref in candidate.get("source_refs", [])
            if isinstance(ref, Mapping)
        }
        if candidate_source_types == {RESEARCH_SUPPLY_TYPE}:
            decision_ref = payload.get("manager_decision_ref")
            snapshot_2200 = payload.get("snapshots", {}).get("2200", {})
            if not supply_documents or not supply_refs:
                raise ValueError("research supply source envelope is missing")
            supply_document = supply_documents[0]
            supply_run_id = str(supply_document.get("run_id") or "")
            if any(
                document.get("run_id") != supply_run_id
                or document.get("source_date") != supply_document.get("source_date")
                or document.get("target_trade_date") != supply_document.get("target_trade_date")
                or document.get("frozen_payload_sha256")
                != supply_document.get("frozen_payload_sha256")
                for document in supply_documents
            ):
                raise ValueError("research supply source envelopes are mixed")
            if snapshot_2200.get("status") == "READY" and snapshot_2200.get("run_id") != supply_run_id:
                raise ValueError("research supply 2200 run binding mismatch")
            ready_later = [
                phase
                for phase in ("0830", "0935", "1620")
                if isinstance(payload.get("snapshots", {}).get(phase), Mapping)
                and payload["snapshots"][phase].get("status") == "READY"
            ]
            expected_product_run = (
                str(payload["snapshots"][ready_later[-1]].get("run_id") or "")
                if ready_later
                else supply_run_id
            )
            if payload.get("run_id") != expected_product_run:
                raise ValueError("research supply product run binding mismatch")
            if snapshot_2200.get("status") == "READY":
                if not isinstance(decision_ref, Mapping):
                    raise ValueError("research supply 2200 manager decision reference is missing")
                decision_path_value = decision_ref.get("path")
                if not isinstance(decision_path_value, str) or not decision_path_value:
                    raise ValueError("manager decision reference is missing")
                decision_path = Path(decision_path_value)
                if not decision_path.is_file() or decision_path.is_symlink():
                    raise ValueError("manager decision reference SHA mismatch")
                decision_raw = decision_path.read_bytes()
                if hashlib.sha256(decision_raw).hexdigest() != str(
                    decision_ref.get("raw_sha256") or ""
                ).lower():
                    raise ValueError("manager decision reference SHA mismatch")
                try:
                    decision_document = json.loads(decision_raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError("manager decision document is invalid JSON") from error
                if not isinstance(decision_document, Mapping):
                    raise ValueError("manager decision document is not an object")
                validate_manager_research_decision(
                    decision_document,
                    candidate_ids=[
                        str(candidate["candidate_id"])
                        for candidate in payload.get("research_candidates", [])
                    ],
                    supply_envelope=supply_document,
                )
                projected = {
                    str(candidate["candidate_id"]): candidate["manager_decision"]
                    for candidate in payload.get("research_candidates", [])
                    if "manager_decision" in candidate
                }
                if projected:
                    expected_projection: dict[str, dict[str, Any]] = {}
                    for role, field in (("CORE", "core"), ("CONDITIONAL", "conditional")):
                        for order, row in enumerate(decision_document[field], 1):
                            expected_projection[str(row["candidate_id"])] = {
                                "schema_version": decision_document["schema_version"],
                                "phase": decision_document["phase"],
                                "decision_state": decision_document["decision_state"],
                                "source_date": decision_document["source_date"],
                                "target_trade_date": decision_document["target_trade_date"],
                                "run_id": decision_document["run_id"],
                                "generated_at": decision_document["generated_at"],
                                "cutoff_at": decision_document["cutoff_at"],
                                "role": role,
                                "order": order,
                                "reason": row["reason"],
                            }
                    if set(projected) != set(expected_projection):
                        raise ValueError(
                            "manager decision projection candidate set mismatch"
                        )
                    for candidate_id, projection in projected.items():
                        validate_manager_decision_projection(
                            projection,
                            source_date=str(payload["source_date"]),
                            target_trade_date=str(payload["target_trade_date"]),
                            cutoff_at=str(payload["cutoff_at"]),
                            expected_run_id=str(decision_document["run_id"]),
                            expected_generated_at=str(decision_document["generated_at"]),
                        )
                        if dict(projection) != expected_projection[candidate_id]:
                            raise ValueError(
                                "manager decision projection does not match decision document"
                            )
                cls._verify_manager_qualification_refs(
                    decision_document,
                    source_date=str(payload["source_date"]),
                    target_trade_date=str(payload["target_trade_date"]),
                    candidate_ids=[
                        str(candidate["candidate_id"])
                        for candidate in payload.get("research_candidates", [])
                    ],
                )
                source_ref = supply_refs[0]
                source_ref_path = str(source_ref.get("path") or "")
                if decision_document.get("supply_ref", {}).get("path") != source_ref_path:
                    raise ValueError("manager decision supply path binding mismatch")
                if decision_document.get("supply_ref", {}).get("raw_sha256") != source_ref.get("raw_sha256"):
                    raise ValueError("manager decision supply raw SHA binding mismatch")
                decision_time = str(decision_document.get("generated_at") or "")
                baseline_ids: set[str] | None = None
                if decision_document.get("baseline_ref") is not None:
                    baseline_ids = cls._verify_manager_baseline(
                        decision_document["baseline_ref"],
                        source_date=str(payload["source_date"]),
                        target_trade_date=str(payload["target_trade_date"]),
                        decision_generated_at=decision_time,
                        _seen_paths=_seen_paths,
                    )
                    keep_ids = {row["candidate_id"] for row in decision_document["KEEP"]}
                    add_ids = {row["candidate_id"] for row in decision_document["ADD"]}
                    remove_ids = {row["candidate_id"] for row in decision_document["REMOVE"]}
                    if not keep_ids.issubset(baseline_ids) or remove_ids - baseline_ids:
                        raise ValueError("manager decision baseline KEEP/REMOVE binding mismatch")
                    if add_ids & baseline_ids:
                        raise ValueError("manager decision baseline ADD binding mismatch")
                    expected_decision_ids = sorted((baseline_ids - remove_ids) | add_ids)
                else:
                    expected_decision_ids = sorted(
                        row["candidate_id"]
                        for row in [
                            *decision_document["core"],
                            *decision_document["conditional"],
                        ]
                    )
                decision_core_ids = {
                    row["candidate_id"]
                    for row in [
                        *decision_document["core"],
                        *decision_document["conditional"],
                    ]
                }
                if decision_core_ids != set(expected_decision_ids):
                    raise ValueError("manager decision baseline action set mismatch")
                expected_decision_ids = sorted(expected_decision_ids)
                if snapshot_2200.get("candidate_ids") != expected_decision_ids:
                    raise ValueError("manager decision 2200 candidate binding mismatch")
                if snapshot_2200.get("run_id") != decision_document.get("run_id"):
                    raise ValueError("manager decision 2200 run binding mismatch")
                if snapshot_2200.get("event_at") != decision_document.get("generated_at"):
                    raise ValueError("manager decision 2200 event binding mismatch")
                if snapshot_2200.get("artifact_sha256") != decision_ref.get("raw_sha256"):
                    raise ValueError("manager decision 2200 artifact binding mismatch")
            elif decision_ref is not None:
                raise ValueError("research supply manager decision lacks a READY 2200 snapshot")
        formal = payload.get("formal_authority")
        if (
            isinstance(formal, Mapping)
            and formal.get("status") == "READY"
            and payload.get("formal_shortlist")
        ):
            candidate_ids = list(payload.get("formal_shortlist") or [])
            candidates_by_id = {
                str(candidate.get("candidate_id")): candidate
                for candidate in payload.get("research_candidates", [])
            }
            source_sha256 = str(formal.get("source_sha256") or "")
            for ref in formal.get("evidence_refs", []):
                document = cls._verify_auxiliary_ref(
                    ref,
                    "formal evidence",
                    schema_version="v3_5.selection_formal_evidence.v1",
                    expected_type="EXACT_DATE_PIT",
                    source_date=str(payload["source_date"]),
                    target_trade_date=str(payload["target_trade_date"]),
                    candidate_ids=candidate_ids,
                    source_sha256=source_sha256,
                    expected_run_id=str(ref.get("run_id") or ""),
                )
                if (
                    not isinstance(document, Mapping)
                    or document.get("status") != "READY"
                    or document.get("pit_status") != "READY"
                ):
                    raise ValueError("formal evidence document is not READY")
                cls._verify_formal_candidate_bindings(
                    document,
                    candidates_by_id=candidates_by_id,
                    candidate_ids=candidate_ids,
                    label="formal evidence",
                )
            decision_ref = formal.get("manager_decision_ref")
            decision_document = cls._verify_auxiliary_ref(
                decision_ref,
                "manager decision",
                schema_version="v3_5.selection_manager_decision.v1",
                expected_type="MANAGER_DECISION",
                source_date=str(payload["source_date"]),
                target_trade_date=str(payload["target_trade_date"]),
                candidate_ids=candidate_ids,
                source_sha256=source_sha256,
                expected_run_id=str(decision_ref.get("run_id") or "")
                if isinstance(decision_ref, Mapping)
                else None,
            )
            if not isinstance(decision_document, Mapping) or decision_document.get("decision") is not True:
                raise ValueError("manager decision document is not approved")
            cls._verify_formal_candidate_bindings(
                decision_document,
                candidates_by_id=candidates_by_id,
                candidate_ids=candidate_ids,
                label="manager decision",
            )

    @classmethod
    def _verify_formal_candidate_bindings(
        cls,
        document: Mapping[str, Any],
        *,
        candidates_by_id: Mapping[str, Mapping[str, Any]],
        candidate_ids: list[str],
        label: str,
    ) -> None:
        """Bind formal proof rows to the exact frozen source locators."""

        bindings = document.get("candidate_bindings")
        if not isinstance(bindings, list) or len(bindings) != len(candidate_ids):
            raise ValueError(f"{label} candidate source binding is incomplete")
        seen: list[str] = []
        for binding in bindings:
            if not isinstance(binding, Mapping) or not {
                "candidate_id",
                "eligibility",
                "pit_status",
                "source_refs",
            }.issubset(binding):
                raise ValueError(f"{label} candidate source binding is invalid")
            candidate_id = binding.get("candidate_id")
            if candidate_id not in candidates_by_id or candidate_id in seen:
                raise ValueError(f"{label} candidate source binding identity is invalid")
            seen.append(candidate_id)
            candidate = candidates_by_id[candidate_id]
            if (
                binding.get("eligibility") != candidate.get("eligibility")
                or binding.get("pit_status") != candidate.get("pit_status")
            ):
                raise ValueError(f"{label} candidate source proof status mismatch")
            source_refs = binding.get("source_refs")
            candidate_refs = candidate.get("source_refs")
            if (
                not isinstance(source_refs, list)
                or not isinstance(candidate_refs, list)
                or any(not isinstance(ref, Mapping) for ref in source_refs)
                or any(not isinstance(ref, Mapping) for ref in candidate_refs)
            ):
                raise ValueError(f"{label} candidate source binding refs are invalid")
            if [cls._source_ref_identity(ref) for ref in source_refs] != [
                cls._source_ref_identity(ref) for ref in candidate_refs
            ]:
                raise ValueError(f"{label} candidate source binding refs mismatch")
        if seen != candidate_ids:
            raise ValueError(f"{label} candidate source binding order mismatch")

    @classmethod
    def _verify_manager_baseline(
        cls,
        baseline_ref: Any,
        *,
        source_date: str,
        target_trade_date: str,
        decision_generated_at: str,
        _seen_paths: set[str] | None = None,
    ) -> set[str]:
        """Verify a real prior manager snapshot used by KEEP/ADD/REMOVE."""

        if not isinstance(baseline_ref, Mapping):
            raise ValueError("manager decision baseline reference is missing")
        path_value = baseline_ref.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise ValueError("manager decision baseline path is missing")
        path = Path(path_value)
        if not path.is_file() or path.is_symlink():
            raise ValueError("manager decision baseline SHA mismatch")
        path_key = str(path)
        seen_paths = set(_seen_paths or set())
        if path_key in seen_paths:
            raise ValueError("manager decision baseline reference cycle")
        seen_paths.add(path_key)
        baseline_raw = path.read_bytes()
        if hashlib.sha256(baseline_raw).hexdigest() != str(
            baseline_ref.get("raw_sha256") or ""
        ).lower():
            raise ValueError("manager decision baseline SHA mismatch")
        try:
            baseline = json.loads(baseline_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("manager decision baseline is invalid JSON") from error
        if not isinstance(baseline, Mapping):
            raise ValueError("manager decision baseline is not an object")
        if baseline.get("source_date") != source_date:
            raise ValueError("manager decision baseline source date mismatch")
        if baseline.get("target_trade_date") != target_trade_date:
            raise ValueError("manager decision baseline target date mismatch")
        baseline_time = baseline.get("generated_at") or baseline.get("event_at")
        if not isinstance(baseline_time, str) or not baseline_time:
            raise ValueError("manager decision baseline timestamp is missing")
        try:
            prior = datetime.fromisoformat(baseline_time.replace("Z", "+00:00"))
            current = datetime.fromisoformat(decision_generated_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("manager decision baseline timestamp is invalid") from error
        if (
            prior.tzinfo is None
            or prior.utcoffset() is None
            or current.tzinfo is None
            or current.utcoffset() is None
            or prior.astimezone(_SHANGHAI) >= current.astimezone(_SHANGHAI)
        ):
            raise ValueError("manager decision baseline is not earlier than decision")

        schema_version = baseline.get("schema_version")
        if schema_version == SELECTION_SCHEMA_VERSION:
            try:
                validate_selection_research_product(baseline)
            except ValueError as error:
                raise ValueError("manager decision baseline selection product is invalid") from error
            try:
                cls._verify_product_sources(baseline, _seen_paths=seen_paths)
            except ValueError as error:
                raise ValueError("manager decision baseline selection source is invalid") from error
            manager_proof = baseline.get("manager_decision_ref")
            formal_authority = baseline.get("formal_authority")
            if isinstance(manager_proof, Mapping):
                proof_ids = cls._verify_manager_baseline(
                    manager_proof,
                    source_date=source_date,
                    target_trade_date=target_trade_date,
                    decision_generated_at=decision_generated_at,
                    _seen_paths=seen_paths,
                )
            elif (
                isinstance(formal_authority, Mapping)
                and formal_authority.get("status") == "READY"
                and baseline.get("formal_shortlist")
                and isinstance(formal_authority.get("manager_decision_ref"), Mapping)
            ):
                # _verify_product_sources above has already verified the
                # structured formal manager proof and its candidate bindings.
                proof_ids = set(baseline["formal_shortlist"])
            else:
                raise ValueError("manager decision baseline lacks a real manager proof")
            snapshots = baseline.get("snapshots")
            if not isinstance(snapshots, Mapping):
                raise ValueError("manager decision baseline snapshots are missing")
            ready_phases = [
                phase
                for phase in ("2200", "0830", "0935", "1620")
                if isinstance(snapshots.get(phase), Mapping)
                and snapshots[phase].get("status") == "READY"
            ]
            if not ready_phases:
                raise ValueError("manager decision baseline has no READY snapshot")
            snapshot = snapshots[ready_phases[-1]]
            candidate_ids = snapshot.get("candidate_ids")
            if not isinstance(candidate_ids, list):
                raise ValueError("manager decision baseline candidate set is invalid")
            if len(candidate_ids) != len(set(candidate_ids)):
                raise ValueError("manager decision baseline candidate set is invalid")
            if isinstance(manager_proof, Mapping) and set(candidate_ids) != proof_ids:
                raise ValueError("manager decision baseline manager proof set mismatch")
            return set(candidate_ids)

        if schema_version != MANAGER_DECISION_SCHEMA_VERSION:
            raise ValueError("manager decision baseline schema is not an accepted product")
        baseline_supply_ref = baseline.get("supply_ref")
        if not isinstance(baseline_supply_ref, Mapping):
            raise ValueError("manager decision baseline supply reference is missing")
        baseline_supply_path_value = baseline_supply_ref.get("path")
        if not isinstance(baseline_supply_path_value, str) or not baseline_supply_path_value:
            raise ValueError("manager decision baseline supply path is missing")
        baseline_supply_path = Path(baseline_supply_path_value)
        if not baseline_supply_path.is_file() or baseline_supply_path.is_symlink():
            raise ValueError("manager decision baseline supply is unavailable")
        baseline_supply_raw = baseline_supply_path.read_bytes()
        baseline_supply_sha = hashlib.sha256(baseline_supply_raw).hexdigest()
        if baseline_supply_sha != str(baseline_supply_ref.get("raw_sha256") or "").lower():
            raise ValueError("manager decision baseline supply SHA mismatch")
        try:
            baseline_supply_document = json.loads(baseline_supply_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("manager decision baseline supply is invalid JSON") from error
        if not isinstance(baseline_supply_document, Mapping):
            raise ValueError("manager decision baseline supply is not an object")
        baseline_run_id = baseline.get("run_id")
        validate_research_supply_envelope(
            baseline_supply_document,
            expected_source_date=source_date,
            expected_target_trade_date=target_trade_date,
            expected_run_id=baseline_run_id,
        )
        if baseline_supply_ref.get("run_id") != baseline_run_id:
            raise ValueError("manager decision baseline supply run binding mismatch")
        if baseline_supply_ref.get("frozen_payload_sha256") != baseline_supply_document.get(
            "frozen_payload_sha256"
        ):
            raise ValueError("manager decision baseline supply frozen SHA mismatch")
        baseline_cards = baseline_supply_document["frozen_payload"].get("event_cards")
        if not isinstance(baseline_cards, list):
            raise ValueError("manager decision baseline supply cards are invalid")
        baseline_candidate_ids: list[str] = []
        for card in baseline_cards:
            ticker = str(card.get("ticker") or "") if isinstance(card, Mapping) else ""
            if not re.fullmatch(r"\d{5}\.HK", ticker):
                raise ValueError("manager decision baseline supply card is invalid")
            candidate_id = f"HK.{ticker.split('.')[0]}|{ticker}"
            if candidate_id in baseline_candidate_ids:
                raise ValueError("manager decision baseline supply candidate is duplicated")
            baseline_candidate_ids.append(candidate_id)
        decision_ids = [
            row.get("candidate_id")
            for row in [*(baseline.get("core") or []), *(baseline.get("conditional") or [])]
            if isinstance(row, Mapping)
        ]
        if len(decision_ids) != len(
            [row for row in [*(baseline.get("core") or []), *(baseline.get("conditional") or [])] if isinstance(row, Mapping)]
        ):
            raise ValueError("manager decision baseline candidate set is invalid")
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("manager decision baseline candidate set is invalid")
        validate_manager_research_decision(
            baseline,
            candidate_ids=baseline_candidate_ids,
            supply_envelope=baseline_supply_document,
        )
        if set(decision_ids) - set(baseline_candidate_ids):
            raise ValueError("manager decision baseline supply candidate binding mismatch")
        predecessor_ids: set[str] | None = None
        if baseline.get("baseline_ref") is not None:
            predecessor_ids = cls._verify_manager_baseline(
                baseline["baseline_ref"],
                source_date=source_date,
                target_trade_date=target_trade_date,
                decision_generated_at=str(baseline["generated_at"]),
                _seen_paths=seen_paths,
            )
        keep_ids = {row["candidate_id"] for row in baseline["KEEP"]}
        add_ids = {row["candidate_id"] for row in baseline["ADD"]}
        remove_ids = {row["candidate_id"] for row in baseline["REMOVE"]}
        if predecessor_ids is None:
            expected_ids = add_ids
        else:
            if not keep_ids.issubset(predecessor_ids) or remove_ids - predecessor_ids:
                raise ValueError("manager decision baseline action set mismatch")
            if add_ids & predecessor_ids:
                raise ValueError("manager decision baseline action set mismatch")
            expected_ids = (predecessor_ids - remove_ids) | add_ids
        if set(decision_ids) != expected_ids:
            raise ValueError("manager decision baseline action set mismatch")
        return set(decision_ids)

    @classmethod
    def _verify_manager_qualification_refs(
        cls,
        decision: Mapping[str, Any],
        *,
        source_date: str,
        target_trade_date: str,
        candidate_ids: list[str],
    ) -> None:
        """Check bytes for optional qualifications without promoting them."""

        for ref in decision.get("qualification_refs", []):
            if not isinstance(ref, Mapping):
                raise ValueError("manager qualification reference is invalid")
            path_value = ref.get("path")
            raw_sha = ref.get("raw_sha256")
            if path_value is None and raw_sha is None:
                continue
            if not isinstance(path_value, str) or not path_value:
                raise ValueError("manager qualification path is missing")
            path = Path(path_value)
            if not path.is_file() or path.is_symlink():
                raise ValueError("manager qualification SHA mismatch")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != str(raw_sha or "").lower():
                raise ValueError("manager qualification SHA mismatch")
            try:
                document = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("manager qualification document is invalid JSON") from error
            if not isinstance(document, Mapping):
                raise ValueError("manager qualification document is not an object")
            if document.get("schema_version") != "v3_5.selection_formal_evidence.v1" or document.get("type") != "EXACT_DATE_PIT":
                raise ValueError("manager qualification document schema is invalid")
            if (
                document.get("source_date") != source_date
                or document.get("target_trade_date") != target_trade_date
            ):
                raise ValueError("manager qualification document date binding mismatch")
            documented_ids = document.get("candidate_ids")
            candidate_id = ref.get("candidate_id")
            if candidate_id not in candidate_ids:
                raise ValueError("manager qualification candidate is unknown")
            if not isinstance(documented_ids, list) or candidate_id not in documented_ids:
                raise ValueError("manager qualification document candidate binding mismatch")
            if document.get("status") not in {"READY", "ELIGIBLE"}:
                raise ValueError("manager qualification document status is invalid")
            if "pit_status" in document and document.get("pit_status") != "READY":
                raise ValueError("manager qualification document PIT status is invalid")
            bindings = document.get("candidate_bindings")
            if bindings is not None:
                if not isinstance(bindings, list):
                    raise ValueError("manager qualification document bindings are invalid")
                matching = [
                    binding
                    for binding in bindings
                    if isinstance(binding, Mapping)
                    and binding.get("candidate_id") == candidate_id
                ]
                if not matching or any(
                    binding.get("eligibility") != "ELIGIBLE"
                    or binding.get("pit_status") != "READY"
                    or not isinstance(binding.get("source_refs"), list)
                    or not binding["source_refs"]
                    for binding in matching
                ):
                    raise ValueError("manager qualification document proof is incomplete")

    @classmethod
    def _verify_auxiliary_ref(
        cls,
        ref: Any,
        label: str,
        *,
        schema_version: str | None = None,
        expected_type: str | None = None,
        source_date: str | None = None,
        target_trade_date: str | None = None,
        candidate_ids: list[str] | None = None,
        source_sha256: str | None = None,
        expected_run_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str) or not ref["path"]:
            raise ValueError(f"{label} reference is missing")
        path = Path(ref["path"])
        if not path.is_file() or path.is_symlink() or cls._raw_sha(path) != str(ref.get("sha256") or "").lower():
            raise ValueError(f"{label} reference SHA mismatch")
        if schema_version is None and expected_type is None:
            return None
        try:
            document = json.loads(path.read_bytes().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"{label} document is not valid JSON") from error
        if not isinstance(document, Mapping):
            raise ValueError(f"{label} document is not an object")
        required = {
            "schema_version",
            "type",
            "source_sha256",
            "source_date",
            "target_trade_date",
            "run_id",
            "candidate_ids",
        }
        if not required.issubset(document):
            raise ValueError(f"{label} document schema is incomplete")
        if schema_version is not None and document.get("schema_version") != schema_version:
            raise ValueError(f"{label} document schema is invalid")
        if expected_type is not None and document.get("type") != expected_type:
            raise ValueError(f"{label} document type is invalid")
        if source_sha256 is not None and document.get("source_sha256") != source_sha256:
            raise ValueError(f"{label} document source binding mismatch")
        if source_date is not None and document.get("source_date") != source_date:
            raise ValueError(f"{label} document source date mismatch")
        if target_trade_date is not None and document.get("target_trade_date") != target_trade_date:
            raise ValueError(f"{label} document target date mismatch")
        if expected_run_id is not None and document.get("run_id") != expected_run_id:
            raise ValueError(f"{label} document run binding mismatch")
        if candidate_ids is not None and document.get("candidate_ids") != candidate_ids:
            raise ValueError(f"{label} document candidate binding mismatch")
        return document

    @staticmethod
    def _source_scope_from_evidence_value(value: Any) -> str | None:
        """Normalize a dispatcher/hourly pointer value to the scope enum."""

        if isinstance(value, str):
            return _selection_market_name(value)
        if isinstance(value, list):
            normalized = [_selection_market_name(item) for item in value]
            if any(scope is None for scope in normalized):
                return None
            scopes = set(normalized)
            if len(scopes) == 1:
                return next(iter(scopes))
            if len(scopes) > 1:
                return "MIXED"
            return None
        if isinstance(value, Mapping):
            for field in ("market_scope", "source_scope", "scope", "eligible_markets", "markets"):
                if field in value:
                    return ResearchSelectionStore._source_scope_from_evidence_value(
                        value[field]
                    )
        return None

    @classmethod
    def _verify_source_scope_evidence(
        cls,
        record: Mapping[str, Any],
    ) -> None:
        """Verify every immutable evidence reference in one invalidation."""

        for ref in record["evidence_refs"]:
            path = Path(ref["path"])
            if not path.is_file() or path.is_symlink():
                raise ValueError("selection source-scope evidence is unavailable")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != str(ref["raw_sha256"]).lower():
                raise ValueError("selection source-scope evidence SHA mismatch")
            try:
                document = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("selection source-scope evidence is invalid JSON") from error
            observed = cls._source_scope_from_evidence_value(
                cls._pointer_value(document, ref["json_pointer"])
            )
            if observed != ref["observed_source_scope"]:
                raise ValueError("selection source-scope evidence scope mismatch")

    def _read_source_scope_invalidations(
        self,
        target_trade_date: str,
    ) -> list[dict[str, Any]]:
        """Read and verify append-only scope records for one exact target date."""

        prefix = f"{self._SELECTION_ROOT}/{target_trade_date}/invalidations/"
        manifest = self._manifest()
        manifest_paths = {
            relative
            for relative in manifest["entries"]
            if relative.startswith(prefix)
        }
        directory = self._path(prefix)
        if not directory.exists():
            if manifest_paths:
                raise ValueError("selection source-scope invalidation manifest mismatch")
            return []
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("selection source-scope invalidation directory is invalid")
        actual_paths: set[str] = set()
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ValueError("selection source-scope invalidation directory is invalid")
            actual_paths.add(f"{prefix}{path.name}")
        if actual_paths != manifest_paths:
            raise ValueError("selection source-scope invalidation manifest mismatch")

        records: list[dict[str, Any]] = []
        for relative in sorted(manifest_paths):
            path = self._path(relative)
            if not path.is_file() or path.is_symlink():
                raise ValueError("selection source-scope invalidation is unavailable")
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if manifest["entries"].get(relative) != digest:
                raise ValueError("selection source-scope invalidation manifest mismatch")
            try:
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("selection source-scope invalidation is invalid JSON") from error
            if not isinstance(record, Mapping):
                raise ValueError("selection source-scope invalidation is not an object")
            try:
                validate_selection_source_scope_invalidation(
                    record,
                    expected_target_trade_date=target_trade_date,
                )
                expected_id = selection_source_scope_invalidation_id(record)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"selection source-scope invalidation is invalid: {error}"
                ) from error
            if path.stem != expected_id or self._canonical_sha(record) != digest:
                raise ValueError("selection source-scope invalidation bytes mismatch")
            records.append(dict(record))
        return records

    def _assert_source_scope_not_invalidated(
        self,
        payload: Mapping[str, Any],
        artifact_sha: str,
    ) -> None:
        records = self._read_source_scope_invalidations(
            str(payload["target_trade_date"])
        )
        for record in records:
            self._verify_source_scope_evidence(record)
            if (
                record["prior_run_id"] != payload.get("run_id")
                or str(record["prior_product_sha256"]).lower() != artifact_sha.lower()
            ):
                continue
            if record["source_date"] != payload.get("source_date"):
                raise ValueError("SOURCE_SCOPE_INVALIDATED: source date binding mismatch")
            raise ValueError(
                "SOURCE_SCOPE_INVALIDATED: upstream market scope invalidation "
                "matched prior run and product SHA"
            )

    def publish_source_scope_invalidation(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one independently attested upstream scope invalidation.

        The record is content-addressed and indexed by the selection manifest;
        it never changes an existing product, receipt, or current pointer.
        """

        target_trade_date = validate_selection_source_scope_invalidation(record)
        invalidation_id = str(record["invalidation_id"]).lower()
        expected_id = selection_source_scope_invalidation_id(record)
        if invalidation_id != expected_id:
            raise ValueError("selection source-scope invalidation id mismatch")
        relative = self._source_scope_invalidation_relative(
            target_trade_date,
            invalidation_id,
        )
        body = dict(record)
        self._verify_source_scope_evidence(body)
        digest = self._canonical_sha(body)
        path = self._path(relative)
        with self._lock():
            manifest = self._manifest()
            entries = dict(manifest["entries"])
            existing = entries.get(relative)
            if existing is not None:
                if existing != digest:
                    raise ValueError("conflicting selection source-scope invalidation")
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or self._raw_sha(path) != digest
                    or self._read(relative) != body
                ):
                    raise ValueError(
                        "selection source-scope invalidation integrity mismatch"
                    )
            else:
                if path.exists():
                    raise ValueError(
                        "orphan selection source-scope invalidation"
                    )
                self._write(relative, body)
                entries[relative] = digest
                self._write_manifest({**manifest, "entries": entries})
        return {
            "target_trade_date": target_trade_date,
            "invalidation_id": invalidation_id,
            "record_path": relative,
            "record_sha256": digest,
            "schema_version": SELECTION_SOURCE_SCOPE_INVALIDATION_SCHEMA_VERSION,
            "type": SELECTION_SOURCE_SCOPE_INVALIDATION_TYPE,
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _read_date_current(self, target_trade_date: str) -> dict[str, Any] | None:
        value, _ = self._read_date_current_snapshot(target_trade_date)
        return value

    def _read_date_current_snapshot(
        self,
        target_trade_date: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        relative = self._date_current_relative(target_trade_date)
        path = self._path(relative)
        if not path.is_file():
            if path.exists():
                raise ValueError("selection current pointer is not a file")
            return None, None
        raw = path.read_bytes()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("selection current pointer is invalid JSON") from error
        self._validate_current(value, target_trade_date=target_trade_date)
        return value, hashlib.sha256(raw).hexdigest()

    def _read_run(self, target_trade_date: str, run_id: str) -> dict[str, Any]:
        if not self._RUN_ID.fullmatch(run_id):
            raise ValueError("invalid selection run_id")
        artifact_relative = self._artifact_relative(target_trade_date, run_id)
        receipt_relative = self._receipt_relative(target_trade_date, run_id)
        run_manifest_relative = self._run_manifest_relative(target_trade_date, run_id)
        artifact_path = self._path(artifact_relative)
        receipt_path = self._path(receipt_relative)
        if not artifact_path.is_file() or not receipt_path.is_file():
            raise ValueError("selection artifact or receipt is missing")
        payload = self._read(artifact_relative)
        artifact_sha = self._raw_sha(artifact_path)
        manifest = self._manifest()
        run_manifest_path = self._path(run_manifest_relative)
        if not run_manifest_path.is_file():
            raise ValueError("selection run manifest is missing")
        run_manifest = self._read(run_manifest_relative)
        self._validate_manifest(run_manifest)
        run_manifest_sha = self._raw_sha(run_manifest_path)
        if (
            run_manifest["entries"].get(artifact_relative) != artifact_sha
            or manifest["entries"].get(artifact_relative) != artifact_sha
            or manifest["entries"].get(run_manifest_relative) != run_manifest_sha
        ):
            raise ValueError("selection artifact manifest mismatch")
        receipt = self._read(receipt_relative)
        receipt_sha = self._raw_sha(receipt_path)
        if (
            run_manifest["entries"].get(receipt_relative) != receipt_sha
            or manifest["entries"].get(receipt_relative) != receipt_sha
            or receipt != self._receipt(payload, artifact_relative, artifact_sha)
        ):
            raise ValueError("selection receipt manifest mismatch")
        if validate_selection_research_product(payload) != target_trade_date or payload.get("run_id") != run_id:
            raise ValueError("selection artifact identity mismatch")
        self._verify_product_sources(payload)
        self._assert_source_scope_not_invalidated(payload, artifact_sha)
        return payload

    def _read_current_run(
        self,
        target_trade_date: str,
        current: Mapping[str, Any],
        *,
        current_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Read a current target only after checking every pointer SHA binding."""

        run_id = str(current["run_id"])
        payload = self._read_run(target_trade_date, run_id)
        artifact_path = self._path(str(current["artifact_path"]))
        receipt_path = self._path(str(current["receipt_path"]))
        manifest_path = self._path(str(current["manifest_path"]))
        actual = {
            "artifact_sha256": self._raw_sha(artifact_path),
            "receipt_sha256": self._raw_sha(receipt_path),
            "manifest_sha256": self._raw_sha(manifest_path),
        }
        for field, digest in actual.items():
            if current.get(field) != digest:
                raise ValueError(f"selection current {field} binding mismatch")
        if current.get("target_trade_date") != target_trade_date:
            raise ValueError("selection current target date mismatch")
        if current.get("run_id") != payload.get("run_id") or current.get("generated_at") != payload.get("generated_at"):
            raise ValueError("selection current run identity binding mismatch")
        if current_sha256 is not None:
            current_path = self._path(self._date_current_relative(target_trade_date))
            if self._raw_sha(current_path) != current_sha256:
                raise ValueError("selection current pointer changed during read")
        global_path = self._path(self._CURRENT_RELATIVE)
        if global_path.is_file():
            global_current = self._read(self._CURRENT_RELATIVE)
            self._validate_global_current(global_current)
            if global_current.get("target_trade_date") == target_trade_date:
                if (
                    global_current.get("run_id") != current.get("run_id")
                    or global_current.get("artifact_sha256") != current.get("artifact_sha256")
                ):
                    raise ValueError("selection global current binding mismatch")
        elif global_path.exists():
            raise ValueError("selection global current pointer is not a file")
        return payload

    def publish(
        self,
        payload: Mapping[str, Any],
        *,
        manager_overlay_source_successor_ref: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Publish one immutable run and advance only the selection current pointer.

        The optional successor proof is a writer-side authorization for a
        later MANUAL_RECOVERY evidence overlay.  It is intentionally not part
        of the persisted product schema or receipt.
        """

        target_trade_date = validate_selection_research_product(payload)
        run_id = str(payload["run_id"])
        if not self._RUN_ID.fullmatch(run_id):
            raise ValueError("invalid selection run_id")
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
                if str(old_current["generated_at"]) > str(payload["generated_at"]):
                    raise ValueError("selection current cannot move backwards")
                for phase in ("0830", "0935", "1620"):
                    if (
                        old_snapshots.get(phase, {}).get("status") == "READY"
                        and old_snapshots.get(phase) != new_snapshots.get(phase)
                    ):
                        raise ValueError(f"selection {phase} snapshot is immutable")
            manifest = self._manifest()
            entries = dict(manifest["entries"])
            existing = entries.get(artifact_relative)
            artifact_path = self._path(artifact_relative)
            receipt_path = self._path(receipt_relative)
            run_manifest_path = self._path(run_manifest_relative)
            if existing and existing != artifact_sha:
                raise ValueError("conflicting selection run")
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
                    raise ValueError("selection existing artifact integrity mismatch")
            else:
                if artifact_path.exists() or receipt_path.exists() or run_manifest_path.exists():
                    raise ValueError("orphan selection artifact or receipt")
                self._write(artifact_relative, payload)
                self._write(receipt_relative, receipt)
                self._write(run_manifest_relative, run_manifest)
                entries[artifact_relative] = artifact_sha
                entries[receipt_relative] = receipt_sha
                entries[run_manifest_relative] = run_manifest_sha
                manifest = {**manifest, "entries": entries}
                self._write_manifest(manifest)
            if existing and entries.get(run_manifest_relative) != run_manifest_sha:
                raise ValueError("selection run manifest index mismatch")
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
                if str(old_global["target_trade_date"]) > target_trade_date:
                    global_pointer = old_global
                elif str(old_global["target_trade_date"]) == target_trade_date and old_global == global_pointer:
                    global_pointer = old_global
                else:
                    global_updated = old_global != global_pointer
            elif global_path.exists():
                raise ValueError("selection global current pointer is not a file")
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

    def read_exact(self, target_trade_date: str) -> dict[str, Any] | None:
        target_trade_date = _date(target_trade_date)
        current, current_sha256 = self._read_date_current_snapshot(target_trade_date)
        if current is None:
            prefix = f"{self._SELECTION_ROOT}/{target_trade_date}/"
            if any(str(path).startswith(prefix) for path in self._manifest()["entries"]):
                raise ValueError("selection artifact exists without current pointer")
            return None
        return self._read_current_run(
            target_trade_date,
            current,
            current_sha256=current_sha256,
        )

    def read_run(self, target_trade_date: str, run_id: str) -> dict[str, Any]:
        return self._read_run(_date(target_trade_date), run_id)

    def read_lineage(self, target_trade_date: str) -> dict[str, Any] | None:
        target_trade_date = _date(target_trade_date)
        _, lineage = self.read_exact_with_lineage(target_trade_date)
        return lineage

    def read_exact_with_lineage(
        self,
        target_trade_date: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        target_trade_date = _date(target_trade_date)
        current, current_sha256 = self._read_date_current_snapshot(target_trade_date)
        if current is None:
            prefix = f"{self._SELECTION_ROOT}/{target_trade_date}/"
            if any(str(path).startswith(prefix) for path in self._manifest()["entries"]):
                raise ValueError("selection artifact exists without current pointer")
            return None, None
        payload = self._read_current_run(
            target_trade_date,
            current,
            current_sha256=current_sha256,
        )
        manifest_path = self._path(str(current["manifest_path"]))
        lineage = {
            "artifact_path": current["artifact_path"],
            "artifact_sha256": current["artifact_sha256"],
            "receipt_path": current["receipt_path"],
            "receipt_sha256": current["receipt_sha256"],
            "manifest_path": current["manifest_path"],
            "manifest_sha256": self._raw_sha(manifest_path),
            "current_path": self._date_current_relative(target_trade_date),
            "current_sha256": current_sha256,
            "run_id": current["run_id"],
            "target_trade_date": target_trade_date,
        }
        return payload, lineage

    def append_phase(
        self,
        target_trade_date: str,
        phase: str,
        *,
        run_id: str,
        event_at: str,
        artifact_sha256: str,
        changes: list[Mapping[str, Any]] | None = None,
        observation: Mapping[str, Any] | None = None,
        outcome: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = self.read_exact(target_trade_date)
        if base is None:
            raise ValueError("selection base ledger is not materialized")
        next_product = append_selection_phase(
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


class HourlyResearchStore(NativeDataStore):
    """Immutable per-slot research artifacts with a LIVE-only latest pointer."""

    def _path(self, relative: str) -> Path:
        return resolve_owned_path(self.root, relative)

    @staticmethod
    def _relative(archive_date: str, slot: str, mode: str) -> str:
        return f"research/hourly/{mode.lower()}/{archive_date}/{slot}.json"

    @staticmethod
    def _receipt_relative(archive_date: str, slot: str, mode: str) -> str:
        return f"receipts/research/hourly/{mode.lower()}/{archive_date}/{slot}.json"

    @staticmethod
    def _transform_validation_relative(
        archive_date: str,
        slot: str,
        mode: str,
        source_input_sha256: str,
        transformer_identity_sha256: str,
    ) -> str:
        validation_key = _sha256(
            {
                "source_input_sha256": source_input_sha256,
                "transformer_identity_sha256": transformer_identity_sha256,
            }
        )
        return (
            "receipts/research/hourly/transform-validation/"
            f"{mode.lower()}/{archive_date}/{slot}/"
            f"{validation_key}.json"
        )

    @staticmethod
    def _receipt(
        payload: Mapping[str, Any], digest: str, *, slot: str, mode: str
    ) -> dict[str, Any]:
        archive_date = str(payload["archive_date"])
        return {
            "schema_version": "v3_5.hourly_research_receipt.v1",
            "archive_date": archive_date,
            "slot": slot,
            "mode": mode,
            "payload_path": HourlyResearchStore._relative(
                archive_date, slot, mode
            ),
            "payload_sha256": digest,
            "source_input_sha256": payload["source_input_sha256"],
            "article_count": payload["article_count"],
            "stock_pool_count": payload["stock_pool_count"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    @staticmethod
    def _transform_validation(
        payload: Mapping[str, Any],
        digest: str,
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str,
    ) -> dict[str, Any]:
        archive_date = str(payload["archive_date"])
        source_input_sha256 = str(payload["source_input_sha256"])
        return {
            "schema_version": "v3_5.hourly_research_transform_validation.v1",
            "archive_date": archive_date,
            "slot": slot,
            "mode": mode,
            "payload_path": HourlyResearchStore._relative(
                archive_date,
                slot,
                mode,
            ),
            "payload_sha256": digest,
            "source_input_sha256": source_input_sha256,
            "transformer_identity_sha256": transformer_identity_sha256,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def publish(
        self,
        payload: Mapping[str, Any],
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str | None = None,
    ) -> dict[str, Any]:
        archive_date = validate_research_archive(payload)
        normalized_slot = _slot(slot)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "hourly research mode must be LIVE, REPLAY, or BACKFILL"
            )
        normalized_transformer_sha = None
        if transformer_identity_sha256 is not None:
            normalized_transformer_sha = str(
                transformer_identity_sha256
            ).lower()
            if not _SHA256.fullmatch(normalized_transformer_sha):
                raise ValueError(
                    "hourly research transformer identity must be SHA-256"
                )
        relative = self._relative(
            archive_date, normalized_slot, normalized_mode
        )
        receipt_relative = self._receipt_relative(
            archive_date, normalized_slot, normalized_mode
        )
        digest = _sha256(payload)
        receipt = self._receipt(
            payload,
            digest,
            slot=normalized_slot,
            mode=normalized_mode,
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
                existing or interrupted_recovery
            ):
                self._assert_latest_not_backwards(
                    archive_date, normalized_slot
                )
            if existing:
                if (
                    not payload_path.is_file()
                    or _sha256(self._read(relative)) != digest
                    or not receipt_path.is_file()
                    or self._read(receipt_relative) != receipt
                ):
                    raise ValueError("hourly research integrity mismatch")
            elif payload_path.exists():
                if (
                    not payload_path.is_file()
                    or _sha256(self._read(relative)) != digest
                ):
                    raise ValueError(
                        "conflicting interrupted hourly research artifact"
                    )
                if receipt_path.exists():
                    if (
                        not receipt_path.is_file()
                        or self._read(receipt_relative) != receipt
                    ):
                        raise ValueError(
                            "conflicting interrupted hourly research receipt"
                        )
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
            if normalized_mode == "LIVE":
                if not self._latest_is_after(
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

    def _publish_transform_validation_locked(
        self,
        payload: Mapping[str, Any],
        digest: str,
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str,
    ) -> None:
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
            archive_date,
            slot,
            mode,
            source_input_sha256,
            transformer_identity_sha256,
        )
        validation_path = self._path(validation_relative)
        if validation_path.exists():
            if (
                not validation_path.is_file()
                or self._read(validation_relative) != validation
            ):
                raise ValueError(
                    "hourly research transform validation mismatch"
                )
        else:
            self._write(validation_relative, validation)

    def _assert_latest_not_backwards(
        self, archive_date: str, slot: str
    ) -> None:
        if self._latest_is_after(archive_date, slot):
            raise ValueError(
                "LIVE hourly research publication cannot move latest backwards"
            )

    def _latest_is_after(self, archive_date: str, slot: str) -> bool:
        destination = self._path("research/hourly/latest.json")
        if not destination.exists():
            return False
        if not destination.is_file():
            raise ValueError("invalid hourly research latest pointer")
        existing = self._read("research/hourly/latest.json")
        self._validate_pointer(existing)
        return (
            str(existing["archive_date"]),
            str(existing["slot"]),
        ) > (archive_date, slot)

    def _update_latest(
        self, archive_date: str, slot: str, digest: str
    ) -> bool:
        relative = "research/hourly/latest.json"
        destination = self._path(relative)
        if destination.is_file():
            existing = self._read(relative)
            self._validate_pointer(existing)
            existing_position = (
                str(existing["archive_date"]),
                str(existing["slot"]),
            )
            requested_position = (archive_date, slot)
            if existing_position > requested_position:
                raise ValueError(
                    "LIVE hourly research publication cannot move latest backwards"
                )
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

    @staticmethod
    def _validate_pointer(pointer: Mapping[str, Any]) -> None:
        fields = {
            "schema_version",
            "archive_date",
            "slot",
            "mode",
            "payload_path",
            "payload_sha256",
            "pointer_semantic_hash",
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
            != HourlyResearchStore._relative(archive_date, slot, "LIVE")
            or not _SHA256.fullmatch(str(pointer.get("payload_sha256") or ""))
            or pointer.get("pointer_semantic_hash") != _sha256(body)
        ):
            raise ValueError("invalid hourly research latest pointer")

    def list_slots(self, archive_date: str, *, mode: str) -> list[str]:
        """Return verified slots for one exact archive date.

        Date-bound consumers must enumerate the manifest and both on-disk
        sides before reading a slot.  In particular, this method never falls
        back to the LIVE latest pointer, which could silently cross a date
        boundary during next-day materialization.
        """

        archive_date = _date(archive_date)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "hourly research mode must be LIVE, REPLAY, or BACKFILL"
            )
        mode_dir = normalized_mode.lower()
        artifact_prefix = f"research/hourly/{mode_dir}/{archive_date}/"
        receipt_prefix = f"receipts/research/hourly/{mode_dir}/{archive_date}/"
        manifest = self._manifest()
        manifest_slots: set[str] = set()
        for relative in manifest:
            if not relative.startswith(artifact_prefix):
                continue
            suffix = relative[len(artifact_prefix) :]
            if "/" in suffix or not suffix.endswith(".json"):
                continue
            manifest_slots.add(_slot(suffix[:-5]))

        def file_slots(relative: str) -> set[str]:
            directory = self._path(relative)
            if not directory.exists():
                return set()
            if not directory.is_dir():
                raise ValueError(
                    "hourly research slot directory is not a directory"
                )
            slots: set[str] = set()
            for candidate in directory.iterdir():
                if not candidate.is_file() or candidate.suffix != ".json":
                    continue
                slots.add(_slot(candidate.stem))
            return slots

        artifact_slots = file_slots(artifact_prefix)
        receipt_slots = file_slots(receipt_prefix)
        if (
            manifest_slots != artifact_slots
            or manifest_slots != receipt_slots
        ):
            raise ValueError("hourly research manifest or receipt mismatch")

        verified: list[str] = []
        for slot in sorted(manifest_slots):
            if self.read_exact(archive_date, slot, mode=normalized_mode) is None:
                raise ValueError("hourly research manifest or receipt mismatch")
            verified.append(slot)
        return verified

    def read_latest_for_date(
        self, archive_date: str, *, mode: str
    ) -> tuple[str, dict[str, Any]] | None:
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

    def read_exact(
        self, archive_date: str, slot: str, *, mode: str
    ) -> dict[str, Any] | None:
        archive_date = _date(archive_date)
        normalized_slot = _slot(slot)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "hourly research mode must be LIVE, REPLAY, or BACKFILL"
            )
        relative = self._relative(
            archive_date, normalized_slot, normalized_mode
        )
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
            != self._receipt(
                payload,
                digest,
                slot=normalized_slot,
                mode=normalized_mode,
            )
            or validate_research_archive(payload) != archive_date
        ):
            raise ValueError("hourly research manifest or receipt mismatch")
        return payload

    def reuse_matching_source(
        self,
        archive_date: str,
        slot: str,
        *,
        mode: str,
        source_input_sha256: str,
        transformer_identity_sha256: str,
    ) -> dict[str, Any] | None:
        """Republish a finalized exact artifact only when its source is identical."""
        archive_date = _date(archive_date)
        normalized_slot = _slot(slot)
        normalized_mode = str(mode).upper()
        if normalized_mode not in _MODES:
            raise ValueError(
                "hourly research mode must be LIVE, REPLAY, or BACKFILL"
            )
        normalized_source_sha = str(source_input_sha256).lower()
        if not _SHA256.fullmatch(normalized_source_sha):
            raise ValueError("hourly research source SHA must be SHA-256")
        normalized_transformer_sha = str(transformer_identity_sha256).lower()
        if not _SHA256.fullmatch(normalized_transformer_sha):
            raise ValueError("hourly research transformer identity must be SHA-256")
        relative = self._relative(
            archive_date,
            normalized_slot,
            normalized_mode,
        )
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
                    raise ValueError(
                        "invalid hourly research transform validation"
                    )
                return None
            if relative not in self._manifest():
                raise ValueError("orphan hourly research transform validation")
            payload = self.read_exact(
                archive_date,
                normalized_slot,
                mode=normalized_mode,
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
                raise ValueError(
                    "hourly research transform validation mismatch"
                )
            if normalized_mode == "LIVE" and not self._latest_is_after(
                archive_date,
                normalized_slot,
            ):
                latest_updated = self._update_latest(
                    archive_date,
                    normalized_slot,
                    digest,
                )
        return {
            "archive_date": archive_date,
            "slot": normalized_slot,
            "mode": normalized_mode,
            "payload_path": relative,
            "receipt_path": self._receipt_relative(
                archive_date,
                normalized_slot,
                normalized_mode,
            ),
            "payload_sha256": digest,
            "latest_updated": latest_updated,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def read_latest(self) -> dict[str, Any] | None:
        relative = "research/hourly/latest.json"
        pointer_path = self._path(relative)
        if not pointer_path.is_file():
            if pointer_path.exists():
                raise ValueError("invalid hourly research latest pointer")
            return None
        pointer = self._read(relative)
        self._validate_pointer(pointer)
        payload = self.read_exact(
            str(pointer["archive_date"]),
            str(pointer["slot"]),
            mode="LIVE",
        )
        if payload is None or _sha256(payload) != pointer["payload_sha256"]:
            raise ValueError("hourly research latest pointer target mismatch")
        return payload


__all__ = ["HourlyResearchStore", "ResearchArchiveStore", "ResearchSelectionStore"]
