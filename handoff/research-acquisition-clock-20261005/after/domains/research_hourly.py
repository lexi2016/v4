from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Iterable, Mapping

READ_ONLY_POLICY = "read_only"
RESEARCH_ONLY = "RESEARCH_ONLY"
NO_BUY_GATE = "none"
FORBIDDEN_DECISION_WORDS = ("BUY_NOW", "ORDER_READY", "AUTO_TRADE", "PRODUCTION_ALLOWED", "正式买入推荐")

SOURCE_TYPES = {
    "zsxq",
    "research_db",
    "hourly_research",
    "morning_news",
    "external_finance",
    "ai_news",
    "wechat",
    "manual",
}

TIME_BUCKETS = (
    ("09:15", "PREMARKET"),
    ("09:30", "AUCTION"),
    ("09:45", "OPEN_0930_0945"),
    ("15:00", "INTRADAY"),
    ("15:30", "CLOSE"),
)

ENTITY_RECEIPT_FIELDS = (
    "source_entity_receipt",
    "source_to_entity_receipt",
    "entity_mapping_receipt",
    "entity_receipt",
)
VERIFIED_ENTITY_RECEIPT_STATUSES = {"VERIFIED", "CONFIRMED", "READY", "VALID"}


@dataclass(frozen=True)
class RawResearchItem:
    raw_id: str
    trade_date: str
    source_type: str
    source_name: str = ""
    source_path: str = ""
    url: str = ""
    title: str = ""
    raw_text: str = ""
    published_at: str = ""
    crawl_time: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchItem:
    item_id: str
    raw_id: str
    trade_date: str
    event_time: str
    source_published_at: str
    first_seen_at: str
    last_checked_at: str
    display_event_time: str
    is_new_since_last_slot: bool
    is_recheck_duplicate: bool
    source_type: str
    source_name: str
    source_path: str
    url: str
    title: str
    summary: str
    themes: tuple[str, ...]
    mentioned_stock_candidates: tuple[str, ...]
    dedup_key: str
    item_quality: str
    source_evidence_level: str
    source_confidence: str
    cannot_confirm: tuple[str, ...]
    source_entity_receipts: tuple[dict[str, Any], ...] = ()
    retrieved_at: str = ""
    available_at: str = ""
    acquisition_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StockResearchEvidence:
    evidence_id: str
    stock_code: str
    stock_name: str
    trade_date: str
    event_time: str
    source_published_at: str
    first_seen_at: str
    last_checked_at: str
    display_event_time: str
    is_new_since_last_slot: bool
    is_recheck_duplicate: bool
    time_bucket: str
    source_type: str
    source_name: str
    source_title: str
    source_path: str
    url: str
    theme: str
    catalyst: str
    evidence_sentence: str
    evidence_level: str
    confidence: str
    extractor: str
    is_direct_stock_mention: bool
    is_theme_only_mapping: bool
    dedup_key: str
    quality_flags: tuple[str, ...]
    cannot_confirm: tuple[str, ...]
    retrieved_at: str = ""
    available_at: str = ""
    acquisition_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StockResearchDaily:
    stock_code: str
    stock_name: str
    trade_date: str
    first_seen_time: str
    last_seen_time: str
    evidence_count: int
    source_count: int
    strong_evidence_count: int
    medium_evidence_count: int
    weak_evidence_count: int
    themes: tuple[str, ...]
    top_catalysts: tuple[str, ...]
    source_types: tuple[str, ...]
    latest_evidence_sentence: str
    research_score: int
    research_status: str
    pool_overlap: dict[str, Any]
    next_action: str


