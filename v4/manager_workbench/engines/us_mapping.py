"""Reviewed, fixed-33 US source mapping: research watch ONLY."""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
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
            rows.append(dict(row(item, "UNASSESSED", "US_REVIEWED_RELATION_ABSENT", source_index=index,
                                 us_symbol=item.get("us_symbol"), relation_type=None), symbol=None))
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
                         source_status=priority, publication_time_gaps=relation.get("publication_time_gaps",[]) if isinstance(relation,dict) else [], research_basis=relation.get("research_basis") if isinstance(relation,dict) else None, relation_source_refs=relation.get("relation_source_refs",[]) if isinstance(relation,dict) else [], quote=item.get("quote"), relation_status=relation.get("status") if isinstance(relation, dict) else None)
            if not (source_ok and isinstance(relation, dict) and hk_symbol(relation.get("target_symbol")) and
                    relation.get("status") == "REVIEWED" and valid_sha(relation.get("sha256")) and
                    relation.get("review_owner") and current(context, relation.get("available_at")) and
                    publication_before_cutoff(context, relation) and relation.get("relation_type") and
                    priority in ("PRIORITY","WATCH","NONE") and change is not None and
                    membership(base, context) is True):
                rows.append(row(base, "UNASSESSED", "US_SESSION_RELATION_OR_CONNECT_UNVERIFIED", **extra))
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

