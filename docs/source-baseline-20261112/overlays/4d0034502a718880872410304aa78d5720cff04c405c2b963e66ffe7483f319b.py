"""Frozen A-only research orchestration and deterministic stock merge.

No implicit source reads, no 200-row cut, no cross-lane failure masking.
"""
from __future__ import annotations
from .common import (LANES, RESEARCH_LANES, DECISIONS, valid_sha, current, hk_symbol,
                     membership, result, plain, timestamp, validate_context, digest)
from .announcement import run_announcements
from .us_mapping import run_us_mapping
from .oversold import run_oversold


def _missing(lane, context, code):
    return dict(lane=lane,state="INPUT_MISSING",rows=[],coverage=dict(scope_count=None,
        observed_count=None,assessed_count=None,unassessed_count=None,gaps=[code]),
        input_sha256=digest(dict(lane=lane,context=context,missing=code)),rules_version=context["rules_version"],
        run_id=context.get("scope_refs",{}).get("run_id") or "A_RUN_ID_NOT_BOUND",evidence_refs=[],gaps=[code])


def _observation(lane, context, batch):
    rows=[]
    for item in batch["records"]:
        if not isinstance(item,dict) or not hk_symbol(item.get("symbol")) or item.get("market")!="HK_CONNECT" or item.get("target_date")!=context["target_date"] or not item.get("owner") or not item.get("source_sha256") or not current(context,item.get("available_at")):
            rows.append(dict(symbol=item.get("symbol") if isinstance(item,dict) else None,
                market="HK_CONNECT",decision="UNASSESSED",reason="REFERENCE_OWNER_OR_DATE_NOT_VERIFIED"))
            continue
        from .common import row, valid_sha
        if not valid_sha(item["source_sha256"]):
            rows.append(row(item,"UNASSESSED","REFERENCE_SHA_NOT_VERIFIED"));continue
        rows.append(row(item,"OBSERVATION_ONLY","ORIGINAL_REFERENCE_NO_VERIFIED_STRICT_ADMISSION"))
    return result(lane,batch,context,rows)


def run_lanes(context, inputs, semantic_executor):
    context=plain(context)
    validate_context(context)
    if not isinstance(inputs,dict):raise ValueError("MWB_INPUT_BATCHES_REQUIRED")
    if set(inputs)-set(LANES):raise ValueError("MWB_UNKNOWN_LANE")
    results={}
    for lane in context.get("scope_refs",{}).get("requested_lanes",LANES):
        batch=plain(inputs.get(lane))
        if not isinstance(batch,dict) or batch.get("lane")!=lane or batch.get("context")!=context:
            results[lane]=_missing(lane,context,"AUTHORITY_BATCH_ABSENT_OR_CHANGED");continue
        if not isinstance(batch.get("records"),list) or not isinstance(batch.get("coverage"),dict):
            results[lane]=_missing(lane,context,"AUTHORITY_BATCH_SHAPE");continue
        if not valid_sha(batch.get("input_sha256")):
            results[lane]=_missing(lane,context,(batch.get("gaps") or ["AUTHORITY_INPUT_IDENTITY_MISSING"])[0]);continue
        if not batch.get("records") and not batch.get("universe_ref") and batch.get("gaps"):
            results[lane]=dict(_missing(lane,context,batch["gaps"][0]),input_sha256=batch["input_sha256"]);continue
        batch=dict(batch,run_id=context.get("scope_refs",{}).get("run_id") or "A_RUN_ID_NOT_BOUND")
        try:
            if lane=="ANNOUNCEMENT":r=run_announcements(context,batch,semantic_executor)
            elif lane=="US_MAPPING":r=run_us_mapping(context,batch)
            elif lane=="OVERSOLD":r=run_oversold(context,batch)
            else:r=_observation(lane,context,batch)
        except Exception:
            results[lane]=dict(_missing(lane,context,"LANE_IMPLEMENTATION_FAILED"),state="FAILED")
        else:
            results[lane]=r
    return results


def _eligibility(record, context):
    return membership(record,context)


