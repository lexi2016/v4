"""Research-only projection and aggregation for the frozen 667/1,003 catalog."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, DecimalException, InvalidOperation
import re
from typing import Any, Mapping
from contracts.us_equity_calendar import NY, session as us_equity_session

from .common import current, timestamp, valid_sha

CATALOG_SOURCE_SHA256 = "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671"
RECOVERY_OVERLAY_SHA256 = "3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c"
MANUAL_QUOTE_SCOPE_SHA256 = "6d163c286d90d1dfd00b18fa134d3f4ec308d9d2efdd51e5cbba800f3d61acf8"
MAPPING_POLICY_VERSION = "FULL_US_HK_INDUSTRY_MAPPING_CONSUMPTION_V4_20261019"
MAPPING_POLICY_SHA256 = "4e40b759f5811383d2a9ea8211dfc77662cb0094d7d863c75e54d8a5dba9a3c2"
INDUSTRY_LISTING_VERSION = "US_HK_INDUSTRY_LISTING_V1_20261024"
# This is a listing policy, independent of the retained strict-selection policy.
INDUSTRY_LISTING_POLICY = dict(version=INDUSTRY_LISTING_VERSION,
    catalog_types=["BUSINESS_PEER", "SAME_ISSUER"],
    catalog_identity="EXACT_RELATION_AND_HK_CODE_WITH_NAMED_INDUSTRY_OR_PEER_SEGMENT",
    classification="SAVED_EXACT_INDUSTRY_MAPPING_WITH_SOURCE_HASH_AND_VERIFIED_HK_IDENTITY",
    return_gate=False, company_transmission_gate=False, technical_gates=False,
    eligibility_gate=False, historical_pit_verified=False)
MANUAL_QUOTE_OWNER = "research_peripheral.external_finance.manual_quote_scope"
SCHEDULED_QUOTE_OWNER = "research_peripheral.external_finance.scheduled_quote_scope"
_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_ASCII_WHITESPACE = " \t\n\r\v\f"

RELATION_ROUTES = {
    "BUSINESS_PEER": ("SUBINDUSTRY_BUSINESS_PEER", "PRIMARY"),
    "SUPPLY_CHAIN": ("UPSTREAM_DOWNSTREAM_ECONOMIC_EXPOSURE", "PRIMARY"),
    "CAPEX_CYCLE": ("CAPEX_DEMAND_CONTEXT", "PRIMARY"),
    "COMMODITY_EXPOSURE": ("COMMODITY_COST_OR_OUTPUT_EXPOSURE", "PRIMARY"),
    "CONTRACTUAL_RELATION": ("CONTRACT_OR_LICENSE_ECONOMIC_EXPOSURE", "PRIMARY"),
    "JOINT_VENTURE": ("JOINT_VENTURE_ECONOMIC_EXPOSURE", "PRIMARY"),
    "OWNERSHIP": ("OWNERSHIP_ECONOMIC_EXPOSURE", "SECONDARY"),
    "SAME_ISSUER": ("SAME_ISSUER_ADR_CONTEXT", "SECONDARY"),
    "INDUSTRY_PROXY": ("BROAD_SECTOR_BACKGROUND", "SECONDARY"),
    "MACRO_FACTOR": ("MACRO_BACKGROUND", "SECONDARY"),
    "SENTIMENT_TRANSMISSION": ("COUNTRY_OR_SENTIMENT_BACKGROUND", "SECONDARY"),
    "TRANSACTION_EVENT": ("DATED_TRANSACTION_EVENT", "SECONDARY"),
}
_EXCLUDED_MARKERS = ("EXCLUDED", "ENDED", "TERMINATED", "OLD_SECURITY", "OLD_PRICE")
_NONCURRENT_MARKERS = ("DATED", "BACKGROUND", "HISTORICAL", "PENDING", "CANNOT_CONFIRM", "OPEN_CURRENT")
_SUPPORTED_CURRENT_STATES = frozenset({"CURRENT_RESEARCH_SCOPE"})
_QUOTE_RETURN_TOLERANCE_PP = Decimal("0.001")


def normalize_us_symbol(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip(_ASCII_WHITESPACE).upper()
    return normalized if _US_SYMBOL.fullmatch(normalized) else None


def normalize_mapping_candidates(context, *, relation_rows, catalog_rows=(),
        industry_rows=(), manual_quote_scope=None, identities=()):
    """One deterministic per-HK candidate; preserve every source disposition."""
    from ..contracts import MappingPath, ResearchCandidate, digest
    from ..inputs.strict_us_selection import validate_mapping_quote
    from .us_mapping_policy import RELATIONSHIP_A, ETF_SYMBOLS, US_SYMBOL_THEMES
    session = (context.get("source_sessions") or {}).get("us") or (context.get("source_sessions") or {}).get("US")
    grouped = defaultdict(list)
    industry_matches = defaultdict(list)
    names = {}
    for item in identities or ():
        code = item if isinstance(item, str) else (item.get("symbol") or item.get("target_symbol") or item.get("hk_code") or item.get("code"))
        if isinstance(code,str) and re.fullmatch(r"\d{1,5}",code):code="HK."+code.zfill(5)
        if isinstance(code, str) and re.fullmatch(r"HK\.[0-9]{5}", code):
            grouped[code]
            if isinstance(item, dict): names[code] = item.get("name") or item.get("hk_name")
    def ref_union(values):
        seen = {}
        for value in values:
            if isinstance(value, dict): seen[digest(value)] = value
        return [seen[key] for key in sorted(seen)]
    def add(item, *, catalog=False, sector=False):
        code = item.get("symbol")
        if not isinstance(code, str) or not re.fullmatch(r"HK\.[0-9]{5}", code): return
        names.setdefault(code, item.get("name"))
        us = normalize_us_symbol(item.get("us_symbol"))
        relation_type = item.get("relation_type")
        role = "SECTOR_CONTEXT" if sector or us in ETF_SYMBOLS else "INDIVIDUAL"
        reasons = []
        source_refs = [dict(owner=item.get("owner"), sha256=item.get("source_sha256"),
            ref=item.get("catalog_relation_id") or item.get("relation_sha256") or item.get("source_sha256"),
            available_at=item.get("available_at"))]
        source_refs += [r for r in item.get("relation_source_refs", []) if isinstance(r, dict)]
        quote_return, quote_gap = validate_mapping_quote(item.get("quote"), us, session)
        quote_verified=(quote_return is not None and not quote_gap and bool(item.get("owner"))
            and valid_sha(item.get("source_sha256")) and current(context,item.get("available_at"))
            and item.get("source_session")==session
            and "EVIDENCE_REFS_PENDING" not in (item.get("diagnostic_gaps") or []))
        if quote_verified:
            try:
                close=us_equity_session(session).close_at
                quote_verified=close is not None and timestamp(item.get("available_at"))>=close
            except (ValueError,TypeError,OverflowError):quote_verified=False
        if quote_gap: reasons.append(quote_gap)
        if not item.get("owner") or not valid_sha(item.get("source_sha256")) or not current(context, item.get("available_at")):
            reasons.append("US_SOURCE_IDENTITY_OR_AVAILABILITY_PENDING")
        if item.get("source_session") != session: reasons.append("US_SOURCE_SESSION_PENDING")
        excluded = False
        if catalog:
            projected = project_catalog_relation(item, manual_binding=manual_quote_scope,
                expected_session=session, cutoff=context.get("cutoff"))
            us = projected.get("us_symbol")
            role = "SECTOR_CONTEXT" if us in ETF_SYMBOLS or projected.get("route") in {"BROAD_SECTOR_BACKGROUND", "MACRO_BACKGROUND"} else "INDIVIDUAL"
            disposition = projected.get("catalog_disposition", "")
            excluded = disposition.startswith("EXCLUDED")
            current_state = projected.get("catalog_current_applicability")
            scope = "current_supported" if projected.get("catalog_current_scope_class") == "LIMITED_SCOPE_SUPPORTED_FOR_RESEARCH" else "pending"
            # The original enum stays authoritative even on older projection schemas.
            recovery = (item.get("catalog_relation") or {}).get("recovery_v2r1", {})
            state, _, conflict = _state_resolution(recovery, "CURRENT_APPLICABILITY")
            if _current_scope_class(state) == "LIMITED_SCOPE_SUPPORTED_FOR_RESEARCH" and not conflict and disposition.startswith("ADOPTED"):
                scope = "current_supported"
            elif _current_scope_class(state) == "DATED_OR_PENDING_SCOPE": scope = "dated_weak"
            if excluded: scope = "excluded"
            relation_type = projected.get("relation_type")
            quote_return = projected.get("us_source_return_pct")
            quote_verified = projected.get("quote_status")=="VERIFIED"
            reasons = [] if scope == "current_supported" and projected.get("quote_status") == "VERIFIED" else [projected.get("catalog_disposition_reason") or "CATALOG_SCOPE_PENDING"]
            if projected.get("quote_status") != "VERIFIED": reasons.append(projected.get("quote_missing_reason") or "QUOTE_PENDING")
            source_refs = [dict(owner=projected.get("catalog_source_owner"),sha256=item.get("catalog_relation_sha256") or item.get("source_sha256"),ref=item.get("catalog_relation_id"),available_at=projected.get("available_at"))]
            industry = projected.get("catalog_research_industry")
            segment = projected.get("catalog_segment")
            # A catalogued business peer establishes an industry association;
            # supply/ownership/cooperation on their own do not. Current company
            # transmission and price/eligibility gates are separate references.
            if (relation_type in {"BUSINESS_PEER", "SAME_ISSUER"}
                    and projected.get("catalog_source_identity_verified") is True
                    and code == "HK." + str(projected.get("catalog_hk_code"))
                    and us and (industry or (segment if relation_type == "BUSINESS_PEER" else None))
                    and projected.get("catalog_fact") and valid_sha(item.get("source_sha256"))):
                refs = ref_union([dict(owner=projected.get("catalog_source_owner"),
                    sha256=item.get("source_sha256"),ref=item.get("catalog_relation_id"),
                    available_at=item.get("available_at")), dict(owner=projected.get("catalog_source_owner"),
                    sha256=item.get("relation_sha256") or digest(item.get("catalog_relation")),
                    ref=item.get("catalog_relation_id"), available_at=item.get("available_at"))])
                if valid_sha(projected.get("source_sha256")):
                    refs = ref_union([*refs, dict(owner=projected.get("owner"),
                        sha256=projected["source_sha256"],ref="US_QUOTE:"+us,
                        available_at=projected.get("available_at"))])
                industry_matches[code].append(dict(us_symbol=us, industry=industry or segment,
                    segment=segment, association=relation_type,
                    role="SECTOR_CONTEXT" if us in ETF_SYMBOLS else "INDIVIDUAL",
                    relation_id=item.get("catalog_relation_id"), return_pct=quote_return,
                    source_session=projected.get("source_session") or item.get("source_session"),
                    current_applicability=current_state, source_refs=refs,
                    warnings=["SAVED_CATALOG_INDUSTRY_ASSOCIATION", "CURRENT_APPLICABILITY_UNVERIFIED",
                        "HISTORICAL_PIT_UNVERIFIED", projected.get("catalog_disposition_reason") or "CATALOG_SCOPE_PENDING"]))
            direction = "UNKNOWN"  # peers/conditional mechanisms do not certify an active sign
            strict_supported = False
        else:
            validity = item.get("relation_current_validity")
            excluded = validity in {"EXCLUDED_CURRENT", "ENDED", "TERMINATED"} or item.get("catalog_research_use") == "EXCLUDED_CURRENT"
            scope = ("excluded" if excluded else "dated_weak" if validity in {"DATED_SCOPE_ONLY", "HISTORICAL"}
                else "current_supported" if validity in {"CURRENT_SUPPORTED", "CURRENT_RESEARCH_SCOPE", "CURRENT"} else "pending")
            if validity is None and relation_type in RELATIONSHIP_A and item.get("relation_status")=="REVIEWED":
                scope="dated_weak"
                reasons.append("RELATION_CURRENT_VALIDITY_PENDING")
            if role == "SECTOR_CONTEXT": scope = "current_supported" if not reasons else "pending"
            elif item.get("relation_status") != "REVIEWED" or item.get("relation_pit_status") == "PIT_UNCONFIRMED" or item.get("publication_time_gaps"):
                scope = "pending" if not excluded else scope; reasons.append("RELATION_REVIEW_OR_PIT_PENDING")
            if scope == "pending" and role == "INDIVIDUAL": reasons.append("RELATION_CURRENT_VALIDITY_PENDING")
            direction = item.get("relation_direction")
            explicit_direction=direction in {"POSITIVE", "NEGATIVE"}
            if not explicit_direction:
                # Preserve the old named-company research hypothesis. It is
                # never positive strict evidence; the explicit gap remains.
                direction="POSITIVE" if relation_type in RELATIONSHIP_A and item.get("relation_status")=="REVIEWED" else "UNKNOWN"
            strict_supported = relation_type in RELATIONSHIP_A and role == "INDIVIDUAL"
            if strict_supported and not explicit_direction: reasons.append("RELATION_DIRECTION_PENDING")
            for gap in item.get("diagnostic_gaps") or []:
                if gap not in {"CONNECT_MEMBERSHIP_UNKNOWN", "TARGET_NOT_IN_CURRENT_CONNECT_MEMBERSHIP", "AUDITED_RESEARCH_PRIORITY_UNAVAILABLE"}:
                    reasons.append(gap)
        if role == "SECTOR_CONTEXT": strict_supported = False; direction = "UNKNOWN"
        status = "REJECT" if excluded else "PENDING" if reasons or scope in {"pending", "dated_weak"} else "PASS"
        ident = dict(symbol=code,us_symbol=us,relation_type=relation_type,role=role,
            relation_id=item.get("catalog_relation_id"))
        path = MappingPath(path_id=digest(ident),symbol=code,us_symbol=us,relation_type=relation_type,
            role=role,scope=scope,status=status,direction=direction,strict_supported=strict_supported,
            primary_theme=item.get("primary_theme") or US_SYMBOL_THEMES.get(us) or item.get("source_industry"),
            # Focus uses the same prechosen path's saved industry; strict theme is unchanged.
            focus_theme=item.get("primary_theme") or US_SYMBOL_THEMES.get(us)
                or ((projected.get("catalog_research_industry") or projected.get("catalog_segment")) if catalog else None)
                or item.get("source_industry"),
            return_pct=quote_return,source_session=session,available_at=item.get("available_at"),
            quote_verified=bool(quote_verified),quote_available_at=projected.get("available_at") if catalog else item.get("available_at"),
            source_refs=ref_union(source_refs),evidence_ids=sorted(set(item.get("evidence_ids") or [])),reasons=sorted(set(reasons)))
        grouped[code].append(path)
    for item in relation_rows:
        if isinstance(item, dict): add(item)
    for item in catalog_rows:
        if isinstance(item, dict): add(item,catalog=True)
    for item in industry_rows:
        if not isinstance(item, dict): continue
        for proxy in item.get("proxy_paths") or []:
            for us in proxy.get("proxy_symbols") or []:
                add(dict(item,us_symbol=us,relation_type="INDUSTRY_PROXY",quote=None,
                    source_session=proxy.get("source_session"),source_sha256=proxy.get("source_sha256"),
                    owner=proxy.get("owner"),available_at=proxy.get("available_at")),sector=True)
                # Reuse the existing exact classification-to-proxy mapping.
                # ETF/basket paths remain explicitly labelled sector context.
                if (normalize_us_symbol(us) and item.get("source_industry")
                        and item.get("identity_status") == "VERIFIED"
                        and item.get("mapping_version") and item.get("mapping_evidence")
                        and item.get("source_owner") and valid_sha(item.get("source_artifact_sha256"))):
                    industry_matches[item["symbol"]].append(dict(us_symbol=us,
                        industry=item["source_industry"], segment=proxy.get("theme"),
                        association="CLASSIFIED_INDUSTRY_PROXY", role="SECTOR_CONTEXT", relation_id=None,
                        return_pct=proxy.get("return_pct") if len(proxy.get("proxy_symbols") or []) == 1 else None,
                        source_session=proxy.get("source_session"), current_applicability=item.get("temporal_status"),
                        source_refs=ref_union([dict(owner=item["source_owner"],sha256=item["source_artifact_sha256"],
                            ref=item.get("source_response_ref") or item.get("source_row_sha256"),available_at=item.get("available_at")),
                            dict(owner="v4.manager_workbench.hk_industry_mapping",ref=item["mapping_version"],
                                sha256=digest(item["mapping_evidence"]))]),
                        warnings=["SAVED_INDUSTRY_CLASSIFICATION", "PROXY_CONTEXT_NOT_COMPANY_TRANSMISSION",
                            "CURRENT_APPLICABILITY_UNVERIFIED", "HISTORICAL_PIT_UNVERIFIED"]))
    candidates = []
    def path_order(p):
        return (0 if p.strict_supported else 1, RELATIONSHIP_A.index(p.relation_type) if p.relation_type in RELATIONSHIP_A else 99,
            p.us_symbol or "", p.path_id)
    for code, paths in grouped.items():
        merged = []
        by_id = defaultdict(list)
        for p in paths: by_id[p.path_id].append(p)
        for identity, versions in sorted(by_id.items()):
            facts = {}
            for p in versions:
                fact = p.model_dump(exclude={"source_refs", "evidence_ids"})
                facts[digest(fact)] = p
            refs = ref_union([r for p in versions for r in p.source_refs]); ids = sorted({e for p in versions for e in p.evidence_ids})
            if len(facts) == 1:
                p = next(iter(facts.values())).model_copy(update=dict(source_refs=refs,evidence_ids=ids))
            else:
                # No precedence exists: keep all fact versions as refs and isolate this key only.
                p = facts[sorted(facts)[0]].model_copy(update=dict(scope="pending",status="PENDING",return_pct=None,quote_verified=False,
                    source_refs=ref_union(refs+[dict(ref="conflicting_fact:"+key,sha256=key,fact=value.model_dump()) for key,value in facts.items()]),
                    evidence_ids=ids,reasons=["DUPLICATE_MAPPING_PATH_CONFLICT"]))
            merged.append(p)
        merged.sort(key=path_order)
        individuals = [p for p in merged if p.role == "INDIVIDUAL" and p.scope != "excluded"]
        primary = next((p for p in individuals if p.strict_supported), None) or next(iter(individuals),None)
        relevant = individuals or merged
        state = "current_supported" if any(p.scope == "current_supported" and p.status == "PASS" for p in relevant) else "dated_weak" if any(p.scope == "dated_weak" for p in relevant) else "pending"
        def research_quote_ready(p):
            return p.return_pct is not None and not any(r.startswith(('QUOTE_','US_SOURCE_','US_SESSION_','US_RELATION_REVIEW_','RELATION_REVIEW_OR_PIT')) for r in p.reasons)
        positive = [p for p in individuals if research_quote_ready(p) and p.direction == "POSITIVE" and Decimal(p.return_pct)>0]
        negative = [p for p in individuals if research_quote_ready(p) and (p.direction == "NEGATIVE" or Decimal(p.return_pct)<0)]
        direction = "CONFLICT" if positive and negative else "POSITIVE" if positive else "NEGATIVE" if negative else "UNKNOWN"
        candidates.append(ResearchCandidate(symbol=code,name=names.get(code),research_state=state,direction=direction,
            primary_path_id=primary.path_id if primary else None,paths=merged,
            reasons=sorted({r for p in merged for r in p.reasons}) or ([] if merged else ["NO_MAPPING_PATH"]),
            source_refs=ref_union([r for p in merged for r in p.source_refs]),
            industry_matches=ref_union(industry_matches[code])))
    def order(c):
        strengths = [Decimal(p.return_pct) for p in c.paths if p.role == "INDIVIDUAL" and p.direction == "POSITIVE" and p.return_pct is not None and Decimal(p.return_pct)>0
            and not any(r.startswith(('QUOTE_','US_SOURCE_','US_SESSION_','US_RELATION_REVIEW_','RELATION_REVIEW_OR_PIT')) for r in p.reasons)]
        return ({"current_supported":0,"dated_weak":1,"pending":2}[c.research_state],
            {"POSITIVE":0,"CONFLICT":1,"NEGATIVE":2,"UNKNOWN":3}[c.direction],-max(strengths,default=Decimal(0)),c.symbol)
    return sorted(candidates,key=order)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _state_resolution(recovery: Any, section: str) -> tuple[str | None, list[dict[str, str]], bool]:
    if not isinstance(recovery, Mapping):
        return None, [], False
    fallback = {
        "CURRENT_APPLICABILITY": "current_applicability_state",
        "FACT_VERIFIED_SCOPE": "fact_state",
        "IDENTITY_SCOPE": "identity_state",
        "EXCLUDED_SCOPE": "excluded_scope_state",
        "PENDING_SCOPE": "pending_scope_state",
    }.get(section)
    values: list[dict[str, str]] = []
    if fallback:
        raw = recovery.get(fallback)
        if isinstance(raw, str) and raw.strip():
            values.append({"path": fallback, "value": raw.strip()})
    for container_name in ("use_scope", "research_layers", "six_layers"):
        container = recovery.get(container_name)
        if not isinstance(container, Mapping):
            continue
        raw = container.get(section)
        if isinstance(raw, Mapping):
            for field in ("state", "status", "finding"):
                state_value = raw.get(field)
                if isinstance(state_value, str) and state_value.strip():
                    values.append({"path": f"{container_name}.{section}.{field}",
                                   "value": state_value.strip()})
        elif isinstance(raw, str) and raw.strip():
            values.append({"path": f"{container_name}.{section}", "value": raw.strip()})
    conflicts = recovery.get("state_conflicts")
    conflict_key = fallback or section
    recorded = conflicts.get(conflict_key) if isinstance(conflicts, Mapping) else None
    if isinstance(recorded, list):
        values.extend(item for item in recorded if isinstance(item, dict)
                      and isinstance(item.get("value"), str) and item.get("value").strip())
    distinct = {item["value"].upper() for item in values}
    if len(distinct) > 1:
        return None, values, True
    return (values[0]["value"] if values else None), values, False


def _current_scope_class(state: str | None) -> str:
    if not state:
        return "CANNOT_CONFIRM_CURRENT_APPLICABILITY"
    upper = state.upper()
    from .us_mapping_policy import CURRENT_RESEARCH_SCOPE_ALIASES, DATED_RESEARCH_SCOPE_ALIASES
    if upper in CURRENT_RESEARCH_SCOPE_ALIASES:
        return "LIMITED_SCOPE_SUPPORTED_FOR_RESEARCH"
    if upper in DATED_RESEARCH_SCOPE_ALIASES:
        return "DATED_OR_PENDING_SCOPE"
    if any(marker in upper for marker in _EXCLUDED_MARKERS):
        return "EXPLICITLY_EXCLUDED_OR_ENDED"
    if any(marker in upper for marker in _NONCURRENT_MARKERS):
        return "DATED_OR_PENDING_SCOPE"
    if upper in _SUPPORTED_CURRENT_STATES:
        return "LIMITED_SCOPE_SUPPORTED_FOR_RESEARCH"
    return "UNRECOGNIZED_CURRENT_APPLICABILITY"


def _is_noncurrent(state: str | None) -> bool:
    return _current_scope_class(state) in {
        "CANNOT_CONFIRM_CURRENT_APPLICABILITY", "DATED_OR_PENDING_SCOPE", "EXPLICITLY_EXCLUDED_OR_ENDED"
    }


def _quote_return(quote: Any) -> Decimal | None:
    if not isinstance(quote, Mapping):
        return None
    value = quote.get("change_pct")
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _quote_price(quote: Mapping[str, Any], field: str) -> Decimal | None:
    value = quote.get(field)
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed.is_finite() else None


def _research_use_explicitly_excluded(value: Any) -> bool:
    return isinstance(value, str) and "EXCLUDED" in value.strip().upper()


def _manual_quote(manual_binding: Any, symbol: str, expected_session: str,
                  cutoff: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(manual_binding, Mapping):
        return None, "MANUAL_QUOTE_SCOPE_NOT_BOUND"
    if manual_binding.get("state") == "CANNOT_CONFIRM":
        return None, str(manual_binding.get("gap") or "MANUAL_QUOTE_SCOPE_NOT_READY")
    if (manual_binding.get("scope_sha256") != MANUAL_QUOTE_SCOPE_SHA256
            or manual_binding.get("owner") not in {MANUAL_QUOTE_OWNER, SCHEDULED_QUOTE_OWNER}
            or manual_binding.get("us_session_date") != expected_session
            or manual_binding.get("state") not in {"READY", "PARTIAL"}
            or not all(valid_sha(manual_binding.get(key)) for key in
                       ("payload_sha256", "receipt_sha256", "manifest_sha256"))
            or not current({"cutoff": cutoff}, manual_binding.get("available_at"))):
        return None, "MANUAL_QUOTE_SCOPE_OWNER_OR_TIME_PIN_INVALID"
    quotes = manual_binding.get("quotes")
    quote = quotes.get(symbol) if isinstance(quotes, Mapping) else None
    if not isinstance(quote, Mapping):
        gaps = manual_binding.get("symbol_gaps")
        reason = gaps.get(symbol) if isinstance(gaps, Mapping) else None
        return None, str(reason or "MANUAL_QUOTE_SYMBOL_MISSING")
    if normalize_us_symbol(quote.get("symbol")) != symbol:
        return None, "MANUAL_QUOTE_SYMBOL_MISMATCH"
    if quote.get("session_date") != expected_session:
        return None, "MANUAL_QUOTE_SESSION_DATE_MISMATCH"
    if not isinstance(quote.get("session_time"), str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d", quote["session_time"]):
        return None, "MANUAL_QUOTE_PROVIDER_TIME_INVALID"
    try:
        official = us_equity_session(expected_session)
        if official.close_at is None:
            return None, "MANUAL_QUOTE_SESSION_NOT_OPEN"
        observed = datetime.strptime(expected_session + " " + quote["session_time"],
            "%Y%m%d %H:%M:%S").replace(tzinfo=NY)
        captured_at = timestamp(manual_binding.get("available_at"))
    except (ValueError, TypeError, OverflowError):
        return None, "MANUAL_QUOTE_SESSION_TIMESTAMP_INVALID"
    if observed < official.close_at:
        return None, "MANUAL_QUOTE_BEFORE_OFFICIAL_CLOSE"
    if observed > captured_at:
        return None, "MANUAL_QUOTE_AFTER_CAPTURE"
    last = _quote_price(quote, "last")
    previous_close = _quote_price(quote, "previous_close")
    if last is None or last <= 0 or previous_close is None or previous_close <= 0:
        return None, "MANUAL_QUOTE_PRICE_INVALID"
    value = _quote_return(quote)
    if value is None:
        return None, "MANUAL_QUOTE_RETURN_INVALID"
    try:
        calculated = (last / previous_close - Decimal(1)) * Decimal(100)
    except DecimalException:
        return None, "MANUAL_QUOTE_RETURN_INVALID"
    if not calculated.is_finite():
        return None, "MANUAL_QUOTE_RETURN_INVALID"
    try:
        return_gap = abs(value - calculated)
    except DecimalException:
        return None, "MANUAL_QUOTE_RETURN_INVALID"
    if return_gap > _QUOTE_RETURN_TOLERANCE_PP:
        return None, "MANUAL_QUOTE_RETURN_MISMATCH"
    return dict(quote), None


def manual_quote_for_symbol(manual_binding: Any, symbol: str, expected_session: str,
                            cutoff: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """Expose the same exact-scope quote validation for frozen sector baselines."""
    normalized = normalize_us_symbol(symbol)
    if not normalized:
        return None, "MANUAL_QUOTE_SYMBOL_INVALID"
    return _manual_quote(manual_binding, normalized, expected_session, cutoff)


def project_catalog_relation(item: Mapping[str, Any], *, manual_binding: Any,
                             expected_session: str, cutoff: str | None) -> dict[str, Any]:
    """Turn one original catalog row into a provenance-linked route record."""
    relation = item.get("catalog_relation") if isinstance(item, Mapping) else None
    relation = relation if isinstance(relation, Mapping) else {}
    source = relation.get("source_record")
    source = source if isinstance(source, Mapping) else {}
    recovery = relation.get("recovery_v2r1")
    recovery = recovery if isinstance(recovery, Mapping) else {}
    use_scope = recovery.get("use_scope")
    current_state, current_state_values, current_state_conflict = _state_resolution(
        recovery, "CURRENT_APPLICABILITY")
    fact_scope, fact_state_values, fact_state_conflict = _state_resolution(
        recovery, "FACT_VERIFIED_SCOPE")
    identity_scope, identity_state_values, identity_state_conflict = _state_resolution(
        recovery, "IDENTITY_SCOPE")
    excluded_scope, _, _ = _state_resolution(recovery, "EXCLUDED_SCOPE")
    pending_scope, _, _ = _state_resolution(recovery, "PENDING_SCOPE")

    relation_id = relation.get("relation_id")
    raw_relation_id = source.get("关系编号")
    relation_type = _text(source.get("type")).upper()
    raw_symbol = source.get("asset_code") or item.get("us_symbol")
    us_symbol = normalize_us_symbol(raw_symbol)
    hk_code = _text(relation.get("hk_code") or source.get("code"))
    target_symbol = _text(item.get("symbol") or item.get("target_symbol"))
    if not target_symbol and re.fullmatch(r"\d{5}", hk_code):
        target_symbol = f"HK.{hk_code}"
    source_id_matches = bool(relation_id and relation_id == raw_relation_id
        and hk_code and source.get("code") == hk_code)

    closure_values = [value for value in (_text(recovery.get("closure_status")),
        _text(relation.get("catalog_recovery_status"))) if value]
    closure_conflict = len(set(closure_values)) > 1
    closure = closure_values[0] if closure_values and not closure_conflict else ""
    route, priority = RELATION_ROUTES.get(relation_type, ("UNMAPPED_RELATION_TYPE", "UNASSESSED"))
    fact = _text(source.get("fact"))
    condition = _text(source.get("condition"))
    segment = _text(source.get("segment"))
    research_industry = _text(source.get("研究行业"))
    quote, quote_gap = _manual_quote(manual_binding, us_symbol or "", expected_session, cutoff)
    quote_return = _quote_return(quote)
    current_class = ("CONFLICTING_CURRENT_APPLICABILITY" if current_state_conflict
        else _current_scope_class(current_state))

    if not source_id_matches:
        disposition, reason = "CANNOT_CONFIRM_SOURCE_IDENTITY", "RELATION_ID_OR_HK_IDENTITY_MISMATCH"
    elif not us_symbol:
        disposition, reason = "CANNOT_CONFIRM_INVALID_US_SYMBOL", "RAW_US_SYMBOL_INVALID_NO_ALIAS_INFERRED"
    elif closure == "CLOSED_EXCLUDED_SCOPE":
        disposition, reason = "EXCLUDED_FOR_SPECIFIED_USE", "RECOVERY_SCOPE_EXPLICITLY_EXCLUDED"
    elif _research_use_explicitly_excluded(relation.get("research_use")):
        disposition, reason = "EXCLUDED_FOR_SPECIFIED_RESEARCH_USE", "CATALOG_RESEARCH_USE_EXPLICITLY_EXCLUDED"
    elif closure_conflict:
        disposition, reason = "CANNOT_CONFIRM_RECOVERY_SCOPE", "RECOVERY_CLOSURE_STATUS_CONFLICT"
    elif closure == "OPEN":
        disposition, reason = "OPEN_OBSERVATION_PENDING", "RECOVERY_SCOPE_OPEN"
    elif closure != "CLOSED_RESEARCH_SCOPE":
        disposition, reason = "CANNOT_CONFIRM_RECOVERY_SCOPE", "RECOVERY_CLOSURE_STATUS_MISSING_OR_UNKNOWN"
    elif relation_type not in RELATION_ROUTES:
        disposition, reason = "CANNOT_CONFIRM_RELATION_TYPE", "RELATION_TYPE_UNMAPPED"
    elif not fact:
        disposition, reason = "CANNOT_CONFIRM_FACT_SCOPE", "ORIGINAL_FACT_FIELD_EMPTY"
    elif fact_state_conflict or identity_state_conflict:
        disposition, reason = "CANNOT_CONFIRM_RECOVERY_STATE", "TOP_LEVEL_NESTED_RECOVERY_STATE_CONFLICT"
    elif relation_type == "BUSINESS_PEER":
        if current_class == "EXPLICITLY_EXCLUDED_OR_ENDED":
            disposition, reason = "EXCLUDED_FOR_CURRENT_PEER_USE", "CURRENT_APPLICABILITY_EXPLICITLY_EXCLUDED_OR_ENDED"
        elif current_class == "CANNOT_CONFIRM_CURRENT_APPLICABILITY":
            disposition, reason = "PEER_CURRENT_SCOPE_UNCONFIRMED", "CURRENT_APPLICABILITY_FIELD_MISSING"
        elif current_class == "CONFLICTING_CURRENT_APPLICABILITY":
            disposition, reason = "PEER_CURRENT_SCOPE_UNCONFIRMED", "CURRENT_APPLICABILITY_TOP_LEVEL_NESTED_CONFLICT"
        elif current_class == "DATED_OR_PENDING_SCOPE":
            disposition, reason = "PEER_BACKGROUND_OR_PENDING", "CURRENT_APPLICABILITY_IS_DATED_BACKGROUND_OR_PENDING"
        elif current_class == "UNRECOGNIZED_CURRENT_APPLICABILITY":
            disposition, reason = "PEER_CURRENT_SCOPE_UNCONFIRMED", "CURRENT_APPLICABILITY_ENUM_UNRECOGNIZED"
        elif not (segment or research_industry):
            disposition, reason = "PEER_SEGMENT_UNCLASSIFIED", "NO_EXACT_SEGMENT_OR_TARGET_INDUSTRY"
        else:
            disposition, reason = "ADOPTED_BUSINESS_PEER", "CLOSED_FACT_AND_CURRENT_PEER_SCOPE_SUPPORT_RESEARCH_COMPARISON"
    elif relation_type in {"SUPPLY_CHAIN", "COMMODITY_EXPOSURE", "CONTRACTUAL_RELATION",
                           "CAPEX_CYCLE", "JOINT_VENTURE", "OWNERSHIP", "TRANSACTION_EVENT"}:
        if current_class == "EXPLICITLY_EXCLUDED_OR_ENDED":
            disposition, reason = "EXCLUDED_FOR_CURRENT_ROUTE", "CURRENT_APPLICABILITY_EXPLICITLY_EXCLUDED_OR_ENDED"
        elif current_class == "CANNOT_CONFIRM_CURRENT_APPLICABILITY":
            disposition, reason = "CANNOT_CONFIRM_CURRENT_SCOPE", "CURRENT_APPLICABILITY_FIELD_UNAVAILABLE"
        elif current_class in {"CONFLICTING_CURRENT_APPLICABILITY", "UNRECOGNIZED_CURRENT_APPLICABILITY"}:
            disposition, reason = "CANNOT_CONFIRM_CURRENT_SCOPE", "CURRENT_APPLICABILITY_CONFLICT_OR_ENUM_UNRECOGNIZED"
        elif current_class == "DATED_OR_PENDING_SCOPE":
            disposition, reason = "CONDITIONAL_ROUTE_BACKGROUND_OR_PENDING", "CURRENT_APPLICABILITY_IS_DATED_BACKGROUND_OR_PENDING"
        elif not condition:
            disposition, reason = "CONDITIONAL_ROUTE_TRIGGER_UNSPECIFIED", "ORIGINAL_CONDITION_FIELD_EMPTY"
        else:
            disposition, reason = "ADOPTED_CONDITIONAL_ROUTE", (
                "CONDITION_NOT_EVALUATED;NO_ACTIVE_TRANSMISSION;CURRENT_SCOPE=" + current_class)
    elif relation_type == "SAME_ISSUER":
        if current_class == "EXPLICITLY_EXCLUDED_OR_ENDED":
            disposition, reason = "EXCLUDED_FOR_CURRENT_ISSUER_USE", "CURRENT_ISSUER_OR_INSTRUMENT_SCOPE_EXCLUDED"
        elif current_class == "CANNOT_CONFIRM_CURRENT_APPLICABILITY":
            disposition, reason = "SAME_ISSUER_CURRENT_SCOPE_UNCONFIRMED", "CURRENT_ISSUER_OR_INSTRUMENT_SCOPE_UNAVAILABLE"
        elif current_class in {"CONFLICTING_CURRENT_APPLICABILITY", "UNRECOGNIZED_CURRENT_APPLICABILITY"}:
            disposition, reason = "SAME_ISSUER_CURRENT_SCOPE_UNCONFIRMED", "CURRENT_ISSUER_OR_INSTRUMENT_SCOPE_CONFLICT_OR_UNRECOGNIZED"
        elif current_class == "DATED_OR_PENDING_SCOPE":
            disposition, reason = "SAME_ISSUER_IDENTITY_ONLY_PENDING", "CURRENT_ISSUER_OR_INSTRUMENT_SCOPE_IS_DATED_OR_PENDING"
        else:
            disposition, reason = "ADOPTED_SAME_ISSUER_CONTEXT", (
                "IDENTITY_CONTEXT_ONLY;NO_ACTIVE_PRICE_TRANSMISSION;PARITY_FX_AND_EXECUTABLE_SPREAD_NOT_INFERRED;CURRENT_SCOPE=" + current_class)
    else:
        disposition, reason = "OBSERVATION_ONLY", "SECONDARY_BACKGROUND_ROUTE"

    source_time = manual_binding.get("available_at") if isinstance(manual_binding, Mapping) else None
    source_valid = quote is not None and quote_return is not None
    return {
        "record_role": "CATALOG_OBSERVATION",
        "market": "HK_CONNECT",
        "symbol": target_symbol or None,
        "name": relation.get("hk_name") or item.get("name"),
        "catalog_relation_id": relation_id,
        "catalog_relation_sha256": item.get("catalog_relation_sha256"),
        "catalog_source_sha256": item.get("catalog_source_sha256"),
        "catalog_source_owner": "v4.manager_workbench.us_mapping_catalog",
        "catalog_hk_code": hk_code,
        "source_row": relation.get("source_row"),
        "us_symbol_raw": raw_symbol,
        "us_symbol": us_symbol,
        "relation_type": relation_type or None,
        "route": route,
        "route_priority": priority,
        "catalog_disposition": disposition,
        "catalog_disposition_reason": reason,
        "catalog_research_use": relation.get("research_use"),
        "catalog_recovery_status": closure or None,
        "catalog_recovery_current_applicability_state": current_state,
        "catalog_recovery_fact_state": recovery.get("fact_state"),
        "catalog_recovery_identity_state": recovery.get("identity_state"),
        "catalog_recovery_closure_basis": recovery.get("acceptance_closure_basis"),
        "catalog_recovery_closure_scope": recovery.get("acceptance_closure_scope"),
        "catalog_current_applicability": current_state,
        "catalog_current_applicability_state_values": current_state_values,
        "catalog_current_applicability_conflict": current_state_conflict,
        "catalog_current_scope_class": current_class,
        "catalog_fact_verified_scope": fact_scope,
        "catalog_fact_state_values": fact_state_values,
        "catalog_fact_state_conflict": fact_state_conflict,
        "catalog_identity_scope": identity_scope,
        "catalog_identity_state_values": identity_state_values,
        "catalog_identity_state_conflict": identity_state_conflict,
        "catalog_recovery_status_conflict": closure_conflict,
        "catalog_excluded_scope": excluded_scope,
        "catalog_pending_scope": pending_scope,
        "catalog_research_layers": dict(recovery.get("research_layers")) if isinstance(recovery.get("research_layers"), Mapping) else {},
        "catalog_remaining_gaps": list(recovery.get("remaining_gaps")) if isinstance(recovery.get("remaining_gaps"), list) else [],
        "catalog_segment": segment or None,
        "catalog_research_industry": research_industry or None,
        "catalog_fact": fact or None,
        "catalog_mechanism": _text(source.get("mechanism")) or None,
        "catalog_condition": condition or None,
        "catalog_direction_raw": _text(source.get("direction")) or None,
        "catalog_failure": _text(source.get("failure")) or None,
        "catalog_timescale": _text(source.get("timescale")) or None,
        "catalog_information_date": _text(source.get("information_date")) or None,
        "catalog_asset_class": _text(source.get("asset_class")) or None,
        "catalog_source_record": dict(source),
        "catalog_relation": dict(relation),
        "catalog_source_identity_verified": source_id_matches,
        "quote": quote,
        "quote_status": "VERIFIED" if source_valid else "MISSING_OR_UNVERIFIED",
        "quote_missing_reason": None if source_valid else quote_gap,
        "us_source_return_pct": format(quote_return, "f") if source_valid else None,
        "signed_hk_return_pct": None,
        "direction_sign": None,
        "condition_trigger_state": "NOT_EVALUATED" if condition else "NOT_SPECIFIED",
        "active_transmission": False,
        "source_session": expected_session,
        "available_at": source_time,
        "owner": manual_binding.get("owner") if isinstance(manual_binding, Mapping) else None,
        "source_sha256": manual_binding.get("payload_sha256") if isinstance(manual_binding, Mapping) else None,
        "receipt_sha256": manual_binding.get("receipt_sha256") if isinstance(manual_binding, Mapping) else None,
        "manifest_sha256": manual_binding.get("manifest_sha256") if isinstance(manual_binding, Mapping) else None,
        "manual_quote_scope_sha256": manual_binding.get("scope_sha256") if isinstance(manual_binding, Mapping) else None,
        "decision": "UNASSESSED",
        "reason": reason if disposition != "ADOPTED_BUSINESS_PEER" else "RESEARCH_PEER_ROUTE_ONLY",
        "reasons": [reason],
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def build_peer_baskets(catalog_rows: list[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Equal-weight available peer quotes per HK target and exact source segment."""
    buckets: dict[tuple[str, str], dict[str, list[Mapping[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in catalog_rows:
        if not isinstance(row, Mapping) or row.get("catalog_disposition") != "ADOPTED_BUSINESS_PEER":
            continue
        target = row.get("symbol")
        us_symbol = normalize_us_symbol(row.get("us_symbol"))
        segment = _text(row.get("catalog_segment")) or _text(row.get("catalog_research_industry"))
        if not isinstance(target, str) or not target or not us_symbol or not segment:
            continue
        buckets[(target, segment)][us_symbol].append(row)

    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (target, segment), members in sorted(buckets.items()):
        declared_symbols = sorted(members)
        valid_members = []
        missing = []
        for symbol in declared_symbols:
            member_rows = members[symbol]
            quote = next((row.get("quote") for row in member_rows
                          if isinstance(row.get("quote"), Mapping)
                          and _quote_return(row.get("quote")) is not None), None)
            value = _quote_return(quote)
            if value is None:
                missing.append({
                    "symbol": symbol,
                    "reason": next((row.get("quote_missing_reason") for row in member_rows
                                    if row.get("quote_missing_reason")), "QUOTE_NOT_AVAILABLE"),
                    "relation_ids": sorted({str(row.get("catalog_relation_id")) for row in member_rows
                                             if row.get("catalog_relation_id")}),
                })
                continue
            valid_members.append((symbol, value, member_rows))
        valid_count = len(valid_members)
        declared_count = len(declared_symbols)
        source_mean = (sum((item[1] for item in valid_members), Decimal(0)) / Decimal(valid_count)
                       if valid_count else None)
        positive_count = sum(value > 0 for _, value, _ in valid_members)
        negative_count = sum(value < 0 for _, value, _ in valid_members)
        zero_count = sum(value == 0 for _, value, _ in valid_members)
        if valid_count == 0:
            signal_type = "NO_QUOTED_PEER_SIGNAL"
            source_direction = "CANNOT_CONFIRM"
        elif valid_count == 1:
            signal_type = "SINGLE_PEER_REFERENCE"
            source_direction = "UP" if source_mean > 0 else "DOWN" if source_mean < 0 else "FLAT"
        else:
            signal_type = "PEER_BASKET"
            source_direction = "UP" if source_mean > 0 else "DOWN" if source_mean < 0 else "FLAT"
        conflict = "MIXED_MEMBER_SIGNS" if positive_count and negative_count else (
            "ZERO_AND_NONZERO" if zero_count and (positive_count or negative_count) else "NO_SIGN_CONFLICT")
        result[target].append({
            "route": "SUBINDUSTRY_BUSINESS_PEER",
            "peer_bucket": segment,
            "signal_type": signal_type,
            "coverage_state": "NO_COVERAGE" if not valid_count else (
                "READY" if valid_count == declared_count else "PARTIAL"),
            "declared_count": declared_count,
            "valid_count": valid_count,
            "coverage_fraction": valid_count / declared_count if declared_count else 0.0,
            "missing_symbols": missing,
            "members": [
                {
                    "symbol": symbol,
                    "return_pct": format(value, "f"),
                    "weight": 1.0 / valid_count,
                    "relation_ids": sorted({str(row.get("catalog_relation_id")) for row in rows
                                             if row.get("catalog_relation_id")}),
                }
                for symbol, value, rows in valid_members
            ],
            "relation_ids": sorted({str(row.get("catalog_relation_id")) for rows in members.values()
                                    for row in rows if row.get("catalog_relation_id")}),
            "source_mean_return_pct": format(source_mean, "f") if source_mean is not None else None,
            "source_move_direction": source_direction,
            "member_sign_conflict": conflict,
            "interpretation": "US peer-source return observation only; not HK expected return or prediction.",
        })
    return {symbol: values for symbol, values in result.items()}


def build_catalog_candidates(catalog_rows: list[Mapping[str, Any]], *,
                            monthly_pool_symbols: set[str] | None = None) -> list[dict[str, Any]]:
    """Aggregate reviewable business peers into one stable row per HK code."""
    buckets: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in catalog_rows:
        if not isinstance(row, Mapping):
            continue
        hk_code = _text(row.get("catalog_hk_code"))
        target = _text(row.get("symbol"))
        relation_id = _text(row.get("catalog_relation_id"))
        us_symbol = normalize_us_symbol(row.get("us_symbol"))
        disposition = _text(row.get("catalog_disposition"))
        segment = _text(row.get("catalog_segment")) or _text(row.get("catalog_research_industry"))
        if (not re.fullmatch(r"\d{5}", hk_code) or target != f"HK.{hk_code}"
                or not relation_id or not row.get("catalog_source_identity_verified")
                or not us_symbol or row.get("relation_type") != "BUSINESS_PEER"
                or row.get("catalog_recovery_status") != "CLOSED_RESEARCH_SCOPE"
                or row.get("catalog_recovery_status_conflict") or not _text(row.get("catalog_fact"))
                or not segment or disposition.startswith("EXCLUDED")
                or _research_use_explicitly_excluded(row.get("catalog_research_use"))):
            continue
        scope_class = _text(row.get("catalog_current_scope_class"))
        state = _text(row.get("catalog_current_applicability"))
        if disposition == "ADOPTED_BUSINESS_PEER":
            qualification = "CURRENT_SUPPORTED"
        elif (scope_class == "DATED_OR_PENDING_SCOPE" and state
                and "DATED" in state.upper() and not row.get("catalog_current_applicability_conflict")):
            qualification = "DATED_WEAK_PEER"
        else:
            qualification = "PENDING_REVIEW"
        buckets[target].append(dict(row, catalog_candidate_qualification=qualification))

    qualification_rank = {"CURRENT_SUPPORTED": 0, "DATED_WEAK_PEER": 1, "PENDING_REVIEW": 2}
    direction_rank = {"POSITIVE_WITHOUT_NEGATIVE": 0, "MIXED_POSITIVE_NEGATIVE": 1,
                      "NEGATIVE_WITHOUT_POSITIVE": 2, "FLAT_OR_UNKNOWN": 3}
    candidates = []
    for symbol, raw_relations in buckets.items():
        relations = sorted(raw_relations, key=lambda row: (
            _text(row.get("us_symbol")), _text(row.get("catalog_relation_id"))))
        qualifications = sorted({row["catalog_candidate_qualification"] for row in relations},
            key=lambda value: qualification_rank[value])
        qualification = qualifications[0]
        positive = []
        negative = []
        flat = []
        unknown = []
        for row in relations:
            value = _quote_return(row.get("quote")) if row.get("quote_status") == "VERIFIED" else None
            if value is None:
                unknown.append(row)
            elif value > 0:
                positive.append((value, row))
            elif value < 0:
                negative.append((value, row))
            else:
                flat.append(row)
        if positive and negative:
            direction_group = "MIXED_POSITIVE_NEGATIVE"
        elif positive:
            direction_group = "POSITIVE_WITHOUT_NEGATIVE"
        elif negative:
            direction_group = "NEGATIVE_WITHOUT_POSITIVE"
        else:
            direction_group = "FLAT_OR_UNKNOWN"
        positive_strength = max((value for value, _ in positive), default=None)
        risk_markers = []
        if negative:
            risk_markers.append("NEGATIVE_SOURCE_MOVE")
        if positive and negative:
            risk_markers.append("MIXED_SOURCE_DIRECTIONS")
        if unknown:
            risk_markers.append("SOURCE_QUOTE_UNVERIFIED")
        if "DATED_WEAK_PEER" in qualifications:
            risk_markers.append("DATED_RELATION_REQUIRES_REVIEW")
        if "PENDING_REVIEW" in qualifications:
            risk_markers.append("CURRENT_SCOPE_REQUIRES_REVIEW")
        hk_code = symbol[3:]
        candidates.append({
            "symbol": symbol,
            "hk_code": hk_code,
            "name": next((_text(row.get("name")) for row in relations if _text(row.get("name"))), None),
            "in_monthly_pool": symbol in (monthly_pool_symbols or set()),
            "qualification": qualification,
            "qualification_groups": qualifications,
            "direction_group": direction_group,
            "positive_source_move_strength_pct": format(positive_strength, "f") if positive_strength is not None else None,
            "positive_relation_ids": sorted(_text(row.get("catalog_relation_id")) for _, row in positive),
            "negative_relation_ids": sorted(_text(row.get("catalog_relation_id")) for _, row in negative),
            "flat_relation_ids": sorted(_text(row.get("catalog_relation_id")) for row in flat),
            "unknown_relation_ids": sorted(_text(row.get("catalog_relation_id")) for row in unknown),
            "risk_markers": risk_markers,
            "relation_count": len(relations),
            "relations": relations,
            "sort_basis": "QUALIFICATION_THEN_SOURCE_DIRECTION_THEN_POSITIVE_US_SOURCE_RETURN_DESC_THEN_HK_CODE",
        })
    candidates.sort(key=lambda row: (
        qualification_rank[row["qualification"]],
        direction_rank[row["direction_group"]],
        -(Decimal(row["positive_source_move_strength_pct"])
          if row["positive_source_move_strength_pct"] is not None else Decimal(0)),
        row["hk_code"],
    ))
    return candidates


def catalog_consumption_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [row for row in rows if isinstance(row, Mapping)]
    relation_ids = [row.get("catalog_relation_id") for row in rows]
    disposition_counts = Counter(str(row.get("catalog_disposition") or "CANNOT_CONFIRM") for row in rows)
    route_counts = Counter(str(row.get("route") or "UNMAPPED_RELATION_TYPE") for row in rows)
    return {
        "state": "READY" if len(rows) == 1003 and len(set(relation_ids)) == 1003
        and all(isinstance(value, str) and value for value in relation_ids)
        and all(isinstance(row.get("catalog_disposition"), str) and row.get("catalog_disposition")
                and isinstance(row.get("catalog_disposition_reason"), str) and row.get("catalog_disposition_reason")
                for row in rows) else "PARTIAL",
        "relation_count": len(rows),
        "unique_relation_id_count": len(set(relation_ids)),
        "quoted_relation_count": sum(row.get("quote_status") == "VERIFIED" for row in rows),
        "missing_quote_relation_count": sum(row.get("quote_status") != "VERIFIED" for row in rows),
        "disposition_counts": dict(sorted(disposition_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "mapping_policy_version": MAPPING_POLICY_VERSION,
        "mapping_policy_sha256": MAPPING_POLICY_SHA256,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


__all__ = [
    "CATALOG_SOURCE_SHA256",
    "MANUAL_QUOTE_OWNER",
    "MANUAL_QUOTE_SCOPE_SHA256",
    "MAPPING_POLICY_SHA256",
    "MAPPING_POLICY_VERSION",
    "RECOVERY_OVERLAY_SHA256",
    "build_catalog_candidates",
    "build_peer_baskets",
    "catalog_consumption_summary",
    "manual_quote_for_symbol",
    "normalize_us_symbol",
    "project_catalog_relation",
]
