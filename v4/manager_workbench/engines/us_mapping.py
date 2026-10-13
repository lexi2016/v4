"""Reviewed, fixed-33 US source mapping: research watch ONLY."""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
import hashlib,json
from .common import current, hk_symbol, membership, result, row, valid_sha,timestamp


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
    configured = u.get("configured_symbols")
    session = u.get("source_session")
    source_session = context["source_sessions"].get("US") or context["source_sessions"].get("us")
    gaps = []
    good_universe = (isinstance(configured, list) and len(configured) == len(set(configured)) == 33 and
        all(isinstance(x, str) and x for x in configured) and u.get("verification") == "VERIFIED" and
        valid_sha(u.get("sha256")) and u.get("universe_ref")==batch.get("universe_ref") and session == source_session and
        isinstance(session, str) and u.get("calendar_verified") is True)
    if not good_universe:
        gaps.append("US_FIXED_33_OR_SESSION_NOT_VERIFIED")
    found = [item.get("us_symbol") for item in batch["records"] if isinstance(item, dict)]
    if good_universe and (len(found) != 33 or set(found) != set(configured) or len(set(found)) != 33):
        gaps.append("US_SOURCE_33_COVERAGE_INCOMPLETE")
    rows = []
    for index, item in enumerate(batch["records"]):
        if not isinstance(item, dict):
            rows.append(row({}, "UNASSESSED", "US_RECORD_INVALID", source_index=index));continue
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
            reason='US_REVIEWED_ASSESSMENT_WITH_GAPS' if assessments else 'US_ETF_THEME_PROXY_ONLY' if proxies else 'US_REVIEWED_RELATION_ABSENT'
            rows.append(dict(row(item, "UNASSESSED", reason, source_index=index,
                                 us_symbol=item.get("us_symbol"), relation_type=None,quote=item.get('quote'),
                                 reviewed_assessments=assessments,proxy_metadata=proxies,
                                 absence_scope='CHECKED_FROZEN_REVIEWED_RELATIONS_AND_SEED_ONLY'), symbol=None))
            continue
        for relation in relations:
            priority=relation.get("research_priority",item.get("source_status")) if isinstance(relation,dict) else None
            change=positive_change(item) if item.get("positive_change_required") else True
            base = dict(item, symbol=relation.get("target_symbol") if isinstance(relation, dict) else None,
                        name=relation.get("target_name") if isinstance(relation, dict) else None,
                        membership=relation.get("membership") if isinstance(relation, dict) else None,
                        evidence_ids=(item.get("evidence_ids") or []) + (relation.get("evidence_ids") or [] if isinstance(relation, dict) else []))
            extra = dict(source_index=index, us_symbol=item.get("us_symbol"),
                         relation_type=relation.get("relation_type") if isinstance(relation, dict) else None,
                         source_status=priority, publication_time_gaps=relation.get("publication_time_gaps",[]) if isinstance(relation,dict) else [], research_basis=relation.get("research_basis") if isinstance(relation,dict) else None, relation_source_refs=relation.get("relation_source_refs",[]) if isinstance(relation,dict) else [], relation_limitations=relation.get("relation_limitations",[]) if isinstance(relation,dict) else [],quote=item.get("quote"), relation_status=relation.get("status") if isinstance(relation, dict) else None)
            relation_ok=(source_ok and isinstance(relation, dict) and hk_symbol(relation.get("target_symbol")) and
                    relation.get("status") == "REVIEWED" and valid_sha(relation.get("sha256")) and
                    relation.get("review_owner") and current(context, relation.get("available_at")) and
                    publication_before_cutoff(context, relation) and relation.get("relation_type"))
            eligible=membership(base,context)
            if not (relation_ok and priority in ("PRIORITY","WATCH","NONE") and change is not None and eligible is True):
                blockers=[]
                if relation_ok and priority not in ('PRIORITY','WATCH','NONE'):blockers.append('AUDITED_RESEARCH_PRIORITY_UNAVAILABLE')
                if eligible is False:blockers.append('TARGET_NOT_IN_CURRENT_CONNECT_MEMBERSHIP')
                reason='US_RELATION_PRIORITY_NOT_REVIEWED' if relation_ok and priority not in ('PRIORITY','WATCH','NONE') else 'US_SESSION_RELATION_OR_CONNECT_UNVERIFIED'
                rows.append(row(base, "UNASSESSED", reason,diagnostic_gaps=blockers, **extra))
            elif change is False:
                rows.append(row(base,"NOT_SELECTED","US_SOURCE_CHANGE_NOT_POSITIVE",**extra))
            elif priority == "NONE":
                rows.append(row(base, "NOT_SELECTED", "US_ORIGINAL_SOURCE_NOT_PRIORITY_OR_WATCH", **extra))
            else:
                rows.append(row(base, "CONDITIONAL_WATCH", "US_REVIEWED_RELATION_CONDITIONAL_ONLY",
                    conditions=["RELATION_NOT_A_STRICT_SELECTION_RULE"], **extra))
    out=result("US_MAPPING", batch, context, rows, gaps=gaps)
    # One US source can have multiple reviewed HK relations: source coverage is
    # measured in unique configured US symbols, not mapped-stock row counts.
    if not out["gaps"] and not any(x.get("positive_change_required") for x in batch["records"]):
        out["coverage"]["assessed_count"] = sum(1 for x in batch["records"] if x.get("source_status") in ("PRIORITY", "WATCH", "NONE"))
        out["coverage"]["unassessed_count"] = 33 - out["coverage"]["assessed_count"]
    return out

