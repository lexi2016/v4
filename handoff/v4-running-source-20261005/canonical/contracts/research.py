"""Strict V3.5 research archive contract."""
from __future__ import annotations

import re
import math
from datetime import datetime
from typing import Any, Mapping


SCHEMA_VERSION = "v3_5.research_archive.v1"
TIMEZONE = "Asia/Shanghai"
DEDUPE_KEY_FIELDS = (
    "stock_code",
    "source_title",
    "url",
    "source_path",
    "source_name",
    "claim_type_or_evidence_level",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTICLE_FIELDS = {
    "article_id",
    "dedupe_key",
    "archive_date",
    "stock_code",
    "stock_name",
    "source_type",
    "source_name",
    "source_title",
    "source_path_sha256",
    "url",
    "theme",
    "catalyst",
    "evidence_sentence",
    "evidence_level",
    "confidence",
    "published_at",
    "collected_at",
    "first_seen_at",
    "duplicate_evidence_count",
    "source_dedup_keys",
    "recommendation_status",
}
_POOL_FIELDS = {
    "stock_code",
    "stock_name",
    "archive_date",
    "research_score",
    "research_status",
    "evidence_count",
    "source_count",
    "strong_evidence_count",
    "medium_evidence_count",
    "weak_evidence_count",
    "source_types",
    "themes",
    "top_catalysts",
    "first_seen_at",
    "collected_at",
    "formal_overlap",
    "stage_overlap",
    "recommendation_status",
}
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "archive_date",
    "status",
    "timezone",
    "source_input_sha256",
    "source_schema_version",
    "source_generated_at",
    "dedupe_key_fields",
    "article_count",
    "stock_pool_count",
    "source_counts",
    "articles",
    "stock_pool",
    "cannot_confirm",
    "write_policy",
    "recommendation_status",
    "production_allowed",
    "buy_gate_updated",
    "orders_sent",
}
_STAGE_EVIDENCE_FIELDS = {
    "schema_version",
    "trade_date",
    "slot",
    "source_input_sha256",
    "payload_sha256_scope",
    "payload_base_sha256",
    "manifest_sha256",
    "receipt_sha256",
    "items",
    "evidence",
}
_STAGE_ITEM_FIELDS = {
    "item_id",
    "raw_id",
    "stock_code",
    "item_quality",
    "quality_score",
    "quality_score_raw",
    "is_new_since_last_slot",
    "is_recheck_duplicate",
    "source_path",
    "source_title",
    "url",
    "cannot_confirm",
}
_STAGE_EVIDENCE_ROW_FIELDS = {
    "evidence_id",
    "stock_code",
    "is_new_since_last_slot",
    "is_recheck_duplicate",
    "evidence_level",
    "confidence",
    "quality_flags",
    "cannot_confirm",
}


