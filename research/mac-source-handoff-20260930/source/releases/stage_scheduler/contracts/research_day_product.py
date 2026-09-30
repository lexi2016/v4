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

    url = unicodedata.normalize(
        "NFKC", str(row.get("url") or row.get("source_url") or "").strip()
    )
    stock_code = unicodedata.normalize(
        "NFKC", str(row.get("stock_code") or row.get("code") or "").strip()
    ).upper()
    if not url or not stock_code:
        return None
    return f"{url}|{stock_code}"


def _validate_slot_matrix(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) != len(EXPECTED_RESEARCH_SLOTS):
        raise ValueError("research day slot matrix must cover all expected slots")
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError("invalid research day slot matrix row")
        if set(row) != {
            "slot",
            "status",
            "raw_rows",
            "exact_rows",
            "excluded_rows",
            "artifact_path",
            "artifact_sha256",
            "receipt_path",
            "receipt_sha256",
            "source_input_sha256",
        }:
            raise ValueError("invalid research day slot matrix fields")
        slot = row.get("slot")
        if slot not in EXPECTED_RESEARCH_SLOTS or slot in seen:
            raise ValueError("research day slot matrix identity mismatch")
        seen.add(str(slot))
        if row.get("status") != "READY":
            raise ValueError("research day slot matrix has non-ready slot")
        for field in ("raw_rows", "exact_rows", "excluded_rows"):
            if type(row.get(field)) is not int or row[field] < 0:
                raise ValueError(f"invalid research day slot {field}")
        for field in (
            "artifact_sha256",
            "receipt_sha256",
            "source_input_sha256",
        ):
            _sha(row.get(field), field)
        if not isinstance(row.get("artifact_path"), str) or not row["artifact_path"]:
            raise ValueError("invalid research day artifact path")
        if not isinstance(row.get("receipt_path"), str) or not row["receipt_path"]:
            raise ValueError("invalid research day receipt path")
    if tuple(row["slot"] for row in value) != EXPECTED_RESEARCH_SLOTS:
        raise ValueError("research day slot matrix must be chronological")
    return value


def _validate_not_materialized_product(payload: Mapping[str, Any]) -> None:
    """Validate a typed base-envelope gap without accepting stale rows."""

    expected = list(EXPECTED_RESEARCH_SLOTS)
    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping) or set(coverage) != {
        "expected_slots",
        "ready_slots",
        "missing_slots",
        "complete",
        "slot_matrix",
    }:
        raise ValueError("invalid research day NOT_MATERIALIZED coverage")
    if (
        coverage.get("expected_slots") != len(expected)
        or coverage.get("ready_slots") != 0
        or coverage.get("missing_slots") != expected
        or coverage.get("complete") is not False
        or coverage.get("slot_matrix") != []
    ):
        raise ValueError("research day NOT_MATERIALIZED coverage must list all missing slots")
    counts = payload.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != {
        "raw_rows",
        "evidence_rows",
        "excluded_rows",
        "mention_pairs",
        "urls",
        "stock_rollups",
        "high_priority",
        "duplicate_pairs",
    } or any(type(value) is not int or value != 0 for value in counts.values()):
        raise ValueError("research day NOT_MATERIALIZED counts must be zero")
    exclusions = payload.get("exclusions")
    if not isinstance(exclusions, Mapping) or set(exclusions) != {
        "date_mismatch",
        "pit_violation",
        "invalid_row",
    } or any(type(value) is not int or value != 0 for value in exclusions.values()):
        raise ValueError("research day NOT_MATERIALIZED exclusions must be zero")
    if payload.get("excluded_by_date") != {}:
        raise ValueError("research day NOT_MATERIALIZED excluded_by_date must be empty")
    for field in ("evidence_rows", "mention_pairs", "stock_rollups", "high_priority"):
        if payload.get(field) != []:
            raise ValueError(f"research day NOT_MATERIALIZED {field} must be empty")
    if payload.get("slot_matrix") != [] or payload.get("lineage") is not None:
        raise ValueError("research day NOT_MATERIALIZED cannot carry product rows or lineage")
    high_status = payload.get("high_priority_status")
    if not isinstance(high_status, Mapping) or set(high_status) != {
        "status",
        "rule_id",
        "registry",
        "cannot_confirm",
    } or high_status.get("status") != "CANNOT_CONFIRM" or high_status.get("registry") != "MISSING":
        raise ValueError("research day NOT_MATERIALIZED high priority must be CANNOT_CONFIRM")
    cannot_confirm = payload.get("cannot_confirm")
    if not isinstance(cannot_confirm, list) or not cannot_confirm:
        raise ValueError("research day NOT_MATERIALIZED requires a typed gap")
    _sorted_strings(cannot_confirm, "cannot_confirm")

    excluded_by_date = payload.get("excluded_by_date")
    if not isinstance(excluded_by_date, Mapping):
        raise ValueError("invalid research day excluded_by_date")
    excluded_dates = list(excluded_by_date)
    if excluded_dates != sorted(excluded_dates):
        raise ValueError("research day excluded_by_date must be chronological")
    for date, count in excluded_by_date.items():
        _date(date)
        if type(count) is not int or count <= 0:
            raise ValueError("invalid research day excluded_by_date count")

    jyg_coverage = payload.get("jyg_coverage")
    if not isinstance(jyg_coverage, Mapping) or set(jyg_coverage) != {
        "status",
        "articles",
        "expected_articles",
        "stock_mentions",
        "registry",
        "gap",
    }:
        raise ValueError("invalid research day jyg coverage")
    if jyg_coverage.get("status") not in {"VALIDATED", "CANNOT_CONFIRM"}:
        raise ValueError("invalid research day jyg coverage status")
    if jyg_coverage.get("registry") not in {"VALIDATED", "MISSING"}:
        raise ValueError("invalid research day jyg coverage registry")
    for field in ("articles", "expected_articles", "stock_mentions"):
        value = jyg_coverage.get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"invalid research day jyg coverage {field}")
    if jyg_coverage.get("status") == "CANNOT_CONFIRM":
        if jyg_coverage.get("registry") != "MISSING" or not jyg_coverage.get("gap"):
            raise ValueError("research day jyg coverage gap is incomplete")
    elif jyg_coverage.get("registry") != "VALIDATED" or jyg_coverage.get("gap") is not None:
        raise ValueError("research day jyg coverage validation mismatch")


