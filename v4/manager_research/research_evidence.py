"""Evidence extraction for the Manager research-attention projection.

This module is intentionally read-only.  It converts already-owned Manager,
announcement, screen, and US-lane products into evidence buckets.  It does not
score securities, fetch data, persist state, or mutate existing ranks.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Mapping, Sequence

from .workspace_projection import FLAGS, canonical_symbol, digest, timestamp
from .issuer_us_relations import material_us_relations
from .evidence_identity import (
    acquired_at as evidence_acquired_at,
    acquisition_is_within_window,
    merge_event_rows,
)

# Cross-taxonomy only.  It never maps a US mover directly to an HK security.
# A retained HK mapping additionally requires pre-existing issuer evidence.
US_LABEL_TO_MANAGER_THEMES: dict[str, tuple[str, ...]] = {
    "生物医药": ("BIOMEDICINE",),
    "石油": ("OIL",),
    "AI算力": ("AI_COMPUTE",),
    "CPO": ("CPO", "AI_COMPUTE"),
    "半导体": ("SEMICONDUCTOR", "AI_COMPUTE"),
    "存储": ("STORAGE", "AI_COMPUTE"),
    "数据中心": ("DATA_CENTER", "AI_COMPUTE"),
    "云计算": ("CLOUD", "AI_APPLICATION"),
    "机器人": ("ROBOTICS",),
    "自动驾驶": ("AUTONOMOUS_DRIVING",),
    "新能源": ("NEW_ENERGY",),
    "光伏": ("SOLAR", "NEW_ENERGY"),
    "锂电池": ("LITHIUM_BATTERY", "NEW_ENERGY"),
    "银行金融": ("BANKING",), "电网": ("GRID",), "铜/有色": ("COPPER",),
    "军工": ("DEFENSE",), "黄金": ("GOLD",), "消费": ("CONSUMER",), "卫星": ("SATELLITE",),
}


@dataclass(frozen=True)
class AttentionEvidence:
    screen_rows: dict[str, dict[str, Any]]
    stock_rows: dict[str, dict[str, Any]]
    official: dict[str, list[dict[str, Any]]]
    company: dict[str, list[dict[str, Any]]]
    us_industry: dict[str, list[dict[str, Any]]]
    us_individual: dict[str, list[dict[str, Any]]]
    trend: dict[str, dict[str, Any]]
    us_mapping_diagnostics: dict[str, Any]

    @property
    def symbols(self) -> list[str]:
        return sorted(
            set(self.screen_rows)
            | set(self.stock_rows)
            | set(self.official)
            | set(self.company)
            | set(self.us_industry)
            | set(self.us_individual)
        )


def _in_window(value: Any, start: datetime | None, cutoff: datetime | None) -> bool:
    parsed = value if isinstance(value, datetime) else timestamp(value)
    return (
        start is not None
        and cutoff is not None
        and parsed is not None
        and start <= parsed <= cutoff
    )


def _relation_acquired_at(row: Mapping[str, Any]) -> datetime | None:
    for key in (
        "issuer_available_at", "issuer_retrieved_at", "available_at",
        "retrieved_at", "first_seen_at", "collected_at",
    ):
        parsed = timestamp(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _relation_clock_valid(row, start, cutoff):
    clock_fields = (
        'issuer_available_at', 'issuer_retrieved_at', 'available_at',
        'retrieved_at', 'first_seen_at', 'collected_at', 'archive_recorded_at',
    )
    values = []
    for key in clock_fields:
        if row.get(key) in (None, ''):
            continue
        parsed = timestamp(row[key])
        if parsed is None or not _in_window(parsed, start, cutoff):
            return False
        values.append(parsed)

    # An observation clock by itself cannot stand in for the explicit source
    # availability/retrieval pair. Keep issuer-scoped and normalized pairs
    # distinct so a lone field from either contract cannot complete the other.
    has_explicit_acquisition_pair = any(
        all(row.get(key) not in (None, '') for key in pair)
        for pair in (
            ('issuer_available_at', 'issuer_retrieved_at'),
            ('available_at', 'retrieved_at'),
        )
    )
    return bool(values) and has_explicit_acquisition_pair


def _matches_theme(relation, label):
    themes=US_LABEL_TO_MANAGER_THEMES.get(label,())
    if relation.get('relation_origin')=='NATIVE_MATERIAL_PROPOSITION':
        # General AI exposure is not a semiconductor/CPO supplier relation.
        themes={'光伏':('SOLAR',),'CPO':('CPO',),'半导体':('SEMICONDUCTOR',),
                '存储':('STORAGE',),'新能源':('NEW_ENERGY','SOLAR','LITHIUM_BATTERY')}.get(label,themes)
    return relation.get('manager_theme') in themes


def _independent_native_relation(relation, source):
    if relation.get('relation_origin')!='NATIVE_MATERIAL_PROPOSITION':return False
    if not isinstance(source,Mapping) or source.get('status')!='VERIFIED':return False
    us_sha=source.get('payload_sha256')
    return (all(isinstance(source.get(k),str) and re.fullmatch(r'[0-9a-f]{64}',source[k])
                for k in ('payload_sha256','receipt_sha256','manifest_sha256'))
            and bool(relation.get('source_refs'))
            and all(ref.get('payload_sha256')!=us_sha for ref in relation.get('source_refs') or []))


def _latest_iso(*values: Any) -> str | None:
    parsed = [
        value if isinstance(value, datetime) else timestamp(value)
        for value in values
    ]
    present = [stamp for stamp in parsed if stamp is not None]
    return max(present).isoformat() if present else None


def screen_rows(screen: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(screen, Mapping):
        return result
    for key in ("strict", "near", "cards"):
        rows = screen.get(key)
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            symbol = canonical_symbol(raw.get("code"))
            if symbol and symbol not in result:
                result[symbol] = deepcopy(dict(raw))
    return result


def workspace_rows(stocks: Sequence[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in stocks or []:
        if not isinstance(raw, Mapping):
            continue
        symbol = canonical_symbol(raw.get("symbol"))
        if symbol:
            result[symbol] = deepcopy(dict(raw))
    return result


def official_evidence(
    lane: Mapping[str, Any] | None,
    start: datetime | None,
    cutoff: datetime | None,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    if not isinstance(lane, Mapping):
        return result
    for raw in lane.get("official_documents") or []:
        if not isinstance(raw, Mapping):
            continue
        symbol = canonical_symbol(raw.get("symbol"))
        if not symbol:
            continue
        identity = str(raw.get("event_id") or raw.get("document_sha256") or "")
        dedupe_key = (symbol, identity)
        published = raw.get("published_at")
        available = raw.get("available_at") or raw.get("retrieved_at")
        if not _in_window(published, start, cutoff) or not _in_window(available, start, cutoff):
            continue
        if identity and dedupe_key in seen:
            continue
        if identity:
            seen.add(dedupe_key)
        row = deepcopy(dict(raw))
        row["evidence_lane"] = "OFFICIAL_ANNOUNCEMENT"
        row["evidence_class"] = (
            "OFFICIAL_PARSED_DOCUMENT"
            if raw.get("body_status") == "BODY_PARSED"
            else "OFFICIAL_DIRECTORY_ONLY"
        )
        result.setdefault(symbol, []).append(row)
    return result


def company_evidence(
    stocks: Sequence[Mapping[str, Any]] | None,
    material_cards: Sequence[Mapping[str, Any]] | None,
    start: datetime | None,
    cutoff: datetime | None,
) -> dict[str, list[dict[str, Any]]]:
    from .announcement_materials import current_company_claim, is_mirror
    result: dict[str,list[dict[str,Any]]]={}
    combined=[e for s in stocks or [] if isinstance(s,Mapping)
              for e in s.get('evidence') or []]+list(material_cards or [])
    seen=set()
    for raw in combined:
        if (not isinstance(raw,Mapping) or raw.get('semantic_status')!='ACCEPTED'
                or not current_company_claim(raw,start,cutoff)):
            continue
        symbol=canonical_symbol(raw.get('symbol'))
        if not symbol:continue
        identity=str(raw.get('evidence_id') or raw.get('card_id') or raw.get('event_id') or digest(raw))
        key=(symbol,identity)
        if key in seen:continue
        seen.add(key)
        row=deepcopy(dict(raw));row['evidence_lane']='COMPANY_MATERIAL'
        row['evidence_class']=('VERIFIED_MIRROR_COMPANY_MATERIAL_NOT_HKEX_FIRST_PUBLICATION'
                               if is_mirror(raw) else 'VERIFIED_COMPANY_SPECIFIC_MATERIAL')
        row['acquired_at']=evidence_acquired_at(row)
        result.setdefault(symbol,[]).append(row)
    # Do not collapse a mirror row into an official or ordinary published row.
    merged={}
    for symbol,rows in result.items():
        mirror=[r for r in rows if is_mirror(r)]
        other=merge_event_rows(symbol,[r for r in rows if not is_mirror(r)])
        for row in other:
            row['evidence_lane']='COMPANY_MATERIAL';row['evidence_class']='VERIFIED_COMPANY_SPECIFIC_MATERIAL'
        merged[symbol]=[*other,*mirror]
    return merged


def verified_theme_relations(
    themes: Sequence[Mapping[str, Any]] | None,
    start: datetime | None,
    cutoff: datetime | None,
    *, audit: list[dict[str,Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Keep original theme admission and retain exact rejected relation facts."""
    result: dict[str, list[dict[str, Any]]] = {}
    for theme in themes or []:
        if not isinstance(theme, Mapping):
            continue
        theme_code = str(theme.get("theme") or "")
        for raw in theme.get("mappings") or []:
            if not isinstance(raw, Mapping):
                continue
            symbol = canonical_symbol(raw.get("symbol"))
            if not symbol or raw.get("relationship_type") != "INDUSTRY_INFERENCE":
                reason='HK_ISSUER_RELATION_IDENTITY_OR_TYPE_INVALID'
            elif not str(raw.get("issuer_quote") or "").strip():
                reason='ISSUER_QUOTE_MISSING'
            elif not isinstance(raw.get("source_refs"),list) or not raw.get("source_refs"):
                reason='ISSUER_SOURCE_REFS_MISSING'
            elif not _in_window(raw.get('issuer_published_at'),start,cutoff):
                reason='ISSUER_PUBLICATION_OUTSIDE_WINDOW'
            elif not _relation_clock_valid(raw,start,cutoff):
                reason='ISSUER_ACQUISITION_TIME_MISSING_INVALID_OR_OUTSIDE_WINDOW'
            else:
                reason='ACCEPTED'
            if audit is not None:
                audit.append({**deepcopy(dict(raw)),'symbol':symbol or raw.get('symbol'),
                    'manager_themes':[theme_code],'related_us_symbols':[],
                    'relation_origin':'EXISTING_MANAGER_THEME','reason':reason})
            if reason!='ACCEPTED':
                continue
            row=deepcopy(dict(raw));row['manager_theme']=theme_code
            result.setdefault(symbol,[]).append(row)
    return result


