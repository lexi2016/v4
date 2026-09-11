"""Background orchestration for the independent manager research product."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
import re
import threading
import time
from typing import Any, Callable, Mapping

from infrastructure.trading_safety import assert_safe_tree

from .contracts import (
    FOUR_FLAGS,
    JOB_SCHEMA_VERSION,
    MANAGER_RESEARCH_ACTION_VALUES,
    PRODUCT_SCHEMA_VERSION,
    ContractError,
    cutoff_at as contract_cutoff_at,
    normalise_observation_input,
    sha256_json,
    strict_trade_date,
)
from .event_source import (
    EVENT_FOCUS_WINDOW_DAYS,
    EVENT_SCHEMA_VERSION,
    _EVENT_BODY_STRONG_TOKENS,
    _classify_hkex_business_clause,
    _is_routine_hkex_event_title,
    build_catalyst_advice,
    event_is_focus_eligible,
)
from .ports import ObservationReader, ResearchSourceProvider
from .reader_source import read_public_news_batch
from .recommendation import (
    RECOMMENDATION_SCHEMA_VERSION,
    assign_investment_priorities,
    build_research_recommendation,
    derive_investment_advice,
    extract_financial_evidence,
    recommendation_summary,
)
from .store import ManagerResearchStore, StoreConflict, StoreError


SAFE_DECISION = "暂不买入，等待验证"
SAFE_CANNOT_DECISION = "暂不买入，补充研究不可确认"
# The public web contract remains v2 for the frozen frontend.  This revision
# is the backend cache boundary for R3: newly written products carry it, while
# legacy products that show either a revenue-component headline or an annual
# report are invalidated and must be re-collected.
CONTENT_CONTRACT_VERSION = "v2.pypdf-6.10.0-structured-cn"
CONTENT_CONTRACT_REVISION = "r3.aggregate-report-bound.latest-report-fail-closed"
_PDF_PAGE_LOCATOR_RE = re.compile(r"^PDF page [1-9][0-9]*$")
_STRUCTURED_FACT_KINDS = frozenset({"financial", "dividend", "egm_resolution", "business"})
_PRIMARY_FINANCIAL_TOKENS = (
    "revenue",
    "sales",
    "gross profit",
    "profit for",
    "loss for",
    "net profit",
    "net loss",
    "operating profit",
    "operating loss",
    "operating income",
    "cash generated",
    "cash used",
    "net cash",
)
_REVENUE_COMPONENT_TOKENS = (
    "other source",
    "rental income",
    "revenue recognised",
    "revenue recognized",
    "timing of revenue",
    "sale of",
    "rendering of",
    "service revenue",
    "segment",
)
_STATUTORY_RESULT_TOKENS = (
    "loss for",
    "profit for",
    "profit (loss) for",
    "profit(loss) for",
    "income for the period",
    "income for the year",
    "net profit",
    "net loss",
    "profit/loss",
)
_STATUTORY_EXCLUDED_LABEL_RE = re.compile(
    r"\b(?:other\s+)?comprehensive\s+income\b|\b(?:income|profit|loss)\s+before\s+tax\b|"
    r"\b(?:operating|gross)\s+(?:profit|loss|income)\b|\bshare\s+of\s+(?:the\s+)?profit\b",
    re.IGNORECASE,
)
_STATUTORY_RESULT_RE = re.compile(
    r"^(?:net\s+)?(?:profit|loss)(?:\s*/?\s*\(?\s*(?:profit|loss)\s*\)?)?\s+"
    r"for\s+the\s+(?:period|year)$|"
    r"^income\s+for\s+the\s+(?:period|year)$|"
    r"^(?:net\s+)?(?:profit|loss)(?:\s*/?\s*\(?\s*(?:profit|loss)\s*\)?)?$",
    re.IGNORECASE,
)
_STATUTORY_ATTRIBUTABLE_RE = re.compile(
    r"^(?:net\s+)?(?:profit|loss)(?:\s*/?\s*\(?\s*(?:profit|loss)\s*\)?)?\s+"
    r"attributable\s+to\s+(?:the\s+)?(?:owners?|equity\s+holders?|shareholders?)"
    r"(?:\s+of\s+(?:the\s+)?(?:company|group|parent|listed\s+company))?$",
    re.IGNORECASE,
)
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


def _current_product(product: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Reject products made by the pre-R1 excerpt parser.

    The date/input path remains the same, but a content parser change is an
    explicit cache boundary.  Returning ``None`` here makes the next GET
    expose the old job as retryable and prevents a stale English fragment from
    reaching the UI.
    """

    if not isinstance(product, Mapping) or product.get("content_contract_version") != CONTENT_CONTRACT_VERSION:
        return None
    if product.get("content_contract_revision") == CONTENT_CONTRACT_REVISION:
        return dict(product)
    if product.get("content_contract_revision") in {None, ""} and not _legacy_product_requires_r3_refresh(product):
        # Preserve unaffected R2 products so R3 can refresh only the dates
        # whose actual source selection/content is affected.  Products with
        # the two discovered generic failure shapes are rejected below.
        return dict(product)
    return None


def _legacy_product_requires_r3_refresh(product: Mapping[str, Any]) -> bool:
    rows = product.get("rows")
    if not isinstance(rows, list):
        return True
    for row in rows:
        if not isinstance(row, Mapping) or row.get("status") != "READY":
            continue
        source = row.get("source")
        title = str(source.get("document_title", "")) if isinstance(source, Mapping) else ""
        # An old annual/final report may have hidden a newer effective interim
        # report.  Re-run it through the report-period binding before showing
        # it again, without hardcoding an issuer or date.
        if re.search(r"\b(?:annual|final)\s+results\b", title, flags=re.IGNORECASE):
            return True
        facts = row.get("facts")
        if not isinstance(facts, list):
            continue
        financial = [fact for fact in facts if isinstance(fact, Mapping) and fact.get("fact_kind") == "financial"]
        revenue_rows = [
            fact
            for fact in financial
            if _label_matches(_fact_value(fact, "label").lower(), "revenue")
        ]
        if revenue_rows and not any(_is_aggregate_revenue_label(_fact_value(fact, "label")) for fact in revenue_rows):
            return True
    return False