def validate_research_day_product(payload: Mapping[str, Any]) -> str:
    """Validate the complete exact-date day-product envelope."""

    if not isinstance(payload, Mapping):
        raise ValueError("invalid research day product fields")
    if set(payload) != _PRODUCT_FIELDS:
        missing = sorted(_PRODUCT_FIELDS - set(payload))
        extra = sorted(set(payload) - _PRODUCT_FIELDS)
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if extra:
            detail.append(f"extra={extra}")
        raise ValueError(f"invalid research day product fields {' '.join(detail)}")
    archive_date = _date(payload.get("archive_date"))
    if payload.get("schema_version") != PRODUCT_SCHEMA_VERSION:
        raise ValueError("invalid research day product schema")
    if payload.get("contract_id") != CONTRACT_ID:
        raise ValueError("invalid research day product contract")
    if payload.get("workflow_name") != WORKFLOW_NAME:
        raise ValueError("invalid research day product workflow")
    if payload.get("pass_signal") != PASS_SIGNAL:
        raise ValueError("invalid research day product pass signal")
    if payload.get("timezone") != TIMEZONE or payload.get("date_mode") != DATE_MODE:
        raise ValueError("research day product must be exact-date Asia/Shanghai")
    if payload.get("write_policy") != "read_only":
        raise ValueError("unsafe research day write policy")
    if payload.get("recommendation_status") != "RESEARCH_ONLY":
        raise ValueError("unsafe research day recommendation status")
    for key, expected in SAFETY_FLAGS.items():
        if payload.get(key) is not expected:
            raise ValueError(f"unsafe research day safety boundary: {key}")
    expected_slots = payload.get("expected_slots")
    if tuple(expected_slots or ()) != EXPECTED_RESEARCH_SLOTS:
        raise ValueError("research day expected slots mismatch")
    status = payload.get("status")
    if status not in {"READY", "READY_WITH_DECLARED_GAPS", "NOT_MATERIALIZED"}:
        raise ValueError("invalid research day status")
    if type(payload.get("authoritative")) is not bool:
        raise ValueError("invalid research day authoritative flag")

    if status == "NOT_MATERIALIZED":
        _validate_not_materialized_product(payload)
        return archive_date

    slot_matrix = _validate_slot_matrix(payload.get("slot_matrix"))
    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping) or set(coverage) != {
        "expected_slots",
        "ready_slots",
        "missing_slots",
        "complete",
        "slot_matrix",
    }:
        raise ValueError("invalid research day coverage")
    if coverage["expected_slots"] != len(EXPECTED_RESEARCH_SLOTS):
        raise ValueError("research day expected slot count mismatch")
    if coverage["ready_slots"] != len(slot_matrix):
        raise ValueError("research day ready slot count mismatch")
    if coverage["missing_slots"] != [] or coverage["complete"] is not True:
        raise ValueError("research day product requires a complete slot matrix")
    if coverage["slot_matrix"] != slot_matrix:
        raise ValueError("research day coverage slot matrix mismatch")

    counts = payload.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != {
        "raw_rows",
        "evidence_rows",
        "excluded_rows",
        "mention_pairs",
        "urls",
        "stock_rollups",
        "high_priority",
        "duplicate_pairs",
    }:
        raise ValueError("invalid research day counts")
    for field in counts:
        if type(counts[field]) is not int or counts[field] < 0:
            raise ValueError(f"invalid research day count: {field}")
    if counts["raw_rows"] != sum(int(row["raw_rows"]) for row in slot_matrix):
        raise ValueError("research day raw row count mismatch")
    if counts["evidence_rows"] != len(payload["evidence_rows"]):
        raise ValueError("research day evidence row count mismatch")
    if counts["excluded_rows"] != sum(int(row["excluded_rows"]) for row in slot_matrix):
        raise ValueError("research day excluded row count mismatch")
    if counts["mention_pairs"] != len(payload["mention_pairs"]):
        raise ValueError("research day mention pair count mismatch")
    if counts["stock_rollups"] != len(payload["stock_rollups"]):
        raise ValueError("research day stock rollup count mismatch")
    if counts["high_priority"] != len(payload["high_priority"]):
        raise ValueError("research day high priority count mismatch")

    exclusions = payload.get("exclusions")
    if not isinstance(exclusions, Mapping) or set(exclusions) != {
        "date_mismatch",
        "pit_violation",
        "invalid_row",
    }:
        raise ValueError("invalid research day exclusions")
    if any(type(value) is not int or value < 0 for value in exclusions.values()):
        raise ValueError("invalid research day exclusion count")
    if sum(exclusions.values()) != counts["excluded_rows"]:
        raise ValueError("research day exclusion count mismatch")

    excluded_by_date = payload.get("excluded_by_date")
    if not isinstance(excluded_by_date, Mapping):
        raise ValueError("invalid research day excluded_by_date")
    excluded_dates = list(excluded_by_date)
    if excluded_dates != sorted(excluded_dates):
        raise ValueError("research day excluded_by_date must be chronological")
    for date, count in excluded_by_date.items():
        _date(date)
        if type(count) is not int or count <= 0:
            raise ValueError("invalid research day excluded_by_date count")
    if exclusions["date_mismatch"] != sum(excluded_by_date.values()):
        raise ValueError("research day excluded_by_date mismatch")

    evidence_rows = payload.get("evidence_rows")
    if not isinstance(evidence_rows, list):
        raise ValueError("invalid research day evidence rows")
    identity_gap = False
    for row in evidence_rows:
        if not isinstance(row, Mapping):
            raise ValueError("invalid research day evidence row")
        if row.get("archive_date") != archive_date:
            raise ValueError("research day evidence date mismatch")
        if row.get("slot") not in EXPECTED_RESEARCH_SLOTS:
            raise ValueError("research day evidence slot mismatch")
        if not isinstance(row.get("source_row_ref"), str) or not row["source_row_ref"]:
            raise ValueError("research day evidence source ref missing")
        if _pair_identity(row) is None:
            identity_gap = True
            if row.get("identity_status") != "URL_REQUIRED/CANNOT_CONFIRM":
                raise ValueError("research day evidence identity is unverified")
        elif row.get("identity_status") != "READY":
            raise ValueError("research day evidence identity status mismatch")
    if identity_gap:
        if status != "READY_WITH_DECLARED_GAPS" or payload.get("authoritative") is not False:
            raise ValueError("research day product cannot authorize an unverified identity")
        if "URL_REQUIRED/CANNOT_CONFIRM" not in payload.get("cannot_confirm", []):
            raise ValueError("research day product identity gap is undeclared")

    mention_pairs = payload.get("mention_pairs")
    if not isinstance(mention_pairs, list):
        raise ValueError("invalid research day mention pairs")
    pair_keys: set[str] = set()
    for row in mention_pairs:
        if not isinstance(row, Mapping):
            raise ValueError("invalid research day mention pair")
        pair_key = row.get("pair_key")
        if not isinstance(pair_key, str) or not pair_key or pair_key in pair_keys:
            raise ValueError("research day mention pair identity mismatch")
        pair_keys.add(pair_key)
        if type(row.get("occurrence_count")) is not int or row["occurrence_count"] < 1:
            raise ValueError("invalid research day occurrence count")
        if type(row.get("variant_count")) is not int or row["variant_count"] < 1:
            raise ValueError("invalid research day variant count")
        for field in ("source_slots", "article_ids", "dedupe_keys", "source_refs"):
            if not isinstance(row.get(field), list):
                raise ValueError(f"invalid research day pair {field}")
    if counts["duplicate_pairs"] != sum(
        1 for row in mention_pairs if row["occurrence_count"] > 1
    ):
        raise ValueError("research day duplicate pair count mismatch")

    stock_rollups = payload.get("stock_rollups")
    if not isinstance(stock_rollups, list):
        raise ValueError("invalid research day stock rollups")
    stock_codes: set[str] = set()
    for row in stock_rollups:
        if not isinstance(row, Mapping):
            raise ValueError("invalid research day stock rollup")
        code = row.get("stock_code")
        if not isinstance(code, str) or not code or code in stock_codes:
            raise ValueError("research day stock rollup identity mismatch")
        stock_codes.add(code)

    high_priority = payload.get("high_priority")
    if not isinstance(high_priority, list):
        raise ValueError("invalid research day high priority")
    high_status = payload.get("high_priority_status")
    if not isinstance(high_status, Mapping) or set(high_status) != {
        "status",
        "rule_id",
        "registry",
        "cannot_confirm",
    }:
        raise ValueError("invalid research day high priority status")
    if high_status["registry"] == "MISSING" and high_priority:
        raise ValueError("registry-missing high priority must be empty")
    if high_status["registry"] == "MISSING" and high_status["status"] != "CANNOT_CONFIRM":
        raise ValueError("registry-missing high priority must be CANNOT_CONFIRM")
    _sorted_strings(payload.get("cannot_confirm"), "cannot_confirm")

    jyg_coverage = payload.get("jyg_coverage")
    if not isinstance(jyg_coverage, Mapping) or set(jyg_coverage) != {
        "status",
        "articles",
        "expected_articles",
        "stock_mentions",
        "registry",
        "gap",
    }:
        raise ValueError("invalid research day jyg coverage")
    if jyg_coverage.get("status") not in {"VALIDATED", "CANNOT_CONFIRM"}:
        raise ValueError("invalid research day jyg coverage status")
    if jyg_coverage.get("registry") not in {"VALIDATED", "MISSING"}:
        raise ValueError("invalid research day jyg coverage registry")
    for field in ("articles", "expected_articles", "stock_mentions"):
        value = jyg_coverage.get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"invalid research day jyg coverage {field}")
    if jyg_coverage.get("status") == "CANNOT_CONFIRM":
        if jyg_coverage.get("registry") != "MISSING" or not jyg_coverage.get("gap"):
            raise ValueError("research day jyg coverage gap is incomplete")
    elif jyg_coverage.get("registry") != "VALIDATED" or jyg_coverage.get("gap") is not None:
        raise ValueError("research day jyg coverage validation mismatch")

    lineage = payload.get("lineage")
    if not isinstance(lineage, Mapping) or set(lineage) != {
        "source_refs",
        "artifact_sha256",
        "manifest_sha256",
        "receipt_sha256",
        "current_sha256",
        "transformer_identity_sha256",
    }:
        raise ValueError("invalid research day lineage")
    if not isinstance(lineage["source_refs"], Mapping):
        raise ValueError("invalid research day source refs")
    source_refs = lineage["source_refs"]
    if set(source_refs) != set(EXPECTED_RESEARCH_SLOTS):
        raise ValueError("research day source refs must cover every exact slot")
    matrix_by_slot = {str(row["slot"]): row for row in slot_matrix}
    for slot in EXPECTED_RESEARCH_SLOTS:
        ref = source_refs.get(slot)
        if not isinstance(ref, Mapping) or set(ref) != {
            "slot",
            "artifact_path",
            "artifact_sha256",
            "receipt_path",
            "receipt_sha256",
            "source_input_sha256",
        }:
            raise ValueError(f"invalid research day source ref: {slot}")
        if ref["slot"] != slot:
            raise ValueError(f"research day source ref slot mismatch: {slot}")
        if ref["artifact_path"] != f"research/hourly/live/{archive_date}/{slot}.json":
            raise ValueError(f"research day source artifact date mismatch: {slot}")
        if ref["receipt_path"] != f"receipts/research/hourly/live/{archive_date}/{slot}.json":
            raise ValueError(f"research day source receipt date mismatch: {slot}")
        for field in ("artifact_sha256", "receipt_sha256", "source_input_sha256"):
            _sha(ref[field], f"source_refs.{slot}.{field}")
        matrix_row = matrix_by_slot[slot]
        for field in ("artifact_path", "artifact_sha256", "receipt_path", "receipt_sha256", "source_input_sha256"):
            if ref[field] != matrix_row[field]:
                raise ValueError(f"research day source ref mismatch: {slot}.{field}")
    for field in (
        "artifact_sha256",
        "manifest_sha256",
        "receipt_sha256",
        "transformer_identity_sha256",
    ):
        _sha(lineage[field], field)
    current_sha = lineage["current_sha256"]
    if current_sha is not None:
        _sha(current_sha, "current_sha256")
    return archive_date


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

    candidates = payload.get("research_candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    scopes: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("selection market scope candidate is invalid")
        market = _selection_market_name(candidate.get("market"))
        if market is None:
            entity_id = candidate.get("entity_id")
            if isinstance(entity_id, str) and "." in entity_id:
                market = _selection_market_name(entity_id.rsplit(".", 1)[1])
        if market is None:
            raise ValueError("selection market scope is unknown")
        scopes.add(market)
    if len(scopes) > 1:
        return "MIXED"
    return next(iter(scopes))


def validate_selection_market_scope(
    payload: Mapping[str, Any],
    *,
    market_focus: str | None = None,
) -> str | None:
    """Validate the declared/inferred market scope and optional HK focus."""

    inferred = selection_market_scope(payload)
    declared_value = payload.get("market_scope")
    declared: str | None = None
    if declared_value is not None:
        if not isinstance(declared_value, str) or declared_value not in SELECTION_MARKET_SCOPES:
            raise ValueError("selection market_scope declaration is invalid")
        declared = declared_value
        if inferred is not None and declared != inferred:
            raise ValueError("selection market_scope declaration does not match candidates")
    effective = declared or inferred
    if effective == "MIXED" and declared is None and payload.get("status") == "READY":
        raise ValueError("selection market scope must be declared for mixed sources")
    if payload.get("status") == "READY" and effective == "A_SHARE":
        raise ValueError(f"selection market scope {effective} cannot be READY")
    if market_focus is not None:
        requested = _selection_market_name(market_focus)
        if requested != SELECTION_MARKET_FOCUS:
            raise ValueError("selection market focus is forced to HK_CONNECT")
        if effective is not None and effective != SELECTION_MARKET_FOCUS:
            raise ValueError(
                f"selection market scope {effective} is incompatible with market focus HK_CONNECT"
            )
    return effective


def selection_source_scope_invalidation_id(value: Mapping[str, Any]) -> str:
    """Return the content id for an append-only source-scope record."""

    if not isinstance(value, Mapping):
        raise ValueError("selection source-scope invalidation is not an object")
    body = {
        key: item for key, item in value.items() if key != "invalidation_id"
    }
    return hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def validate_selection_source_scope_invalidation(
    value: Mapping[str, Any],
    *,
    expected_target_trade_date: str | None = None,
) -> str:
    """Validate one independent, append-only upstream scope invalidation."""

    if not isinstance(value, Mapping) or set(value) != _SELECTION_SOURCE_SCOPE_INVALIDATION_FIELDS:
        raise ValueError("invalid selection source-scope invalidation fields")
    if value.get("schema_version") != SELECTION_SOURCE_SCOPE_INVALIDATION_SCHEMA_VERSION:
        raise ValueError("invalid selection source-scope invalidation schema")
    if value.get("type") != SELECTION_SOURCE_SCOPE_INVALIDATION_TYPE:
        raise ValueError("invalid selection source-scope invalidation type")
    invalidation_id = value.get("invalidation_id")
    if not isinstance(invalidation_id, str) or not _SELECTION_SHA256.fullmatch(invalidation_id.lower()):
        raise ValueError("invalid selection source-scope invalidation id")
    if selection_source_scope_invalidation_id(value) != invalidation_id.lower():
        raise ValueError("selection source-scope invalidation id mismatch")
    source_date = _selection_date(value.get("source_date"), "source_date")
    target_trade_date = _selection_date(
        value.get("target_trade_date"), "target_trade_date"
    )
    if (
        expected_target_trade_date is not None
        and target_trade_date != expected_target_trade_date
    ):
        raise ValueError("selection source-scope invalidation target date mismatch")
    prior_run_id = value.get("prior_run_id")
    if not isinstance(prior_run_id, str) or not _SELECTION_RUN_ID.fullmatch(prior_run_id):
        raise ValueError("selection source-scope prior run id is invalid")
    _selection_sha(value.get("prior_product_sha256"), "prior product SHA")
    expected_focus = value.get("expected_market_focus")
    if expected_focus != SELECTION_MARKET_FOCUS:
        raise ValueError("selection source-scope expected market focus must be HK_CONNECT")
    observed_scope = value.get("observed_source_scope")
    if observed_scope not in SELECTION_MARKET_SCOPES:
        raise ValueError("selection source-scope observed scope is invalid")
    if observed_scope == expected_focus:
        raise ValueError("selection source-scope invalidation has no scope mismatch")
    evidence_refs = value.get("evidence_refs")
    if not isinstance(evidence_refs, list) or len(evidence_refs) < 2:
        raise ValueError("selection source-scope evidence refs are incomplete")
    evidence_kinds: set[str] = set()
    for ref in evidence_refs:
        if not isinstance(ref, Mapping) or set(ref) != _SELECTION_SOURCE_SCOPE_EVIDENCE_FIELDS:
            raise ValueError("invalid selection source-scope evidence ref")
        kind = ref.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("selection source-scope evidence kind is invalid")
        evidence_kinds.add(kind)
        if not isinstance(ref.get("path"), str) or not ref["path"]:
            raise ValueError("selection source-scope evidence path is missing")
        _selection_sha(ref.get("raw_sha256"), "source-scope evidence SHA")
        pointer = ref.get("json_pointer")
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("selection source-scope evidence JSON pointer is invalid")
        if ref.get("observed_source_scope") != observed_scope:
            raise ValueError("selection source-scope evidence scope mismatch")
    if not {"DISPATCHER", "HOURLY"}.issubset(evidence_kinds):
        raise ValueError("selection source-scope evidence lacks dispatcher/hourly refs")
    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        raise ValueError("selection source-scope invalidation reason is invalid")
    _selection_timestamp(value.get("generated_at"), "source-scope invalidation generated_at")
    safety = value.get("safety")
    if not isinstance(safety, Mapping) or set(safety) != set(SAFETY_FLAGS):
        raise ValueError("invalid selection source-scope invalidation safety")
    for field, expected in SAFETY_FLAGS.items():
        if safety.get(field) is not expected:
            raise ValueError(f"unsafe selection source-scope invalidation boundary: {field}")
    return target_trade_date


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
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid selection {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid selection {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"selection {field} must include timezone")
    return value


def _selection_parsed_timestamp(value: Any, field: str) -> datetime:
    """Parse a required timestamp after enforcing an explicit timezone."""

    text = _selection_timestamp(value, field)
    assert text is not None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid selection {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"selection {field} must include timezone")
    return parsed


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
    if not isinstance(value, Mapping) or set(value) != _SUPPLY_SAFETY_FIELDS:
        raise ValueError(f"invalid {label} safety fields")
    expected = {
        "RESEARCH_ONLY": True,
        "WATCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    for field, required in expected.items():
        if value.get(field) is not required:
            raise ValueError(f"unsafe {label} safety boundary: {field}")


def _validate_supply_action_rows(
    value: Any,
    field: str,
    *,
    candidate_ids: set[str] | None = None,
    maximum: int | None = None,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"invalid supply {field}")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"supply {field} exceeds maximum size")
    selected: list[str] = []
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {"candidate_id", "reason"}:
            raise ValueError(f"invalid supply {field} row")
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError(f"invalid supply {field} candidate")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError(f"invalid supply {field} reason")
        if candidate_ids is not None and candidate_id not in candidate_ids:
            raise ValueError(f"supply {field} candidate is unknown")
        if candidate_id in selected:
            raise ValueError(f"duplicate supply {field} candidate")
        selected.append(candidate_id)
    return selected


def _validate_supply_card(value: Any) -> str:
    required = {
        "event_id",
        "ticker",
        "entity",
        "market",
        "candidate_status",
        "bucket",
        "published_at",
        "event_at",
        "source",
        "catalyst",
        "financial_bridge",
        "counterevidence",
        "invalidation",
        "evidence_level",
        "consensus",
        "overnight_pending",
        "origin_routes",
        "content_source_receipts",
        "official_source",
        "independent_evidence_dimensions",
        "sector_watch_basket",
        "eligibility_status",
        "price_confirmation_plan_0925_0935",
        "promotion_missing_fields",
    }
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise ValueError("invalid research supply event card fields")
    ticker = value.get("ticker")
    if not isinstance(ticker, str) or not _SUPPLY_TICKER.fullmatch(ticker):
        raise ValueError("research supply ticker must be a five-digit HK code")
    if value.get("market") != "HK":
        raise ValueError("research supply event card market must be HK")
    if not isinstance(value.get("event_id"), str) or not value["event_id"].strip():
        raise ValueError("research supply event card event_id is invalid")
    # The supply envelope is an evidence ledger, not a completed research
    # card.  Unknown facts are represented by null or by a structured typed
    # value and must remain available for later verification.  Only identity
    # and container shape are required here; downstream promotion gates do
    # the stricter evidence/PIT checks.
    flexible_fields = (
        "entity",
        "candidate_status",
        "bucket",
        "published_at",
        "event_at",
        "source",
        "catalyst",
        "financial_bridge",
        "counterevidence",
        "invalidation",
        "evidence_level",
        "consensus",
        "overnight_pending",
        "independent_evidence_dimensions",
        "sector_watch_basket",
        "eligibility_status",
        "price_confirmation_plan_0925_0935",
    )
    if any(
        not isinstance(value.get(field), (str, Mapping, list, type(None), bool, int, float))
        for field in flexible_fields
    ):
        raise ValueError("research supply event card contains an invalid field value")
    if value.get("source") is None:
        # A missing source is still a typed, reviewable supply card; the
        # official_source identity container below records the gap.
        pass
    elif not isinstance(value.get("source"), (str, Mapping, list)):
        raise ValueError("research supply event card source is invalid")
    routes = value.get("origin_routes")
    if not isinstance(routes, list) or any(
        not isinstance(route, (str, Mapping)) for route in routes
    ):
        raise ValueError("research supply event card origin_routes must be a list")
    if not isinstance(value.get("content_source_receipts"), list):
        raise ValueError("research supply event card content receipts are invalid")
    official = value.get("official_source")
    if not isinstance(official, Mapping):
        raise ValueError("research supply official source is incomplete")
    identity_status = official.get("identity_status")
    if identity_status is not None and (
        not isinstance(identity_status, str) or not identity_status.strip()
    ):
        raise ValueError("research supply official source identity status is invalid")
    for field in ("url", "publisher", "published_at", "event_at"):
        if field in official and not isinstance(
            official.get(field), (str, Mapping, list, type(None), bool, int, float)
        ):
            raise ValueError(f"research supply official source {field} is invalid")
    eligibility = value.get("eligibility_status")
    if isinstance(eligibility, str):
        if eligibility.strip() not in {
            "ELIGIBILITY_CANNOT_CONFIRM",
            "ELIGIBLE",
        }:
            raise ValueError("research supply eligibility status is invalid")
    elif isinstance(eligibility, Mapping):
        if (
            not isinstance(eligibility.get("status"), str)
            or not eligibility["status"].strip()
        ):
            raise ValueError("research supply eligibility status is invalid")
    elif eligibility is not None:
        raise ValueError("research supply eligibility status is invalid")
    if not isinstance(value.get("promotion_missing_fields"), list) or any(
        not isinstance(item, str) for item in value["promotion_missing_fields"]
    ):
        raise ValueError("research supply promotion gaps are invalid")
    return ticker


def validate_research_supply_envelope(
    value: Mapping[str, Any],
    *,
    expected_source_date: str | None = None,
    expected_target_trade_date: str | None = None,
    expected_run_id: str | None = None,
) -> str:
    """Validate the new Baimao supply envelope without reading external files."""

    if not isinstance(value, Mapping) or not _SUPPLY_ENVELOPE_FIELDS.issubset(value):
        raise ValueError("invalid research supply envelope fields")
    extra = set(value) - _SUPPLY_ENVELOPE_FIELDS - {"safety"}
    if extra:
        raise ValueError(f"invalid research supply envelope fields extra={sorted(extra)}")
    if value.get("type") != RESEARCH_SUPPLY_TYPE:
        raise ValueError("invalid research supply envelope type")
    if value.get("schema_version") != RESEARCH_SUPPLY_SCHEMA_VERSION:
        raise ValueError("invalid research supply envelope schema")
    if value.get("owner") != RESEARCH_SUPPLY_OWNER:
        raise ValueError("invalid research supply envelope owner")
    if value.get("phase") != RESEARCH_SUPPLY_PHASE:
        raise ValueError("invalid research supply envelope phase")
    source_date = _selection_date(value.get("source_date"), "supply source_date")
    target_date = _selection_date(value.get("target_trade_date"), "supply target_trade_date")
    if expected_source_date is not None and source_date != expected_source_date:
        raise ValueError("research supply source date mismatch")
    if expected_target_trade_date is not None and target_date != expected_target_trade_date:
        raise ValueError("research supply target date mismatch")
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or not _SELECTION_RUN_ID.fullmatch(run_id):
        raise ValueError("invalid research supply run_id")
    if expected_run_id is not None and run_id != expected_run_id:
        raise ValueError("research supply run_id mismatch")
    generated = _selection_parsed_timestamp(value.get("generated_at"), "supply generated_at")
    coverage_started = _selection_parsed_timestamp(
        value.get("coverage_started_at"), "supply coverage_started_at"
    )
    coverage_through = _selection_parsed_timestamp(
        value.get("coverage_through"), "supply coverage_through"
    )
    cutoff = _selection_parsed_timestamp(value.get("cutoff_at"), "supply cutoff_at")
    if coverage_started > coverage_through or coverage_through > generated:
        raise ValueError("research supply coverage interval is invalid")
    if cutoff != coverage_through:
        raise ValueError("research supply cutoff must equal coverage_through")
    frozen_payload = value.get("frozen_payload")
    if not isinstance(frozen_payload, Mapping):
        raise ValueError("research supply frozen_payload is missing")
    if _selection_canonical_sha(frozen_payload) != str(
        value.get("frozen_payload_sha256") or ""
    ).lower():
        raise ValueError("research supply frozen_payload SHA mismatch")
    if set(frozen_payload.get("route_status", {})) != _SUPPLY_ROUTE_FIELDS:
        raise ValueError("research supply route status coverage is incomplete")
    if any(
        not isinstance(status, str) or not status.strip()
        for status in frozen_payload["route_status"].values()
    ):
        raise ValueError("research supply route status is invalid")
    if not isinstance(frozen_payload.get("source_receipts"), list):
        raise ValueError("research supply source receipts are invalid")
    cards = frozen_payload.get("event_cards")
    if not isinstance(cards, list):
        raise ValueError("research supply event cards are invalid")
    card_ids = []
    for card in cards:
        ticker = _validate_supply_card(card)
        if ticker in card_ids:
            raise ValueError("duplicate research supply ticker")
        card_ids.append(ticker)
    candidate_id_set = {f"HK.{ticker.split('.')[0]}|{ticker}" for ticker in card_ids}
    for field in ("core_research_candidates", "conditional_watch_candidates"):
        rows = frozen_payload.get(field)
        if not isinstance(rows, list) or len(rows) > 5:
            raise ValueError(f"invalid research supply {field}")
        for row in rows:
            if isinstance(row, str):
                candidate_id = row
            elif isinstance(row, Mapping):
                candidate_id = row.get("candidate_id")
            else:
                raise ValueError(f"invalid research supply {field} row")
            if candidate_id not in candidate_id_set:
                raise ValueError(f"research supply {field} candidate is unknown")
    core_ids = [
        row if isinstance(row, str) else row.get("candidate_id")
        for row in frozen_payload["core_research_candidates"]
    ]
    conditional_ids = [
        row if isinstance(row, str) else row.get("candidate_id")
        for row in frozen_payload["conditional_watch_candidates"]
    ]
    if set(core_ids) & set(conditional_ids):
        raise ValueError("research supply core and conditional candidates overlap")
    action_ids: set[str] = set()
    for field in ("KEEP", "ADD", "REMOVE"):
        selected = _validate_supply_action_rows(
            frozen_payload.get(field), field, candidate_ids=candidate_id_set
        )
        if action_ids.intersection(selected):
            raise ValueError("research supply candidate action is duplicated")
        action_ids.update(selected)
    _validate_supply_safety(frozen_payload.get("safety"), "research supply envelope")
    if "safety" in value:
        _validate_supply_safety(value["safety"], "research supply envelope")
        if value["safety"] != frozen_payload["safety"]:
            raise ValueError("research supply top-level safety does not reconcile")
    return target_date


def validate_research_supply_receipt(
    value: Mapping[str, Any],
    *,
    envelope: Mapping[str, Any] | None = None,
    artifact_path: str | None = None,
    artifact_sha256: str | None = None,
) -> str:
    """Validate a supply receipt and, when supplied, bind it to its envelope."""

    if not isinstance(value, Mapping) or not _SUPPLY_RECEIPT_FIELDS.issubset(value):
        raise ValueError("invalid research supply receipt fields")
    extra = set(value) - _SUPPLY_RECEIPT_FIELDS - {"type"}
    if extra:
        raise ValueError(f"invalid research supply receipt fields extra={sorted(extra)}")
    if value.get("schema_version") != RESEARCH_SUPPLY_RECEIPT_SCHEMA_VERSION:
        raise ValueError("invalid research supply receipt schema")
    if not isinstance(value.get("artifact_path"), str) or not value["artifact_path"]:
        raise ValueError("research supply receipt artifact path is missing")
    _selection_sha(value.get("artifact_sha256"), "supply artifact SHA")
    _selection_sha(value.get("frozen_payload_sha256"), "supply frozen SHA")
    _selection_date(value.get("source_date"), "supply receipt source_date")
    _selection_date(value.get("target_trade_date"), "supply receipt target_trade_date")
    _selection_timestamp(value.get("generated_at"), "supply receipt generated_at")
    _selection_timestamp(value.get("coverage_started_at"), "supply receipt coverage_started_at")
    _selection_timestamp(value.get("coverage_through"), "supply receipt coverage_through")
    _selection_timestamp(value.get("cutoff_at"), "supply receipt cutoff_at")
    if value.get("cutoff_at") != value.get("coverage_through"):
        raise ValueError("research supply receipt cutoff does not equal coverage_through")
    _validate_supply_safety(value.get("safety"), "research supply receipt")
    if artifact_path is not None and value.get("artifact_path") != artifact_path:
        raise ValueError("research supply receipt artifact path mismatch")
    if artifact_sha256 is not None and value.get("artifact_sha256") != artifact_sha256:
        raise ValueError("research supply receipt artifact SHA mismatch")
    if envelope is not None:
        target = validate_research_supply_envelope(envelope)
        for field in (
            "run_id",
            "source_date",
            "target_trade_date",
            "generated_at",
            "cutoff_at",
            "coverage_started_at",
            "coverage_through",
        ):
            if value.get(field) != envelope.get(field):
                raise ValueError(f"research supply receipt {field} mismatch")
        if value.get("frozen_payload_sha256") != envelope.get("frozen_payload_sha256"):
            raise ValueError("research supply receipt frozen SHA mismatch")
        if value.get("safety") != envelope["frozen_payload"]["safety"]:
            raise ValueError("research supply receipt safety mismatch")
        return target
    return str(value["target_trade_date"])


def validate_manager_research_decision(
    value: Mapping[str, Any],
    *,
    candidate_ids: list[str] | None = None,
    supply_envelope: Mapping[str, Any] | None = None,
) -> str:
    """Validate the typed 22:00 manager delta used for a supply snapshot."""

    if not isinstance(value, Mapping) or set(value) != _MANAGER_DECISION_FIELDS:
        raise ValueError("invalid manager research decision fields")
    if value.get("schema_version") != MANAGER_DECISION_SCHEMA_VERSION:
        raise ValueError("invalid manager research decision schema")
    if value.get("phase") != MANAGER_DECISION_PHASE:
        raise ValueError("invalid manager research decision phase")
    if value.get("decision_state") != MANAGER_DECISION_STATE:
        raise ValueError("invalid manager research decision state")
    source_date = _selection_date(value.get("source_date"), "decision source_date")
    target_date = _selection_date(value.get("target_trade_date"), "decision target_trade_date")
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or not _SELECTION_RUN_ID.fullmatch(run_id):
        raise ValueError("invalid manager research decision run_id")
    generated = _selection_parsed_timestamp(value.get("generated_at"), "decision generated_at")
    cutoff = _selection_parsed_timestamp(value.get("cutoff_at"), "decision cutoff_at")
    if cutoff > generated:
        raise ValueError("manager decision cutoff exceeds generated_at")
    source_start_hkt = datetime.strptime(source_date, "%Y%m%d").replace(tzinfo=_SHANGHAI)
    target_start_hkt = datetime.strptime(target_date, "%Y%m%d").replace(tzinfo=_SHANGHAI)
    generated_hkt = generated.astimezone(_SHANGHAI)
    if not source_start_hkt <= generated_hkt < target_start_hkt:
        raise ValueError("manager decision generated_at source date mismatch")
    if cutoff.astimezone(_SHANGHAI).strftime("%Y%m%d") != source_date:
        raise ValueError("manager decision cutoff source date mismatch")
    if supply_envelope is not None:
        validate_research_supply_envelope(
            supply_envelope,
            expected_source_date=source_date,
            expected_target_trade_date=target_date,
            expected_run_id=run_id,
        )
        supply_generated = _selection_parsed_timestamp(
            supply_envelope["generated_at"], "supply generated_at"
        )
        if generated < supply_generated:
            raise ValueError("manager decision generated_at predates supply envelope")
        if cutoff < _selection_parsed_timestamp(
            supply_envelope["cutoff_at"], "supply cutoff_at"
        ):
            raise ValueError("manager decision cutoff predates supply coverage")
    supply_ref = value.get("supply_ref")
    if not isinstance(supply_ref, Mapping) or set(supply_ref) != {
        "path",
        "raw_sha256",
        "frozen_payload_sha256",
        "run_id",
    }:
        raise ValueError("manager decision supply reference is incomplete")
    if not isinstance(supply_ref.get("path"), str) or not supply_ref["path"]:
        raise ValueError("manager decision supply path is missing")
    _selection_sha(supply_ref.get("raw_sha256"), "manager decision supply raw SHA")
    _selection_sha(
        supply_ref.get("frozen_payload_sha256"), "manager decision supply frozen SHA"
    )
    if supply_ref.get("run_id") != run_id:
        raise ValueError("manager decision supply run binding mismatch")
    if supply_envelope is not None and supply_ref.get("frozen_payload_sha256") != supply_envelope.get("frozen_payload_sha256"):
        raise ValueError("manager decision supply frozen SHA binding mismatch")
    baseline = value.get("baseline_ref")
    if baseline is not None:
        if not isinstance(baseline, Mapping) or set(baseline) != {"path", "raw_sha256"}:
            raise ValueError("manager decision baseline reference is invalid")
        if not isinstance(baseline.get("path"), str) or not baseline["path"]:
            raise ValueError("manager decision baseline path is missing")
        _selection_sha(baseline.get("raw_sha256"), "manager decision baseline SHA")
    known = set(candidate_ids or [])
    core_ids = _validate_supply_action_rows(
        value.get("core"), "core", candidate_ids=known or None, maximum=5
    )
    conditional_ids = _validate_supply_action_rows(
        value.get("conditional"), "conditional", candidate_ids=known or None, maximum=5
    )
    if set(core_ids) & set(conditional_ids):
        raise ValueError("manager decision core and conditional candidates overlap")
    decision_ids = set(core_ids) | set(conditional_ids)
    action_ids: set[str] = set()
    for field in ("KEEP", "ADD", "REMOVE"):
        selected = _validate_supply_action_rows(
            value.get(field), field, candidate_ids=known or None
        )
        if action_ids.intersection(selected):
            raise ValueError("manager decision action candidate is duplicated")
        action_ids.update(selected)
    if baseline is None:
        if value["KEEP"] or value["REMOVE"]:
            raise ValueError("manager decision baseline is required for KEEP/REMOVE")
        if set(row["candidate_id"] for row in value["ADD"]) != decision_ids:
            raise ValueError("manager decision initial ADD set does not reconcile")
    qualification_refs = value.get("qualification_refs")
    if not isinstance(qualification_refs, list):
        raise ValueError("manager decision qualification refs are invalid")
    qualified: set[str] = set()
    for ref in qualification_refs:
        if not isinstance(ref, Mapping) or set(ref) != {
            "candidate_id",
            "status",
            "path",
            "raw_sha256",
        }:
            raise ValueError("manager decision qualification ref is invalid")
        candidate_id = ref.get("candidate_id")
        if not isinstance(candidate_id, str) or (known and candidate_id not in known):
            raise ValueError("manager decision qualification candidate is unknown")
        if candidate_id in qualified:
            raise ValueError("duplicate manager decision qualification candidate")
        qualified.add(candidate_id)
        if not isinstance(ref.get("status"), str) or not ref["status"].strip():
            raise ValueError("manager decision qualification status is invalid")
        if ref["status"] == "ELIGIBILITY_CANNOT_CONFIRM":
            if ref.get("path") is not None or ref.get("raw_sha256") is not None:
                raise ValueError("unconfirmed qualification cannot carry evidence")
        else:
            if not isinstance(ref.get("path"), str) or not ref["path"]:
                raise ValueError("confirmed qualification path is missing")
            _selection_sha(ref.get("raw_sha256"), "manager qualification SHA")
    _validate_supply_safety(value.get("safety"), "manager decision")
    return target_date


def _validate_selection_source_ref(value: Any, *, source_date: str) -> None:
    if isinstance(value, Mapping) and value.get("type") == RESEARCH_SUPPLY_TYPE:
        required = {
            "type",
            "path",
            "raw_sha256",
            "frozen_payload_sha256",
            "json_pointer",
            "source_date",
            "source_time",
            "supply_receipt_path",
            "supply_receipt_sha256",
        }
        if set(value) != required:
            raise ValueError("invalid research supply source reference")
        if not isinstance(value.get("path"), str) or not value["path"]:
            raise ValueError("research supply source path is missing")
        if not isinstance(value.get("supply_receipt_path"), str) or not value["supply_receipt_path"]:
            raise ValueError("research supply receipt path is missing")
        _selection_sha(value.get("raw_sha256"), "supply source raw SHA")
        _selection_sha(value.get("frozen_payload_sha256"), "supply source frozen SHA")
        _selection_sha(value.get("supply_receipt_sha256"), "supply receipt SHA")
        pointer = value.get("json_pointer")
        if not isinstance(pointer, str) or not re.fullmatch(
            r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
        ):
            raise ValueError("research supply source JSON pointer is missing")
        if value.get("source_date") != source_date:
            raise ValueError("research supply source date mismatch")
        _selection_timestamp(value.get("source_time"), "research supply source_time")
        return
    required = {
        "type",
        "path",
        "raw_sha256",
        "frozen_payload_sha256",
        "json_pointer",
        "source_date",
        "source_time",
    }
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise ValueError("invalid selection source reference")
    if value.get("type") != "EARLY_DRAFT_FROZEN_ENVELOPE":
        raise ValueError("selection source reference type is not frozen envelope")
    if not isinstance(value.get("path"), str) or not value["path"]:
        raise ValueError("selection source reference path is missing")
    _selection_sha(value.get("raw_sha256"), "source raw SHA")
    _selection_sha(value.get("frozen_payload_sha256"), "source frozen SHA")
    pointer = value.get("json_pointer")
    if not isinstance(pointer, str) or not re.fullmatch(
        r"/frozen_payload/event_cards/(?:0|[1-9][0-9]*)", pointer
    ):
        raise ValueError("selection source JSON pointer is missing")
    if value.get("source_date") != source_date:
        raise ValueError("selection source date mismatch")
    _selection_timestamp(value.get("source_time"), "source_time")


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

    if not isinstance(value, Mapping) or set(value) != _MANAGER_DECISION_PROJECTION_FIELDS:
        raise ValueError("invalid manager decision projection fields")
    if value.get("schema_version") != MANAGER_DECISION_SCHEMA_VERSION:
        raise ValueError("invalid manager decision projection schema")
    if value.get("phase") != MANAGER_DECISION_PHASE:
        raise ValueError("invalid manager decision projection phase")
    if value.get("decision_state") != MANAGER_DECISION_STATE:
        raise ValueError("invalid manager decision projection state")
    if value.get("source_date") != source_date:
        raise ValueError("manager decision projection source date mismatch")
    if value.get("target_trade_date") != target_trade_date:
        raise ValueError("manager decision projection target date mismatch")
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or not _SELECTION_RUN_ID.fullmatch(run_id):
        raise ValueError("invalid manager decision projection run_id")
    if expected_run_id is not None and run_id != expected_run_id:
        raise ValueError("manager decision projection run binding mismatch")
    generated_at = _selection_timestamp(value.get("generated_at"), "manager decision projection generated_at")
    generated_value = _selection_parsed_timestamp(
        generated_at,
        "manager decision projection generated_at",
    )
    cutoff_value = _selection_parsed_timestamp(value.get("cutoff_at"), "manager decision projection cutoff_at")
    if cutoff_value > generated_value:
        raise ValueError(
            "manager decision projection cutoff must not be later than generated_at"
        )
    if cutoff_value != _selection_parsed_timestamp(cutoff_at, "cutoff_at"):
        raise ValueError("manager decision projection cutoff mismatch")
    if expected_generated_at is not None and generated_at != expected_generated_at:
        raise ValueError("manager decision projection generated_at mismatch")
    if value.get("role") not in _MANAGER_DECISION_PROJECTION_ROLES:
        raise ValueError("manager decision projection role is invalid")
    if type(value.get("order")) is not int or value["order"] < 1 or value["order"] > 5:
        raise ValueError("manager decision projection order is invalid")
    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        raise ValueError("manager decision projection reason is invalid")


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

    _validate_manager_decision_projection(
        value,
        source_date=source_date,
        target_trade_date=target_trade_date,
        cutoff_at=cutoff_at,
        expected_run_id=expected_run_id,
        expected_generated_at=expected_generated_at,
    )


def _validate_selection_candidate(
    value: Any,
    *,
    source_date: str,
    cutoff_at: str,
) -> None:
    if not isinstance(value, Mapping) or not _SELECTION_CANDIDATE_FIELDS.issubset(value):
        raise ValueError("invalid selection candidate fields")
    if not (set(value) - _SELECTION_CANDIDATE_FIELDS).issubset(
        _SELECTION_CANDIDATE_OPTIONAL_FIELDS
    ):
        raise ValueError("invalid selection candidate fields")
    refs = value.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise ValueError("selection candidate source refs are missing")
    source_types = {
        ref.get("type") for ref in refs if isinstance(ref, Mapping)
    }
    if len(source_types) != 1:
        raise ValueError("selection candidate source reference types are mixed")
    supply_source = source_types == {RESEARCH_SUPPLY_TYPE}
    required_text = (
        "candidate_id",
        "event_stock_link_id",
        "market",
        "normalized_code",
        "entity_id",
        "event_id",
        "acceptance",
        "eligibility",
        "pit_status",
        "research_status",
        "recommendation_status",
    )
    if any(not isinstance(value.get(field), str) or not value[field] for field in required_text):
        raise ValueError("selection candidate identity or status is missing")
    if value.get("research_status") != "RESEARCH_ONLY" or value.get("recommendation_status") != "RESEARCH_ONLY":
        raise ValueError("unsafe selection candidate recommendation")
    expected_acceptance = (
        RESEARCH_SUPPLY_ACCEPTANCE if supply_source else "EARLY_DRAFT_FROZEN_ONLY"
    )
    if value.get("acceptance") != expected_acceptance:
        raise ValueError("selection candidate acceptance is not frozen-draft only")
    entity_id = unicodedata.normalize("NFKC", value["entity_id"].strip())
    if "." not in entity_id:
        raise ValueError("selection candidate entity identity is invalid")
    code, market = entity_id.rsplit(".", 1)
    expected_candidate_id = f"{market.upper()}.{code.upper()}|{entity_id}"
    if value.get("candidate_id") != expected_candidate_id:
        raise ValueError("selection candidate identity does not reconcile")
    if value.get("event_stock_link_id") != f"{value['event_id']}|{expected_candidate_id}":
        raise ValueError("selection event-stock link does not reconcile")
    if value.get("eligibility") not in {"ELIGIBILITY_CANNOT_CONFIRM", "ELIGIBLE"}:
        raise ValueError("selection candidate eligibility is invalid")
    if value.get("pit_status") not in {"READY", "PIT_FAILED", "CANNOT_CONFIRM"}:
        raise ValueError("invalid selection candidate PIT status")
    for field in (
        "bucket",
        "catalyst",
        "counterevidence",
        "invalidation",
        "evidence_level",
        "financial_bridge",
        "consensus",
        "overnight_pending",
        "source_status",
        "published_at",
        "source_time",
    ):
        if not isinstance(value.get(field), str):
            raise ValueError(f"invalid selection candidate {field}")
    if not isinstance(value.get("source_metadata"), Mapping):
        raise ValueError("selection candidate source metadata is missing")
    _selection_timestamp(value.get("source_time"), "candidate source_time")
    published_aware = value.get("published_at_aware")
    if published_aware is not None:
        _selection_timestamp(published_aware, "candidate published_at_aware")
    if value.get("pit_status") == "READY":
        cutoff_value = _selection_parsed_timestamp(cutoff_at, "cutoff_at")
        if published_aware is None:
            raise ValueError("selection candidate PIT READY lacks published timestamp")
        published_value = _selection_parsed_timestamp(
            published_aware,
            "candidate published_at_aware",
        )
        source_value = _selection_parsed_timestamp(
            value.get("source_time"), "candidate source_time"
        )
        if published_value > cutoff_value or (
            not supply_source and source_value > cutoff_value
        ):
            raise ValueError("selection candidate PIT READY exceeds cutoff")
    route_status = value.get("route_status")
    if not isinstance(route_status, Mapping) or set(route_status) != {"R1", "R6"}:
        raise ValueError("selection candidate route status must separate R1 and R6")
    if route_status.get("R6") == "GEMINI_DISCOVERY_UNVERIFIED":
        raise ValueError("selection R6 cannot alias Gemini discovery")
    if value.get("gemini_status") not in {"UNVERIFIED", "NOT_MATERIALIZED"}:
        raise ValueError("Gemini selection status must remain unverified")
    for ref in refs:
        _validate_selection_source_ref(ref, source_date=source_date)


def _validate_selection_snapshot(value: Any, *, phase: str, target_trade_date: str) -> None:
    if not isinstance(value, Mapping) or set(value) != _SELECTION_SNAPSHOT_FIELDS:
        raise ValueError(f"invalid selection {phase} snapshot fields")
    if value.get("phase") != phase or value.get("status") not in SELECTION_SNAPSHOT_STATUSES:
        raise ValueError(f"invalid selection {phase} snapshot identity")
    _selection_strings(value.get("candidate_ids"), f"{phase} candidate_ids")
    if not isinstance(value.get("changes"), list) or any(not isinstance(item, Mapping) for item in value["changes"]):
        raise ValueError(f"invalid selection {phase} changes")
    status = value["status"]
    if status == "NOT_MATERIALIZED" or status == "CANNOT_CONFIRM":
        if any(value.get(field) is not None for field in ("run_id", "event_at", "artifact_sha256", "freeze_run_id", "freeze_snapshot_sha256", "snapshot_sha256")):
            raise ValueError(f"unmaterialized selection {phase} snapshot has identity")
        if value.get("candidate_ids") or value.get("changes"):
            raise ValueError(f"unmaterialized selection {phase} snapshot has rows")
        return
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or not _SELECTION_RUN_ID.fullmatch(run_id):
        raise ValueError(f"selection {phase} snapshot run_id is invalid")
    _selection_timestamp(value.get("event_at"), f"{phase} event_at")
    _selection_sha(value.get("artifact_sha256"), f"{phase} artifact_sha256")
    _selection_sha(value.get("snapshot_sha256"), f"{phase} snapshot_sha256")
    snapshot_body = {
        key: item for key, item in value.items() if key != "snapshot_sha256"
    }
    if value.get("snapshot_sha256") != _selection_canonical_sha(snapshot_body):
        raise ValueError(f"selection {phase} snapshot SHA mismatch")
    if phase in {"0935", "1620"}:
        if not isinstance(value.get("freeze_run_id"), str) or not _SELECTION_RUN_ID.fullmatch(value["freeze_run_id"]):
            raise ValueError(f"selection {phase} must reference an 0830 run")
        _selection_sha(value.get("freeze_snapshot_sha256"), f"{phase} freeze_snapshot_sha256")
    elif value.get("freeze_run_id") is not None or value.get("freeze_snapshot_sha256") is not None:
        raise ValueError(f"selection {phase} cannot carry a freeze reference")


def _selection_apply_changes(
    changes: Any,
    *,
    current_ids: set[str],
    candidate_ids: set[str],
    phase: str,
) -> set[str]:
    """Validate deterministic KEEP/ADD/REMOVE semantics and return the set."""

    if not isinstance(changes, list):
        raise ValueError(f"selection {phase} changes are invalid")
    working = set(current_ids)
    seen: set[str] = set()
    for change in changes:
        if not isinstance(change, Mapping) or set(change) != {"action", "candidate_id"}:
            raise ValueError(f"selection {phase} change fields are invalid")
        action = change.get("action")
        candidate_id = change.get("candidate_id")
        if action not in {"KEEP", "ADD", "REMOVE"} or not isinstance(candidate_id, str):
            raise ValueError(f"selection {phase} change operation is invalid")
        if candidate_id not in candidate_ids:
            raise ValueError(f"selection {phase} change candidate is unknown")
        if candidate_id in seen:
            raise ValueError(f"selection {phase} change candidate is duplicated")
        seen.add(candidate_id)
        if action == "KEEP" and candidate_id not in working:
            raise ValueError(f"selection {phase} KEEP candidate is not in the current set")
        if action == "ADD":
            if candidate_id in working:
                raise ValueError(f"selection {phase} ADD candidate is already in the current set")
            working.add(candidate_id)
        if action == "REMOVE":
            if candidate_id not in working:
                raise ValueError(f"selection {phase} REMOVE candidate is not in the current set")
            working.remove(candidate_id)
    return working


def _validate_selection_formal_authority(value: Any, *, target_trade_date: str) -> None:
    if not isinstance(value, Mapping) or set(value) != _SELECTION_FORMAL_AUTHORITY_FIELDS:
        raise ValueError("invalid selection formal authority fields")
    if value.get("status") not in {"READY", "NOT_MATERIALIZED", "STALE", "CANNOT_CONFIRM"}:
        raise ValueError("invalid selection formal authority status")
    if value.get("target_trade_date") != target_trade_date:
        raise ValueError("selection formal authority target date mismatch")
    for field in ("pit_status", "selector_status"):
        if not isinstance(value.get(field), str):
            raise ValueError(f"invalid selection formal authority {field}")
    if type(value.get("research_evidence")) is not bool or type(value.get("manager_decision")) is not bool:
        raise ValueError("selection formal authority gates must be boolean")
    evidence_refs = value.get("evidence_refs")
    if not isinstance(evidence_refs, list) or any(not isinstance(ref, Mapping) for ref in evidence_refs):
        raise ValueError("selection formal evidence refs are invalid")
    decision_ref = value.get("manager_decision_ref")
    if decision_ref is not None and not isinstance(decision_ref, Mapping):
        raise ValueError("selection manager decision ref is invalid")
    if value.get("status") == "READY":
        if value.get("pit_status") != "READY" or value.get("selector_status") != "READY" or not value["research_evidence"] or not value["manager_decision"]:
            raise ValueError("selection formal authority READY gate is incomplete")
        if not evidence_refs or decision_ref is None:
            raise ValueError("selection formal authority references are incomplete")
        for ref in evidence_refs:
            if not isinstance(ref.get("path"), str) or not ref["path"]:
                raise ValueError("selection formal evidence ref path is missing")
            _selection_sha(ref.get("sha256"), "formal evidence SHA")
        if not isinstance(decision_ref.get("path"), str) or not decision_ref["path"]:
            raise ValueError("selection manager decision ref path is missing")
        _selection_sha(decision_ref.get("sha256"), "manager decision SHA")
        _selection_sha(value.get("source_sha256"), "formal authority source_sha256")
    elif value.get("source_sha256") is not None:
        _selection_sha(value.get("source_sha256"), "formal authority source_sha256")


def _validate_selection_formal_refs(
    authority: Mapping[str, Any],
    *,
    source_date: str,
    target_trade_date: str,
    candidate_ids: list[str],
) -> None:
    """Validate the immutable, typed references behind a formal shortlist."""

    if not candidate_ids:
        return
    expected_source_sha = authority.get("source_sha256")
    evidence_refs = authority.get("evidence_refs")
    decision_ref = authority.get("manager_decision_ref")
    authority_run_ids: set[str] = set()
    for ref in evidence_refs:
        required = {
            "schema_version",
            "type",
            "path",
            "sha256",
            "source_sha256",
            "source_date",
            "target_trade_date",
            "run_id",
            "candidate_ids",
            "candidate_bindings",
            "status",
            "pit_status",
        }
        if not required.issubset(ref):
            raise ValueError("selection formal evidence reference schema is incomplete")
        if ref.get("schema_version") != "v3_5.selection_formal_evidence.v1" or ref.get("type") != "EXACT_DATE_PIT":
            raise ValueError("selection formal evidence reference type is invalid")
        if ref.get("source_sha256") != expected_source_sha:
            raise ValueError("selection formal evidence source binding mismatch")
        if (
            ref.get("source_date") != source_date
            or ref.get("target_trade_date") != target_trade_date
            or not isinstance(ref.get("run_id"), str)
            or not _SELECTION_RUN_ID.fullmatch(ref["run_id"])
        ):
            raise ValueError("selection formal evidence date/run binding mismatch")
        authority_run_ids.add(ref["run_id"])
        if ref.get("candidate_ids") != candidate_ids or ref.get("status") != "READY" or ref.get("pit_status") != "READY":
            raise ValueError("selection formal evidence candidate binding mismatch")
        _validate_selection_proof_bindings(
            ref,
            candidate_ids=candidate_ids,
            source_date=source_date,
            label="selection formal evidence",
        )
    required_decision = {
        "schema_version",
        "type",
        "path",
        "sha256",
        "source_sha256",
        "source_date",
        "target_trade_date",
        "run_id",
        "candidate_ids",
        "candidate_bindings",
        "decision",
    }
    if not isinstance(decision_ref, Mapping) or not required_decision.issubset(decision_ref):
        raise ValueError("selection manager decision reference schema is incomplete")
    if decision_ref.get("schema_version") != "v3_5.selection_manager_decision.v1" or decision_ref.get("type") != "MANAGER_DECISION":
        raise ValueError("selection manager decision reference type is invalid")
    if decision_ref.get("source_sha256") != expected_source_sha:
        raise ValueError("selection manager decision source binding mismatch")
    if (
        decision_ref.get("source_date") != source_date
        or decision_ref.get("target_trade_date") != target_trade_date
        or not isinstance(decision_ref.get("run_id"), str)
        or not _SELECTION_RUN_ID.fullmatch(decision_ref["run_id"])
    ):
        raise ValueError("selection manager decision date/run binding mismatch")
    authority_run_ids.add(decision_ref["run_id"])
    if decision_ref.get("candidate_ids") != candidate_ids or decision_ref.get("decision") is not True:
        raise ValueError("selection manager decision candidate binding mismatch")
    _validate_selection_proof_bindings(
        decision_ref,
        candidate_ids=candidate_ids,
        source_date=source_date,
        label="selection manager decision",
    )
    if len(authority_run_ids) != 1:
        raise ValueError("selection formal references use conflicting authority runs")


def _validate_selection_proof_bindings(
    value: Mapping[str, Any],
    *,
    candidate_ids: list[str],
    source_date: str,
    label: str,
) -> None:
    bindings = value.get("candidate_bindings")
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
        if candidate_id not in candidate_ids or candidate_id in seen:
            raise ValueError(f"{label} candidate source binding identity is invalid")
        if binding.get("eligibility") != "ELIGIBLE" or binding.get("pit_status") != "READY":
            raise ValueError(f"{label} candidate source proof status is incomplete")
        refs = binding.get("source_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"{label} candidate source binding refs are missing")
        for ref in refs:
            _validate_selection_source_ref(ref, source_date=source_date)
        seen.append(candidate_id)
    if seen != candidate_ids:
        raise ValueError(f"{label} candidate source binding order mismatch")
def validate_selection_research_product(
    payload: Mapping[str, Any],
    *,
    market_focus: str | None = None,
) -> str:
    """Validate the selection ledger without reading files or runtime state."""

    if not isinstance(payload, Mapping) or not _SELECTION_PRODUCT_FIELDS.issubset(payload):
        raise ValueError("invalid selection research product fields")
    extra_fields = set(payload) - _SELECTION_PRODUCT_FIELDS
    if not extra_fields.issubset(_SELECTION_OPTIONAL_FIELDS):
        raise ValueError("invalid selection research product fields")
    if payload.get("schema_version") != SELECTION_SCHEMA_VERSION:
        raise ValueError("invalid selection research product schema")
    if payload.get("contract_id") != SELECTION_CONTRACT_ID:
        raise ValueError("invalid selection research product contract")
    if payload.get("workflow_name") != SELECTION_WORKFLOW_NAME:
        raise ValueError("invalid selection research product workflow")
    if payload.get("pass_signal") != SELECTION_PASS_SIGNAL:
        raise ValueError("invalid selection research product pass signal")
    source_date = _selection_date(payload.get("source_date"), "source_date")
    target_date = _selection_date(payload.get("target_trade_date"), "target_trade_date")
    if payload.get("timezone") != TIMEZONE:
        raise ValueError("selection timezone must be Asia/Shanghai")
    _selection_timestamp(payload.get("cutoff_at"), "cutoff_at")
    _selection_timestamp(payload.get("generated_at"), "generated_at")
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not _SELECTION_RUN_ID.fullmatch(run_id):
        raise ValueError("invalid selection run_id")
    if payload.get("origin") not in SELECTION_ORIGINS:
        raise ValueError("invalid selection origin")
    if payload.get("status") not in SELECTION_STATUSES:
        raise ValueError("invalid selection research status")
    if payload.get("acceptance") not in {
        "EARLY_DRAFT_FROZEN_ONLY",
        RESEARCH_SUPPLY_ACCEPTANCE,
        "NOT_MATERIALIZED",
    }:
        raise ValueError("invalid selection acceptance")
    for key, expected in SAFETY_FLAGS.items():
        if payload.get(key) is not expected:
            raise ValueError(f"unsafe selection safety boundary: {key}")

    candidates = payload.get("research_candidates")
    if not isinstance(candidates, list):
        raise ValueError("invalid selection research candidates")
    candidate_ids: list[str] = []
    for candidate in candidates:
        _validate_selection_candidate(
            candidate,
            source_date=source_date,
            cutoff_at=str(payload.get("cutoff_at")),
        )
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in candidate_ids:
            raise ValueError("duplicate selection candidate")
        candidate_ids.append(candidate_id)
    if candidate_ids != sorted(candidate_ids):
        raise ValueError("selection candidates must be sorted by candidate_id")
    validate_selection_market_scope(payload, market_focus=market_focus)
    candidate_source_types = {
        ref.get("type")
        for candidate in candidates
        for ref in candidate.get("source_refs", [])
        if isinstance(ref, Mapping)
    }
    if len(candidate_source_types) > 1:
        raise ValueError("selection product source reference types are mixed")
    supply_product = candidate_source_types == {RESEARCH_SUPPLY_TYPE}
    if supply_product and payload.get("acceptance") != RESEARCH_SUPPLY_ACCEPTANCE:
        raise ValueError("research supply product acceptance is invalid")
    if not supply_product and payload.get("acceptance") == RESEARCH_SUPPLY_ACCEPTANCE:
        raise ValueError("research supply acceptance lacks supply source")
    manager_decision_ref = payload.get("manager_decision_ref")
    if manager_decision_ref is not None:
        if not supply_product:
            raise ValueError("manager decision reference requires research supply")
        if not isinstance(manager_decision_ref, Mapping) or set(manager_decision_ref) != {
            "path",
            "raw_sha256",
        }:
            raise ValueError("invalid manager decision reference")
        if not isinstance(manager_decision_ref.get("path"), str) or not manager_decision_ref["path"]:
            raise ValueError("manager decision reference path is missing")
        _selection_sha(manager_decision_ref.get("raw_sha256"), "manager decision raw SHA")

    formal = payload.get("formal_shortlist")
    if not isinstance(formal, list) or any(not isinstance(item, str) for item in formal):
        raise ValueError("invalid selection formal shortlist")
    if formal != sorted(set(formal)) or any(item not in candidate_ids for item in formal):
        raise ValueError("selection formal shortlist identity mismatch")
    formal_authority = payload.get("formal_authority")
    _validate_selection_formal_authority(
        formal_authority,
        target_trade_date=target_date,
    )

    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, Mapping) or set(snapshots) != set(SELECTION_PHASES):
        raise ValueError("selection snapshots must cover every phase")
    for phase in SELECTION_PHASES:
        _validate_selection_snapshot(snapshots[phase], phase=phase, target_trade_date=target_date)
        if any(candidate_id not in candidate_ids for candidate_id in snapshots[phase]["candidate_ids"]):
            raise ValueError(f"selection {phase} snapshot contains unknown candidate")

    snapshot_2200 = snapshots["2200"]
    snapshot_0830 = snapshots["0830"]
    snapshot_0935 = snapshots["0935"]
    snapshot_1620 = snapshots["1620"]
    candidate_id_set = set(candidate_ids)
    projected_candidates = [
        candidate
        for candidate in candidates
        if "manager_decision" in candidate
    ]
    if projected_candidates:
        if manager_decision_ref is None:
            raise ValueError("manager decision projection requires a decision reference")
        if snapshot_2200["status"] != "READY":
            raise ValueError("manager decision projection requires a READY 2200 snapshot")
        if snapshot_2200["artifact_sha256"] != manager_decision_ref["raw_sha256"]:
            raise ValueError("manager decision projection reference does not match 2200 snapshot")
        projected_ids = [candidate["candidate_id"] for candidate in projected_candidates]
        if projected_ids != list(dict.fromkeys(projected_ids)):
            raise ValueError("manager decision projection candidate ids are duplicated")
        if sorted(projected_ids) != snapshot_2200["candidate_ids"]:
            raise ValueError("manager decision projection does not reconcile with 2200 snapshot")
        role_orders: dict[str, list[int]] = {role: [] for role in _MANAGER_DECISION_PROJECTION_ROLES}
        for candidate in projected_candidates:
            projection = candidate["manager_decision"]
            _validate_manager_decision_projection(
                projection,
                source_date=source_date,
                target_trade_date=target_date,
                cutoff_at=str(payload["cutoff_at"]),
                expected_run_id=str(snapshot_2200["run_id"]),
                expected_generated_at=str(snapshot_2200["event_at"]),
            )
            role_orders[projection["role"]].append(projection["order"])
        for role, orders in role_orders.items():
            if sorted(orders) != list(range(1, len(orders) + 1)):
                raise ValueError(f"manager decision projection {role} order is not contiguous")
    if supply_product:
        if snapshot_2200["status"] == "READY" and manager_decision_ref is None:
            raise ValueError("research supply 2200 requires a manager decision reference")
        if snapshot_2200["status"] != "READY" and manager_decision_ref is not None:
            raise ValueError("research supply manager decision lacks a 2200 snapshot")
    if snapshot_2200["status"] == "READY":
        if snapshot_2200["changes"]:
            raise ValueError("selection 2200 initial snapshot cannot carry changes")
    for phase, snapshot in (("0830", snapshot_0830), ("0935", snapshot_0935), ("1620", snapshot_1620)):
        if snapshot["status"] != "READY":
            continue
        if phase == "0830":
            if snapshot_2200["status"] != "READY":
                raise ValueError("selection 0830 requires a READY 2200 dependency")
            expected_ids = _selection_apply_changes(
                snapshot["changes"],
                current_ids=set(snapshot_2200["candidate_ids"]),
                candidate_ids=candidate_id_set,
                phase=phase,
            )
            if sorted(expected_ids) != snapshot["candidate_ids"]:
                raise ValueError("selection 0830 changes do not reconcile with its candidate set")
        else:
            if snapshot_0830["status"] != "READY":
                raise ValueError(f"selection {phase} requires a READY 0830 dependency")
            if (
                snapshot.get("freeze_run_id") != snapshot_0830.get("run_id")
                or snapshot.get("freeze_snapshot_sha256") != snapshot_0830.get("snapshot_sha256")
            ):
                raise ValueError(f"selection {phase} freeze binding is invalid")
            expected_ids = _selection_apply_changes(
                snapshot["changes"],
                current_ids=set(snapshot_0830["candidate_ids"]),
                candidate_ids=candidate_id_set,
                phase=phase,
            )
            # Intraday/outcome changes are append-only observations.  They
            # must never rewrite the frozen 08:30 membership.
            if any(
                change["action"] == "REMOVE"
                or (change["action"] == "KEEP" and change["candidate_id"] not in snapshot_0830["candidate_ids"])
                for change in snapshot["changes"]
            ):
                raise ValueError(f"selection {phase} changes rewrite the 0830 freeze")
            if any(
                change["action"] == "ADD" and change["candidate_id"] in snapshot_0830["candidate_ids"]
                for change in snapshot["changes"]
            ):
                raise ValueError(f"selection {phase} changes rewrite the 0830 freeze")
            if not set(snapshot["candidate_ids"]) == set(snapshot_0830["candidate_ids"]):
                raise ValueError(f"selection {phase} changed the 0830 frozen membership")

    if snapshot_0935["status"] == "READY":
        matching_observation = any(
            isinstance(observation, Mapping)
            and observation.get("kind") == "APPEND_ONLY"
            and observation.get("freeze_run_id") == snapshot_0830["run_id"]
            and observation.get("freeze_snapshot_sha256") == snapshot_0830["snapshot_sha256"]
            for observation in payload.get("intraday_observations", [])
        )
        if not matching_observation:
            raise ValueError("selection 0935 requires an append-only observation bound to 0830")
    if snapshot_1620["status"] == "READY":
        matching_outcome = any(
            isinstance(outcome, Mapping)
            and outcome.get("kind") == "OUTCOME_REFERENCE"
            and outcome.get("freeze_run_id") == snapshot_0830["run_id"]
            and outcome.get("freeze_snapshot_sha256") == snapshot_0830["snapshot_sha256"]
            for outcome in payload.get("outcomes", [])
        )
        if not matching_outcome:
            raise ValueError("selection 1620 requires an outcome bound to 0830")

    for field in ("intraday_observations", "outcomes"):
        if not isinstance(payload.get(field), list) or any(not isinstance(item, Mapping) for item in payload[field]):
            raise ValueError(f"invalid selection {field}")
    for observation in payload["intraday_observations"]:
        if observation.get("kind") != "APPEND_ONLY":
            raise ValueError("selection intraday observation must be APPEND_ONLY")
        if "observed_at" in observation:
            _selection_timestamp(observation.get("observed_at"), "intraday observed_at")
    for outcome in payload["outcomes"]:
        if outcome.get("kind") != "OUTCOME_REFERENCE":
            raise ValueError("selection outcome kind is invalid")
        if "observed_at" in outcome:
            _selection_timestamp(outcome.get("observed_at"), "outcome observed_at")
    counts = payload.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != _SELECTION_COUNTS_FIELDS:
        raise ValueError("invalid selection counts")
    for key, value in counts.items():
        if type(value) is not int or value < 0:
            raise ValueError(f"invalid selection count {key}")
    expected_counts = {
        "research_candidates": len(candidates),
        "formal_shortlist": len(formal),
        "snapshots": len(SELECTION_PHASES),
        "intraday_observations": len(payload["intraday_observations"]),
        "outcomes": len(payload["outcomes"]),
    }
    if dict(counts) != expected_counts:
        raise ValueError("selection counts do not reconcile")

    expected_gaps: set[str] = set()
    for phase in SELECTION_PHASES:
        if snapshots[phase]["status"] != "READY":
            if supply_product and phase == "2200":
                expected_gaps.add("SUPPLY_2200_DECISION_NOT_MATERIALIZED")
            else:
                expected_gaps.add(f"SNAPSHOT_{phase}_NOT_MATERIALIZED")
    if not formal or formal_authority.get("status") != "READY":
        expected_gaps.add("FORMAL_AUTHORITY_NOT_MATERIALIZED")
    if any(candidate["pit_status"] != "READY" for candidate in candidates):
        expected_gaps.add("CANDIDATE_PIT_NOT_CONFIRMED")
    if set(payload.get("cannot_confirm", [])) != expected_gaps:
        raise ValueError("selection cannot_confirm gaps do not reconcile")
    expected_status = (
        "NOT_MATERIALIZED"
        if not candidates
        else (
            RESEARCH_SUPPLY_STATUS
            if supply_product
            and not any(snapshots[phase]["status"] == "READY" for phase in SELECTION_PHASES)
            else (
                "EARLY_DRAFT_IMPORTED"
                if not any(snapshots[phase]["status"] == "READY" for phase in SELECTION_PHASES)
                else ("READY_WITH_DECLARED_GAPS" if expected_gaps else "READY")
            )
        )
    )
    if payload.get("status") != expected_status:
        raise ValueError("selection status does not reconcile with materialized phases and gaps")
    expected_first_failed = min(expected_gaps) if expected_gaps else None
    if payload.get("first_failed_layer") != expected_first_failed:
        raise ValueError("selection first_failed_layer does not reconcile")

    route_status = payload.get("route_status")
    if not isinstance(route_status, Mapping) or set(route_status) != {"R1", "R2", "R6", "GEMINI"}:
        raise ValueError("selection route status must separate R1, R2, R6 and Gemini")
    if any(not isinstance(value, str) or not value for value in route_status.values()):
        raise ValueError("invalid selection route status value")
    if route_status.get("R6") == "GEMINI_DISCOVERY_UNVERIFIED":
        raise ValueError("selection R6 cannot alias Gemini discovery")
    if route_status.get("GEMINI") not in {"UNVERIFIED", "NOT_MATERIALIZED"}:
        raise ValueError("Gemini route status must remain unverified")
    if payload.get("gemini_status") not in {"UNVERIFIED", "NOT_MATERIALIZED"}:
        raise ValueError("Gemini must remain UNVERIFIED or NOT_MATERIALIZED")
    if payload.get("gemini_status") != route_status.get("GEMINI"):
        raise ValueError("Gemini route and product status do not reconcile")
    if formal:
        authority = formal_authority
        if authority.get("status") != "READY":
            raise ValueError("selection formal shortlist lacks READY authority")
        candidates_by_id = {
            candidate["candidate_id"]: candidate for candidate in candidates
        }
        for candidate_id in formal:
            candidate = candidates_by_id[candidate_id]
            if candidate.get("eligibility") != "ELIGIBLE" or candidate.get("pit_status") != "READY":
                raise ValueError("selection formal shortlist candidate gate is incomplete")
        _validate_selection_formal_refs(
            authority,
            source_date=source_date,
            target_trade_date=target_date,
            candidate_ids=formal,
        )

    refs = payload.get("source_refs")
    if not isinstance(refs, list):
        raise ValueError("invalid selection source refs")
    for ref in refs:
        _validate_selection_source_ref(ref, source_date=source_date)
    if refs != [ref for candidate in candidates for ref in candidate["source_refs"]]:
        raise ValueError("selection source refs do not reconcile with candidates")

    first_failed = payload.get("first_failed_layer")
    if first_failed is not None and (not isinstance(first_failed, str) or not first_failed):
        raise ValueError("invalid selection first_failed_layer")
    _selection_strings(payload.get("cannot_confirm"), "cannot_confirm")
    if not candidates and payload.get("status") != "NOT_MATERIALIZED":
        raise ValueError("empty selection ledger must be NOT_MATERIALIZED")
    if candidates and payload.get("status") == "NOT_MATERIALIZED":
        raise ValueError("selection ledger with candidates cannot be NOT_MATERIALIZED")
    return target_date


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
