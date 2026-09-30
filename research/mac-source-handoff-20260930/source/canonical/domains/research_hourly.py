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
    from domains._research_hourly_parts.research_projection import _build_raw_items_body as _v4_impl
    return _v4_impl(globals(), trade_date, rows)


def normalize_research_items(raw_items: Iterable[RawResearchItem]) -> list[ResearchItem]:
    from domains._research_hourly_parts.research_projection import _normalize_research_items_body as _v4_impl
    return _v4_impl(globals(), raw_items)


def stock_aliases(stock_master: dict[str, Any]) -> dict[str, tuple[str, str]]:
    from domains._research_hourly_parts.rows_topics import _stock_aliases_body as _v4_impl
    return _v4_impl(globals(), stock_master)


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
    from domains._research_hourly_parts.source_evidence import __receipt_entity_body as _v4_impl
    return _v4_impl(globals(), receipt, aliases)


def unassigned_entity_notes(
    items: Iterable[ResearchItem], stock_master: dict[str, Any]
) -> list[dict[str, Any]]:
    """Report candidate tags that lack text or an explicit mapping receipt."""
    from domains._research_hourly_parts.rows_topics import _unassigned_entity_notes_body as _v4_impl
    return _v4_impl(globals(), items, stock_master)


def normalized_source_evidence_level(item: ResearchItem) -> tuple[str, str] | None:
    from domains._research_hourly_parts.source_evidence import _normalized_source_evidence_level_body as _v4_impl
    return _v4_impl(globals(), item)


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
    from domains._research_hourly_parts.source_evidence import _extract_stock_evidence_body as _v4_impl
    return _v4_impl(globals(), items, stock_master)


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
    from domains._research_hourly_parts.rows_topics import _aggregate_stock_research_daily_body as _v4_impl
    return _v4_impl(globals(), evidence_rows)


def build_research_pool_bridge(
    trade_date: str,
    daily_rows: Iterable[StockResearchDaily],
    evidence_rows: Iterable[StockResearchEvidence],
    pool_rows: Iterable[dict[str, Any]] | None = None,
) -> list[ResearchPoolBridge]:
    from domains._research_hourly_parts.research_projection import _build_research_pool_bridge_body as _v4_impl
    return _v4_impl(globals(), trade_date, daily_rows, evidence_rows, pool_rows)


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
    from domains._research_hourly_parts.lane_snapshot import _build_research_lane_snapshot_body as _v4_impl
    return _v4_impl(globals(), trade_date, source_rows, stock_master, pool_rows)


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
    from domains._research_hourly_parts.research_projection import _write_snapshot_outputs_body as _v4_impl
    return _v4_impl(globals(), snapshot, output_dir)


# This is a read-only projection of one already collected source, not a scorer
# or another collector.  Keep the original archive/phase6 payload unchanged.
_HOURLY_SOURCE_TIMES = (
    "event_time", "published_at", "source_published_at", "first_seen_at",
    "last_checked_at", "crawl_time", "display_event_time", "first_seen_time", "last_seen_time",
)
_HOURLY_OBSERVATION_TIMES = frozenset({
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
    manifest_pit_cutoff: datetime | None = None,
) -> None:
    """Validate source identity and times that the archive projection discards.

    A late-observation exception is only used by the original CLI recovery path.
    The stage reader never uses it: every observed timestamp must precede the
    actual stage cutoff.  No date, timestamp, score or delta flag is repaired.
    """
    from domains._research_hourly_parts.source_evidence import _validate_hourly_stage_source_body as _v4_impl
    return _v4_impl(globals(), source, trade_date=trade_date, slot=slot, cutoff=cutoff, allow_late_observations=allow_late_observations, manifest_pit_cutoff=manifest_pit_cutoff)


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
    from domains._research_hourly_parts.research_projection import _project_hourly_stage_fields_body as _v4_impl
    return _v4_impl(globals(), source)
