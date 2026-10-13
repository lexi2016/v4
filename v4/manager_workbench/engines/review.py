"""Ex-post comparison of a frozen plan to an injected COMPLETE matching close list."""
from __future__ import annotations
from .common import VERSION, hk_symbol, valid_sha, validate_context


STRATEGIES=("ANNOUNCEMENT","US_MAPPING","OVERSOLD","STAGE_REFERENCE","CLOSE_REFERENCE")


def _blank(plan, reason):
    context=plan["context"]
    return dict(target_date=context["target_date"],plan_run_id=plan["run_id"],
        evaluation_scope_ref=context["scope_refs"].get("review_universe"),
        mode="NOT_EVALUATED",ranking_date=None,top20=[],
        strict_coverage=dict(covered=None,denominator=None,ratio=None,intersection=[]),
        extended_coverage=dict(covered=None,denominator=None,ratio=None,intersection=[]),
        selected_denominator=None, strategy_contributions=None,missing_reasons=[],gaps=[reason])


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
    if not isinstance(plan,dict) or plan.get("schema_version")!=VERSION or not isinstance(plan.get("stocks"),list) or not plan.get("run_id"):
        raise ValueError("MWB_FROZEN_PLAN_REQUIRED")
    context=validate_context(plan["context"])
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
            any(r.get("lane")==strategy and r.get("decision")=="SELECTED" for r in x.get("lane_decisions",[]))}
        ext_lane={x["symbol"] for x in plan["stocks"] if hk_symbol(x.get("symbol")) and
            any(r.get("lane")==strategy and r.get("decision") in ("SELECTED","CONDITIONAL_WATCH")
                for r in x.get("lane_decisions",[]))}
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
        if why:missing.append(dict(symbol=symbol,reason=why))
    gaps=["ZERO_CLOSE_DENOMINATOR"] if not denom else []
    return dict(target_date=context["target_date"],plan_run_id=plan["run_id"],
        evaluation_scope_ref=context["scope_refs"]["review_universe"],mode="FROZEN_PLAN_VS_COMPLETE_CLOSE",
        ranking_date=close["ranking_date"],top20=out,strict_coverage=metric(strict_hits),
        extended_coverage=metric(extended_hits),selected_denominator=len(selected),
        strategy_contributions=contributions,missing_reasons=missing,gaps=gaps)
