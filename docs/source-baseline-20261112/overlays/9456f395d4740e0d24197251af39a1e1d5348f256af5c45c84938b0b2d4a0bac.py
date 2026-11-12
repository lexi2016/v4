"""Strict V4 research archive contract."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo


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
_READY_EMPTY_EVIDENCE_FIELDS = {
    "schema_version", "trade_date", "slot", "status", "source_input_sha256",
    "source_receipt_path", "source_receipt_sha256", "fetch_ok", "fetch_success",
    "summary_sha256", "fetch_result_sha256",
    "page_count", "topic_count", "effective_topic_count", "fetched_at",
    "source_cutoff", "capture_origin", "materialization_origin",
    "materialized_at", "available_at", "natural_execution_verified",
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


def _ready_empty_evidence(
    value: Any, *, archive_date: str, source_sha: str, source_generated_at: str,
) -> None:
    if not isinstance(value, Mapping) or set(value) != _READY_EMPTY_EVIDENCE_FIELDS:
        raise ValueError("invalid research ready-empty evidence fields")
    if (
        archive_date != "20261012"
        or value.get("schema_version") != "v3_5.zsxq_ready_empty.v1"
        or value.get("trade_date") != archive_date
        or value.get("slot") != "1700"
        or value.get("status") != "READY_EMPTY"
        or value.get("source_input_sha256") != source_sha
        or value.get("source_receipt_path") != (
            f"research_module/runtime_outputs/zsxq_hourly/{archive_date}/1700/"
            f"v35_zsxq_hourly_status_{archive_date}_1700.json"
        )
        or not _SHA256.fullmatch(str(value.get("source_receipt_sha256") or ""))
        or not _SHA256.fullmatch(str(value.get("summary_sha256") or ""))
        or not _SHA256.fullmatch(str(value.get("fetch_result_sha256") or ""))
        or value.get("fetch_ok") is not True
        or type(value.get("fetch_ok")) is not bool
        or value.get("fetch_success") is not True
        or type(value.get("fetch_success")) is not bool
        or type(value.get("page_count")) is not int
        or value.get("page_count") < 1
        or type(value.get("topic_count")) is not int
        or value.get("topic_count") != 0
        or type(value.get("effective_topic_count")) is not int
        or value.get("effective_topic_count") != 0
        or value.get("capture_origin") != "ORIGINAL_SLOT"
        or value.get("materialization_origin") != "MANUAL_RECOVERY"
        or value.get("natural_execution_verified") is not False
        or type(value.get("natural_execution_verified")) is not bool
    ):
        raise ValueError("invalid research ready-empty source identity")
    cutoff = datetime.strptime("202610121700", "%Y%m%d%H%M").replace(
        tzinfo=ZoneInfo("Asia/Shanghai"), second=59
    )
    fetched = datetime.fromisoformat(_aware_timestamp(value.get("fetched_at"), "ready_empty.fetched_at").replace("Z", "+00:00")).astimezone(cutoff.tzinfo)
    declared_cutoff = datetime.fromisoformat(_aware_timestamp(value.get("source_cutoff"), "ready_empty.source_cutoff").replace("Z", "+00:00")).astimezone(cutoff.tzinfo)
    materialized = datetime.fromisoformat(_aware_timestamp(value.get("materialized_at"), "ready_empty.materialized_at").replace("Z", "+00:00")).astimezone(cutoff.tzinfo)
    available = datetime.fromisoformat(_aware_timestamp(value.get("available_at"), "ready_empty.available_at").replace("Z", "+00:00")).astimezone(cutoff.tzinfo)
    generated = datetime.fromisoformat(_aware_timestamp(source_generated_at, "source_generated_at").replace("Z", "+00:00")).astimezone(cutoff.tzinfo)
    if (
        declared_cutoff != cutoff
        or fetched.strftime("%Y%m%d") != archive_date
        or fetched > cutoff
        or materialized.strftime("%Y%m%d") != archive_date
        or materialized < cutoff
        or available != materialized
        or generated != materialized
    ):
        raise ValueError("research ready-empty time provenance mismatch")


def validate_research_archive(payload: Mapping[str, Any]) -> str:
    if (
        not isinstance(payload, Mapping)
        or not _TOP_LEVEL_FIELDS.issubset(payload)
        or set(payload) - (_TOP_LEVEL_FIELDS | {"ready_empty_evidence_v1"})
    ):
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
    has_empty_evidence = "ready_empty_evidence_v1" in payload
    if not isinstance(articles, list) or not isinstance(stock_pool, list):
        raise ValueError("research archive rows must be lists")
    if not has_empty_evidence and (not articles or not stock_pool):
        raise ValueError("research archive requires articles and stock pool")
    if has_empty_evidence:
        _ready_empty_evidence(
            payload.get("ready_empty_evidence_v1"),
            archive_date=archive_date,
            source_sha=str(payload.get("source_input_sha256") or ""),
            source_generated_at=str(payload.get("source_generated_at") or ""),
        )
        if articles or stock_pool or payload.get("article_count") != 0 or payload.get("stock_pool_count") != 0 or payload.get("source_counts") != {}:
            raise ValueError("research ready-empty archive contains rows or counts")
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
    return archive_date


__all__ = [
    "DEDUPE_KEY_FIELDS",
    "SCHEMA_VERSION",
    "TIMEZONE",
    "validate_research_archive",
]