def _usable_fact(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    statement = value.get("statement_cn")
    locator = value.get("locator")
    excerpt = value.get("source_excerpt")
    page = value.get("page")
    fields = value.get("fields")
    return (
        isinstance(statement, str)
        and bool(statement.strip())
        and bool(re.search(r"[\u3400-\u9fff]", statement))
        and isinstance(locator, str)
        and _PDF_PAGE_LOCATOR_RE.fullmatch(locator.strip()) is not None
        and isinstance(page, int)
        and not isinstance(page, bool)
        and page >= 1
        and isinstance(excerpt, str)
        and len(excerpt.strip()) >= 8
        and isinstance(fields, Mapping)
        and bool(fields)
        and isinstance(value.get("fact_kind"), str)
        and value.get("fact_kind") in _STRUCTURED_FACT_KINDS
    )


def _has_researchable_fact_set(facts: list[Mapping[str, Any]]) -> bool:
    """Require a meaningful company fact before exposing source READY.

    Balance-sheet fragments such as an isolated expense, liability, or asset
    line can be perfectly parseable while still being insufficient for a
    company research card. Dividend/EGM/business facts have their own
    structured meaning; a financial set needs at least one primary operating,
    profit/loss, or cash-flow metric.
    """

    revenue_rows = [
        fact
        for fact in facts
        if fact.get("fact_kind") == "financial"
        and _label_matches(_fact_value(fact, "label").lower(), "revenue")
    ]
    # A revenue component with no parsed total/aggregate row cannot support a
    # company-level revenue claim.  Keep the row's source receipt visible, but
    # fail closed rather than promoting a component (for example rental
    # income) into the headline.  Other financial sets with no revenue row can
    # still be useful when they contain a primary profit/loss or cash metric.
    if revenue_rows and not any(_is_aggregate_revenue_label(_fact_value(fact, "label")) for fact in revenue_rows):
        return False
    for fact in facts:
        kind = fact.get("fact_kind")
        if kind in {"dividend", "egm_resolution", "business"}:
            return True
        if kind == "financial":
            label = _fact_value(fact, "label").lower()
            if any(token in label for token in _PRIMARY_FINANCIAL_TOKENS):
                return True
    return False


def _fact_value(fact: Mapping[str, Any], field: str, default: str = "") -> str:
    fields = fact.get("fields")
    if isinstance(fields, Mapping):
        value = fields.get(field)
        if isinstance(value, str):
            return value.strip()
    return default


_SERVICE_CURRENCY_CN = {
    "RMB": "人民币",
    "CNY": "人民币",
    "HKD": "港元",
    "USD": "美元",
    "S$": "新加坡元",
}
_SERVICE_UNIT_CN = {
    "thousands": "千元",
    "thousand": "千元",
    "millions": "百万元",
    "million": "百万元",
    "percentages": "%",
    "yuan": "元",
}


def _fact_label_cn(fact: Mapping[str, Any]) -> str:
    fields = fact.get("fields")
    if isinstance(fields, Mapping):
        label_cn = fields.get("label_cn")
        if isinstance(label_cn, str) and label_cn.strip():
            return label_cn.strip()
        label = fields.get("label")
        if isinstance(label, str):
            translations = {
                "revenue": "收入",
                "total revenues": "总收入",
                "gross profit": "毛利",
                "loss for the period": "期内亏损",
                "profit for the period": "期内利润",
                "profit (loss) for the period": "期内利润/（亏损）",
                "profit(loss) for the period": "期内利润/（亏损）",
                "income for the period": "期内收益",
                "loss for the year": "年度亏损",
                "profit for the year": "年度利润",
                "profit (loss) for the year": "年度利润/（亏损）",
                "profit(loss) for the year": "年度利润/（亏损）",
                "income for the year": "年度收益",
                "operating profit": "经营利润",
                "operating loss": "经营亏损",
                "expenses": "费用",
                "liabilities": "负债",
                "cash and cash equivalents": "现金及现金等价物",
                "cash and bank balances": "现金及银行结余",
                "adjusted net loss for the year (a non-ifrs measure)": "经调整年度亏损（非国际财务报告准则）",
                "adjusted net loss (non-ifrs measure)": "经调整期内亏损（非国际财务报告准则）",
            }
            exact = translations.get(label.strip().lower())
            if exact:
                return exact
    statement = fact.get("statement_cn")
    if isinstance(statement, str) and statement.startswith("财务表："):
        return statement.removeprefix("财务表：").split("；", 1)[0].strip()
    return "财务项目"


def _is_adjusted_fact(fact: Mapping[str, Any]) -> bool:
    label = _fact_value(fact, "label").lower()
    statement = str(fact.get("statement_cn", "")).lower()
    return "adjusted" in label or "non-ifrs" in label or "non-ifrs" in statement or "经调整" in statement


def _financial_rows(facts: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    rows = [fact for fact in facts if fact.get("fact_kind") == "financial"]
    # Keep net/adjusted result rows near the core metrics for deterministic
    # fallback rendering, while statutory selection below remains role-aware.
    priority_tokens = ("revenue", "gross profit", "net profit", "net loss", "profit/loss", "operating", "cash")
    return sorted(
        rows,
        key=lambda fact: (
            0 if (
                any(token in _fact_value(fact, "label").lower() for token in priority_tokens)
                or _is_statutory_result_label(_fact_value(fact, "label"))
            ) else 1,
            int(fact.get("page", 0)),
            _fact_value(fact, "label").lower(),
        ),
    )


def _raw_decimal(raw: Any) -> Decimal | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().replace(",", "")
    if value in {"", "—", "–", "-", "N/A", "n/a"}:
        return None
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    try:
        parsed = Decimal(value.rstrip("%"))
    except (InvalidOperation, ValueError):
        return None
    return -parsed if negative else parsed


def _financial_value_map(fact: Mapping[str, Any]) -> dict[str, str]:
    fields = fact.get("fields")
    values = fields.get("values") if isinstance(fields, Mapping) else None
    if not isinstance(values, list):
        return {}
    result: dict[str, str] = {}
    for item in values:
        if isinstance(item, Mapping) and isinstance(item.get("column"), str) and isinstance(item.get("raw"), str):
            result[item["column"]] = item["raw"]
    return result


def _first_financial(facts: list[Mapping[str, Any]], *tokens: str) -> Mapping[str, Any] | None:
    for fact in _financial_rows(facts):
        label = _fact_value(fact, "label").lower()
        if any(_label_matches(label, token) for token in tokens):
            return fact
    return None


def _first_financial_with_adjustment(
    facts: list[Mapping[str, Any]],
    *tokens: str,
    adjusted: bool | None = None,
) -> Mapping[str, Any] | None:
    candidates: list[Mapping[str, Any]] = []
    for fact in _financial_rows(facts):
        if adjusted is not None and _is_adjusted_fact(fact) != adjusted:
            continue
        label = _fact_value(fact, "label").lower()
        if any(_label_matches(label, token) for token in tokens):
            candidates.append(fact)
    if not candidates:
        return None
    if "revenue" not in tokens:
        return candidates[0]
    # Only an aggregate/total revenue row is suitable for a company headline.
    # Components remain in the folded fact evidence and are never allowed to
    # replace a missing total.
    aggregate = [fact for fact in candidates if _is_aggregate_revenue_label(_fact_value(fact, "label"))]
    if not aggregate:
        return None
    return aggregate[0]


def _is_aggregate_revenue_label(label: str) -> bool:
    """Return whether an official label represents a total revenue measure.

    HKEX financial tables commonly place a total ``Revenue`` row beside
    source/segment rows.  Qualifiers such as ``other source``, recognised-at-
    a-point-in-time, rental and product/service rows identify components and
    must not be promoted to the company-level metric.
    """

    clean = re.sub(r"\s+", " ", str(label or "").strip().lower())
    if not clean or any(token in clean for token in _REVENUE_COMPONENT_TOKENS):
        return False
    if re.search(r"\b(?:total|net|operating)?\s*revenues?\s*$", clean):
        return True
    # IFRS 15 wording is an aggregate contract-revenue measure even when the
    # table appends the scope or business description after the standard label.
    if re.match(r"^(?:total\s+)?revenue\s+from\s+contracts\s+with\s+customers\b", clean):
        return True
    return False


def _label_matches(label: str, token: str) -> bool:
    if token == "revenue":
        if "cost of revenue" in label or "cost of revenues" in label:
            return False
        # ``revenue`` is also used as a qualifier in rows such as interest
        # income arising from revenue contracts.  A revenue metric must be a
        # leading metric phrase so those ancillary rows cannot replace total
        # revenue in the card summary.
        return bool(re.match(r"^(?:(?:total|operating)\s+)?revenues?\b", label))
    if token in _STATUTORY_RESULT_TOKENS:
        return _is_statutory_result_label(label)
    return token in label


def _is_statutory_result_label(label: str) -> bool:
    """Match the legal profit/loss result row without accepting components.

    HKEX statements place Other comprehensive income beside the legal period
    result. A substring check for income for the period therefore selects the
    component when it sorts first. Keep the selector role-aware: only an exact
    period/year result, a net profit/loss result, or an explicitly attributable
    owner/equity-holder result is statutory here.
    """

    clean = re.sub(r"\s+", " ", str(label or "").strip().lower())
    clean = clean.replace("／", "/").replace("−", "-")
    if (
        not clean
        or _STATUTORY_EXCLUDED_LABEL_RE.search(clean)
        or re.search(r"\b(?:after\s+deducting|excluding|adjusted|non[- ]ifrs|non[- ]recurring)\b", clean)
    ):
        return False
    if _STATUTORY_RESULT_RE.fullmatch(clean):
        return True
    return _STATUTORY_ATTRIBUTABLE_RE.fullmatch(clean) is not None


def _financial_values(fact: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    fields = fact.get("fields")
    if not isinstance(fields, Mapping):
        return [], {}
    raw_columns = fields.get("columns")
    raw_values = fields.get("values")
    columns = [str(item) for item in raw_columns if isinstance(item, str)] if isinstance(raw_columns, list) else []
    values: dict[str, str] = {}
    if isinstance(raw_values, list):
        for item in raw_values:
            if isinstance(item, Mapping) and isinstance(item.get("column"), str) and isinstance(item.get("raw"), str):
                values[item["column"]] = item["raw"]
    return columns, values


def _comparison_columns(fact: Mapping[str, Any]) -> tuple[str, str | None]:
    columns, values = _financial_values(fact)
    years = sorted({column for column in columns if re.fullmatch(r"\d{4}", column)}, key=int, reverse=True)
    if years:
        return years[0], years[1] if len(years) > 1 else None
    usable = [column for column in columns if column not in {"Change", "Change (%)"} and column in values]
    if usable:
        return usable[0], usable[1] if len(usable) > 1 else None
    return "", None


def _amount_text(fact: Mapping[str, Any], raw: str) -> str:
    fields = fact.get("fields")
    if not isinstance(fields, Mapping):
        return raw
    currency = _SERVICE_CURRENCY_CN.get(str(fields.get("currency", "")).upper(), str(fields.get("currency", "")))
    unit = _SERVICE_UNIT_CN.get(str(fields.get("unit", "")).lower(), str(fields.get("unit", "")))
    suffix = f"{currency}{unit}" if currency and unit else currency or unit
    exact = f"{raw}{suffix}" if suffix else raw
    number = _raw_decimal(raw)
    raw_unit = str(fields.get("unit", "")).lower()
    if number is None or raw_unit not in {"thousands", "thousand", "millions", "million"} or not currency:
        return exact
    base = number * (Decimal(1000) if raw_unit in {"thousands", "thousand"} else Decimal(1000000))
    approximate_currency = "元" if currency == "人民币" else currency
    absolute = abs(base)
    if absolute >= Decimal(100000000):
        approximate = f"约{absolute / Decimal(100000000):.2f}亿{approximate_currency}"
    elif absolute >= Decimal(10000):
        approximate = f"约{absolute / Decimal(10000):.2f}万{approximate_currency}"
    else:
        approximate = f"约{absolute:.0f}{approximate_currency}"
    if base < 0:
        approximate = approximate.replace("约", "约-", 1)
    return f"{exact}（{approximate}）"


def _period_short(fact: Mapping[str, Any]) -> str:
    period = _fact_value(fact, "period_label_cn")
    columns, _ = _financial_values(fact)
    years = [int(item) for item in columns if re.fullmatch(r"\d{4}", item)]
    year = max(years) if years else None
    if not year:
        period_year = re.search(r"\b(19\d{2}|20\d{2})\b", period)
        year = int(period_year.group(1)) if period_year else None
    if "截至年度" in period:
        return f"{year}年度" if year else "年度"
    if "截至六个月" in period:
        return f"{year}年上半年" if year else "上半年"
    if "截至三个月" in period:
        return f"{year}年截至三个月" if year else "截至三个月"
    return "公告报告期"


def _change_text(fact: Mapping[str, Any], current: str, previous: str | None, *, compute_if_missing: bool = True) -> str:
    _, values = _financial_values(fact)
    raw_change = values.get("Change (%)") or values.get("Change")
    if raw_change:
        parsed = _raw_decimal(raw_change)
        if parsed is not None:
            direction = "增加" if parsed >= 0 else "减少"
            return f"同比{direction}{abs(parsed):g}%"
        return f"公告披露同比{raw_change if raw_change.rstrip().endswith('%') else raw_change + '%'}"
    if not compute_if_missing:
        return "公告未直接披露同比"
    current_number = _raw_decimal(current)
    previous_number = _raw_decimal(previous) if previous else None
    if current_number is not None and previous_number not in {None, Decimal(0)} and previous is not None:
        # A computed comparison is labelled as approximate and retains the
        # source values in the sentence; negative-base profit rows are handled
        # by the caller as a widening/narrowing statement.
        change = (current_number - previous_number) / abs(previous_number) * Decimal(100)
        return f"同比约{change:+.1f}%"
    return "公告未直接披露同比"


def _financial_summary_sentence(fact: Mapping[str, Any], *, role: str = "metric") -> str:
    label = _fact_label_cn(fact)
    current_column, previous_column = _comparison_columns(fact)
    _, values = _financial_values(fact)
    current = values.get(current_column, "")
    previous = values.get(previous_column, "") if previous_column else ""
    if not current:
        return f"{label}原表当前列无值"
    current_text = _amount_text(fact, current)
    if role == "statutory" or role == "adjusted":
        current_number = _raw_decimal(current)
        previous_number = _raw_decimal(previous) if previous else None
        if current_number is not None and current_number < 0:
            if previous_number is not None and abs(current_number) < abs(previous_number):
                trend = "，亏损额较上年同期收窄"
            elif previous_number is not None and abs(current_number) > abs(previous_number):
                trend = "，亏损额较上年同期扩大"
            else:
                trend = ""
            prefix = "经调整口径亏损" if role == "adjusted" else "法定口径亏损"
            suffix = "（非IFRS）" if role == "adjusted" else ""
            if role == "adjusted" and "（约" in current_text:
                exact_text, approximate_text = current_text.split("（约", 1)
                return f"{prefix}{exact_text}{suffix}（约{approximate_text}{trend}"
            return f"{prefix}{current_text}{suffix}{trend}"
        prefix = "经调整口径利润" if role == "adjusted" else "法定口径利润"
        suffix = "（非IFRS）" if role == "adjusted" else ""
        if role == "adjusted" and "（约" in current_text:
            exact_text, approximate_text = current_text.split("（约", 1)
            return f"{prefix}{exact_text}{suffix}（约{approximate_text}"
        return f"{prefix}{current_text}{suffix}"
    change = _change_text(fact, current, previous or None, compute_if_missing=role != "fallback")
    return f"{label}{current_text}，{change}"


def _build_research_sections(
    issuer: str,
    code: str,
    facts: list[Mapping[str, Any]],
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive readable Chinese research from the structured source fields.

    Every sentence containing a company claim is tied to a parsed fact.  The
    remaining sentences explicitly describe what the source does not prove,
    so a headline or one generic disclaimer cannot become a thesis.
    """

    kinds = {str(fact.get("fact_kind")) for fact in facts}
    name = issuer.strip() or str(observation.get("name") or code)
    display = f"{name}（{code}）"
    if "financial" in kinds:
        financial = _financial_rows(facts)
        selected: list[Mapping[str, Any]] = []
        for candidate in (
            _first_financial_with_adjustment(facts, "revenue", adjusted=False),
            _first_financial_with_adjustment(facts, "gross profit", adjusted=False),
            _first_financial_with_adjustment(facts, *_STATUTORY_RESULT_TOKENS, adjusted=False),
            _first_financial_with_adjustment(facts, "adjusted net loss", "adjusted loss", "adjusted profit", adjusted=True),
        ):
            if candidate is not None and candidate not in selected:
                selected.append(candidate)
        selected.extend(fact for fact in financial if fact not in selected and len(selected) < 4)
        selected = selected[:4]
        revenue = _first_financial_with_adjustment(facts, "revenue", adjusted=False)
        gross = _first_financial_with_adjustment(facts, "gross profit", adjusted=False)
        statutory = _first_financial_with_adjustment(
            facts,
            *_STATUTORY_RESULT_TOKENS,
            adjusted=False,
        )
        adjusted = _first_financial_with_adjustment(
            facts,
            "adjusted net loss",
            "adjusted loss",
            "adjusted profit",
            adjusted=True,
        )
        summary_parts: list[str] = []
        if revenue is not None:
            summary_parts.append(_financial_summary_sentence(revenue))
        if gross is not None:
            summary_parts.append(_financial_summary_sentence(gross))
        if statutory is not None:
            summary_parts.append(_financial_summary_sentence(statutory, role="statutory"))
        if adjusted is not None:
            summary_parts.append(_financial_summary_sentence(adjusted, role="adjusted"))
        summary_labels = {_fact_label_cn(fact) for fact in (revenue, gross, statutory, adjusted) if fact is not None}
        # Once the principal operating/profit rows are present, keep
        # ancillary rows such as interest income out of the headline.  A
        # fallback row is useful only when a primary metric was genuinely not
        # found; the folded fact list still retains the complete bounded set.
        has_core_summary = revenue is not None and gross is not None and (statutory is not None or adjusted is not None)
        if not has_core_summary:
            for fact in selected:
                if len(summary_parts) >= 4:
                    break
                label = _fact_label_cn(fact)
                if fact not in (revenue, gross, statutory, adjusted) and label not in summary_labels:
                    summary_parts.append(_financial_summary_sentence(fact, role="fallback"))
                    summary_labels.add(label)
        period = _period_short(selected[0]) if selected else "公告报告期"
        if statutory is not None:
            _, stat_values = _financial_values(statutory)
            stat_column, _ = _comparison_columns(statutory)
            stat_number = _raw_decimal(stat_values.get(stat_column, ""))
            if stat_number is not None and stat_number < 0:
                meaning = "法定口径仍为亏损，收入或毛利改善尚未证明已经盈利"
            elif stat_number is not None:
                meaning = "法定口径已列示利润，仍需核对现金流与后续期间持续性"
            else:
                meaning = "法定利润/亏损数值无法解析，不能据此扩大结论"
        else:
            meaning = "公告未形成法定利润/亏损行，不能据收入或毛利直接推断盈利"
        if adjusted is not None:
            meaning += "；经调整口径仅作补充，不能替代法定口径"
        thesis = f"{display}：{period}{'；'.join(summary_parts)}。{meaning}。"
        inferences: list[str] = []
        if revenue is not None:
            values = _financial_value_map(revenue)
            change = values.get("Change (%)") or values.get("Change")
            current_column, _ = _comparison_columns(revenue)
            current = values.get(current_column) or next(iter(values.values()), "")
            if change:
                parsed_change = _raw_decimal(change)
                direction = "增加" if parsed_change is not None and parsed_change >= 0 else "减少" if parsed_change is not None else "未知方向"
                change_text = change if change.rstrip().endswith("%") else f"{change}%"
                inferences.append(f"收入行的公告披露同比原始值为{change_text}，本研究仅据该值记录为{direction}信号，当期数值为{current}。")
            else:
                current_column, previous_column = _comparison_columns(revenue)
                previous = values.get(previous_column, "") if previous_column else ""
                derived = _change_text(revenue, current, previous or None)
                if derived.startswith("同比约"):
                    inferences.append(
                        f"公告未直接披露同比，按同口径{current_column}/{previous_column}数值计算{derived}；该比较不能预测未来增长。"
                    )
                else:
                    inferences.append(f"收入行当期数值为{current}；公告未直接披露同比，不能预测未来增长。")
        if gross is not None and statutory is not None:
            gross_values = _financial_value_map(gross)
            loss_values = _financial_value_map(statutory)
            first_gross = next(iter(gross_values.values()), "")
            first_loss = next(iter(loss_values.values()), "")
            loss_negative = _raw_decimal(first_loss) is not None and (_raw_decimal(first_loss) or Decimal(0)) < 0
            inferences.append(
                f"同一财务表同时列出毛利{first_gross}与法定口径{'亏损' if loss_negative else '利润'}{first_loss}；收入/毛利改善不能直接推导为已盈利。"
            )
        elif statutory is None:
            inferences.append("当前公告未形成可复核的法定利润/亏损行；其他财务项目不能替代该口径。")
        if adjusted is not None and statutory is not None:
            adjusted_column, _ = _comparison_columns(adjusted)
            stat_column, _ = _comparison_columns(statutory)
            adjusted_values = _financial_value_map(adjusted)
            statutory_values = _financial_value_map(statutory)
            inferences.append(
                f"法定口径与经调整口径分别列为{statutory_values.get(stat_column, '')}和{adjusted_values.get(adjusted_column, '')}；经调整项目不替代法定结果。"
            )
        inferences.append("这些数字属于公告报告期，不能替代目标日盘面承接、订单、现金流或后续期间验证。")
        counter = [f"当前证据是单份公告的{period}数据，未证明后续期间能够维持同一口径。"]
        if statutory is None:
            counter.append("公告没有法定利润/亏损行，收入、毛利或其他财务项目不能单独支持盈利结论。")
        else:
            counter.append("若法定利润/亏损、费用或经营现金流未改善，收入增长也不能单独支持积极结论。")
        if adjusted is not None:
            counter.append("经调整口径与法定结果存在口径差异，调整项无法由当前摘要证明可持续。")
        confirm = [
            "复核下一期同币种、同单位、同列顺序的收入、毛利与利润/亏损行，并核对公告页码。",
            "补查经营现金流、应收账款及订单/客户兑现证据，再观察阶段价格承接是否持续。",
        ]
        invalid = [
            "若下一期收入或毛利按同口径转弱，或公告披露同比与当前方向相反，则撤回经营改善判断。",
            "若法定亏损扩大、经营现金流恶化或关键数字无法由官方原文复核，保持不可确认。",
        ]
        return {
            "thesis_cn": thesis,
            "inferences_cn": inferences[:4],
            "counterevidence_cn": counter,
            "confirmation_conditions": confirm,
            "invalidation_conditions": invalid,
        }
    if "dividend" in kinds:
        dividend = [fact for fact in facts if fact.get("fact_kind") == "dividend"]
        detail = "；".join(str(fact["statement_cn"]).rstrip("。") for fact in dividend[:4])
        thesis = f"{display}：官方公告正文确认股息与登记/派付安排：{detail}。"
        amount = next((_fact_value(fact, "value_raw") for fact in dividend if _fact_value(fact, "field") == "dividend_declared"), "")
        inferences = [
            f"公告股息字段的原始值为{amount or '未提供'}；除息、登记和派付日期按原文分别保留，不能改写为目标日收益。",
            "股息安排是公司分配事项，未提供经营利润、现金流或除息后价格承接的完整证据。",
        ]
        return {
            "thesis_cn": thesis,
            "inferences_cn": inferences,
            "counterevidence_cn": [
                "股息金额和日期不等同于经营改善，也不能证明除息后价格不会回落。",
                "当前公告未单独证明派息资金来源、持续性或下一期盈利兑现。",
            ],
            "confirmation_conditions": [
                "核对同一公告的报告期、派息资格和实际派付状态，并复核后续财务现金流。",
                "观察除息后成交与阶段承接，再与下一期利润和现金流口径交叉验证。",
            ],
            "invalidation_conditions": [
                "若登记/派付安排变更、取消或原文日期无法复核，则撤回该股息事实。",
                "若下一期盈利或现金流恶化、或除息后承接明显失效，保持暂不买入。",
            ],
        }
    if "egm_resolution" in kinds:
        resolutions = [fact for fact in facts if fact.get("fact_kind") == "egm_resolution"]
        detail = "；".join(str(fact["statement_cn"]).rstrip("。") for fact in resolutions)
        thesis = f"{display}：官方股东会文件可读到以下待审议事项：{detail}。"
        return {
            "thesis_cn": thesis,
            "inferences_cn": [
                "文件记录的是股东会决议议题及其类别，说明治理或资金安排进入审议流程，不代表已经通过或执行。",
                "注册资本/章程变更与现金管理额度议题本身没有提供收入、利润或现金流改善数值。",
            ],
            "counterevidence_cn": [
                "决议需要结合股东会结果、登记变更和后续公告核验，议题标题不能算已完成事项。",
                "提高现金管理额度不等同于主营经营改善，资金运用与风险边界仍未知。",
            ],
            "confirmation_conditions": [
                "复核股东会表决结果、注册资本/章程登记及后续执行公告，并保留对应页码。",
                "核对现金管理实际余额、期限、收益及主营现金流，再观察同日阶段承接。",
            ],
            "invalidation_conditions": [
                "若议案未获通过、登记未完成或后续公告否定原议题，则撤回相应推断。",
                "若资金安排出现违约、损失或无法复核执行状态，保持不可确认。",
            ],
        }
    if "business" in kinds:
        business = [fact for fact in facts if fact.get("fact_kind") == "business"]
        detail = "；".join(str(fact["statement_cn"]).rstrip("。") for fact in business[:3])
        return {
            "thesis_cn": f"{display}：官方经营段落提供以下可读事实：{detail}。",
            "inferences_cn": [
                "经营段落中的收入、规模或产品字段是公司自述指标，需与财务表和后续兑现核对。",
                "阶段观察只能说明目标时点的盘面变化，不能把公告段落直接转成买入结论。",
            ],
            "counterevidence_cn": [
                "经营描述未必包含利润率、现金流、订单质量和客户集中度，仍存在基本面反证。",
                "单份公告和单个产品/规模字段不能证明持续增长或目标日后的价格承接。",
            ],
            "confirmation_conditions": [
                "将经营字段与下一期同口径收入、利润、现金流和客户/订单披露交叉核对。",
                "继续观察同一阶段观察口径下的承接与波动，并复核原文页码和发布时间。",
            ],
            "invalidation_conditions": [
                "若后续财务数据无法印证经营段落，或客户/产品指标回落，则撤回改善推断。",
                "若原文正文不可复核、发布时间越过截止点或来源身份不一致，降级为不可确认。",
            ],
        }
    return {
        "thesis_cn": "官方来源虽已返回，但没有形成可用结构化正文事实，不能写成公司深研。",
        "inferences_cn": [],
        "counterevidence_cn": [],
        "confirmation_conditions": [],
        "invalidation_conditions": [],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_v2_recommendation(value: Any) -> bool:
    if not isinstance(value, Mapping) or value.get("schema_version") != RECOMMENDATION_SCHEMA_VERSION:
        return False
    return (
        isinstance(value.get("investment_advice"), Mapping)
        and isinstance(value.get("execution_gate"), Mapping)
        and isinstance(value.get("as_of"), Mapping)
        and isinstance(value.get("evidence"), Mapping)
    )


def _row_date_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()[:10].replace("-", "")
    return token if re.fullmatch(r"20\d{6}", token) else None


def _empty_catalyst_row(
    code: str,
    *,
    status: str = "CANNOT_CONFIRM",
    reason: str = "EVENT_SOURCE_NOT_RUN",
) -> dict[str, Any]:
    """Keep event coverage explicit when the independent event lane is absent."""

    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "events": [],
        "historical_events": [],
        "current_events": [],
        "catalyst_advice": {
            "status": "CANNOT_CONFIRM",
            "label": "CANNOT_CONFIRM（催化）",
            "priority_rank": None,
            "priority_reason": "催化来源尚未运行；不把财报或行情字段当作事件证据。",
            "summary": "事件、财务意见和执行门保持分开。",
        },
        "source_coverage": [],
        "source_receipts": [],
        "coverage": {
            "requested_candidates": 1,
            "source_count": 0,
            "historical_event_count": 0,
            "current_event_count": 0,
            "no_match_is_not_complete": True,
            "completeness": "EVENT_SOURCE_NOT_RUN",
        },
        "current_event_as_of": None,
        "financial_counterevidence": [],
        "market_confirmation_gap": ["EVENT_SOURCE_NOT_RUN"],
        "code": code,
    }


def _reader_materials(bundle: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return the bounded reader rows in display order, without classification."""

    if not isinstance(bundle, Mapping):
        return []
    materials: list[dict[str, Any]] = []
    for key in ("materials", "company_news", "background"):
        values = bundle.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, Mapping):
                materials.append(dict(item))
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in materials:
        key = str(item.get("id") or item.get("source_url") or item.get("title") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(item)
    result.sort(key=lambda item: (str(item.get("published_at") or ""), str(item.get("id") or "")), reverse=True)
    return result


def _attach_reader_batch(
    event_batch: Mapping[str, Any],
    reader_batch: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Attach source material to each exact row while keeping event semantics separate."""

    updated = dict(event_batch)
    raw_rows = event_batch.get("rows") if isinstance(event_batch.get("rows"), Mapping) else {}
    reader_rows = reader_batch.get("rows") if isinstance(reader_batch.get("rows"), Mapping) else {}
    rows: dict[str, dict[str, Any]] = {}
    for observation in observations:
        code = str(observation.get("code") or "")
        base = raw_rows.get(code) if isinstance(raw_rows, Mapping) else None
        row = dict(base) if isinstance(base, Mapping) else _empty_catalyst_row(code, reason="EVENT_ROW_MISSING")
        bundle = reader_rows.get(code) if isinstance(reader_rows, Mapping) else None
        bundle_copy = dict(bundle) if isinstance(bundle, Mapping) else {
            "schema": "v4.manager_research.material_reader.v1",
            "status": "CANNOT_CONFIRM",
            "code": code,
            "name": observation.get("name"),
            "source_gaps": ["PUBLIC_NEWS_ROW_MISSING"],
            "materials": [],
            "company_news": [],
            "background": [],
        }
        display_materials = _reader_materials(bundle_copy)
        row["reader_bundle"] = bundle_copy
        row["reader_materials"] = display_materials
        row["reader_status"] = bundle_copy.get("status", "CANNOT_CONFIRM")
        row["reader_source_gaps"] = list(bundle_copy.get("source_gaps") or []) if isinstance(bundle_copy.get("source_gaps"), list) else []
        rows[code] = row
    updated["rows"] = rows
    source_count = reader_batch.get("source_counts")
    if isinstance(source_count, Mapping):
        updated["reader_source_counts"] = [dict(source_count)]
    else:
        updated["reader_source_counts"] = []
    reader_coverage = dict(reader_batch.get("coverage")) if isinstance(reader_batch.get("coverage"), Mapping) else {
        "status": "CANNOT_CONFIRM",
        "completeness": "BOUNDED_FIXED_CANDIDATE_PUBLIC_NEWS",
    }
    updated["reader_coverage"] = reader_coverage
    updated["reader_current_as_of"] = reader_batch.get("queried_at") or _now()
    coverage = dict(updated.get("coverage")) if isinstance(updated.get("coverage"), Mapping) else {}
    coverage.update({
        "reader_material_count": sum(len(row.get("reader_materials", [])) for row in rows.values()),
        "reader_candidate_count": sum(1 for row in rows.values() if row.get("reader_materials")),
        "reader_status": reader_batch.get("status", "CANNOT_CONFIRM"),
        "reader_coverage": reader_coverage,
        "full_day_coverage": "NOT_VERIFIED",
        "no_material_is_not_no_candidate": True,
    })
    updated["coverage"] = coverage
    reader_material_count = int(coverage.get("reader_material_count") or 0)
    if reader_material_count and str(updated.get("status") or "").upper() == "CANNOT_CONFIRM":
        # The event source may be unavailable while the independent reader is
        # healthy.  Preserve the per-source gap and expose the partial product.
        updated["status"] = "PARTIAL_WITH_ROWS"
        updated["reason"] = "PUBLIC_NEWS_READER_AVAILABLE_EVENT_SOURCE_PARTIAL"
    return updated


def _financial_counterevidence_for_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Re-evaluate persisted facts for the event card without collecting finance.

    Catalyst refreshes must make the financial boundary visible, while the
    existing official facts and source receipt remain the only inputs.  This
    helper intentionally has no provider dependency and reports its zero
    recollection boundary in the returned metadata.
    """

    raw_facts = row.get("facts")
    facts = [item for item in raw_facts if isinstance(item, Mapping)] if isinstance(raw_facts, list) else []
    source = row.get("source") if isinstance(row.get("source"), Mapping) else None
    observation = row.get("observation") if isinstance(row.get("observation"), Mapping) else {}
    evidence = extract_financial_evidence(facts, source)
    existing = row.get("research_recommendation") if isinstance(row.get("research_recommendation"), Mapping) else {}
    existing_advice = existing.get("investment_advice") if isinstance(existing.get("investment_advice"), Mapping) else {}
    timing = str(existing.get("timing_status") or row.get("observation_timing_status") or "CUTOFF_UNCONFIRMED")
    advice = derive_investment_advice(
        evidence,
        observation,
        timing,
        source_status=str(row.get("source_status") or "READY"),
        source_reason=str(row.get("source_reason") or "") or None,
        source_available=source is not None,
    )
    dimensions = evidence.get("dimensions") if isinstance(evidence.get("dimensions"), Mapping) else {}
    counterevidence: list[str] = []
    refs: list[dict[str, Any]] = []
    for name, item in dimensions.items():
        if not isinstance(item, Mapping):
            continue
        state = str(item.get("state") or "")
        if state not in {"NEGATIVE", "MIXED", "CONFLICT"}:
            continue
        dimension = str(name).upper()
        current = item.get("current") or "CANNOT_CONFIRM"
        previous = item.get("previous") or "CANNOT_CONFIRM"
        period = item.get("period") or "CANNOT_CONFIRM_PERIOD"
        if state == "CONFLICT":
            counterevidence.append(f"证据冲突：{dimension} 存在不同值/币种/单位（{period}），不得按正向信号消费。")
        elif state == "MIXED":
            counterevidence.append(f"口径信号转弱：{dimension} 当前={current}、前期={previous}（{period}）。")
        else:
            counterevidence.append(f"已确认财务反证：{dimension} 当前={current}、前期={previous}（{period}）。")
        refs.append(
            {
                "dimension": dimension,
                "state": state,
                "current": item.get("current"),
                "previous": item.get("previous"),
                "period": item.get("period"),
                "currency": item.get("currency"),
                "unit": item.get("unit"),
                "fact_refs": list(item.get("fact_refs") or []),
            }
        )
    missing = [str(value) for value in advice.get("missing_dimensions", []) if isinstance(value, str)]
    market_missing = any(value in {"PRICE_PIT_UNAVAILABLE", "price", "volume", "volume_ratio", "support", "pressure"} for value in missing)
    reevaluation = {
        "status": advice.get("status"),
        "action": advice.get("action"),
        "label_cn": advice.get("label_cn"),
        "evidence_grade": evidence.get("evidence_grade"),
        "reason": advice.get("reason"),
        "missing_dimensions": missing,
        "fact_count": evidence.get("fact_count", len(facts)),
        "source_sha256": source.get("sha256") if source else None,
        "financial_collection_calls": 0,
        "from_cached_facts": True,
        "existing_recommendation_action": existing_advice.get("action") if isinstance(existing_advice, Mapping) else None,
    }
    return {
        "financial_counterevidence": list(dict.fromkeys(counterevidence)),
        "financial_counterevidence_refs": refs,
        "financial_re_evaluation": reevaluation,
        "market_price_volume_unconfirmed": market_missing,
    }


class ManagerResearchJobService:
    """Own job state, deduplication and product assembly.

    A job's identity is ``target_trade_date + input_identity``.  The service
    never accepts a symbol list from the HTTP client; the injected observer is
    the only source of the fixed stage rows.
    """

    def __init__(
        self,
        store: ManagerResearchStore,
        observation_reader: ObservationReader | Callable[[str], Mapping[str, Any]] | None,
        source_provider: ResearchSourceProvider | Callable[..., Mapping[str, Any]] | None,
        *,
        max_workers: int = 4,
        row_timeout_seconds: float = 45.0,
        reader_fetcher: Callable[..., Any] | None = None,
    ) -> None:
        self.store = store
        self.observation_reader = observation_reader
        self.source_provider = source_provider
        self.row_timeout_seconds = max(1.0, float(row_timeout_seconds))
        # Only the production HKEX provider opts into the external public-news
        # reader.  Fixture providers remain fully offline unless a test passes
        # an explicit fetcher, so event tests never make accidental requests.
        self.reader_fetcher = reader_fetcher
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)), thread_name_prefix="manager-research")
        # Shared across jobs: timeouts must not create a fresh set of
        # unbounded stranded provider threads on every retry. Running calls
        # cannot be killed by Python; their own transport timeout still applies.
        self._row_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="manager-research-row")
        self._active: dict[str, Future[Any]] = {}
        self._cancelled: set[str] = set()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=False)
        self._row_executor.shutdown(wait=False, cancel_futures=True)

    def _read_input(self, target_trade_date: str) -> dict[str, Any]:
        target_trade_date = strict_trade_date(target_trade_date)
        if self.observation_reader is None:
            raise ContractError("STAGE_OBSERVATION_READER_UNAVAILABLE")
        if hasattr(self.observation_reader, "read"):
            raw = self.observation_reader.read(target_trade_date)  # type: ignore[union-attr]
        else:
            raw = self.observation_reader(target_trade_date)  # type: ignore[operator]
        if raw is None:
            raise ContractError("STAGE_OBSERVATION_NOT_MATERIALIZED")
        input_data = normalise_observation_input(raw)
        if input_data["target_trade_date"] != target_trade_date:
            raise ContractError("STAGE_OBSERVATION_TARGET_DATE_MISMATCH")
        return input_data

    @staticmethod
    def _job_id(input_data: Mapping[str, Any]) -> str:
        return f"mr-{input_data['target_trade_date']}-{str(input_data['input_identity'])[:32]}"

    @staticmethod
    def _legacy_input_identity(input_data: Mapping[str, Any]) -> str | None:
        """Return the pre-stage-evidence identity for a compatible cache read."""

        identity_payload = input_data.get("identity_payload")
        if not isinstance(identity_payload, Mapping):
            return None
        legacy_payload = {
            key: value
            for key, value in identity_payload.items()
            if key not in {"source_status", "cannot_confirm"}
        }
        try:
            return sha256_json(legacy_payload)
        except ContractError:
            return None

    @staticmethod
    def _exact_cache_is_consistent(input_data: Mapping[str, Any], product: Mapping[str, Any]) -> bool:
        """Re-validate an exact-key cache hit before trusting its content.

        A file that sits at the exact-key path but whose own identity
        metadata, source digest or nested safety semantics no longer match
        the request is corrupt evidence: it must never surface as READY.
        """

        if product.get("target_trade_date") != input_data["target_trade_date"]:
            return False
        if product.get("input_identity") != input_data["input_identity"]:
            return False
        if product.get("stage_id") != input_data["stage_id"]:
            return False
        if product.get("market") != input_data["market"]:
            return False
        if product.get("input_row_count") != input_data["input_row_count"]:
            return False
        if product.get("input_source_sha256") != input_data.get("input_source_sha256"):
            return False
        try:
            assert_safe_tree(
                product,
                label="manager product",
                extra_allowed_action_values=MANAGER_RESEARCH_ACTION_VALUES,
            )
        except ValueError:
            return False
        return True

    def _read_cached_product(self, input_data: Mapping[str, Any]) -> dict[str, Any] | None:
        """Read the exact product, then one validated pre-evidence alias."""

        target_trade_date = str(input_data["target_trade_date"])
        input_identity = str(input_data["input_identity"])
        exact = self.store.read_product(target_trade_date, input_identity)
        if exact is not None:
            if self._exact_cache_is_consistent(input_data, exact):
                return exact
            logging.getLogger(__name__).warning(
                "manager research exact cache identity mismatch at %s/%s; ignoring for re-materialization",
                target_trade_date,
                input_identity,
            )
            return None
        legacy_identity = self._legacy_input_identity(input_data)
        if legacy_identity is None or legacy_identity == input_identity:
            return None
        return self.store.read_compatible_product(
            target_trade_date,
            legacy_input_identity=legacy_identity,
            input_source_sha256=input_data.get("input_source_sha256"),
            input_row_count=int(input_data["input_row_count"]),
            stage_id=str(input_data["stage_id"]),
            market=str(input_data["market"]),
            normalized_rows=input_data.get("rows", []),
        )

    @staticmethod
    def _bind_product_to_input(
        input_data: Mapping[str, Any],
        product: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Bind a validated legacy product to the current stage identity."""

        current_identity = str(input_data["input_identity"])
        if product.get("input_identity") == current_identity:
            return dict(product), False
        bound = dict(product)
        bound.update(
            {
                "target_trade_date": input_data["target_trade_date"],
                "stage_id": input_data["stage_id"],
                "market": input_data["market"],
                "cutoff_at": input_data["cutoff_at"],
                "input_identity": current_identity,
                "input_source_sha256": input_data.get("input_source_sha256"),
                "input_row_count": input_data["input_row_count"],
                "product_id": f"manager-research-{input_data['target_trade_date']}-{current_identity[:24]}",
            }
        )
        return bound, True

    @staticmethod
    def _progress(total: int, results: Mapping[str, Mapping[str, Any]]) -> dict[str, int | float]:
        ready = sum(1 for item in results.values() if item.get("status") == "READY" and item.get("facts"))
        cannot = sum(1 for item in results.values() if item.get("status") != "READY" or not item.get("facts"))
        completed = len(results)
        return {
            "total": total,
            "completed": completed,
            "ready": ready,
            "cannot_confirm": cannot,
            "failed": sum(1 for item in results.values() if item.get("failure_detail") or item.get("reason", "").endswith("FAILED")),
            "coverage_ratio": round(ready / total, 6) if total else 0.0,
        }

    def _commit_gap(
        self,
        input_data: Mapping[str, Any],
        product: Mapping[str, Any],
        job: Mapping[str, Any],
    ) -> str | None:
        """Return the first missing commit step for a READY product, if any.

        READY means product + job + receipt were all committed.  A reader must
        never observe READY from a half-written commit (e.g. a receipt write
        that failed after the product landed).
        """

        if job.get("status") != "READY":
            return "COMMIT_JOB_NOT_READY"
        job_id = str(job.get("job_id") or "")
        receipt = (
            self.store.read_receipt(str(input_data["target_trade_date"]), job_id)
            if job_id
            else None
        )
        if receipt is None:
            return "COMMIT_RECEIPT_MISSING"
        if receipt.get("input_identity") != input_data["input_identity"]:
            return "COMMIT_RECEIPT_IDENTITY_MISMATCH"
        if any(
            receipt.get(flag) is not False
            for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
        ):
            return "COMMIT_RECEIPT_UNSAFE_FLAGS"
        return None

    def _envelope(
        self,
        input_data: Mapping[str, Any],
        *,
        product: Mapping[str, Any] | None = None,
        job: Mapping[str, Any] | None = None,
        status: str | None = None,
        cannot_confirm: list[str] | None = None,
    ) -> dict[str, Any]:
        resolved_status = status or (product or {}).get("status") or (job or {}).get("status") or "NOT_MATERIALIZED"
        if resolved_status == "READY" and product is not None and job is not None:
            gap = self._commit_gap(input_data, product, job)
            if gap is not None:
                resolved_status = "CANNOT_CONFIRM"
                cannot_confirm = [*(cannot_confirm or []), gap]
        return {
            "schema_version": PRODUCT_SCHEMA_VERSION,
            "kind": "MANAGER_RESEARCH",
            "target_trade_date": input_data["target_trade_date"],
            "stage_id": input_data["stage_id"],
            "market": input_data["market"],
            "cutoff_at": input_data["cutoff_at"],
            "input_identity": input_data["input_identity"],
            "input_source_sha256": input_data.get("input_source_sha256"),
            "input_row_count": input_data["input_row_count"],
            "status": resolved_status,
            "product": dict(product) if product is not None else None,
            "job": dict(job) if job is not None else None,
            "can_ensure": resolved_status in {"NOT_MATERIALIZED", "CANNOT_CONFIRM", "FAILED", "PARTIAL_WITH_ROWS"},
            "can_retry": resolved_status in {"CANNOT_CONFIRM", "FAILED", "PARTIAL_WITH_ROWS"},
            "cannot_confirm": list(cannot_confirm or []),
            **FOUR_FLAGS,
            "safety": dict(FOUR_FLAGS),
        }

    def _unowned_job_envelope(
        self, input_data: Mapping[str, Any], job: Mapping[str, Any]
    ) -> dict[str, Any]:
        # A persisted receipt is not evidence that this process owns a worker.
        # Do not overwrite it or start a second worker: another process may live.
        result = self._envelope(
            input_data, job=job, status="CANNOT_CONFIRM",
            cannot_confirm=["JOB_OWNER_UNCONFIRMED"],
        )
        result.update(can_ensure=False, can_retry=False)
        return result

    @staticmethod
    def _reassemble_cached_recommendations(
        input_data: Mapping[str, Any],
        product: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Attach the recommendation contract to an existing exact-date cache.

        This is a cache migration only.  It reuses the persisted stage row,
        official source receipt and structured facts; it never calls the
        provider and never widens the candidate universe.  A row without the
        market/timing evidence required by the new contract stays
        ``DATA_INSUFFICIENT`` rather than being promoted from a legacy
        decision string.
        """

        if not isinstance(product, Mapping):
            return None
        rows = product.get("rows")
        stage_rows = input_data.get("rows")
        if not isinstance(rows, list) or not isinstance(stage_rows, list):
            return None
        target_trade_date = str(input_data.get("target_trade_date") or "")
        if not target_trade_date:
            return None
        product_date = _row_date_token(product.get("target_trade_date"))
        if product_date is not None and product_date != target_trade_date:
            return None
        cutoff = str(input_data.get("cutoff_at") or product.get("cutoff_at") or contract_cutoff_at(target_trade_date))
        # A v1 product's generated_at describes the old materialization.  A
        # v2 cache migration is a new pure derivation and records its own
        # event time; subsequent reads remain stable because the migrated
        # product is persisted.
        generated_at = _now()
        # The exact stage input is the authority for a legacy product whose
        # new evidence fields are absent.  In particular, an overall product
        # status of READY only describes provider rows; it cannot stand in for
        # a missing stage status and must never upgrade PARTIAL_WITH_ROWS.
        stage_status_value = input_data.get("stage_status") or input_data.get("source_status")
        if not isinstance(stage_status_value, str) or not stage_status_value.strip():
            stage_status_value = product.get("stage_status")
        if not isinstance(stage_status_value, str) or not stage_status_value.strip():
            stage_status_value = product.get("source_status")
        if not isinstance(stage_status_value, str) or not stage_status_value.strip():
            product_status = product.get("status")
            stage_status_value = product_status if product_status in {"PARTIAL_WITH_ROWS", "CANNOT_CONFIRM"} else "CANNOT_CONFIRM"
        stage_status = str(stage_status_value).strip()
        cannot_confirm = input_data.get("cannot_confirm") if "cannot_confirm" in input_data else product.get("cannot_confirm")
        if cannot_confirm is None:
            cannot_confirm = product.get("cannot_confirm", [])
        input_source_sha256 = input_data.get("input_source_sha256")
        stage_by_code: dict[str, Mapping[str, Any]] = {}
        for stage_row in stage_rows:
            if not isinstance(stage_row, Mapping):
                return None
            code = stage_row.get("code")
            if isinstance(code, str) and code.strip():
                stage_by_code[code.strip()] = stage_row
        migrated_rows: list[dict[str, Any]] = []
        recommendations: list[Mapping[str, Any]] = []
        for raw_row in rows:
            if not isinstance(raw_row, Mapping):
                return None
            row = dict(raw_row)
            row_target = _row_date_token(row.get("target_trade_date"))
            if row_target is not None and row_target != target_trade_date:
                return None
            row_observation = row.get("observation")
            persisted_observation = dict(row_observation) if isinstance(row_observation, Mapping) else {}
            code_value = row.get("code") or persisted_observation.get("code")
            code = str(code_value).strip() if isinstance(code_value, str) else ""
            if not code or code not in stage_by_code:
                return None
            nested_target = _row_date_token(persisted_observation.get("target_trade_date"))
            if nested_target is not None and nested_target != target_trade_date:
                return None
            # The exact stage row supplies gate and market fields.  Persisted
            # observation fields are retained, with exact input taking
            # precedence on conflicts so a stale row cannot override it.
            observation = dict(persisted_observation)
            observation.update(dict(stage_by_code[code]))
            observation.update({"code": code, "target_trade_date": target_trade_date, "input_identity": input_data.get("input_identity")})
            for key in (
                "name", "action_level", "trade_status", "trade_status_contract", "formal_eligible",
                "source_last_bar_time", "observed_at", "last_price", "current_price", "price", "support",
                "support_price", "support_primary_price", "pressure", "pressure_price", "resistance",
                "resistance_price", "volume", "volume_ratio", "pct_chg", "current_change_pct",
            ):
                if key not in observation and key in row:
                    observation[key] = row[key]
            raw_facts = row.get("facts")
            facts = raw_facts if isinstance(raw_facts, list) else []
            source = row.get("source") if isinstance(row.get("source"), Mapping) else None
            provider_status = row.get("source_status") or row.get("status")
            row["observation"] = observation
            row["stage_observation"] = dict(observation)
            # Make the execution input visible to API/UI consumers without
            # overwriting the provider row's own READY/CANNOT_CONFIRM status.
            for key in (
                "action_level", "trade_status", "trade_status_contract", "formal_eligible", "last_price",
                "current_price", "price", "support", "support_price", "support_primary_price", "pressure",
                "pressure_price", "resistance", "resistance_price", "volume", "volume_ratio", "rank",
            ):
                if key in observation:
                    row[key] = observation[key]
            row["stage_rank"] = observation.get("stage_rank")
            row["stage_row_status"] = observation.get("status")
            recommendation = build_research_recommendation(
                observation=observation,
                result={
                    "status": "READY" if provider_status == "READY" and facts else provider_status,
                    "reason": row.get("source_reason"),
                    "source": source,
                    "facts": facts,
                },
                target_trade_date=target_trade_date,
                cutoff_at=cutoff,
                generated_at=generated_at,
                input_source_sha256=input_source_sha256 if isinstance(input_source_sha256, str) else None,
                stage_status=stage_status,
                cannot_confirm=cannot_confirm,
            )
            row["research_recommendation"] = recommendation
            row["observation_timing_status"] = recommendation.get("timing_status")
            recommendations.append(recommendation)
            migrated_rows.append(row)
        assign_investment_priorities(migrated_rows)
        recommendations = [
            row["research_recommendation"]
            for row in migrated_rows
            if isinstance(row.get("research_recommendation"), Mapping)
        ]
        migrated = dict(product)
        migrated["rows"] = migrated_rows
        migrated["target_trade_date"] = target_trade_date
        migrated["input_identity"] = input_data.get("input_identity")
        migrated["input_source_sha256"] = input_source_sha256
        migrated["input_row_count"] = input_data.get("input_row_count")
        migrated["stage_id"] = input_data.get("stage_id")
        migrated["market"] = input_data.get("market")
        migrated["cutoff_at"] = cutoff
        migrated["product_id"] = f"manager-research-{target_trade_date}-{str(input_data.get('input_identity'))[:24]}"
        migrated["stage_status"] = stage_status
        migrated["cannot_confirm"] = cannot_confirm
        migrated["recommendation_summary"] = recommendation_summary(recommendations)
        migrated["generated_at"] = generated_at
        return migrated

    def _current_or_migrated_product(
        self,
        input_data: Mapping[str, Any],
        raw_product: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if raw_product is None:
            return None
        product, _bound_from_legacy = self._bind_product_to_input(input_data, raw_product)
        current_product = _current_product(product)
        if current_product is not None:
            rows = current_product.get("rows")
            has_recommendations = (
                isinstance(rows, list)
                and all(isinstance(row, Mapping) and _is_v2_recommendation(row.get("research_recommendation")) for row in rows)
                and isinstance(current_product.get("recommendation_summary"), Mapping)
                and "stage_status" in current_product
                and "cannot_confirm" in current_product
            )
            if has_recommendations:
                # GET is a read path: NEVER persist here.  A legacy-bound or
                # stale-label projection stays in memory; persistence only
                # happens through an explicit ensure/retry commit.
                return _project_cached_catalysts(current_product)
        # Only the current content contract is eligible for this small cache
        # migration.  Sources invalidated by the existing R3 content boundary
        # must still go through the normal provider-backed ensure path.
        if (
            product.get("content_contract_version") == CONTENT_CONTRACT_VERSION
            and product.get("content_contract_revision") in {CONTENT_CONTRACT_REVISION, None, ""}
            and not _legacy_product_requires_r3_refresh(product)
        ):
            migrated = self._reassemble_cached_recommendations(input_data, product)
            if migrated is not None:
                # Same rule: return the projection in memory without rewriting
                # the exact product or the legacy path during a read.
                return migrated
        return current_product

    def get(self, target_trade_date: str) -> dict[str, Any]:
        try:
            input_data = self._read_input(target_trade_date)
        except (ContractError, StoreError) as exc:
            # A typed missing-source response is useful to the UI and avoids a
            # synthetic empty product when the stage host is not configured.
            return {
                "schema_version": PRODUCT_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH",
                "target_trade_date": target_trade_date,
                "stage_id": "STAGE_0935_0940",
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "product": None,
                "job": None,
                "can_ensure": False,
                "can_retry": False,
                "cannot_confirm": [str(exc)],
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
        raw_product = self._read_cached_product(input_data)
        product = self._current_or_migrated_product(input_data, raw_product)
        job_id = self._job_id(input_data)
        with self._lock:
            job = self.store.read_job(job_id)
            running = self._active.get(job_id)
            if (job is not None and job.get("status") in {"QUEUED", "RUNNING"}
                    and (running is None or running.done())):
                return self._unowned_job_envelope(input_data, job)
        if product is not None:
            return self._envelope(input_data, product=product, job=job)
        # A terminal READY job can outlive the content revision that produced
        # its product.  Keep the stale product hidden, but expose an explicit
        # ensure signal so the existing date-page flow starts one bounded
        # refresh.  Returning the old READY status here made the UI believe
        # the stale result was current and skipped the POST /ensure step.
        if raw_product is not None and job is not None and job.get("status") == "READY":
            return self._envelope(
                input_data,
                job=job,
                status="NOT_MATERIALIZED",
                cannot_confirm=["STALE_CONTENT_CONTRACT"],
            )
        if job is not None:
            return self._envelope(input_data, job=job)
        return self._envelope(input_data)

    def ensure(self, target_trade_date: str, *, force: bool = False) -> dict[str, Any]:
        try:
            input_data = self._read_input(target_trade_date)
        except (ContractError, StoreError) as exc:
            return {
                "schema_version": PRODUCT_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH",
                "target_trade_date": target_trade_date,
                "stage_id": "STAGE_0935_0940",
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "product": None,
                "job": None,
                "can_ensure": False,
                "can_retry": False,
                "cannot_confirm": [str(exc)],
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
        job_id = self._job_id(input_data)
        with self._lock:
            if self._closed:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=["SERVICE_CLOSED"])
            raw_product = self._read_cached_product(input_data)
            product = self._current_or_migrated_product(input_data, raw_product)
            job = self.store.read_job(job_id)
            running = self._active.get(job_id)
            if running is not None and not running.done():
                return self._envelope(input_data, product=product, job=job, status="RUNNING")
            if job is not None and job.get("status") in {"QUEUED", "RUNNING"}:
                return self._unowned_job_envelope(input_data, job)
            if product is not None and not force:
                return self._envelope(input_data, product=product, job=job)
            attempt = int(job.get("attempt", 0)) + 1 if job else 1
            now = _now()
            new_job = {
                "schema_version": JOB_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH_JOB",
                "job_id": job_id,
                "attempt": attempt,
                "target_trade_date": input_data["target_trade_date"],
                "stage_id": input_data["stage_id"],
                "market": input_data["market"],
                "cutoff_at": input_data["cutoff_at"],
                "input_identity": input_data["input_identity"],
                "input_source_sha256": input_data.get("input_source_sha256"),
                "input_row_count": input_data["input_row_count"],
                "status": "QUEUED",
                "progress": self._progress(input_data["input_row_count"], {}),
                "results": {},
                "error": None,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "can_retry": False,
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
            self._cancelled.discard(job_id)
            self.store.write_job(new_job)
            future = self._executor.submit(self._run_job, input_data, new_job)
            self._active[job_id] = future
            return self._envelope(input_data, job=new_job, status="QUEUED")

    @staticmethod
    def _event_job_id(input_data: Mapping[str, Any]) -> str:
        return f"mr-events-{input_data['target_trade_date']}-{str(input_data['input_identity'])[:32]}"

    def ensure_events(self, target_trade_date: str, *, force: bool = False) -> dict[str, Any]:
        """Refresh catalysts for an existing product without recollecting PDFs."""

        try:
            input_data = self._read_input(target_trade_date)
        except (ContractError, StoreError) as exc:
            return {
                "schema_version": PRODUCT_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH",
                "target_trade_date": target_trade_date,
                "stage_id": "STAGE_0935_0940",
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "product": None,
                "job": None,
                "can_ensure": False,
                "can_retry": False,
                "cannot_confirm": [str(exc)],
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
        with self._lock:
            if self._closed:
                return self._envelope(input_data, status="CANNOT_CONFIRM", cannot_confirm=["SERVICE_CLOSED"])
            raw_product = self._read_cached_product(input_data)
            product = self._current_or_migrated_product(input_data, raw_product)
            if product is None:
                return self._envelope(
                    input_data,
                    status="NOT_MATERIALIZED",
                    cannot_confirm=["FINANCIAL_PRODUCT_NOT_MATERIALIZED"],
                )
            job_id = self._event_job_id(input_data)
            job = self.store.read_job(job_id)
            running = self._active.get(job_id)
            if running is not None and not running.done():
                return self._envelope(input_data, product=product, job=job, status="RUNNING")
            if job is not None and job.get("status") in {"QUEUED", "RUNNING"}:
                return self._unowned_job_envelope(input_data, job)
            if job is not None and job.get("status") in {"READY", "PARTIAL_WITH_ROWS", "CANNOT_CONFIRM", "FAILED"} and not force:
                return self._envelope(input_data, product=product, job=job, status=job.get("status"))
            now = _now()
            new_job = {
                "schema_version": JOB_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH_EVENT_REFRESH_JOB",
                "job_id": job_id,
                "attempt": int(job.get("attempt", 0)) + 1 if job else 1,
                "target_trade_date": input_data["target_trade_date"],
                "stage_id": input_data["stage_id"],
                "market": input_data["market"],
                "cutoff_at": input_data["cutoff_at"],
                "input_identity": input_data["input_identity"],
                "input_source_sha256": input_data.get("input_source_sha256"),
                "input_row_count": input_data["input_row_count"],
                "status": "QUEUED",
                "mode": "EVENT_REFRESH",
                "progress": {"total": input_data["input_row_count"], "completed": 0, "event_rows": 0},
                "results": {},
                "error": None,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "can_retry": False,
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
            self._cancelled.discard(job_id)
            self.store.write_job(new_job)
            future = self._executor.submit(self._run_event_refresh_job, input_data, new_job, product)
            self._active[job_id] = future
            return self._envelope(input_data, product=product, job=new_job, status="QUEUED")

    def _run_event_refresh_job(
        self,
        input_data: Mapping[str, Any],
        job: Mapping[str, Any],
        product: Mapping[str, Any],
    ) -> None:
        job_id = str(job["job_id"])
        job_state = dict(job)
        job_state.update(status="RUNNING", started_at=_now(), updated_at=_now())
        self.store.write_job(job_state)
        observations = list(input_data["rows"])
        try:
            previous_rows = {
                str(row.get("code")): row.get("catalyst_result")
                for row in product.get("rows", [])
                if isinstance(row, Mapping) and isinstance(row.get("code"), str) and isinstance(row.get("catalyst_result"), Mapping)
            }
            event_batch = self._collect_events(input_data, observations, previous_rows=previous_rows)
            # Attach onto the LATEST committed product: a financial retry that
            # finished while events were collecting must not be reverted to
            # this refresh's older snapshot.
            latest_product = (
                self.store.read_product(input_data["target_trade_date"], input_data["input_identity"])
                or product
            )
            updated = self._attach_catalyst_to_product(latest_product, event_batch, observations)
            if job_id in self._cancelled:
                job_state.update(status="CANCELLED", error="CANCELLED_BY_REQUEST", can_retry=True)
            else:
                self.store.replace_product(updated)
                rows = event_batch.get("rows") if isinstance(event_batch.get("rows"), Mapping) else {}
                result_map = {
                    str(code): {
                        "status": item.get("status", "CANNOT_CONFIRM"),
                        "event_count": len(item.get("events", [])) if isinstance(item.get("events"), list) else 0,
                        "reader_material_count": len(item.get("reader_materials", [])) if isinstance(item.get("reader_materials"), list) else 0,
                        "reader_status": item.get("reader_status", "CANNOT_CONFIRM"),
                    }
                    for code, item in rows.items()
                    if isinstance(item, Mapping)
                }
                event_count = sum(int(item.get("event_count", 0)) for item in result_map.values())
                reader_material_count = sum(int(item.get("reader_material_count", 0)) for item in result_map.values())
                batch_status = str(event_batch.get("status") or "CANNOT_CONFIRM")
                reader_coverage = event_batch.get("reader_coverage") if isinstance(event_batch.get("reader_coverage"), Mapping) else {}
                reader_status = str(reader_coverage.get("status") or "CANNOT_CONFIRM")
                # A source-wide failure is authoritative even when a malformed
                # provider result happens to report a non-zero row count.  Do
                # not let the refresh job manufacture READY from that count.
                final_status = (
                    batch_status
                    if batch_status in {"CANNOT_CONFIRM", "FAILED"}
                    else "READY" if event_count or reader_status == "READY" else batch_status
                )
                job_state.update(
                    status=final_status,
                    results=result_map,
                    progress={"total": len(observations), "completed": len(result_map), "event_rows": event_count, "reader_materials": reader_material_count},
                    can_retry=final_status != "READY",
                )
                self.store.write_receipt(
                    input_data["target_trade_date"],
                    job_id,
                    {
                        "schema_version": "v4.manager_research.catalyst_receipt.v1",
                        "job_id": job_id,
                        "target_trade_date": input_data["target_trade_date"],
                        "input_identity": input_data["input_identity"],
                        "status": final_status,
                        "progress": job_state["progress"],
                        "catalyst_status": updated.get("catalyst_status"),
                        "catalyst_coverage": updated.get("catalyst_coverage"),
                        "catalyst_source_counts": updated.get("catalyst_source_counts"),
                        "catalyst_source_receipt_count": len(updated.get("catalyst_source_receipts", [])),
                        "reader_coverage": updated.get("reader_coverage"),
                        "reader_source_counts": updated.get("reader_source_counts"),
                        "reader_current_as_of": updated.get("reader_current_as_of"),
                        "reader_material_count": reader_material_count,
                        "financial_recollection": False,
                        **FOUR_FLAGS,
                    },
                )
            job_state.update(completed_at=_now(), updated_at=_now())
            self.store.write_job(job_state)
        except Exception as exc:
            job_state.update(
                status="FAILED",
                error=f"{type(exc).__name__}: {exc}",
                completed_at=_now(),
                updated_at=_now(),
                can_retry=True,
            )
            self.store.write_job(job_state)
        finally:
            with self._lock:
                self._active.pop(job_id, None)

    def migrate(self, target_trade_date: str) -> dict[str, Any]:
        """Explicitly persist one in-memory cache migration.

        Read paths (``get``) never write.  This command reassembles the
        current-contract product from a legacy or pre-recommendation cache
        and writes it through the validated store commit path; it never
        calls the provider and never touches the legacy alias file.
        """

        try:
            input_data = self._read_input(target_trade_date)
        except (ContractError, StoreError) as exc:
            return {
                "schema_version": PRODUCT_SCHEMA_VERSION,
                "kind": "MANAGER_RESEARCH",
                "target_trade_date": target_trade_date,
                "stage_id": "STAGE_0935_0940",
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "product": None,
                "job": None,
                "can_ensure": False,
                "can_retry": False,
                "cannot_confirm": [str(exc)],
                **FOUR_FLAGS,
                "safety": dict(FOUR_FLAGS),
            }
        with self._lock:
            raw_product = self._read_cached_product(input_data)
            product = self._current_or_migrated_product(input_data, raw_product)
            if product is None:
                return self._envelope(
                    input_data,
                    status="NOT_MATERIALIZED",
                    cannot_confirm=["NO_MIGRATABLE_PRODUCT"],
                )
            try:
                if product.get("input_identity") == str(input_data["input_identity"]):
                    stored = self.store.replace_product(product)
                else:
                    stored = self.store.write_product(product)
            except (StoreError, ValueError) as exc:
                return self._envelope(
                    input_data,
                    status="CANNOT_CONFIRM",
                    cannot_confirm=[f"MIGRATION_WRITE_FAILED: {exc}"],
                )
            job = self.store.read_job(self._job_id(input_data))
            return self._envelope(input_data, product=stored, job=job)

    def retry(self, target_trade_date: str) -> dict[str, Any]:
        return self.ensure(target_trade_date, force=True)

    def job(self, job_id: str, target_trade_date: str | None = None) -> dict[str, Any] | None:
        job = self.store.read_job(job_id)
        if job is None:
            return None
        if target_trade_date is not None and job.get("target_trade_date") != target_trade_date:
            return None
        return job

    def cancel(self, job_id: str, target_trade_date: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            job = self.store.read_job(job_id)
            if job is None or (target_trade_date is not None and job.get("target_trade_date") != target_trade_date):
                return None
            if job.get("status") in {"READY", "PARTIAL_WITH_ROWS", "CANNOT_CONFIRM", "FAILED", "CANCELLED"}:
                return job
            self._cancelled.add(job_id)
            updated = dict(job)
            updated["status"] = "CANCELLED"
            updated["error"] = "CANCELLED_BY_REQUEST"
            updated["can_retry"] = True
            updated["updated_at"] = _now()
            self.store.write_job(updated)
            return updated

    def _collect_one(self, target_trade_date: str, cutoff_at: str, observation: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.source_provider is None:
            return {
                "status": "CANNOT_CONFIRM",
                "reason": "SOURCE_PROVIDER_UNAVAILABLE",
                "failure_detail": "no official research source provider is configured",
                "issuer": None,
                "source": None,
                "facts": [],
            }
        try:
            if hasattr(self.source_provider, "collect"):
                result = self.source_provider.collect(  # type: ignore[union-attr]
                    target_trade_date=target_trade_date,
                    cutoff_at=cutoff_at,
                    observation=observation,
                )
            else:
                result = self.source_provider(  # type: ignore[operator]
                    target_trade_date=target_trade_date,
                    cutoff_at=cutoff_at,
                    observation=observation,
                )
            if not isinstance(result, Mapping):
                raise ContractError("source provider returned a non-object")
            status = result.get("status")
            facts = result.get("facts")
            if status == "READY" and not isinstance(facts, list):
                return {
                    **dict(result),
                    "status": "CANNOT_CONFIRM",
                    "reason": "SOURCE_FACTS_MISSING",
                    "failure_detail": "provider claimed READY without extracted facts",
                    "facts": [],
                }
            if status == "READY":
                verifiable_facts = [
                    fact
                    for fact in facts
                    if _usable_fact(fact)
                ]
                if not verifiable_facts:
                    return {
                        **dict(result),
                        "status": "CANNOT_CONFIRM",
                        "reason": "SOURCE_FACTS_NOT_STRUCTURED",
                        "failure_detail": "provider claimed READY without Chinese, page-locatable structured facts",
                        "facts": [],
                    }
                if not _has_researchable_fact_set(verifiable_facts):
                    return {
                        **dict(result),
                        "status": "CANNOT_CONFIRM",
                        "reason": "SOURCE_FACTS_NOT_RESEARCHABLE",
                        "failure_detail": "parsed financial rows contain no primary operating, profit/loss, or cash-flow metric",
                        "facts": [],
                    }
                source = result.get("source")
                if not isinstance(source, Mapping):
                    return {
                        **dict(result),
                        "status": "CANNOT_CONFIRM",
                        "reason": "SOURCE_RECEIPT_MISSING",
                        "failure_detail": "structured facts are not bound to an official source receipt",
                        "facts": [],
                    }
                result = {**dict(result), "facts": verifiable_facts}
            if status not in {"READY", "CANNOT_CONFIRM", "NO_MATCH"}:
                return {
                    **dict(result),
                    "status": "CANNOT_CONFIRM",
                    "reason": "SOURCE_STATUS_INVALID",
                    "failure_detail": f"unsupported provider status: {status!r}",
                    "facts": [],
                }
            return dict(result)
        except Exception as exc:
            return {
                "status": "CANNOT_CONFIRM",
                "reason": "SOURCE_PROVIDER_FAILED",
                "failure_detail": f"{type(exc).__name__}: {exc}",
                "issuer": None,
                "source": None,
                "facts": [],
            }

    @staticmethod
    def _empty_event_batch(
        input_data: Mapping[str, Any],
        observations: list[Mapping[str, Any]],
        reason: str,
    ) -> dict[str, Any]:
        rows = {
            str(observation.get("code")): _empty_catalyst_row(
                str(observation.get("code")),
                reason=reason,
            )
            for observation in observations
            if observation.get("code")
        }
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "status": "CANNOT_CONFIRM",
            "source_id": None,
            "rows": rows,
            "source_counts": [],
            "coverage": {
                "requested_candidates": len(observations),
                "event_count": 0,
                "historical_event_count": 0,
                "current_event_count": 0,
                "completeness": "EVENT_SOURCE_NOT_RUN",
                "no_match_is_not_complete": True,
                "reason": reason,
            },
            "current_event_as_of": _now(),
            "historical_cutoff_at": input_data.get("cutoff_at"),
        }

    def _collect_events(
        self,
        input_data: Mapping[str, Any],
        observations: list[Mapping[str, Any]],
        *,
        previous_rows: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        """Run only the bounded event lane and keep its failure independent."""

        collector = getattr(self.source_provider, "collect_events", None) if self.source_provider is not None else None
        try:
            if callable(collector):
                result = collector(
                    target_trade_date=input_data["target_trade_date"],
                    cutoff_at=input_data["cutoff_at"],
                    observations=observations,
                    previous_rows=previous_rows or {},
                    current_event_as_of=_now(),
                )
                if not isinstance(result, Mapping):
                    raise ContractError("event provider returned a non-object")
                raw_rows = result.get("rows")
                rows: dict[str, Mapping[str, Any]] = {}
                if isinstance(raw_rows, Mapping):
                    for observation in observations:
                        code = str(observation.get("code") or "")
                        item = raw_rows.get(code)
                        rows[code] = item if isinstance(item, Mapping) else _empty_catalyst_row(code, reason="EVENT_ROW_MISSING")
                else:
                    rows = {
                        str(observation.get("code")): _empty_catalyst_row(
                            str(observation.get("code")),
                            reason="EVENT_ROWS_MISSING",
                        )
                        for observation in observations
                        if observation.get("code")
                    }
                normalized = {**dict(result), "rows": rows}
            else:
                # The public reader can be exercised independently of the
                # optional event provider (for example in a canary or a
                # source outage).  Preserve that source boundary per row.
                normalized = self._empty_event_batch(input_data, observations, "EVENT_PROVIDER_UNAVAILABLE")
            reader_enabled = bool(getattr(self.source_provider, "reader_source_enabled", False)) or self.reader_fetcher is not None
            if not reader_enabled:
                return normalized
            reader_batch = read_public_news_batch(
                observations,
                target_date=str(input_data["target_trade_date"]),
                queried_at=_now(),
                fetcher=self.reader_fetcher,
            )
            return _attach_reader_batch(normalized, reader_batch, observations)
        except Exception as exc:
            return self._empty_event_batch(
                input_data,
                observations,
                f"EVENT_PROVIDER_FAILED:{type(exc).__name__}",
            )

    @staticmethod
    def _attach_catalyst_to_product(
        product: Mapping[str, Any],
        event_batch: Mapping[str, Any],
        observations: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Attach event evidence while preserving every financial field."""

        event_rows = event_batch.get("rows") if isinstance(event_batch.get("rows"), Mapping) else {}
        updated = dict(product)
        updated_rows: list[dict[str, Any]] = []
        catalyst_receipts: list[dict[str, Any]] = []
        for observation in observations:
            code = str(observation.get("code") or "")
            existing = next(
                (row for row in product.get("rows", []) if isinstance(row, Mapping) and str(row.get("code") or "") == code),
                None,
            )
            if not isinstance(existing, Mapping):
                continue
            row = dict(existing)
            catalyst = event_rows.get(code) if isinstance(event_rows, Mapping) else None
            catalyst_result = dict(catalyst) if isinstance(catalyst, Mapping) else _empty_catalyst_row(code, reason="EVENT_ROW_MISSING")
            catalyst_result.setdefault("code", code)
            finance = _financial_counterevidence_for_row(row)
            financial_text = list(finance.get("financial_counterevidence") or [])
            financial_refs = list(finance.get("financial_counterevidence_refs") or [])
            financial_revaluation = finance.get("financial_re_evaluation")
            catalyst_result["financial_counterevidence"] = financial_text
            catalyst_result["financial_counterevidence_refs"] = financial_refs
            catalyst_result["financial_re_evaluation"] = financial_revaluation
            catalyst_gaps = list(catalyst_result.get("market_confirmation_gap") or [])
            if finance.get("market_price_volume_unconfirmed"):
                catalyst_gaps.append("MARKET_PRICE_VOLUME_UNCONFIRMED")
            catalyst_result["market_confirmation_gap"] = list(dict.fromkeys(str(item) for item in catalyst_gaps if item))
            enriched_events: list[dict[str, Any]] = []
            event_by_key: dict[str, dict[str, Any]] = {}
            for event_item in catalyst_result.get("events", []) if isinstance(catalyst_result.get("events"), list) else []:
                if not isinstance(event_item, Mapping):
                    continue
                event = dict(event_item)
                event["financial_counterevidence"] = list(dict.fromkeys([
                    *([str(item) for item in event.get("financial_counterevidence", []) if item]),
                    *financial_text,
                ]))
                event["financial_counterevidence_refs"] = financial_refs
                event["financial_re_evaluation"] = financial_revaluation
                event_gaps = list(event.get("market_confirmation_gap") or [])
                if finance.get("market_price_volume_unconfirmed"):
                    event_gaps.append("MARKET_PRICE_VOLUME_UNCONFIRMED")
                event["market_confirmation_gap"] = list(dict.fromkeys(str(item) for item in event_gaps if item))
                enriched_events.append(event)
                event_key = str(event.get("event_id") or event.get("source_url") or event.get("source_title") or "")
                if event_key:
                    event_by_key[event_key] = event
            # Copy the event so a provider's result object cannot be mutated
            # outside this product assembly boundary, and keep the historical
            # and current projections consistent with the enriched event list.
            catalyst_result["events"] = enriched_events
            for projection in ("historical_events", "current_events"):
                raw_projection = catalyst_result.get(projection)
                if not isinstance(raw_projection, list):
                    continue
                catalyst_result[projection] = [
                    event_by_key.get(
                        str(event.get("event_id") or event.get("source_url") or event.get("source_title") or ""),
                        dict(event),
                    )
                    for event in raw_projection
                    if isinstance(event, Mapping)
                ]
            row["catalyst_result"] = catalyst_result
            row["current_research"] = {
                "status": catalyst_result.get("status", "CANNOT_CONFIRM"),
                "catalyst_advice": catalyst_result.get("catalyst_advice"),
                "financial_advice": financial_revaluation,
                "financial_counterevidence": financial_text,
                "financial_counterevidence_refs": financial_refs,
                "execution_gate": row.get("research_recommendation", {}).get("execution_gate")
                if isinstance(row.get("research_recommendation"), Mapping)
                else None,
                "research_only": True,
            }
            updated_rows.append(row)
            receipts = catalyst_result.get("source_receipts")
            if isinstance(receipts, list):
                catalyst_receipts.extend(item for item in receipts if isinstance(item, Mapping))
        # The backend owns the small focus set.  All exact candidates remain
        # in ``rows`` with their complete event evidence, while only up to
        # three interpretable recent rows receive unique continuous ranks.
        _assign_catalyst_focus_ranks(
            updated_rows,
            str(product.get("target_trade_date") or ""),
        )
        for row in updated_rows:
            result = row.get("catalyst_result")
            if isinstance(result, Mapping):
                current_research = dict(row.get("current_research")) if isinstance(row.get("current_research"), Mapping) else {}
                current_research["catalyst_advice"] = result.get("catalyst_advice")
                row["current_research"] = current_research
        updated["rows"] = updated_rows
        updated["catalyst_schema_version"] = EVENT_SCHEMA_VERSION
        updated["catalyst_status"] = str(event_batch.get("status") or "CANNOT_CONFIRM")
        updated["catalyst_coverage"] = dict(event_batch.get("coverage")) if isinstance(event_batch.get("coverage"), Mapping) else {
            "completeness": "BOUNDED_SOURCES_ONLY",
            "no_match_is_not_complete": True,
        }
        updated["catalyst_source_counts"] = list(event_batch.get("source_counts")) if isinstance(event_batch.get("source_counts"), list) else []
        updated["catalyst_source_receipts"] = catalyst_receipts
        updated["catalyst_current_event_as_of"] = event_batch.get("current_event_as_of") or _now()
        updated["reader_coverage"] = dict(event_batch.get("reader_coverage")) if isinstance(event_batch.get("reader_coverage"), Mapping) else {
            "status": "CANNOT_CONFIRM",
            "completeness": "READER_NOT_RUN",
        }
        updated["reader_source_counts"] = list(event_batch.get("reader_source_counts")) if isinstance(event_batch.get("reader_source_counts"), list) else []
        updated["reader_current_as_of"] = event_batch.get("reader_current_as_of")
        updated["current_research"] = {
            "status": updated["catalyst_status"],
            "catalyst_coverage": updated["catalyst_coverage"],
            "catalyst_source_counts": updated["catalyst_source_counts"],
            "catalyst_current_event_as_of": updated["catalyst_current_event_as_of"],
            "reader_coverage": updated["reader_coverage"],
            "reader_current_as_of": updated["reader_current_as_of"],
            "financial_research_status": product.get("status"),
            "research_only": True,
        }
        return updated

    def _run_job(self, input_data: Mapping[str, Any], job: Mapping[str, Any]) -> None:
        job_id = str(job["job_id"])
        job_state = dict(job)
        job_state["status"] = "RUNNING"
        job_state["started_at"] = _now()
        job_state["updated_at"] = _now()
        self.store.write_job(job_state)
        results: dict[str, Mapping[str, Any]] = {}
        observations = list(input_data["rows"])
        # Four bounded provider calls keep the public endpoint responsive while
        # still exposing each row's status as soon as it finishes.
        row_workers = min(4, max(1, len(observations)))
        deadline = time.monotonic() + self.row_timeout_seconds * max(1, len(observations) // row_workers + 1)
        futures: dict[Future[Any], Mapping[str, Any]] = {}
        try:
            futures = {
                self._row_executor.submit(self._collect_one, input_data["target_trade_date"], input_data["cutoff_at"], observation): observation
                for observation in observations
            }
            try:
                completed_futures = as_completed(
                    futures,
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                for future in completed_futures:
                    if job_id in self._cancelled:
                        for pending in futures:
                            pending.cancel()
                        break
                    observation = futures[future]
                    code = str(observation["code"])
                    try:
                        result = dict(future.result(timeout=max(0.1, deadline - time.monotonic())))
                    except Exception as exc:
                        result = {
                            "status": "CANNOT_CONFIRM",
                            "reason": "SOURCE_PROVIDER_FAILED",
                            "failure_detail": f"{type(exc).__name__}: {exc}",
                            "issuer": None,
                            "source": None,
                            "facts": [],
                        }
                    results[code] = result
                    job_state["results"] = {key: dict(value) for key, value in results.items()}
                    job_state["progress"] = self._progress(len(observations), results)
                    job_state["updated_at"] = _now()
                    self.store.write_job(job_state)
            except FutureTimeoutError:
                # A public source can stall independently of the HTTP
                # request.  Finish every unfinished row as visible
                # CANNOT_CONFIRM instead of leaving a forever-running job.
                for pending, observation in futures.items():
                    code = str(observation["code"])
                    if code in results:
                        continue
                    pending.cancel()
                    results[code] = {
                        "status": "CANNOT_CONFIRM",
                        "reason": "SOURCE_PROVIDER_TIMEOUT",
                        "failure_detail": f"provider exceeded {self.row_timeout_seconds:.1f}s row budget",
                        "issuer": None,
                        "source": None,
                        "facts": [],
                    }
                job_state["results"] = {key: dict(value) for key, value in results.items()}
                job_state["progress"] = self._progress(len(observations), results)
                job_state["updated_at"] = _now()
                self.store.write_job(job_state)
            # The catalyst lane is independent of the financial collection.
            # A source failure here remains visible on the product and never
            # discards already parsed official financial facts.
            event_batch = self._collect_events(input_data, observations)
            product = self._build_product(input_data, observations, results, event_batch=event_batch)
            final_status = product["status"]
            receipt_payload = {
                "schema_version": "v4.manager_research.receipt.v1",
                "job_id": job_id,
                "target_trade_date": input_data["target_trade_date"],
                "input_identity": input_data["input_identity"],
                "provider_id": getattr(self.source_provider, "provider_id", type(self.source_provider).__name__ if self.source_provider else None),
                "status": final_status,
                "progress": job_state["progress"],
                "source_receipt_count": len(product.get("source_receipts", [])),
                "content_contract_version": CONTENT_CONTRACT_VERSION,
                "content_contract_revision": CONTENT_CONTRACT_REVISION,
                "pdf_parser": "pypdf",
                "pdf_parser_version": "6.10.0",
                "generated_at": product["generated_at"],
                **FOUR_FLAGS,
            }
            with self._lock:
                # Publish under the same lock that cancel() takes and re-check
                # both the in-memory flag and the persisted job: a cancel that
                # arrived after the row-collection check must win, and a
                # CANCELLED job must never be overwritten by a late READY.
                latest_job = self.store.read_job(job_id)
                if job_id in self._cancelled or (
                    latest_job is not None and latest_job.get("status") == "CANCELLED"
                ):
                    job_state["status"] = "CANCELLED"
                    job_state["error"] = "CANCELLED_BY_REQUEST"
                    job_state["completed_at"] = _now()
                    job_state["updated_at"] = _now()
                    job_state["can_retry"] = True
                    self.store.write_job(job_state)
                    return
                # Commit order: receipt first, product second, job last.  A
                # reader therefore never observes a READY product without its
                # receipt, and any I/O failure keeps the job out of READY.
                self.store.write_receipt(input_data["target_trade_date"], job_id, receipt_payload)
                prior = self.store.read_product(input_data["target_trade_date"], input_data["input_identity"])
                if prior is not None:
                    self.store.replace_product(product)
                else:
                    self.store.write_product(product)
                job_state["status"] = final_status
                job_state["completed_at"] = _now()
                job_state["updated_at"] = _now()
                job_state["can_retry"] = final_status != "READY"
                self.store.write_job(job_state)
        except Exception as exc:
            job_state["status"] = "FAILED"
            job_state["error"] = f"{type(exc).__name__}: {exc}"
            job_state["updated_at"] = _now()
            job_state["completed_at"] = _now()
            job_state["can_retry"] = True
            self.store.write_job(job_state)
        finally:
            # Never wait here for a timed-out public transport. Cancel queued
            # calls; running calls are bounded by the shared four-worker pool.
            for pending in futures:
                pending.cancel()
            with self._lock:
                self._active.pop(job_id, None)

    @staticmethod
    def _build_product(
        input_data: Mapping[str, Any],
        observations: list[Mapping[str, Any]],
        results: Mapping[str, Mapping[str, Any]],
        *,
        event_batch: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        generated = _now()
        raw_stage_status = input_data.get("stage_status", input_data.get("source_status"))
        stage_status = raw_stage_status.strip() if isinstance(raw_stage_status, str) and raw_stage_status.strip() else "CANNOT_CONFIRM"
        stage_cannot_confirm = input_data.get("cannot_confirm", [])
        ready_count = sum(1 for result in results.values() if result.get("status") == "READY" and result.get("facts"))
        if ready_count == len(observations):
            overall_status = "READY"
        elif ready_count > 0:
            overall_status = "PARTIAL_WITH_ROWS"
        else:
            overall_status = "CANNOT_CONFIRM"
        product_rows: list[dict[str, Any]] = []
        source_receipts: list[dict[str, Any]] = []
        for observation in observations:
            code = str(observation["code"])
            result = results.get(
                code,
                {
                    "status": "CANNOT_CONFIRM",
                    "reason": "ROW_NOT_COMPLETED",
                    "failure_detail": "row did not receive a provider response",
                    "facts": [],
                    "source": None,
                },
            )
            row_status = "READY" if result.get("status") == "READY" and result.get("facts") else "CANNOT_CONFIRM"
            facts: list[dict[str, Any]] = []
            for fact in result.get("facts") or []:
                if not isinstance(fact, Mapping):
                    continue
                if not _usable_fact(fact):
                    continue
                source_map = result.get("source") if isinstance(result.get("source"), Mapping) else {}
                facts.append(
                    {
                        "statement_cn": str(fact["statement_cn"]).strip(),
                        "fact_type": "OFFICIAL_FACT",
                        "fact_kind": str(fact["fact_kind"]),
                        "locator": str(fact["locator"]),
                        "page": int(fact["page"]),
                        "source_excerpt": str(fact["source_excerpt"]).strip(),
                        "fields": dict(fact["fields"]),
                        "source_url": source_map.get("url"),
                        "source_sha256": source_map.get("sha256"),
                    }
                )
            source = dict(result.get("source")) if isinstance(result.get("source"), Mapping) else None
            receipt = {"code": code, "status": row_status, "reason": result.get("reason")}
            if source is not None:
                receipt.update(source)
            # Keep one receipt slot per requested row even when the provider
            # could not establish an issuer mapping.  The absence of a URL is
            # itself visible evidence for CANNOT_CONFIRM, never a title-only
            # substitute.
            source_receipts.append(receipt)
            source_url = source.get("url") if source else None
            sections = _build_research_sections(
                str(result.get("issuer") or observation.get("name") or code),
                code,
                facts,
                observation,
            ) if row_status == "READY" else {
                "thesis_cn": "官方来源尚未形成可核实正文事实，不能把标题或行情写成完整公司深研。",
                "inferences_cn": [],
                "counterevidence_cn": ["当前没有可复核的正文事实，不能据此形成公司判断。"],
                "confirmation_conditions": ["补齐官方正文、页码和同日来源回执后再研究。"],
                "invalidation_conditions": ["若身份、日期或正文继续无法确认，保持不可确认。"],
            }
            thesis = str(sections["thesis_cn"])
            observation_full = dict(observation)
            observation_full.update(
                {
                    "code": code,
                    "name": observation.get("name", code),
                    "market": input_data["market"],
                    "stage_id": input_data["stage_id"],
                    "target_trade_date": input_data["target_trade_date"],
                    "input_identity": input_data.get("input_identity"),
                }
            )
            research_row = {
                "status": row_status,
                "code": code,
                "market": "HK_CONNECT",
                "name": observation.get("name", code),
                "issuer": result.get("issuer"),
                "target_trade_date": input_data["target_trade_date"],
                "decision": SAFE_DECISION if row_status == "READY" else SAFE_CANNOT_DECISION,
                "direction": "观察" if row_status == "READY" else "UNVERIFIED",
                "thesis_cn": thesis,
                "facts": facts,
                "inferences_cn": list(sections["inferences_cn"]),
                "counterevidence_cn": list(sections["counterevidence_cn"]),
                "confirmation_conditions": list(sections["confirmation_conditions"]),
                "invalidation_conditions": list(sections["invalidation_conditions"]),
                "research_next_action": (
                    "按原文页码复核上述字段，并补下一期同口径数据与阶段承接。"
                    if row_status == "READY"
                    else "保留本股原始观察，按来源回执补齐可复核公司材料。"
                ),
                # Keep the complete exact stage row alongside the provider
                # facts.  This is required for a provider-zero v1->v2
                # re-projection to recover gate and market fields by code.
                "observation": observation_full,
                "stage_observation": dict(observation_full),
                "observation_source": {
                    "kind": "LIVE_STAGE_ARTIFACT",
                    "stage_id": input_data["stage_id"],
                    "source_last_bar_time": observation.get("source_last_bar_time"),
                    "artifact_sha256": input_data.get("input_source_sha256"),
                    "code": code,
                },
                "source": source,
                "source_url": source_url,
                "source_status": row_status,
                "source_reason": result.get("reason"),
                "source_failure_detail": result.get("failure_detail"),
                # The recommendation builder below classifies the observation
                # timing from the exact target date, stage bar, source publish
                # time and product generation time.  Keep the legacy fields,
                # but derive them so a complete current-day row is not
                # mislabeled as an historical backfill before it is reviewed.
                "origin": "CURRENT_DAY_RESEARCH",
                "historical_system_available": False,
                "historical_system_note": "当前日目标09:40之后生成；仅证明请求时点可对齐，不证明系统在09:40已消费；研究建议仍受 RESEARCH_ONLY 边界约束。",
                **FOUR_FLAGS,
            }
            for key in (
                "action_level", "trade_status", "trade_status_contract", "formal_eligible", "last_price",
                "current_price", "price", "support", "support_price", "support_primary_price", "pressure",
                "pressure_price", "resistance", "resistance_price", "volume", "volume_ratio", "rank",
            ):
                if key in observation:
                    research_row[key] = observation[key]
            research_row["stage_rank"] = observation.get("stage_rank")
            research_row["stage_row_status"] = observation.get("status")
            research_row["stage_status"] = stage_status
            recommendation = build_research_recommendation(
                observation=observation,
                result={**dict(result), "status": row_status, "facts": facts, "source": source},
                target_trade_date=input_data["target_trade_date"],
                cutoff_at=input_data["cutoff_at"],
                generated_at=generated,
                input_source_sha256=input_data.get("input_source_sha256"),
                stage_status=stage_status,
                cannot_confirm=stage_cannot_confirm,
            )
            research_row["research_recommendation"] = recommendation
            research_row["observation_timing_status"] = recommendation.get("timing_status")
            if recommendation.get("timing_status") != "CURRENT_AFTER_CUTOFF":
                research_row["origin"] = "AUTOMATIC_HISTORICAL_BACKFILL"
                research_row["historical_system_available"] = False
                research_row["historical_system_note"] = "本产品由目标日请求后回溯采集；不证明目标09:40系统当时已消费该研究。"
            product_rows.append(research_row)
        assign_investment_priorities(product_rows)
        recommendations = [
            row["research_recommendation"]
            for row in product_rows
            if isinstance(row.get("research_recommendation"), Mapping)
        ]
        current_day_rows = bool(recommendations) and all(
            recommendation.get("timing_status") == "CURRENT_AFTER_CUTOFF"
            for recommendation in recommendations
        )
        product = {
            "schema_version": PRODUCT_SCHEMA_VERSION,
            "kind": "MANAGER_RESEARCH_PRODUCT",
            "product_id": f"manager-research-{input_data['target_trade_date']}-{input_data['input_identity'][:24]}",
            "owner": "stock_investment_research_manager",
            "provider_id": next(
                (
                    receipt.get("provider_id")
                    for receipt in source_receipts
                    if isinstance(receipt.get("provider_id"), str) and receipt.get("provider_id")
                ),
                None,
            ),
            "target_trade_date": input_data["target_trade_date"],
            "stage_id": input_data["stage_id"],
            "market": input_data["market"],
            "cutoff_at": input_data["cutoff_at"],
            "input_identity": input_data["input_identity"],
            "input_source_sha256": input_data.get("input_source_sha256"),
            "input_row_count": input_data["input_row_count"],
            "status": overall_status,
            "stage_status": stage_status,
            "cannot_confirm": stage_cannot_confirm,
            "content_contract_version": CONTENT_CONTRACT_VERSION,
            "content_contract_revision": CONTENT_CONTRACT_REVISION,
            "pdf_parser": "pypdf",
            "pdf_parser_version": "6.10.0",
            "coverage": {
                "requested_rows": len(observations),
                "ready_rows": ready_count,
                "cannot_confirm_rows": len(observations) - ready_count,
                "coverage_ratio": round(ready_count / len(observations), 6) if observations else 0.0,
            },
            "rows": product_rows,
            "recommendation_summary": recommendation_summary(recommendations),
            "source_receipts": source_receipts,
            "generated_at": generated,
            "historical_system_available": False,
            "historical_system_note": (
                "当前日目标09:40之后生成；仅证明请求时点可对齐，不证明系统在09:40已消费；研究建议仍受 RESEARCH_ONLY 边界约束。"
                if current_day_rows
                else "自动研究结果是目标日请求后的历史回溯；不回填旧人工日期 JSON，也不宣称当时已在线消费。"
            ),
            **FOUR_FLAGS,
            "safety": dict(FOUR_FLAGS),
        }
        if event_batch is not None:
            return ManagerResearchJobService._attach_catalyst_to_product(product, event_batch, observations)
        return product
