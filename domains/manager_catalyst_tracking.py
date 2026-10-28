"""PIT-safe catalyst aggregation and cross-day research tracking for HK manager workbench.

This module is deliberately evidence-preserving.  It consumes already-owned
hourly research inputs and previously materialized manager-workbench artifacts;
it does not fetch news, create a security master, alter formal Stage ranking, or
update BUY gates.

Security mapping policy (R2C v1)
--------------------------------
1. A catalyst can be attached to a HK candidate only when a structured research
   row names the exact current-universe security name, or carries an explicit
   normalized ``HK.#####`` code.
2. Theme aggregation uses the upstream research row's structured ``themes`` /
   ``theme`` classification only. Raw-text keyword matches are not counted as
   theme-strength evidence and never create a stock mapping.
3. ``published_at`` / ``first_seen_at`` evidence later than the requested
   ``as_of`` is excluded from same-session attribution.
4. Duplicate URLs / topic ids / raw ids / title+published pairs collapse before
   cross-day counts are computed.

The output is research-only context.  It never changes production ranking,
model score, or execution state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from infrastructure.manager_input_attestation import read_attestation, PublicationError, digest

_VERIFIED_EVENT = object()
HK_TZ = ZoneInfo("Asia/Hong_Kong")
RULE_VERSION = "manager-catalyst-tracking-r2-rework-v1"
HK_CODE_RE = re.compile(r"^HK\.\d{5}$")
DATE_RE = re.compile(r"^\d{8}$")
EXPLICIT_HK_RE = re.compile(r"\bHK\.(\d{5})\b", re.IGNORECASE)

STRUCTURED_THEME_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("ROBOTICS", ("机器人", "具身智能", "人形机器人"), ("机器人", "具身智能", "人形机器人", "robotics")),
    ("OPTICAL_INTERCONNECT", ("光通信", "光模块", "CPO", "硅光", "光互连"), ("光通信", "光模块", "CPO", "硅光", "光互连", "optical")),
    ("AI_APPLICATION", ("AI应用", "大模型", "智能体", "多模态"), ("AI", "大模型", "智能体", "多模态", "agent")),
    ("SEMICONDUCTOR", ("半导体", "芯片", "碳化硅", "SiC"), ("半导体", "芯片", "晶圆", "碳化硅", "SiC")),
)



def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _as_dt(value: Any) -> datetime | None:
    # Availability has no local-time/mtime fallback. Input event timestamps
    # also remain unknown when their timezone is not explicit.
    if not isinstance(value,str) or not value.strip(): return None
    try: parsed=datetime.fromisoformat(value.strip().replace("Z","+00:00"))
    except ValueError: return None
    if parsed.tzinfo is None: return None
    return parsed.astimezone(HK_TZ)


def _not_after(value: Any, as_of: datetime) -> bool:
    parsed = _as_dt(value)
    return parsed is not None and parsed <= as_of.astimezone(HK_TZ)


def _first_text(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _list_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Extract rows from known research input shapes without guessing data."""
    rows: list[Mapping[str, Any]] = []
    for key in ("research_items", "raw_items", "items", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, Mapping))
    # Stable de-dup by object JSON. Some inputs intentionally expose the same
    # item in raw+research arrays; aggregation must not double-count it.
    seen: set[str] = set()
    output: list[Mapping[str, Any]] = []
    for row in rows:
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        output.append(row)
    return output


def _row_time(row: Mapping[str, Any]) -> tuple[str | None, str | None]:
    published = _first_text(
        row,
        (
            "source_published_at",
            "published_at",
            "publish_time",
            "published_time",
            "created_at",
            "created_time",
            "event_time",
        ),
    ) or None
    first_seen = _first_text(
        row,
        (
            "first_seen_at",
            "first_seen_time",
            "observed_at",
            "available_at",
            "fetched_at",
            "collected_at",
            "ingested_at",
        ),
    ) or None
    return published, first_seen