def structured_us_symbols(row: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("related_us_symbols", "us_symbols"):
        raw = row.get(key)
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, list):
            values.update(
                value.strip().upper()
                for value in raw
                if isinstance(value, str) and value.strip()
            )
    basis = row.get("identity_pair_basis")
    if isinstance(basis, Mapping):
        for key in ("related_us_symbols", "us_symbols", "us_symbol"):
            raw = basis.get(key)
            if isinstance(raw, str):
                raw = [raw]
            if isinstance(raw, list):
                values.update(str(value).strip().upper() for value in raw if str(value).strip())
    return values


def structured_us_issuer_relations(
    material_cards: Sequence[Mapping[str, Any]] | None,
    start: datetime | None,
    cutoff: datetime | None,
) -> dict[str, list[dict[str, Any]]]:
    """Keep issuer evidence only when an explicit US symbol and lineage exist."""
    result: dict[str, list[dict[str, Any]]] = {}
    for raw in material_cards or []:
        if not isinstance(raw, Mapping) or raw.get("semantic_status") != "ACCEPTED":
            continue
        symbol = canonical_symbol(raw.get("symbol"))
        if not symbol or not structured_us_symbols(raw):
            continue
        if not isinstance(raw.get("source_refs"), list) or not raw.get("source_refs"):
            continue
        published = raw.get("published_at")
        acquired = (
            raw.get("available_at")
            or raw.get("retrieved_at")
            or raw.get("first_seen_at")
            or raw.get("collected_at")
        )
        if (not _in_window(published, start, cutoff)
                or not acquisition_is_within_window(raw, start, cutoff)
                or not _relation_clock_valid(raw, start, cutoff)):
            continue
        result.setdefault(symbol, []).append(deepcopy(dict(raw)))
    return result