@dataclass(frozen=True)
class ResearchPoolBridge:
    bridge_id: str
    trade_date: str
    stock_code: str
    stock_name: str
    research_score: int
    evidence_level: str
    matched_pool: str
    matched_stage: str
    formal_overlap: bool
    stage_overlap: bool
    reason: str
    next_action: str
    source_evidence_ids: tuple[str, ...]
    default_status: str = RESEARCH_ONLY
    write_policy: str = READ_ONLY_POLICY
    buy_gate_effect: str = NO_BUY_GATE
    live_order_effect: str = NO_BUY_GATE


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def compact_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def split_tokens(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        raw = [str(item).strip() for item in value]
    else:
        raw = re.split(r"[,，/、;；|\n]+", str(value or ""))
    seen: list[str] = []
    for item in raw:
        item = compact_text(item, 80)
        if item and item not in seen:
            seen.append(item)
    return tuple(seen)


def _entity_receipt_entries(value: Any) -> list[dict[str, Any]]:
    """Flatten the existing receipt shapes without treating tags as receipts."""
    if isinstance(value, dict):
        nested = value.get("mappings") or value.get("entities") or value.get("rows")
        if isinstance(nested, (list, tuple)):
            return [dict(item) for item in nested if isinstance(item, dict)]
        return [dict(value)]
    if isinstance(value, (list, tuple)):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def normalize_entity_receipts(raw_payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Retain only explicitly supplied source-to-entity receipt records."""
    receipts: list[dict[str, Any]] = []
    for field_name in ENTITY_RECEIPT_FIELDS:
        for receipt in _entity_receipt_entries(raw_payload.get(field_name)):
            if receipt not in receipts:
                receipts.append(receipt)
    return tuple(receipts)


def normalize_source_type(value: Any) -> str:
    source_type = str(value or "manual").strip().lower()
    return source_type if source_type in SOURCE_TYPES else "manual"


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def event_time_of(raw: RawResearchItem) -> str:
    return raw.published_at or raw.crawl_time or f"{raw.trade_date} 00:00:00"


def time_bucket(event_time: str) -> str:
    match = re.search(r"(\d{2}:\d{2})", str(event_time or ""))
    if not match:
        return "UNKNOWN"
    hhmm = match.group(1)
    for upper, bucket in TIME_BUCKETS:
        if hhmm < upper:
            return bucket
    return "AFTERHOURS"


def as_plain_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "__dataclass_fields__"):
        payload = asdict(row)
    elif isinstance(row, dict):
        payload = dict(row)
    else:
        payload = dict(row)
    for key, value in list(payload.items()):
        if isinstance(value, tuple):
            payload[key] = list(value)
    return payload


def build_raw_items(trade_date: str, rows: Iterable[dict[str, Any]]) -> list[RawResearchItem]:
    raw_items: list[RawResearchItem] = []
    for index, row in enumerate(rows):
        source_type = normalize_source_type(row.get("source_type"))
        title = compact_text(row.get("title"), 300)
        raw_text = compact_text(row.get("raw_text") or row.get("body") or row.get("summary"), 5000)
        published_at = compact_text(row.get("display_event_time") or row.get("published_at") or row.get("event_time"), 40)
        source_path = compact_text(row.get("source_path"), 300)
        url = compact_text(row.get("url"), 500)
        flags: list[str] = []
        if not title:
            flags.append("MISSING_TITLE")
        if not raw_text:
            flags.append("MISSING_TEXT")
        if not published_at:
            flags.append("MISSING_PUBLISHED_AT")
        raw_id = compact_text(row.get("raw_id")) or stable_hash(
            "|".join([trade_date, source_type, title, raw_text[:300], str(index)])
        )
        raw_items.append(
            RawResearchItem(
                raw_id=raw_id,
                trade_date=trade_date,
                source_type=source_type,
                source_name=compact_text(row.get("source_name"), 120),
                source_path=source_path,
                url=url,
                title=title,
                raw_text=raw_text,
                published_at=published_at,
                crawl_time=compact_text(row.get("crawl_time"), 40),
                raw_payload=dict(row),
                quality_flags=tuple(flags),
            )
        )
    return raw_items


def normalize_research_items(raw_items: Iterable[RawResearchItem]) -> list[ResearchItem]:
    dedup: dict[str, ResearchItem] = {}
    for raw in raw_items:
        text = raw.raw_text or raw.title
        summary = compact_text(text, 280)
        themes = split_tokens(raw.raw_payload.get("themes") or raw.raw_payload.get("theme") or raw.raw_payload.get("sector"))
        candidates = split_tokens(
            raw.raw_payload.get("mentioned_stock_candidates")
            or raw.raw_payload.get("stock_tags")
            or raw.raw_payload.get("stocks")
            or raw.raw_payload.get("stock")
        )
        cannot = list(raw.quality_flags)
        source_cannot = raw.raw_payload.get("source_cannot_confirm") or raw.raw_payload.get("cannot_confirm")
        if source_cannot:
            cannot.extend(split_tokens(source_cannot))
        if not (raw.source_path or raw.url):
            cannot.append("MISSING_SOURCE_TRACE")
        quality = "OK" if not cannot else "CANNOT_CONFIRM"
        dedup_key = stable_hash("|".join([raw.source_type, raw.title, raw.published_at or raw.trade_date, summary[:100]]))
        item = ResearchItem(
            item_id=stable_hash("item|" + dedup_key),
            raw_id=raw.raw_id,
            trade_date=raw.trade_date,
            event_time=event_time_of(raw),
            source_published_at=compact_text(raw.raw_payload.get("source_published_at"), 40),
            first_seen_at=compact_text(raw.raw_payload.get("first_seen_at"), 40),
            last_checked_at=compact_text(raw.raw_payload.get("last_checked_at") or raw.crawl_time, 40),
            display_event_time=compact_text(raw.raw_payload.get("display_event_time") or event_time_of(raw), 40),
            is_new_since_last_slot=truthy(raw.raw_payload.get("is_new_since_last_slot")),
            is_recheck_duplicate=truthy(raw.raw_payload.get("is_recheck_duplicate")),
            source_type=raw.source_type,
            source_name=raw.source_name,
            source_path=raw.source_path,
            url=raw.url,
            title=raw.title or "未命名研报/资讯",
            summary=summary,
            themes=themes,
            mentioned_stock_candidates=candidates,
            dedup_key=dedup_key,
            item_quality=quality,
            source_evidence_level=compact_text(raw.raw_payload.get("source_evidence_level"), 40),
            source_confidence=compact_text(raw.raw_payload.get("source_confidence"), 40),
            cannot_confirm=tuple(dict.fromkeys(cannot)),
            source_entity_receipts=normalize_entity_receipts(raw.raw_payload),
            retrieved_at=raw.raw_payload.get("retrieved_at", ""),
            available_at=raw.raw_payload.get("available_at", ""),
            acquisition_provenance=raw.raw_payload.get("acquisition_provenance", {}),
        )
        dedup.setdefault(dedup_key, item)
    return list(dedup.values())


def stock_aliases(stock_master: dict[str, Any]) -> dict[str, tuple[str, str]]:
    aliases: dict[str, tuple[str, str]] = {}
    for code, info in stock_master.items():
        if isinstance(info, dict):
            name = str(info.get("name") or info.get("stock_name") or "").strip()
            alias_values = [name, code, *(info.get("aliases") or [])]
        else:
            name = str(info).strip()
            alias_values = [name, code]
        if not name:
            name = code
        for alias in alias_values:
            alias = str(alias or "").strip()
            if alias:
                aliases[alias] = (code, name)
    return aliases


def evidence_sentence(
    item: ResearchItem, stock_name: str, stock_aliases_for_entity: Iterable[str] = ()
) -> str:
    text = item.summary or item.title
    sentences = re.split(r"(?<=[。！？!?；;])", text)
    targets = (stock_name, *stock_aliases_for_entity)
    for sentence in sentences:
        if any(target and target in sentence for target in targets):
            return compact_text(sentence, 300)
    return compact_text(text, 300)


def _receipt_status(receipt: dict[str, Any]) -> str:
    status = str(receipt.get("status") or receipt.get("mapping_status") or "").strip().upper()
    if not status and truthy(receipt.get("verified") or receipt.get("is_verified")):
        return "VERIFIED"
    return status


def _receipt_locator(receipt: dict[str, Any]) -> str:
    locator = receipt.get("receipt_path") or receipt.get("receipt_id") or receipt.get("mapping_id")
    if locator:
        return compact_text(locator, 500)
    digest = str(receipt.get("receipt_sha256") or receipt.get("mapping_sha256") or "").strip()
    return digest if re.fullmatch(r"[0-9a-fA-F]{64}", digest) else ""


def _receipt_evidence_sentence(receipt: dict[str, Any]) -> str:
    return compact_text(
        receipt.get("evidence_sentence")
        or receipt.get("evidence")
        or receipt.get("excerpt")
        or receipt.get("quote"),
        300,
    )


def _receipt_entity(
    receipt: dict[str, Any], aliases: dict[str, tuple[str, str]]
) -> tuple[str, str] | None:
    status = _receipt_status(receipt)
    if status not in VERIFIED_ENTITY_RECEIPT_STATUSES:
        return None
    if not _receipt_locator(receipt):
        return None
    code = str(
        receipt.get("stock_code")
        or receipt.get("code")
        or receipt.get("normalized_code")
        or receipt.get("entity_id")
        or ""
    ).strip()
    name = str(receipt.get("stock_name") or receipt.get("name") or receipt.get("entity_name") or "").strip()
    resolved: tuple[str, str] | None = None
    if code and code in aliases:
        resolved = aliases[code]
    if name and name in aliases:
        if resolved is not None and resolved[0] != aliases[name][0]:
            return None
        resolved = aliases[name]
    return resolved


def unassigned_entity_notes(
    items: Iterable[ResearchItem], stock_master: dict[str, Any]
) -> list[dict[str, Any]]:
    """Report candidate tags that lack text or an explicit mapping receipt."""
    aliases = stock_aliases(stock_master)
    notes: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        haystack = " ".join([item.title, item.summary])
        direct_codes = {code for alias, (code, _name) in aliases.items() if alias and alias in haystack}
        receipt_codes = {
            entity[0]
            for receipt in item.source_entity_receipts
            if (entity := _receipt_entity(receipt, aliases)) is not None
        }
        for candidate in item.mentioned_stock_candidates:
            entity = aliases.get(candidate)
            if entity is None or entity[0] in direct_codes or entity[0] in receipt_codes:
                continue
            key = (item.item_id, entity[0])
            if key in seen:
                continue
            seen.add(key)
            notes.append(
                {
                    "item_id": item.item_id,
                    "reason": "STOCK_CANDIDATE_ENTITY_NOT_VERIFIED",
                    "stock_code": entity[0],
                    "stock_name": entity[1],
                    "source_path": item.source_path,
                    "url": item.url,
                }
            )
    return notes


def normalized_source_evidence_level(item: ResearchItem) -> tuple[str, str] | None:
    raw_level = str(item.source_evidence_level or "").strip().upper()
    if raw_level not in {"L1_WEAK", "L2_MEDIUM", "L3_STRONG"}:
        return None
    if raw_level == "L3_STRONG" and item.cannot_confirm:
        raw_level = "L2_MEDIUM"
    confidence = str(item.source_confidence or "").strip().upper()
    if confidence not in {"LOW", "MEDIUM", "HIGH"}:
        confidence = {"L1_WEAK": "LOW", "L2_MEDIUM": "MEDIUM", "L3_STRONG": "HIGH"}[raw_level]
    if raw_level != "L3_STRONG" and confidence == "HIGH":
        confidence = "MEDIUM" if raw_level == "L2_MEDIUM" else "LOW"
    return raw_level, confidence


def evidence_level(item: ResearchItem, direct: bool, theme_only: bool, matched_pool: bool = False) -> tuple[str, str]:
    upstream = normalized_source_evidence_level(item)
    if upstream:
        return upstream
    if direct and item.source_type in {"zsxq", "research_db", "hourly_research"} and not item.cannot_confirm:
        return "L3_STRONG", "HIGH"
    if matched_pool or direct:
        return "L2_MEDIUM", "MEDIUM"
    if theme_only:
        return "L1_WEAK", "LOW"
    return "L1_WEAK", "LOW"


def extract_stock_evidence(items: Iterable[ResearchItem], stock_master: dict[str, Any]) -> list[StockResearchEvidence]:
    aliases = stock_aliases(stock_master)
    aliases_by_code: dict[str, tuple[str, ...]] = {}
    for alias, (code, _name) in aliases.items():
        aliases_by_code.setdefault(code, tuple())
        aliases_by_code[code] = (*aliases_by_code[code], alias)
    evidence: dict[str, StockResearchEvidence] = {}
    for item in items:
        haystack = " ".join([item.title, item.summary])
        matched: list[tuple[str, str, bool, dict[str, Any] | None]] = []
        for alias, (code, name) in aliases.items():
            if alias and alias in haystack:
                matched.append((code, name, True, None))
        for receipt in item.source_entity_receipts:
            entity = _receipt_entity(receipt, aliases)
            if entity:
                matched.append((entity[0], entity[1], False, receipt))
        unique_matches: dict[str, tuple[str, str, bool, dict[str, Any] | None]] = {}
        for code, name, direct, receipt in matched:
            existing = unique_matches.get(code)
            if existing is None or (direct and not existing[2]):
                unique_matches[code] = (code, name, direct, receipt)
        matched = list(unique_matches.values())
        if not matched:
            continue
        for code, name, direct, receipt in matched:
            theme_only = not direct and receipt is None
            level, confidence = evidence_level(item, direct=direct, theme_only=theme_only)
            cannot = list(item.cannot_confirm)
            if theme_only:
                cannot.append("THEME_ONLY_OR_TAG_MAPPING_NEEDS_REVIEW")
            sentence = (
                _receipt_evidence_sentence(receipt)
                if receipt is not None
                else evidence_sentence(item, name, aliases_by_code.get(code, ()))
            )
            receipt_locator = _receipt_locator(receipt) if receipt is not None else ""
            if receipt is not None and not sentence:
                sentence = f"source-to-entity receipt {receipt_locator} verifies {name}"
            dedup_key = stable_hash("|".join([code, item.trade_date, item.source_type, item.title, sentence]))
            row = StockResearchEvidence(
                evidence_id=stable_hash("evidence|" + dedup_key),
                stock_code=code,
                stock_name=name,
                trade_date=item.trade_date,
                event_time=item.display_event_time or item.event_time,
                source_published_at=item.source_published_at,
                first_seen_at=item.first_seen_at,
                last_checked_at=item.last_checked_at,
                retrieved_at=item.retrieved_at,
                available_at=item.available_at,
                acquisition_provenance=item.acquisition_provenance,
                display_event_time=item.display_event_time or item.event_time,
                is_new_since_last_slot=item.is_new_since_last_slot,
                is_recheck_duplicate=item.is_recheck_duplicate,
                time_bucket=time_bucket(item.display_event_time or item.event_time),
                source_type=item.source_type,
                source_name=item.source_name,
                source_title=item.title,
                source_path=item.source_path,
                url=item.url,
                theme=item.themes[0] if item.themes else "",
                catalyst=item.themes[0] if item.themes else "",
                evidence_sentence=sentence,
                evidence_level=level,
                confidence=confidence,
                extractor="dictionary",
                is_direct_stock_mention=direct,
                is_theme_only_mapping=theme_only,
                dedup_key=dedup_key,
                quality_flags=(f"SOURCE_ENTITY_RECEIPT:{receipt_locator}",) if receipt_locator else (),
                cannot_confirm=tuple(dict.fromkeys(cannot)),
            )
            evidence.setdefault(dedup_key, row)
    return sorted(evidence.values(), key=lambda row: (row.stock_code, row.event_time, row.source_type))


def score_evidence(rows: list[StockResearchEvidence]) -> int:
    score = 0
    for row in rows:
        if row.evidence_level == "L3_STRONG":
            score += 30
        elif row.evidence_level == "L2_MEDIUM":
            score += 15
        else:
            score += 5
    score += 5 * len({row.source_type for row in rows})
    return min(score, 100)


def aggregate_stock_research_daily(evidence_rows: Iterable[StockResearchEvidence]) -> list[StockResearchDaily]:
    grouped: dict[tuple[str, str], list[StockResearchEvidence]] = {}
    for row in evidence_rows:
        grouped.setdefault((row.trade_date, row.stock_code), []).append(row)
    daily: list[StockResearchDaily] = []
    for (_trade_date, _code), rows in grouped.items():
        rows.sort(key=lambda row: row.event_time)
        strong = sum(row.evidence_level == "L3_STRONG" for row in rows)
        medium = sum(row.evidence_level == "L2_MEDIUM" for row in rows)
        weak = sum(row.evidence_level == "L1_WEAK" for row in rows)
        score = score_evidence(rows)
        if strong:
            status = "HOT"
        elif len(rows) >= 2:
            status = "REPEATED"
        elif rows[0].cannot_confirm:
            status = "CANNOT_CONFIRM"
        else:
            status = "NEW"
        daily.append(
            StockResearchDaily(
                stock_code=rows[0].stock_code,
                stock_name=rows[0].stock_name,
                trade_date=rows[0].trade_date,
                first_seen_time=rows[0].event_time,
                last_seen_time=rows[-1].event_time,
                evidence_count=len(rows),
                source_count=len({row.source_type for row in rows}),
                strong_evidence_count=strong,
                medium_evidence_count=medium,
                weak_evidence_count=weak,
                themes=tuple(sorted({row.theme for row in rows if row.theme})),
                top_catalysts=tuple(sorted({row.catalyst for row in rows if row.catalyst})),
                source_types=tuple(sorted({row.source_type for row in rows})),
                latest_evidence_sentence=rows[-1].evidence_sentence,
                research_score=score,
                research_status=status,
                pool_overlap={},
                next_action="补盘口/分时/成交/复盘证据，等待正式池或人工审查确认。",
            )
        )
    return sorted(daily, key=lambda row: (-row.research_score, row.first_seen_time, row.stock_code))


def build_research_pool_bridge(
    trade_date: str,
    daily_rows: Iterable[StockResearchDaily],
    evidence_rows: Iterable[StockResearchEvidence],
    pool_rows: Iterable[dict[str, Any]] | None = None,
) -> list[ResearchPoolBridge]:
    pools_by_code: dict[str, dict[str, Any]] = {}
    for row in pool_rows or []:
        code = str(row.get("stock_code") or row.get("symbol") or row.get("code") or "").strip()
        if code:
            pools_by_code[code] = row
    evidence_by_code: dict[str, list[StockResearchEvidence]] = {}
    for row in evidence_rows:
        evidence_by_code.setdefault(row.stock_code, []).append(row)
    bridges: list[ResearchPoolBridge] = []
    for daily in daily_rows:
        pool = pools_by_code.get(daily.stock_code, {})
        matched_pool = str(pool.get("matched_pool") or pool.get("pool") or "NONE") if pool else "NONE"
        matched_stage = str(pool.get("matched_stage") or pool.get("stage") or "") if pool else ""
        formal_overlap = matched_pool.upper() == "FORMAL" or bool(pool.get("formal_overlap"))
        stage_overlap = bool(matched_stage)
        evidence_ids = tuple(row.evidence_id for row in evidence_by_code.get(daily.stock_code, []))
        max_level = "L3_STRONG" if daily.strong_evidence_count else "L2_MEDIUM" if daily.medium_evidence_count else "L1_WEAK"
        bridges.append(
            ResearchPoolBridge(
                bridge_id=stable_hash("bridge|" + "|".join([trade_date, daily.stock_code, matched_pool, matched_stage])),
                trade_date=trade_date,
                stock_code=daily.stock_code,
                stock_name=daily.stock_name,
                research_score=daily.research_score,
                evidence_level=max_level,
                matched_pool=matched_pool,
                matched_stage=matched_stage,
                formal_overlap=formal_overlap,
                stage_overlap=stage_overlap,
                reason="研报/资讯证据与池或阶段形成只读桥接" if pool else "研报/资讯证据已形成，但未命中池或阶段",
                next_action=daily.next_action,
                source_evidence_ids=evidence_ids,
            )
        )
    return bridges


def assert_research_only(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    forbidden = [word for word in FORBIDDEN_DECISION_WORDS if word in text]
    if forbidden:
        raise ValueError(f"forbidden decision words in research-only payload: {forbidden}")
    if payload.get("write_policy") != READ_ONLY_POLICY:
        raise ValueError("research payload must stay read_only")
    if payload.get("default_status") != RESEARCH_ONLY:
        raise ValueError("research payload must stay RESEARCH_ONLY")


def build_research_lane_snapshot(
    trade_date: str,
    source_rows: Iterable[dict[str, Any]],
    stock_master: dict[str, Any],
    pool_rows: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_items = build_raw_items(trade_date, source_rows)
    items = normalize_research_items(raw_items)
    evidence = extract_stock_evidence(items, stock_master)
    daily = aggregate_stock_research_daily(evidence)
    bridges = build_research_pool_bridge(trade_date, daily, evidence, pool_rows)
    unassigned = unassigned_entity_notes(items, stock_master)
    cannot_confirm = []
    for item in items:
        for reason in item.cannot_confirm:
            cannot_confirm.append({"item_id": item.item_id, "reason": reason})
    cannot_confirm.extend(unassigned)
    summary = {
        "raw_item_count": len(raw_items),
        "research_item_count": len(items),
        "stock_evidence_count": len(evidence),
        "stock_daily_count": len(daily),
        "bridge_count": len(bridges),
        "l3_strong_count": sum(row.evidence_level == "L3_STRONG" for row in evidence),
        "l2_medium_count": sum(row.evidence_level == "L2_MEDIUM" for row in evidence),
        "l1_weak_count": sum(row.evidence_level == "L1_WEAK" for row in evidence),
        "formal_overlap_count": sum(row.formal_overlap for row in bridges),
        "cannot_confirm_count": len(cannot_confirm),
    }
    payload = {
        "ok": True,
        "schema_version": "v3_research_lane.v2",
        "trade_date": trade_date,
        "module_id": "research_intelligence",
        "write_policy": READ_ONLY_POLICY,
        "default_status": RESEARCH_ONLY,
        "buy_gate_effect": NO_BUY_GATE,
        "live_order_effect": NO_BUY_GATE,
        "research_quality_summary": summary,
        "raw_items": [as_plain_dict(row) for row in raw_items],
        "research_items": [as_plain_dict(row) for row in items],
        "stock_research_timeline": [as_plain_dict(row) for row in evidence],
        "stock_research_daily": [as_plain_dict(row) for row in daily],
        "research_pool_bridge": [as_plain_dict(row) for row in bridges],
        "source_manifest": {
            "source_types": sorted({row.source_type for row in raw_items}),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "module_path": "v3.5/domains/research_hourly",
            "version": datetime.now().strftime("%Y%m%d%H%M%S") + "-" + stable_hash(
                "|".join([trade_date, *[row.raw_id for row in raw_items], *[row.evidence_id for row in evidence]])
            )[:8],
            "event_id": "",
        },
        "quality_status": "QUALITY_PASS" if daily else "QUALITY_FAIL",
        "stock_timeline_available": bool(daily and evidence),
        "source_health": {
            "research_module_snapshot": "READY" if daily or raw_items else "EMPTY_OR_UNMAPPED",
            "stock_timeline": "READY" if evidence else "EMPTY_OR_UNMAPPED",
        },
        "integration_state": "generated_snapshot_live",
        "morning_news": {
            "status": "GENERATED_SNAPSHOT",
            "articles": [],
            "articles_count": 0,
            "write_policy": READ_ONLY_POLICY,
            "buy_gate_effect": NO_BUY_GATE,
            "live_order_effect": NO_BUY_GATE,
            "cannot_confirm_items": [],
        },
        "news_workbench": {
            "schema_version": "generated_snapshot.v1",
            "status": "GENERATED_SNAPSHOT",
            "quality_summary": summary,
            "action_rows": [],
            "source_health": {},
            "cannot_confirm_items": [],
            "write_policy": READ_ONLY_POLICY,
            "buy_gate_effect": NO_BUY_GATE,
            "live_order_effect": NO_BUY_GATE,
        },
        "research_sections": [
            {"section_id": "stock_research_daily", "display_name": "股票主线", "count": len(daily), "status": "READY" if daily else "EMPTY_OR_UNMAPPED", "source_path": "stock_research_daily"},
            {"section_id": "stock_research_timeline", "display_name": "股票时间线", "count": len(evidence), "status": "READY" if evidence else "EMPTY_OR_UNMAPPED", "source_path": "stock_research_timeline"},
        ],
        "research_cards": [],
        "lanes": [
            {
                "lane_id": "v3_research_module_generated_snapshot",
                "display_name": "v3.5 研报模块生成快照",
                "status": RESEARCH_ONLY,
                "source_path": "research/hourly/latest.json",
                "opens_buy_gate": False,
                "next_action": "生成完成后供 8872 只读页面读取。",
            }
        ],
        "cannot_confirm": cannot_confirm + [
            {"module": "research_intelligence", "reason": "RESEARCH_ONLY_NO_BUY_GATE"}
        ],
    }
    assert_research_only(payload)
    return payload


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()}) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()})


def write_snapshot_outputs(snapshot: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "research_lane_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )
    write_jsonl(output_dir / "raw_items.jsonl", snapshot.get("raw_items") or [])
    write_jsonl(output_dir / "research_items.jsonl", snapshot.get("research_items") or [])
    write_csv(output_dir / "stock_research_evidence.csv", snapshot.get("stock_research_timeline") or [])
    write_csv(output_dir / "stock_research_daily.csv", snapshot.get("stock_research_daily") or [])
    write_csv(output_dir / "research_pool_bridge.csv", snapshot.get("research_pool_bridge") or [])
    (output_dir / "manifest.json").write_text(json.dumps(snapshot.get("source_manifest") or {}, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    summary = snapshot.get("research_quality_summary") or {}
    cannot_confirm = snapshot.get("cannot_confirm") or []
    report = [
        "# v3.5 研报模块质量报告",
        "",
        f"trade_date: {snapshot['trade_date']}",
        f"schema_version: {snapshot['schema_version']}",
        f"write_policy: {snapshot['write_policy']}",
        f"default_status: {snapshot['default_status']}",
        "",
        "## Counts",
        *[f"- {key}: {value}" for key, value in summary.items()],
        "",
        "## Cannot Confirm",
        *[f"- {item}" for item in cannot_confirm],
    ]
    (output_dir / "quality_report.md").write_text("\n".join(report), encoding="utf-8-sig")


# This is a read-only projection of one already collected source, not a scorer
# or another collector.  Keep the original archive/phase6 payload unchanged.
_HOURLY_SOURCE_TIMES = (
    "retrieved_at", "available_at",
    "event_time", "published_at", "source_published_at", "first_seen_at",
    "last_checked_at", "crawl_time", "display_event_time", "first_seen_time", "last_seen_time",
)
_HOURLY_OBSERVATION_TIMES = frozenset({
    "retrieved_at", "available_at",
    "first_seen_at", "last_checked_at", "crawl_time", "first_seen_time", "last_seen_time",
})


def hourly_source_time(value: Any) -> datetime:
    """Use the existing producer's explicit Shanghai interpretation of naive time."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("HOURLY_SOURCE_PIT_TIMESTAMP_MISSING")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai")) if parsed.tzinfo is None
            else parsed.astimezone(ZoneInfo("Asia/Shanghai")))


def validate_hourly_stage_source(
    source: Mapping[str, Any], *, trade_date: str, slot: str, cutoff: datetime,
    allow_late_observations: bool = False,
) -> None:
    """Validate source identity and times that the archive projection discards.

    A late-observation exception is only used by the original CLI recovery path.
    The stage reader never uses it: every observed timestamp must precede the
    actual stage cutoff.  No date, timestamp, score or delta flag is repaired.
    """
    manifest = source.get("source_manifest")
    if (source.get("trade_date") != trade_date or not isinstance(manifest, Mapping)
            or manifest.get("hourly_slot") != slot):
        raise ValueError("HOURLY_SOURCE_DATE_SLOT_MISMATCH")
    if source.get("slot", slot) != slot or manifest.get("trade_date", trade_date) != trade_date:
        raise ValueError("HOURLY_SOURCE_DATE_SLOT_MISMATCH")
    declared_pit_cutoff = manifest.get("pit_cutoff")
    # New producer snapshots carry an explicit PIT declaration.  Bind it to
    # the slot-derived cutoff before projecting any rows.  A few older unit
    # fixtures predate this field and remain compatible when they have none;
    # once the producer identity (or a declaration itself) is present, a
    # missing declaration is an invalid source rather than an inferred time.
    requires_pit_cutoff = bool(
        source.get("slot") == slot
        or manifest.get("producer") == "ops.collect_hourly_research_input"
        or manifest.get("capture_origin") == "ORIGINAL_SLOT"
        or declared_pit_cutoff not in (None, "")
    )
    if declared_pit_cutoff in (None, ""):
        if requires_pit_cutoff:
            raise ValueError("HOURLY_SOURCE_MANIFEST_PIT_CUTOFF_MISSING")
    else:
        declared_cutoff = hourly_source_time(declared_pit_cutoff)
        expected_cutoff = cutoff.replace(microsecond=0)
        if declared_cutoff != expected_cutoff:
            raise ValueError("HOURLY_SOURCE_MANIFEST_PIT_CUTOFF_MISMATCH")
    for name in ("generated_at", "published_at"):
        if manifest.get(name) not in (None, ""):
            value = hourly_source_time(manifest[name])
            if value.strftime("%Y%m%d") != trade_date or value > cutoff:
                raise ValueError("HOURLY_SOURCE_MANIFEST_PIT_MISMATCH")
    for name in ("raw_items", "research_items", "stock_research_timeline", "stock_research_daily"):
        rows = source.get(name, [])
        if not isinstance(rows, list):
            raise ValueError("HOURLY_SOURCE_ROWS_INVALID:" + name)
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("HOURLY_SOURCE_ROW_INVALID:" + name)
            values = [row]
            if name == "raw_items" and "raw_payload" in row:
                if not isinstance(row["raw_payload"], Mapping):
                    raise ValueError("HOURLY_SOURCE_RAW_PAYLOAD_INVALID")
                values.append(row["raw_payload"])
            for value in values:
                if value.get("trade_date", trade_date) != trade_date or value.get("slot", slot) != slot:
                    raise ValueError("HOURLY_SOURCE_ROW_DATE_SLOT_MISMATCH")
                for field in _HOURLY_SOURCE_TIMES:
                    if value.get(field) in (None, ""):
                        continue
                    if hourly_source_time(value[field]) > cutoff and not (
                        allow_late_observations and field in _HOURLY_OBSERVATION_TIMES
                    ):
                        raise ValueError("HOURLY_SOURCE_ROW_PIT_MISMATCH:" + name + "." + field)


def canonical_stage_a_code(value: Any) -> str:
    """Exact A-share identity only; never extract six digits from a HK/US code."""
    text = str(value or "").strip().upper()
    match = re.fullmatch(r"(?:A\.)?(\d{6})", text)
    return "A." + match.group(1) if match else ""


def _stage_item_identity(row: Mapping[str, Any], *, evidence: bool = False) -> tuple[Any, ...]:
    # extract_stock_evidence copies these exact fields. Its dedup_key includes
    # code and evidence_sentence and is NOT the ResearchItem dedup_key.
    return tuple(row.get(k, "") for k in (
        "trade_date", "source_type", "source_name", "source_path", "url",
    )) + (
        row.get("source_title" if evidence else "title", ""),
        row.get("display_event_time") or row.get("event_time"),
        row.get("source_published_at", ""), row.get("first_seen_at", ""), row.get("last_checked_at", ""),
    )


def project_hourly_stage_fields(source: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Project only explicitly present facts through frozen producer lineage.

    Caller must first verify the raw SHA against the exact archive receipt and
    validate dates/PIT. No title-only join, text/entity re-extraction, quality
    scale conversion, default delta flag or stock_pool.research_score alias.
    Ambiguous/missing lineage affects that evidence/code, never another code.
    """
    normalized: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    raw_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for item in source.get("research_items", []):
        normalized.setdefault(_stage_item_identity(item), []).append(item)
    for raw in source.get("raw_items", []):
        raw_by_id.setdefault(str(raw.get("raw_id") or ""), []).append(raw)
    items: dict[tuple[str, str], dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    gaps: list[str] = []
    for row in source.get("stock_research_timeline", []):
        code = canonical_stage_a_code(row.get("stock_code"))
        if not code:
            continue
        matched = normalized.get(_stage_item_identity(row, evidence=True), [])
        if len(matched) != 1 or not str(matched[0].get("item_id") or ""):
            gaps.append("RESEARCH_ITEM_LINEAGE_MISSING_OR_AMBIGUOUS:" + code)
            continue
        item = matched[0]
        raw_id = str(item.get("raw_id") or "").strip()
        if not raw_id:
            gaps.append("RESEARCH_RAW_LINEAGE_MISSING:" + code)
            continue
        raw_candidates = raw_by_id.get(raw_id, [])
        raw_payload: Mapping[str, Any] = {}
        if len(raw_candidates) == 0:
            gaps.append("RESEARCH_RAW_LINEAGE_MISSING:" + code)
        elif len(raw_candidates) > 1:
            gaps.append("RESEARCH_RAW_LINEAGE_AMBIGUOUS:" + code)
        else:
            raw_payload = raw_candidates[0].get("raw_payload", {})
        output: dict[str, Any] = {
            "stock_code": code, "item_id": item["item_id"], "raw_id": raw_id,
            "source_title": row.get("source_title", ""), "source_path": row.get("source_path", ""),
            "url": row.get("url", ""), "cannot_confirm": list(item.get("cannot_confirm") or []),
        }
        if isinstance(item.get("item_quality"), str):
            output["item_quality"] = item["item_quality"]
        for flag in ("is_new_since_last_slot", "is_recheck_duplicate"):
            values = [r[flag] for r in (item, raw_payload, row) if flag in r]
            if values and all(type(v) is bool for v in values) and len(set(values)) == 1:
                output[flag] = values[0]
            else:
                gaps.append("RESEARCH_DELTA_FLAG_UNPROVEN:" + code)
        numeric = [r["quality_score"] for r in (item, raw_payload) if "quality_score" in r]
        if numeric:
            if all(type(v) in (int, float) and math.isfinite(float(v)) for v in numeric) and len(set(numeric)) == 1:
                output["quality_score"] = numeric[0]
            else:
                gaps.append("RESEARCH_ITEM_QUALITY_SCORE_INVALID:" + code)
        key = (code, str(item["item_id"]))
        if key in items and items[key] != output:
            # Never select one side of a conflicting item/code association.
            raise ValueError("HOURLY_SOURCE_ITEM_CODE_CONFLICT:" + code)
        items.setdefault(key, output)
        evidence.append({"stock_code": code, "evidence_id": row.get("evidence_id"),
                         "cannot_confirm": list(row.get("cannot_confirm") or [])})
    return list(items.values()), evidence, list(dict.fromkeys(gaps))
