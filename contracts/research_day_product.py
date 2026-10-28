"""Frozen contract for the V3.5 exact-date full-day research product.

The day product is deliberately separate from the legacy research_archive
schema. The legacy contract remains valid for old imports; this module only
defines the versioned envelope assembled from explicit hourly slots.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo


PRODUCT_SCHEMA_VERSION = "v3_5.research_day_product.v1"
CONTRACT_ID = PRODUCT_SCHEMA_VERSION
WORKFLOW_NAME = "V35_DAILY_RESEARCH_AUTHORITY_V1"
PASS_SIGNAL = "V35_DAILY_RESEARCH_AUTHORITY_PASS_V1"
TIMEZONE = "Asia/Shanghai"
DATE_MODE = "EXACT"
EXPECTED_RESEARCH_SLOTS = (
    "1000",
    "1100",
    "1200",
    "1300",
    "1400",
    "1500",
    "1600",
    "1700",
)
SAFETY_FLAGS = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHANGHAI = ZoneInfo(TIMEZONE)

_PRODUCT_FIELDS = {
    "schema_version",
    "contract_id",
    "workflow_name",
    "pass_signal",
    "archive_date",
    "timezone",
    "date_mode",
    "status",
    "authoritative",
    "write_policy",
    "recommendation_status",
    "expected_slots",
    "coverage",
    "counts",
    "exclusions",
    "excluded_by_date",
    "slot_matrix",
    "evidence_rows",
    "mention_pairs",
    "stock_rollups",
    "high_priority",
    "high_priority_status",
    "jyg_coverage",
    "lineage",
    "cannot_confirm",
    "RESEARCH_ONLY",
    "production_allowed",
    "buy_gate_updated",
    "orders_sent",
}


def _date(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("research day archive_date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("research day archive_date must be a real date") from error
    return value


def _sha(value: Any, field: str) -> str:
    normalized = str(value or "").lower()
    if not _SHA256.fullmatch(normalized):
        raise ValueError(f"invalid research day {field}")
    return normalized


def _sorted_strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"invalid research day {field}")
    if value != sorted(set(value)):
        raise ValueError(f"research day {field} must be sorted and unique")
    return value


def _pair_identity(row: Mapping[str, Any]) -> str | None:
    """Match the producer's exact URL+stock identity without guessing missing data."""
    from contracts._research_day_product_parts.primitives import __pair_identity_body as _v4_impl
    return _v4_impl(globals(), row)


def _validate_slot_matrix(value: Any) -> list[Mapping[str, Any]]:
    from contracts._research_day_product_parts.day_product import __validate_slot_matrix_body as _v4_impl
    return _v4_impl(globals(), value)


def _validate_not_materialized_product(payload: Mapping[str, Any]) -> None:
    """Validate a typed base-envelope gap without accepting stale rows."""
    from contracts._research_day_product_parts.day_product import __validate_not_materialized_product_body as _v4_impl
    return _v4_impl(globals(), payload)


def validate_research_day_product(payload: Mapping[str, Any]) -> str:
    """Validate the complete exact-date day-product envelope."""
    from contracts._research_day_product_parts.day_product import _validate_research_day_product_body as _v4_impl
    return _v4_impl(globals(), payload)


