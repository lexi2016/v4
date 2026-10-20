"""Deterministic join of frozen current-close ranks and saved research decisions.

No network, selection execution, rule tuning, provider writes or store writes.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
import csv
import hashlib
import json
from pathlib import Path


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(path):return json.loads(Path(path).read_bytes())

def json_sha(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def lane(plan):return next(x for x in plan["lanes"] if x["lane"]=="US_MAPPING")

def factor_and_daily(result):
    factor=next((x["us_factor_summary"]for x in result["rows"]if"us_factor_summary"in x),{})
    return factor,factor.get("single_day_mapping")

def row_evidence(row):
    keys=["symbol","name","decision","reason","subtype","source_industry","source_session",
          "source_artifact_sha256","source_sha256","identity_status","available_at","captured_at","conditions"]
    value={k:row.get(k)for k in keys if k in row}
    value["proxy_paths"]=[{k:p.get(k)for k in ["proxy_symbols","source_session","return_pct","status","direction","source_sha256","available_at"]}for p in row.get("proxy_paths",[])]
    return value

def relation_evidence(row):
    return {k:row.get(k)for k in ["catalog_relation_id","us_symbol","relation_type","route","catalog_disposition",
        "catalog_disposition_reason","catalog_current_applicability","catalog_current_scope_class","quote_status",
        "quote_missing_reason","us_source_return_pct","condition_trigger_state","active_transmission",
        "source_session","source_sha256","receipt_sha256","manifest_sha256","catalog_pending_scope"]}

def daily_evidence(row):
    if row is None:return {"decision":"OUTSIDE_SAVED_MONTHLY_POOL","reason":"CURRENT_CODE_NOT_IN_FROZEN_POOL"}
    return {k:row.get(k)for k in ["symbol","decision","reason","reasons","mapping_grade","primary_proxy","primary_us_symbol","primary_status","source_industry"]}

def pins(plan):
    c=plan["context"];u=c["scope_refs"].get("owner_bindings",{}).get("us_mapping",{})
    _,m=factor_and_daily(lane(plan))
    return dict(source_sessions=c["source_sessions"],cutoff=c["cutoff"],quote_sha256=u.get("quote_sha256"),
        quote_receipt_sha256=u.get("owner_receipt_sha256"),quote_manifest_sha256=u.get("owner_manifest_sha256"),
        relation_registry_sha256=u.get("relation_sha256"),monthly_source_sha256=(m or{}).get("monthly_source_sha256"),
        monthly_codes_sha256=(m or{}).get("monthly_codes_sha256"))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--raw-root",type=Path,required=True)
    parser.add_argument("--candidate-snapshot",type=Path,required=True)
    parser.add_argument("--output-root",type=Path,required=True)
    args=parser.parse_args();raw=args.raw_root;out=args.output_root
    if "local_only/research" not in str(raw):raise ValueError("LOCAL_ONLY_RAW_REQUIRED")
    frozen=read(raw/"actual-saved-selection-sets-frozen.json")
    ranking=read(raw/"close-ranking-frozen.json")
    quote=read(raw/"top20-current-close-snapshots.json")
    universe=read(raw/"top20-universe-frozen.json")
    history=read(raw/"online-history.json")
    assert frozen["freeze_before_close_ranking_observation"] is True
    assert datetime.fromisoformat(frozen["frozen_at"]) < datetime.fromisoformat(quote["started_at"]) < datetime.fromisoformat(ranking["frozen_at"])
    assert sha(raw/"top20-current-close-snapshots.json")==ranking["raw_sha256"]
    snapshots=[r for b in quote["batches"]for r in b["rows"]]
    assert len(snapshots)==len({r["code"]for r in snapshots})==len(universe["codes"])==698
    ordered=sorted(snapshots,key=lambda r:(-((Decimal(str(r["last_price"]))/Decimal(str(r["prev_close_price"])))-1)*100,r["code"]))
    assert [r["code"]for r in ordered]==[r["symbol"]for r in ranking["all_ranked_rows"]]
    assert all(r["update_time"].startswith("2026-10-20 ")for r in snapshots)
    assert all(Decimal(str(r["last_price"]))>0 and Decimal(str(r["prev_close_price"]))>0 for r in snapshots)
    types={r["code"]:r["stock_type"]for p in universe["plates"]for r in p["rows"]}
    assert [r["code"]for r in ordered if types[r["code"]]=="STOCK"][:20]==[r["symbol"]for r in ranking["top20"]]
    stock_types=dict(Counter(types.values()))
    top=ranking["top20"];top_codes={r["symbol"]for r in top};source_plans={};actual_metrics=[]
    online_ids={r["run_id"]for r in history["data"]["versions"]}
    for f in frozen["runs"]:
        p=Path(f["snapshot_path"]);assert sha(p)==f["snapshot_raw_sha256"]
        d=read(p);assert d["run_id"]==f["run_id"] and d["product_sha256"]==f["product_sha256"]
        assert f["run_id"]in online_ids
        source_plans[f["run_id"]]=d
        actual_metrics.append(dict(run_id=f["run_id"],phase=f["phase"],generated_at=f["generated_at"],
            snapshot_raw_sha256=f["snapshot_raw_sha256"],input_sha256=f["input_sha256"],product_sha256=f["product_sha256"],
            sets={k:dict(denominator=len(v),top20_overlap_count=len(set(v)&top_codes),top20_overlap_symbols=sorted(set(v)&top_codes))for k,v in f["lane_sets"].items()},
            daily_benefit=None if f["daily_benefit_symbols"]is None else dict(denominator=len(f["daily_benefit_symbols"]),top20_overlap_symbols=sorted(set(f["daily_benefit_symbols"])&top_codes)),
            daily_observation=None if f["daily_observation_symbols"]is None else dict(denominator=len(f["daily_observation_symbols"]),top20_overlap_symbols=sorted(set(f["daily_observation_symbols"])&top_codes)),
            strict_v1_status=f["strict_v1_status"],pins=pins(d)))
    morning=source_plans["52d6d87a1fe547a484b189448d0ddfb7"]
    screenshot=source_plans["9f12b7e877f741e1b24da9d2fda578d3"]
    latest=source_plans["e96a793fe0f0464ca354927d301e13d3"]
    m_lane=lane(morning);i_lane=lane(screenshot)
    _,m_daily=factor_and_daily(m_lane)
    assert m_daily is not None
    m_index={r["symbol"]:r for r in m_daily["rows"]}
    i_index={r["symbol"]:r for r in i_lane["rows"]if r.get("subtype")=="HK_INDUSTRY_PROXY_FACTOR_CANDIDATE"}
    c_hash=sha(args.candidate_snapshot)
    assert c_hash=="cc37d7899d973025cbb0549a731dc37fc41d46328268518a1de49b81c67348d8"
    candidate=read(args.candidate_snapshot)
    assert candidate["run_id"]=="05d40e7775c44304bbd98016194b0d0e" and candidate["run_id"]not in online_ids
    _,c_daily=factor_and_daily(lane(candidate));assert c_daily is not None
    assert c_daily["strict_v1_status"]=="PAUSED_NOT_EXECUTED"
    c_index={r["symbol"]:r for r in c_daily["rows"]}
    same_source_keys=["quote_sha256","quote_receipt_sha256","quote_manifest_sha256","relation_registry_sha256"]
    assert all(pins(candidate)[key]==pins(morning)[key]for key in same_source_keys)
    assert pins(candidate)["source_sessions"]==pins(morning)["source_sessions"]=={"us":"20261019","hk_price":"20261016"}
    current_scope=set(universe["codes"]);saved_scope=set(m_index)
    catalog={}
    for r in m_daily["catalog_relation_dispositions"]:catalog.setdefault(r["symbol"],[]).append(relation_evidence(r))
    rows=[]
    for close in top:
        symbol=close["symbol"];original=m_index.get(symbol);intraday=i_index.get(symbol);repair=c_index.get(symbol)
        if symbol not in saved_scope:
            reason="当前代码不在冻结月池；不能把旧代码自动别名成当前证券。"
        elif intraday and intraday["decision"]=="CONDITIONAL_WATCH":
            reason="盘中仅宽行业条件观察，未成为严格/具名A受益；原单日ETF只作C背景。"
        elif not catalog.get(symbol):
            reason="无catalog关系；现有行业没有代理映射；没有已验收A主路径。"
        else:
            reason="已有catalog背景/待核关系，未形成已验收A主路径；现有行业没有代理映射。"
        rows.append(dict(**close,actual_morning=daily_evidence(original),actual_intraday=row_evidence(intraday)if intraday else None,
            actual_strict_hit=False,actual_morning_benefit_hit=symbol in set(m_daily["benefit_rows"]),
            actual_intraday_conditional_overlap=bool(intraday and intraday["decision"]=="CONDITIONAL_WATCH"),
            offline_repair=daily_evidence(repair),offline_repair_benefit_overlap=symbol in set(c_daily["benefit_rows"]),
            named_catalog_evidence=catalog.get(symbol,[]),miss_explanation=reason,price_driver_causality="CANNOT_CONFIRM_NOT_INVESTIGATED"))
    assert len(rows)==20 and len({r["symbol"]for r in rows})==20
    assert sum(r["actual_intraday_conditional_overlap"]for r in rows)==7
    assert not any(r["actual_strict_hit"]or r["actual_morning_benefit_hit"]or r["offline_repair_benefit_overlap"]for r in rows)
    # Ancillary chronology checks reuse the already frozen conditional set;
    # they do not introduce a later-optimized selection set or denominator.
    earliest_path=Path(morning["context"]["scope_refs"].get("unused",Path(frozen["runs"][0]["snapshot_path"]).parent))/"fffc5d472f724bc6b3a8e0b76629d595.json"
    earliest=read(earliest_path);earliest_watch={r["symbol"]for r in lane(earliest)["rows"]if r.get("symbol")and r["decision"]=="CONDITIONAL_WATCH"}
    screenshot_watch={r["symbol"]for r in i_lane["rows"]if r.get("symbol")and r["decision"]=="CONDITIONAL_WATCH"}
    assert earliest_watch==screenshot_watch=={r["symbol"]for r in lane(latest)["rows"]if r.get("symbol")and r["decision"]=="CONDITIONAL_WATCH"}
    highxin=[]
    for d in [source_plans["571e25ceffed46528fbc6b8ea45de3d3"],source_plans["dc205639f22e483e984555d689dcd226"],morning,earliest,screenshot]:
        l=lane(d);_,dd=factor_and_daily(l);dr=next((r for r in(dd or{}).get("rows",[])if r["symbol"]=="HK.06808"),None)
        candidates=[r for r in(dd or{}).get("catalog_candidates",[])if r["symbol"]=="HK.06808"]
        factor_row=next((r for r in l["rows"]if r.get("symbol")=="HK.06808"and r.get("subtype")=="HK_INDUSTRY_PROXY_FACTOR_CANDIDATE"),None)
        highxin.append(dict(run_id=d["run_id"],generated_at=d["generated_at"],phase=d["context"]["phase"],pins=pins(d),
            single_day=daily_evidence(dr)if dr else None,
            catalog_dispositions=[{k:r.get(k)for k in ["relation_id","us_symbol","source_return_pct","quote_status","current_applicability","disposition","reason","condition_trigger_state","active_transmission"]}for r in(dr or{}).get("catalog_relation_dispositions",[])],
            candidate=[{k:r.get(k)for k in ["qualification","direction_group","positive_source_move_strength_pct","risk_markers"]}for r in candidates],
            factor=row_evidence(factor_row)if factor_row else None))
    all_ranks={r["symbol"]:r for r in ranking["all_ranked_rows"]}
    benefit_performance=[dict(symbol=s,name=all_ranks.get(s,{}).get("name"),close_rank=all_ranks.get(s,{}).get("rank"),pct_close=all_ranks.get(s,{}).get("pct_close"))for s in c_daily["benefit_rows"]]
    result=dict(schema_version="v4.research.us_mapping_top20_comparison.v1",status="PREPARED_PENDING_INDEPENDENT_REVIEW",target_date="20261020",
        boundary=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,rule_tuning=False,selection_reexecuted=False),
        scope=dict(source="Current Futu get_plate_stock union of HK.GangGuTong and HK.LIST1922",universe_count=698,security_type_counts=stock_types,
            top20_all_stock=True,stock_only_top20_identical=True,quotes_valid=698,coverage_ratio=1.0,
            suspended_count=sum(r.get("suspension")is True for r in snapshots),sort=ranking["sort"],
            current_not_in_saved_monthly=sorted(current_scope-saved_scope),saved_monthly_not_current=sorted(saved_scope-current_scope),
            top20_outside_saved_monthly=sorted(top_codes-saved_scope),denominator_preserved=20,formal_target_eligibility="CANNOT_CONFIRM_NOT_PROMOTED"),
        timing=dict(actual_sets_frozen_at=frozen["frozen_at"],quote_started_at=quote["started_at"],quote_completed_at=quote["completed_at"],rank_frozen_at=ranking["frozen_at"],
            source_update_min=ranking["row_update_time_min"],source_update_max=ranking["row_update_time_max"],query_after_1610=True,
            earliest_identical_conditional_run=dict(run_id=earliest["run_id"],generated_at=earliest["generated_at"],snapshot_sha256=sha(earliest_path),same_set_as_screenshot=True,
                temporal_limit="After open at09:38; price move already realized at selection time is not established. Not a pre-open prediction hit.")),
        evidence=dict(actual_sets_frozen_sha256=sha(raw/"actual-saved-selection-sets-frozen.json"),ranking_frozen_sha256=sha(raw/"close-ranking-frozen.json"),
            snapshots_sha256=sha(raw/"top20-current-close-snapshots.json"),universe_sha256=sha(raw/"top20-universe-frozen.json"),
            online_history_sha256=sha(raw/"online-history.json"),review_api_sha256=sha(raw/"review-api-20261020.json"),
            existing_review_top20_count=0,existing_review_status="CANNOT_CONFIRM",raw_root=str(raw)),
        actual_runs=actual_metrics,offline_counterfactual=dict(run_id=candidate["run_id"],snapshot_path=str(args.candidate_snapshot),snapshot_sha256=c_hash,
            generated_at=candidate["generated_at"],cutoff=candidate["context"]["cutoff"],pins=pins(candidate),input_sha256=candidate["input_sha256"],product_sha256=candidate["product_sha256"],
            counts=c_daily["counts"],strict_v1_status=c_daily["strict_v1_status"],benefit_top20_overlap=0,
            observation_top20_overlap=len(top_codes&set(c_daily["observation_rows"])),actual_hit_credit=False,benefit_stocks_close_performance=benefit_performance,
            note="Generated at10:24 with same US19/HK16 source pins plus existing master; not a05:44 execution and not deployed."),
        top20=rows,highxin_case=dict(symbol="HK.06808",name="高鑫零售",close_rank=17,pct_close=all_ranks["HK.06808"]["pct_close"],
            chronology=highxin,user_mentioned_yesterday="User statement accepted; yesterday handoff documents the exact case. Original chat message not independently retrieved in this research worker.",
            conclusion="Yesterday's nested-state adaptation defect hid a valid dated weak-peer candidate. By23:30 it was visible as DATED_WEAK_PEER, not a qualified benefit. At05:44 WMT US19 quote was negative and a separate alias bug contaminated daily classification. By09:38 highxin was in the232 broad-industry conditional observations via XLY/XLP, never strict selected.",
            price_driver_causality="CANNOT_CONFIRM; transfer-custody/CCASS lead is not verified buying or cause; no causal claim made."),
        limitations=["Single-date descriptive join, not a backtest or model-effectiveness proof.","232 broad conditional observations overlap7/20; broad coverage is not strict stock selection.","05d40 is an unserved offline counterfactual; no retrospective hit credit.","No account, order, collection producer, service, source rule or store mutation.","No original user-chat retrieval or issuer causal-news validation by this worker."])
    out.mkdir(parents=True,exist_ok=True)
    (out/"RESEARCH_RESULT.json").write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    fields=["rank","symbol","name","pct_close","actual_morning","actual_intraday","actual_strict_hit","actual_intraday_conditional_overlap","offline_repair","miss_explanation","catalog_evidence"]
    with(out/"RESEARCH_TOP20.csv").open("w",encoding="utf-8-sig",newline="")as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for r in rows:
            writer.writerow(dict(rank=r["rank"],symbol=r["symbol"],name=r["name"],pct_close=r["pct_close"],
                actual_morning=r["actual_morning"]["decision"]+":"+str(r["actual_morning"].get("reason")),
                actual_intraday=(r["actual_intraday"]or{}).get("decision","NOT_IN_SAVED_INPUT")+":"+str((r["actual_intraday"]or{}).get("reason")),
                actual_strict_hit=r["actual_strict_hit"],actual_intraday_conditional_overlap=r["actual_intraday_conditional_overlap"],
                offline_repair=r["offline_repair"]["decision"],miss_explanation=r["miss_explanation"],
                catalog_evidence="; ".join(str(c["catalog_relation_id"])+" "+str(c["us_symbol"])+" "+str(c["catalog_disposition"])+" / "+str(c["quote_status"])for c in r["named_catalog_evidence"])))
    concise=dict(target_date="20261020",strict_actual_hits=0,morning_benefit_hits=0,intraday_conditional_hits=7,intraday_conditional_count=232,top20_denominator=20,offline_benefit_hits=0,
        offline_benefit_count=5,offline_observation_overlap=7,highxin_rank=17,result_sha256=sha(out/"RESEARCH_RESULT.json"),csv_sha256=sha(out/"RESEARCH_TOP20.csv"))
    (out/"RESEARCH_CHECKS.json").write_text(json.dumps(concise,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print(json.dumps(concise,ensure_ascii=False))


if __name__=="__main__":main()
