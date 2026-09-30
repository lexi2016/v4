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
from infrastructure._research_store_parts import schema_values as _v4_definitions
_MANAGER_OVERLAY_PROOF_FIELDS = _v4_definitions._value__MANAGER_OVERLAY_PROOF_FIELDS(globals())
_MANAGER_OVERLAY_SUPPLY_REF_FIELDS = _v4_definitions._value__MANAGER_OVERLAY_SUPPLY_REF_FIELDS(globals())
_MANAGER_OVERLAY_RECORD_FIELDS = frozenset(
    {"candidate_id", "ticker", "before_card_sha", "after_card_sha", "changed_paths"}
)
_MANAGER_OVERLAY_SAFETY_FIELDS = frozenset(
    {"RESEARCH_ONLY", "WATCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent"}
)

# This is deliberately a closed set.  The proof is an authorization for the
# observed V2 -> V4 evidence enrichment only; it cannot grant itself a new
# mutation class by adding a path to the artifact.
MANAGER_OVERLAY_CARD_CHANGED_PATHS = _v4_definitions._value_MANAGER_OVERLAY_CARD_CHANGED_PATHS(globals())
MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS = _v4_definitions._value_MANAGER_OVERLAY_ENVELOPE_CHANGED_PATHS(globals())
MANAGER_OVERLAY_PRODUCT_DERIVED_FIELDS = frozenset(
    {"catalyst", "evidence_level", "source_status", "source_time"}
)


