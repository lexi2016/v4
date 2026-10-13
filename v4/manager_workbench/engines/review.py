"""Ex-post comparison of a frozen plan to an injected COMPLETE matching close list."""
from __future__ import annotations
from .common import VERSION, hk_symbol, plain, valid_sha, validate_context


STRATEGIES=("ANNOUNCEMENT","US_MAPPING","OVERSOLD","STAGE_REFERENCE","CLOSE_REFERENCE")


def _blank(plan, reason):
    context=plan["context"]
    return dict(target_date=context["target_date"],plan_run_id=plan["run_id"],
        evaluation_scope_ref=context["scope_refs"].get("review_universe"),
        mode="NOT_EVALUATED",ranking_date=None,top20_rows=[],
        strict_coverage=dict(covered=None,denominator=None,ratio=None,intersection=[]),
        extended_coverage=dict(covered=None,denominator=None,ratio=None,intersection=[]),
        selected_denominator=None, lane_incremental_coverage={},uncovered_reasons=[],gaps=[reason])


def _normalize_close_input(context, close):
    """Accept B's InputBatch without inventing a second complete-close type."""
    if not isinstance(close,dict) or close.get("lane")!="CLOSE_REFERENCE":
        return close
    bctx=plain(close.get("context"))
    coverage=plain(close.get("coverage"))
    if (bctx != context or not isinstance(coverage,dict) or close.get("gaps") or
        coverage.get("gaps") or close.get("universe_ref") != context["scope_refs"].get("review_universe") or
        coverage.get("scope_count") is None or
        coverage.get("scope_count") != coverage.get("observed_count") or
        coverage.get("scope_count") != len(close.get("records", []))):
        return None
    verified=[plain(e) for e in close.get("evidence_refs",[]) if isinstance(plain(e),dict)]
    official=[e for e in verified if e.get("role")=="FULL_CLOSE_RANKING" and
        e.get("verification")=="VERIFIED" and e.get("source_date")==context["target_date"] and
        valid_sha(e.get("sha256")) and e.get("owner") and e.get("manifest_ref") and e.get("receipt_ref")]
    if len(official)!=1:
        return None
    return dict(market="HK_CONNECT", target_date=context["target_date"],
        ranking_date=context["target_date"], full_scope_verified=True,
        scope_ref=close["universe_ref"],source_sha256=official[0]["sha256"],owner=official[0]["owner"],
        scope_count=coverage["scope_count"],rows=close["records"])


def _close_valid(context, close):
    expected=context["scope_refs"].get("review_universe")
    if not isinstance(close,dict) or expected is None:return False
    if not (close.get("market")=="HK_CONNECT" and close.get("target_date")==context["target_date"] and
        close.get("ranking_date")==context["target_date"] and close.get("scope_ref")==expected and
        close.get("full_scope_verified") is True and close.get("owner") and
        valid_sha(close.get("source_sha256")) and type(close.get("scope_count")) is int and
        close["scope_count"]>=0 and isinstance(close.get("rows"),list) and
        len(close["rows"])==close["scope_count"]):
        return False
    symbols=set()
    for rank,item in enumerate(close["rows"],1):
        if (not isinstance(item,dict) or item.get("rank")!=rank or not hk_symbol(item.get("symbol")) or
            item["symbol"] in symbols):return False
        symbols.add(item["symbol"])
    return True


def evaluate_review(plan, close_inputs):
    """Never calculate an apparent 0% result from unknown or partial close data.

    Strict = frozen SELECTED; extended = frozen SELECTED or WATCH. The
    per-strategy incremental contribution uses the deterministic listed order,
    not a retrospectively optimized allocation.
    """
    plan=plain(plan)
    close_inputs=plain(close_inputs)
    if not isinstance(plan,dict) or plan.get("schema_version")!=VERSION or not isinstance(plan.get("stocks"),list) or not plan.get("run_id"):
        raise ValueError("MWB_FROZEN_PLAN_REQUIRED")
    context=validate_context(plain(plan["context"]))
    close_inputs=_normalize_close_input(context,close_inputs)
    if not _close_valid(context,close_inputs):
        return _blank(plan,"COMPLETE_SAME_SCOPE_CLOSE_RANKING_NOT_VERIFIED")
    close=close_inputs
    top=close["rows"][:20]
    universe={item["symbol"] for item in top}
    selected={item["symbol"]:item for item in plan["stocks"] if item.get("decision")=="SELECTED" and hk_symbol(item.get("symbol"))}
    extended={item["symbol"]:item for item in plan["stocks"] if item.get("decision") in ("SELECTED","CONDITIONAL_WATCH") and hk_symbol(item.get("symbol"))}
    strict_hits=set(selected)&universe
    extended_hits=set(extended)&universe
    denom=len(top)
    def metric(hit):
        return dict(covered=len(hit),denominator=denom,ratio=(len(hit)/denom if denom else None),intersection=sorted(hit))
    contributions={};strict_so_far=set();ext_so_far=set()
    for strategy in STRATEGIES:
        strict_lane={x["symbol"] for x in plan["stocks"] if hk_symbol(x.get("symbol")) and
            any(r.get("decision")=="SELECTED" for r in x.get("lane_decisions",{}).get(strategy,[]))}
        ext_lane={x["symbol"] for x in plan["stocks"] if hk_symbol(x.get("symbol")) and
            any(r.get("decision") in ("SELECTED","CONDITIONAL_WATCH")
                for r in x.get("lane_decisions",{}).get(strategy,[]))}
        new_strict=(strict_lane & strict_hits)-strict_so_far
        new_ext=(ext_lane & extended_hits)-ext_so_far
        contributions[strategy]=dict(strict_total=len(strict_lane&strict_hits),extended_total=len(ext_lane&extended_hits),
            strict_added=len(new_strict),extended_added=len(new_ext),strict_added_symbols=sorted(new_strict),
            extended_added_symbols=sorted(new_ext))
        strict_so_far.update(strict_lane&strict_hits)
        ext_so_far.update(ext_lane&extended_hits)
    frozen={x.get("symbol"):x for x in plan["stocks"] if hk_symbol(x.get("symbol"))}
    out=[];missing=[]
    for x in top:
        symbol=x["symbol"];decision=frozen.get(symbol,{}).get("decision")
        if symbol in strict_hits:why=None
        elif symbol in extended_hits:why="CONDITIONAL_ONLY_NOT_STRICT"
        elif decision=="UNASSESSED":why="RESEARCH_EVIDENCE_UNASSESSED"
        elif decision=="OBSERVATION_ONLY":why="OBSERVATION_NO_STRICT_ADMISSION"
        elif decision=="NOT_SELECTED":why="ALL_APPLICABLE_RESEARCH_NEGATIVE"
        else:why="NOT_IN_FROZEN_RESEARCH_PLAN"
        entry=dict(x,stock_decision=decision or "NOT_IN_PLAN",strict_hit=symbol in strict_hits,
                   extended_hit=symbol in extended_hits,missed_reason=why)
        out.append(entry)
        if why:missing.append(symbol+":"+why)
    gaps=["ZERO_CLOSE_DENOMINATOR"] if not denom else []
    return dict(target_date=context["target_date"],plan_run_id=plan["run_id"],
        evaluation_scope_ref=context["scope_refs"]["review_universe"],mode="FROZEN_PLAN_VS_COMPLETE_CLOSE",
        ranking_date=close["ranking_date"],top20_rows=out,strict_coverage=metric(strict_hits),
        extended_coverage=metric(extended_hits),selected_denominator=len(selected),
        lane_incremental_coverage=contributions,uncovered_reasons=missing,gaps=gaps)
