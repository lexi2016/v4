"""Graph-backed normalization of a frozen legacy research-lane snapshot."""
from __future__ import annotations

import hashlib
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
    validate_research_archive(payload)
    return payload


__all__ = ["build_research_archive"]