def _archive_date(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("research archive_date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("research archive_date must be a real calendar date") from error
    return value


def _aware_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing research {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid research {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"research {field} must include timezone")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"invalid research {field}")
    return value


def _stage_evidence(value: Any, archive_date: str, source_sha: str) -> None:
    """Validate the optional research-to-stage projection.

    The projection is deliberately additive.  Existing archive payloads do
    not carry it, while a producer that does carry it must provide enough
    identity to bind the stage reader to one exact archive slot.  The
    ``payload_base_sha256`` names the canonical payload digest before this
    extension is attached; a self-referential whole-payload digest would not
    be meaningful.  The store still verifies the final payload digest and
    receipt independently.
    """
    if not isinstance(value, Mapping) or set(value) != _STAGE_EVIDENCE_FIELDS:
        raise ValueError("invalid research stage_evidence_v1 fields")
    if value.get("schema_version") != "v4.stage_evidence.v1":
        raise ValueError("invalid research stage_evidence_v1 schema")
    if value.get("trade_date") != archive_date:
        raise ValueError("research stage evidence date mismatch")
    slot = value.get("slot")
    if not isinstance(slot, str) or re.fullmatch(r"(?:[01]\d|2[0-3])[0-5]\d", slot) is None:
        raise ValueError("research stage evidence slot is invalid")
    if value.get("source_input_sha256") != source_sha:
        raise ValueError("research stage evidence source SHA mismatch")
    if value.get("payload_sha256_scope") != "ARCHIVE_WITHOUT_STAGE_EVIDENCE_V1":
        raise ValueError("research stage evidence payload scope mismatch")
    for field in (
        "payload_base_sha256",
        "source_input_sha256",
        "manifest_sha256",
        "receipt_sha256",
    ):
        if not _SHA256.fullmatch(str(value.get(field) or "")):
            raise ValueError(f"invalid research stage evidence {field}")
    items = value.get("items")
    if not isinstance(items, list):
        raise ValueError("research stage evidence items must be a list")
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("invalid research stage evidence item")
        if not {"stock_code", "item_quality", "is_new_since_last_slot", "is_recheck_duplicate"}.issubset(item):
            raise ValueError("research stage evidence item identity is incomplete")
        if set(item) - _STAGE_ITEM_FIELDS:
            raise ValueError("invalid research stage evidence item fields")
        if not str(item.get("stock_code") or "").strip():
            raise ValueError("research stage evidence item stock code is missing")
        if not isinstance(item.get("item_quality"), str) or not item["item_quality"].strip():
            raise ValueError("research stage evidence item quality is invalid")
        if type(item.get("is_new_since_last_slot")) is not bool or type(item.get("is_recheck_duplicate")) is not bool:
            raise ValueError("research stage evidence flags must be strict booleans")
        if "quality_score" in item:
            score = item.get("quality_score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                raise ValueError("research stage evidence quality score is invalid")
        if "quality_score_raw" in item and not isinstance(item.get("quality_score_raw"), str):
            raise ValueError("research stage evidence raw quality score is invalid")
        if "cannot_confirm" in item:
            _string_list(item.get("cannot_confirm"), "stage_evidence.item.cannot_confirm")
    evidence = value.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("research stage evidence rows must be a list")
    for row in evidence:
        if not isinstance(row, Mapping) or set(row) != _STAGE_EVIDENCE_ROW_FIELDS:
            raise ValueError("invalid research stage evidence row fields")
        if not str(row.get("evidence_id") or "").strip() or not str(row.get("stock_code") or "").strip():
            raise ValueError("research stage evidence row identity is missing")
        if type(row.get("is_new_since_last_slot")) is not bool or type(row.get("is_recheck_duplicate")) is not bool:
            raise ValueError("research stage evidence row flags must be strict booleans")
        for field in ("quality_flags", "cannot_confirm"):
            _string_list(row.get(field), f"stage_evidence.evidence.{field}")
        for field in ("evidence_level", "confidence"):
            if not isinstance(row.get(field), str):
                raise ValueError(f"research stage evidence row {field} is invalid")


def validate_research_archive(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping) or not set(payload).issubset(_TOP_LEVEL_FIELDS | {"stage_evidence_v1"}) or not _TOP_LEVEL_FIELDS.issubset(payload):
        raise ValueError("invalid research archive fields")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid research archive schema")
    archive_date = _archive_date(payload.get("archive_date"))
    fixed = {
        "status": "READY",
        "timezone": TIMEZONE,
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if any(payload.get(key) != expected for key, expected in fixed.items()):
        raise ValueError("unsafe research archive boundary")
    if not _SHA256.fullmatch(str(payload.get("source_input_sha256") or "")):
        raise ValueError("invalid research source SHA-256")
    if not isinstance(payload.get("source_schema_version"), str):
        raise ValueError("invalid research source schema")
    _aware_timestamp(payload.get("source_generated_at"), "source_generated_at")
    if tuple(payload.get("dedupe_key_fields") or ()) != DEDUPE_KEY_FIELDS:
        raise ValueError("research dedupe contract mismatch")

    articles = payload.get("articles")
    stock_pool = payload.get("stock_pool")
    if not isinstance(articles, list) or not articles:
        raise ValueError("research archive requires articles")
    if not isinstance(stock_pool, list) or not stock_pool:
        raise ValueError("research archive requires stock pool")
    if payload.get("article_count") != len(articles):
        raise ValueError("research article count mismatch")
    if payload.get("stock_pool_count") != len(stock_pool):
        raise ValueError("research stock-pool count mismatch")

    article_ids: set[str] = set()
    dedupe_keys: set[str] = set()
    for article in articles:
        if not isinstance(article, Mapping) or set(article) != _ARTICLE_FIELDS:
            raise ValueError("invalid research article fields")
        if article.get("archive_date") != archive_date:
            raise ValueError("research article date mismatch")
        for field in ("article_id", "dedupe_key", "source_path_sha256"):
            if not _SHA256.fullmatch(str(article.get(field) or "")):
                raise ValueError(f"invalid research article {field}")
        if article["article_id"] in article_ids or article["dedupe_key"] in dedupe_keys:
            raise ValueError("duplicate research article identity")
        article_ids.add(str(article["article_id"]))
        dedupe_keys.add(str(article["dedupe_key"]))
        for field in ("published_at", "collected_at", "first_seen_at"):
            _aware_timestamp(article.get(field), field)
        if article.get("recommendation_status") != "RESEARCH_ONLY":
            raise ValueError("unsafe research article recommendation")
        if type(article.get("duplicate_evidence_count")) is not int or article["duplicate_evidence_count"] < 1:
            raise ValueError("invalid research duplicate count")
        if sorted(set(_string_list(article.get("source_dedup_keys"), "source_dedup_keys"))) != article["source_dedup_keys"]:
            raise ValueError("research source dedup keys must be sorted and unique")

    stock_codes: set[str] = set()
    for row in stock_pool:
        if not isinstance(row, Mapping) or set(row) != _POOL_FIELDS:
            raise ValueError("invalid research stock-pool fields")
        code = str(row.get("stock_code") or "")
        if not code or code in stock_codes or row.get("archive_date") != archive_date:
            raise ValueError("invalid research stock-pool identity")
        stock_codes.add(code)
        for field in ("first_seen_at", "collected_at"):
            _aware_timestamp(row.get(field), field)
        if row.get("recommendation_status") != "RESEARCH_ONLY":
            raise ValueError("unsafe research stock-pool recommendation")
        for field in ("source_types", "themes", "top_catalysts"):
            _string_list(row.get(field), field)

    source_counts = payload.get("source_counts")
    if not isinstance(source_counts, Mapping) or any(
        not isinstance(key, str) or type(value) is not int or value < 0
        for key, value in source_counts.items()
    ):
        raise ValueError("invalid research source counts")
    cannot_confirm = _string_list(payload.get("cannot_confirm"), "cannot_confirm")
    if cannot_confirm != sorted(set(cannot_confirm)):
        raise ValueError("research cannot_confirm must be sorted and unique")
    if "stage_evidence_v1" in payload:
        _stage_evidence(
            payload["stage_evidence_v1"],
            archive_date,
            str(payload.get("source_input_sha256") or ""),
        )
    return archive_date


__all__ = [
    "DEDUPE_KEY_FIELDS",
    "SCHEMA_VERSION",
    "TIMEZONE",
    "validate_research_archive",
]
