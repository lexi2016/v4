"""Fixed-scope US daily-return factor candidate for retrospective research.

This module consumes the existing 33-symbol quote owner and its 24 proxy rows.
It does not rank stocks, combine factor paths into a score, or produce a buy.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

from .common import current, hk_symbol, timestamp, valid_sha

RULES_VERSION = "POSITIVE_OPERATING_RESEARCH_V1_US_DAILY_RETURN_FACTOR_V1"
EXPECTED_US_SOURCES = 33
EXPECTED_PROXY_SOURCES = 24
AGGREGATE_TOLERANCE_PP = Decimal("0.001")
AS_REPORTED_EXPOSURE_REASONS = frozenset((
    "ACCEPT_AS_OF_REPORTED_QUALITATIVE_EXPOSURE",
    "ACCEPT_AS_OF_REPORTED_QUALITATIVE_EXPOSURE_ONLY",
))
LIMITATION_REASONS = frozenset(("LIMITS", "LIMITS_REQUIRED"))
HK_INDUSTRY_MAPPING_VERSION = "HK_ISSUER_INDUSTRY_TO_US_PROXY_THEME_V1"
# Only exact provider labels backed by a reviewed canary belong here. New labels
# stay visible as unmapped until their source spelling and proxy fit are frozen.
HK_INDUSTRY_TO_PROXY = {
    "家庭电器及用品": dict(theme="消费", proxy_symbols=["XLY", "XLP"],
        mapping_type="EXACT_PROVIDER_INDUSTRY", mapping_evidence="EASTMONEY_F10_HK00300_CANARY"),
}


def _reason_tokens(reasons):
    if not isinstance(reasons, list):
        return set()
    return {value.partition(":")[0].strip() for value in reasons if isinstance(value, str)}


def _number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("US_FACTOR_NUMBER_UNKNOWN")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("US_FACTOR_NUMBER_INVALID") from None
    if not number.is_finite():
        raise ValueError("US_FACTOR_NUMBER_NONFINITE")
    return number


def _latest_time(paths):
    values = []
    for path in paths:
        value = path.get("consumer_available_at")
        if value:
            try:
                values.append(timestamp(value))
            except (ValueError, TypeError):
                continue
    return max(values).isoformat() if values else None


def _return_pct(quote, expected_session):
    if not isinstance(quote, dict) or quote.get("session_date") != expected_session:
        raise ValueError("US_FACTOR_QUOTE_SESSION_UNKNOWN")
    last = _number(quote.get("last"))
    previous_close = _number(quote.get("previous_close"))
    if last <= 0 or previous_close <= 0:
        raise ValueError("US_FACTOR_QUOTE_PRICE_INVALID")
    value = (last / previous_close - Decimal(1)) * Decimal(100)
    saved = _number(quote.get("change_pct"))
    if abs(value - saved) > AGGREGATE_TOLERANCE_PP:
        raise ValueError("US_FACTOR_QUOTE_RETURN_MISMATCH")
    return value


def _proxy_returns(records, expected_session, context):
    """Verify each configured proxy from all of its fixed owner members."""
    quotes = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        symbol = record.get("us_symbol")
        if isinstance(symbol, str) and symbol not in quotes:
            quotes[symbol] = record.get("quote")

    owner_rows = {}
    malformed = set()
    source_bad = set()
    source_identities = {}
    source_details = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        for metadata in record.get("proxy_metadata") or []:
            if not isinstance(metadata, dict):
                continue
            owner_row = metadata.get("owner_row")
            if not isinstance(owner_row, dict):
                continue
            label = owner_row.get("label")
            if not isinstance(label, str) or not label:
                continue
            identity = (metadata.get("owner"), metadata.get("source_sha256"))
            if (metadata.get("owner") != record.get("owner")
                    or metadata.get("source_sha256") != record.get("source_sha256")
                    or not valid_sha(metadata.get("source_sha256"))
                    or not current(context, metadata.get("available_at"))):
                source_bad.add(label)
            if label in source_identities and source_identities[label] != identity:
                source_bad.add(label)
            source_identities[label] = identity
            source_details[label] = dict(owner=identity[0], source_sha256=identity[1],
                available_at=metadata.get("available_at"))
            if label in owner_rows and owner_rows[label] != owner_row:
                malformed.add(label)
            owner_rows[label] = owner_row

    results = {}
    for label, owner_row in owner_rows.items():
        try:
            if label in malformed:
                raise ValueError("US_FACTOR_PROXY_OWNER_ROW_CONFLICT")
            if label in source_bad:
                raise ValueError("US_FACTOR_PROXY_SOURCE_IDENTITY_OR_TIME_INVALID")
            mapping_type = owner_row.get("mapping_type")
            if mapping_type not in ("etf_proxy", "etf_basket_proxy", "stock_basket_proxy"):
                raise ValueError("US_FACTOR_PROXY_TYPE_INVALID")
            members = owner_row.get("proxy_symbols")
            if (not isinstance(members, list) or not members or len(members) != len(set(members))
                    or any(not isinstance(member, str) or not member for member in members)):
                raise ValueError("US_FACTOR_PROXY_MEMBERS_INVALID")
            if mapping_type == "etf_proxy" and len(members) != 1:
                raise ValueError("US_FACTOR_SINGLE_PROXY_MEMBER_INVALID")
            available = owner_row.get("available_symbols")
            requested = owner_row.get("requested_symbols")
            if not isinstance(available, list):
                raise ValueError("US_FACTOR_PROXY_MEMBER_COVERAGE_UNKNOWN")
            if isinstance(requested, list) and requested != members:
                raise ValueError("US_FACTOR_PROXY_REQUESTED_MEMBERS_MISMATCH")
            if set(available) != set(members):
                raise ValueError("US_FACTOR_PROXY_MEMBER_MISSING")
            coverage = owner_row.get("coverage")
            if not isinstance(coverage, dict) or (coverage.get("available") != len(members)
                    or coverage.get("requested") != len(members)):
                raise ValueError("US_FACTOR_PROXY_COVERAGE_INCOMPLETE")
            if owner_row.get("status") not in ("READY", "OK", "SUCCESS"):
                raise ValueError("US_FACTOR_PROXY_OWNER_NOT_READY")
            dates = owner_row.get("quote_session_dates")
            if (not isinstance(dates, list) or not dates
                    or any(day != expected_session for day in dates)):
                raise ValueError("US_FACTOR_PROXY_SESSION_MISMATCH")
            member_values = [_return_pct(quotes.get(member), expected_session) for member in members]
            calculated = sum(member_values, Decimal(0)) / Decimal(len(members))
            saved = _number(owner_row.get("change_pct"))
            if abs(calculated - saved) > AGGREGATE_TOLERANCE_PP:
                raise ValueError("US_FACTOR_PROXY_OWNER_AGGREGATE_MISMATCH")
            results[label] = dict(status="VERIFIED", return_pct=str(calculated),
                mapping_type=mapping_type, proxy_symbols=list(members),
                owner_change_pct=str(saved), owner_status=owner_row.get("status"),
                quote_session_dates=list(dates), **source_details.get(label, {}))
        except (ValueError, TypeError, InvalidOperation, KeyError) as error:
            results[label] = dict(status="UNASSESSED", reason=str(error) if isinstance(error, ValueError)
                else "US_FACTOR_PROXY_INVALID", mapping_type=owner_row.get("mapping_type"),
                proxy_symbols=owner_row.get("proxy_symbols"))
    return results, owner_rows


def _industry_asof_date(value):
    if not isinstance(value, str) or not value:
        return None, value is None
    try:
        if len(value) == 8 and value.isascii() and value.isdigit():
            return datetime.strptime(value, "%Y%m%d").date(), True
        if len(value) == 10:
            parsed = date.fromisoformat(value)
            return parsed if parsed.isoformat() == value else None, parsed.isoformat() == value
        parsed_time = timestamp(value)
        return parsed_time.date(), True
    except (ValueError, TypeError):
        return None, False


def _industry_time_state(artifact, context):
    captured = artifact.get("captured_at")
    try:
        captured_at = timestamp(captured)
        cutoff = timestamp(context.get("cutoff"))
        target = datetime.strptime(context.get("target_date", ""), "%Y%m%d").date()
    except (ValueError, TypeError):
        return False, "CLASSIFICATION_CAPTURE_OR_CUTOFF_UNKNOWN", captured
    if captured_at > cutoff:
        return False, "CLASSIFICATION_CAPTURE_AFTER_CUTOFF", captured_at.isoformat()
    source_asof = artifact.get("source_asof")
    asof_date, asof_valid = _industry_asof_date(source_asof)
    if not asof_valid:
        return False, "CLASSIFICATION_SOURCE_ASOF_INVALID", captured_at.isoformat()
    if source_asof is not None and asof_date == target:
        return True, "SOURCE_ASOF_TARGET_DATE", captured_at.isoformat()
    local_capture_date = captured_at.date()
    if source_asof is None and local_capture_date == target:
        return True, "OBSERVED_BY_TARGET_CUTOFF", captured_at.isoformat()
    return False, "RETROSPECTIVE_PIT_UNKNOWN", captured_at.isoformat()


def _hk_industry_candidates(context, payload, proxy_returns):
    """Project exact-date issuer classifications into a separate research funnel."""
    binding = payload.get("hk_industry_classification") if isinstance(payload, dict) else None
    scope_count = payload.get("hk_scope_count") if isinstance(payload, dict) else None
    scope_codes = payload.get("hk_scope_codes") if isinstance(payload, dict) else None
    if not isinstance(scope_codes, list) and isinstance(binding, dict):
        scope_codes = binding.get("hk_scope_codes")
    scope_codes = sorted(scope_codes) if isinstance(scope_codes, list) and all(hk_symbol(code) for code in scope_codes) else []
    if type(scope_count) is not int and scope_codes:
        scope_count = len(scope_codes)
    identity = payload.get("hk_industry_identity") if isinstance(payload, dict) else None
    if not isinstance(identity, dict) and isinstance(binding, dict):
        identity = binding.get("hk_industry_identity")
    master_codes = identity.get("master_codes") if isinstance(identity, dict) else None
    master_codes_ok = (isinstance(master_codes, list) and bool(master_codes)
        and all(hk_symbol(code) for code in master_codes)
        and len(master_codes) == len(set(master_codes)))
    master_codes = sorted(master_codes) if master_codes_ok else []
    identity_source_day = ((context.get("source_sessions") or {}).get("hk_price")
        or (context.get("source_sessions") or {}).get("HK_PRICE"))
    actual_master_codes_sha = sha256(json.dumps(
        {"market": "HK_CONNECT", "codes": master_codes}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() if master_codes else None
    master_identity_ok = (isinstance(identity, dict) and identity.get("status") == "READY" and master_codes_ok
        and type(identity.get("master_scope_count")) is int
        and identity.get("master_scope_count") == len(master_codes)
        and identity.get("identity_codes_sha256") == actual_master_codes_sha
        and isinstance(identity.get("owner"), str) and bool(identity.get("owner"))
        and identity.get("source_date") == identity_source_day
        and current(context, identity.get("available_at"))
        and valid_sha(identity.get("artifact_sha256")) and valid_sha(identity.get("manifest_sha256")))
    identity_gap_symbols = sorted(set(scope_codes) - set(master_codes)) if master_identity_ok else list(scope_codes)
    identity_resolved_count = max(0, len(scope_codes) - len(identity_gap_symbols)) if scope_codes else None
    identity_gap_count = len(identity_gap_symbols) if scope_codes else None
    identity_gap = (None if master_identity_ok and not identity_gap_symbols else
        identity.get("gap") if isinstance(identity, dict) and identity.get("gap") else
        "HK_SECURITY_MASTER_IDENTITY_SCOPE_GAP" if master_identity_ok else "HK_SECURITY_MASTER_IDENTITY_UNAVAILABLE")
    empty_summary = dict(display_only=True, mapping_version=HK_INDUSTRY_MAPPING_VERSION,
        source_status=(binding or {}).get("status", "UNAVAILABLE"), source_gap=(binding or {}).get("gap"),
        target_date=context.get("target_date"), scope_count=scope_count if type(scope_count) is int else None,
        classified_count=0, mapping_covered_count=0, industry_unmapped_count=0,
        classification_missing_count=scope_count if type(scope_count) is int else None,
        triggered_unique_stock_count=0, unknown_unique_stock_count=scope_count if type(scope_count) is int else None,
        candidate_row_count=0,
        decision_counts={"CONDITIONAL_WATCH": 0, "NOT_SELECTED": 0,
            "UNASSESSED": scope_count if type(scope_count) is int else None},
        source_asof=None, source_asof_status="UNKNOWN", captured_at=None,
        temporal_status="CANNOT_CONFIRM", historical_pit_verified=False,
        membership_codes_sha256=payload.get("membership_codes_sha256") if isinstance(payload, dict) else None,
        membership_artifact_sha256=payload.get("membership_artifact_sha256") if isinstance(payload, dict) else None,
        identity_resolved_count=identity_resolved_count, identity_gap_count=identity_gap_count,
        identity_gap_symbols=identity_gap_symbols, identity_gap=identity_gap,
        security_master_scope_count=identity.get("master_scope_count") if master_identity_ok else None,
        security_master_owner=identity.get("owner") if master_identity_ok else None,
        security_master_source_date=identity.get("source_date") if master_identity_ok else None,
        security_master_available_at=identity.get("available_at") if master_identity_ok else None,
        security_master_artifact_sha256=identity.get("artifact_sha256") if master_identity_ok else None,
        security_master_manifest_sha256=identity.get("manifest_sha256") if master_identity_ok else None,
        source_artifact_sha256=None, source_response_count=None, out_of_scope_row_count=None,
        bad_row_count=None)
    if not isinstance(binding, dict) or binding.get("status") != "READY":
        return [], empty_summary
    artifact = binding.get("artifact")
    if not isinstance(artifact, dict):
        empty_summary.update(source_status="INVALID", source_gap="HK_INDUSTRY_CLASSIFICATION_ARTIFACT_INVALID")
        return [], empty_summary

    codes = binding.get("hk_scope_codes")
    expected_scope_count = binding.get("hk_scope_count")
    expected_codes_sha = binding.get("membership_codes_sha256")
    expected_member_sha = binding.get("membership_artifact_sha256")
    actual_codes_sha = sha256(json.dumps(
        {"market": "HK_CONNECT", "codes": sorted(codes) if isinstance(codes, list) else []},
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    rows = artifact.get("rows")
    artifact_sha = binding.get("artifact_sha256")
    identity_ok = (
        artifact.get("schema_version") == "v4.manager_workbench.hk_industry_classification.v1"
        and artifact.get("source_id") == "EASTMONEY_F10_RPT_HKF10_INFO_ORGPROFILE"
        and artifact.get("market") == "HK_CONNECT"
        and artifact.get("scope_type") == "HK_CONNECT_FULL_MARKET"
        and artifact.get("target_date") == context.get("target_date")
        and type(expected_scope_count) is int and expected_scope_count >= 0
        and isinstance(codes, list) and len(codes) == expected_scope_count
        and len(set(codes)) == len(codes) and all(hk_symbol(code) for code in codes)
        and artifact.get("scope_count") == expected_scope_count
        and artifact.get("membership_codes_sha256") == expected_codes_sha
        and expected_codes_sha == actual_codes_sha
        and artifact.get("membership_artifact_sha256") == expected_member_sha
        and valid_sha(expected_member_sha) and valid_sha(artifact_sha)
        and isinstance(binding.get("membership_owner"), str) and bool(binding.get("membership_owner"))
        and current(context, binding.get("membership_available_at"))
        and isinstance(binding.get("membership_effective_from"), str)
        and isinstance(binding.get("membership_effective_through"), str)
        and binding["membership_effective_from"] <= context.get("target_date", "") <= binding["membership_effective_through"]
        and isinstance(rows, list)
        and isinstance(binding.get("owner"), str) and bool(binding.get("owner"))
        and valid_sha(artifact.get("batch_response_sha256"))
        and isinstance(artifact.get("source_url"), str) and bool(artifact.get("source_url"))
    )
    source_asof = artifact.get("source_asof")
    if artifact.get("source_asof_status") != ("UNKNOWN" if source_asof is None else "KNOWN"):
        identity_ok = False
    if not identity_ok:
        empty_summary.update(source_status="INVALID", source_gap="HK_INDUSTRY_CLASSIFICATION_SCOPE_OR_IDENTITY_INVALID",
            source_asof=source_asof, captured_at=artifact.get("captured_at"),
            source_artifact_sha256=artifact_sha)
        return [], empty_summary

    time_ok, temporal_status, captured_at = _industry_time_state(artifact, context)
    code_set = set(codes)
    by_symbol = {}
    duplicate_symbols = set()
    out_of_scope = 0
    bad_row_count = 0
    for item in rows:
        if not isinstance(item, dict):
            bad_row_count += 1
            continue
        symbol = item.get("symbol")
        if not hk_symbol(symbol):
            bad_row_count += 1
            continue
        if symbol not in code_set:
            out_of_scope += 1
            continue
        if symbol in by_symbol:
            duplicate_symbols.add(symbol)
            bad_row_count += 1
        else:
            by_symbol[symbol] = item

    results = []
    counts = {d: 0 for d in ("CONDITIONAL_WATCH", "NOT_SELECTED", "UNASSESSED")}
    classified = mapped = missing = unmapped = triggered = 0
    expected_session = (context.get("source_sessions") or {}).get("us") or (context.get("source_sessions") or {}).get("US")
    member = dict(verification="VERIFIED", eligible=True, owner=binding.get("membership_owner"),
        sha256=expected_member_sha, available_at=binding.get("membership_available_at"),
        effective_from=binding.get("membership_effective_from"),
        effective_through=binding.get("membership_effective_through"), version=binding.get("membership_version"))
    master_code_set = set(master_codes)
    for symbol in sorted(codes):
        symbol_identity_ok = master_identity_ok and symbol in master_code_set
        item = by_symbol.get(symbol)
        source_industry = item.get("source_industry") if item else None
        source_name = item.get("issuer_name") if item else None
        row_sha = item.get("source_row_sha256") if item else None
        response_sha = item.get("source_response_sha256") if item else None
        response_ref = item.get("source_response_ref") if item else None
        classification_present = isinstance(source_industry, str) and bool(source_industry.strip())
        if classification_present:
            classified += 1
        theme_info = HK_INDUSTRY_TO_PROXY.get(source_industry) if classification_present else None
        conditions = []
        reason = ""
        decision = "UNASSESSED"
        proxy = None
        exposure = None
        if not time_ok:
            conditions.append(temporal_status)
        if symbol in duplicate_symbols:
            conditions.append("CLASSIFICATION_ROW_DUPLICATE")
        if item is None or not classification_present:
            missing += 1
            conditions.append("CLASSIFICATION_MISSING")
            reason = "HK_INDUSTRY_CLASSIFICATION_MISSING"
        elif not valid_sha(row_sha) or not valid_sha(response_sha) or not isinstance(response_ref, str) or not response_ref:
            conditions.append("CLASSIFICATION_RAW_PROVENANCE_INVALID")
            reason = "HK_INDUSTRY_CLASSIFICATION_PROVENANCE_UNVERIFIED"
        elif symbol in duplicate_symbols:
            reason = "HK_INDUSTRY_CLASSIFICATION_DUPLICATE"
        elif not theme_info:
            unmapped += 1
            conditions.append("INDUSTRY_UNMAPPED_TO_FROZEN_24_PROXY_MAP")
            reason = "HK_INDUSTRY_PROXY_MAPPING_UNAVAILABLE"
        else:
            mapped += 1
            theme = theme_info["theme"]
            proxy = proxy_returns.get(theme)
            if not isinstance(proxy, dict) or proxy.get("status") != "VERIFIED":
                conditions.append(proxy.get("reason", "THEME_PROXY_RETURN_UNASSESSED") if isinstance(proxy, dict)
                    else "THEME_PROXY_OWNER_ROW_MISSING")
            elif item.get("mapping_type") != theme_info["mapping_type"]:
                conditions.append("INDUSTRY_MAPPING_TYPE_MISMATCH")
            else:
                try:
                    exposure = _number(proxy.get("return_pct"))
                except ValueError:
                    conditions.append("THEME_PROXY_RETURN_INVALID")
            if not time_ok:
                conditions.append(temporal_status)
            if symbol in duplicate_symbols:
                conditions.append("CLASSIFICATION_ROW_DUPLICATE")
            if not conditions:
                if exposure is not None and exposure > 0:
                    decision, reason = "CONDITIONAL_WATCH", "HK_INDUSTRY_US_PROXY_RETURN_POSITIVE_RESEARCH_ONLY"
                    triggered += 1
                elif exposure is not None:
                    decision, reason = "NOT_SELECTED", "HK_INDUSTRY_US_PROXY_RETURN_NOT_POSITIVE"
                else:
                    decision, reason = "UNASSESSED", "HK_INDUSTRY_PROXY_RETURN_UNASSESSED"
            elif temporal_status in conditions:
                reason = "HK_INDUSTRY_RETROSPECTIVE_PIT_UNKNOWN"
            elif not time_ok:
                reason = "HK_INDUSTRY_RETROSPECTIVE_PIT_UNKNOWN"
        if not symbol_identity_ok:
            if decision == "CONDITIONAL_WATCH":
                triggered -= 1
            decision, reason = "UNASSESSED", "UNASSESSED_IDENTITY"
            conditions.append("UNASSESSED_IDENTITY")
        counts[decision] += 1
        theme = theme_info.get("theme") if theme_info else None
        results.append(dict(market="HK_CONNECT", symbol=symbol, name=source_name,
            decision=decision, reason=reason or "HK_INDUSTRY_RESEARCH_PATH_UNASSESSED",
            conditions=list(dict.fromkeys(conditions)), invalidation_conditions=[],
            risks=["RESEARCH_ONLY", "NOT_A_SELECTION_SCORE", "NOT_PIT_VERIFIED"], metrics={},
            evidence_ids=list(binding.get("evidence_ids") or []), membership=member if member.get("owner") else None,
            subtype="HK_INDUSTRY_PROXY_FACTOR_CANDIDATE", factor_rules_version=RULES_VERSION,
            source_industry=source_industry, theme=theme,
            mapping_type=theme_info.get("mapping_type") if theme_info else None,
            mapping_version=HK_INDUSTRY_MAPPING_VERSION,
            mapping_evidence=theme_info.get("mapping_evidence") if theme_info else None,
            return_pct=str(exposure) if exposure is not None else None, return_unit="PERCENT",
            source_session=expected_session, proxy_symbols=theme_info.get("proxy_symbols") if theme_info else None,
            proxy_status=proxy.get("status") if isinstance(proxy, dict) else "UNASSESSED",
            proxy_owner=proxy.get("owner") if isinstance(proxy, dict) else None,
            proxy_source_sha256=proxy.get("source_sha256") if isinstance(proxy, dict) else None,
            source_owner=binding.get("owner"), source_id=artifact.get("source_id"),
            source_artifact_sha256=artifact_sha, source_batch_response_sha256=artifact.get("batch_response_sha256"),
            source_response_sha256=response_sha, source_response_ref=response_ref,
            source_row_sha256=row_sha, source_asof=source_asof,
            identity_status="VERIFIED" if symbol_identity_ok else "UNASSESSED_IDENTITY",
            security_master_owner=identity.get("owner") if master_identity_ok else None,
            security_master_source_date=identity.get("source_date") if master_identity_ok else None,
            security_master_artifact_sha256=identity.get("artifact_sha256") if master_identity_ok else None,
            security_master_manifest_sha256=identity.get("manifest_sha256") if master_identity_ok else None,
            source_asof_status=artifact.get("source_asof_status"), captured_at=artifact.get("captured_at"),
            temporal_status=(temporal_status if time_ok else "RETROSPECTIVE_PIT_UNKNOWN"),
            historical_pit_verified=False, available_at=captured_at,
            research_effectiveness="UNVALIDATED"))
    summary = dict(display_only=True, mapping_version=HK_INDUSTRY_MAPPING_VERSION,
        source_status="READY" if time_ok and not (missing or out_of_scope or bad_row_count
            or duplicate_symbols or identity_gap_symbols)
            else "PARTIAL" if time_ok else "RETROSPECTIVE_PIT_UNKNOWN",
        source_gap=(temporal_status if not time_ok else identity_gap), target_date=context.get("target_date"),
        scope_count=expected_scope_count, classified_count=classified,
        mapping_covered_count=mapped, industry_unmapped_count=unmapped,
        classification_missing_count=missing, triggered_unique_stock_count=triggered,
        unknown_unique_stock_count=counts["UNASSESSED"],
        candidate_row_count=triggered, decision_counts=counts,
        source_asof=source_asof, source_asof_status=artifact.get("source_asof_status"),
        captured_at=artifact.get("captured_at"), temporal_status=temporal_status,
        historical_pit_verified=False, membership_codes_sha256=expected_codes_sha,
        membership_artifact_sha256=expected_member_sha, source_artifact_sha256=artifact_sha,
        source_response_count=len({item.get("source_response_sha256") for item in rows if isinstance(item, dict)}),
        out_of_scope_row_count=out_of_scope, bad_row_count=bad_row_count,
        identity_resolved_count=identity_resolved_count, identity_gap_count=identity_gap_count,
        identity_gap_symbols=identity_gap_symbols, identity_gap=identity_gap,
        security_master_scope_count=identity.get("master_scope_count") if master_identity_ok else None,
        security_master_owner=identity.get("owner") if master_identity_ok else None,
        security_master_source_date=identity.get("source_date") if master_identity_ok else None,
        security_master_available_at=identity.get("available_at") if master_identity_ok else None,
        security_master_artifact_sha256=identity.get("artifact_sha256") if master_identity_ok else None,
        security_master_manifest_sha256=identity.get("manifest_sha256") if master_identity_ok else None)
    return results, summary


def _reviewed_facts(payload, context):
    candidate = payload.get("candidate") if isinstance(payload, dict) else None
    review = payload.get("review") if isinstance(payload, dict) else None
    if not isinstance(candidate, dict) or not isinstance(review, dict):
        return [], (payload.get("gap") if isinstance(payload, dict) else None) or "US_FACTOR_PAIRED_REVIEW_UNAVAILABLE"
    candidate_sha = payload.get("candidate_sha256")
    review_sha = payload.get("review_sha256")
    if not valid_sha(candidate_sha) or not valid_sha(review_sha):
        return [], "US_FACTOR_ARTIFACT_IDENTITY_UNKNOWN"
    if (candidate.get("schema_version") != "v4.manager_workbench.us_factor_exposure_candidate.v1"
            or candidate.get("target_date") != context.get("target_date")
            or review.get("schema") != "v4.manager_workbench.us_factor_exposure_review.v1"
            or review.get("artifact_sha256") != candidate_sha
            or review.get("review_owner") is None
            or not current(context, review.get("reviewed_at"))
            or candidate.get("RESEARCH_ONLY") is not True
            or candidate.get("production_allowed") is not False
            or candidate.get("orders_sent") is not False
            or candidate.get("buy_gate_updated") is not False):
        return [], "US_FACTOR_PAIRED_REVIEW_IDENTITY_INVALID"
    facts = candidate.get("rows")
    decisions = review.get("rows")
    if not isinstance(facts, list) or not isinstance(decisions, list):
        return [], "US_FACTOR_PAIRED_ROWS_INVALID"
    fact_ids = [fact.get("id") for fact in facts if isinstance(fact, dict)]
    reviewed_ids = [entry.get("id") for entry in decisions if isinstance(entry, dict)]
    if (len(fact_ids) != len(facts) or len(set(fact_ids)) != len(fact_ids)
            or len(reviewed_ids) != len(decisions) or len(set(reviewed_ids)) != len(reviewed_ids)
            or set(fact_ids) != set(reviewed_ids)):
        return [], "US_FACTOR_PAIRED_ROW_COVERAGE_INVALID"
    by_id = {entry["id"]: entry for entry in decisions}
    return [(fact, by_id[fact["id"]]) for fact in facts], None


def _fact_scope(fact, decision, context, proxy_returns, target_membership):
    gaps = []
    if context.get("phase") != "RETROSPECTIVE":
        gaps.append("US_FACTOR_RETROSPECTIVE_ONLY")
    if decision.get("decision") != "ACCEPT":
        gaps.append("EXPOSURE_NOT_INDEPENDENTLY_ACCEPTED")
    if not isinstance(decision.get("reasons"), list) or not decision.get("reasons"):
        gaps.append("INDEPENDENT_REVIEW_SCOPE_REASON_MISSING")
    if not hk_symbol(fact.get("symbol")):
        gaps.append("HK_SYMBOL_IDENTITY_INVALID")
    if not valid_sha(fact.get("id")):
        gaps.append("EXPOSURE_FACT_ID_INVALID")
    if not isinstance(fact.get("statement"), str) or not fact.get("statement"):
        gaps.append("ORIGINAL_STATEMENT_MISSING")
    if not valid_sha(fact.get("source_raw_sha256")) or not valid_sha(fact.get("source_row_sha256")):
        gaps.append("ORIGINAL_SOURCE_HASH_MISSING")
    statement = fact.get("statement")
    statement_sha = fact.get("statement_sha256")
    if (not isinstance(statement, str) or not valid_sha(statement_sha)
            or sha256(statement.encode("utf-8")).hexdigest() != statement_sha):
        gaps.append("ORIGINAL_STATEMENT_IDENTITY_INVALID")
    span = fact.get("span")
    if (not isinstance(span, dict) or type(span.get("start")) is not int
            or type(span.get("end")) is not int or span["start"] < 0
            or span["end"] <= span["start"]):
        gaps.append("ORIGINAL_STATEMENT_SPAN_INVALID")
    if not isinstance(fact.get("source_ref"), dict) or not fact.get("source_ref"):
        gaps.append("ORIGINAL_SOURCE_REFERENCE_MISSING")
    else:
        source_ref = fact["source_ref"]
        if (not source_ref.get("path") or not source_ref.get("receipt_path")
                or not source_ref.get("raw_article_field")
                or not valid_sha(source_ref.get("receipt_raw_sha256"))
                or not valid_sha(source_ref.get("archive_metadata_raw_sha256"))):
            gaps.append("ORIGINAL_SOURCE_RECEIPT_IDENTITY_INCOMPLETE")
    subject = fact.get("subject_verification")
    if (not isinstance(subject, dict)
            or subject.get("status") != "CURRENT_OWNER_NAME_AND_CONNECT_VERIFIED_ORIGINAL_SENTENCE_ANCHORED"
            or subject.get("target_date") != context.get("target_date")
            or subject.get("in_current_692") is not True
            or not isinstance(subject.get("identity_refs"), list) or not subject.get("identity_refs")):
        gaps.append("EXPOSURE_SUBJECT_IDENTITY_UNVERIFIED")
    if not current(context, fact.get("source_available_at")):
        gaps.append("ORIGINAL_SOURCE_AVAILABLE_AT_UNKNOWN_OR_LATE")
    for field in ("publication_at", "collected_at", "archive_recorded_at"):
        value = fact.get(field)
        if value is not None and not current(context, value):
            gaps.append("ORIGINAL_SOURCE_TIME_AFTER_CUTOFF")
    if fact.get("target_date") not in (None, context.get("target_date")):
        gaps.append("EXPOSURE_TARGET_DATE_MISMATCH")
    start, end = fact.get("fact_effective_from"), fact.get("fact_effective_through")
    if start is not None or end is not None:
        if (not isinstance(start, str) or not isinstance(end, str)
                or not start.isdigit() or not end.isdigit()
                or not (start <= context["target_date"] <= end)):
            gaps.append("EXPOSURE_EXPLICIT_PERIOD_DOES_NOT_COVER_TARGET")
    else:
        # An independently accepted as-reported fact may remain useful in this
        # retrospective research run, but its unknown historical period stays visible.
        if fact.get("fact_effective_status") != "UNKNOWN":
            gaps.append("EXPOSURE_EFFECTIVE_PERIOD_UNCLEAR")
        reasons = _reason_tokens(decision.get("reasons"))
        if (not reasons.intersection(AS_REPORTED_EXPOSURE_REASONS)
                or not reasons.intersection(LIMITATION_REASONS)):
            gaps.append("AS_REPORTED_RETROSPECTIVE_SCOPE_NOT_EXPLICIT")
    member = target_membership if isinstance(target_membership, dict) else None
    if (not isinstance(member, dict) or member.get("verification") != "VERIFIED"
            or member.get("eligible") is not True or not valid_sha(member.get("sha256"))
            or not member.get("owner") or not current(context, member.get("available_at"))
            or not isinstance(member.get("effective_from"), str)
            or not isinstance(member.get("effective_through"), str)
            or not (member["effective_from"] <= context["target_date"] <= member["effective_through"])):
        gaps.append("TARGET_DATE_CONNECT_ELIGIBILITY_UNVERIFIED")
    theme = fact.get("theme")
    proxy = proxy_returns.get(theme)
    if not isinstance(proxy, dict):
        gaps.append("THEME_PROXY_OWNER_ROW_MISSING")
    elif proxy.get("status") != "VERIFIED":
        gaps.append(proxy.get("reason") or "THEME_PROXY_RETURN_UNASSESSED")
    elif fact.get("proxy_symbols") != proxy.get("proxy_symbols"):
        gaps.append("THEME_PROXY_MEMBERSHIP_MISMATCH")
    return gaps, proxy


def run_us_factor(context, batch, payload):
    """Return one factor row per HK stock plus scope-preserving summary fields."""
    paired, pair_gap = _reviewed_facts(payload, context)
    expected_session = (context.get("source_sessions") or {}).get("us") or (context.get("source_sessions") or {}).get("US")
    proxy_returns, owner_rows = _proxy_returns(batch.get("records") or [], expected_session, context)
    grouped = {}
    path_count = 0
    for fact, review in paired:
        symbol = fact.get("symbol")
        if not hk_symbol(symbol):
            continue
        target_membership = (payload.get("target_memberships") or {}).get(fact.get("id"))
        gaps, proxy = _fact_scope(fact, review, context, proxy_returns, target_membership)
        if pair_gap:
            gaps = [pair_gap]
        if (review.get("decision") == "ACCEPT" and proxy and proxy.get("status") == "VERIFIED"
                and proxy.get("return_pct") is not None and not pair_gap):
            try:
                exposure = _number(proxy.get("return_pct"))
            except ValueError:
                gaps.append("THEME_PROXY_RETURN_INVALID")
                exposure = None
        else:
            exposure = None
        if gaps or exposure is None:
            decision, reason = "UNASSESSED", "US_FACTOR_PATH_UNASSESSED"
        elif exposure > 0:
            decision, reason = "CONDITIONAL_WATCH", "US_FACTOR_DAILY_RETURN_POSITIVE_RESEARCH_ONLY"
        else:
            decision, reason = "NOT_SELECTED", "US_FACTOR_DAILY_RETURN_NOT_POSITIVE"
        review_time = (payload.get("review") or {}).get("reviewed_at") if isinstance(payload, dict) else None
        try:
            consumer_available = max(timestamp(fact.get("source_available_at")), timestamp(review_time)).isoformat()
        except (ValueError, TypeError):
            consumer_available = None
        path = dict(fact_id=fact.get("id"), theme=fact.get("theme"), decision=decision,
            reason=reason, conditions=list(gaps), return_pct=str(exposure) if exposure is not None else None,
            return_unit="PERCENT", source_session=expected_session, proxy_symbols=fact.get("proxy_symbols"),
            proxy_status=proxy.get("status") if isinstance(proxy, dict) else "UNASSESSED",
            proxy_owner_return_pct=proxy.get("owner_change_pct") if isinstance(proxy, dict) else None,
            proxy_owner=proxy.get("owner") if isinstance(proxy, dict) else None,
            proxy_source_sha256=proxy.get("source_sha256") if isinstance(proxy, dict) else None,
            proxy_available_at=proxy.get("available_at") if isinstance(proxy, dict) else None,
            source_raw_sha256=fact.get("source_raw_sha256"), source_row_sha256=fact.get("source_row_sha256"),
            statement=fact.get("statement"), statement_sha256=fact.get("statement_sha256"),
            supplemental_evidence=list(fact.get("supplemental_evidence") or []),
            source_field=fact.get("source_field"), span=fact.get("span"),
            subject_verification=fact.get("subject_verification"), source_ref=fact.get("source_ref"),
            source_available_at=fact.get("source_available_at"),
            source_available_at_basis=fact.get("source_available_at_basis"),
            publication_at=fact.get("publication_at"), collected_at=fact.get("collected_at"),
            archive_recorded_at=fact.get("archive_recorded_at"),
            consumer_available_at=consumer_available,
            fact_effective_from=fact.get("fact_effective_from"),
            fact_effective_through=fact.get("fact_effective_through"),
            fact_effective_status=fact.get("fact_effective_status"),
            review_decision=review.get("decision"), review_reasons=list(review.get("reasons") or []),
            review_owner=(payload.get("review") or {}).get("review_owner"),
            reviewed_at=(payload.get("review") or {}).get("reviewed_at"),
            historical_pit_verified=False)
        path_count += 1
        grouped.setdefault(symbol, []).append((path, target_membership))

    rows = []
    unknown_stock_count = 0
    for symbol, paths in sorted(grouped.items()):
        path_rows = [value[0] for value in paths]
        known = [path["decision"] for path in path_rows if path["decision"] != "UNASSESSED"]
        if "CONDITIONAL_WATCH" in known:
            decision = "CONDITIONAL_WATCH"
            reason = "US_FACTOR_AT_LEAST_ONE_REVIEWED_POSITIVE_PATH"
        elif path_rows and all(path["decision"] == "NOT_SELECTED" for path in path_rows):
            decision = "NOT_SELECTED"
            reason = "US_FACTOR_ALL_REVIEWED_PATHS_NOT_POSITIVE"
        else:
            decision = "UNASSESSED"
            reason = "US_FACTOR_PATHS_INCOMPLETE_OR_UNKNOWN"
            unknown_stock_count += 1
        membership = next((member for _, member in paths if isinstance(member, dict)
            and member.get("verification") == "VERIFIED" and member.get("eligible") is True), None)
        if membership is None:
            # Keep a missing/not-eligible membership from becoming a global negative.
            membership = None
        rows.append(dict(market="HK_CONNECT", symbol=symbol, name=None, decision=decision,
            reason=reason, conditions=sorted({gap for path in path_rows for gap in path["conditions"]}),
            invalidation_conditions=[], risks=["RESEARCH_ONLY", "NOT_A_SELECTION_SCORE", "NOT_PIT_VERIFIED"],
            metrics={}, evidence_ids=list(payload.get("evidence_ids") or []), membership=membership,
            available_at=_latest_time(path_rows),
            subtype="US_DAILY_RETURN_FACTOR_CANDIDATE", factor_rules_version=RULES_VERSION,
            factor_paths=path_rows, factor_path_count=len(path_rows), historical_pit_verified=False,
            research_effectiveness="UNVALIDATED"))

    candidate_rows = payload.get("candidate", {}).get("rows", []) if isinstance(payload, dict) else []
    total_scope = payload.get("hk_scope_count") if isinstance(payload, dict) else None
    proxy_verified = sum(value.get("status") == "VERIFIED" for value in proxy_returns.values())
    proxy_observed = len(owner_rows)
    factor_decision_counts = {decision: sum(row.get("decision") == decision for row in rows)
        for decision in ("SELECTED", "CONDITIONAL_WATCH", "NOT_SELECTED", "UNASSESSED")}
    factor_summary = dict(display_only=True, rules_version=RULES_VERSION,
        target_date=context.get("target_date"), phase=context.get("phase"),
        us_source_symbol_count=EXPECTED_US_SOURCES,
        proxy_source_count=proxy_observed if proxy_observed else None,
        expected_proxy_source_count=EXPECTED_PROXY_SOURCES,
        verified_proxy_source_count=proxy_verified if proxy_observed else None,
        unknown_proxy_source_count=max(0, EXPECTED_PROXY_SOURCES-proxy_verified) if proxy_observed else None,
        eligible_hk_scope_count=total_scope if type(total_scope) is int and total_scope >= 0 else None,
        unique_factor_stock_count=len(grouped), factor_path_count=path_count,
        unknown_factor_stock_count=unknown_stock_count if grouped else None,
        factor_decision_counts=factor_decision_counts,
        registry_fact_count=len(candidate_rows) if isinstance(candidate_rows, list) else None,
        paired_review_available=pair_gap is None, paired_review_gap=pair_gap,
        supplemental_evidence_receipt=(payload.get("candidate", {}).get("supplemental_evidence_receipt")
            if isinstance(payload, dict) and isinstance(payload.get("candidate"), dict) else None),
        source_session=expected_session, historical_pit_verified=False,
        combined_source_and_stock_count=None)
    industry_rows, industry_summary = _hk_industry_candidates(context, payload, proxy_returns)
    factor_summary["industry_summary"] = industry_summary
    rows.extend(industry_rows)
    return rows, factor_summary
