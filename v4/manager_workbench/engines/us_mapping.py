"""Configured US source mapping: research watch ONLY."""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
import hashlib,json
from .common import US_FACTOR_RULES_VERSION, current, hk_symbol, membership, result, row, valid_sha,timestamp
from .us_factor import run_us_factor
from .strict_us_selection import (
    run_single_day_mapping,
    cannot_confirm_single_day_mapping,
)
from ..inputs.us_universe import (
    LEGACY_UNIVERSE_VERSION,
    UNIVERSE_VERSION,
    build_legacy_us_universe_contract,
    validate_us_universe_contract,
)


def _daily_run_contract_gaps(context):
    phase = context.get("phase")
    if phase not in ("MANUAL", "NEXT_DAY"):
        return []
    contract = (context.get("scope_refs") or {}).get("US_MAPPING_RUN_CONTRACT_V1")
    if not isinstance(contract, dict):
        return ["US_MAPPING_DAILY_RUN_CONTRACT_MISSING"]
    declared_sha = contract.get("contract_sha256")
    unhashed = dict(contract)
    unhashed.pop("contract_sha256", None)
    try:
        actual_sha = hashlib.sha256(json.dumps(unhashed, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return ["US_MAPPING_DAILY_RUN_CONTRACT_INVALID"]
    gaps = []
    if (contract.get("schema_version") != "v4.manager_workbench.us_mapping_daily_run_contract.v1"
            or not valid_sha(declared_sha) or actual_sha != declared_sha):
        gaps.append("US_MAPPING_DAILY_RUN_CONTRACT_IDENTITY_INVALID")
    if (contract.get("state") != "VERIFIED" or contract.get("gaps")
            or contract.get("mode") != phase
            or contract.get("target_hk_date") != context.get("target_date")
            or contract.get("cutoff") != context.get("cutoff")
            or contract.get("us_source_session") != ((context.get("source_sessions") or {}).get("us")
                or (context.get("source_sessions") or {}).get("US"))):
        gaps.append("US_MAPPING_DAILY_RUN_CONTRACT_UNVERIFIED")
    universe = contract.get("universe")
    if (not isinstance(universe, dict) or universe.get("version") != UNIVERSE_VERSION
            or universe.get("symbol_count") != 48
            or not valid_sha(universe.get("contract_sha256"))
            or not valid_sha(universe.get("symbols_sha256"))):
        gaps.append("US_MAPPING_DAILY_UNIVERSE_PIN_INVALID")
    owners = contract.get("owners")
    quote = owners.get("quote") if isinstance(owners, dict) else None
    if (not isinstance(quote, dict) or not quote.get("owner")
            or not valid_sha(quote.get("artifact_sha256"))
            or not valid_sha(quote.get("receipt_sha256"))
            or not valid_sha(quote.get("manifest_sha256"))
            or not current(context, quote.get("available_at"))):
        gaps.append("US_MAPPING_DAILY_QUOTE_OWNER_PIN_INVALID")
    connect = owners.get("connect") if isinstance(owners, dict) else None
    if not isinstance(connect, dict) or connect.get("target_eligibility") not in ("VERIFIED", "CANNOT_CONFIRM"):
        gaps.append("US_MAPPING_DAILY_CONNECT_STATE_MISSING")
    return list(dict.fromkeys(gaps))


def _catalog_record(item):
    return isinstance(item, dict) and (
        item.get("record_role") == "CATALOG_OBSERVATION"
        or item.get("source_status") == "CATALOG_OBSERVATION"
        or item.get("catalog_relation_id") is not None)


def publication_before_cutoff(context, relation):
    """Keep DATE evidence as a date; upper bound is a check, never publication time."""
    if current(context,relation.get("published_at")):return True
    for source in relation.get("publication_evidence",[]):
        if not isinstance(source,dict) or source.get("role")!='RELATION':continue
        value=source.get("published_at")
        if source.get("precision")=='TIMESTAMP' and current(context,value):return True
        if source.get("precision")!='DATE' or not isinstance(value,str):continue
        try:
            day=date.fromisoformat(value)
            if day.isoformat()!=value:continue
            # Latest end of a civil date anywhere in UTC-12..UTC+14.
            upper=datetime.combine(day+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)+timedelta(hours=12)
            if upper<=timestamp(context['cutoff']):return True
        except (ValueError,TypeError,KeyError,OverflowError):continue
    return False


def positive_change(item):
    try:
        raw=item.get('quote',{}).get('change_pct')
        if isinstance(raw,bool) or raw is None:return None
        value=Decimal(str(raw))
        return value>0 if value.is_finite() else None
    except (InvalidOperation,TypeError,AttributeError):return None


def reviewed_diagnostic(context, item, assessment):
    try:
        original=assessment['original']
        identity=hashlib.sha256(json.dumps(original,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return (assessment.get('verification')=='REVIEWED' and identity==assessment.get('assessment_sha256')
            and assessment.get('review_owner') and current(context,assessment.get('available_at'))
            and current(context,original.get('available_at')) and original.get('us_symbol')==item.get('us_symbol')
            and original.get('status')=='ASSESSED_WITH_GAPS' and original.get('conclusion')=='CANNOT_CONFIRM')
    except (ValueError,TypeError,KeyError,AttributeError):return False


def run_us_mapping(context, batch):
    u = context["scope_refs"].get("US_MAPPING") or {}
    catalog_records = [item for item in batch["records"] if _catalog_record(item)]
    source_records = [item for item in batch["records"] if not _catalog_record(item)]
    configured = u.get("configured_symbols")
    session = u.get("source_session")
    source_session = context["source_sessions"].get("US") or context["source_sessions"].get("us")
    gaps = []
    daily_contract_gaps = _daily_run_contract_gaps(context)
    gaps.extend(daily_contract_gaps)
    declared_version = u.get("universe_version")
    universe_contract = u.get("universe_contract")
    universe_version = declared_version
    expected_symbols = None
    if universe_contract is not None:
        try:
            universe_contract = validate_us_universe_contract(universe_contract)
            universe_version = universe_contract["version"]
            if (declared_version not in (None, universe_version)
                    or u.get("universe_contract_sha256") not in (None, universe_contract["contract_sha256"])):
                gaps.append("US_UNIVERSE_CONTRACT_IDENTITY_MISMATCH")
            else:
                expected_symbols = universe_contract["symbols"]
        except (TypeError, ValueError):
            gaps.append("US_UNIVERSE_CONTRACT_INVALID")
    elif declared_version in (None, LEGACY_UNIVERSE_VERSION, "LEGACY_US_UNIVERSE_V1"):
        legacy_contract = build_legacy_us_universe_contract()
        if configured == legacy_contract["symbols"]:
            universe_version = declared_version or "LEGACY_US_UNIVERSE_V1"
            expected_symbols = legacy_contract["symbols"]
        else:
            gaps.append("US_LEGACY_FIXED_33_SCOPE_INVALID")
    elif declared_version == UNIVERSE_VERSION:
        gaps.append("US_UNIVERSE_CONTRACT_MISSING")
    else:
        gaps.append("US_UNIVERSE_CONTRACT_VERSION_UNSUPPORTED")
    expected_count = len(expected_symbols) if expected_symbols is not None else 0
    legacy_gap = universe_version in (LEGACY_UNIVERSE_VERSION, "LEGACY_US_UNIVERSE_V1")
    good_universe = (expected_symbols is not None and isinstance(configured, list)
        and configured == expected_symbols and len(configured) == len(set(configured))
        and len(configured) == expected_count and all(isinstance(x, str) and x for x in configured)
        and u.get("verification") == "VERIFIED"
        and valid_sha(u.get("sha256"))
        and u.get("universe_ref")==batch.get("universe_ref") and session == source_session
        and isinstance(session, str) and u.get("calendar_verified") is True)
    if daily_contract_gaps:
        good_universe = False
    if not good_universe:
        gaps.append("US_UNIVERSE_CONTRACT_OR_SESSION_NOT_VERIFIED")
    found = [item.get("us_symbol") for item in source_records if isinstance(item, dict)]
    if good_universe and (len(found) != expected_count or len(found) != len(configured) or set(found) != set(configured)):
        gaps.append("US_SOURCE_33_COVERAGE_INCOMPLETE" if legacy_gap else "US_SOURCE_UNIVERSE_COVERAGE_INCOMPLETE")
    rows = []
    catalog_rows = []
    source_index = 0
    for item in batch["records"]:
        is_catalog = _catalog_record(item)
        row_source_index = None if is_catalog else source_index
        if not is_catalog:
            source_index += 1
        output_rows = catalog_rows if is_catalog else rows
        if not isinstance(item, dict):
            output_rows.append(row({}, "UNASSESSED", "US_RECORD_INVALID", source_index=row_source_index));continue
        source_ok = (good_universe and item.get("us_symbol") in configured and
            item.get("source_session") == session and item.get("owner") and
            valid_sha(item.get("source_sha256")) and
            current(context, item.get("available_at")))
        relations = item.get("relations")
        if not isinstance(relations, list) or not relations:
            # No relationship is never an implicit HK winner.
            assessments=[a for a in item.get("reviewed_assessments",[]) if isinstance(a,dict)
                and reviewed_diagnostic(context,item,a)] if source_ok else []
            proxies=[p for p in item.get('proxy_metadata',[]) if isinstance(p,dict) and p.get('mapping_type') in ('etf_proxy','etf_basket_proxy')
                and p.get('source_sha256')==item.get('source_sha256') and p.get('owner')==item.get('owner')
                and current(context,p.get('available_at'))] if source_ok else []
            quote_missing_reason=item.get("quote_missing_reason")
            unmapped_disposition=item.get("unmapped_disposition")
            reason=(quote_missing_reason or ("US_RELATION_UNMAPPED_CANNOT_CONFIRM" if unmapped_disposition
                else 'US_REVIEWED_ASSESSMENT_WITH_GAPS' if assessments else 'US_ETF_THEME_PROXY_ONLY' if proxies else 'US_REVIEWED_RELATION_ABSENT'))
            observation_conditions=(['OBSERVATION_ONLY','NOT_STRICT_SELECTION']
                if quote_missing_reason or unmapped_disposition else [])
            no_relation_gaps=list(item.get("source_gaps", [])) if isinstance(item.get("source_gaps"), list) else []
            if unmapped_disposition:
                no_relation_gaps.append(unmapped_disposition.get("reason", "US_RELATION_UNMAPPED_CANNOT_CONFIRM"))
            output_rows.append(dict(row(item, "UNASSESSED", reason, source_index=row_source_index,
                                 record_role=item.get("record_role") or ("CATALOG_OBSERVATION" if is_catalog else "SOURCE_CANDIDATE"),
                                 us_symbol=item.get("us_symbol"), relation_type=None,quote=item.get('quote'),
                                 quote_missing_reason=quote_missing_reason,source_gaps=no_relation_gaps,
                                 unmapped_disposition=unmapped_disposition,conditions=observation_conditions,
                                 diagnostic_gaps=no_relation_gaps,reviewed_assessments=assessments,proxy_metadata=proxies,
                                 absence_scope='CHECKED_FROZEN_REVIEWED_RELATIONS_AND_SEED_ONLY'), symbol=None))
            continue
        for relation in relations:
            priority=relation.get("research_priority",item.get("source_status")) if isinstance(relation,dict) else None
            change=positive_change(item) if item.get("positive_change_required") else True
            positive_change_required = item.get("positive_change_required") is True
            base = dict(item, symbol=relation.get("target_symbol") if isinstance(relation, dict) else None,
                        name=relation.get("target_name") if isinstance(relation, dict) else None,
                        membership=relation.get("membership") if isinstance(relation, dict) else None,
                        evidence_ids=(item.get("evidence_ids") or []) + (relation.get("evidence_ids") or [] if isinstance(relation, dict) else []))
            extra = dict(record_role=item.get("record_role") or ("CATALOG_OBSERVATION" if is_catalog else "SOURCE_CANDIDATE"),
                         source_index=row_source_index, us_symbol=item.get("us_symbol"),
                         relation_type=relation.get("relation_type") if isinstance(relation, dict) else None,
                         source_status=priority, publication_time_gaps=relation.get("publication_time_gaps",[]) if isinstance(relation,dict) else [], research_basis=relation.get("research_basis") if isinstance(relation,dict) else None, relation_source_refs=relation.get("relation_source_refs",[]) if isinstance(relation,dict) else [], relation_limitations=relation.get("relation_limitations",[]) if isinstance(relation,dict) else [],quote=item.get("quote"), relation_status=relation.get("status") if isinstance(relation, dict) else None,
                         catalog_relation=relation.get("catalog_relation") if isinstance(relation,dict) else None,
                         catalog_relation_id=relation.get("catalog_relation_id") if isinstance(relation,dict) else None,
                         catalog_research_use=relation.get("catalog_research_use") if isinstance(relation,dict) else None,
                         catalog_recovery_status=relation.get("catalog_recovery_status") if isinstance(relation,dict) else None,
                         relation_pit_status=relation.get("pit_status") if isinstance(relation,dict) else None,quote_missing_reason=item.get("quote_missing_reason"),
                         source_gaps=item.get("source_gaps",[]),unmapped_disposition=item.get("unmapped_disposition"))
            if isinstance(relation,dict) and relation.get('priority_assessment'):
                extra.update(research_priority_reason=relation.get('research_priority_reason'),
                             priority_assessment=relation['priority_assessment'])
            quote_missing_reason=item.get("quote_missing_reason")
            if isinstance(quote_missing_reason, str) and quote_missing_reason.startswith("QUOTE_SYMBOL_MISSING:"):
                conditions=["OBSERVATION_ONLY", "NOT_STRICT_SELECTION"]
                if isinstance(relation,dict) and relation.get("pit_status") == "PIT_UNCONFIRMED":
                    conditions.append("PIT_UNCONFIRMED")
                diagnostic_gaps=list(item.get("source_gaps", [])) if isinstance(item.get("source_gaps"), list) else []
                if isinstance(relation,dict) and relation.get("pit_status") == "PIT_UNCONFIRMED":
                    diagnostic_gaps.append("US_RELATION_PROPOSED_PIT_UNCONFIRMED")
                output_rows.append(row(base, "UNASSESSED", quote_missing_reason, conditions=conditions,
                    diagnostic_gaps=diagnostic_gaps, **extra))
                continue

            change_evidence_verified = (
                positive_change_required
                and source_ok
                and change is not None
                and not quote_missing_reason
                and not item.get("source_gaps")
            )
            if (change_evidence_verified and change is False and isinstance(relation, dict)
                    and hk_symbol(relation.get("target_symbol"))):
                # A valid false necessary trigger disposes of this declared
                # direct relation path, while its other admission gates remain
                # visible and unresolved. This is not a stock-level verdict.
                relation_ok=(source_ok and hk_symbol(relation.get("target_symbol")) and
                        relation.get("status") == "REVIEWED" and valid_sha(relation.get("sha256")) and
                        relation.get("review_owner") and current(context, relation.get("available_at")) and
                        publication_before_cutoff(context, relation) and relation.get("relation_type"))
                eligible=membership(base,context)
                qualification_gaps=[]
                if (relation.get("status") == "PROPOSED"
                        or relation.get("pit_status") == "PIT_UNCONFIRMED"):
                    qualification_gaps.append("US_RELATION_PROPOSED_PIT_UNCONFIRMED")
                elif not relation_ok:
                    qualification_gaps.append("US_RELATION_REVIEW_OR_CUTOFF_GUARD_NOT_PASSED")
                if priority not in ("PRIORITY", "WATCH", "NONE"):
                    qualification_gaps.append("AUDITED_RESEARCH_PRIORITY_UNAVAILABLE")
                if eligible is None:
                    qualification_gaps.append("CONNECT_MEMBERSHIP_UNKNOWN")
                elif eligible is False:
                    qualification_gaps.append("TARGET_NOT_IN_CURRENT_CONNECT_MEMBERSHIP")
                output_rows.append(row(base, "NOT_SELECTED", "US_SOURCE_CHANGE_NOT_POSITIVE",
                    conditions=["DIRECT_RELATION_PATH_ONLY", "NOT_STOCK_LEVEL_DECISION"],
                    diagnostic_gaps=qualification_gaps,
                    path_disposition_scope="DIRECT_US_HK_RELATION_ONLY", **extra))
                continue
            if isinstance(relation, dict) and (
                relation.get("status") == "PROPOSED"
                or relation.get("pit_status") == "PIT_UNCONFIRMED"
            ):
                output_rows.append(row(base, "UNASSESSED", "US_RELATION_PROPOSED_PIT_UNCONFIRMED",
                    conditions=["OBSERVATION_ONLY", "NOT_STRICT_SELECTION"], **extra))
                continue
            relation_ok=(source_ok and isinstance(relation, dict) and hk_symbol(relation.get("target_symbol")) and
                    relation.get("status") == "REVIEWED" and valid_sha(relation.get("sha256")) and
                    relation.get("review_owner") and current(context, relation.get("available_at")) and
                    publication_before_cutoff(context, relation) and relation.get("relation_type"))
            eligible=membership(base,context)
            if not (relation_ok and priority in ("PRIORITY","WATCH","NONE") and change is not None and eligible is True
                    and (change is not False or change_evidence_verified)):
                blockers=[]
                if relation_ok and priority not in ('PRIORITY','WATCH','NONE'):blockers.append('AUDITED_RESEARCH_PRIORITY_UNAVAILABLE')
                if eligible is False:blockers.append('TARGET_NOT_IN_CURRENT_CONNECT_MEMBERSHIP')
                if change is False and not change_evidence_verified:
                    blockers.append('US_SOURCE_CHANGE_EVIDENCE_UNVERIFIED')
                reason=('US_SOURCE_CHANGE_EVIDENCE_UNVERIFIED' if change is False and not change_evidence_verified
                    else 'US_RELATION_PRIORITY_NOT_REVIEWED' if relation_ok and priority not in ('PRIORITY','WATCH','NONE')
                    else 'US_SESSION_RELATION_OR_CONNECT_UNVERIFIED')
                output_rows.append(row(base, "UNASSESSED", reason,diagnostic_gaps=blockers, **extra))
            elif change is False:
                output_rows.append(row(base,"NOT_SELECTED","US_SOURCE_CHANGE_NOT_POSITIVE",**extra))
            elif priority == "NONE":
                output_rows.append(row(base, "NOT_SELECTED", "US_ORIGINAL_SOURCE_NOT_PRIORITY_OR_WATCH", **extra))
            else:
                output_rows.append(row(base, "CONDITIONAL_WATCH", "US_REVIEWED_RELATION_CONDITIONAL_ONLY",
                    conditions=["RELATION_NOT_A_STRICT_SELECTION_RULE"], **extra))
    source_batch = dict(batch, records=source_records)
    out=result("US_MAPPING", source_batch, context, rows, gaps=gaps)
    out["rows"].extend(catalog_rows)
    overlay_summary = u.get("full_overlay_summary") or {}
    consumed_relations = sum(len(item.get("relations", [])) for item in catalog_records
                             if isinstance(item.get("relations"), list))
    if out["rows"]:
        out["rows"][0]["us_mapping_catalog_summary"] = {
            "state": overlay_summary.get("state", "CANNOT_CONFIRM"),
            "stock_count": overlay_summary.get("stock_count"),
            "relation_count": overlay_summary.get("relation_count"),
            "consumed_relation_count": consumed_relations,
            "status_counts": overlay_summary.get("status_counts"),
            "catalog_file_sha256": overlay_summary.get("catalog_file_sha256"),
            "review_overlay_file_sha256": overlay_summary.get("review_overlay_file_sha256"),
            "recovery_overlay_integrity_sha256": overlay_summary.get("recovery_overlay_integrity_sha256"),
            "gap": overlay_summary.get("gap"),
        }
    if overlay_summary.get("state") == "READY" and consumed_relations != overlay_summary.get("relation_count"):
        out["gaps"].append("US_MAPPING_OVERLAY_CONSUMER_COUNT_MISMATCH")
        out["coverage"]["gaps"].append("US_MAPPING_OVERLAY_CONSUMER_COUNT_MISMATCH")
        out["state"] = "PARTIAL"
    if context.get("rules_version") == US_FACTOR_RULES_VERSION:
        payload = next((record.get("us_factor_payload") for record in source_batch.get("records", [])
                       if isinstance(record, dict) and isinstance(record.get("us_factor_payload"), dict)), None)
        try:
            factor_rows, factor_summary = run_us_factor(context, source_batch, payload)
        except Exception:
            # A factor-specific parser/owner failure must not discard the original
            # independently reviewed US relationship rows.
            factor_rows = []
            factor_summary = dict(display_only=True, rules_version=US_FACTOR_RULES_VERSION,
                target_date=context.get("target_date"), phase=context.get("phase"),
                us_source_symbol_count=33, proxy_source_count=None, expected_proxy_source_count=24,
                verified_proxy_source_count=None, unknown_proxy_source_count=None,
                eligible_hk_scope_count=None, unique_factor_stock_count=0,
                factor_path_count=0, unknown_factor_stock_count=None, registry_fact_count=None,
                paired_review_available=False, paired_review_gap="US_FACTOR_ENGINE_FAILED",
                source_session=(context.get("source_sessions") or {}).get("us"),
                historical_pit_verified=False, combined_source_and_stock_count=None)
        full_mapping_mode = (context.get("target_date") == "20261020"
            and context.get("phase") in ("MANUAL", "NEXT_DAY")
            and ((context.get("source_sessions") or {}).get("us")
                 or (context.get("source_sessions") or {}).get("US")) == "20261016"
            and ((context.get("source_sessions") or {}).get("hk_price")
                 or (context.get("source_sessions") or {}).get("HK_PRICE")) == "20261016")
        if full_mapping_mode:
            legacy_counts = dict(factor_summary.get("factor_decision_counts") or {})
            for factor_row in factor_rows:
                if not isinstance(factor_row, dict) or factor_row.get("subtype") != "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE":
                    continue
                factor_row["legacy_factor_decision"] = factor_row.get("decision")
                factor_row["full_mapping_source_observation_only"] = True
                factor_row["direction_basis"] = "US_SECTOR_PROXY_SOURCE_RETURN"
                factor_row["direction_sign"] = None
                factor_row["signed_hk_return_pct"] = None
                factor_row["decision"] = "UNASSESSED"
                factor_row["reason"] = "FULL_MAPPING_SECTOR_BASELINE_ONLY_NO_HK_SIGN"
                factor_row["conditions"] = list(dict.fromkeys([
                    *(factor_row.get("conditions") or []),
                    "BROAD_SECTOR_BACKGROUND_ONLY", "NO_HK_SIGN_OR_PRIMARY_SELECTION_PATH"]))
            factor_summary["full_mapping_sector_policy"] = "BROAD_SECTOR_BACKGROUND_ONLY"
            factor_summary["sector_proxy_effectiveness"] = "UNVERIFIED"
            factor_summary["sector_proxy_direction_basis"] = "US_SOURCE_RETURN_ONLY"
            factor_summary["legacy_factor_decision_counts_before_full_mapping_policy"] = legacy_counts
            factor_summary["factor_decision_counts"] = {
                decision: sum(1 for item in factor_rows if isinstance(item, dict) and item.get("decision") == decision)
                for decision in ("SELECTED", "CONDITIONAL_WATCH", "NOT_SELECTED", "UNASSESSED", "OBSERVATION_ONLY")}
            if isinstance(factor_summary.get("industry_summary"), dict):
                factor_summary["industry_summary"]["triggered_unique_stock_count"] = 0
                factor_summary["industry_summary"]["full_mapping_route"] = "BROAD_SECTOR_BACKGROUND"
                factor_summary["industry_summary"]["full_mapping_direction"] = "US_SOURCE_OBSERVATION_ONLY"
        if (context.get("phase") in ("MANUAL", "NEXT_DAY")
                and context.get("target_date") == "20261020"
                and ((context.get("source_sessions") or {}).get("us")
                    or (context.get("source_sessions") or {}).get("US")) == "20261016"
                and ((context.get("source_sessions") or {}).get("hk_price")
                    or (context.get("source_sessions") or {}).get("HK_PRICE")) == "20261016"):
            try:
                mapping_payload = (payload.get("single_day_mapping_payload") or {}).get("monthly_membership") if isinstance(payload, dict) else None
                single_day_summary = run_single_day_mapping(context,
                    relation_rows=rows,
                    catalog_rows=catalog_rows,
                    catalog_stock_identities=(u.get("full_overlay_stock_identities")
                        if overlay_summary.get("state") == "READY" else None),
                    catalog_expected_stock_count=(overlay_summary.get("stock_count")
                        if overlay_summary.get("state") == "READY" else None),
                    industry_rows=factor_rows,
                    factor_summary=factor_summary,
                    membership=mapping_payload,
                    manual_quote_scope=(payload or {}).get("manual_quote_scope") if isinstance(payload, dict) else None)
            except Exception:
                # A single-day summary failure must not discard prior
                # reviewed US relations or the independent factor result.
                single_day_summary = cannot_confirm_single_day_mapping(context,
                    "SINGLE_DAY_MAPPING_FAILED")
            factor_summary["single_day_mapping"] = single_day_summary
        out["rows"].extend(factor_rows)
        holder = next(iter(factor_rows), None) or next(iter(out["rows"]), None)
        if holder is not None:
            holder["us_factor_summary"] = factor_summary
        industry_summary = factor_summary.get("industry_summary") or {}
        if industry_summary.get("source_status") not in (None, "READY", "UNAVAILABLE"):
            out["gaps"].append("HK_INDUSTRY_CLASSIFICATION_COVERAGE_PARTIAL")
            out["coverage"]["gaps"].append("HK_INDUSTRY_CLASSIFICATION_COVERAGE_PARTIAL")
            out["state"] = "PARTIAL"
        if factor_summary.get("paired_review_gap"):
            out["gaps"].append(factor_summary["paired_review_gap"])
            out["coverage"]["gaps"].append(factor_summary["paired_review_gap"])
            out["state"] = "PARTIAL"
        elif factor_summary.get("unknown_factor_stock_count"):
            out["gaps"].append("US_FACTOR_PATHS_UNASSESSED")
            out["coverage"]["gaps"].append("US_FACTOR_PATHS_UNASSESSED")
            out["state"] = "PARTIAL"
    # One US source can have multiple reviewed HK relations: source coverage is
    # measured in unique configured US symbols, not mapped-stock row counts.
    if not out["gaps"] and not any(x.get("positive_change_required") for x in source_records if isinstance(x, dict)):
        out["coverage"]["assessed_count"] = sum(1 for x in source_records if isinstance(x, dict) and x.get("source_status") in ("PRIORITY", "WATCH", "NONE"))
        out["coverage"]["unassessed_count"] = expected_count - out["coverage"]["assessed_count"]
    return out