def _manager_overlay_changed_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    """Return deterministic leaf/container paths for an evidence diff."""
    from infrastructure._research_store_parts.overlay_references import __manager_overlay_changed_paths_body as _v4_impl
    return _v4_impl(globals(), before, after, prefix)


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
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore__receipt_body as _v4_impl
        return _v4_impl(globals(), payload, digest)

    @staticmethod
    def _day_receipt(payload: Mapping[str, Any], digest: str) -> dict[str, Any]:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore__day_receipt_body as _v4_impl
        return _v4_impl(globals(), payload, digest)

    def publish(self, payload: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore_publish_body as _v4_impl
        return _v4_impl(globals(), self, payload, mode=mode)

    def _update_latest(self, archive_date: str, digest: str) -> bool:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore__update_latest_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, digest)

    @staticmethod
    def _validate_pointer(pointer: Mapping[str, Any]) -> None:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore__validate_pointer_body as _v4_impl
        return _v4_impl(globals(), pointer)

    def read_exact(self, archive_date: str) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore_read_exact_body as _v4_impl
        return _v4_impl(globals(), self, archive_date)

    def publish_day_product(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Publish a complete exact-date day product in its own namespace.

        The legacy generic archive and its receipt remain authoritative at
        ``research/archives/{date}.json``.  Day products use a separate
        manifest key and pointer namespace, so publishing a full-day product
        cannot overwrite or reinterpret a same-date generic archive.
        """
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore_publish_day_product_body as _v4_impl
        return _v4_impl(globals(), self, payload)

    def _update_day_latest(self, archive_date: str, digest: str) -> bool:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore__update_day_latest_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, digest)

    @staticmethod
    def _validate_day_latest_pointer(pointer: Mapping[str, Any]) -> None:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore__validate_day_latest_pointer_body as _v4_impl
        return _v4_impl(globals(), pointer)

    def _update_day_current(self, archive_date: str, digest: str) -> bool:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore__update_day_current_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, digest)

    @staticmethod
    def _validate_current_pointer(pointer: Mapping[str, Any]) -> None:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore__validate_current_pointer_body as _v4_impl
        return _v4_impl(globals(), pointer)

    def read_day_exact(self, archive_date: str) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore_read_day_exact_body as _v4_impl
        return _v4_impl(globals(), self, archive_date)

    def read_day_latest(self) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore_read_day_latest_body as _v4_impl
        return _v4_impl(globals(), self)

    def read_day_current(self) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore_read_day_current_body as _v4_impl
        return _v4_impl(globals(), self)

    def read_latest(self) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.archive_products import _ResearchArchiveStore_read_latest_body as _v4_impl
        return _v4_impl(globals(), self)

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
        from infrastructure._research_store_parts.selection_pointers import _ResearchSelectionStore__validate_manifest_body as _v4_impl
        return _v4_impl(globals(), cls, value)

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
        from infrastructure._research_store_parts.selection_pointers import _ResearchSelectionStore__receipt_body as _v4_impl
        return _v4_impl(globals(), cls, payload, artifact_relative, artifact_sha)

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
        from infrastructure._research_store_parts.selection_pointers import _ResearchSelectionStore__current_pointer_body as _v4_impl
        return _v4_impl(globals(), cls, payload, artifact_relative=artifact_relative, artifact_sha=artifact_sha, receipt_relative=receipt_relative, receipt_sha=receipt_sha, manifest_relative=manifest_relative, manifest_sha=manifest_sha)

    @classmethod
    def _validate_current(
        cls,
        value: Mapping[str, Any],
        *,
        target_trade_date: str | None = None,
    ) -> None:
        from infrastructure._research_store_parts.selection_pointers import _ResearchSelectionStore__validate_current_body as _v4_impl
        return _v4_impl(globals(), cls, value, target_trade_date=target_trade_date)

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
        from infrastructure._research_store_parts.selection_pointers import _ResearchSelectionStore__validate_global_current_body as _v4_impl
        return _v4_impl(globals(), cls, value)

    @staticmethod
    def _pointer_value(document: Any, pointer: str) -> Any:
        from infrastructure._research_store_parts.selection_pointers import _ResearchSelectionStore__pointer_value_body as _v4_impl
        return _v4_impl(globals(), document, pointer)

    @classmethod
    def _verify_source_ref(
        cls,
        ref: Mapping[str, Any],
        *,
        expected_target_trade_date: str | None = None,
    ) -> dict[str, Any]:
        from infrastructure._research_store_parts.source_evidence import _ResearchSelectionStore__verify_source_ref_body as _v4_impl
        return _v4_impl(globals(), cls, ref, expected_target_trade_date=expected_target_trade_date)

    @staticmethod
    def _selection_identity_text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _source_ref_identity(cls, ref: Mapping[str, Any]) -> tuple[str, ...]:
        """Return immutable locator fields used by formal proof bindings."""
        from infrastructure._research_store_parts.source_evidence import _ResearchSelectionStore__source_ref_identity_body as _v4_impl
        return _v4_impl(globals(), cls, ref)

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
        from infrastructure._research_store_parts.source_projection import _ResearchSelectionStore__verify_candidate_source_projection_body as _v4_impl
        return _v4_impl(globals(), cls, candidate, ref, verified, source_date=source_date, target_trade_date=target_trade_date, cutoff_at=cutoff_at)

    @staticmethod
    def _manager_overlay_time(value: Any, field: str) -> datetime:
        from infrastructure._research_store_parts.overlay_references import _ResearchSelectionStore__manager_overlay_time_body as _v4_impl
        return _v4_impl(globals(), value, field)

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
        from infrastructure._research_store_parts.overlay_references import _ResearchSelectionStore__read_manager_overlay_json_ref_body as _v4_impl
        return _v4_impl(globals(), cls, ref, label=label)

    @classmethod
    def _read_manager_overlay_supply_ref(
        cls,
        ref: Any,
        *,
        source_date: str,
        target_trade_date: str,
        label: str,
    ) -> dict[str, Any]:
        from infrastructure._research_store_parts.overlay_references import _ResearchSelectionStore__read_manager_overlay_supply_ref_body as _v4_impl
        return _v4_impl(globals(), cls, ref, source_date=source_date, target_trade_date=target_trade_date, label=label)

    @classmethod
    def _read_manager_overlay_decision(
        cls,
        payload: Mapping[str, Any],
        *,
        source_envelope: Mapping[str, Any],
        candidate_ids: list[str],
        label: str,
    ) -> tuple[dict[str, Any], str]:
        from infrastructure._research_store_parts.overlay_references import _ResearchSelectionStore__read_manager_overlay_decision_body as _v4_impl
        return _v4_impl(globals(), cls, payload, source_envelope=source_envelope, candidate_ids=candidate_ids, label=label)

    @classmethod
    def _product_supply_refs(
        cls,
        payload: Mapping[str, Any],
        *,
        label: str,
    ) -> dict[str, Mapping[str, Any]]:
        from infrastructure._research_store_parts.overlay_references import _ResearchSelectionStore__product_supply_refs_body as _v4_impl
        return _v4_impl(globals(), cls, payload, label=label)

    @staticmethod
    def _manager_overlay_expected_projections(
        decision: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        from infrastructure._research_store_parts.overlay_references import _ResearchSelectionStore__manager_overlay_expected_projections_body as _v4_impl
        return _v4_impl(globals(), decision)

    @classmethod
    def _validate_manager_overlay_proof_shape(
        cls,
        proof: Mapping[str, Any],
        *,
        source_date: str,
        target_trade_date: str,
    ) -> None:
        from infrastructure._research_store_parts.overlay_references import _ResearchSelectionStore__validate_manager_overlay_proof_shape_body as _v4_impl
        return _v4_impl(globals(), cls, proof, source_date=source_date, target_trade_date=target_trade_date)

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
        from infrastructure._research_store_parts.overlay_product_diff import _ResearchSelectionStore__verify_manager_overlay_product_diff_body as _v4_impl
        return _v4_impl(globals(), cls, old_payload, new_payload, proof=proof, old_supply=old_supply, new_supply=new_supply, expected_projections=expected_projections)

    @classmethod
    def _verify_manager_overlay_successor(
        cls,
        old_payload: Mapping[str, Any],
        new_payload: Mapping[str, Any],
        proof_ref: Any,
    ) -> None:
        from infrastructure._research_store_parts.overlay_successor import _ResearchSelectionStore__verify_manager_overlay_successor_body as _v4_impl
        return _v4_impl(globals(), cls, old_payload, new_payload, proof_ref)

    @classmethod
    def _verify_product_sources(
        cls,
        payload: Mapping[str, Any],
        *,
        _seen_paths: set[str] | None = None,
    ) -> None:
        from infrastructure._research_store_parts.source_products import _ResearchSelectionStore__verify_product_sources_body as _v4_impl
        return _v4_impl(globals(), cls, payload, _seen_paths=_seen_paths)

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
        from infrastructure._research_store_parts.source_evidence import _ResearchSelectionStore__verify_formal_candidate_bindings_body as _v4_impl
        return _v4_impl(globals(), cls, document, candidates_by_id=candidates_by_id, candidate_ids=candidate_ids, label=label)

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
        from infrastructure._research_store_parts.manager_baseline import _ResearchSelectionStore__verify_manager_baseline_body as _v4_impl
        return _v4_impl(globals(), cls, baseline_ref, source_date=source_date, target_trade_date=target_trade_date, decision_generated_at=decision_generated_at, _seen_paths=_seen_paths)

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
        from infrastructure._research_store_parts.manager_baseline import _ResearchSelectionStore__verify_manager_qualification_refs_body as _v4_impl
        return _v4_impl(globals(), cls, decision, source_date=source_date, target_trade_date=target_trade_date, candidate_ids=candidate_ids)

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
        from infrastructure._research_store_parts.source_evidence import _ResearchSelectionStore__verify_auxiliary_ref_body as _v4_impl
        return _v4_impl(globals(), cls, ref, label, schema_version=schema_version, expected_type=expected_type, source_date=source_date, target_trade_date=target_trade_date, candidate_ids=candidate_ids, source_sha256=source_sha256, expected_run_id=expected_run_id)

    @staticmethod
    def _source_scope_from_evidence_value(value: Any) -> str | None:
        """Normalize a dispatcher/hourly pointer value to the scope enum."""
        from infrastructure._research_store_parts.source_invalidation import _ResearchSelectionStore__source_scope_from_evidence_value_body as _v4_impl
        return _v4_impl(globals(), value)

    @classmethod
    def _verify_source_scope_evidence(
        cls,
        record: Mapping[str, Any],
    ) -> None:
        """Verify every immutable evidence reference in one invalidation."""
        from infrastructure._research_store_parts.source_invalidation import _ResearchSelectionStore__verify_source_scope_evidence_body as _v4_impl
        return _v4_impl(globals(), cls, record)

    def _read_source_scope_invalidations(
        self,
        target_trade_date: str,
    ) -> list[dict[str, Any]]:
        """Read and verify append-only scope records for one exact target date."""
        from infrastructure._research_store_parts.source_invalidation import _ResearchSelectionStore__read_source_scope_invalidations_body as _v4_impl
        return _v4_impl(globals(), self, target_trade_date)

    def _assert_source_scope_not_invalidated(
        self,
        payload: Mapping[str, Any],
        artifact_sha: str,
    ) -> None:
        from infrastructure._research_store_parts.source_invalidation import _ResearchSelectionStore__assert_source_scope_not_invalidated_body as _v4_impl
        return _v4_impl(globals(), self, payload, artifact_sha)

    def publish_source_scope_invalidation(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one independently attested upstream scope invalidation.

        The record is content-addressed and indexed by the selection manifest;
        it never changes an existing product, receipt, or current pointer.
        """
        from infrastructure._research_store_parts.source_invalidation import _ResearchSelectionStore_publish_source_scope_invalidation_body as _v4_impl
        return _v4_impl(globals(), self, record)

    def _read_date_current(self, target_trade_date: str) -> dict[str, Any] | None:
        value, _ = self._read_date_current_snapshot(target_trade_date)
        return value

    def _read_date_current_snapshot(
        self,
        target_trade_date: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        from infrastructure._research_store_parts.selection_readers import _ResearchSelectionStore__read_date_current_snapshot_body as _v4_impl
        return _v4_impl(globals(), self, target_trade_date)

    def _read_run(self, target_trade_date: str, run_id: str) -> dict[str, Any]:
        from infrastructure._research_store_parts.selection_readers import _ResearchSelectionStore__read_run_body as _v4_impl
        return _v4_impl(globals(), self, target_trade_date, run_id)

    def _read_current_run(
        self,
        target_trade_date: str,
        current: Mapping[str, Any],
        *,
        current_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Read a current target only after checking every pointer SHA binding."""
        from infrastructure._research_store_parts.selection_readers import _ResearchSelectionStore__read_current_run_body as _v4_impl
        return _v4_impl(globals(), self, target_trade_date, current, current_sha256=current_sha256)

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
        from infrastructure._research_store_parts.selection_publish import _ResearchSelectionStore_publish_body as _v4_impl
        return _v4_impl(globals(), self, payload, manager_overlay_source_successor_ref=manager_overlay_source_successor_ref)

    def read_exact(self, target_trade_date: str) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.selection_readers import _ResearchSelectionStore_read_exact_body as _v4_impl
        return _v4_impl(globals(), self, target_trade_date)

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
        from infrastructure._research_store_parts.selection_readers import _ResearchSelectionStore_read_exact_with_lineage_body as _v4_impl
        return _v4_impl(globals(), self, target_trade_date)

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
        from infrastructure._research_store_parts.selection_publish import _ResearchSelectionStore_append_phase_body as _v4_impl
        return _v4_impl(globals(), self, target_trade_date, phase, run_id=run_id, event_at=event_at, artifact_sha256=artifact_sha256, changes=changes, observation=observation, outcome=outcome)


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
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__transform_validation_relative_body as _v4_impl
        return _v4_impl(globals(), archive_date, slot, mode, source_input_sha256, transformer_identity_sha256)

    @staticmethod
    def _receipt(
        payload: Mapping[str, Any], digest: str, *, slot: str, mode: str
    ) -> dict[str, Any]:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__receipt_body as _v4_impl
        return _v4_impl(globals(), payload, digest, slot=slot, mode=mode)

    @staticmethod
    def _transform_validation(
        payload: Mapping[str, Any],
        digest: str,
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str,
    ) -> dict[str, Any]:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__transform_validation_body as _v4_impl
        return _v4_impl(globals(), payload, digest, slot=slot, mode=mode, transformer_identity_sha256=transformer_identity_sha256)

    def publish(
        self,
        payload: Mapping[str, Any],
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str | None = None,
    ) -> dict[str, Any]:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore_publish_body as _v4_impl
        return _v4_impl(globals(), self, payload, slot=slot, mode=mode, transformer_identity_sha256=transformer_identity_sha256)

    def _publish_transform_validation_locked(
        self,
        payload: Mapping[str, Any],
        digest: str,
        *,
        slot: str,
        mode: str,
        transformer_identity_sha256: str,
    ) -> None:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__publish_transform_validation_locked_body as _v4_impl
        return _v4_impl(globals(), self, payload, digest, slot=slot, mode=mode, transformer_identity_sha256=transformer_identity_sha256)

    def _assert_latest_not_backwards(
        self, archive_date: str, slot: str
    ) -> None:
        if self._latest_is_after(archive_date, slot):
            raise ValueError(
                "LIVE hourly research publication cannot move latest backwards"
            )

    def _latest_is_after(self, archive_date: str, slot: str) -> bool:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__latest_is_after_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, slot)

    def _update_latest(
        self, archive_date: str, slot: str, digest: str
    ) -> bool:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__update_latest_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, slot, digest)

    @staticmethod
    def _validate_pointer(pointer: Mapping[str, Any]) -> None:
        from infrastructure._research_store_parts.hourly_publish import _HourlyResearchStore__validate_pointer_body as _v4_impl
        return _v4_impl(globals(), pointer)

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
        from infrastructure._research_store_parts.hourly_sources import _HourlyResearchStore_read_latest_for_date_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, mode=mode)

    def read_exact(
        self, archive_date: str, slot: str, *, mode: str
    ) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.hourly_sources import _HourlyResearchStore_read_exact_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, slot, mode=mode)

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
        from infrastructure._research_store_parts.hourly_sources import _HourlyResearchStore_reuse_matching_source_body as _v4_impl
        return _v4_impl(globals(), self, archive_date, slot, mode=mode, source_input_sha256=source_input_sha256, transformer_identity_sha256=transformer_identity_sha256)

    def read_latest(self) -> dict[str, Any] | None:
        from infrastructure._research_store_parts.hourly_sources import _HourlyResearchStore_read_latest_body as _v4_impl
        return _v4_impl(globals(), self)


__all__ = ["HourlyResearchStore", "ResearchArchiveStore", "ResearchSelectionStore"]
