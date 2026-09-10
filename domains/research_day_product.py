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

    if not isinstance(value, str) or not value:
        raise ValueError("missing published_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("invalid published_at") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("published_at must include timezone")
    return parsed.astimezone(_SHANGHAI)


def _variant(row: Mapping[str, Any]) -> dict[str, Any]:
    ignored = {
        "slot",
        "article_id",
        "dedupe_key",
        "source_dedup_keys",
        "duplicate_evidence_count",
        "published_at",
        "collected_at",
        "first_seen_at",
        "event_time",
        "source_published_at",
        "last_checked_at",
        "source_row_ref",
        "source_artifact_path",
        "source_artifact_sha256",
        "source_receipt_path",
        "source_receipt_sha256",
        "source_input_sha256",
        "identity_status",
    }
    return {str(key): value for key, value in row.items() if key not in ignored}


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
    ref = dict(source_ref or {})
    artifact_sha = _text(ref.get("artifact_sha256") or payload.get("artifact_sha256"))
    receipt_sha = _text(ref.get("receipt_sha256") or payload.get("receipt_sha256"))
    source_input_sha = _text(
        ref.get("source_input_sha256") or payload.get("source_input_sha256")
    )
    if not artifact_sha:
        artifact_sha = _sha256({"slot": slot, "payload": payload})
    if not receipt_sha:
        receipt_sha = _sha256({"slot": slot, "artifact_sha256": artifact_sha})
    if not source_input_sha:
        source_input_sha = _sha256(payload)
    return {
        "artifact_path": _text(
            ref.get("artifact_path")
            or f"research/hourly/live/{{date}}/{slot}.json"
        ),
        "artifact_sha256": artifact_sha.lower(),
        "receipt_path": _text(
            ref.get("receipt_path")
            or f"receipts/research/hourly/live/{{date}}/{slot}.json"
        ),
        "receipt_sha256": receipt_sha.lower(),
        "source_input_sha256": source_input_sha.lower(),
    }


def _changed_fields(row: Mapping[str, Any], winner: Mapping[str, Any]) -> list[str]:
    fields = sorted(
        key
        for key in set(_variant(row)) | set(_variant(winner))
        if _variant(row).get(key) != _variant(winner).get(key)
    )
    return fields


def _registry_projection(registry: Any) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    if not isinstance(registry, Mapping) or registry.get("status") != "VALIDATED":
        return (
            [],
            {
                "status": "CANNOT_CONFIRM",
                "rule_id": None,
                "registry": "MISSING",
                "cannot_confirm": _MISSING_REGISTRY_GAP,
            },
            [_MISSING_REGISTRY_GAP],
        )
    rule_id = _text(registry.get("rule_id"))
    rows = registry.get("high_priority")
    if not isinstance(rows, list) or not rule_id:
        return (
            [],
            {
                "status": "CANNOT_CONFIRM",
                "rule_id": rule_id or None,
                "registry": "MISSING",
                "cannot_confirm": _MISSING_REGISTRY_GAP,
            },
            [_MISSING_REGISTRY_GAP],
        )
    projected: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("rule_id") != rule_id:
            raise ValueError("high priority must carry the producer frozen rule_id")
        if "rank" not in row or "reason" not in row:
            raise ValueError("high priority requires producer rank and reason")
        projected.append(
            {
                "stock_code": _text(row.get("stock_code")),
                "rank": row["rank"],
                "reason": _text(row.get("reason")),
                "rule_id": rule_id,
                "recommendation_status": "RESEARCH_ONLY",
            }
        )
    return (
        sorted(projected, key=lambda row: (row["rank"], row["stock_code"])),
        {
            "status": "READY",
            "rule_id": rule_id,
            "registry": "VALIDATED",
            "cannot_confirm": None,
        },
        [],
    )


def _jyg_coverage(registry: Any) -> dict[str, Any]:
    """Project only explicitly supplied JYG observations; never infer them."""

    if not isinstance(registry, Mapping):
        observed: Mapping[str, Any] = {}
        status = "CANNOT_CONFIRM"
        registry_status = "MISSING"
    else:
        candidate = registry.get("jyg_coverage") or registry.get("observed")
        if isinstance(candidate, Mapping):
            observed = candidate
            status = "VALIDATED" if registry.get("status") == "VALIDATED" else "CANNOT_CONFIRM"
            registry_status = "VALIDATED" if status == "VALIDATED" else "MISSING"
        else:
            observed = {}
            status = "CANNOT_CONFIRM"
            registry_status = "MISSING"
    result = {
        "status": status,
        "articles": observed.get("articles") if type(observed.get("articles")) is int else None,
        "expected_articles": observed.get("expected_articles") if type(observed.get("expected_articles")) is int else None,
        "stock_mentions": observed.get("stock_mentions") if type(observed.get("stock_mentions")) is int else None,
        "registry": registry_status,
        "gap": None if status == "VALIDATED" else _MISSING_REGISTRY_GAP,
    }
    return result


def build_research_day_product(
    archive_date: str,
    slots: Mapping[str, Mapping[str, Any]],
    *,
    source_refs: Mapping[str, Mapping[str, Any]] | None = None,
    stock_mentions_registry: Mapping[str, Any] | None = None,
    transformer_identity_sha256: str | None = None,
) -> dict[str, Any]:
    """Build one day product from eight named, already materialized slots."""

    archive_date = _date(archive_date)
    if set(slots) != set(EXPECTED_RESEARCH_SLOTS):
        missing = sorted(set(EXPECTED_RESEARCH_SLOTS) - set(slots))
        extra = sorted(set(slots) - set(EXPECTED_RESEARCH_SLOTS))
        raise ValueError(f"research day requires exact slots missing={missing} extra={extra}")
    source_refs = source_refs or {}
    slot_matrix: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    exclusions = {"date_mismatch": 0, "pit_violation": 0, "invalid_row": 0}
    excluded_by_date: dict[str, int] = {}
    lineage_refs: dict[str, dict[str, Any]] = {}
    cannot_confirm: list[str] = []

    for slot in EXPECTED_RESEARCH_SLOTS:
        payload = slots[slot]
        if not isinstance(payload, Mapping):
            raise ValueError(f"research day slot {slot} is not an object")
        ref = _lineage_ref(slot, payload, source_refs.get(slot))
        ref["artifact_path"] = ref["artifact_path"].replace("{date}", archive_date)
        ref["receipt_path"] = ref["receipt_path"].replace("{date}", archive_date)
        lineage_refs[slot] = {
            **ref,
            "slot": slot,
            "source_input_sha256": ref["source_input_sha256"],
        }
        rows = _source_rows(payload)
        exact_count = 0
        for index, raw_row in enumerate(rows):
            if not isinstance(raw_row, Mapping):
                exclusions["invalid_row"] += 1
                cannot_confirm.append(f"INVALID_ROW:{slot}:{index}")
                continue
            row = dict(raw_row)
            try:
                published_at = _published_timestamp(row.get("published_at"))
            except ValueError:
                exclusions["invalid_row"] += 1
                cannot_confirm.append(f"PUBLISHED_AT_INVALID:{slot}:{index}")
                continue
            published_date = published_at.strftime("%Y%m%d")
            if published_date != archive_date:
                exclusions["date_mismatch"] += 1
                excluded_by_date[published_date] = excluded_by_date.get(published_date, 0) + 1
                continue
            row["archive_date"] = archive_date
            row["slot"] = slot
            row["source_row_ref"] = f"{slot}:{index}"
            row["source_artifact_path"] = ref["artifact_path"]
            row["source_artifact_sha256"] = ref["artifact_sha256"]
            row["source_receipt_path"] = ref["receipt_path"]
            row["source_receipt_sha256"] = ref["receipt_sha256"]
            row["source_input_sha256"] = ref["source_input_sha256"]
            if normalize_pair_identity(
                row.get("url") or row.get("source_url"),
                row.get("stock_code") or row.get("code"),
            ) is None:
                row["identity_status"] = "URL_REQUIRED/CANNOT_CONFIRM"
            else:
                row["identity_status"] = "READY"
            evidence_rows.append(row)
            exact_count += 1
        slot_matrix.append(
            {
                "slot": slot,
                "status": "READY",
                "raw_rows": len(rows),
                "exact_rows": exact_count,
                "excluded_rows": len(rows) - exact_count,
                "artifact_path": ref["artifact_path"],
                "artifact_sha256": ref["artifact_sha256"],
                "receipt_path": ref["receipt_path"],
                "receipt_sha256": ref["receipt_sha256"],
                "source_input_sha256": ref["source_input_sha256"],
            }
        )

    evidence_rows.sort(key=lambda row: (_slot_number(row["slot"]), row["source_row_ref"]))
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence_rows:
        pair_key = normalize_pair_identity(
            row.get("url") or row.get("source_url"),
            row.get("stock_code") or row.get("code"),
        )
        if pair_key is None:
            cannot_confirm.append("URL_REQUIRED/CANNOT_CONFIRM")
            continue
        row["_variant_sha256"] = _sha256(_variant(row))
        groups[pair_key].append(row)

    mention_pairs: list[dict[str, Any]] = []
    stock_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair_key in sorted(groups):
        rows = groups[pair_key]
        winner = sorted(
            rows,
            key=lambda row: (
                -_level_rank(row.get("evidence_level")),
                -_slot_number(row.get("slot")),
                -_confidence_rank(row.get("confidence")),
                -len(_text(row.get("evidence_sentence"))),
                row["_variant_sha256"],
            ),
        )[0]
        for row in rows:
            row["changed_fields"] = _changed_fields(row, winner)
        variants = sorted({row["_variant_sha256"] for row in rows})
        source_slots = sorted({row["slot"] for row in rows})
        code = unicodedata.normalize(
            "NFKC", _text(winner.get("stock_code") or winner.get("code"))
        ).upper()
        pair = {
            "pair_key": pair_key,
            "normalized_url": unicodedata.normalize(
                "NFKC", _text(winner.get("url") or winner.get("source_url"))
            ),
            "stock_code": code,
            "stock_name": _text(winner.get("stock_name") or winner.get("name")),
            "winner": {
                key: value
                for key, value in winner.items()
                if not key.startswith("_")
            },
            "source_slots": source_slots,
            "occurrence_count": len(rows),
            "variant_count": len(variants),
            "article_ids": sorted(
                {
                    _text(row.get("article_id") or row.get("evidence_id"))
                    for row in rows
                    if _text(row.get("article_id") or row.get("evidence_id"))
                }
            ),
            "dedupe_keys": sorted(
                {
                    _text(row.get("dedupe_key"))
                    for row in rows
                    if _text(row.get("dedupe_key"))
                }
            ),
            "source_refs": [
                _source_ref(row)
                for row in sorted(rows, key=lambda item: item["source_row_ref"])
            ],
            "duplicate_reason": (
                "UNIQUE"
                if len(rows) == 1
                else "CROSS_SLOT_REPEAT"
                if len(source_slots) > 1
                else "INTRA_SLOT_REPEAT"
            ),
            "tiebreaker": {
                "evidence_level": _text(winner.get("evidence_level")) or "UNKNOWN",
                "slot": winner["slot"],
                "confidence": _text(winner.get("confidence")) or "UNKNOWN",
                "evidence_sentence_length": len(
                    _text(winner.get("evidence_sentence"))
                ),
                "variant_sha256": winner["_variant_sha256"],
                "order": [
                    "evidence_level",
                    "slot",
                    "confidence",
                    "evidence_sentence_length_desc",
                    "variant_sha256_asc",
                ],
            },
            "recommendation_status": "RESEARCH_ONLY",
        }
        mention_pairs.append(pair)
        stock_groups[code].append(pair)

    stock_rollups = []
    for code in sorted(stock_groups):
        pairs = stock_groups[code]
        stock_rollups.append(
            {
                "stock_code": code,
                "stock_name": _text(pairs[0].get("stock_name")),
                "mention_pair_count": len(pairs),
                "evidence_row_count": sum(
                    int(pair["occurrence_count"]) for pair in pairs
                ),
                "source_slots": sorted(
                    {slot for pair in pairs for slot in pair["source_slots"]}
                ),
                "urls": sorted({pair["normalized_url"] for pair in pairs}),
                "pair_keys": [pair["pair_key"] for pair in pairs],
                "duplicate_pair_count": sum(
                    1 for pair in pairs if pair["occurrence_count"] > 1
                ),
                "recommendation_status": "RESEARCH_ONLY",
            }
        )

    high_priority, high_status, registry_gaps = _registry_projection(
        stock_mentions_registry
    )
    cannot_confirm.extend(registry_gaps)
    jyg_coverage = _jyg_coverage(stock_mentions_registry)
    if jyg_coverage["gap"]:
        cannot_confirm.append(str(jyg_coverage["gap"]))
    cannot_confirm = sorted(set(cannot_confirm))
    transformer = (
        transformer_identity_sha256
        if transformer_identity_sha256
        else _sha256({"contract_id": CONTRACT_ID, "workflow_name": WORKFLOW_NAME})
    )
    if len(transformer) != 64:
        raise ValueError("research day transformer identity must be SHA-256")

    counts = {
        "raw_rows": sum(row["raw_rows"] for row in slot_matrix),
        "evidence_rows": len(evidence_rows),
        "excluded_rows": sum(row["excluded_rows"] for row in slot_matrix),
        "mention_pairs": len(mention_pairs),
        "urls": len({pair["normalized_url"] for pair in mention_pairs}),
        "stock_rollups": len(stock_rollups),
        "high_priority": len(high_priority),
        "duplicate_pairs": sum(
            1 for pair in mention_pairs if pair["occurrence_count"] > 1
        ),
    }
    lineage = {
        "source_refs": lineage_refs,
        "artifact_sha256": _sha256(
            {
                "archive_date": archive_date,
                "evidence_rows": evidence_rows,
                "mention_pairs": mention_pairs,
                "stock_rollups": stock_rollups,
                "excluded_by_date": excluded_by_date,
                "jyg_coverage": jyg_coverage,
            }
        ),
        "manifest_sha256": _sha256(slot_matrix),
        "receipt_sha256": _sha256(lineage_refs),
        "current_sha256": None,
        "transformer_identity_sha256": transformer,
    }
    product = {
        "schema_version": PRODUCT_SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "workflow_name": WORKFLOW_NAME,
        "pass_signal": PASS_SIGNAL,
        "archive_date": archive_date,
        "timezone": TIMEZONE,
        "date_mode": DATE_MODE,
        "status": "READY_WITH_DECLARED_GAPS" if cannot_confirm else "READY",
        "authoritative": not cannot_confirm and high_status["status"] == "READY",
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "expected_slots": list(EXPECTED_RESEARCH_SLOTS),
        "coverage": {
            "expected_slots": len(EXPECTED_RESEARCH_SLOTS),
            "ready_slots": len(slot_matrix),
            "missing_slots": [],
            "complete": True,
            "slot_matrix": slot_matrix,
        },
        "counts": counts,
        "exclusions": exclusions,
        "excluded_by_date": dict(sorted(excluded_by_date.items())),
        "slot_matrix": slot_matrix,
        "evidence_rows": [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in evidence_rows
        ],
        "mention_pairs": mention_pairs,
        "stock_rollups": stock_rollups,
        "high_priority": high_priority,
        "high_priority_status": high_status,
        "jyg_coverage": jyg_coverage,
        "lineage": lineage,
        "cannot_confirm": cannot_confirm,
        **SAFETY_FLAGS,
    }
    validate_research_day_product(product)
    return product


def consume_authoritative_research_day(
    product: Mapping[str, Any] | None,
    *,
    requested_date: str,
) -> dict[str, Any]:
    """White-hair consumer: exact-date and authoritative-only, fail closed."""

    requested_date = _date(requested_date)
    if product is None:
        return _consumer_gap(
            requested_date,
            f"RESEARCH_DAY_PRODUCT_NOT_MATERIALIZED:{requested_date}",
        )
    try:
        validated_date = validate_research_day_product(product)
    except ValueError as error:
        return _consumer_gap(
            requested_date,
            f"RESEARCH_DAY_PRODUCT_INVALID:{error}",
        )
    if (
        validated_date != requested_date
        or product.get("status") != "READY"
        or not product.get("authoritative")
    ):
        return _consumer_gap(
            requested_date,
            str(
                (product.get("cannot_confirm") or [
                    f"RESEARCH_DAY_NOT_AUTHORITATIVE:{requested_date}"
                ])[0]
            ),
            resolved_date=validated_date if validated_date == requested_date else None,
        )
    return dict(product)


def _consumer_gap(
    requested_date: str,
    reason: str,
    *,
    resolved_date: str | None = None,
) -> dict[str, Any]:
    """Return a complete diagnostic envelope without exposing a non-authority pool."""

    empty_coverage = {
        "expected_slots": len(EXPECTED_RESEARCH_SLOTS),
        "ready_slots": 0,
        "missing_slots": list(EXPECTED_RESEARCH_SLOTS),
        "complete": False,
        "slot_matrix": [],
    }
    return {
        "schema_version": PRODUCT_SCHEMA_VERSION,
        "contract_id": CONTRACT_ID,
        "workflow_name": WORKFLOW_NAME,
        "pass_signal": PASS_SIGNAL,
        "status": "CANNOT_CONFIRM",
        "authoritative": False,
        "endpoint_mode": "EXACT",
        "date_mode": DATE_MODE,
        "archive_date": requested_date,
        "requested_date": requested_date,
        "resolved_date": resolved_date,
        "timezone": TIMEZONE,
        "is_full_day": True,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "expected_slots": list(EXPECTED_RESEARCH_SLOTS),
        "coverage": empty_coverage,
        "counts": {
            "raw_rows": 0,
            "evidence_rows": 0,
            "excluded_rows": 0,
            "mention_pairs": 0,
            "urls": 0,
            "stock_rollups": 0,
            "high_priority": 0,
            "duplicate_pairs": 0,
        },
        "exclusions": {
            "date_mismatch": 0,
            "pit_violation": 0,
            "invalid_row": 0,
        },
        "excluded_by_date": {},
        "slot_matrix": [],
        "evidence_rows": [],
        "mention_pairs": [],
        "stock_rollups": [],
        "high_priority": [],
        "high_priority_status": {
            "status": "CANNOT_CONFIRM",
            "rule_id": None,
            "registry": "MISSING",
            "cannot_confirm": "JYG_STOCK_MENTIONS_REGISTRY_MISSING",
        },
        "jyg_coverage": {
            "status": "CANNOT_CONFIRM",
            "articles": None,
            "expected_articles": None,
            "stock_mentions": None,
            "registry": "MISSING",
            "gap": _MISSING_REGISTRY_GAP,
        },
        "lineage": None,
        "cannot_confirm": [reason],
        "loading_complete": True,
        **SAFETY_FLAGS,
    }


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

    values = [
        unicodedata.normalize("NFKC", str(value or "").strip())
        for value in (market, normalized_code, entity_id)
    ]
    if any(not value for value in values):
        raise ValueError("selection candidate identity is incomplete")
    if any("|" in value for value in values[:2]):
        raise ValueError("selection candidate identity contains a separator")
    return f"{values[0].upper()}.{values[1].upper()}|{values[2]}"


def event_stock_link_id(event_id: Any, candidate_id: Any) -> str:
    """Return a stable event-to-stock link distinct from candidate identity."""

    event = str(event_id or "").strip()
    candidate = str(candidate_id or "").strip()
    if not event or not candidate:
        raise ValueError("selection event-stock link is incomplete")
    return f"{event}|{candidate}"


def _selection_aware_hkt(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith(" HKT"):
        try:
            parsed = datetime.strptime(raw[:-4], "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        return parsed.replace(tzinfo=_SHANGHAI).isoformat()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(_SHANGHAI).isoformat()


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
    if not isinstance(source_ref, Mapping):
        raise ValueError("selection card source reference is required")
    result = dict(source_ref)
    source_type = result.get("type", "EARLY_DRAFT_FROZEN_ENVELOPE")
    result.setdefault("type", source_type)
    result.setdefault("source_date", source_date)
    if source_type == RESEARCH_SUPPLY_TYPE:
        # New supply refs are a closed locator contract.  Do not add the
        # legacy denormalized source fields: the selected card and its raw
        # envelope are the source of truth and are verified by the store.
        if set(result) != {
            "type",
            "path",
            "raw_sha256",
            "frozen_payload_sha256",
            "json_pointer",
            "source_date",
            "source_time",
            "supply_receipt_path",
            "supply_receipt_sha256",
        }:
            raise ValueError("research supply source reference fields are invalid")
        return result
    else:
        source = card.get("source") if isinstance(card.get("source"), Mapping) else {}
        result.setdefault("official_url", source.get("official_url", ""))
        result.setdefault("published_at", source.get("published_at", ""))
        result.setdefault("source_status", source.get("status", ""))
    if not result.get("source_time"):
        raise ValueError("selection card source_time is required")
    return result


def _selection_entity_parts(
    entry: Mapping[str, Any],
    card: Mapping[str, Any],
    *,
    supply_source: bool,
) -> tuple[str, str, str]:
    entity = _text(entry.get("entity_id"))
    if not entity:
        if supply_source:
            entity = _text(card.get("ticker"))
    if not entity:
        entities = card.get("entities")
        if not isinstance(entities, list) or len(entities) != 1:
            raise ValueError("selection card must identify one entity")
        entity = _text(entities[0])
    explicit_market = _text(entry.get("market"))
    explicit_code = _text(entry.get("normalized_code"))
    if explicit_market and explicit_code:
        return explicit_market, explicit_code, entity
    if "." not in entity:
        raise ValueError("selection entity must include market suffix")
    code, market = entity.rsplit(".", 1)
    if not code or not market:
        raise ValueError("selection entity identity is incomplete")
    return market, code, entity


def _selection_candidate(
    entry: Mapping[str, Any],
    *,
    source_date: str,
    cutoff_at: str,
    route_status: Mapping[str, str],
) -> dict[str, Any]:
    card_value = entry.get("card", entry)
    if not isinstance(card_value, Mapping):
        raise ValueError("selection card is not an object")
    card = card_value
    event_id = _text(entry.get("event_id") or card.get("event_id"))
    if not event_id:
        raise ValueError("selection card event_id is missing")
    source_ref_value = entry.get("source_ref")
    if source_ref_value is None:
        refs = entry.get("source_refs")
        if isinstance(refs, list) and refs:
            source_ref_value = refs[0]
    source_ref = _selection_source_ref(card, source_ref_value, source_date=source_date)
    supply_source = source_ref.get("type") == RESEARCH_SUPPLY_TYPE
    market, code, entity = _selection_entity_parts(
        entry,
        card,
        supply_source=supply_source,
    )
    candidate = selection_candidate_id(market, code, entity)
    if supply_source:
        source = card.get("official_source") if isinstance(card.get("official_source"), Mapping) else {}
        status = _text(source.get("identity_status"))
    else:
        source = card.get("source") if isinstance(card.get("source"), Mapping) else {}
        status = _text(entry.get("source_status") or source.get("status"))
    if supply_source:
        if not status or status.upper() in {
            "UNKNOWN",
            "UNVERIFIED",
            "CANNOT_CONFIRM",
            "NOT_MATERIALIZED",
        }:
            status = "UNVERIFIED"
    elif not status:
        # Preserve legacy producer status strings byte-for-byte.  Only a
        # genuinely absent legacy status receives the historical fallback.
        status = "UNVERIFIED"
    gemini_status = _text(entry.get("gemini_status")) or (
        "UNVERIFIED" if "GEMINI" in status.upper() else route_status["GEMINI"]
    )
    if gemini_status not in {"UNVERIFIED", "NOT_MATERIALIZED"}:
        gemini_status = "UNVERIFIED"
    if supply_source:
        candidate_routes = {
            "R1": route_status["R1"],
            "R6": route_status["R6"],
        }
    else:
        candidate_routes = {
            "R1": _text(entry.get("r1_status"))
            or (
                "VERIFIED_SOURCE_IDENTITY"
                if "VERIFIED_SOURCE_IDENTITY" in status.upper()
                else route_status["R1"]
            ),
            "R6": _text(entry.get("r6_status")) or route_status["R6"],
        }
    if candidate_routes["R6"] == "GEMINI_DISCOVERY_UNVERIFIED":
        raise ValueError("selection R6 is not a Gemini alias")
    eligibility = entry.get("eligibility")
    if eligibility is None:
        eligibility = card.get("eligibility_status") if supply_source else card.get("eligibility")
    if isinstance(eligibility, Mapping):
        raw_eligibility_status = _text(eligibility.get("status"))
    elif isinstance(eligibility, str):
        raw_eligibility_status = eligibility.strip()
    else:
        raw_eligibility_status = ""
    eligibility_status = (
        raw_eligibility_status
        if raw_eligibility_status in {"ELIGIBILITY_CANNOT_CONFIRM", "ELIGIBLE"}
        else "ELIGIBILITY_CANNOT_CONFIRM"
    )
    if supply_source:
        published_at_value = card.get("published_at")
        if published_at_value is None:
            published_at_value = source.get("published_at")
        published_at = _selection_value_text(published_at_value)
    else:
        published_at = _text(
            entry.get("published_at")
            or source.get("published_at")
        )
    source_time = _text(source_ref.get("source_time"))
    published_aware = _selection_aware_hkt(published_at)
    try:
        cutoff_value = datetime.fromisoformat(cutoff_at.replace("Z", "+00:00"))
        source_value = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
    except ValueError:
        cutoff_value = None
        source_value = None
    if cutoff_value is None or source_value is None or source_value.tzinfo is None or source_value.utcoffset() is None:
        pit_status = "CANNOT_CONFIRM"
    elif published_aware is None:
        pit_status = "CANNOT_CONFIRM"
    else:
        published_value = datetime.fromisoformat(published_aware)
        pit_status = (
            "READY"
            if published_value.astimezone(_SHANGHAI) <= cutoff_value.astimezone(_SHANGHAI)
            and (
                supply_source
                or source_value.astimezone(_SHANGHAI) <= cutoff_value.astimezone(_SHANGHAI)
            )
            else "PIT_FAILED"
        )
    explicit_pit = _text(entry.get("pit_status") or (None if supply_source else card.get("pit_status")))
    if explicit_pit in {"PIT_FAILED", "CANNOT_CONFIRM"}:
        pit_status = explicit_pit
    value_text = _selection_value_text if supply_source else _text
    return {
        "candidate_id": candidate,
        "event_stock_link_id": event_stock_link_id(event_id, candidate),
        "market": unicodedata.normalize("NFKC", market.strip()).upper(),
        "normalized_code": unicodedata.normalize("NFKC", code.strip()).upper(),
        "entity_id": entity,
        "event_id": event_id,
        "bucket": value_text(entry.get("bucket") if entry.get("bucket") is not None else card.get("bucket")),
        "catalyst": value_text(entry.get("catalyst") if entry.get("catalyst") is not None else card.get("catalyst")),
        "counterevidence": value_text(entry.get("counterevidence") if entry.get("counterevidence") is not None else card.get("counterevidence")),
        "invalidation": value_text(entry.get("invalidation") if entry.get("invalidation") is not None else card.get("invalidation")),
        "evidence_level": value_text(entry.get("evidence_level") if entry.get("evidence_level") is not None else card.get("evidence_level")),
        "financial_bridge": value_text(entry.get("financial_bridge") if entry.get("financial_bridge") is not None else card.get("financial_bridge")),
        "consensus": value_text(entry.get("consensus") if entry.get("consensus") is not None else card.get("consensus")),
        "overnight_pending": value_text(entry.get("overnight_pending") if entry.get("overnight_pending") is not None else card.get("overnight_pending")),
        "source_metadata": (
            {"supply_card": deepcopy(dict(card))}
            if supply_source
            else dict(source)
        ),
        "source_status": status,
        "published_at": published_at,
        "published_at_aware": published_aware,
        "source_time": source_time,
        "acceptance": (
            RESEARCH_SUPPLY_ACCEPTANCE
            if supply_source
            else "EARLY_DRAFT_FROZEN_ONLY"
        ),
        "eligibility": eligibility_status,
        "pit_status": pit_status,
        "research_status": "RESEARCH_ONLY",
        "recommendation_status": "RESEARCH_ONLY",
        "route_status": candidate_routes,
        "gemini_status": gemini_status,
        "source_refs": [source_ref],
    }


def _selection_snapshot(
    phase: str,
    value: Mapping[str, Any] | None,
    *,
    candidate_ids: list[str],
) -> dict[str, Any]:
    supplied_candidate_ids = (
        isinstance(value, Mapping) and "candidate_ids" in value
    )
    base: dict[str, Any] = {
        "phase": phase,
        "status": "NOT_MATERIALIZED",
        "run_id": None,
        "event_at": None,
        "artifact_sha256": None,
        "candidate_ids": [],
        "changes": [],
        "freeze_run_id": None,
        "freeze_snapshot_sha256": None,
        "snapshot_sha256": None,
    }
    if isinstance(value, Mapping):
        base.update(dict(value))
    base["phase"] = phase
    base["candidate_ids"] = sorted(set(base.get("candidate_ids") or []))
    base["changes"] = list(base.get("changes") or [])
    if base["status"] == "READY":
        if not supplied_candidate_ids:
            base["candidate_ids"] = list(candidate_ids)
        body = {key: item for key, item in base.items() if key != "snapshot_sha256"}
        calculated = _sha256(body)
        if base.get("snapshot_sha256") is not None and base["snapshot_sha256"] != calculated:
            raise ValueError(f"selection {phase} snapshot SHA mismatch")
        base["snapshot_sha256"] = calculated
    else:
        base.update(
            {
                    "status": base["status"],
                    "run_id": None,
                    "event_at": None,
                    "artifact_sha256": None,
                    "candidate_ids": [],
                "changes": [],
                "freeze_run_id": None,
                "freeze_snapshot_sha256": None,
                "snapshot_sha256": None,
            }
        )
    return base


def _selection_formal_authority(
    value: Mapping[str, Any] | None,
    *,
    target_trade_date: str,
) -> dict[str, Any]:
    default = {
        "status": "NOT_MATERIALIZED",
        "target_trade_date": target_trade_date,
        "pit_status": "CANNOT_CONFIRM",
        "selector_status": "CANNOT_CONFIRM",
        "research_evidence": False,
        "manager_decision": False,
        "source_sha256": None,
        "evidence_refs": [],
        "manager_decision_ref": None,
    }
    if not isinstance(value, Mapping):
        return default
    result = {**default, **dict(value)}
    if result.get("target_trade_date") != target_trade_date:
        result["status"] = "STALE"
        result["target_trade_date"] = target_trade_date
        result["pit_status"] = "CANNOT_CONFIRM"
        result["selector_status"] = "CANNOT_CONFIRM"
        result["research_evidence"] = False
        result["manager_decision"] = False
        result["source_sha256"] = None
    if result.get("status") == "READY" and not (
        result.get("pit_status") == "READY"
        and result.get("selector_status") == "READY"
        and result.get("research_evidence") is True
        and result.get("manager_decision") is True
        and _selection_hash_text(result.get("source_sha256"))
        and isinstance(result.get("evidence_refs"), list)
        and bool(result.get("evidence_refs"))
        and isinstance(result.get("manager_decision_ref"), Mapping)
    ):
        result["status"] = "CANNOT_CONFIRM"
    return result


def _selection_formal_refs_bind_candidates(
    authority: Mapping[str, Any],
    candidate_ids: list[str],
) -> bool:
    """Check the pure shape of candidate proof before requesting promotion."""

    if not candidate_ids:
        return False
    refs = list(authority.get("evidence_refs") or [])
    decision = authority.get("manager_decision_ref")
    if not refs or not isinstance(decision, Mapping):
        return False
    for ref in [*refs, decision]:
        bindings = ref.get("candidate_bindings")
        if not isinstance(bindings, list) or [
            binding.get("candidate_id")
            for binding in bindings
            if isinstance(binding, Mapping)
        ] != candidate_ids:
            return False
        for binding in bindings:
            if not isinstance(binding, Mapping):
                return False
            if (
                binding.get("eligibility") != "ELIGIBLE"
                or binding.get("pit_status") != "READY"
                or not isinstance(binding.get("source_refs"), list)
                or not binding["source_refs"]
            ):
                return False
    return True


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

    source_date = _date(source_date)
    target_trade_date = _date(target_trade_date)
    supply_envelope = (
        source_envelope
        if isinstance(source_envelope, Mapping)
        and source_envelope.get("type") == RESEARCH_SUPPLY_TYPE
        else None
    )
    if isinstance(source_envelope, Mapping) and source_envelope.get("type") not in {
        None,
        RESEARCH_SUPPLY_TYPE,
    }:
        raise ValueError("selection source envelope type is unsupported")
    if supply_envelope is not None:
        validate_research_supply_envelope(
            supply_envelope,
            expected_source_date=source_date,
            expected_target_trade_date=target_trade_date,
        )
        supply_run_id = str(supply_envelope.get("run_id") or "")
        supplied_snapshots = snapshots if isinstance(snapshots, Mapping) else {}
        ready_later = [
            phase
            for phase in ("0830", "0935", "1620")
            if isinstance(supplied_snapshots.get(phase), Mapping)
            and supplied_snapshots[phase].get("status") == "READY"
        ]
        expected_run_id = (
            str(supplied_snapshots[ready_later[-1]].get("run_id") or "")
            if ready_later
            else supply_run_id
        )
        if run_id != expected_run_id:
            raise ValueError("research supply product run must bind to source or latest phase")
        if manager_decision is None and str(cutoff_at) != str(supply_envelope["cutoff_at"]):
            raise ValueError("research supply source-only cutoff must bind to supply envelope")
        if manager_decision is None and manager_decision_ref is not None:
            raise ValueError("manager decision reference requires a decision document")
    elif manager_decision is not None or manager_decision_ref is not None:
        raise ValueError("manager decision requires a research supply envelope")
    if not source_cards and isinstance(source_envelope, Mapping):
        frozen = source_envelope.get("frozen_payload")
        cards = frozen.get("event_cards") if isinstance(frozen, Mapping) else None
        if isinstance(cards, list):
            if not isinstance(source_ref, Mapping):
                if len(cards) != 1:
                    raise ValueError(
                        "selection source envelope requires one explicit card reference"
                    )
                source_cards = [{"card": cards[0], "source_ref": source_ref}]
            else:
                pointer = source_ref.get("json_pointer")
                prefix = "/frozen_payload/event_cards/"
                index_text = (
                    pointer[len(prefix) :]
                    if isinstance(pointer, str) and pointer.startswith(prefix)
                    else ""
                )
                if not index_text.isdigit() or str(int(index_text)) != index_text:
                    raise ValueError(
                        "selection source envelope reference must target one event card"
                    )
                index = int(index_text)
                if index >= len(cards) or not isinstance(cards[index], Mapping):
                    raise ValueError("selection source envelope card reference is missing")
                source_cards = [{"card": cards[index], "source_ref": source_ref}]
    source_cards = list(source_cards or [])
    if supply_envelope is not None:
        envelope_route = supply_envelope["frozen_payload"]["route_status"]
        route = {
            "R1": str(envelope_route["R1"]),
            "R2": str(envelope_route["R2"]),
            "R6": str(envelope_route["R6"]),
            "GEMINI": "UNVERIFIED",
        }
        if route_status:
            supplied_route = {str(key): str(value) for key, value in route_status.items()}
            for key in ("R1", "R2", "R6"):
                if key in supplied_route and supplied_route[key] != route[key]:
                    raise ValueError("research supply route status does not reconcile")
            if "GEMINI" in supplied_route and supplied_route["GEMINI"] not in {
                "UNVERIFIED",
                "NOT_MATERIALIZED",
            }:
                raise ValueError("research supply Gemini route is unverified only")
    else:
        route = dict(_SELECTION_DEFAULT_ROUTE_STATUS)
        if route_status:
            route.update({str(key): str(value) for key, value in route_status.items()})
    if set(route) != set(_SELECTION_DEFAULT_ROUTE_STATUS):
        raise ValueError("selection route status fields are incomplete")
    if any("GEMINI" in str(value).upper() for value in route.values() if value):
        # Gemini is represented only by the independent GEMINI field.
        route["GEMINI"] = "UNVERIFIED"
    candidates = sorted(
        [
            _selection_candidate(
                entry,
                source_date=source_date,
                cutoff_at=cutoff_at,
                route_status=route,
            )
            for entry in source_cards
        ],
        key=lambda row: row["candidate_id"],
    )
    candidate_ids = [row["candidate_id"] for row in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("selection candidate identity collision")
    if candidates and route["GEMINI"] == "NOT_MATERIALIZED":
        route["GEMINI"] = "UNVERIFIED"
    for candidate in candidates:
        # Keep per-card route evidence; do not promote a global route from a
        # non-empty ledger.  Gemini remains its own unverified channel.
        candidate["gemini_status"] = candidate.get("gemini_status") or route["GEMINI"]
    source_refs = [ref for candidate in candidates for ref in candidate["source_refs"]]
    if manager_decision is not None and manager_decision_ref is None:
        raise ValueError("manager decision reference is required")
    if manager_decision_ref is not None:
        if supply_envelope is None or manager_decision is None:
            raise ValueError("manager decision reference requires a supply decision")
        if (
            not isinstance(manager_decision_ref, Mapping)
            or set(manager_decision_ref) != {"path", "raw_sha256"}
            or not isinstance(manager_decision_ref.get("path"), str)
            or not manager_decision_ref["path"]
            or _selection_hash_text(manager_decision_ref.get("raw_sha256")) is None
        ):
            raise ValueError("manager decision reference is invalid")
    if manager_decision is not None:
        if supply_envelope is None:
            raise ValueError("manager decision requires a research supply envelope")
        validate_manager_research_decision(
            manager_decision,
            candidate_ids=candidate_ids,
            supply_envelope=supply_envelope,
        )
        if str(cutoff_at) != str(manager_decision["cutoff_at"]):
            raise ValueError("research supply product cutoff must bind to manager decision")
        decision_ids = sorted(
            [
                row["candidate_id"]
                for row in [
                    *manager_decision["core"],
                    *manager_decision["conditional"],
                ]
            ]
        )
        decision_snapshot = {
            "phase": "2200",
            "status": "READY",
            "run_id": manager_decision["run_id"],
            "event_at": manager_decision["generated_at"],
            "artifact_sha256": manager_decision_ref["raw_sha256"],
            "candidate_ids": decision_ids,
            "changes": [],
            "freeze_run_id": None,
            "freeze_snapshot_sha256": None,
            "snapshot_sha256": None,
        }
        supplied_2200 = (snapshots or {}).get("2200") if snapshots else None
        if isinstance(supplied_2200, Mapping) and supplied_2200.get("status") == "READY":
            if (
                supplied_2200.get("run_id") != decision_snapshot["run_id"]
                or sorted(supplied_2200.get("candidate_ids") or []) != decision_ids
            ):
                raise ValueError("manager decision does not reconcile with 2200 snapshot")
        decision_projection: dict[str, dict[str, Any]] = {}
        for role, field in (("CORE", "core"), ("CONDITIONAL", "conditional")):
            for order, row in enumerate(manager_decision[field], 1):
                decision_projection[row["candidate_id"]] = {
                    "schema_version": manager_decision["schema_version"],
                    "phase": manager_decision["phase"],
                    "decision_state": manager_decision["decision_state"],
                    "source_date": manager_decision["source_date"],
                    "target_trade_date": manager_decision["target_trade_date"],
                    "run_id": manager_decision["run_id"],
                    "generated_at": manager_decision["generated_at"],
                    "cutoff_at": manager_decision["cutoff_at"],
                    "role": role,
                    "order": order,
                    "reason": row["reason"],
                }
        for candidate in candidates:
            metadata = candidate.get("source_metadata")
            if not isinstance(metadata, Mapping) or not isinstance(metadata.get("supply_card"), Mapping):
                raise ValueError("manager decision projection requires a supply card")
            projection = decision_projection.get(candidate["candidate_id"])
            if projection is not None:
                # Keep the frozen supply card byte-for-byte equivalent to its
                # source envelope.  The typed manager role is a derived
                # candidate projection, never part of source_metadata.
                candidate["manager_decision"] = projection
        snapshots = {**dict(snapshots or {}), "2200": decision_snapshot}
    snapshot_map = {
        phase: _selection_snapshot(
            phase,
            (snapshots or {}).get(phase),
            candidate_ids=candidate_ids,
        )
        for phase in SELECTION_PHASES
    }
    observations = [dict(item) for item in (intraday_observations or [])]
    outcome_rows = [dict(item) for item in (outcomes or [])]
    formal = _selection_formal_authority(
        formal_authority,
        target_trade_date=target_trade_date,
    )
    requested_formal = sorted(set(formal_candidate_ids or []))
    formal_ids = (
        requested_formal
        if formal["status"] == "READY"
        and _selection_formal_refs_bind_candidates(formal, requested_formal)
        and all(candidate_id in candidate_ids for candidate_id in requested_formal)
        and all(
            candidate["pit_status"] == "READY"
            and candidate["eligibility"] == "ELIGIBLE"
            for candidate in candidates
            if candidate["candidate_id"] in requested_formal
        )
        else []
    )
    cannot_confirm: list[str] = []
    for phase, snapshot in snapshot_map.items():
        if snapshot["status"] != "READY":
            cannot_confirm.append(
                "SUPPLY_2200_DECISION_NOT_MATERIALIZED"
                if supply_envelope is not None and phase == "2200"
                else f"SNAPSHOT_{phase}_NOT_MATERIALIZED"
            )
    if formal["status"] != "READY" or not formal_ids:
        cannot_confirm.append("FORMAL_AUTHORITY_NOT_MATERIALIZED")
    if any(candidate["pit_status"] != "READY" for candidate in candidates):
        cannot_confirm.append("CANDIDATE_PIT_NOT_CONFIRMED")
    cannot_confirm = sorted(set(cannot_confirm))
    status = "NOT_MATERIALIZED" if not candidates else (
        RESEARCH_SUPPLY_STATUS
        if supply_envelope is not None
        and all(snapshot_map[phase]["status"] != "READY" for phase in SELECTION_PHASES)
        else (
            "EARLY_DRAFT_IMPORTED"
            if all(snapshot_map[phase]["status"] != "READY" for phase in SELECTION_PHASES)
            else ("READY" if not cannot_confirm else "READY_WITH_DECLARED_GAPS")
        )
    )
    acceptance = (
        RESEARCH_SUPPLY_ACCEPTANCE
        if supply_envelope is not None and candidates
        else ("EARLY_DRAFT_FROZEN_ONLY" if candidates else "NOT_MATERIALIZED")
    )
    first_failed = cannot_confirm[0] if cannot_confirm else None
    product = {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "contract_id": SELECTION_CONTRACT_ID,
        "workflow_name": SELECTION_WORKFLOW_NAME,
        "pass_signal": SELECTION_PASS_SIGNAL,
        "source_date": source_date,
        "target_trade_date": target_trade_date,
        "timezone": TIMEZONE,
        "cutoff_at": cutoff_at,
        "generated_at": generated_at,
        "run_id": run_id,
        "origin": origin,
        "status": status,
        "acceptance": acceptance,
        "research_candidates": candidates,
        "formal_shortlist": formal_ids,
        "snapshots": snapshot_map,
        "intraday_observations": observations,
        "outcomes": outcome_rows,
        "counts": {
            "research_candidates": len(candidates),
            "formal_shortlist": len(formal_ids),
            "snapshots": len(SELECTION_PHASES),
            "intraday_observations": len(observations),
            "outcomes": len(outcome_rows),
        },
        "route_status": route,
        "gemini_status": route["GEMINI"],
        "formal_authority": formal,
        "source_refs": source_refs,
        "first_failed_layer": first_failed,
        "cannot_confirm": cannot_confirm,
        **SAFETY_FLAGS,
    }
    if manager_decision_ref is not None:
        product["manager_decision_ref"] = dict(manager_decision_ref)
    validate_selection_research_product(product)
    return product


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

    validate_selection_research_product(product)
    if phase not in SELECTION_PHASES or phase == "2200":
        raise ValueError("selection append phase must be 0830, 0935 or 1620")
    result = deepcopy(dict(product))
    snapshots = result["snapshots"]
    candidate_ids = [row["candidate_id"] for row in result["research_candidates"]]
    candidate_set = set(candidate_ids)

    def validate_changes(
        values: list[Mapping[str, Any]] | None,
        *,
        current_ids: set[str] | None = None,
    ) -> tuple[list[Mapping[str, Any]], set[str]]:
        rows = list(values or [])
        seen: set[str] = set()
        working = set(current_ids if current_ids is not None else candidate_set)
        for change in rows:
            if not isinstance(change, Mapping):
                raise ValueError("selection phase change must be an object")
            action = _text(change.get("action")).upper()
            candidate_id = _text(change.get("candidate_id"))
            if action not in {"KEEP", "ADD", "REMOVE"}:
                raise ValueError("selection phase change action is invalid")
            if not candidate_id or candidate_id not in candidate_set:
                raise ValueError("selection phase change candidate is unknown")
            if candidate_id in seen:
                raise ValueError("selection phase change candidate is duplicated")
            seen.add(candidate_id)
            if action == "KEEP":
                if candidate_id not in working:
                    raise ValueError("selection KEEP candidate is not in the current set")
            elif action == "ADD":
                if candidate_id in working:
                    raise ValueError("selection ADD candidate is already in the current set")
                working.add(candidate_id)
            elif candidate_id not in working:
                raise ValueError("selection REMOVE candidate is not in the current set")
            else:
                working.remove(candidate_id)
        return rows, working

    try:
        previous_generated = datetime.fromisoformat(
            str(result["generated_at"]).replace("Z", "+00:00")
        )
        next_event = datetime.fromisoformat(event_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("selection phase timestamp is invalid") from error
    if (
        previous_generated.tzinfo is None
        or previous_generated.utcoffset() is None
        or next_event.tzinfo is None
        or next_event.utcoffset() is None
        or next_event.astimezone(_SHANGHAI) < previous_generated.astimezone(_SHANGHAI)
    ):
        raise ValueError("selection phase event cannot move backwards")
    supply_product = any(
        isinstance(ref, Mapping) and ref.get("type") == RESEARCH_SUPPLY_TYPE
        for candidate in result.get("research_candidates", [])
        for ref in candidate.get("source_refs", [])
    )
    if supply_product and next_event.astimezone(_SHANGHAI).strftime("%Y%m%d") != result["target_trade_date"]:
        raise ValueError("research supply phase event target date mismatch")
    if phase == "0830":
        if snapshots["0830"]["status"] == "READY":
            raise ValueError("selection 0830 snapshot is immutable")
        initial = snapshots["2200"]
        if initial["status"] != "READY":
            raise ValueError("selection 0830 requires a 2200 initial snapshot")
        initial_ids = set(initial["candidate_ids"])
        if not initial_ids.issubset(candidate_set):
            raise ValueError("selection 2200 snapshot contains unknown candidates")
        change_rows, frozen_candidate_ids = validate_changes(
            changes,
            current_ids=initial_ids,
        )
        freeze = {
            "phase": "0830",
            "status": "READY",
            "run_id": run_id,
            "event_at": event_at,
            "artifact_sha256": artifact_sha256,
            "candidate_ids": sorted(frozen_candidate_ids),
            "changes": change_rows,
            "freeze_run_id": None,
            "freeze_snapshot_sha256": None,
            "snapshot_sha256": None,
        }
        snapshots["0830"] = _selection_snapshot("0830", freeze, candidate_ids=candidate_ids)
    elif phase == "0935":
        freeze = snapshots["0830"]
        if freeze["status"] != "READY":
            raise ValueError("selection 0935 requires an 0830 freeze")
        if observation is None:
            raise ValueError("selection 0935 requires an append observation")
        change_rows, _ = validate_changes(
            changes,
            current_ids=set(freeze["candidate_ids"]),
        )
        observation_row = dict(observation)
        observation_row.setdefault("kind", "APPEND_ONLY")
        if observation_row.get("kind") != "APPEND_ONLY":
            raise ValueError("selection 0935 observation must be APPEND_ONLY")
        observation_candidate = observation_row.get("candidate_id")
        if observation_candidate is not None and _text(observation_candidate) not in candidate_set:
            raise ValueError("selection 0935 observation candidate is unknown")
        observation_row["freeze_run_id"] = freeze["run_id"]
        observation_row["freeze_snapshot_sha256"] = freeze["snapshot_sha256"]
        result["intraday_observations"].append(observation_row)
        snapshots["0935"] = _selection_snapshot(
            "0935",
            {
                "phase": "0935",
                "status": "READY",
                "run_id": run_id,
                "event_at": event_at,
                "artifact_sha256": artifact_sha256,
                "candidate_ids": list(freeze["candidate_ids"]),
                "changes": change_rows,
                "freeze_run_id": freeze["run_id"],
                "freeze_snapshot_sha256": freeze["snapshot_sha256"],
                "snapshot_sha256": None,
            },
            candidate_ids=list(freeze["candidate_ids"]),
        )
    else:
        freeze = snapshots["0830"]
        if freeze["status"] != "READY":
            raise ValueError("selection 1620 requires an 0830 freeze")
        if outcome is None:
            raise ValueError("selection 1620 requires an outcome reference")
        change_rows, _ = validate_changes(
            changes,
            current_ids=set(freeze["candidate_ids"]),
        )
        outcome_row = dict(outcome)
        if outcome_row.get("freeze_run_id") != freeze["run_id"] or outcome_row.get("freeze_snapshot_sha256") != freeze["snapshot_sha256"]:
            raise ValueError("selection outcome does not reference the frozen run")
        result["outcomes"].append(outcome_row)
        snapshots["1620"] = _selection_snapshot(
            "1620",
            {
                "phase": "1620",
                "status": "READY",
                "run_id": run_id,
                "event_at": event_at,
                "artifact_sha256": artifact_sha256,
                "candidate_ids": list(freeze["candidate_ids"]),
                "changes": change_rows,
                "freeze_run_id": freeze["run_id"],
                "freeze_snapshot_sha256": freeze["snapshot_sha256"],
                "snapshot_sha256": None,
            },
            candidate_ids=list(freeze["candidate_ids"]),
        )
    result["run_id"] = run_id
    result["generated_at"] = event_at
    result["counts"] = {
        "research_candidates": len(result["research_candidates"]),
        "formal_shortlist": len(result["formal_shortlist"]),
        "snapshots": len(SELECTION_PHASES),
        "intraday_observations": len(result["intraday_observations"]),
        "outcomes": len(result["outcomes"]),
    }
    refreshed_gaps = [
        gap
        for gap in result["cannot_confirm"]
        if not any(gap == f"SNAPSHOT_{known_phase}_NOT_MATERIALIZED" for known_phase in SELECTION_PHASES)
    ]
    for known_phase in SELECTION_PHASES:
        if snapshots[known_phase]["status"] != "READY":
            refreshed_gaps.append(f"SNAPSHOT_{known_phase}_NOT_MATERIALIZED")
    if result["formal_authority"].get("status") != "READY" or not result["formal_shortlist"]:
        refreshed_gaps.append("FORMAL_AUTHORITY_NOT_MATERIALIZED")
    if any(candidate["pit_status"] != "READY" for candidate in result["research_candidates"]):
        refreshed_gaps.append("CANDIDATE_PIT_NOT_CONFIRMED")
    result["cannot_confirm"] = sorted(set(refreshed_gaps))
    result["first_failed_layer"] = result["cannot_confirm"][0] if result["cannot_confirm"] else None
    result["status"] = "READY_WITH_DECLARED_GAPS" if result["cannot_confirm"] else "READY"
    validate_selection_research_product(result)
    return result


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