# The selection/research vertical slice deliberately lives beside the day
# contract so consumers can share the existing contract module without
# creating a second producer.  It has its own schema and storage namespace;
# it is not a legacy archive or a daily full-day authority.
SELECTION_SCHEMA_VERSION = "v3_5.selection_research_product.v1"
SELECTION_CONTRACT_ID = SELECTION_SCHEMA_VERSION
SELECTION_WORKFLOW_NAME = "V35_SELECTION_RESEARCH_PRODUCT"
SELECTION_PASS_SIGNAL = "V35_SELECTION_RESEARCH_VERTICAL_SLICE_VERIFIED"
SELECTION_ORIGINS = frozenset(
    {"NATURAL", "AUTO_RETRY", "MANUAL_RECOVERY", "HISTORICAL_RECONSTRUCTION"}
)
SELECTION_PHASES = ("2200", "0830", "0935", "1620")
SELECTION_MARKET_FOCUS = "HK_CONNECT"
SELECTION_MARKET_SCOPES = frozenset({"A_SHARE", "HK_CONNECT", "MIXED"})
SELECTION_SOURCE_SCOPE_INVALIDATION_SCHEMA_VERSION = (
    "v3_5.selection_source_scope_invalidation.v1"
)
SELECTION_SOURCE_SCOPE_INVALIDATION_TYPE = "SELECTION_SOURCE_SCOPE_INVALIDATION"
SELECTION_STATUSES = frozenset(
    {
        "EARLY_DRAFT_IMPORTED",
        "RESEARCH_SUPPLY_IMPORTED",
        "READY",
        "READY_WITH_DECLARED_GAPS",
        "NOT_MATERIALIZED",
        "CANNOT_CONFIRM",
    }
)
SELECTION_SNAPSHOT_STATUSES = frozenset(
    {"READY", "NOT_MATERIALIZED", "CANNOT_CONFIRM"}
)
RESEARCH_SUPPLY_TYPE = "RESEARCH_SUPPLY_FROZEN_ENVELOPE"
RESEARCH_SUPPLY_SCHEMA_VERSION = "BAIMAO_RESEARCH_SUPPLY_V1"
RESEARCH_SUPPLY_RECEIPT_SCHEMA_VERSION = "BAIMAO_RESEARCH_SUPPLY_RECEIPT_V1"
RESEARCH_SUPPLY_OWNER = "baimao-researcher"
RESEARCH_SUPPLY_PHASE = "INITIAL_RESEARCH_SUPPLY"
RESEARCH_SUPPLY_STATUS = "RESEARCH_SUPPLY_IMPORTED"
RESEARCH_SUPPLY_ACCEPTANCE = "RESEARCH_SUPPLY_ONLY"
MANAGER_DECISION_SCHEMA_VERSION = "v3_5.manager_research_decision.v1"
MANAGER_DECISION_PHASE = "2200"
MANAGER_DECISION_STATE = "INITIAL_RESEARCH_DELTA"
_MANAGER_DECISION_PROJECTION_FIELDS = {
    "schema_version",
    "phase",
    "decision_state",
    "source_date",
    "target_trade_date",
    "run_id",
    "generated_at",
    "cutoff_at",
    "role",
    "order",
    "reason",
}
_MANAGER_DECISION_PROJECTION_ROLES = frozenset({"CORE", "CONDITIONAL"})
_SUPPLY_ROUTE_FIELDS = {"R1", "R2", "R3", "R4", "R5", "R6"}
_SUPPLY_SAFETY_FIELDS = {
    "RESEARCH_ONLY",
    "WATCH_ONLY",
    "production_allowed",
    "buy_gate_updated",
    "orders_sent",
}
_SUPPLY_ENVELOPE_FIELDS = {
    "type",
    "schema_version",
    "owner",
    "phase",
    "run_id",
    "source_date",
    "target_trade_date",
    "generated_at",
    "coverage_started_at",
    "coverage_through",
    "cutoff_at",
    "frozen_payload",
    "frozen_payload_sha256",
}
_SUPPLY_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_path",
    "artifact_sha256",
    "frozen_payload_sha256",
    "run_id",
    "source_date",
    "target_trade_date",
    "generated_at",
    "cutoff_at",
    "coverage_started_at",
    "coverage_through",
    "safety",
}
_MANAGER_DECISION_FIELDS = {
    "schema_version",
    "phase",
    "decision_state",
    "source_date",
    "target_trade_date",
    "run_id",
    "generated_at",
    "cutoff_at",
    "supply_ref",
    "baseline_ref",
    "core",
    "conditional",
    "KEEP",
    "ADD",
    "REMOVE",
    "qualification_refs",
    "safety",
}
_SELECTION_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SELECTION_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SUPPLY_TICKER = re.compile(r"^\d{5}\.HK$")
_SELECTION_PRODUCT_FIELDS = {
    "schema_version",
    "contract_id",
    "workflow_name",
    "pass_signal",
    "source_date",
    "target_trade_date",
    "timezone",
    "cutoff_at",
    "generated_at",
    "run_id",
    "origin",
    "status",
    "acceptance",
    "research_candidates",
    "formal_shortlist",
    "snapshots",
    "intraday_observations",
    "outcomes",
    "counts",
    "route_status",
    "gemini_status",
    "formal_authority",
    "source_refs",
    "first_failed_layer",
    "cannot_confirm",
    "RESEARCH_ONLY",
    "production_allowed",
    "buy_gate_updated",
    "orders_sent",
}
_SELECTION_OPTIONAL_FIELDS = {"manager_decision_ref", "market_scope"}
_SELECTION_CANDIDATE_FIELDS = {
    "candidate_id",
    "event_stock_link_id",
    "market",
    "normalized_code",
    "entity_id",
    "event_id",
    "bucket",
    "catalyst",
    "counterevidence",
    "invalidation",
    "evidence_level",
    "financial_bridge",
    "consensus",
    "overnight_pending",
    "source_metadata",
    "source_status",
    "published_at",
    "published_at_aware",
    "source_time",
    "acceptance",
    "eligibility",
    "pit_status",
    "research_status",
    "recommendation_status",
    "route_status",
    "gemini_status",
    "source_refs",
}
_SELECTION_CANDIDATE_OPTIONAL_FIELDS = {"manager_decision"}
_SELECTION_SNAPSHOT_FIELDS = {
    "phase",
    "status",
    "run_id",
    "event_at",
    "artifact_sha256",
    "candidate_ids",
    "changes",
    "freeze_run_id",
    "freeze_snapshot_sha256",
    "snapshot_sha256",
}
_SELECTION_FORMAL_AUTHORITY_FIELDS = {
    "status",
    "target_trade_date",
    "pit_status",
    "selector_status",
    "research_evidence",
    "manager_decision",
    "source_sha256",
    "evidence_refs",
    "manager_decision_ref",
}
_SELECTION_COUNTS_FIELDS = {
    "research_candidates",
    "formal_shortlist",
    "snapshots",
    "intraday_observations",
    "outcomes",
}

