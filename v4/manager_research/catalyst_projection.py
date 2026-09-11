"""Pure cached-catalyst projection; never performs I/O or source collection."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Mapping
from .event_source import (
    EVENT_FOCUS_WINDOW_DAYS, _EVENT_BODY_STRONG_TOKENS,
    _classify_hkex_business_clause, _is_routine_hkex_event_title,
    build_catalyst_advice, event_is_focus_eligible,
)
from .financial_projection import _build_research_sections

_CACHED_EVENT_LEGAL_TOKENS = (
    "by order of the board",
    "by order of board",
    "order of the board",
    "for and on behalf of the board",
    "registered office",
    "no responsibility",
    "listing rules",
    "this announcement is made pursuant",
    "pursuant to the listing",
    "hereinafter",
    "memorandum and articles",
    "incorporated in",
    "company secretary",
    "disclaimer",
    "information only",
)

def _cached_event_semantic_class(event: Mapping[str, Any]) -> str:
    """Classify a cached event using the same action bridge as fresh parses."""

    if event.get("source_kind") == "OFFICIAL":
        title = str(event.get("source_title") or event.get("catalyst") or "")
        if _is_routine_hkex_event_title(title):
            return "NON_SUBSTANTIVE"
        if event.get("body_parsed") is not True:
            return "UNCONFIRMED"
        excerpt = str(event.get("source_excerpt") or event.get("why_might_affect_business") or "").strip()
        raw_score = event.get("score")
        score = int(raw_score) if isinstance(raw_score, int) and not isinstance(raw_score, bool) else 0
        score = max(score, sum(1 for token in _EVENT_BODY_STRONG_TOKENS if token.lower() in excerpt.lower()))
        _event_kind, reason = _classify_hkex_business_clause(excerpt, score, title=title)
        if reason:
            return "UNCONFIRMED"
    if (
        event.get("event_relevant") is False
        or event.get("event_status") == "CANNOT_CONFIRM"
        or event.get("summary_status") == "UNCONFIRMED"
    ):
        return "UNCONFIRMED"
    return "ELIGIBLE"

def _cached_event_requires_semantic_downgrade(event: Mapping[str, Any]) -> str | None:
    """Detect old cached event rows that were promoted from boilerplate.

    This is intentionally a pure projection guard.  It lets a GET correct a
    stale cached ``ORDER_OR_CUSTOMER``/``COOPERATION`` label immediately while
    retaining the original source URL, body hash and page locator.
    """

    semantic_class = _cached_event_semantic_class(event)
    if semantic_class == "NON_SUBSTANTIVE":
        return "CACHE_SEMANTIC_NON_SUBSTANTIVE"
    if event.get("summary_status") == "UNCONFIRMED" or event.get("event_status") == "CANNOT_CONFIRM":
        return None
    text = " ".join(
        str(event.get(key) or "")
        for key in ("source_excerpt", "why_might_affect_business", "catalyst", "source_title")
    ).strip().lower()
    if event.get("source_kind") == "OFFICIAL" and event.get("body_parsed") is True:
        excerpt = str(event.get("source_excerpt") or event.get("why_might_affect_business") or "").strip()
        raw_score = event.get("score")
        score = int(raw_score) if isinstance(raw_score, int) and not isinstance(raw_score, bool) else 0
        lower_excerpt = excerpt.lower()
        score = max(score, sum(1 for token in _EVENT_BODY_STRONG_TOKENS if token.lower() in lower_excerpt))
        _event_kind, reason = _classify_hkex_business_clause(
            excerpt,
            score,
            title=str(event.get("source_title") or event.get("catalyst") or ""),
        )
        if reason:
            reason_code = {
                "HKEX_EVENT_LEGAL_OR_SIGNATURE_TEXT": "LEGAL_OR_SIGNATURE_TEXT",
                "HKEX_EVENT_BUSINESS_CLAUSE_TOO_SHORT": "SHORT_BUSINESS_TEXT",
                "HKEX_EVENT_ROUTINE_DOCUMENT_EXCLUDED": "NON_SUBSTANTIVE",
            }.get(reason, "BUSINESS_ACTION_UNCONFIRMED")
            return f"CACHE_SEMANTIC_DOWNGRADE_{reason_code}"
        # The same clause classifier is the source of truth for a fresh
        # official body parse.  A valid MARKET_ACCESS clause such as
        # "included in the list of eligible securities" therefore remains
        # interpretable when it is only being projected from cache.
        return None
    if any(token in text for token in _CACHED_EVENT_LEGAL_TOKENS):
        return "CACHE_SEMANTIC_DOWNGRADE_LEGAL_OR_SIGNATURE_TEXT"
    return None

def _downgrade_cached_event(
    event: Mapping[str, Any],
    reason: str,
    *,
    semantic_class: str = "UNCONFIRMED",
) -> dict[str, Any]:
    projected = dict(event)
    projected.setdefault("original_event_type", event.get("event_type"))
    projected["event_type"] = "OFFICIAL_UNCONFIRMED"
    projected["event_relevant"] = False
    projected["event_status"] = "CANNOT_CONFIRM"
    projected["summary_status"] = "UNCONFIRMED"
    projected["summary_reason"] = (
        "正文和定位已保留；原缓存材料属于例行公司事务，不计作业务事件或焦点排名。"
        if semantic_class == "NON_SUBSTANTIVE"
        else "正文和定位已保留；原缓存摘要未形成完整业务动作条款，不计作业务事件或焦点排名。"
    )
    projected["official_confirmation_status"] = "CANNOT_CONFIRM"
    projected["evidence_level"] = "OFFICIAL_BODY_PARSED_UNCONFIRMED"
    projected["semantic_class"] = semantic_class
    projected["why_might_affect_business"] = "正文和定位已保留；业务影响摘要待核实，不计作已解释事件。"
    projected["body_parse_reason"] = reason
    gaps = projected.get("market_confirmation_gap")
    projected["market_confirmation_gap"] = list(dict.fromkeys([
        *([str(item) for item in gaps if item] if isinstance(gaps, list) else []),
        "BUSINESS_SUMMARY_UNCONFIRMED",
    ]))
    return projected

def _assign_catalyst_focus_ranks(rows: list[dict[str, Any]], target_trade_date: str) -> None:
    """Give at most three eligible exact-pool rows unique continuous ranks."""

    candidates: list[tuple[int, int, str, str, dict[str, Any], list[dict[str, Any]]]] = []
    for index, row in enumerate(rows):
        result = row.get("catalyst_result")
        if not isinstance(result, Mapping):
            continue
        events = [item for item in result.get("events", []) if isinstance(item, Mapping)]
        focus_events = [
            dict(item) for item in events
            if event_is_focus_eligible(item, target_trade_date=target_trade_date)
        ]
        advice = dict(result.get("catalyst_advice")) if isinstance(result.get("catalyst_advice"), Mapping) else {}
        advice["priority_rank"] = None
        advice["focus_eligible"] = bool(focus_events)
        advice["focus_window_days"] = EVENT_FOCUS_WINDOW_DAYS
        result["catalyst_advice"] = advice  # result is a fresh row projection
        if not focus_events:
            continue
        latest = max(str(event.get("publisher_timestamp") or "") for event in focus_events)
        current = 1 if any(event.get("as_of_bucket") == "current" for event in focus_events) else 0
        media_cooperation = 1 if any(
            event.get("source_kind") == "MEDIA" and event.get("event_type") == "COOPERATION"
            for event in focus_events
        ) else 0
        candidates.append((current, media_cooperation, latest, str(row.get("code") or ""), row, focus_events))
    def publication_timestamp(value: str) -> float:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return float("-inf")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    candidates.sort(key=lambda item: (-item[0], -item[1], -publication_timestamp(item[2]), item[3]))
    for rank, (_current, _media, _latest, _code, row, _events) in enumerate(candidates[:3], start=1):
        result = row.get("catalyst_result")
        if not isinstance(result, dict):
            continue
        advice = result.get("catalyst_advice")
        if not isinstance(advice, dict):
            advice = {}
            result["catalyst_advice"] = advice
        advice["priority_rank"] = rank
        advice["priority_label"] = "首选" if rank == 1 else "次选" if rank == 2 else "研究优先"
        advice["priority_reason"] = (
            f"近{EVENT_FOCUS_WINDOW_DAYS}个自然日内存在完整业务动作条款，按目标日固定候选池的"
            f"可解释催化排为焦点 #{rank}；官方确认、订单/收入和量价仍待核验。"
        )
    for row in rows:
        result = row.get("catalyst_result")
        if not isinstance(result, dict):
            continue
        advice = result.get("catalyst_advice")
        if isinstance(advice, dict) and advice.get("focus_eligible") and advice.get("priority_rank") is None:
            advice["priority_reason"] = (
                f"近{EVENT_FOCUS_WINDOW_DAYS}个自然日内存在可解释事件，但焦点只保留前3条；"
                "其余材料仍在完整候选与审计区，不能据此扩展重点集合。"
            )

def _project_cached_catalysts(product: Mapping[str, Any]) -> dict[str, Any]:
    """Purely re-project cached event/financial wording for a GET response."""

    projected = dict(product)
    target = str(product.get("target_trade_date") or "")
    projected_rows: list[dict[str, Any]] = []
    for raw_row in product.get("rows", []) if isinstance(product.get("rows"), list) else []:
        if not isinstance(raw_row, Mapping):
            continue
        row = dict(raw_row)
        raw_result = row.get("catalyst_result")
        if isinstance(raw_result, Mapping):
            result = dict(raw_result)
            events: list[dict[str, Any]] = []
            downgraded_urls: set[str] = set()
            for raw_event in result.get("events", []) if isinstance(result.get("events"), list) else []:
                if not isinstance(raw_event, Mapping):
                    continue
                reason = _cached_event_requires_semantic_downgrade(raw_event)
                semantic_class = _cached_event_semantic_class(raw_event)
                event = (
                    _downgrade_cached_event(raw_event, reason, semantic_class=semantic_class)
                    if reason
                    else {**dict(raw_event), "semantic_class": semantic_class}
                )
                if reason:
                    url = str(event.get("source_url") or event.get("source_url") or "")
                    if url:
                        downgraded_urls.add(url)
                events.append(event)
            result["events"] = events
            by_key = {
                str(event.get("event_id") or event.get("source_url") or event.get("source_title") or ""): event
                for event in events
            }
            for projection_name in ("historical_events", "current_events"):
                raw_projection = result.get(projection_name)
                if isinstance(raw_projection, list):
                    result[projection_name] = [
                        by_key.get(str(item.get("event_id") or item.get("source_url") or item.get("source_title") or ""), dict(item))
                        for item in raw_projection
                        if isinstance(item, Mapping)
                    ]
            if target:
                result["catalyst_advice"] = build_catalyst_advice(events, target_trade_date=target)
            gaps = [
                str(item) for event in events
                for item in (event.get("market_confirmation_gap") if isinstance(event.get("market_confirmation_gap"), list) else [])
                if item
            ]
            result["market_confirmation_gap"] = list(dict.fromkeys(gaps))
            receipts = []
            for raw_receipt in result.get("source_receipts", []) if isinstance(result.get("source_receipts"), list) else []:
                if not isinstance(raw_receipt, Mapping):
                    continue
                receipt = dict(raw_receipt)
                if str(receipt.get("url") or "") in downgraded_urls:
                    receipt["status"] = "CANNOT_CONFIRM"
                    receipt["event_relevant"] = False
                    receipt["summary_status"] = "UNCONFIRMED"
                receipts.append(receipt)
            result["source_receipts"] = receipts
            row["catalyst_result"] = result
            current_research = dict(row.get("current_research")) if isinstance(row.get("current_research"), Mapping) else {}
            current_research["catalyst_advice"] = result.get("catalyst_advice")
            row["current_research"] = current_research
        facts = row.get("facts")
        if isinstance(facts, list) and row.get("status") == "READY":
            sections = _build_research_sections(
                str(row.get("issuer") or row.get("name") or row.get("code") or ""),
                str(row.get("code") or ""),
                [item for item in facts if isinstance(item, Mapping)],
                row.get("observation") if isinstance(row.get("observation"), Mapping) else {},
            )
            for key in ("thesis_cn", "inferences_cn", "counterevidence_cn", "confirmation_conditions", "invalidation_conditions"):
                row[key] = sections[key]
        projected_rows.append(row)
    projected["rows"] = projected_rows
    if target:
        _assign_catalyst_focus_ranks(projected_rows, target)
        for row in projected_rows:
            result = row.get("catalyst_result")
            if isinstance(result, Mapping):
                current = dict(row.get("current_research")) if isinstance(row.get("current_research"), Mapping) else {}
                current["catalyst_advice"] = result.get("catalyst_advice")
                row["current_research"] = current
    # The cached source receipt's ``substantive_body`` counter is a collection
    # time metric.  Recompute the current semantic counts from the exact event
    # projection used for advice and focus ranking, while retaining the raw
    # source counts below for audit.
    projected_events = [
        event
        for row in projected_rows
        for event in (
            row.get("catalyst_result", {}).get("events", [])
            if isinstance(row.get("catalyst_result"), Mapping)
            and isinstance(row.get("catalyst_result", {}).get("events"), list)
            else []
        )
        if isinstance(event, Mapping)
    ]
    semantic_counts = {
        "ELIGIBLE": sum(1 for event in projected_events if event.get("semantic_class") == "ELIGIBLE"),
        "UNCONFIRMED": sum(1 for event in projected_events if event.get("semantic_class") == "UNCONFIRMED"),
        "NON_SUBSTANTIVE": sum(1 for event in projected_events if event.get("semantic_class") == "NON_SUBSTANTIVE"),
    }
    if isinstance(projected.get("catalyst_coverage"), Mapping):
        coverage = dict(projected["catalyst_coverage"])
        coverage.update({
            "event_count": len(projected_events),
            "historical_event_count": sum(1 for event in projected_events if event.get("as_of_bucket") == "historical"),
            "current_event_count": sum(1 for event in projected_events if event.get("as_of_bucket") == "current"),
            "focus_event_count": sum(
                1 for event in projected_events
                if target and event_is_focus_eligible(event, target_trade_date=target)
            ),
            "eligible_event_count": semantic_counts["ELIGIBLE"],
            "unconfirmed_event_count": semantic_counts["UNCONFIRMED"],
            "non_substantive_event_count": semantic_counts["NON_SUBSTANTIVE"],
            "semantic_class_counts": semantic_counts,
            "classification_basis": "CURRENT_EVENT_PROJECTION",
            "raw_source_counts_retained_for_audit": True,
        })
        projected["catalyst_coverage"] = coverage
    return projected
