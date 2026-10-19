"""Research-only projection and aggregation for the frozen 667/1,003 catalog."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping

from .common import current, valid_sha

CATALOG_SOURCE_SHA256 = "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671"
RECOVERY_OVERLAY_SHA256 = "3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c"
MANUAL_QUOTE_SCOPE_SHA256 = "6d163c286d90d1dfd00b18fa134d3f4ec308d9d2efdd51e5cbba800f3d61acf8"
MAPPING_POLICY_VERSION = "FULL_US_HK_INDUSTRY_MAPPING_CONSUMPTION_V4_20261019"
MAPPING_POLICY_SHA256 = "4e40b759f5811383d2a9ea8211dfc77662cb0094d7d863c75e54d8a5dba9a3c2"
MANUAL_QUOTE_OWNER = "research_peripheral.external_finance.manual_quote_scope"
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
_NONCURRENT_MARKERS = ("BACKGROUND", "HISTORICAL", "PENDING", "CANNOT_CONFIRM", "OPEN_CURRENT")


def normalize_us_symbol(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip(_ASCII_WHITESPACE).upper()
    return normalized if _US_SYMBOL.fullmatch(normalized) else None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _state(use_scope: Any, section: str) -> str | None:
    if not isinstance(use_scope, Mapping):
        return None
    candidates = [use_scope.get("use_scope"), use_scope.get("research_layers"), use_scope]
    for container in candidates:
        if not isinstance(container, Mapping):
            continue
        value = container.get(section)
        if isinstance(value, Mapping):
            raw = value.get("state") or value.get("status") or value.get("finding")
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        elif isinstance(value, str) and value.strip():
            return value.strip()
    fallback = {
        "CURRENT_APPLICABILITY": "current_applicability_state",
        "FACT_VERIFIED_SCOPE": "fact_state",
    }.get(section)
    if fallback:
        raw = use_scope.get(fallback)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _current_scope_class(state: str | None) -> str:
    if not state:
        return "CANNOT_CONFIRM_CURRENT_APPLICABILITY"
    upper = state.upper()
    if any(marker in upper for marker in _EXCLUDED_MARKERS):
        return "EXPLICITLY_EXCLUDED_OR_ENDED"
    if any(marker in upper for marker in _NONCURRENT_MARKERS):
        return "DATED_OR_PENDING_SCOPE"
    return "LIMITED_SCOPE_SUPPORTED_FOR_RESEARCH"


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


def _manual_quote(manual_binding: Any, symbol: str, expected_session: str,
                  cutoff: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(manual_binding, Mapping):
        return None, "MANUAL_QUOTE_SCOPE_NOT_BOUND"
    if manual_binding.get("state") == "CANNOT_CONFIRM":
        return None, str(manual_binding.get("gap") or "MANUAL_QUOTE_SCOPE_NOT_READY")
    if (manual_binding.get("scope_sha256") != MANUAL_QUOTE_SCOPE_SHA256
            or manual_binding.get("owner") != MANUAL_QUOTE_OWNER
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
    if quote.get("session_date") != expected_session:
        return None, "MANUAL_QUOTE_SESSION_DATE_MISMATCH"
    if not isinstance(quote.get("session_time"), str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d", quote["session_time"]):
        return None, "MANUAL_QUOTE_PROVIDER_TIME_INVALID"
    value = _quote_return(quote)
    if value is None:
        return None, "MANUAL_QUOTE_RETURN_INVALID"
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
    current_state = _state(recovery, "CURRENT_APPLICABILITY")
    fact_scope = _state(recovery, "FACT_VERIFIED_SCOPE")
    excluded_scope = _state(recovery, "EXCLUDED_SCOPE")
    pending_scope = _state(recovery, "PENDING_SCOPE")

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

    closure = _text(recovery.get("closure_status")) or _text(
        relation.get("catalog_recovery_status"))
    route, priority = RELATION_ROUTES.get(relation_type, ("UNMAPPED_RELATION_TYPE", "UNASSESSED"))
    fact = _text(source.get("fact"))
    condition = _text(source.get("condition"))
    segment = _text(source.get("segment"))
    research_industry = _text(source.get("研究行业"))
    quote, quote_gap = _manual_quote(manual_binding, us_symbol or "", expected_session, cutoff)
    quote_return = _quote_return(quote)
    current_class = _current_scope_class(current_state)

    if not source_id_matches:
        disposition, reason = "CANNOT_CONFIRM_SOURCE_IDENTITY", "RELATION_ID_OR_HK_IDENTITY_MISMATCH"
    elif not us_symbol:
        disposition, reason = "CANNOT_CONFIRM_INVALID_US_SYMBOL", "RAW_US_SYMBOL_INVALID_NO_ALIAS_INFERRED"
    elif closure == "CLOSED_EXCLUDED_SCOPE":
        disposition, reason = "EXCLUDED_FOR_SPECIFIED_USE", "RECOVERY_SCOPE_EXPLICITLY_EXCLUDED"
    elif closure == "OPEN":
        disposition, reason = "OPEN_OBSERVATION_PENDING", "RECOVERY_SCOPE_OPEN"
    elif closure != "CLOSED_RESEARCH_SCOPE":
        disposition, reason = "CANNOT_CONFIRM_RECOVERY_SCOPE", "RECOVERY_CLOSURE_STATUS_MISSING_OR_UNKNOWN"
    elif relation_type not in RELATION_ROUTES:
        disposition, reason = "CANNOT_CONFIRM_RELATION_TYPE", "RELATION_TYPE_UNMAPPED"
    elif not fact:
        disposition, reason = "CANNOT_CONFIRM_FACT_SCOPE", "ORIGINAL_FACT_FIELD_EMPTY"
    elif relation_type == "BUSINESS_PEER":
        if current_class == "EXPLICITLY_EXCLUDED_OR_ENDED":
            disposition, reason = "EXCLUDED_FOR_CURRENT_PEER_USE", "CURRENT_APPLICABILITY_EXPLICITLY_EXCLUDED_OR_ENDED"
        elif current_class == "CANNOT_CONFIRM_CURRENT_APPLICABILITY":
            disposition, reason = "PEER_CURRENT_SCOPE_UNCONFIRMED", "CURRENT_APPLICABILITY_FIELD_MISSING"
        elif current_class == "DATED_OR_PENDING_SCOPE":
            disposition, reason = "PEER_BACKGROUND_OR_PENDING", "CURRENT_APPLICABILITY_IS_DATED_BACKGROUND_OR_PENDING"
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
        "catalog_current_scope_class": current_class,
        "catalog_fact_verified_scope": fact_scope,
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
        "owner": MANUAL_QUOTE_OWNER if isinstance(manual_binding, Mapping) else None,
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
    "build_peer_baskets",
    "catalog_consumption_summary",
    "manual_quote_for_symbol",
    "normalize_us_symbol",
    "project_catalog_relation",
]
