"""Read-only decision compression for Manager research-attention cards.

The module deliberately does *not* calculate a trading signal.  It only turns
already-admitted evidence into a deterministic research state so the Manager UI
can answer four questions quickly:

1. is there fresh company-specific evidence?
2. is there an already-owned market confirmation lane?
3. what should be checked next?
4. what would invalidate this research priority?

No thresholds, quotes, ranks, Stage results, BUY gates or orders are created or
mutated here.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

DECISION_SCHEMA = "v4.manager_research.attention_decision.v1"
DECISION_VERSION = "20260927.evidence-state-triage.proposal-v1"

_GROUP_ORDER = {
    "COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION": 0,
    "COMPANY_EVIDENCE_WAIT_MARKET": 1,
    "MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE": 2,
    "CONTEXT_ONLY": 3,
    "INSUFFICIENT": 4,
}

_GROUP_LABEL = {
    "COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION": "公司证据 + 市场确认",
    "COMPANY_EVIDENCE_WAIT_MARKET": "公司证据，待市场确认",
    "MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE": "市场结构先行，缺公司级原因",
    "CONTEXT_ONLY": "产业/海外背景",
    "INSUFFICIENT": "证据不足",
}

_LANE_LABELS = {
    "OFFICIAL_ANNOUNCEMENT": "公司公告/官方披露",
    "COMPANY_MATERIAL": "公司特异材料",
    "STRICT_NEAR_SCREEN": "既有量价筛选",
    "TREND_CONTINUATION": "趋势延续",
    "US_INDIVIDUAL_MAPPING": "已核美股个股映射",
    "US_INDUSTRY_MAPPING": "已核美股行业映射",
}


def _as_lanes(card: Mapping[str, Any]) -> set[str]:
    raw = card.get("qualified_lanes")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return set()
    return {str(item) for item in raw if isinstance(item, str) and item}


def _official_strength(card: Mapping[str, Any]) -> int:
    """3=parsed official body, 2=directory-only official, 0=none.

    We inspect only evidence already admitted upstream.  This function never
    upgrades an unverified source into an official announcement.
    """
    if "OFFICIAL_ANNOUNCEMENT" not in _as_lanes(card):
        return 0
    evidence = card.get("evidence")
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)):
        for row in evidence:
            if (
                isinstance(row, Mapping)
                and row.get("evidence_lane") == "OFFICIAL_ANNOUNCEMENT"
                and row.get("evidence_class") == "OFFICIAL_PARSED_DOCUMENT"
                and row.get("body_status") == "BODY_PARSED"
            ):
                return 3
    return 2


def company_evidence_strength(card: Mapping[str, Any]) -> int:
    lanes = _as_lanes(card)
    official = _official_strength(card)
    if official:
        return official
    if "COMPANY_MATERIAL" in lanes:
        return 1
    return 0


def market_confirmation_strength(card: Mapping[str, Any]) -> int:
    classification = str(card.get("screen_classification") or "")
    if classification == "STRICT_REBOUND":
        return 3
    if classification == "NEAR_CONDITION":
        return 2
    if "TREND_CONTINUATION" in _as_lanes(card):
        return 1
    return 0


def context_strength(card: Mapping[str, Any]) -> int:
    lanes = _as_lanes(card)
    if "US_INDIVIDUAL_MAPPING" in lanes:
        return 2
    if "US_INDUSTRY_MAPPING" in lanes:
        return 1
    return 0


def _state(card: Mapping[str, Any]) -> str:
    company = company_evidence_strength(card)
    market = market_confirmation_strength(card)
    context = context_strength(card)
    if company and market:
        return "COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION"
    if company:
        return "COMPANY_EVIDENCE_WAIT_MARKET"
    if market:
        return "MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE"
    if context:
        return "CONTEXT_ONLY"
    return "INSUFFICIENT"


def _summary(state: str) -> str:
    if state == "COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION":
        return "已有截止时点内的公司证据，且现有量价/趋势通道给出确认；优先核事件兑现与市场确认能否持续。"
    if state == "COMPANY_EVIDENCE_WAIT_MARKET":
        return "已有截止时点内的公司证据，但现有量价/趋势通道尚未确认；先等市场确认，不因事件本身升级为交易准入。"
    if state == "MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE":
        return "量价或趋势结构已经出现，但缺少可验证的公司级新原因；保留结构观察，同时补公司公告/材料。"
    if state == "CONTEXT_ONLY":
        return "当前只有已核产业或海外映射背景；它能解释研究方向，不能替代本公司的直接事实。"
    return "当前证据不足以形成更高研究优先级；缺什么就显示什么，不以0或当前时间补写。"


def _next_check(state: str) -> str:
    if state == "COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION":
        return "复核同一事件的后续原文/兑现节点，并用既有市场通道确认量价或趋势没有转弱。"
    if state == "COMPANY_EVIDENCE_WAIT_MARKET":
        return "等待既有 strict/near/趋势通道出现同窗确认；盘前不能用盘后或未来行情回填。"
    if state == "MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE":
        return "补查 research cutoff 前的公司公告或公司特异材料；补不到时维持‘市场结构观察’，不升级成公司催化。"
    if state == "CONTEXT_ONLY":
        return "继续核主体关系、业务传导与时点；只有出现公司级证据或市场确认后才进入更高研究组。"
    return "先补足来源、主体、时点或量价证据；在缺件未闭合前维持待核。"


def _invalidation(state: str) -> str:
    if state == "COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION":
        return "若公司证据被更正/主体不匹配/超出当时可见窗口，或后续同口径市场确认失效，则降级研究优先级。"
    if state == "COMPANY_EVIDENCE_WAIT_MARKET":
        return "若公司证据被更正、主体关系失效或证明当时不可见，则撤销该公司证据优先级。"
    if state == "MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE":
        return "若后续同口径 screen/趋势不再成立且仍无公司级证据，则撤销该结构优先级。"
    if state == "CONTEXT_ONLY":
        return "若映射关系、lineage 或业务传导被否定，则撤销该背景关联。"
    return "任何关键来源或身份校验失败都保持/降为待核，不自动补齐。"


def readable_reasons(card: Mapping[str, Any]) -> list[str]:
    lanes = _as_lanes(card)
    ordered = (
        "OFFICIAL_ANNOUNCEMENT",
        "COMPANY_MATERIAL",
        "STRICT_NEAR_SCREEN",
        "TREND_CONTINUATION",
        "US_INDIVIDUAL_MAPPING",
        "US_INDUSTRY_MAPPING",
    )
    out = [_LANE_LABELS[lane] for lane in ordered if lane in lanes]
    return out


def enrich_attention_card(card: Mapping[str, Any]) -> dict[str, Any]:
    """Return optional decision fields without modifying the input card."""
    state = _state(card)
    company = company_evidence_strength(card)
    market = market_confirmation_strength(card)
    context = context_strength(card)
    score = int(card.get("research_attention_score") or 0)
    lane_count = int(card.get("qualified_lane_count") or 0)
    return {
        "schema_version": DECISION_SCHEMA,
        "version": DECISION_VERSION,
        "status": "PROPOSAL_ONLY",
        "state": state,
        "group_label": _GROUP_LABEL[state],
        "group_order": _GROUP_ORDER[state],
        "summary": _summary(state),
        "next_check": _next_check(state),
        "invalidation": _invalidation(state),
        "why_now_readable": readable_reasons(card),
        "company_evidence_strength": company,
        "market_confirmation_strength": market,
        "context_strength": context,
        # This key is inspectable and deterministic.  Existing score remains a
        # tie-breaker; it is no longer treated as the primary evidence class.
        "research_priority_key": [
            _GROUP_ORDER[state],
            -score,
            -company,
            -market,
            -context,
            -lane_count,
        ],
        "formal_rank_writeback": False,
        "stage_writeback": False,
        "buy_gate_writeback": False,
    }


def attention_sort_key(card: Mapping[str, Any]) -> tuple[int, int, int, int, int, int]:
    decision = card.get("decision")
    if not isinstance(decision, Mapping):
        decision = enrich_attention_card(card)
    key = decision.get("research_priority_key")
    if not isinstance(key, Sequence) or isinstance(key, (str, bytes)) or len(key) != 6:
        return (99, 0, 0, 0, 0, 0)
    try:
        return tuple(int(value) for value in key)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return (99, 0, 0, 0, 0, 0)


__all__ = [
    "DECISION_SCHEMA",
    "DECISION_VERSION",
    "attention_sort_key",
    "company_evidence_strength",
    "context_strength",
    "enrich_attention_card",
    "market_confirmation_strength",
    "readable_reasons",
]
