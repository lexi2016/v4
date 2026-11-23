"""Signed ACT017: execution attribution and two fixed quarterly risk models.

Consumes ACT015's bound RAM projection. No security-level data are persisted.
All fills are counterfactual or conservative estimates, never real executions.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any,Callable

APP_ROOT=Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0,str(APP_ROOT))
from ops import pft_act015_execution as base

SIGNED_DOC="1SInAiiPWMde2FHAroSKG0GQPp3gvfXtZoaCxRSDBhhs"
SCHEMA="pft_act017_execution.v1"
FEATURES=tuple(base.MODEL_FEATURES)
QUARTERS=("2024Q4",*[f"{year}Q{q}" for year in (2025,2026) for q in (1,2,3,4)])
PARAMS=dict(max_iter=100,learning_rate=.05,max_leaf_nodes=7,max_depth=3,
            l2_regularization=1.,early_stopping=False,random_state=0)
FLAGS=dict(base.FLAGS)


class Act017Error(RuntimeError):
    pass


def raw_open_allowed(book:Any,day:int,code:int) -> bool:
    import numpy as np
    opening,volume=(book.values[x][day,code] for x in ("open","vol"))
    tradeable=book.values.get("tradeable_basic")
    return bool(np.isfinite(opening) and opening>0 and np.isfinite(volume) and volume>0
                and (tradeable is None or tradeable[day,code]==1))


def tail_close_allowed(book:Any,day:int,code:int) -> tuple[bool,str]:
    """Same prior-close/board proxy as ACT015, evaluated at D close only."""
    from types import SimpleNamespace
    view=SimpleNamespace(values={**book.values,"open":book.values["close"]},codes=book.codes)
    return base.entry_status(view,day,code)


def attach_targets(candidates:Any,book:Any) -> tuple[Any,dict[str,Any]]:
    """Exact Q15 negative path-MDD and executable T3 binary targets."""
    import numpy as np
    out=candidates.copy()
    sid=out.session.to_numpy(dtype=int)
    cid=out.code_index.to_numpy(dtype=int)
    close=book.values["close"]
    n=len(out)
    dclose=close[sid,cid]
    peak=dclose.copy()
    mdd=np.zeros(n)
    complete=np.ones(n,dtype=bool)
    for offset in range(1,6):
        inside=sid+offset<len(book.dates)
        prices=np.full(n,np.nan)
        prices[inside]=np.where(book.valid[(sid+offset)[inside],cid[inside]],
                                close[(sid+offset)[inside],cid[inside]],np.nan)
        complete &= np.isfinite(prices)
        peak=np.maximum(peak,np.nan_to_num(prices,nan=0))
        mdd=np.minimum(mdd,np.nan_to_num(prices/peak-1,nan=0))
    out["q15_target"]=np.where(complete,mdd,np.nan)
    out["q15_target_date"]=[book.dates[d+5] if d+5<len(book.dates) else "" for d in sid]
    # All-A gross exact T1-open to T3-close endpoints, independent of signal gate.
    bench=np.full(len(book.dates),np.nan)
    if len(book.dates)>3:
        opening=book.values["open"][1:-2]
        ending=close[3:]
        valid=(np.isfinite(opening)&(opening>0)&book.valid[1:-2]&book.valid[3:])
        values=np.where(valid,ending/opening-1,np.nan)
        count=np.isfinite(values).sum(axis=1)
        bench[:-3]=np.divide(np.nansum(values,axis=1),count,
                            out=np.full(len(count),np.nan),where=count>0)
    exec_label=np.full(n,np.nan)
    reasons=defaultdict(int)
    for i,(day,code) in enumerate(zip(sid,cid)):
        if day+3>=len(book.dates):
            reasons["immature_exact_t3"]+=1
            continue
        entry,reason=base.entry_status(book,day+1,code)
        if not entry:
            reasons["entry_"+reason]+=1
            continue
        exit_ok,reason=base.exit_status(book,day+3,code)
        if not exit_ok:
            reasons["exit_"+reason]+=1
            continue
        if not book.valid[day+1:day+4,code].all() or not np.isfinite(bench[day]):
            reasons["incomplete_path_or_benchmark"]+=1
            continue
        opening=book.values["open"][day+1,code]
        path=np.r_[opening,close[day+1:day+4,code]]
        drawdown=np.min(path/np.maximum.accumulate(path)-1)
        excess=path[-1]/opening-1-bench[day]
        exec_label[i]=float(excess>=.02 and drawdown>=-.05)
        reasons["eligible_known"]+=1
    out["exec_t3_target"]=exec_label
    out["exec_t3_target_date"]=[book.dates[d+3] if d+3<len(book.dates) else "" for d in sid]
    return out,{"q15_known":int(np.isfinite(out.q15_target).sum()),
                "q15_target":"signed negative exact D..T5 close running MDD",
                "exec_t3_known":int(np.isfinite(exec_label).sum()),
                "exec_t3_positive":int(np.nansum(exec_label)),"exec_t3_eligibility":dict(reasons),
                "exec_t3_target":"gross exact T1 open..T3 close excess >=2%, complete execution path MDD >=-5%; entry and scheduled exit proxies must pass",
                "benchmark":"all-A exact valid open/end quotes, gross, independently of candidate/entry gates"}


def quarter_masks(candidates:Any,q:str,target:str) -> tuple[Any,Any,dict[str,Any]]:
    first=base.quarter_start(q)
    lower=max(base.TRAIN_START,base.training_start(q))
    train=(candidates.trade_date.ge(lower)&candidates.trade_date.lt(first)
           &candidates[target].notna()&candidates[target+"_date"].ne("")
           &candidates[target+"_date"].lt(first))
    predict=candidates.trade_date.map(base.quarter).eq(q)&candidates.trade_date.between(base.START,base.END)
    anchor_date=candidates._anchor_date.fillna("").astype(str)
    anchors=candidates.ts_code.astype(str)+"|K|"+anchor_date
    repair=candidates.rebuild_episode_id.fillna("").astype(str)
    cross_k=set(anchors[train&anchor_date.ne("")])&set(anchors[predict&anchor_date.ne("")])
    cross_r=set(repair[train&repair.ne("")])&set(repair[predict&repair.ne("")])
    purge=train&((anchor_date.ne("")&anchors.isin(cross_k))|(repair.ne("")&repair.isin(cross_r)))
    before=int(train.sum())
    train &= ~purge
    report=dict(quarter=q,train_start=lower,train_end_exclusive=first,target_mature_before=first,
                train_before_purge=before,train_rows=int(train.sum()),purged_rows=int(purge.sum()),
                predict_rows=int(predict.sum()),cross_k_groups=len(cross_k),cross_repair_groups=len(cross_r))
    if train.any():
        report.update(latest_train_signal=candidates.loc[train,"trade_date"].max(),
                      latest_train_target=candidates.loc[train,target+"_date"].max())
    return train,predict,report


def model_contract(binding:dict[str,Any]) -> dict[str,Any]:
    import ast
    import hashlib
    tree=ast.parse(Path(__file__).read_text())
    definitions={n.name:ast.dump(n,include_attributes=False) for n in tree.body
                 if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in
                 {"raw_open_allowed","tail_close_allowed","attach_targets","quarter_masks"}}
    return dict(schema=SCHEMA,signed_doc=SIGNED_DOC,binding=binding,features=list(FEATURES),
                params=PARAMS,quantile=.15,loss="quantile",classifier_class_balance="TRAIN-only n/(2*n_class)",
                target_policy_sha256=hashlib.sha256(str(sorted(definitions.items())).encode()).hexdigest(),
                act015_source_sha256=hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest(),**FLAGS)


def fit_models(candidates:Any,binding:dict[str,Any],output_dir:Path,
               progress:Callable[...,None]|None=None,resume:bool=False,
               estimator_factory:Callable[[str],Any]|None=None) -> tuple[Any,dict[str,Any]]:
    """18 fixed fits at most; successful quarter weights are immutable checkpoints."""
    import joblib
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier,HistGradientBoostingRegressor
    out=candidates.copy()
    contract=model_contract(binding)
    reports=[]
    for kind,target,column in (("q15","q15_target","q15_score"),("exec_t3","exec_t3_target","exec_t3_score")):
        out[column]=np.nan
        for q in QUARTERS:
            train,predict,report=quarter_masks(out,q,target)
            path=output_dir/f"{kind}_{q}.joblib"
            report.update(kind=kind,fits=0,reused=False,target=target)
            if path.exists():
                if not resume:
                    raise Act017Error(f"CHECKPOINT_EXISTS_USE_RESUME:{path.name}")
                stored=joblib.load(path)
                if stored.get("contract")!=contract:
                    raise Act017Error(f"CHECKPOINT_CONTRACT_MISMATCH:{path.name}")
                expected={k:v for k,v in report.items() if k not in {"fits","reused"}}
                observed={k:v for k,v in stored["fit"].items() if k not in {"fits","reused","status"}}
                if expected!=observed:
                    raise Act017Error(f"CHECKPOINT_POPULATION_MISMATCH:{path.name}")
                model=stored["model"]
                report.update(status="REUSED_COMPLETED_QUARTER",reused=True)
            else:
                y=out.loc[train,target].to_numpy(dtype=float)
                if not len(y) or not predict.any() or (kind=="exec_t3" and len(np.unique(y))!=2):
                    raise Act017Error(f"INSUFFICIENT_FIXED_QUARTER:{kind}:{q}")
                model=(estimator_factory(kind) if estimator_factory else
                       HistGradientBoostingRegressor(loss="quantile",quantile=.15,**PARAMS) if kind=="q15" else
                       HistGradientBoostingClassifier(**PARAMS))
                x=out.loc[train,list(FEATURES)].to_numpy(dtype=float,copy=True)
                x[~np.isfinite(x)]=np.nan
                if progress:
                    progress("model","FIT_STARTED",report)
                if kind=="exec_t3":
                    classes,counts=np.unique(y,return_counts=True)
                    weights=np.where(y==classes[0],len(y)/(2*counts[0]),len(y)/(2*counts[1]))
                    model.fit(x,y.astype(int),sample_weight=weights)
                else:
                    model.fit(x,y)
                report.update(fits=1,status="FIT_COMPLETE")
                temporary=path.with_suffix(".joblib.tmp")
                joblib.dump(dict(model=model,contract=contract,fit=report),temporary)
                temporary.replace(path)
            score_x=out.loc[predict,list(FEATURES)].to_numpy(dtype=float,copy=True)
            score_x[~np.isfinite(score_x)]=np.nan
            out.loc[predict,column]=(model.predict(score_x) if kind=="q15" else model.predict_proba(score_x)[:,1])
            reports.append({**report,"model_file":path.name})
            base._write_json(output_dir/"fit_accounting.json",dict(S=0,search=0,
                actual_fits=sum(r["fits"] for r in reports),reused=sum(r["reused"] for r in reports),quarters=reports))
            if progress:
                progress("model","QUARTER_COMPLETE",reports[-1])
    return out,dict(S=0,search=0,actual_fits=sum(r["fits"] for r in reports),
                    reused=sum(r["reused"] for r in reports),quarters=reports)


@dataclass(frozen=True)
class ExecutionPolicy:
    clock:str
    entry_gate:str
    constrained_exit:bool
    fee:float


POLICIES={
    "I0":ExecutionPolicy("close","signal_valid",False,0.),
    "O0_RAW":ExecutionPolicy("open","raw_open",False,0.),
    "MATCHED_D0":ExecutionPolicy("close","next_raw_open",False,0.),
    "O0_FILTERED":ExecutionPolicy("open","original",True,0.),
    "OCOST":ExecutionPolicy("open","original",True,.0015),
    "TAIL_COST":ExecutionPolicy("close","tail",True,.0015),
}


def simulate(book:Any,signals:dict[int,list[int]],horizon:int,policy_name:str,
             regimes:dict[str,str],start:str=base.START,end:str=base.END) -> tuple[Any,dict[str,Any],list[dict[str,Any]]]:
    """Self-financing ACT015 sleeves plus aggregate scheduled-exit lot risk."""
    import numpy as np
    import pandas as pd
    policy=POLICIES[policy_name]
    days=[i for i,d in enumerate(book.dates) if start<=d<=end]
    if not days:
        raise Act017Error("EMPTY_EVALUATION_DATES")
    first,last=days[0],days[-1]
    cash=np.full(horizon,1/horizon)
    holdings=[]
    stats=dict(attempts=0,fills=0,blocked=defaultdict(int),delayed_positions=0,
               delayed_exit_sessions=0,stale_mark_sessions=0,buy_fees=0.,sell_fees=0.,max_daily_holding=0)
    lot_counts=defaultdict(lambda:dict(scheduled_exit_denominator=0,net_loss_below_minus10=0,
                                      delayed_positions=0,unclosed_positions=0))
    def count(position:dict[str,Any],key:str) -> None:
        for regime in {"ALL",position["signal_regime"]}:
            lot_counts[regime][key]+=1
    def enter(signal_day:int,execution_day:int) -> None:
        codes=list(dict.fromkeys(signals.get(signal_day,[])))
        if not codes or signal_day+horizon>last:
            return
        sleeve=(signal_day-first)%horizon
        budget=cash[sleeve]/len(codes)
        for code in codes:
            stats["attempts"]+=1
            price=book.values["open" if policy.clock=="open" else "close"][execution_day,code]
            gate=policy.entry_gate
            if gate=="original":
                allowed,reason=base.entry_status(book,execution_day,code)
            elif gate=="tail":
                allowed,reason=tail_close_allowed(book,execution_day,code)
            elif gate=="next_raw_open":
                allowed=raw_open_allowed(book,signal_day+1,code) and book.valid[signal_day,code]
                reason="missing_matched_next_open_or_signal_close"
            elif gate=="raw_open":
                allowed,reason=raw_open_allowed(book,execution_day,code),"missing_raw_open_quote"
            else:
                allowed,reason=bool(book.valid[execution_day,code]),"invalid_signal_close"
            if not allowed or not np.isfinite(price) or price<=0:
                stats["blocked"][reason]+=1
                continue
            if budget<=0:
                stats["blocked"]["no_sleeve_cash"]+=1
                continue
            notional=budget/(1+policy.fee)
            cash[sleeve]-=budget
            stats["buy_fees"]+=budget-notional
            stats["fills"]+=1
            holdings.append(dict(sleeve=sleeve,code=code,shares=notional/price,target=signal_day+horizon,
                                 mark=price,delayed=False,entry_budget=budget,
                                 signal_regime=regimes.get(book.dates[signal_day],"UNKNOWN")))
    rows=[]
    for day in days:
        attempts_before,fills_before=stats["attempts"],stats["fills"]
        if policy.clock=="open" and day>first:
            enter(day-1,day)
        retained=[]
        for position in holdings:
            code=position["code"]
            price=book.values["close"][day,code]
            if book.valid[day,code] and np.isfinite(price) and price>0:
                position["mark"]=float(price)
            else:
                stats["stale_mark_sessions"]+=1
            if day>=position["target"]:
                allowed=(base.exit_status(book,day,code)[0] if policy.constrained_exit else bool(book.valid[day,code]))
                if allowed:
                    gross=position["shares"]*position["mark"]
                    net=gross*(1-policy.fee)
                    cash[position["sleeve"]]+=net
                    stats["sell_fees"]+=gross*policy.fee
                    if day==position["target"]:
                        count(position,"scheduled_exit_denominator")
                        if net/position["entry_budget"]-1 < -.10:
                            count(position,"net_loss_below_minus10")
                    continue
                if not position["delayed"]:
                    position["delayed"]=True
                    stats["delayed_positions"]+=1
                    count(position,"delayed_positions")
                stats["delayed_exit_sessions"]+=1
            retained.append(position)
        holdings=retained
        if policy.clock=="close":
            enter(day,day)
        invested=sum(p["shares"]*p["mark"] for p in holdings)
        nav=float(cash.sum()+invested)
        if not np.isfinite(nav) or nav<=0 or cash.min() < -1e-10:
            raise Act017Error("SELF_FINANCING_INVALID")
        nheld=len({p["code"] for p in holdings})
        stats["max_daily_holding"]=max(stats["max_daily_holding"],nheld)
        rows.append(dict(trade_date=book.dates[day],nav=nav,cash=float(cash.sum()),invested=invested,
                         holding_count=nheld,position_lots=len(holdings),gross_exposure=invested/nav,
                         attempts=stats["attempts"]-attempts_before,fills=stats["fills"]-fills_before))
    for position in holdings:
        count(position,"unclosed_positions")
    lot_rows=[]
    for regime,values in lot_counts.items():
        denominator=values["scheduled_exit_denominator"]
        lot_rows.append(dict(signal_regime=regime,**values,
                             net_loss_below_minus10_rate=values["net_loss_below_minus10"]/denominator if denominator else None))
    stats.update(blocked=dict(stats["blocked"]),residual_positions=len(holdings),
                 residual_market_value=sum(p["shares"]*p["mark"] for p in holdings),
                 fill_rate=stats["fills"]/stats["attempts"] if stats["attempts"] else None,
                 execution_policy=policy_name,real_fill_confirmed=False)
    return pd.DataFrame(rows),stats,lot_rows


def ranked_signals(candidates:Any,score:str|None=None,top:int|None=None,
                   f5:bool=False,b_confirmed:bool=False) -> dict[int,list[int]]:
    mask=candidates.trade_date.between(base.START,base.END)
    if f5:
        mask &= candidates.f5_s1_pass
    if b_confirmed:
        mask &= candidates.b_any
    if score:
        mask &= candidates[score].notna()
    rows=candidates.loc[mask]
    if score:
        # Negative Q15 is deliberately sorted descending: -.02 is safer than -.20.
        rows=rows.sort_values(["trade_date",score,"ts_code"],ascending=[True,False,True],kind="mergesort")
    return {int(day):(group.head(top) if top else group).code_index.astype(int).tolist()
            for day,group in rows.groupby("session",sort=True)}


def attribution_values(endpoints:dict[str,float]) -> dict[str,float]:
    i0,matched,raw,filtered,cost=(endpoints[k] for k in ("I0","MATCHED_D0","O0_RAW","O0_FILTERED","OCOST"))
    gap=matched-raw
    availability=(i0-matched)+(raw-filtered)
    fees=filtered-cost
    residual=(i0-cost)-(gap+availability+fees)
    if abs(residual)>1e-10:
        raise Act017Error("ATTRIBUTION_NOT_ADDITIVE")
    return dict(ideal_minus_original_constrained=i0-cost,pure_gap_contribution=gap,
                fill_availability_contribution=availability,sequential_fee_contribution=fees,
                additive_residual=residual,**{f"{k}_absolute_return":v for k,v in endpoints.items()})


def certify_legacy(daily:Any,accepted_path:Path) -> dict[str,Any]:
    import numpy as np
    import pandas as pd
    accepted=pd.read_csv(accepted_path,dtype={"trade_date":str})
    results=[]
    for strategy in ("clean","clean_b"):
        for horizon in (3,5):
            for name,mode in (("I0","ideal"),("OCOST","constrained")):
                observed=daily.loc[(daily.strategy==strategy)&(daily.horizon==horizon)&(daily["mode"]==name)].sort_values("trade_date")
                prior=accepted.loc[(accepted.strategy==strategy)&(accepted.horizon==horizon)&(accepted["mode"]==mode)].sort_values("trade_date")
                if (observed.trade_date.tolist()!=prior.trade_date.tolist() or len(observed)!=499
                    or not np.allclose(observed.nav.to_numpy(),prior.nav.to_numpy(),rtol=1e-11,atol=1e-12)):
                    raise Act017Error(f"ACT015_LEGACY_NAV_PARITY_FAIL:{strategy}:{horizon}:{mode}")
                results.append(dict(strategy=strategy,horizon=horizon,mode=mode,status="PASS_499_DAILY_NAV"))
    return dict(status="PASS",comparisons=results,accepted_path=str(accepted_path))


def run_once(data_root:Path,output_dir:Path,accepted_run_dir:Path,resume:bool=False) -> dict[str,Any]:
    import hashlib
    import numpy as np
    import pandas as pd
    import resource
    output_dir,accepted_run_dir=Path(output_dir).resolve(),Path(accepted_run_dir).resolve()
    data_root=Path(data_root).resolve()
    if (output_dir==data_root or data_root in output_dir.parents or output_dir==accepted_run_dir
        or accepted_run_dir in output_dir.parents or output_dir in accepted_run_dir.parents):
        raise Act017Error("OUTPUT_MUST_PRESERVE_AUTHORITY_AND_ACCEPTED_RUN")
    output_dir.mkdir(parents=True,exist_ok=True)
    if (output_dir/"run_summary.json").exists() and not resume:
        raise Act017Error("EXISTING_RUN_REQUIRES_EXPLICIT_RESUME")
    progress_path=output_dir/"run_progress.jsonl"
    def progress(stage:str,status:str,details:dict[str,Any]) -> None:
        base.a9._append_progress(progress_path,stage,status,details)
    summary=dict(schema=SCHEMA,signed_doc=SIGNED_DOC,status="RUNNING",**FLAGS,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        evaluation_window=[base.START,base.END],evaluation_sessions_expected=499,
        fit_plan=dict(Q15=9,executable_T3=9,S=0,search=0),resume=resume,
        benchmark="same external all-A EW daily close-to-close fully invested cost-free; not exposure/execution matched",
        exact_exchange_limit_price_coverage="CANNOT_CONFIRM",real_fills_confirmed=False,
        tail_close="counterfactual D close decision and buy; conservative D prior-close cap proxy; no exact official limits",
        attribution="sequential compounded cumulative-return contrasts; MATCHED_D0 diagnostic uses same future-T1 eligible quotes as raw O0",
        feature_names=list(FEATURES),row_export_files=0,full_panel_written=False)
    base._write_json(output_dir/"run_summary.json",summary)
    progress("run","STARTED",{"signed_doc":SIGNED_DOC,"resume":resume})
    try:
        with base.v12.bind_current_panels(data_root) as (panel_path,source,recheck):
            binding=base.a9._assert_bound_source(source)
            summary.update(binding=binding,source=source,model_contract=model_contract(binding))
            accepted_summary=__import__("json").loads((accepted_run_dir/"run_summary.json").read_text())
            if accepted_summary.get("binding")!=binding:
                raise Act017Error("ACCEPTED_ACT015_BINDING_MISMATCH")
            raw,read_meta=base.read_projected(panel_path)
            summary["read"]=read_meta
            progress("read","PASS",read_meta)
            book=base.PriceBook.from_frame(raw)
            dates=[d for d in book.dates if base.START<=d<=base.END]
            if len(dates)!=499 or dates[-1]!=base.END:
                raise Act017Error("EXPECTED_499_EVALUATION_DATES")
            candidates,meta=base.build_candidates(raw,book,read_meta["formula_prep_start"],progress)
            del raw
            if int(meta["raw_union_counts"].get("20261119",-1))!=159 or not np.isclose(base.f5_s1(meta["raw_union_counts"]).get("20261119",np.nan),.075):
                raise Act017Error("ACT015_D19_F5_PARITY_FAIL")
            summary.update(clean_candidate_rows=len(candidates),f5_d19_raw_count=159,f5_d19_percentile=.075)
            recheck()
            daily_frames=[]
            execution_reports=[]
            lot_reports=[]
            attribution=[]
            def evaluate(strategy:str,signals:dict[int,list[int]],horizon:int,policy:str) -> Any:
                daily,stats,lots=simulate(book,signals,horizon,policy,meta["regimes"])
                daily=daily.assign(strategy=strategy,horizon=horizon,mode=policy)
                daily["daily_return"]=daily.nav.pct_change().fillna(daily.nav.iloc[0]-1)
                benchmark=daily.trade_date.map(meta["all_a_d_returns"]).astype(float)
                benchmark.iloc[0]=0.
                daily["benchmark_daily_return"]=benchmark
                daily["benchmark_nav"]=(1+benchmark).cumprod()
                daily["relative_nav"]=daily.nav/daily.benchmark_nav
                daily["regime"]=daily.trade_date.map(meta["regimes"])
                daily_frames.append(daily)
                execution_reports.append(dict(strategy=strategy,horizon=horizon,mode=policy,**stats))
                lot_reports.extend(dict(strategy=strategy,horizon=horizon,mode=policy,**lot) for lot in lots)
                return daily
            for strategy,b_gate in (("clean",False),("clean_b",True)):
                signals=ranked_signals(candidates,b_confirmed=b_gate)
                for horizon in (3,5):
                    endpoints={}
                    for policy in POLICIES:
                        daily=evaluate(strategy,signals,horizon,policy)
                        endpoints[policy]=float(daily.nav.iloc[-1]-1)
                    attribution.append(dict(strategy=strategy,horizon=horizon,**attribution_values(endpoints)))
            summary["legacy_parity"]=certify_legacy(pd.concat(daily_frames,ignore_index=True),accepted_run_dir/"daily_portfolio_nav.csv")
            progress("legacy_parity","PASS",summary["legacy_parity"])
            pd.DataFrame(attribution).to_csv(output_dir/"attribution_decomposition.csv",index=False)
            candidates,maturity=attach_targets(candidates,book)
            base._write_json(output_dir/"target_maturity_ledger.json",maturity)
            summary["target_maturity"]=maturity
            candidates,fit_report=fit_models(candidates,binding,output_dir,progress,resume)
            summary["fit_accounting"]=fit_report
            for model,score in (("A1_Q15","q15_score"),("A2_EXEC_T3","exec_t3_score")):
                for top in (10,20):
                    for f5 in (False,True):
                        strategy=f"{model}_TOP{top}_F5_{'ON' if f5 else 'OFF'}"
                        signals=ranked_signals(candidates,score,top,f5)
                        for horizon in ((3,5) if model=="A1_Q15" else (3,)):
                            for policy in (("TAIL_COST","OCOST") if model=="A1_Q15" else ("OCOST",)):
                                evaluate(strategy,signals,horizon,policy)
                        progress("portfolio","STRATEGY_COMPLETE",{"strategy":strategy})
            del candidates
            daily=pd.concat(daily_frames,ignore_index=True)
            metrics=base.aggregate_metrics(daily)
            daily.to_csv(output_dir/"daily_portfolio_nav.csv",index=False)
            metrics.to_csv(output_dir/"quarter_regime_metrics.csv",index=False)
            pd.DataFrame(lot_reports).to_csv(output_dir/"scheduled_exit_lot_risk.csv",index=False)
            base._write_json(output_dir/"execution_accounting.json",execution_reports)
            recheck()
            summary.update(status="COMPLETED_ESTIMATED_EXECUTION_RESEARCH",metric_rows=len(metrics),
                           daily_aggregate_rows=len(daily),peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                           completed_model_checkpoints=len(fit_report["quarters"]),
                           artifacts=["attribution_decomposition.csv","quarter_regime_metrics.csv",
                                      "daily_portfolio_nav.csv","scheduled_exit_lot_risk.csv",
                                      "target_maturity_ledger.json","fit_accounting.json","execution_accounting.json"])
            base._write_json(output_dir/"run_summary.json",summary)
            progress("run","COMPLETED",{"fits":fit_report["actual_fits"],"reused":fit_report["reused"]})
            return summary
    except Exception as exc:
        summary.update(status="FAILED",error=f"{type(exc).__name__}:{exc}")
        base._write_json(output_dir/"run_summary.json",summary)
        progress("run","FAILED",{"error":summary["error"]})
        raise


def main(argv:list[str]|None=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--accepted-run-dir",type=Path,required=True)
    parser.add_argument("--resume",action="store_true",help="Reuse completed exact-contract quarter checkpoints; fit missing quarters only")
    args=parser.parse_args(argv)
    run_once(args.data_root,args.output_dir,args.accepted_run_dir,args.resume)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