def us_mappings(
    us_market: Mapping[str, Any] | None,
    relations: Mapping[str, Sequence[Mapping[str, Any]]],
    direct_us_relations: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    industry: dict[str, list[dict[str, Any]]] = {}
    individual: dict[str, list[dict[str, Any]]] = {}
    if (not isinstance(us_market, Mapping)
            or us_market.get("status") not in {"READY", "PARTIAL"}
            or us_market.get("mapping_eligible") is not True):
        return industry, individual
    source_identity = deepcopy(us_market.get("source_identity"))
    us_acquired_at = timestamp(us_market.get("captured_at"))
    if us_acquired_at is None:
        return industry, individual

    for mover in us_market.get("raw_industry_up") or []:
        if not isinstance(mover, Mapping) or mover.get("status") not in {"READY", "PARTIAL"}:
            continue
        accepted_themes = set(US_LABEL_TO_MANAGER_THEMES.get(str(mover.get("label") or ""), ()))
        if not accepted_themes:
            continue
        for symbol, rows in relations.items():
            for relation in rows:
                if not _independent_native_relation(relation,source_identity):continue
                if not _matches_theme(relation,str(mover.get("label") or "")):
                    continue
                industry.setdefault(symbol, []).append(
                    {
                        "evidence_lane": "US_INDUSTRY_MAPPING",
                        "evidence_class": "VERIFIED_US_INDUSTRY_WITH_HK_ISSUER_RELATION",
                        "us_mover": deepcopy(dict(mover)),
                        "hk_relation": deepcopy(dict(relation)),
                        "issuer_published_at": relation.get("issuer_published_at"),
                        "available_at": _latest_iso(us_acquired_at, _relation_acquired_at(relation)),
                        "us_captured_at": us_acquired_at.isoformat(),
                        "source_identity": source_identity,
                    }
                )

    for mover in us_market.get("raw_individual_up") or []:
        if not isinstance(mover, Mapping):
            continue
        us_symbol = str(mover.get("symbol") or "").upper()
        if not us_symbol:
            continue
        for symbol, rows in direct_us_relations.items():
            for relation in rows:
                if not _independent_native_relation(relation,source_identity):continue
                if us_symbol not in structured_us_symbols(relation):
                    continue
                individual.setdefault(symbol, []).append(
                    {
                        "evidence_lane": "US_INDIVIDUAL_MAPPING",
                        "evidence_class": "VERIFIED_US_INDIVIDUAL_WITH_STRUCTURED_HK_RELATION",
                        "us_mover": deepcopy(dict(mover)),
                        "hk_relation": deepcopy(dict(relation)),
                        "published_at": relation.get("published_at"),
                        "available_at": _latest_iso(
                            us_acquired_at,
                            relation.get("available_at"), relation.get("retrieved_at"),
                            relation.get("first_seen_at"), relation.get("collected_at"),
                        ),
                        "us_captured_at": us_acquired_at.isoformat(),
                        "source_identity": source_identity,
                    }
                )
    return industry, individual



def us_mapping_diagnostics(
    us_market: Mapping[str, Any] | None,
    theme_relations: Mapping[str, Sequence[Mapping[str, Any]]],
    direct_relations: Mapping[str, Sequence[Mapping[str, Any]]],
    industry: Mapping[str, Sequence[Mapping[str, Any]]],
    individual: Mapping[str, Sequence[Mapping[str, Any]]],
    *, material_audit: Sequence[Mapping[str,Any]] = (), material_count: int = 0,
) -> dict[str, Any]:
    raw_industry=list((us_market or {}).get("raw_industry_up") or []) if isinstance(us_market,Mapping) else []
    raw_individual=list((us_market or {}).get("raw_individual_up") or []) if isinstance(us_market,Mapping) else []
    eligible=isinstance(us_market,Mapping) and us_market.get("mapping_eligible") is True
    industry_rows=[]
    for mover in raw_industry:
        if not isinstance(mover,Mapping):continue
        label=str(mover.get("label") or "")
        themes=set(US_LABEL_TO_MANAGER_THEMES.get(label,()))
        relation_count=sum(1 for rows in theme_relations.values() for row in rows if _matches_theme(row,label))
        accepted=sum(1 for rows in industry.values() for row in rows
                     if isinstance(row.get("us_mover"),Mapping) and dict(row["us_mover"])==dict(mover))
        reason=("US_MAPPING_INPUT_NOT_ELIGIBLE" if not eligible else "NO_MANAGER_THEME_TAXONOMY" if not themes else
                "NO_CUTOFF_BOUND_HK_ISSUER_RELATION" if relation_count==0 else "ACCEPTED" if accepted else "RELATION_PRESENT_BUT_MAPPING_NOT_ACCEPTED")
        rejected=[deepcopy(dict(r)) for r in material_audit if r.get('reason')!='ACCEPTED' and themes.intersection(r.get('manager_themes') or [])]
        industry_rows.append({"label":label,"candidate_relation_count":relation_count,"accepted_mapping_count":accepted,"reason":reason,
            "rejected_candidates":rejected,"candidate_owner":"MaterialStore/ResearchArchiveStore -> native issuer proposition",
            "accepted_candidates":[{"symbol":s,"relation":deepcopy(r['hk_relation'])} for s,rows in industry.items() for r in rows if r.get('us_mover')==mover]})
    individual_rows=[]
    for mover in raw_individual:
        if not isinstance(mover,Mapping):continue
        us_symbol=str(mover.get("symbol") or "").upper()
        relation_count=sum(1 for rows in direct_relations.values() for row in rows if us_symbol in structured_us_symbols(row))
        accepted=sum(1 for rows in individual.values() for row in rows
                     if isinstance(row.get("us_mover"),Mapping) and dict(row["us_mover"])==dict(mover))
        reason=("US_MAPPING_INPUT_NOT_ELIGIBLE" if not eligible else "NO_STRUCTURED_HK_US_RELATION" if relation_count==0 else "ACCEPTED" if accepted else "RELATION_PRESENT_BUT_MAPPING_NOT_ACCEPTED")
        rejected=[deepcopy(dict(r)) for r in material_audit if r.get('reason')!='ACCEPTED' and us_symbol in (r.get('related_us_symbols') or [])]
        individual_rows.append({"symbol":us_symbol,"candidate_relation_count":relation_count,"accepted_mapping_count":accepted,"reason":reason,
            "rejected_candidates":rejected,"candidate_owner":"MaterialStore/ResearchArchiveStore -> explicit US symbol in issuer clause",
            "accepted_candidates":[{"symbol":s,"relation":deepcopy(r['hk_relation'])} for s,rows in individual.items() for r in rows if r.get('us_mover')==mover]})
    accepted_count=sum(len(rows) for rows in industry.values())+sum(len(rows) for rows in individual.values())
    material_input=(us_market.get('research_material_input') if isinstance(us_market,Mapping) else None)
    material_input=deepcopy(dict(material_input)) if isinstance(material_input,Mapping) else {}
    complete_material_input=material_input.get('complete') is True
    all_movers=[*industry_rows,*individual_rows]
    pending_candidates=[row for row in all_movers
        if int(row.get('candidate_relation_count') or 0)>int(row.get('accepted_mapping_count') or 0)]
    rejected_evidence=[candidate for row in all_movers
        for candidate in row.get('rejected_candidates',[]) if isinstance(candidate,Mapping)]
    reasons=[]
    market_status=(us_market.get('status') if isinstance(us_market,Mapping) else None)
    if market_status not in {'READY','PARTIAL'}:
        reasons.extend((us_market.get('gaps') or []) if isinstance(us_market,Mapping) else ['US_MARKET_INPUT_NOT_READ'])
        if not reasons:reasons=['US_MARKET_INPUT_NOT_READY']
        assessment_state='NOT_EVALUATED'
    elif not eligible:
        ineligible_reasons=(us_market.get('mapping_ineligible_reasons') or us_market.get('gaps') or []) \
            if isinstance(us_market,Mapping) else []
        reasons.extend(ineligible_reasons)
        if not reasons:reasons=['US_MAPPING_INPUT_NOT_ELIGIBLE']
        assessment_state='NOT_EVALUATED'
    elif not material_count and not complete_material_input:
        reasons.extend(material_input.get('gaps') or ['FULL_VERIFIED_MATERIAL_CARDS_REQUIRED'])
        if not reasons:reasons=['FULL_VERIFIED_MATERIAL_CARDS_REQUIRED']
        assessment_state='NOT_EVALUATED'
    elif accepted_count>0:
        assessment_state='ASSESSED_WITH_RELATIONS'
        reasons=['VERIFIED_RELATIONS_PASSED_TWO_SOURCE_PIT']
    elif (market_status!='READY' or not complete_material_input or pending_candidates or rejected_evidence):
        if market_status!='READY':
            reasons.extend((us_market.get('gaps') or ['US_MARKET_INPUT_PARTIAL'])
                           if isinstance(us_market,Mapping) else ['US_MARKET_INPUT_PARTIAL'])
        if not complete_material_input:
            reasons.extend(material_input.get('gaps') or ['MATERIAL_INPUT_COMPLETENESS_UNVERIFIED'])
        if pending_candidates:
            reasons.append('TWO_SOURCE_PIT_VERIFIED_REQUIRED')
        for row in rejected_evidence:
            row_reasons=row.get('rejection_reasons')
            if isinstance(row_reasons,list):
                reasons.extend(str(value) for value in row_reasons if isinstance(value,str))
            elif isinstance(row.get('reason'),str):
                reasons.append(row['reason'])
        assessment_state='INSUFFICIENT'
    else:
        assessment_state='ASSESSED_ZERO'
        reasons=['NO_QUALIFIED_RELATION_AFTER_COMPLETE_TWO_SOURCE_PIT_EVALUATION']
    reasons=sorted(set(reason for reason in reasons if isinstance(reason,str) and reason))
    accepted_count_value=(accepted_count if assessment_state in {'ASSESSED_ZERO','ASSESSED_WITH_RELATIONS'} else None)
    membership_counts=material_input.get('target_connect_membership_counts',{})
    return {
        "status":"COMPUTED_BY_RELATION_LAYER",
        "source_material_card_count":material_count,"material_relation_audit":list(material_audit),
        "missing_input" : "FULL_VERIFIED_MATERIAL_CARDS_REQUIRED" if not material_count and not complete_material_input else None,
        "mapping_eligible":eligible,
        "accepted_hk_mapping_count":accepted_count_value,
        "assessment_state":assessment_state,
        "assessment_reason":reasons[0] if reasons else None,
        "assessment_reasons":reasons,
        "candidate_relation_count":sum(int(row.get('candidate_relation_count') or 0) for row in all_movers),
        "material_input":material_input,
        "target_connect_membership_counts":deepcopy(membership_counts) if isinstance(membership_counts,Mapping) else {},
        "industry":industry_rows,"individual":individual_rows,
        "raw_movers_retained_when_unmapped":True,
        "relation_gate":"TWO_SOURCE_PIT_VERIFIED_REQUIRED",
        **FLAGS,
    }

def trend_evidence(screen: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for symbol, row in screen_rows(screen).items():
        r3 = row.get("recent_3_session_return_pct")
        r5 = row.get("recent_5_session_return_pct")
        if type(r3) in (int, float) and type(r5) in (int, float) and r3 > 0 and r5 > 0:
            result[symbol] = {
                "evidence_lane": "TREND_CONTINUATION",
                "evidence_class": "VERIFIED_SCREEN_HISTORY_TREND",
                "recent_3_session_return_pct": r3,
                "recent_5_session_return_pct": r5,
                "verified_session": row.get("verified_session"),
                "source_refs": deepcopy(row.get("source_refs") or []),
            }
    return result


def collect_attention_evidence(
    *,
    market_screen: Mapping[str, Any] | None,
    stocks: Sequence[Mapping[str, Any]] | None,
    material_cards: Sequence[Mapping[str, Any]] | None,
    themes: Sequence[Mapping[str, Any]] | None,
    announcement_observation: Mapping[str, Any] | None,
    us_market: Mapping[str, Any] | None,
    start: datetime | None,
    cutoff: datetime | None,
) -> AttentionEvidence:
    screens = screen_rows(market_screen)
    stock_index = workspace_rows(stocks)
    official = official_evidence(announcement_observation, start, cutoff)
    company = company_evidence(stocks, material_cards, start, cutoff)
    theme_audit: list[dict[str,Any]]=[]
    verified_theme_relations(themes,start,cutoff,audit=theme_audit)
    for row in theme_audit:
        if row.get('reason')=='ACCEPTED':
            row['reason']='LEGACY_THEME_RELATION_REQUIRES_ORIGINAL_ISSUER_PROPOSITION'
    # ALL executable joins must pass the one original body/span parser, even
    # when a legacy cache has related_us_symbols or a matching theme label.
    theme_relations,direct_relations,material_audit=material_us_relations(material_cards,start,cutoff)
    membership_by_card={
        str(card.get('card_id')):deepcopy(dict(card['target_connect_membership']))
        for card in material_cards or []
        if isinstance(card,Mapping) and card.get('card_id') and isinstance(card.get('target_connect_membership'),Mapping)
    }
    membership_by_proposition={
        str(row.get('proposition_id')):deepcopy(membership_by_card[str(row.get('card_id'))])
        for row in material_audit
        if isinstance(row,Mapping) and row.get('proposition_id') and row.get('card_id') and
        str(row.get('card_id')) in membership_by_card
    }
    for relation_group in (theme_relations,direct_relations):
        for rows in relation_group.values():
            for relation in rows:
                membership=(membership_by_card.get(str(relation.get('card_id') or '')) or
                            membership_by_proposition.get(str(relation.get('proposition_id') or '')))
                if membership is not None:relation['target_connect_membership']=deepcopy(membership)
    for audit_row in material_audit:
        membership=membership_by_card.get(str(audit_row.get('card_id') or ''))
        if membership is not None:audit_row['target_connect_membership']=deepcopy(membership)
    material_audit=[*theme_audit,*material_audit]
    mapping_input=us_market
    if isinstance(us_market,Mapping) and not _in_window(us_market.get('captured_at'),start,cutoff):
        mapping_input={**us_market,'mapping_eligible':False}
    us_industry, us_individual = us_mappings(mapping_input, theme_relations, direct_relations)
    diagnostics = us_mapping_diagnostics(mapping_input, theme_relations, direct_relations, us_industry, us_individual, material_audit=material_audit, material_count=len(material_cards or []))
    return AttentionEvidence(
        screen_rows=screens,
        stock_rows=stock_index,
        official=official,
        company=company,
        us_industry=us_industry,
        us_individual=us_individual,
        trend=trend_evidence(market_screen),
        us_mapping_diagnostics=diagnostics,
    )


__all__ = [
    "AttentionEvidence",
    "US_LABEL_TO_MANAGER_THEMES",
    "collect_attention_evidence",
    "screen_rows",
    "structured_us_symbols",
    "us_mapping_diagnostics",
]