_SELECTION_SOURCE_SCOPE_INVALIDATION_FIELDS = frozenset(
    {
        "schema_version",
        "type",
        "invalidation_id",
        "source_date",
        "target_trade_date",
        "prior_run_id",
        "prior_product_sha256",
        "expected_market_focus",
        "observed_source_scope",
        "evidence_refs",
        "reason",
        "generated_at",
        "safety",
    }
)
_SELECTION_SOURCE_SCOPE_EVIDENCE_FIELDS = frozenset(
    {
        "kind",
        "path",
        "raw_sha256",
        "json_pointer",
        "observed_source_scope",
    }
)


_SELECTION_MARKET_ALIASES = {
    "A": "A_SHARE",
    "A_SHARE": "A_SHARE",
    "ASHARE": "A_SHARE",
    "CN": "A_SHARE",
    "HK": "HK_CONNECT",
    "HK_CONNECT": "HK_CONNECT",
    "HKCONNECT": "HK_CONNECT",
    "MIXED": "MIXED",
}


def _selection_market_name(value: Any) -> str | None:
    """Normalize a candidate or requested market to the manager scope enum."""

    if not isinstance(value, str) or not value.strip():
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    return _SELECTION_MARKET_ALIASES.get(normalized)


def selection_market_scope(payload: Mapping[str, Any]) -> str | None:
    """Infer the market scope from the candidate identities in a product.

    The inferred scope deliberately comes from each candidate's normalized
    market rather than from a caller-provided focus.  This keeps an A-share
    or mixed-source product from passing merely because a consumer requested
    the HK_CONNECT view.
    """
    from contracts._research_day_product_parts.market_scope import _selection_market_scope_body as _v4_impl
    return _v4_impl(globals(), payload)


def validate_selection_market_scope(
    payload: Mapping[str, Any],
    *,
    market_focus: str | None = None,
) -> str | None:
    """Validate the declared/inferred market scope and optional HK focus."""
    from contracts._research_day_product_parts.market_scope import _validate_selection_market_scope_body as _v4_impl
    return _v4_impl(globals(), payload, market_focus=market_focus)


def selection_source_scope_invalidation_id(value: Mapping[str, Any]) -> str:
    """Return the content id for an append-only source-scope record."""
    from contracts._research_day_product_parts.market_scope import _selection_source_scope_invalidation_id_body as _v4_impl
    return _v4_impl(globals(), value)


def validate_selection_source_scope_invalidation(
    value: Mapping[str, Any],
    *,
    expected_target_trade_date: str | None = None,
) -> str:
    """Validate one independent, append-only upstream scope invalidation."""
    from contracts._research_day_product_parts.market_scope import _validate_selection_source_scope_invalidation_body as _v4_impl
    return _v4_impl(globals(), value, expected_target_trade_date=expected_target_trade_date)