def merge_decisions(context, lane_results):
    """Return ALL stock decisions, sorted by decision/evidence date/code.

    A StockDecision never assumes a failing/missing research lane rejected a
    stock. Global NOT_SELECTED requires explicit same-stock negative verdicts
    from all applicable, completed research lanes.
    """
    context=plain(context)
    validate_context(context)
    if isinstance(lane_results,dict):
        values=[plain(x) for x in lane_results.values()]
    elif isinstance(lane_results,list):
        values=[plain(x) for x in lane_results]
    else:
        raise ValueError("MWB_LANE_RESULTS_REQUIRED")
    seen=set();stocks={};states={};evidence_times={}
    for lr in values:
        if not isinstance(lr,dict) or lr.get("lane") not in LANES or lr["lane"] in seen:
            raise ValueError("MWB_LANE_DUPLICATE_OR_UNKNOWN")
        lane=lr["lane"];seen.add(lane);states[lane]=lr.get("state")
        lane_context=(context.get('scope_refs',{}).get('decision_lane_contexts') or {}).get(lane,context)
        validate_context(lane_context)
        if any(lane_context.get(key)!=context.get(key) for key in ('market','target_date','rules_version')):
            raise ValueError('MWB_LANE_CONTEXT_IDENTITY_MISMATCH')
        if not isinstance(lr.get("rows"),list):raise ValueError("MWB_LANE_ROWS")
        if lr["state"] in ("NOT_RUN", "RUNNING", "FAILED", "INPUT_MISSING", "NOT_APPLICABLE"):
            continue  # a failed/not-executed lane cannot carry trusted stock verdicts
        for evidence in lr.get("evidence_refs") or []:
            if not isinstance(evidence,dict):continue
            eid=evidence.get("evidence_id")
            if (isinstance(eid,str) and evidence.get("verification")=="VERIFIED" and
                current(lane_context,evidence.get("available_at"))):
                value=timestamp(evidence["available_at"]).timestamp()
                evidence_times[eid]=max(evidence_times.get(eid,value),value)
        for item in lr["rows"]:
            if lane == "US_MAPPING" and lr.get("selection") is not None and isinstance(item,dict) and item.get("source_diagnostic"):
                continue  # canonical per-HK decision already contains every path judgment
            if (isinstance(item, dict) and
                    (item.get("record_role") == "CATALOG_OBSERVATION"
                     or item.get("catalog_relation_id") is not None)):
                continue  # full catalog observations remain queryable, never merge as candidate evidence
            if not isinstance(item,dict) or item.get("market")!="HK_CONNECT" or not hk_symbol(item.get("symbol")):
                continue  # no fabricated HK security for unmapped US originals
            if item.get("decision") not in DECISIONS:raise ValueError("MWB_ROW_DECISION")
            symbol=item["symbol"]
            entry=stocks.setdefault(symbol,dict(market="HK_CONNECT",symbol=symbol,name=item.get("name"),
                decision=None,lane_decisions={},reasons=[],conditions=[],invalidation_conditions=[],
                risks=[],evidence_ids=[],membership_status="UNKNOWN"))
            if not entry["name"] and item.get("name"):entry["name"]=item["name"]
            eligible=_eligibility(item,lane_context)
            if eligible is True:entry["membership_status"]="VERIFIED_ELIGIBLE" if entry["membership_status"]!="VERIFIED_INELIGIBLE" else "CONFLICT"
            elif eligible is False:entry["membership_status"]="VERIFIED_INELIGIBLE" if entry["membership_status"]!="VERIFIED_ELIGIBLE" else "CONFLICT"
            entry["lane_decisions"].setdefault(lane,[]).append(dict(item))
            entry["reasons"].append(item.get("reason") or "UNKNOWN")
            for key in ("conditions","invalidation_conditions","risks","evidence_ids"):
                entry[key].extend(item.get(key) or [])
    for symbol,entry in stocks.items():
        rec=[dict(row, lane=ln) for ln,rows in entry["lane_decisions"].items() for row in rows]
        research=[x for x in rec if x["lane"] in RESEARCH_LANES]
        statuses={x["decision"] for x in rec}
        eligible=entry["membership_status"]
        if eligible in ("CONFLICT","VERIFIED_INELIGIBLE"):
            decision="UNASSESSED" if eligible=="CONFLICT" else "NOT_SELECTED"
        elif "SELECTED" in statuses:
            decision="SELECTED" if eligible=="VERIFIED_ELIGIBLE" else "UNASSESSED"
        elif "CONDITIONAL_WATCH" in statuses:
            decision="CONDITIONAL_WATCH"
        elif "UNASSESSED" in statuses:
            decision="UNASSESSED"
        elif research:
            # Explicit negatives alone are insufficient if other applicable
            # research sources have not proven this stock was evaluated.
            negatives={x["lane"] for x in research if x["decision"]=="NOT_SELECTED"}
            complete=(all(states.get(l) in ("READY","READY_EMPTY","NOT_APPLICABLE") for l in RESEARCH_LANES)
                      and all(l in negatives or states.get(l)=="NOT_APPLICABLE" or
                              (states.get(l)=="READY_EMPTY" and next((v.get("coverage",{}).get("scope_count") for v in values if v["lane"]==l),None)==0)
                              for l in RESEARCH_LANES))
            decision="NOT_SELECTED" if complete else "UNASSESSED"
        else:
            decision="OBSERVATION_ONLY"
        entry["decision"]=decision
        for key in ("conditions","invalidation_conditions","risks","evidence_ids"):
            entry[key]=list(dict.fromkeys(entry[key]))
    priority=dict(SELECTED=0,CONDITIONAL_WATCH=1,UNASSESSED=2,OBSERVATION_ONLY=3,NOT_SELECTED=4)
    def sort_key(item):
        times=[evidence_times[eid] for eid in item["evidence_ids"] if eid in evidence_times]
        return (priority[item["decision"]],not bool(times),-max(times) if times else 0,item["symbol"])
    return sorted(stocks.values(),key=sort_key)