def _pit_eligible(row: Mapping[str, Any], as_of: datetime) -> tuple[bool, str]:
    published, first_seen = _row_time(row)
    # If the source carries an evidence timestamp, every supplied evidence
    # timestamp must be <= as_of.  Rows with no usable time cannot qualify as a
    # same-session stock catalyst, but may remain visible as an input gap.
    if not published or not first_seen:
        return False, "CATALYST_EVENT_TIME_INCOMPLETE"
    parsed=[_as_dt(published),_as_dt(first_seen)]
    if any(value is None for value in parsed):
        return False, "CATALYST_TIMESTAMP_INVALID"
    if any(value > as_of.astimezone(HK_TZ) for value in parsed):
        return False, "CATALYST_AFTER_AS_OF"
    if parsed[0] > parsed[1]:
        return False, "CATALYST_EVENT_TIME_ORDER_INVALID"
    return True, "PIT_OK"


def _structured_theme_labels(row: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            labels.append(value.strip())
        elif isinstance(value, list):
            labels.extend(item.strip() for item in value if isinstance(item, str) and item.strip())

    collect(row.get("themes"))
    collect(row.get("theme"))
    raw_payload = row.get("raw_payload")
    if isinstance(raw_payload, Mapping):
        collect(raw_payload.get("themes"))
        collect(raw_payload.get("theme"))
    # Preserve first appearance order while de-duplicating exact upstream labels.
    return list(dict.fromkeys(labels))


def _themes(row: Mapping[str, Any], *, include_extended_themes: bool = False) -> list[str]:
    """Conservative theme evidence: structured label + content corroboration.

    Upstream structured ``themes`` is the authority that admits a theme class.
    Title/summary/raw text only corroborates that class for this individual
    event.  Text alone can never create a theme event, so cross-day strength is
    not a bare keyword counter.
    """
    labels = _structured_theme_labels(row)
    if not labels:
        return []
    label_text = " / ".join(labels)
    content_parts: list[str] = []
    for key in ("title", "summary", "content", "text", "raw_text", "body"):
        value = row.get(key)
        if isinstance(value, str):
            content_parts.append(value)
    raw_payload = row.get("raw_payload")
    if isinstance(raw_payload, Mapping):
        for key in ("title", "raw_text", "summary"):
            value = raw_payload.get(key)
            if isinstance(value, str):
                content_parts.append(value)
    content_text = "\n".join(content_parts)

    found: list[str] = []
    ai_tokens = ("AI应用", "大模型", "人工智能", "AI算力")
    health_tokens = ("医药", "医疗", "创新药")
    content_health_tokens = ("医药", "医疗", "药企", "新药", "药物", "临床", "mRNA")
    if include_extended_themes:
        ai_tokens += ("AI医疗", "AI制药", "AI药物研发", "AIDD", "AI_HEALTHCARE")
        health_tokens += ("制药", "药物研发", "AIDD", "AI_HEALTHCARE")
        content_health_tokens += ("drug discovery", "drug development", "clinical development", "pharma")
    has_structured_ai = any(token in label_text for token in ai_tokens)
    has_structured_health = any(token in label_text for token in health_tokens)
    has_content_ai = any(token.lower() in content_text.lower() for token in ("AI", "大模型", "人工智能", "AI4S", "Anthropic"))
    has_content_health = any(token.lower() in content_text.lower() for token in content_health_tokens)
    if has_structured_ai and has_structured_health and has_content_ai and has_content_health:
        found.append("AI_HEALTHCARE")

    for theme, structured_tokens, content_tokens in STRUCTURED_THEME_RULES:
        if any(token in label_text for token in structured_tokens) and any(
            token.lower() in content_text.lower() for token in content_tokens
        ):
            found.append(theme)
    return list(dict.fromkeys(found))



def _event_key(row: Mapping[str, Any], published: str | None) -> str:
    strong = _first_text(row, ("url", "source_url", "topic_id", "raw_id", "item_id", "id"))
    if strong:
        return f"id:{strong}"
    title = _first_text(row, ("title", "headline", "summary"))
    return "fallback:" + hashlib.sha256(f"{title}|{published or ''}".encode("utf-8")).hexdigest()


def _normalize_hk_code(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if HK_CODE_RE.fullmatch(text):
        return text
    return None


def _structured_security_names(row: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("stock_name", "security_name", "company_name"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    candidates = row.get("mentioned_stock_candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                names.append(candidate.strip())
            elif isinstance(candidate, Mapping):
                for key in ("stock_name", "security_name", "name"):
                    value = candidate.get(key)
                    if isinstance(value, str) and value.strip():
                        names.append(value.strip())
                        break
    return names


def _structured_security_codes(row: Mapping[str, Any]) -> list[str]:
    codes: list[str] = []
    for key in ("stock_code", "security_code", "code", "symbol"):
        code = _normalize_hk_code(row.get(key))
        if code:
            codes.append(code)
    candidates = row.get("mentioned_stock_candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                for key in ("stock_code", "security_code", "code", "symbol"):
                    code = _normalize_hk_code(candidate.get(key))
                    if code:
                        codes.append(code)
                        break
    return codes


@dataclass(frozen=True)
class CatalystEvent:
    event_id: str
    source_date: str
    source_ref: str
    source_sha256: str
    source_run_id: str
    source_owner: str
    source_available_at: str | None
    title: str
    published_at: str | None
    first_seen_at: str | None
    themes: tuple[str, ...]
    mapped_symbols: tuple[str, ...]
    mapping_basis: str
    publication_ref: str | None = None
    publication_sha256: str | None = None
    source_url: str | None = None
    _seal: object = field(default=None,repr=False,compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source_date": self.source_date,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "source_run_id": self.source_run_id,
            "source_owner": self.source_owner,
            "source_available_at": self.source_available_at,
            "title": self.title,
            "published_at": self.published_at,
            "first_seen_at": self.first_seen_at,
            "themes": list(self.themes),
            "mapped_symbols": list(self.mapped_symbols),
            "mapping_basis": self.mapping_basis,
            "publication_ref": self.publication_ref,
            "publication_sha256": self.publication_sha256,
        }


def read_catalyst_events(
    paths: Iterable[Path],
    *,
    as_of: datetime,
    universe_names: Mapping[str, str],
    reference_root: Path | None = None,
    owner_root: Path | None = None,
    include_extended_themes: bool = False,
) -> tuple[list[CatalystEvent], list[str]]:
    """Read/dedupe PIT-safe events from already-materialized research inputs.

    ``universe_names`` maps normalized HK codes to the exact current-universe
    display name.  Name mapping is accepted only when that name is unique.
    """
    if as_of.tzinfo is None:
        return [], ["CATALYST_AS_OF_NAIVE"]
    if reference_root is None or owner_root is None:
        return [], ["CATALYST_OWNER_BINDING_MISSING"]
    as_of = as_of.astimezone(HK_TZ)
    reverse: dict[str, list[str]] = {}
    for symbol, name in universe_names.items():
        if HK_CODE_RE.fullmatch(symbol) and isinstance(name, str) and name.strip():
            reverse.setdefault(name.strip(), []).append(symbol)

    output: list[CatalystEvent] = []
    gaps: list[str] = []
    seen_events: set[str] = set()
    for path in sorted(set(paths)):
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            gaps.append(f"CATALYST_INPUT_UNREADABLE:{path.name}")
            continue
        if not isinstance(payload, Mapping):
            gaps.append(f"CATALYST_INPUT_INVALID:{path.name}")
            continue
        try:
            attestation=read_attestation(path,data_root=reference_root,owner_root=owner_root,as_of=as_of)
        except (PublicationError,OSError,ValueError,TypeError,KeyError):
            gaps.append("CATALYST_PUBLICATION_UNVERIFIED:"+path.name)
            continue
        source_date=attestation["trade_date"]
        source_sha=attestation["artifact_sha256"]
        source_ref=attestation["artifact_ref"]
        source_owner=attestation["producer"]
        source_run_id=attestation["run_id"]
        source_available_at=attestation["available_at"]
        publication_ref=source_ref+".publication.json"
        publication_sha=digest((reference_root/publication_ref).read_bytes())
        for row in _list_rows(payload):
            eligible, reason = _pit_eligible(row, as_of)
            if not eligible:
                if reason not in gaps:
                    gaps.append(reason)
                continue
            published, first_seen = _row_time(row)
            if _as_dt(first_seen) > _as_dt(source_available_at):
                gaps.append("CATALYST_EVENT_AFTER_SOURCE_PUBLICATION")
                continue
            event_key = _event_key(row, published)
            if event_key in seen_events:
                continue
            seen_events.add(event_key)
            explicit_codes = sorted(
                {code for code in _structured_security_codes(row) if code in universe_names}
            )
            mapped = set(explicit_codes)
            mapping_basis = "EXPLICIT_HK_CODE" if explicit_codes else "UNMAPPED"
            if not explicit_codes:
                for name in _structured_security_names(row):
                    symbols = reverse.get(name, [])
                    if len(symbols) == 1:
                        mapped.add(symbols[0])
                if mapped:
                    mapping_basis = "EXACT_UNIQUE_UNIVERSE_NAME"
            title = _first_text(row, ("title", "headline", "summary")) or "未命名研究事件"
            output.append(
                CatalystEvent(
                    event_id=hashlib.sha256(
                        f"{source_date}|{event_key}".encode("utf-8")
                    ).hexdigest()[:24],
                    source_date=source_date,
                    source_ref=source_ref,
                    source_sha256=source_sha,
                    source_run_id=source_run_id,
                    source_owner=source_owner,
                    source_available_at=source_available_at,
                    title=title[:240],
                    published_at=published,
                    first_seen_at=first_seen,
                    themes=tuple(_themes(row, include_extended_themes=include_extended_themes)),
                    mapped_symbols=tuple(sorted(mapped)),
                    mapping_basis=mapping_basis,
                    publication_ref=publication_ref,
                    publication_sha256=publication_sha,
                    source_url=(_first_text(row, ("url", "source_url", "canonical_url")) or
                                (_first_text(row["raw_payload"], ("url", "source_url", "canonical_url"))
                                 if isinstance(row.get("raw_payload"), Mapping) else "") or None),
                    _seal=_VERIFIED_EVENT,
                )
            )
    output.sort(key=lambda item: (item.published_at or item.first_seen_at or "", item.event_id))
    return output, sorted(set(gaps))


def candidate_catalyst(symbol: str, events: Sequence[CatalystEvent], *, as_of: datetime | None = None) -> dict[str, Any]:
    admitted=[event for event in events if event._seal is _VERIFIED_EVENT and symbol in event.mapped_symbols
              and as_of is not None and _not_after(event.source_available_at,as_of)]
    matched=[event for event in admitted if _as_dt(event.first_seen_at).date()==as_of.astimezone(HK_TZ).date()]
    if admitted and not matched:
        return {"status":"KNOWN_CONTEXT","summary":"已有直接资料；不是当天新增催化", "event_ids":[x.event_id for x in admitted],
                "themes":sorted({t for x in admitted for t in x.themes}),"evidence":[],"rule_version":RULE_VERSION}

    if not matched:
        return {
            "status": "UNKNOWN",
            "summary": "截至 as_of 未发现可按显式港股代码或唯一证券名直接映射的催化证据",
            "event_ids": [],
            "themes": [],
            "evidence": [],
            "rule_version": RULE_VERSION,
        }
    themes = sorted({theme for event in matched for theme in event.themes})
    evidence = [
        {
            "owner": event.source_owner,
            "role": "CATALYST_RESEARCH_INPUT",
            "artifact_ref": event.source_ref,
            "run_id": event.source_run_id,
            "sha256": event.source_sha256,
            "source_date": event.source_date,
            "reason": f"direct security mapping via {event.mapping_basis}",
            "publication_ref": event.publication_ref,
            "publication_sha256": event.publication_sha256,
            "published_at": event.published_at,
            "first_seen_at": event.first_seen_at,
            "available_at": event.source_available_at or event.first_seen_at,
        }
        for event in matched
    ]
    return {
        "status": "CONFIRMED_PIT",
        "summary": "；".join(event.title for event in matched[:3]),
        "event_ids": [event.event_id for event in matched],
        "themes": themes,
        "mapping_basis": sorted({event.mapping_basis for event in matched}),
        "evidence": evidence,
        "rule_version": RULE_VERSION,
    }


def theme_summary(events: Sequence[CatalystEvent]) -> list[dict[str, Any]]:
    grouped: dict[str, list[CatalystEvent]] = {}
    for event in events:
        if event._seal is not _VERIFIED_EVENT: continue
        for theme in event.themes:
            grouped.setdefault(theme, []).append(event)
    rows: list[dict[str, Any]] = []
    for theme, items in sorted(grouped.items()):
        # Require two deduplicated events before calling this a theme change.
        if len(items) < 2:
            continue
        latest = max(
            (_as_dt(item.first_seen_at) or _as_dt(item.published_at) for item in items),
            default=None,
        )
        if latest is None:
            continue
        rows.append(
            {
                "theme": theme,
                "event_count": len(items),
                "event_ids": [item.event_id for item in items],
                "occurred_at": latest.isoformat(timespec="seconds"),
                "reason": f"{theme} 在 PIT 截止前出现 {len(items)} 个去重且具上游结构化主题标签的事件；仅作研究主题聚合，不自动映射股票",
                "rule_version": RULE_VERSION,
            }
        )
    return rows


def prior_workbench_candidates(path: Path, *, expected_date: str, as_of: datetime | None = None) -> dict[str, Mapping[str, Any]]:
    """Return candidates only from the canonical B1 exact-1530 validator."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        from apps.api.v35_api.manager_workbench_router import validate_workbench_payload

        validated = validate_workbench_payload(payload, expected_date=expected_date)
        observed=_as_dt(validated.get("as_of")); generated=_as_dt(validated.get("generated_at"))
        if (observed is None or generated is None or observed.strftime("%Y%m%d")!=expected_date
            or not (15,30) <= (observed.hour,observed.minute) < (15,32)
            or generated.strftime("%Y%m%d")!=expected_date
            or generated<observed or (as_of is not None and generated>as_of)):
            return {}
        # B1 validates every candidate, lane, safety flag, run and source hash.
        # A prior artifact without timestamped independent lineage is not reusable.
        if not validated.get("run_id"): return {}
        for candidate in validated.get("candidates",[]):
            for source in candidate.get("sources",[]):
                if any(not source.get(k) for k in ("source_date","run_id","sha256","reason","observed_at","available_at")):
                    return {}
                if source["source_date"] > expected_date or _as_dt(source["observed_at"]) > _as_dt(source["available_at"]):
                    return {}
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError, KeyError):
        return {}
    if validated.get("status") not in {"READY", "PARTIAL", "STALE"}:
        return {}
    rows = validated.get("candidates")
    if not isinstance(rows, list):
        return {}
    output: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = row.get("symbol")
        if isinstance(symbol, str) and HK_CODE_RE.fullmatch(symbol) and symbol not in output:
            output[symbol] = row
    return output

@dataclass(frozen=True)
class VerifiedPrior:
    rows: Mapping[str,Mapping[str,Any]]
    source: Mapping[str,Any]
    _seal: object=field(default=None,repr=False,compare=False)


def read_prior_evidence(state_root: Path, *, expected_date: str, as_of: datetime) -> VerifiedPrior | None:
    from infrastructure.manager_input_attestation import resolve
    path=resolve(state_root,f'workbench_research/{expected_date}/1530.json')
    try:
        before=path.read_bytes()
        rows=prior_workbench_candidates(path,expected_date=expected_date,as_of=as_of)
        after=path.read_bytes()
        if not rows or before!=after: return None
        payload=json.loads(before)
        source={'owner':'v4.manager_workbench.close_discovery','role':'PREVIOUS_EXACT_WORKBENCH_RESEARCH',
                'market':'HK_CONNECT','lane':'CONTINUOUS_TRACKING','source_date':expected_date,
                'artifact_ref':f'workbench_research/{expected_date}/1530.json','run_id':payload['run_id'],
                'sha256':_sha_bytes(before),'observed_at':payload['as_of'],'available_at':payload['generated_at'],
                'reason':'前一交易日完整B1合同验证的观察；仅持续跟踪，不更改正式排名'}
        return VerifiedPrior(rows,source,_VERIFIED_EVENT)
    except (OSError,ValueError,TypeError,KeyError): return None


def verified_prior_rows(evidence: Any) -> tuple[Mapping[str,Mapping[str,Any]],Mapping[str,Any] | None]:
    if isinstance(evidence,VerifiedPrior) and evidence._seal is _VERIFIED_EVENT:
        return evidence.rows,evidence.source
    return {},None