def _selection_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError(f"selection {field} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"selection {field} must be a real date") from error
    return value


def _selection_sha(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not _SELECTION_SHA256.fullmatch(value.lower()):
        raise ValueError(f"invalid selection {field}")
    return value.lower()


def _selection_timestamp(value: Any, field: str, *, nullable: bool = False) -> str | None:
    from contracts._research_day_product_parts.primitives import __selection_timestamp_body as _v4_impl
    return _v4_impl(globals(), value, field, nullable=nullable)


def _selection_parsed_timestamp(value: Any, field: str) -> datetime:
    """Parse a required timestamp after enforcing an explicit timezone."""
    from contracts._research_day_product_parts.primitives import __selection_parsed_timestamp_body as _v4_impl
    return _v4_impl(globals(), value, field)


def _selection_canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _selection_strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"invalid selection {field}")
    if value != sorted(set(value)):
        raise ValueError(f"selection {field} must be sorted and unique")
    return value


def _validate_supply_safety(value: Any, label: str) -> None:
    from contracts._research_day_product_parts.supply_envelopes import __validate_supply_safety_body as _v4_impl
    return _v4_impl(globals(), value, label)


def _validate_supply_action_rows(
    value: Any,
    field: str,
    *,
    candidate_ids: set[str] | None = None,
    maximum: int | None = None,
) -> list[str]:
    from contracts._research_day_product_parts.supply_envelopes import __validate_supply_action_rows_body as _v4_impl
    return _v4_impl(globals(), value, field, candidate_ids=candidate_ids, maximum=maximum)


def _validate_supply_card(value: Any) -> str:
    from contracts._research_day_product_parts.supply_envelopes import __validate_supply_card_body as _v4_impl
    return _v4_impl(globals(), value)


def validate_research_supply_envelope(
    value: Mapping[str, Any],
    *,
    expected_source_date: str | None = None,
    expected_target_trade_date: str | None = None,
    expected_run_id: str | None = None,
) -> str:
    """Validate the new Baimao supply envelope without reading external files."""
    from contracts._research_day_product_parts.supply_envelopes import _validate_research_supply_envelope_body as _v4_impl
    return _v4_impl(globals(), value, expected_source_date=expected_source_date, expected_target_trade_date=expected_target_trade_date, expected_run_id=expected_run_id)


def validate_research_supply_receipt(
    value: Mapping[str, Any],
    *,
    envelope: Mapping[str, Any] | None = None,
    artifact_path: str | None = None,
    artifact_sha256: str | None = None,
) -> str:
    """Validate a supply receipt and, when supplied, bind it to its envelope."""
    from contracts._research_day_product_parts.supply_envelopes import _validate_research_supply_receipt_body as _v4_impl
    return _v4_impl(globals(), value, envelope=envelope, artifact_path=artifact_path, artifact_sha256=artifact_sha256)


def validate_manager_research_decision(
    value: Mapping[str, Any],
    *,
    candidate_ids: list[str] | None = None,
    supply_envelope: Mapping[str, Any] | None = None,
) -> str:
    """Validate the typed 22:00 manager delta used for a supply snapshot."""
    from contracts._research_day_product_parts.manager_decisions import _validate_manager_research_decision_body as _v4_impl
    return _v4_impl(globals(), value, candidate_ids=candidate_ids, supply_envelope=supply_envelope)


def _validate_selection_source_ref(value: Any, *, source_date: str) -> None:
    from contracts._research_day_product_parts.primitives import __validate_selection_source_ref_body as _v4_impl
    return _v4_impl(globals(), value, source_date=source_date)


def _validate_manager_decision_projection(
    value: Any,
    *,
    source_date: str,
    target_trade_date: str,
    cutoff_at: str,
    expected_run_id: str | None = None,
    expected_generated_at: str | None = None,
) -> None:
    """Validate one candidate's typed manager projection without source mutation."""
    from contracts._research_day_product_parts.manager_decisions import __validate_manager_decision_projection_body as _v4_impl
    return _v4_impl(globals(), value, source_date=source_date, target_trade_date=target_trade_date, cutoff_at=cutoff_at, expected_run_id=expected_run_id, expected_generated_at=expected_generated_at)


def validate_manager_decision_projection(
    value: Any,
    *,
    source_date: str,
    target_trade_date: str,
    cutoff_at: str,
    expected_run_id: str | None = None,
    expected_generated_at: str | None = None,
) -> None:
    """Public validation entry point for Store/API candidate projections."""
    from contracts._research_day_product_parts.manager_decisions import _validate_manager_decision_projection_body as _v4_impl
    return _v4_impl(globals(), value, source_date=source_date, target_trade_date=target_trade_date, cutoff_at=cutoff_at, expected_run_id=expected_run_id, expected_generated_at=expected_generated_at)


def _validate_selection_candidate(
    value: Any,
    *,
    source_date: str,
    cutoff_at: str,
) -> None:
    from contracts._research_day_product_parts.selection_candidates import __validate_selection_candidate_body as _v4_impl
    return _v4_impl(globals(), value, source_date=source_date, cutoff_at=cutoff_at)


def _validate_selection_snapshot(value: Any, *, phase: str, target_trade_date: str) -> None:
    from contracts._research_day_product_parts.selection_candidates import __validate_selection_snapshot_body as _v4_impl
    return _v4_impl(globals(), value, phase=phase, target_trade_date=target_trade_date)


def _selection_apply_changes(
    changes: Any,
    *,
    current_ids: set[str],
    candidate_ids: set[str],
    phase: str,
) -> set[str]:
    """Validate deterministic KEEP/ADD/REMOVE semantics and return the set."""
    from contracts._research_day_product_parts.selection_candidates import __selection_apply_changes_body as _v4_impl
    return _v4_impl(globals(), changes, current_ids=current_ids, candidate_ids=candidate_ids, phase=phase)


def _validate_selection_formal_authority(value: Any, *, target_trade_date: str) -> None:
    from contracts._research_day_product_parts.formal_authority import __validate_selection_formal_authority_body as _v4_impl
    return _v4_impl(globals(), value, target_trade_date=target_trade_date)


def _validate_selection_formal_refs(
    authority: Mapping[str, Any],
    *,
    source_date: str,
    target_trade_date: str,
    candidate_ids: list[str],
) -> None:
    """Validate the immutable, typed references behind a formal shortlist."""
    from contracts._research_day_product_parts.formal_authority import __validate_selection_formal_refs_body as _v4_impl
    return _v4_impl(globals(), authority, source_date=source_date, target_trade_date=target_trade_date, candidate_ids=candidate_ids)


def _validate_selection_proof_bindings(
    value: Mapping[str, Any],
    *,
    candidate_ids: list[str],
    source_date: str,
    label: str,
) -> None:
    from contracts._research_day_product_parts.formal_authority import __validate_selection_proof_bindings_body as _v4_impl
    return _v4_impl(globals(), value, candidate_ids=candidate_ids, source_date=source_date, label=label)
def validate_selection_research_product(
    payload: Mapping[str, Any],
    *,
    market_focus: str | None = None,
) -> str:
    """Validate the selection ledger without reading files or runtime state."""
    from contracts._research_day_product_parts.selection_product import _validate_selection_research_product_body as _v4_impl
    return _v4_impl(globals(), payload, market_focus=market_focus)


__all__ = [
    "CONTRACT_ID",
    "DATE_MODE",
    "EXPECTED_RESEARCH_SLOTS",
    "PASS_SIGNAL",
    "PRODUCT_SCHEMA_VERSION",
    "SAFETY_FLAGS",
    "TIMEZONE",
    "WORKFLOW_NAME",
    "MANAGER_DECISION_PHASE",
    "MANAGER_DECISION_SCHEMA_VERSION",
    "MANAGER_DECISION_STATE",
    "RESEARCH_SUPPLY_ACCEPTANCE",
    "RESEARCH_SUPPLY_OWNER",
    "RESEARCH_SUPPLY_PHASE",
    "RESEARCH_SUPPLY_RECEIPT_SCHEMA_VERSION",
    "RESEARCH_SUPPLY_SCHEMA_VERSION",
    "RESEARCH_SUPPLY_STATUS",
    "RESEARCH_SUPPLY_TYPE",
    "SELECTION_CONTRACT_ID",
    "SELECTION_MARKET_FOCUS",
    "SELECTION_MARKET_SCOPES",
    "SELECTION_SOURCE_SCOPE_INVALIDATION_SCHEMA_VERSION",
    "SELECTION_SOURCE_SCOPE_INVALIDATION_TYPE",
    "SELECTION_ORIGINS",
    "SELECTION_PASS_SIGNAL",
    "SELECTION_PHASES",
    "SELECTION_SCHEMA_VERSION",
    "SELECTION_WORKFLOW_NAME",
    "validate_manager_decision_projection",
    "validate_manager_research_decision",
    "validate_research_supply_envelope",
    "validate_research_supply_receipt",
    "selection_market_scope",
    "selection_source_scope_invalidation_id",
    "validate_selection_market_scope",
    "validate_selection_source_scope_invalidation",
    "validate_selection_research_product",
    "validate_research_day_product",
]
