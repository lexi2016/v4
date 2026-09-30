"""Deterministic evidence-first research priority for the Manager workbench.

This is a pure read-only projection.  It does not select securities, mutate the
existing strict/near screen, overwrite the Manager focus rank, or change Stage,
BUY or orders.  Its only job is to make already-owned evidence easier to triage.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from .workspace_projection import FLAGS, digest, timestamp
from .research_evidence import US_LABEL_TO_MANAGER_THEMES, collect_attention_evidence
from .attention_decision import attention_sort_key, enrich_attention_card

SCHEMA = "v4.manager_research.research_attention.v1"
CONFIG_VERSION = "20260927.research-attention.evidence-state-v2"


@dataclass(frozen=True)
class ResearchAttentionConfig:
    official_parsed: int = 42
    official_directory_only: int = 18
    company_specific_material: int = 24
    verified_us_individual: int = 24
    verified_us_industry: int = 18
    strict_screen: int = 10
    near_screen: int = 6
    trend_continuation: int = 8
    cross_lane_bonus: int = 10
    immediate_threshold: int = 55
    high_threshold: int = 35
    normal_threshold: int = 20
    max_score: int = 100
    max_evidence_age_hours: int = 120
    display_limit: int = 30

    def as_dict(self) -> dict[str, Any]:
        row = dict(self.__dict__)
        row.update(version=CONFIG_VERSION, status="PROPOSAL_ONLY")
        return row


DEFAULT_CONFIG = ResearchAttentionConfig()


def _freshest_for_keys(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> str | None:
    values: list[tuple[datetime, str]] = []
    for row in rows:
        for key in keys:
            parsed = timestamp(row.get(key))
            if parsed is not None:
                values.append((parsed, parsed.isoformat()))
                break
    return max(values)[1] if values else None


def _freshness_clocks(rows: Sequence[Mapping[str, Any]]) -> dict[str, str | None]:
    # Publication/event time and system acquisition time answer different PIT
    # questions.  Never let a late retrieval timestamp masquerade as a late
    # publication, or vice versa.  Keep the legacy aggregate only for backward
    # compatible display/sorting diagnostics.
    published = _freshest_for_keys(rows, ("published_at", "issuer_published_at"))
    acquired = _freshest_for_keys(rows, (
        "acquired_at", "available_at", "retrieved_at", "first_seen_at",
        "collected_at", "archive_recorded_at", "captured_at", "us_captured_at",
    ))
    aggregate_values = [timestamp(value) for value in (published, acquired) if value]
    aggregate = max(aggregate_values).isoformat() if aggregate_values else None
    return {
        "freshest_published_at": published,
        "freshest_acquired_at": acquired,
        "freshest_evidence_at": aggregate,
    }


def _band(score: int, config: ResearchAttentionConfig) -> str:
    if score >= config.immediate_threshold:
        return "IMMEDIATE_RESEARCH"
    if score >= config.high_threshold:
        return "HIGH_RESEARCH"
    if score >= config.normal_threshold:
        return "NORMAL_RESEARCH"
    if score > 0:
        return "BACKGROUND_RESEARCH"
    return "UNVERIFIED"


def _rejected_raw_mover_count(raw_rows: Any, diagnostics: Any) -> int:
    """Count rejected source movers from one-row-per-mover diagnostics.

    This is the independently verified R3 business-completion fix and must be
    preserved while R5 changes only the research triage order.
    """
    raw_count = len(raw_rows) if isinstance(raw_rows, list) else 0
    accepted_count = sum(
        1 for row in diagnostics
        if isinstance(row, Mapping)
        and type(row.get("accepted_mapping_count")) is int
        and row["accepted_mapping_count"] > 0
    ) if isinstance(diagnostics, list) else 0
    return max(0, raw_count - accepted_count)


def _score_card(
    *, symbol: str, screen: Mapping[str, Any] | None, stock: Mapping[str, Any] | None,
    official: Sequence[Mapping[str, Any]], company: Sequence[Mapping[str, Any]],
    us_industry: Sequence[Mapping[str, Any]], us_individual: Sequence[Mapping[str, Any]],
    trend: Mapping[str, Any] | None, config: ResearchAttentionConfig,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    lane_points: dict[str, int] = {}
    if official:
        evidence.extend(deepcopy(list(official)))
        parsed = any(row.get("body_status") == "BODY_PARSED" for row in official)
        lane_points["OFFICIAL_ANNOUNCEMENT"] = config.official_parsed if parsed else config.official_directory_only
    if company:
        evidence.extend(deepcopy(list(company)))
        lane_points["COMPANY_MATERIAL"] = config.company_specific_material
    if us_industry:
        evidence.extend(deepcopy(list(us_industry)))
        lane_points["US_INDUSTRY_MAPPING"] = config.verified_us_industry
    if us_individual:
        evidence.extend(deepcopy(list(us_individual)))
        lane_points["US_INDIVIDUAL_MAPPING"] = config.verified_us_individual
    if trend:
        evidence.append(deepcopy(dict(trend)))
        lane_points["TREND_CONTINUATION"] = config.trend_continuation
    classification = str((screen or {}).get("classification") or "")
    if classification == "STRICT_REBOUND":
        lane_points["STRICT_NEAR_SCREEN"] = config.strict_screen
    elif classification == "NEAR_CONDITION":
        lane_points["STRICT_NEAR_SCREEN"] = config.near_screen
    qualified_lanes = sorted(lane_points)
    score_components = [{"component": lane, "points": lane_points[lane]} for lane in qualified_lanes]
    if len(qualified_lanes) >= 2:
        score_components.append({"component": "CROSS_LANE_BONUS", "points": config.cross_lane_bonus})
    raw_score = sum(int(row["points"]) for row in score_components)
    score = min(config.max_score, raw_score)
    if score != raw_score:
        score_components.append({"component": "MAX_SCORE_CAP", "points": score - raw_score})
    issuer_names={str(r.get('name')) for r in company if r.get('symbol')==symbol and r.get('name')}
    issuer_names.update(str(r['hk_relation']['name']) for r in [*us_industry,*us_individual]
                        if isinstance(r.get('hk_relation'),Mapping) and r['hk_relation'].get('symbol')==symbol and r['hk_relation'].get('name'))
    native_name=next(iter(issuer_names)) if len(issuer_names)==1 else None
    name = str((screen or {}).get("name") or (stock or {}).get("name") or native_name or symbol)
    screen_rank = (screen or {}).get("research_priority_rank")
    why_now = [f"{row['component']}:{row['points']}" for row in score_components if int(row["points"]) > 0]
    missing: list[str] = []
    if not official:
        missing.append("NO_CUTOFF_BOUND_OFFICIAL_ANNOUNCEMENT")
    if not us_industry and not us_individual:
        missing.append("NO_VERIFIED_US_TO_HK_MAPPING")
    if not company:
        missing.append("NO_FRESH_COMPANY_SPECIFIC_MATERIAL")
    clocks = _freshness_clocks(evidence)
    card = {
        "symbol": symbol,
        "name": name,
        "research_attention_score": score,
        "research_attention_band": _band(score, config),
        "qualified_lane_count": len(qualified_lanes),
        "qualified_lanes": qualified_lanes,
        "why_now": why_now,
        "score_components": score_components,
        "score_reconciled": sum(int(row["points"]) for row in score_components) == score,
        "missing": missing,
        "screen_classification": classification or None,
        "original_screen_rank": screen_rank if isinstance(screen_rank, int) else None,
        "screen_reason": (screen or {}).get("reason_for_group"),
        **clocks,
        "evidence": evidence,
        "existing_focus": bool((stock or {}).get("is_focus", False)),
        "research_only": True,
        **FLAGS,
    }
    card["decision"] = enrich_attention_card(card)
    if us_industry or us_individual:
        relationships=[]
        for evidence_row in [*us_industry,*us_individual]:
            relation=evidence_row['hk_relation']; mover=evidence_row['us_mover']
            relationships.append(dict(symbol=symbol,name=name,lane=evidence_row['evidence_lane'],
                us_signal=mover.get('symbol') or mover.get('label'),
                direction=relation.get('direction','UNCONFIRMED_NOT_BENEFICIARY_ASSERTION'),
                issuer_cautions=deepcopy(relation.get('issuer_cautions') or []),
                evidence_quote=relation.get('issuer_quote') or relation.get('evidence_quote') or relation.get('relation_quote'),
                published_at=relation.get('issuer_published_at') or relation.get('published_at'),
                acquired_at=evidence_row.get('available_at'),
                source_refs=[deepcopy(evidence_row.get('source_identity')), *deepcopy(relation.get('source_refs') or [])],
                target_connect_eligibility=relation.get('connect_eligibility','NOT_CHECKED'),
                observation_condition='先核双来源与本公司业务；量价及Stage条件仍由原通道决定，US上涨不等于HK可买。',
                invalidation='主体/业务关系被更正、来源或取得时间失效时撤销；不得用事后取得材料补回旧计划。'))
        card['research_relationships']=relationships
        directions=sorted({r['direction'] for r in relationships})
        card['decision']['why_now_readable'].append('美股关联原文方向：'+ ' / '.join(directions)+'；关联不等于受益或买入。')
    return card


def build_research_attention(
    target_trade_date: str,
    *,
    context: Mapping[str, Any],
    market_screen: Mapping[str, Any] | None,
    stocks: Sequence[Mapping[str, Any]] | None,
    material_cards: Sequence[Mapping[str, Any]] | None,
    themes: Sequence[Mapping[str, Any]] | None,
    announcement_observation: Mapping[str, Any] | None,
    us_market: Mapping[str, Any] | None,
    config: ResearchAttentionConfig = DEFAULT_CONFIG,
) -> dict[str, Any]:
    cutoff = timestamp(context.get("research_cutoff"))
    configured_start = cutoff - timedelta(hours=config.max_evidence_age_hours) if cutoff is not None else None
    context_start = timestamp(context.get("focus_window_start"))
    freshness_start = max(value for value in (configured_start, context_start) if value is not None) if (configured_start is not None or context_start is not None) else None
    evidence = collect_attention_evidence(
        market_screen=market_screen, stocks=stocks, material_cards=material_cards,
        themes=themes, announcement_observation=announcement_observation,
        us_market=us_market, start=freshness_start, cutoff=cutoff,
    )
    symbols = evidence.symbols
    cards = [
        _score_card(
            symbol=symbol,
            screen=evidence.screen_rows.get(symbol),
            stock=evidence.stock_rows.get(symbol),
            official=evidence.official.get(symbol, []),
            company=evidence.company.get(symbol, []),
            us_industry=evidence.us_industry.get(symbol, []),
            us_individual=evidence.us_individual.get(symbol, []),
            trend=evidence.trend.get(symbol),
            config=config,
        )
        for symbol in symbols
    ]
    # Evidence state is the primary research triage key.  Existing proposal score
    # stays intact and remains an inspectable tie-breaker inside the decision key.
    # This changes only the read-only research-attention order; formal screen
    # ranks, Stage, focus, BUY and orders are never written back.
    cards.sort(key=lambda row: (
        *attention_sort_key(row),
        -(timestamp(row.get("freshest_acquired_at")).timestamp() if timestamp(row.get("freshest_acquired_at")) else float("-inf")),
        -(timestamp(row.get("freshest_published_at")).timestamp() if timestamp(row.get("freshest_published_at")) else float("-inf")),
        int(row["original_screen_rank"]) if isinstance(row.get("original_screen_rank"), int) else 10**9,
        str(row["symbol"]),
    ))
    if cutoff is None:
        cards = []
    status = "READY" if cutoff is not None else "CANNOT_CONFIRM"
    gaps: list[str] = []
    if cutoff is None:
        gaps.append("RESEARCH_ATTENTION_CUTOFF_UNVERIFIED")
    if cutoff is not None and context_start is None:
        gaps.append("FOCUS_WINDOW_START_MISSING_USED_CONFIGURED_LOOKBACK")
    if not isinstance(us_market, Mapping) or us_market.get("status") not in {"READY", "PARTIAL"}:
        gaps.append("US_MARKET_MAPPING_INPUT_NOT_READY")
    if not isinstance(announcement_observation, Mapping) or announcement_observation.get("status") in {"NOT_RUN", "FAILED", "READBACK_FAILED"}:
        gaps.append("ANNOUNCEMENT_INPUT_NOT_READY")
    identity = digest({
        "target_trade_date": target_trade_date,
        "identity_contract": "ADMITTED_CONTENT_AND_POLICY_V2_NOT_READ_CLOCK",
        "focus_window_start": context.get("focus_window_start"),
        "max_evidence_age_hours": config.max_evidence_age_hours,
        "cutoff_verified": cutoff is not None,
        "market_screen_input_identity": (market_screen or {}).get("input_identity") if isinstance(market_screen, Mapping) else None,
        "announcement_status": (announcement_observation or {}).get("status") if isinstance(announcement_observation, Mapping) else None,
        "announcement_capture_runs": (announcement_observation or {}).get("capture_runs") if isinstance(announcement_observation, Mapping) else None,
        "us_source_identity": (us_market or {}).get("source_identity") if isinstance(us_market, Mapping) else None,
        "attention_cards_digest": digest(cards),
        "config": config.as_dict(),
    })
    return {
        "schema_version": SCHEMA,
        "target_trade_date": target_trade_date,
        "research_cutoff": context.get("research_cutoff"),
        "freshness": {
            "basis": "MAX_OF_PLAN_FOCUS_WINDOW_AND_CONFIGURED_LOOKBACK",
            "focus_window_start": context.get("focus_window_start"),
            "max_evidence_age_hours": config.max_evidence_age_hours,
            "effective_start": freshness_start.isoformat() if freshness_start is not None else None,
            "status": "PROPOSAL_ONLY",
        },
        "status": status if not gaps else "READY_WITH_GAPS" if cutoff is not None else "CANNOT_CONFIRM",
        "priority_name": "EVIDENCE_STATE_RESEARCH_ATTENTION_NOT_EXISTING_FOCUS_OR_BUY_RANK",
        "ordering_basis": "EVIDENCE_STATE_THEN_EXISTING_PROPOSAL_SCORE_THEN_PIT_FRESHNESS",
        "config": config.as_dict(),
        "cards": cards,
        "coverage": {
            "candidate_union_count": len(symbols),
            "screen_candidate_count": len(evidence.screen_rows),
            "existing_workspace_stock_count": len(evidence.stock_rows),
            "official_symbol_count": len(evidence.official),
            "company_material_symbol_count": len(evidence.company),
            "us_industry_mapped_symbol_count": len(evidence.us_industry),
            "us_individual_mapped_symbol_count": len(evidence.us_individual),
            "raw_us_industry_up_count": len((us_market or {}).get("raw_industry_up") or []) if isinstance(us_market, Mapping) else 0,
            "raw_us_individual_up_count": len((us_market or {}).get("raw_individual_up") or []) if isinstance(us_market, Mapping) else 0,
            "us_mapping_rejected_industry_count": _rejected_raw_mover_count(
                (us_market or {}).get("raw_industry_up"), evidence.us_mapping_diagnostics.get("industry"),
            ) if isinstance(us_market, Mapping) else 0,
            "us_mapping_rejected_individual_count": _rejected_raw_mover_count(
                (us_market or {}).get("raw_individual_up"), evidence.us_mapping_diagnostics.get("individual"),
            ) if isinstance(us_market, Mapping) else 0,
        },
        "us_mapping_diagnostics": deepcopy(evidence.us_mapping_diagnostics),
        "gaps": sorted(set(gaps)),
        "input_identity": identity,
        "strict_near_unchanged": True,
        "existing_focus_rank_unchanged": True,
        "stage_unchanged": True,
        **FLAGS,
    }


__all__ = [
    "CONFIG_VERSION", "DEFAULT_CONFIG", "ResearchAttentionConfig",
    "SCHEMA", "US_LABEL_TO_MANAGER_THEMES", "build_research_attention",
]
