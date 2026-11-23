"""Signed ACT-015 execution study. RAM-only projected V4 input; no row export.

This runner is deliberately separate from the unrelated ACT-015 study. It uses
the accepted ACT009B formulas and a self-financing H-sleeve portfolio. It never
updates a panel, trading gate, service, or external destination.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Callable

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from ops import pft_s_v12_full_a as v12
from ops import pft_sb_v13_act009 as a9
from ops import pft_sb_v13_act009b as a9b

SCHEMA = "pft_act015_execution.v1"
SIGNED_DOC = "1GKJhP3mVyIoZRTnUyZ0CP4eephSyCuA2Buje47LCjv4"
START, END, TRAIN_START = "20241101", "20261120", "20231001"
FLAGS = dict(v12.FLAGS)
MODEL_FEATURES = tuple(a9b.F5_B_FEATURE_NAMES) + ("f5_s1_percentile",)
STRATEGIES = ("clean", "clean_b", "clean_b_f5_s1", "clean_b_f5_s1_hgb_top20")
OPTIONAL_ALIASES = {
    "tradeable_basic": ("tradeable_basic",),
    "limit_up_approx": ("limit_up_approx",),
    "limit_down_approx": ("limit_down_approx",),
    "pre_close": ("pre_close", "prev_close"),
    "limit_up_price": ("up_limit", "limit_up_price", "upper_limit"),
    "limit_down_price": ("down_limit", "limit_down_price", "lower_limit"),
}


class ExecutionError(RuntimeError):
    pass


def quarter(day: str) -> str:
    return f"{day[:4]}Q{(int(day[4:6])-1)//3+1}"


def quarter_start(value: str) -> str:
    return f"{value[:4]}{1+3*(int(value[-1])-1):02d}01"


def training_start(value: str) -> str:
    return f"{int(value[:4])-1}{1+3*(int(value[-1])-1):02d}01"


def read_projected(panel_path: Path) -> tuple[Any, dict[str, Any]]:
    """Exactly one logical read with explicit columns and date predicates."""
    from ops.research_panel_logical import parquet
    schema = parquet.read_schema(panel_path)
    actual = {name.lower(): name for name in schema.names}
    mapping = {}
    for semantic, aliases in {**v12.ALIASES, **OPTIONAL_ALIASES}.items():
        found = next((actual[x] for x in aliases if x in actual), None)
        if found is None and semantic in v12.ALIASES:
            raise ExecutionError(f"REQUIRED_COLUMN_MISSING:{semantic}")
        if found:
            mapping[semantic] = found
    prep = (datetime.strptime(TRAIN_START, "%Y%m%d") - timedelta(days=120)).strftime("%Y%m%d")
    warm = (datetime.strptime(prep, "%Y%m%d") - timedelta(days=180)).strftime("%Y%m%d")
    names = list(dict.fromkeys(mapping.values()))
    filters = [(mapping["trade_date"], ">=", v12._arrow_date_value(schema, mapping["trade_date"], warm)),
               (mapping["trade_date"], "<=", v12._arrow_date_value(schema, mapping["trade_date"], END))]
    table = parquet.read_table(panel_path, columns=names, filters=filters)
    frame = table.to_pandas().rename(columns={v: k for k, v in mapping.items()})
    del table
    frame["market_type"] = frame["market_type"].fillna("").astype(str).str.upper().str.strip()
    frame = frame.loc[frame.market_type.isin({"A", "A_SHARE", "ASHARE", "CN_A", "A-SHARE", "SH", "SZ", "BJ"})].copy()
    frame["ts_code"] = v12._normalize_observed_column(frame.ts_code, v12._code, "ts_code")
    frame["trade_date"] = v12._normalize_observed_column(frame.trade_date, lambda x: v12._day(x, "trade_date"), "trade_date")
    frame.sort_values(["ts_code", "trade_date"], inplace=True, kind="mergesort")
    frame.reset_index(drop=True, inplace=True)
    if frame.duplicated(["ts_code", "trade_date"]).any():
        raise ExecutionError("DUPLICATE_PANEL_KEY")
    return frame, {"logical_read_calls": 1, "columns": mapping, "read_start": warm,
                   "formula_prep_start": prep, "asof": END, "rows": len(frame),
                   "missing_optional_columns": sorted(set(OPTIONAL_ALIASES)-set(mapping))}


@dataclass
class PriceBook:
    dates: list[str]
    codes: list[str]
    values: dict[str, Any]
    valid: Any

    @classmethod
    def from_frame(cls, frame: Any) -> "PriceBook":
        import numpy as np
        import pandas as pd
        dates, codes = sorted(frame.trade_date.unique()), sorted(frame.ts_code.unique())
        di, ci = {x: i for i, x in enumerate(dates)}, {x: i for i, x in enumerate(codes)}
        d = frame.trade_date.map(di).to_numpy(dtype=int)
        c = frame.ts_code.map(ci).to_numpy(dtype=int)
        values = {}
        for name in ("open", "high", "low", "close", "vol", "pct_chg", *OPTIONAL_ALIASES):
            if name not in frame:
                continue
            target = np.full((len(dates), len(codes)), np.nan)
            target[d, c] = pd.to_numeric(frame[name], errors="coerce").to_numpy(dtype=float)
            values[name] = target
        o, h, l, p, v = (values[x] for x in ("open", "high", "low", "close", "vol"))
        valid = (np.isfinite(o+h+l+p+v) & (np.minimum.reduce([o,h,l,p])>0)
                 & (v>0) & (h>=np.maximum.reduce([o,l,p])) & (l<=np.minimum.reduce([o,h,p])))
        return cls(dates, codes, values, valid)

    def forward_returns(self, horizon: int) -> Any:
        import numpy as np
        out = np.full(self.valid.shape, np.nan)
        close = self.values["close"]
        known = self.valid[:-horizon] & self.valid[horizon:]
        out[:-horizon] = np.where(known, close[horizon:]/close[:-horizon]-1, np.nan)
        return out


def f5_s1(raw_counts: Any) -> Any:
    """Signed weak empirical CDF: count(window <= D) / 40, including D."""
    return raw_counts.rolling(40, min_periods=40).apply(
        lambda window: (window <= window[-1]).sum()/40, raw=True)


def build_candidates(raw: Any, book: PriceBook, prep_start: str,
                     progress: Callable[..., None] | None = None,
                     cohort_size: int = 256) -> tuple[Any, dict[str, Any]]:
    """Reuse group-isolated formulas in bounded cohorts, then global aggregates."""
    import numpy as np
    import pandas as pd
    dates = book.dates
    date_index = {day: i for i, day in enumerate(dates)}
    counts = pd.Series(0, index=dates, dtype="int64")
    activity_n = pd.Series(0., index=dates)
    activity_up = activity_n.copy()
    projections = []
    keep = list(dict.fromkeys(["ts_code", "trade_date", *v12.FEATURE_NAMES,
          *a9.B_FEATURE_NAMES, "pullback", "readvance", "rebuild_v13", "union",
          "v13_candidate_union", "clean_union", "b1_candidate", "b2_candidate", "b3_candidate",
          "hard_score_pullback", "hard_score_readvance", "hard_score_rebuild",
          "_anchor_date", "rebuild_episode_id"]))
    # Input is sorted by code. Slicing cohorts avoids thousands of pandas setup
    # calls, without changing per-security rolling or repair-episode state.
    code_values=raw.ts_code.to_numpy()
    boundaries=np.r_[0,np.flatnonzero(code_values[1:]!=code_values[:-1])+1,len(raw)]
    if cohort_size<1:
        raise ExecutionError("INVALID_FORMULA_COHORT_SIZE")
    for first_code in range(0,len(boundaries)-1,cohort_size):
        last_code=min(first_code+cohort_size,len(boundaries)-1)
        group=raw.iloc[boundaries[first_code]:boundaries[last_code]]
        part, _ = v12._vectorize_rows(group.reset_index(drop=True), start_date=prep_start, asof_date=END)
        if not len(part):
            continue
        part, _ = a9._attach_exact_market_features(part, dates)
        part, _ = a9._derive_rebuild_v13(part, dates)
        part, _ = a9._add_b_confirmations(part)
        part, _ = a9b._add_f1_f4(part)
        day_counts = part.groupby("trade_date", observed=True)["union"].sum()
        counts.loc[day_counts.index] += day_counts.astype("int64")
        valid = a9._valid_trade_rows(part)
        activity_known = valid & part._d_vr5.notna() & part._prior5v.gt(0)
        n = part.loc[activity_known].groupby("trade_date", observed=True).size()
        up = part.loc[activity_known & part._d_vr5.ge(1)].groupby("trade_date", observed=True).size()
        activity_n.loc[n.index] += n
        activity_up.loc[up.index] += up
        pop = part["union"] | part["v13_candidate_union"]
        # S score is computed globally after all symbols have been recombined.
        projections.append(part.loc[pop, [name for name in keep if name in part]].copy())
        if progress:
            progress("formula", "PROGRESS", {"symbols_done": last_code, "symbols_total": len(book.codes),
                                               "cohort_size":cohort_size})
    if not projections:
        raise ExecutionError("NO_FORMULA_CANDIDATES")
    out = pd.concat(projections, ignore_index=True)
    out, _ = a9._apply_s_rule(out)
    # Exactly global market denominators; never per-symbol approximations.
    valid = book.valid
    close = book.values["close"]
    def prior_return(n: int) -> Any:
        result = np.full(valid.shape, np.nan)
        result[n:] = np.where(valid[n:] & valid[:-n], close[n:]/close[:-n]-1, np.nan)
        return result
    returns1, returns5 = prior_return(1), prior_return(5)
    def mean_rows(array: Any) -> Any:
        n = np.isfinite(array).sum(axis=1)
        return np.divide(np.nansum(array, axis=1), n, out=np.full(len(n), np.nan), where=n>0)
    mean1, mean5 = mean_rows(returns1), mean_rows(returns5)
    pct = book.values["pct_chg"]
    breadth_known = valid & np.isfinite(pct)
    denominator = breadth_known.sum(axis=1)
    breadth = np.divide((breadth_known & (pct>0)).sum(axis=1), denominator,
                        out=np.full(len(dates), np.nan), where=denominator>0)
    activity = activity_up/activity_n.replace(0, np.nan)
    median = activity.shift(1).rolling(20, min_periods=20).median()
    daily = {"market_breadth_up_fraction": breadth,
             "market_activity_fraction": activity.to_numpy(),
             "market_activity_prior20_median": median.to_numpy(),
             "crowding": counts.to_numpy(),
             "crowding_rolling_p25": counts.shift(1).rolling(60,min_periods=60).quantile(.25).to_numpy(),
             "crowding_rolling_p75": counts.shift(1).rolling(60,min_periods=60).quantile(.75).to_numpy(),
             "f5_s1_percentile": f5_s1(counts).to_numpy()}
    sid = out.trade_date.map(date_index).to_numpy(dtype=int)
    cid = out.ts_code.map({x:i for i,x in enumerate(book.codes)}).to_numpy(dtype=int)
    for name, value in daily.items():
        out[name] = value[sid]
    out["exact_d_return"], out["exact_trailing5_return"] = returns1[sid,cid], returns5[sid,cid]
    out["relative_d_return"] = out.exact_d_return.to_numpy()-mean1[sid]
    out["relative_trailing5_return"] = out.exact_trailing5_return.to_numpy()-mean5[sid]
    out["breadth_known_feature"] = np.isfinite(breadth[sid]).astype(float)
    out["activity_timing_known_feature"] = (np.isfinite(activity.to_numpy()[sid]) & np.isfinite(median.to_numpy()[sid])).astype(float)
    out["breadth_over_50_feature"] = (breadth[sid]>.5).astype(float)
    out["activity_over_prior20_median_feature"] = (activity.to_numpy()[sid]>median.to_numpy()[sid]).astype(float)
    out["timing_gate_feature"] = (out.breadth_known_feature.eq(1) & out.activity_timing_known_feature.eq(1)
                                      & out.breadth_over_50_feature.eq(1) & out.activity_over_prior20_median_feature.eq(1)).astype(float)
    out = out.loc[out.clean_union & out.trade_date.ge(TRAIN_START)].copy()
    out["b_any"] = out[["b1_candidate", "b2_candidate", "b3_candidate"]].any(axis=1)
    out["f5_s1_pass"] = out.f5_s1_percentile.notna() & out.f5_s1_percentile.le(.70)
    sid = out.trade_date.map(date_index).to_numpy(dtype=int)
    cid = out.ts_code.map({x:i for i,x in enumerate(book.codes)}).to_numpy(dtype=int)
    ret5 = book.forward_returns(5)
    mean_forward5 = mean_rows(ret5)
    out["label_excess_t5"] = ret5[sid,cid]-mean_forward5[sid]
    peak = close[sid,cid].copy()
    mdd = np.zeros(len(out))
    complete = np.ones(len(out), dtype=bool)
    for offset in range(1,6):
        idx = sid+offset
        inside = idx<len(dates)
        p = np.full(len(out), np.nan)
        p[inside] = np.where(valid[idx[inside],cid[inside]], close[idx[inside],cid[inside]], np.nan)
        complete &= np.isfinite(p)
        peak = np.maximum(peak, np.nan_to_num(p, nan=0))
        mdd = np.minimum(mdd, np.nan_to_num(p/peak-1, nan=0))
    out["label"] = np.where(complete & out.label_excess_t5.notna(),
                              ((out.label_excess_t5>=.03)&(mdd>=-.05)).astype(float), np.nan)
    out["label_target_date"] = [dates[x+5] if x+5<len(dates) else "" for x in sid]
    out["session"], out["code_index"] = sid, cid
    regime_base = pd.Series(mean1,index=dates)
    trailing = (1+regime_base).rolling(60,min_periods=60).apply(np.prod,raw=True).shift(1)-1
    regimes = np.where(trailing.isna(), "UNKNOWN", np.where(trailing>=.05,"bull",np.where(trailing<=-.05,"bear","sideways")))
    return out.reset_index(drop=True), {"raw_union_counts": counts, "regimes": dict(zip(dates,regimes)),
          "all_a_d_returns": dict(zip(dates,mean1)), "clean_rows": len(out), "candidate_feature_count": len(MODEL_FEATURES)}


def fit_quarters(candidates: Any, output_dir: Path | None = None,
                 estimator_factory: Callable[[], Any] | None = None,
                 progress: Callable[..., None] | None = None) -> tuple[Any, list[dict[str, Any]]]:
    """One fixed HGB per quarter, TRAIN-only balanced weights and group purge."""
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    out = candidates.copy()
    out["p_hgb"] = np.nan
    reports = []
    quarters = sorted({quarter(x) for x in out.loc[out.trade_date.between(START,END),"trade_date"]})
    for q in quarters:
        first, low = quarter_start(q), max(TRAIN_START, training_start(q))
        train = (out.b_any & out.trade_date.ge(low) & out.trade_date.lt(first)
                 & out.label_target_date.ne("") & out.label_target_date.lt(first) & out.label.notna())
        predict = out.b_any & out.trade_date.map(quarter).eq(q) & out.trade_date.between(START,END)
        anchor = out.ts_code.astype(str)+"|K|"+out._anchor_date.fillna("").astype(str)
        has_anchor = out._anchor_date.fillna("").astype(str).ne("")
        repair = out.rebuild_episode_id.fillna("").astype(str)
        cross_k = set(anchor[train & has_anchor]) & set(anchor[predict & has_anchor])
        cross_repair = set(repair[train & repair.ne("")]) & set(repair[predict & repair.ne("")])
        purge = train & ((has_anchor & anchor.isin(cross_k)) | (repair.ne("") & repair.isin(cross_repair)))
        before = int(train.sum())
        train &= ~purge
        report = {"quarter": q, "train_start": low, "train_end_exclusive": first,
                  "target_mature_before": first, "train_before_purge": before,
                  "purged_rows": int(purge.sum()), "train_rows": int(train.sum()),
                  "predict_rows": int(predict.sum()), "fits": 0,
                  "cross_k_groups": len(cross_k), "cross_repair_groups": len(cross_repair)}
        y = out.loc[train,"label"].to_numpy(dtype=int)
        classes, n = np.unique(y,return_counts=True)
        if len(classes)!=2 or not predict.any():
            report["status"] = "CANNOT_CONFIRM_INSUFFICIENT_CLASSES_OR_OOS"
            reports.append(report)
            continue
        model = (estimator_factory() if estimator_factory else HistGradientBoostingClassifier(
            max_iter=100,learning_rate=.05,max_leaf_nodes=7,max_depth=3,
            l2_regularization=1.,early_stopping=False,random_state=0))
        weights = np.where(y==classes[0],len(y)/(2*n[0]),len(y)/(2*n[1]))
        x = out.loc[train,list(MODEL_FEATURES)].to_numpy(dtype=float,copy=True)
        x[~np.isfinite(x)] = np.nan
        if progress:
            progress("hgb", "FIT_STARTED", report)
        model.fit(x,y,sample_weight=weights)
        score_x = out.loc[predict,list(MODEL_FEATURES)].to_numpy(dtype=float,copy=True)
        score_x[~np.isfinite(score_x)] = np.nan
        out.loc[predict,"p_hgb"] = model.predict_proba(score_x)[:,1]
        report.update(status="FIT_COMPLETE",fits=1,positive_rows=int(y.sum()),
                      latest_train_signal=out.loc[train,"trade_date"].max(),
                      latest_train_target=out.loc[train,"label_target_date"].max(),
                      class_balance="TRAIN-only n/(2*n_class)")
        if output_dir:
            import joblib
            path = output_dir/f"hgb_{q}.joblib"
            joblib.dump({"model":model,"features":MODEL_FEATURES,"fit":report,
                         "signed_doc":SIGNED_DOC,**FLAGS},path)
            report["model_file"] = path.name
        reports.append(report)
        if progress:
            progress("hgb", "FIT_COMPLETE", report)
    return out,reports


def replay_source_contract() -> dict[str,Any]:
    """Verify model-producing source against the exact accepted fit commit."""
    import ast
    import hashlib
    import subprocess
    commit="c9639d42b4ec6212c5dd2c8da4d56d45e56642ad"
    relative="ops/pft_act015_execution.py"
    def original(path:str) -> bytes:
        result=subprocess.run(["git","-C",str(APP_ROOT),"show",f"{commit}:{path}"],
                              check=True,capture_output=True)
        return result.stdout
    prior=original(relative)
    expected="6359654b50785d5e7c166d8ec2723f72ad8c017ee7b3de3078946ca8dae3b6ae"
    if hashlib.sha256(prior).hexdigest()!=expected:
        raise ExecutionError("REPLAY_ORIGINAL_SOURCE_SHA_MISMATCH")
    current=Path(__file__).read_bytes()
    before,after=ast.parse(prior),ast.parse(current)
    protected={"quarter","quarter_start","training_start","read_projected","PriceBook",
               "f5_s1","build_candidates","fit_quarters","select_signals","board_band",
               "entry_status","exit_status","SIGNED_DOC","START","MODEL_FEATURES","OPTIONAL_ALIASES"}
    def selected(tree:Any) -> dict[str,str]:
        result={}
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in protected:
                result[node.name]=ast.dump(node,include_attributes=False)
            if isinstance(node,ast.Assign):
                names={n.id for target in node.targets for n in ast.walk(target) if isinstance(n,ast.Name)}
                for name in names & protected:
                    result[name]=ast.dump(node,include_attributes=False)
        return result
    if selected(before)!=selected(after):
        raise ExecutionError("REPLAY_MODEL_OR_FORMULA_POLICY_SOURCE_CHANGED")
    helpers={}
    for module in (v12,a9,a9b):
        path=Path(module.__file__).resolve()
        rel=str(path.relative_to(APP_ROOT))
        observed=hashlib.sha256(path.read_bytes()).hexdigest()
        if observed!=hashlib.sha256(original(rel)).hexdigest():
            raise ExecutionError(f"REPLAY_HELPER_SOURCE_CHANGED:{rel}")
        helpers[rel]=observed
    return {"original_fit_commit":commit,"original_source_sha256":expected,
            "replay_source_sha256":hashlib.sha256(current).hexdigest(),
            "protected_policy_ast":"MATCH","helper_sha256":helpers}


def replay_quarters(candidates:Any,model_dir:Path,binding:dict[str,Any],
                    progress:Callable[...,None]|None=None) -> tuple[Any,dict[str,Any]]:
    """Predict only with all nine original quarter weights; never call fit."""
    import hashlib
    import joblib
    import numpy as np
    source_check=replay_source_contract()
    model_dir=Path(model_dir).resolve()
    summary_path=model_dir/"run_summary.json"
    fit_path=model_dir/"fit_accounting.json"
    original_summary=json.loads(summary_path.read_text())
    accounting=json.loads(fit_path.read_text())
    if (original_summary.get("status")!="COMPLETED_ESTIMATED_EXECUTION_RESEARCH"
        or original_summary.get("signed_doc")!=SIGNED_DOC
        or original_summary.get("binding")!=binding
        or binding!={**a9.EXPECTED_BINDING,"asof_date":str(a9.EXPECTED_BINDING["asof_date"])}
        or original_summary.get("evaluation_window")!=[START,END]
        or original_summary.get("model_features")!=list(MODEL_FEATURES)
        or any(original_summary.get(k)!=v for k,v in FLAGS.items())
        or original_summary.get("fit_accounting")!=accounting):
        raise ExecutionError("REPLAY_ORIGINAL_RUN_CONTRACT_MISMATCH")
    expected=["2024Q4",*[f"{year}Q{q}" for year in (2025,2026) for q in (1,2,3,4)]]
    reports=accounting.get("quarters",[])
    if (accounting.get("HGB")!=9 or accounting.get("S")!=0 or accounting.get("search")!=0
        or [x.get("quarter") for x in reports]!=expected
        or any(x.get("fits")!=1 or x.get("status")!="FIT_COMPLETE" for x in reports)):
        raise ExecutionError("REPLAY_REQUIRES_EXACT_NINE_COMPLETED_QUARTERS")
    out=candidates.copy()
    out["p_hgb"]=np.nan
    reused=[]
    for report in reports:
        q=report["quarter"]
        filename=f"hgb_{q}.joblib"
        if report.get("model_file")!=filename:
            raise ExecutionError("REPLAY_MODEL_FILENAME_MISMATCH")
        path=model_dir/filename
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        payload=joblib.load(path)
        stored_fit={k:v for k,v in report.items() if k!="model_file"}
        if (payload.get("signed_doc")!=SIGNED_DOC or list(payload.get("features",[]))!=list(MODEL_FEATURES)
            or payload.get("fit")!=stored_fit or any(payload.get(k)!=v for k,v in FLAGS.items())):
            raise ExecutionError(f"REPLAY_WEIGHT_CONTRACT_MISMATCH:{q}")
        predict=out.b_any & out.trade_date.map(quarter).eq(q) & out.trade_date.between(START,END)
        if int(predict.sum())!=report["predict_rows"]:
            raise ExecutionError(f"REPLAY_PREDICTION_POPULATION_CHANGED:{q}")
        score_x=out.loc[predict,list(MODEL_FEATURES)].to_numpy(dtype=float,copy=True)
        score_x[~np.isfinite(score_x)]=np.nan
        out.loc[predict,"p_hgb"]=payload["model"].predict_proba(score_x)[:,1]
        reused.append({"quarter":q,"fits":0,"reused":True,"model_path":str(path),
                       "model_sha256":digest,"predict_rows":int(predict.sum())})
        if progress:
            progress("hgb","REPLAY_PREDICT_ONLY",reused[-1])
    return out,{"S":0,"HGB":0,"search":0,"reused_HGB":9,"quarters":reused,
                "source_checks":source_check,"original_model_dir":str(model_dir),
                "original_fit_accounting_sha256":hashlib.sha256(fit_path.read_bytes()).hexdigest(),
                "original_run_summary_sha256":hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                "original_fit_accounting":accounting}


def select_signals(candidates: Any) -> dict[str, dict[int, list[int]]]:
    masks = {"clean": candidates.clean_union,
             "clean_b": candidates.clean_union & candidates.b_any,
             "clean_b_f5_s1": candidates.clean_union & candidates.b_any & candidates.f5_s1_pass}
    result = {}
    for name, mask in masks.items():
        rows = candidates.loc[mask & candidates.trade_date.between(START,END)]
        result[name] = {int(day):group.code_index.astype(int).tolist()
                        for day,group in rows.groupby("session",sort=True)}
    rows = candidates.loc[masks["clean_b_f5_s1"] & candidates.p_hgb.notna()
                           & candidates.trade_date.between(START,END)].sort_values(
                               ["trade_date","p_hgb","ts_code"],ascending=[True,False,True],kind="mergesort")
    result[STRATEGIES[-1]] = {int(day):group.head(20).code_index.astype(int).tolist()
                             for day,group in rows.groupby("session",sort=True)}
    return result


def board_band(code: str) -> float | None:
    if code.endswith(".BJ"):
        return .30
    if code.endswith(".SZ") and code.startswith(("300","301")):
        return .20
    if code.endswith(".SH") and code.startswith(("688","689")):
        return .20
    if code.endswith((".SH",".SZ")) and code[:6].isdigit():
        return .05  # Unknown historical ST: smallest plausible main-board cap.
    return None


def entry_status(book: PriceBook, day: int, code: int) -> tuple[bool,str]:
    """Conservative opening proxy. Never consult T1 high/low/close for entry."""
    import math
    values = book.values
    opening = values["open"][day,code]
    if not math.isfinite(opening) or opening<=0:
        return False,"missing_open"
    tradeable = values.get("tradeable_basic")
    if tradeable is not None and (not math.isfinite(tradeable[day,code]) or tradeable[day,code]!=1):
        return False,"suspended_or_unknown_tradeable"
    volume = values["vol"][day,code]
    if not math.isfinite(volume) or volume<=0:
        return False,"suspended_or_missing_volume"
    cap = values.get("limit_up_price")
    if cap is not None and math.isfinite(cap[day,code]) and cap[day,code]>0:
        return (False,"native_upper_cap_block") if opening>=cap[day,code] else (True,"native_cap_proxy_fill")
    reference = values.get("pre_close")
    ref = reference[day,code] if reference is not None else float("nan")
    band = board_band(book.codes[code])
    if not math.isfinite(ref) or ref<=0 or band is None:
        return False,"unknown_reference_or_board"
    gap = opening/ref-1
    buffer = .003 + min(.01,.005/ref)
    if gap >= band-buffer:
        reason = "main_5_to_10_unknown_strict_exclusion" if band==.05 and gap<.10 else "predicted_upper_cap_block"
        return False,reason
    return True,"conservative_estimated_proxy_fill"


def exit_status(book: PriceBook, day: int, code: int) -> tuple[bool,str]:
    import math
    import numpy as np
    if not book.valid[day,code]:
        return False,"missing_or_suspended_exit"
    tradeable = book.values.get("tradeable_basic")
    if tradeable is not None and (not math.isfinite(tradeable[day,code]) or tradeable[day,code]!=1):
        return False,"unknown_or_untradeable_exit"
    p = book.values["close"][day,code]
    one_price = np.isclose(book.values["high"][day,code],book.values["low"][day,code],rtol=0,atol=1e-10)
    cap = book.values.get("limit_down_price")
    if cap is not None and math.isfinite(cap[day,code]) and cap[day,code]>0:
        return (False,"native_one_price_down_exit") if one_price and p<=cap[day,code] else (True,"native_exit")
    legacy = book.values.get("limit_down_approx")
    ref_values = book.values.get("pre_close")
    ref = ref_values[day,code] if ref_values is not None else float("nan")
    band = board_band(book.codes[code])
    known = math.isfinite(ref) and ref>0 and band is not None
    near_down = known and p/ref-1<=-band+.003+min(.01,.005/ref)
    flagged = legacy is not None and math.isfinite(legacy[day,code]) and legacy[day,code]==1
    if one_price and (flagged or near_down):
        return False,"estimated_one_price_down_exit"
    if one_price and not known:
        return False,"unknown_one_price_exit"
    return True,"estimated_close_exit"


def simulate(book: PriceBook, signals: dict[int,list[int]], horizon: int, mode: str,
             start: str=START, end: str=END) -> tuple[Any,dict[str,Any]]:
    """H disjoint cash sleeves, shares held to target (or delayed) close.

    Each sleeve owns only its cash and securities. New cohorts use that sleeve's
    available cash; residual delayed positions cannot finance new purchases.
    Rejected entries retain their original equal-weight cash allocation.
    """
    import numpy as np
    import pandas as pd
    if horizon not in (3,5) or mode not in ("ideal","constrained"):
        raise ExecutionError("INVALID_SIMULATION_POLICY")
    active_days = [i for i,d in enumerate(book.dates) if start<=d<=end]
    if not active_days:
        raise ExecutionError("EMPTY_EVALUATION_WINDOW")
    first,last = active_days[0],active_days[-1]
    cash = np.full(horizon,1./horizon)
    # Positions are (sleeve, code, shares, target, last_mark, first_delay).
    holdings:list[dict[str,Any]]=[]
    statistics = {"attempts":0,"fills":0,"blocked":{},
                  "immature_signal_count":sum(len(set(codes)) for day,codes in signals.items()
                      if first<=day<=last and day+horizon>last),
                  "delayed_positions":0,"delayed_exit_sessions":0,"stale_mark_sessions":0,
                  "max_daily_holding":0,"max_position_lots":0,"buy_fees":0.,"sell_fees":0.,
                  "native_cap_entry_attempts":0,"proxy_entry_attempts":0}
    rows=[]
    fee = .0015 if mode=="constrained" else 0.
    def enter(signal_day:int, execution_day:int) -> None:
        codes = list(dict.fromkeys(signals.get(signal_day,[])))
        if not codes:
            return
        if signal_day+horizon>last:
            return
        sleeve = (signal_day-first)%horizon
        budget = cash[sleeve]/len(codes)
        for code in codes:
            statistics["attempts"]+=1
            if mode=="constrained":
                allowed,reason = entry_status(book,execution_day,code)
                cap = book.values.get("limit_up_price")
                native = cap is not None and np.isfinite(cap[execution_day,code]) and cap[execution_day,code]>0
                statistics["native_cap_entry_attempts" if native else "proxy_entry_attempts"]+=1
                price = book.values["open"][execution_day,code]
            else:
                price = book.values["close"][execution_day,code]
                allowed,reason = bool(book.valid[execution_day,code]),"invalid_signal_close"
            if not allowed or not np.isfinite(price) or price<=0:
                statistics["blocked"][reason]=statistics["blocked"].get(reason,0)+1
                continue
            if budget<=0:
                statistics["blocked"]["no_sleeve_cash"]=statistics["blocked"].get("no_sleeve_cash",0)+1
                continue
            notional = budget/(1+fee)
            cash[sleeve]-=budget
            statistics["buy_fees"]+=budget-notional
            statistics["fills"]+=1
            holdings.append(dict(sleeve=sleeve,code=code,shares=notional/price,
                                 target=signal_day+horizon,mark=price,delayed=False))
    for day in active_days:
        attempts_before,fills_before=statistics["attempts"],statistics["fills"]
        if mode=="constrained" and day>first:
            enter(day-1,day)
        retained=[]
        for position in holdings:
            code=position["code"]
            price=book.values["close"][day,code]
            if book.valid[day,code] and np.isfinite(price) and price>0:
                position["mark"]=float(price)
            else:
                statistics["stale_mark_sessions"]+=1
            if day>=position["target"]:
                can_exit,_ = exit_status(book,day,code) if mode=="constrained" else (bool(book.valid[day,code]),"")
                if can_exit:
                    proceeds=position["shares"]*position["mark"]
                    cash[position["sleeve"]]+=proceeds*(1-fee)
                    statistics["sell_fees"]+=proceeds*fee
                    continue
                if not position["delayed"]:
                    statistics["delayed_positions"]+=1
                    position["delayed"]=True
                statistics["delayed_exit_sessions"]+=1
            retained.append(position)
        holdings=retained
        if mode=="ideal":
            enter(day,day)
        invested=sum(x["shares"]*x["mark"] for x in holdings)
        nav=float(cash.sum()+invested)
        if not np.isfinite(nav) or nav<=0 or cash.min() < -1e-10:
            raise ExecutionError("SELF_FINANCING_NAV_OR_CASH_INVALID")
        unique_holding_count=len({x["code"] for x in holdings})
        statistics["max_daily_holding"]=max(statistics["max_daily_holding"],unique_holding_count)
        statistics["max_position_lots"]=max(statistics["max_position_lots"],len(holdings))
        rows.append({"trade_date":book.dates[day],"nav":nav,"cash":float(cash.sum()),
                     "invested":invested,"holding_count":unique_holding_count,"position_lots":len(holdings),
                     "attempts":statistics["attempts"]-attempts_before,
                     "fills":statistics["fills"]-fills_before,
                     "gross_exposure":invested/nav})
    statistics.update(residual_positions=len(holdings),residual_market_value=sum(x["shares"]*x["mark"] for x in holdings),
                      horizon=horizon,mode=mode,
                      execution_evidence="IDEAL_COUNTERFACTUAL" if mode=="ideal" else "CONSERVATIVE_ESTIMATED_PROXY_NOT_REAL_FILL",
                      exact_exchange_price_coverage="CANNOT_CONFIRM")
    return pd.DataFrame(rows),statistics


def metric_values(returns: Any, benchmark_returns: Any) -> dict[str,Any]:
    import numpy as np
    import pandas as pd
    r=np.asarray(returns,dtype=float)
    b=np.asarray(benchmark_returns,dtype=float)
    known=np.isfinite(r)&np.isfinite(b)
    r,b=r[known],b[known]
    if not len(r):
        return {"sessions":0,"status":"CANNOT_CONFIRM_NO_MATCHED_RETURNS"}
    nav=np.cumprod(1+r)
    bench=np.cumprod(1+b)
    relative=nav/bench
    peak=np.maximum.accumulate(np.r_[1.,nav])
    mdd=float(np.min(np.r_[1.,nav]/peak-1))
    risk=float(np.std(r,ddof=1)) if len(r)>1 else 0.
    active=r-b
    active_risk=float(np.std(active,ddof=1)) if len(r)>1 else 0.
    return {"sessions":len(r),"absolute_return":float(nav[-1]-1),
            "absolute_cagr_252":float(nav[-1]**(252/len(r))-1),
            "benchmark_return":float(bench[-1]-1),
            "benchmark_cagr_252":float(bench[-1]**(252/len(r))-1),
            "excess_return_relative_nav":float(relative[-1]-1),
            "excess_cagr_relative_nav_252":float(relative[-1]**(252/len(r))-1),
            "mdd":mdd,"annualized_volatility":risk*252**.5,
            "sharpe_zero_interest":float(np.mean(r)/risk*252**.5) if risk>0 else None,
            "active_risk_annualized":active_risk*252**.5,
            "information_ratio":float(np.mean(active)/active_risk*252**.5) if active_risk>0 else None,
            "status":"CALCULATED"}


def aggregate_metrics(daily: Any) -> Any:
    import numpy as np
    import pandas as pd
    rows=[]
    for (strategy,horizon,mode),group in daily.groupby(["strategy","horizon","mode"],sort=True):
        group=group.sort_values("trade_date").copy()
        group["quarter"]=group.trade_date.map(quarter)
        segments=[("full","ALL",group)]
        segments.extend(("quarter",str(key),part) for key,part in group.groupby("quarter",sort=True))
        segments.extend(("regime",str(key),part) for key,part in group.groupby("regime",sort=True))
        for kind,key,part in segments:
            values=metric_values(part.daily_return,part.benchmark_daily_return)
            monthly=part.assign(month=part.trade_date.str[:6]).groupby("month").daily_return.apply(lambda x: np.prod(1+x)-1)
            rows.append({"strategy":strategy,"horizon":int(horizon),"mode":mode,
                         "segment_kind":kind,"segment":key,"first_date":part.trade_date.min(),
                         "last_date":part.trade_date.max(),"monthly_observed_groups":len(monthly),
                         "monthly_win_rate":float(monthly.gt(0).mean()),
                         "max_daily_holding":int(part.holding_count.max()),
                         "attempts":int(part.attempts.sum()),"fills":int(part.fills.sum()),
                         "fill_rate":float(part.fills.sum()/part.attempts.sum()) if part.attempts.sum()>0 else None,
                         "regime_sampling":"noncontiguous same-regime returns compounded" if kind=="regime" else "contiguous",
                         **values})
    return pd.DataFrame(rows)


def _write_json(path: Path,value: Any) -> None:
    payload=a9._json_safe(value)
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    temporary.replace(path)


def run_once(data_root: Path,output_dir: Path,replay_model_dir:Path|None=None) -> dict[str,Any]:
    """Root-authorized runner. This function is never invoked during unit tests."""
    import numpy as np
    import pandas as pd
    import os
    import resource
    output_dir=Path(output_dir).resolve()
    if output_dir==Path(data_root).resolve() or Path(data_root).resolve() in output_dir.parents:
        raise ExecutionError("OUTPUT_INSIDE_AUTHORITY_DATA_ROOT")
    if replay_model_dir is not None:
        original_dir=Path(replay_model_dir).resolve()
        if output_dir==original_dir or original_dir in output_dir.parents or output_dir in original_dir.parents:
            raise ExecutionError("REPLAY_OUTPUT_MUST_PRESERVE_ORIGINAL_DIRECTORY")
    output_dir.mkdir(parents=True,exist_ok=True)
    if (output_dir/"run_summary.json").exists():
        raise ExecutionError("EXISTING_RUN_SUMMARY_REFUSE_RECOMPUTE")
    progress_path=output_dir/"run_progress.jsonl"
    def progress(stage:str,status:str,details:dict[str,Any]) -> None:
        a9._append_progress(progress_path,stage,status,details)
    summary={"schema":SCHEMA,"signed_doc":SIGNED_DOC,"status":"RUNNING",**FLAGS,
             "evaluation_window":[START,END],"training_earliest":TRAIN_START,
             "model_features":list(MODEL_FEATURES),"fit_plan":{"S":0,"HGB_per_quarter":0 if replay_model_dir else 1,"search":0},
             "run_mode":"REPLAY_SAVED_MODELS_NO_FIT" if replay_model_dir else "ORIGINAL_FIT",
             "resource":{"logical_cpus":os.cpu_count(),"python":sys.executable,
                         "formula_workers":1,"formula_cohort_symbols":256,"input_policy":"one projected RAM read; bounded cohort formula temporaries; no row export"},
             "execution_scenario":"CONSERVATIVE_ESTIMATED_PROXY_NOT_REAL_FILL",
             "exact_exchange_limit_price_coverage":"CANNOT_CONFIRM",
             "benchmark":"all-A daily equal-weight close-to-close fully invested, no costs; broad-market active risk benchmark",
             "execution_clock_benchmark":"all modes use same external broad-market benchmark on same evaluation dates; not exposure-matched or constrained-execution-matched",
             "no_entry_replacement":True,"costs":{"ideal_buy":0.,"ideal_sell":0.,"proxy_buy":.0015,"proxy_sell":.0015},
             "regime":"prior 60 all-A daily equal-weight sessions compounded, shift1; >=5% bull, <=-5% bear",
             "f5":"raw V12 union weak endpoint rank count(window <= D)/40; >.70 cash; unknown cash"}
    _write_json(output_dir/"run_summary.json",summary)
    progress("run","STARTED",{"signed_doc":SIGNED_DOC})
    try:
        with v12.bind_current_panels(Path(data_root)) as (panel_path,source,recheck):
            binding=a9._assert_bound_source(source)
            summary["binding"]=binding
            summary["source"]=source
            progress("binding","PASS",binding)
            raw,read_meta=read_projected(panel_path)
            summary["read"]=read_meta
            progress("read","PASS",read_meta)
            book=PriceBook.from_frame(raw)
            study_dates=[d for d in book.dates if START<=d<=END]
            if not study_dates or study_dates[-1]!=END or study_dates[0]>"20241104":
                raise ExecutionError("EVALUATION_DATE_COVERAGE_GAP")
            summary["evaluation_sessions"]=len(study_dates)
            summary["symbols"]=len(book.codes)
            candidates,meta=build_candidates(raw,book,read_meta["formula_prep_start"],progress)
            del raw
            summary["clean_candidate_rows"]=len(candidates)
            summary["f5_d19_raw_count"]=int(meta["raw_union_counts"].get("20261119",-1))
            summary["f5_d19_percentile"]=float(f5_s1(meta["raw_union_counts"]).get("20261119",np.nan))
            if summary["f5_d19_raw_count"]!=159 or not np.isclose(summary["f5_d19_percentile"],.075):
                raise ExecutionError("ACCEPTED_D19_F5_PARITY_FAILED")
            recheck()
            progress("formula","PASS",{"clean_rows":len(candidates),"D19":summary["f5_d19_raw_count"],"F5_rank":summary["f5_d19_percentile"]})
            if replay_model_dir is not None:
                candidates,summary["fit_accounting"]=replay_quarters(candidates,replay_model_dir,binding,progress)
            else:
                candidates,fit_reports=fit_quarters(candidates,output_dir,progress=progress)
                summary["fit_accounting"]={"S":0,"HGB":sum(x["fits"] for x in fit_reports),"search":0,
                                           "expected_evaluation_quarters":9,"quarters":fit_reports}
            _write_json(output_dir/"fit_accounting.json",summary["fit_accounting"])
            selections=select_signals(candidates)
            del candidates
            frames=[]
            accounting=[]
            for horizon in (3,5):
                for mode in ("ideal","constrained"):
                    for strategy in STRATEGIES:
                        progress("portfolio","STARTED",{"strategy":strategy,"horizon":horizon,"mode":mode})
                        daily,stats=simulate(book,selections[strategy],horizon,mode)
                        daily["strategy"],daily["horizon"],daily["mode"]=strategy,horizon,mode
                        daily["daily_return"]=daily.nav.pct_change().fillna(daily.nav.iloc[0]-1)
                        benchmark=daily.trade_date.map(meta["all_a_d_returns"]).astype(float)
                        benchmark.iloc[0]=0.
                        daily["benchmark_daily_return"]=benchmark
                        daily["benchmark_nav"]=(1+benchmark).cumprod()
                        daily["relative_nav"]=daily.nav/daily.benchmark_nav
                        daily["regime"]=daily.trade_date.map(meta["regimes"])
                        accounting.append({"strategy":strategy,**stats})
                        frames.append(daily)
            result=pd.concat(frames,ignore_index=True)
            metrics=aggregate_metrics(result)
            result.to_csv(output_dir/"daily_portfolio_nav.csv",index=False)
            metrics.to_csv(output_dir/"quarter_regime_metrics.csv",index=False)
            _write_json(output_dir/"execution_accounting.json",accounting)
            recheck()
            summary.update(status="COMPLETED_ESTIMATED_EXECUTION_RESEARCH",peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                           artifacts=["daily_portfolio_nav.csv","quarter_regime_metrics.csv","execution_accounting.json","fit_accounting.json"],
                           row_export_files=0,full_panel_written=False,
                           portfolio_rows=len(result),metric_rows=len(metrics))
            _write_json(output_dir/"run_summary.json",summary)
            progress("run","COMPLETED",{"status":summary["status"],"fit_counts":summary["fit_accounting"]["HGB"]})
            return summary
    except Exception as exc:
        summary.update(status="FAILED",error=f"{type(exc).__name__}:{exc}")
        _write_json(output_dir/"run_summary.json",summary)
        progress("run","FAILED",{"error":summary["error"]})
        raise


def main(argv:list[str]|None=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--replay-model-dir",type=Path,help="Reuse exact original nine quarter weights; no fits; separate output required")
    args=parser.parse_args(argv)
    run_once(args.data_root,args.output_dir,args.replay_model_dir)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
