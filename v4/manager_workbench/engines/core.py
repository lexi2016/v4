"""Frozen A-only research orchestration and deterministic stock merge.

No implicit source reads, no 200-row cut, no cross-lane failure masking.
"""
from __future__ import annotations
from .common import (LANES, RESEARCH_LANES, DECISIONS, valid_sha, current, hk_symbol,
                     membership, result, plain, timestamp, validate_context, digest, run_identity)
from .announcement import run_announcements
from .us_mapping import run_us_mapping
from .oversold import run_oversold


def _missing(lane, context, code, batch=None):
    # Preserve B's original InputBatch identity when a bound but unavailable
    # authority snapshot has no usable universe. Never rekey its ledger input.
    bound_sha=(batch or {}).get("input_sha256") if isinstance(batch,dict) else None
    gaps=list(dict.fromkeys([*((batch or {}).get("gaps") or []),code]))
    return dict(lane=lane,state="INPUT_MISSING",rows=[],coverage=dict(scope_count=None,
        observed_count=None,assessed_count=None,unassessed_count=None,gaps=gaps),
        input_sha256=bound_sha if valid_sha(bound_sha) else digest(dict(lane=lane,context=context,missing=code)),
        rules_version=context["rules_version"],run_id=run_identity(context),evidence_refs=[],gaps=gaps)


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
        # MWB_V1 freezes Stage/close reference rows as observations. Previous
        # owner flags/receipt SHA are provenance, NOT a manager strict rule.
        original = dict(rule=item.get("original_rule_version"),
            owner_receipt_sha256=(item.get("original_owner_receipt_sha256")
                if valid_sha(item.get("original_owner_receipt_sha256")) else None),
            original_formal_admission=item.get("original_formal_admission"),
            original_rule_verified=item.get("original_rule_verified")) if lane=="STAGE_REFERENCE" else None
        rows.append(row(item,"OBSERVATION_ONLY","ORIGINAL_REFERENCE_NO_VERIFIED_STRICT_ADMISSION",
            **({"original_stage":original} if original is not None else {})))
    return result(lane,batch,context,rows)


def run_lanes(context, inputs, semantic_executor):
    context=plain(context)
    validate_context(context)
    selected = None
    if isinstance(inputs, (list, tuple)):
        batches = [plain(batch) for batch in inputs]
        if any(not isinstance(batch, dict) or batch.get("lane") not in LANES for batch in batches):
            raise ValueError("MWB_INPUT_BATCHES_REQUIRED")
        names = [batch["lane"] for batch in batches]
        if len(names) != len(set(names)):
            raise ValueError("MWB_DUPLICATE_INPUT_LANE")
        inputs = dict(zip(names, batches))
        selected = names
    elif not isinstance(inputs, dict):
        raise ValueError("MWB_INPUT_BATCHES_REQUIRED")
    # B owns job identity; never silently substitute another run id.
    run_identity(context)
    if set(inputs)-set(LANES):raise ValueError("MWB_UNKNOWN_LANE")
    if selected is None:
        selected = context["scope_refs"].get("requested_lanes",list(LANES))
    else:
        requested = context["scope_refs"].get("requested_lanes")
        if requested is not None and set(selected)!=set(requested):
            raise ValueError("MWB_REQUESTED_LANES_CONFLICT")
    if (not isinstance(selected,list) or len(selected)!=len(set(selected)) or
            any(lane not in LANES for lane in selected) or set(inputs)-set(selected)):
        raise ValueError("MWB_REQUESTED_LANES_INVALID")
    results={}
    for lane in selected:
        batch=plain(inputs.get(lane))
        if not isinstance(batch,dict) or batch.get("lane")!=lane or batch.get("context")!=context:
            results[lane]=_missing(lane,context,"AUTHORITY_BATCH_ABSENT_OR_CHANGED",batch);continue
        if not isinstance(batch.get("records"),list) or not isinstance(batch.get("coverage"),dict):
            results[lane]=_missing(lane,context,"AUTHORITY_BATCH_SHAPE",batch);continue
        if not valid_sha(batch.get("input_sha256")) or not isinstance(batch.get("universe_ref"),str):
            results[lane]=_missing(lane,context,(batch.get("gaps") or ["AUTHORITY_INPUT_IDENTITY_MISSING"])[0],batch);continue
        batch=dict(batch,run_id=run_identity(context))
        try:
            if lane=="ANNOUNCEMENT":r=run_announcements(context,batch,semantic_executor)
            elif lane=="US_MAPPING":r=run_us_mapping(context,batch)
            elif lane=="OVERSOLD":r=run_oversold(context,batch)
            else:r=_observation(lane,context,batch)
        except Exception:
            results[lane]=dict(_missing(lane,context,"LANE_IMPLEMENTATION_FAILED",batch),state="FAILED")
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
        if not isinstance(lr.get("rows"),list):raise ValueError("MWB_LANE_ROWS")
        if lr["state"] in ("NOT_RUN", "RUNNING", "FAILED", "INPUT_MISSING", "NOT_APPLICABLE"):
            continue  # a failed/not-executed lane cannot carry trusted stock verdicts
        for evidence in lr.get("evidence_refs") or []:
            if not isinstance(evidence,dict):continue
            eid=evidence.get("evidence_id")
            if (isinstance(eid,str) and evidence.get("verification")=="VERIFIED" and
                current(context,evidence.get("available_at"))):
                value=timestamp(evidence["available_at"]).timestamp()
                evidence_times[eid]=max(evidence_times.get(eid,value),value)
        for item in lr["rows"]:
            if not isinstance(item,dict) or item.get("market")!="HK_CONNECT" or not hk_symbol(item.get("symbol")):
                continue  # no fabricated HK security for unmapped US originals
            if item.get("decision") not in DECISIONS:raise ValueError("MWB_ROW_DECISION")
            if lane in ("STAGE_REFERENCE", "CLOSE_REFERENCE") and item["decision"] != "OBSERVATION_ONLY":
                # Defense in depth for a foreign/original owner row. Neither
                # reference lane defines a strict manager selection predicate.
                item=dict(item, original_owner_decision=item["decision"],
                          decision="OBSERVATION_ONLY",
                          reason="REFERENCE_NON_RESEARCH_VERDICT_IGNORED")
            symbol=item["symbol"]
            entry=stocks.setdefault(symbol,dict(market="HK_CONNECT",symbol=symbol,name=item.get("name"),
                decision=None,lane_decisions={},reasons=[],conditions=[],invalidation_conditions=[],
                risks=[],evidence_ids=[],membership_status="UNKNOWN"))
            if not entry["name"] and item.get("name"):entry["name"]=item["name"]
            eligible=_eligibility(item,context)
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
