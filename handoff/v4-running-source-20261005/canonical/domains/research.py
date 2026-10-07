"""Graph-backed normalization of a frozen legacy research-lane snapshot."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from contracts.research import (
    DEDUPE_KEY_FIELDS,
    SCHEMA_VERSION,
    TIMEZONE,
    validate_research_archive,
)
from infrastructure.data_store import _date


_SHANGHAI = ZoneInfo(TIMEZONE)
_LEGACY_RUNTIME_PATH = re.compile(
    r"(?i)(?:[a-z]:\\|\\\\)[^；;\r\n]*?\\v3_system\\[^；;\r\n]*"
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: int | float = 0) -> int | float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _time(value: Any, *, fallback: Any = None) -> tuple[str, bool]:
    raw = _text(value) or _text(fallback)
    if not raw:
        raise ValueError("research timestamp is missing")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid research timestamp: {raw}") from error
    assumed = parsed.tzinfo is None or parsed.utcoffset() is None
    if assumed:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.isoformat(timespec="seconds"), assumed


def _dedupe_tuple(row: Mapping[str, Any]) -> tuple[str, str, str, str, str, str]:
    norm = lambda value: _text(value).lower()
    return (
        norm(row.get("stock_code") or row.get("code")),
        norm(row.get("source_title") or row.get("title")),
        norm(row.get("url") or row.get("source_url")),
        norm(row.get("source_path")),
        norm(row.get("source_name") or row.get("source_type")),
        norm(row.get("claim_type") or row.get("evidence_level")),
    )


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _redact_legacy_runtime_paths(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        return _LEGACY_RUNTIME_PATH.subn(
            lambda match: f"[LEGACY_PATH_SHA256:{_sha_text(match.group(0))}]",
            value,
        )
    if isinstance(value, list):
        output: list[Any] = []
        redactions = 0
        for item in value:
            sanitized, count = _redact_legacy_runtime_paths(item)
            output.append(sanitized)
            redactions += count
        return output, redactions
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        redactions = 0
        for key, item in value.items():
            sanitized, count = _redact_legacy_runtime_paths(item)
            output[str(key)] = sanitized
            redactions += count
        return output, redactions
    return value, 0


_STAGE_ITEM_FIELDS = (
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
)


_V4_20260929_1400_REPORT_ROLE_WARNING_SOURCE_SHA256 = (
    "506c947cad54071a286853df20afc74e10bb544b2b639fea1ea7a443216bc3fc"
)
_V4_20260929_1400_REPORT_ROLE_WARNING_CODES = (
    "002202", "600346", "600875", "601918",
)


def _canonical_payload_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _stage_evidence_from_source(
    source: Mapping[str, Any],
    *,
    archive_date: str,
    source_input_sha256: str,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Project already-produced item facts into the optional stage extension.

    The converter is not a producer of quality or delta facts.  It copies
    strict values supplied by the existing hourly input only when that input
    also supplies the slot/manifest/receipt provenance needed to bind them.
    Incomplete provenance is left out so the stage reader reports
    ``CANNOT_CONFIRM`` instead of accepting an unbound projection.
    """
    manifest = source.get("source_manifest") if isinstance(source.get("source_manifest"), Mapping) else {}
    supplied = source.get("stage_evidence_v1")
    supplied = dict(supplied) if isinstance(supplied, Mapping) else {}
    slot = _text(supplied.get("slot") or source.get("slot") or manifest.get("hourly_slot"))
    manifest_sha = _text(
        supplied.get("manifest_sha256")
        or source.get("manifest_sha256")
        or manifest.get("manifest_sha256")
    ).lower()
    receipt_sha = _text(
        supplied.get("receipt_sha256")
        or source.get("receipt_sha256")
        or manifest.get("receipt_sha256")
    ).lower()
    if not re.fullmatch(r"(?:[01]\d|2[0-3])[0-5]\d", slot):
        return None
    if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (manifest_sha, receipt_sha)):
        return None

    def item_projection(row: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(row, Mapping):
            return None
        if (
            not str(row.get("stock_code") or row.get("code") or "").strip()
            or not isinstance(row.get("item_quality"), str)
            or not row.get("item_quality", "").strip()
            or type(row.get("is_new_since_last_slot")) is not bool
            or type(row.get("is_recheck_duplicate")) is not bool
        ):
            return None
        output = {
            field: row[field]
            for field in _STAGE_ITEM_FIELDS
            if field in row
        }
        output["stock_code"] = _text(row.get("stock_code") or row.get("code"))
        if "cannot_confirm" in output and not isinstance(output["cannot_confirm"], list):
            return None
        return output

    def evidence_projection(row: Mapping[str, Any]) -> dict[str, Any] | None:
        if not isinstance(row, Mapping):
            return None
        required = (
            "stock_code",
            "is_new_since_last_slot",
            "is_recheck_duplicate",
            "evidence_level",
            "confidence",
        )
        if (
            not str(row.get("stock_code") or row.get("code") or "").strip()
            or any(type(row.get(field)) is not bool for field in required[1:3])
            or any(not isinstance(row.get(field), str) for field in required[3:])
        ):
            return None
        quality_flags = row.get("quality_flags", [])
        cannot_confirm = row.get("cannot_confirm", [])
        if not isinstance(quality_flags, (list, tuple)) or not isinstance(cannot_confirm, (list, tuple)):
            return None
        return {
            "evidence_id": _text(row.get("evidence_id")) or _sha_text(
                f"stage-evidence|{archive_date}|{row.get('stock_code') or row.get('code')}|{row.get('source_title') or row.get('title')}"
            ),
            "stock_code": _text(row.get("stock_code") or row.get("code")),
            "is_new_since_last_slot": row["is_new_since_last_slot"],
            "is_recheck_duplicate": row["is_recheck_duplicate"],
            "evidence_level": row["evidence_level"],
            "confidence": row["confidence"],
            "quality_flags": [str(item) for item in quality_flags],
            "cannot_confirm": [str(item) for item in cannot_confirm],
        }

    raw_items = supplied.get("items") if isinstance(supplied.get("items"), list) else source.get("research_items")
    raw_evidence = supplied.get("evidence") if isinstance(supplied.get("evidence"), list) else source.get("stock_research_timeline")
    items = [projected for row in (raw_items or []) if (projected := item_projection(row)) is not None]
    evidence = [projected for row in (raw_evidence or []) if (projected := evidence_projection(row)) is not None]
    if not supplied and not items and not evidence:
        return None
    base_sha = _canonical_payload_sha(payload)
    extension = {
        "schema_version": "v4.stage_evidence.v1",
        "trade_date": archive_date,
        "slot": slot,
        "source_input_sha256": source_input_sha256.lower(),
        "payload_sha256_scope": "ARCHIVE_WITHOUT_STAGE_EVIDENCE_V1",
        "payload_base_sha256": base_sha,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
        "items": items,
        "evidence": evidence,
    }
    sanitized, _ = _redact_legacy_runtime_paths(extension)
    return sanitized


def _dedupe_timeline(rows: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    for source in rows:
        if not isinstance(source, Mapping):
            continue
        key = _dedupe_tuple(source)
        if not key[0]:
            continue
        current = grouped.get(key)
        if current is None:
            current = deepcopy(dict(source))
            current["duplicate_evidence_count"] = 1
            current["source_dedup_keys"] = [
                _text(source.get("dedup_key"))
            ] if source.get("dedup_key") else []
            current["_v35_dedupe_tuple"] = key
            grouped[key] = current
            continue
        current["duplicate_evidence_count"] += 1
        if source.get("dedup_key"):
            current["source_dedup_keys"].append(_text(source.get("dedup_key")))
        if len(_text(source.get("evidence_sentence"))) > len(_text(current.get("evidence_sentence"))):
            current["evidence_sentence"] = source.get("evidence_sentence")
        if _text(source.get("event_time")) > _text(current.get("event_time")):
            current["event_time"] = source.get("event_time")
    return sorted(
        grouped.values(),
        key=lambda item: (_text(item.get("event_time")), _text(item.get("stock_code"))),
        reverse=True,
    )


def _exact_v4_20260929_1400_report_role_warnings(
    source: Mapping[str, Any],
    *,
    archive_date: str,
    source_input_sha256: str,
) -> list[str]:
    """Reproduce the four pinned 2026-09-29 14:00 report-role warnings.

    This narrow compatibility is available only for the exact original-slot
    source witness.  The report audit must still identify the same four
    excluded entities, with each exclusion explicitly marked ineligible.
    Other source identities retain the normal warning projection.
    """
    if source_input_sha256.lower() != _V4_20260929_1400_REPORT_ROLE_WARNING_SOURCE_SHA256:
        return []
    if (
        archive_date != "20260929"
        or source.get("schema_version") != "v3_research_lane.v2"
        or source.get("trade_date") != "20260929"
        or source.get("slot") != "1400"
    ):
        raise ValueError("V4_20260929_1400_ROLE_WARNING_SOURCE_DATE_SLOT_MISMATCH")

    manifest = source.get("source_manifest")
    if not isinstance(manifest, Mapping) or (
        manifest.get("trade_date") != "20260929"
        or manifest.get("hourly_slot") != "1400"
        or manifest.get("capture_origin") != "ORIGINAL_SLOT"
        or manifest.get("original_time_capture") is not True
        or manifest.get("natural_execution_verified") is not False
    ):
        raise ValueError("V4_20260929_1400_ROLE_WARNING_SOURCE_MANIFEST_MISMATCH")

    audit = source.get("report_entity_audit")
    if not isinstance(audit, Mapping) or audit.get("policy_version") != "report_subject_scoring.v1":
        raise ValueError("V4_20260929_1400_ROLE_WARNING_REPORT_AUDIT_MISSING_OR_UNKNOWN")
    affected = audit.get("affected_codes")
    excluded = audit.get("excluded_evidence")
    receipts = manifest.get("source_receipts")
    if (
        not isinstance(affected, list)
        or affected != list(_V4_20260929_1400_REPORT_ROLE_WARNING_CODES)
        or not isinstance(excluded, list)
        or len(excluded) != len(_V4_20260929_1400_REPORT_ROLE_WARNING_CODES)
        or audit.get("excluded_evidence_count") != len(excluded)
        or audit.get("historical_capture_reconstructed") is not False
        or audit.get("original_entities_retained") is not True
        or audit.get("score_weights_changed") is not False
        or audit.get("security_master_attested") is not False
        or not isinstance(receipts, list)
        or len(receipts) != 1
        or not isinstance(receipts[0], str)
        or not receipts[0].strip()
    ):
        raise ValueError("V4_20260929_1400_ROLE_WARNING_REPORT_AUDIT_SHAPE_INVALID")

    excluded_codes: list[str] = []
    evidence_ids: list[str] = []
    for item in excluded:
        if (
            not isinstance(item, Mapping)
            or item.get("entity_role") != "TITLE_NAME_MARKET_UNCONFIRMED"
            or item.get("research_subject_eligible") is not False
            or item.get("source_path") != receipts[0]
        ):
            raise ValueError("V4_20260929_1400_ROLE_WARNING_EXCLUDED_EVIDENCE_INVALID")
        code = item.get("stock_code")
        evidence_id = item.get("evidence_id")
        if (
            not isinstance(code, str)
            or re.fullmatch(r"\d{6}", code) is None
            or not isinstance(evidence_id, str)
            or not evidence_id.strip()
        ):
            raise ValueError("V4_20260929_1400_ROLE_WARNING_EXCLUDED_EVIDENCE_IDENTITY_INVALID")
        excluded_codes.append(code)
        evidence_ids.append(evidence_id)
    if (
        sorted(excluded_codes) != list(_V4_20260929_1400_REPORT_ROLE_WARNING_CODES)
        or len(set(excluded_codes)) != len(excluded_codes)
        or len(set(evidence_ids)) != len(evidence_ids)
    ):
        raise ValueError("V4_20260929_1400_ROLE_WARNING_AUDIT_CODE_MISMATCH")
    return [
        f"REPORT_ROLE_EVIDENCE_EXCLUDED:{code}"
        for code in _V4_20260929_1400_REPORT_ROLE_WARNING_CODES
    ]


def build_research_archive(
    source: Mapping[str, Any],
    *,
    source_input_sha256: str,
) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        raise ValueError("research source must be an object")
    archive_date = _date(_text(source.get("trade_date")))
    if not isinstance(source.get("stock_research_timeline"), list):
        raise ValueError("research source timeline is missing")
    if not isinstance(source.get("stock_research_daily"), list):
        raise ValueError("research source stock pool is missing")
    manifest = source.get("source_manifest") if isinstance(source.get("source_manifest"), Mapping) else {}
    generated_at, generated_assumed = _time(
        manifest.get("published_at") or manifest.get("generated_at"),
        fallback=f"{archive_date[:4]}-{archive_date[4:6]}-{archive_date[6:]}T00:00:00",
    )

    assumed_timezone = generated_assumed
    articles: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    articles_by_stock: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _dedupe_timeline(source["stock_research_timeline"]):
        key = row.pop("_v35_dedupe_tuple")
        canonical_key = "\x1f".join(key)
        published_at, published_assumed = _time(
            row.get("source_published_at"),
            fallback=row.get("event_time"),
        )
        collected_at, collected_assumed = _time(
            row.get("last_checked_at"),
            fallback=row.get("event_time"),
        )
        first_seen_at, first_seen_assumed = _time(
            row.get("first_seen_at"),
            fallback=row.get("event_time"),
        )
        assumed_timezone = assumed_timezone or published_assumed or collected_assumed or first_seen_assumed
        source_name = _text(row.get("source_name") or row.get("source_type"))
        source_counts[source_name or "UNKNOWN"] += 1
        article = {
            "article_id": _sha_text(f"{archive_date}\x1e{canonical_key}"),
            "dedupe_key": _sha_text(canonical_key),
            "archive_date": archive_date,
            "stock_code": _text(row.get("stock_code") or row.get("code")),
            "stock_name": _text(row.get("stock_name") or row.get("name")),
            "source_type": _text(row.get("source_type")),
            "source_name": source_name,
            "source_title": _text(row.get("source_title") or row.get("title")),
            "source_path_sha256": _sha_text(_text(row.get("source_path"))),
            "url": _text(row.get("url") or row.get("source_url")),
            "theme": _text(row.get("theme")),
            "catalyst": _text(row.get("catalyst")),
            "evidence_sentence": _text(row.get("evidence_sentence")),
            "evidence_level": _text(row.get("evidence_level")),
            "confidence": _text(row.get("confidence")),
            "published_at": published_at,
            "collected_at": collected_at,
            "first_seen_at": first_seen_at,
            "duplicate_evidence_count": int(row.get("duplicate_evidence_count") or 1),
            "source_dedup_keys": sorted(set(row.get("source_dedup_keys") or [])),
            "recommendation_status": "RESEARCH_ONLY",
        }
        articles.append(article)
        articles_by_stock[article["stock_code"]].append(article)

    bridges = {
        _text(row.get("stock_code")): row
        for row in (source.get("research_pool_bridge") or [])
        if isinstance(row, Mapping) and row.get("stock_code")
    }
    stock_pool: list[dict[str, Any]] = []
    for source_row in source["stock_research_daily"]:
        if not isinstance(source_row, Mapping):
            continue
        code = _text(source_row.get("stock_code"))
        if not code:
            continue
        matching = articles_by_stock.get(code, [])
        first_fallback = min((row["first_seen_at"] for row in matching), default=generated_at)
        collected_fallback = max((row["collected_at"] for row in matching), default=generated_at)
        first_seen_at, first_assumed = _time(source_row.get("first_seen_time"), fallback=first_fallback)
        collected_at, collected_assumed = _time(source_row.get("last_seen_time"), fallback=collected_fallback)
        assumed_timezone = assumed_timezone or first_assumed or collected_assumed
        bridge = bridges.get(code) if isinstance(bridges.get(code), Mapping) else {}
        stock_pool.append(
            {
                "stock_code": code,
                "stock_name": _text(source_row.get("stock_name")),
                "archive_date": archive_date,
                "research_score": _number(source_row.get("research_score")),
                "research_status": _text(source_row.get("research_status")),
                "evidence_count": int(_number(source_row.get("evidence_count"))),
                "source_count": int(_number(source_row.get("source_count"))),
                "strong_evidence_count": int(_number(source_row.get("strong_evidence_count"))),
                "medium_evidence_count": int(_number(source_row.get("medium_evidence_count"))),
                "weak_evidence_count": int(_number(source_row.get("weak_evidence_count"))),
                "source_types": sorted({_text(item) for item in source_row.get("source_types", []) if _text(item)}),
                "themes": sorted({_text(item) for item in source_row.get("themes", []) if _text(item)}),
                "top_catalysts": sorted({_text(item) for item in source_row.get("top_catalysts", []) if _text(item)}),
                "first_seen_at": first_seen_at,
                "collected_at": collected_at,
                "formal_overlap": bool(bridge.get("formal_overlap", False)),
                "stage_overlap": bool(bridge.get("stage_overlap", False)),
                "recommendation_status": "RESEARCH_ONLY",
            }
        )
    stock_pool.sort(key=lambda row: (-float(row["research_score"]), row["stock_code"]))

    articles, article_path_redactions = _redact_legacy_runtime_paths(articles)
    stock_pool, pool_path_redactions = _redact_legacy_runtime_paths(stock_pool)
    path_redactions = article_path_redactions + pool_path_redactions

    cannot_confirm: list[str] = []
    if assumed_timezone:
        cannot_confirm.append("LEGACY_NAIVE_TIMESTAMP_ASSUMED_ASIA_SHANGHAI")
    source_gaps = source.get("cannot_confirm")
    if isinstance(source_gaps, list) and source_gaps:
        cannot_confirm.append(f"LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:{len(source_gaps)}")
    if path_redactions:
        cannot_confirm.append(f"LEGACY_RUNTIME_PATHS_REDACTED:{path_redactions}")
    cannot_confirm.extend(
        _exact_v4_20260929_1400_report_role_warnings(
            source,
            archive_date=archive_date,
            source_input_sha256=source_input_sha256,
        )
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "archive_date": archive_date,
        "status": "READY",
        "timezone": TIMEZONE,
        "source_input_sha256": source_input_sha256.lower(),
        "source_schema_version": _text(source.get("schema_version")),
        "source_generated_at": generated_at,
        "dedupe_key_fields": list(DEDUPE_KEY_FIELDS),
        "article_count": len(articles),
        "stock_pool_count": len(stock_pool),
        "source_counts": dict(sorted(source_counts.items())),
        "articles": articles,
        "stock_pool": stock_pool,
        "cannot_confirm": sorted(set(cannot_confirm)),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    stage_evidence = _stage_evidence_from_source(
        source,
        archive_date=archive_date,
        source_input_sha256=source_input_sha256,
        payload=payload,
    )
    if stage_evidence is not None:
        payload["stage_evidence_v1"] = stage_evidence
    validate_research_archive(payload)
    return payload


__all__ = ["build_research_archive"]
