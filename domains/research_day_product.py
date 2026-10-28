"""Deterministic exact-date aggregation for V3.5 research day products."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from contracts.research_day_product import (
    CONTRACT_ID,
    DATE_MODE,
    EXPECTED_RESEARCH_SLOTS,
    MANAGER_DECISION_PHASE,
    RESEARCH_SUPPLY_ACCEPTANCE,
    RESEARCH_SUPPLY_STATUS,
    RESEARCH_SUPPLY_TYPE,
    PASS_SIGNAL,
    PRODUCT_SCHEMA_VERSION,
    SAFETY_FLAGS,
    SELECTION_CONTRACT_ID,
    SELECTION_ORIGINS,
    SELECTION_PASS_SIGNAL,
    SELECTION_PHASES,
    SELECTION_SCHEMA_VERSION,
    SELECTION_WORKFLOW_NAME,
    TIMEZONE,
    WORKFLOW_NAME,
    validate_selection_research_product,
    validate_manager_research_decision,
    validate_research_supply_envelope,
    validate_research_day_product,
)


_SHANGHAI = ZoneInfo(TIMEZONE)
_EVIDENCE_RANK = {
    "L3": 3,
    "L3_STRONG": 3,
    "L2": 2,
    "L2_MEDIUM": 2,
    "L1": 1,
    "L1_WEAK": 1,
}
_CONFIDENCE_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
_MISSING_REGISTRY_GAP = "JYG_STOCK_MENTIONS_REGISTRY_MISSING"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _selection_value_text(value: Any) -> str:
    """Project optional supply values without losing deterministic encoding."""
    from domains._research_day_product_parts.primitives import __selection_value_text_body as _v4_impl
    return _v4_impl(globals(), value)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _date(value: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("research day date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("research day date must be a real date") from error
    return value


def normalize_pair_identity(url: Any, stock_code: Any) -> str | None:
    """Return the frozen URL+stock pair key, without changing URL path/query."""

    if not isinstance(url, str) or not isinstance(stock_code, str):
        return None
    normalized_url = unicodedata.normalize("NFKC", url.strip())
    normalized_stock = unicodedata.normalize("NFKC", stock_code.strip()).upper()
    if not normalized_url or not normalized_stock:
        return None
    return f"{normalized_url}|{normalized_stock}"


def _source_rows(payload: Mapping[str, Any]) -> list[Any]:
    for field in ("evidence_rows", "rows", "articles", "stock_research_timeline"):
        value = payload.get(field)
        if isinstance(value, list):
            return value
    raise ValueError("research day slot has no explicit rows")


def _published_timestamp(value: Any) -> datetime:
    """Parse the article publication timestamp without assuming a timezone."""
    from domains._research_day_product_parts.primitives import __published_timestamp_body as _v4_impl
    return _v4_impl(globals(), value)


def _variant(row: Mapping[str, Any]) -> dict[str, Any]:
    from domains._research_day_product_parts.primitives import __variant_body as _v4_impl
    return _v4_impl(globals(), row)


def _level_rank(value: Any) -> int:
    text = _text(value).upper()
    return _EVIDENCE_RANK.get(text, 0)


def _confidence_rank(value: Any) -> int:
    return _CONFIDENCE_RANK.get(_text(value).upper(), 0)


def _slot_number(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return -1


def _source_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "slot": row["slot"],
        "source_row_ref": row["source_row_ref"],
        "artifact_path": row["source_artifact_path"],
        "artifact_sha256": row["source_artifact_sha256"],
        "receipt_path": row["source_receipt_path"],
        "receipt_sha256": row["source_receipt_sha256"],
        "source_input_sha256": row["source_input_sha256"],
        "changed_fields": list(row.get("changed_fields") or []),
    }


def _lineage_ref(
    slot: str,
    payload: Mapping[str, Any],
    source_ref: Mapping[str, Any] | None,
) -> dict[str, str]:
    from domains._research_day_product_parts.source_lineage import __lineage_ref_body as _v4_impl
    return _v4_impl(globals(), slot, payload, source_ref)


def _changed_fields(row: Mapping[str, Any], winner: Mapping[str, Any]) -> list[str]:
    fields = sorted(
        key
        for key in set(_variant(row)) | set(_variant(winner))
        if _variant(row).get(key) != _variant(winner).get(key)
    )
    return fields


def _registry_projection(registry: Any) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    from domains._research_day_product_parts.source_lineage import __registry_projection_body as _v4_impl
    return _v4_impl(globals(), registry)


def _jyg_coverage(registry: Any) -> dict[str, Any]:
    """Project only explicitly supplied JYG observations; never infer them."""
    from domains._research_day_product_parts.source_lineage import __jyg_coverage_body as _v4_impl
    return _v4_impl(globals(), registry)


def build_research_day_product(
    archive_date: str,
    slots: Mapping[str, Mapping[str, Any]],
    *,
    source_refs: Mapping[str, Mapping[str, Any]] | None = None,
    stock_mentions_registry: Mapping[str, Any] | None = None,
    transformer_identity_sha256: str | None = None,
) -> dict[str, Any]:
    """Build one day product from eight named, already materialized slots."""
    from domains._research_day_product_parts.day_assembly import _build_research_day_product_body as _v4_impl
    return _v4_impl(globals(), archive_date, slots, source_refs=source_refs, stock_mentions_registry=stock_mentions_registry, transformer_identity_sha256=transformer_identity_sha256)


def consume_authoritative_research_day(
    product: Mapping[str, Any] | None,
    *,
    requested_date: str,
) -> dict[str, Any]:
    """White-hair consumer: exact-date and authoritative-only, fail closed."""
    from domains._research_day_product_parts.consumer import _consume_authoritative_research_day_body as _v4_impl
    return _v4_impl(globals(), product, requested_date=requested_date)


def _consumer_gap(
    requested_date: str,
    reason: str,
    *,
    resolved_date: str | None = None,
) -> dict[str, Any]:
    """Return a complete diagnostic envelope without exposing a non-authority pool."""
    from domains._research_day_product_parts.consumer import __consumer_gap_body as _v4_impl
    return _v4_impl(globals(), requested_date, reason, resolved_date=resolved_date)


def build_authoritative_research_consumer(
    product: Mapping[str, Any] | None,
    *,
    requested_date: str,
) -> dict[str, Any]:
    """Compatibility name for the research-only white-hair adapter."""

    return consume_authoritative_research_day(product, requested_date=requested_date)


_SELECTION_DEFAULT_ROUTE_STATUS = {
    "R1": "NOT_MATERIALIZED",
    "R2": "NOT_MATERIALIZED",
    "R6": "NOT_MATERIALIZED",
    "GEMINI": "NOT_MATERIALIZED",
}


def selection_candidate_id(market: Any, normalized_code: Any, entity_id: Any) -> str:
    """Build the only selection identity; event linkage stays separate."""
    from domains._research_day_product_parts.primitives import _selection_candidate_id_body as _v4_impl
    return _v4_impl(globals(), market, normalized_code, entity_id)


def event_stock_link_id(event_id: Any, candidate_id: Any) -> str:
    """Return a stable event-to-stock link distinct from candidate identity."""

    event = str(event_id or "").strip()
    candidate = str(candidate_id or "").strip()
    if not event or not candidate:
        raise ValueError("selection event-stock link is incomplete")
    return f"{event}|{candidate}"


def _selection_aware_hkt(value: Any) -> str | None:
    from domains._research_day_product_parts.primitives import __selection_aware_hkt_body as _v4_impl
    return _v4_impl(globals(), value)


def _selection_hash_text(value: Any) -> str | None:
    text = _text(value).lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        return None
    return text


def _selection_source_ref(
    card: Mapping[str, Any],
    source_ref: Mapping[str, Any] | None,
    *,
    source_date: str,
) -> dict[str, Any]:
    from domains._research_day_product_parts.source_lineage import __selection_source_ref_body as _v4_impl
    return _v4_impl(globals(), card, source_ref, source_date=source_date)


def _selection_entity_parts(
    entry: Mapping[str, Any],
    card: Mapping[str, Any],
    *,
    supply_source: bool,
) -> tuple[str, str, str]:
    from domains._research_day_product_parts.selection_candidate import __selection_entity_parts_body as _v4_impl
    return _v4_impl(globals(), entry, card, supply_source=supply_source)


def _selection_candidate(
    entry: Mapping[str, Any],
    *,
    source_date: str,
    cutoff_at: str,
    route_status: Mapping[str, str],
) -> dict[str, Any]:
    from domains._research_day_product_parts.selection_candidate import __selection_candidate_body as _v4_impl
    return _v4_impl(globals(), entry, source_date=source_date, cutoff_at=cutoff_at, route_status=route_status)


def _selection_snapshot(
    phase: str,
    value: Mapping[str, Any] | None,
    *,
    candidate_ids: list[str],
) -> dict[str, Any]:
    from domains._research_day_product_parts.selection_candidate import __selection_snapshot_body as _v4_impl
    return _v4_impl(globals(), phase, value, candidate_ids=candidate_ids)


def _selection_formal_authority(
    value: Mapping[str, Any] | None,
    *,
    target_trade_date: str,
) -> dict[str, Any]:
    from domains._research_day_product_parts.formal_refs import __selection_formal_authority_body as _v4_impl
    return _v4_impl(globals(), value, target_trade_date=target_trade_date)


def _selection_formal_refs_bind_candidates(
    authority: Mapping[str, Any],
    candidate_ids: list[str],
) -> bool:
    """Check the pure shape of candidate proof before requesting promotion."""
    from domains._research_day_product_parts.formal_refs import __selection_formal_refs_bind_candidates_body as _v4_impl
    return _v4_impl(globals(), authority, candidate_ids)


def build_selection_research_product(
    source_date: str,
    target_trade_date: str,
    *,
    source_cards: list[Mapping[str, Any]] | None = None,
    source_envelope: Mapping[str, Any] | None = None,
    source_ref: Mapping[str, Any] | None = None,
    generated_at: str,
    cutoff_at: str,
    run_id: str,
    origin: str = "HISTORICAL_RECONSTRUCTION",
    route_status: Mapping[str, str] | None = None,
    snapshots: Mapping[str, Mapping[str, Any]] | None = None,
    intraday_observations: list[Mapping[str, Any]] | None = None,
    outcomes: list[Mapping[str, Any]] | None = None,
    formal_authority: Mapping[str, Any] | None = None,
    formal_candidate_ids: list[str] | None = None,
    manager_decision: Mapping[str, Any] | None = None,
    manager_decision_ref: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic ledger from explicitly supplied research cards."""
    from domains._research_day_product_parts.selection_assembly import _build_selection_research_product_body as _v4_impl
    return _v4_impl(globals(), source_date, target_trade_date, source_cards=source_cards, source_envelope=source_envelope, source_ref=source_ref, generated_at=generated_at, cutoff_at=cutoff_at, run_id=run_id, origin=origin, route_status=route_status, snapshots=snapshots, intraday_observations=intraday_observations, outcomes=outcomes, formal_authority=formal_authority, formal_candidate_ids=formal_candidate_ids, manager_decision=manager_decision, manager_decision_ref=manager_decision_ref)


def append_selection_phase(
    product: Mapping[str, Any],
    phase: str,
    *,
    run_id: str,
    event_at: str,
    artifact_sha256: str,
    changes: list[Mapping[str, Any]] | None = None,
    observation: Mapping[str, Any] | None = None,
    outcome: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one phase while preserving the immutable 08:30 freeze."""
    from domains._research_day_product_parts.phase_append import _append_selection_phase_body as _v4_impl
    return _v4_impl(globals(), product, phase, run_id=run_id, event_at=event_at, artifact_sha256=artifact_sha256, changes=changes, observation=observation, outcome=outcome)


__all__ = [
    "append_selection_phase",
    "build_authoritative_research_consumer",
    "build_research_day_product",
    "build_selection_research_product",
    "consume_authoritative_research_day",
    "event_stock_link_id",
    "normalize_pair_identity",
    "selection_candidate_id",
]
