"""Fixed-scope US daily-return factor candidate for retrospective research.

This module consumes the existing 33-symbol quote owner and its 24 proxy rows.
It does not rank stocks, combine factor paths into a score, or produce a buy.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256

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
    return rows, factor_summary
