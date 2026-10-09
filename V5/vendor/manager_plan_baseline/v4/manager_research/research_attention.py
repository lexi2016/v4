"""Deterministic evidence-first research priority for the Manager workbench.

This is a pure read-only projection.  It does not select securities, mutate the
existing strict/near screen, overwrite the Manager focus rank, or change Stage,
BUY or orders.  Its only job is to make already-owned evidence easier to triage.
"""
from __future__ import annotations

from copy import deepcopy
import re
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
        # decision.why_now_readable is the exact lane-label contract. Direction,
        # risk and source explanations remain in research_relationships for UI.
    return card


def _screen_source_refs_are_valid(row: Mapping[str, Any]) -> bool:
    refs = row.get("source_refs")
    if not isinstance(refs, list) or len(refs) < 2:
        return False
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        if not isinstance(ref, Mapping):
            return False
        if not all(isinstance(ref.get(key), str) and ref.get(key) for key in
                   ("owner", "payload_path", "manifest_path")):
            return False
        payload_sha = ref.get("payload_sha256")
        manifest_sha = ref.get("manifest_sha256")
        if (not isinstance(payload_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", payload_sha)
                or not isinstance(manifest_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_sha)):
            return False
        seen.add((payload_sha, manifest_sha))
    return len(seen) >= 2


def build_research_selection_ledger(
    screen: Mapping[str, Any] | None,
    cards: Sequence[Mapping[str, Any]],
    target_trade_date: str,
) -> dict[str, Any]:
    """Account for every existing rebound-screen row without changing its gates.

    This ledger is a retrospective research view.  It deliberately does not
    reuse the source-session Connect label as target-day eligibility and does
    not feed the formal selection, focus, Stage, BUY, or order paths.
    """
    unknown_coverage = {
        "input_row_count": None,
        "accounted_input_row_count": None,
        "unique_decision_count": None,
        "selected_count": None,
        "near_watch_count": None,
        "excluded_count": None,
        "unresolved_count": None,
        "source_group_counts": {"strict": None, "near": None, "pending": None, "excluded": None, "screen_unresolved": None},
    }
    group_keys = ("strict", "near", "pending", "excluded", "screen_unresolved")

    def unavailable_ledger(source_status: Any = None, source_gaps: Sequence[Any] = ()) -> dict[str, Any]:
        return {
            "schema_version": "v4.manager_research.selection_ledger.v1",
            "status": "CANNOT_CONFIRM", "target_trade_date": target_trade_date,
            "source_date": None, "source_input_identity": None, "decision_identity": digest([]),
            "source_rule_version": None, "decisions": [], "coverage": unknown_coverage,
            "source_status": source_status,
            "gaps": sorted({"REBOUND_SCREEN_INPUT_NOT_AVAILABLE",
                *(gap for gap in source_gaps if isinstance(gap, str) and gap)}), "universe_exhaustive": False,
            "formal_selection_input": False, "target_connect_eligibility": "UNCHANGED_SEPARATE_FORMAL_SELECTION",
            "as_of_claim": "NONE_RETROSPECTIVE_RESEARCH", **FLAGS,
        }

    if not isinstance(screen, Mapping):
        return unavailable_ledger()

    # A failed empty producer response contains no observed universe. Keep all
    # counts unknown until the original screen identity and ready state exist.
    screen_identity = screen.get("input_identity")
    screen_ready = (screen.get("schema_version") == "v4.manager_research.rebound_v3_screen.v1"
        and screen.get("status") in {"READY", "READY_WITH_GAPS"}
        and screen.get("main_screen_ready") is True
        and isinstance(screen_identity, str) and re.fullmatch(r"[0-9a-f]{64}", screen_identity))
    has_observed_rows = any(isinstance(screen.get(group), list) and bool(screen.get(group)) for group in group_keys)
    if not screen_ready and not has_observed_rows:
        return unavailable_ledger(screen.get("status"), screen.get("gaps") or [])

    source_date_raw = screen.get("verified_session")
    source_date = str(source_date_raw) if source_date_raw is not None else None
    source_identity = screen.get("input_identity")
    source_rule = screen.get("rule_version")
    source_status = screen.get("status")
    global_gaps: list[str] = []
    if screen.get("schema_version") != "v4.manager_research.rebound_v3_screen.v1":
        global_gaps.append("REBOUND_SCREEN_SCHEMA_UNVERIFIED")
    if source_status not in {"READY", "READY_WITH_GAPS"} or screen.get("main_screen_ready") is not True:
        global_gaps.append("REBOUND_SCREEN_NOT_READY")
    if screen.get("target_trade_date") != target_trade_date:
        global_gaps.append("REBOUND_SCREEN_TARGET_DATE_MISMATCH")
    if not isinstance(source_date, str) or not re.fullmatch(r"\d{8}", source_date) or source_date > target_trade_date:
        global_gaps.append("REBOUND_SCREEN_SOURCE_SESSION_UNVERIFIED")
    if not isinstance(source_identity, str) or not re.fullmatch(r"[0-9a-f]{64}", source_identity):
        global_gaps.append("REBOUND_SCREEN_INPUT_IDENTITY_UNVERIFIED")
    if not isinstance(source_rule, str) or not source_rule:
        global_gaps.append("REBOUND_SCREEN_RULE_IDENTITY_UNVERIFIED")

    raw_groups: dict[str, list[Mapping[str, Any]]] = {}
    for group in group_keys:
        raw = screen.get(group)
        if not isinstance(raw, list) or any(not isinstance(row, Mapping) for row in raw):
            global_gaps.append("REBOUND_SCREEN_GROUP_INVALID:" + group)
            raw_groups[group] = []
        else:
            raw_groups[group] = list(raw)
    input_count = sum(len(rows) for rows in raw_groups.values())
    coverage = screen.get("coverage") if isinstance(screen.get("coverage"), Mapping) else {}
    declared_count = coverage.get("input_candidate_count")
    if type(declared_count) is not int or declared_count != input_count:
        global_gaps.append("REBOUND_SCREEN_INPUT_COUNT_MISMATCH")
    history_complete = coverage.get("history_complete_count")
    history_pending = coverage.get("history_pending_count")
    if (type(history_complete) is not int or type(history_pending) is not int
            or history_complete + history_pending != input_count):
        global_gaps.append("REBOUND_SCREEN_HISTORY_COVERAGE_MISMATCH")
    if coverage.get("row_accounted_count") != input_count:
        global_gaps.append("REBOUND_SCREEN_ROW_ACCOUNTING_MISMATCH")
    for key, field in (("strict", "strict_count"), ("near", "near_candidate_count"),
                       ("pending", "history_pending_count"), ("excluded", "excluded_count"),
                       ("screen_unresolved", "screen_unresolved_count")):
        if type(coverage.get(field)) is not int or coverage.get(field) != len(raw_groups[key]):
            global_gaps.append("REBOUND_SCREEN_GROUP_COUNT_MISMATCH:" + key)
    if (type(coverage.get("selected_count")) is not int
            or coverage.get("selected_count") != len(raw_groups["strict"]) + len(raw_groups["near"])):
        global_gaps.append("REBOUND_SCREEN_SELECTED_COUNT_MISMATCH")
    cards_input = screen.get("cards")
    if not isinstance(cards_input, list) or cards_input != [*raw_groups["strict"], *raw_groups["near"]]:
        global_gaps.append("REBOUND_SCREEN_CARDS_LIST_MISMATCH")
    source_contract_gaps = list(global_gaps)
    source_gaps = screen.get("gaps")
    if isinstance(source_gaps, list):
        global_gaps.extend(gap for gap in source_gaps if isinstance(gap, str) and gap)

    priority_by_symbol: dict[str, dict[str, Any]] = {}
    for rank, card in enumerate(cards, 1):
        symbol = card.get("symbol")
        if not isinstance(symbol, str) or not re.fullmatch(r"HK\.(?!00000)\d{5}", symbol):
            continue
        decision = card.get("decision")
        if not isinstance(decision, Mapping):
            continue
        priority_by_symbol[symbol] = {
            "priority_rank": rank,
            "research_attention_score": card.get("research_attention_score"),
            "research_attention_band": card.get("research_attention_band"),
            "decision": deepcopy(dict(decision)),
            "ordering_basis": "EVIDENCE_STATE_THEN_EXISTING_PROPOSAL_SCORE_THEN_PIT_FRESHNESS",
            "status": "PROPOSAL_ONLY",
        }

    occurrences: dict[str, list[tuple[str, int, Mapping[str, Any]]]] = {}
    invalid_symbols: list[tuple[str, int, Mapping[str, Any]]] = []
    row_index = 0
    for group in group_keys:
        for raw in raw_groups[group]:
            row_index += 1
            symbol = raw.get("code")
            entry = (group, row_index, raw)
            if not isinstance(symbol, str) or not re.fullmatch(r"HK\.(?!00000)\d{5}", symbol):
                invalid_symbols.append(entry)
            else:
                occurrences.setdefault(symbol, []).append(entry)

    def source_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
        keys = (
            "classification", "history_status", "history_unknown_reasons", "target_monday", "verified_session",
            "prior60_session_count", "previous5_session_count", "prior60_session_high", "close",
            "oversold_cutoff_80pct_prior60_high", "oversold_flag", "volume_ratio_5d",
            "volume_flag_5d_ge_1_5", "strict_two_gate_oversold_5dvolume", "near_two_gate_one_missing",
            "near_failed_gate", "near_failed_value", "near_gate_value", "near_gate_gap_ratio",
            "screen_decision", "exclusion_reason_code",
        )
        return {key: deepcopy(row.get(key)) for key in keys if key in row}

    def make_decision(symbol: str | None, entries: list[tuple[str, int, Mapping[str, Any]]]) -> dict[str, Any]:
        first_group, first_index, row = entries[0]
        refs_ok = all(_screen_source_refs_are_valid(raw) for _, _, raw in entries)
        row_dates_ok = all(
            str(raw.get("target_monday") or "") == target_trade_date
            and str(raw.get("verified_session") or "") == (source_date or "")
            and raw.get("qualification_status") == "RESEARCH_ONLY_CANDIDATE"
            for _, _, raw in entries
        )
        decision_status = "UNRESOLVED"
        reason_code = "REBOUND_SCREEN_SOURCE_CONTRACT_UNVERIFIED"
        reason = "来源身份、时间或逐行字段不足；保持未决。"
        priority = None
        if len(entries) > 1:
            reason_code = "DUPLICATE_REBOUND_SCREEN_SYMBOL"
            reason = f"原筛选输入中该代码出现 {len(entries)} 次，不能静默去重后授予研究选择。"
            global_gaps.append("REBOUND_SCREEN_DUPLICATE_SYMBOL:" + str(symbol))
        elif source_contract_gaps:
            reason_code = source_contract_gaps[0]
            reason = "筛选整体身份或计数契约未通过；所有受影响行保持未决。"
        elif not row_dates_ok:
            reason_code = "REBOUND_SCREEN_ROW_DATE_OR_QUALIFICATION_MISMATCH"
        elif not refs_ok:
            reason_code = "REBOUND_SCREEN_ROW_SOURCE_REFS_UNVERIFIED"
            reason = "该行缺少两份可核验的原owner payload/manifest SHA引用；保持未决。"
        elif first_group == "strict":
            gates_pass = (row.get("history_status") == "KNOWN"
                and row.get("strict_two_gate_oversold_5dvolume") is True
                and row.get("oversold_flag") is True
                and row.get("volume_flag_5d_ge_1_5") is True
                and row.get("classification") == "STRICT_REBOUND")
            priority = priority_by_symbol.get(str(symbol))
            if gates_pass and priority:
                decision_status = "SELECTED"
                reason_code = "ORIGINAL_STRICT_TWO_GATE_PASSED"
                reason = str(row.get("reason_for_group") or "原strict两项准入门均通过；仅保留研究候选。")
            elif gates_pass:
                reason_code = "EXISTING_RESEARCH_PRIORITY_UNAVAILABLE"
                reason = "原strict两项准入门均通过，但当前PIT研究优先级不可得；暂列未决。"
            else:
                reason_code = "STRICT_SCREEN_ROW_RULE_CONTRADICTION"
                reason = "该行位于strict输入组，但原筛选状态与组别不一致；暂列未决。"
        elif first_group == "near":
            gates_valid = (row.get("history_status") == "KNOWN"
                and row.get("near_two_gate_one_missing") is True
                and row.get("strict_two_gate_oversold_5dvolume") is False
                and row.get("classification") == "NEAR_CONDITION"
                and row.get("near_failed_gate") in {"volume_5d_ratio", "oversold_close_le_80pct_prior60_high"}
                and type(row.get("near_failed_value")) in (int, float)
                and type(row.get("near_gate_value")) in (int, float))
            priority = priority_by_symbol.get(str(symbol))
            if gates_valid and priority:
                decision_status = "NEAR_WATCH"
                reason_code = "ORIGINAL_NEAR_ONE_GATE_MISSED"
                reason = str(row.get("reason_for_group") or "保留原near观察；逐项门槛差异见筛选字段。")
            elif gates_valid:
                reason_code = "EXISTING_RESEARCH_PRIORITY_UNAVAILABLE"
                reason = "原near门槛及差异可核，但当前PIT研究优先级不可得；暂列未决。"
            else:
                reason_code = "NEAR_SCREEN_ROW_RULE_CONTRADICTION"
                reason = "该行位于near输入组，但原门槛状态与组别不一致；暂列未决。"
        elif first_group == "pending":
            if row.get("history_status") == "KNOWN":
                reason_code = "PENDING_SCREEN_ROW_CONTRADICTION"
                reason = "原输入将该行列为待核，但历史状态标为KNOWN；需复核源产物。"
            else:
                reason_code = "ORIGINAL_SCREEN_HISTORY_PENDING"
                reason = str(row.get("history_unknown_reasons") or "原筛选历史字段不完整；保持未决。")
        elif first_group == "excluded":
            if (row.get("history_status") == "KNOWN"
                    and row.get("screen_decision") == "EXCLUDED"
                    and row.get("oversold_flag") is False
                    and row.get("volume_flag_5d_ge_1_5") is False
                    and isinstance(row.get("exclusion_reason_code"), str)
                    and isinstance(row.get("reason_for_exclusion"), str)):
                decision_status = "EXCLUDED"
                reason_code = str(row["exclusion_reason_code"])
                reason = str(row["reason_for_exclusion"])
            else:
                reason_code = "EXCLUSION_ROW_RULE_CONTRADICTION"
                reason = "原排除组缺少完整历史、双门未通过或逐股理由；保持未决。"
        else:
            reason_code = str(row.get("exclusion_reason_code") or "ORIGINAL_SCREEN_ROW_UNRESOLVED")
            reason = str(row.get("reason_for_exclusion") or row.get("history_unknown_reasons")
                         or "原screen未能给出可验证的选入/排除判定；保持未决。")

        item = {
            "symbol": symbol,
            "name": str(row.get("name") or symbol or "未识别代码"),
            "decision_status": decision_status,
            "source_group": first_group if len(entries) == 1 else "duplicate",
            "source_row_count": len(entries),
            "source_row_indexes": [index for _, index, _ in entries],
            "target_trade_date": target_trade_date,
            "source_date": source_date,
            "source_input_identity": source_identity,
            "source_rule_version": source_rule,
            "decision_reason_code": reason_code,
            "decision_reason": reason,
            "source_metrics": source_metrics(row),
            "source_refs": deepcopy(row.get("source_refs") or []),
            "research_priority": priority if decision_status in {"SELECTED", "NEAR_WATCH"} else None,
            "target_connect_eligibility": "UNCHANGED_SEPARATE_FORMAL_SELECTION",
            "as_of_claim": "NONE_RETROSPECTIVE_RESEARCH",
            **FLAGS,
        }
        if len(entries) > 1:
            item["duplicate_source_rows"] = [
                {"source_group": group, "source_row_index": index,
                 "source_metrics": source_metrics(raw), "source_refs": deepcopy(raw.get("source_refs") or [])}
                for group, index, raw in entries
            ]
        return item

    decisions = [make_decision(symbol, entries) for symbol, entries in occurrences.items()]
    for group, index, row in invalid_symbols:
        decisions.append(make_decision(None, [(group, index, row)]))
        decisions[-1]["decision_status"] = "UNRESOLVED"
        decisions[-1]["research_priority"] = None
        decisions[-1]["decision_reason_code"] = "REBOUND_SCREEN_SYMBOL_INVALID"
        decisions[-1]["decision_reason"] = "原筛选行缺少规范港股代码；不能形成逐股选择。"
        global_gaps.append("REBOUND_SCREEN_INVALID_SYMBOL_ROW")

    group_order = {"strict": 0, "near": 1, "pending": 2, "excluded": 3, "screen_unresolved": 4, "duplicate": 5}
    decisions.sort(key=lambda item: (
        group_order.get(str(item.get("source_group")), 6),
        int((item.get("research_priority") or {}).get("priority_rank") or 10**9),
        str(item.get("symbol") or ""),
        min(item.get("source_row_indexes") or [10**9]),
    ))
    accounted_rows = sum(int(item.get("source_row_count") or 0) for item in decisions)
    counts = {
        "input_row_count": input_count,
        "accounted_input_row_count": accounted_rows,
        "unique_decision_count": len(decisions),
        "selected_count": sum(item["decision_status"] == "SELECTED" for item in decisions),
        "near_watch_count": sum(item["decision_status"] == "NEAR_WATCH" for item in decisions),
        "excluded_count": sum(item["decision_status"] == "EXCLUDED" for item in decisions),
        "unresolved_count": sum(item["decision_status"] == "UNRESOLVED" for item in decisions),
        "source_group_counts": {key: len(raw_groups[key]) for key in group_keys},
    }
    if accounted_rows != input_count:
        global_gaps.append("REBOUND_SCREEN_LEDGER_ACCOUNTING_MISMATCH")
    if counts["selected_count"] + counts["near_watch_count"] + counts["excluded_count"] + counts["unresolved_count"] != len(decisions):
        global_gaps.append("REBOUND_SCREEN_DECISION_COUNTS_MISMATCH")
    status = ("CANNOT_CONFIRM" if not input_count or source_contract_gaps else
              "READY_WITH_GAPS" if global_gaps or counts["unresolved_count"] else "READY")
    return {
        "schema_version": "v4.manager_research.selection_ledger.v1",
        "status": status,
        "target_trade_date": target_trade_date,
        "source_date": source_date,
        "source_input_identity": source_identity,
        "source_rule_version": source_rule,
        "source_status": source_status,
        "decision_identity": digest({"target_trade_date": target_trade_date,
            "source_date": source_date, "source_input_identity": source_identity,
            "source_rule_version": source_rule, "decisions": decisions, "coverage": counts,
            "gaps": sorted(set(global_gaps))}),
        "decisions": decisions,
        "coverage": counts,
        "gaps": sorted(set(global_gaps)),
        "universe_exhaustive": False,
        "formal_selection_input": False,
        "target_connect_eligibility": "UNCHANGED_SEPARATE_FORMAL_SELECTION",
        "as_of_claim": "NONE_RETROSPECTIVE_RESEARCH",
        **FLAGS,
    }

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
    research_selection = build_research_selection_ledger(market_screen, cards, target_trade_date)
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
        "research_selection_digest": research_selection["decision_identity"],
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
        "research_selection": research_selection,
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
    "build_research_selection_ledger",
]
